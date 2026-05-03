
# ─────────────────────────────────────────
# HELPER: Save/update customer record from any dashboard
# ─────────────────────────────────────────

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
        return customer
    except Exception:
        return None


# ─────────────────────────────────────────
# FIXED record_retail_sale — captures customer name + phone
# ─────────────────────────────────────────

@role_required("RETAIL")
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
def record_multichoice_sale(request):
    if request.method == "POST":
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())

        weekly_report, _ = MultiChoiceWeeklyReport.objects.get_or_create(
            staff=request.user,
            branch=request.user.branch,
            week_start_date=week_start,
            defaults={"opening_balance": Decimal("0"), "additional_funds": Decimal("0")}
        )

        cost_price     = Decimal(request.POST.get("cost_price") or "0")
        amount         = Decimal(request.POST.get("amount") or "0")
        customer_name  = request.POST.get("customer_name", "")
        customer_phone = request.POST.get("customer_phone", "")
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
            weekly_report.total_subscriptions = (
                weekly_report.total_subscriptions or Decimal("0")
            ) + amount
            weekly_report.save(update_fields=["total_subscriptions"])

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
