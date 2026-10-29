"""ROLES_V3: weekly email to the Director listing what the Sub Director(s) did.

Usage: python manage.py sub_director_weekly --email=director@company.com [--days=7]
"""
from datetime import timedelta
from html import escape

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.utils import timezone

from core import models as m


class Command(BaseCommand):
    help = "Email the Director a weekly list of what the Sub Director requested, approved and rejected."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--days", type=int, default=7)

    def handle(self, *args, **opts):
        days = opts["days"]
        since = timezone.now() - timedelta(days=days)
        events = (m.StockApprovalEvent.objects
                  .filter(actor__role="SUB_DIRECTOR", created_at__gte=since)
                  .select_related("actor", "request", "request__product", "request__to_branch", "request__from_branch")
                  .order_by("created_at"))
        rows = list(events)
        waiting = m.StockApprovalRequest.objects.filter(
            status="PENDING", approval_stage="DIRECTOR", requested_by__role="SUB_DIRECTOR").count()
        subject = "GPSL: Sub Director weekly activity (%s)" % timezone.localtime().strftime("%d %b %Y")
        if not m.User.objects.filter(role="SUB_DIRECTOR").exists():
            self.stdout.write("No Sub Director account exists; nothing sent.")
            return

        def line(e):
            r = e.request
            what = "%sx %s" % (r.quantity, r.product.model_name if r.product_id else "item")
            where = "%s to %s" % (r.source_label, r.dest_label) if r.kind == "MOVE" else "into %s" % r.dest_label
            act = "Requested" if e.action == "SUBMITTED" else e.action.replace("_", " ").title()
            when = timezone.localtime(e.created_at).strftime("%a %d %b, %H:%M")
            return when, e.actor.username if e.actor else "(removed)", act, "%s %s" % (what, where), (e.detail or "")

        lines = []
        for e in rows:
            try:
                lines.append(line(e))
            except Exception:
                continue
        text = ["Sub Director activity, last %d days: %d action(s)." % (days, len(lines))]
        if waiting:
            text.append("%d of their stock addition(s) are waiting for YOUR confirmation in Pending Approvals." % waiting)
        text += ["%s | %s | %s | %s" % l[:4] for l in lines] or ["Nothing this week."]
        trs = "".join(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % tuple(escape(str(x)) for x in l[:4]) for l in lines
        ) or "<tr><td colspan='4'>Nothing this week.</td></tr>"
        html = (
            "<div style=\"font-family:Segoe UI,Arial,sans-serif;max-width:720px;margin:0 auto;color:#1e293b;\">"
            "<div style='background:#004F9F;color:#fff;padding:1rem 1.4rem;border-radius:10px 10px 0 0;'>"
            "<h2 style='margin:0;font-size:1.1rem;'>Sub Director weekly activity</h2>"
            "<p style='margin:.2rem 0 0;font-size:.8rem;opacity:.85;'>Last %d days: %d action(s)</p></div>"
            "<div style='border:1px solid #e2e8f0;border-top:none;padding:1rem 1.4rem;border-radius:0 0 10px 10px;'>%s"
            "<table style='width:100%%;border-collapse:collapse;font-size:.85rem;' cellpadding='6'>"
            "<tr style='background:#f1f5f9;text-align:left;'><th>When</th><th>Who</th><th>Action</th><th>Stock</th></tr>%s</table>"
            "<p style='font-size:.75rem;color:#94a3b8;'>Full trail: Director menu, Sub Director Activity.</p></div></div>"
            % (days, len(lines),
               ("<p style='background:#fef3c7;color:#92400e;padding:.6rem .8rem;border-radius:8px;'>%d stock addition(s) from the Sub Director wait for your confirmation in Pending Approvals.</p>" % waiting) if waiting else "",
               trs)
        )
        msg = EmailMultiAlternatives(subject, "\n".join(text), settings.DEFAULT_FROM_EMAIL, [opts["email"]])
        msg.attach_alternative(html, "text/html")
        msg.send()
        self.stdout.write(self.style.SUCCESS("Sent to %s (%d action(s))" % (opts["email"], len(lines))))
