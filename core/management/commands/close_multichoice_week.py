"""MC_WEEKLY_SELFHEAL_V1

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
