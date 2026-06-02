from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, F, Q, DecimalField, ExpressionWrapper
from django.core.paginator import Paginator
from django.utils import timezone
from django.conf import settings as django_settings
from decimal import Decimal
from datetime import date, time, timedelta
import math
import csv
import io
try:
    import PIL.Image as _PILImage
except ImportError:
    _PILImage = None

from core.models import (
    User, Branch, DeviceTag, ServiceTarget, ServiceActivity,
    BranchSafeStock, StockMovement, Product, StaffStock,
    RetailSale, RetailCategory, RetailSubCategory, RetailSubSubCategory,
    MultiChoiceSale, MultiChoiceWeeklyReport, MultiChoiceBalance,
    Expense, StockRequest, Attendance, DirectorSafeStock,
    CheckInOutLog, SimInventory, SimInventoryLog,
    Customer, StockAlert, DeviceTagCommission, CommissionPayment,
    Invoice, WholesaleDeviceSale,
    MoniepointTransaction, LoyaltyPoint, LoyaltyTransaction
)
from core.models import log_action
from core.utils.decorators import role_required

def close_weekly_report(request):
    if request.method == "POST" and request.user.role == "MULTICHOICE":
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
        report = MultiChoiceWeeklyReport.objects.filter(staff=request.user, week_start_date=week_start).first()
        if report and not report.is_closed:
            report.closing_balance = request.POST.get("closing_balance")
            week_total = MultiChoiceSale.objects.filter(
                staff=request.user, date__range=[week_start, today]
            ).aggregate(total=Sum("amount"))["total"] or 0
            report.total_subscriptions = week_total
            report.calculate_commission()
            report.is_closed = True
            report.save()
            messages.success(request, f"Week closed. Commission: ₦{report.commission:,.2f}")
    return redirect("multichoice_dashboard")
@role_required("MULTICHOICE")
def record_balance(request):
    if request.method == "POST":
        weekly_report = MultiChoiceWeeklyReport.objects.filter(
            staff=request.user, branch=request.user.branch, is_closed=False
        ).order_by("-id").first()
        balance = request.POST.get("current_balance")
        if weekly_report and balance:
            latest = MultiChoiceBalance.objects.filter(
                weekly_report=weekly_report
            ).order_by("-date", "-time", "-id").first()
            before = latest.balance_after_sale if latest and latest.balance_after_sale is not None else weekly_report.opening_balance + weekly_report.additional_funds
            after = Decimal(balance)
            MultiChoiceBalance.objects.create(
                weekly_report=weekly_report,
                balance_amount=before,
                balance_after_sale=after,
                sale_cost_price=Decimal("0"),
                notes=request.POST.get("notes", ""),
            )
            weekly_report.closing_balance = after
            weekly_report.save(update_fields=["closing_balance"])
            messages.success(request, f"Balance ₦{balance} recorded.")
        else:
            messages.error(request, "No active weekly report or invalid balance.")
    return redirect("multichoice_dashboard")


@login_required
def record_daily_balance(request):
    if request.method == "POST" and request.user.role == "MULTICHOICE":
        balance = Decimal(request.POST.get("balance", 0))
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
        weekly_report = (
            MultiChoiceWeeklyReport.objects.filter(
                staff=request.user,
                branch=request.user.branch,
                week_start_date=week_start,
            )
            .order_by("-id")
            .first()
        )
        if weekly_report is None:
            weekly_report = MultiChoiceWeeklyReport.objects.create(
                staff=request.user,
                branch=request.user.branch,
                week_start_date=week_start,
                opening_balance=Decimal("0"),
                additional_funds=Decimal("0"),
            )
        balance_record = MultiChoiceBalance.objects.create(
            weekly_report=weekly_report, balance_amount=balance,
            balance_after_sale=balance,
            sale_cost_price=Decimal("0"),
            notes=request.POST.get("notes", ""),
        )
        prev = MultiChoiceBalance.objects.filter(
            weekly_report=weekly_report
        ).order_by("-date", "-time", "-id").first()
        if prev and balance > prev.balance_amount:
            commission_amt = balance - prev.balance_amount
            balance_record.is_commission_payment = True
            balance_record.save()
            CommissionPayment.objects.create(
                staff=request.user, branch=request.user.branch,
                balance_record=balance_record,
                previous_balance=prev.balance_amount,
                current_balance=balance,
                commission_detected=commission_amt,
                date_paid=today,
            )
            messages.success(request, f"Commission detected: ₦{commission_amt:,.2f}")
        else:
            messages.success(request, f"Balance ₦{balance:,.2f} recorded.")
        weekly_report.closing_balance = balance
        weekly_report.save(update_fields=["closing_balance"])
    return redirect("multichoice_dashboard")


@login_required
def my_commissions(request):
    if request.user.role != "MULTICHOICE":
        return HttpResponseForbidden()
    commissions = CommissionPayment.objects.filter(staff=request.user).order_by("-date_detected")
    total_earned = commissions.aggregate(total=Sum("commission_detected"))["total"] or 0
    return render(request, "my_commissions.html", {"commissions": commissions, "total_earned": total_earned})


# ─────────────────────────────────────────
# STOCK MANAGEMENT
# ─────────────────────────────────────────

@role_required("MANAGER")
def start_weekly_report(request):
    if request.method == "POST" and request.user.role == "MULTICHOICE":
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
        # Safely parse decimal values — default to 0 if empty
        try:
            opening_balance = Decimal(request.POST.get("opening_balance") or "0")
        except Exception:
            opening_balance = Decimal("0")
        try:
            additional_funds = Decimal(request.POST.get("additional_funds") or "0")
        except Exception:
            additional_funds = Decimal("0")

        obj, created = MultiChoiceWeeklyReport.objects.get_or_create(
            staff=request.user,
            branch=request.user.branch,
            week_start_date=week_start,
            defaults={
                "opening_balance": opening_balance,
                "additional_funds": additional_funds,
            }
        )
        if created:
            messages.success(request, f"Weekly report started. Opening balance: ₦{opening_balance:,.2f}")
        else:
            messages.info(request, "A weekly report already exists for this week.")
    return redirect("multichoice_dashboard")


# ─────────────────────────────────────────
# VOID / CANCEL A RETAIL SALE (Manager)
# ─────────────────────────────────────────

@role_required("MANAGER")
def multichoice_dashboard(request):
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    weekly_report = MultiChoiceWeeklyReport.objects.filter(
        staff=request.user, week_start_date=week_start
    ).first()

    today_sales = MultiChoiceSale.objects.filter(
        staff=request.user, date=today
    ).order_by("-time")

    search_query   = request.GET.get("search", "").strip()
    date_from      = request.GET.get("date_from", "")
    date_to        = request.GET.get("date_to", "")
    selected_month = request.GET.get("month", today.strftime("%Y-%m"))

    all_sales = MultiChoiceSale.objects.filter(staff=request.user).order_by("-date", "-time")
    if date_from:
        all_sales = all_sales.filter(date__gte=date_from)
    if date_to:
        all_sales = all_sales.filter(date__lte=date_to)
    if not date_from and not date_to and selected_month:
        yr, mo = selected_month.split("-")
        all_sales = all_sales.filter(date__year=yr, date__month=mo)
    if search_query:
        from django.db.models import Q
        all_sales = all_sales.filter(
            Q(customer_name__icontains=search_query) |
            Q(customer_phone__icontains=search_query) |
            Q(package_type__icontains=search_query)
        )

    paginator = Paginator(all_sales, 30)
    all_sales_page = paginator.get_page(request.GET.get("page"))

    # Current running balance
    current_balance = None
    balance_history = None
    if weekly_report:
        last_balance = MultiChoiceBalance.objects.filter(
            weekly_report=weekly_report
        ).order_by("-date", "-time").first()
        if last_balance and last_balance.balance_after_sale is not None:
            current_balance = last_balance.balance_after_sale
        else:
            current_balance = weekly_report.opening_balance + weekly_report.additional_funds
        balance_history = MultiChoiceBalance.objects.filter(
            weekly_report=weekly_report
        ).order_by("-date", "-time")

    weekly_total_sales = weekly_report.total_subscriptions if weekly_report and weekly_report.is_closed else (
        weekly_report.total_subscriptions if weekly_report else 0
    )

    return render(request, "multichoice_dashboard.html", {
        "today_sales": today_sales,
        "all_sales": all_sales_page,
        "total_today": today_sales.aggregate(total=Sum("amount"))["total"] or 0,
        "weekly_report": weekly_report,
        "is_monday": today.weekday() == 0,
        "is_saturday": today.weekday() == 5,
        "weekly_total_sales": weekly_total_sales,
        "balance_history": balance_history,
        "current_balance": current_balance,
        "search_query": search_query,
        "selected_month": selected_month,
        "date_from": date_from,
        "date_to": date_to,
        "check_logs": CheckInOutLog.objects.filter(staff=request.user).order_by("-date", "-check_in_time")[:20],
    })


# ─────────────────────────────────────────
# DEVICE COMMISSION — with history
# ─────────────────────────────────────────

@role_required("MANAGER")
def multichoice_export_pdf(request):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER

    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")
    sales = MultiChoiceSale.objects.filter(staff=request.user).order_by("-date", "-time")
    if date_from:
        sales = sales.filter(date__gte=date_from)
    if date_to:
        sales = sales.filter(date__lte=date_to)

    buffer = io.BytesIO()
    BLUE = colors.HexColor("#004F9F")
    doc = SimpleDocTemplate(buffer, rightMargin=0.5*inch, leftMargin=0.5*inch,
                            topMargin=0.7*inch, bottomMargin=0.7*inch)
    styles = getSampleStyleSheet()

    label = f"{request.user.username} — MultiChoice Sales"
    if date_from or date_to:
        label += f"  |  {date_from or 'Start'} → {date_to or 'Today'}"

    elements = [
        Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED", ParagraphStyle("T", parent=styles["Heading1"], fontSize=14, textColor=BLUE, alignment=TA_CENTER)),
        Paragraph(label, ParagraphStyle("S", parent=styles["Normal"], fontSize=9, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=12)),
    ]

    total_amount = sales.aggregate(t=Sum("amount"))["t"] or 0
    total_cost   = sales.aggregate(t=Sum("cost_price"))["t"] or 0

    data = [["Date", "Customer", "Phone", "Service", "Package", "Type", "Amount", "Cost"]]
    for s in sales:
        data.append([
            s.date.strftime("%d %b %Y"),
            s.customer_name[:20],
            s.customer_phone or "—",
            s.service_type,
            s.package_type[:18],
            s.transaction_type,
            f"N{s.amount:,.0f}",
            f"N{s.cost_price:,.0f}",
        ])
    data.append(["", "", "", "", "", "TOTAL", f"N{total_amount:,.0f}", f"N{total_cost:,.0f}"])

    t = Table(data, colWidths=[0.85*inch, 1.3*inch, 0.9*inch, 0.65*inch, 1.2*inch, 0.7*inch, 0.8*inch, 0.8*inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), BLUE),
        ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("BACKGROUND",    (0,-1), (-1,-1), colors.HexColor("#F3F4F6")),
        ("FONTNAME",      (0,-1), (-1,-1), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 7.5),
        ("GRID",          (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS",(0,1), (-1,-2), [colors.white, colors.HexColor("#F9FAFB")]),
        ("ALIGN",         (5,0), (-1,-1), "CENTER"),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    elements.append(t)

    doc.build(elements)
    buffer.seek(0)
    fname = f"MultiChoice_{request.user.username}_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ", "_")
    return HttpResponse(buffer, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})

# ─────────────────────────────────────────
# PASSWORD RESET FIX
# ─────────────────────────────────────────

from django.contrib.auth.views import PasswordResetConfirmView as DjPRCV

def record_multichoice_sale(request):
    if request.method == "POST":
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())

        weekly_report = (
            MultiChoiceWeeklyReport.objects.filter(
                staff=request.user,
                branch=request.user.branch,
                week_start_date=week_start,
            )
            .order_by("-id")
            .first()
        )
        if weekly_report is None:
            weekly_report = MultiChoiceWeeklyReport.objects.create(
                staff=request.user,
                branch=request.user.branch,
                week_start_date=week_start,
                opening_balance=Decimal("0"),
                additional_funds=Decimal("0"),
            )

        cost_price     = Decimal(request.POST.get("cost_price") or "0")
        amount         = Decimal(request.POST.get("amount") or "0")
        customer_name  = request.POST.get("customer_name", "")
        customer_phone = request.POST.get("customer_phone", "")
        iuc_number     = request.POST.get("iuc_number", "")
        service_type   = request.POST.get("service_type", "DSTV")
        package_type   = request.POST.get("package_type", "")
        transaction_type = request.POST.get("transaction_type", "NEW")

        prev = MultiChoiceBalance.objects.filter(
            weekly_report=weekly_report
        ).order_by("-date", "-time").first()

        current_balance = (
            prev.balance_after_sale
            if prev and prev.balance_after_sale is not None
            else weekly_report.opening_balance + weekly_report.additional_funds
        )
        balance_after = current_balance - cost_price

        with transaction.atomic():
            MultiChoiceSale.objects.create(
                staff=request.user,
                branch=request.user.branch,
                customer_name=customer_name,
                customer_phone=customer_phone,
                iuc_number=iuc_number,
                service_type=service_type,
                package_type=package_type,
                transaction_type=transaction_type,
                cost_price=cost_price,
                amount=amount,
            )
            MultiChoiceBalance.objects.create(
                weekly_report=weekly_report,
                balance_amount=current_balance,
                balance_after_sale=balance_after,
                sale_cost_price=cost_price,
                notes=f"{service_type} — {package_type} — {customer_name}",
            )
            weekly_report.closing_balance = balance_after
            weekly_report.total_subscriptions = (
                weekly_report.total_subscriptions or Decimal("0")
            ) + amount
            weekly_report.save(update_fields=["closing_balance", "total_subscriptions"])

            # Update Customer CRM
            if customer_phone:
                _upsert_customer(
                    phone=customer_phone,
                    name=customer_name,
                    branch=request.user.branch,
                    amount=amount,
                    source="MULTICHOICE",
                )

        messages.success(
            request,
            f"Sale recorded. Balance: ₦{current_balance:,.2f} → ₦{balance_after:,.2f}"
        )
    return redirect("multichoice_dashboard")


# ─────────────────────────────────────────
# FIXED staff_dashboard (TELECOM) — updates Customer CRM on activity
# ─────────────────────────────────────────

@role_required("TELECOM")
def director_multichoice_balance(request):
    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")
    branch_flt = request.GET.get("branch", "")

    # Get all active weekly reports
    reports = MultiChoiceWeeklyReport.objects.select_related(
        "staff", "branch"
    ).order_by("-week_start_date")

    if branch_flt:
        reports = reports.filter(branch_id=branch_flt)
    if date_from:
        reports = reports.filter(week_start_date__gte=date_from)
    if date_to:
        reports = reports.filter(week_start_date__lte=date_to)

    # For each report, get current running balance
    report_data = []
    for r in reports:
        last_balance = MultiChoiceBalance.objects.filter(
            weekly_report=r
        ).order_by("-date", "-time").first()

        if last_balance and last_balance.balance_after_sale is not None:
            current_balance = last_balance.balance_after_sale
        else:
            current_balance = r.opening_balance + r.additional_funds

        report_data.append({
            "report": r,
            "staff": r.staff.username,
            "branch": r.branch.name,
            "week_start": r.week_start_date,
            "opening_balance": r.opening_balance,
            "additional_funds": r.additional_funds,
            "total_subscriptions": r.total_subscriptions or 0,
            "current_balance": current_balance,
            "commission": r.commission or 0,
            "is_closed": r.is_closed,
        })

    # Summary stats - active balance is current week only
    from datetime import date as _date
    today = _date.today()
    month_start = today.replace(day=1)

    # Total active balance = sum of current running balances of all OPEN weeks only
    from datetime import date as _dt
    this_week_start = _dt.today()
    this_week_start = this_week_start - __import__('datetime').timedelta(days=this_week_start.weekday())
    total_balance = sum(
        d["current_balance"] for d in report_data
        if not d["is_closed"] and d["week_start"] >= this_week_start
    )
    total_commission = sum(d["commission"] for d in report_data if d["is_closed"])

    # Total subscriptions only from 1st of current month to today
    from django.db.models import Sum as _Sum
    total_subscriptions = MultiChoiceSale.objects.filter(
        date__gte=month_start,
        date__lte=today,
    ).aggregate(t=_Sum("amount"))["t"] or 0

    if branch_flt:
        total_subscriptions = MultiChoiceSale.objects.filter(
            date__gte=month_start,
            date__lte=today,
            branch_id=branch_flt,
        ).aggregate(t=_Sum("amount"))["t"] or 0

    return render(request, "director/multichoice_balance.html", {
        "report_data": report_data,
        "total_balance": total_balance,
        "total_commission": total_commission,
        "total_subscriptions": total_subscriptions,
        "branches": Branch.objects.all(),
        "date_from": date_from,
        "date_to": date_to,
        "branch_flt": branch_flt,
    })


# ─────────────────────────────────────────
# INVOICE GENERATION
# ─────────────────────────────────────────

from django.core.mail import EmailMessage


@login_required