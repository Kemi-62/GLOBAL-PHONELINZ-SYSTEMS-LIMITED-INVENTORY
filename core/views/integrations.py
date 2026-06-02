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

    lp.points_balance -= points
    lp.total_redeemed += points
    lp.save(update_fields=["points_balance", "total_redeemed"])

    LoyaltyTransaction.objects.create(
        loyalty_point=lp,
        transaction_type="REDEEM",
        points=points,
        description=description,
        created_by=request.user,
    )

    log_action(request.user, "UPDATE", "LoyaltyPoint", f"Redeemed {points} points for {phone}")
    return JsonResponse({
        "success": True,
        "points_redeemed": points,
        "remaining_balance": lp.points_balance,
        "message": f"Redeemed {points} points. Remaining: {lp.points_balance}",
    })

