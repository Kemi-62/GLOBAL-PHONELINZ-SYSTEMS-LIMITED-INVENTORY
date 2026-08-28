"""
apply_monthly_performance_archive.py
=======================================
Builds the missing pieces for month-to-month / historical performance
review:

1. A permanent HISTORICAL ARCHIVE (MonthlyPerformanceArchive model) --
   once a month closes, its final numbers are locked in and stored
   forever, per branch AND company-wide.
2. A management command (archive_monthly_performance) that computes and
   saves a given month's figures -- supports backfilling past months too.
3. A cron endpoint so this runs automatically on the 1st of every month,
   archiving the month that just ended.
4. A new Director-only page, "Monthly Performance", with:
   - A 12-month trend chart (revenue / expenses / net profit)
   - A month-vs-month comparison table (pick any two months)
   - A branch-by-branch breakdown for the latest archived month
   - The current (still in-progress) month shown live, clearly marked
5. A sidebar link for the Director.

HOW TO RUN (Replit Shell)
    python apply_monthly_performance_archive.py

Then:
    pip install python-dateutil   # if not already installed
    python manage.py makemigrations --check
    python manage.py migrate
    python manage.py check

BACKFILL YOUR PAST MONTHS (do this once):
    python manage.py archive_monthly_performance --backfill-months=6

Then push:
    git add . && git commit -m "Add monthly performance archive, trends, and comparison" && git push

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


MODELS_MARKER = "class MonthlyPerformanceArchive"

MODELS_OLD = "class DeviceTagCommission(models.Model):"

MODELS_NEW = '''class MonthlyPerformanceArchive(models.Model):
    """A permanently-stored snapshot of one month's performance, per branch
    and company-wide (branch=NULL). Once a month is archived here, its
    numbers don't change -- this is the historical record for
    month-to-month comparison."""
    month = models.DateField(help_text="Always the 1st of the archived month")
    branch = models.ForeignKey(
        'Branch', on_delete=models.CASCADE, null=True, blank=True,
        related_name='monthly_archives',
        help_text="Null = company-wide total row for this month"
    )
    retail_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    retail_quantity = models.IntegerField(default=0)
    retail_gross_profit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    multichoice_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    multichoice_quantity = models.IntegerField(default=0)
    total_expenses = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_profit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    new_customers = models.IntegerField(default=0)
    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('month', 'branch')
        ordering = ['-month']

    def __str__(self):
        scope = self.branch.name if self.branch else "Company-wide"
        return f"{scope} - {self.month.strftime('%B %Y')}"


class DeviceTagCommission(models.Model):'''


MIGRATION_CONTENT = '''# Generated manually to match Django 5.0.2 migration style
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0040_add_time_to_activity_expense'),
    ]

    operations = [
        migrations.CreateModel(
            name='MonthlyPerformanceArchive',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('month', models.DateField(help_text='Always the 1st of the archived month')),
                ('retail_revenue', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('retail_quantity', models.IntegerField(default=0)),
                ('retail_gross_profit', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('multichoice_revenue', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('multichoice_quantity', models.IntegerField(default=0)),
                ('total_expenses', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('net_profit', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('new_customers', models.IntegerField(default=0)),
                ('generated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(blank=True, help_text='Null = company-wide total row for this month', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='monthly_archives', to='core.branch')),
            ],
            options={
                'ordering': ['-month'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='monthlyperformancearchive',
            unique_together={('month', 'branch')},
        ),
    ]
'''


COMMAND_CONTENT = '''"""Management command: archive a month's finalized performance figures.

Usage:
    python manage.py archive_monthly_performance
        -> archives the PREVIOUS calendar month (the one that just ended)

    python manage.py archive_monthly_performance --month=2026-07-01
        -> archives a specific month

    python manage.py archive_monthly_performance --backfill-months=6
        -> archives the last 6 calendar months (run once to seed history)
"""
from datetime import date
from dateutil.relativedelta import relativedelta

from django.core.management.base import BaseCommand
from django.db.models import Sum, F, ExpressionWrapper, DecimalField

from core.models import (
    Branch, RetailSale, MultiChoiceSale, Expense, Customer,
    MonthlyPerformanceArchive,
)


def _archive_one_month(stdout, month_start):
    from django.utils import timezone as _tz
    from datetime import datetime as _dt

    month_end = month_start + relativedelta(months=1)
    month_start_aware = _tz.make_aware(_dt.combine(month_start, _dt.min.time()))
    month_end_aware = _tz.make_aware(_dt.combine(month_end, _dt.min.time()))
    profit_expr = ExpressionWrapper(
        (F("selling_price") - F("product__cost_price")) * F("quantity"),
        output_field=DecimalField(),
    )

    branches = list(Branch.objects.all())
    scopes = branches + [None]

    for branch in scopes:
        retail_qs = RetailSale.objects.filter(
            date__gte=month_start, date__lt=month_end, is_voided=False
        )
        mc_qs = MultiChoiceSale.objects.filter(date__gte=month_start, date__lt=month_end)
        exp_qs = Expense.objects.filter(date__gte=month_start, date__lt=month_end)
        cust_qs = Customer.objects.filter(
            last_purchase__gte=month_start_aware, last_purchase__lt=month_end_aware
        )

        if branch is not None:
            retail_qs = retail_qs.filter(branch=branch)
            mc_qs = mc_qs.filter(branch=branch)
            exp_qs = exp_qs.filter(branch=branch)
            cust_qs = cust_qs.filter(branch=branch)

        retail_revenue = retail_qs.aggregate(t=Sum(F("quantity") * F("selling_price")))["t"] or 0
        retail_quantity = retail_qs.aggregate(t=Sum("quantity"))["t"] or 0
        retail_gross = retail_qs.aggregate(t=Sum(profit_expr))["t"] or 0
        mc_revenue = mc_qs.aggregate(t=Sum("amount"))["t"] or 0
        mc_quantity = mc_qs.count()
        total_expenses = exp_qs.aggregate(t=Sum("amount"))["t"] or 0
        new_customers = cust_qs.count()
        net_profit = (retail_gross or 0) + (mc_revenue or 0) - (total_expenses or 0)

        MonthlyPerformanceArchive.objects.update_or_create(
            month=month_start, branch=branch,
            defaults={
                "retail_revenue": retail_revenue,
                "retail_quantity": retail_quantity,
                "retail_gross_profit": retail_gross,
                "multichoice_revenue": mc_revenue,
                "multichoice_quantity": mc_quantity,
                "total_expenses": total_expenses,
                "net_profit": net_profit,
                "new_customers": new_customers,
            },
        )

    scope_label = "company-wide + " + str(len(branches)) + " branch(es)"
    stdout.write("Archived " + month_start.strftime("%B %Y") + " (" + scope_label + ")")


class Command(BaseCommand):
    help = "Archive a month's finalized performance figures for month-to-month comparison."

    def add_arguments(self, parser):
        parser.add_argument("--month", default="", help="Specific month to archive, e.g. 2026-07-01")
        parser.add_argument("--backfill-months", type=int, default=0, help="Archive the last N calendar months")

    def handle(self, *args, **options):
        month_str = options["month"]
        backfill = options["backfill_months"]

        if backfill:
            today_first = date.today().replace(day=1)
            for i in range(1, backfill + 1):
                target = today_first - relativedelta(months=i)
                _archive_one_month(self.stdout, target)
            self.stdout.write(self.style.SUCCESS(f"Backfilled {backfill} month(s)."))
            return

        if month_str:
            target = date.fromisoformat(month_str).replace(day=1)
        else:
            target = (date.today().replace(day=1)) - relativedelta(months=1)

        _archive_one_month(self.stdout, target)
        self.stdout.write(self.style.SUCCESS("Done."))
'''


VIEWS_MARKER = "def monthly_performance(request):"

VIEWS_OLD_ANCHOR = "# DIRECTOR \u2014 ALL BRANCH STOCK VIEW"

VIEWS_NEW_BLOCK = '''# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# MONTHLY PERFORMANCE ARCHIVE + TRENDS
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def cron_archive_monthly_performance(request):
    if not _check_cron_secret(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    try:
        from django.core.management import call_command
        call_command('archive_monthly_performance')
        return JsonResponse({'ok': True, 'message': 'Previous month archived'})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@role_required("DIRECTOR")
def monthly_performance(request):
    """Month-to-month comparison, 12-month trend, and branch breakdown,
    backed by the permanent MonthlyPerformanceArchive history."""
    from core.models import MonthlyPerformanceArchive
    from dateutil.relativedelta import relativedelta
    from django.db.models import Sum, F, ExpressionWrapper, DecimalField

    today_first = timezone.now().date().replace(day=1)

    company_rows = list(
        MonthlyPerformanceArchive.objects.filter(branch__isnull=True)
        .order_by("-month")[:12]
    )
    company_rows.reverse()
    trend_labels = [r.month.strftime("%b %Y") for r in company_rows]
    trend_revenue = [float(r.retail_revenue + r.multichoice_revenue) for r in company_rows]
    trend_expenses = [float(r.total_expenses) for r in company_rows]
    trend_net = [float(r.net_profit) for r in company_rows]

    profit_expr = ExpressionWrapper(
        (F("selling_price") - F("product__cost_price")) * F("quantity"), output_field=DecimalField()
    )
    live_retail = RetailSale.objects.filter(date__gte=today_first, is_voided=False)
    live_mc = MultiChoiceSale.objects.filter(date__gte=today_first)
    live_exp = Expense.objects.filter(date__gte=today_first)
    live_revenue = (live_retail.aggregate(t=Sum(F("quantity") * F("selling_price")))["t"] or 0) + \\
                   (live_mc.aggregate(t=Sum("amount"))["t"] or 0)
    live_expenses = live_exp.aggregate(t=Sum("amount"))["t"] or 0
    live_gross = live_retail.aggregate(t=Sum(profit_expr))["t"] or 0
    live_mc_rev = live_mc.aggregate(t=Sum("amount"))["t"] or 0
    live_net = (live_gross or 0) + (live_mc_rev or 0) - (live_expenses or 0)

    compare_a = request.GET.get("month_a", "")
    compare_b = request.GET.get("month_b", "")
    all_months = list(
        MonthlyPerformanceArchive.objects.filter(branch__isnull=True)
        .order_by("-month").values_list("month", flat=True)
    )

    def _get_month_row(month_val):
        if not month_val:
            return None
        try:
            from datetime import date as _date
            m = _date.fromisoformat(month_val)
        except ValueError:
            return None
        return MonthlyPerformanceArchive.objects.filter(branch__isnull=True, month=m).first()

    if not compare_a and len(all_months) >= 1:
        compare_a = all_months[0].isoformat()
    if not compare_b and len(all_months) >= 2:
        compare_b = all_months[1].isoformat()

    row_a = _get_month_row(compare_a)
    row_b = _get_month_row(compare_b)

    def _pct_change(new_val, old_val):
        if not old_val:
            return None
        return round(((float(new_val) - float(old_val)) / float(old_val)) * 100, 1)

    comparison = None
    if row_a and row_b:
        rev_a = float(row_a.retail_revenue + row_a.multichoice_revenue)
        rev_b = float(row_b.retail_revenue + row_b.multichoice_revenue)
        comparison = {
            "a": row_a, "b": row_b,
            "revenue_change": _pct_change(rev_a, rev_b),
            "expense_change": _pct_change(row_a.total_expenses, row_b.total_expenses),
            "net_change": _pct_change(row_a.net_profit, row_b.net_profit),
        }

    latest_month = all_months[0] if all_months else None
    branch_breakdown = []
    if latest_month:
        branch_breakdown = list(
            MonthlyPerformanceArchive.objects.filter(
                branch__isnull=False, month=latest_month
            ).select_related("branch").order_by("-net_profit")
        )

    return render(request, "monthly_performance.html", {
        "trend_labels": trend_labels,
        "trend_revenue": trend_revenue,
        "trend_expenses": trend_expenses,
        "trend_net": trend_net,
        "live_month_label": today_first.strftime("%B %Y"),
        "live_revenue": live_revenue,
        "live_expenses": live_expenses,
        "live_net": live_net,
        "all_months": all_months,
        "compare_a": compare_a,
        "compare_b": compare_b,
        "comparison": comparison,
        "latest_month": latest_month,
        "branch_breakdown": branch_breakdown,
        "has_history": len(all_months) > 0,
    })


# DIRECTOR \u2014 ALL BRANCH STOCK VIEW'''


URLS_MARKER = "monthly_performance"

URLS_OLD_ANCHOR = "    path('cron/whatsapp-report/', views.cron_whatsapp_report, name='cron_whatsapp_report'),\n]"

URLS_NEW_BLOCK = '''    path('cron/whatsapp-report/', views.cron_whatsapp_report, name='cron_whatsapp_report'),
    path('director/monthly-performance/', views.monthly_performance, name='monthly_performance'),
    path('cron/archive-monthly-performance/', views.cron_archive_monthly_performance, name='cron_archive_monthly_performance'),
]'''


SIDEBAR_MARKER = "monthly_performance"

SIDEBAR_OLD_ANCHOR = '''        <a href="{% url 'director_dashboard' %}" class="sidebar-link">
            <span class="icon">\U0001F4CA</span> Dashboard
        </a>
        <a href="{% url 'daily_sales_report' %}" class="sidebar-link">'''

SIDEBAR_NEW_BLOCK = '''        <a href="{% url 'director_dashboard' %}" class="sidebar-link">
            <span class="icon">\U0001F4CA</span> Dashboard
        </a>
        <a href="{% url 'monthly_performance' %}" class="sidebar-link">
            <span class="icon">\U0001F4C8</span> Monthly Performance
        </a>
        <a href="{% url 'daily_sales_report' %}" class="sidebar-link">'''


TEMPLATE_CONTENT = '''{% extends "base.html" %}
{% block content %}
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
.page-title{font-size:1.2rem;font-weight:700;color:#004F9F;margin:0}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1.1rem 1.3rem;margin-bottom:1rem}
.card-title{font-size:.92rem;font-weight:700;margin:0 0 .85rem}
.badge{display:inline-block;padding:.2rem .55rem;border-radius:999px;font-size:.72rem;font-weight:700}
.up{background:#dcfce7;color:#065f46}
.down{background:#fee2e2;color:#991b1b}
.flat{background:#f1f5f9;color:#475569}
table.data-table{width:100%;border-collapse:collapse;font-size:.85rem}
table.data-table th{text-align:left;padding:.5rem;background:#f9fafb;color:#374151;font-size:.78rem}
table.data-table td{padding:.5rem;border-bottom:1px solid #f3f4f6}
</style>

<div style="margin-bottom:1.25rem">
  <h1 class="page-title">\U0001F4C8 Monthly Performance</h1>
  <p style="font-size:.85rem;color:#6b7280;margin:.3rem 0 0;">Historical month-by-month archive, trends, and comparison.</p>
</div>

{% if not has_history %}
<div class="card" style="background:#fef3c7;border-color:#fde68a;">
  <p style="margin:0;font-size:.85rem;color:#92400e;">
    No archived months yet. Run <code>python manage.py archive_monthly_performance --backfill-months=6</code>
    in your Shell to build your history from existing records, then this page fills in automatically.
    From next month onward, archiving happens automatically on the 1st of every month.
  </p>
</div>
{% endif %}

<div class="card">
  <p class="card-title">\U0001F4C5 {{ live_month_label }} (In Progress \u2014 Not Yet Finalized)</p>
  <div style="display:flex;gap:1.5rem;flex-wrap:wrap;">
    <div><p style="font-size:.72rem;color:#9ca3af;margin:0 0 .2rem;">Revenue So Far</p><p style="font-size:1.15rem;font-weight:700;margin:0;">\u20a6{{ live_revenue|floatformat:0 }}</p></div>
    <div><p style="font-size:.72rem;color:#9ca3af;margin:0 0 .2rem;">Expenses So Far</p><p style="font-size:1.15rem;font-weight:700;margin:0;">\u20a6{{ live_expenses|floatformat:0 }}</p></div>
    <div><p style="font-size:.72rem;color:#9ca3af;margin:0 0 .2rem;">Net So Far</p><p style="font-size:1.15rem;font-weight:700;margin:0;color:#065f46;">\u20a6{{ live_net|floatformat:0 }}</p></div>
  </div>
  <p style="font-size:.75rem;color:#9ca3af;margin:.6rem 0 0;">This month finalizes and locks into the archive automatically on the 1st of next month.</p>
</div>

{% if trend_labels %}
<div class="card">
  <p class="card-title">12-Month Trend</p>
  <canvas id="trendChart" style="max-height:280px;"></canvas>
</div>
{% endif %}

{% if all_months|length > 1 %}
<div class="card">
  <p class="card-title">\U0001F500 Compare Two Months</p>
  <form method="GET" style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;margin-bottom:1rem;">
    <select name="month_a" style="padding:.45rem .7rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem;">
      {% for m in all_months %}<option value="{{ m|date:'Y-m-d' }}" {% if compare_a == m|date:'Y-m-d' %}selected{% endif %}>{{ m|date:"F Y" }}</option>{% endfor %}
    </select>
    <span style="font-size:.8rem;color:#6b7280;">vs</span>
    <select name="month_b" style="padding:.45rem .7rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem;">
      {% for m in all_months %}<option value="{{ m|date:'Y-m-d' }}" {% if compare_b == m|date:'Y-m-d' %}selected{% endif %}>{{ m|date:"F Y" }}</option>{% endfor %}
    </select>
    <button type="submit" class="badge flat" style="border:none;cursor:pointer;padding:.5rem .9rem;">Compare</button>
  </form>

  {% if comparison %}
  <table class="data-table">
    <thead><tr><th></th><th>{{ comparison.a.month|date:"F Y" }}</th><th>{{ comparison.b.month|date:"F Y" }}</th><th>Change</th></tr></thead>
    <tbody>
      <tr>
        <td>Revenue</td>
        <td>\u20a6{{ comparison.a.retail_revenue|add:comparison.a.multichoice_revenue|floatformat:0 }}</td>
        <td>\u20a6{{ comparison.b.retail_revenue|add:comparison.b.multichoice_revenue|floatformat:0 }}</td>
        <td>{% if comparison.revenue_change > 0 %}<span class="badge up">\u2191 {{ comparison.revenue_change }}%</span>{% elif comparison.revenue_change < 0 %}<span class="badge down">\u2193 {{ comparison.revenue_change }}%</span>{% else %}<span class="badge flat">\u2014</span>{% endif %}</td>
      </tr>
      <tr>
        <td>Expenses</td>
        <td>\u20a6{{ comparison.a.total_expenses|floatformat:0 }}</td>
        <td>\u20a6{{ comparison.b.total_expenses|floatformat:0 }}</td>
        <td>{% if comparison.expense_change > 0 %}<span class="badge down">\u2191 {{ comparison.expense_change }}%</span>{% elif comparison.expense_change < 0 %}<span class="badge up">\u2193 {{ comparison.expense_change }}%</span>{% else %}<span class="badge flat">\u2014</span>{% endif %}</td>
      </tr>
      <tr style="background:#f0fdf4;">
        <td><strong>Net Profit</strong></td>
        <td><strong>\u20a6{{ comparison.a.net_profit|floatformat:0 }}</strong></td>
        <td><strong>\u20a6{{ comparison.b.net_profit|floatformat:0 }}</strong></td>
        <td>{% if comparison.net_change > 0 %}<span class="badge up">\u2191 {{ comparison.net_change }}%</span>{% elif comparison.net_change < 0 %}<span class="badge down">\u2193 {{ comparison.net_change }}%</span>{% else %}<span class="badge flat">\u2014</span>{% endif %}</td>
      </tr>
      <tr><td>New Customers</td><td>{{ comparison.a.new_customers }}</td><td>{{ comparison.b.new_customers }}</td><td>\u2014</td></tr>
    </tbody>
  </table>
  {% endif %}
</div>
{% endif %}

{% if branch_breakdown %}
<div class="card">
  <p class="card-title">\U0001F3EA Branch Breakdown \u2014 {{ latest_month|date:"F Y" }}</p>
  <table class="data-table">
    <thead><tr><th>Branch</th><th style="text-align:right;">Revenue</th><th style="text-align:right;">Expenses</th><th style="text-align:right;">Net Profit</th></tr></thead>
    <tbody>
      {% for row in branch_breakdown %}
      <tr>
        <td><strong>{{ row.branch.name }}</strong></td>
        <td style="text-align:right;">\u20a6{{ row.retail_revenue|add:row.multichoice_revenue|floatformat:0 }}</td>
        <td style="text-align:right;">\u20a6{{ row.total_expenses|floatformat:0 }}</td>
        <td style="text-align:right;font-weight:700;color:{% if row.net_profit >= 0 %}#065f46{% else %}#991b1b{% endif %};">\u20a6{{ row.net_profit|floatformat:0 }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}

{% if trend_labels %}
<script>
new Chart(document.getElementById('trendChart'), {
  type: 'line',
  data: {
    labels: {{ trend_labels|safe }},
    datasets: [
      { label: 'Revenue', data: {{ trend_revenue|safe }}, borderColor: '#004F9F', backgroundColor: 'rgba(0,79,159,.08)', tension: .3, fill: true },
      { label: 'Expenses', data: {{ trend_expenses|safe }}, borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,.05)', tension: .3, fill: true },
      { label: 'Net Profit', data: {{ trend_net|safe }}, borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,.08)', tension: .3, fill: true },
    ]
  },
  options: { responsive: true, plugins: { legend: { position: 'bottom' } } }
});
</script>
{% endif %}
{% endblock %}
'''


WORKFLOW_YML = '''name: GPSL Monthly Performance Archive

on:
  schedule:
    - cron: '10 0 1 * *'
  workflow_dispatch:

jobs:
  archive-monthly:
    runs-on: ubuntu-latest
    steps:
      - name: Wake Render app
        run: |
          curl -s --max-time 60 "https://app.globalphonelinz.com/system/keepalive/" || true
          sleep 15
      - name: Archive previous month
        run: |
          curl -s --max-time 120 \\
            "https://app.globalphonelinz.com/cron/archive-monthly-performance/?key=gpsl2026backup"
'''


def main():
    print("-- Applying Monthly Performance Archive --\n")

    patch("core/models.py", MODELS_OLD, MODELS_NEW, MODELS_MARKER,
          "models.py: MonthlyPerformanceArchive model")

    migration_path = os.path.join(BASE_DIR, "core", "migrations", "0041_monthly_performance_archive.py")
    if os.path.exists(migration_path):
        print("SKIP  migration 0041: already exists, skipping.")
    else:
        write("core/migrations/0041_monthly_performance_archive.py", MIGRATION_CONTENT)
        print("OK    Created core/migrations/0041_monthly_performance_archive.py")

    command_path = os.path.join(BASE_DIR, "core", "management", "commands", "archive_monthly_performance.py")
    if os.path.exists(command_path):
        print("SKIP  management command: already exists, skipping.")
    else:
        write("core/management/commands/archive_monthly_performance.py", COMMAND_CONTENT)
        print("OK    Created core/management/commands/archive_monthly_performance.py")

    patch("core/views.py", VIEWS_OLD_ANCHOR, VIEWS_NEW_BLOCK, VIEWS_MARKER,
          "views.py: monthly_performance view + cron endpoint")
    patch("core/urls.py", URLS_OLD_ANCHOR, URLS_NEW_BLOCK, URLS_MARKER,
          "urls.py: 2 new routes")
    patch("templates/base.html", SIDEBAR_OLD_ANCHOR, SIDEBAR_NEW_BLOCK, SIDEBAR_MARKER,
          "base.html: sidebar link")

    template_path = os.path.join(BASE_DIR, "templates", "monthly_performance.html")
    if os.path.exists(template_path):
        print("SKIP  templates/monthly_performance.html: already exists, skipping.")
    else:
        write("templates/monthly_performance.html", TEMPLATE_CONTENT)
        print("OK    Created templates/monthly_performance.html")

    workflow_path = os.path.join(BASE_DIR, ".github", "workflows", "monthly_archive.yml")
    if os.path.exists(workflow_path):
        print("SKIP  .github/workflows/monthly_archive.yml: already exists, skipping.")
    else:
        os.makedirs(os.path.dirname(workflow_path), exist_ok=True)
        write(".github/workflows/monthly_archive.yml", WORKFLOW_YML)
        print("OK    Created .github/workflows/monthly_archive.yml")

    print("\n-- Done --")
    print("Next steps:")
    print("  pip install python-dateutil   # if not already installed")
    print("  python manage.py makemigrations --check")
    print("  python manage.py migrate")
    print("  python manage.py check")
    print("  python manage.py archive_monthly_performance --backfill-months=6")
    print("  git add . && git commit -m 'Add monthly performance archive, trends, comparison' && git push")


if __name__ == "__main__":
    main()
