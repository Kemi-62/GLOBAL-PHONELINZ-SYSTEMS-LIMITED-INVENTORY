"""Management command: send stock reorder alerts + subscription expiry alerts via email.
Covers:
- Branch Safe Stock low/out
- Retail Staff Stock low/out
- Telecom Wholesale Device Stock low/out
- MultiChoice low balance
- MultiChoice subscriptions expiring in 1-7 days
- MultiChoice subscriptions already expired (last 3 days)
- Router subscriptions expiring in 1-7 days
- Router subscriptions already expired

Usage: python manage.py stock_alert_email --email=director@company.com
"""
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.conf import settings
from django.utils import timezone
from datetime import timedelta, date

from core.models import (
    BranchSafeStock, StaffStock, WholesaleDevice,
    MultiChoiceWeeklyReport, MultiChoiceBalance,
    MultiChoiceSale,
)

LOW_STOCK_THRESHOLD  = 1
MULTICHOICE_LOW_BAL  = 5000
EXPIRY_WARN_DAYS     = 7   # warn when this many days left


class Command(BaseCommand):
    help = "Send stock, balance, and subscription expiry alert emails."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Email address to send alerts to")

    def handle(self, *args, **options):
        email   = options["email"]
        today   = date.today()
        sections = []
        html_sections = []

        # ── 1. Branch Safe Stock ──
        branch_low = BranchSafeStock.objects.filter(
            quantity__lte=LOW_STOCK_THRESHOLD
        ).select_related("product", "branch")
        if branch_low.exists():
            lines = []
            for item in branch_low:
                status = "OUT OF STOCK" if item.quantity == 0 else "LOW STOCK"
                lines.append(f"  [{status}] {item.product.model_name} @ {item.branch.name}: {item.quantity} remaining")
            sections.append("BRANCH SAFE STOCK\n" + "\n".join(lines))
            html_sections.append(("🏪 Branch Safe Stock", lines, "#ef4444"))

        # ── 2. Retail Staff Stock ──
        staff_low = StaffStock.objects.filter(
            quantity__lte=LOW_STOCK_THRESHOLD, staff__role="RETAIL"
        ).select_related("product", "staff", "staff__branch")
        if staff_low.exists():
            lines = []
            for item in staff_low:
                status = "OUT OF STOCK" if item.quantity == 0 else "LOW STOCK"
                branch_name = item.staff.branch.name if item.staff.branch else "No branch"
                lines.append(f"  [{status}] {item.product.model_name} — {item.staff.username} ({branch_name}): {item.quantity} remaining")
            sections.append("RETAIL STAFF STOCK\n" + "\n".join(lines))
            html_sections.append(("🛒 Retail Staff Stock", lines, "#f97316"))

        # ── 3. Telecom Wholesale Device Stock ──
        try:
            device_low = WholesaleDevice.objects.filter(
                quantity__lte=LOW_STOCK_THRESHOLD
            ).select_related("staff", "branch")
            if device_low.exists():
                lines = []
                for item in device_low:
                    status = "OUT OF STOCK" if item.quantity == 0 else "LOW STOCK"
                    lines.append(f"  [{status}] {item.product_name} ({item.network_type}) — {item.staff.username} ({item.branch.name}): {item.quantity} remaining")
                sections.append("TELECOM DEVICE STOCK\n" + "\n".join(lines))
                html_sections.append(("📡 Telecom Device Stock", lines, "#f97316"))
        except Exception:
            pass

        # ── 4. MultiChoice Low Balance ──
        week_start = today - timedelta(days=today.weekday())
        open_reports = MultiChoiceWeeklyReport.objects.filter(
            is_closed=False, week_start_date__gte=week_start,
        ).select_related("staff", "branch")
        mc_balance_lines = []
        for report in open_reports:
            last_balance = MultiChoiceBalance.objects.filter(
                weekly_report=report
            ).order_by("-date", "-time").first()
            current_balance = (
                last_balance.balance_after_sale
                if last_balance and last_balance.balance_after_sale is not None
                else report.opening_balance + report.additional_funds
            )
            if current_balance <= MULTICHOICE_LOW_BAL:
                mc_balance_lines.append(
                    f"  [LOW BALANCE] {report.staff.username} ({report.branch.name}): ₦{current_balance:,.2f} remaining"
                )
        if mc_balance_lines:
            sections.append("MULTICHOICE LOW BALANCE\n" + "\n".join(mc_balance_lines))
            html_sections.append(("💰 MultiChoice Low Balance", mc_balance_lines, "#eab308"))

        # ── 5. MultiChoice Subscriptions Expiring Soon ──
        try:
            mc_expiring = MultiChoiceSale.objects.filter(
                expiry_date__range=[today, today + timedelta(days=EXPIRY_WARN_DAYS)]
            ).select_related("staff", "branch").order_by("expiry_date")
            if mc_expiring.exists():
                lines = []
                for sale in mc_expiring:
                    days_left = (sale.expiry_date - today).days
                    urgency = "TODAY" if days_left == 0 else f"in {days_left} day{'s' if days_left != 1 else ''}"
                    lines.append(
                        f"  [EXPIRES {urgency.upper()}] {sale.customer_name} | "
                        f"{sale.service_type} {sale.package_type} | "
                        f"IUC: {sale.iuc_number or 'N/A'} | "
                        f"Phone: {sale.customer_phone or 'N/A'} | "
                        f"Staff: {sale.staff.username} ({sale.branch.name}) | "
                        f"Expires: {sale.expiry_date}"
                    )
                sections.append("MULTICHOICE SUBSCRIPTIONS EXPIRING SOON\n" + "\n".join(lines))
                html_sections.append(("📺 MC Subscriptions Expiring Soon", lines, "#eab308"))
        except Exception:
            pass

        # ── 6. MultiChoice Subscriptions Already Expired ──
        try:
            mc_expired = MultiChoiceSale.objects.filter(
                expiry_date__range=[today - timedelta(days=3), today - timedelta(days=1)]
            ).select_related("staff", "branch").order_by("expiry_date")
            if mc_expired.exists():
                lines = []
                for sale in mc_expired:
                    days_ago = (today - sale.expiry_date).days
                    lines.append(
                        f"  [EXPIRED {days_ago} DAY{'S' if days_ago != 1 else ''} AGO] {sale.customer_name} | "
                        f"{sale.service_type} {sale.package_type} | "
                        f"Phone: {sale.customer_phone or 'N/A'} | "
                        f"Staff: {sale.staff.username} ({sale.branch.name})"
                    )
                sections.append("MULTICHOICE SUBSCRIPTIONS EXPIRED\n" + "\n".join(lines))
                html_sections.append(("❌ MC Subscriptions Expired", lines, "#ef4444"))
        except Exception:
            pass

        # ── 7. Router Subscriptions Expiring Soon ──
        try:
            from core.models import RouterSubscription
            router_expiring = RouterSubscription.objects.filter(
                is_active=True,
                expiry_date__range=[today, today + timedelta(days=EXPIRY_WARN_DAYS)]
            ).select_related("staff", "branch").order_by("expiry_date")
            if router_expiring.exists():
                lines = []
                for sub in router_expiring:
                    days_left = (sub.expiry_date - today).days
                    urgency = "TODAY" if days_left == 0 else f"in {days_left} day{'s' if days_left != 1 else ''}"
                    lines.append(
                        f"  [EXPIRES {urgency.upper()}] {sub.customer_name} | "
                        f"{sub.router_type} Router | "
                        f"Router#: {sub.router_number} | "
                        f"Phone: {sub.customer_phone} | "
                        f"Alt: {sub.alt_phone or 'N/A'} | "
                        f"Staff: {sub.staff.username} ({sub.branch.name}) | "
                        f"Month {sub.month_number} | Expires: {sub.expiry_date}"
                    )
                sections.append("ROUTER SUBSCRIPTIONS EXPIRING SOON\n" + "\n".join(lines))
                html_sections.append(("📡 Router Subscriptions Expiring", lines, "#eab308"))
        except Exception:
            pass

        # ── 8. Router Subscriptions Expired ──
        try:
            from core.models import RouterSubscription
            router_expired = RouterSubscription.objects.filter(
                is_active=True,
                expiry_date__lt=today,
            ).select_related("staff", "branch").order_by("expiry_date")
            if router_expired.exists():
                lines = []
                for sub in router_expired:
                    days_ago = (today - sub.expiry_date).days
                    lines.append(
                        f"  [EXPIRED {days_ago} DAY{'S' if days_ago != 1 else ''} AGO] {sub.customer_name} | "
                        f"{sub.router_type} | Router#: {sub.router_number} | "
                        f"Phone: {sub.customer_phone} | Staff: {sub.staff.username} ({sub.branch.name})"
                    )
                sections.append("ROUTER SUBSCRIPTIONS EXPIRED\n" + "\n".join(lines))
                html_sections.append(("❌ Router Subscriptions Expired", lines, "#ef4444"))
        except Exception:
            pass

        if not sections:
            self.stdout.write(self.style.SUCCESS("No alerts needed today."))
            return

        # ── Build plain text body ──
        body_text = "\n\n".join(sections)
        subject = f"GPSL Alert — {today.strftime('%d %b %Y')}"
        body = f"""GPSL AUTOMATION — Daily Alerts
Date: {today.strftime('%A, %d %B %Y')}

{body_text}

Please take action on the above items.
— GPSL Business Suite
"""

        # ── Build HTML body ──
        html_parts = []
        for title, lines, color in html_sections:
            items_html = "".join(
                f'<li style="padding:.35rem 0;border-bottom:1px solid #f1f5f9;font-size:.85rem;">{l.strip()}</li>'
                for l in lines
            )
            html_parts.append(f"""
<div style="margin-bottom:1.2rem;background:#fff;border-radius:8px;overflow:hidden;border:1px solid #e2e8f0;">
  <div style="background:{color};color:#fff;padding:.6rem 1rem;font-weight:700;font-size:.9rem;">{title}</div>
  <ul style="list-style:none;padding:.5rem 1rem;margin:0;">{items_html}</ul>
</div>""")

        html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family:'Segoe UI',Arial,sans-serif;background:#f8fafc;padding:1.5rem;color:#1e293b;max-width:700px;margin:0 auto;">
  <div style="background:#004F9F;color:#fff;padding:1rem 1.5rem;border-radius:10px 10px 0 0;">
    <h2 style="margin:0;font-size:1.1rem;">GPSL Business Suite — Daily Alerts</h2>
    <p style="margin:.25rem 0 0;font-size:.8rem;opacity:.8;">{today.strftime('%A, %d %B %Y')}</p>
  </div>
  <div style="background:#fff;padding:1.2rem 1.5rem;border-radius:0 0 10px 10px;border:1px solid #e2e8f0;border-top:none;">
    {''.join(html_parts)}
    <p style="font-size:.75rem;color:#94a3b8;margin-top:1rem;">
      This is an automated alert from GPSL Business Suite. Please take action on the above items.
    </p>
  </div>
</body>
</html>"""

        try:
            msg = EmailMultiAlternatives(
                subject, body,
                settings.DEFAULT_FROM_EMAIL, [email]
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send()
            self.stdout.write(self.style.SUCCESS(f"Alert email sent to {email} — {len(sections)} section(s)"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to send alert: {e}"))
