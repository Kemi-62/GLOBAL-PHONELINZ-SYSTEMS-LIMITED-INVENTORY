#!/usr/bin/env python3
"""
apply_mc_renewals.py   (marker: MC_RENEWALS_V1)

Adds a "Renewals Due" page for MultiChoice (DStv / GOtv) customers.

  * Finds each customer's LATEST paid subscription (by IUC number, or phone if there is no IUC)
    and works out expiry = payment date + 30 days
  * Groups them: Due in 5 days, Overdue, Coming up (6-10 days), Lapsed (30+ days overdue)
  * A customer who has paid again no longer shows; voided sales are ignored
  * One-tap WhatsApp button with a ready message, and a Call button
  * MultiChoice staff see their own customers, Managers their branch,
    Director and Sub Director every branch (with a branch filter)

Works with the existing data. No migration. Run from the folder with manage.py:

    python apply_mc_renewals.py

Safe to run twice; checks everything before writing anything.
"""
import os, sys, shutil
ROOT = os.getcwd()
PATCHES = [('core/urls.py',
  'from . import roles_views as rv  # ROLES_V1',
  'from . import roles_views as rv  # ROLES_V1\nfrom . import mc_renewals as mcr  # MC_RENEWALS_V1',
  'urls: import'),
 ('core/urls.py',
  "    path('director/mc-retention/', views.mc_subscription_retention, name='mc_subscription_retention'),",
  "    path('director/mc-retention/', views.mc_subscription_retention, name='mc_subscription_retention'),\n"
  "    path('renewals-due/', mcr.mc_renewals, name='mc_renewals'),  # MC_RENEWALS_V1",
  'urls: renewals-due/'),
 ('templates/base.html',
  '            <a href="{% url \'mc_subscription_retention\' %}" class="sidebar-link">\n'
  '                <span class="icon">📺</span> Subscription Renewals\n'
  '            </a>',
  '            <a href="{% url \'mc_renewals\' %}" class="sidebar-link">{# MC_RENEWALS_V1 #}\n'
  '                <span class="icon">🔔</span> Renewals Due\n'
  '            </a>',
  'sidebar: MultiChoice staff link'),
 ('templates/base.html',
  '            <a href="{% url \'mc_subscription_retention\' %}" class="sidebar-link">\n'
  '                <span class="icon">📺</span> MC Retention\n'
  '            </a>',
  '            <a href="{% url \'mc_subscription_retention\' %}" class="sidebar-link">\n'
  '                <span class="icon">📺</span> MC Retention\n'
  '            </a>\n'
  '            <a href="{% url \'mc_renewals\' %}" class="sidebar-link">{# MC_RENEWALS_V1 #}\n'
  '                <span class="icon">🔔</span> Renewals Due\n'
  '            </a>',
  'sidebar: Director link'),
 ('templates/base.html',
  '                <span class="icon">📡</span> Router Subscriptions\n'
  '            </a>\n'
  '<a href="{% url \'supplier_list\' %}" class="sidebar-link">',
  '                <span class="icon">📡</span> Router Subscriptions\n'
  '            </a>\n'
  '            <a href="{% url \'mc_renewals\' %}" class="sidebar-link">{# MC_RENEWALS_V1 #}\n'
  '                <span class="icon">🔔</span> MultiChoice Renewals\n'
  '            </a>\n'
  '<a href="{% url \'supplier_list\' %}" class="sidebar-link">',
  'sidebar: Manager link'),
 ('templates/base.html',
  '        <a href="{% url \'purchase_order_list\' %}" class="sidebar-link">\n'
  '            <span class="icon">📦</span> Purchase Orders\n'
  '        </a>\n'
  '        <a href="{% url \'catalog_management\' %}" class="sidebar-link">',
  '        <a href="{% url \'purchase_order_list\' %}" class="sidebar-link">\n'
  '            <span class="icon">📦</span> Purchase Orders\n'
  '        </a>\n'
  '        <a href="{% url \'mc_renewals\' %}" class="sidebar-link">{# MC_RENEWALS_V1 #}\n'
  '            <span class="icon">🔔</span> MultiChoice Renewals\n'
  '        </a>\n'
  '        <a href="{% url \'catalog_management\' %}" class="sidebar-link">',
  'sidebar: Sub Director link')]
NEWFILES = {'core/mc_renewals.py': '"""MC_RENEWALS_V1: who needs to renew their DStv / GOtv, with a one-tap WhatsApp reminder."""\n'
                        'from datetime import timedelta\n'
                        'from urllib.parse import quote\n'
                        '\n'
                        'from django.shortcuts import render\n'
                        'from django.utils import timezone\n'
                        '\n'
                        'from core import models as m\n'
                        'from core.utils.decorators import role_required\n'
                        '\n'
                        'CYCLE_DAYS = 30        # one subscription month\n'
                        'DUE_SOON_DAYS = 5      # "due" bucket: expires within this many days\n'
                        'UPCOMING_DAYS = 10     # "coming up" bucket\n'
                        'LAPSED_AFTER = 30      # overdue longer than this = lapsed (win-back)\n'
                        'LOOKBACK_DAYS = 120\n'
                        '\n'
                        '\n'
                        'def wa_number(phone):\n'
                        '    """Nigerian number to international digits for wa.me, or None."""\n'
                        '    d = "".join(ch for ch in (phone or "") if ch.isdigit())\n'
                        '    if d.startswith("234") and len(d) == 13:\n'
                        '        return d\n'
                        '    if d.startswith("0") and len(d) == 11:\n'
                        '        return "234" + d[1:]\n'
                        '    if len(d) == 10:\n'
                        '        return "234" + d\n'
                        '    return None\n'
                        '\n'
                        '\n'
                        'def _message(row):\n'
                        '    s = row["sale"]\n'
                        '    svc = s.service_type\n'
                        '    when = row["expiry"].strftime("%d %b")\n'
                        '    if row["days_left"] < 0:\n'
                        '        status = "expired on %s" % when\n'
                        '    elif row["days_left"] == 0:\n'
                        '        status = "expires today"\n'
                        '    else:\n'
                        '        status = "expires on %s" % when\n'
                        '    iuc = (" (IUC %s)" % s.iuc_number.strip()) if s.iuc_number else ""\n'
                        '    return ("Hello %s, your %s %s subscription%s %s. "\n'
                        '            "Renew with Global Phonelinz Systems Limited to stay connected. Thank you!"\n'
                        '            % (s.customer_name.strip().title(), svc, s.package_type, iuc, status))\n'
                        '\n'
                        '\n'
                        'def due_rows(user, branch_id=None, today=None):\n'
                        '    """Latest paid subscription per customer, with its expiry. Voided sales are ignored,\n'
                        '    and a customer who has paid again since is not listed twice."""\n'
                        '    today = today or timezone.localdate()\n'
                        '    qs = (m.MultiChoiceSale.objects\n'
                        '          .filter(is_voided=False, date__gte=today - timedelta(days=LOOKBACK_DAYS))\n'
                        '          .select_related("staff", "branch").order_by("date", "time", "id"))\n'
                        '    role = getattr(user, "role", "")\n'
                        '    if role == "MULTICHOICE":\n'
                        '        qs = qs.filter(staff=user)\n'
                        '    elif role == "MANAGER":\n'
                        '        qs = qs.filter(branch_id=user.branch_id)\n'
                        '    elif branch_id:\n'
                        '        qs = qs.filter(branch_id=branch_id)\n'
                        '    latest = {}\n'
                        '    for s in qs:\n'
                        '        iuc = (s.iuc_number or "").strip().upper()\n'
                        '        if iuc:\n'
                        '            key = (s.service_type, iuc)\n'
                        '        else:\n'
                        '            num = wa_number(s.customer_phone)\n'
                        '            if not num:\n'
                        '                continue\n'
                        '            key = (s.service_type, num)\n'
                        '        latest[key] = s      # ordered ascending, so the last one wins\n'
                        '    rows = []\n'
                        '    for s in latest.values():\n'
                        '        expiry = s.date + timedelta(days=CYCLE_DAYS)\n'
                        '        days_left = (expiry - today).days\n'
                        '        row = {"sale": s, "expiry": expiry, "days_left": days_left, "days_over": -days_left}\n'
                        '        num = wa_number(s.customer_phone)\n'
                        '        row["phone"] = s.customer_phone or ""\n'
                        '        row["wa"] = ("https://wa.me/%s?text=%s" % (num, quote(_message(row)))) if num else ""\n'
                        '        rows.append(row)\n'
                        '    rows.sort(key=lambda r: r["expiry"])\n'
                        '    return rows\n'
                        '\n'
                        '\n'
                        'def bucket(rows):\n'
                        '    due, overdue, upcoming, lapsed = [], [], [], []\n'
                        '    for r in rows:\n'
                        '        d = r["days_left"]\n'
                        '        if d < -LAPSED_AFTER:\n'
                        '            lapsed.append(r)\n'
                        '        elif d < 0:\n'
                        '            overdue.append(r)\n'
                        '        elif d <= DUE_SOON_DAYS:\n'
                        '            due.append(r)\n'
                        '        elif d <= UPCOMING_DAYS:\n'
                        '            upcoming.append(r)\n'
                        '    return due, overdue, upcoming, lapsed\n'
                        '\n'
                        '\n'
                        '@role_required("MULTICHOICE", "MANAGER", "DIRECTOR", "SUB_DIRECTOR")\n'
                        'def mc_renewals(request):\n'
                        '    branch_id = request.GET.get("branch") or None\n'
                        '    rows = due_rows(request.user, branch_id)\n'
                        '    due, overdue, upcoming, lapsed = bucket(rows)\n'
                        '    can_filter = request.user.role in ("DIRECTOR", "SUB_DIRECTOR", "SUPERADMIN")\n'
                        '    return render(request, "multichoice_renewals.html", {\n'
                        '        "due": due, "overdue": overdue, "upcoming": upcoming, "lapsed": lapsed,\n'
                        '        "branches": m.Branch.objects.all() if can_filter else [],\n'
                        '        "branch_flt": branch_id or "",\n'
                        '        "show_staff": request.user.role != "MULTICHOICE",\n'
                        '        "due_soon_days": DUE_SOON_DAYS,\n'
                        '    })\n',
 'templates/multichoice_renewals.html': '{% extends "base.html" %}\n'
                                        '{# MC_RENEWALS_V1 #}\n'
                                        '{% block content %}\n'
                                        '<style>\n'
                                        '.rn-t{font-size:1.3rem;font-weight:700;color:#004F9F;margin:0 0 .3rem}\n'
                                        '.rn-s{font-size:.85rem;color:#6b7280;margin:0 0 1.1rem}\n'
                                        '.rn-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:.7rem;margin-bottom:1.2rem}\n'
                                        '.rn-st{background:#fff;border:1px solid '
                                        '#e5e7eb;border-radius:10px;padding:.8rem;text-align:center}\n'
                                        '.rn-st b{display:block;font-size:1.5rem}\n'
                                        '.rn-st span{font-size:.72rem;color:#6b7280}\n'
                                        '.rn-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:1rem '
                                        '1.1rem;margin-bottom:1rem}\n'
                                        '.rn-card h3{font-size:.95rem;margin:0 0 .7rem}\n'
                                        '.rn-row{display:flex;justify-content:space-between;align-items:center;gap:.8rem;padding:.6rem '
                                        '0;border-bottom:1px solid #f1f5f9;flex-wrap:wrap}\n'
                                        '.rn-row:last-child{border-bottom:none}\n'
                                        '.rn-n{font-weight:600;font-size:.9rem}\n'
                                        '.rn-m{font-size:.76rem;color:#6b7280}\n'
                                        '.rn-b{display:flex;gap:.4rem}\n'
                                        '.rn-btn{padding:.4rem '
                                        '.8rem;border-radius:7px;font-size:.78rem;font-weight:600;text-decoration:none;background:#16a34a;color:#fff}\n'
                                        '.rn-btn.call{background:#e5e7eb;color:#374151}\n'
                                        '.rn-empty{font-size:.82rem;color:#9ca3af}\n'
                                        '.rn-f{margin-bottom:1rem}\n'
                                        '</style>\n'
                                        '<h1 class="rn-t">📺 Renewals Due</h1>\n'
                                        '<p class="rn-s">DStv and GOtv customers whose last payment is about 30 days old. Tap WhatsApp to '
                                        'open a ready message, check it and send.</p>\n'
                                        '\n'
                                        '{% if branches %}\n'
                                        '<form method="GET" class="rn-f">\n'
                                        '  <select name="branch" onchange="this.form.submit()">\n'
                                        '    <option value="">All branches</option>\n'
                                        '    {% for b in branches %}<option value="{{ b.id }}" {% if branch_flt == b.id|stringformat:"s" '
                                        '%}selected{% endif %}>{{ b.name }}</option>{% endfor %}\n'
                                        '  </select>\n'
                                        '</form>\n'
                                        '{% endif %}\n'
                                        '\n'
                                        '<div class="rn-stats">\n'
                                        '  <div class="rn-st"><b style="color:#d97706">{{ due|length }}</b><span>Due in {{ due_soon_days '
                                        '}} days</span></div>\n'
                                        '  <div class="rn-st"><b style="color:#dc2626">{{ overdue|length }}</b><span>Overdue</span></div>\n'
                                        '  <div class="rn-st"><b style="color:#2563eb">{{ upcoming|length }}</b><span>Coming '
                                        'up</span></div>\n'
                                        '  <div class="rn-st"><b style="color:#6b7280">{{ lapsed|length }}</b><span>Lapsed (30+ '
                                        'days)</span></div>\n'
                                        '</div>\n'
                                        '\n'
                                        '{% include "partials/renewal_list.html" with title="Due now" rows=due %}\n'
                                        '{% include "partials/renewal_list.html" with title="Overdue: call these first" rows=overdue %}\n'
                                        '{% include "partials/renewal_list.html" with title="Coming up" rows=upcoming %}\n'
                                        '{% include "partials/renewal_list.html" with title="Lapsed: win them back" rows=lapsed %}\n'
                                        '<p class="rn-m">Expiry is the last payment date plus 30 days. A customer who has paid again no '
                                        'longer shows here. Voided sales are ignored.</p>\n'
                                        '{% endblock %}\n',
 'templates/partials/renewal_list.html': '{# MC_RENEWALS_V1 #}\n'
                                         '<div class="rn-card">\n'
                                         '  <h3>{{ title }} ({{ rows|length }})</h3>\n'
                                         '  {% for r in rows %}\n'
                                         '  <div class="rn-row">\n'
                                         '    <div>\n'
                                         '      <div class="rn-n">{{ r.sale.customer_name }}</div>\n'
                                         '      <div class="rn-m">{{ r.sale.service_type }} {{ r.sale.package_type }}{% if '
                                         'r.sale.iuc_number %} &middot; IUC {{ r.sale.iuc_number }}{% endif %}\n'
                                         '        &middot; {% if r.days_left < 0 %}expired {{ r.days_over }} day{{ r.days_over|pluralize '
                                         '}} ago{% elif r.days_left == 0 %}expires today{% else %}expires in {{ r.days_left }} day{{ '
                                         'r.days_left|pluralize }}{% endif %}\n'
                                         '        {% if show_staff %}&middot; {{ r.sale.branch.name }}, {{ r.sale.staff.username }}{% '
                                         'endif %}</div>\n'
                                         '    </div>\n'
                                         '    <div class="rn-b">\n'
                                         '      {% if r.wa %}<a class="rn-btn" href="{{ r.wa }}" target="_blank" '
                                         'rel="noopener">WhatsApp</a>{% endif %}\n'
                                         '      {% if r.phone %}<a class="rn-btn call" href="tel:{{ r.phone }}">Call</a>{% else %}<span '
                                         'class="rn-empty">No phone</span>{% endif %}\n'
                                         '    </div>\n'
                                         '  </div>\n'
                                         '  {% empty %}<div class="rn-empty">Nobody here.</div>{% endfor %}\n'
                                         '</div>\n'}

def p(rel): return os.path.join(ROOT, *rel.split("/"))
def read(rel):
    with open(p(rel), encoding="utf-8") as f: return f.read()
if not os.path.exists(p("manage.py")) or not os.path.isdir(p("core")):
    print("ABORT: run this from the folder that contains manage.py"); sys.exit(1)
if not os.path.exists(p("core/roles_views.py")):
    print("ABORT: apply_roles_v1.py (and v2) must be applied first."); sys.exit(1)
texts, errors, plan = {}, [], []
for rel, old, new, label in PATCHES:
    if not os.path.exists(p(rel)):
        errors.append("missing file: " + rel); continue
    t = texts.get(rel) or read(rel)
    if new in t: plan.append(("SKIP", label)); texts[rel] = t; continue
    if t.count(old) != 1:
        errors.append("%s: expected 1 match for [%s], found %d" % (rel, label, t.count(old))); texts[rel] = t; continue
    texts[rel] = t.replace(old, new, 1); plan.append(("OK", label))
if errors:
    print("ABORT: nothing was changed.\n"); [print("  -", e) for e in errors]; sys.exit(1)
changed = [r for r, t in texts.items() if t != read(r)]
for rel in changed:
    b = p(rel) + ".pre_mcren.bak"
    if not os.path.exists(b): shutil.copy2(p(rel), b)
    with open(p(rel), "w", encoding="utf-8", newline="") as f: f.write(texts[rel])
wrote = False
for rel, content in NEWFILES.items():
    if os.path.exists(p(rel)) and read(rel) == content:
        plan.append(("SKIP", "file " + rel)); continue
    os.makedirs(os.path.dirname(p(rel)), exist_ok=True)
    with open(p(rel), "w", encoding="utf-8", newline="") as f: f.write(content)
    plan.append(("OK", "file " + rel)); wrote = True
for s, l in plan: print(("OK   " if s == "OK" else "SKIP ") + l)
print("\nDone. No migration needed. Commit, push and redeploy." if (changed or wrote) else "\nNothing to do: already applied.")