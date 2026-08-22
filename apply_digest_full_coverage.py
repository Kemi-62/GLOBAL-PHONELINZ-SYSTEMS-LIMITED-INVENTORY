"""
apply_digest_full_coverage.py
================================
Closes the last gap in the rolling-window digest: Telecom Activity
(ServiceActivity) and Expenses only store a DATE in the database, so the
digest can't tell a 5pm entry from a 9pm one and has to keep filtering
those two sections by calendar day only.

This script:
1. Adds a `time` field to ServiceActivity and Expense (matching what
   RetailSale and MultiChoiceSale already have) - migration included,
   with a safe backfill default (12:00pm) for existing rows.
2. Rewrites daily_digest.py again so Telecom Activity and Expenses use
   the SAME rolling-window logic as Retail/MultiChoice/New Customers.

After this, ALL FIVE sections of the digest are gap-free.

RUN THIS AFTER apply_daily_digest_rolling_window.py.

HOW TO RUN (Replit Shell)
    python apply_digest_full_coverage.py

Then:
    python manage.py makemigrations --check   # should say "No changes detected"
    python manage.py migrate
    python manage.py check
    git add . && git commit -m "Digest: full time-of-day coverage for expenses + telecom activity" && git push

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


def patch(path, old, new, marker, label):
    content = read(path)
    if marker in content:
        print("SKIP  " + label + ": already applied, skipping.")
        return
    if old not in content:
        print("FAIL  " + label + ": couldn't find the expected anchor text in " + path + ".")
        print("      Send the current version of that file and ask for a regenerated script.")
        sys.exit(1)
    content = content.replace(old, new, 1)
    write(path, content)
    print("OK    " + label + ": patched " + path)


PREREQ_MARKER = "ROLLING WINDOW DIGEST v1"


def check_prereq():
    content = read("core/management/commands/daily_digest.py")
    if PREREQ_MARKER not in content:
        print("XX This script builds on top of apply_daily_digest_rolling_window.py.")
        print("   Run that one first: python apply_daily_digest_rolling_window.py")
        sys.exit(1)
    print("OK    Prerequisite check: rolling-window digest is in place.\n")


SA_OLD = '''    device_tag = models.ForeignKey(DeviceTag, on_delete=models.CASCADE, null=True, blank=True)
    quantity = models.PositiveIntegerField()
    date = models.DateField(auto_now_add=True)

    approved = models.BooleanField(default=False)'''

SA_NEW = '''    device_tag = models.ForeignKey(DeviceTag, on_delete=models.CASCADE, null=True, blank=True)
    quantity = models.PositiveIntegerField()
    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    approved = models.BooleanField(default=False)'''

EXPENSE_OLD = '''    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True)
    date = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.category} - {self.amount} at {self.branch.name}"'''

EXPENSE_NEW = '''    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True)
    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.category} - {self.amount} at {self.branch.name}"'''

TIME_FIELD_MARKER = "time = models.TimeField(auto_now_add=True)\n\n    approved = models.BooleanField(default=False)"
EXPENSE_TIME_MARKER = "time = models.TimeField(auto_now_add=True)\n\n    def __str__(self):\n        return f\"{self.category}"


MIGRATION_CONTENT = '''# Generated manually to match Django 5.0.2 migration style
import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0039_multichoice_hardware'),
    ]

    operations = [
        migrations.AddField(
            model_name='serviceactivity',
            name='time',
            field=models.TimeField(auto_now_add=True, default=datetime.time(12, 0)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='expense',
            name='time',
            field=models.TimeField(auto_now_add=True, default=datetime.time(12, 0)),
            preserve_default=False,
        ),
    ]
'''


DIGEST_MARKER = "FULL COVERAGE v1"

DIGEST_OLD_TOTALS = '''        total_expenses_all = Expense.objects.filter(date=end_date).aggregate(
            t=Sum("amount")
        )["t"] or 0

        new_customers = Customer.objects.filter('''

DIGEST_NEW_TOTALS = '''        # FULL COVERAGE v1 - Expenses and Telecom Activity now have a time
        # field too, so they get the same rolling-window treatment.
        expenses_all = _window_qs(Expense, Expense.objects.all())
        total_expenses_all = expenses_all.aggregate(
            t=Sum("amount")
        )["t"] or 0
        service_activities_all = _window_qs(ServiceActivity, ServiceActivity.objects.all())

        new_customers = Customer.objects.filter('''

DIGEST_OLD_BRANCH_ACTIVITY = '''            b_activities = ServiceActivity.objects.filter(branch=branch, date=end_date)
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
            )["t"] or 0'''

DIGEST_NEW_BRANCH_ACTIVITY = '''            b_activities = service_activities_all.filter(branch=branch)
            b_activity_summary = (
                b_activities.values("service_type")
                .annotate(qty=Sum("quantity"))
                .order_by("-qty")
            )

            b_att = Attendance.objects.filter(branch=branch, date=end_date)
            b_present = b_att.count()
            b_late = b_att.filter(is_late=True).count()
            b_absent = b_att.filter(is_absent=True).count()

            b_expenses = expenses_all.filter(branch=branch).aggregate(
                t=Sum("amount")
            )["t"] or 0'''

DIGEST_OLD_DIGEST_SAVE = '''                    "total_service_activities": ServiceActivity.objects.filter(date=end_date).count(),'''
DIGEST_NEW_DIGEST_SAVE = '''                    "total_service_activities": service_activities_all.count(),'''


def main():
    print("-- Applying Digest Full Coverage (Expenses + Telecom Activity) --\n")

    check_prereq()

    patch("core/models.py", SA_OLD, SA_NEW, TIME_FIELD_MARKER,
          "models.py: ServiceActivity.time field")
    patch("core/models.py", EXPENSE_OLD, EXPENSE_NEW, EXPENSE_TIME_MARKER,
          "models.py: Expense.time field")

    migration_path = os.path.join(BASE_DIR, "core", "migrations", "0040_add_time_to_activity_expense.py")
    if os.path.exists(migration_path):
        print("SKIP  migration 0040: already exists, skipping.")
    else:
        write("core/migrations/0040_add_time_to_activity_expense.py", MIGRATION_CONTENT)
        print("OK    Created core/migrations/0040_add_time_to_activity_expense.py")

    digest_content = read("core/management/commands/daily_digest.py")
    if DIGEST_MARKER in digest_content:
        print("SKIP  daily_digest.py: full coverage already applied, skipping.")
    else:
        if DIGEST_OLD_TOTALS not in digest_content:
            print("FAIL  daily_digest.py: anchor not found - has this file changed since the last script ran?")
            sys.exit(1)
        digest_content = digest_content.replace(DIGEST_OLD_TOTALS, DIGEST_NEW_TOTALS, 1)
        digest_content = digest_content.replace(DIGEST_OLD_BRANCH_ACTIVITY, DIGEST_NEW_BRANCH_ACTIVITY, 1)
        digest_content = digest_content.replace(DIGEST_OLD_DIGEST_SAVE, DIGEST_NEW_DIGEST_SAVE, 1)
        digest_content = digest_content.replace(
            "# ROLLING WINDOW DIGEST v1",
            "# ROLLING WINDOW DIGEST v1\n# FULL COVERAGE v1 - Expenses + Telecom Activity also use the rolling window",
            1,
        )
        write("core/management/commands/daily_digest.py", digest_content)
        print("OK    daily_digest.py: Expenses + Telecom Activity now use the rolling window")

    print("\n-- Done --")
    print("Next steps:")
    print("  python manage.py makemigrations --check   # should say 'No changes detected'")
    print("  python manage.py migrate")
    print("  python manage.py check")
    print("  git add . && git commit -m 'Digest: full time-of-day coverage' && git push")


if __name__ == "__main__":
    main()
