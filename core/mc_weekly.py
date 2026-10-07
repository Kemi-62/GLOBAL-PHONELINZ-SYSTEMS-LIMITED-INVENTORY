"""MC_WEEKLY_SELFHEAL_V1

Shared logic for the MultiChoice weekly report: closing a week, carrying the
closing balance forward, and healing weeks that were left open or created with
the wrong opening balance. Used by the close command, the daily safety-net
command, and the sale-recording view.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from core.models import MultiChoiceWeeklyReport, MultiChoiceSale

ZERO = Decimal("0")


def current_week_start(today=None):
    """Monday of the current week, using the Lagos calendar date."""
    today = today or timezone.localdate()
    return today - timedelta(days=today.weekday())


def closing_of(report):
    """Closing balance of a report, falling back to opening + extra funds."""
    if report.closing_balance is not None:
        return report.closing_balance
    return report.opening_balance + report.additional_funds


def _week_sales(report):
    week_end = report.week_start_date + timedelta(days=7)
    return MultiChoiceSale.objects.filter(
        staff=report.staff, branch=report.branch,
        date__gte=report.week_start_date, date__lt=week_end,
        is_voided=False,
    )


def finalize_week(report):
    """Close one open weekly report (totals, commission, is_closed)."""
    report.total_subscriptions = (
        _week_sales(report).aggregate(t=Sum("amount"))["t"] or ZERO
    )
    if report.closing_balance is None:
        report.closing_balance = report.opening_balance + report.additional_funds
    report.calculate_commission()
    report.is_closed = True
    report.save()
    return report


def align_opening(report, expected, repair, log):
    """Check that `report` opens with `expected`. Only an OPEN report is ever
    rewritten, and only when repair=True. Returns 'ok', 'repaired' or 'mismatch'."""
    if report.opening_balance == expected:
        return "ok"
    if report.is_closed:
        log("  WARNING week %s is already closed and opens with %s, but the previous "
            "week closed at %s. Not touching a closed week." % (
                report.week_start_date, report.opening_balance, expected))
        return "mismatch"
    if not repair:
        log("  WARNING week %s opens with %s but the previous week closed at %s "
            "(run with --repair to fix)." % (
                report.week_start_date, report.opening_balance, expected))
        return "mismatch"

    old = report.opening_balance
    sales = list(_week_sales(report))
    report.opening_balance = expected
    report.closing_balance = (
        expected + report.additional_funds - sum((s.cost_price for s in sales), ZERO)
    )
    report.total_subscriptions = sum((s.amount for s in sales), ZERO)
    report.save()
    log("  REPAIRED week %s: opening %s -> %s, closing balance now %s" % (
        report.week_start_date, old, expected, report.closing_balance))
    return "repaired"


def ensure_next_week(closed_report, repair, log):
    """Make sure the week after `closed_report` exists and opens with its
    closing balance. Returns (next_report, 'created'|'ok'|'repaired'|'mismatch')."""
    carried = closing_of(closed_report)
    next_start = closed_report.week_start_date + timedelta(days=7)
    nxt = MultiChoiceWeeklyReport.objects.filter(
        staff=closed_report.staff, branch=closed_report.branch,
        week_start_date=next_start,
    ).order_by("-id").first()
    if nxt is None:
        nxt = MultiChoiceWeeklyReport.objects.create(
            staff=closed_report.staff, branch=closed_report.branch,
            week_start_date=next_start,
            opening_balance=carried, additional_funds=ZERO,
        )
        log("  CREATED week %s opening with %s" % (next_start, carried))
        return nxt, "created"
    return nxt, align_opening(nxt, carried, repair, log)


def heal_staff(staff, repair=False, log=print, today=None):
    """Bring one staff member's weekly reports up to date.

    1. Close every overdue open week, oldest first, carrying each closing
       balance into the following week.
    2. Make sure the current week exists and opens with the most recent
       closing balance.
    Returns a dict of counts: closed, created, repaired, mismatch.
    """
    stats = {"closed": 0, "created": 0, "repaired": 0, "mismatch": 0}
    cur_ws = current_week_start(today)
    base = MultiChoiceWeeklyReport.objects.filter(staff=staff, branch=staff.branch)

    while True:
        overdue = base.filter(
            is_closed=False, week_start_date__lt=cur_ws
        ).order_by("week_start_date").first()
        if overdue is None:
            break
        finalize_week(overdue)
        stats["closed"] += 1
        log("  CLOSED overdue week %s (closing balance %s)" % (
            overdue.week_start_date, overdue.closing_balance))
        _, result = ensure_next_week(overdue, repair, log)
        if result in stats:
            stats[result] += 1

    cur = base.filter(week_start_date=cur_ws).order_by("-id").first()
    prev = base.filter(week_start_date__lt=cur_ws).order_by("-week_start_date").first()
    expected = closing_of(prev) if prev is not None else ZERO

    if cur is None:
        MultiChoiceWeeklyReport.objects.create(
            staff=staff, branch=staff.branch, week_start_date=cur_ws,
            opening_balance=expected, additional_funds=ZERO,
        )
        stats["created"] += 1
        log("  CREATED current week %s opening with %s" % (cur_ws, expected))
    else:
        result = align_opening(cur, expected, repair, log)
        if result in stats:
            stats[result] += 1
    return stats
