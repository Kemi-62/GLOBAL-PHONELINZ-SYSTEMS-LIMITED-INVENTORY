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

def approve_activity(request, activity_id):
    if request.user.role not in ["MANAGER", "SUPERADMIN"] and not request.user.is_superuser:
        return HttpResponseForbidden("Not allowed")
    activity = get_object_or_404(ServiceActivity, id=activity_id, branch=request.user.branch)
    activity.approved = True
    activity.requires_approval = False
    activity.save()
    messages.success(request, "Activity approved.")
    return redirect("manager_dashboard")


# ─────────────────────────────────────────
# DIRECTOR DASHBOARD
# ─────────────────────────────────────────
@role_required("DIRECTOR")
def record_physical_product(request):
    if request.method == "POST":
        product_type = request.POST.get("product_type")
        quantity = int(request.POST.get("quantity", 0))
        with transaction.atomic():
            ServiceActivity.objects.create(
                branch=request.user.branch, staff=request.user,
                service_type=product_type, quantity=quantity,
            )
            if product_type == "WHOLESALE_SIM":
                try:
                    inv = SimInventory.objects.get(branch=request.user.branch)
                    inv.total_sold += quantity
                    inv.save()
                    SimInventoryLog.objects.create(
                        inventory=inv, transaction_type="SOLD", quantity=quantity,
                        description=f"Wholesale SIM: {quantity} by {request.user.username}",
                        created_by=request.user,
                    )
                except SimInventory.DoesNotExist:
                    pass
        messages.success(request, f"Recorded {quantity} × {product_type}.")
    return redirect("staff_dashboard")


@role_required("MANAGER")
def add_sim_received(request):
    if request.method == "POST":
        quantity = int(request.POST.get("quantity", 0))
        if quantity > 0:
            inv = get_object_or_404(SimInventory, branch=request.user.branch)
            with transaction.atomic():
                inv.total_received += quantity
                inv.save()
                SimInventoryLog.objects.create(
                    inventory=inv, transaction_type="RECEIVED", quantity=quantity,
                    description=f"SIM received: {request.POST.get('notes', '')}",
                    created_by=request.user,
                )
            messages.success(request, f"Added {quantity} SIM to inventory.")
        else:
            messages.error(request, "Quantity must be greater than 0.")
    return redirect("manager_dashboard")


@role_required("MANAGER")
def set_sim_opening_balance(request):
    if request.method == "POST":
        quantity = int(request.POST.get("quantity", 0))
        if quantity >= 0:
            inv = get_object_or_404(SimInventory, branch=request.user.branch)
            now = timezone.now()
            if inv.current_month != now.month or inv.current_year != now.year:
                with transaction.atomic():
                    inv.opening_balance = quantity
                    inv.total_received = 0
                    inv.total_sold = 0
                    inv.current_month = now.month
                    inv.current_year = now.year
                    inv.save()
                    SimInventoryLog.objects.create(
                        inventory=inv, transaction_type="OPENING", quantity=quantity,
                        description=f"Opening balance for {now.strftime('%B %Y')}",
                        created_by=request.user,
                    )
                messages.success(request, f"Opening balance set to {quantity}.")
            else:
                messages.warning(request, "Opening balance already set for this month.")
        else:
            messages.error(request, "Quantity must be 0 or more.")
    return redirect("manager_dashboard")


# ─────────────────────────────────────────
# EXPENSES / MISC
# ─────────────────────────────────────────

@role_required("MANAGER")
def create_service_target(request):
    if request.method == "POST":
        ServiceTarget.objects.update_or_create(
            branch=request.user.branch,
            service_type=request.POST.get("service_type"),
            device_tag_id=request.POST.get("device_tag") or None,
            date=date.today().replace(day=1),
            defaults={"target_number": int(request.POST.get("target_number", 0)), "created_by": request.user}
        )
        messages.success(request, "Target set.")
    return redirect("manager_dashboard")


@role_required("MANAGER")
def staff_monthly_activity(request):
    activities = ServiceActivity.objects.filter(
        branch=request.user.branch,
        date__year=date.today().year,
        date__month=date.today().month,
    ).select_related("staff")
    return render(request, "manager_dashboard.html", {"activities": activities})

def telecom_activity_history(request):
    from django.db.models import Sum
    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to", "")
    stype      = request.GET.get("service_type", "")
    export     = request.GET.get("export", "")

    activities = ServiceActivity.objects.filter(
        staff=request.user
    ).select_related("branch", "device_tag").order_by("-date", "-id")

    if date_from:
        activities = activities.filter(date__gte=date_from)
    if date_to:
        activities = activities.filter(date__lte=date_to)
    if stype:
        activities = activities.filter(service_type=stype)

    total_qty = activities.filter(approved=True).aggregate(t=Sum("quantity"))["t"] or 0

    if export == "pdf":
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.enums import TA_CENTER
        import io as _io
        BLUE = colors.HexColor("#004F9F")
        buf = _io.BytesIO()
        doc = SimpleDocTemplate(buf, rightMargin=0.5*inch, leftMargin=0.5*inch,
                                topMargin=0.6*inch, bottomMargin=0.6*inch)
        styles = getSampleStyleSheet()
        label = f"{request.user.username} - Telecom Activity History"
        if date_from or date_to:
            label += f"  |  {date_from or 'Start'} to {date_to or 'Today'}"
        elements = [
            Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED",
                ParagraphStyle("T", parent=styles["Heading1"], fontSize=13, textColor=BLUE, alignment=TA_CENTER)),
            Paragraph(label,
                ParagraphStyle("S", parent=styles["Normal"], fontSize=8, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=10)),
        ]
        data = [["Date", "Service Type", "Device Tag", "Quantity", "Status", "Recorded By"]]
        for a in activities:
            data.append([
                a.date.strftime("%d %b %Y"),
                a.service_type,
                a.device_tag.tag_name if a.device_tag else "—",
                str(a.quantity),
                "Approved" if a.approved else ("Pending" if a.requires_approval else "Logged"),
                a.staff.username,
            ])
        t = Table(data, colWidths=[1*inch, 1.3*inch, 1*inch, 0.7*inch, 0.9*inch, 1.3*inch], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), BLUE),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
            ("TOPPADDING", (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ]))
        elements.append(t)
        doc.build(elements)
        buf.seek(0)
        fname = f"TelecomActivity_{request.user.username}_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ", "_")
        from django.http import HttpResponse
        return HttpResponse(buf, content_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    from django.core.paginator import Paginator
    paginator = Paginator(activities, 30)
    page = paginator.get_page(request.GET.get("page"))

    service_types = ServiceActivity.objects.filter(
        staff=request.user
    ).values_list("service_type", flat=True).distinct()

    return render(request, "staff/activity_history.html", {
        "activities": page,
        "total_qty": total_qty,
        "date_from": date_from,
        "date_to": date_to,
        "selected_type": stype,
        "service_types": service_types,
    })



# ─────────────────────────────────────────
# HELPER: Save/update customer record from any dashboard
# ─────────────────────────────────────────

def staff_dashboard(request):
    today = date.today()
    branch = request.user.branch

    targets = ServiceTarget.objects.filter(
        branch=branch, date__year=today.year, date__month=today.month
    )
    activities = ServiceActivity.objects.filter(
        staff=request.user, date__year=today.year, date__month=today.month
    ).order_by("-date", "-id")

    if request.method == "POST":
        service_type   = request.POST.get("service_type")
        quantity       = int(request.POST.get("quantity") or 0)
        customer_phone = request.POST.get("customer_phone", "").strip()
        customer_name  = request.POST.get("customer_name", "").strip()
        price          = Decimal(request.POST.get("price") or "0")
        device_tag_id  = request.POST.get("device_tag")
        device_tag     = None
        if device_tag_id:
            device_tag = DeviceTag.objects.filter(id=device_tag_id).first()

        requires_approval = False
        if service_type == "SIM_REG":
            target = ServiceTarget.objects.filter(
                branch=branch, service_type="SIM_REG",
                device_tag=device_tag,
                date__year=today.year, date__month=today.month
            ).first()
            if target:
                achieved = ServiceActivity.objects.filter(
                    branch=branch, service_type="SIM_REG",
                    device_tag=device_tag,
                    date__year=today.year, date__month=today.month,
                    approved=True
                ).aggregate(total=Sum("quantity"))["total"] or 0
                if achieved >= target.target_number:
                    requires_approval = True

        with transaction.atomic():
            activity = ServiceActivity.objects.create(
                branch=branch,
                staff=request.user,
                service_type=service_type,
                device_tag=device_tag,
                quantity=quantity,
                customer_phone=customer_phone,
                requires_approval=requires_approval,
                approved=not requires_approval,
            )

            if service_type in ["SIM_REG", "SIM_SWAP", "SIM_UPGRADE"]:
                try:
                    inv = SimInventory.objects.get(branch=branch)
                    inv.total_sold += quantity
                    inv.save()
                    SimInventoryLog.objects.create(
                        inventory=inv,
                        transaction_type="SOLD",
                        quantity=quantity,
                        description=f"{service_type}: {quantity} SIM by {request.user.username}",
                        created_by=request.user,
                    )
                except SimInventory.DoesNotExist:
                    pass

            # Update Customer CRM if phone provided
            if customer_phone:
                _upsert_customer(
                    phone=customer_phone,
                    name=customer_name,
                    branch=branch,
                    amount=price * quantity,
                    source="TELECOM",
                )

        messages.success(request, "Activity recorded.")
        return redirect("staff_dashboard")

    # Build device progress
    device_progress = []
    for target in targets.filter(service_type="SIM_REG"):
        achieved = activities.filter(
            service_type="SIM_REG", device_tag=target.device_tag, approved=True
        ).aggregate(total=Sum("quantity"))["total"] or 0
        pct = round((achieved / target.target_number) * 100, 2) if target.target_number else 0
        device_progress.append({
            "device": target.device_tag.tag_name if target.device_tag else "Generic",
            "target": target.target_number,
            "achieved": achieved,
            "remaining": max(target.target_number - achieved, 0),
            "percentage": pct,
            "exceeded": achieved >= target.target_number,
        })

    # Recent activity log (paginated)
    from django.core.paginator import Paginator as _Pag
    paginator = _Pag(activities, 20)
    activities_page = paginator.get_page(request.GET.get("page"))

    check_logs = CheckInOutLog.objects.filter(staff=request.user).order_by(
        "-date", "-check_in_time"
    )[:20]
    sim_inventory, _ = SimInventory.objects.get_or_create(branch=branch)

    # ── WHOLESALE DEVICE DATA (merged into telecom dashboard) ──
    from core.models import WholesaleDevice, WholesaleDeviceSale
    wholesale_devices = WholesaleDevice.objects.filter(
        branch=branch, staff=request.user
    ).order_by("-date_added")
    wholesale_sales = WholesaleDeviceSale.objects.filter(
        branch=branch, sold_by=request.user
    ).select_related("device").order_by("-created_at")
    wholesale_inventory_value = sum(d.total_value for d in wholesale_devices)
    wholesale_sales_total = wholesale_sales.aggregate(t=Sum("total_amount"))["t"] or 0
    wholesale_director_total = wholesale_sales.filter(
        is_director_sale=True
    ).aggregate(t=Sum("total_amount"))["t"] or 0

    return render(request, "staff_dashboard.html", {
        "device_progress": device_progress,
        "device_tags": DeviceTag.objects.filter(branch=branch),
        "activities": activities_page,
        "pending_activities": activities.filter(approved=False, requires_approval=True),
        "monthly_total": activities.filter(approved=True).aggregate(
            total=Sum("quantity")
        )["total"] or 0,
        "categories": RetailCategory.objects.all(),
        "check_logs": check_logs,
        "sim_inventory": sim_inventory,
        # wholesale
        "wholesale_devices": wholesale_devices,
        "wholesale_sales": wholesale_sales,
        "wholesale_inventory_value": wholesale_inventory_value,
        "wholesale_sales_total": wholesale_sales_total,
        "wholesale_director_total": wholesale_director_total,
    })


# ─────────────────────────────────────────
# FIXED customer_crm — director sees ALL customers,
# with filters: date range, source, search
# ─────────────────────────────────────────

@role_required("DIRECTOR")