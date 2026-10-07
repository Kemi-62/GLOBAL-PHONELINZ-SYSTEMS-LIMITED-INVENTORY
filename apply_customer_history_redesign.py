#!/usr/bin/env python3
"""
apply_customer_history_redesign.py  --  GPSL ERP, Issue B fix
==============================================================
Customer history / CRM: blank page, missed repeat customers, department views.

WHAT WAS WRONG (confirmed from your code and your screenshot)
  1. /customer/<id>/history/ only looked at RETAIL sales. A MultiChoice or
     Telecom customer (e.g. Sunday Winbo) therefore always showed N0 and
     "No purchase history found".
  2. Worse, that page OVERWROTE the customer's stored purchase count and
     total spent with the retail-only numbers (zeros) every time it was opened.
  3. Phones were matched as exact text, so 07087094757, 7087094757 and
     +234 708 709 4757 counted as three different customers -- which is why a
     customer with two subscriptions was not seen as a repeat customer.
  4. Staff had no history page at all, and the CRM "Retail / MultiChoice /
     Telecom" badges never showed (the numbers behind them were never set).

WHAT THIS DOES
  * One shared phone matcher: any way of writing the same Nigerian number is
    the same customer.
  * DIRECTOR history: the full cross-department picture -- total spend,
    quantities, prices, every item/service, a per-department breakdown, and a
    separate box for the online-sales log (not added into totals, because it
    can duplicate a recorded sale). Opening it no longer changes any data.
  * STAFF history ("View History" in My Customers): only that customer's
    transactions in YOUR department at YOUR branch, from ALL staff, so a
    MultiChoice agent sees that a colleague already renewed them. Retail,
    MultiChoice and Telecom never see each other's departments. Managers see
    all three departments, for their own branch only.
  * Repeat-customer badge in My Customers (2+ purchases in your department).
  * New customers are filed under one record per real number.
  * New command to repair totals already zeroed:
        python manage.py recalculate_customer_stats            (preview)
        python manage.py recalculate_customer_stats --apply    (save)

CHANGES  (no database migration; safe to run more than once)
  NEW    core/customer_history.py, core/customer_views.py
  NEW    core/management/commands/recalculate_customer_stats.py
  NEW    templates/my_customer_history.html
  EDIT   templates/customer_history.html, templates/partials/my_customers.html,
         core/templatetags/customer_tags.py, core/urls.py, core/views.py
         (each original is saved next to it as *.pre_custhist.bak)

RUN from the project root (next to manage.py):
    python apply_customer_history_redesign.py
"""
import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARKER = "CUSTOMER_HISTORY_V1"

if not os.path.exists(os.path.join(BASE_DIR, "manage.py")):
    sys.exit("ERROR: run this from the project root (the folder that contains manage.py).")


# =========================================================================
# core/customer_history.py
# =========================================================================
CUSTOMER_HISTORY_PY = r'''"""CUSTOMER_HISTORY_V1

Shared customer-history logic: matching phone numbers whatever way they were
typed, and collecting every transaction a customer has made, per department.
"""
import re
from collections import Counter
from datetime import date as _date, datetime as _datetime, time as _time
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

ZERO = Decimal("0")

DEPT_RETAIL = "RETAIL"
DEPT_MULTICHOICE = "MULTICHOICE"
DEPT_TELECOM = "TELECOM"
DEPT_ONLINE = "ONLINE"

REAL_DEPARTMENTS = [DEPT_RETAIL, DEPT_MULTICHOICE, DEPT_TELECOM]
ALL_DEPARTMENTS = REAL_DEPARTMENTS + [DEPT_ONLINE]

DEPT_LABELS = {
    DEPT_RETAIL: "Retail",
    DEPT_MULTICHOICE: "MultiChoice",
    DEPT_TELECOM: "Telecom",
    DEPT_ONLINE: "Online sales log",
}

ROLE_DEPARTMENTS = {
    "RETAIL": DEPT_RETAIL,
    "MULTICHOICE": DEPT_MULTICHOICE,
    "TELECOM": DEPT_TELECOM,
}


# ---------------------------------------------------------------------------
# Phone numbers
# ---------------------------------------------------------------------------

def phone_digits(phone):
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


def phone_key(phone):
    """Identity of a phone number: its last 10 digits. 07087094757,
    7087094757, 2347087094757 and '+234 708 709 4757' all give 7087094757.
    Returns '' when there is nothing usable."""
    digits = phone_digits(phone)
    if len(digits) < 7:
        return ""
    return digits[-10:]


def canonical_phone(phone):
    """Standard stored form for Nigerian numbers: 0XXXXXXXXXX. Anything that
    isn't clearly a Nigerian number is returned as typed (trimmed)."""
    raw = str(phone or "").strip()
    digits = phone_digits(raw)
    key = phone_key(raw)
    if len(key) == 10 and (
        len(digits) == 10
        or (len(digits) == 11 and digits.startswith("0"))
        or (len(digits) == 13 and digits.startswith("234"))
    ):
        return "0" + key
    return raw


def phone_regex(phone):
    """Database regex that matches every way of writing this number."""
    key = phone_key(phone)
    if not key:
        return None
    body = r"\D*".join(re.escape(ch) for ch in key)
    if len(key) == 10:
        return r"^\D*(?:(?:00)?(?:234|0)\D*)?" + body + r"\D*$"
    return r"^\D*" + body + r"\D*$"


def phone_q(field, phone):
    pattern = phone_regex(phone)
    if pattern is None:
        return Q(pk__in=[])
    return Q(**{field + "__iregex": pattern})


def find_customer_by_phone(phone):
    """The existing Customer record for this number, in any written form."""
    from core.models import Customer
    if not phone_key(phone):
        return None
    return Customer.objects.filter(phone_q("phone_number", phone)).order_by("id").first()


# ---------------------------------------------------------------------------
# Who may see what
# ---------------------------------------------------------------------------

def scope_for_user(user):
    """(departments, branch) a user may see. Director sees everything.
    Manager sees all three departments at their branch. Staff see only their
    own department at their branch. An unassigned branch means no access."""
    role = getattr(user, "role", "")
    if getattr(user, "is_superuser", False) or role in ("DIRECTOR", "SUPERADMIN"):
        return list(REAL_DEPARTMENTS), None
    branch = getattr(user, "branch", None)
    if branch is None:
        return [], None
    if role == "MANAGER":
        return list(REAL_DEPARTMENTS), branch
    if role in ROLE_DEPARTMENTS:
        return [ROLE_DEPARTMENTS[role]], branch
    return [], None


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def _sources(dept):
    """[(kind, base queryset, phone field)] for one department."""
    from core import models as m
    if dept == DEPT_RETAIL:
        return [("retail", m.RetailSale.objects.filter(is_voided=False), "customer_phone")]
    if dept == DEPT_MULTICHOICE:
        return [
            ("mc_sub", m.MultiChoiceSale.objects.filter(is_voided=False), "customer_phone"),
            ("mc_hw", m.MultiChoiceHardwareSale.objects.all(), "customer_phone"),
        ]
    if dept == DEPT_TELECOM:
        return [
            ("service", m.ServiceActivity.objects.all(), "customer_phone"),
            ("router", m.RouterSubscription.objects.all(), "customer_phone"),
        ]
    if dept == DEPT_ONLINE:
        return [("online", m.OnlineSaleLog.objects.all(), "customer_phone")]
    return []


def _scope(qs, field, phone, branch, staff):
    qs = qs.exclude(**{field + "__isnull": True}).exclude(**{field: ""})
    if phone:
        qs = qs.filter(phone_q(field, phone))
    if branch is not None:
        qs = qs.filter(branch_id=getattr(branch, "pk", branch))
    if staff is not None:
        qs = qs.filter(staff_id=getattr(staff, "pk", staff))
    return qs


def _row(dept, kind, obj, when, at, item, detail, qty, unit, amount, phone, name, pending=False):
    return {
        "department": dept,
        "department_label": DEPT_LABELS[dept],
        "kind": kind,
        "date": when,
        "time": at,
        "item": item,
        "detail": detail,
        "quantity": qty,
        "unit_price": unit,
        "amount": amount,
        "branch": obj.branch.name if obj.branch_id else "",
        "branch_id": obj.branch_id,
        "staff": obj.staff.username if obj.staff_id else "",
        "staff_id": obj.staff_id,
        "phone": phone or "",
        "key": phone_key(phone),
        "name": (name or "").strip(),
        "pending": pending,
    }


def _per_unit(amount, qty):
    try:
        return (amount / qty) if qty else amount
    except Exception:
        return amount


def _map_row(dept, kind, s):
    from core import models as m
    if kind == "retail":
        item = s.product.model_name
        if s.color:
            item = "%s (%s)" % (item, s.color)
        return _row(dept, kind, s, s.date, s.time, item, s.get_payment_method_display(),
                    s.quantity, s.selling_price, s.quantity * s.selling_price,
                    s.customer_phone, "")
    if kind == "mc_sub":
        detail = s.get_transaction_type_display()
        if s.iuc_number:
            detail += " - IUC " + s.iuc_number
        return _row(dept, kind, s, s.date, s.time,
                    ("%s %s" % (s.service_type, s.package_type)).strip(), detail,
                    1, s.amount, s.amount, s.customer_phone, s.customer_name)
    if kind == "mc_hw":
        label = s.other_description if s.item_type == "OTHER" and s.other_description else s.get_item_type_display()
        return _row(dept, kind, s, s.date, s.time, "%s (hardware)" % label, s.notes or "",
                    s.quantity, _per_unit(s.amount, s.quantity), s.amount,
                    s.customer_phone, s.customer_name)
    if kind == "service":
        label = dict(m.ServiceActivity.SERVICE_CHOICES).get(s.service_type, s.service_type)
        return _row(dept, kind, s, s.date, s.time, label,
                    "" if s.approved else "Awaiting approval",
                    s.quantity, _per_unit(s.price, s.quantity), s.price,
                    s.customer_phone, s.customer_name, pending=not s.approved)
    if kind == "router":
        return _row(dept, kind, s, s.subscription_date, None,
                    "%s router subscription" % s.router_type,
                    "Month %s - router %s" % (s.month_number, s.router_number),
                    1, s.amount, s.amount, s.customer_phone, s.customer_name)
    # online
    return _row(dept, kind, s, s.sale_date, None, s.product_name,
                s.get_platform_display(), 1, s.amount, s.amount,
                s.customer_phone, s.customer_name)


def _select_related(kind):
    if kind == "retail":
        return ("product", "staff", "branch")
    return ("staff", "branch")


def customer_transactions(phone=None, departments=None, branch=None, staff=None):
    """Every transaction (newest first). phone=None means all customers."""
    depts = ALL_DEPARTMENTS if departments is None else departments
    rows = []
    for dept in depts:
        for kind, qs, field in _sources(dept):
            qs = _scope(qs, field, phone, branch, staff).select_related(*_select_related(kind))
            for obj in qs:
                rows.append(_map_row(dept, kind, obj))
    rows.sort(key=lambda r: (r["date"] or _date.min, r["time"] or _time.min), reverse=True)
    return rows


def phone_counts(departments, branch=None, staff=None):
    """Counter of phone_key -> number of transactions (cheap: phones only)."""
    counts = Counter()
    for dept in departments:
        for kind, qs, field in _sources(dept):
            for value in _scope(qs, field, None, branch, staff).values_list(field, flat=True):
                key = phone_key(value)
                if key:
                    counts[key] += 1
    return counts


def rows_by_key(rows):
    grouped = {}
    for r in rows:
        if r["key"]:
            grouped.setdefault(r["key"], []).append(r)
    return grouped


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------

def summarize(rows):
    """Totals for the real departments (the online log is shown separately
    and is never added in, because it can duplicate a recorded sale)."""
    rows = [r for r in rows if r["department"] != DEPT_ONLINE]
    total = sum((r["amount"] or ZERO for r in rows), ZERO)
    items = sum((r["quantity"] or 0 for r in rows), 0)
    dates = [r["date"] for r in rows if r["date"]]
    per_dept = []
    for dept in REAL_DEPARTMENTS:
        part = [r for r in rows if r["department"] == dept]
        if part:
            per_dept.append({
                "department": dept,
                "label": DEPT_LABELS[dept],
                "count": len(part),
                "items": sum((r["quantity"] or 0 for r in part), 0),
                "total": sum((r["amount"] or ZERO for r in part), ZERO),
            })
    return {
        "count": len(rows),
        "total_spent": total,
        "total_items": items,
        "last_date": max(dates) if dates else None,
        "departments": per_dept,
        "is_repeat": len(rows) >= 2,
    }


def last_purchase_datetime(rows):
    """Aware datetime of the most recent real transaction, or None."""
    best = None
    for r in rows:
        if r["department"] == DEPT_ONLINE or not r["date"]:
            continue
        stamp = (r["date"], r["time"] or _time.min)
        if best is None or stamp > best:
            best = stamp
    if best is None:
        return None
    return timezone.make_aware(_datetime.combine(best[0], best[1]))


# ---------------------------------------------------------------------------
# Director CRM list helpers
# ---------------------------------------------------------------------------

def filter_customers_by_source(customers, source):
    keys = set(phone_counts([source]))
    ids = [pk for pk, phone in customers.values_list("id", "phone_number") if phone_key(phone) in keys]
    return customers.filter(id__in=ids)


def filter_customers_by_staff(customers, staff_id):
    keys = set(phone_counts(REAL_DEPARTMENTS, staff=staff_id))
    ids = [pk for pk, phone in customers.values_list("id", "phone_number") if phone_key(phone) in keys]
    return customers.filter(id__in=ids)


def annotate_department_counts(customers):
    """Set retail_count / mc_count / telecom_count on each customer so the
    CRM list badges (which read these) actually show."""
    retail = phone_counts([DEPT_RETAIL])
    mc = phone_counts([DEPT_MULTICHOICE])
    telecom = phone_counts([DEPT_TELECOM])
    for c in customers:
        key = phone_key(c.phone_number)
        c.retail_count = retail.get(key, 0)
        c.mc_count = mc.get(key, 0)
        c.telecom_count = telecom.get(key, 0)
    return customers
'''


# =========================================================================
# core/customer_views.py
# =========================================================================
CUSTOMER_VIEWS_PY = r'''"""CUSTOMER_HISTORY_V1

Customer history pages: the Director's full cross-department view and the
staff department-scoped view.
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render

from core.models import Customer
from core.utils.decorators import role_required
from core.customer_history import (
    DEPT_LABELS, DEPT_ONLINE, REAL_DEPARTMENTS,
    canonical_phone, customer_transactions, find_customer_by_phone,
    phone_key, phone_q, scope_for_user, summarize,
)


def _display_name(customer, rows, phone):
    if customer is not None and (customer.name or "").strip() and customer.name.strip().lower() != "unknown":
        return customer.name.strip()
    for r in rows:
        if r["name"]:
            return r["name"]
    return canonical_phone(phone) or phone


@role_required("DIRECTOR")
def customer_history(request, customer_id):
    """Director: everything this customer has bought, across every department.
    Read-only -- opening this page never changes stored customer totals."""
    customer = get_object_or_404(Customer, id=customer_id)
    rows = customer_transactions(customer.phone_number, departments=REAL_DEPARTMENTS)
    online_rows = customer_transactions(customer.phone_number, departments=[DEPT_ONLINE])
    summary = summarize(rows)

    written_as = sorted({r["phone"] for r in rows + online_rows if r["phone"]})
    same_number_records = []
    if phone_key(customer.phone_number):
        same_number_records = list(
            Customer.objects.filter(phone_q("phone_number", customer.phone_number))
            .exclude(id=customer.id).select_related("branch")
        )

    return render(request, "customer_history.html", {
        "customer": customer,
        "display_name": _display_name(customer, rows, customer.phone_number),
        "rows": rows,
        "online_rows": online_rows,
        "summary": summary,
        "total_spent": summary["total_spent"],
        "total_items": summary["total_items"],
        "written_as": written_as if len(written_as) > 1 else [],
        "same_number_records": same_number_records,
    })


@login_required
def my_customer_history(request):
    """Staff/Manager: this customer's transactions in the viewer's own
    department(s) and branch, from ALL staff there (so a colleague's sale is
    visible). Never shows other departments or other branches."""
    departments, branch = scope_for_user(request.user)
    if not departments:
        return HttpResponseForbidden("You do not have permission to view customer history.")

    phone = request.GET.get("phone", "").strip()
    if not phone_key(phone):
        return render(request, "my_customer_history.html", {
            "missing_phone": True, "scope_label": "",
        })

    rows = customer_transactions(phone, departments=departments, branch=branch)
    customer = find_customer_by_phone(phone)
    summary = summarize(rows)
    for r in rows:
        r["mine"] = (r["staff_id"] == request.user.id)

    if branch is None:
        scope_label = "all departments, all branches"
    else:
        names = " + ".join(DEPT_LABELS[d] for d in departments)
        scope_label = "%s at %s" % (names, branch.name)

    return render(request, "my_customer_history.html", {
        "display_name": _display_name(customer, rows, phone),
        "phone": canonical_phone(phone),
        "rows": rows,
        "summary": summary,
        "scope_label": scope_label,
        "my_count": sum(1 for r in rows if r["mine"]),
        "colleague_count": sum(1 for r in rows if not r["mine"]),
        "missing_phone": False,
    })
'''


# =========================================================================
# management command
# =========================================================================
RECALC_CMD_PY = r'''"""CUSTOMER_HISTORY_V1

Repair stored customer totals (purchase count, total spent, last purchase)
from the real sales records. The old customer-history page overwrote these
with retail-only numbers; this puts the true company-wide figures back.

    python manage.py recalculate_customer_stats            (preview only)
    python manage.py recalculate_customer_stats --apply    (save changes)

Also lists CRM records that share the same real phone number.
"""
from django.core.management.base import BaseCommand

from core.models import Customer
from core.customer_history import (
    REAL_DEPARTMENTS, customer_transactions, last_purchase_datetime,
    phone_key, rows_by_key, summarize,
)


class Command(BaseCommand):
    help = "Recompute Customer.purchase_count / total_spent / last_purchase from real sales."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Save the corrected values (default is preview only).")

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        grouped = rows_by_key(customer_transactions(None, departments=REAL_DEPARTMENTS))
        by_key = {}
        changed = 0

        for customer in Customer.objects.all().order_by("id"):
            key = phone_key(customer.phone_number)
            by_key.setdefault(key, []).append(customer)
            rows = grouped.get(key, []) if key else []
            summary = summarize(rows)
            new_count = summary["count"]
            new_total = summary["total_spent"]
            new_last = last_purchase_datetime(rows)

            if (customer.purchase_count == new_count
                    and (customer.total_spent or 0) == new_total):
                continue
            changed += 1
            self.stdout.write("%s (%s): count %s -> %s, total %s -> %s" % (
                customer.name, customer.phone_number, customer.purchase_count, new_count,
                customer.total_spent, new_total))
            if apply_changes:
                customer.purchase_count = new_count
                customer.total_spent = new_total
                if new_last is not None:
                    customer.last_purchase = new_last
                customer.save(update_fields=["purchase_count", "total_spent", "last_purchase"])

        duplicates = {k: v for k, v in by_key.items() if k and len(v) > 1}
        for key, records in duplicates.items():
            self.stdout.write(self.style.WARNING(
                "SAME NUMBER, %d CRM records: %s" % (
                    len(records), ", ".join("#%s %s (%s)" % (c.id, c.name, c.phone_number) for c in records))))

        label = "Saved" if apply_changes else "[PREVIEW - nothing saved] Would fix"
        self.stdout.write(self.style.SUCCESS(
            "%s %d customer record(s); %d number(s) have duplicate CRM records." % (
                label, changed, len(duplicates))))
        if not apply_changes and changed:
            self.stdout.write("Run again with --apply to save.")
'''


# =========================================================================
# core/templatetags/customer_tags.py  (whole file)
# =========================================================================
CUSTOMER_TAGS_PY = r'''"""CUSTOMER_HISTORY_V1

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
'''


# =========================================================================
# templates
# =========================================================================
MY_CUSTOMERS_PARTIAL = r'''{# CUSTOMER_HISTORY_V1 #}
<div class="card">
  <p class="card-title">👥 My Customers</p>
  <p style="font-size:.8rem;color:#6b7280;margin:-.5rem 0 1rem;">Customers you've personally sold to — separate from company-wide records. Tap <strong>History</strong> to see everything bought in your department, including by colleagues.</p>

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
    <a href="{% url 'export_my_customers_csv' %}?cust_search={{ cust_search }}&cust_month={{ cust_month }}" class="btn-sm btn-outline">⬇️ Export CSV</a>
  </form>

  {% if month_filter_active %}
  <p style="font-size:.78rem;color:#004F9F;background:#eff6ff;padding:.5rem .8rem;border-radius:6px;margin-bottom:1rem;">
    Showing {{ total_customers_count }} customer(s) you sold to that month — good list for a month-end thank-you message.
  </p>
  {% endif %}

  <div style="overflow-x:auto;">
    <table class="data-table">
      <thead><tr><th>Customer</th><th>Phone</th><th style="text-align:center;">Purchases</th><th style="text-align:right;">Total Spent</th><th>Last Purchase</th><th></th></tr></thead>
      <tbody>
        {% for c in my_customers %}
        <tr>
          <td><strong>{{ c.name }}</strong>
            {% if c.is_repeat %}<span title="{{ c.dept_purchase_count }} purchases in your department" style="margin-left:.35rem;background:#ede9fe;color:#6d28d9;border-radius:999px;padding:.1rem .5rem;font-size:.68rem;font-weight:700;white-space:nowrap;">🔁 Repeat ×{{ c.dept_purchase_count }}</span>{% endif %}
          </td>
          <td style="font-size:.82rem;color:#6b7280;">{{ c.phone }}</td>
          <td style="text-align:center;">{{ c.purchase_count }}</td>
          <td style="text-align:right;">₦{{ c.total_spent|floatformat:0 }}</td>
          <td style="font-size:.8rem;color:#6b7280;">{{ c.last_purchase|date:"d M Y"|default:"—" }}</td>
          <td style="white-space:nowrap;">
            <a href="{% url 'my_customer_history' %}?{{ c.history_query }}" class="btn-sm btn-outline" style="padding:.35rem .7rem;font-size:.78rem;">📜 History</a>
            {% if c.wa_number %}
            <a href="https://wa.me/{{ c.wa_number }}?text={{ c.wa_message }}" target="_blank" class="btn-sm" style="background:#25D366;color:#fff;text-decoration:none;padding:.35rem .7rem;font-size:.78rem;">💬 Message</a>
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


DIRECTOR_HISTORY_HTML = r'''{# CUSTOMER_HISTORY_V1 #}{% extends "base.html" %}
{% block content %}
<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.8rem;margin-bottom:1.5rem;">
  <h1 style="font-size:1.3rem;font-weight:700;color:#004F9F;margin:0;">👤 {{ display_name }}
    {% if summary.is_repeat %}<span style="margin-left:.4rem;background:#ede9fe;color:#6d28d9;border-radius:999px;padding:.15rem .6rem;font-size:.72rem;font-weight:700;vertical-align:middle;">🔁 Repeat customer</span>{% endif %}
  </h1>
  <a href="{% url 'customer_crm' %}" style="padding:.45rem .9rem;font-size:.82rem;border-radius:6px;border:1px solid #d1d5db;color:#374151;text-decoration:none;background:#fff;">← Back to CRM</a>
</div>

{% if same_number_records %}
<div style="background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;padding:.7rem 1rem;margin-bottom:1rem;font-size:.82rem;color:#92400e;">
  ⚠️ The CRM has another record for this same phone number:
  {% for c in same_number_records %}<strong>{{ c.name }}</strong> ({{ c.phone_number }}){% if not forloop.last %}, {% endif %}{% endfor %}.
  Their purchases are combined below.
</div>
{% endif %}

<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem;margin-bottom:1.2rem;">
  <div style="background:#fff;border-radius:10px;border:1px solid #e5e7eb;padding:1rem 1.2rem;border-left:4px solid #10b981;">
    <p style="font-size:.72rem;text-transform:uppercase;color:#6b7280;margin:0 0 .3rem;">Total Spent (all departments)</p>
    <p style="font-size:1.4rem;font-weight:700;margin:0;">₦{{ total_spent|floatformat:0 }}</p>
  </div>
  <div style="background:#fff;border-radius:10px;border:1px solid #e5e7eb;padding:1rem 1.2rem;border-left:4px solid #3b82f6;">
    <p style="font-size:.72rem;text-transform:uppercase;color:#6b7280;margin:0 0 .3rem;">Transactions / Items</p>
    <p style="font-size:1.4rem;font-weight:700;margin:0;">{{ summary.count }} <span style="font-size:.9rem;color:#6b7280;font-weight:500;">/ {{ total_items }}</span></p>
  </div>
  <div style="background:#fff;border-radius:10px;border:1px solid #e5e7eb;padding:1rem 1.2rem;border-left:4px solid #f59e0b;">
    <p style="font-size:.72rem;text-transform:uppercase;color:#6b7280;margin:0 0 .3rem;">Phone</p>
    <p style="font-size:1rem;font-weight:700;margin:0;">{{ customer.phone_number|default:"—" }}</p>
    {% if written_as %}<p style="font-size:.7rem;color:#9ca3af;margin:.3rem 0 0;">Also typed as: {{ written_as|join:", " }}</p>{% endif %}
  </div>
  <div style="background:#fff;border-radius:10px;border:1px solid #e5e7eb;padding:1rem 1.2rem;border-left:4px solid #8b5cf6;">
    <p style="font-size:.72rem;text-transform:uppercase;color:#6b7280;margin:0 0 .3rem;">Last Purchase</p>
    <p style="font-size:1rem;font-weight:700;margin:0;">{{ summary.last_date|date:"d M Y"|default:"—" }}</p>
  </div>
</div>

{% if summary.departments %}
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:1.2rem;">
  {% for d in summary.departments %}
  <div style="background:#fff;border-radius:10px;border:1px solid #e5e7eb;padding:.9rem 1.1rem;">
    <p style="font-size:.78rem;font-weight:700;color:#004F9F;margin:0 0 .4rem;">{% if d.department == "RETAIL" %}🛍️{% elif d.department == "MULTICHOICE" %}📺{% else %}📡{% endif %} {{ d.label }}</p>
    <p style="font-size:1.15rem;font-weight:700;margin:0;">₦{{ d.total|floatformat:0 }}</p>
    <p style="font-size:.75rem;color:#6b7280;margin:.2rem 0 0;">{{ d.count }} transaction{{ d.count|pluralize }} · {{ d.items }} item{{ d.items|pluralize }}</p>
  </div>
  {% endfor %}
</div>
{% endif %}

<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:1.2rem 1.4rem;margin-bottom:1.2rem;">
  <p style="font-size:1rem;font-weight:700;color:#111827;margin:0 0 1rem;">Purchase History</p>
  <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;font-size:.85rem;">
      <thead><tr style="background:#f9fafb;">
        <th style="padding:.65rem .9rem;text-align:left;border-bottom:1px solid #e5e7eb;font-weight:600;color:#374151;">Date</th>
        <th style="padding:.65rem .9rem;text-align:left;border-bottom:1px solid #e5e7eb;font-weight:600;color:#374151;">Dept</th>
        <th style="padding:.65rem .9rem;text-align:left;border-bottom:1px solid #e5e7eb;font-weight:600;color:#374151;">Item / Service</th>
        <th style="padding:.65rem .9rem;text-align:center;border-bottom:1px solid #e5e7eb;font-weight:600;color:#374151;">Qty</th>
        <th style="padding:.65rem .9rem;text-align:right;border-bottom:1px solid #e5e7eb;font-weight:600;color:#374151;">Unit Price</th>
        <th style="padding:.65rem .9rem;text-align:right;border-bottom:1px solid #e5e7eb;font-weight:600;color:#374151;">Amount</th>
        <th style="padding:.65rem .9rem;text-align:left;border-bottom:1px solid #e5e7eb;font-weight:600;color:#374151;">Branch</th>
        <th style="padding:.65rem .9rem;text-align:left;border-bottom:1px solid #e5e7eb;font-weight:600;color:#374151;">Staff</th>
      </tr></thead>
      <tbody>
        {% for r in rows %}
        <tr style="border-bottom:1px solid #f3f4f6;">
          <td style="padding:.6rem .9rem;color:#9ca3af;white-space:nowrap;">{{ r.date|date:"d M Y" }}</td>
          <td style="padding:.6rem .9rem;"><span style="background:{% if r.department == 'RETAIL' %}#dcfce7;color:#166534{% elif r.department == 'MULTICHOICE' %}#ede9fe;color:#5b21b6{% else %}#dbeafe;color:#1e40af{% endif %};border-radius:999px;padding:.1rem .55rem;font-size:.7rem;font-weight:700;">{{ r.department_label }}</span></td>
          <td style="padding:.6rem .9rem;"><strong>{{ r.item }}</strong>{% if r.detail %}<br><span style="font-size:.72rem;color:#9ca3af;">{{ r.detail }}</span>{% endif %}</td>
          <td style="padding:.6rem .9rem;text-align:center;">{{ r.quantity }}</td>
          <td style="padding:.6rem .9rem;text-align:right;">₦{{ r.unit_price|floatformat:0 }}</td>
          <td style="padding:.6rem .9rem;text-align:right;font-weight:600;">₦{{ r.amount|floatformat:0 }}</td>
          <td style="padding:.6rem .9rem;color:#9ca3af;">{{ r.branch }}</td>
          <td style="padding:.6rem .9rem;">{{ r.staff }}</td>
        </tr>
        {% empty %}
        <tr><td colspan="8" style="text-align:center;color:#9ca3af;padding:2rem 0;">No purchases recorded for this phone number in Retail, MultiChoice or Telecom.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>

{% if online_rows %}
<div style="background:#fff;border:1px dashed #d1d5db;border-radius:10px;padding:1.2rem 1.4rem;">
  <p style="font-size:.95rem;font-weight:700;color:#111827;margin:0 0 .3rem;">Online sales log</p>
  <p style="font-size:.76rem;color:#6b7280;margin:0 0 .8rem;">Logged WhatsApp/Instagram/Facebook sales for this number. Not included in the totals above, because a logged sale may also have been entered as a normal sale.</p>
  <table style="width:100%;border-collapse:collapse;font-size:.83rem;">
    <tbody>
      {% for r in online_rows %}
      <tr style="border-bottom:1px solid #f3f4f6;">
        <td style="padding:.5rem .7rem;color:#9ca3af;white-space:nowrap;">{{ r.date|date:"d M Y" }}</td>
        <td style="padding:.5rem .7rem;"><strong>{{ r.item }}</strong> <span style="font-size:.72rem;color:#9ca3af;">via {{ r.detail }}</span></td>
        <td style="padding:.5rem .7rem;text-align:right;">₦{{ r.amount|floatformat:0 }}</td>
        <td style="padding:.5rem .7rem;color:#9ca3af;">{{ r.branch }}</td>
        <td style="padding:.5rem .7rem;">{{ r.staff }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}
{% endblock %}
'''


STAFF_HISTORY_HTML = r'''{# CUSTOMER_HISTORY_V1 #}{% extends "base.html" %}
{% block content %}
{% if missing_phone %}
<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:2rem;text-align:center;color:#6b7280;">
  No phone number was given, so there is no history to show.
  <p style="margin:1rem 0 0;"><a href="javascript:history.back()" style="color:#004F9F;">← Go back</a></p>
</div>
{% else %}
<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.8rem;margin-bottom:1rem;">
  <h1 style="font-size:1.3rem;font-weight:700;color:#004F9F;margin:0;">👤 {{ display_name }}
    {% if summary.is_repeat %}<span style="margin-left:.4rem;background:#ede9fe;color:#6d28d9;border-radius:999px;padding:.15rem .6rem;font-size:.72rem;font-weight:700;vertical-align:middle;">🔁 Repeat customer</span>{% endif %}
  </h1>
  <a href="javascript:history.back()" style="padding:.45rem .9rem;font-size:.82rem;border-radius:6px;border:1px solid #d1d5db;color:#374151;text-decoration:none;background:#fff;">← Back</a>
</div>
<p style="font-size:.8rem;color:#6b7280;margin:0 0 1rem;">{{ phone }} · Showing: <strong>{{ scope_label }}</strong> (all staff)</p>

<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem;margin-bottom:1.2rem;">
  <div style="background:#fff;border-radius:10px;border:1px solid #e5e7eb;padding:1rem 1.2rem;border-left:4px solid #10b981;">
    <p style="font-size:.72rem;text-transform:uppercase;color:#6b7280;margin:0 0 .3rem;">Total Spent</p>
    <p style="font-size:1.4rem;font-weight:700;margin:0;">₦{{ summary.total_spent|floatformat:0 }}</p>
  </div>
  <div style="background:#fff;border-radius:10px;border:1px solid #e5e7eb;padding:1rem 1.2rem;border-left:4px solid #3b82f6;">
    <p style="font-size:.72rem;text-transform:uppercase;color:#6b7280;margin:0 0 .3rem;">Transactions</p>
    <p style="font-size:1.4rem;font-weight:700;margin:0;">{{ summary.count }}</p>
    <p style="font-size:.72rem;color:#6b7280;margin:.2rem 0 0;">{{ my_count }} by you · {{ colleague_count }} by colleagues</p>
  </div>
  <div style="background:#fff;border-radius:10px;border:1px solid #e5e7eb;padding:1rem 1.2rem;border-left:4px solid #8b5cf6;">
    <p style="font-size:.72rem;text-transform:uppercase;color:#6b7280;margin:0 0 .3rem;">Last Purchase</p>
    <p style="font-size:1rem;font-weight:700;margin:0;">{{ summary.last_date|date:"d M Y"|default:"—" }}</p>
  </div>
</div>

<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:1.2rem 1.4rem;">
  <p style="font-size:1rem;font-weight:700;color:#111827;margin:0 0 1rem;">Purchase History</p>
  <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;font-size:.85rem;">
      <thead><tr style="background:#f9fafb;">
        <th style="padding:.65rem .9rem;text-align:left;border-bottom:1px solid #e5e7eb;font-weight:600;color:#374151;">Date</th>
        <th style="padding:.65rem .9rem;text-align:left;border-bottom:1px solid #e5e7eb;font-weight:600;color:#374151;">Item / Service</th>
        <th style="padding:.65rem .9rem;text-align:center;border-bottom:1px solid #e5e7eb;font-weight:600;color:#374151;">Qty</th>
        <th style="padding:.65rem .9rem;text-align:right;border-bottom:1px solid #e5e7eb;font-weight:600;color:#374151;">Unit Price</th>
        <th style="padding:.65rem .9rem;text-align:right;border-bottom:1px solid #e5e7eb;font-weight:600;color:#374151;">Amount</th>
        <th style="padding:.65rem .9rem;text-align:left;border-bottom:1px solid #e5e7eb;font-weight:600;color:#374151;">Handled by</th>
      </tr></thead>
      <tbody>
        {% for r in rows %}
        <tr style="border-bottom:1px solid #f3f4f6;">
          <td style="padding:.6rem .9rem;color:#9ca3af;white-space:nowrap;">{{ r.date|date:"d M Y" }}</td>
          <td style="padding:.6rem .9rem;"><strong>{{ r.item }}</strong>{% if r.detail %}<br><span style="font-size:.72rem;color:#9ca3af;">{{ r.detail }}</span>{% endif %}
            {% if summary.departments|length > 1 %}<br><span style="font-size:.7rem;color:#6d28d9;">{{ r.department_label }}</span>{% endif %}</td>
          <td style="padding:.6rem .9rem;text-align:center;">{{ r.quantity }}</td>
          <td style="padding:.6rem .9rem;text-align:right;">₦{{ r.unit_price|floatformat:0 }}</td>
          <td style="padding:.6rem .9rem;text-align:right;font-weight:600;">₦{{ r.amount|floatformat:0 }}</td>
          <td style="padding:.6rem .9rem;">{% if r.mine %}<strong>You</strong>{% else %}{{ r.staff }}{% endif %}
            {% if r.branch %}<br><span style="font-size:.7rem;color:#9ca3af;">{{ r.branch }}</span>{% endif %}</td>
        </tr>
        {% empty %}
        <tr><td colspan="6" style="text-align:center;color:#9ca3af;padding:2rem 0;">No purchases by this customer in {{ scope_label }}.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endif %}
{% endblock %}
'''


# =========================================================================
# views.py patches
# =========================================================================
UPSERT_OLD = r'''    phone = phone.strip()
    try:
        customer, created = Customer.objects.get_or_create(
            phone_number=phone,
'''
UPSERT_NEW = r'''    phone = phone.strip()
    try:
        # CUSTOMER_HISTORY_V1: one customer per real phone number, however it was typed
        from core.customer_history import find_customer_by_phone, canonical_phone
        _existing = find_customer_by_phone(phone)
        phone = _existing.phone_number if _existing is not None else (canonical_phone(phone) or phone)
        customer, created = Customer.objects.get_or_create(
            phone_number=phone,
'''

CRM_NEW = r'''    # CUSTOMER_HISTORY_V1: match phones by real number (0803.. = +234803..), not exact text
    from core.customer_history import (
        filter_customers_by_source, filter_customers_by_staff, annotate_department_counts,
    )
    if source in ("RETAIL", "MULTICHOICE", "TELECOM"):
        customers = filter_customers_by_source(customers, source)
    if staff_flt:
        customers = filter_customers_by_staff(customers, staff_flt)

    paginator = Paginator(customers, 30)
    page = paginator.get_page(request.GET.get("page"))
    annotate_department_counts(page)
'''

URLS_OLD = "    path('customer/<int:customer_id>/history/', views.customer_history, name='customer_history'),\n"
URLS_NEW = (
    "    path('customer/<int:customer_id>/history/', customer_views.customer_history, name='customer_history'),  # CUSTOMER_HISTORY_V1\n"
    "    path('my-customers/history/', customer_views.my_customer_history, name='my_customer_history'),\n"
)
URLS_IMPORT_OLD = "from . import views\n"
URLS_IMPORT_NEW = "from . import views\nfrom . import customer_views  # CUSTOMER_HISTORY_V1\n"


# =========================================================================
# Helpers
# =========================================================================

def read(rel):
    with open(os.path.join(BASE_DIR, rel), encoding="utf-8") as fh:
        return fh.read()


def write_file(rel, content):
    path = os.path.join(BASE_DIR, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def backup(rel):
    path = os.path.join(BASE_DIR, rel)
    bak = path + ".pre_custhist.bak"
    if os.path.exists(path) and not os.path.exists(bak):
        shutil.copy2(path, bak)


def install_file(rel, content):
    """Create or fully replace a file; skip if already applied."""
    path = os.path.join(BASE_DIR, rel)
    if os.path.exists(path):
        if MARKER in read(rel):
            print("SKIP  %s: already applied" % rel)
            return True
        backup(rel)
        write_file(rel, content)
        print("OK    %s: replaced (original kept as %s.pre_custhist.bak)" % (rel, os.path.basename(rel)))
    else:
        write_file(rel, content)
        print("OK    %s: created" % rel)
    return True


def patch_urls():
    rel = "core/urls.py"
    src = read(rel)
    if MARKER in src:
        print("SKIP  %s: already applied" % rel)
        return True
    if src.count(URLS_OLD) != 1 or src.count(URLS_IMPORT_OLD) < 1:
        print("FAIL  %s: customer_history route not found exactly once; nothing edited." % rel)
        return False
    backup(rel)
    src = src.replace(URLS_IMPORT_OLD, URLS_IMPORT_NEW, 1)
    src = src.replace(URLS_OLD, URLS_NEW, 1)
    write_file(rel, src)
    print("OK    %s: customer history routes updated" % rel)
    return True


def patch_views():
    rel = "core/views.py"
    src = read(rel)
    if MARKER in src:
        print("SKIP  %s: already applied" % rel)
        return True

    if src.count(UPSERT_OLD) != 1:
        print("FAIL  %s: _upsert_customer block not found exactly once; nothing edited." % rel)
        return False
    src = src.replace(UPSERT_OLD, UPSERT_NEW, 1)

    lines = src.splitlines(keepends=True)
    start = end = None
    in_crm = False
    for i, line in enumerate(lines):
        if line.startswith("def customer_crm("):
            in_crm = True
        elif in_crm and line.startswith("def "):
            break
        if in_crm and start is None and line.startswith("    # Filter by source"):
            start = i
        if in_crm and start is not None and line.startswith('    page = paginator.get_page(request.GET.get("page"))'):
            end = i + 1
            break
    if start is None or end is None:
        print("FAIL  %s: customer_crm filter block not found; nothing edited." % rel)
        return False
    block = "".join(lines[start:end])
    for needle in ('source == "RETAIL"', "staff_phones", "Paginator(customers, 30)"):
        if needle not in block:
            print("FAIL  %s: customer_crm block looks different (%s missing); nothing edited." % (rel, needle))
            return False
    lines[start:end] = [CRM_NEW]
    backup(rel)
    write_file(rel, "".join(lines))
    print("OK    %s: _upsert_customer and customer_crm now match phones by real number" % rel)
    return True


def main():
    print("GPSL - customer history redesign (Issue B)")
    print("-" * 56)
    ok = True
    install_file("core/customer_history.py", CUSTOMER_HISTORY_PY)
    install_file("core/customer_views.py", CUSTOMER_VIEWS_PY)
    install_file("core/management/commands/recalculate_customer_stats.py", RECALC_CMD_PY)
    install_file("core/templatetags/customer_tags.py", CUSTOMER_TAGS_PY)
    install_file("templates/partials/my_customers.html", MY_CUSTOMERS_PARTIAL)
    install_file("templates/customer_history.html", DIRECTOR_HISTORY_HTML)
    install_file("templates/my_customer_history.html", STAFF_HISTORY_HTML)
    ok = patch_views() and ok
    ok = patch_urls() and ok
    print("-" * 56)
    if not ok:
        print("Finished with a failure above. Nothing was half-edited in that file; send me the output.")
        sys.exit(1)
    print("Done. Next steps:")
    print("  1. python manage.py recalculate_customer_stats            (preview the repair)")
    print("  2. python manage.py recalculate_customer_stats --apply    (save it)")
    print("  3. Restart the app, open Customer CRM -> View History.")


if __name__ == "__main__":
    main()