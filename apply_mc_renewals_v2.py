#!/usr/bin/env python3
"""
apply_mc_renewals_v2.py   (marker: MC_RENEWALS_V2)

Run after apply_mc_renewals.py. Adds:

  * "Months paid" on the MultiChoice sale form (1-12). Renewal reminders then count
    expiry as payment date + 30 days x months paid. Old sales count as 1 month.
  * A daily 7:00 am (Lagos) notice to each MultiChoice staff member with how many customers
    to remind, plus a banner on their dashboard.

NEEDS a migration:   python apply_mc_renewals_v2.py   then   python manage.py migrate
Uses the existing CRON_KEY. Safe to run twice; checks everything before writing anything.
"""
import os, re, sys, shutil
ROOT = os.getcwd()
MARK = "MC_RENEWALS_V2"
PATCHES = [('core/models.py',
  '    transaction_type = models.CharField(\n        max_length=20,\n        choices=(\n            ("NEW", "New Subscription"),',
  '    months_paid = models.PositiveSmallIntegerField(default=1, help_text="How many months this payment covers (used for renewal '
  'reminders).")  # MC_RENEWALS_V2\n'
  '    transaction_type = models.CharField(\n'
  '        max_length=20,\n'
  '        choices=(\n'
  '            ("NEW", "New Subscription"),',
  'model: MultiChoiceSale.months_paid'),
 ('core/views.py',
  '        transaction_type = request.POST.get("transaction_type", "NEW")\n\n        prev = MultiChoiceBalance.objects',
  '        transaction_type = request.POST.get("transaction_type", "NEW")\n'
  '        try:  # MC_RENEWALS_V2\n'
  '            months_paid = max(1, min(12, int(request.POST.get("months_paid") or 1)))\n'
  '        except (TypeError, ValueError):\n'
  '            months_paid = 1\n'
  '\n'
  '        prev = MultiChoiceBalance.objects',
  'sale view: read months paid'),
 ('core/views.py',
  '                transaction_type=transaction_type,\n'
  '                cost_price=cost_price,\n'
  '                amount=amount,\n'
  '            )\n'
  '            MultiChoiceBalance.objects.create(',
  '                transaction_type=transaction_type,\n'
  '                months_paid=months_paid,\n'
  '                cost_price=cost_price,\n'
  '                amount=amount,\n'
  '            )\n'
  '            MultiChoiceBalance.objects.create(',
  'sale view: save months paid'),
 ('core/views.py',
  '        "total_today": today_sales.aggregate(total=Sum("amount"))["total"] or 0,',
  '        "total_today": today_sales.aggregate(total=Sum("amount"))["total"] or 0,\n'
  '        "renewals_due_count": _mc_renewals_due_count(request.user),  # MC_RENEWALS_V2',
  'dashboard: renewals count'),
 ('core/views.py',
  '@role_required("MULTICHOICE")\ndef record_multichoice_sale(request):',
  'def _mc_renewals_due_count(user):  # MC_RENEWALS_V2\n'
  '    try:\n'
  '        from core import mc_renewals as _mr\n'
  '        due, overdue, _up, _lapsed = _mr.bucket(_mr.due_rows(user))\n'
  '        return len(due) + len(overdue)\n'
  '    except Exception:\n'
  '        return 0\n'
  '\n'
  '\n'
  '@role_required("MULTICHOICE")\n'
  'def record_multichoice_sale(request):',
  'view helper: _mc_renewals_due_count'),
 ('core/views.py',
  'def cron_ensure_multichoice_open_week(request):',
  'def cron_mc_renewal_nudge(request):  # MC_RENEWALS_V2\n'
  '    if not _check_cron_secret(request):\n'
  "        return JsonResponse({'error': 'Unauthorized'}, status=403)\n"
  '    try:\n'
  '        from django.core.management import call_command\n'
  "        call_command('mc_renewal_nudge')\n"
  "        return JsonResponse({'ok': True, 'message': 'MultiChoice renewal notices sent'})\n"
  '    except Exception as e:\n'
  "        return JsonResponse({'ok': False, 'error': str(e)}, status=500)\n"
  '\n'
  '\n'
  'def cron_ensure_multichoice_open_week(request):',
  'view: cron_mc_renewal_nudge'),
 ('core/urls.py',
  "    path('renewals-due/', mcr.mc_renewals, name='mc_renewals'),  # MC_RENEWALS_V1",
  "    path('renewals-due/', mcr.mc_renewals, name='mc_renewals'),  # MC_RENEWALS_V1\n"
  "    path('cron/mc-renewal-nudge/', views.cron_mc_renewal_nudge, name='cron_mc_renewal_nudge'),  # MC_RENEWALS_V2",
  'url: cron/mc-renewal-nudge/'),
 ('core/mc_renewals.py',
  '        expiry = s.date + timedelta(days=CYCLE_DAYS)',
  "        expiry = s.date + timedelta(days=CYCLE_DAYS * max(1, getattr(s, 'months_paid', 1) or 1))  # MC_RENEWALS_V2",
  'renewals: expiry uses months paid'),
 ('templates/multichoice_dashboard.html',
  '            <option value="UPGRADE">Upgrade</option>\n          </select>\n        </div>\n      </div>',
  '            <option value="UPGRADE">Upgrade</option>\n'
  '          </select>\n'
  '        </div>\n'
  '        <div class="form-group"><label>Months paid *</label>{# MC_RENEWALS_V2 #}\n'
  '          <select name="months_paid" required>\n'
  '            <option value="1" selected>1 month</option>\n'
  '            <option value="2">2 months</option><option value="3">3 months</option><option value="4">4 months</option>\n'
  '            <option value="5">5 months</option><option value="6">6 months</option><option value="12">12 months</option>\n'
  '          </select>\n'
  '        </div>\n'
  '      </div>',
  'sale form: months paid'),
 ('templates/multichoice_dashboard.html',
  '<div class="dash-header">',
  '{% if renewals_due_count %}{# MC_RENEWALS_V2 #}\n'
  '<a href="{% url \'mc_renewals\' %}" style="display:block;background:#fef3c7;color:#92400e;border-radius:10px;padding:.8rem '
  '1rem;margin-bottom:1rem;text-decoration:none;font-size:.9rem;font-weight:600;">\n'
  '  🔔 {{ renewals_due_count }} customer{{ renewals_due_count|pluralize }} to remind about renewal. Tap to open Renewals Due.\n'
  '</a>\n'
  '{% endif %}\n'
  '<div class="dash-header">',
  'dashboard: renewal banner')]
NEWFILES = {'.github/workflows/mc_renewal_nudge.yml': '# MC_RENEWALS_V2\n'
                                           'name: GPSL MultiChoice Renewal Nudge\n'
                                           '\n'
                                           'on:\n'
                                           '  schedule:\n'
                                           '    # Daily 06:00 UTC = 7:00 am Lagos (WAT)\n'
                                           "    - cron: '0 6 * * *'\n"
                                           '  workflow_dispatch:\n'
                                           '\n'
                                           'jobs:\n'
                                           '  mc-renewal-nudge:\n'
                                           '    runs-on: ubuntu-latest\n'
                                           '    steps:\n'
                                           '      - name: Wake Render app\n'
                                           '        run: |\n'
                                           '          curl -s --max-time 60 "https://app.globalphonelinz.com/system/keepalive/" || true\n'
                                           '          sleep 15\n'
                                           '      - name: Send renewal nudges\n'
                                           '        env:\n'
                                           '          CRON_KEY: ${{ secrets.CRON_KEY }}\n'
                                           '        run: |\n'
                                           '          if [ -z "$CRON_KEY" ]; then\n'
                                           '            echo "CRON_KEY secret is not set (GitHub repo > Settings > Secrets and variables > '
                                           'Actions)"\n'
                                           '            exit 1\n'
                                           '          fi\n'
                                           '          curl -fsS --retry 2 --retry-delay 20 --retry-all-errors --max-time 120 \\\\\n'
                                           '            -H "X-Cron-Secret: $CRON_KEY" \\\\\n'
                                           '            "https://app.globalphonelinz.com/cron/mc-renewal-nudge/"\n',
 'core/management/commands/mc_renewal_nudge.py': '"""MC_RENEWALS_V2: each morning, tell every MultiChoice staff member how many of their '
                                                 'customers need a renewal reminder.\n'
                                                 '\n'
                                                 '    python manage.py mc_renewal_nudge            (send)\n'
                                                 '    python manage.py mc_renewal_nudge --dry-run  (preview only)\n'
                                                 'Safe to run twice a day: only one notice per person per day.\n'
                                                 '"""\n'
                                                 'from django.core.management.base import BaseCommand\n'
                                                 'from django.utils import timezone\n'
                                                 '\n'
                                                 'from core import mc_renewals as mr\n'
                                                 'from core.models import Notification, User\n'
                                                 '\n'
                                                 '\n'
                                                 'class Command(BaseCommand):\n'
                                                 '    help = "Send MultiChoice staff a daily in-app notice of customers due for renewal."\n'
                                                 '\n'
                                                 '    def add_arguments(self, parser):\n'
                                                 '        parser.add_argument("--dry-run", action="store_true")\n'
                                                 '\n'
                                                 '    def handle(self, *args, **opts):\n'
                                                 '        today = timezone.localdate()\n'
                                                 '        sent = 0\n'
                                                 '        for u in User.objects.filter(role="MULTICHOICE", is_active=True):\n'
                                                 '            due, overdue, _up, _lapsed = mr.bucket(mr.due_rows(u, today=today))\n'
                                                 '            n = len(due) + len(overdue)\n'
                                                 '            if not n:\n'
                                                 '                continue\n'
                                                 '            title = "%d MultiChoice customer%s to remind today" % (n, "" if n == 1 else '
                                                 '"s")\n'
                                                 '            already = Notification.objects.filter(recipient=u, notif_type="GENERAL", '
                                                 'title__startswith="%d MultiChoice" % n,\n'
                                                 '                                                  created_at__date=today).exists() or '
                                                 '\\\n'
                                                 '                Notification.objects.filter(recipient=u, link="/renewals-due/", '
                                                 'created_at__date=today).exists()\n'
                                                 '            if already:\n'
                                                 '                continue\n'
                                                 '            msg = "%d due within %d days and %d overdue. Open Renewals Due and tap '
                                                 'WhatsApp to remind them." % (\n'
                                                 '                len(due), mr.DUE_SOON_DAYS, len(overdue))\n'
                                                 '            if opts["dry_run"]:\n'
                                                 '                self.stdout.write("%s: %s" % (u.username, title))\n'
                                                 '            else:\n'
                                                 '                Notification.objects.create(recipient=u, notif_type="GENERAL", '
                                                 'title=title, message=msg, link="/renewals-due/")\n'
                                                 '            sent += 1\n'
                                                 '        self.stdout.write(self.style.SUCCESS("%s%d notice(s)" % ("[DRY RUN] " if '
                                                 'opts["dry_run"] else "", sent)))\n'}
MIGRATION = '# MC_RENEWALS_V2\nfrom django.db import migrations, models\n\n\nclass Migration(migrations.Migration):\n\n    dependencies = [\n        ("core", "@@LAST@@"),\n    ]\n\n    operations = [\n        migrations.AddField(\n            model_name="multichoicesale",\n            name="months_paid",\n            field=models.PositiveSmallIntegerField(default=1, help_text="How many months this payment covers (used for renewal reminders)."),\n        ),\n    ]\n'

def p(rel): return os.path.join(ROOT, *rel.split("/"))
def read(rel):
    with open(p(rel), encoding="utf-8") as f: return f.read()
if not os.path.exists(p("manage.py")) or not os.path.isdir(p("core")):
    print("ABORT: run this from the folder that contains manage.py"); sys.exit(1)
if not os.path.exists(p("core/mc_renewals.py")):
    print("ABORT: apply_mc_renewals.py has not been applied yet."); sys.exit(1)
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
    b = p(rel) + ".pre_mcren2.bak"
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
    name = "%04d_mc_months_paid.py" % (int(last[:4]) + 1)
    with open(os.path.join(mig_dir, name), "w", encoding="utf-8", newline="") as f:
        f.write(MIGRATION.replace("@@LAST@@", last))
    plan.append(("OK", "migration " + name)); wrote = True
for s, l in plan: print(("OK   " if s == "OK" else "SKIP ") + l)
print("\nDone. Next:  python manage.py migrate   then commit, push and redeploy." if (changed or wrote) else "\nNothing to do: already applied.")