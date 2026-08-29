"""
apply_my_customers_csv_export.py
===================================
Adds an "Export CSV" button to the My Customers tab, so staff can
download their (optionally filtered) customer list as a CSV file --
open it in Excel/Google Sheets, or copy the phone number column straight
into WhatsApp's bulk broadcast / any messaging app's bulk-import.

The export respects whatever filter is currently applied on the page --
if a staff member has filtered to "Sold to in August 2026", the exported
CSV contains only that month's customers.

WHAT THIS SCRIPT DOES
1. core/templatetags/customer_tags.py -> refactors the customer-fetching
   logic into a standalone function so it can be reused (previously it
   only lived inside the template tag) -- no behavior change, purely
   makes the logic reusable for the CSV export below.
2. core/views.py -> new export_my_customers_csv view, using that same
   shared function so the CSV always matches exactly what's on screen.
3. core/urls.py -> the export route.
4. templates/partials/my_customers.html -> "Export CSV" button added
   next to the Filter button, carrying over the current search/month
   filter as query params.

CSV COLUMNS: Name, Phone, Purchases, Total Spent, Last Purchase

HOW TO RUN (Replit Shell)
    python apply_my_customers_csv_export.py

Then:
    python manage.py check
    git add . && git commit -m "Add CSV export to My Customers tab" && git push

IDEMPOTENT - safe to run twice.

PREREQUISITE: apply_my_customers_tab.py must already be applied (this
script builds directly on top of it and will stop with a clear message
if it isn't there yet).
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


PREREQ_MARKER = "def my_customers_page(context):"


def check_prereq():
    content = read("core/templatetags/customer_tags.py")
    if PREREQ_MARKER not in content:
        print("XX This script builds on top of apply_my_customers_tab.py,")
        print("   which doesn't look like it's been applied yet.")
        print("   Run that one first: python apply_my_customers_tab.py")
        sys.exit(1)


TAGS_MARKER = "def get_my_customers_data("

TAGS_OLD = '''@register.inclusion_tag('partials/my_customers.html', takes_context=True)
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
    }'''

TAGS_NEW = '''def get_my_customers_data(user, search="", month_str=""):
    """Shared logic: a staff member's own customer list, optionally
    filtered by search text and/or a specific month sold-to. Used by both
    the dashboard tab (my_customers_page) and the CSV export view, so the
    export always matches exactly what's on screen."""
    from core.models import RetailSale, MultiChoiceSale, ServiceActivity, Customer

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


@register.inclusion_tag('partials/my_customers.html', takes_context=True)
def my_customers_page(context):
    request = context['request']
    user = request.user
    search = request.GET.get("cust_search", "").strip()
    month_str = request.GET.get("cust_month", "")
    return get_my_customers_data(user, search, month_str)'''


VIEWS_MARKER = "def export_my_customers_csv(request):"

VIEWS_OLD_ANCHOR = "# DIRECTOR \u2014 ALL BRANCH STOCK VIEW"

VIEWS_NEW_BLOCK = '''@login_required
def export_my_customers_csv(request):
    """Download the logged-in staff member's own (optionally filtered)
    customer list as CSV -- for bulk messaging or spreadsheet use."""
    from core.templatetags.customer_tags import get_my_customers_data

    search = request.GET.get("cust_search", "").strip()
    month_str = request.GET.get("cust_month", "")
    data = get_my_customers_data(request.user, search, month_str)

    response = HttpResponse(content_type="text/csv")
    filename = "my_customers"
    if month_str:
        filename += "_" + month_str
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'

    writer = csv.writer(response)
    writer.writerow(["Name", "Phone", "Purchases", "Total Spent", "Last Purchase"])
    for c in data["my_customers"]:
        writer.writerow([
            c["name"],
            c["phone"],
            c["purchase_count"],
            f'{c["total_spent"]:.2f}',
            c["last_purchase"].strftime("%Y-%m-%d") if c["last_purchase"] else "",
        ])
    return response


# DIRECTOR \u2014 ALL BRANCH STOCK VIEW'''


URLS_MARKER = "export_my_customers_csv"

URLS_OLD_ANCHOR = "    path('cron/archive-staff-monthly-performance/', views.cron_archive_staff_monthly_performance, name='cron_archive_staff_monthly_performance'),\n]"

URLS_NEW_BLOCK = '''    path('cron/archive-staff-monthly-performance/', views.cron_archive_staff_monthly_performance, name='cron_archive_staff_monthly_performance'),
    path('my-customers/export/', views.export_my_customers_csv, name='export_my_customers_csv'),
]'''


TEMPLATE_MARKER = "export_my_customers_csv"

TEMPLATE_OLD = '''    <button type="submit" class="btn-sm btn-primary">Filter</button>
    {% if cust_search or cust_month %}<a href="?" class="btn-sm btn-outline">Clear</a>{% endif %}
  </form>'''

TEMPLATE_NEW = '''    <button type="submit" class="btn-sm btn-primary">Filter</button>
    {% if cust_search or cust_month %}<a href="?" class="btn-sm btn-outline">Clear</a>{% endif %}
    <a href="{% url 'export_my_customers_csv' %}?cust_search={{ cust_search }}&cust_month={{ cust_month }}" class="btn-sm btn-outline">\u2b07\ufe0f Export CSV</a>
  </form>'''


def main():
    print("-- Applying My Customers CSV Export --\n")

    check_prereq()

    patch("core/templatetags/customer_tags.py", TAGS_OLD, TAGS_NEW, TAGS_MARKER,
          "customer_tags.py: extract shared get_my_customers_data() function")
    patch("core/views.py", VIEWS_OLD_ANCHOR, VIEWS_NEW_BLOCK, VIEWS_MARKER,
          "views.py: export_my_customers_csv view")
    patch("core/urls.py", URLS_OLD_ANCHOR, URLS_NEW_BLOCK, URLS_MARKER,
          "urls.py: export route")
    patch("templates/partials/my_customers.html", TEMPLATE_OLD, TEMPLATE_NEW, TEMPLATE_MARKER,
          "my_customers.html: Export CSV button")

    print("\n-- Done --")
    print("Next steps:")
    print("  python manage.py check")
    print("  git add . && git commit -m 'Add CSV export to My Customers tab' && git push")


if __name__ == "__main__":
    main()
