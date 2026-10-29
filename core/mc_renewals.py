"""MC_RENEWALS_V1: who needs to renew their DStv / GOtv, with a one-tap WhatsApp reminder."""
from datetime import timedelta
from urllib.parse import quote

from django.shortcuts import render
from django.utils import timezone

from core import models as m
from core.utils.decorators import role_required

CYCLE_DAYS = 30        # one subscription month
DUE_SOON_DAYS = 5      # "due" bucket: expires within this many days
UPCOMING_DAYS = 10     # "coming up" bucket
LAPSED_AFTER = 30      # overdue longer than this = lapsed (win-back)
LOOKBACK_DAYS = 120


def wa_number(phone):
    """Nigerian number to international digits for wa.me, or None."""
    d = "".join(ch for ch in (phone or "") if ch.isdigit())
    if d.startswith("234") and len(d) == 13:
        return d
    if d.startswith("0") and len(d) == 11:
        return "234" + d[1:]
    if len(d) == 10:
        return "234" + d
    return None


def _message(row):
    s = row["sale"]
    svc = s.service_type
    when = row["expiry"].strftime("%d %b")
    if row["days_left"] < 0:
        status = "expired on %s" % when
    elif row["days_left"] == 0:
        status = "expires today"
    else:
        status = "expires on %s" % when
    iuc = (" (IUC %s)" % s.iuc_number.strip()) if s.iuc_number else ""
    return ("Hello %s, your %s %s subscription%s %s. "
            "Renew with Global Phonelinz Systems Limited to stay connected. Thank you!"
            % (s.customer_name.strip().title(), svc, s.package_type, iuc, status))


def due_rows(user, branch_id=None, today=None):
    """Latest paid subscription per customer, with its expiry. Voided sales are ignored,
    and a customer who has paid again since is not listed twice."""
    today = today or timezone.localdate()
    qs = (m.MultiChoiceSale.objects
          .filter(is_voided=False, date__gte=today - timedelta(days=LOOKBACK_DAYS))
          .select_related("staff", "branch").order_by("date", "time", "id"))
    role = getattr(user, "role", "")
    if role == "MULTICHOICE":
        qs = qs.filter(staff=user)
    elif role == "MANAGER":
        qs = qs.filter(branch_id=user.branch_id)
    elif branch_id:
        qs = qs.filter(branch_id=branch_id)
    latest = {}
    for s in qs:
        iuc = (s.iuc_number or "").strip().upper()
        if iuc:
            key = (s.service_type, iuc)
        else:
            num = wa_number(s.customer_phone)
            if not num:
                continue
            key = (s.service_type, num)
        latest[key] = s      # ordered ascending, so the last one wins
    rows = []
    for s in latest.values():
        expiry = s.date + timedelta(days=CYCLE_DAYS * max(1, getattr(s, 'months_paid', 1) or 1))  # MC_RENEWALS_V2
        days_left = (expiry - today).days
        row = {"sale": s, "expiry": expiry, "days_left": days_left, "days_over": -days_left}
        num = wa_number(s.customer_phone)
        row["phone"] = s.customer_phone or ""
        row["wa"] = ("https://wa.me/%s?text=%s" % (num, quote(_message(row)))) if num else ""
        rows.append(row)
    rows.sort(key=lambda r: r["expiry"])
    return rows


def bucket(rows):
    due, overdue, upcoming, lapsed = [], [], [], []
    for r in rows:
        d = r["days_left"]
        if d < -LAPSED_AFTER:
            lapsed.append(r)
        elif d < 0:
            overdue.append(r)
        elif d <= DUE_SOON_DAYS:
            due.append(r)
        elif d <= UPCOMING_DAYS:
            upcoming.append(r)
    return due, overdue, upcoming, lapsed


@role_required("MULTICHOICE", "MANAGER", "DIRECTOR", "SUB_DIRECTOR")
def mc_renewals(request):
    branch_id = request.GET.get("branch") or None
    rows = due_rows(request.user, branch_id)
    due, overdue, upcoming, lapsed = bucket(rows)
    can_filter = request.user.role in ("DIRECTOR", "SUB_DIRECTOR", "SUPERADMIN")
    return render(request, "multichoice_renewals.html", {
        "due": due, "overdue": overdue, "upcoming": upcoming, "lapsed": lapsed,
        "branches": m.Branch.objects.all() if can_filter else [],
        "branch_flt": branch_id or "",
        "show_staff": request.user.role != "MULTICHOICE",
        "due_soon_days": DUE_SOON_DAYS,
    })
