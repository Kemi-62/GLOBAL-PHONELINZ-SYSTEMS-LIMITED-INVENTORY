"""CUSTOMER_HISTORY_V1

Repair stored customer totals (purchase count, total spent, last purchase)
from the real sales records. The old customer-history page overwrote these
with retail-only numbers; this puts the true company-wide figures back.

    python manage.py recalculate_customer_stats            (preview only)
    python manage.py recalculate_customer_stats --apply    (save changes)

Also lists CRM records that share the same real phone number.
"""
from django.core.management.base import BaseCommand

from core.models import Customer
from core.customer_history import (
    REAL_DEPARTMENTS, customer_transactions, last_purchase_datetime,
    phone_key, rows_by_key, summarize,
)


class Command(BaseCommand):
    help = "Recompute Customer.purchase_count / total_spent / last_purchase from real sales."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Save the corrected values (default is preview only).")

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        grouped = rows_by_key(customer_transactions(None, departments=REAL_DEPARTMENTS))
        by_key = {}
        changed = 0

        for customer in Customer.objects.all().order_by("id"):
            key = phone_key(customer.phone_number)
            by_key.setdefault(key, []).append(customer)
            rows = grouped.get(key, []) if key else []
            summary = summarize(rows)
            new_count = summary["count"]
            new_total = summary["total_spent"]
            new_last = last_purchase_datetime(rows)

            if (customer.purchase_count == new_count
                    and (customer.total_spent or 0) == new_total):
                continue
            changed += 1
            self.stdout.write("%s (%s): count %s -> %s, total %s -> %s" % (
                customer.name, customer.phone_number, customer.purchase_count, new_count,
                customer.total_spent, new_total))
            if apply_changes:
                customer.purchase_count = new_count
                customer.total_spent = new_total
                if new_last is not None:
                    customer.last_purchase = new_last
                customer.save(update_fields=["purchase_count", "total_spent", "last_purchase"])

        duplicates = {k: v for k, v in by_key.items() if k and len(v) > 1}
        for key, records in duplicates.items():
            self.stdout.write(self.style.WARNING(
                "SAME NUMBER, %d CRM records: %s" % (
                    len(records), ", ".join("#%s %s (%s)" % (c.id, c.name, c.phone_number) for c in records))))

        label = "Saved" if apply_changes else "[PREVIEW - nothing saved] Would fix"
        self.stdout.write(self.style.SUCCESS(
            "%s %d customer record(s); %d number(s) have duplicate CRM records." % (
                label, changed, len(duplicates))))
        if not apply_changes and changed:
            self.stdout.write("Run again with --apply to save.")
