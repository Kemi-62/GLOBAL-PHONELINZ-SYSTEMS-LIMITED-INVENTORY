"""
apply_crm_staff_filter.py
==========================
Adds a "Staff" filter to the Customer CRM page (Director), on top of the
existing Branch / Sales Origin / Date range filters.

WHAT THIS SCRIPT DOES
1. core/views.py            -> customer_crm() gets a staff_flt filter + staff_list context
2. templates/customer_crm.html -> new "Staff" dropdown, active-filter badge, pagination links

HOW TO RUN (Replit Shell)
    python apply_crm_staff_filter.py

Then:
    python manage.py check
    git add . && git commit -m "Add staff filter to Customer CRM" && git push

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


VIEW_MARKER = "staff member who handled the sale"

VIEW_OLD = '''    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to", "")
    search     = request.GET.get("search", "")
    source     = request.GET.get("source", "")   # RETAIL, MULTICHOICE, TELECOM
    branch_flt = request.GET.get("branch", "")
    sort_by    = request.GET.get("sort", "-last_purchase")  # or -total_spent, -purchase_count

    customers = Customer.objects.all().order_by(sort_by)

    if search:
        customers = customers.filter(
            Q(name__icontains=search) | Q(phone_number__icontains=search)
        )
    if date_from:
        customers = customers.filter(last_purchase__date__gte=date_from)
    if date_to:
        customers = customers.filter(last_purchase__date__lte=date_to)
    if branch_flt:
        customers = customers.filter(branch_id=branch_flt)

    # Filter by source — check if phone appears in that source
    if source == "RETAIL":
        phones = RetailSale.objects.filter(
            is_voided=False
        ).values_list("customer_phone", flat=True).distinct()
        customers = customers.filter(phone_number__in=phones)
    elif source == "MULTICHOICE":
        phones = MultiChoiceSale.objects.values_list(
            "customer_phone", flat=True
        ).distinct()
        customers = customers.filter(phone_number__in=phones)
    elif source == "TELECOM":
        phones = ServiceActivity.objects.values_list(
            "customer_phone", flat=True
        ).distinct()
        customers = customers.filter(phone_number__in=phones)

    paginator = Paginator(customers, 30)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "customer_crm.html", {
        "customers": page,
        "total_customers": customers.count(),
        "search": search,
        "date_from": date_from,
        "date_to": date_to,
        "source": source,
        "branch_flt": branch_flt,
        "sort_by": sort_by,
        "branches": Branch.objects.all(),
    })'''

VIEW_NEW = '''    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to", "")
    search     = request.GET.get("search", "")
    source     = request.GET.get("source", "")   # RETAIL, MULTICHOICE, TELECOM
    branch_flt = request.GET.get("branch", "")
    staff_flt  = request.GET.get("staff", "")     # filter by the specific staff member who made the sale
    sort_by    = request.GET.get("sort", "-last_purchase")  # or -total_spent, -purchase_count

    customers = Customer.objects.all().order_by(sort_by)

    if search:
        customers = customers.filter(
            Q(name__icontains=search) | Q(phone_number__icontains=search)
        )
    if date_from:
        customers = customers.filter(last_purchase__date__gte=date_from)
    if date_to:
        customers = customers.filter(last_purchase__date__lte=date_to)
    if branch_flt:
        customers = customers.filter(branch_id=branch_flt)

    # Filter by source — check if phone appears in that source
    if source == "RETAIL":
        phones = RetailSale.objects.filter(
            is_voided=False
        ).values_list("customer_phone", flat=True).distinct()
        customers = customers.filter(phone_number__in=phones)
    elif source == "MULTICHOICE":
        phones = MultiChoiceSale.objects.values_list(
            "customer_phone", flat=True
        ).distinct()
        customers = customers.filter(phone_number__in=phones)
    elif source == "TELECOM":
        phones = ServiceActivity.objects.values_list(
            "customer_phone", flat=True
        ).distinct()
        customers = customers.filter(phone_number__in=phones)

    # Filter by the specific staff member who handled the sale — checks
    # across all three sale types so it works regardless of the source filter above.
    if staff_flt:
        staff_phones = set()
        staff_phones.update(
            RetailSale.objects.filter(staff_id=staff_flt, is_voided=False)
            .values_list("customer_phone", flat=True).distinct()
        )
        staff_phones.update(
            MultiChoiceSale.objects.filter(staff_id=staff_flt)
            .values_list("customer_phone", flat=True).distinct()
        )
        staff_phones.update(
            ServiceActivity.objects.filter(staff_id=staff_flt)
            .values_list("customer_phone", flat=True).distinct()
        )
        customers = customers.filter(phone_number__in=staff_phones)

    paginator = Paginator(customers, 30)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "customer_crm.html", {
        "customers": page,
        "total_customers": customers.count(),
        "search": search,
        "date_from": date_from,
        "date_to": date_to,
        "source": source,
        "branch_flt": branch_flt,
        "staff_flt": staff_flt,
        "sort_by": sort_by,
        "branches": Branch.objects.all(),
        "staff_list": User.objects.filter(
            role__in=["RETAIL", "TELECOM", "MULTICHOICE"]
        ).order_by("username"),
    })'''


TEMPLATE_MARKER = 'name="staff"'

FILTER_OLD = '''    <div>
      <span class="filter-label">Branch</span>
      <select name="branch">
        <option value="">All Branches</option>
        {% for b in branches %}
        <option value="{{ b.id }}" {% if branch_flt == b.id|stringformat:"s" %}selected{% endif %}>{{ b.name }}</option>
        {% endfor %}
      </select>
    </div>'''

FILTER_NEW = '''    <div>
      <span class="filter-label">Branch</span>
      <select name="branch">
        <option value="">All Branches</option>
        {% for b in branches %}
        <option value="{{ b.id }}" {% if branch_flt == b.id|stringformat:"s" %}selected{% endif %}>{{ b.name }}</option>
        {% endfor %}
      </select>
    </div>
    <div>
      <span class="filter-label">Staff</span>
      <select name="staff">
        <option value="">All Staff</option>
        {% for s in staff_list %}
        <option value="{{ s.id }}" {% if staff_flt == s.id|stringformat:"s" %}selected{% endif %}>{{ s.username }} ({{ s.role|title }})</option>
        {% endfor %}
      </select>
    </div>'''

BANNER_MARKER = "Staff: <strong>"

BANNER_OLD = '''  {% if search or date_from or date_to or source or branch_flt %}
  <div style="background:#eff6ff;border:1px solid #93c5fd;border-radius:6px;padding:.5rem .9rem;font-size:.82rem;color:#1e40af;margin-bottom:1rem;">
    Filtered results
    {% if source %} — Source: <strong>{{ source }}</strong>{% endif %}
    {% if date_from %} — From: <strong>{{ date_from }}</strong>{% endif %}
    {% if date_to %} — To: <strong>{{ date_to }}</strong>{% endif %}
    {% if search %} — Search: <strong>{{ search }}</strong>{% endif %}
  </div>
  {% endif %}'''

BANNER_NEW = '''  {% if search or date_from or date_to or source or branch_flt or staff_flt %}
  <div style="background:#eff6ff;border:1px solid #93c5fd;border-radius:6px;padding:.5rem .9rem;font-size:.82rem;color:#1e40af;margin-bottom:1rem;">
    Filtered results
    {% if source %} — Source: <strong>{{ source }}</strong>{% endif %}
    {% if staff_flt %} — Staff: <strong>{{ staff_flt }}</strong>{% endif %}
    {% if date_from %} — From: <strong>{{ date_from }}</strong>{% endif %}
    {% if date_to %} — To: <strong>{{ date_to }}</strong>{% endif %}
    {% if search %} — Search: <strong>{{ search }}</strong>{% endif %}
  </div>
  {% endif %}'''

PAGINATION_MARKER = "&staff={{ staff_flt }}"

PAGINATION_OLD = '''    <a href="?page={{ customers.previous_page_number }}&search={{ search }}&date_from={{ date_from }}&date_to={{ date_to }}&source={{ source }}&branch={{ branch_flt }}&sort={{ sort_by }}" class="btn-sm btn-outline">← Prev</a>
    {% endif %}
    <span style="padding:.5rem 1rem;font-size:.85rem;color:#6b7280;">Page {{ customers.number }} of {{ customers.paginator.num_pages }}</span>
    {% if customers.has_next %}
    <a href="?page={{ customers.next_page_number }}&search={{ search }}&date_from={{ date_from }}&date_to={{ date_to }}&source={{ source }}&branch={{ branch_flt }}&sort={{ sort_by }}" class="btn-sm btn-outline">Next →</a>'''

PAGINATION_NEW = '''    <a href="?page={{ customers.previous_page_number }}&search={{ search }}&date_from={{ date_from }}&date_to={{ date_to }}&source={{ source }}&branch={{ branch_flt }}&staff={{ staff_flt }}&sort={{ sort_by }}" class="btn-sm btn-outline">← Prev</a>
    {% endif %}
    <span style="padding:.5rem 1rem;font-size:.85rem;color:#6b7280;">Page {{ customers.number }} of {{ customers.paginator.num_pages }}</span>
    {% if customers.has_next %}
    <a href="?page={{ customers.next_page_number }}&search={{ search }}&date_from={{ date_from }}&date_to={{ date_to }}&source={{ source }}&branch={{ branch_flt }}&staff={{ staff_flt }}&sort={{ sort_by }}" class="btn-sm btn-outline">Next →</a>'''


def main():
    print("-- Applying CRM Staff Filter --\n")

    patch("core/views.py", VIEW_OLD, VIEW_NEW, VIEW_MARKER,
          "views.py: customer_crm staff filter")
    patch("templates/customer_crm.html", FILTER_OLD, FILTER_NEW, TEMPLATE_MARKER,
          "customer_crm.html: Staff dropdown")
    patch("templates/customer_crm.html", BANNER_OLD, BANNER_NEW, BANNER_MARKER,
          "customer_crm.html: active-filter banner")
    patch("templates/customer_crm.html", PAGINATION_OLD, PAGINATION_NEW, PAGINATION_MARKER,
          "customer_crm.html: pagination links")

    print("\n-- Done --")
    print("Next steps:")
    print("  python manage.py check")
    print("  git add . && git commit -m 'Add staff filter to Customer CRM' && git push")


if __name__ == "__main__":
    main()
