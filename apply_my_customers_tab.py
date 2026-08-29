"""
apply_my_customers_tab.py
============================
Adds a "My Customers" tab to every staff dashboard (Retail, Telecom,
MultiChoice, Manager) -- separate from the Director's company-wide CRM.
Each staff member sees only the customers THEY have personally sold to,
with a one-tap WhatsApp message link per customer, and a month filter so
staff can pull up "who did I sell to last month" for month-end outreach.

WHAT THIS SCRIPT DOES
1. core/templatetags/customer_tags.py -> NEW: a template tag that computes
   a staff member's own customer list (checks across Retail, MultiChoice,
   and Telecom sales, same attribution logic as the Director's CRM staff
   filter), with per-staff totals -- not the customer's global totals.
2. templates/partials/my_customers.html -> NEW: the tab content -- a
   searchable, filterable customer table with a WhatsApp message button
   per customer.
3. templates/retail_dashboard.html, staff_dashboard.html (Telecom),
   multichoice_dashboard.html, manager_dashboard.html -> each gets a new
   "My Customers" tab.

Built the same low-risk way as the Monthly History tab: a template tag
that fetches its own data, so no dashboard view function needs editing --
zero risk of anchor mismatch against those already-patched views.

WHATSAPP MESSAGING
Each customer gets a "Message" button that opens WhatsApp (wa.me) with a
friendly, pre-filled greeting using their name -- staff can edit the text
right there in WhatsApp before sending, same pattern as the WhatsApp
Report feature. Nigerian numbers are auto-normalized (leading 0 -> 234)
so the links work correctly.

MONTH FILTER
A dropdown lets staff narrow the list to "customers I sold to in
[month]" -- built specifically for the month-end outreach use case.

HOW TO RUN (Replit Shell)
    python apply_my_customers_tab.py

Then:
    python manage.py check
    git add . && git commit -m "Add per-staff My Customers tab with WhatsApp messaging" && git push

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


TAGS_CONTENT = '''from django import template
from datetime import date as _date
from urllib.parse import quote

register = template.Library()


def _normalize_wa_number(phone):
    """Turn a Nigerian local number into the international format wa.me needs."""
    if not phone:
        return ""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("0") and len(digits) == 11:
        return "234" + digits[1:]
    if digits.startswith("234"):
        return digits
    return digits


@register.inclusion_tag('partials/my_customers.html', takes_context=True)
def my_customers_page(context):
    request = context['request']
    user = request.user
    from core.models import RetailSale, MultiChoiceSale, ServiceActivity, Customer

    search = request.GET.get("cust_search", "").strip()
    month_str = request.GET.get("cust_month", "")

    retail_qs = RetailSale.objects.filter(staff=user, is_voided=False)
    mc_qs = MultiChoiceSale.objects.filter(staff=user)
    tel_qs = ServiceActivity.objects.filter(staff=user)

    month_filter_active = False
    if month_str:
        try:
            m_start = _date.fromisoformat(month_str)
            from dateutil.relativedelta import relativedelta
            m_end = m_start + relativedelta(months=1)
            retail_qs = retail_qs.filter(date__gte=m_start, date__lt=m_end)
            mc_qs = mc_qs.filter(date__gte=m_start, date__lt=m_end)
            tel_qs = tel_qs.filter(date__gte=m_start, date__lt=m_end)
            month_filter_active = True
        except ValueError:
            pass

    phones = set()
    phones.update(retail_qs.exclude(customer_phone="").values_list("customer_phone", flat=True))
    phones.update(mc_qs.exclude(customer_phone="").values_list("customer_phone", flat=True))
    phones.update(tel_qs.exclude(customer_phone="").values_list("customer_phone", flat=True))

    if search:
        phones = {p for p in phones if search.lower() in p.lower()}

    customers = []
    for phone in phones:
        cust = Customer.objects.filter(phone_number=phone).first()
        name = cust.name if cust else phone

        if search and cust and search.lower() not in name.lower() and search.lower() not in phone.lower():
            continue

        r_sales = retail_qs.filter(customer_phone=phone)
        m_sales = mc_qs.filter(customer_phone=phone)
        t_sales = tel_qs.filter(customer_phone=phone)

        from django.db.models import Sum, F, Max
        r_total = r_sales.aggregate(t=Sum(F("quantity") * F("selling_price")))["t"] or 0
        m_total = m_sales.aggregate(t=Sum("amount"))["t"] or 0
        total_spent = float(r_total) + float(m_total)
        purchase_count = r_sales.count() + m_sales.count() + t_sales.count()

        last_dates = []
        r_last = r_sales.aggregate(m=Max("date"))["m"]
        m_last = m_sales.aggregate(m=Max("date"))["m"]
        t_last = t_sales.aggregate(m=Max("date"))["m"]
        for d in (r_last, m_last, t_last):
            if d:
                last_dates.append(d)
        last_purchase = max(last_dates) if last_dates else None

        if purchase_count == 0:
            continue

        customers.append({
            "name": name,
            "phone": phone,
            "wa_number": _normalize_wa_number(phone),
            "total_spent": total_spent,
            "purchase_count": purchase_count,
            "last_purchase": last_purchase,
            "wa_message": quote(f"Hi {name}, thank you for shopping with us at GPSL! We wanted to check in and see how you're doing \\u2014 let us know if there's anything you need. \\U0001F60A"),
        })

    customers.sort(key=lambda c: c["last_purchase"] or _date.min, reverse=True)

    available_months = []
    seen = set()
    for d in list(retail_qs.values_list("date", flat=True)) + list(mc_qs.values_list("date", flat=True)) + list(tel_qs.values_list("date", flat=True)):
        month_start = d.replace(day=1)
        if month_start not in seen:
            seen.add(month_start)
            available_months.append(month_start)
    available_months.sort(reverse=True)

    return {
        "my_customers": customers,
        "cust_search": search,
        "cust_month": month_str,
        "available_months": available_months,
        "month_filter_active": month_filter_active,
        "total_customers_count": len(customers),
    }
'''

PARTIAL_CONTENT = '''<div class="card">
  <p class="card-title">\U0001F465 My Customers</p>
  <p style="font-size:.8rem;color:#6b7280;margin:-.5rem 0 1rem;">Customers you've personally sold to \u2014 separate from company-wide records. Great for month-end check-ins.</p>

  <form method="GET" style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;margin-bottom:1rem;">
    <input type="text" name="cust_search" value="{{ cust_search }}" placeholder="Search name or phone"
           style="padding:.45rem .7rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem;flex:1;min-width:160px;">
    {% if available_months %}
    <select name="cust_month" style="padding:.45rem .7rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem;">
      <option value="">All Time</option>
      {% for m in available_months %}
      <option value="{{ m|date:'Y-m-d' }}" {% if cust_month == m|date:'Y-m-d' %}selected{% endif %}>Sold to in {{ m|date:"F Y" }}</option>
      {% endfor %}
    </select>
    {% endif %}
    <button type="submit" class="btn-sm btn-primary">Filter</button>
    {% if cust_search or cust_month %}<a href="?" class="btn-sm btn-outline">Clear</a>{% endif %}
  </form>

  {% if month_filter_active %}
  <p style="font-size:.78rem;color:#004F9F;background:#eff6ff;padding:.5rem .8rem;border-radius:6px;margin-bottom:1rem;">
    Showing {{ total_customers_count }} customer(s) you sold to that month \u2014 good list for a month-end thank-you message.
  </p>
  {% endif %}

  <div style="overflow-x:auto;">
    <table class="data-table">
      <thead><tr><th>Customer</th><th>Phone</th><th style="text-align:center;">Purchases</th><th style="text-align:right;">Total Spent</th><th>Last Purchase</th><th></th></tr></thead>
      <tbody>
        {% for c in my_customers %}
        <tr>
          <td><strong>{{ c.name }}</strong></td>
          <td style="font-size:.82rem;color:#6b7280;">{{ c.phone }}</td>
          <td style="text-align:center;">{{ c.purchase_count }}</td>
          <td style="text-align:right;">\u20a6{{ c.total_spent|floatformat:0 }}</td>
          <td style="font-size:.8rem;color:#6b7280;">{{ c.last_purchase|date:"d M Y"|default:"\u2014" }}</td>
          <td>
            {% if c.wa_number %}
            <a href="https://wa.me/{{ c.wa_number }}?text={{ c.wa_message }}" target="_blank" class="btn-sm" style="background:#25D366;color:#fff;text-decoration:none;padding:.35rem .7rem;font-size:.78rem;">\U0001F4AC Message</a>
            {% endif %}
          </td>
        </tr>
        {% empty %}
        <tr><td colspan="6" style="text-align:center;color:#9ca3af;padding:1.5rem;">No customers found{% if cust_search or cust_month %} for this filter{% endif %}.</td></tr>
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

TABBAR_OLD = '''  <button class="tab-btn" onclick="switchTab('myhistory',this)">\U0001F4C8 My Monthly History</button>
</div>'''

TABBAR_NEW = '''  <button class="tab-btn" onclick="switchTab('myhistory',this)">\U0001F4C8 My Monthly History</button>
  <button class="tab-btn" onclick="switchTab('mycustomers',this)">\U0001F465 My Customers</button>
</div>'''

PANEL_OLD = '''<script>
function switchTab(name, btn) {'''

PANEL_NEW = '''<div id="tab-mycustomers" class="tab-panel">
  {% load customer_tags %}
  {% my_customers_page %}
</div>

<script>
function switchTab(name, btn) {'''

MARKER = 'tab-mycustomers" class="tab-panel'


def main():
    print("-- Applying My Customers Tab --\n")

    templatetags_dir = os.path.join(BASE_DIR, "core", "templatetags")
    os.makedirs(templatetags_dir, exist_ok=True)
    init_path = os.path.join(templatetags_dir, "__init__.py")
    if not os.path.exists(init_path):
        write("core/templatetags/__init__.py", "")
        print("OK    Created core/templatetags/__init__.py")

    tags_path = os.path.join(templatetags_dir, "customer_tags.py")
    if os.path.exists(tags_path):
        print("SKIP  core/templatetags/customer_tags.py: already exists, skipping.")
    else:
        write("core/templatetags/customer_tags.py", TAGS_CONTENT)
        print("OK    Created core/templatetags/customer_tags.py")

    partial_path = os.path.join(BASE_DIR, "templates", "partials", "my_customers.html")
    if os.path.exists(partial_path):
        print("SKIP  templates/partials/my_customers.html: already exists, skipping.")
    else:
        os.makedirs(os.path.dirname(partial_path), exist_ok=True)
        write("templates/partials/my_customers.html", PARTIAL_CONTENT)
        print("OK    Created templates/partials/my_customers.html")

    for path, label in DASHBOARDS:
        content = read(path)
        if MARKER in content:
            print("SKIP  " + label + ": already has My Customers tab, skipping.")
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
        print("OK    " + label + ": added My Customers tab")

    print("\n-- Done --")
    print("Next steps:")
    print("  python manage.py check")
    print("  git add . && git commit -m 'Add per-staff My Customers tab with WhatsApp messaging' && git push")


if __name__ == "__main__":
    main()
