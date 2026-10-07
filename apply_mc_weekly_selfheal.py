#!/usr/bin/env python3
"""
apply_mc_weekly_selfheal.py  --  GPSL ERP, Issue A fix
=======================================================
MultiChoice weekly close / reopen carry-forward, made self-healing.

WHAT IT FIXES
  1. ensure_multichoice_open_week used to carry the balance from the last
     CLOSED week and ignored any older week still left OPEN. Now it first
     closes every overdue open week (oldest first), carries each closing
     balance into the next week, and only then makes sure the current week
     exists with the right opening balance.
  2. record_multichoice_sale used to create a missing week with an opening
     balance of 0 and used the UTC date (wrong between 00:00-01:00 WAT on
     Mondays). It now uses the Lagos date and runs the same self-heal.
  3. The Sunday-close and daily safety-net GitHub workflows were missing
     from the repo. Both are added (they need ONE secret: CRON_KEY).

WHAT IT CREATES / CHANGES
  NEW   core/mc_weekly.py
  EDIT  core/management/commands/close_multichoice_week.py   (backup kept)
  EDIT  core/management/commands/ensure_multichoice_open_week.py (backup kept)
  EDIT  core/views.py  (record_multichoice_sale only; backup kept)
  NEW   .github/workflows/mc_weekly_close.yml
  NEW   .github/workflows/mc_ensure_open_week.yml
  No database migration. Safe to run more than once.

RUN (from the project root, next to manage.py):
    python apply_mc_weekly_selfheal.py

THEN CHECK YOUR REAL DATA WITHOUT CHANGING ANYTHING:
    python manage.py ensure_multichoice_open_week --dry-run
and, when the report looks right, fix a wrong current-week opening balance:
    python manage.py ensure_multichoice_open_week --repair
"""
import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARKER = "MC_WEEKLY_SELFHEAL_V1"

if not os.path.exists(os.path.join(BASE_DIR, "manage.py")):
    sys.exit("ERROR: run this from the project root (the folder that contains manage.py).")


# --------------------------------------------------------------------------
# File contents
# --------------------------------------------------------------------------

MC_WEEKLY_PY = r'''"""MC_WEEKLY_SELFHEAL_V1

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
'''


CLOSE_CMD_PY = r'''"""MC_WEEKLY_SELFHEAL_V1

Close every MultiChoice staff member's open weekly report and start the next
week with the closing balance carried forward as the new opening balance.
Runs every Sunday at 10pm WAT -- see .github/workflows/mc_weekly_close.yml.
Safe to run twice: already-closed weeks are skipped.

    python manage.py close_multichoice_week --dry-run   (preview, saves nothing)
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import MultiChoiceWeeklyReport
from core.mc_weekly import finalize_week, ensure_next_week, current_week_start


class Command(BaseCommand):
    help = "Close all open MultiChoice weekly reports and auto-start next week."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Show what would happen, then roll everything back.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        log = lambda msg: self.stdout.write(msg)
        closed_count = 0

        with transaction.atomic():
            # Never touch a FUTURE week: if this command runs twice on the same
            # Sunday, the week it just opened must stay open.
            open_reports = MultiChoiceWeeklyReport.objects.filter(
                is_closed=False, week_start_date__lte=current_week_start()
            ).select_related("staff", "branch").order_by("week_start_date", "id")

            for report in list(open_reports):
                log("%s / %s" % (report.staff.username, report.week_start_date))
                finalize_week(report)
                closed_count += 1
                log("  CLOSED week %s (closing balance %s)" % (
                    report.week_start_date, report.closing_balance))
                ensure_next_week(report, repair=False, log=log)

            if dry_run:
                transaction.set_rollback(True)

        prefix = "[DRY RUN - nothing saved] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            prefix + "Closed %d weekly report(s) and started next week for each." % closed_count
        ))
'''


ENSURE_CMD_PY = r'''"""MC_WEEKLY_SELFHEAL_V1

Self-healing safety net for MultiChoice weekly reports. Safe to run daily.

For every MultiChoice staff member it:
  1. closes any overdue OPEN week (oldest first) and carries each closing
     balance into the next week, then
  2. makes sure the current week exists and opens with the most recent
     closing balance.

    python manage.py ensure_multichoice_open_week              (normal run)
    python manage.py ensure_multichoice_open_week --dry-run    (preview only)
    python manage.py ensure_multichoice_open_week --repair     (also correct a
        wrong opening balance on the CURRENT open week; closed weeks are never
        rewritten)
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import User
from core.mc_weekly import heal_staff, current_week_start


class Command(BaseCommand):
    help = "Close overdue MultiChoice weeks and make sure the current week opens with the right balance."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Show what would happen, then roll everything back.")
        parser.add_argument("--repair", action="store_true",
                            help="Correct a wrong opening balance on the current open week.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        repair = options["repair"]
        log = lambda msg: self.stdout.write(msg)
        totals = {"closed": 0, "created": 0, "repaired": 0, "mismatch": 0}

        self.stdout.write("Current week starts %s" % current_week_start())

        with transaction.atomic():
            for staff in User.objects.filter(role="MULTICHOICE").select_related("branch"):
                if staff.branch_id is None:
                    log("%s: no branch set, skipped" % staff.username)
                    continue
                log("%s:" % staff.username)
                stats = heal_staff(staff, repair=repair, log=log)
                for key, value in stats.items():
                    totals[key] += value
                if not any(stats.values()):
                    log("  already correct")

            if dry_run:
                transaction.set_rollback(True)

        prefix = "[DRY RUN - nothing saved] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            prefix + "Closed %(closed)d overdue week(s), created %(created)d, "
            "repaired %(repaired)d, %(mismatch)d need attention." % totals
        ))
'''


WORKFLOW_CLOSE = r'''# MC_WEEKLY_SELFHEAL_V1
name: MultiChoice Weekly Close

on:
  schedule:
    # Sunday 21:00 UTC = Sunday 10:00 pm Lagos (WAT)
    - cron: '0 21 * * 0'
  workflow_dispatch:

jobs:
  close-week:
    runs-on: ubuntu-latest
    steps:
      - name: Wake Render app
        run: |
          curl -s --max-time 60 "https://app.globalphonelinz.com/system/keepalive/" || true
          sleep 15
      - name: Close MultiChoice week
        env:
          CRON_KEY: ${{ secrets.CRON_KEY }}
        run: |
          if [ -z "$CRON_KEY" ]; then
            echo "CRON_KEY secret is not set (GitHub repo > Settings > Secrets and variables > Actions)"
            exit 1
          fi
          curl -fsS --retry 3 --retry-delay 20 --retry-all-errors --max-time 120 \
            -H "X-Cron-Secret: $CRON_KEY" \
            "https://app.globalphonelinz.com/cron/close-multichoice-week/"
'''


WORKFLOW_ENSURE = r'''# MC_WEEKLY_SELFHEAL_V1
name: MultiChoice Ensure Open Week

on:
  schedule:
    # Daily 05:00 UTC = 6:00 am Lagos (WAT). Self-healing: if the Sunday close
    # was late or missed, this run closes the overdue week and carries its
    # balance into the new week.
    - cron: '0 5 * * *'
  workflow_dispatch:

jobs:
  ensure-open-week:
    runs-on: ubuntu-latest
    steps:
      - name: Wake Render app
        run: |
          curl -s --max-time 60 "https://app.globalphonelinz.com/system/keepalive/" || true
          sleep 15
      - name: Ensure open week
        env:
          CRON_KEY: ${{ secrets.CRON_KEY }}
        run: |
          if [ -z "$CRON_KEY" ]; then
            echo "CRON_KEY secret is not set (GitHub repo > Settings > Secrets and variables > Actions)"
            exit 1
          fi
          curl -fsS --retry 3 --retry-delay 20 --retry-all-errors --max-time 120 \
            -H "X-Cron-Secret: $CRON_KEY" \
            "https://app.globalphonelinz.com/cron/ensure-multichoice-open-week/"
'''


# views.py patch ------------------------------------------------------------
VIEWS_OLD = r'''        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())

        weekly_report = (
            MultiChoiceWeeklyReport.objects.filter(
                staff=request.user,
                branch=request.user.branch,
                week_start_date=week_start,
            )
            .order_by("-id")
            .first()
        )
        if weekly_report is None:
            weekly_report = MultiChoiceWeeklyReport.objects.create(
                staff=request.user,
                branch=request.user.branch,
                week_start_date=week_start,
                opening_balance=Decimal("0"),
                additional_funds=Decimal("0"),
            )
'''

VIEWS_NEW = r'''        # MC_WEEKLY_SELFHEAL_V1: Lagos date, and self-heal a missing week
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())

        weekly_report = (
            MultiChoiceWeeklyReport.objects.filter(
                staff=request.user,
                branch=request.user.branch,
                week_start_date=week_start,
            )
            .order_by("-id")
            .first()
        )
        if weekly_report is None:
            from core.mc_weekly import heal_staff
            heal_staff(request.user, log=lambda msg: None)
            weekly_report = (
                MultiChoiceWeeklyReport.objects.filter(
                    staff=request.user,
                    branch=request.user.branch,
                    week_start_date=week_start,
                )
                .order_by("-id")
                .first()
            )
        if weekly_report is None:
            weekly_report = MultiChoiceWeeklyReport.objects.create(
                staff=request.user,
                branch=request.user.branch,
                week_start_date=week_start,
                opening_balance=Decimal("0"),
                additional_funds=Decimal("0"),
            )
'''


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def read(rel):
    with open(os.path.join(BASE_DIR, rel), encoding="utf-8") as fh:
        return fh.read()


def write_file(rel, content):
    path = os.path.join(BASE_DIR, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def install_file(rel, content):
    """Create or replace a whole file. Skips when the marker is already there."""
    path = os.path.join(BASE_DIR, rel)
    if os.path.exists(path):
        if MARKER in read(rel):
            print("SKIP  %s: already applied" % rel)
            return
        backup = path + ".pre_selfheal.bak"
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
        write_file(rel, content)
        print("OK    %s: replaced (original saved as %s)" % (rel, os.path.basename(backup)))
    else:
        write_file(rel, content)
        print("OK    %s: created" % rel)


def patch_views():
    rel = "core/views.py"
    src = read(rel)
    if MARKER in src:
        print("SKIP  %s: already applied" % rel)
        return
    count = src.count(VIEWS_OLD)
    if count != 1:
        print("FAIL  %s: expected the old record_multichoice_sale block exactly once, "
              "found %d. The file has changed; nothing was edited there." % (rel, count))
        return False
    backup = os.path.join(BASE_DIR, rel + ".pre_selfheal.bak")
    if not os.path.exists(backup):
        shutil.copy2(os.path.join(BASE_DIR, rel), backup)
    write_file(rel, src.replace(VIEWS_OLD, VIEWS_NEW))
    print("OK    %s: record_multichoice_sale now uses the Lagos date and self-heals" % rel)
    return True


def main():
    print("GPSL - MultiChoice weekly self-heal (Issue A)")
    print("-" * 52)
    install_file("core/mc_weekly.py", MC_WEEKLY_PY)
    install_file("core/management/commands/close_multichoice_week.py", CLOSE_CMD_PY)
    install_file("core/management/commands/ensure_multichoice_open_week.py", ENSURE_CMD_PY)
    ok = patch_views()
    install_file(".github/workflows/mc_weekly_close.yml", WORKFLOW_CLOSE)
    install_file(".github/workflows/mc_ensure_open_week.yml", WORKFLOW_ENSURE)
    print("-" * 52)
    if ok is False:
        print("Finished with ONE failure (views.py). Send me the output above.")
        sys.exit(1)
    print("Done. Next steps:")
    print("  1. python manage.py ensure_multichoice_open_week --dry-run")
    print("  2. python manage.py ensure_multichoice_open_week --repair   (if it reports a mismatch)")
    print("  3. git add/commit/push, then add GitHub secret CRON_KEY")
    print("     (repo > Settings > Secrets and variables > Actions > New repository secret)")


if __name__ == "__main__":
    main()