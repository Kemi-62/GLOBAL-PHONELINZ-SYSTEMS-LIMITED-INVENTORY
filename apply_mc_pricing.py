#!/usr/bin/env python3
"""
apply_mc_pricing.py   (marker: MC_PRICING_V1)

Run after apply_mc_renewals_v2.py. Changes how MultiChoice subscriptions are recorded:

  * The "Amount collected from customer" box is GONE. The system works it out:
        Customer subscription  ->  cost price + N200
        Activation / Office subscription / Given by Director  ->  cost price only
  * New "Sale type" dropdown (Customer is the default)
  * The form shows the amount live as the staff types the cost price
  * Every sale type (including Office and Director-given) still counts as a customer, shows in
    history, deducts the cost price from the main balance, and appears in renewal reminders
  * Old sales are untouched (they count as Customer)

The N200 is one number: MARKUP in core/mc_pricing.py.

NEEDS a migration:  python apply_mc_pricing.py   then   python manage.py migrate
Safe to run twice; checks everything before writing anything.
"""
import os, re, sys, shutil
ROOT = os.getcwd()
MARK = "MC_PRICING_V1"
PATCHES = [('core/models.py',
  '    months_paid = models.PositiveSmallIntegerField(default=1, help_text="How many months this payment covers (used for renewal '
  'reminders).")  # MC_RENEWALS_V2\n',
  '    months_paid = models.PositiveSmallIntegerField(default=1, help_text="How many months this payment covers (used for renewal '
  'reminders).")  # MC_RENEWALS_V2\n'
  '    sale_category = models.CharField(max_length=12, default="CUSTOMER", choices=(("CUSTOMER", "Customer subscription"), ("ACTIVATION", '
  '"Activation"), ("OFFICE", "Office subscription"), ("DIRECTOR", "Given by Director")))  # MC_PRICING_V1\n',
  'model: MultiChoiceSale.sale_category'),
 ('core/views.py',
  '        amount         = Decimal(request.POST.get("amount") or "0")\n        customer_name  = request.POST.get("customer_name", "")',
  '        from core import mc_pricing as _mp  # MC_PRICING_V1: amount is worked out, never typed\n'
  '        sale_category  = _mp.clean_category(request.POST.get("sale_category"))\n'
  '        amount         = _mp.amount_for(cost_price, sale_category)\n'
  '        customer_name  = request.POST.get("customer_name", "")',
  'sale view: amount = cost + markup'),
 ('core/views.py',
  '                months_paid=months_paid,\n                cost_price=cost_price,',
  '                months_paid=months_paid,\n                sale_category=sale_category,\n                cost_price=cost_price,',
  'sale view: save category'),
 ('core/views.py',
  '            # Update Customer CRM\n'
  '            if customer_phone:\n'
  '                _upsert_customer(\n'
  '                    phone=customer_phone,\n'
  '                    name=customer_name,\n'
  '                    branch=request.user.branch,\n'
  '                    amount=amount,\n'
  '                    source="MULTICHOICE",',
  '            # Update Customer CRM\n'
  '            if customer_phone and sale_category not in _mp.NOT_CUSTOMERS:\n'
  '                _upsert_customer(\n'
  '                    phone=customer_phone,\n'
  '                    name=customer_name,\n'
  '                    branch=request.user.branch,\n'
  '                    amount=amount,\n'
  '                    source="MULTICHOICE",',
  'sale view: office/director sales stay out of the CRM'),
 ('core/views.py',
  '        "renewals_due_count": _mc_renewals_due_count(request.user),  # MC_RENEWALS_V2',
  '        "renewals_due_count": _mc_renewals_due_count(request.user),  # MC_RENEWALS_V2\n'
  '        "mc_markup": __import__("core.mc_pricing", fromlist=["MARKUP"]).MARKUP,  # MC_PRICING_V1',
  'dashboard: markup for the form'),
 ('templates/multichoice_dashboard.html',
  '        <div class="form-group"><label>Amount Collected from Customer (₦) *</label><input type="number" name="amount" step="0.01" '
  'min="0" required placeholder="e.g. 4900"></div>',
  '        <div class="form-group"><label>Sale type *</label>{# MC_PRICING_V1 #}\n'
  '          <select name="sale_category" id="mc-cat" required>\n'
  '            <option value="CUSTOMER" selected>Customer (cost + ₦{{ mc_markup|floatformat:0 }})</option>\n'
  '            <option value="ACTIVATION">Activation (at cost)</option>\n'
  '            <option value="OFFICE">Office subscription (at cost)</option>\n'
  '            <option value="DIRECTOR">Given by Director (at cost)</option>\n'
  '          </select>\n'
  '        </div>',
  'form: sale type dropdown replaces amount'),
 ('templates/multichoice_dashboard.html',
  '        <input type="number" name="cost_price" step="0.01" min="0" required placeholder="e.g. 4500">\n'
  '        <p style="font-size:.75rem;color:#6b7280;margin:.3rem 0 0;">This amount will be deducted from your current balance.</p>',
  '        <input type="number" name="cost_price" id="mc-cost" step="0.01" min="0" required placeholder="e.g. 4500">\n'
  '        <p style="font-size:.75rem;color:#6b7280;margin:.3rem 0 0;">This amount will be deducted from your current balance.</p>\n'
  '        <p id="mc-collect" style="font-size:.9rem;font-weight:700;color:#166534;margin:.5rem 0 0;"></p>{# MC_PRICING_V1 #}',
  'form: live amount preview'),
 ('templates/multichoice_dashboard.html',
  '✔ Record Subscription</button>\n    </form>',
  '✔ Record Subscription</button>\n'
  '    </form>\n'
  '    <script>{# MC_PRICING_V1 #}\n'
  '    (function(){\n'
  "      var cat=document.getElementById('mc-cat'), cost=document.getElementById('mc-cost'), out=document.getElementById('mc-collect'), "
  'markup={{ mc_markup|floatformat:0 }};\n'
  '      function show(){\n'
  "        var c=parseFloat(cost.value); if(isNaN(c)){out.textContent='';return;}\n"
  "        var amt=(cat.value==='CUSTOMER')?c+markup:c;\n"
  "        out.textContent=(cat.value==='CUSTOMER'?'Collect from customer: ':'Recorded at cost: "
  "')+'₦'+amt.toLocaleString('en-NG',{minimumFractionDigits:2,maximumFractionDigits:2});\n"
  '      }\n'
  "      cat.addEventListener('change',show); cost.addEventListener('input',show); show();\n"
  '    })();\n'
  '    </script>',
  'form: preview script'),
 ('templates/multichoice_dashboard.html',
  '            <td>{{ sale.get_transaction_type_display }}</td>\n'
  '            <td>₦{{ sale.amount|floatformat:2 }}</td>\n'
  '                <td>{{ sale.computed_expiry',
  '            <td>{{ sale.get_transaction_type_display }}{% if sale.sale_category != "CUSTOMER" %}<br><span '
  'style="font-size:.68rem;color:#92400e;">{{ sale.get_sale_category_display }}</span>{% endif %}</td>\n'
  '            <td>₦{{ sale.amount|floatformat:2 }}</td>\n'
  '                <td>{{ sale.computed_expiry',
  'today table: show sale type'),
 ('templates/multichoice_dashboard.html',
  '            <td>{{ sale.get_transaction_type_display }}</td>\n'
  '            <td>₦{{ sale.amount|floatformat:2 }}</td>\n'
  '            <td style="color:#ef4444;">',
  '            <td>{{ sale.get_transaction_type_display }}{% if sale.sale_category != "CUSTOMER" %}<br><span '
  'style="font-size:.68rem;color:#92400e;">{{ sale.get_sale_category_display }}</span>{% endif %}</td>\n'
  '            <td>₦{{ sale.amount|floatformat:2 }}</td>\n'
  '            <td style="color:#ef4444;">',
  'history table: show sale type')]
NEWFILES = {'core/mc_pricing.py': '"""MC_PRICING_V1: how the amount collected from the customer is worked out.\n'
                       '\n'
                       'Change MARKUP here and every new MultiChoice subscription follows it.\n'
                       '"""\n'
                       'from decimal import Decimal\n'
                       '\n'
                       'MARKUP = Decimal("200")\n'
                       '\n'
                       'CATEGORIES = (\n'
                       '    ("CUSTOMER", "Customer subscription"),\n'
                       '    ("ACTIVATION", "Activation (recorded at cost)"),\n'
                       '    ("OFFICE", "Office subscription (recorded at cost)"),\n'
                       '    ("DIRECTOR", "Given by Director (recorded at cost)"),\n'
                       ')\n'
                       'AT_COST = {"ACTIVATION", "OFFICE", "DIRECTOR"}\n'
                       'NOT_CUSTOMERS = set()   # every sale type counts as a real customer (CRM and renewal reminders)\n'
                       '\n'
                       '\n'
                       'def amount_for(cost_price, category):\n'
                       '    cost = Decimal(cost_price or 0)\n'
                       '    return cost if category in AT_COST else cost + MARKUP\n'
                       '\n'
                       '\n'
                       'def clean_category(value):\n'
                       '    return value if value in dict(CATEGORIES) else "CUSTOMER"\n'
                       '\n'
                       '\n'
                       'def markup_for(category):\n'
                       '    """The part of the amount that is the business\'s service charge (never commission)."""\n'
                       '    return Decimal("0") if category in AT_COST else MARKUP\n',
 'core/mc_renewals.py': '"""MC_RENEWALS_V1: who needs to renew their DStv / GOtv, with a one-tap WhatsApp reminder."""\n'
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
                        "        expiry = s.date + timedelta(days=CYCLE_DAYS * max(1, getattr(s, 'months_paid', 1) or 1))  # "
                        'MC_RENEWALS_V2\n'
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
                        '    })\n'}
MIGRATION = '# MC_PRICING_V1\nfrom django.db import migrations, models\n\n\nclass Migration(migrations.Migration):\n\n    dependencies = [\n        ("core", "@@LAST@@"),\n    ]\n\n    operations = [\n        migrations.AddField(\n            model_name="multichoicesale",\n            name="sale_category",\n            field=models.CharField(choices=[("CUSTOMER", "Customer subscription"), ("ACTIVATION", "Activation"), ("OFFICE", "Office subscription"), ("DIRECTOR", "Given by Director")], default="CUSTOMER", max_length=12),\n        ),\n    ]\n'

def p(rel): return os.path.join(ROOT, *rel.split("/"))
def read(rel):
    with open(p(rel), encoding="utf-8") as f: return f.read()
if not os.path.exists(p("manage.py")) or not os.path.isdir(p("core")):
    print("ABORT: run this from the folder that contains manage.py"); sys.exit(1)
if "MC_RENEWALS_V2" not in read("core/views.py"):
    print("ABORT: apply_mc_renewals_v2.py has not been applied yet."); sys.exit(1)
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
    b = p(rel) + ".pre_mcprice.bak"
    if not os.path.exists(b): shutil.copy2(p(rel), b)
    with open(p(rel), "w", encoding="utf-8", newline="") as f: f.write(texts[rel])
wrote = False
for rel, content in NEWFILES.items():
    if os.path.exists(p(rel)) and read(rel) == content:
        plan.append(("SKIP", "file " + rel)); continue
    os.makedirs(os.path.dirname(p(rel)), exist_ok=True)
    with open(p(rel), "w", encoding="utf-8", newline="") as f: f.write(content)
    plan.append(("OK", "file " + rel)); wrote = True
mig_dir = p("core/migrations")
nums = sorted(f for f in os.listdir(mig_dir) if re.match(r"^\d{4}_.*\.py$", f))
if any(MARK in open(os.path.join(mig_dir, f), encoding="utf-8").read() for f in nums):
    plan.append(("SKIP", "migration"))
else:
    last = nums[-1][:-3]
    name = "%04d_mc_sale_category.py" % (int(last[:4]) + 1)
    with open(os.path.join(mig_dir, name), "w", encoding="utf-8", newline="") as f:
        f.write(MIGRATION.replace("@@LAST@@", last))
    plan.append(("OK", "migration " + name)); wrote = True
for s, l in plan: print(("OK   " if s == "OK" else "SKIP ") + l)
print("\nDone. Next:  python manage.py migrate   then commit, push and redeploy." if (changed or wrote) else "\nNothing to do: already applied.")