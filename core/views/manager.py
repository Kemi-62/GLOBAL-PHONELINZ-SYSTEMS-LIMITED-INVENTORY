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
from .helpers import _get_director_phone

@role_required("DIRECTOR")
def request_stock(request):
    if request.method == "POST" and request.user.role == "RETAIL":
        StockRequest.objects.create(
            staff=request.user, branch=request.user.branch,
            product_name=request.POST.get("product_name"),
            quantity=request.POST.get("quantity"),
        )
        messages.success(request, "Stock request submitted.")
    return redirect("retail_dashboard")



@role_required("MANAGER")
def add_stock_to_safe(request):
    if request.method == "POST":
        try:
            branch = request.user.branch
            if request.POST.get("is_new_product") == "true":
                category = RetailCategory.objects.get(id=request.POST.get("category"))
                subcategory, _ = RetailSubCategory.objects.get_or_create(
                    category=category, name=request.POST.get("new_subcategory")
                )
                subsubcategory = None
                ssname = request.POST.get("new_subsubcategory")
                if ssname:
                    subsubcategory, _ = RetailSubSubCategory.objects.get_or_create(subcategory=subcategory, name=ssname)
                product = Product.objects.create(
                    subcategory=subcategory, subsubcategory=subsubcategory,
                    product_name=request.POST.get("product_name", ""),
                    model_name=request.POST.get("model_name"),
                    description=request.POST.get("description", ""),
                    imei_serial=request.POST.get("imei_serial", "") or None,
                    cost_price=float(request.POST.get("cost_price", 0)) or 0,
                    selling_price=float(request.POST.get("selling_price", 0)) or 0,
                )
            else:
                product = get_object_or_404(Product, id=request.POST.get("product"))

            quantity = int(request.POST.get("quantity", 0))
            with transaction.atomic():
                safe_stock, _ = BranchSafeStock.objects.get_or_create(branch=branch, product=product)
                safe_stock.quantity += quantity
                safe_stock.save()
                StockMovement.objects.create(
                    branch=branch, product=product, quantity=quantity,
                    movement_type="IN", performed_by=request.user,
                )
            messages.success(request, f"Added {quantity} × {product.model_name} to safe.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("manager_dashboard")



@role_required("MANAGER")
def release_stock(request):
    if request.method == "POST":
        branch = request.user.branch
        product = get_object_or_404(Product, id=request.POST.get("product"))
        staff = get_object_or_404(User, id=request.POST.get("staff"), branch=branch)
        quantity = int(request.POST.get("quantity", 0))

        safe_stock = get_object_or_404(BranchSafeStock, branch=branch, product=product)
        if quantity > safe_stock.quantity:
            messages.error(request, "Insufficient safe stock.")
            return redirect("manager_dashboard")

        with transaction.atomic():
            safe_stock.quantity -= quantity
            safe_stock.save()
            staff_stock, _ = StaffStock.objects.get_or_create(staff=staff, product=product)
            staff_stock.quantity += quantity
            staff_stock.save()
            StockMovement.objects.create(
                branch=branch, product=product, quantity=quantity,
                movement_type="OUT", performed_by=request.user,
            )
        messages.success(request, f"Released {quantity} × {product.model_name} to {staff.username}.")
    return redirect("manager_dashboard")



@role_required("MANAGER")
def approve_stock_request(request, request_id):
    stock_req = get_object_or_404(StockRequest, id=request_id, branch=request.user.branch)
    stock_req.status = "APPROVED"
    stock_req.save()
    messages.success(request, "Stock request approved.")
    return redirect("manager_dashboard")



@login_required
def upload_stock_csv(request):
    if request.user.role not in ["DIRECTOR", "MANAGER"]:
        return HttpResponseForbidden()
    redirect_to = "director_dashboard" if request.user.role == "DIRECTOR" else "manager_dashboard"
    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "No file uploaded.")
            return redirect(redirect_to)
        if not csv_file.name.endswith(".csv"):
            messages.error(request, "Please upload a .csv file only.")
            return redirect(redirect_to)
        if csv_file.size > 5 * 1024 * 1024:
            messages.error(request, "File too large. Maximum 5 MB.")
            return redirect(redirect_to)
        try:
            decoded = csv_file.read().decode("utf-8").splitlines()
            reader = csv.DictReader(decoded)
            count = 0
            errors = 0
            for row in reader:
                branch_id = row.get("branch_id")
                product_id = row.get("product_id")
                quantity = int(row.get("quantity", 0))
                if not product_id:
                    errors += 1
                    continue
                if branch_id:
                    branch_obj = Branch.objects.filter(id=branch_id).first()
                else:
                    branch_obj = request.user.branch
                if not branch_obj:
                    errors += 1
                    continue
                BranchSafeStock.objects.update_or_create(
                    branch=branch_obj,
                    product_id=product_id,
                    defaults={"quantity": quantity},
                )
                count += 1
            msg = f"Imported {count} stock items."
            if errors:
                msg += f" {errors} rows skipped (missing product_id or branch)."
            messages.success(request, msg)
        except Exception as e:
            messages.error(request, f"CSV error: {e}")
    return redirect(redirect_to)



@login_required
def stock_alerts(request):
    alerts = StockAlert.objects.filter(branch=request.user.branch, is_active=True)
    return render(request, "stock_alerts.html", {"alerts": alerts})


# ─────────────────────────────────────────
# DIRECTOR SAFE STOCK
# ─────────────────────────────────────────

@role_required("MANAGER")
def send_daily_report_whatsapp(request):
    if request.method == "POST":
        branch = request.user.branch
        today = timezone.now().date()

        sales = RetailSale.objects.filter(branch=branch, date=today)
        total_qty = sales.aggregate(t=Sum("quantity"))["t"] or 0
        total_rev = sales.aggregate(
            t=Sum(F("quantity") * F("selling_price"))
        )["t"] or 0
        mc_rev = MultiChoiceSale.objects.filter(branch=branch, date=today).aggregate(
            t=Sum("amount")
        )["t"] or 0
        expenses = Expense.objects.filter(branch=branch, date=today).aggregate(
            t=Sum("amount")
        )["t"] or 0
        pending_requests = StockRequest.objects.filter(
            branch=branch, status="PENDING"
        ).count()

        message = (
            f"📊 *DAILY BRANCH REPORT*\n"
            f"Branch: {branch.name}\n"
            f"Date: {today.strftime('%d %B %Y')}\n"
            f"Sent by: {request.user.username}\n\n"
            f"🛍️ Retail Sales: {total_qty} items\n"
            f"💰 Retail Revenue: ₦{total_rev:,.0f}\n"
            f"📺 MultiChoice: ₦{mc_rev:,.0f}\n"
            f"💸 Expenses: ₦{expenses:,.0f}\n"
            f"📦 Pending Stock Requests: {pending_requests}\n\n"
            f"Net (Retail - Expenses): ₦{(total_rev - expenses):,.0f}"
        )

        phone = _get_director_phone()
        sent = send_whatsapp(phone, message)

        if sent:
            messages.success(request, "Daily report sent to Director on WhatsApp.")
        else:
            messages.warning(
                request,
                "Could not send WhatsApp. Check DIRECTOR_WHATSAPP and CALLMEBOT_API_KEY in your .env file."
            )
    return redirect("manager_dashboard")


# ─────────────────────────────────────────
# SEND STOCK REQUEST VIA WHATSAPP
# ─────────────────────────────────────────


@role_required("MANAGER")
def send_stock_request_whatsapp(request):
    if request.method == "POST":
        branch = request.user.branch
        product_name = request.POST.get("product_name", "")
        quantity = request.POST.get("quantity", "")
        notes = request.POST.get("notes", "")

        # Save the stock request
        StockRequest.objects.create(
            staff=request.user,
            branch=branch,
            product_name=product_name,
            quantity=quantity,
        )

        message = (
            f"📦 *STOCK REQUEST*\n"
            f"Branch: {branch.name}\n"
            f"Requested by: {request.user.username}\n\n"
            f"Product: {product_name}\n"
            f"Quantity needed: {quantity}\n"
            f"Notes: {notes or 'None'}\n\n"
            f"Please approve in the ERP system."
        )

        phone = _get_director_phone()
        sent = send_whatsapp(phone, message)

        if sent:
            messages.success(request, f"Stock request for {product_name} sent to Director on WhatsApp.")
        else:
            messages.success(request, f"Stock request saved. WhatsApp notification could not be sent.")
    return redirect("manager_dashboard")


# ─────────────────────────────────────────
# DIRECTOR — ALL BRANCH STOCK VIEW
# ─────────────────────────────────────────


@role_required("MANAGER")
def manager_sales_today(request):
    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to", "")
    staff_flt  = request.GET.get("staff", "")
    export     = request.GET.get("export", "")
    today      = date.today()

    # Default to today if no filter
    if not date_from and not date_to:
        date_from = today.isoformat()
        date_to   = today.isoformat()

    sales = RetailSale.objects.filter(
        branch=request.user.branch
    ).select_related("product", "staff").order_by("-date", "-time")

    if date_from:
        sales = sales.filter(date__gte=date_from)
    if date_to:
        sales = sales.filter(date__lte=date_to)
    if staff_flt:
        sales = sales.filter(staff_id=staff_flt)

    total_revenue = sales.filter(is_voided=False).aggregate(
        t=Sum(F("quantity") * F("selling_price"))
    )["t"] or 0

    if export == "pdf":
        return _retail_sales_pdf(sales, request.user, date_from, date_to)

    paginator = Paginator(sales, 50)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "manager/sales_today.html", {
        "sales": page,
        "total_revenue": total_revenue,
        "today": today,
        "date_from": date_from,
        "date_to": date_to,
        "staff_flt": staff_flt,
        "retail_staff": User.objects.filter(branch=request.user.branch, role="RETAIL"),
    })

# ─────────────────────────────────────────
# FIXED director_release_stock
# Adds to existing stock, logs every release
# ─────────────────────────────────────────



# ─────────────────────────────────────────
# FIXED director_release_stock
# Adds to existing stock, logs every release
# ─────────────────────────────────────────


@role_required("MANAGER")
def manager_dashboard(request):
    today = date.today()
    branch = request.user.branch

    activities = ServiceActivity.objects.filter(
        branch=branch, date__year=today.year, date__month=today.month
    )
    targets = ServiceTarget.objects.filter(
        branch=branch, date__year=today.year, date__month=today.month
    )
    pending_approvals = ServiceActivity.objects.filter(
        branch=branch, requires_approval=True, approved=False
    )

    search_query = request.GET.get("search", "")
    if search_query:
        activities = activities.filter(staff__username__icontains=search_query)

    target_data = []
    for t in targets:
        achieved = activities.filter(
            service_type=t.service_type
        ).aggregate(total=Sum("quantity"))["total"] or 0
        pct = round((achieved / t.target_number) * 100, 2) if t.target_number else 0
        target_data.append({
            "service_type": t.service_type,
            "target_number": t.target_number,
            "achieved": achieved,
            "remaining": max(t.target_number - achieved, 0),
            "percentage": pct,
            "id": t.id,
        })

    safe_stocks = BranchSafeStock.objects.filter(
        branch=branch
    ).select_related("product")

    # Stock alerts
    low_stock_alerts = BranchSafeStock.objects.filter(
        branch=branch, quantity__lte=3
    ).select_related("product")
    out_of_stock_alerts = BranchSafeStock.objects.filter(
        branch=branch, quantity=0
    ).select_related("product")

    retail_sales_today = RetailSale.objects.filter(
        branch=branch, date=today, is_voided=False
    )
    total_retail_revenue = retail_sales_today.aggregate(
        total=Sum(F("quantity") * F("selling_price"))
    )["total"] or 0
    total_retail_quantity = retail_sales_today.aggregate(
        total=Sum("quantity")
    )["total"] or 0
    sales_per_staff = retail_sales_today.values(
        "staff__username"
    ).annotate(
        total_qty=Sum("quantity"),
        total_revenue=Sum(F("quantity") * F("selling_price"))
    )
    top_products = retail_sales_today.values(
        "product__model_name"
    ).annotate(total_qty=Sum("quantity")).order_by("-total_qty")[:5]

    multichoice_revenue = MultiChoiceSale.objects.filter(
        branch=branch, date=today
    ).aggregate(total=Sum("amount"))["total"] or 0

    retail_staff = User.objects.filter(branch=branch, role="RETAIL")
    telecom_staff = User.objects.filter(branch=branch, role="TELECOM")
    categories    = RetailCategory.objects.all()
    pending_stock_requests = StockRequest.objects.filter(
        branch=branch, status="PENDING"
    )
    expenses = Expense.objects.filter(branch=branch).order_by("-date")[:10]
    check_logs = CheckInOutLog.objects.filter(
        branch=branch
    ).order_by("-date", "-check_in_time")[:20]
    sim_inventory, _ = SimInventory.objects.get_or_create(branch=branch)
    sim_logs = SimInventoryLog.objects.filter(
        inventory=sim_inventory
    ).order_by("-date_created")[:15]
    today_movements = StockMovement.objects.filter(branch=branch, date=today)
    total_stock_out = today_movements.filter(
        movement_type="OUT"
    ).aggregate(total=Sum("quantity"))["total"] or 0

    return render(request, "manager_dashboard.html", {
        "target_data": target_data,
        "activities": activities,
        "pending_approvals": pending_approvals,
        "safe_stocks": safe_stocks,
        "categories": categories,
        "retail_staff": retail_staff,
        "telecom_staff": telecom_staff,
        "today_movements": today_movements,
        "total_stock_out": total_stock_out,
        "multichoice_revenue": multichoice_revenue,
        "total_retail_quantity": total_retail_quantity,
        "total_retail_revenue": total_retail_revenue,
        "sales_per_staff": sales_per_staff,
        "top_products": top_products,
        "search_query": search_query,
        "pending_stock_requests": pending_stock_requests,
        "expenses": expenses,
        "check_logs": check_logs,
        "sim_inventory": sim_inventory,
        "sim_logs": sim_logs,
        "low_stock_alerts": low_stock_alerts,
        "out_of_stock_alerts": out_of_stock_alerts,
        "device_tags": DeviceTag.objects.filter(branch=branch),
        "today": today,
    })

# ─────────────────────────────────────────
# WHOLESALE DEVICE CATALOG VIEWS (Telecom Staff)
# ─────────────────────────────────────────

