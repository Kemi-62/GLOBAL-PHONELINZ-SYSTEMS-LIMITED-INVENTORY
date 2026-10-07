"""CUSTOMER_HISTORY_V1

Template tags for the staff "My Customers" tab. Customers are matched by real
phone number, and repeat customers are detected across the whole department.
"""
from datetime import date as _date, timedelta
from urllib.parse import quote, urlencode

from django import template

register = template.Library()


def _normalize_wa_number(phone):
    """Turn a Nigerian number, however typed, into the format wa.me needs."""
    from core.customer_history import phone_key, phone_digits
    key = phone_key(phone)
    if len(key) == 10:
        return "234" + key
    return phone_digits(phone)


def get_my_customers_data(user, search="", month_str=""):
    """A staff member's own customer list. Shared by the dashboard tab and
    the CSV export so the export always matches the screen. Customers are
    grouped by real phone number (0803.. and +234803.. are one customer) and
    flagged as repeat when they have 2+ purchases anywhere in the user's
    department (all staff), not just the ones this user handled."""
    from core.models import Customer
    from core.customer_history import (
        canonical_phone, customer_transactions, phone_counts, phone_key, scope_for_user,
    )

    departments, branch = scope_for_user(user)
    own_rows = customer_transactions(None, departments=departments, staff=user) if departments else []

    available_months = sorted({r["date"].replace(day=1) for r in own_rows if r["date"]}, reverse=True)

    month_filter_active = False
    if month_str:
        try:
            m_start = _date.fromisoformat(month_str)
            m_end = (m_start.replace(day=28) + timedelta(days=4)).replace(day=1)
            own_rows = [r for r in own_rows if r["date"] and m_start <= r["date"] < m_end]
            month_filter_active = True
        except ValueError:
            pass

    grouped = {}
    for r in own_rows:
        if r["key"]:
            grouped.setdefault(r["key"], []).append(r)

    dept_counts = phone_counts(departments, branch=branch) if departments else {}

    names = {}
    for c in Customer.objects.only("id", "name", "phone_number").order_by("-id"):
        key = phone_key(c.phone_number)
        if key and (c.name or "").strip() and c.name.strip().lower() != "unknown":
            names[key] = c.name.strip()

    needle = (search or "").strip().lower()
    customers = []
    for key, rows in grouped.items():
        rows = sorted(rows, key=lambda r: r["date"] or _date.min, reverse=True)
        name = names.get(key) or next((r["name"] for r in rows if r["name"]), "") or ""
        phone = canonical_phone(rows[0]["phone"])
        if not name:
            name = phone
        if needle and needle not in name.lower() and needle not in phone.lower() \
                and needle not in "".join(ch for ch in phone if ch.isdigit()):
            continue
        total_spent = float(sum((r["amount"] or 0 for r in rows), 0))
        last_dates = [r["date"] for r in rows if r["date"]]
        dept_count = dept_counts.get(key, len(rows))
        customers.append({
            "name": name,
            "phone": phone,
            "wa_number": _normalize_wa_number(phone),
            "total_spent": total_spent,
            "purchase_count": len(rows),
            "dept_purchase_count": dept_count,
            "is_repeat": dept_count >= 2,
            "last_purchase": max(last_dates) if last_dates else None,
            "history_query": urlencode({"phone": phone}),
            "wa_message": quote("Hi %s, thank you for shopping with us at GPSL! We wanted to check in and see how you're doing — let us know if there's anything you need. \U0001F60A" % name),
        })

    customers.sort(key=lambda c: c["last_purchase"] or _date.min, reverse=True)

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
    return get_my_customers_data(user, search, month_str)
