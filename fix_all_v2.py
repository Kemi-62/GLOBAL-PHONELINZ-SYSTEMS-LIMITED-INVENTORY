"""
FIX ALL ISSUES AT ONCE
========================
Run: python /home/runner/workspace/fix_all_v2.py

Fixes:
1. Migration conflict (core_catalogcategory already exists)
2. MC retention FieldError (expiry_date not in MultiChoiceSale yet)
3. RouterSubscription table missing
4. Manager sidebar missing Router Subs link
5. Retail sidebar - Router Subs not needed there (retail staff don't do router subs)
6. Telecom sidebar link check
"""
import os

W = '/home/runner/workspace'

print("=" * 55)
print("FIX ALL V2")
print("=" * 55)

# ── FIX 1: MC retention view - remove expiry_date filter ──
# The expiry_date field hasn't been migrated yet
# So the mc_subscription_retention view crashes
# We replace the expiry_date filters with Python-level filtering
print("\n--- Fix 1: MC retention view - use Python filtering not DB ---")
views = open(f'{W}/core/views.py').read()

old_mc_expiring = """    # Expiring soon (next 7 days)
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
    })"""

new_mc_expiring = """    # Get all MC sales and filter in Python (expiry_date may not be migrated yet)
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
        sale._computed_expiry = exp
        sale._computed_days_left = days_left
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
    })"""

if old_mc_expiring in views:
    views = views.replace(old_mc_expiring, new_mc_expiring)
    print("  MC retention view patched - uses Python filtering")
else:
    print("  WARNING: exact pattern not found - check mc_subscription_retention view manually")

open(f'{W}/core/views.py', 'w').write(views)

# ── FIX 2: Router overview - guard against missing table ──
print("\n--- Fix 2: Router overview - guard against missing table ---")
views = open(f'{W}/core/views.py').read()

old_router_overview = """    subs = RouterSubscription.objects.filter(
        is_active=True
    ).select_related("staff", "branch").order_by("expiry_date")"""

new_router_overview = """    try:
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
        })"""

if old_router_overview in views:
    views = views.replace(old_router_overview, new_router_overview)
    print("  Router overview patched with try/except guard")
else:
    print("  Pattern not found - skipping")

open(f'{W}/core/views.py', 'w').write(views)

# ── FIX 3: Sidebar links for Manager and Telecom ──
print("\n--- Fix 3: Adding sidebar links ---")
base = open(f'{W}/templates/base.html').read()
changed = False

# Manager sidebar - add Router Subs overview
if 'manager_router_subscriptions' not in base and 'router_subscriptions_overview' not in base:
    # Find manager section in sidebar
    manager_anchors = [
        "{% url 'manager_sales_today' %}",
        "{% url 'manager_dashboard' %}",
    ]
    for anchor in manager_anchors:
        if anchor in base:
            idx = base.find(anchor)
            end = base.find('</a>', idx) + 4
            insert = '\n            <a href="{% url \'router_subscriptions_overview\' %}" class="sidebar-link">\n                <span class="icon">📡</span> Router Subscriptions\n            </a>'
            base = base[:end] + insert + base[end:]
            print("  Router Subs added to Manager sidebar")
            changed = True
            break
    if not changed:
        print("  WARNING: Manager sidebar anchor not found - add manually")

# Telecom sidebar - add Router Subs
if 'router_subscriptions' not in base or base.count('router_subscriptions') < 2:
    telecom_anchors = [
        "{% url 'telecom_dashboard' %}",
        "{% if user.role == 'TELECOM' %}",
    ]
    for anchor in telecom_anchors:
        if anchor in base:
            idx = base.find(anchor)
            end = base.find('</a>', idx) + 4
            insert = '\n            <a href="{% url \'router_subscriptions\' %}" class="sidebar-link">\n                <span class="icon">📡</span> Router Subscriptions\n            </a>'
            base = base[:end] + insert + base[end:]
            print("  Router Subs added to Telecom sidebar")
            changed = True
            break
    if not changed:
        print("  WARNING: Telecom sidebar anchor not found")

if changed:
    open(f'{W}/templates/base.html', 'w').write(base)
else:
    print("  No sidebar changes needed or patterns not found")

# ── FIX 4: Update mc_retention.html to use _computed fields ──
print("\n--- Fix 4: Update mc_retention template for computed expiry ---")
mc_tmpl_path = f'{W}/templates/director/mc_retention.html'
if os.path.exists(mc_tmpl_path):
    tmpl = open(mc_tmpl_path).read()
    # Replace expiry_date references with computed ones
    tmpl = tmpl.replace('{{ s.expiry_date }}', '{{ s._computed_expiry|default:s.expiry_date }}')
    tmpl = tmpl.replace('s.days_to_expiry', 's._computed_days_left')
    tmpl = tmpl.replace('{{ s.days_to_expiry }}', '{{ s._computed_days_left }}')
    open(mc_tmpl_path, 'w').write(tmpl)
    print("  mc_retention.html updated for computed expiry fields")
else:
    print("  mc_retention.html not found - upload it first")

print("\n" + "=" * 55)
print("FIX COMPLETE")
print("=" * 55)
print("\nNow run migration fix:")
print("  python manage.py migrate core 0033 --fake")
print("  python manage.py migrate")
print("\nThen restart:")
print("  python manage.py runserver 0.0.0.0:8000")
