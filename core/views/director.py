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

def delete_director_stock(request, stock_id):
    stock = get_object_or_404(DirectorSafeStock, id=stock_id)
    stock.delete()
    messages.success(request, "Deleted from director safe.")
    return redirect("director_safe_stock")


@role_required("DIRECTOR")
def edit_director_stock(request, stock_id):
    stock = get_object_or_404(DirectorSafeStock, id=stock_id)
    new_qty = request.GET.get("quantity")
    if new_qty:
        stock.quantity = int(new_qty)
        stock.save()
        messages.success(request, "Quantity updated.")
    return redirect("director_safe_stock")


@role_required("DIRECTOR")
def create_director_product(request):
    if request.method == "POST":
        try:
            cat_id = request.POST.get("category_id")
            if cat_id == "new":
                category, _ = RetailCategory.objects.get_or_create(name=request.POST.get("new_category_name"))
            else:
                category = get_object_or_404(RetailCategory, id=cat_id)
            subcategory, _ = RetailSubCategory.objects.get_or_create(
                category=category, name=request.POST.get("subcategory_name")
            )
            subsubcategory = None
            ssname = request.POST.get("subsubcategory_name")
            if ssname:
                subsubcategory, _ = RetailSubSubCategory.objects.get_or_create(subcategory=subcategory, name=ssname)
            product = Product.objects.create(
                subcategory=subcategory, subsubcategory=subsubcategory,
                product_name=request.POST.get("product_name"),
                model_name=request.POST.get("model_name"),
                description=request.POST.get("description"),
                imei_serial=request.POST.get("imei_serial") or None,
                cost_price=request.POST.get("cost_price"),
                selling_price=request.POST.get("selling_price"),
            )
            qty = int(request.POST.get("quantity", 0))
            DirectorSafeStock.objects.create(product=product, quantity=qty, notes="Created by Director")
            messages.success(request, f"Product created. {qty} units added to safe.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("director_safe_stock")


# ─────────────────────────────────────────
# ATTENDANCE
# ─────────────────────────────────────────

@login_required
def manage_branch_locations(request):
    if request.method == "POST":
        try:
            branch = get_object_or_404(Branch, id=request.POST.get("branch_id"))
            branch.latitude = float(request.POST.get("latitude"))
            branch.longitude = float(request.POST.get("longitude"))
            branch.allowed_radius = int(request.POST.get("allowed_radius", 100))
            branch.street_address = request.POST.get("street_address", "")
            branch.city = request.POST.get("city", "")
            branch.state = request.POST.get("state", "")
            branch.location_locked = True
            branch.save()
            messages.success(request, f"Location saved for {branch.name}.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
        return redirect("manage_branch_locations")
    return render(request, "director/manage_locations.html", {"branches": Branch.objects.all()})


# ─────────────────────────────────────────
# TELECOM – PHYSICAL PRODUCTS / SIM
# ─────────────────────────────────────────

@role_required("TELECOM")
def generate_branch_report_pdf(request, branch_id):
    if request.user.role not in ["DIRECTOR", "MANAGER"] and not request.user.is_superuser:
        return HttpResponseForbidden()
    branch = get_object_or_404(Branch, id=branch_id)
    today = timezone.now().date()

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="Daily_Report_{branch.name}_{today}.pdf"'

    from reportlab.pdfgen import canvas as pdf_canvas
    from reportlab.lib.pagesizes import letter
    p = pdf_canvas.Canvas(response, pagesize=letter)
    width, height = letter
    y = height - 50

def export_branch_report(request):
    branch = request.user.branch
    today = timezone.now().date()
    sales = RetailSale.objects.filter(branch=branch, date=today)
    buffer = io.BytesIO()
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
    from reportlab.lib.styles import getSampleStyleSheet
    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()
    elements = [Paragraph("Branch Daily Retail Report", styles["Title"]), Spacer(1, 12)]
    data = [["Product", "Quantity", "Amount"]]
    for s in sales:
        data.append([s.product.model_name, s.quantity, f"₦{s.total_amount():,.2f}"])
    elements.append(Table(data))
    doc.build(elements)
    buffer.seek(0)
    return HttpResponse(buffer, content_type="application/pdf")


# ─────────────────────────────────────────
# CRM
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def check_in(request):
    if request.method == "POST":
        user = request.user
        branch = user.branch
        if not branch or not branch.latitude or not branch.longitude:
            msg = "Branch location not configured. Contact your director."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": msg})
            messages.error(request, msg)
            return redirect(_get_dashboard_url(user))

        try:
            latitude = float(request.POST.get("latitude"))
            longitude = float(request.POST.get("longitude"))
        except (TypeError, ValueError):
            msg = "Could not read your location. Please enable GPS and try again."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": msg})
            messages.error(request, msg)
            return redirect(_get_dashboard_url(user))

        selfie = request.FILES.get("selfie")
        today = timezone.now().date()

        if Attendance.objects.filter(user=user, date=today, session="morning").exists():
            msg = "You have already checked in today."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": msg})
            messages.warning(request, msg)
            return redirect(_get_dashboard_url(user))

        distance = calculate_distance(latitude, longitude, branch.latitude, branch.longitude)
        if distance > branch.allowed_radius:
            msg = f"You are {distance:.0f}m away from your branch. Allowed radius is {branch.allowed_radius}m."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": msg, "distance": round(distance, 2)})
            messages.error(request, msg)
            return redirect(_get_dashboard_url(user))

        status = attendance_status()
        if selfie:
            selfie = _compress_image(selfie)

        attendance = Attendance(
            user=user, branch=branch, session="morning",
            check_in_time=timezone.now(),
            latitude=latitude, longitude=longitude,
            distance_from_branch=distance, selfie=selfie,
        )
        if status == "late":
            attendance.is_late = True
            attendance.deduction_amount = Decimal("250.00")
        elif status == "absent":
            attendance.is_absent = True
        attendance.save()

        msg = "Check-in successful! You are " + ("on time." if status == "ontime" else "marked late." if status == "late" else "recorded.")
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": msg})
        messages.success(request, msg)
        return redirect(_get_dashboard_url(user))

    return render(request, "staff/attendance.html")


@role_required("MANAGER")
def staff_checkout(request, staff_id=None):
    if request.method == "POST":
        sid = request.POST.get("staff_id") or staff_id
        if not sid or str(sid) == "0":
            messages.error(request, "Please select a staff member.")
            return redirect("manager_dashboard")
        staff = get_object_or_404(User, id=sid, branch=request.user.branch)
        purpose = request.POST.get("purpose", "Office outing")
        CheckInOutLog.objects.create(
            staff=staff, branch=request.user.branch,
            check_in_time=timezone.now(),
            purpose=purpose, is_checkout=True,
        )
        messages.success(request, f"{staff.username} checked out for: {purpose}")
    return redirect("manager_dashboard")


@role_required("MANAGER")
def staff_checkin(request, staff_id):
    log = CheckInOutLog.objects.filter(
        staff_id=staff_id, branch=request.user.branch,
        is_checkout=True, check_out_time__isnull=True
    ).last()
    if log:
        log.check_out_time = timezone.now()
        log.save()
        messages.success(request, f"{log.staff.username} is back.")
    else:
        messages.warning(request, "No active outing found for this staff.")
    return redirect("manager_dashboard")


@role_required("MANAGER")
def check_out(request):
    if request.method == "POST":
        user = request.user
        branch = user.branch
        if not branch or not branch.latitude or not branch.longitude:
            return JsonResponse({"error": "Branch location not configured."})

        try:
            latitude = float(request.POST.get("latitude"))
            longitude = float(request.POST.get("longitude"))
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid location data."})

        selfie = request.FILES.get("selfie")
        today = timezone.now().date()

        attendance = Attendance.objects.filter(user=user, date=today, session="morning").first()
        if not attendance:
            return JsonResponse({"error": "No morning check-in found for today. Please check in first."})

        if attendance.check_out_time:
            return JsonResponse({"error": "You have already checked out today."})

        distance = calculate_distance(latitude, longitude, branch.latitude, branch.longitude)
        if distance > branch.allowed_radius:
            return JsonResponse({
                "error": f"You are {distance:.0f}m away. Allowed radius is {branch.allowed_radius}m.",
                "distance": round(distance, 2),
                "allowed_radius": branch.allowed_radius,
            })

        attendance.check_out_time = timezone.now()
        if selfie:
            attendance.selfie = selfie
        attendance.save()
        return JsonResponse({"success": "Check-out successful! Have a great evening."})

    return render(request, "staff/attendance.html")


# ─────────────────────────────────────────
# RETAIL STAFF BULK CSV UPLOAD
# ─────────────────────────────────────────

@role_required("RETAIL")
def director_all_branch_stock(request):
    branch_filter = request.GET.get("branch", "")
    search = request.GET.get("search", "")

    # Branch safe stock
    branch_safe = BranchSafeStock.objects.select_related(
        "branch", "product", "product__subcategory"
    ).order_by("branch__name", "product__model_name")

    # Staff stock
    staff_stock = StaffStock.objects.select_related(
        "staff", "staff__branch", "product", "product__subcategory"
    ).order_by("staff__branch__name", "product__model_name")

    if branch_filter:
        branch_safe = branch_safe.filter(branch_id=branch_filter)
        staff_stock = staff_stock.filter(staff__branch_id=branch_filter)

    if search:
        branch_safe = branch_safe.filter(product__model_name__icontains=search)
        staff_stock = staff_stock.filter(product__model_name__icontains=search)

    # Combine into one list with type label
    stock_items = []
    for s in branch_safe:
        if s.quantity > 0:
            stock_items.append({
                "branch": s.branch.name,
                "product": s.product.model_name,
                "category": s.product.subcategory.name if s.product.subcategory else "—",
                "quantity": s.quantity,
                "held_by": "Branch Safe (Manager)",
                "holder_name": "Branch Safe",
                "type": "safe",
                "cost_price": s.product.cost_price,
                "selling_price": s.product.selling_price,
            })
    for s in staff_stock:
        if s.quantity > 0:
            stock_items.append({
                "branch": s.staff.branch.name if s.staff.branch else "—",
                "product": s.product.model_name,
                "category": s.product.subcategory.name if s.product.subcategory else "—",
                "quantity": s.quantity,
                "held_by": "Staff",
                "holder_name": s.staff.username,
                "type": "staff",
                "cost_price": s.product.cost_price,
                "selling_price": s.product.selling_price,
            })

    # Sort by branch name
    stock_items.sort(key=lambda x: (x["branch"], x["product"]))

    total_units = sum(i["quantity"] for i in stock_items)
    total_value = sum(i["quantity"] * (i["selling_price"] or 0) for i in stock_items)

    return render(request, "director/all_branch_stock.html", {
        "stock_items": stock_items,
        "branches": Branch.objects.all(),
        "selected_branch": branch_filter,
        "search": search,
        "total_units": total_units,
        "total_value": total_value,
    })


# ─────────────────────────────────────────
# DIRECTOR — ALL BRANCHES DAILY ACTIVITIES
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def director_all_activities(request):
    date_filter = request.GET.get("date", timezone.now().date().isoformat())
    branch_filter = request.GET.get("branch", "")

    try:
        from datetime import date as _date
        selected_date = _date.fromisoformat(date_filter)
    except Exception:
        selected_date = timezone.now().date()

    # Retail sales
    sales = RetailSale.objects.filter(date=selected_date).select_related(
        "staff", "branch", "product"
    ).order_by("branch__name", "-id")
    if branch_filter:
        sales = sales.filter(branch_id=branch_filter)

    # MultiChoice sales
    mc_sales = MultiChoiceSale.objects.filter(date=selected_date).select_related(
        "staff", "branch"
    ).order_by("branch__name")
    if branch_filter:
        mc_sales = mc_sales.filter(branch_id=branch_filter)

    # Telecom activities
    telecom = ServiceActivity.objects.filter(
        date=selected_date, approved=True
    ).select_related("staff", "branch", "device_tag").order_by("branch__name")
    if branch_filter:
        telecom = telecom.filter(branch_id=branch_filter)

    # Staff movements
    movements = CheckInOutLog.objects.filter(date=selected_date).select_related(
        "staff", "branch"
    ).order_by("branch__name", "-check_in_time")
    if branch_filter:
        movements = movements.filter(branch_id=branch_filter)

    # Attendance
    attendance = Attendance.objects.filter(date=selected_date).select_related(
        "user", "branch"
    ).order_by("branch__name")
    if branch_filter:
        attendance = attendance.filter(branch_id=branch_filter)

    # Summaries
    retail_summary = sales.values("branch__name").annotate(
        total_qty=Sum("quantity"),
        total_rev=Sum(F("quantity") * F("selling_price"))
    ).order_by("branch__name")

    return render(request, "director/all_activities.html", {
        "sales": sales,
        "mc_sales": mc_sales,
        "telecom": telecom,
        "movements": movements,
        "attendance": attendance,
        "retail_summary": retail_summary,
        "branches": Branch.objects.all(),
        "selected_branch": branch_filter,
        "selected_date": selected_date,
        "total_retail_rev": sales.aggregate(
            t=Sum(F("quantity") * F("selling_price"))
        )["t"] or 0,
        "total_mc_rev": mc_sales.aggregate(t=Sum("amount"))["t"] or 0,
        "total_telecom": telecom.aggregate(t=Sum("quantity"))["t"] or 0,
    })
# ─────────────────────────────────────────
# start_weekly_report — handle empty decimal fields
# ─────────────────────────────────────────

@login_required
def payroll_deduction_summary(request):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch

    year  = int(request.GET.get("year",  date.today().year))
    month = int(request.GET.get("month", date.today().month))

    records = Attendance.objects.filter(
        date__year=year, date__month=month
    ).select_related("user", "branch").order_by("user__username")

    # Aggregate per staff
    from django.db.models import Count
    staff_summary = (
        records.values("user__username", "branch__name")
        .annotate(
            total_late=Count("id", filter=Q(is_late=True)),
            total_absent=Count("id", filter=Q(is_absent=True)),
            total_deduction=Sum("deduction_amount"),
        )
        .order_by("branch__name", "user__username")
    )

    export = request.GET.get("export")
    if export == "pdf":
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer)
        styles = getSampleStyleSheet()
        month_name = date(year, month, 1).strftime("%B %Y")
        elements = [
            Paragraph(f"Payroll Deduction Summary — {month_name}", styles["Title"]),
            Spacer(1, 0.2 * inch),
        ]
        data = [["Staff", "Branch", "Late Days", "Absent Days", "Total Deduction (₦)"]]
        grand_total = Decimal(0)
        for s in staff_summary:
            ded = s["total_deduction"] or Decimal(0)
            grand_total += ded
            data.append([
                s["user__username"], s["branch__name"],
                s["total_late"], s["total_absent"],
                f"₦{ded:,.2f}",
            ])
        data.append(["", "", "", "TOTAL", f"₦{grand_total:,.2f}"])
        t = Table(data, colWidths=[2*inch, 1.5*inch, 1*inch, 1*inch, 1.5*inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#004F9F")),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
            ("GRID",       (0,0), (-1,-1), 0.5, colors.grey),
            ("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#f3f4f6")),
            ("FONTNAME",   (0,-1), (-1,-1), "Helvetica-Bold"),
        ]))
        elements.append(t)
        doc.build(elements)
        buffer.seek(0)
        fname = f"Payroll_Deductions_{month_name.replace(' ','_')}.pdf"
        return HttpResponse(buffer, content_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    months = [(i, date(2000, i, 1).strftime("%B")) for i in range(1, 13)]
    years  = list(range(date.today().year - 2, date.today().year + 1))
    return render(request, "director/payroll_summary.html", {
        "staff_summary": staff_summary,
        "year": year, "month": month,
        "months": months, "years": years,
        "month_name": date(year, month, 1).strftime("%B %Y"),
        "grand_total": sum(s["total_deduction"] or 0 for s in staff_summary),
    })


# ─────────────────────────────────────────
# DIRECTOR DASHBOARD WITH CACHING + CHART DATA
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def director_dashboard(request):
    from django.core.cache import cache
    today = timezone.now().date()
    device_filter = request.GET.get("device")

    # Cache key changes daily and by device filter
    cache_key = f"director_dash_{today}_{device_filter or 'all'}"
    cached = cache.get(cache_key)

    if not cached:
        activities = ServiceActivity.objects.filter(
            date__year=today.year, date__month=today.month, approved=True
        ).select_related("staff", "branch", "device_tag")
        if device_filter:
            activities = activities.filter(device_tag_id=device_filter)
        branch_summary = list(activities.values("branch__name").annotate(total=Sum("quantity")).order_by("-total"))

        all_sales_today = RetailSale.objects.filter(date=today, is_voided=False)
        total_expenses = Expense.objects.filter(date=today).aggregate(total=Sum("amount"))["total"] or 0
        total_quantity = all_sales_today.aggregate(total=Sum("quantity"))["total"] or 0
        total_revenue  = all_sales_today.aggregate(total=Sum(F("quantity") * F("selling_price")))["total"] or 0
        profit_expr = ExpressionWrapper(
            (F("selling_price") - F("product__cost_price")) * F("quantity"), output_field=DecimalField()
        )
        gross_profit = all_sales_today.aggregate(total=Sum(profit_expr))["total"] or 0
        net_profit   = (gross_profit or 0) - total_expenses

        monthly_sales    = RetailSale.objects.filter(date__month=today.month, date__year=today.year, is_voided=False)
        monthly_expenses = Expense.objects.filter(date__month=today.month, date__year=today.year).aggregate(total=Sum("amount"))["total"] or 0
        monthly_revenue  = monthly_sales.aggregate(total=Sum(F("quantity") * F("selling_price")))["total"] or 0
        monthly_gross    = monthly_sales.aggregate(total=Sum(profit_expr))["total"] or 0
        monthly_net      = (monthly_gross or 0) - monthly_expenses

        mc_today = MultiChoiceSale.objects.filter(date=today)
        multichoice_total      = mc_today.aggregate(total=Sum("amount"))["total"] or 0
        multichoice_by_branch  = list(mc_today.values("branch__name").annotate(total_revenue=Sum("amount")).order_by("-total_revenue"))
        branch_performance     = list(all_sales_today.values("branch__name").annotate(
            total_qty=Sum("quantity"), total_revenue=Sum(F("quantity") * F("selling_price"))
        ).order_by("-total_revenue"))
        staff_performance      = list(all_sales_today.values("staff__username", "branch__name").annotate(
            total_qty=Sum("quantity"), total_revenue=Sum(F("quantity") * F("selling_price"))
        ).order_by("-total_revenue")[:10])
        top_products           = list(all_sales_today.values("product__model_name").annotate(
            total_qty=Sum("quantity")
        ).order_by("-total_qty")[:10])
        low_stock = list(BranchSafeStock.objects.filter(quantity__lt=1).select_related("product", "branch"))

        # 30-day revenue chart data
        chart_labels  = []
        chart_revenue = []
        for i in range(29, -1, -1):
            d = today - timedelta(days=i)
            rev = RetailSale.objects.filter(date=d, is_voided=False).aggregate(
                t=Sum(F("quantity") * F("selling_price"))
            )["t"] or 0
            chart_labels.append(d.strftime("%-d %b"))
            chart_revenue.append(float(rev))

        cached = {
            "branch_summary": branch_summary,
            "total_quantity": total_quantity,
            "total_revenue": total_revenue,
            "total_profit": net_profit,
            "gross_profit": gross_profit,
            "total_expenses": total_expenses,
            "monthly_revenue": monthly_revenue,
            "monthly_profit": monthly_net,
            "monthly_gross_profit": monthly_gross,
            "monthly_expenses": monthly_expenses,
            "multichoice_total": multichoice_total,
            "multichoice_by_branch": multichoice_by_branch,
            "branch_performance": branch_performance,
            "staff_performance": staff_performance,
            "top_products": top_products,
            "low_stock": low_stock,
            "chart_labels": chart_labels,
            "chart_revenue": chart_revenue,
        }
        cache.set(cache_key, cached, 300)  # cache 5 minutes

    from core.models import Notification
    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    check_logs   = CheckInOutLog.objects.filter(branch=request.user.branch).order_by("-date", "-check_in_time")[:20]

    cached.update({
        "device_tags": DeviceTag.objects.all(),
        "selected_device": device_filter,
        "categories": RetailCategory.objects.all(),
        "all_branches": Branch.objects.all(),
        "check_logs": check_logs,
        "unread_count": unread_count,
    })
    return render(request, "director_dashboard.html", cached)


# ─────────────────────────────────────────
# AUDIT LOG VIEW (Director only)
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def audit_log_view(request):
    from core.models import AuditLog
    logs = AuditLog.objects.select_related("user").order_by("-timestamp")
    action_filter = request.GET.get("action", "")
    model_filter  = request.GET.get("model", "")
    if action_filter:
        logs = logs.filter(action=action_filter)
    if model_filter:
        logs = logs.filter(model_name__icontains=model_filter)
    paginator = Paginator(logs, 50)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "director/audit_log.html", {
        "logs": page,
        "action_filter": action_filter,
        "model_filter": model_filter,
    })


# ─────────────────────────────────────────
# CUSTOMER PURCHASE HISTORY
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def customer_history(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    # Match by phone number across sales
    sales = RetailSale.objects.filter(
        customer_phone=customer.phone_number, is_voided=False
    ).select_related("product", "staff", "branch").order_by("-date", "-time")

    total_spent = sales.aggregate(
        t=Sum(F("quantity") * F("selling_price"))
    )["t"] or 0
    total_items = sales.aggregate(t=Sum("quantity"))["t"] or 0

    # Update customer totals
    customer.purchase_count = sales.count()
    customer.total_spent    = total_spent
    if sales.exists():
        latest = sales.first()
        customer.last_purchase = timezone.make_aware(
            timezone.datetime.combine(latest.date, latest.time)
        )
    customer.save(update_fields=["purchase_count", "total_spent", "last_purchase"])

    return render(request, "customer_history.html", {
        "customer": customer,
        "sales": sales,
        "total_spent": total_spent,
        "total_items": total_items,
    })


# ─────────────────────────────────────────
# MANAGER: VIEW TODAY'S SALES WITH VOID OPTION
# ─────────────────────────────────────────

@role_required("MANAGER")
def director_attendance_dashboard(request):
    selected_date_str = request.GET.get("date", timezone.now().date().isoformat())
    branch_filter = request.GET.get("branch", "")

    try:
        from datetime import date as _date
        selected_date = _date.fromisoformat(selected_date_str)
    except Exception:
        selected_date = timezone.now().date()

    staff_filter = request.GET.get("staff", "")

    records = Attendance.objects.filter(date=selected_date).select_related("user", "branch").order_by("branch__name", "user__username")

    if branch_filter:
        records = records.filter(branch_id=branch_filter)
    if staff_filter:
        records = records.filter(user_id=staff_filter)

    all_staff = User.objects.exclude(role__in=["DIRECTOR","SUPERADMIN"]).select_related("branch").order_by("branch__name", "username")

    return render(request, "director/attendance.html", {
        "records": records,
        "selected_date": selected_date,
        "selected_branch": branch_filter,
        "selected_staff": staff_filter,
        "branches": Branch.objects.all(),
        "all_staff": all_staff,
        "total_ontime": records.filter(is_late=False, is_absent=False).count(),
        "total_late": records.filter(is_late=True).count(),
        "total_absent": records.filter(is_absent=True).count(),
        "total_deductions": records.aggregate(Sum("deduction_amount"))["deduction_amount__sum"] or 0,
    })


# ─────────────────────────────────────────
# FULL ATTENDANCE PDF — with selfies, check-in/out times, status
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def export_monthly_attendance_pdf(request):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER

    date_str   = request.GET.get("date", "")
    month_str  = request.GET.get("month", "")
    branch_str = request.GET.get("branch", "")

    records = Attendance.objects.all().select_related("user", "branch").order_by("branch__name", "date", "user__username")
    filename_label = "Full_Report"

    if date_str:
        try:
            from datetime import date as _d
            d = _d.fromisoformat(date_str)
            records = records.filter(date=d)
            filename_label = d.strftime("%d_%b_%Y")
        except Exception:
            pass
    elif month_str:
        try:
            yr, mo = month_str.split("-")
            records = records.filter(date__year=int(yr), date__month=int(mo))
            from datetime import date as _d
            filename_label = _d(int(yr), int(mo), 1).strftime("%B_%Y")
        except Exception:
            pass

    if branch_str:
        records = records.filter(branch_id=branch_str)

    BLUE  = colors.HexColor("#004F9F")
    LGRAY = colors.HexColor("#F3F4F6")
    MGRAY = colors.HexColor("#374151")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, rightMargin=0.5*inch, leftMargin=0.5*inch, topMargin=0.7*inch, bottomMargin=0.7*inch)
    styles = getSampleStyleSheet()

    title_s = ParagraphStyle("T", parent=styles["Heading1"], fontSize=15, textColor=BLUE, alignment=TA_CENTER, spaceAfter=2)
    sub_s   = ParagraphStyle("S", parent=styles["Normal"], fontSize=9, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=10)
    foot_s  = ParagraphStyle("F", parent=styles["Normal"], fontSize=8, textColor=colors.grey, alignment=TA_CENTER)

    elements = [
        Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED", title_s),
        Paragraph(f"Staff Attendance Report — {filename_label.replace(chr(95), chr(32))}", sub_s),
        HRFlowable(width="100%", thickness=2, color=BLUE, spaceAfter=10),
    ]

    branch_groups = {}
    for r in records:
        bn = r.branch.name if r.branch else "No Branch"
        branch_groups.setdefault(bn, []).append(r)

    summary_data = [["Branch", "Present", "On Time", "Late", "Absent", "Total Deductions"]]
    grand_ded = Decimal(0)
    for bn, recs in branch_groups.items():
        on_time = sum(1 for r in recs if not r.is_late and not r.is_absent)
        late    = sum(1 for r in recs if r.is_late)
        absent  = sum(1 for r in recs if r.is_absent)
        ded     = sum(r.deduction_amount or 0 for r in recs)
        grand_ded += ded
        summary_data.append([bn, len(recs), on_time, late, absent, f"N{ded:,.2f}"])
    summary_data.append(["TOTAL", sum(len(v) for v in branch_groups.values()), "", "", "", f"N{grand_ded:,.2f}"])

    st = Table(summary_data, colWidths=[2.2*inch, 0.8*inch, 0.8*inch, 0.7*inch, 0.7*inch, 1.3*inch])
    st.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (-1,0), BLUE), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME",    (0,0), (-1,0), "Helvetica-Bold"),
        ("BACKGROUND",  (0,-1), (-1,-1), LGRAY), ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
        ("GRID",        (0,0), (-1,-1), 0.4, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0,1), (-1,-2), [colors.white, colors.HexColor("#F9FAFB")]),
        ("ALIGN",       (1,0), (-1,-1), "CENTER"), ("FONTSIZE", (0,0), (-1,-1), 9),
        ("TOPPADDING",  (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    elements.append(Paragraph("Summary by Branch", styles["Heading2"]))
    elements.append(st)
    elements.append(Spacer(1, 0.25*inch))

    for bn, recs in branch_groups.items():
        branch_header = Table([[Paragraph(f"  {bn}", ParagraphStyle("bh", parent=styles["Normal"], fontSize=10, textColor=colors.white, fontName="Helvetica-Bold"))]], colWidths=[7.5*inch])
        branch_header.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), MGRAY), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5)]))
        elements.append(branch_header)
        elements.append(Spacer(1, 2))

        rows = [["Staff", "Date", "Check In", "Check Out", "Status", "Distance", "Deduction"]]
        for r in recs:
            status  = "ABSENT" if r.is_absent else ("LATE" if r.is_late else "ON TIME")
            cin     = r.check_in_time.strftime("%H:%M")  if r.check_in_time  else "--"
            cout    = r.check_out_time.strftime("%H:%M") if r.check_out_time else "Not out"
            dist    = f"{r.distance_from_branch:.0f}m" if r.distance_from_branch else "--"
            ded     = f"N{r.deduction_amount:,.2f}" if r.deduction_amount else "--"
            rows.append([r.user.username, r.date.strftime("%d %b %Y"), cin, cout, status, dist, ded])

        dt = Table(rows, colWidths=[1.3*inch, 0.9*inch, 0.75*inch, 0.8*inch, 0.75*inch, 0.75*inch, 0.95*inch], repeatRows=1)
        dt.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0), colors.HexColor("#E5E7EB")),
            ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",      (0,0), (-1,-1), 8),
            ("GRID",          (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
            ("ALIGN",         (1,0), (-1,-1), "CENTER"),
            ("TOPPADDING",    (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ]))
        elements.append(dt)
        elements.append(Spacer(1, 0.15*inch))

    elements.append(HRFlowable(width="100%", thickness=1, color=BLUE, spaceBefore=10))
    elements.append(Paragraph("Generated " + timezone.now().strftime("%d %B %Y at %H:%M") + " — Global Phonelinz Systems Ltd", foot_s))

    doc.build(elements)
    buffer.seek(0)
    return HttpResponse(buffer, content_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="Attendance_{filename_label}.pdf"'})



# ─────────────────────────────────────────
# FIXED record_multichoice_sale
# Balance reduces after every subscription
# Shows running balance clearly
# ─────────────────────────────────────────

@role_required("MULTICHOICE")
def director_safe_stock(request):
    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")
    export    = request.GET.get("export", "")

    stocks = DirectorSafeStock.objects.all().select_related(
        "product", "product__subcategory"
    ).order_by("-date_added")

    if date_from:
        stocks = stocks.filter(date_added__date__gte=date_from)
    if date_to:
        stocks = stocks.filter(date_added__date__lte=date_to)

    all_stocks = list(stocks)
    total_quantity = sum(s.quantity for s in all_stocks)
    total_value    = sum(s.total_value for s in all_stocks)

    if export == "pdf":
        return _director_safe_pdf(all_stocks, date_from, date_to)

    # Logs for director safe
    from core.models import AuditLog
    safe_logs = AuditLog.objects.filter(
        model_name="DirectorSafeStock"
    ).select_related("user").order_by("-timestamp")
    if date_from:
        safe_logs = safe_logs.filter(timestamp__date__gte=date_from)
    if date_to:
        safe_logs = safe_logs.filter(timestamp__date__lte=date_to)
    paginator_logs = Paginator(safe_logs, 30)
    logs_page = paginator_logs.get_page(request.GET.get("log_page"))

    return render(request, "director/director_safe.html", {
        "stocks": all_stocks,
        "products": Product.objects.all().order_by("model_name"),
        "categories": RetailCategory.objects.all(),
        "total_quantity": total_quantity,
        "total_value": total_value,
        "all_branches": Branch.objects.all(),
        "all_staff": User.objects.exclude(
            role__in=["DIRECTOR", "SUPERADMIN"]
        ).select_related("branch").order_by("branch__name", "username"),
        "safe_logs": logs_page,
        "date_from": date_from,
        "date_to": date_to,
    })


def add_director_stock(request):
    if request.method == "POST":
        try:
            product = get_object_or_404(Product, id=request.POST.get("product_id"))
            qty = int(request.POST.get("quantity", 0))
            notes = request.POST.get("notes", "")
            with transaction.atomic():
                DirectorSafeStock.objects.create(product=product, quantity=qty, notes=notes)
                try:
                    from core.models import AuditLog
                    AuditLog.objects.create(
                        user=request.user, action="CREATE",
                        model_name="DirectorSafeStock",
                        description=f"Added {qty}x {product.model_name} to director safe. Notes: {notes}",
                    )
                except Exception:
                    pass
            messages.success(request, f"Added {qty}x {product.model_name} to director safe.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("director_safe_stock")



@role_required("RETAIL")
def attendance_history(request):
    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")
    export    = request.GET.get("export", "")

    qs = Attendance.objects.filter(user=request.user).order_by("-date")

    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    total_late     = qs.filter(is_late=True).count()
    total_absent   = qs.filter(is_absent=True).count()
    total_deductions = qs.aggregate(t=Sum("deduction_amount"))["t"] or 0

    if export == "pdf":
        return _attendance_pdf(qs, request.user, date_from, date_to)

    paginator = Paginator(qs, 30)
    records = paginator.get_page(request.GET.get("page"))
    return render(request, "staff/attendance_history.html", {
        "records": records,
        "total_late": total_late,
        "total_absent": total_absent,
        "total_deductions": total_deductions,
        "date_from": date_from,
        "date_to": date_to,
    })


def daily_sales_report(request):
    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to", "")
    branch_flt = request.GET.get("branch", "")
    staff_flt  = request.GET.get("staff", "")
    export     = request.GET.get("export", "")
    today      = timezone.now().date()

    if not date_from and not date_to:
        date_from = today.isoformat()
        date_to   = today.isoformat()

    sales = RetailSale.objects.filter(
        is_voided=False
    ).select_related("product", "branch", "staff").order_by("branch__name", "-date", "-time")

    if date_from:
        sales = sales.filter(date__gte=date_from)
    if date_to:
        sales = sales.filter(date__lte=date_to)
    if branch_flt:
        sales = sales.filter(branch_id=branch_flt)
    if staff_flt:
        sales = sales.filter(staff_id=staff_flt)

    total_qty     = sales.aggregate(t=Sum("quantity"))["t"] or 0
    total_revenue = sales.aggregate(t=Sum(F("quantity") * F("selling_price")))["t"] or 0

    branch_sales_summary = {}
    for s in sales:
        amt = Decimal(s.quantity) * s.selling_price
        bk  = s.branch.name
        if bk not in branch_sales_summary:
            branch_sales_summary[bk] = {"sales": [], "total_qty": 0, "total_revenue": Decimal(0)}
        branch_sales_summary[bk]["sales"].append({
            "product": s.product.model_name, "quantity": s.quantity,
            "price": s.selling_price, "amount": amt,
            "staff": s.staff.username,
            "date": s.date, "time": s.time,
        })
        branch_sales_summary[bk]["total_qty"] += s.quantity
        branch_sales_summary[bk]["total_revenue"] += amt

    if export == "pdf":
        return _director_sales_pdf(branch_sales_summary, total_qty, total_revenue, date_from, date_to)

    return render(request, "daily_sales_report.html", {
        "branch_sales_summary": branch_sales_summary,
        "total_qty": total_qty, "total_revenue": total_revenue,
        "all_branches": Branch.objects.all(),
        "all_staff": User.objects.exclude(role__in=["DIRECTOR","SUPERADMIN"]).order_by("username"),
        "date_from": date_from,
        "date_to": date_to,
        "selected_branch": branch_flt,
        "selected_staff": staff_flt,
        "today": today,
    })


def director_release_stock(request):
    if request.method == "POST":
        product_id   = request.POST.get("product_id")
        quantity     = int(request.POST.get("quantity", 0))
        release_type = request.POST.get("release_type")
        branch_id    = request.POST.get("branch_id")
        staff_id     = request.POST.get("staff_id")

        if not product_id:
            messages.error(request, "Please select a product.")
            return redirect("director_safe_stock")

        director_stock = DirectorSafeStock.objects.filter(
            product_id=product_id
        ).first()

        if not director_stock:
            messages.error(request, "Product not found in director safe.")
            return redirect("director_safe_stock")

        if quantity <= 0:
            messages.error(request, "Quantity must be greater than 0.")
            return redirect("director_safe_stock")

        if quantity > director_stock.quantity:
            messages.error(
                request,
                f"Only {director_stock.quantity} unit(s) of "
                f"{director_stock.product.model_name} available in director safe."
            )
            return redirect("director_safe_stock")

        product = director_stock.product
        desc    = ""

        with transaction.atomic():
            # Reduce director safe
            director_stock.quantity -= quantity
            if director_stock.quantity == 0:
                director_stock.delete()
            else:
                director_stock.save()

            if release_type == "sale":
                desc = (
                    f"Director direct sale: {quantity}x {product.model_name}. "
                    f"Branch: {Branch.objects.filter(id=branch_id).first().name if branch_id else 'N/A'}."
                )
                messages.success(
                    request,
                    f"Recorded direct sale of {quantity}x {product.model_name} from director safe."
                )

            elif release_type == "branch_safe":
                if not branch_id:
                    messages.error(request, "Please select a branch.")
                    return redirect("director_safe_stock")
                branch = get_object_or_404(Branch, id=branch_id)

                # ADD to branch safe stock (not replace)
                safe_stock, _ = BranchSafeStock.objects.get_or_create(
                    branch=branch, product=product
                )
                safe_stock.quantity += quantity
                safe_stock.save()

                StockMovement.objects.create(
                    branch=branch, product=product,
                    quantity=quantity, movement_type="IN",
                    performed_by=request.user,
                )
                desc = (
                    f"Released {quantity}x {product.model_name} from director safe "
                    f"to {branch.name} branch safe. New branch safe qty: {safe_stock.quantity}."
                )
                messages.success(request, desc)

            elif release_type == "staff":
                if not staff_id:
                    messages.error(request, "Please select a staff member.")
                    return redirect("director_safe_stock")
                staff = get_object_or_404(User, id=staff_id)

                # ADD to staff stock (not replace)
                staff_stock, _ = StaffStock.objects.get_or_create(
                    staff=staff, product=product
                )
                staff_stock.quantity += quantity
                staff_stock.save()

                desc = (
                    f"Released {quantity}x {product.model_name} from director safe "
                    f"directly to {staff.username} "
                    f"({staff.branch.name if staff.branch else 'No branch'}). "
                    f"Staff stock now: {staff_stock.quantity}."
                )
                messages.success(request, desc)

            else:
                messages.error(request, "Invalid release type selected.")
                return redirect("director_safe_stock")

            # Log to AuditLog
            try:
                from core.models import AuditLog
                AuditLog.objects.create(
                    user=request.user,
                    action="UPDATE",
                    model_name="DirectorSafeStock",
                    description=desc,
                )
            except Exception:
                pass

    return redirect("director_safe_stock")


@role_required("TELECOM")
def customer_crm(request):
    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to", "")
    search     = request.GET.get("search", "")
    source     = request.GET.get("source", "")   # RETAIL, MULTICHOICE, TELECOM
    branch_flt = request.GET.get("branch", "")
    sort_by    = request.GET.get("sort", "-last_purchase")  # or -total_spent, -purchase_count

    customers = Customer.objects.all().order_by(sort_by)

    if search:
        customers = customers.filter(
            Q(name__icontains=search) | Q(phone_number__icontains=search)
        )
    if date_from:
        customers = customers.filter(last_purchase__date__gte=date_from)
    if date_to:
        customers = customers.filter(last_purchase__date__lte=date_to)
    if branch_flt:
        customers = customers.filter(branch_id=branch_flt)

    # Filter by source — check if phone appears in that source
    if source == "RETAIL":
        phones = RetailSale.objects.filter(
            is_voided=False
        ).values_list("customer_phone", flat=True).distinct()
        customers = customers.filter(phone_number__in=phones)
    elif source == "MULTICHOICE":
        phones = MultiChoiceSale.objects.values_list(
            "customer_phone", flat=True
        ).distinct()
        customers = customers.filter(phone_number__in=phones)
    elif source == "TELECOM":
        phones = ServiceActivity.objects.values_list(
            "customer_phone", flat=True
        ).distinct()
        customers = customers.filter(phone_number__in=phones)

    paginator = Paginator(customers, 30)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "customer_crm.html", {
        "customers": page,
        "total_customers": customers.count(),
        "search": search,
        "date_from": date_from,
        "date_to": date_to,
        "source": source,
        "branch_flt": branch_flt,
        "sort_by": sort_by,
        "branches": Branch.objects.all(),
    })


