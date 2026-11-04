"""MC_COMMISSION_V2: real MultiChoice commission, found by comparing the real wallet balance
with the balance the system expects.

Each week, BEFORE the first sale, the MultiChoice staff member enters the real balance shown in the
MultiChoice app (with a screenshot). The system compares it with what it expected
(last week's closing + any top-ups). A higher real balance is commission (pending until the Director
confirms it); a lower one is a shortage. The week then opens with the REAL balance.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from core import models as m

TOLERANCE = Decimal("50")        # differences up to this (naira) count as a match
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _week_sales(report):
    return m.MultiChoiceSale.objects.filter(
        staff=report.staff, branch=report.branch,
        date__gte=report.week_start_date, date__lt=report.week_start_date + timedelta(days=7),
        is_voided=False,
    )


def needs_check(user, report):
    """True when the staff member must enter the real balance before recording sales."""
    if report is None or report.is_closed or getattr(user, "role", "") != "MULTICHOICE":
        return False
    if m.MultiChoiceBalanceCheck.objects.filter(weekly_report=report).exists():
        return False
    if _week_sales(report).exists():       # week already running (for example rollout day): no gate
        return False
    return True


def _notify_approvers(title, message):
    for u in m.User.objects.filter(role__in=("DIRECTOR", "SUB_DIRECTOR"), is_active=True):
        m.Notification.objects.create(recipient=u, notif_type="GENERAL", title=title,
                                      message=message, link="/director/mc-commission/")


def record_check(user, report, actual=None, screenshot=None, note="", skip_reason=""):
    """Save a week-start check. Returns the MultiChoiceBalanceCheck."""
    expected = report.opening_balance + report.additional_funds
    has_prev = m.MultiChoiceWeeklyReport.objects.filter(
        staff=report.staff, week_start_date__lt=report.week_start_date).exists()
    if skip_reason.strip():
        chk = m.MultiChoiceBalanceCheck.objects.create(
            staff=user, branch=report.branch, weekly_report=report, expected_balance=expected,
            status="SKIPPED", note=skip_reason.strip())
        _notify_approvers("MultiChoice balance check skipped",
                          "%s skipped the week-start balance check: %s" % (user.username, skip_reason.strip()))
        return chk
    actual = Decimal(actual)
    diff = actual - expected
    if not has_prev:
        status = "BASELINE"
    elif abs(diff) <= TOLERANCE:
        status = "MATCHED"
    elif diff > 0:
        status = "COMMISSION"
    else:
        status = "SHORTAGE"
    chk = m.MultiChoiceBalanceCheck.objects.create(
        staff=user, branch=report.branch, weekly_report=report, expected_balance=expected,
        actual_balance=actual, difference=diff, status=status, screenshot=screenshot, note=(note or "").strip())
    # the week opens with the REAL balance
    report.opening_balance = actual - report.additional_funds
    report.save(update_fields=["opening_balance"])
    if status == "COMMISSION":
        _notify_approvers("MultiChoice commission detected",
                          "%s: N%s more than expected in the wallet. Open MC Commission to confirm." % (user.username, "{:,.2f}".format(diff)))
    elif status == "SHORTAGE":
        _notify_approvers("MultiChoice balance SHORTAGE",
                          "%s: wallet is N%s lower than expected. Open MC Commission to review." % (user.username, "{:,.2f}".format(-diff)))
    return chk


def month_commission(user, today=None):
    """Confirmed commission for this staff member in the current month."""
    today = today or timezone.localdate()
    qs = m.MultiChoiceBalanceCheck.objects.filter(
        staff=user, status="COMMISSION_OK", checked_at__year=today.year, checked_at__month=today.month)
    return qs.aggregate(t=Sum("difference"))["t"] or Decimal("0")
