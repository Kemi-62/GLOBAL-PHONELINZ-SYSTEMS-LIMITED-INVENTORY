"""
apply_momo_tracking.py
=========================
New feature: Momo virtual card float tracking, tied directly to the
existing evening check-out flow.

HOW IT WORKS
- Any staff member (Retail, Telecom, MultiChoice, Manager) can carry a
  Momo float. The first time they ever report a closing balance at
  check-out, their Momo tracking begins.
- Once a staff member has ANY Momo history, entering their closing
  balance becomes REQUIRED to complete check-out -- they cannot finish
  checking out without it.
- The next day's opening balance auto-carries from that closing balance.
- At each closing, staff can also self-report any additional funds
  received that day -- these are visible to the Director in the
  oversight view for accountability.
- A "Momo History" tab is added to every staff dashboard.
- A dedicated Director-only "Momo Oversight" page shows every staff
  member's current balance, recent history, and flags anyone who hasn't
  reported in a few days.

HOW TO RUN (Replit Shell)
    python apply_momo_tracking.py

Then:
    python manage.py makemigrations --check
    python manage.py migrate
    python manage.py check
    git add . && git commit -m "Add Momo daily balance tracking tied to attendance check-out" && git push

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


MODELS_MARKER = "class DailyMomoBalance"

MODELS_OLD = "class DeviceTagCommission(models.Model):"

MODELS_NEW = '''class DailyMomoBalance(models.Model):
    """A staff member's daily Momo (virtual card) float balance, recorded
    at evening check-out. Opening balance auto-carries from the previous
    day's closing balance -- staff never re-type it."""
    staff = models.ForeignKey('User', on_delete=models.CASCADE, related_name='momo_balances')
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    additional_funds = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_balance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_closed = models.BooleanField(default=False)
    recorded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('staff', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.staff.username} - {self.date}"


class DeviceTagCommission(models.Model):'''


MIGRATION_CONTENT = '''# Generated manually to match Django 5.0.2 migration style
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0043_multichoice_sale_void_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DailyMomoBalance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('opening_balance', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('additional_funds', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('closing_balance', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('is_closed', models.BooleanField(default=False)),
                ('recorded_at', models.DateTimeField(blank=True, null=True)),
                ('branch', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.branch')),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='momo_balances', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-date'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='dailymomobalance',
            unique_together={('staff', 'date')},
        ),
    ]
'''


CHECKOUT_MARKER = "Momo closing balance"

CHECKOUT_OLD = '''        attendance.check_out_time = timezone.now()
        if selfie:
            attendance.selfie = selfie
        attendance.save()
        return JsonResponse({"success": "Check-out successful! Have a great evening."})

    return render(request, "staff/attendance.html")'''

CHECKOUT_NEW = '''        # Momo: if this staff member has ANY prior Momo history, entering
        # today's closing balance is required to complete check-out. If
        # they've never reported one before, it's optional (this is how
        # tracking begins for a staff member the first time).
        from core.models import DailyMomoBalance
        from decimal import Decimal, InvalidOperation
        from datetime import timedelta

        has_momo_history = DailyMomoBalance.objects.filter(staff=user).exists()
        momo_closing_str = request.POST.get("momo_closing_balance", "").strip()

        if has_momo_history and not momo_closing_str:
            return JsonResponse({"error": "Please enter your Momo closing balance to check out."})

        if momo_closing_str:
            try:
                momo_closing = Decimal(momo_closing_str)
            except InvalidOperation:
                return JsonResponse({"error": "Momo closing balance must be a valid number."})

            momo_additional_str = request.POST.get("momo_additional_funds", "").strip()
            try:
                momo_additional = Decimal(momo_additional_str) if momo_additional_str else Decimal("0")
            except InvalidOperation:
                momo_additional = Decimal("0")

            yesterday = today - timedelta(days=1)
            yesterday_record = DailyMomoBalance.objects.filter(
                staff=user, date=yesterday, is_closed=True
            ).first()
            opening_balance = (
                yesterday_record.closing_balance
                if yesterday_record and yesterday_record.closing_balance is not None
                else Decimal("0")
            )

            momo_record, _ = DailyMomoBalance.objects.get_or_create(
                staff=user, date=today,
                defaults={"branch": branch, "opening_balance": opening_balance},
            )
            momo_record.additional_funds = momo_additional
            momo_record.closing_balance = momo_closing
            momo_record.is_closed = True
            momo_record.recorded_at = timezone.now()
            momo_record.save()

        attendance.check_out_time = timezone.now()
        if selfie:
            attendance.selfie = selfie
        attendance.save()
        return JsonResponse({"success": "Check-out successful! Have a great evening."})

    return render(request, "staff/attendance.html")'''


MOMO_OVERSIGHT_MARKER = "def momo_oversight(request):"

MOMO_OVERSIGHT_OLD_ANCHOR = "# DIRECTOR \u2014 ALL BRANCH STOCK VIEW"

MOMO_OVERSIGHT_BLOCK = '''# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# MOMO BALANCE OVERSIGHT (DIRECTOR)
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

@role_required("DIRECTOR")
def momo_oversight(request):
    """Every staff member who carries a Momo float: their latest reported
    balance, and how many days it's been since they last reported."""
    from core.models import DailyMomoBalance, User
    from datetime import timedelta

    branch_flt = request.GET.get("branch", "")

    staff_ids = DailyMomoBalance.objects.values_list("staff_id", flat=True).distinct()
    staff_qs = User.objects.filter(id__in=staff_ids).select_related("branch")
    if branch_flt:
        staff_qs = staff_qs.filter(branch_id=branch_flt)

    today = timezone.now().date()
    staff_rows = []
    for staff in staff_qs:
        latest = DailyMomoBalance.objects.filter(staff=staff, is_closed=True).order_by("-date").first()
        days_since = (today - latest.date).days if latest else None
        staff_rows.append({
            "staff": staff,
            "latest": latest,
            "days_since": days_since,
            "is_stale": days_since is not None and days_since >= 2,
        })
    staff_rows.sort(key=lambda r: (r["days_since"] is None, -(r["days_since"] or 0)), reverse=True)

    recent_records = DailyMomoBalance.objects.filter(
        is_closed=True
    ).select_related("staff", "branch").order_by("-date", "-recorded_at")[:50]
    if branch_flt:
        recent_records = recent_records.filter(branch_id=branch_flt)

    return render(request, "momo_oversight.html", {
        "staff_rows": staff_rows,
        "recent_records": recent_records,
        "branches": Branch.objects.all(),
        "branch_flt": branch_flt,
    })


# DIRECTOR \u2014 ALL BRANCH STOCK VIEW'''


URLS_MARKER = "momo_oversight"

URLS_OLD_ANCHOR = "    path('cron/ensure-multichoice-open-week/', views.cron_ensure_multichoice_open_week, name='cron_ensure_multichoice_open_week'),\n]"

URLS_NEW_BLOCK = '''    path('cron/ensure-multichoice-open-week/', views.cron_ensure_multichoice_open_week, name='cron_ensure_multichoice_open_week'),
    path('director/momo-oversight/', views.momo_oversight, name='momo_oversight'),
]'''


MOMO_TAGS_CONTENT = '''from django import template

register = template.Library()


@register.simple_tag
def momo_has_history(user):
    from core.models import DailyMomoBalance
    return DailyMomoBalance.objects.filter(staff=user).exists()


@register.inclusion_tag('partials/momo_history.html', takes_context=True)
def momo_history_widget(context):
    request = context['request']
    user = request.user
    from core.models import DailyMomoBalance

    history = DailyMomoBalance.objects.filter(
        staff=user, is_closed=True
    ).order_by("-date")[:30]

    return {"momo_history": history}
'''


WIDGET_FLAG_MARKER = "window.HAS_MOMO_HISTORY"

WIDGET_FLAG_OLD = '''{% comment %}
  Include this partial in any dashboard that needs check-in/out:
  {% include "partials/attendance_widget.html" %}
{% endcomment %}'''

WIDGET_FLAG_NEW = '''{% comment %}
  Include this partial in any dashboard that needs check-in/out:
  {% include "partials/attendance_widget.html" %}
{% endcomment %}
{% load momo_tags %}
{% momo_has_history request.user as has_momo_history_flag %}
<script>window.HAS_MOMO_HISTORY = {{ has_momo_history_flag|yesno:"true,false" }};</script>'''

WIDGET_MARKER = "momo-section"

WIDGET_OLD = '''      <div style="margin-bottom:.8rem;">
        <label style="font-size:.78rem;font-weight:600;color:#374151;display:block;margin-bottom:.3rem;">Selfie Photo *</label>
        <input type="file" name="selfie" accept="image/*" capture="user" required
               style="width:100%;padding:.4rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem;">
      </div>
      <div style="display:flex;gap:.6rem;">'''

WIDGET_NEW = '''      <div style="margin-bottom:.8rem;">
        <label style="font-size:.78rem;font-weight:600;color:#374151;display:block;margin-bottom:.3rem;">Selfie Photo *</label>
        <input type="file" name="selfie" accept="image/*" capture="user" required
               style="width:100%;padding:.4rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem;">
      </div>
      <div id="momo-section" style="display:none;margin-bottom:.8rem;padding:.7rem;background:#f9fafb;border-radius:8px;">
        <label style="font-size:.78rem;font-weight:600;color:#374151;display:block;margin-bottom:.3rem;" id="momo-closing-label">Momo Closing Balance (\u20a6)</label>
        <input type="number" name="momo_closing_balance" id="momo-closing-input" step="0.01" min="0" placeholder="Your Momo balance right now"
               style="width:100%;padding:.4rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem;margin-bottom:.5rem;">
        <label style="font-size:.78rem;font-weight:600;color:#374151;display:block;margin-bottom:.3rem;">Additional Funds Received Today (\u20a6)</label>
        <input type="number" name="momo_additional_funds" step="0.01" min="0" placeholder="0.00 (if you received a top-up today)"
               style="width:100%;padding:.4rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem;">
        <p id="momo-help-text" style="font-size:.72rem;color:#9ca3af;margin:.4rem 0 0;">If you don't carry a Momo float, leave this blank.</p>
      </div>
      <div style="display:flex;gap:.6rem;">'''

WIDGET_JS_MARKER = "HAS_MOMO_HISTORY"

WIDGET_JS_OLD = '''function openAttModal(type) {
  attType = type;
  _geoAttempts = 0;

  var modal     = document.getElementById('att-modal');
  var title     = document.getElementById('att-modal-title');
  var submitBtn = document.getElementById('att-submit-btn');
  var form      = document.getElementById('att-form');
  var locStatus = document.getElementById('att-location-status');

  title.textContent     = type === 'in' ? '\U0001F305 Morning Check-In' : '\U0001F306 Evening Check-Out';
  submitBtn.textContent = type === 'in' ? 'Submit Check-In' : 'Submit Check-Out';
  submitBtn.className   = 'btn-sm ' + (type === 'in' ? 'btn-success' : 'btn-danger');
  submitBtn.style.flex  = '1';
  form.action           = type === 'in' ? '{% url "check_in" %}' : '{% url "check_out" %}';
  submitBtn.disabled    = true;'''

WIDGET_JS_NEW = '''function openAttModal(type) {
  attType = type;
  _geoAttempts = 0;

  var modal     = document.getElementById('att-modal');
  var title     = document.getElementById('att-modal-title');
  var submitBtn = document.getElementById('att-submit-btn');
  var form      = document.getElementById('att-form');
  var locStatus = document.getElementById('att-location-status');
  var momoSection = document.getElementById('momo-section');
  var momoInput = document.getElementById('momo-closing-input');
  var momoLabel = document.getElementById('momo-closing-label');

  title.textContent     = type === 'in' ? '\U0001F305 Morning Check-In' : '\U0001F306 Evening Check-Out';
  submitBtn.textContent = type === 'in' ? 'Submit Check-In' : 'Submit Check-Out';
  submitBtn.className   = 'btn-sm ' + (type === 'in' ? 'btn-success' : 'btn-danger');
  submitBtn.style.flex  = '1';
  form.action           = type === 'in' ? '{% url "check_in" %}' : '{% url "check_out" %}';
  submitBtn.disabled    = true;

  if (type === 'out') {
    momoSection.style.display = 'block';
    if (window.HAS_MOMO_HISTORY) {
      momoInput.required = true;
      momoLabel.textContent = 'Momo Closing Balance (\\u20a6) *';
    } else {
      momoInput.required = false;
      momoLabel.textContent = 'Momo Closing Balance (\\u20a6)';
    }
  } else {
    momoSection.style.display = 'none';
    momoInput.required = false;
  }'''


MOMO_HISTORY_PARTIAL = '''<div class="card">
  <p class="card-title">\U0001F4B3 Momo History</p>
  <p style="font-size:.8rem;color:#6b7280;margin:-.5rem 0 1rem;">Your daily Momo closing balances, most recent first. Opening balance carries forward automatically.</p>
  <div style="overflow-x:auto;">
    <table class="data-table">
      <thead><tr><th>Date</th><th style="text-align:right;">Opening</th><th style="text-align:right;">Additional Funds</th><th style="text-align:right;">Closing</th></tr></thead>
      <tbody>
        {% for r in momo_history %}
        <tr>
          <td><strong>{{ r.date|date:"d M Y" }}</strong></td>
          <td style="text-align:right;">\u20a6{{ r.opening_balance|floatformat:2 }}</td>
          <td style="text-align:right;">\u20a6{{ r.additional_funds|floatformat:2 }}</td>
          <td style="text-align:right;font-weight:700;">\u20a6{{ r.closing_balance|floatformat:2 }}</td>
        </tr>
        {% empty %}
        <tr><td colspan="4" style="text-align:center;color:#9ca3af;padding:1.5rem;">No Momo history yet \u2014 record your closing balance at check-out to begin.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
'''


DASHBOARDS = [
    ("templates/retail_dashboard.html", "retail_dashboard.html"),
    ("templates/staff_dashboard.html", "staff_dashboard.html (Telecom)"),
    ("templates/multichoice_dashboard.html", "multichoice_dashboard.html"),
    ("templates/manager_dashboard.html", "manager_dashboard.html"),
]

TABBAR_OLD = '''  <button class="tab-btn" onclick="switchTab('mycustomers',this)">\U0001F465 My Customers</button>
</div>'''

TABBAR_NEW = '''  <button class="tab-btn" onclick="switchTab('mycustomers',this)">\U0001F465 My Customers</button>
  <button class="tab-btn" onclick="switchTab('momo',this)">\U0001F4B3 Momo History</button>
</div>'''

PANEL_OLD = '''<script>
function switchTab(name, btn) {'''

PANEL_NEW = '''<div id="tab-momo" class="tab-panel">
  {% load momo_tags %}
  {% momo_history_widget %}
</div>

<script>
function switchTab(name, btn) {'''

MARKER = 'tab-momo" class="tab-panel'


MOMO_OVERSIGHT_TEMPLATE = '''{% extends "base.html" %}
{% block content %}
<style>
.page-title{font-size:1.2rem;font-weight:700;color:#004F9F;margin:0}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1.1rem 1.3rem;margin-bottom:1rem}
.card-title{font-size:.92rem;font-weight:700;margin:0 0 .85rem}
table.data-table{width:100%;border-collapse:collapse;font-size:.85rem}
table.data-table th{text-align:left;padding:.5rem;background:#f9fafb;color:#374151;font-size:.78rem}
table.data-table td{padding:.5rem;border-bottom:1px solid #f3f4f6}
</style>

<div style="margin-bottom:1.25rem">
  <h1 class="page-title">\U0001F4B3 Momo Oversight</h1>
  <p style="font-size:.85rem;color:#6b7280;margin:.3rem 0 0;">Every staff member's Momo float, and how long since they last reported it.</p>
</div>

<div class="card">
  <form method="GET" style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;">
    <select name="branch" style="padding:.45rem .7rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem;">
      <option value="">All Branches</option>
      {% for b in branches %}<option value="{{ b.id }}" {% if branch_flt == b.id|stringformat:"s" %}selected{% endif %}>{{ b.name }}</option>{% endfor %}
    </select>
    <button type="submit" class="btn-sm btn-primary">Filter</button>
  </form>
</div>

<div class="card">
  <p class="card-title">\U0001F4CB Staff Momo Status</p>
  <div style="overflow-x:auto;">
    <table class="data-table">
      <thead><tr><th>Staff</th><th>Branch</th><th style="text-align:right;">Latest Closing Balance</th><th>Last Reported</th><th>Status</th></tr></thead>
      <tbody>
        {% for row in staff_rows %}
        <tr>
          <td><strong>{{ row.staff.username }}</strong></td>
          <td>{{ row.staff.branch.name|default:"\u2014" }}</td>
          <td style="text-align:right;">{% if row.latest %}\u20a6{{ row.latest.closing_balance|floatformat:2 }}{% else %}\u2014{% endif %}</td>
          <td>{% if row.latest %}{{ row.latest.date|date:"d M Y" }} ({{ row.days_since }} day{{ row.days_since|pluralize }} ago){% else %}Never{% endif %}</td>
          <td>
            {% if row.is_stale %}<span class="badge" style="background:#fee2e2;color:#991b1b;padding:.25rem .6rem;border-radius:999px;font-size:.72rem;">\u26A0\uFE0F Not reporting</span>
            {% elif row.latest %}<span class="badge" style="background:#d1fae5;color:#065f46;padding:.25rem .6rem;border-radius:999px;font-size:.72rem;">Up to date</span>
            {% else %}<span class="badge" style="background:#f1f5f9;color:#475569;padding:.25rem .6rem;border-radius:999px;font-size:.72rem;">No history</span>{% endif %}
          </td>
        </tr>
        {% empty %}
        <tr><td colspan="5" style="text-align:center;color:#9ca3af;padding:1.5rem;">No staff have started Momo tracking yet.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>

<div class="card">
  <p class="card-title">\U0001F4C5 Recent Daily Records</p>
  <div style="overflow-x:auto;">
    <table class="data-table">
      <thead><tr><th>Date</th><th>Staff</th><th>Branch</th><th style="text-align:right;">Opening</th><th style="text-align:right;">Additional Funds</th><th style="text-align:right;">Closing</th></tr></thead>
      <tbody>
        {% for r in recent_records %}
        <tr>
          <td>{{ r.date|date:"d M Y" }}</td>
          <td><strong>{{ r.staff.username }}</strong></td>
          <td>{{ r.branch.name|default:"\u2014" }}</td>
          <td style="text-align:right;">\u20a6{{ r.opening_balance|floatformat:2 }}</td>
          <td style="text-align:right;">\u20a6{{ r.additional_funds|floatformat:2 }}</td>
          <td style="text-align:right;font-weight:700;">\u20a6{{ r.closing_balance|floatformat:2 }}</td>
        </tr>
        {% empty %}
        <tr><td colspan="6" style="text-align:center;color:#9ca3af;padding:1.5rem;">No records yet.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
'''


SIDEBAR_MARKER = "momo_oversight"

SIDEBAR_OLD = '''        <a href="{% url 'monthly_performance' %}" class="sidebar-link">
            <span class="icon">\U0001F4C8</span> Monthly Performance
        </a>'''

SIDEBAR_NEW = '''        <a href="{% url 'monthly_performance' %}" class="sidebar-link">
            <span class="icon">\U0001F4C8</span> Monthly Performance
        </a>
        <a href="{% url 'momo_oversight' %}" class="sidebar-link">
            <span class="icon">\U0001F4B3</span> Momo Oversight
        </a>'''


def main():
    print("-- Applying Momo Balance Tracking --\n")

    patch("core/models.py", MODELS_OLD, MODELS_NEW, MODELS_MARKER,
          "models.py: DailyMomoBalance model")

    migration_path = os.path.join(BASE_DIR, "core", "migrations", "0044_daily_momo_balance.py")
    if os.path.exists(migration_path):
        print("SKIP  migration 0044: already exists, skipping.")
    else:
        write("core/migrations/0044_daily_momo_balance.py", MIGRATION_CONTENT)
        print("OK    Created core/migrations/0044_daily_momo_balance.py")

    patch("core/views.py", CHECKOUT_OLD, CHECKOUT_NEW, CHECKOUT_MARKER,
          "views.py: check_out extended with Momo handling")
    patch("core/views.py", MOMO_OVERSIGHT_OLD_ANCHOR, MOMO_OVERSIGHT_BLOCK, MOMO_OVERSIGHT_MARKER,
          "views.py: momo_oversight view")
    patch("core/urls.py", URLS_OLD_ANCHOR, URLS_NEW_BLOCK, URLS_MARKER,
          "urls.py: momo_oversight route")

    tags_dir = os.path.join(BASE_DIR, "core", "templatetags")
    os.makedirs(tags_dir, exist_ok=True)
    init_path = os.path.join(tags_dir, "__init__.py")
    if not os.path.exists(init_path):
        write("core/templatetags/__init__.py", "")
        print("OK    Created core/templatetags/__init__.py")

    momo_tags_path = os.path.join(tags_dir, "momo_tags.py")
    if os.path.exists(momo_tags_path):
        print("SKIP  core/templatetags/momo_tags.py: already exists, skipping.")
    else:
        write("core/templatetags/momo_tags.py", MOMO_TAGS_CONTENT)
        print("OK    Created core/templatetags/momo_tags.py")

    patch("templates/partials/attendance_widget.html", WIDGET_FLAG_OLD, WIDGET_FLAG_NEW, WIDGET_FLAG_MARKER,
          "attendance_widget.html: HAS_MOMO_HISTORY JS flag")
    patch("templates/partials/attendance_widget.html", WIDGET_OLD, WIDGET_NEW, WIDGET_MARKER,
          "attendance_widget.html: Momo fields in checkout modal")
    patch("templates/partials/attendance_widget.html", WIDGET_JS_OLD, WIDGET_JS_NEW, WIDGET_JS_MARKER,
          "attendance_widget.html: JS to show/require Momo on check-out")

    momo_history_path = os.path.join(BASE_DIR, "templates", "partials", "momo_history.html")
    if os.path.exists(momo_history_path):
        print("SKIP  templates/partials/momo_history.html: already exists, skipping.")
    else:
        os.makedirs(os.path.dirname(momo_history_path), exist_ok=True)
        write("templates/partials/momo_history.html", MOMO_HISTORY_PARTIAL)
        print("OK    Created templates/partials/momo_history.html")

    for path, label in DASHBOARDS:
        content = read(path)
        if MARKER in content:
            print("SKIP  " + label + ": already has Momo History tab, skipping.")
            continue
        if TABBAR_OLD not in content:
            print("FAIL  " + label + ": tab bar anchor not found.")
            print("      Send the current version of that file and ask for a regenerated script.")
            sys.exit(1)
        content = content.replace(TABBAR_OLD, TABBAR_NEW, 1)
        if PANEL_OLD not in content:
            print("FAIL  " + label + ": panel anchor not found.")
            sys.exit(1)
        content = content.replace(PANEL_OLD, PANEL_NEW, 1)
        write(path, content)
        print("OK    " + label + ": added Momo History tab")

    momo_oversight_path = os.path.join(BASE_DIR, "templates", "momo_oversight.html")
    if os.path.exists(momo_oversight_path):
        print("SKIP  templates/momo_oversight.html: already exists, skipping.")
    else:
        write("templates/momo_oversight.html", MOMO_OVERSIGHT_TEMPLATE)
        print("OK    Created templates/momo_oversight.html")

    patch("templates/base.html", SIDEBAR_OLD, SIDEBAR_NEW, SIDEBAR_MARKER,
          "base.html: Momo Oversight sidebar link")

    print("\n-- Done --")
    print("Next steps:")
    print("  python manage.py makemigrations --check")
    print("  python manage.py migrate")
    print("  python manage.py check")
    print("  git add . && git commit -m 'Add Momo daily balance tracking' && git push")


if __name__ == "__main__":
    main()


