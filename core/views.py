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
    _PILImage = None  # type: ignore[assignment]

from .models import (
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
from .models import log_action
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


def _get_dashboard_url(user):
    """Return the dashboard URL name for the given user's role."""
    from django.urls import reverse
    role_map = {
        "DIRECTOR":    "director_dashboard",
        "SUPERADMIN":  "director_dashboard",
        "MANAGER":     "manager_dashboard",
        "RETAIL":      "retail_dashboard",
        "MULTICHOICE": "multichoice_dashboard",
        "TELECOM":     "staff_dashboard",
    }
    if getattr(user, "is_superuser", False):
        return reverse("director_dashboard")
    name = role_map.get(getattr(user, "role", None), "login")
    return reverse(name)


def _get_director_phone():
    """Return the director's WhatsApp number from settings."""
    return getattr(django_settings, "DIRECTOR_WHATSAPP", "")


def send_whatsapp(phone, message):
    """Send a WhatsApp message via CallMeBot API. Returns True on success."""
    if not phone:
        return False
    import urllib.request
    import urllib.parse
    api_key = getattr(django_settings, "CALLMEBOT_API_KEY", "")
    if not api_key:
        return False
    try:
        encoded = urllib.parse.quote(message)
        url = f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={encoded}&apikey={api_key}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


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
            # Mark failed login for middleware rate limiting
            request._failed_login = True
            # Also track in model for account-level locking
            try:
                u = User.objects.get(username=username)
                if not u.is_superuser:
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
# ─────────────────────────────────────────
# MANAGER DASHBOARD
# ─────────────────────────────────────────
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
# ─────────────────────────────────────────
# RETAIL DASHBOARD
# ─────────────────────────────────────────
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
                color=request.POST.get("color", ""),
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
def edit_staff_stock_quantity(request, stock_id):
    if request.user.role != "RETAIL":
        return HttpResponseForbidden()
    stock = get_object_or_404(StaffStock, id=stock_id, staff=request.user)
    new_qty = request.GET.get("quantity")
    if new_qty is not None and new_qty != "":
        old_qty = stock.quantity
        stock.quantity = max(int(new_qty), 0)
        stock.save(update_fields=["quantity"])
        log_action(
            request.user,
            "UPDATE",
            "StaffStock",
            stock.id,
            f"Quantity updated from {old_qty} to {stock.quantity} for {stock.product.model_name}",
            request,
        )
        messages.success(request, "Quantity updated.")
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
        "products": Product.objects.select_related("subcategory", "created_by").all().order_by("-date_added"),
        "categories": RetailCategory.objects.all(),
    })


# ─────────────────────────────────────────
# MULTICHOICE DASHBOARD
# ─────────────────────────────────────────
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
@role_required("DIRECTOR")
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
def _compress_image(image_file, max_size_kb=100, max_dimension=600):
    """Compress uploaded image to reduce storage size aggressively (target ~100KB)."""
    try:
        img = _PILImage.open(image_file)
        # Convert RGBA to RGB if needed
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        # Resize if too large
        w, h = img.size
        if w > max_dimension or h > max_dimension:
            img.thumbnail((max_dimension, max_dimension), _PILImage.LANCZOS)
        # Save compressed aggressively
        output = io.BytesIO()
        quality = 70
        while True:
            output.seek(0)
            output.truncate()
            img.save(output, format="JPEG", quality=quality, optimize=True)
            size_kb = output.tell() / 1024
            if size_kb <= max_size_kb or quality <= 30:
                break
            quality -= 5
        output.seek(0)
        from django.core.files.uploadedfile import InMemoryUploadedFile
        return InMemoryUploadedFile(
            output, "ImageField",
            image_file.name.rsplit(".", 1)[0] + ".jpg",
            "image/jpeg", output.getbuffer().nbytes, None
        )
    except Exception:
        return image_file  # fallback to original if PIL fails


# ─────────────────────────────────────────
# CHANGE LOG UTILITY — record every significant data change
# ─────────────────────────────────────────

def _log_change(user, action, model_name, object_id=None, description="", old_value="", new_value="", request=None):
    """Log a change to the ChangeLog model."""
    try:
        from core.models import ChangeLog
        ip = None
        branch = None
        if request:
            ip = _get_client_ip(request)
            if hasattr(request, 'user') and request.user and getattr(request.user, 'branch', None):
                branch = request.user.branch
        ChangeLog.objects.create(
            user=user, action=action, model_name=model_name,
            object_id=object_id, description=description,
            old_value=str(old_value) if old_value else "", new_value=str(new_value) if new_value else "",
            ip_address=ip, branch=branch,
        )
    except Exception:
        pass  # Never fail the main operation for logging

def _get_client_ip(request):
    """Get the real client IP from request headers."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _get_price_floor(product, branch):
    """Get the minimum selling price for a product in a branch."""
    from core.models import PriceFloor
    try:
        floor = PriceFloor.objects.get(product=product, branch=branch)
        return floor.min_selling_price
    except PriceFloor.DoesNotExist:
        return product.selling_price  # default to product selling price
    except Exception:
        return product.selling_price


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
                "color": s.product.color,
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
                "color": s.product.color,
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
# ─────────────────────────────────────────
# FIXED DIRECTOR ATTENDANCE DASHBOARD
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def director_attendance_dashboard(request):
    # Default to current week view
    view_mode = request.GET.get("view", "week")  # 'week' or 'archive'
    branch_filter = request.GET.get("branch", "")
    staff_filter = request.GET.get("staff", "")
    selected_date_str = request.GET.get("date", "")

    today = timezone.now().date()
    from datetime import date as _date, timedelta

    if view_mode == "week":
        # Show current week (Monday to Sunday)
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        records = Attendance.objects.filter(
            date__range=(week_start, week_end)
        ).select_related("user", "branch").order_by("-date", "branch__name", "user__username")
        selected_date = week_start
        date_range_label = f"{week_start.strftime('%d %b')} — {week_end.strftime('%d %b %Y')}"
    else:
        # Archive view — specific date or date range
        try:
            selected_date = _date.fromisoformat(selected_date_str) if selected_date_str else today
        except Exception:
            selected_date = today
        records = Attendance.objects.filter(date=selected_date).select_related("user", "branch").order_by("branch__name", "user__username")
        date_range_label = selected_date.strftime("%d %b %Y")

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
        "view_mode": view_mode,
        "date_range_label": date_range_label,
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
# ─────────────────────────────────────────
# FIXED multichoice_dashboard — shows current balance
# ─────────────────────────────────────────

@role_required("MULTICHOICE")
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

    # Add expiry countdown to sales
    from datetime import timedelta as _td
    _today = today if hasattr(today, "year") else today.date()
    for _s in all_sales_page:
        try:
            _exp = _s.expiry_date
        except Exception:
            _exp = None
        if _exp is None:
            try:
                _sd = _s.date if hasattr(_s.date, "year") else _s.date.date()
                _exp = _sd + _td(days=30)
            except Exception:
                _exp = None
        _s.computed_expiry = _exp
        _s.computed_days_left = (_exp - _today).days if _exp else None

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
        "checkinout_logs": CheckInOutLog.objects.filter(staff=request.user).order_by("-date", "-check_in_time")[:20],
    })


# ─────────────────────────────────────────
# DEVICE COMMISSION — with history
# ─────────────────────────────────────────

@role_required("MANAGER")
def add_device_commission(request):
    branch      = request.user.branch
    device_tags = DeviceTag.objects.filter(branch=branch)

    if request.method == "POST":
        DeviceTagCommission.objects.update_or_create(
            branch=branch,
            device_tag_id=request.POST.get("device_tag_id"),
            month_year=request.POST.get("month_year"),
            defaults={
                "commission_amount": request.POST.get("commission_amount"),
                "created_by": request.user,
            },
        )
        messages.success(request, "Commission recorded.")
        return redirect("add_device_commission")

    # History with filters
    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")
    history   = DeviceTagCommission.objects.filter(branch=branch).select_related(
        "device_tag", "created_by"
    ).order_by("-created_at")
    if date_from:
        history = history.filter(created_at__date__gte=date_from)
    if date_to:
        history = history.filter(created_at__date__lte=date_to)

    paginator = Paginator(history, 30)
    history_page = paginator.get_page(request.GET.get("page"))

    total_commission = history.aggregate(t=Sum("commission_amount"))["t"] or 0

    return render(request, "device_commission_form.html", {
        "device_tags": device_tags,
        "history": history_page,
        "total_commission": total_commission,
        "date_from": date_from,
        "date_to": date_to,
    })


# ─────────────────────────────────────────
# STOCK MOVEMENT LOG — with date range + PDF download
# ─────────────────────────────────────────

@role_required("MANAGER")
def stock_movement_log(request):
    branch        = request.user.branch
    movement_type = request.GET.get("type", "")
    date_from     = request.GET.get("date_from", "")
    date_to       = request.GET.get("date_to", "")
    export        = request.GET.get("export", "")

    movements = StockMovement.objects.filter(
        branch=branch
    ).select_related("product", "performed_by").order_by("-date", "-time")

    if movement_type:
        movements = movements.filter(movement_type=movement_type)
    if date_from:
        movements = movements.filter(date__gte=date_from)
    if date_to:
        movements = movements.filter(date__lte=date_to)

    total_in  = movements.filter(movement_type="IN").aggregate(t=Sum("quantity"))["t"] or 0
    total_out = movements.filter(movement_type="OUT").aggregate(t=Sum("quantity"))["t"] or 0

    if export == "pdf":
        return _stock_log_pdf(movements, branch, date_from, date_to, movement_type)

    paginator = Paginator(movements, 50)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "manager/stock_log.html", {
        "movements": page,
        "total_in": total_in,
        "total_out": total_out,
        "selected_type": movement_type,
        "date_from": date_from,
        "date_to": date_to,
    })


def _stock_log_pdf(movements, branch, date_from, date_to, movement_type):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, rightMargin=0.5*inch, leftMargin=0.5*inch,
                            topMargin=0.7*inch, bottomMargin=0.7*inch)
    styles = getSampleStyleSheet()
    BLUE = colors.HexColor("#004F9F")

    label = f"{branch.name} Stock Log"
    if date_from or date_to:
        label += f"  |  {date_from or 'Start'} → {date_to or 'Today'}"
    if movement_type:
        label += f"  |  {movement_type} only"

    elements = [
        Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED", ParagraphStyle("T", parent=styles["Heading1"], fontSize=14, textColor=BLUE, alignment=TA_CENTER)),
        Paragraph(label, ParagraphStyle("S", parent=styles["Normal"], fontSize=9, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=12)),
    ]

    data = [["Date", "Time", "Product", "Type", "Qty", "Done By"]]
    for m in movements:
        data.append([
            m.date.strftime("%d %b %Y"),
            m.time.strftime("%H:%M") if m.time else "—",
            m.product.model_name[:35],
            m.movement_type,
            str(m.quantity),
            m.performed_by.username if m.performed_by else "—",
        ])

    t = Table(data, colWidths=[1.1*inch, 0.7*inch, 2.2*inch, 0.9*inch, 0.6*inch, 1.2*inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), BLUE),
        ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 8),
        ("GRID",          (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("ALIGN",         (3,0), (-1,-1), "CENTER"),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.15*inch))
    elements.append(Paragraph(
        f"Generated {timezone.now().strftime('%d %B %Y at %H:%M')} — Global Phonelinz Systems Ltd",
        ParagraphStyle("F", parent=styles["Normal"], fontSize=7, textColor=colors.grey, alignment=TA_CENTER)
    ))

    doc.build(elements)
    buffer.seek(0)
    fname = f"StockLog_{branch.name}_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ", "_")
    return HttpResponse(buffer, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ─────────────────────────────────────────
# MULTICHOICE HISTORY — PDF download filtered
# ─────────────────────────────────────────

@role_required("MULTICHOICE")
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

class CustomPasswordResetConfirmView(DjPRCV):
    template_name = "registration/password_reset_confirm.html"

    def form_valid(self, form):
        user = form.save()
        # Force save using set_password properly
        new_password = form.cleaned_data.get("new_password1")
        user.set_password(new_password)
        user.save()
        messages.success(self.request, "Password updated successfully. Please log in with your new password.")
        return redirect("login")


# ─────────────────────────────────────────
# DIRECTOR SAFE STOCK — with all_branches, all_staff, date filter, log
# ─────────────────────────────────────────

@role_required("DIRECTOR")
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


def _director_safe_pdf(stocks, date_from, date_to):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER
    BLUE = colors.HexColor("#004F9F")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, rightMargin=0.5*inch, leftMargin=0.5*inch,
                            topMargin=0.7*inch, bottomMargin=0.7*inch)
    styles = getSampleStyleSheet()
    label = f"Director Safe Stock"
    if date_from or date_to:
        label += f"  |  {date_from or 'Start'} to {date_to or 'Today'}"
    elements = [
        Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED", ParagraphStyle("T", parent=styles["Heading1"], fontSize=14, textColor=BLUE, alignment=TA_CENTER)),
        Paragraph(label, ParagraphStyle("S", parent=styles["Normal"], fontSize=9, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=12)),
    ]
    data = [["Product", "Category", "Cost Price", "Sell Price", "Qty", "Value", "Date Added"]]
    for s in stocks:
        data.append([
            s.product.model_name if s.product else "—",
            s.product.subcategory.name if s.product and s.product.subcategory else "—",
            f"N{s.product.cost_price:,.0f}" if s.product else "—",
            f"N{s.product.selling_price:,.0f}" if s.product else "—",
            str(s.quantity),
            f"N{s.total_value:,.0f}",
            s.date_added.strftime("%d %b %Y") if s.date_added else "—",
        ])
    t = Table(data, colWidths=[1.8*inch, 1.1*inch, 0.9*inch, 0.9*inch, 0.5*inch, 0.9*inch, 0.9*inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BLUE), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 8),
        ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    elements.append(t)
    elements.append(Paragraph(
        f"Generated {timezone.now().strftime('%d %B %Y at %H:%M')} — GPSL",
        ParagraphStyle("F", parent=styles["Normal"], fontSize=7, textColor=colors.grey, alignment=TA_CENTER, spaceBefore=10)
    ))
    doc.build(elements)
    buf.seek(0)
    fname = f"DirectorSafe_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ", "_")
    return HttpResponse(buf, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@role_required("DIRECTOR")
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
def retail_sales_history(request):
    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")
    product_q = request.GET.get("product", "")
    export    = request.GET.get("export", "")

    sales = RetailSale.objects.filter(
        staff=request.user
    ).select_related("product", "branch").order_by("-date", "-time")

    if date_from:
        sales = sales.filter(date__gte=date_from)
    if date_to:
        sales = sales.filter(date__lte=date_to)
    if product_q:
        sales = sales.filter(product__model_name__icontains=product_q)

    total_revenue = sales.filter(is_voided=False).aggregate(
        t=Sum(F("quantity") * F("selling_price"))
    )["t"] or 0
    total_qty = sales.filter(is_voided=False).aggregate(t=Sum("quantity"))["t"] or 0

    if export == "pdf":
        return _retail_sales_pdf(sales, request.user, date_from, date_to)

    paginator = Paginator(sales, 30)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "retail/sales_history.html", {
        "sales": page,
        "total_revenue": total_revenue,
        "total_qty": total_qty,
        "date_from": date_from,
        "date_to": date_to,
        "product_q": product_q,
    })


def _retail_sales_pdf(sales, user, date_from, date_to):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER
    BLUE = colors.HexColor("#004F9F")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, rightMargin=0.5*inch, leftMargin=0.5*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch)
    styles = getSampleStyleSheet()
    label = f"{user.username} — Sales History"
    if date_from or date_to:
        label += f"  |  {date_from or 'Start'} to {date_to or 'Today'}"
    elements = [
        Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED", ParagraphStyle("T", parent=styles["Heading1"], fontSize=13, textColor=BLUE, alignment=TA_CENTER)),
        Paragraph(label, ParagraphStyle("S", parent=styles["Normal"], fontSize=8, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=10)),
    ]
    data = [["Date", "Time", "Product", "Qty", "Price", "Total", "Payment", "Status"]]
    total = Decimal(0)
    for s in sales:
        amt = Decimal(s.quantity) * s.selling_price
        if not s.is_voided:
            total += amt
        data.append([
            s.date.strftime("%d %b %Y"),
            s.time.strftime("%H:%M") if s.time else "—",
            s.product.model_name[:28],
            str(s.quantity),
            f"N{s.selling_price:,.0f}",
            f"N{amt:,.0f}",
            s.payment_method,
            "VOIDED" if s.is_voided else "Active",
        ])
    data.append(["", "", "", "", "", f"N{total:,.0f}", "TOTAL", ""])
    t = Table(data, colWidths=[0.85*inch, 0.6*inch, 1.8*inch, 0.45*inch, 0.75*inch, 0.75*inch, 0.75*inch, 0.65*inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BLUE), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#F3F4F6")),
        ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 7.5),
        ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0,1), (-1,-2), [colors.white, colors.HexColor("#F9FAFB")]),
        ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)
    fname = f"SalesHistory_{user.username}_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ", "_")
    return HttpResponse(buf, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ─────────────────────────────────────────
# ATTENDANCE HISTORY — with date range + download
# ─────────────────────────────────────────

@login_required
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


def _attendance_pdf(qs, user, date_from, date_to):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER
    BLUE = colors.HexColor("#004F9F")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, rightMargin=0.5*inch, leftMargin=0.5*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch)
    styles = getSampleStyleSheet()
    label = f"{user.username} — Attendance History"
    if date_from or date_to:
        label += f"  |  {date_from or 'Start'} to {date_to or 'Today'}"
    elements = [
        Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED", ParagraphStyle("T", parent=styles["Heading1"], fontSize=13, textColor=BLUE, alignment=TA_CENTER)),
        Paragraph(label, ParagraphStyle("S", parent=styles["Normal"], fontSize=8, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=10)),
    ]
    data = [["Date", "Check In", "Check Out", "Status", "Distance", "Deduction"]]
    for r in qs:
        data.append([
            r.date.strftime("%d %b %Y"),
            r.check_in_time.strftime("%H:%M") if r.check_in_time else "—",
            r.check_out_time.strftime("%H:%M") if r.check_out_time else "Not out",
            "ABSENT" if r.is_absent else ("LATE" if r.is_late else "ON TIME"),
            f"{r.distance_from_branch:.0f}m" if r.distance_from_branch else "—",
            f"N{r.deduction_amount:,.2f}" if r.deduction_amount else "—",
        ])
    t = Table(data, colWidths=[1*inch, 0.8*inch, 0.8*inch, 0.8*inch, 0.8*inch, 0.9*inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BLUE), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 8),
        ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)
    fname = f"Attendance_{user.username}_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ", "_")
    return HttpResponse(buf, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ─────────────────────────────────────────
# DIRECTOR SALES REPORT — with date range + download
# ─────────────────────────────────────────

@role_required("DIRECTOR")
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

    # Retail sales
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

    # MultiChoice sales
    mc_sales = MultiChoiceSale.objects.select_related(
        "branch", "staff"
    ).order_by("branch__name", "-date")
    if date_from:
        mc_sales = mc_sales.filter(date__gte=date_from)
    if date_to:
        mc_sales = mc_sales.filter(date__lte=date_to)
    if branch_flt:
        mc_sales = mc_sales.filter(branch_id=branch_flt)
    if staff_flt:
        mc_sales = mc_sales.filter(staff_id=staff_flt)

    # Telecom activities
    telecom_acts = ServiceActivity.objects.select_related(
        "branch", "staff"
    ).order_by("branch__name", "-date")
    if date_from:
        telecom_acts = telecom_acts.filter(date__gte=date_from)
    if date_to:
        telecom_acts = telecom_acts.filter(date__lte=date_to)
    if branch_flt:
        telecom_acts = telecom_acts.filter(branch_id=branch_flt)
    if staff_flt:
        telecom_acts = telecom_acts.filter(staff_id=staff_flt)

    total_qty          = sales.aggregate(t=Sum("quantity"))["t"] or 0
    total_revenue      = sales.aggregate(t=Sum(F("quantity") * F("selling_price")))["t"] or 0
    total_mc_revenue   = mc_sales.aggregate(t=Sum("amount"))["t"] or 0
    total_mc_count     = mc_sales.count()
    total_telecom_acts = telecom_acts.aggregate(t=Sum("quantity"))["t"] or 0

    branch_sales_summary = {}
    for s in sales:
        amt = Decimal(s.quantity) * s.selling_price
        bk  = s.branch.name
        if bk not in branch_sales_summary:
            branch_sales_summary[bk] = {
                "retail": [], "multichoice": [], "telecom": [],
                "total_qty": 0, "total_revenue": Decimal(0),
                "mc_revenue": Decimal(0), "mc_count": 0,
                "telecom_count": 0,
            }
        branch_sales_summary[bk]["retail"].append({
            "product": s.product.model_name, "quantity": s.quantity,
            "price": s.selling_price, "amount": amt,
            "staff": s.staff.username,
            "date": s.date, "time": s.time,
        })
        branch_sales_summary[bk]["total_qty"] += s.quantity
        branch_sales_summary[bk]["total_revenue"] += amt

    for mc in mc_sales:
        bk = mc.branch.name
        if bk not in branch_sales_summary:
            branch_sales_summary[bk] = {
                "retail": [], "multichoice": [], "telecom": [],
                "total_qty": 0, "total_revenue": Decimal(0),
                "mc_revenue": Decimal(0), "mc_count": 0,
                "telecom_count": 0,
            }
        branch_sales_summary[bk]["multichoice"].append({
            "service_type": mc.service_type,
            "package_type": mc.package_type,
            "amount": mc.amount or Decimal(0),
            "staff": mc.staff.username,
            "date": mc.date,
            "customer": mc.customer_name or "—",
        })
        branch_sales_summary[bk]["mc_revenue"] += mc.amount or Decimal(0)
        branch_sales_summary[bk]["mc_count"] += 1

    for act in telecom_acts:
        bk = act.branch.name
        if bk not in branch_sales_summary:
            branch_sales_summary[bk] = {
                "retail": [], "multichoice": [], "telecom": [],
                "total_qty": 0, "total_revenue": Decimal(0),
                "mc_revenue": Decimal(0), "mc_count": 0,
                "telecom_count": 0,
            }
        branch_sales_summary[bk]["telecom"].append({
            "service_type": act.service_type,
            "quantity": act.quantity,
            "staff": act.staff.username,
            "date": act.date,
        })
        branch_sales_summary[bk]["telecom_count"] += act.quantity or 0

    if export == "pdf":
        return _director_sales_pdf(branch_sales_summary, total_qty, total_revenue, date_from, date_to)

    return render(request, "daily_sales_report.html", {
        "branch_sales_summary": branch_sales_summary,
        "total_qty": total_qty,
        "total_revenue": total_revenue,
        "total_mc_revenue": total_mc_revenue,
        "total_mc_count": total_mc_count,
        "total_telecom_acts": total_telecom_acts,
        "all_branches": Branch.objects.all(),
        "all_staff": User.objects.exclude(role__in=["DIRECTOR","SUPERADMIN"]).order_by("username"),
        "date_from": date_from,
        "date_to": date_to,
        "selected_branch": branch_flt,
        "selected_staff": staff_flt,
        "today": today,
    })


def _director_sales_pdf(branch_summary, total_qty, total_revenue, date_from, date_to):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER
    BLUE = colors.HexColor("#004F9F")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, rightMargin=0.5*inch, leftMargin=0.5*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch)
    styles = getSampleStyleSheet()
    label = f"Sales Report  |  {date_from or 'All'} to {date_to or 'Today'}"
    elements = [
        Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED", ParagraphStyle("T", parent=styles["Heading1"], fontSize=14, textColor=BLUE, alignment=TA_CENTER)),
        Paragraph(label, ParagraphStyle("S", parent=styles["Normal"], fontSize=9, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=10)),
    ]
    for bn, data in branch_summary.items():
        bh = Table([[Paragraph(f"  {bn}", ParagraphStyle("bh", parent=styles["Normal"], fontSize=10, textColor=colors.white, fontName="Helvetica-Bold"))]],
                   colWidths=[7.5*inch])
        bh.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#374151")),
                                 ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        elements.append(bh)
        rows = [["Date", "Time", "Product", "Staff", "Qty", "Price", "Total"]]
        for s in data["sales"]:
            rows.append([
                s["date"].strftime("%d %b %Y") if s["date"] else "—",
                s["time"].strftime("%H:%M") if s["time"] else "—",
                str(s["product"])[:28],
                str(s["staff"]),
                str(s["quantity"]),
                f"N{s['price']:,.0f}",
                f"N{s['amount']:,.0f}",
            ])
        rows.append(["","","","BRANCH TOTAL", str(data["total_qty"]),"",f"N{data['total_revenue']:,.0f}"])
        t = Table(rows, colWidths=[0.85*inch,0.6*inch,1.8*inch,1*inch,0.5*inch,0.8*inch,0.85*inch], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#E5E7EB")),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("BACKGROUND",(0,-1),(-1,-1),colors.HexColor("#F0FDF4")),
            ("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),
            ("FONTSIZE",(0,0),(-1,-1),7.5),
            ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#E5E7EB")),
            ("ROWBACKGROUNDS",(0,1),(-1,-2),[colors.white,colors.HexColor("#F9FAFB")]),
            ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 0.12*inch))

    # Grand total
    gt = Table([[f"GRAND TOTAL — {total_qty} items", f"N{total_revenue:,.0f}"]], colWidths=[5*inch, 2.5*inch])
    gt.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),BLUE),("TEXTCOLOR",(0,0),(-1,-1),colors.white),
        ("FONTNAME",(0,0),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),10),
        ("ALIGN",(1,0),(1,0),"RIGHT"),("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
    ]))
    elements.append(gt)
    doc.build(elements)
    buf.seek(0)
    fname = f"SalesReport_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ","_")
    return HttpResponse(buf, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ─────────────────────────────────────────
# MANAGER SALES HISTORY — date range + staff + download
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

@role_required("DIRECTOR")
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

def _earn_loyalty_points(customer, branch, amount, source):
    """Auto-earn loyalty points: 1 point per N100 spent."""
    if not amount or amount <= 0:
        return
    points = int(Decimal(str(amount)) / 100)
    if points < 1:
        return

    from decimal import Decimal
    lp, _ = LoyaltyPoint.objects.get_or_create(
        customer=customer,
        branch=branch,
        defaults={'points_balance': 0, 'total_earned': 0, 'total_redeemed': 0, 'tier': 'BRONZE'}
    )
    lp.points_balance += points
    lp.total_earned += points
    lp.save(update_fields=['points_balance', 'total_earned'])
    lp.update_tier()

    LoyaltyTransaction.objects.create(
        loyalty_point=lp,
        transaction_type='EARN',
        points=points,
        amount_spent=Decimal(str(amount)),
        description=f"Points earned from {source} purchase",
        sale_type=source,
    )


def _upsert_customer(phone, name, branch, amount=0, source="RETAIL"):
    """
    Create or update a customer record from any sale source.
    phone: customer phone number (required)
    name: customer name (optional, uses existing or 'Unknown')
    branch: branch object
    amount: sale amount to add to total_spent
    source: RETAIL, MULTICHOICE, TELECOM
    """
    if not phone or not phone.strip():
        return None
    phone = phone.strip()
    try:
        customer, created = Customer.objects.get_or_create(
            phone_number=phone,
            defaults={
                "name": (name or "").strip() or "Unknown",
                "branch": branch,
                "purchase_count": 0,
                "total_spent": Decimal("0"),
            }
        )
        # Update name if we now have one and didn't before
        if not created and name and name.strip() and customer.name in ("Unknown", "", None):
            customer.name = name.strip()

        # Update stats
        customer.purchase_count += 1
        customer.total_spent = (customer.total_spent or Decimal("0")) + Decimal(str(amount or 0))
        customer.last_purchase = timezone.now()
        customer.save()

        # Auto-earn loyalty points: 1 point per N100 spent
        try:
            _earn_loyalty_points(customer, customer.branch, amount, source)
        except Exception:
            pass  # Don't fail sale if loyalty fails
        return customer
    except Exception:
        return None


# ─────────────────────────────────────────
# FIXED record_retail_sale — captures customer name + phone
# ─────────────────────────────────────────

@role_required("RETAIL")
def record_retail_sale(request):
    if request.method == "POST":
        product_ids    = request.POST.getlist("product")
        quantities     = request.POST.getlist("quantity")
        selling_prices = request.POST.getlist("selling_price")
        payment_method = request.POST.get("payment_method", "CASH")
        customer_name  = request.POST.get("customer_name", "").strip()
        customer_phone = request.POST.get("customer_phone", "").strip()
        moniepoint_txn_id = request.POST.get("moniepoint_txn_id", "").strip()

        if not product_ids or not any(product_ids):
            messages.error(request, "Please select at least one product.")
            return redirect("retail_dashboard")

        total_amount = Decimal("0")
        sale_items = []

        with transaction.atomic():
            for i, product_id in enumerate(product_ids):
                if not product_id:
                    continue
                qty = int(quantities[i]) if i < len(quantities) else 1
                price = Decimal(selling_prices[i]) if i < len(selling_prices) else Decimal("0")

                product = get_object_or_404(Product, id=product_id)

                try:
                    staff_stock = StaffStock.objects.get(staff=request.user, product=product)
                except StaffStock.DoesNotExist:
                    messages.error(request, f"You do not have {product.model_name} in stock.")
                    return redirect("retail_dashboard")

                if qty > staff_stock.quantity:
                    messages.error(request, f"Insufficient stock for {product.model_name}. You have {staff_stock.quantity} unit(s).")
                    return redirect("retail_dashboard")

                # PRICE FLOOR CHECK
                min_price = _get_price_floor(product, request.user.branch)
                if price < min_price:
                    messages.error(request, f"Selling price for {product.model_name} too low. Minimum: ₦{min_price:,.0f}. Current: ₦{price:,.0f}.")
                    return redirect("retail_dashboard")

                staff_stock.quantity -= qty
                staff_stock.save()

                sale = RetailSale.objects.create(
                    staff=request.user,
                    branch=request.user.branch,
                    product=product,
                    quantity=qty,
                    selling_price=price,
                    payment_method=payment_method,
                    customer_phone=customer_phone,
                )

                sale_items.append({"product": product.model_name, "qty": qty, "total": qty * price})
                total_amount += qty * price

                # Log change
                _log_change(
                    user=request.user, action="SALE", model_name="RetailSale",
                    object_id=sale.id, description=f"Retail sale: {qty}x {product.model_name} @ ₦{price}",
                    new_value=f"Total: ₦{qty * price}", request=request,
                )

            # Update Customer CRM (once for the whole transaction)
            if customer_phone:
                _upsert_customer(
                    phone=customer_phone,
                    name=customer_name,
                    branch=request.user.branch,
                    amount=total_amount,
                    source="RETAIL",
                )

        item_summary = ", ".join([f"{s['qty']}x {s['product']}" for s in sale_items])
        messages.success(request, f"Sale recorded: {item_summary}. Grand Total: ₦{total_amount:,.0f}")
    return redirect("retail_dashboard")


# ─────────────────────────────────────────
# FIXED record_multichoice_sale — updates Customer CRM
# ─────────────────────────────────────────

@role_required("MULTICHOICE")
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


# ─────────────────────────────────────────
# FIXED commission_tracking — shows ALL types
# DeviceTag commissions (Telecom) + MultiChoice commissions
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def commission_tracking(request):
    date_from   = request.GET.get("date_from", "")
    date_to     = request.GET.get("date_to", "")
    branch_flt  = request.GET.get("branch", "")
    comm_type   = request.GET.get("type", "")  # TELECOM or MULTICHOICE

    # MultiChoice commissions
    mc_commissions = CommissionPayment.objects.select_related(
        "staff", "branch"
    ).order_by("-date_detected")

    # Device tag (Telecom) commissions
    telecom_commissions = DeviceTagCommission.objects.select_related(
        "device_tag", "branch", "created_by"
    ).order_by("-created_at")

    if date_from:
        mc_commissions = mc_commissions.filter(date_detected__date__gte=date_from)
        telecom_commissions = telecom_commissions.filter(created_at__date__gte=date_from)
    if date_to:
        mc_commissions = mc_commissions.filter(date_detected__date__lte=date_to)
        telecom_commissions = telecom_commissions.filter(created_at__date__lte=date_to)
    if branch_flt:
        mc_commissions = mc_commissions.filter(branch_id=branch_flt)
        telecom_commissions = telecom_commissions.filter(branch_id=branch_flt)

    total_mc = mc_commissions.aggregate(
        t=Sum("commission_detected")
    )["t"] or 0
    total_telecom = telecom_commissions.aggregate(
        t=Sum("commission_amount")
    )["t"] or 0

    return render(request, "commission_tracking.html", {
        "mc_commissions": mc_commissions,
        "telecom_commissions": telecom_commissions,
        "total_mc": total_mc,
        "total_telecom": total_telecom,
        "grand_total": total_mc + total_telecom,
        "branches": Branch.objects.all(),
        "date_from": date_from,
        "date_to": date_to,
        "branch_flt": branch_flt,
        "comm_type": comm_type,
    })


# ─────────────────────────────────────────
# RETAIL DASHBOARD — with stock alerts
# ─────────────────────────────────────────

@role_required("RETAIL")
def retail_dashboard(request):
    staff = request.user
    staff_stock = StaffStock.objects.filter(
        staff=staff
    ).select_related("product", "product__subcategory")

    # Stock alerts for retail staff — items with 0 or low stock
    low_stock_items = [s for s in staff_stock if s.quantity <= 2]
    out_of_stock    = [s for s in staff_stock if s.quantity == 0]

    sales_qs = RetailSale.objects.filter(
        staff=staff
    ).select_related("product").order_by("-date", "-id")

    paginator = Paginator(sales_qs, 30)
    sales_history = paginator.get_page(request.GET.get("page"))
    for s in sales_history:
        s.total_revenue = Decimal(s.quantity) * s.selling_price

    check_logs = CheckInOutLog.objects.filter(staff=staff).order_by(
        "-date", "-check_in_time"
    )[:20]

    return render(request, "retail_dashboard.html", {
        "staff_stock": staff_stock,
        "categories": RetailCategory.objects.all(),
        "check_logs": check_logs,
        "checkinout_logs": check_logs,
        "sales_history": sales_history,
        "low_stock_items": low_stock_items,
        "out_of_stock": out_of_stock,
    })


# ─────────────────────────────────────────
# MANAGER DASHBOARD — with stock alerts + service target form
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

@role_required("TELECOM")
def wholesale_catalog(request):
    """Redirect to the integrated staff dashboard Device Stock tab."""
    return redirect("staff_dashboard")


@role_required("TELECOM")
def wholesale_add_device(request):
    from core.models import WholesaleDevice
    if request.method == "POST":
        try:
            qty   = int(request.POST.get("quantity", 0))
            cost  = Decimal(request.POST.get("cost_price") or "0")
            price = Decimal(request.POST.get("selling_price") or "0")

            with transaction.atomic():
                # Check if device already exists (same name + type + network)
                existing = WholesaleDevice.objects.filter(
                    branch=request.user.branch,
                    staff=request.user,
                    product_name__iexact=request.POST.get("product_name", "").strip(),
                    product_type=request.POST.get("product_type"),
                    network_type=request.POST.get("network_type"),
                ).first()

                if existing:
                    existing.quantity += qty
                    if cost:
                        existing.cost_price = cost
                    if price:
                        existing.selling_price = price
                    existing.save()
                    messages.success(
                        request,
                        f"Added {qty} unit(s) to existing {existing.product_name}. "
                        f"New total: {existing.quantity}."
                    )
                else:
                    WholesaleDevice.objects.create(
                        branch=request.user.branch,
                        staff=request.user,
                        product_name=request.POST.get("product_name", "").strip(),
                        product_type=request.POST.get("product_type", "MIFI"),
                        network_type=request.POST.get("network_type", "4G"),
                        serial_number=request.POST.get("serial_number", "").strip(),
                        quantity=qty,
                        cost_price=cost,
                        selling_price=price,
                        notes=request.POST.get("notes", "").strip(),
                    )
                    messages.success(
                        request,
                        f"Device added to catalog with {qty} unit(s)."
                    )
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("staff_dashboard")


@role_required("TELECOM")
def wholesale_record_sale(request):
    from core.models import WholesaleDevice, WholesaleDeviceSale
    if request.method == "POST":
        device_id   = request.POST.get("device_id")
        qty         = int(request.POST.get("quantity", 0))
        unit_price  = Decimal(request.POST.get("unit_price") or "0")
        buyer_type  = request.POST.get("buyer_type", "CUSTOMER")
        buyer_name  = request.POST.get("buyer_name", "").strip()
        buyer_phone = request.POST.get("buyer_phone", "").strip()
        payment     = request.POST.get("payment_method", "CASH")
        notes       = request.POST.get("notes", "").strip()

        device = get_object_or_404(
            WholesaleDevice, id=device_id,
            branch=request.user.branch, staff=request.user
        )

        if qty <= 0:
            messages.error(request, "Quantity must be at least 1.")
            return redirect("staff_dashboard")

        if qty > device.quantity:
            messages.error(
                request,
                f"Only {device.quantity} unit(s) available for {device.product_name}."
            )
            return redirect("staff_dashboard")

        total = qty * unit_price
        is_director = buyer_type == "DIRECTOR"

        with transaction.atomic():
            device.quantity -= qty
            device.save()

            WholesaleDeviceSale.objects.create(
                device=device,
                sold_by=request.user,
                branch=request.user.branch,
                buyer_type=buyer_type,
                buyer_name=buyer_name or ("Director" if is_director else "Walk-in Customer"),
                buyer_phone=buyer_phone,
                quantity=qty,
                unit_price=unit_price,
                total_amount=total,
                payment_method=payment,
                is_director_sale=is_director,
                notes=notes,
            )

            # Save customer to CRM if phone provided
            if buyer_phone and not is_director:
                _upsert_customer(
                    phone=buyer_phone,
                    name=buyer_name,
                    branch=request.user.branch,
                    amount=total,
                    source="TELECOM",
                )

            # Audit log
            try:
                from core.models import AuditLog
                AuditLog.objects.create(
                    user=request.user,
                    action="CREATE",
                    model_name="WholesaleDeviceSale",
                    description=(
                        f"{'[DIRECTOR SALE] ' if is_director else ''}"
                        f"Sold {qty}x {device.product_name} ({device.network_type}) "
                        f"to {buyer_name or buyer_type} for ₦{total:,.2f}. "
                        f"Payment: {payment}."
                    ),
                )
            except Exception:
                pass

        label = "director" if is_director else buyer_name or "customer"
        messages.success(
            request,
            f"Sale recorded. {qty}x {device.product_name} sold to {label} "
            f"for ₦{total:,.2f}."
        )
    return redirect("staff_dashboard")


def _wholesale_pdf(devices, sales, user, date_from, date_to):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER

    BLUE = colors.HexColor("#004F9F")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, rightMargin=0.5*inch, leftMargin=0.5*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch)
    styles = getSampleStyleSheet()
    label = f"{user.username} — Wholesale Device Report"
    if date_from or date_to:
        label += f"  |  {date_from or 'Start'} to {date_to or 'Today'}"

    elements = [
        Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED",
            ParagraphStyle("T", parent=styles["Heading1"], fontSize=13,
                           textColor=BLUE, alignment=TA_CENTER)),
        Paragraph(label,
            ParagraphStyle("S", parent=styles["Normal"], fontSize=8,
                           textColor=colors.grey, alignment=TA_CENTER, spaceAfter=10)),
        Paragraph("CATALOG INVENTORY",
            ParagraphStyle("H", parent=styles["Heading2"], fontSize=10,
                           textColor=BLUE, spaceBefore=8, spaceAfter=4)),
    ]

    # Inventory table
    inv_data = [["Product", "Type", "Network", "Qty", "Cost Price", "Sell Price", "Value", "Date Added"]]
    for d in devices:
        inv_data.append([
            d.product_name,
            d.get_product_type_display(),
            d.get_network_type_display(),
            str(d.quantity),
            f"N{d.cost_price:,.0f}",
            f"N{d.selling_price:,.0f}",
            f"N{d.total_value:,.0f}",
            d.date_added.strftime("%d %b %Y"),
        ])

    t1 = Table(inv_data,
               colWidths=[1.4*inch, 0.75*inch, 0.75*inch, 0.4*inch,
                          0.8*inch, 0.8*inch, 0.8*inch, 0.8*inch],
               repeatRows=1)
    t1.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BLUE),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,-1), 7.5),
        ("GRID",       (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    elements.append(t1)
    elements.append(Spacer(1, 0.2*inch))
    elements.append(Paragraph("SALES LOG",
        ParagraphStyle("H2", parent=styles["Heading2"], fontSize=10,
                       textColor=BLUE, spaceBefore=8, spaceAfter=4)))

    # Sales table
    sales_data = [["Date", "Time", "Product", "Buyer Type", "Buyer", "Qty", "Unit Price", "Total", "Payment"]]
    for s in sales:
        sales_data.append([
            s.date.strftime("%d %b %Y"),
            s.time.strftime("%H:%M") if s.time else "—",
            s.device.product_name,
            f"{'⭐ ' if s.is_director_sale else ''}{s.buyer_type}",
            s.buyer_name or "—",
            str(s.quantity),
            f"N{s.unit_price:,.0f}",
            f"N{s.total_amount:,.0f}",
            s.payment_method,
        ])

    t2 = Table(sales_data,
               colWidths=[0.75*inch, 0.5*inch, 1.2*inch, 0.75*inch,
                          0.9*inch, 0.4*inch, 0.75*inch, 0.8*inch, 0.65*inch],
               repeatRows=1)
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#374151")),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,-1), 7),
        ("GRID",       (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    elements.append(t2)
    elements.append(Paragraph(
        f"Generated {timezone.now().strftime('%d %B %Y at %H:%M')} — GPSL",
        ParagraphStyle("F", parent=styles["Normal"], fontSize=7,
                       textColor=colors.grey, alignment=TA_CENTER, spaceBefore=10)
    ))

    doc.build(elements)
    buf.seek(0)
    fname = f"Wholesale_{user.username}_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ", "_")
    return HttpResponse(buf, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ─────────────────────────────────────────
# DIRECTOR: View MultiChoice balance across all branches
# ─────────────────────────────────────────

@role_required("DIRECTOR")
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
def invoice_preview(request, sale_type, sale_id):
    """Preview and manage invoice for any sale. Click-to-generate (not automatic)."""
    # Resolve the actual sale record
    if sale_type == 'RETAIL':
        sale = get_object_or_404(RetailSale, id=sale_id)
    elif sale_type == 'MULTICHOICE':
        sale = get_object_or_404(MultiChoiceSale, id=sale_id)
    elif sale_type == 'TELECOM':
        sale = get_object_or_404(ServiceActivity, id=sale_id)
    elif sale_type == 'WHOLESALE':
        sale = get_object_or_404(WholesaleDeviceSale, id=sale_id)
    else:
        return HttpResponseForbidden("Invalid sale type")

    # Permission: same branch or superuser
    if sale.branch != request.user.branch and not request.user.is_superuser:
        return HttpResponseForbidden()

    # Build or retrieve invoice record
    staff = getattr(sale, 'staff', None) or getattr(sale, 'sold_by', None)
    invoice, created = Invoice.objects.get_or_create(
        sale_type=sale_type,
        sale_id=sale_id,
        defaults={
            'invoice_number': f"GPSL-{sale_type[:3].upper()}-{sale_id:06d}-{timezone.now().strftime('%Y%m%d')}",
            'branch': sale.branch,
            'staff': staff,
            'customer_name': getattr(sale, 'customer_name', '') or '',
            'customer_phone': getattr(sale, 'customer_phone', '') or '',
            'quantity': getattr(sale, 'quantity', 1) or 1,
            'unit_price': (
                getattr(sale, 'selling_price', None) or
                getattr(sale, 'amount', None) or
                getattr(sale, 'unit_price', None) or
                getattr(sale, 'price', None) or
                0
            ),
            'total_amount': (
                getattr(sale, 'total_amount', None) or
                getattr(sale, 'total_revenue', None) or
                getattr(sale, 'amount', None) or
                getattr(sale, 'price', None) or
                0
            ),
            'payment_method': getattr(sale, 'payment_method', 'CASH') or 'CASH',
        }
    )

    # Update description based on sale type
    desc = ""
    if sale_type == 'RETAIL':
        desc = f"{sale.product.model_name} ({sale.product.subcategory.name})"
    elif sale_type == 'MULTICHOICE':
        desc = f"{sale.service_type} - {sale.package_type} ({sale.get_transaction_type_display()})"
    elif sale_type == 'TELECOM':
        tag = sale.device_tag.tag_name if sale.device_tag else ""
        desc = f"{sale.service_type} {tag}".strip()
    elif sale_type == 'WHOLESALE':
        desc = f"{sale.device.product_name} ({sale.device.network_type})"

    if not invoice.product_description:
        invoice.product_description = desc
        invoice.save(update_fields=['product_description'])

    # Handle email send
    if request.method == 'POST':
        email_to = request.POST.get('email', '').strip()
        if email_to:
            try:
                pdf_buffer = _build_invoice_pdf(invoice)
                email = EmailMessage(
                    subject=f"Invoice {invoice.invoice_number} — GLOBAL PHONELINZ SYSTEMS LIMITED",
                    body=(
                        f"Dear {invoice.customer_name or 'Customer'},\n\n"
                        f"Please find attached your invoice {invoice.invoice_number}.\n\n"
                        f"Total Amount: ₦{invoice.total_amount:,.2f}\n\n"
                        f"Thank you for your business.\n\n"
                        f"Best regards,\nGLOBAL PHONELINZ SYSTEMS LIMITED"
                    ),
                    from_email=None,
                    to=[email_to],
                )
                email.attach(f"Invoice_{invoice.invoice_number}.pdf", pdf_buffer.getvalue(), 'application/pdf')
                email.send()
                invoice.emailed_to = email_to
                invoice.save(update_fields=['emailed_to'])
                messages.success(request, f"Invoice emailed to {email_to}")
            except Exception as e:
                messages.error(request, f"Failed to send email: {e}")
        return redirect('invoice_preview', sale_type=sale_type, sale_id=sale_id)

    return render(request, 'invoice_preview.html', {
        'invoice': invoice,
        'sale': sale,
        'sale_type': sale_type,
        'sale_id': sale_id,
    })


@login_required
def invoice_download_pdf(request, sale_type, sale_id):
    """Download invoice as PDF."""
    invoice = get_object_or_404(Invoice, sale_type=sale_type, sale_id=sale_id)
    if invoice.branch != request.user.branch and not request.user.is_superuser:
        return HttpResponseForbidden()
    pdf_buffer = _build_invoice_pdf(invoice)
    response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Invoice_{invoice.invoice_number}.pdf"'
    return response


@login_required
def invoice_receipt(request, sale_type, sale_id):
    """Compact thermal receipt view optimized for 58mm/80mm printers and mobile."""
    invoice = get_object_or_404(Invoice, sale_type=sale_type, sale_id=sale_id)
    if invoice.branch != request.user.branch and not request.user.is_superuser:
        return HttpResponseForbidden()
    return render(request, 'invoice_receipt.html', {
        'invoice': invoice,
        'sale_type': sale_type,
        'sale_id': sale_id,
    })


def _build_invoice_pdf(invoice):
    """Build a professional invoice PDF using ReportLab."""
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        rightMargin=0.6*inch,
        leftMargin=0.6*inch,
        topMargin=0.6*inch,
        bottomMargin=0.6*inch,
    )

    styles = getSampleStyleSheet()
    BLUE = colors.HexColor("#004F9F")

    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=BLUE,
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.grey,
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    section_style = ParagraphStyle(
        'Section',
        parent=styles['Heading3'],
        fontSize=11,
        textColor=BLUE,
        spaceAfter=4,
        spaceBefore=8,
    )
    normal_style = ParagraphStyle(
        'NormalCustom',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=4,
    )

    elements = []

    # Header
    elements.append(Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED", title_style))
    elements.append(Paragraph("Telecom & Retail Solutions", subtitle_style))
    elements.append(Paragraph("08066090000, 08032036766, 08032036764", subtitle_style))
    elements.append(Spacer(1, 6))

    # Invoice meta
    elements.append(Paragraph(f"<b>INVOICE</b>  —  {invoice.invoice_number}", section_style))
    elements.append(Spacer(1, 4))

    meta_data = [
        ['Branch:', str(invoice.branch.name)],
        ['Address:', str(invoice.branch.full_address)],
        ['Date:', f"{invoice.date.strftime('%d %B %Y')} {invoice.time.strftime('%H:%M')}"],
        ['Payment Method:', str(invoice.payment_method or '—')],
    ]
    meta_table = Table(meta_data, colWidths=[1.8*inch, 4*inch])
    meta_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('TEXTCOLOR', (0,0), (0,-1), BLUE),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 8))

    # Customer info
    elements.append(Paragraph("Bill To", section_style))
    customer_lines = []
    if invoice.customer_name:
        customer_lines.append(f"Name: {invoice.customer_name}")
    if invoice.customer_phone:
        customer_lines.append(f"Phone: {invoice.customer_phone}")
    if not customer_lines:
        customer_lines.append("Walk-in Customer")

    cust_data = [[line] for line in customer_lines]
    cust_table = Table(cust_data, colWidths=[5.8*inch])
    cust_table.setStyle(TableStyle([
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
    ]))
    elements.append(cust_table)
    elements.append(Spacer(1, 12))

    # Product table
    elements.append(Paragraph("Item(s)", section_style))
    product_data = [
        ['Description', 'Qty', 'Unit Price (₦)', 'Total (₦)'],
        [
            invoice.product_description or 'Service / Product',
            str(invoice.quantity),
            f"{invoice.unit_price:,.2f}",
            f"{invoice.total_amount:,.2f}",
        ],
    ]
    product_table = Table(product_data, colWidths=[3.2*inch, 0.8*inch, 1.4*inch, 1.4*inch])
    product_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), BLUE),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('ALIGN', (1,0), (-1,-1), 'CENTER'),
        ('ALIGN', (-1,1), (-1,-1), 'RIGHT'),
        ('FONTNAME', (0,1), (0,1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,1), (-1,1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
    ]))
    elements.append(product_table)
    elements.append(Spacer(1, 8))

    # Total
    total_data = [['', '', 'Total Amount (₦):', f"{invoice.total_amount:,.2f}"]]
    total_table = Table(total_data, colWidths=[3.2*inch, 0.8*inch, 1.4*inch, 1.4*inch])
    total_table.setStyle(TableStyle([
        ('FONTNAME', (2,0), (3,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 11),
        ('TEXTCOLOR', (2,0), (3,0), BLUE),
        ('ALIGN', (2,0), (3,0), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        ('TOPPADDING', (0,0), (-1,0), 8),
    ]))
    elements.append(total_table)
    elements.append(Spacer(1, 20))

    # Footer
    staff_name = invoice.staff.get_full_name() or invoice.staff.username
    elements.append(Paragraph(f"<b>Attended to by:</b> {staff_name}", normal_style))
    elements.append(Paragraph(f"<b>Branch:</b> {invoice.branch.name}", normal_style))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("Thank you for your patronage. For enquiries, contact your branch manager.", subtitle_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer


# ────────────────────────────────────────────
# MONIEPOINT POS INTEGRATION
# ────────────────────────────────────────────

@login_required
def record_moniepoint(request):
    """Staff records a Moniepoint POS transaction for reconciliation."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    transaction_id = request.POST.get("transaction_id", "").strip()
    amount = Decimal(request.POST.get("amount") or "0")
    customer_phone = request.POST.get("customer_phone", "").strip()
    customer_name = request.POST.get("customer_name", "").strip()
    notes = request.POST.get("notes", "").strip()
    sale_type = request.POST.get("sale_type", "").strip()
    sale_id = request.POST.get("sale_id")

    if not transaction_id:
        return JsonResponse({"error": "Transaction ID is required"}, status=400)
    if amount <= 0:
        return JsonResponse({"error": "Valid amount is required"}, status=400)

    # Check for duplicate
    if MoniepointTransaction.objects.filter(transaction_id=transaction_id).exists():
        return JsonResponse({"error": "This transaction ID already exists"}, status=400)

    txn = MoniepointTransaction.objects.create(
        transaction_id=transaction_id,
        branch=request.user.branch,
        staff=request.user,
        customer_name=customer_name,
        customer_phone=customer_phone,
        amount=amount,
        status='SUCCESS',
        notes=notes,
        sale_type=sale_type,
        sale_id=int(sale_id) if sale_id else None,
    )

    log_action(request.user, "CREATE", "MoniepointTransaction", f"Recorded POS transaction {transaction_id} for N{amount}")
    return JsonResponse({"success": True, "id": txn.id, "message": f"Moniepoint transaction {transaction_id} recorded."})


@role_required("DIRECTOR")
def moniepoint_reconcile(request):
    """Director view: reconcile Moniepoint transactions with branch totals."""
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    branch_id = request.GET.get("branch", "")
    status = request.GET.get("status", "")

    txns = MoniepointTransaction.objects.all().select_related("branch", "staff")

    if date_from:
        txns = txns.filter(date__gte=date_from)
    if date_to:
        txns = txns.filter(date__lte=date_to)
    if branch_id:
        txns = txns.filter(branch_id=branch_id)
    if status:
        txns = txns.filter(status=status)

    total_amount = txns.aggregate(t=Sum("amount"))["t"] or 0
    total_count = txns.count()

    # Summary by branch
    branch_summary = []
    for b in Branch.objects.all():
        b_txns = txns.filter(branch=b)
        b_total = b_txns.aggregate(t=Sum("amount"))["t"] or 0
        b_count = b_txns.count()
        if b_count > 0:
            branch_summary.append({"branch": b, "count": b_count, "total": b_total})

    paginator = Paginator(txns.order_by("-created_at"), 50)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "director/moniepoint_reconcile.html", {
        "transactions": page,
        "total_amount": total_amount,
        "total_count": total_count,
        "branch_summary": branch_summary,
        "branches": Branch.objects.all(),
        "date_from": date_from,
        "date_to": date_to,
        "status_filter": status,
    })


# ────────────────────────────────────────────
# LOYALTY PROGRAM VIEWS
# ────────────────────────────────────────────

@login_required
def loyalty_customer_lookup(request, phone):
    """AJAX endpoint: get customer loyalty status by phone."""
    phone = phone.strip()
    try:
        customer = Customer.objects.get(phone_number=phone)
    except Customer.DoesNotExist:
        return JsonResponse({"found": False, "message": "Customer not found."})

    lp = LoyaltyPoint.objects.filter(customer=customer, branch=request.user.branch).first()
    if not lp:
        return JsonResponse({
            "found": True,
            "name": customer.name,
            "points": 0,
            "tier": "BRONZE",
            "total_spent": str(customer.total_spent),
            "purchase_count": customer.purchase_count,
        })

    return JsonResponse({
        "found": True,
        "name": customer.name,
        "points": lp.points_balance,
        "tier": lp.tier,
        "total_earned": lp.total_earned,
        "total_redeemed": lp.total_redeemed,
        "total_spent": str(customer.total_spent),
        "purchase_count": customer.purchase_count,
    })


@login_required
def loyalty_redeem(request):
    """Staff redeems loyalty points for a customer (e.g., discount on sale)."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    phone = request.POST.get("phone", "").strip()
    points = int(request.POST.get("points") or 0)
    description = request.POST.get("description", "Point redemption").strip()

    if not phone or points <= 0:
        return JsonResponse({"error": "Phone and points required"}, status=400)

    try:
        customer = Customer.objects.get(phone_number=phone)
    except Customer.DoesNotExist:
        return JsonResponse({"error": "Customer not found"}, status=404)

    lp = LoyaltyPoint.objects.filter(customer=customer, branch=request.user.branch).first()
    if not lp or lp.points_balance < points:
        return JsonResponse({"error": f"Insufficient points. Balance: {lp.points_balance if lp else 0}"}, status=400)

    # Redeem
    lp.points_balance -= points
    lp.total_redeemed += points
    lp.save()
    LoyaltyTransaction.objects.create(
        loyalty_point=lp, transaction_type="REDEEM", points=points,
        description=description, created_by=request.user,
    )
    return JsonResponse({"success": True, "new_balance": lp.points_balance, "tier": lp.tier})


# ─────────────────────────────────────────
# CHANGE LOG VIEW
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def change_log_view(request):
    from core.models import ChangeLog
    logs = ChangeLog.objects.select_related("user", "branch").order_by("-timestamp")
    action_filter = request.GET.get("action", "")
    model_filter = request.GET.get("model", "")
    branch_filter = request.GET.get("branch", "")
    if action_filter:
        logs = logs.filter(action=action_filter)
    if model_filter:
        logs = logs.filter(model_name__icontains=model_filter)
    if branch_filter:
        logs = logs.filter(branch_id=branch_filter)
    paginator = Paginator(logs, 50)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "director/change_log.html", {
        "logs": page,
        "action_filter": action_filter,
        "model_filter": model_filter,
        "branch_filter": branch_filter,
        "branches": Branch.objects.all(),
    })


# ─────────────────────────────────────────
# BACKUP VIEWS
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def backup_history_view(request):
    logs = BackupLog.objects.all()
    return render(request, "director/backup_history.html", {"logs": logs})


@role_required("DIRECTOR")
def trigger_backup(request):
    """Responds immediately, runs backup in background to avoid timeout."""
    from django.http import JsonResponse
    from decouple import config as _config
    import threading as _threading
    import subprocess as _subprocess
    secret = request.GET.get('key', '')
    expected = _config('BACKUP_SECRET_KEY', default='')
    if expected and secret != expected:
        return JsonResponse({'error': 'unauthorized'}, status=403)
    def _run():
        try:
            _subprocess.run(
                ['python', '/opt/render/project/src/cron.py', 'backup'],
                timeout=300
            )
        except Exception:
            pass
    _threading.Thread(target=_run, daemon=True).start()
    return JsonResponse({'status': 'started', 'message': 'Backup running in background'})


def barcode_lookup(request):
    barcode = request.GET.get('barcode', '').strip()
    if not barcode:
        return JsonResponse({'found': False})
    try:
        product = Product.objects.filter(imei_serial__contains=barcode).first()
        if product:
            return JsonResponse({
                'found': True,
                'id': product.id,
                'name': product.model_name,
                'price': str(product.selling_price),
                'color': product.color,
                'imei': product.imei_serial,
                'source': 'partial_imei',
            })
        return JsonResponse({'found': False, 'message': 'No product found with this barcode/IMEI.'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ════════════════════════════════════════════
# CRON JOB ENDPOINTS — for cron-job.org / external schedulers
# ════════════════════════════════════════════

def _check_cron_secret(request):
    """Verify cron secret token from header or query param.
    Accepts CRON_SECRET, BACKUP_SECRET_KEY, ?secret= or ?key= params.
    """
    token = (
        request.headers.get('X-Cron-Secret') or
        request.GET.get('secret', '') or
        request.GET.get('key', '')
    )
    if not token:
        return False
    valid = [
        getattr(django_settings, 'CRON_SECRET', ''),
        getattr(django_settings, 'BACKUP_SECRET_KEY', ''),
    ]
    return token in [s for s in valid if s]

def cron_daily_digest(request):
    if not _check_cron_secret(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    from django.core.management import call_command
    from core.models import DirectorDailyDigest
    email = request.GET.get('email', django_settings.DEFAULT_FROM_EMAIL or '')
    if not email:
        return JsonResponse({'error': 'No email provided'}, status=400)
    try:
        call_command('daily_digest', email=email)
        return JsonResponse({'ok': True, 'message': 'Daily digest sent'})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)

def cron_backup(request):
    if not _check_cron_secret(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    from django.core.management import call_command
    email = request.GET.get('email', '')
    upload_supabase = request.GET.get('upload', '') == 'true'
    try:
        args = {'trigger': 'cron', 'send_email': email}
        if upload_supabase:
            args['upload_supabase'] = True
        call_command('backup_database', **args)
        return JsonResponse({'ok': True, 'message': 'Backup completed'})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)

def cron_stock_alert(request):
    if not _check_cron_secret(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    from django.core.management import call_command
    email = request.GET.get('email', django_settings.DEFAULT_FROM_EMAIL or '')
    if not email:
        return JsonResponse({'error': 'No email provided'}, status=400)
    try:
        call_command('stock_alert_email', email=email)
        return JsonResponse({'ok': True, 'message': 'Stock alerts sent'})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)

def cron_monthly_reset(request):
    if not _check_cron_secret(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    from django.core.management import call_command
    try:
        call_command('monthly_reset')
        return JsonResponse({'ok': True, 'message': 'Monthly reset completed'})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)



def offline_page(request):
    """PWA offline fallback page."""
    return render(request, "offline.html")


def pwa_manifest(request):
    """Serve PWA manifest.json."""
    import json as _json
    from django.http import HttpResponse as _HR
    manifest = {
        "name": "GPSL Business Suite",
        "short_name": "GPSL",
        "description": "Global Phonelinz Systems Limited",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#004F9F",
        "theme_color": "#004F9F",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"}
        ]
    }
    return _HR(_json.dumps(manifest), content_type="application/manifest+json")


def keepalive_ping(request):
    """Keep Render and Supabase awake. Ping from cron-job.org every 4 days."""
    from django.http import JsonResponse as _JR
    try:
        from django.db import connection as _conn
        with _conn.cursor() as c:
            c.execute("SELECT 1")
        return _JR({"status": "ok", "time": str(timezone.now())})
    except Exception as e:
        return _JR({"status": "error", "detail": str(e)}, status=500)


@role_required("DIRECTOR")
def manage_price_floors(request):
    from django.db.models import Q
    search = request.GET.get("search", "")
    products = Product.objects.all().select_related(
        "subcategory", "subcategory__category"
    ).order_by("model_name")

    if search:
        products = products.filter(
            Q(model_name__icontains=search) |
            Q(product_name__icontains=search)
        )

    if request.method == "POST":
        product_id = request.POST.get("product_id")
        new_price  = request.POST.get("selling_price")
        try:
            product = Product.objects.get(id=product_id)
            old_price = product.selling_price
            product.selling_price = Decimal(new_price)
            product.save()
            try:
                AuditLog.objects.create(
                    user=request.user,
                    action="UPDATE",
                    model_name="Product",
                    object_id=product.id,
                    description=(
                        f"Price updated: {product.model_name} "
                        f"N{old_price:,.2f} -> N{Decimal(new_price):,.2f}"
                    ),
                )
            except Exception:
                pass
            messages.success(
                request,
                f"{product.model_name} price updated to N{Decimal(new_price):,.0f}."
            )
        except Exception as e:
            messages.error(request, f"Error updating price: {e}")
        return redirect("manage_price_floors")

    return render(request, "director/price_floors.html", {
        "products": products,
        "search": search,
    })


def scan_barcode(request):
    """Barcode/IMEI scanner endpoint for retail dashboard."""
    barcode = request.GET.get('barcode', '').strip()
    if not barcode:
        return JsonResponse({'found': False, 'message': 'No barcode provided'})
    try:
        # Try exact IMEI match first
        product = Product.objects.filter(imei_serial=barcode).first()
        if not product:
            # Try partial match
            product = Product.objects.filter(
                imei_serial__contains=barcode
            ).first()
        if not product:
            # Try model name match
            product = Product.objects.filter(
                model_name__icontains=barcode
            ).first()
        if product:
            return JsonResponse({
                'found': True,
                'id': product.id,
                'name': product.model_name,
                'price': str(product.selling_price),
                'cost_price': str(product.cost_price),
                'imei': product.imei_serial or '',
                'category': product.subcategory.category.name if product.subcategory else '',
            })
        return JsonResponse({
            'found': False,
            'message': f'No product found for: {barcode}'
        })
    except Exception as e:
        return JsonResponse({'error': str(e), 'found': False}, status=500)


# ─────────────────────────────────────────
# MISSING VIEWS - Added by fix script
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def daily_summary_trigger(request):
    """Triggered by cron-job.org or GitHub Actions daily to email director summary."""
    from django.http import JsonResponse as _JR
    from decouple import config as _cfg
    import threading as _threading
    secret = request.GET.get("key", "")
    expected = _cfg("BACKUP_SECRET_KEY", default="")
    if expected and secret != expected:
        return _JR({"error": "unauthorized"}, status=403)
    def _run():
        try:
            send_daily_summary_email()
        except Exception:
            pass
    _threading.Thread(target=_run, daemon=True).start()
    return _JR({"status": "started", "message": "Daily digest running in background"})


@role_required("DIRECTOR")
def audit_log(request):
    """Director view - full audit log with date filters."""
    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to", "")
    search     = request.GET.get("search", "")
    action_flt = request.GET.get("action", "")
    model_flt  = request.GET.get("model", "")

    logs = AuditLog.objects.select_related("user").order_by("-timestamp")

    if date_from:
        logs = logs.filter(timestamp__date__gte=date_from)
    if date_to:
        logs = logs.filter(timestamp__date__lte=date_to)
    if search:
        logs = logs.filter(
            Q(description__icontains=search) |
            Q(user__username__icontains=search)
        )
    if action_flt:
        logs = logs.filter(action=action_flt)
    if model_flt:
        logs = logs.filter(model_name__icontains=model_flt)

    paginator = Paginator(logs, 50)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "director/audit_log.html", {
        "logs": page,
        "date_from": date_from,
        "date_to": date_to,
        "search": search,
        "action_flt": action_flt,
        "model_flt": model_flt,
        "action_choices": ["CREATE", "UPDATE", "DELETE", "VIEW"],
    })


@role_required("DIRECTOR")
def change_log(request):
    """Director view - change log with date filters."""
    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")
    search    = request.GET.get("search", "")

    logs = AuditLog.objects.filter(
        action__in=["UPDATE", "DELETE"]
    ).select_related("user").order_by("-timestamp")

    if date_from:
        logs = logs.filter(timestamp__date__gte=date_from)
    if date_to:
        logs = logs.filter(timestamp__date__lte=date_to)
    if search:
        logs = logs.filter(
            Q(description__icontains=search) |
            Q(user__username__icontains=search) |
            Q(model_name__icontains=search)
        )

    paginator = Paginator(logs, 50)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "director/change_log.html", {
        "logs": page,
        "date_from": date_from,
        "date_to": date_to,
        "search": search,
    })


@role_required("DIRECTOR")
def all_branch_stock(request):
    """Director view - all branch safe stock with date and branch filters."""
    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to", "")
    branch_flt = request.GET.get("branch", "")
    search     = request.GET.get("search", "")
    export     = request.GET.get("export", "")

    stocks = BranchSafeStock.objects.select_related(
        "product", "branch", "product__subcategory"
    ).order_by("branch__name", "product__model_name")

    if branch_flt:
        stocks = stocks.filter(branch_id=branch_flt)
    if search:
        stocks = stocks.filter(
            Q(product__model_name__icontains=search) |
            Q(branch__name__icontains=search)
        )
    if date_from:
        stocks = stocks.filter(date_added__date__gte=date_from)
    if date_to:
        stocks = stocks.filter(date_added__date__lte=date_to)

    total_value = sum(
        (s.quantity * s.product.selling_price) for s in stocks
    )
    total_units = sum(s.quantity for s in stocks)

    # Group by branch
    branch_stock = {}
    for s in stocks:
        bname = s.branch.name
        if bname not in branch_stock:
            branch_stock[bname] = {
                "items": [], "total_units": 0, "total_value": Decimal(0)
            }
        val = s.quantity * s.product.selling_price
        branch_stock[bname]["items"].append({
            "product": s.product.model_name,
            "quantity": s.quantity,
            "selling_price": s.product.selling_price,
            "cost_price": s.product.cost_price,
            "value": val,
            "category": s.product.subcategory.category.name if s.product.subcategory else "—",
        })
        branch_stock[bname]["total_units"] += s.quantity
        branch_stock[bname]["total_value"] += val

    if export == "pdf":
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.enums import TA_CENTER
        import io
        BLUE = colors.HexColor("#004F9F")
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, rightMargin=0.5*inch, leftMargin=0.5*inch,
                                topMargin=0.6*inch, bottomMargin=0.6*inch)
        styles = getSampleStyleSheet()
        elements = [
            Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED",
                ParagraphStyle("T", parent=styles["Heading1"], fontSize=13,
                               textColor=BLUE, alignment=TA_CENTER)),
            Paragraph(f"All Branch Stock Report | {date_from or 'All'} to {date_to or 'Today'}",
                ParagraphStyle("S", parent=styles["Normal"], fontSize=8,
                               textColor=colors.grey, alignment=TA_CENTER, spaceAfter=10)),
        ]
        data = [["Branch", "Product", "Category", "Qty", "Sell Price", "Value"]]
        for bname, bdata in branch_stock.items():
            for item in bdata["items"]:
                data.append([
                    bname, item["product"], item["category"],
                    str(item["quantity"]),
                    f"N{item['selling_price']:,.0f}",
                    f"N{item['value']:,.0f}",
                ])
        t = Table(data, repeatRows=1)
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
        fname = f"AllBranchStock_{date_from or 'All'}_{date_to or 'Today'}.pdf"
        return HttpResponse(buf, content_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    return render(request, "director/all_branch_stock.html", {
        "branch_stock": branch_stock,
        "total_value": total_value,
        "total_units": total_units,
        "branches": Branch.objects.all(),
        "date_from": date_from,
        "date_to": date_to,
        "branch_flt": branch_flt,
        "search": search,
    })
@role_required("DIRECTOR")
def catalog_management(request):
    """Director page to manage landing page slideshow and products."""
    from core.models import SlideShowItem, CatalogCategory, CatalogProduct

    slides   = SlideShowItem.objects.all()
    cats     = CatalogCategory.objects.all()
    products = CatalogProduct.objects.select_related('category').all()

    return render(request, "director/catalog_management.html", {
        "slides": slides,
        "cats": cats,
        "products": products,
    })


@role_required("DIRECTOR")
def catalog_add_slide(request):
    from core.models import SlideShowItem
    if request.method == "POST":
        try:
            slide = SlideShowItem(
                title    = request.POST.get("title","").strip(),
                subtitle = request.POST.get("subtitle","").strip(),
                badge_text = request.POST.get("badge_text","").strip(),
                price    = request.POST.get("price") or None,
                old_price = request.POST.get("old_price") or None,
                cta_text = request.POST.get("cta_text","Order on WhatsApp").strip(),
                whatsapp_msg = request.POST.get("whatsapp_msg","").strip(),
                image_url = request.POST.get("image_url","").strip(),
                is_active = request.POST.get("is_active") == "on",
                order    = int(request.POST.get("order",0) or 0),
            )
            if "image" in request.FILES:
                slide.image = request.FILES["image"]
            slide.save()
            messages.success(request, f"Slide '{slide.title}' added.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("catalog_management")


@role_required("DIRECTOR")
def catalog_edit_slide(request, slide_id):
    from core.models import SlideShowItem
    slide = get_object_or_404(SlideShowItem, id=slide_id)
    if request.method == "POST":
        try:
            slide.title      = request.POST.get("title","").strip()
            slide.subtitle   = request.POST.get("subtitle","").strip()
            slide.badge_text = request.POST.get("badge_text","").strip()
            slide.price      = request.POST.get("price") or None
            slide.old_price  = request.POST.get("old_price") or None
            slide.cta_text   = request.POST.get("cta_text","Order on WhatsApp").strip()
            slide.whatsapp_msg = request.POST.get("whatsapp_msg","").strip()
            slide.image_url  = request.POST.get("image_url","").strip()
            slide.is_active  = request.POST.get("is_active") == "on"
            slide.order      = int(request.POST.get("order",0) or 0)
            if "image" in request.FILES:
                slide.image = request.FILES["image"]
            slide.save()
            messages.success(request, f"Slide updated.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("catalog_management")


@role_required("DIRECTOR")
def catalog_delete_slide(request, slide_id):
    from core.models import SlideShowItem
    if request.method == "POST":
        get_object_or_404(SlideShowItem, id=slide_id).delete()
        messages.success(request, "Slide deleted.")
    return redirect("catalog_management")


@role_required("DIRECTOR")
def catalog_add_product(request):
    from core.models import CatalogProduct, CatalogCategory
    if request.method == "POST":
        try:
            cat_id = request.POST.get("category")
            cat    = CatalogCategory.objects.get(id=cat_id) if cat_id else None
            prod   = CatalogProduct(
                category    = cat,
                name        = request.POST.get("name","").strip(),
                description = request.POST.get("description","").strip(),
                price       = request.POST.get("price",0),
                old_price   = request.POST.get("old_price") or None,
                badge       = request.POST.get("badge","").strip(),
                condition   = request.POST.get("condition","NEW"),
                is_available = request.POST.get("is_available") == "on",
                is_featured = request.POST.get("is_featured") == "on",
                whatsapp_msg = request.POST.get("whatsapp_msg","").strip(),
                image_url   = request.POST.get("image_url","").strip(),
                order       = int(request.POST.get("order",0) or 0),
            )
            if "image" in request.FILES:
                prod.image = request.FILES["image"]
            prod.save()
            messages.success(request, f"Product '{prod.name}' added.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("catalog_management")


@role_required("DIRECTOR")
def catalog_edit_product(request, product_id):
    from core.models import CatalogProduct, CatalogCategory
    prod = get_object_or_404(CatalogProduct, id=product_id)
    if request.method == "POST":
        try:
            cat_id = request.POST.get("category")
            prod.category    = CatalogCategory.objects.get(id=cat_id) if cat_id else None
            prod.name        = request.POST.get("name","").strip()
            prod.description = request.POST.get("description","").strip()
            prod.price       = request.POST.get("price",0)
            prod.old_price   = request.POST.get("old_price") or None
            prod.badge       = request.POST.get("badge","").strip()
            prod.condition   = request.POST.get("condition","NEW")
            prod.is_available = request.POST.get("is_available") == "on"
            prod.is_featured = request.POST.get("is_featured") == "on"
            prod.whatsapp_msg = request.POST.get("whatsapp_msg","").strip()
            prod.image_url   = request.POST.get("image_url","").strip()
            prod.order       = int(request.POST.get("order",0) or 0)
            if "image" in request.FILES:
                prod.image = request.FILES["image"]
            prod.save()
            messages.success(request, "Product updated.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("catalog_management")


@role_required("DIRECTOR")
def catalog_delete_product(request, product_id):
    from core.models import CatalogProduct
    if request.method == "POST":
        get_object_or_404(CatalogProduct, id=product_id).delete()
        messages.success(request, "Product deleted.")
    return redirect("catalog_management")


@role_required("DIRECTOR")
def catalog_add_category(request):
    from core.models import CatalogCategory
    if request.method == "POST":
        name  = request.POST.get("name","").strip()
        icon  = request.POST.get("icon","").strip()
        order = int(request.POST.get("order",0) or 0)
        if name:
            CatalogCategory.objects.create(name=name, icon=icon, order=order)
            messages.success(request, f"Category '{name}' added.")
    return redirect("catalog_management")


def landing_page(request):
    """
    Root URL handler.
    globalphonelinz.com  -> landing page
    app.globalphonelinz.com -> redirect to login
    """
    from core.models import SlideShowItem, CatalogCategory, CatalogProduct
    host = request.get_host().lower()
    if 'app.' in host:
        return redirect('login')

    slides   = SlideShowItem.objects.filter(is_active=True).order_by('order')
    cats     = CatalogCategory.objects.all()
    featured = CatalogProduct.objects.filter(
        is_available=True, is_featured=True
    ).select_related('category').order_by('order')[:8]
    all_products = CatalogProduct.objects.filter(
        is_available=True
    ).select_related('category').order_by('order')

    # Seed placeholder slides if none exist
    if not slides.exists():
        SlideShowItem.objects.bulk_create([
            SlideShowItem(title="Latest iPhones — Best Prices in Uyo", subtitle="Brand new, sealed in box. All models available.", badge_text="NEW ARRIVAL", price=650000, old_price=720000, order=1),
            SlideShowItem(title="MTN SIM Registration — Fast & Easy", subtitle="Get your SIM registered in minutes. NIN linking available.", badge_text="FREE SERVICE", order=2),
            SlideShowItem(title="DStv & GOtv Subscriptions", subtitle="Renew or start a new subscription today at all branches.", badge_text="HOT DEAL", order=3),
        ])
        slides = SlideShowItem.objects.filter(is_active=True).order_by('order')

    # Seed placeholder categories if none exist
    if not cats.exists():
        CatalogCategory.objects.bulk_create([
            CatalogCategory(name="Phones", icon="📱", order=1),
            CatalogCategory(name="Accessories", icon="🎧", order=2),
            CatalogCategory(name="MiFi & Routers", icon="📡", order=3),
            CatalogCategory(name="DStv & GOtv", icon="📺", order=4),
        ])
        cats = CatalogCategory.objects.all()

    return render(request, "landing.html", {
        "slides": slides,
        "cats": cats,
        "featured": featured,
        "all_products": all_products,
        "whatsapp_number": "2348032036766",
    })



# ─────────────────────────────────────────────────────────────
# ADD THESE VIEWS TO core/views.py
# All go at the end of the file
# ─────────────────────────────────────────────────────────────


# ── ROUTER SUBSCRIPTION VIEWS (Telecom Staff) ──

@role_required("TELECOM")
def router_subscriptions(request):
    """Telecom staff - view and add router subscriptions."""
    from datetime import date, timedelta
    from core.models import RouterSubscription

    today = date.today()
    subs = RouterSubscription.objects.filter(
        staff=request.user, is_active=True
    ).order_by('expiry_date')

    # Categorise
    expired    = [s for s in subs if s.is_expired]
    critical   = [s for s in subs if not s.is_expired and s.days_to_expiry <= 3]
    warning    = [s for s in subs if not s.is_expired and 3 < s.days_to_expiry <= 7]
    active     = [s for s in subs if not s.is_expired and s.days_to_expiry > 7]

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add":
            try:
                from datetime import datetime
                sub_date_str = request.POST.get("subscription_date")
                sub_date = datetime.strptime(sub_date_str, "%Y-%m-%d").date() if sub_date_str else today

                RouterSubscription.objects.create(
                    staff=request.user,
                    branch=request.user.branch,
                    customer_name=request.POST.get("customer_name","").strip(),
                    customer_phone=request.POST.get("customer_phone","").strip(),
                    alt_phone=request.POST.get("alt_phone","").strip(),
                    router_number=request.POST.get("router_number","").strip(),
                    router_type=request.POST.get("router_type","4G"),
                    network=request.POST.get("network","MTN").strip(),
                    subscription_date=sub_date,
                    month_number=int(request.POST.get("month_number",1)),
                    amount=request.POST.get("amount",0) or 0,
                    notes=request.POST.get("notes","").strip(),
                )
                messages.success(request, "Router subscription recorded successfully.")
            except Exception as e:
                messages.error(request, f"Error: {e}")
            return redirect("router_subscriptions")

        elif action == "renew":
            sub_id = request.POST.get("sub_id")
            try:
                sub = RouterSubscription.objects.get(id=sub_id, staff=request.user)
                # Create a new renewal record
                RouterSubscription.objects.create(
                    staff=request.user,
                    branch=request.user.branch,
                    customer_name=sub.customer_name,
                    customer_phone=sub.customer_phone,
                    alt_phone=sub.alt_phone,
                    router_number=sub.router_number,
                    router_type=sub.router_type,
                    network=sub.network,
                    subscription_date=today,
                    month_number=sub.month_number + 1,
                    amount=request.POST.get("amount", sub.amount) or sub.amount,
                    notes=f"Renewal of subscription #{sub.id}",
                )
                # Mark old one inactive
                sub.is_active = False
                sub.save()
                messages.success(request, f"Subscription renewed for {sub.customer_name}.")
            except Exception as e:
                messages.error(request, f"Error: {e}")
            return redirect("router_subscriptions")

    return render(request, "telecom/router_subscriptions.html", {
        "subs": subs,
        "expired": expired,
        "critical": critical,
        "warning": warning,
        "active_subs": active,
        "today": today,
        "total": subs.count(),
        "expired_count": len(expired),
        "critical_count": len(critical),
    })


@role_required("DIRECTOR", "MANAGER")
def router_subscriptions_overview(request):
    """Manager/Director - see all router subscriptions across staff/branches."""
    from datetime import date
    from core.models import RouterSubscription

    today = date.today()
    branch_flt = request.GET.get("branch", "")
    staff_flt  = request.GET.get("staff", "")
    status_flt = request.GET.get("status", "")

    try:
        subs = RouterSubscription.objects.filter(
            is_active=True
        ).select_related("staff", "branch").order_by("expiry_date")
    except Exception:
        from django.shortcuts import render as _r
        from core.models import Branch as _B
        return _r(request, "director/router_subscriptions_overview.html", {
            "subs": [], "total": 0, "expired_count": 0,
            "critical_count": 0, "warning_count": 0,
            "branches": _B.objects.all(), "staff_list": [],
            "branch_flt": "", "staff_flt": "", "status_flt": "",
            "today": today,
            "error": "Router subscriptions table not yet created. Run python manage.py migrate.",
        })

    # Managers only see their branch
    if request.user.role == "MANAGER" and request.user.branch:
        subs = subs.filter(branch=request.user.branch)
    elif branch_flt:
        subs = subs.filter(branch_id=branch_flt)

    if staff_flt:
        subs = subs.filter(staff_id=staff_flt)

    # Status filter
    all_subs = list(subs)
    if status_flt == "expired":
        all_subs = [s for s in all_subs if s.is_expired]
    elif status_flt == "critical":
        all_subs = [s for s in all_subs if not s.is_expired and s.days_to_expiry <= 3]
    elif status_flt == "warning":
        all_subs = [s for s in all_subs if not s.is_expired and 3 < s.days_to_expiry <= 7]
    elif status_flt == "active":
        all_subs = [s for s in all_subs if not s.is_expired and s.days_to_expiry > 7]

    expired_count  = sum(1 for s in subs if s.is_expired)
    critical_count = sum(1 for s in subs if not s.is_expired and s.days_to_expiry <= 3)
    warning_count  = sum(1 for s in subs if not s.is_expired and 3 < s.days_to_expiry <= 7)

    from core.models import Branch, User as UserModel
    branches = Branch.objects.all()
    staff_list = UserModel.objects.filter(role="TELECOM").order_by("username")
    if request.user.role == "MANAGER" and request.user.branch:
        staff_list = staff_list.filter(branch=request.user.branch)

    return render(request, "director/router_subscriptions_overview.html", {
        "subs": all_subs,
        "total": subs.count(),
        "expired_count": expired_count,
        "critical_count": critical_count,
        "warning_count": warning_count,
        "branches": branches,
        "staff_list": staff_list,
        "branch_flt": branch_flt,
        "staff_flt": staff_flt,
        "status_flt": status_flt,
        "today": today,
    })


@role_required("DIRECTOR", "MULTICHOICE")
def mc_subscription_retention(request):
    """Director - MultiChoice customer retention overview."""
    from datetime import date, timedelta
    from django.db.models import Count, Q

    today = date.today()
    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")
    branch_flt = request.GET.get("branch", "")

    sales = MultiChoiceSale.objects.select_related("staff", "branch").order_by("-date")

    if branch_flt:
        sales = sales.filter(branch_id=branch_flt)
    if date_from:
        sales = sales.filter(date__gte=date_from)
    if date_to:
        sales = sales.filter(date__lte=date_to)

    # Get all MC sales and filter in Python (expiry_date may not be migrated yet)
    all_mc = MultiChoiceSale.objects.select_related("staff", "branch").order_by("-date")
    if branch_flt:
        all_mc = all_mc.filter(branch_id=branch_flt)

    # Calculate expiry in Python (date + 30 days) if field not available
    expiring_soon = []
    expired = []
    for sale in all_mc:
        try:
            exp = sale.expiry_date
        except Exception:
            exp = None
        if exp is None:
            from datetime import timedelta as _td
            try:
                sale_date = sale.date
                if hasattr(sale_date, 'date'):
                    sale_date = sale_date.date()
                exp = sale_date + _td(days=30)
            except Exception:
                continue
        days_left = (exp - today).days
        sale.computed_expiry = exp
        sale.computed_days_left = days_left
        if 0 <= days_left <= 7:
            expiring_soon.append(sale)
        elif -14 <= days_left < 0:
            expired.append(sale)

    # Renewal rate
    renewed_phones = MultiChoiceSale.objects.values("customer_phone").annotate(
        count=Count("id")
    ).filter(count__gt=1, customer_phone__isnull=False).exclude(customer_phone="")

    from core.models import Branch
    branches = Branch.objects.all()

    return render(request, "director/mc_retention.html", {
        "expiring_soon": expiring_soon,
        "expired": expired,
        "renewed_count": renewed_phones.count(),
        "expiring_count": len(expiring_soon),
        "expired_count": len(expired),
        "total_customers": MultiChoiceSale.objects.values("customer_phone").distinct().count(),
        "branches": branches,
        "branch_flt": branch_flt,
        "date_from": date_from,
        "date_to": date_to,
        "today": today,
    })




# ─────────────────────────────────────────
# STOCK TRANSFER — Branch to Branch, Director, Staff
# ─────────────────────────────────────────

@role_required("DIRECTOR", "MANAGER")
def stock_transfer(request):
    """Record a stock transfer between any two parties."""
    from core.models import (
        StockTransfer, DirectorSafeStock, BranchSafeStock,
        StaffStock, Product, Branch
    )
    from django.utils import timezone as _tz

    branches = Branch.objects.all()
    products = Product.objects.all().order_by('model_name')
    staff_list = User.objects.filter(
        role__in=['RETAIL', 'TELECOM', 'MULTICHOICE']
    ).order_by('username')

    # For managers, limit to their branch
    if request.user.role == 'MANAGER':
        staff_list = staff_list.filter(branch=request.user.branch)

    if request.method == 'POST':
        try:
            transfer_type = request.POST.get('transfer_type')
            product_id    = request.POST.get('product')
            quantity      = int(request.POST.get('quantity', 0))
            notes         = request.POST.get('notes', '').strip()
            from_branch_id = request.POST.get('from_branch') or None
            to_branch_id   = request.POST.get('to_branch') or None
            to_staff_id    = request.POST.get('to_staff') or None

            product  = get_object_or_404(Product, id=product_id)
            from_branch = Branch.objects.get(id=from_branch_id) if from_branch_id else None
            to_branch   = Branch.objects.get(id=to_branch_id) if to_branch_id else None
            to_staff    = User.objects.get(id=to_staff_id) if to_staff_id else None

            if quantity <= 0:
                messages.error(request, 'Quantity must be greater than 0.')
                return redirect('stock_transfer')

            # Deduct from source
            if transfer_type == 'DIRECTOR_TO_BRANCH':
                src = DirectorSafeStock.objects.filter(product=product).first()
                if not src or src.quantity < quantity:
                    messages.error(request, f'Insufficient stock in Director Safe. Available: {src.quantity if src else 0}')
                    return redirect('stock_transfer')
                src.quantity -= quantity
                src.save()
                # Add to branch
                dst, _ = BranchSafeStock.objects.get_or_create(product=product, branch=to_branch)
                dst.quantity += quantity
                dst.save()

            elif transfer_type == 'BRANCH_TO_BRANCH':
                src = BranchSafeStock.objects.filter(product=product, branch=from_branch).first()
                if not src or src.quantity < quantity:
                    messages.error(request, f'Insufficient stock in {from_branch.name}. Available: {src.quantity if src else 0}')
                    return redirect('stock_transfer')
                src.quantity -= quantity
                src.save()
                dst, _ = BranchSafeStock.objects.get_or_create(product=product, branch=to_branch)
                dst.quantity += quantity
                dst.save()

            elif transfer_type == 'BRANCH_TO_STAFF':
                src = BranchSafeStock.objects.filter(product=product, branch=from_branch).first()
                if not src or src.quantity < quantity:
                    messages.error(request, f'Insufficient stock in {from_branch.name}. Available: {src.quantity if src else 0}')
                    return redirect('stock_transfer')
                src.quantity -= quantity
                src.save()
                dst, _ = StaffStock.objects.get_or_create(product=product, staff=to_staff)
                dst.quantity += quantity
                dst.save()

            elif transfer_type == 'BRANCH_TO_DIRECTOR':
                src = BranchSafeStock.objects.filter(product=product, branch=from_branch).first()
                if not src or src.quantity < quantity:
                    messages.error(request, f'Insufficient stock in {from_branch.name}. Available: {src.quantity if src else 0}')
                    return redirect('stock_transfer')
                src.quantity -= quantity
                src.save()
                dst, _ = DirectorSafeStock.objects.get_or_create(product=product)
                dst.quantity += quantity
                dst.save()

            elif transfer_type == 'STAFF_TO_BRANCH':
                src = StaffStock.objects.filter(product=product, staff=to_staff).first()
                if not src or src.quantity < quantity:
                    messages.error(request, f'Insufficient stock with {to_staff.username}. Available: {src.quantity if src else 0}')
                    return redirect('stock_transfer')
                src.quantity -= quantity
                src.save()
                dst, _ = BranchSafeStock.objects.get_or_create(product=product, branch=to_branch)
                dst.quantity += quantity
                dst.save()

            # Record transfer
            StockTransfer.objects.create(
                transfer_type=transfer_type,
                product=product,
                quantity=quantity,
                status='COMPLETED',
                notes=notes,
                from_branch=from_branch,
                to_branch=to_branch,
                to_staff=to_staff,
                initiated_by=request.user,
                approved_by=request.user,
                completed_at=_tz.now(),
            )

            # Audit log
            try:
                AuditLog.objects.create(
                    user=request.user,
                    action='TRANSFER',
                    model_name='StockTransfer',
                    description=f"Transferred {quantity}x {product.model_name}: {from_branch.name if from_branch else 'Director'} → {to_branch.name if to_branch else (to_staff.username if to_staff else 'Director')}"
                )
            except Exception:
                pass

            messages.success(request, f"Transfer complete: {quantity}x {product.model_name} moved successfully.")
        except Exception as e:
            messages.error(request, f"Transfer failed: {e}")
        return redirect('stock_transfer')

    # Recent transfers
    transfers = StockTransfer.objects.select_related(
        'product', 'from_branch', 'to_branch', 'to_staff', 'initiated_by'
    ).order_by('-created_at')[:50]

    if request.user.role == 'MANAGER':
        transfers = transfers.filter(
            Q(from_branch=request.user.branch) | Q(to_branch=request.user.branch)
        )

    return render(request, 'stock_transfer.html', {
        'branches': branches,
        'products': products,
        'staff_list': staff_list,
        'transfers': transfers,
        'today': timezone.now().date(),
    })


@role_required("DIRECTOR")
def stock_transfer_history(request):
    """Director - full stock transfer history with filters."""
    from core.models import StockTransfer
    date_from   = request.GET.get('date_from', '')
    date_to     = request.GET.get('date_to', '')
    branch_flt  = request.GET.get('branch', '')
    type_flt    = request.GET.get('type', '')

    transfers = StockTransfer.objects.select_related(
        'product', 'from_branch', 'to_branch', 'to_staff', 'initiated_by'
    ).order_by('-created_at')

    if date_from:
        transfers = transfers.filter(created_at__date__gte=date_from)
    if date_to:
        transfers = transfers.filter(created_at__date__lte=date_to)
    if branch_flt:
        transfers = transfers.filter(
            Q(from_branch_id=branch_flt) | Q(to_branch_id=branch_flt)
        )
    if type_flt:
        transfers = transfers.filter(transfer_type=type_flt)

    from core.models import Branch
    return render(request, 'director/stock_transfer_history.html', {
        'transfers': transfers[:200],
        'branches': Branch.objects.all(),
        'date_from': date_from,
        'date_to': date_to,
        'branch_flt': branch_flt,
        'type_flt': type_flt,
        'transfer_types': StockTransfer.TRANSFER_TYPE_CHOICES,
    })


def custom_password_reset(request):
    """
    Password reset with username + email verification.
    Both must match the account before sending reset email.
    """
    from django.contrib.auth.forms import PasswordResetForm
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    from django.utils.http import urlsafe_base64_encode
    from django.utils.encoding import force_bytes
    from django.contrib.auth.tokens import default_token_generator
    import threading

    error = None
    success = False

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email    = request.POST.get('email', '').strip().lower()

        try:
            user = User.objects.get(username__iexact=username)
            if user.email.lower() != email:
                error = "The email address does not match our records for this username."
            else:
                # Send reset email in background thread
                def send_reset():
                    try:
                        token = default_token_generator.make_token(user)
                        uid   = urlsafe_base64_encode(force_bytes(user.pk))
                        domain = request.get_host()
                        protocol = 'https' if request.is_secure() else 'http'
                        reset_url = f"{protocol}://{domain}/reset/{uid}/{token}/"

                        subject = "GPSL Business Suite - Password Reset"
                        body = f"""Hello {user.username},

You requested a password reset for your GPSL Business Suite account.

Click the link below to set a new password:
{reset_url}

This link expires in 3 days.

If you did not request this, ignore this email.

— GPSL Business Suite
"""
                        send_mail(
                            subject, body,
                            settings.DEFAULT_FROM_EMAIL,
                            [user.email],
                            fail_silently=False
                        )
                    except Exception as e:
                        pass

                threading.Thread(target=send_reset, daemon=True).start()
                success = True
        except User.DoesNotExist:
            error = "No account found with that username."

    return render(request, 'registration/password_reset_form.html', {
        'error': error,
        'success': success,
        'custom_reset': True,
    })
