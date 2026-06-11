
# ─────────────────────────────────────────
# FIXED record_retail_sale
# Price is LOCKED — taken from product, not from form input
# Staff cannot change price during sale
# ─────────────────────────────────────────

@role_required("RETAIL")
def record_retail_sale(request):
    if request.method == "POST":
        product_id     = request.POST.get("product")
        quantity       = int(request.POST.get("quantity", 0))
        payment_method = request.POST.get("payment_method", "CASH")
        customer_name  = request.POST.get("customer_name", "").strip()
        customer_phone = request.POST.get("customer_phone", "").strip()

        product = get_object_or_404(Product, id=product_id)

        # PRICE LOCK: always use the approved product price, ignore any form input
        selling_price = product.selling_price

        try:
            staff_stock = StaffStock.objects.get(staff=request.user, product=product)
        except StaffStock.DoesNotExist:
            messages.error(request, "You do not have this product in stock.")
            return redirect("retail_dashboard")

        if quantity <= 0:
            messages.error(request, "Quantity must be at least 1.")
            return redirect("retail_dashboard")

        if quantity > staff_stock.quantity:
            messages.error(
                request,
                f"Insufficient stock. You have {staff_stock.quantity} unit(s) of {product.model_name}."
            )
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

            # Audit log
            try:
                from core.models import AuditLog
                AuditLog.objects.create(
                    user=request.user,
                    action="CREATE",
                    model_name="RetailSale",
                    object_id=sale.id,
                    description=(
                        f"Sale: {quantity}x {product.model_name} @ "
                        f"N{selling_price:,.2f} = N{quantity * selling_price:,.2f}. "
                        f"Payment: {payment_method}. Ref: GPSL-{sale.id:05d}."
                    ),
                )
            except Exception:
                pass

        messages.success(
            request,
            f"Sale recorded. GPSL-{sale.id:05d} | "
            f"{product.model_name} x{quantity} | "
            f"N{quantity * selling_price:,.2f} | {payment_method}."
        )
    return redirect("retail_dashboard")


# ─────────────────────────────────────────
# KEEPALIVE PING — for cron-job.org
# Keeps Render and Supabase awake
# ─────────────────────────────────────────

def keepalive_ping(request):
    from django.http import JsonResponse
    try:
        from django.db import connection
        with connection.cursor() as c:
            c.execute("SELECT 1")
        return JsonResponse({
            "status": "ok",
            "time": str(timezone.now()),
            "app": "GPSL ERP",
        })
    except Exception as e:
        return JsonResponse({"status": "error", "detail": str(e)}, status=500)


# ─────────────────────────────────────────
# DAILY EMAIL SUMMARY TO DIRECTOR
# Called by cron-job.org every day at 8pm
# ─────────────────────────────────────────

def send_daily_summary_email(request=None):
    """
    Send a daily summary email to the director.
    Can be called as a view (via cron URL) or directly from cron.py.
    """
    from django.core.mail import send_mail
    from django.conf import settings
    from django.template.loader import render_to_string
    from django.http import JsonResponse

    today = timezone.now().date()

    # Gather all data
    branches = Branch.objects.all()
    all_sales = RetailSale.objects.filter(date=today, is_voided=False)
    all_mc    = MultiChoiceSale.objects.filter(date=today)
    all_exp   = Expense.objects.filter(date=today)
    all_att   = Attendance.objects.filter(date=today)
    low_stock = BranchSafeStock.objects.filter(
        quantity__lte=3
    ).select_related("product", "branch")

    total_retail_rev = all_sales.aggregate(
        t=Sum(F("quantity") * F("selling_price"))
    )["t"] or 0
    total_mc_rev  = all_mc.aggregate(t=Sum("amount"))["t"] or 0
    total_expenses = all_exp.aggregate(t=Sum("amount"))["t"] or 0
    total_present  = all_att.count()
    total_late     = all_att.filter(is_late=True).count()
    total_absent   = all_att.filter(is_absent=True).count()

    # Per branch summary
    branch_summaries = []
    for branch in branches:
        branch_sales = all_sales.filter(branch=branch)
        branch_mc    = all_mc.filter(branch=branch)
        branch_exp   = all_exp.filter(branch=branch)
        branch_att   = all_att.filter(branch=branch)

        rev = branch_sales.aggregate(
            t=Sum(F("quantity") * F("selling_price"))
        )["t"] or 0
        mc  = branch_mc.aggregate(t=Sum("amount"))["t"] or 0
        exp = branch_exp.aggregate(t=Sum("amount"))["t"] or 0

        branch_summaries.append({
            "name": branch.name,
            "retail_revenue": rev,
            "mc_revenue": mc,
            "expenses": exp,
            "net": rev + mc - exp,
            "present": branch_att.count(),
            "late": branch_att.filter(is_late=True).count(),
            "absent": branch_att.filter(is_absent=True).count(),
        })

    # Build email body
    date_str = today.strftime("%A, %d %B %Y")
    lines = [
        f"GPSL DAILY SUMMARY — {date_str}",
        "=" * 50,
        "",
        "OVERALL TOTALS",
        f"  Retail Revenue:    N{total_retail_rev:>12,.2f}",
        f"  MultiChoice Rev:   N{total_mc_rev:>12,.2f}",
        f"  Total Expenses:    N{total_expenses:>12,.2f}",
        f"  Net Revenue:       N{(total_retail_rev + total_mc_rev - total_expenses):>12,.2f}",
        "",
        f"  Staff Present:     {total_present}",
        f"  Late:              {total_late}",
        f"  Absent:            {total_absent}",
        "",
        "BRANCH BREAKDOWN",
        "-" * 50,
    ]

    for b in branch_summaries:
        lines += [
            f"\n{b['name'].upper()}",
            f"  Retail:    N{b['retail_revenue']:,.2f}",
            f"  MultiChoice: N{b['mc_revenue']:,.2f}",
            f"  Expenses:  N{b['expenses']:,.2f}",
            f"  Net:       N{b['net']:,.2f}",
            f"  Attendance: {b['present']} present | {b['late']} late | {b['absent']} absent",
        ]

    if low_stock:
        lines += ["", "LOW STOCK ALERTS", "-" * 50]
        for s in low_stock:
            lines.append(
                f"  {s.product.model_name} — {s.quantity} left in {s.branch.name}"
            )

    lines += [
        "",
        "-" * 50,
        f"Generated automatically by GPSL ERP at {timezone.now().strftime('%H:%M')} WAT",
        "Log in at your Render URL to view full details.",
    ]

    body = "\n".join(lines)

    # Get director emails
    director_emails = list(
        User.objects.filter(
            role__in=["DIRECTOR", "SUPERADMIN"]
        ).exclude(email="").values_list("email", flat=True)
    )

    if not director_emails:
        director_emails = [settings.DEFAULT_FROM_EMAIL]

    try:
        send_mail(
            subject=f"GPSL Daily Summary — {date_str}",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=director_emails,
            fail_silently=False,
        )
        result = {"status": "sent", "to": director_emails, "date": str(today)}
    except Exception as e:
        result = {"status": "error", "detail": str(e)}

    if request:
        from django.http import JsonResponse
        return JsonResponse(result)
    return result


def daily_summary_trigger(request):
    """URL endpoint for cron-job.org to call."""
    from django.http import JsonResponse
    from decouple import config as _config
    secret = request.GET.get("key", "")
    expected = _config("BACKUP_SECRET_KEY", default="")
    if expected and secret != expected:
        return JsonResponse({"error": "unauthorized"}, status=403)
    return send_daily_summary_email(request)


# ─────────────────────────────────────────
# STOCK REORDER ALERT EMAIL
# Called from signals when stock hits low/zero
# ─────────────────────────────────────────

def send_stock_alert_email(product_name, branch_name, quantity, alert_type):
    """Send email alert when stock is low or out."""
    from django.core.mail import send_mail
    from django.conf import settings

    subject = (
        f"GPSL {'OUT OF STOCK' if quantity == 0 else 'LOW STOCK'} ALERT — "
        f"{product_name} at {branch_name}"
    )

    if quantity == 0:
        body = (
            f"OUT OF STOCK ALERT\n\n"
            f"Product: {product_name}\n"
            f"Branch:  {branch_name}\n"
            f"Current stock: 0 units\n\n"
            f"This product is completely out of stock. "
            f"Please arrange restocking immediately.\n\n"
            f"— GPSL ERP System"
        )
    else:
        body = (
            f"LOW STOCK ALERT\n\n"
            f"Product: {product_name}\n"
            f"Branch:  {branch_name}\n"
            f"Current stock: {quantity} unit(s) remaining\n\n"
            f"Stock is running low. Please reorder soon.\n\n"
            f"— GPSL ERP System"
        )

    # Send to directors and managers of that branch
    recipients = list(
        User.objects.filter(
            role__in=["DIRECTOR", "MANAGER"]
        ).exclude(email="").values_list("email", flat=True)
    )

    if not recipients:
        return

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=list(set(recipients)),
            fail_silently=True,
        )
    except Exception:
        pass


# ─────────────────────────────────────────
# MONTHLY DATA RESET CONTEXT
# Dashboards show only current month data by default
# History always available via date filters
# ─────────────────────────────────────────

def get_monthly_context():
    """
    Returns date boundaries for current month.
    Use this in all dashboard views to scope default data display.
    All dashboards show current month data.
    History is always accessible via date range filters.
    """
    today = timezone.now().date()
    month_start = today.replace(day=1)
    return {
        "today": today,
        "month_start": month_start,
        "current_month_label": today.strftime("%B %Y"),
    }
