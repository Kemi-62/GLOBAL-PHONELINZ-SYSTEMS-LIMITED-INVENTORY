from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, F, Q, DecimalField, ExpressionWrapper
from django.core.paginator import Paginator
from django.utils import timezone
from decimal import Decimal
from datetime import date, time, timedelta
import math
import csv
import io

from .models import (
    User, Branch, DeviceTag, ServiceTarget, ServiceActivity,
    BranchSafeStock, StockMovement, Product, StaffStock,
    RetailSale, RetailCategory, RetailSubCategory, RetailSubSubCategory,
    MultiChoiceSale, MultiChoiceWeeklyReport, MultiChoiceBalance,
    Expense, StockRequest, Attendance, DirectorSafeStock,
    CheckInOutLog, SimInventory, SimInventoryLog,
    Customer, StockAlert, DeviceTagCommission, CommissionPayment
)
from .utils.decorators import role_required

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def attendance_status():
    now = timezone.localtime()
    t = now.time()
    wd = now.weekday()
    if wd < 5:   # Mon–Fri
        if time(7, 30) <= t <= time(8, 0):   return "ontime"
        if time(8, 1)  <= t <= time(8, 59):  return "late"
        if t >= time(9, 0):                   return "absent"
    if wd == 5:  # Saturday
        if time(9, 0) <= t <= time(9, 15):   return "ontime"
        if t > time(9, 15):                   return "late"
    return "early"


# ─────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────

ROLE_REDIRECTS = {
    "DIRECTOR":   "director_dashboard",
    "SUPERADMIN": "director_dashboard",
    "MANAGER":    "manager_dashboard",
    "RETAIL":     "retail_dashboard",
    "MULTICHOICE":"multichoice_dashboard",
    "TELECOM":    "staff_dashboard",
}

def _redirect_by_role(user):
    if user.is_superuser:
        return redirect("director_dashboard")
    return redirect(ROLE_REDIRECTS.get(getattr(user, "role", None), "login"))


def custom_login(request):
    if request.user.is_authenticated:
        return _redirect_by_role(request.user)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        if not username or not password:
            messages.error(request, "Username and password are required.")
            return render(request, "login.html")

        user = authenticate(request, username=username, password=password)
        if user:
            if getattr(user, "is_locked", False):
                messages.error(request, "This account is locked. Contact your director.")
                return render(request, "login.html")
            login(request, user)
            user.failed_login_count = 0
            user.save(update_fields=["failed_login_count"])
            return _redirect_by_role(user)
        else:
            # Increment failed attempts
            try:
                u = User.objects.get(username=username)
                u.failed_login_count = (u.failed_login_count or 0) + 1
                if u.failed_login_count >= 5:
                    u.is_locked = True
                    messages.error(request, "Too many failed attempts. Account locked.")
                else:
                    messages.error(request, f"Invalid credentials. {5 - u.failed_login_count} attempt(s) remaining.")
                u.save(update_fields=["failed_login_count", "is_locked"])
            except User.DoesNotExist:
                messages.error(request, "Invalid credentials.")

    return render(request, "login.html")


def user_logout(request):
    logout(request)
    messages.success(request, "Logged out successfully.")
    return redirect("login")


def csrf_failure(request, reason=""):
    messages.error(request, "Your session expired. Please log in again.")
    return redirect("login")


def admin_redirect(request):
    if not request.user.is_authenticated:
        return redirect("login")
    return _redirect_by_role(request.user)


# ─────────────────────────────────────────
# STAFF / TELECOM DASHBOARD
# ─────────────────────────────────────────

@role_required("TELECOM")
def staff_dashboard(request):
    today = date.today()
    branch = request.user.branch

    targets = ServiceTarget.objects.filter(branch=branch, date__year=today.year, date__month=today.month)
    activities = ServiceActivity.objects.filter(staff=request.user, date__year=today.year, date__month=today.month)

    if request.method == "POST":
        service_type = request.POST.get("service_type")
        quantity = int(request.POST.get("quantity") or 0)
        device_tag_id = request.POST.get("device_tag")
        device_tag = None
        if device_tag_id:
            device_tag = DeviceTag.objects.filter(id=device_tag_id).first()

        requires_approval = False
        if service_type == "SIM_REG":
            target = ServiceTarget.objects.filter(
                branch=branch, service_type="SIM_REG",
                device_tag=device_tag, date__year=today.year, date__month=today.month
            ).first()
            if target:
                achieved = ServiceActivity.objects.filter(
                    branch=branch, service_type="SIM_REG", device_tag=device_tag,
                    date__year=today.year, date__month=today.month, approved=True
                ).aggregate(total=Sum("quantity"))["total"] or 0
                if achieved >= target.target_number:
                    requires_approval = True

        with transaction.atomic():
            ServiceActivity.objects.create(
                branch=branch, staff=request.user, service_type=service_type,
                device_tag=device_tag, quantity=quantity,
                requires_approval=requires_approval, approved=not requires_approval,
            )
            if service_type in ["SIM_REG", "SIM_SWAP", "SIM_UPGRADE"]:
                try:
                    inv = SimInventory.objects.get(branch=branch)
                    inv.total_sold += quantity
                    inv.save()
                    SimInventoryLog.objects.create(
                        inventory=inv, transaction_type="SOLD", quantity=quantity,
                        description=f"{service_type}: {quantity} SIM by {request.user.username}",
                        created_by=request.user,
                    )
                except SimInventory.DoesNotExist:
                    pass

        messages.success(request, "Activity recorded.")
        return redirect("staff_dashboard")

    device_progress = []
    for target in targets.filter(service_type="SIM_REG"):
        achieved = activities.filter(service_type="SIM_REG", device_tag=target.device_tag, approved=True).aggregate(total=Sum("quantity"))["total"] or 0
        pct = round((achieved / target.target_number) * 100, 2) if target.target_number else 0
        device_progress.append({
            "device": target.device_tag.tag_name if target.device_tag else "Generic",
            "target": target.target_number, "achieved": achieved,
            "remaining": max(target.target_number - achieved, 0),
            "percentage": pct, "exceeded": achieved >= target.target_number,
        })

    check_logs = CheckInOutLog.objects.filter(staff=request.user).order_by("-date", "-check_in_time")[:20]

    return render(request, "staff_dashboard.html", {
        "device_progress": device_progress,
        "device_tags": DeviceTag.objects.filter(branch=branch),
        "activities": activities,
        "pending_activities": activities.filter(approved=False, requires_approval=True),
        "monthly_total": activities.filter(approved=True).aggregate(total=Sum("quantity"))["total"] or 0,
        "categories": RetailCategory.objects.all(),
        "check_logs": check_logs,
    })


# ─────────────────────────────────────────
# MANAGER DASHBOARD
# ─────────────────────────────────────────

@role_required("MANAGER")
def manager_dashboard(request):
    today = date.today()
    branch = request.user.branch

    activities = ServiceActivity.objects.filter(branch=branch, date__year=today.year, date__month=today.month)
    targets = ServiceTarget.objects.filter(branch=branch, date__year=today.year, date__month=today.month)
    pending_approvals = ServiceActivity.objects.filter(branch=branch, requires_approval=True, approved=False)

    # Search
    search_query = request.GET.get("search", "")
    if search_query:
        activities = activities.filter(staff__username__icontains=search_query)

    # Target progress
    target_data = []
    for t in targets:
        achieved = activities.filter(service_type=t.service_type).aggregate(total=Sum("quantity"))["total"] or 0
        pct = round((achieved / t.target_number) * 100, 2) if t.target_number else 0
        target_data.append({
            "service_type": t.service_type, "target_number": t.target_number,
            "achieved": achieved, "remaining": max(t.target_number - achieved, 0), "percentage": pct,
        })

    # Stock
    safe_stocks = BranchSafeStock.objects.filter(branch=branch).select_related("product")
    today_movements = StockMovement.objects.filter(branch=branch, date=today)
    total_stock_out = today_movements.filter(movement_type="OUT").aggregate(total=Sum("quantity"))["total"] or 0

    # Retail sales
    product_filter = request.GET.get("product")
    staff_filter = request.GET.get("staff")
    retail_sales_today = RetailSale.objects.filter(branch=branch, date=today)
    if product_filter:
        retail_sales_today = retail_sales_today.filter(product_id=product_filter)
    if staff_filter:
        retail_sales_today = retail_sales_today.filter(staff_id=staff_filter)

    total_retail_revenue = retail_sales_today.aggregate(
        total=Sum(F("quantity") * F("selling_price"))
    )["total"] or 0
    total_retail_quantity = retail_sales_today.aggregate(total=Sum("quantity"))["total"] or 0
    sales_per_staff = retail_sales_today.values("staff__username").annotate(
        total_qty=Sum("quantity"), total_revenue=Sum(F("quantity") * F("selling_price"))
    )
    top_products = retail_sales_today.values("product__model_name").annotate(
        total_qty=Sum("quantity")
    ).order_by("-total_qty")[:5]

    # MultiChoice
    multichoice_revenue = MultiChoiceSale.objects.filter(branch=branch, date=today).aggregate(
        total=Sum("amount")
    )["total"] or 0

    # Misc
    retail_staff = User.objects.filter(branch=branch, role="RETAIL")
    categories = RetailCategory.objects.all()
    pending_stock_requests = StockRequest.objects.filter(branch=branch, status="PENDING")
    expenses = Expense.objects.filter(branch=branch).order_by("-date")[:10]
    check_logs = CheckInOutLog.objects.filter(branch=branch).order_by("-date", "-check_in_time")[:20]
    sim_inventory, _ = SimInventory.objects.get_or_create(branch=branch)
    sim_logs = SimInventoryLog.objects.filter(inventory=sim_inventory).order_by("-date_created")[:15]

    return render(request, "manager_dashboard.html", {
        "target_data": target_data,
        "activities": activities,
        "pending_approvals": pending_approvals,
        "safe_stocks": safe_stocks,
        "categories": categories,
        "retail_staff": retail_staff,
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
    })


@login_required
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
def daily_sales_report(request):
    today = timezone.now().date()
    daily_sales = RetailSale.objects.filter(date=today).select_related("product", "branch", "staff").order_by("branch__name", "-id")
    branch_sales_summary = {}
    total_qty, total_revenue = 0, Decimal(0)
    for s in daily_sales:
        amt = Decimal(s.quantity) * s.selling_price
        s.total_amount = amt
        bk = s.branch.name
        if bk not in branch_sales_summary:
            branch_sales_summary[bk] = {"sales": [], "total_qty": 0, "total_revenue": Decimal(0)}
        branch_sales_summary[bk]["sales"].append({
            "product": s.product.model_name, "quantity": s.quantity,
            "price": s.selling_price, "amount": amt, "staff": s.staff.username,
        })
        branch_sales_summary[bk]["total_qty"] += s.quantity
        branch_sales_summary[bk]["total_revenue"] += amt
        total_qty += s.quantity
        total_revenue += amt

    return render(request, "daily_sales_report.html", {
        "branch_sales_summary": branch_sales_summary,
        "total_qty": total_qty, "total_revenue": total_revenue,
        "categories": RetailCategory.objects.all(),
        "all_branches": Branch.objects.all(),
        "today": today,
    })


# ─────────────────────────────────────────
# RETAIL DASHBOARD
# ─────────────────────────────────────────

@role_required("RETAIL")
def retail_dashboard(request):
    staff = request.user
    staff_stock = StaffStock.objects.filter(staff=staff).select_related("product")
    sales_qs = RetailSale.objects.filter(staff=staff).select_related("product").order_by("-date", "-id")

    paginator = Paginator(sales_qs, 30)
    sales_history = paginator.get_page(request.GET.get("page"))
    for s in sales_history:
        s.total_revenue = Decimal(s.quantity) * s.selling_price

    check_logs = CheckInOutLog.objects.filter(staff=staff).order_by("-date", "-check_in_time")[:20]

    return render(request, "retail_dashboard.html", {
        "staff_stock": staff_stock,
        "categories": RetailCategory.objects.all(),
        "check_logs": check_logs,
        "sales_history": sales_history,
    })


@role_required("RETAIL")
def record_retail_sale(request):
    if request.method == "POST":
        product_id = request.POST.get("product")
        quantity = int(request.POST.get("quantity", 0))
        selling_price = Decimal(request.POST.get("selling_price", 0))
        payment_method = request.POST.get("payment_method", "CASH")

        product = get_object_or_404(Product, id=product_id)

        try:
            staff_stock = StaffStock.objects.get(staff=request.user, product=product)
        except StaffStock.DoesNotExist:
            messages.error(request, "You do not have this product in stock.")
            return redirect("retail_dashboard")

        if quantity > staff_stock.quantity:
            messages.error(request, f"Insufficient stock. You have {staff_stock.quantity} unit(s).")
            return redirect("retail_dashboard")

        with transaction.atomic():
            staff_stock.quantity -= quantity
            staff_stock.save()
            RetailSale.objects.create(
                staff=request.user, branch=request.user.branch,
                product=product, quantity=quantity,
                selling_price=selling_price, payment_method=payment_method,
            )
        messages.success(request, "Sale recorded successfully.")
    return redirect("retail_dashboard")


@login_required
def request_stock(request):
    if request.method == "POST" and request.user.role == "RETAIL":
        StockRequest.objects.create(
            staff=request.user, branch=request.user.branch,
            product_name=request.POST.get("product_name"),
            quantity=request.POST.get("quantity"),
        )
        messages.success(request, "Stock request submitted.")
    return redirect("retail_dashboard")


@login_required
def staff_create_product(request):
    if request.method == "POST" and request.user.role == "RETAIL":
        try:
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
                imei_serial=request.POST.get("imei", ""),
                cost_price=0,
                selling_price=float(request.POST.get("selling_price", 0)) or 0,
            )
            qty = int(request.POST.get("quantity", 1))
            with transaction.atomic():
                stock, _ = StaffStock.objects.get_or_create(staff=request.user, product=product)
                stock.quantity += qty
                stock.save()
            messages.success(request, f"{product.model_name} created and added to your stock.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("retail_dashboard")


@login_required
def edit_staff_stock_price(request, stock_id):
    if request.user.role != "RETAIL":
        return HttpResponseForbidden()
    stock = get_object_or_404(StaffStock, id=stock_id, staff=request.user)
    new_price = request.GET.get("price")
    if new_price:
        stock.product.selling_price = float(new_price)
        stock.product.save()
        messages.success(request, f"Price updated to ₦{new_price}.")
    return redirect("retail_dashboard")


@login_required
def edit_product_price(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    new_price = request.GET.get("price")
    if new_price:
        product.selling_price = float(new_price)
        product.save()
        messages.success(request, f"Price updated to ₦{new_price}.")
    return redirect("product_catalog")


@login_required
def product_catalog(request):
    if request.user.role != "RETAIL":
        return HttpResponseForbidden()
    return render(request, "retail_catalog.html", {
        "products": Product.objects.all(),
        "categories": RetailCategory.objects.all(),
    })


# ─────────────────────────────────────────
# MULTICHOICE DASHBOARD
# ─────────────────────────────────────────

@role_required("MULTICHOICE")
def multichoice_dashboard(request):
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    weekly_report = MultiChoiceWeeklyReport.objects.filter(staff=request.user, week_start_date=week_start).first()

    today_sales = MultiChoiceSale.objects.filter(staff=request.user, date=today).order_by("-time")

    search_query = request.GET.get("search", "").strip()
    selected_month = request.GET.get("month", today.strftime("%Y-%m"))
    all_sales = MultiChoiceSale.objects.filter(staff=request.user).order_by("-date", "-time")
    if selected_month:
        yr, mo = selected_month.split("-")
        all_sales = all_sales.filter(date__year=yr, date__month=mo)
    if search_query:
        all_sales = all_sales.filter(
            Q(customer_name__icontains=search_query) |
            Q(customer_phone__icontains=search_query) |
            Q(package_type__icontains=search_query)
        )

    balance_history = weekly_report.balance_history.all() if weekly_report else None
    weekly_total_sales = weekly_report.total_subscriptions if weekly_report and weekly_report.is_closed else 0

    return render(request, "multichoice_dashboard.html", {
        "today_sales": today_sales,
        "all_sales": all_sales,
        "total_today": today_sales.aggregate(total=Sum("amount"))["total"] or 0,
        "categories": RetailCategory.objects.all(),
        "weekly_report": weekly_report,
        "is_monday": today.weekday() == 0,
        "is_saturday": today.weekday() == 5,
        "weekly_total_sales": weekly_total_sales,
        "balance_history": balance_history,
        "check_logs": CheckInOutLog.objects.filter(staff=request.user).order_by("-date", "-check_in_time")[:20],
        "search_query": search_query,
        "selected_month": selected_month,
    })

@login_required
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
def record_multichoice_sale(request):
    if request.method == "POST":
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
        weekly_report, _ = MultiChoiceWeeklyReport.objects.get_or_create(
            staff=request.user, branch=request.user.branch, week_start_date=week_start
        )
        cost_price = Decimal(request.POST.get("cost_price", 0) or 0)
        amount = Decimal(request.POST.get("amount", 0) or 0)

        prev = MultiChoiceBalance.objects.filter(weekly_report=weekly_report).order_by("-date", "-time").first()
        starting = prev.balance_after_sale if prev and prev.balance_after_sale is not None else (
            weekly_report.opening_balance + weekly_report.additional_funds
        )
        balance_after = starting - cost_price

        with transaction.atomic():
            MultiChoiceSale.objects.create(
                staff=request.user, branch=request.user.branch,
                customer_name=request.POST.get("customer_name"),
                customer_phone=request.POST.get("customer_phone", ""),
                service_type=request.POST.get("service_type"),
                package_type=request.POST.get("package_type"),
                transaction_type=request.POST.get("transaction_type"),
                cost_price=cost_price, amount=amount,
            )
            MultiChoiceBalance.objects.create(
                weekly_report=weekly_report,
                balance_amount=starting,
                balance_after_sale=balance_after,
                sale_cost_price=cost_price,
                notes=f"Subscription: {request.POST.get('package_type')}",
            )
            weekly_report.total_subscriptions = (weekly_report.total_subscriptions or 0) + amount
            weekly_report.save(update_fields=["total_subscriptions"])
        messages.success(request, "Sale recorded.")
    return redirect("multichoice_dashboard")


@role_required("MULTICHOICE")
def record_balance(request):
    if request.method == "POST":
        weekly_report = MultiChoiceWeeklyReport.objects.filter(
            staff=request.user, branch=request.user.branch, is_closed=False
        ).first()
        balance = request.POST.get("current_balance")
        if weekly_report and balance:
            MultiChoiceBalance.objects.create(
                weekly_report=weekly_report,
                balance_amount=balance,
                notes=request.POST.get("notes", ""),
            )
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
        weekly_report, _ = MultiChoiceWeeklyReport.objects.get_or_create(
            staff=request.user, branch=request.user.branch, week_start_date=week_start
        )
        balance_record = MultiChoiceBalance.objects.create(
            weekly_report=weekly_report, balance_amount=balance,
            notes=request.POST.get("notes", ""),
        )
        prev = MultiChoiceBalance.objects.filter(
            weekly_report__staff=request.user, date__lt=today
        ).order_by("-date", "-time").first()
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

@role_required("DIRECTOR")
def director_safe_stock(request):
    stocks = DirectorSafeStock.objects.all().order_by("-date_added")
    return render(request, "director/director_safe.html", {
        "stocks": stocks,
        "products": Product.objects.all(),
        "categories": RetailCategory.objects.all(),
        "total_quantity": sum(s.quantity for s in stocks),
        "total_value": sum(s.total_value for s in stocks),
    })


@role_required("DIRECTOR")
def add_director_stock(request):
    if request.method == "POST":
        try:
            product = get_object_or_404(Product, id=request.POST.get("product_id"))
            DirectorSafeStock.objects.create(
                product=product, quantity=int(request.POST.get("quantity")),
                notes=request.POST.get("notes", ""),
            )
            messages.success(request, f"Added to director safe.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("director_safe_stock")


@role_required("DIRECTOR")
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
def attendance_history(request):
    qs = Attendance.objects.filter(user=request.user).order_by("-date")
    paginator = Paginator(qs, 30)
    records = paginator.get_page(request.GET.get("page"))
    return render(request, "staff/attendance_history.html", {"records": records})


@role_required("DIRECTOR")
def manage_branch_locations(request):
    if request.method == "POST":
        try:
            branch = get_object_or_404(Branch, id=request.POST.get("branch_id"))
            branch.latitude = float(request.POST.get("latitude"))
            branch.longitude = float(request.POST.get("longitude"))
            branch.allowed_radius = int(request.POST.get("allowed_radius", 100))
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
def record_expense(request):
    if request.method == "POST":
        Expense.objects.create(
            branch=request.user.branch,
            category=request.POST.get("category"),
            amount=request.POST.get("amount"),
            description=request.POST.get("description", ""),
        )
        messages.success(request, "Expense recorded.")
    return redirect("manager_dashboard")


@login_required
def add_category(request):
    if request.method == "POST" and request.user.role in ["MANAGER", "SUPERADMIN"]:
        name = request.POST.get("name", "").strip()
        if name:
            RetailCategory.objects.get_or_create(name=name)
            messages.success(request, f"Category '{name}' added.")
    return redirect(request.META.get("HTTP_REFERER", "manager_dashboard"))


# ─────────────────────────────────────────
# REPORTS / PDF
# ─────────────────────────────────────────

@login_required
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

    def draw_line(text, size=10, bold=False):
        nonlocal y
        p.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        p.drawString(50, y, text)
        y -= size + 4
        if y < 80:
            p.showPage()
            y = height - 50

    draw_line(f"DAILY BRANCH REPORT: {branch.name.upper()}", 16, bold=True)
    draw_line(f"Date: {today.strftime('%d-%b-%Y')}", 11)
    y -= 10

    sales = RetailSale.objects.filter(branch=branch, date=today).select_related("product", "staff")
    total_rev = sum(Decimal(s.quantity) * s.selling_price for s in sales)
    draw_line("RETAIL SALES SUMMARY", 12, bold=True)
    draw_line(f"  Items Sold: {sum(s.quantity for s in sales)}  |  Revenue: ₦{total_rev:,.2f}")
    y -= 8
    for s in sales[:20]:
        amt = Decimal(s.quantity) * s.selling_price
        draw_line(f"  {s.product.model_name[:28]:<30} x{s.quantity}  ₦{amt:,.0f}  ({s.staff.username})", 8)

    y -= 10
    exps = Expense.objects.filter(branch=branch, date=today)
    total_exp = sum(e.amount for e in exps)
    mc_rev = MultiChoiceSale.objects.filter(branch=branch, date=today).aggregate(t=Sum("amount"))["t"] or 0
    gross = sum((Decimal(s.selling_price) - Decimal(s.product.cost_price or 0)) * s.quantity for s in sales)

    draw_line("FINANCIAL SUMMARY", 12, bold=True)
    draw_line(f"  MultiChoice Revenue: ₦{mc_rev:,.2f}")
    draw_line(f"  Gross Profit (Retail): ₦{gross:,.2f}")
    draw_line(f"  Total Expenses: ₦{total_exp:,.2f}")
    draw_line(f"  Net Profit: ₦{gross - total_exp:,.2f}", bold=True)

    p.showPage()
    p.save()
    return response


@role_required("MANAGER")
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
def customer_crm(request):
    customers = Customer.objects.filter(branch=request.user.branch).order_by("-last_purchase")
    search = request.GET.get("search", "")
    if search:
        customers = customers.filter(Q(name__icontains=search) | Q(phone_number__icontains=search))
    paginator = Paginator(customers, 30)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "customer_crm.html", {
        "customers": page, "total_customers": customers.count(), "search": search,
    })


def _compress_image(image_file, max_size_kb=200, max_dimension=800):
    """Compress uploaded image to reduce storage size."""
    try:
        img = _PILImage.open(image_file)
        # Convert RGBA to RGB if needed
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        # Resize if too large
        w, h = img.size
        if w > max_dimension or h > max_dimension:
            img.thumbnail((max_dimension, max_dimension), _PILImage.LANCZOS)
        # Save compressed
        output = _io.BytesIO()
        quality = 85
        while True:
            output.seek(0)
            output.truncate()
            img.save(output, format="JPEG", quality=quality, optimize=True)
            size_kb = output.tell() / 1024
            if size_kb <= max_size_kb or quality <= 40:
                break
            quality -= 10
        output.seek(0)
        from django.core.files.uploadedfile import InMemoryUploadedFile
        return InMemoryUploadedFile(
            output, "ImageField",
            image_file.name.rsplit(".", 1)[0] + ".jpg",
            "image/jpeg", output.getbuffer().nbytes, None
        )
    except Exception:
        return image_file  # fallback to original if PIL fails


@login_required
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


@login_required


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
def add_device_commission(request):
    device_tags = DeviceTag.objects.filter(branch=request.user.branch)
    if request.method == "POST":
        DeviceTagCommission.objects.update_or_create(
            branch=request.user.branch,
            device_tag_id=request.POST.get("device_tag_id"),
            month_year=request.POST.get("month_year"),
            defaults={"commission_amount": request.POST.get("commission_amount"), "created_by": request.user},
        )
        messages.success(request, "Commission recorded.")
        return redirect("manager_dashboard")
    return render(request, "device_commission_form.html", {"device_tags": device_tags})


@role_required("DIRECTOR")
def commission_tracking(request):
    commissions = CommissionPayment.objects.filter(
        branch=request.user.branch
    ).select_related("staff").order_by("-date_detected")
    staff_filter = request.GET.get("staff")
    if staff_filter:
        commissions = commissions.filter(staff_id=staff_filter)
    return render(request, "commission_tracking.html", {
        "commissions": commissions,
        "total_commissions": commissions.aggregate(total=Sum("commission_detected"))["total"] or 0,
        "staff_list": User.objects.filter(branch=request.user.branch, role="MULTICHOICE"),
        "selected_staff": staff_filter,
    })


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
def upload_retail_csv(request):
    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "No file uploaded.")
            return redirect("retail_dashboard")
        if not csv_file.name.endswith(".csv"):
            messages.error(request, "Please upload a .csv file only.")
            return redirect("retail_dashboard")
        if csv_file.size > 5 * 1024 * 1024:
            messages.error(request, "File too large. Maximum 5MB.")
            return redirect("retail_dashboard")
        try:
            decoded = csv_file.read().decode("utf-8").splitlines()
            reader = csv.DictReader(decoded)
            count = 0
            errors = []
            for i, row in enumerate(reader, start=2):
                try:
                    model_name = (row.get("model_name") or "").strip()
                    if not model_name:
                        errors.append(f"Row {i}: missing model_name")
                        continue

                    category_name = (row.get("category") or "General").strip()
                    subcategory_name = (row.get("subcategory") or "General").strip()
                    selling_price = float(row.get("selling_price") or 0)
                    quantity = int(row.get("quantity") or 1)
                    imei = (row.get("imei_serial") or "").strip() or None

                    category, _ = RetailCategory.objects.get_or_create(name=category_name)
                    subcategory, _ = RetailSubCategory.objects.get_or_create(
                        category=category, name=subcategory_name
                    )

                    # Find existing product by model_name or create new
                    product, created = Product.objects.get_or_create(
                        model_name=model_name,
                        defaults={
                            "subcategory": subcategory,
                            "product_name": row.get("product_name") or model_name,
                            "description": row.get("description") or "",
                            "imei_serial": imei,
                            "cost_price": float(row.get("cost_price") or 0),
                            "selling_price": selling_price,
                        }
                    )
                    if not created:
                        # Update price if provided
                        if selling_price:
                            product.selling_price = selling_price
                            product.save(update_fields=["selling_price"])

                    with transaction.atomic():
                        stock, _ = StaffStock.objects.get_or_create(
                            staff=request.user, product=product
                        )
                        stock.quantity += quantity
                        stock.save()
                    count += 1
                except Exception as e:
                    errors.append(f"Row {i}: {e}")

            msg = f"Uploaded {count} product(s) to your catalog."
            if errors:
                msg += f" {len(errors)} row(s) had issues: {'; '.join(errors[:3])}"
            messages.success(request, msg)
        except Exception as e:
            messages.error(request, f"CSV error: {e}")
    return redirect("retail_dashboard")


# ─────────────────────────────────────────
# MANAGER BULK CSV UPLOAD (to branch safe)
# ─────────────────────────────────────────

@role_required("MANAGER")
def upload_manager_csv(request):
    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "No file uploaded.")
            return redirect("manager_dashboard")
        if not csv_file.name.endswith(".csv"):
            messages.error(request, "Please upload a .csv file only.")
            return redirect("manager_dashboard")
        if csv_file.size > 5 * 1024 * 1024:
            messages.error(request, "File too large. Maximum 5MB.")
            return redirect("manager_dashboard")
        try:
            branch = request.user.branch
            decoded = csv_file.read().decode("utf-8").splitlines()
            reader = csv.DictReader(decoded)
            count = 0
            errors = []
            for i, row in enumerate(reader, start=2):
                try:
                    model_name = (row.get("model_name") or "").strip()
                    if not model_name:
                        errors.append(f"Row {i}: missing model_name")
                        continue

                    category_name = (row.get("category") or "General").strip()
                    subcategory_name = (row.get("subcategory") or "General").strip()
                    quantity = int(row.get("quantity") or 0)
                    cost_price = float(row.get("cost_price") or 0)
                    selling_price = float(row.get("selling_price") or 0)
                    imei = (row.get("imei_serial") or "").strip() or None

                    category, _ = RetailCategory.objects.get_or_create(name=category_name)
                    subcategory, _ = RetailSubCategory.objects.get_or_create(
                        category=category, name=subcategory_name
                    )

                    product, created = Product.objects.get_or_create(
                        model_name=model_name,
                        defaults={
                            "subcategory": subcategory,
                            "product_name": row.get("product_name") or model_name,
                            "description": row.get("description") or "",
                            "imei_serial": imei,
                            "cost_price": cost_price,
                            "selling_price": selling_price,
                        }
                    )
                    if not created and (cost_price or selling_price):
                        if cost_price:
                            product.cost_price = cost_price
                        if selling_price:
                            product.selling_price = selling_price
                        product.save(update_fields=["cost_price", "selling_price"])

                    with transaction.atomic():
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
                    count += 1
                except Exception as e:
                    errors.append(f"Row {i}: {e}")

            msg = f"Imported {count} product(s) to branch safe."
            if errors:
                msg += f" {len(errors)} row(s) skipped: {'; '.join(errors[:3])}"
            messages.success(request, msg)
        except Exception as e:
            messages.error(request, f"CSV error: {e}")
    return redirect("manager_dashboard")


# ─────────────────────────────────────────
# DIRECTOR BULK CSV UPLOAD (to director safe)
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def upload_director_csv(request):
    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "No file uploaded.")
            return redirect("director_safe_stock")
        if not csv_file.name.endswith(".csv"):
            messages.error(request, "Please upload a .csv file only.")
            return redirect("director_safe_stock")
        if csv_file.size > 5 * 1024 * 1024:
            messages.error(request, "File too large. Maximum 5MB.")
            return redirect("director_safe_stock")
        try:
            decoded = csv_file.read().decode("utf-8").splitlines()
            reader = csv.DictReader(decoded)
            count = 0
            errors = []
            for i, row in enumerate(reader, start=2):
                try:
                    model_name = (row.get("model_name") or "").strip()
                    if not model_name:
                        errors.append(f"Row {i}: missing model_name")
                        continue

                    category_name = (row.get("category") or "General").strip()
                    subcategory_name = (row.get("subcategory") or "General").strip()
                    quantity = int(row.get("quantity") or 0)
                    cost_price = float(row.get("cost_price") or 0)
                    selling_price = float(row.get("selling_price") or 0)
                    imei = (row.get("imei_serial") or "").strip() or None

                    category, _ = RetailCategory.objects.get_or_create(name=category_name)
                    subcategory, _ = RetailSubCategory.objects.get_or_create(
                        category=category, name=subcategory_name
                    )

                    product, created = Product.objects.get_or_create(
                        model_name=model_name,
                        defaults={
                            "subcategory": subcategory,
                            "product_name": row.get("product_name") or model_name,
                            "description": row.get("description") or "",
                            "imei_serial": imei,
                            "cost_price": cost_price,
                            "selling_price": selling_price,
                        }
                    )
                    if not created and (cost_price or selling_price):
                        if cost_price:
                            product.cost_price = cost_price
                        if selling_price:
                            product.selling_price = selling_price
                        product.save(update_fields=["cost_price", "selling_price"])

                    # Update or create director safe stock - just add to quantity
                    with transaction.atomic():
                        existing = DirectorSafeStock.objects.filter(product=product).first()
                        if existing:
                            existing.quantity += quantity
                            existing.save()
                        else:
                            DirectorSafeStock.objects.create(
                                product=product, quantity=quantity,
                                notes=f"Bulk uploaded"
                            )
                    count += 1
                except Exception as e:
                    errors.append(f"Row {i}: {e}")

            msg = f"Imported {count} product(s) to director safe."
            if errors:
                msg += f" {len(errors)} row(s) skipped: {'; '.join(errors[:3])}"
            messages.success(request, msg)
        except Exception as e:
            messages.error(request, f"CSV error: {e}")
    return redirect("director_safe_stock")


# ─────────────────────────────────────────
# DIRECTOR RELEASE STOCK TO BRANCH/STAFF
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def director_release_stock(request):
    if request.method == "POST":
        product_id = request.POST.get("product_id")
        quantity = int(request.POST.get("quantity", 0))
        release_type = request.POST.get("release_type")  # "branch_safe" or "staff"
        branch_id = request.POST.get("branch_id")
        staff_id = request.POST.get("staff_id")
        selling_price = request.POST.get("selling_price")

        director_stock = get_object_or_404(DirectorSafeStock, product_id=product_id)

        if quantity <= 0:
            messages.error(request, "Quantity must be greater than 0.")
            return redirect("director_safe_stock")

        if quantity > director_stock.quantity:
            messages.error(request, f"Only {director_stock.quantity} unit(s) available in director safe.")
            return redirect("director_safe_stock")

        with transaction.atomic():
            director_stock.quantity -= quantity
            if director_stock.quantity == 0:
                director_stock.delete()
            else:
                director_stock.save()

            if release_type == "sale":
                # Direct sale — just deduct from safe, log it
                StockMovement.objects.create(
                    branch=Branch.objects.filter(id=branch_id).first() if branch_id else None,
                    product_id=product_id,
                    quantity=quantity,
                    movement_type="OUT",
                    performed_by=request.user,
                )
                messages.success(request, f"Recorded sale of {quantity} unit(s) from director safe.")

            elif release_type == "branch_safe":
                branch = get_object_or_404(Branch, id=branch_id)
                safe_stock, _ = BranchSafeStock.objects.get_or_create(
                    branch=branch, product_id=product_id
                )
                safe_stock.quantity += quantity
                safe_stock.save()
                StockMovement.objects.create(
                    branch=branch, product_id=product_id,
                    quantity=quantity, movement_type="IN",
                    performed_by=request.user,
                )
                messages.success(request, f"Released {quantity} unit(s) to {branch.name} safe.")

            elif release_type == "staff":
                staff = get_object_or_404(User, id=staff_id)
                staff_stock, _ = StaffStock.objects.get_or_create(
                    staff=staff, product_id=product_id
                )
                staff_stock.quantity += quantity
                staff_stock.save()
                messages.success(request, f"Released {quantity} unit(s) directly to {staff.username}.")

    return redirect("director_safe_stock")
# ─────────────────────────────────────────
# FIXED STAFF CHECKOUT — gets staff_id from POST not URL
# ──────────────────────────────────────

# STOCK MOVEMENT LOG VIEW (Manager)
# ─────────────────────────────────────────
@role_required("MANAGER")
def stock_movement_log(request):
    branch = request.user.branch
    movements = StockMovement.objects.filter(
        branch=branch
    ).select_related("product", "performed_by").order_by("-date", "-time")

    # Filters
    movement_type = request.GET.get("type", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")

    if movement_type:
        movements = movements.filter(movement_type=movement_type)
    if date_from:
        movements = movements.filter(date__gte=date_from)
    if date_to:
        movements = movements.filter(date__lte=date_to)

    paginator = Paginator(movements, 50)
    page = paginator.get_page(request.GET.get("page"))

    # Totals
    total_in = movements.filter(movement_type="IN").aggregate(t=Sum("quantity"))["t"] or 0
    total_out = movements.filter(movement_type="OUT").aggregate(t=Sum("quantity"))["t"] or 0

    return render(request, "manager/stock_log.html", {
        "movements": page,
        "total_in": total_in,
        "total_out": total_out,
        "selected_type": movement_type,
        "date_from": date_from,
        "date_to": date_to,
    })


# ─────────────────────────────────────────
# SEND DAILY REPORT TO DIRECTOR VIA WHATSAPP
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

@role_required("DIRECTOR")
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
import io
from datetime import date, timedelta
from decimal import Decimal

# ─────────────────────────────────────────
# FIX: start_weekly_report — handle empty decimal fields
# ─────────────────────────────────────────

@login_required
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
def void_sale(request, sale_id):
    from core.models import AuditLog, Notification
    sale = get_object_or_404(RetailSale, id=sale_id, branch=request.user.branch)

    if getattr(sale, 'is_voided', False):
        messages.warning(request, "This sale is already voided.")
        return redirect("manager_dashboard")

    if request.method == "POST":
        void_reason = request.POST.get("void_reason", "No reason provided")
        with transaction.atomic():
            # Mark sale as voided
            sale.is_voided = True
            sale.void_reason = void_reason
            sale.voided_by = request.user
            sale.voided_at = timezone.now()
            sale.save()

            # Return stock to staff
            staff_stock, _ = StaffStock.objects.get_or_create(
                staff=sale.staff, product=sale.product
            )
            staff_stock.quantity += sale.quantity
            staff_stock.save()

            # Audit log
            try:
                AuditLog.objects.create(
                    user=request.user,
                    action='VOID',
                    model_name='RetailSale',
                    object_id=sale.id,
                    description=f"Voided sale of {sale.quantity}x {sale.product.model_name} by {sale.staff.username}. Reason: {void_reason}",
                )
            except Exception:
                pass

            # Notify director
            try:
                for director in User.objects.filter(role='DIRECTOR'):
                    Notification.objects.create(
                        recipient=director,
                        notif_type='VOID',
                        title=f'Sale voided at {sale.branch.name}',
                        message=f'{request.user.username} voided a sale of {sale.quantity}x {sale.product.model_name}. Reason: {void_reason}',
                        link='/manager/',
                    )
            except Exception:
                pass

        messages.success(request, f"Sale voided. {sale.quantity} unit(s) of {sale.product.model_name} returned to {sale.staff.username}.")
    return redirect("manager_dashboard")


# ─────────────────────────────────────────
# NOTIFICATIONS VIEW
# ─────────────────────────────────────────

@login_required
def notifications_view(request):
    from core.models import Notification
    notifs = Notification.objects.filter(recipient=request.user).order_by('-created_at')[:50]
    # Mark all as read
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return render(request, "notifications.html", {"notifications": notifs})


@login_required
def notification_count(request):
    from core.models import Notification
    count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return JsonResponse({"count": count})


# ─────────────────────────────────────────
# SUPPLIER MANAGEMENT (Director/Manager)
# ─────────────────────────────────────────

@login_required
def supplier_list(request):
    if request.user.role not in ['DIRECTOR', 'MANAGER']:
        return HttpResponseForbidden()
    from core.models import Supplier
    suppliers = Supplier.objects.all().order_by('name')
    return render(request, "suppliers/supplier_list.html", {"suppliers": suppliers})


@login_required
def supplier_create(request):
    if request.user.role not in ['DIRECTOR', 'MANAGER']:
        return HttpResponseForbidden()
    from core.models import Supplier
    if request.method == "POST":
        Supplier.objects.create(
            name=request.POST.get("name", ""),
            phone=request.POST.get("phone", ""),
            email=request.POST.get("email", ""),
            address=request.POST.get("address", ""),
            notes=request.POST.get("notes", ""),
        )
        messages.success(request, "Supplier added.")
        return redirect("supplier_list")
    return render(request, "suppliers/supplier_form.html")


@login_required
def purchase_order_list(request):
    if request.user.role not in ['DIRECTOR', 'MANAGER']:
        return HttpResponseForbidden()
    from core.models import PurchaseOrder
    orders = PurchaseOrder.objects.select_related('supplier', 'branch', 'ordered_by').order_by('-date_ordered')
    if request.user.role == 'MANAGER':
        orders = orders.filter(branch=request.user.branch)
    return render(request, "suppliers/po_list.html", {"orders": orders})


@login_required
def purchase_order_create(request):
    if request.user.role not in ['DIRECTOR', 'MANAGER']:
        return HttpResponseForbidden()
    from core.models import Supplier, PurchaseOrder, PurchaseOrderItem
    if request.method == "POST":
        supplier_id = request.POST.get("supplier")
        notes = request.POST.get("notes", "")
        branch = request.user.branch

        product_ids = request.POST.getlist("product_id")
        quantities  = request.POST.getlist("quantity")
        unit_costs  = request.POST.getlist("unit_cost")

        if not product_ids:
            messages.error(request, "Add at least one product to the order.")
            return redirect("purchase_order_create")

        with transaction.atomic():
            po = PurchaseOrder.objects.create(
                supplier_id=supplier_id,
                branch=branch,
                ordered_by=request.user,
                notes=notes,
            )
            total = Decimal(0)
            for pid, qty, cost in zip(product_ids, quantities, unit_costs):
                q = int(qty or 0)
                c = Decimal(cost or 0)
                if q > 0 and pid:
                    PurchaseOrderItem.objects.create(
                        order=po, product_id=pid, quantity=q, unit_cost=c
                    )
                    total += q * c
            po.total_amount = total
            po.save(update_fields=['total_amount'])

        messages.success(request, f"Purchase order #{po.id} created for ₦{total:,.0f}.")
        return redirect("purchase_order_list")

    from core.models import Supplier
    return render(request, "suppliers/po_form.html", {
        "suppliers": Supplier.objects.all().order_by("name"),
        "products": Product.objects.all().order_by("model_name"),
        "branches": Branch.objects.all(),
    })


@login_required
def purchase_order_receive(request, po_id):
    if request.user.role not in ['DIRECTOR', 'MANAGER']:
        return HttpResponseForbidden()
    from core.models import PurchaseOrder, AuditLog
    po = get_object_or_404(PurchaseOrder, id=po_id)
    if po.status == 'RECEIVED':
        messages.warning(request, "This order has already been received.")
        return redirect("purchase_order_list")

    with transaction.atomic():
        po.status = 'RECEIVED'
        po.date_received = date.today()
        po.save()
        # Add each item to branch safe stock
        for item in po.items.select_related('product'):
            safe_stock, _ = BranchSafeStock.objects.get_or_create(
                branch=po.branch, product=item.product
            )
            safe_stock.quantity += item.quantity
            safe_stock.save()
            StockMovement.objects.create(
                branch=po.branch, product=item.product,
                quantity=item.quantity, movement_type='IN',
                performed_by=request.user,
            )
        try:
            AuditLog.objects.create(
                user=request.user, action='UPDATE',
                model_name='PurchaseOrder', object_id=po.id,
                description=f"Received PO#{po.id} from {po.supplier.name}. Stock added to {po.branch.name}.",
            )
        except Exception:
            pass

    messages.success(request, f"PO#{po.id} received. Stock added to {po.branch.name} safe.")
    return redirect("purchase_order_list")


# ─────────────────────────────────────────
# MONTHLY PAYROLL DEDUCTION SUMMARY
# ─────────────────────────────────────────

@role_required("DIRECTOR")
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
def manager_sales_today(request):
    today = date.today()
    sales = RetailSale.objects.filter(
        branch=request.user.branch, date=today
    ).select_related("product", "staff").order_by("-time")
    total_revenue = sales.filter(is_voided=False).aggregate(
        t=Sum(F("quantity") * F("selling_price"))
    )["t"] or 0
    return render(request, "manager/sales_today.html", {
        "sales": sales,
        "total_revenue": total_revenue,
        "today": today,
    })

# ─────────────────────────────────────────
# FIXED DIRECTOR ATTENDANCE DASHBOARD
# ─────────────────────────────────────────

@role_required("DIRECTOR")
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


