"""Management command: send director daily digest email.

Usage: python manage.py daily_digest --email=director@company.com
"""
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, F
from datetime import date
from core.models import (
    RetailSale, MultiChoiceSale, ServiceActivity,
    Customer, StockAlert, Attendance, Expense,
    DirectorDailyDigest,
)

class Command(BaseCommand):
    help = "Send daily digest email to director with all day's activity."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Director email address")
        parser.add_argument("--date", default="", help="Date to report (YYYY-MM-DD), default today")

    def handle(self, *args, **options):
        email = options["email"]
        today_str = options["date"]
        if today_str:
            from datetime import datetime
            today = datetime.strptime(today_str, "%Y-%m-%d").date()
        else:
            today = date.today()

        # Gather stats
        retail_sales = RetailSale.objects.filter(date=today, is_voided=False)
        retail_revenue = retail_sales.aggregate(
            total=Sum(F("quantity") * F("selling_price"))
        )["total"] or 0
        retail_count = retail_sales.count()

        mc_sales = MultiChoiceSale.objects.filter(date=today)
        mc_revenue = mc_sales.aggregate(total=Sum("amount"))["total"] or 0
        mc_count = mc_sales.count()

        activities = ServiceActivity.objects.filter(date=today)
        activity_count = activities.count()

        new_customers = Customer.objects.filter(
            last_purchase__date=today
        ).count()

        stock_alerts = StockAlert.objects.filter(is_active=True).count()
        attendance_count = Attendance.objects.filter(date=today).count()
        total_expenses = Expense.objects.filter(date=today).aggregate(
            total=Sum("amount")
        )["total"] or 0

        total_deductions = Attendance.objects.filter(
            date=today
        ).aggregate(total=Sum("deduction_amount"))["total"] or 0

        # Build digest
        subject = f"GPSL Daily Digest — {today.strftime('%A, %d %B %Y')}"
        body = f"""GPSL AUTOMATION — Daily Activity Summary
Date: {today.strftime('%A, %d %B %Y')}

RETAIL SALES
• Total transactions: {retail_count}
• Total revenue: ₦{retail_revenue:,.0f}

MULTICHOICE SALES
• Total transactions: {mc_count}
• Total revenue: ₦{mc_revenue:,.0f}

SERVICE ACTIVITIES
• Total activities: {activity_count}

CUSTOMERS
• New customers today: {new_customers}

STOCK
• Active stock alerts: {stock_alerts}

ATTENDANCE
• Staff checked in: {attendance_count}
• Total deductions: ₦{total_deductions:,.0f}

EXPENSES
• Total expenses: ₦{total_expenses:,.0f}

OVERALL
• Total revenue: ₦{(retail_revenue + mc_revenue):,.0f}
• Net after expenses: ₦{(retail_revenue + mc_revenue - total_expenses):,.0f}

—
This is an automated daily digest from GPSL ERP.
To view full details, log in to your dashboard.
"""

        try:
            msg = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [email])
            msg.send()

            # Log digest
            digest, _ = DirectorDailyDigest.objects.get_or_create(date=today, defaults={
                "email_sent": True,
                "email_recipient": email,
                "total_retail_sales": retail_count,
                "total_retail_revenue": retail_revenue,
                "total_multichoice_sales": mc_count,
                "total_multichoice_revenue": mc_revenue,
                "total_service_activities": activity_count,
                "total_new_customers": new_customers,
                "total_stock_alerts": stock_alerts,
                "total_attendance_records": attendance_count,
                "total_expenses": total_expenses,
                "total_deductions": total_deductions,
                "sent_at": timezone.now(),
            })
            digest.email_sent = True
            digest.sent_at = timezone.now()
            digest.save()

            self.stdout.write(self.style.SUCCESS(f"Daily digest sent to {email}"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to send digest: {e}"))
