import requests as _requests

# ─────────────────────────────────────────
# WHATSAPP VIA CALLMEBOT
# ─────────────────────────────────────────

def send_whatsapp(phone, message):
    """
    Send WhatsApp message via CallMeBot.
    phone: international format without + e.g. 2348012345678
    Requires CALLMEBOT_API_KEY in .env
    """
    try:
        from django.conf import settings
        api_key = getattr(settings, 'CALLMEBOT_API_KEY', '')
        if not api_key or not phone:
            return False
        url = "https://api.callmebot.com/whatsapp.php"
        params = {
            "phone": phone,
            "text": message,
            "apikey": api_key,
        }
        resp = _requests.get(url, params=params, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def _get_director_phone():
    """Get the director's WhatsApp phone number from settings."""
    from django.conf import settings
    return getattr(settings, 'DIRECTOR_WHATSAPP', '')


# ─────────────────────────────────────────
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
