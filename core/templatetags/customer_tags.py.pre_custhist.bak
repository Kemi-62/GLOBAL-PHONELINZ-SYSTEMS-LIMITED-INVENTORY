from django import template
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


def get_my_customers_data(user, search="", month_str=""):
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
            "wa_message": quote(f"Hi {name}, thank you for shopping with us at GPSL! We wanted to check in and see how you're doing \u2014 let us know if there's anything you need. \U0001F60A"),
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
    return get_my_customers_data(user, search, month_str)
