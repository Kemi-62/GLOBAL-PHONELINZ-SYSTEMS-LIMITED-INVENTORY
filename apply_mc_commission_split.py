#!/usr/bin/env python3
"""
apply_mc_commission_split.py   (marker: MC_COMMISSION_V1)

Run after apply_mc_pricing.py. Keeps the automatic service charge (N200) OUT of commission:

  * Each new customer sale remembers its service charge (markup_amount)
  * Weekly commission = (collected + closing balance) - (opening + funds) - service charge
    so the N200 is never counted as commission. Older sales are unchanged (their markup is 0).
  * The weekly summary and closed-week banner show "Service charge" on its own line
  * Director > MultiChoice Balances gets a "Service Charge (this month)" card
  * The balance still goes down by the full cost price for EVERY sale type

NEEDS a migration:  python apply_mc_commission_split.py   then   python manage.py migrate
Safe to run twice; checks everything before writing anything.
"""
import os, re, sys, shutil
ROOT = os.getcwd()
MARK = "MC_COMMISSION_V1"
PATCHES = [('core/models.py',
  'Given by Director")))  # MC_PRICING_V1\n',
  'Given by Director")))  # MC_PRICING_V1\n'
  '    markup_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # MC_COMMISSION_V1: the service charge inside '
  'amount\n',
  'model: MultiChoiceSale.markup_amount'),
 ('core/models.py',
  '    def calculate_commission(self):\n'
  '        if self.closing_balance is not None:\n'
  '            self.commission = (self.closing_balance + self.total_subscriptions) - (self.opening_balance + self.additional_funds)\n'
  '            return self.commission\n'
  '        return 0',
  '    def service_charge(self):  # MC_COMMISSION_V1\n'
  '        """Total service charge (the automatic markup) on this week\'s sales. It is NOT commission."""\n'
  '        from datetime import timedelta\n'
  '        from django.db.models import Sum\n'
  '        total = MultiChoiceSale.objects.filter(\n'
  '            staff=self.staff, branch=self.branch,\n'
  '            date__gte=self.week_start_date, date__lt=self.week_start_date + timedelta(days=7),\n'
  '            is_voided=False,\n'
  '        ).aggregate(t=Sum("markup_amount"))["t"]\n'
  '        return total or 0\n'
  '\n'
  '    def calculate_commission(self):\n'
  '        if self.closing_balance is not None:\n'
  '            self.commission = (self.closing_balance + self.total_subscriptions) - (self.opening_balance + self.additional_funds) - '
  'self.service_charge()  # MC_COMMISSION_V1\n'
  '            return self.commission\n'
  '        return 0',
  'model: commission excludes the service charge'),
 ('core/views.py',
  '                sale_category=sale_category,\n                cost_price=cost_price,',
  '                sale_category=sale_category,\n'
  '                markup_amount=_mp.markup_for(sale_category),\n'
  '                cost_price=cost_price,',
  'sale view: save markup_amount'),
 ('core/views.py',
  '        "total_commission": total_commission,\n        "total_subscriptions": total_subscriptions,',
  '        "total_commission": total_commission,\n'
  '        "total_service_charge": MultiChoiceSale.objects.filter(\n'
  '            date__gte=month_start, date__lte=today, is_voided=False,\n'
  '            **({"branch_id": branch_flt} if branch_flt else {}),\n'
  '        ).aggregate(t=_Sum("markup_amount"))["t"] or 0,  # MC_COMMISSION_V1\n'
  '        "total_subscriptions": total_subscriptions,',
  'director page: service charge total'),
 ('templates/director/multichoice_balance.html',
  '    <p class="kpi-label">Total Commission Paid</p>\n    <p class="kpi-value">₦{{ total_commission|floatformat:0 }}</p>\n  </div>',
  '    <p class="kpi-label">Total Commission Paid</p>\n'
  '    <p class="kpi-value">₦{{ total_commission|floatformat:0 }}</p>\n'
  '  </div>\n'
  '  <div class="kpi amber">{# MC_COMMISSION_V1 #}\n'
  '    <p class="kpi-label">Service Charge (this month)</p>\n'
  '    <p class="kpi-value">₦{{ total_service_charge|floatformat:0 }}</p>\n'
  '  </div>',
  'director page: service charge card'),
 ('templates/multichoice_dashboard.html',
  '  <strong>✅ This week is closed.</strong> Commission earned: <strong>₦{{ weekly_report.commission|floatformat:2 }}</strong>',
  '  <strong>✅ This week is closed.</strong> Commission earned: <strong>₦{{ weekly_report.commission|floatformat:2 }}</strong> &middot; '
  'Service charge: <strong>₦{{ weekly_report.service_charge|floatformat:2 }}</strong>{# MC_COMMISSION_V1 #}',
  'dashboard: closed-week banner shows service charge'),
 ('templates/multichoice_dashboard.html',
  '        <tr style="background:#d1fae5;"><td><strong>Commission Earned</strong></td><td><strong '
  'style="color:#065f46;font-size:1.1rem;">₦{{ weekly_report.commission|floatformat:2 }}</strong></td></tr>',
  '        <tr style="background:#d1fae5;"><td><strong>Commission Earned</strong></td><td><strong '
  'style="color:#065f46;font-size:1.1rem;">₦{{ weekly_report.commission|floatformat:2 }}</strong></td></tr>\n'
  '        <tr><td>Service Charge (not commission)</td><td><strong>₦{{ weekly_report.service_charge|floatformat:2 }}</strong></td></tr>{# '
  'MC_COMMISSION_V1 #}',
  'dashboard: weekly summary shows service charge')]
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
                       '    return Decimal("0") if category in AT_COST else MARKUP\n'}
MIGRATION = '# MC_COMMISSION_V1\nfrom django.db import migrations, models\n\n\nclass Migration(migrations.Migration):\n\n    dependencies = [\n        ("core", "@@LAST@@"),\n    ]\n\n    operations = [\n        migrations.AddField(\n            model_name="multichoicesale",\n            name="markup_amount",\n            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),\n        ),\n    ]\n'

def p(rel): return os.path.join(ROOT, *rel.split("/"))
def read(rel):
    with open(p(rel), encoding="utf-8") as f: return f.read()
if not os.path.exists(p("manage.py")) or not os.path.isdir(p("core")):
    print("ABORT: run this from the folder that contains manage.py"); sys.exit(1)
if not os.path.exists(p("core/mc_pricing.py")):
    print("ABORT: apply_mc_pricing.py has not been applied yet."); sys.exit(1)
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
    b = p(rel) + ".pre_mccomm.bak"
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
    name = "%04d_mc_markup_amount.py" % (int(last[:4]) + 1)
    with open(os.path.join(mig_dir, name), "w", encoding="utf-8", newline="") as f:
        f.write(MIGRATION.replace("@@LAST@@", last))
    plan.append(("OK", "migration " + name)); wrote = True
for s, l in plan: print(("OK   " if s == "OK" else "SKIP ") + l)
print("\nDone. Next:  python manage.py migrate   then commit, push and redeploy." if (changed or wrote) else "\nNothing to do: already applied.")