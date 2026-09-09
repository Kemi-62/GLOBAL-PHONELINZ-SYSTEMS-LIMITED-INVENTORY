"""Safety net: make sure every MultiChoice staff member has an open
weekly report for the current week. Idempotent -- safe to run daily."""
from datetime import timedelta, date as _date
from decimal import Decimal

from django.core.management.base import BaseCommand

from core.models import User, MultiChoiceWeeklyReport


class Command(BaseCommand):
    help = "Ensure every MultiChoice staff member has an open weekly report for the current week."

    def handle(self, *args, **options):
        today = _date.today()
        week_start = today - timedelta(days=today.weekday())
        created_count = 0

        for staff in User.objects.filter(role="MULTICHOICE"):
            existing = MultiChoiceWeeklyReport.objects.filter(
                staff=staff, branch=staff.branch, week_start_date=week_start
            ).first()
            if existing:
                continue

            last_closed = MultiChoiceWeeklyReport.objects.filter(
                staff=staff, branch=staff.branch, is_closed=True
            ).order_by("-week_start_date").first()
            opening_balance = (
                last_closed.closing_balance
                if last_closed and last_closed.closing_balance is not None
                else Decimal("0")
            )

            MultiChoiceWeeklyReport.objects.create(
                staff=staff, branch=staff.branch, week_start_date=week_start,
                opening_balance=opening_balance, additional_funds=Decimal("0"),
            )
            created_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Checked all MultiChoice staff -- created {created_count} new open week report(s)."
        ))
