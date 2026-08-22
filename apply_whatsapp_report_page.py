"""
apply_whatsapp_report_page.py
================================
Adds a dedicated WhatsApp Report page for Managers, plus a cron endpoint
so GitHub Actions can auto-send a company-wide report every evening.

The backend logic (send_daily_report_whatsapp, send_stock_request_whatsapp)
already existed in your code but was never wired to a URL or a button --
dead code. This script wires it up properly with a real page.

WHAT THIS SCRIPT DOES
1. core/views.py     -> adds report-building helpers, whatsapp_report_page() view,
                        cron_whatsapp_report() view
2. core/urls.py      -> adds /manager/whatsapp-report/ and /cron/whatsapp-report/
3. templates/manager_dashboard.html -> adds a WhatsApp Report button to the header
4. templates/whatsapp_report.html   -> NEW FILE - the report preview page
5. templates/base.html -> adds a WhatsApp Report sidebar link for Managers
6. .github/workflows/whatsapp_report.yml -> NEW FILE - daily cron trigger
7. django_project/settings.py -> DIRECTOR_WHATSAPP / CALLMEBOT_API_KEY settings

HOW TO RUN (Replit Shell)
    python apply_whatsapp_report_page.py

Then:
    python manage.py check
    git add . && git commit -m "Add dedicated WhatsApp report page + cron" && git push

Setup (free CallMeBot API, one-time):
1. On the Director's phone, WhatsApp "I allow callmebot to send me messages"
   to +34 644 51 95 23
2. CallMeBot replies with a personal apikey
3. Add DIRECTOR_WHATSAPP (director's number, no + or spaces) and
   CALLMEBOT_API_KEY (the key from step 2) to your Render environment variables

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


VIEWS_MARKER = "def whatsapp_report_page(request):"

VIEWS_OLD_ANCHOR = "# DIRECTOR \u2014 ALL BRANCH STOCK VIEW"

VIEWS_NEW_BLOCK = '''# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# WHATSAPP REPORT - DEDICATED PAGE + CRON
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def _build_daily_report_message(branch, report_date):
    """Build the WhatsApp-formatted daily report text for one branch."""
    sales = RetailSale.objects.filter(branch=branch, date=report_date, is_voided=False)
    total_qty = sales.aggregate(t=Sum("quantity"))["t"] or 0
    total_rev = sales.aggregate(t=Sum(F("quantity") * F("selling_price")))["t"] or 0
    mc_rev = MultiChoiceSale.objects.filter(branch=branch, date=report_date).aggregate(t=Sum("amount"))["t"] or 0
    expenses = Expense.objects.filter(branch=branch, date=report_date).aggregate(t=Sum("amount"))["t"] or 0
    pending_requests = StockRequest.objects.filter(branch=branch, status="PENDING").count()

    lines = [
        "\U0001F4CA *DAILY BRANCH REPORT*",
        "Branch: " + branch.name,
        "Date: " + report_date.strftime("%d %B %Y"),
        "",
        "\U0001F6CD\uFE0F Retail Sales: " + str(total_qty) + " items",
        "\U0001F4B0 Retail Revenue: \u20A6{:,.0f}".format(total_rev),
        "\U0001F4FA MultiChoice: \u20A6{:,.0f}".format(mc_rev),
        "\U0001F4B8 Expenses: \u20A6{:,.0f}".format(expenses),
        "\U0001F4E6 Pending Stock Requests: " + str(pending_requests),
        "",
        "Net (Retail - Expenses): \u20A6{:,.0f}".format(total_rev - expenses),
    ]
    return "\\n".join(lines)


def _build_all_branches_report_message(report_date):
    """One combined WhatsApp report covering every branch - used by the cron job."""
    lines = ["\U0001F4CA *GPSL COMPANY DAILY REPORT*", report_date.strftime("%d %B %Y"), ""]
    grand_rev = 0
    grand_qty = 0
    for branch in Branch.objects.all():
        sales = RetailSale.objects.filter(branch=branch, date=report_date, is_voided=False)
        qty = sales.aggregate(t=Sum("quantity"))["t"] or 0
        rev = sales.aggregate(t=Sum(F("quantity") * F("selling_price")))["t"] or 0
        if qty or rev:
            lines.append("\U0001F3EA *" + branch.name + "*: " + str(qty) + " items \u2014 \u20A6{:,.0f}".format(rev))
        grand_rev += rev
        grand_qty += qty
    lines.append("")
    lines.append("\U0001F4B0 *Total Revenue*: \u20A6{:,.0f}".format(grand_rev))
    lines.append("\U0001F6CD\uFE0F *Total Items Sold*: " + str(grand_qty))
    return "\\n".join(lines)


@role_required("MANAGER")
def whatsapp_report_page(request):
    """Dedicated page: preview today's (or a chosen date's) branch report,
    then send it to the Director via CallMeBot or open it directly in WhatsApp."""
    from urllib.parse import quote

    branch = request.user.branch
    date_str = request.GET.get("date", "")
    if date_str:
        try:
            report_date = timezone.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            report_date = timezone.now().date()
    else:
        report_date = timezone.now().date()

    message = _build_daily_report_message(branch, report_date)
    wa_link = "https://wa.me/?text=" + quote(message)

    return render(request, "whatsapp_report.html", {
        "report_message": message,
        "report_date": report_date,
        "wa_link": wa_link,
    })


# DIRECTOR \u2014 ALL BRANCH STOCK VIEW'''

CRON_MARKER = "def cron_whatsapp_report(request):"

CRON_OLD_ANCHOR = '''def offline_page(request):
    """PWA offline fallback page."""'''

CRON_NEW_BLOCK = '''def cron_whatsapp_report(request):
    if not _check_cron_secret(request):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    try:
        report_date = timezone.now().date()
        message = _build_all_branches_report_message(report_date)
        phone = _get_director_phone()
        sent = send_whatsapp(phone, message)
        return JsonResponse({
            'ok': bool(sent),
            'message': 'WhatsApp report sent' if sent else 'Could not send - check DIRECTOR_WHATSAPP/CALLMEBOT_API_KEY',
        })
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


def offline_page(request):
    """PWA offline fallback page."""'''


URLS_MARKER = "whatsapp_report_page"

URLS_OLD_ANCHOR = "    path('online-sales/overview/', views.online_sales_overview, name='online_sales_overview'),\n]"

URLS_NEW_BLOCK = '''    path('online-sales/overview/', views.online_sales_overview, name='online_sales_overview'),
    path('manager/send-daily-report-whatsapp/', views.send_daily_report_whatsapp, name='send_daily_report_whatsapp'),
    path('manager/send-stock-request-whatsapp/', views.send_stock_request_whatsapp, name='send_stock_request_whatsapp'),
    path('manager/whatsapp-report/', views.whatsapp_report_page, name='whatsapp_report_page'),
    path('cron/whatsapp-report/', views.cron_whatsapp_report, name='cron_whatsapp_report'),
]'''


DASH_MARKER = "whatsapp_report_page"

DASH_OLD_ANCHOR = '''  <div style="display:flex;gap:.6rem;flex-wrap:wrap;">
    {% include "partials/attendance_widget.html" %}
  </div>
</div>'''

DASH_NEW_BLOCK = '''  <div style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;">
    <a href="{% url 'whatsapp_report_page' %}" class="btn-sm" style="background:#25D366;color:#fff;text-decoration:none;">\U0001F4F1 WhatsApp Report</a>
    {% include "partials/attendance_widget.html" %}
  </div>
</div>'''


SIDEBAR_MARKER = "whatsapp_report_page"

SIDEBAR_OLD_ANCHOR = '''        <a href="{% url 'stock_alerts' %}" class="sidebar-link">
            <span class="icon">\u26A0\uFE0F</span> Stock Alerts
        </a>
    </div>
    <div class="sidebar-divider"></div>
    <div class="sidebar-section">
        <div class="sidebar-section-label">Telecom</div>
        <a href="{% url 'add_device_commission' %}" class="sidebar-link">'''

SIDEBAR_NEW_BLOCK = '''        <a href="{% url 'stock_alerts' %}" class="sidebar-link">
            <span class="icon">\u26A0\uFE0F</span> Stock Alerts
        </a>
        <a href="{% url 'whatsapp_report_page' %}" class="sidebar-link">
            <span class="icon">\U0001F4F1</span> WhatsApp Report
        </a>
    </div>
    <div class="sidebar-divider"></div>
    <div class="sidebar-section">
        <div class="sidebar-section-label">Telecom</div>
        <a href="{% url 'add_device_commission' %}" class="sidebar-link">'''


WHATSAPP_REPORT_TEMPLATE = '''{% extends "base.html" %}
{% block content %}
<style>
.page-title{font-size:1.2rem;font-weight:700;color:#004F9F;margin:0}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1.1rem 1.3rem;margin-bottom:1rem}
.card-title{font-size:.92rem;font-weight:700;margin:0 0 .85rem}
.btn-sm{padding:.5rem 1rem;font-size:.85rem;border-radius:6px;border:none;cursor:pointer;font-weight:600;text-decoration:none;display:inline-block}
.wa-preview{background:#e5ddd5;border-radius:10px;padding:1rem;font-size:.88rem;line-height:1.6;white-space:pre-wrap;font-family:inherit;color:#111;}
.wa-bubble{background:#fff;border-radius:8px;padding:.8rem 1rem;box-shadow:0 1px 2px rgba(0,0,0,.15);white-space:pre-wrap;}
</style>

<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.75rem;margin-bottom:1.25rem">
  <h1 class="page-title">\U0001F4F1 WhatsApp Report</h1>
  <form method="GET" style="display:flex;gap:.5rem;align-items:center;">
    <input type="date" name="date" value="{{ report_date|date:'Y-m-d' }}"
           style="padding:.45rem .7rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem;">
    <button type="submit" class="btn-sm" style="background:#004F9F;color:#fff;">Preview</button>
  </form>
</div>

{% if messages %}{% for m in messages %}
<div style="background:{% if m.tags == 'error' %}#fee2e2{% else %}#dcfce7{% endif %};border-radius:7px;padding:.65rem 1rem;font-size:.83rem;margin-bottom:1rem;">{{ m }}</div>
{% endfor %}{% endif %}

<div class="card">
  <p class="card-title">Preview - {{ report_date|date:"d M Y" }}</p>
  <div class="wa-preview">
    <div class="wa-bubble">{{ report_message }}</div>
  </div>
</div>

<div class="card">
  <p class="card-title">Send It</p>
  <div style="display:flex;gap:.75rem;flex-wrap:wrap;">
    <form method="POST" action="{% url 'send_daily_report_whatsapp' %}">
      {% csrf_token %}
      <button type="submit" class="btn-sm" style="background:#25D366;color:#fff;">\U0001F4E4 Send via CallMeBot to Director</button>
    </form>
    <a href="{{ wa_link }}" target="_blank" class="btn-sm" style="background:#128C7E;color:#fff;">\U0001F4AC Open in WhatsApp App</a>
  </div>
  <p style="font-size:.78rem;color:#6b7280;margin:.75rem 0 0;">
    "Send via CallMeBot" only works if <code>DIRECTOR_WHATSAPP</code> and <code>CALLMEBOT_API_KEY</code>
    are set in your environment. "Open in WhatsApp App" always works.
  </p>
</div>
{% endblock %}
'''

WORKFLOW_YML = '''name: GPSL WhatsApp Report

on:
  schedule:
    - cron: '15 18 * * 1-6'
  workflow_dispatch:

jobs:
  whatsapp-report:
    runs-on: ubuntu-latest
    steps:
      - name: Wake Render app
        run: |
          curl -s --max-time 60 "https://app.globalphonelinz.com/system/keepalive/" || true
          sleep 15
      - name: Send WhatsApp report
        run: |
          curl -s --max-time 120 \\
            "https://app.globalphonelinz.com/cron/whatsapp-report/?key=gpsl2026backup"
'''

SETTINGS_MARKER = "DIRECTOR_WHATSAPP"
SETTINGS_OLD = "WHATSAPP_PHONE_NUMBER_ID = config('WHATSAPP_PHONE_NUMBER_ID', default='')"
SETTINGS_NEW = '''WHATSAPP_PHONE_NUMBER_ID = config('WHATSAPP_PHONE_NUMBER_ID', default='')

# CallMeBot -- used for the Manager WhatsApp Report page.
DIRECTOR_WHATSAPP = config('DIRECTOR_WHATSAPP', default='')
CALLMEBOT_API_KEY = config('CALLMEBOT_API_KEY', default='')'''


def main():
    print("-- Applying WhatsApp Report Page --\n")

    patch("core/views.py", VIEWS_OLD_ANCHOR, VIEWS_NEW_BLOCK, VIEWS_MARKER,
          "views.py: report-building helpers + page view")
    patch("core/views.py", CRON_OLD_ANCHOR, CRON_NEW_BLOCK, CRON_MARKER,
          "views.py: cron_whatsapp_report endpoint")
    patch("core/urls.py", URLS_OLD_ANCHOR, URLS_NEW_BLOCK, URLS_MARKER,
          "urls.py: new routes")
    patch("templates/manager_dashboard.html", DASH_OLD_ANCHOR, DASH_NEW_BLOCK, DASH_MARKER,
          "manager_dashboard.html: header button")
    patch("templates/base.html", SIDEBAR_OLD_ANCHOR, SIDEBAR_NEW_BLOCK, SIDEBAR_MARKER,
          "base.html: sidebar link")
    patch("django_project/settings.py", SETTINGS_OLD, SETTINGS_NEW, SETTINGS_MARKER,
          "settings.py: DIRECTOR_WHATSAPP + CALLMEBOT_API_KEY")

    wa_report_path = os.path.join(BASE_DIR, "templates", "whatsapp_report.html")
    if os.path.exists(wa_report_path):
        print("SKIP  templates/whatsapp_report.html: already exists, skipping.")
    else:
        write("templates/whatsapp_report.html", WHATSAPP_REPORT_TEMPLATE)
        print("OK    Created templates/whatsapp_report.html")

    workflow_path = os.path.join(BASE_DIR, ".github", "workflows", "whatsapp_report.yml")
    if os.path.exists(workflow_path):
        print("SKIP  .github/workflows/whatsapp_report.yml: already exists, skipping.")
    else:
        os.makedirs(os.path.dirname(workflow_path), exist_ok=True)
        write(".github/workflows/whatsapp_report.yml", WORKFLOW_YML)
        print("OK    Created .github/workflows/whatsapp_report.yml")

    print("\n-- Done --")
    print("Next steps:")
    print("  python manage.py check")
    print("  git add . && git commit -m 'Add dedicated WhatsApp report page + cron' && git push")


if __name__ == "__main__":
    main()
