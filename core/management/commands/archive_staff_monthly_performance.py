"""Management command: archive + email each staff member's monthly
performance report.

Usage:
    python manage.py archive_staff_monthly_performance
        -> archives the PREVIOUS month for every active staff member,
           no emails sent (safe default for manual runs)

    python manage.py archive_staff_monthly_performance --send-email
        -> same, but also emails each staff member their report
           (this is what the automated month-end cron uses)

    python manage.py archive_staff_monthly_performance --backfill-months=3
        -> archives the last 3 months for every staff member, no emails
"""
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.conf import settings
from django.db.models import Sum, Q, F
from django.utils import timezone

from core.models import (
    User, RetailSale, MultiChoiceSale, Attendance,
    StaffMonthlyPerformanceArchive,
)


def _build_email_html(staff, archive, previous_archive):
    def _fmt(n):
        return "\u20a6{:,.0f}".format(float(n or 0))

    change_line = ""
    if previous_archive and previous_archive.total_revenue:
        diff = float(archive.total_revenue) - float(previous_archive.total_revenue)
        pct = round((diff / float(previous_archive.total_revenue)) * 100, 1)
        arrow = "\u2191" if pct >= 0 else "\u2193"
        color = "#065f46" if pct >= 0 else "#991b1b"
        change_line = (
            f'<p style="font-size:13px;color:{color};margin:4px 0 0;">'
            f'{arrow} {abs(pct)}% vs {previous_archive.month.strftime("%B")}</p>'
        )

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;background:#f3f4f6;padding:20px;">
        <div style="background:#004F9F;color:#FFCB05;padding:20px;border-radius:10px 10px 0 0;text-align:center;">
            <h1 style="margin:0;font-size:19px;">Your Monthly Performance</h1>
            <p style="margin:4px 0 0;font-size:13px;color:#fff;">{archive.month.strftime('%B %Y')}</p>
        </div>
        <div style="background:#fff;padding:20px;border-radius:0 0 10px 10px;">
            <p style="font-size:14px;color:#374151;">Hi {staff.username},</p>
            <p style="font-size:13px;color:#6b7280;">Here's how {archive.month.strftime('%B %Y')} went for you:</p>

            <div style="background:#f0fdf4;border-radius:8px;padding:14px;margin:14px 0;text-align:center;">
                <div style="font-size:22px;font-weight:700;color:#065f46;">{_fmt(archive.total_revenue)}</div>
                <div style="font-size:12px;color:#6b7280;">Total Sales Revenue</div>
                {change_line}
            </div>

            <table style="width:100%;border-collapse:collapse;font-size:13px;">
                <tr><td style="padding:6px 0;color:#6b7280;">Retail Sales</td><td style="text-align:right;">{_fmt(archive.retail_revenue)} ({archive.retail_quantity} items)</td></tr>
                <tr><td style="padding:6px 0;color:#6b7280;">MultiChoice Subscriptions</td><td style="text-align:right;">{_fmt(archive.multichoice_revenue)} ({archive.multichoice_quantity})</td></tr>
                <tr><td style="padding:6px 0;color:#6b7280;">Hardware Sales</td><td style="text-align:right;">{_fmt(archive.hardware_revenue)} ({archive.hardware_quantity})</td></tr>
                <tr><td style="padding:6px 0;color:#6b7280;">Online Sales</td><td style="text-align:right;">{_fmt(archive.online_sales_revenue)} ({archive.online_sales_count})</td></tr>
                <tr><td style="padding:6px 0;color:#6b7280;">Telecom Activities</td><td style="text-align:right;">{archive.telecom_activity_count}</td></tr>
            </table>

            <p style="font-size:13px;font-weight:600;color:#374151;margin:16px 0 6px;">Attendance</p>
            <p style="font-size:13px;color:#374151;margin:0;">
                {archive.days_present} days present \u00b7 {archive.days_late} late \u00b7 {archive.days_absent} absent
            </p>

            <p style="font-size:11px;color:#9ca3af;text-align:center;margin-top:20px;border-top:1px solid #e5e7eb;padding-top:12px;">
                Automated monthly report from GPSL ERP.
            </p>
        </div>
    </div>
    """


def _archive_one_staff_month(staff, month_start, send_email):
    month_end = month_start + relativedelta(months=1)

    retail_qs = RetailSale.objects.filter(
        staff=staff, date__gte=month_start, date__lt=month_end, is_voided=False
    )
    retail_revenue = retail_qs.aggregate(t=Sum(F("quantity") * F("selling_price")))["t"] or 0
    retail_quantity = retail_qs.aggregate(t=Sum("quantity"))["t"] or 0

    mc_qs = MultiChoiceSale.objects.filter(staff=staff, date__gte=month_start, date__lt=month_end)
    mc_revenue = mc_qs.aggregate(t=Sum("amount"))["t"] or 0
    mc_quantity = mc_qs.count()

    hardware_revenue = 0
    hardware_quantity = 0
    try:
        from core.models import MultiChoiceHardwareSale
        hw_qs = MultiChoiceHardwareSale.objects.filter(
            staff=staff, date__gte=month_start, date__lt=month_end
        )
        hardware_revenue = hw_qs.aggregate(t=Sum("amount"))["t"] or 0
        hardware_quantity = hw_qs.aggregate(t=Sum("quantity"))["t"] or 0
    except Exception:
        pass

    online_revenue = 0
    online_count = 0
    try:
        from core.models import OnlineSaleLog
        ol_qs = OnlineSaleLog.objects.filter(
            staff=staff, sale_date__gte=month_start, sale_date__lt=month_end
        )
        online_revenue = ol_qs.aggregate(t=Sum("amount"))["t"] or 0
        online_count = ol_qs.count()
    except Exception:
        pass

    telecom_count = 0
    try:
        from core.models import ServiceActivity
        telecom_count = ServiceActivity.objects.filter(
            staff=staff, date__gte=month_start, date__lt=month_end
        ).count()
    except Exception:
        pass

    att_qs = Attendance.objects.filter(user=staff, date__gte=month_start, date__lt=month_end)
    days_present = att_qs.count()
    days_late = att_qs.filter(is_late=True).count()
    days_absent = att_qs.filter(is_absent=True).count()

    archive, _ = StaffMonthlyPerformanceArchive.objects.update_or_create(
        staff=staff, month=month_start,
        defaults={
            "branch": staff.branch,
            "retail_revenue": retail_revenue,
            "retail_quantity": retail_quantity,
            "multichoice_revenue": mc_revenue,
            "multichoice_quantity": mc_quantity,
            "hardware_revenue": hardware_revenue,
            "hardware_quantity": hardware_quantity,
            "online_sales_count": online_count,
            "online_sales_revenue": online_revenue,
            "telecom_activity_count": telecom_count,
            "days_present": days_present,
            "days_late": days_late,
            "days_absent": days_absent,
        },
    )

    if send_email and staff.email:
        previous_month = month_start - relativedelta(months=1)
        previous_archive = StaffMonthlyPerformanceArchive.objects.filter(
            staff=staff, month=previous_month
        ).first()
        try:
            html = _build_email_html(staff, archive, previous_archive)
            msg = EmailMessage(
                subject=f"Your {month_start.strftime('%B %Y')} Performance Report - GPSL",
                body=html,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[staff.email],
            )
            msg.content_subtype = "html"
            msg.send()
            archive.email_sent = True
            archive.email_sent_at = timezone.now()
            archive.save()
        except Exception:
            pass

    return archive


class Command(BaseCommand):
    help = "Archive each staff member's monthly performance, optionally emailing their report."

    def add_arguments(self, parser):
        parser.add_argument("--month", default="", help="Specific month, e.g. 2026-07-01")
        parser.add_argument("--backfill-months", type=int, default=0, help="Archive the last N months (no email)")
        parser.add_argument("--send-email", action="store_true", help="Email each staff member their report")

    def handle(self, *args, **options):
        month_str = options["month"]
        backfill = options["backfill_months"]
        send_email = options["send_email"]

        staff_members = User.objects.filter(
            role__in=["RETAIL", "TELECOM", "MULTICHOICE", "MANAGER"]
        )

        if backfill:
            today_first = date.today().replace(day=1)
            for i in range(1, backfill + 1):
                target = today_first - relativedelta(months=i)
                for staff in staff_members:
                    _archive_one_staff_month(staff, target, send_email=False)
                self.stdout.write(f"Archived {target.strftime('%B %Y')} for {staff_members.count()} staff.")
            self.stdout.write(self.style.SUCCESS(f"Backfilled {backfill} month(s) for all staff."))
            return

        if month_str:
            target = date.fromisoformat(month_str).replace(day=1)
        else:
            target = (date.today().replace(day=1)) - relativedelta(months=1)

        count = 0
        for staff in staff_members:
            _archive_one_staff_month(staff, target, send_email=send_email)
            count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Archived {target.strftime('%B %Y')} for {count} staff member(s)."
            + (" Emails sent." if send_email else " No emails sent (use --send-email to send).")
        ))
