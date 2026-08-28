"""Management command: archive a month's finalized performance figures.

Usage:
    python manage.py archive_monthly_performance
        -> archives the PREVIOUS calendar month (the one that just ended)

    python manage.py archive_monthly_performance --month=2026-07-01
        -> archives a specific month

    python manage.py archive_monthly_performance --backfill-months=6
        -> archives the last 6 calendar months (run once to seed history)
"""
from datetime import date
from dateutil.relativedelta import relativedelta

from django.core.management.base import BaseCommand
from django.db.models import Sum, F, ExpressionWrapper, DecimalField

from core.models import (
    Branch, RetailSale, MultiChoiceSale, Expense, Customer,
    MonthlyPerformanceArchive,
)


def _archive_one_month(stdout, month_start):
    from django.utils import timezone as _tz
    from datetime import datetime as _dt

    month_end = month_start + relativedelta(months=1)
    month_start_aware = _tz.make_aware(_dt.combine(month_start, _dt.min.time()))
    month_end_aware = _tz.make_aware(_dt.combine(month_end, _dt.min.time()))
    profit_expr = ExpressionWrapper(
        (F("selling_price") - F("product__cost_price")) * F("quantity"),
        output_field=DecimalField(),
    )

    branches = list(Branch.objects.all())
    scopes = branches + [None]

    for branch in scopes:
        retail_qs = RetailSale.objects.filter(
            date__gte=month_start, date__lt=month_end, is_voided=False
        )
        mc_qs = MultiChoiceSale.objects.filter(date__gte=month_start, date__lt=month_end)
        exp_qs = Expense.objects.filter(date__gte=month_start, date__lt=month_end)
        cust_qs = Customer.objects.filter(
            last_purchase__gte=month_start_aware, last_purchase__lt=month_end_aware
        )

        if branch is not None:
            retail_qs = retail_qs.filter(branch=branch)
            mc_qs = mc_qs.filter(branch=branch)
            exp_qs = exp_qs.filter(branch=branch)
            cust_qs = cust_qs.filter(branch=branch)

        retail_revenue = retail_qs.aggregate(t=Sum(F("quantity") * F("selling_price")))["t"] or 0
        retail_quantity = retail_qs.aggregate(t=Sum("quantity"))["t"] or 0
        retail_gross = retail_qs.aggregate(t=Sum(profit_expr))["t"] or 0
        mc_revenue = mc_qs.aggregate(t=Sum("amount"))["t"] or 0
        mc_quantity = mc_qs.count()
        total_expenses = exp_qs.aggregate(t=Sum("amount"))["t"] or 0
        new_customers = cust_qs.count()
        net_profit = (retail_gross or 0) + (mc_revenue or 0) - (total_expenses or 0)

        MonthlyPerformanceArchive.objects.update_or_create(
            month=month_start, branch=branch,
            defaults={
                "retail_revenue": retail_revenue,
                "retail_quantity": retail_quantity,
                "retail_gross_profit": retail_gross,
                "multichoice_revenue": mc_revenue,
                "multichoice_quantity": mc_quantity,
                "total_expenses": total_expenses,
                "net_profit": net_profit,
                "new_customers": new_customers,
            },
        )

    scope_label = "company-wide + " + str(len(branches)) + " branch(es)"
    stdout.write("Archived " + month_start.strftime("%B %Y") + " (" + scope_label + ")")


class Command(BaseCommand):
    help = "Archive a month's finalized performance figures for month-to-month comparison."

    def add_arguments(self, parser):
        parser.add_argument("--month", default="", help="Specific month to archive, e.g. 2026-07-01")
        parser.add_argument("--backfill-months", type=int, default=0, help="Archive the last N calendar months")

    def handle(self, *args, **options):
        month_str = options["month"]
        backfill = options["backfill_months"]

        if backfill:
            today_first = date.today().replace(day=1)
            for i in range(1, backfill + 1):
                target = today_first - relativedelta(months=i)
                _archive_one_month(self.stdout, target)
            self.stdout.write(self.style.SUCCESS(f"Backfilled {backfill} month(s)."))
            return

        if month_str:
            target = date.fromisoformat(month_str).replace(day=1)
        else:
            target = (date.today().replace(day=1)) - relativedelta(months=1)

        _archive_one_month(self.stdout, target)
        self.stdout.write(self.style.SUCCESS("Done."))
