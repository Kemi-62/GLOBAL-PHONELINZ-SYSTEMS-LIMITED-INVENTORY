"""Management command: send stock reorder alerts via email.

Usage: python manage.py stock_alert_email --email=director@company.com
"""
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.conf import settings
from django.db import models
from core.models import BranchSafeStock, StockAlert

class Command(BaseCommand):
    help = "Send stock reorder alert emails to director."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Email address to send alerts to")

    def handle(self, *args, **options):
        email = options["email"]

        # Find low stock items
        low_stock = BranchSafeStock.objects.filter(
            quantity__lte=models.F("product__reorder_threshold")
        ).select_related("product", "branch")

        if not low_stock.exists():
            self.stdout.write(self.style.SUCCESS("No stock alerts needed."))
            return

        lines = []
        for item in low_stock:
            lines.append(
                f"  • {item.product.model_name} @ {item.branch.name}: "
                f"{item.quantity} remaining (threshold: {item.product.reorder_threshold or 'N/A'})"
            )

        subject = "GPSL Stock Reorder Alert"
        body = f"""GPSL AUTOMATION — Stock Reorder Alert

The following items are below their reorder threshold:

{"\n".join(lines)}

Please review and restock as needed.

— GPSL ERP System
"""

        try:
            msg = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [email])
            msg.send()
            self.stdout.write(self.style.SUCCESS(f"Stock alert sent to {email}"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to send stock alert: {e}"))
