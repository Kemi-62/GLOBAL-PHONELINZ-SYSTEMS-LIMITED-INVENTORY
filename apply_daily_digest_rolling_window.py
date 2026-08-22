"""
apply_daily_digest_rolling_window.py
======================================
Fixes the daily digest missing evening sales. Keeps your 7pm WAT schedule
but makes the digest itself smarter: it now reports everything that
happened SINCE the last digest was sent, up to right now - so an 8:40pm
sale made yesterday shows up in TODAY's digest instead of being skipped
forever.

WHAT CHANGED
- Digest no longer filters strictly by "today's calendar date" for Retail
  Sales, MultiChoice Sales, and New Customers. It now uses a rolling
  window: (last digest's send time) -> (this run's send time).
- If this is the very first digest ever sent (no prior record), it
  defaults to covering the last 24 hours.
- The email header now shows the actual period covered.
- The cron stays at 7pm WAT (0 18 * * 1-6) — this script does NOT touch
  the schedule, since capturing the full history via the rolling window
  is the actual fix, not a later send time.

A SCHEMA LIMIT WORTH KNOWING
  Telecom Activity (ServiceActivity) and Expenses only store a DATE, not
  a time-of-day, so they still filter by calendar day only for now. Run
  apply_digest_full_coverage.py after this one to close that gap too
  (it adds a `time` field to both via migration).

HOW TO RUN (Replit Shell)
    python apply_daily_digest_rolling_window.py

Then:
    python manage.py check
    git add . && git commit -m "Daily digest: rolling window instead of missing evening sales" && git push

IDEMPOTENT - safe to run twice.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def read(path):
    full = os.path.join(BASE_DIR, path)
    if not os.path.exists(full):
        print("XX Could not find " + path + " - are you running this from your project root?")
        sys.exit(1)
    with open(full, "r", encoding="utf-8") as f:
        return f.read()


def write(path, content):
    full = os.path.join(BASE_DIR, path)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


NEW_DIGEST_MARKER = "ROLLING WINDOW DIGEST v1"

NEW_DIGEST_FILE = '''"""Management command: send director daily digest email.
Detailed HTML version - per-branch breakdown, products sold, telecom/multichoice activity.

# ROLLING WINDOW DIGEST v1
Reports everything since the last digest was sent (not just "today"), so
evening sales made after the previous run are never silently dropped.

Usage: python manage.py daily_digest --email=director@company.com
       python manage.py daily_digest --email=director@company.com --date=2026-08-04   (backfill a single calendar day)
"""
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, F, Count
from datetime import date, datetime, timedelta, time as dt_time

from core.models import (
    RetailSale, MultiChoiceSale, ServiceActivity,
    Customer, StockAlert, Attendance, Expense,
    DirectorDailyDigest, Branch, BranchSafeStock,
)


class Command(BaseCommand):
    help = "Send detailed HTML daily digest email to director, covering everything since the last digest."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Director email address")
        parser.add_argument("--date", default="", help="Backfill a single calendar day (YYYY-MM-DD) instead of the rolling window")

    def handle(self, *args, **options):
        email = options["email"]
        date_str = options["date"]
        now_aware = timezone.localtime(timezone.now())

        if date_str:
            report_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            period_start_aware = timezone.make_aware(datetime.combine(report_date, dt_time.min))
            period_end_aware = timezone.make_aware(datetime.combine(report_date, dt_time.max))
        else:
            report_date = now_aware.date()
            period_end_aware = now_aware
            last_digest = DirectorDailyDigest.objects.filter(
                email_sent=True, sent_at__isnull=False
            ).order_by("-sent_at").first()
            if last_digest:
                period_start_aware = timezone.localtime(last_digest.sent_at)
            else:
                period_start_aware = period_end_aware - timedelta(hours=24)

        period_start_naive = period_start_aware.replace(tzinfo=None)
        period_end_naive = period_end_aware.replace(tzinfo=None)
        start_date = period_start_naive.date()
        end_date = period_end_naive.date()

        def _window_qs(model, base_qs):
            candidates = base_qs.filter(date__range=[start_date, end_date])
            matching_ids = [
                r.id for r in candidates.only("id", "date", "time")
                if period_start_naive < datetime.combine(r.date, r.time) <= period_end_naive
            ]
            return model.objects.filter(id__in=matching_ids)

        branches = Branch.objects.all()

        retail_sales_all = _window_qs(RetailSale, RetailSale.objects.filter(is_voided=False))
        retail_revenue_all = retail_sales_all.aggregate(
            t=Sum(F("quantity") * F("selling_price"))
        )["t"] or 0
        mc_sales_all = _window_qs(MultiChoiceSale, MultiChoiceSale.objects.all())
        mc_revenue_all = mc_sales_all.aggregate(t=Sum("amount"))["t"] or 0

        total_expenses_all = Expense.objects.filter(date=end_date).aggregate(
            t=Sum("amount")
        )["t"] or 0

        new_customers = Customer.objects.filter(
            last_purchase__gt=period_start_aware, last_purchase__lte=period_end_aware
        ).count()

        stock_alerts = StockAlert.objects.filter(is_active=True).select_related(
            "product", "branch"
        )
        total_deductions = Attendance.objects.filter(date=end_date).aggregate(
            t=Sum("deduction_amount")
        )["t"] or 0

        branch_blocks = []
        for branch in branches:
            b_retail = retail_sales_all.filter(branch=branch).select_related("product")
            b_revenue = b_retail.aggregate(
                t=Sum(F("quantity") * F("selling_price"))
            )["t"] or 0
            b_count = b_retail.count()

            products_sold = (
                b_retail.values("product__model_name")
                .annotate(
                    qty=Sum("quantity"),
                    revenue=Sum(F("quantity") * F("selling_price")),
                )
                .order_by("-revenue")
            )

            b_mc = mc_sales_all.filter(branch=branch)
            b_mc_revenue = b_mc.aggregate(t=Sum("amount"))["t"] or 0
            b_mc_count = b_mc.count()

            b_activities = ServiceActivity.objects.filter(branch=branch, date=end_date)
            b_activity_summary = (
                b_activities.values("service_type")
                .annotate(qty=Sum("quantity"))
                .order_by("-qty")
            )

            b_att = Attendance.objects.filter(branch=branch, date=end_date)
            b_present = b_att.count()
            b_late = b_att.filter(is_late=True).count()
            b_absent = b_att.filter(is_absent=True).count()

            b_expenses = Expense.objects.filter(branch=branch, date=end_date).aggregate(
                t=Sum("amount")
            )["t"] or 0

            if products_sold:
                product_rows = "".join(
                    f"""<tr>
                        <td style="padding:6px 10px;border-bottom:1px solid #f3f4f6;">{p['product__model_name']}</td>
                        <td style="padding:6px 10px;border-bottom:1px solid #f3f4f6;text-align:center;">{p['qty']}</td>
                        <td style="padding:6px 10px;border-bottom:1px solid #f3f4f6;text-align:right;">N{p['revenue']:,.0f}</td>
                    </tr>"""
                    for p in products_sold
                )
            else:
                product_rows = """<tr><td colspan="3" style="padding:10px;color:#9ca3af;text-align:center;">No retail sales in this period</td></tr>"""

            if b_activity_summary:
                activity_rows = "".join(
                    f"<li>{a['service_type']}: {a['qty']}</li>"
                    for a in b_activity_summary
                )
            else:
                activity_rows = "<li style='color:#9ca3af;'>No telecom activity today</li>"

            block = f"""
            <div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:18px;margin-bottom:16px;">
                <h3 style="margin:0 0 12px;color:#004F9F;font-size:16px;">{branch.name}</h3>

                <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px;">
                    <div style="background:#f0fdf4;border-radius:6px;padding:8px 14px;font-size:13px;">
                        <strong style="color:#065f46;">N{b_revenue:,.0f}</strong><br>
                        <span style="color:#6b7280;">Retail Revenue ({b_count} sales)</span>
                    </div>
                    <div style="background:#ede9fe;border-radius:6px;padding:8px 14px;font-size:13px;">
                        <strong style="color:#5b21b6;">N{b_mc_revenue:,.0f}</strong><br>
                        <span style="color:#6b7280;">MultiChoice ({b_mc_count} subs)</span>
                    </div>
                    <div style="background:#fef3c7;border-radius:6px;padding:8px 14px;font-size:13px;">
                        <strong style="color:#92400e;">N{b_expenses:,.0f}</strong><br>
                        <span style="color:#6b7280;">Expenses (today)</span>
                    </div>
                    <div style="background:#dbeafe;border-radius:6px;padding:8px 14px;font-size:13px;">
                        <strong style="color:#1e40af;">{b_present} present</strong><br>
                        <span style="color:#6b7280;">{b_late} late \\u00b7 {b_absent} absent</span>
                    </div>
                </div>

                <p style="font-size:13px;font-weight:600;color:#374151;margin:0 0 6px;">Products Sold This Period</p>
                <table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:12px;">
                    <thead>
                        <tr style="background:#f9fafb;">
                            <th style="padding:6px 10px;text-align:left;color:#374151;">Product</th>
                            <th style="padding:6px 10px;text-align:center;color:#374151;">Qty</th>
                            <th style="padding:6px 10px;text-align:right;color:#374151;">Revenue</th>
                        </tr>
                    </thead>
                    <tbody>{product_rows}</tbody>
                </table>

                <p style="font-size:13px;font-weight:600;color:#374151;margin:0 0 4px;">Telecom Activity (today)</p>
                <ul style="font-size:13px;color:#374151;margin:0;padding-left:18px;">{activity_rows}</ul>
            </div>
            """
            branch_blocks.append(block)

        branch_html = "".join(branch_blocks)

        if stock_alerts:
            alert_rows = "".join(
                f"<li>{a.product.model_name} - {a.branch.name} ({a.current_quantity} left)</li>"
                for a in stock_alerts
            )
            stock_html = f"<ul style='font-size:13px;color:#991b1b;margin:0;padding-left:18px;'>{alert_rows}</ul>"
        else:
            stock_html = "<p style='font-size:13px;color:#6b7280;'>No active stock alerts.</p>"

        if period_start_naive.date() == period_end_naive.date():
            date_label = period_end_naive.strftime("%A, %d %B %Y")
        else:
            date_label = (
                period_start_naive.strftime("%a %d %b, %I:%M%p")
                + " \\u2192 "
                + period_end_naive.strftime("%a %d %b, %I:%M%p")
            )

        overall_net = retail_revenue_all + mc_revenue_all - total_expenses_all

        html_body = f"""
        <div style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;background:#f3f4f6;padding:20px;">
            <div style="background:#004F9F;color:#FFCB05;padding:20px;border-radius:10px 10px 0 0;text-align:center;">
                <h1 style="margin:0;font-size:20px;">GPSL Daily Digest</h1>
                <p style="margin:4px 0 0;font-size:13px;color:#fff;">{date_label}</p>
            </div>

            <div style="background:#fff;padding:18px;">
                <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px;">
                    <div style="flex:1;min-width:140px;background:#004F9F;color:#fff;border-radius:8px;padding:14px;text-align:center;">
                        <div style="font-size:20px;font-weight:700;">N{(retail_revenue_all + mc_revenue_all):,.0f}</div>
                        <div style="font-size:12px;opacity:.85;">Total Revenue</div>
                    </div>
                    <div style="flex:1;min-width:140px;background:#10b981;color:#fff;border-radius:8px;padding:14px;text-align:center;">
                        <div style="font-size:20px;font-weight:700;">N{overall_net:,.0f}</div>
                        <div style="font-size:12px;opacity:.85;">Net After Expenses</div>
                    </div>
                    <div style="flex:1;min-width:140px;background:#f59e0b;color:#fff;border-radius:8px;padding:14px;text-align:center;">
                        <div style="font-size:20px;font-weight:700;">{new_customers}</div>
                        <div style="font-size:12px;opacity:.85;">New Customers</div>
                    </div>
                </div>

                <h2 style="font-size:16px;color:#111827;margin:0 0 12px;border-bottom:2px solid #e5e7eb;padding-bottom:8px;">
                    Branch Breakdown
                </h2>
                {branch_html}

                <h2 style="font-size:16px;color:#111827;margin:20px 0 12px;border-bottom:2px solid #e5e7eb;padding-bottom:8px;">
                    Stock Alerts
                </h2>
                {stock_html}

                <p style="font-size:12px;color:#9ca3af;text-align:center;margin-top:24px;border-top:1px solid #e5e7eb;padding-top:14px;">
                    Automated daily digest from GPSL ERP \\u00b7 Log in to your dashboard for full details.
                </p>
            </div>
        </div>
        """

        plain_text = f"GPSL Daily Digest - {date_label}\\n\\nView this email in HTML for full details.\\nTotal Revenue: N{(retail_revenue_all + mc_revenue_all):,.0f}"

        try:
            msg = EmailMessage(
                subject=f"GPSL Daily Digest - {report_date.strftime('%d %b %Y')}",
                body=html_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[email],
            )
            msg.content_subtype = "html"
            msg.send()

            digest, _ = DirectorDailyDigest.objects.get_or_create(
                date=report_date,
                defaults={
                    "email_sent": True,
                    "email_recipient": email,
                    "total_retail_sales": retail_sales_all.count(),
                    "total_retail_revenue": retail_revenue_all,
                    "total_multichoice_sales": mc_sales_all.count(),
                    "total_multichoice_revenue": mc_revenue_all,
                    "total_service_activities": ServiceActivity.objects.filter(date=end_date).count(),
                    "total_new_customers": new_customers,
                    "total_stock_alerts": stock_alerts.count(),
                    "total_attendance_records": Attendance.objects.filter(date=end_date).count(),
                    "total_expenses": total_expenses_all,
                    "total_deductions": total_deductions,
                    "sent_at": now_aware,
                },
            )
            digest.email_sent = True
            digest.sent_at = now_aware
            digest.save()

            self.stdout.write(self.style.SUCCESS(f"Detailed daily digest sent to {email} (covering {date_label})"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to send digest: {e}"))
'''


def main():
    print("-- Applying Rolling-Window Daily Digest --\n")

    digest_path = os.path.join(BASE_DIR, "core", "management", "commands", "daily_digest.py")
    if not os.path.exists(digest_path):
        print("XX Could not find core/management/commands/daily_digest.py")
        sys.exit(1)
    current = read("core/management/commands/daily_digest.py")
    if NEW_DIGEST_MARKER in current:
        print("SKIP  daily_digest.py: rolling-window version already in place, skipping.")
    else:
        write("core/management/commands/daily_digest.py", NEW_DIGEST_FILE)
        print("OK    daily_digest.py: replaced with rolling-window version")

    print("\n-- Done --")
    print("Next steps:")
    print("  python manage.py check")
    print("  git add . && git commit -m 'Daily digest: rolling window' && git push")
    print("")
    print("Optional manual test of a specific calendar day:")
    print("  python manage.py daily_digest --email=you@example.com --date=2026-08-04")


if __name__ == "__main__":
    main()
