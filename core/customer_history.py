"""CUSTOMER_HISTORY_V1

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
