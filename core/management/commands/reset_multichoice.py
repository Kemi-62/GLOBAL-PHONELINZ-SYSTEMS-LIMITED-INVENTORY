"""MC_RESET_V1: wipe MultiChoice history and start fresh.

Deletes, for ALL MultiChoice staff (or one, with --staff):
  * MultiChoice subscription sales
  * MultiChoice hardware sales
  * weekly reports and their balance history
  * commission payment records tied to MultiChoice staff
KEEPS: users, branches, decoder/accessory stock quantities (unless --include-hardware-stock),
customer CRM, and everything from retail, telecom and stock.

Afterwards each MultiChoice staff member gets a new open week at N0.

    python manage.py reset_multichoice                       preview only, deletes nothing
    python manage.py reset_multichoice --confirm "RESET MULTICHOICE"
    python manage.py reset_multichoice --staff mc_okobo --confirm "RESET MULTICHOICE"

Before deleting, every row is saved to backups/mc_reset_<timestamp>.json.
Take a full database backup first as well (Director > Backups > Run Backup Now).
"""
import json
from pathlib import Path

from django.core import serializers
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core import models as m
from core.mc_weekly import heal_staff

PHRASE = "RESET MULTICHOICE"


class Command(BaseCommand):
    help = "Delete all MultiChoice sales, balances and weekly reports and start fresh at zero."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", default="")
        parser.add_argument("--staff", default="", help="Only this MultiChoice username")
        parser.add_argument("--include-hardware-stock", action="store_true",
                            help="Also zero the decoder / accessory stock quantities")

    def handle(self, *args, **opts):
        staff = m.User.objects.filter(role="MULTICHOICE")
        if opts["staff"]:
            staff = staff.filter(username=opts["staff"])
            if not staff.exists():
                raise CommandError("No MultiChoice user called %r" % opts["staff"])
        ids = list(staff.values_list("id", flat=True))
        sets = [
            ("subscription sales", m.MultiChoiceSale.objects.filter(staff_id__in=ids)),
            ("hardware sales", m.MultiChoiceHardwareSale.objects.filter(staff_id__in=ids)),
            ("balance history rows", m.MultiChoiceBalance.objects.filter(weekly_report__staff_id__in=ids)),
            ("weekly reports", m.MultiChoiceWeeklyReport.objects.filter(staff_id__in=ids)),
            ("commission payment records", m.CommissionPayment.objects.filter(staff_id__in=ids)),
        ]
        if opts["include_hardware_stock"]:
            sets.append(("hardware stock rows", m.MultiChoiceHardwareStock.objects.filter(staff_id__in=ids)))

        self.stdout.write("MultiChoice staff affected: %s" % ", ".join(staff.values_list("username", flat=True)))
        for label, qs in sets:
            self.stdout.write("  %-28s %d" % (label, qs.count()))
        if opts["confirm"] != PHRASE:
            self.stdout.write(self.style.WARNING(
                '\nPREVIEW ONLY. Nothing was deleted. To go ahead run again with --confirm "%s"' % PHRASE))
            return

        Path("backups").mkdir(exist_ok=True)
        path = Path("backups") / ("mc_reset_%s.json" % timezone.now().strftime("%Y%m%d_%H%M%S"))
        with open(path, "w", encoding="utf-8") as f:
            f.write("[")
            first = True
            for _label, qs in sets:
                for obj in qs.iterator():
                    if not first:
                        f.write(",")
                    f.write(serializers.serialize("json", [obj])[1:-1])
                    first = False
            f.write("]")
        self.stdout.write("Saved a copy of every row to %s" % path)

        with transaction.atomic():
            # children first
            m.CommissionPayment.objects.filter(staff_id__in=ids).delete()
            m.MultiChoiceBalance.objects.filter(weekly_report__staff_id__in=ids).delete()
            m.MultiChoiceWeeklyReport.objects.filter(staff_id__in=ids).delete()
            m.MultiChoiceSale.objects.filter(staff_id__in=ids).delete()
            m.MultiChoiceHardwareSale.objects.filter(staff_id__in=ids).delete()
            if opts["include_hardware_stock"]:
                m.MultiChoiceHardwareStock.objects.filter(staff_id__in=ids).update(quantity=0)
            for u in staff:
                if u.branch_id:
                    heal_staff(u, log=lambda msg: None)
        self.stdout.write(self.style.SUCCESS("Done. Each MultiChoice staff member now has a fresh week at N0."))
