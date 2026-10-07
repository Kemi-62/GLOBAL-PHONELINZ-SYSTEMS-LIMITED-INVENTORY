"""MC_WEEKLY_SELFHEAL_V1

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
