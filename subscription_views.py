
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


@role_required("MANAGER", "DIRECTOR")
def router_subscriptions_overview(request):
    """Manager/Director - see all router subscriptions across staff/branches."""
    from datetime import date
    from core.models import RouterSubscription

    today = date.today()
    branch_flt = request.GET.get("branch", "")
    staff_flt  = request.GET.get("staff", "")
    status_flt = request.GET.get("status", "")

    subs = RouterSubscription.objects.filter(
        is_active=True
    ).select_related("staff", "branch").order_by("expiry_date")

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


@role_required("DIRECTOR", "MANAGER")
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

    # Expiring soon (next 7 days)
    expiring_soon = MultiChoiceSale.objects.filter(
        expiry_date__range=[today, today + timedelta(days=7)]
    ).select_related("staff", "branch").order_by("expiry_date")
    if branch_flt:
        expiring_soon = expiring_soon.filter(branch_id=branch_flt)

    # Already expired (last 14 days - not yet renewed)
    expired = MultiChoiceSale.objects.filter(
        expiry_date__range=[today - timedelta(days=14), today - timedelta(days=1)]
    ).select_related("staff", "branch").order_by("expiry_date")
    if branch_flt:
        expired = expired.filter(branch_id=branch_flt)

    # Renewal rate - customers who have renewed at least once
    renewed_phones = MultiChoiceSale.objects.values("customer_phone").annotate(
        count=Count("id")
    ).filter(count__gt=1, customer_phone__isnull=False).exclude(customer_phone="")

    from core.models import Branch
    branches = Branch.objects.all()

    return render(request, "director/mc_retention.html", {
        "expiring_soon": expiring_soon,
        "expired": expired,
        "renewed_count": renewed_phones.count(),
        "expiring_count": expiring_soon.count(),
        "expired_count": expired.count(),
        "total_customers": MultiChoiceSale.objects.values("customer_phone").distinct().count(),
        "branches": branches,
        "branch_flt": branch_flt,
        "date_from": date_from,
        "date_to": date_to,
        "today": today,
    })
