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

@role_required("MULTICHOICE")
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


def record_retail_sale(request):
    if request.method == "POST":
        product_id     = request.POST.get("product")
        quantity       = int(request.POST.get("quantity", 0))
        selling_price  = Decimal(request.POST.get("selling_price", 0))
        payment_method = request.POST.get("payment_method", "CASH")
        customer_name  = request.POST.get("customer_name", "").strip()
        customer_phone = request.POST.get("customer_phone", "").strip()

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

            sale = RetailSale.objects.create(
                staff=request.user,
                branch=request.user.branch,
                product=product,
                quantity=quantity,
                selling_price=selling_price,
                payment_method=payment_method,
                customer_phone=customer_phone,
            )

            # Update Customer CRM
            if customer_phone:
                _upsert_customer(
                    phone=customer_phone,
                    name=customer_name,
                    branch=request.user.branch,
                    amount=quantity * selling_price,
                    source="RETAIL",
                )

        messages.success(request, f"Sale recorded. ₦{quantity * selling_price:,.0f} — {product.model_name}.")
    return redirect("retail_dashboard")


# ─────────────────────────────────────────
# FIXED record_multichoice_sale — updates Customer CRM
# ─────────────────────────────────────────

@role_required("MULTICHOICE")
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
        "sales_history": sales_history,
        "low_stock_items": low_stock_items,
        "out_of_stock": out_of_stock,
    })


# ─────────────────────────────────────────
# MANAGER DASHBOARD — with stock alerts + service target form
# ─────────────────────────────────────────

@role_required("MANAGER")
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

