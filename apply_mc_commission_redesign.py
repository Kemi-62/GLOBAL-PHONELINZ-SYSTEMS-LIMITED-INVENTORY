"""
apply_mc_commission_redesign.py
==================================
Full redesign of the MultiChoice balance/commission system to close the
fraud loopholes in the manual-entry flow.

1. MANUAL BALANCE ENTRY REMOVED ENTIRELY
   "Record Balance", "Record Daily Balance", manual "Start This Week",
   and manual "Close This Week" are all disabled -- staff can no longer
   type in any balance figure themselves. The running balance is now
   ONLY ever changed by (a) recording an actual sale (auto-deducts cost
   price) or (b) voiding a sale (reverses it).

2. VOID A SUBSCRIPTION (same-day only for staff, any time for Director)
   - MultiChoice staff can void their OWN sale, but only from TODAY.
   - Director can void ANY sale, any day (oversight/correction).
   - Soft-delete (marked voided with a reason, staff, and timestamp --
     stays visible for audit) rather than a true delete.
   - The whole week's balance is recomputed from scratch after any void.

3. FULLY AUTOMATIC WEEKLY CYCLE
   - Every Sunday at 10pm WAT, each staff member's open week is closed
     and the NEXT week is immediately opened with the closing balance
     carried forward as the new opening balance.
   - A daily safety-net job makes sure nobody is ever left without an
     open week.

4. STREAMLINED COMMISSION TRACKING
   - "My Commissions" (staff) and "Commission Tracking" (Director) are
     rebuilt to pull from the system-computed weekly reports instead of
     the old manual-entry-triggered CommissionPayment model.
   - Director's Commission Tracking page also gets a "Today's MultiChoice
     Sales" oversight table with a Void action per row.

HOW TO RUN (Replit Shell)
    python apply_mc_commission_redesign.py

Then:
    python manage.py makemigrations --check
    python manage.py migrate
    python manage.py check
    python manage.py ensure_multichoice_open_week

Then push:
    git add . && git commit -m "MultiChoice: fraud-resistant commission redesign" && git push

IDEMPOTENT - safe to run twice.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def read(path):
    full = os.path.join(BASE_DIR, path)
    if not os.path.exists(full):
        print("XX Could not find " + path + " - are you running this from your project root?")
        sys.exit(1)
    with open(full, "r", encoding="utf-8") as f:
        return f.read()


def write(path, content):
    full = os.path.join(BASE_DIR, path)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


def patch(path, old, new, marker, label):
    content = read(path)
    if marker in content:
        print("SKIP  " + label + ": already applied, skipping.")
        return
    if old not in content:
        print("FAIL  " + label + ": couldn't find the expected anchor text in " + path + ".")
        print("      Your file may have changed since this script was written.")
        print("      Send the current version of that file and ask for a regenerated script.")
        sys.exit(1)
    content = content.replace(old, new, 1)
    write(path, content)
    print("OK    " + label + ": patched " + path)


MODELS_MARKER = "voided_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='voided_mc_sales')"

MODELS_OLD = '''    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.customer_name} - {self.package_type}"'''

MODELS_NEW = '''    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    is_voided = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True, default='')
    voided_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='voided_mc_sales')
    voided_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.customer_name} - {self.package_type}"'''


MIGRATION_CONTENT = '''# Generated manually to match Django 5.0.2 migration style
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0042_staff_monthly_performance'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='multichoicesale',
            name='is_voided',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='multichoicesale',
            name='void_reason',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='multichoicesale',
            name='voided_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='multichoicesale',
            name='voided_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='voided_mc_sales', to=settings.AUTH_USER_MODEL),
        ),
    ]
'''


RECORD_BALANCE_OLD_SIG = "def record_balance(request):"
RECORD_DAILY_BALANCE_OLD_SIG = "def record_daily_balance(request):"
START_WEEKLY_OLD_SIG = "def start_weekly_report(request):"
CLOSE_WEEKLY_OLD_SIG = "def close_weekly_report(request):"


def guard_function(content, func_signature, guard_message, label):
    marker = f"GUARD::{func_signature}"
    if marker in content:
        print("SKIP  " + label + ": already guarded, skipping.")
        return content, False

    idx = content.find(func_signature)
    if idx == -1:
        print("FAIL  " + label + ": function not found in core/views.py.")
        print("      Send the current version of core/views.py and ask for a regenerated script.")
        sys.exit(1)

    def_line_start = content.rfind("\n", 0, idx) + 1
    search_from = content.find("\n", idx) + 1
    pos = search_from
    next_def = content.find("\ndef ", pos - 1)
    next_at = content.find("\n@", pos - 1)
    candidates = [c for c in [next_def, next_at] if c != -1]
    end_idx = min(candidates) + 1 if candidates else len(content)

    func_name = func_signature.split("(")[0].replace("def ", "")
    params = func_signature.split("(", 1)[1]
    new_block = (
        f"# {marker}\n"
        f"def {func_name}({params}\n"
        f"    messages.info(request, \"{guard_message}\")\n"
        f"    return redirect(\"multichoice_dashboard\")\n\n\n"
    )
    content = content[:def_line_start] + new_block + content[end_idx:]
    print("OK    " + label + ": guarded")
    return content, True


VIEWS_NEW_FEATURES_MARKER = "def void_multichoice_sale(request, sale_id):"

VIEWS_NEW_FEATURES_OLD_ANCHOR = "# DIRECTOR \u2014 ALL BRANCH STOCK VIEW"

VIEWS_NEW_FEATURES_BLOCK = '''# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# MULTICHOICE COMMISSION REDESIGN -- VOID + AUTO WEEKLY CYCLE
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def _recompute_mc_weekly_balance(weekly_report):
    """Replay all non-voided sales for this weekly report in chronological
    order to recompute the running balance and total subscriptions from
    scratch -- keeps the balance correct regardless of which sale in the
    week's sequence was voided, and works whether the week is still open
    or already closed (recalculates commission too in that case)."""
    from datetime import timedelta
    from decimal import Decimal

    week_end = weekly_report.week_start_date + timedelta(days=7)
    sales = MultiChoiceSale.objects.filter(
        staff=weekly_report.staff,
        branch=weekly_report.branch,
        date__gte=weekly_report.week_start_date,
        date__lt=week_end,
        is_voided=False,
    ).order_by("date", "time", "id")

    running_balance = weekly_report.opening_balance + weekly_report.additional_funds
    total_subscriptions = Decimal("0")
    for sale in sales:
        running_balance = running_balance - sale.cost_price
        total_subscriptions += sale.amount

    weekly_report.closing_balance = running_balance
    weekly_report.total_subscriptions = total_subscriptions
    if weekly_report.is_closed:
        weekly_report.calculate_commission()
        weekly_report.save(update_fields=["closing_balance", "total_subscriptions", "commission"])
    else:
        weekly_report.save(update_fields=["closing_balance", "total_subscriptions"])


@login_required
def void_multichoice_sale(request, sale_id):
    """Void a MultiChoice subscription sale and reverse its balance impact.
    MultiChoice staff can only void their OWN sale, and only from TODAY.
    Director (or superuser) can void any sale, any day, for oversight."""
    from datetime import timedelta
    from django.urls import reverse

    sale = get_object_or_404(MultiChoiceSale, id=sale_id)
    is_director = request.user.role == "DIRECTOR" or request.user.is_superuser
    is_own_today = (
        request.user.role == "MULTICHOICE"
        and sale.staff_id == request.user.id
        and sale.date == timezone.now().date()
    )
    fallback_url = request.META.get("HTTP_REFERER") or reverse("multichoice_dashboard")

    if not (is_director or is_own_today):
        return HttpResponseForbidden("You don't have permission to void this sale.")

    if sale.is_voided:
        messages.info(request, "This sale has already been voided.")
        return redirect(fallback_url)

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        if not reason:
            messages.error(request, "Please provide a reason for voiding this sale.")
            return redirect(fallback_url)

        sale.is_voided = True
        sale.void_reason = reason
        sale.voided_by = request.user
        sale.voided_at = timezone.now()
        sale.save(update_fields=["is_voided", "void_reason", "voided_by", "voided_at"])

        week_start = sale.date - timedelta(days=sale.date.weekday())
        weekly_report = MultiChoiceWeeklyReport.objects.filter(
            staff=sale.staff, branch=sale.branch, week_start_date=week_start
        ).first()
        if weekly_report:
            _recompute_mc_weekly_balance(weekly_report)

        messages.success(request, f"Subscription voided. \\u20a6{sale.cost_price:,.2f} added back to the balance.")
    return redirect(fallback_url)


def cron_close_multichoice_week(request):
    if not _check_cron_secret(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    try:
        from django.core.management import call_command
        call_command('close_multichoice_week')
        return JsonResponse({'ok': True, 'message': 'MultiChoice weekly reports closed; next week started for each staff member'})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


def cron_ensure_multichoice_open_week(request):
    if not _check_cron_secret(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    try:
        from django.core.management import call_command
        call_command('ensure_multichoice_open_week')
        return JsonResponse({'ok': True, 'message': 'Ensured every MultiChoice staff member has an open weekly report'})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


# DIRECTOR \u2014 ALL BRANCH STOCK VIEW'''


MY_COMMISSIONS_MARKER = "reports = MultiChoiceWeeklyReport.objects.filter(\n        staff=request.user\n    ).order_by(\"-week_start_date\")"
MY_COMMISSIONS_OLD_SIG = "def my_commissions(request):"

COMMISSION_TRACKING_MARKER = "todays_mc_sales"
COMMISSION_TRACKING_OLD_SIG = "def commission_tracking(request):"


URLS_MARKER = "void_multichoice_sale"

URLS_OLD_ANCHOR = "    path('multichoice/add-weekly-funds/', views.add_weekly_funds, name='add_weekly_funds'),\n]"

URLS_NEW_BLOCK_WITH_FUNDS = '''    path('multichoice/add-weekly-funds/', views.add_weekly_funds, name='add_weekly_funds'),
    path('multichoice/void-sale/<int:sale_id>/', views.void_multichoice_sale, name='void_multichoice_sale'),
    path('cron/close-multichoice-week/', views.cron_close_multichoice_week, name='cron_close_multichoice_week'),
    path('cron/ensure-multichoice-open-week/', views.cron_ensure_multichoice_open_week, name='cron_ensure_multichoice_open_week'),
]'''

URLS_OLD_ANCHOR_NO_FUNDS = "    path('my-customers/export/', views.export_my_customers_csv, name='export_my_customers_csv'),\n]"

URLS_NEW_BLOCK_NO_FUNDS = '''    path('my-customers/export/', views.export_my_customers_csv, name='export_my_customers_csv'),
    path('multichoice/void-sale/<int:sale_id>/', views.void_multichoice_sale, name='void_multichoice_sale'),
    path('cron/close-multichoice-week/', views.cron_close_multichoice_week, name='cron_close_multichoice_week'),
    path('cron/ensure-multichoice-open-week/', views.cron_ensure_multichoice_open_week, name='cron_ensure_multichoice_open_week'),
]'''


CLOSE_WEEK_COMMAND = '''"""Close every MultiChoice staff member's current open weekly report and
immediately start next week's report with the closing balance carried
forward as the new opening balance. Runs automatically every Sunday at
10pm WAT -- see .github/workflows/mc_weekly_close.yml."""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from core.models import MultiChoiceWeeklyReport, MultiChoiceSale


class Command(BaseCommand):
    help = "Close all open MultiChoice weekly reports and auto-start next week."

    def handle(self, *args, **options):
        closed_count = 0
        open_reports = MultiChoiceWeeklyReport.objects.filter(is_closed=False)

        for report in open_reports:
            week_end = report.week_start_date + timedelta(days=7)
            week_total = MultiChoiceSale.objects.filter(
                staff=report.staff, branch=report.branch,
                date__gte=report.week_start_date, date__lt=week_end,
                is_voided=False,
            ).aggregate(t=Sum("amount"))["t"] or Decimal("0")
            report.total_subscriptions = week_total
            if report.closing_balance is None:
                report.closing_balance = report.opening_balance + report.additional_funds
            report.calculate_commission()
            report.is_closed = True
            report.save()
            closed_count += 1

            next_week_start = report.week_start_date + timedelta(days=7)
            MultiChoiceWeeklyReport.objects.get_or_create(
                staff=report.staff, branch=report.branch,
                week_start_date=next_week_start,
                defaults={
                    "opening_balance": report.closing_balance,
                    "additional_funds": Decimal("0"),
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f"Closed {closed_count} weekly report(s) and started next week for each."
        ))
'''

ENSURE_OPEN_WEEK_COMMAND = '''"""Safety net: make sure every MultiChoice staff member has an open
weekly report for the current week. Idempotent -- safe to run daily."""
from datetime import timedelta, date as _date
from decimal import Decimal

from django.core.management.base import BaseCommand

from core.models import User, MultiChoiceWeeklyReport


class Command(BaseCommand):
    help = "Ensure every MultiChoice staff member has an open weekly report for the current week."

    def handle(self, *args, **options):
        today = _date.today()
        week_start = today - timedelta(days=today.weekday())
        created_count = 0

        for staff in User.objects.filter(role="MULTICHOICE"):
            existing = MultiChoiceWeeklyReport.objects.filter(
                staff=staff, branch=staff.branch, week_start_date=week_start
            ).first()
            if existing:
                continue

            last_closed = MultiChoiceWeeklyReport.objects.filter(
                staff=staff, branch=staff.branch, is_closed=True
            ).order_by("-week_start_date").first()
            opening_balance = (
                last_closed.closing_balance
                if last_closed and last_closed.closing_balance is not None
                else Decimal("0")
            )

            MultiChoiceWeeklyReport.objects.create(
                staff=staff, branch=staff.branch, week_start_date=week_start,
                opening_balance=opening_balance, additional_funds=Decimal("0"),
            )
            created_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Checked all MultiChoice staff -- created {created_count} new open week report(s)."
        ))
'''


DASH_STARTWEEK_MARKER = "starts automatically"

DASH_STARTWEEK_OLD = '''{% if not weekly_report %}
<div class="week-status week-none">
  <strong>\u26A0\uFE0F No active weekly report.</strong> Start one before recording subscriptions.
  {% if is_monday %}
  <form method="POST" action="{% url 'start_weekly_report' %}" style="margin-top:.8rem;">
    {% csrf_token %}
    <div class="form-row">
      <div class="form-group"><label>Opening Balance (\u20a6) *</label><input type="number" name="opening_balance" step="0.01" min="0" placeholder="Cash/balance you start with" required></div>
      <div class="form-group"><label>Additional Funds (\u20a6)</label><input type="number" name="additional_funds" step="0.01" min="0" placeholder="0.00"></div>
    </div>
    <button type="submit" class="btn-sm btn-success">\u25B6 Start This Week</button>
  </form>
  {% else %}
  <p style="margin:.5rem 0 0;font-size:.83rem;">Weekly reports can only be started on Monday.</p>
  {% endif %}
</div>
{% endif %}'''

DASH_STARTWEEK_NEW = '''{% if not weekly_report %}
<div class="week-status week-none">
  <strong>\u23F3 Setting up your week.</strong> Your weekly report starts automatically -- check back shortly, or contact your Director if this doesn't resolve on its own.
</div>
{% endif %}'''

DASH_CLOSEWEEK_MARKER = "closes automatically every Sunday"

DASH_CLOSEWEEK_OLD = '''  {% if is_saturday %}
  <div class="card">
    <p class="card-title">\U0001F512 Close This Week</p>
    <form method="POST" action="{% url 'close_weekly_report' %}">
      {% csrf_token %}
      <div class="form-group"><label>Closing Balance (\u20a6) *</label><input type="number" name="closing_balance" step="0.01" min="0" required placeholder="Your cash balance at end of week"></div>
      <button type="submit" class="btn-sm btn-danger" onclick="return confirm('Close this week? This cannot be undone.')">Close Week & Calculate Commission</button>
    </form>
  </div>
  {% endif %}'''

DASH_CLOSEWEEK_NEW = '''  <div class="card" style="background:#eff6ff;border-color:#bfdbfe;">
    <p style="margin:0;font-size:.83rem;color:#1e40af;">\U0001F512 Your week closes automatically every Sunday at 10pm \u2014 no action needed. Next Monday's opening balance carries forward automatically.</p>
  </div>'''

DASH_VOID_MARKER = "void_multichoice_sale"

DASH_LEFTOVER_MSG_MARKER = "next week begins automatically"

DASH_LEFTOVER_MSG_OLD = '''  {% else %}
  <div style="background:#fef3c7;border:1px solid #fcd34d;border-radius:8px;padding:.9rem 1rem;font-size:.85rem;color:#92400e;">
    {% if not weekly_report %}\u26A0\uFE0F Start a weekly report first.
    {% else %}\u2705 This week is closed. Start next week on Monday.{% endif %}
  </div>
  {% endif %}'''

DASH_LEFTOVER_MSG_NEW = '''  {% else %}
  <div style="background:#fef3c7;border:1px solid #fcd34d;border-radius:8px;padding:.9rem 1rem;font-size:.85rem;color:#92400e;">
    {% if not weekly_report %}\u23F3 Setting up your week \u2014 check back shortly.
    {% else %}\u2705 This week is closed \u2014 next week begins automatically.{% endif %}
  </div>
  {% endif %}'''

DASH_VOID_OLD = '''            <td>
              <a href="{% url 'invoice_preview' sale_type='MULTICHOICE' sale_id=sale.id %}" class="btn-sm btn-outline" style="font-size:.72rem;padding:.25rem .55rem;">\U0001F9FE Invoice</a>
            </td>
          </tr>
          {% empty %}
          <tr><td colspan="10" style="text-align:center;color:#9ca3af;padding:1.5rem;">No subscriptions today yet.</td></tr>'''

DASH_VOID_NEW = '''            <td>
              {% if sale.is_voided %}
              <span class="badge" style="background:#fee2e2;color:#991b1b;padding:.2rem .5rem;border-radius:999px;font-size:.7rem;">Voided</span>
              {% else %}
              <a href="{% url 'invoice_preview' sale_type='MULTICHOICE' sale_id=sale.id %}" class="btn-sm btn-outline" style="font-size:.72rem;padding:.25rem .55rem;">\U0001F9FE Invoice</a>
              <form method="POST" action="{% url 'void_multichoice_sale' sale.id %}" style="display:inline-flex;gap:.3rem;margin-left:.3rem;vertical-align:middle;" onsubmit="return confirm('Void this subscription? The cost will be added back to your balance.');">
                {% csrf_token %}
                <input type="text" name="reason" placeholder="Reason" required style="width:80px;font-size:.7rem;padding:.2rem .35rem;border:1px solid #d1d5db;border-radius:4px;">
                <button type="submit" class="btn-sm btn-outline" style="font-size:.72rem;padding:.25rem .5rem;color:#ef4444;border-color:#fecaca;">\U0001F5D1</button>
              </form>
              {% endif %}
            </td>
          </tr>
          {% empty %}
          <tr><td colspan="10" style="text-align:center;color:#9ca3af;padding:1.5rem;">No subscriptions today yet.</td></tr>'''


SIDEBAR_MARKER = "#balance\" class=\"sidebar-link\""

SIDEBAR_OLD = '''        <a href="{% url 'record_balance' %}" class="sidebar-link">
            <span class="icon">\U0001F4B3</span> Record Balance
        </a>
    </div>
    <div class="sidebar-divider"></div>
    <div class="sidebar-section">
        <div class="sidebar-section-label">Earnings</div>
        <a href="{% url 'my_commissions' %}" class="sidebar-link">
            <span class="icon">\U0001F4B0</span> My Commissions
        </a>
        <a href="{% url 'start_weekly_report' %}" class="sidebar-link">
            <span class="icon">\U0001F4CA</span> Weekly Report
        </a>
    </div>'''

SIDEBAR_NEW = '''    </div>
    <div class="sidebar-divider"></div>
    <div class="sidebar-section">
        <div class="sidebar-section-label">Earnings</div>
        <a href="{% url 'my_commissions' %}" class="sidebar-link">
            <span class="icon">\U0001F4B0</span> My Commissions
        </a>
        <a href="{% url 'multichoice_dashboard' %}#balance" class="sidebar-link">
            <span class="icon">\U0001F4CA</span> Weekly Report
        </a>
    </div>'''


MY_COMMISSIONS_TEMPLATE = '''{% extends "base.html" %}
{% block content %}
<div class="card">
    <h2 style="margin:0;">\U0001F4B0 My Commissions</h2>
    <p style="color:#6b7280;margin:.4rem 0 0;">Calculated automatically from your weekly balance and subscription sales \u2014 no manual entry, nothing to fake.</p>
</div>

<div style="display:flex;gap:1rem;flex-wrap:wrap;">
  <div class="card" style="flex:1;min-width:200px;border-left:5px solid #10b981;">
      <h3 style="margin:0;font-size:.85rem;color:#6b7280;">Total Commission Earned</h3>
      <p style="font-size:2rem;font-weight:bold;color:#004F9F;margin:.4rem 0 0;">\u20a6{{ total_earned|floatformat:2 }}</p>
  </div>
  <div class="card" style="flex:1;min-width:200px;border-left:5px solid #8b5cf6;">
      <h3 style="margin:0;font-size:.85rem;color:#6b7280;">This Month</h3>
      <p style="font-size:2rem;font-weight:bold;color:#5b21b6;margin:.4rem 0 0;">\u20a6{{ month_earned|floatformat:2 }}</p>
  </div>
</div>

<div class="card">
    <h3 style="margin:0 0 1rem;">\U0001F4CB Weekly Commission History</h3>
    <div style="overflow-x:auto;">
    <table class="data-table">
        <thead>
            <tr>
                <th>Week</th>
                <th style="text-align:right;">Opening</th>
                <th style="text-align:right;">Additional Funds</th>
                <th style="text-align:right;">Subscriptions Sold</th>
                <th style="text-align:right;">Closing Balance</th>
                <th style="text-align:right;">Commission</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody>
            {% for r in reports %}
            <tr>
                <td><strong>{{ r.week_start_date|date:"d M Y" }}</strong></td>
                <td style="text-align:right;">\u20a6{{ r.opening_balance|floatformat:2 }}</td>
                <td style="text-align:right;">\u20a6{{ r.additional_funds|floatformat:2 }}</td>
                <td style="text-align:right;">\u20a6{{ r.total_subscriptions|floatformat:2 }}</td>
                <td style="text-align:right;">{% if r.closing_balance is not None %}\u20a6{{ r.closing_balance|floatformat:2 }}{% else %}\u2014{% endif %}</td>
                <td style="text-align:right;font-weight:700;color:{% if r.commission >= 0 %}#065f46{% else %}#991b1b{% endif %};">\u20a6{{ r.commission|floatformat:2 }}</td>
                <td>
                  {% if r.is_closed %}<span class="badge" style="background:#d1fae5;color:#065f46;padding:.2rem .5rem;border-radius:999px;font-size:.72rem;">Closed</span>
                  {% else %}<span class="badge" style="background:#fef3c7;color:#92400e;padding:.2rem .5rem;border-radius:999px;font-size:.72rem;">Open</span>{% endif %}
                </td>
            </tr>
            {% empty %}
            <tr><td colspan="7" style="text-align:center;padding:2rem;color:#9ca3af;">No weekly reports yet \u2014 this fills in automatically as weeks close.</td></tr>
            {% endfor %}
        </tbody>
    </table>
    </div>
</div>
{% endblock %}
'''


CT_ALLCOMM_MARKER = "Weekly report</td>"

CT_ALLCOMM_OLD = '''          {% for c in mc_commissions %}
          <tr>
            <td style="color:#9ca3af;white-space:nowrap;">{{ c.date_detected|date:"d M Y" }}</td>
            <td style="color:#9ca3af;">{{ c.date_detected|time:"H:i"|default:"\u2014" }}</td>
            <td><span class="badge badge-purple">\U0001F4FA MultiChoice</span></td>
            <td><strong>{{ c.staff.username }}</strong></td>
            <td>{{ c.branch.name }}</td>
            <td style="font-size:.78rem;color:#6b7280;">Balance increase detected</td>
            <td style="text-align:right;font-weight:700;color:#5b21b6;">\u20a6{{ c.commission_detected|floatformat:2 }}</td>
            <td>System</td>
          </tr>
          {% empty %}
          {% endfor %}
          {% if not telecom_commissions and not mc_commissions %}'''

CT_ALLCOMM_NEW = '''          {% for c in mc_reports %}
          <tr>
            <td style="color:#9ca3af;white-space:nowrap;">{{ c.week_start_date|date:"d M Y" }}</td>
            <td style="color:#9ca3af;">Week</td>
            <td><span class="badge badge-purple">\U0001F4FA MultiChoice</span></td>
            <td><strong>{{ c.staff.username }}</strong></td>
            <td>{{ c.branch.name }}</td>
            <td style="font-size:.78rem;color:#6b7280;">Weekly report</td>
            <td style="text-align:right;font-weight:700;color:#5b21b6;">\u20a6{{ c.commission|floatformat:2 }}</td>
            <td>System</td>
          </tr>
          {% empty %}
          {% endfor %}
          {% if not telecom_commissions and not mc_reports %}'''

CT_MCTAB_MARKER = "Today's MultiChoice Sales"

CT_MCTAB_OLD = '''<div id="tab-multichoice" class="tab-panel">
  <div class="card">
    <p class="card-title">\U0001F4FA MultiChoice Commissions</p>
    <p style="font-size:.83rem;color:#6b7280;margin-bottom:1rem;">Auto-detected when closing balance exceeds expected balance at end of week.</p>
    <div style="overflow-x:auto;">
      <table class="data-table">
        <thead>
          <tr>
            <th>Date Detected</th>
            <th>Staff</th>
            <th>Branch</th>
            <th>Previous Balance</th>
            <th>Closing Balance</th>
            <th style="text-align:right;">Commission</th>
          </tr>
        </thead>
        <tbody>
          {% for c in mc_commissions %}
          <tr>
            <td style="color:#9ca3af;white-space:nowrap;">{{ c.date_detected|date:"d M Y" }}</td>
            <td><strong>{{ c.staff.username }}</strong></td>
            <td>{{ c.branch.name }}</td>
            <td>\u20a6{{ c.previous_balance|floatformat:2 }}</td>
            <td>\u20a6{{ c.current_balance|floatformat:2 }}</td>
            <td style="text-align:right;font-weight:700;color:#5b21b6;">\u20a6{{ c.commission_detected|floatformat:2 }}</td>
          </tr>
          {% empty %}
          <tr><td colspan="6" style="text-align:center;color:#9ca3af;padding:2rem 0;">No MultiChoice commission records.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    <div style="margin-top:1rem;padding-top:1rem;border-top:1px solid #f3f4f6;text-align:right;">
      <strong>Total MultiChoice Commissions: \u20a6{{ total_mc|floatformat:2 }}</strong>
    </div>
  </div>
</div>'''

CT_MCTAB_NEW = '''<div id="tab-multichoice" class="tab-panel">
  <div class="card">
    <p class="card-title">\U0001F4FA MultiChoice Weekly Commission Reports</p>
    <p style="font-size:.83rem;color:#6b7280;margin-bottom:1rem;">Computed automatically from each staff member's weekly balance and subscription sales \u2014 no manual entry involved.</p>
    <div style="overflow-x:auto;">
      <table class="data-table">
        <thead>
          <tr>
            <th>Week</th>
            <th>Staff</th>
            <th>Branch</th>
            <th style="text-align:right;">Opening</th>
            <th style="text-align:right;">Additional Funds</th>
            <th style="text-align:right;">Subscriptions</th>
            <th style="text-align:right;">Closing</th>
            <th style="text-align:right;">Commission</th>
          </tr>
        </thead>
        <tbody>
          {% for r in mc_reports %}
          <tr>
            <td style="color:#9ca3af;white-space:nowrap;">{{ r.week_start_date|date:"d M Y" }}</td>
            <td><strong>{{ r.staff.username }}</strong></td>
            <td>{{ r.branch.name }}</td>
            <td style="text-align:right;">\u20a6{{ r.opening_balance|floatformat:2 }}</td>
            <td style="text-align:right;">\u20a6{{ r.additional_funds|floatformat:2 }}</td>
            <td style="text-align:right;">\u20a6{{ r.total_subscriptions|floatformat:2 }}</td>
            <td style="text-align:right;">\u20a6{{ r.closing_balance|floatformat:2 }}</td>
            <td style="text-align:right;font-weight:700;color:#5b21b6;">\u20a6{{ r.commission|floatformat:2 }}</td>
          </tr>
          {% empty %}
          <tr><td colspan="8" style="text-align:center;color:#9ca3af;padding:2rem 0;">No closed weekly reports yet.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    <div style="margin-top:1rem;padding-top:1rem;border-top:1px solid #f3f4f6;text-align:right;">
      <strong>Total MultiChoice Commissions: \u20a6{{ total_mc|floatformat:2 }}</strong>
    </div>
  </div>

  <div class="card">
    <p class="card-title">\U0001F5D1 Today's MultiChoice Sales \u2014 Void a Sale</p>
    <p style="font-size:.83rem;color:#6b7280;margin-bottom:1rem;">Director oversight: void an incorrect sale from today, any branch or staff member. Voiding reverses the balance deduction automatically.</p>
    <div style="overflow-x:auto;">
      <table class="data-table">
        <thead><tr><th>Time</th><th>Staff</th><th>Branch</th><th>Customer</th><th>Service</th><th style="text-align:right;">Amount</th><th style="text-align:right;">Cost</th><th>Status</th><th>Action</th></tr></thead>
        <tbody>
          {% for sale in todays_mc_sales %}
          <tr>
            <td style="color:#9ca3af;">{{ sale.time|time:"H:i" }}</td>
            <td><strong>{{ sale.staff.username }}</strong></td>
            <td>{{ sale.branch.name }}</td>
            <td>{{ sale.customer_name }}</td>
            <td>{{ sale.service_type }} - {{ sale.package_type }}</td>
            <td style="text-align:right;">\u20a6{{ sale.amount|floatformat:2 }}</td>
            <td style="text-align:right;color:#ef4444;">\u20a6{{ sale.cost_price|floatformat:2 }}</td>
            <td>
              {% if sale.is_voided %}<span class="badge" style="background:#fee2e2;color:#991b1b;padding:.2rem .5rem;border-radius:999px;font-size:.7rem;">Voided</span>
              {% else %}<span class="badge badge-green">Active</span>{% endif %}
            </td>
            <td>
              {% if not sale.is_voided %}
              <form method="POST" action="{% url 'void_multichoice_sale' sale.id %}" style="display:inline-flex;gap:.3rem;" onsubmit="return confirm('Void this sale? Balance will be reversed.');">
                {% csrf_token %}
                <input type="text" name="reason" placeholder="Reason" required style="width:90px;font-size:.72rem;padding:.25rem .4rem;border:1px solid #d1d5db;border-radius:4px;">
                <button type="submit" class="btn-sm btn-outline" style="font-size:.72rem;padding:.25rem .5rem;color:#ef4444;border-color:#fecaca;">Void</button>
              </form>
              {% else %}
              <span style="font-size:.72rem;color:#9ca3af;">by {{ sale.voided_by.username|default:"\u2014" }}</span>
              {% endif %}
            </td>
          </tr>
          {% empty %}
          <tr><td colspan="9" style="text-align:center;color:#9ca3af;padding:1.5rem;">No MultiChoice sales recorded today.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>'''


MC_WEEKLY_CLOSE_YML = '''name: GPSL MultiChoice Weekly Close

on:
  schedule:
    - cron: '0 21 * * 0'
  workflow_dispatch:

jobs:
  close-mc-week:
    runs-on: ubuntu-latest
    steps:
      - name: Wake Render app
        run: |
          curl -s --max-time 60 "https://app.globalphonelinz.com/system/keepalive/" || true
          sleep 15
      - name: Close MultiChoice weekly reports
        run: |
          curl -s --max-time 120 \\
            "https://app.globalphonelinz.com/cron/close-multichoice-week/?key=gpsl2026backup"
'''

MC_ENSURE_OPEN_YML = '''name: GPSL MultiChoice Ensure Open Week

on:
  schedule:
    - cron: '10 0 * * *'
  workflow_dispatch:

jobs:
  ensure-mc-open-week:
    runs-on: ubuntu-latest
    steps:
      - name: Wake Render app
        run: |
          curl -s --max-time 60 "https://app.globalphonelinz.com/system/keepalive/" || true
          sleep 15
      - name: Ensure open weekly reports
        run: |
          curl -s --max-time 120 \\
            "https://app.globalphonelinz.com/cron/ensure-multichoice-open-week/?key=gpsl2026backup"
'''


def main():
    print("-- Applying MultiChoice Commission Redesign --\n")

    patch("core/models.py", MODELS_OLD, MODELS_NEW, MODELS_MARKER,
          "models.py: MultiChoiceSale void fields")

    migration_path = os.path.join(BASE_DIR, "core", "migrations", "0043_multichoice_sale_void_fields.py")
    if os.path.exists(migration_path):
        print("SKIP  migration 0043: already exists, skipping.")
    else:
        write("core/migrations/0043_multichoice_sale_void_fields.py", MIGRATION_CONTENT)
        print("OK    Created core/migrations/0043_multichoice_sale_void_fields.py")

    content = read("core/views.py")
    changed_any = False
    for sig, label, msg in [
        (RECORD_BALANCE_OLD_SIG, "views.py: guard record_balance",
         "Manual balance entry has been disabled -- your balance updates automatically with each sale."),
        (RECORD_DAILY_BALANCE_OLD_SIG, "views.py: guard record_daily_balance",
         "Manual balance entry has been disabled -- your balance updates automatically with each sale."),
        (START_WEEKLY_OLD_SIG, "views.py: guard start_weekly_report",
         "Weekly reports now start automatically -- no manual action needed."),
        (CLOSE_WEEKLY_OLD_SIG, "views.py: guard close_weekly_report",
         "Weeks now close automatically every Sunday at 10pm -- no manual action needed."),
    ]:
        content, did_change = guard_function(content, sig, msg, label)
        changed_any = changed_any or did_change
    if changed_any:
        write("core/views.py", content)

    patch("core/views.py", VIEWS_NEW_FEATURES_OLD_ANCHOR, VIEWS_NEW_FEATURES_BLOCK, VIEWS_NEW_FEATURES_MARKER,
          "views.py: void_multichoice_sale + cron endpoints")

    content = read("core/views.py")
    if MY_COMMISSIONS_MARKER not in content:
        idx = content.find(MY_COMMISSIONS_OLD_SIG)
        if idx == -1:
            print("FAIL  views.py: my_commissions not found (may already be guarded/renamed).")
            sys.exit(1)
        def_line_start = content.rfind("\n", 0, idx) + 1
        search_from = content.find("\n", idx) + 1
        pos = search_from
        next_def = content.find("\ndef ", pos - 1)
        next_at = content.find("\n@", pos - 1)
        candidates = [c for c in [next_def, next_at] if c != -1]
        end_idx = min(candidates) + 1 if candidates else len(content)

        new_my_commissions = '''def my_commissions(request):
    from django.db.models import Sum
    from django.utils import timezone as _tz

    reports = MultiChoiceWeeklyReport.objects.filter(
        staff=request.user
    ).order_by("-week_start_date")

    total_earned = reports.filter(is_closed=True).aggregate(t=Sum("commission"))["t"] or 0
    this_month = _tz.now().date().replace(day=1)
    month_earned = reports.filter(
        is_closed=True, week_start_date__gte=this_month
    ).aggregate(t=Sum("commission"))["t"] or 0

    return render(request, "my_commissions.html", {
        "reports": reports,
        "total_earned": total_earned,
        "month_earned": month_earned,
    })


'''
        content = content[:def_line_start] + new_my_commissions + content[end_idx:]
        write("core/views.py", content)
        print("OK    views.py: my_commissions rebuilt")
    else:
        print("SKIP  views.py: my_commissions already rebuilt, skipping.")

    content = read("core/views.py")
    if COMMISSION_TRACKING_MARKER not in content:
        idx = content.find(COMMISSION_TRACKING_OLD_SIG)
        if idx == -1:
            print("FAIL  views.py: commission_tracking not found.")
            sys.exit(1)
        def_line_start = content.rfind("\n", 0, idx) + 1
        search_from = content.find("\n", idx) + 1
        pos = search_from
        next_def = content.find("\ndef ", pos - 1)
        next_at = content.find("\n@", pos - 1)
        candidates = [c for c in [next_def, next_at] if c != -1]
        end_idx = min(candidates) + 1 if candidates else len(content)

        new_commission_tracking = '''def commission_tracking(request):
    from django.db.models import Sum

    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to", "")
    branch_flt = request.GET.get("branch", "")
    comm_type  = request.GET.get("type", "")

    mc_reports = MultiChoiceWeeklyReport.objects.filter(
        is_closed=True
    ).select_related("staff", "branch").order_by("-week_start_date")

    telecom_commissions = DeviceTagCommission.objects.select_related(
        "device_tag", "branch", "created_by"
    ).order_by("-created_at")

    if date_from:
        mc_reports = mc_reports.filter(week_start_date__gte=date_from)
        telecom_commissions = telecom_commissions.filter(created_at__date__gte=date_from)
    if date_to:
        mc_reports = mc_reports.filter(week_start_date__lte=date_to)
        telecom_commissions = telecom_commissions.filter(created_at__date__lte=date_to)
    if branch_flt:
        mc_reports = mc_reports.filter(branch_id=branch_flt)
        telecom_commissions = telecom_commissions.filter(branch_id=branch_flt)

    total_mc = mc_reports.aggregate(t=Sum("commission"))["t"] or 0
    total_telecom = telecom_commissions.aggregate(t=Sum("commission_amount"))["t"] or 0

    today = timezone.now().date()
    todays_mc_sales = MultiChoiceSale.objects.filter(
        date=today
    ).select_related("staff", "branch").order_by("-time")

    return render(request, "commission_tracking.html", {
        "mc_reports": mc_reports,
        "telecom_commissions": telecom_commissions,
        "total_mc": total_mc,
        "total_telecom": total_telecom,
        "grand_total": total_mc + total_telecom,
        "branches": Branch.objects.all(),
        "date_from": date_from,
        "date_to": date_to,
        "branch_flt": branch_flt,
        "comm_type": comm_type,
        "todays_mc_sales": todays_mc_sales,
    })


'''
        content = content[:def_line_start] + new_commission_tracking + content[end_idx:]
        write("core/views.py", content)
        print("OK    views.py: commission_tracking rebuilt")
    else:
        print("SKIP  views.py: commission_tracking already rebuilt, skipping.")

    urls_content = read("core/urls.py")
    if URLS_MARKER in urls_content:
        print("SKIP  urls.py: void/cron routes already present, skipping.")
    elif URLS_OLD_ANCHOR in urls_content:
        patch("core/urls.py", URLS_OLD_ANCHOR, URLS_NEW_BLOCK_WITH_FUNDS, URLS_MARKER,
              "urls.py: void + cron routes")
    else:
        patch("core/urls.py", URLS_OLD_ANCHOR_NO_FUNDS, URLS_NEW_BLOCK_NO_FUNDS, URLS_MARKER,
              "urls.py: void + cron routes")

    close_cmd_path = os.path.join(BASE_DIR, "core", "management", "commands", "close_multichoice_week.py")
    if os.path.exists(close_cmd_path):
        print("SKIP  close_multichoice_week.py: already exists, skipping.")
    else:
        write("core/management/commands/close_multichoice_week.py", CLOSE_WEEK_COMMAND)
        print("OK    Created core/management/commands/close_multichoice_week.py")

    ensure_cmd_path = os.path.join(BASE_DIR, "core", "management", "commands", "ensure_multichoice_open_week.py")
    if os.path.exists(ensure_cmd_path):
        print("SKIP  ensure_multichoice_open_week.py: already exists, skipping.")
    else:
        write("core/management/commands/ensure_multichoice_open_week.py", ENSURE_OPEN_WEEK_COMMAND)
        print("OK    Created core/management/commands/ensure_multichoice_open_week.py")

    patch("templates/multichoice_dashboard.html", DASH_STARTWEEK_OLD, DASH_STARTWEEK_NEW, DASH_STARTWEEK_MARKER,
          "multichoice_dashboard.html: remove manual Start Week form")
    patch("templates/multichoice_dashboard.html", DASH_CLOSEWEEK_OLD, DASH_CLOSEWEEK_NEW, DASH_CLOSEWEEK_MARKER,
          "multichoice_dashboard.html: remove manual Close Week form")
    patch("templates/multichoice_dashboard.html", DASH_VOID_OLD, DASH_VOID_NEW, DASH_VOID_MARKER,
          "multichoice_dashboard.html: add Void button to today's subscriptions")
    patch("templates/multichoice_dashboard.html", DASH_LEFTOVER_MSG_OLD, DASH_LEFTOVER_MSG_NEW, DASH_LEFTOVER_MSG_MARKER,
          "multichoice_dashboard.html: fix leftover manual-Monday message")

    patch("templates/base.html", SIDEBAR_OLD, SIDEBAR_NEW, SIDEBAR_MARKER,
          "base.html: remove Record Balance link, repoint Weekly Report link")

    write("templates/my_commissions.html", MY_COMMISSIONS_TEMPLATE)
    print("OK    templates/my_commissions.html: rewritten")

    patch("templates/commission_tracking.html", CT_ALLCOMM_OLD, CT_ALLCOMM_NEW, CT_ALLCOMM_MARKER,
          "commission_tracking.html: All Commissions tab MultiChoice rows")
    patch("templates/commission_tracking.html", CT_MCTAB_OLD, CT_MCTAB_NEW, CT_MCTAB_MARKER,
          "commission_tracking.html: MultiChoice tab rebuilt + void oversight table")

    wf1 = os.path.join(BASE_DIR, ".github", "workflows", "mc_weekly_close.yml")
    if os.path.exists(wf1):
        print("SKIP  mc_weekly_close.yml: already exists, skipping.")
    else:
        os.makedirs(os.path.dirname(wf1), exist_ok=True)
        write(".github/workflows/mc_weekly_close.yml", MC_WEEKLY_CLOSE_YML)
        print("OK    Created .github/workflows/mc_weekly_close.yml")

    wf2 = os.path.join(BASE_DIR, ".github", "workflows", "mc_ensure_open_week.yml")
    if os.path.exists(wf2):
        print("SKIP  mc_ensure_open_week.yml: already exists, skipping.")
    else:
        write(".github/workflows/mc_ensure_open_week.yml", MC_ENSURE_OPEN_YML)
        print("OK    Created .github/workflows/mc_ensure_open_week.yml")

    print("\n-- Done --")
    print("Next steps:")
    print("  python manage.py makemigrations --check")
    print("  python manage.py migrate")
    print("  python manage.py check")
    print("  python manage.py ensure_multichoice_open_week")
    print("  git add . && git commit -m 'MultiChoice: fraud-resistant commission redesign' && git push")


if __name__ == "__main__":
    main()

