"""Management command: reset current-month KPIs.

Usage: python manage.py monthly_reset
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from core.models import MonthlyResetLog
from datetime import date

User = get_user_model()

class Command(BaseCommand):
    help = "Reset current-month KPIs. Archives the previous month data."

    def handle(self, *args, **options):
        today = date.today()
        user = User.objects.filter(role="SUPERADMIN").first()

        # Check if already reset this month
        if MonthlyResetLog.objects.filter(year=today.year, month=today.month).exists():
            self.stdout.write(self.style.WARNING(f"Month {today.year}-{today.month:02d} already reset."))
            return

        # Reset logic: nothing to delete — history stays in tables.
        # Dashboards just filter by current month by default.
        # This command records that the reset happened.
        log = MonthlyResetLog.objects.create(
            year=today.year,
            month=today.month,
            reset_by=user,
            notes=f"Monthly reset executed automatically on {today}. All historical data preserved.",
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Month {today.year}-{today.month:02d} reset logged. "
                "Dashboards will now show current-month data by default."
            )
        )
