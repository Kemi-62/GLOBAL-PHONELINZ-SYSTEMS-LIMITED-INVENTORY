#!/usr/bin/env python3
"""
apply_roles_v3_weekly.py   (marker: ROLES_V3)

Run after apply_roles_v2_delegation.py. Adds:
  * a Monday 7:00 am (Lagos) email to the Director listing what the Sub Director
    requested, approved and rejected that week, plus anything of theirs still waiting
    for the Director's confirmation
  * python-dateutil in requirements.txt (the monthly performance pages need it)

Needs no migration and no new secret (it uses the existing CRON_KEY).
Run from the project root:  python apply_roles_v3_weekly.py
Safe to run twice; checks everything before writing anything.
"""
import os, sys, shutil
ROOT = os.getcwd()
PATCHES = [('core/views.py',
  'def cron_backup(request):',
  'def cron_sub_director_weekly(request):  # ROLES_V3\n'
  '    if not _check_cron_secret(request):\n'
  "        return JsonResponse({'error': 'Unauthorized'}, status=403)\n"
  '    from django.core.management import call_command\n'
  "    email = request.GET.get('email', django_settings.DEFAULT_FROM_EMAIL or '')\n"
  '    if not email:\n'
  "        return JsonResponse({'error': 'No email provided'}, status=400)\n"
  '    try:\n'
  "        call_command('sub_director_weekly', email=email)\n"
  "        return JsonResponse({'ok': True, 'message': 'Sub Director weekly email sent'})\n"
  '    except Exception as e:\n'
  "        return JsonResponse({'ok': False, 'error': str(e)}, status=500)\n"
  '\n'
  'def cron_backup(request):',
  'view: cron_sub_director_weekly'),
 ('core/urls.py',
  "    path('cron/backup/', views.cron_backup, name='cron_backup'),",
  "    path('cron/backup/', views.cron_backup, name='cron_backup'),\n"
  "    path('cron/sub-director-weekly/', views.cron_sub_director_weekly, name='cron_sub_director_weekly'),  # ROLES_V3",
  'url: cron/sub-director-weekly/'),
 ('requirements.txt',
  'psycopg2-binary==2.9.11\n',
  'psycopg2-binary==2.9.11\npython-dateutil==2.9.0.post0\n',
  'requirements: python-dateutil')]
NEWFILES = {'.github/workflows/sub_director_weekly.yml': '# ROLES_V3\n'
                                              'name: GPSL Sub Director Weekly\n'
                                              '\n'
                                              'on:\n'
                                              '  schedule:\n'
                                              '    # Monday 06:00 UTC = 7:00 am Lagos (WAT)\n'
                                              "    - cron: '0 6 * * 1'\n"
                                              '  workflow_dispatch:\n'
                                              '\n'
                                              'jobs:\n'
                                              '  sub-director-weekly:\n'
                                              '    runs-on: ubuntu-latest\n'
                                              '    steps:\n'
                                              '      - name: Wake Render app\n'
                                              '        run: |\n'
                                              '          curl -s --max-time 60 "https://app.globalphonelinz.com/system/keepalive/" || '
                                              'true\n'
                                              '          sleep 15\n'
                                              '      - name: Send Sub Director weekly email\n'
                                              '        env:\n'
                                              '          CRON_KEY: ${{ secrets.CRON_KEY }}\n'
                                              '        run: |\n'
                                              '          if [ -z "$CRON_KEY" ]; then\n'
                                              '            echo "CRON_KEY secret is not set (GitHub repo > Settings > Secrets and '
                                              'variables > Actions)"\n'
                                              '            exit 1\n'
                                              '          fi\n'
                                              '          curl -fsS --retry 2 --retry-delay 20 --retry-all-errors --max-time 120 \\\n'
                                              '            -H "X-Cron-Secret: $CRON_KEY" \\\n'
                                              '            '
                                              '"https://app.globalphonelinz.com/cron/sub-director-weekly/?email=kemimonday00@gmail.com"\n',
 'core/management/commands/sub_director_weekly.py': '"""ROLES_V3: weekly email to the Director listing what the Sub Director(s) did.\n'
                                                    '\n'
                                                    'Usage: python manage.py sub_director_weekly --email=director@company.com [--days=7]\n'
                                                    '"""\n'
                                                    'from datetime import timedelta\n'
                                                    'from html import escape\n'
                                                    '\n'
                                                    'from django.conf import settings\n'
                                                    'from django.core.mail import EmailMultiAlternatives\n'
                                                    'from django.core.management.base import BaseCommand\n'
                                                    'from django.utils import timezone\n'
                                                    '\n'
                                                    'from core import models as m\n'
                                                    '\n'
                                                    '\n'
                                                    'class Command(BaseCommand):\n'
                                                    '    help = "Email the Director a weekly list of what the Sub Director requested, '
                                                    'approved and rejected."\n'
                                                    '\n'
                                                    '    def add_arguments(self, parser):\n'
                                                    '        parser.add_argument("--email", required=True)\n'
                                                    '        parser.add_argument("--days", type=int, default=7)\n'
                                                    '\n'
                                                    '    def handle(self, *args, **opts):\n'
                                                    '        days = opts["days"]\n'
                                                    '        since = timezone.now() - timedelta(days=days)\n'
                                                    '        events = (m.StockApprovalEvent.objects\n'
                                                    '                  .filter(actor__role="SUB_DIRECTOR", created_at__gte=since)\n'
                                                    '                  .select_related("actor", "request", "request__product", '
                                                    '"request__to_branch", "request__from_branch")\n'
                                                    '                  .order_by("created_at"))\n'
                                                    '        rows = list(events)\n'
                                                    '        waiting = m.StockApprovalRequest.objects.filter(\n'
                                                    '            status="PENDING", approval_stage="DIRECTOR", '
                                                    'requested_by__role="SUB_DIRECTOR").count()\n'
                                                    '        subject = "GPSL: Sub Director weekly activity (%s)" % '
                                                    'timezone.localtime().strftime("%d %b %Y")\n'
                                                    '        if not m.User.objects.filter(role="SUB_DIRECTOR").exists():\n'
                                                    '            self.stdout.write("No Sub Director account exists; nothing sent.")\n'
                                                    '            return\n'
                                                    '\n'
                                                    '        def line(e):\n'
                                                    '            r = e.request\n'
                                                    '            what = "%sx %s" % (r.quantity, r.product.model_name if r.product_id else '
                                                    '"item")\n'
                                                    '            where = "%s to %s" % (r.source_label, r.dest_label) if r.kind == "MOVE" '
                                                    'else "into %s" % r.dest_label\n'
                                                    '            act = "Requested" if e.action == "SUBMITTED" else e.action.replace("_", " '
                                                    '").title()\n'
                                                    '            when = timezone.localtime(e.created_at).strftime("%a %d %b, %H:%M")\n'
                                                    '            return when, e.actor.username if e.actor else "(removed)", act, "%s %s" % '
                                                    '(what, where), (e.detail or "")\n'
                                                    '\n'
                                                    '        lines = []\n'
                                                    '        for e in rows:\n'
                                                    '            try:\n'
                                                    '                lines.append(line(e))\n'
                                                    '            except Exception:\n'
                                                    '                continue\n'
                                                    '        text = ["Sub Director activity, last %d days: %d action(s)." % (days, '
                                                    'len(lines))]\n'
                                                    '        if waiting:\n'
                                                    '            text.append("%d of their stock addition(s) are waiting for YOUR '
                                                    'confirmation in Pending Approvals." % waiting)\n'
                                                    '        text += ["%s | %s | %s | %s" % l[:4] for l in lines] or ["Nothing this '
                                                    'week."]\n'
                                                    '        trs = "".join(\n'
                                                    '            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % '
                                                    'tuple(escape(str(x)) for x in l[:4]) for l in lines\n'
                                                    '        ) or "<tr><td colspan=\'4\'>Nothing this week.</td></tr>"\n'
                                                    '        html = (\n'
                                                    '            "<div style=\\"font-family:Segoe '
                                                    'UI,Arial,sans-serif;max-width:720px;margin:0 auto;color:#1e293b;\\">"\n'
                                                    '            "<div style=\'background:#004F9F;color:#fff;padding:1rem '
                                                    '1.4rem;border-radius:10px 10px 0 0;\'>"\n'
                                                    '            "<h2 style=\'margin:0;font-size:1.1rem;\'>Sub Director weekly '
                                                    'activity</h2>"\n'
                                                    '            "<p style=\'margin:.2rem 0 0;font-size:.8rem;opacity:.85;\'>Last %d days: '
                                                    '%d action(s)</p></div>"\n'
                                                    '            "<div style=\'border:1px solid #e2e8f0;border-top:none;padding:1rem '
                                                    '1.4rem;border-radius:0 0 10px 10px;\'>%s"\n'
                                                    '            "<table style=\'width:100%%;border-collapse:collapse;font-size:.85rem;\' '
                                                    'cellpadding=\'6\'>"\n'
                                                    '            "<tr '
                                                    'style=\'background:#f1f5f9;text-align:left;\'><th>When</th><th>Who</th><th>Action</th><th>Stock</th></tr>%s</table>"\n'
                                                    '            "<p style=\'font-size:.75rem;color:#94a3b8;\'>Full trail: Director menu, '
                                                    'Sub Director Activity.</p></div></div>"\n'
                                                    '            % (days, len(lines),\n'
                                                    '               ("<p style=\'background:#fef3c7;color:#92400e;padding:.6rem '
                                                    ".8rem;border-radius:8px;'>%d stock addition(s) from the Sub Director wait for your "
                                                    'confirmation in Pending Approvals.</p>" % waiting) if waiting else "",\n'
                                                    '               trs)\n'
                                                    '        )\n'
                                                    '        msg = EmailMultiAlternatives(subject, "\\n".join(text), '
                                                    'settings.DEFAULT_FROM_EMAIL, [opts["email"]])\n'
                                                    '        msg.attach_alternative(html, "text/html")\n'
                                                    '        msg.send()\n'
                                                    '        self.stdout.write(self.style.SUCCESS("Sent to %s (%d action(s))" % '
                                                    '(opts["email"], len(lines))))\n'}

def p(rel): return os.path.join(ROOT, *rel.split("/"))
def read(rel):
    with open(p(rel), encoding="utf-8") as f: return f.read()
if not os.path.exists(p("manage.py")) or not os.path.isdir(p("core")):
    print("ABORT: run this from the folder that contains manage.py"); sys.exit(1)
if "ROLES_V2" not in read("core/stock_approvals.py") and "ROLES_V2" not in read("core/views.py"):
    print("ABORT: apply_roles_v2_delegation.py has not been applied yet."); sys.exit(1)
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
    b = p(rel) + ".pre_roles3.bak"
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
print("\nDone. Commit, push and redeploy. Then test once: GitHub > Actions > GPSL Sub Director Weekly > Run workflow." if (changed or wrote) else "\nNothing to do: already applied.")