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

