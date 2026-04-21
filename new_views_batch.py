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
            total_late=Count("id", filter=models.Q(is_late=True)),
            total_absent=Count("id", filter=models.Q(is_absent=True)),
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
