"""MC_RENEWALS_V2: each morning, tell every MultiChoice staff member how many of their customers need a renewal reminder.

    python manage.py mc_renewal_nudge            (send)
    python manage.py mc_renewal_nudge --dry-run  (preview only)
Safe to run twice a day: only one notice per person per day.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core import mc_renewals as mr
from core.models import Notification, User


class Command(BaseCommand):
    help = "Send MultiChoice staff a daily in-app notice of customers due for renewal."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        today = timezone.localdate()
        sent = 0
        for u in User.objects.filter(role="MULTICHOICE", is_active=True):
            due, overdue, _up, _lapsed = mr.bucket(mr.due_rows(u, today=today))
            n = len(due) + len(overdue)
            if not n:
                continue
            title = "%d MultiChoice customer%s to remind today" % (n, "" if n == 1 else "s")
            already = Notification.objects.filter(recipient=u, notif_type="GENERAL", title__startswith="%d MultiChoice" % n,
                                                  created_at__date=today).exists() or \
                Notification.objects.filter(recipient=u, link="/renewals-due/", created_at__date=today).exists()
            if already:
                continue
            msg = "%d due within %d days and %d overdue. Open Renewals Due and tap WhatsApp to remind them." % (
                len(due), mr.DUE_SOON_DAYS, len(overdue))
            if opts["dry_run"]:
                self.stdout.write("%s: %s" % (u.username, title))
            else:
                Notification.objects.create(recipient=u, notif_type="GENERAL", title=title, message=msg, link="/renewals-due/")
            sent += 1
        self.stdout.write(self.style.SUCCESS("%s%d notice(s)" % ("[DRY RUN] " if opts["dry_run"] else "", sent)))
