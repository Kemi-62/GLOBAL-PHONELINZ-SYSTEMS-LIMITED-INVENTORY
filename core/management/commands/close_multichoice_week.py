"""Close every MultiChoice staff member's current open weekly report and
immediately start next week's report with the closing balance carried
forward as the new opening balance. Runs automatically every Sunday at
10pm WAT -- see .github/workflows/mc_weekly_close.yml."""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from core.models import MultiChoiceWeeklyReport, MultiChoiceSale


class Command(BaseCommand):
    help = "Close all open MultiChoice weekly reports and auto-start next week."

    def handle(self, *args, **options):
        closed_count = 0
        open_reports = MultiChoiceWeeklyReport.objects.filter(is_closed=False)

        for report in open_reports:
            week_end = report.week_start_date + timedelta(days=7)
            week_total = MultiChoiceSale.objects.filter(
                staff=report.staff, branch=report.branch,
                date__gte=report.week_start_date, date__lt=week_end,
                is_voided=False,
            ).aggregate(t=Sum("amount"))["t"] or Decimal("0")
            report.total_subscriptions = week_total
            if report.closing_balance is None:
                report.closing_balance = report.opening_balance + report.additional_funds
            report.calculate_commission()
            report.is_closed = True
            report.save()
            closed_count += 1

            next_week_start = report.week_start_date + timedelta(days=7)
            MultiChoiceWeeklyReport.objects.get_or_create(
                staff=report.staff, branch=report.branch,
                week_start_date=next_week_start,
                defaults={
                    "opening_balance": report.closing_balance,
                    "additional_funds": Decimal("0"),
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f"Closed {closed_count} weekly report(s) and started next week for each."
        ))
