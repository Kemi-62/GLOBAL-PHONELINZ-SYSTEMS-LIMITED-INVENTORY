"""Management command: send stock reorder alerts via email.
Covers: Branch Safe Stock, Retail Staff Stock, Telecom Staff Stock (wholesale devices),
and MultiChoice low balance.

Usage: python manage.py stock_alert_email --email=director@company.com
"""
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from core.models import (
    BranchSafeStock, StaffStock, WholesaleDevice,
    MultiChoiceWeeklyReport, MultiChoiceBalance,
)

LOW_STOCK_THRESHOLD = 1       # branch/staff/device stock
MULTICHOICE_LOW_BALANCE = 5000  # naira


class Command(BaseCommand):
    help = "Send stock and balance reorder alert emails to director."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Email address to send alerts to")

    def handle(self, *args, **options):
        email = options["email"]
        sections = []

        # ── 1. Branch Safe Stock ──
        branch_low = BranchSafeStock.objects.filter(
            quantity__lte=LOW_STOCK_THRESHOLD
        ).select_related("product", "branch")

        if branch_low.exists():
            lines = []
            for item in branch_low:
                status = "OUT OF STOCK" if item.quantity == 0 else "LOW STOCK"
                lines.append(
                    f"  - [{status}] {item.product.model_name} @ {item.branch.name} (Branch Safe): "
                    f"{item.quantity} remaining"
                )
            sections.append("BRANCH SAFE STOCK\n" + "\n".join(lines))

        # ── 2. Retail Staff Stock ──
        staff_low = StaffStock.objects.filter(
            quantity__lte=LOW_STOCK_THRESHOLD,
            staff__role="RETAIL",
        ).select_related("product", "staff", "staff__branch")

        if staff_low.exists():
            lines = []
            for item in staff_low:
                status = "OUT OF STOCK" if item.quantity == 0 else "LOW STOCK"
                branch_name = item.staff.branch.name if item.staff.branch else "No branch"
                lines.append(
                    f"  - [{status}] {item.product.model_name} — {item.staff.username} "
                    f"({branch_name}, Retail): {item.quantity} remaining"
                )
            sections.append("RETAIL STAFF STOCK\n" + "\n".join(lines))

        # ── 3. Telecom Wholesale Device Stock ──
        try:
            device_low = WholesaleDevice.objects.filter(
                quantity__lte=LOW_STOCK_THRESHOLD
            ).select_related("staff", "branch")

            if device_low.exists():
                lines = []
                for item in device_low:
                    status = "OUT OF STOCK" if item.quantity == 0 else "LOW STOCK"
                    lines.append(
                        f"  - [{status}] {item.product_name} ({item.network_type}) — "
                        f"{item.staff.username} ({item.branch.name}, Telecom): "
                        f"{item.quantity} remaining"
                    )
                sections.append("TELECOM DEVICE STOCK\n" + "\n".join(lines))
        except Exception:
            pass

        # ── 4. MultiChoice Low Balance ──
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())

        open_reports = MultiChoiceWeeklyReport.objects.filter(
            is_closed=False,
            week_start_date__gte=week_start,
        ).select_related("staff", "branch")

        mc_lines = []
        for report in open_reports:
            last_balance = MultiChoiceBalance.objects.filter(
                weekly_report=report
            ).order_by("-date", "-time").first()

            if last_balance and last_balance.balance_after_sale is not None:
                current_balance = last_balance.balance_after_sale
            else:
                current_balance = report.opening_balance + report.additional_funds

            if current_balance <= MULTICHOICE_LOW_BALANCE:
                mc_lines.append(
                    f"  - [LOW BALANCE] {report.staff.username} ({report.branch.name}, "
                    f"MultiChoice): N{current_balance:,.2f} remaining"
                )

        if mc_lines:
            sections.append("MULTICHOICE LOW BALANCE\n" + "\n".join(mc_lines))

        # ── No alerts case ──
        if not sections:
            self.stdout.write(self.style.SUCCESS("No stock or balance alerts needed."))
            return

        body_sections = "\n\n".join(sections)

        subject = "GPSL Stock & Balance Reorder Alert"
        body = f"""GPSL AUTOMATION — Stock & Balance Reorder Alert

The following items need attention:

{body_sections}

Please review and restock/refund as needed.

— GPSL ERP System
"""

        try:
            msg = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [email])
            msg.send()
            self.stdout.write(self.style.SUCCESS(f"Stock & balance alert sent to {email}"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to send alert: {e}"))