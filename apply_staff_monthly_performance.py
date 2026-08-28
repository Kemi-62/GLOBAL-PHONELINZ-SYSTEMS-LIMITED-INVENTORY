"""
apply_staff_monthly_performance.py
=====================================
Per-staff version of the Monthly Performance Archive: each staff member
gets their own permanent monthly history, an emailed report at month-end,
and a "My Monthly History" tab on their own dashboard with a month-vs-
month comparison.

WHAT THIS SCRIPT DOES
1. core/models.py -> StaffMonthlyPerformanceArchive model (one row per
   staff member per month, permanent record)
2. core/migrations/0042_staff_monthly_performance.py -> new migration
3. core/management/commands/archive_staff_monthly_performance.py ->
   computes and saves each staff member's month, and emails them a report
4. core/views.py -> cron endpoint to trigger this automatically
5. core/urls.py -> the cron route
6. core/templatetags/monthly_history_tags.py -> NEW: a template tag that
   fetches a staff member's own archive + comparison, so no dashboard
   view function needs to be touched or risk an anchor mismatch
7. templates/partials/staff_monthly_history.html -> NEW: the shared tab
   content (their history + a "compare two months" tool)
8. templates/retail_dashboard.html, staff_dashboard.html (Telecom),
   multichoice_dashboard.html, manager_dashboard.html -> each gets a new
   "My Monthly History" tab using the template tag above

WHY A TEMPLATE TAG INSTEAD OF EDITING EACH VIEW
The 4 dashboard views have already been patched several times this
project by earlier scripts, so their exact context dict contents differ
in ways that are fragile to string-match against. A template tag queries
its own data independently of the view -- zero risk of anchor mismatch,
and it's reusable across all 4 dashboards from one place.

EMAIL BEHAVIOR
- The automated month-end run (via cron) archives + emails every active
  staff member their own report for the month that just ended.
- Manual/backfill runs do NOT send email by default (so backfilling your
  history doesn't spam everyone) -- pass --send-email explicitly if you
  want a specific manual run to email too.

HOW TO RUN (Replit Shell)
    python apply_staff_monthly_performance.py

Then:
    python manage.py makemigrations --check
    python manage.py migrate
    python manage.py check

BACKFILL PAST MONTHS (no emails sent for these):
    python manage.py archive_staff_monthly_performance --backfill-months=3

Then push:
    git add . && git commit -m "Add per-staff monthly performance archive + emailed reports" && git push

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


# ---------------------------------------------------------------
# 1. core/models.py
# ---------------------------------------------------------------

MODELS_MARKER = "class StaffMonthlyPerformanceArchive"

MODELS_OLD = "class DeviceTagCommission(models.Model):"

MODELS_NEW = '''class StaffMonthlyPerformanceArchive(models.Model):
    """A permanently-stored snapshot of one staff member's performance for
    one month -- their historical record, independent of the raw sales
    tables, and the source for their monthly emailed report."""
    staff = models.ForeignKey(
        'User', on_delete=models.CASCADE, related_name='monthly_archives'
    )
    month = models.DateField(help_text="Always the 1st of the archived month")
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True)

    retail_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    retail_quantity = models.IntegerField(default=0)
    multichoice_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    multichoice_quantity = models.IntegerField(default=0)
    hardware_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    hardware_quantity = models.IntegerField(default=0)
    online_sales_count = models.IntegerField(default=0)
    online_sales_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    telecom_activity_count = models.IntegerField(default=0)

    days_present = models.IntegerField(default=0)
    days_late = models.IntegerField(default=0)
    days_absent = models.IntegerField(default=0)

    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('staff', 'month')
        ordering = ['-month']

    @property
    def total_revenue(self):
        return (self.retail_revenue or 0) + (self.multichoice_revenue or 0) + \\
               (self.hardware_revenue or 0) + (self.online_sales_revenue or 0)

    def __str__(self):
        return f"{self.staff.username} - {self.month.strftime('%B %Y')}"


class DeviceTagCommission(models.Model):'''


# ---------------------------------------------------------------
# 2. migration
# ---------------------------------------------------------------

MIGRATION_CONTENT = '''# Generated manually to match Django 5.0.2 migration style
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0041_monthly_performance_archive'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='StaffMonthlyPerformanceArchive',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('month', models.DateField(help_text='Always the 1st of the archived month')),
                ('retail_revenue', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('retail_quantity', models.IntegerField(default=0)),
                ('multichoice_revenue', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('multichoice_quantity', models.IntegerField(default=0)),
                ('hardware_revenue', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('hardware_quantity', models.IntegerField(default=0)),
                ('online_sales_count', models.IntegerField(default=0)),
                ('online_sales_revenue', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('telecom_activity_count', models.IntegerField(default=0)),
                ('days_present', models.IntegerField(default=0)),
                ('days_late', models.IntegerField(default=0)),
                ('days_absent', models.IntegerField(default=0)),
                ('email_sent', models.BooleanField(default=False)),
                ('email_sent_at', models.DateTimeField(blank=True, null=True)),
                ('generated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.branch')),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='monthly_archives', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-month'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='staffmonthlyperformancearchive',
            unique_together={('staff', 'month')},
        ),
    ]
'''


# ---------------------------------------------------------------
# 3. management command
# ---------------------------------------------------------------

COMMAND_CONTENT = '''"""Management command: archive + email each staff member's monthly
performance report.

Usage:
    python manage.py archive_staff_monthly_performance
        -> archives the PREVIOUS month for every active staff member,
           no emails sent (safe default for manual runs)

    python manage.py archive_staff_monthly_performance --send-email
        -> same, but also emails each staff member their report
           (this is what the automated month-end cron uses)

    python manage.py archive_staff_monthly_performance --backfill-months=3
        -> archives the last 3 months for every staff member, no emails
"""
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.conf import settings
from django.db.models import Sum, Q, F
from django.utils import timezone

from core.models import (
    User, RetailSale, MultiChoiceSale, Attendance,
    StaffMonthlyPerformanceArchive,
)


def _build_email_html(staff, archive, previous_archive):
    def _fmt(n):
        return "\\u20a6{:,.0f}".format(float(n or 0))

    change_line = ""
    if previous_archive and previous_archive.total_revenue:
        diff = float(archive.total_revenue) - float(previous_archive.total_revenue)
        pct = round((diff / float(previous_archive.total_revenue)) * 100, 1)
        arrow = "\\u2191" if pct >= 0 else "\\u2193"
        color = "#065f46" if pct >= 0 else "#991b1b"
        change_line = (
            f'<p style="font-size:13px;color:{color};margin:4px 0 0;">'
            f'{arrow} {abs(pct)}% vs {previous_archive.month.strftime("%B")}</p>'
        )

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;background:#f3f4f6;padding:20px;">
        <div style="background:#004F9F;color:#FFCB05;padding:20px;border-radius:10px 10px 0 0;text-align:center;">
            <h1 style="margin:0;font-size:19px;">Your Monthly Performance</h1>
            <p style="margin:4px 0 0;font-size:13px;color:#fff;">{archive.month.strftime('%B %Y')}</p>
        </div>
        <div style="background:#fff;padding:20px;border-radius:0 0 10px 10px;">
            <p style="font-size:14px;color:#374151;">Hi {staff.username},</p>
            <p style="font-size:13px;color:#6b7280;">Here's how {archive.month.strftime('%B %Y')} went for you:</p>

            <div style="background:#f0fdf4;border-radius:8px;padding:14px;margin:14px 0;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#065f46;">{_fmt(archive.total_revenue)}</div>
                <div style="font-size:12px;color:#6b7280;">Total Sales Revenue</div>
                {change_line}
            </div>

            <table style="width:100%;border-collapse:collapse;font-size:13px;">
                <tr><td style="padding:6px 0;color:#6b7280;">Retail Sales</td><td style="text-align:right;">{_fmt(archive.retail_revenue)} ({archive.retail_quantity} items)</td></tr>
                <tr><td style="padding:6px 0;color:#6b7280;">MultiChoice Subscriptions</td><td style="text-align:right;">{_fmt(archive.multichoice_revenue)} ({archive.multichoice_quantity})</td></tr>
                <tr><td style="padding:6px 0;color:#6b7280;">Hardware Sales</td><td style="text-align:right;">{_fmt(archive.hardware_revenue)} ({archive.hardware_quantity})</td></tr>
                <tr><td style="padding:6px 0;color:#6b7280;">Online Sales</td><td style="text-align:right;">{_fmt(archive.online_sales_revenue)} ({archive.online_sales_count})</td></tr>
                <tr><td style="padding:6px 0;color:#6b7280;">Telecom Activities</td><td style="text-align:right;">{archive.telecom_activity_count}</td></tr>
            </table>

            <p style="font-size:13px;font-weight:600;color:#374151;margin:16px 0 6px;">Attendance</p>
            <p style="font-size:13px;color:#374151;margin:0;">
                {archive.days_present} days present \\u00b7 {archive.days_late} late \\u00b7 {archive.days_absent} absent
            </p>

            <p style="font-size:11px;color:#9ca3af;text-align:center;margin-top:20px;border-top:1px solid #e5e7eb;padding-top:12px;">
                Automated monthly report from GPSL ERP.
            </p>
        </div>
    </div>
    """


def _archive_one_staff_month(staff, month_start, send_email):
    month_end = month_start + relativedelta(months=1)

    retail_qs = RetailSale.objects.filter(
        staff=staff, date__gte=month_start, date__lt=month_end, is_voided=False
    )
    retail_revenue = retail_qs.aggregate(t=Sum(F("quantity") * F("selling_price")))["t"] or 0
    retail_quantity = retail_qs.aggregate(t=Sum("quantity"))["t"] or 0

    mc_qs = MultiChoiceSale.objects.filter(staff=staff, date__gte=month_start, date__lt=month_end)
    mc_revenue = mc_qs.aggregate(t=Sum("amount"))["t"] or 0
    mc_quantity = mc_qs.count()

    hardware_revenue = 0
    hardware_quantity = 0
    try:
        from core.models import MultiChoiceHardwareSale
        hw_qs = MultiChoiceHardwareSale.objects.filter(
            staff=staff, date__gte=month_start, date__lt=month_end
        )
        hardware_revenue = hw_qs.aggregate(t=Sum("amount"))["t"] or 0
        hardware_quantity = hw_qs.aggregate(t=Sum("quantity"))["t"] or 0
    except Exception:
        pass

    online_revenue = 0
    online_count = 0
    try:
        from core.models import OnlineSaleLog
        ol_qs = OnlineSaleLog.objects.filter(
            staff=staff, sale_date__gte=month_start, sale_date__lt=month_end
        )
        online_revenue = ol_qs.aggregate(t=Sum("amount"))["t"] or 0
        online_count = ol_qs.count()
    except Exception:
        pass

    telecom_count = 0
    try:
        from core.models import ServiceActivity
        telecom_count = ServiceActivity.objects.filter(
            staff=staff, date__gte=month_start, date__lt=month_end
        ).count()
    except Exception:
        pass

    att_qs = Attendance.objects.filter(user=staff, date__gte=month_start, date__lt=month_end)
    days_present = att_qs.count()
    days_late = att_qs.filter(is_late=True).count()
    days_absent = att_qs.filter(is_absent=True).count()

    archive, _ = StaffMonthlyPerformanceArchive.objects.update_or_create(
        staff=staff, month=month_start,
        defaults={
            "branch": staff.branch,
            "retail_revenue": retail_revenue,
            "retail_quantity": retail_quantity,
            "multichoice_revenue": mc_revenue,
            "multichoice_quantity": mc_quantity,
            "hardware_revenue": hardware_revenue,
            "hardware_quantity": hardware_quantity,
            "online_sales_count": online_count,
            "online_sales_revenue": online_revenue,
            "telecom_activity_count": telecom_count,
            "days_present": days_present,
            "days_late": days_late,
            "days_absent": days_absent,
        },
    )

    if send_email and staff.email:
        previous_month = month_start - relativedelta(months=1)
        previous_archive = StaffMonthlyPerformanceArchive.objects.filter(
            staff=staff, month=previous_month
        ).first()
        try:
            html = _build_email_html(staff, archive, previous_archive)
            msg = EmailMessage(
                subject=f"Your {month_start.strftime('%B %Y')} Performance Report - GPSL",
                body=html,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[staff.email],
            )
            msg.content_subtype = "html"
            msg.send()
            archive.email_sent = True
            archive.email_sent_at = timezone.now()
            archive.save()
        except Exception:
            pass

    return archive


class Command(BaseCommand):
    help = "Archive each staff member's monthly performance, optionally emailing their report."

    def add_arguments(self, parser):
        parser.add_argument("--month", default="", help="Specific month, e.g. 2026-07-01")
        parser.add_argument("--backfill-months", type=int, default=0, help="Archive the last N months (no email)")
        parser.add_argument("--send-email", action="store_true", help="Email each staff member their report")

    def handle(self, *args, **options):
        month_str = options["month"]
        backfill = options["backfill_months"]
        send_email = options["send_email"]

        staff_members = User.objects.filter(
            role__in=["RETAIL", "TELECOM", "MULTICHOICE", "MANAGER"]
        )

        if backfill:
            today_first = date.today().replace(day=1)
            for i in range(1, backfill + 1):
                target = today_first - relativedelta(months=i)
                for staff in staff_members:
                    _archive_one_staff_month(staff, target, send_email=False)
                self.stdout.write(f"Archived {target.strftime('%B %Y')} for {staff_members.count()} staff.")
            self.stdout.write(self.style.SUCCESS(f"Backfilled {backfill} month(s) for all staff."))
            return

        if month_str:
            target = date.fromisoformat(month_str).replace(day=1)
        else:
            target = (date.today().replace(day=1)) - relativedelta(months=1)

        count = 0
        for staff in staff_members:
            _archive_one_staff_month(staff, target, send_email=send_email)
            count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Archived {target.strftime('%B %Y')} for {count} staff member(s)."
            + (" Emails sent." if send_email else " No emails sent (use --send-email to send).")
        ))
'''


# ---------------------------------------------------------------
# 4. core/views.py -- cron endpoint only
# ---------------------------------------------------------------

VIEWS_MARKER = "def cron_archive_staff_monthly_performance(request):"

VIEWS_OLD_ANCHOR = "# DIRECTOR \u2014 ALL BRANCH STOCK VIEW"

VIEWS_NEW_BLOCK = '''def cron_archive_staff_monthly_performance(request):
    if not _check_cron_secret(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    try:
        from django.core.management import call_command
        call_command('archive_staff_monthly_performance', send_email=True)
        return JsonResponse({'ok': True, 'message': 'Previous month archived and emailed for all staff'})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


# DIRECTOR \u2014 ALL BRANCH STOCK VIEW'''


# ---------------------------------------------------------------
# 5. core/urls.py
# ---------------------------------------------------------------

URLS_MARKER = "cron_archive_staff_monthly_performance"

URLS_OLD_ANCHOR = "    path('cron/archive-monthly-performance/', views.cron_archive_monthly_performance, name='cron_archive_monthly_performance'),\n]"

URLS_NEW_BLOCK = '''    path('cron/archive-monthly-performance/', views.cron_archive_monthly_performance, name='cron_archive_monthly_performance'),
    path('cron/archive-staff-monthly-performance/', views.cron_archive_staff_monthly_performance, name='cron_archive_staff_monthly_performance'),
]'''


# ---------------------------------------------------------------
# 6. template tag
# ---------------------------------------------------------------

TAGS_INIT = ""

TAGS_CONTENT = '''from django import template
from datetime import date as _date

register = template.Library()


@register.inclusion_tag('partials/staff_monthly_history.html', takes_context=True)
def staff_monthly_history(context):
    request = context['request']
    user = request.user
    from core.models import StaffMonthlyPerformanceArchive

    all_months = list(
        StaffMonthlyPerformanceArchive.objects.filter(staff=user)
        .order_by("-month").values_list("month", flat=True)
    )

    compare_a_str = request.GET.get("my_month_a", "")
    compare_b_str = request.GET.get("my_month_b", "")

    def _row(month_val):
        if not month_val:
            return None
        try:
            m = _date.fromisoformat(month_val)
        except ValueError:
            return None
        return StaffMonthlyPerformanceArchive.objects.filter(staff=user, month=m).first()

    if not compare_a_str and len(all_months) >= 1:
        compare_a_str = all_months[0].isoformat()
    if not compare_b_str and len(all_months) >= 2:
        compare_b_str = all_months[1].isoformat()

    row_a = _row(compare_a_str)
    row_b = _row(compare_b_str)

    def _pct(new_val, old_val):
        if not old_val:
            return None
        return round(((float(new_val) - float(old_val)) / float(old_val)) * 100, 1)

    comparison = None
    if row_a and row_b:
        comparison = {
            "a": row_a, "b": row_b,
            "revenue_change": _pct(row_a.total_revenue, row_b.total_revenue),
        }

    history = list(
        StaffMonthlyPerformanceArchive.objects.filter(staff=user).order_by("-month")[:12]
    )

    return {
        "my_history": history,
        "my_all_months": all_months,
        "my_compare_a": compare_a_str,
        "my_compare_b": compare_b_str,
        "my_comparison": comparison,
        "has_my_history": len(all_months) > 0,
    }
'''


# ---------------------------------------------------------------
# 7. shared partial
# ---------------------------------------------------------------

PARTIAL_CONTENT = '''<div class="card">
  <p class="card-title">\U0001F4C8 My Monthly History</p>

  {% if not has_my_history %}
  <p style="font-size:.83rem;color:#9ca3af;">No monthly history yet \u2014 this builds up automatically as each month closes.</p>
  {% else %}
  <div style="overflow-x:auto;">
    <table class="data-table">
      <thead><tr><th>Month</th><th style="text-align:right;">Total Revenue</th><th style="text-align:center;">Present</th><th style="text-align:center;">Late</th><th style="text-align:center;">Absent</th></tr></thead>
      <tbody>
        {% for row in my_history %}
        <tr>
          <td><strong>{{ row.month|date:"F Y" }}</strong></td>
          <td style="text-align:right;">\u20a6{{ row.total_revenue|floatformat:0 }}</td>
          <td style="text-align:center;">{{ row.days_present }}</td>
          <td style="text-align:center;">{{ row.days_late }}</td>
          <td style="text-align:center;">{{ row.days_absent }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
</div>

{% if my_all_months|length > 1 %}
<div class="card">
  <p class="card-title">\U0001F500 Compare Two Months</p>
  <form method="GET" style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;margin-bottom:1rem;">
    <select name="my_month_a" style="padding:.45rem .7rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem;">
      {% for m in my_all_months %}<option value="{{ m|date:'Y-m-d' }}" {% if my_compare_a == m|date:'Y-m-d' %}selected{% endif %}>{{ m|date:"F Y" }}</option>{% endfor %}
    </select>
    <span style="font-size:.8rem;color:#6b7280;">vs</span>
    <select name="my_month_b" style="padding:.45rem .7rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem;">
      {% for m in my_all_months %}<option value="{{ m|date:'Y-m-d' }}" {% if my_compare_b == m|date:'Y-m-d' %}selected{% endif %}>{{ m|date:"F Y" }}</option>{% endfor %}
    </select>
    <button type="submit" class="btn-sm btn-primary">Compare</button>
  </form>

  {% if my_comparison %}
  <table class="data-table">
    <thead><tr><th></th><th>{{ my_comparison.a.month|date:"F Y" }}</th><th>{{ my_comparison.b.month|date:"F Y" }}</th><th>Change</th></tr></thead>
    <tbody>
      <tr>
        <td>Total Revenue</td>
        <td>\u20a6{{ my_comparison.a.total_revenue|floatformat:0 }}</td>
        <td>\u20a6{{ my_comparison.b.total_revenue|floatformat:0 }}</td>
        <td>
          {% if my_comparison.revenue_change > 0 %}<span class="badge" style="background:#dcfce7;color:#065f46;">\u2191 {{ my_comparison.revenue_change }}%</span>
          {% elif my_comparison.revenue_change < 0 %}<span class="badge" style="background:#fee2e2;color:#991b1b;">\u2193 {{ my_comparison.revenue_change }}%</span>
          {% else %}<span class="badge" style="background:#f1f5f9;color:#475569;">\u2014</span>{% endif %}
        </td>
      </tr>
    </tbody>
  </table>
  {% endif %}
</div>
{% endif %}
'''


# ---------------------------------------------------------------
# 8. Dashboard tabs -- all 4
# ---------------------------------------------------------------

DASHBOARDS = [
    ("templates/retail_dashboard.html", "retail_dashboard.html"),
    ("templates/staff_dashboard.html", "staff_dashboard.html (Telecom)"),
    ("templates/multichoice_dashboard.html", "multichoice_dashboard.html"),
    ("templates/manager_dashboard.html", "manager_dashboard.html"),
]

TABBAR_OLD = '''  <button class="tab-btn" onclick="switchTab('onlinesales',this)">\U0001F4F1 Online Sales</button>
</div>'''

TABBAR_NEW = '''  <button class="tab-btn" onclick="switchTab('onlinesales',this)">\U0001F4F1 Online Sales</button>
  <button class="tab-btn" onclick="switchTab('myhistory',this)">\U0001F4C8 My Monthly History</button>
</div>'''

PANEL_OLD = '''<script>
function switchTab(name, btn) {'''

PANEL_NEW = '''<div id="tab-myhistory" class="tab-panel">
  {% load monthly_history_tags %}
  {% staff_monthly_history %}
</div>

<script>
function switchTab(name, btn) {'''

MARKER = 'tab-myhistory" class="tab-panel'


def main():
    print("-- Applying Per-Staff Monthly Performance --\n")

    patch("core/models.py", MODELS_OLD, MODELS_NEW, MODELS_MARKER,
          "models.py: StaffMonthlyPerformanceArchive model")

    migration_path = os.path.join(BASE_DIR, "core", "migrations", "0042_staff_monthly_performance.py")
    if os.path.exists(migration_path):
        print("SKIP  migration 0042: already exists, skipping.")
    else:
        write("core/migrations/0042_staff_monthly_performance.py", MIGRATION_CONTENT)
        print("OK    Created core/migrations/0042_staff_monthly_performance.py")

    command_path = os.path.join(BASE_DIR, "core", "management", "commands", "archive_staff_monthly_performance.py")
    if os.path.exists(command_path):
        print("SKIP  management command: already exists, skipping.")
    else:
        write("core/management/commands/archive_staff_monthly_performance.py", COMMAND_CONTENT)
        print("OK    Created core/management/commands/archive_staff_monthly_performance.py")

    patch("core/views.py", VIEWS_OLD_ANCHOR, VIEWS_NEW_BLOCK, VIEWS_MARKER,
          "views.py: cron_archive_staff_monthly_performance endpoint")
    patch("core/urls.py", URLS_OLD_ANCHOR, URLS_NEW_BLOCK, URLS_MARKER,
          "urls.py: new route")

    templatetags_dir = os.path.join(BASE_DIR, "core", "templatetags")
    os.makedirs(templatetags_dir, exist_ok=True)
    init_path = os.path.join(templatetags_dir, "__init__.py")
    if not os.path.exists(init_path):
        write("core/templatetags/__init__.py", TAGS_INIT)
        print("OK    Created core/templatetags/__init__.py")
    else:
        print("SKIP  core/templatetags/__init__.py: already exists, skipping.")

    tags_path = os.path.join(templatetags_dir, "monthly_history_tags.py")
    if os.path.exists(tags_path):
        print("SKIP  core/templatetags/monthly_history_tags.py: already exists, skipping.")
    else:
        write("core/templatetags/monthly_history_tags.py", TAGS_CONTENT)
        print("OK    Created core/templatetags/monthly_history_tags.py")

    partial_path = os.path.join(BASE_DIR, "templates", "partials", "staff_monthly_history.html")
    if os.path.exists(partial_path):
        print("SKIP  templates/partials/staff_monthly_history.html: already exists, skipping.")
    else:
        os.makedirs(os.path.dirname(partial_path), exist_ok=True)
        write("templates/partials/staff_monthly_history.html", PARTIAL_CONTENT)
        print("OK    Created templates/partials/staff_monthly_history.html")

    for path, label in DASHBOARDS:
        content = read(path)
        if MARKER in content:
            print("SKIP  " + label + ": already has My Monthly History tab, skipping.")
            continue
        if TABBAR_OLD not in content:
            print("FAIL  " + label + ": tab bar anchor not found.")
            sys.exit(1)
        content = content.replace(TABBAR_OLD, TABBAR_NEW, 1)
        if PANEL_OLD not in content:
            print("FAIL  " + label + ": panel anchor not found.")
            sys.exit(1)
        content = content.replace(PANEL_OLD, PANEL_NEW, 1)
        write(path, content)
        print("OK    " + label + ": added My Monthly History tab")

    workflow_path = os.path.join(BASE_DIR, ".github", "workflows", "monthly_archive.yml")
    if os.path.exists(workflow_path):
        wf_content = read(".github/workflows/monthly_archive.yml")
        if "archive-staff-monthly-performance" not in wf_content:
            wf_content = wf_content.rstrip() + '''
      - name: Archive + email staff performance
        run: |
          curl -s --max-time 120 \\
            "https://app.globalphonelinz.com/cron/archive-staff-monthly-performance/?key=gpsl2026backup"
'''
            write(".github/workflows/monthly_archive.yml", wf_content)
            print("OK    .github/workflows/monthly_archive.yml: extended with staff archive step")
        else:
            print("SKIP  .github/workflows/monthly_archive.yml: already extended, skipping.")
    else:
        print("!!    .github/workflows/monthly_archive.yml not found -- run apply_monthly_performance_archive.py first")
        print("      (or create this workflow manually to trigger staff archiving monthly)")

    print("\n-- Done --")
    print("Next steps:")
    print("  python manage.py makemigrations --check")
    print("  python manage.py migrate")
    print("  python manage.py check")
    print("  python manage.py archive_staff_monthly_performance --backfill-months=3")
    print("  git add . && git commit -m 'Add per-staff monthly performance archive + emailed reports' && git push")


if __name__ == "__main__":
    main()
