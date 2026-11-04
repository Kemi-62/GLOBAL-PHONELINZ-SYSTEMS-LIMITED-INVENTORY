#!/usr/bin/env python3
"""
apply_mc_reconciliation.py   (marker: MC_COMMISSION_V2)

Run after apply_mc_commission_split.py. Finds the REAL MultiChoice commission.

  * Each week, BEFORE the first sale, the MultiChoice staff member enters the real balance
    from the MultiChoice app and attaches a screenshot. Sales are blocked until then.
  * The system compares it with the balance it expected (last week's closing + top-ups, less costs).
      - Higher by more than N50  -> commission detected, waits for the Director to confirm
      - Lower by more than N50   -> shortage, flagged for the Director to review
      - Within N50               -> matched
  * The week then opens with the REAL balance, so errors never pile up.
  * "Can't check right now?" lets a staff member skip with a reason (the Director is told).
  * Director and Sub Director: new page "MC Commission" to confirm or reject, see shortages,
    skipped checks, and confirmed commission by month and staff.
  * The staff dashboard commission card now shows CONFIRMED commission for the month.
  * The expected balance is never shown to staff.

NEEDS a migration:  python apply_mc_reconciliation.py   then   python manage.py migrate
Safe to run twice; checks everything before writing anything.
"""
import os, re, sys, shutil
ROOT = os.getcwd()
MARK = "MC_COMMISSION_V2"
PATCHES = [('core/models.py',
  'class CommissionPayment(models.Model):',
  'class MultiChoiceBalanceCheck(models.Model):  # MC_COMMISSION_V2\n'
  '    """The real MultiChoice wallet balance entered at the start of a week, compared with what the system expected."""\n'
  '    STATUS = (\n'
  '        ("BASELINE", "First balance (starting point)"),\n'
  '        ("MATCHED", "Matched"),\n'
  '        ("COMMISSION", "Commission detected (waiting)"),\n'
  '        ("COMMISSION_OK", "Commission confirmed"),\n'
  '        ("REJECTED", "Commission rejected"),\n'
  '        ("SHORTAGE", "Shortage (to review)"),\n'
  '        ("SHORTAGE_REVIEWED", "Shortage reviewed"),\n'
  '        ("SKIPPED", "Skipped"),\n'
  '    )\n'
  "    staff = models.ForeignKey('User', on_delete=models.CASCADE, related_name='mc_balance_checks')\n"
  "    branch = models.ForeignKey('Branch', on_delete=models.CASCADE)\n"
  "    weekly_report = models.ForeignKey('MultiChoiceWeeklyReport', on_delete=models.CASCADE, related_name='balance_checks')\n"
  '    checked_at = models.DateTimeField(auto_now_add=True)\n'
  '    expected_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)\n'
  '    actual_balance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)\n'
  '    difference = models.DecimalField(max_digits=12, decimal_places=2, default=0)\n'
  '    status = models.CharField(max_length=20, choices=STATUS, default="MATCHED")\n'
  "    screenshot = models.ImageField(upload_to='mc_balance_proofs/', null=True, blank=True)\n"
  "    note = models.TextField(blank=True, default='')\n"
  "    decided_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='mc_balance_decisions')\n"
  '    decided_at = models.DateTimeField(null=True, blank=True)\n'
  "    decision_note = models.TextField(blank=True, default='')\n"
  '\n'
  '    class Meta:\n'
  "        ordering = ['-checked_at']\n"
  '\n'
  '    def __str__(self):\n'
  '        return "%s %s %s" % (self.staff.username, self.get_status_display(), self.checked_at)\n'
  '\n'
  '\n'
  'class CommissionPayment(models.Model):',
  'model: MultiChoiceBalanceCheck'),
 ('core/views.py',
  '        cost_price     = Decimal(request.POST.get("cost_price") or "0")\n',
  '        from core import mc_commission as _mcc  # MC_COMMISSION_V2: real balance first, every week\n'
  '        if _mcc.needs_check(request.user, weekly_report):\n'
  '            messages.error(request, "Please enter your MultiChoice balance for this week before recording sales.")\n'
  '            return redirect("multichoice_dashboard")\n'
  '        cost_price     = Decimal(request.POST.get("cost_price") or "0")\n',
  'sale view: weekly balance gate'),
 ('core/views.py',
  '        "renewals_due_count": _mc_renewals_due_count(request.user),  # MC_RENEWALS_V2\n',
  '        "renewals_due_count": _mc_renewals_due_count(request.user),  # MC_RENEWALS_V2\n'
  '        "needs_balance_check": __import__("core.mc_commission", fromlist=["x"]).needs_check(request.user, weekly_report),  # '
  'MC_COMMISSION_V2\n'
  '        "month_commission": __import__("core.mc_commission", fromlist=["x"]).month_commission(request.user),  # MC_COMMISSION_V2\n',
  'dashboard: balance gate and confirmed commission'),
 ('core/urls.py',
  'from . import mc_renewals as mcr  # MC_RENEWALS_V1',
  'from . import mc_renewals as mcr  # MC_RENEWALS_V1\nfrom . import mc_commission_views as mcv  # MC_COMMISSION_V2',
  'urls: import'),
 ('core/urls.py',
  "    path('renewals-due/', mcr.mc_renewals, name='mc_renewals'),  # MC_RENEWALS_V1",
  "    path('renewals-due/', mcr.mc_renewals, name='mc_renewals'),  # MC_RENEWALS_V1\n"
  "    path('multichoice/balance-check/', mcv.mc_balance_check, name='mc_balance_check'),  # MC_COMMISSION_V2\n"
  "    path('director/mc-commission/', mcv.mc_commission_review, name='mc_commission_review'),  # MC_COMMISSION_V2\n"
  "    path('director/mc-commission/<int:pk>/decide/', mcv.mc_commission_decide, name='mc_commission_decide'),  # MC_COMMISSION_V2",
  'urls: routes'),
 ('core/mc_weekly.py',
  '    if report.opening_balance == expected:\n        return "ok"\n    if report.is_closed:',
  '    if report.opening_balance == expected:\n'
  '        return "ok"\n'
  "    try:  # MC_COMMISSION_V2: a week opened with the staff member's REAL balance is correct by design\n"
  '        from core.models import MultiChoiceBalanceCheck\n'
  '        _chk = MultiChoiceBalanceCheck.objects.filter(weekly_report=report).exclude(status="SKIPPED").order_by("-id").first()\n'
  '        if _chk is not None and _chk.actual_balance is not None and report.opening_balance == _chk.actual_balance - '
  'report.additional_funds:\n'
  '            return "ok"\n'
  '    except Exception:\n'
  '        pass\n'
  '    if report.is_closed:',
  'weekly self-heal: accept a real-balance opening'),
 ('templates/multichoice_dashboard.html',
  '  {% if weekly_report and not weekly_report.is_closed %}\n  <div class="card">\n    <p class="card-title">📺 Record New Subscription</p>',
  '  {% if needs_balance_check %}{# MC_COMMISSION_V2 #}\n'
  '  <div class="card">\n'
  '    <p class="card-title">💳 Enter your MultiChoice balance first</p>\n'
  '    <p style="font-size:.85rem;color:#6b7280;margin:0 0 1rem;">New week. Open the MultiChoice app, read your wallet balance, type it '
  'below and attach a screenshot. If you topped up, record it under Add Funds first. You can record sales straight after.</p>\n'
  '    <form method="POST" action="{% url \'mc_balance_check\' %}" enctype="multipart/form-data">\n'
  '      {% csrf_token %}\n'
  '      <div class="form-row">\n'
  '        <div class="form-group"><label>Balance in the MultiChoice app (₦) *</label><input type="number" name="actual_balance" '
  'step="0.01" min="0" required placeholder="e.g. 52000"></div>\n'
  '        <div class="form-group"><label>Screenshot of the balance *</label><input type="file" name="screenshot" accept="image/*" '
  'required></div>\n'
  '      </div>\n'
  '      <div class="form-group"><label>Note (optional)</label><input type="text" name="note" placeholder="Anything the Director should '
  'know"></div>\n'
  '      <button type="submit" class="btn-sm btn-success" style="width:100%;">✔ Save balance</button>\n'
  '    </form>\n'
  '    <details style="margin-top:1rem;"><summary style="cursor:pointer;font-size:.8rem;color:#6b7280;">Can\'t check the app right '
  'now?</summary>\n'
  '      <form method="POST" action="{% url \'mc_balance_check\' %}" style="margin-top:.6rem;">\n'
  '        {% csrf_token %}\n'
  '        <input type="text" name="skip_reason" required placeholder="Why can\'t you check? (the Director is told)" '
  'style="width:100%;margin-bottom:.5rem;">\n'
  '        <button type="submit" class="btn-sm btn-outline">Skip this week</button>\n'
  '      </form>\n'
  '    </details>\n'
  '  </div>\n'
  '  {% elif weekly_report and not weekly_report.is_closed %}\n'
  '  <div class="card">\n'
  '    <p class="card-title">📺 Record New Subscription</p>',
  'dashboard: balance check card before sales'),
 ('templates/multichoice_dashboard.html',
  '    <p class="kpi-label">Commission</p>\n'
  '    <p class="kpi-value">₦{% if weekly_report %}{{ weekly_report.commission|floatformat:0 }}{% else %}0{% endif %}</p>',
  '    <p class="kpi-label">Commission (confirmed, this month)</p>\n'
  '    <p class="kpi-value">₦{{ month_commission|floatformat:0 }}</p>{# MC_COMMISSION_V2 #}',
  'dashboard: commission card shows confirmed commission'),
 ('templates/multichoice_dashboard.html',
  'Commission earned: <strong>₦{{ weekly_report.commission|floatformat:2 }}</strong> &middot; Service charge:',
  'Service charge:',
  'dashboard: closed-week banner no longer shows the old commission'),
 ('templates/multichoice_dashboard.html',
  '<tr style="background:#d1fae5;"><td><strong>Commission Earned</strong></td><td><strong style="color:#065f46;font-size:1.1rem;">₦{{ '
  'weekly_report.commission|floatformat:2 }}</strong></td></tr>',
  '<tr style="background:#d1fae5;"><td><strong>Commission (confirmed, this month)</strong></td><td><strong '
  'style="color:#065f46;font-size:1.1rem;">₦{{ month_commission|floatformat:2 }}</strong></td></tr>',
  'dashboard: weekly summary shows confirmed commission'),
 ('templates/base.html',
  '                <span class="icon">📺</span> MC Retention\n            </a>',
  '                <span class="icon">📺</span> MC Retention\n'
  '            </a>\n'
  '            <a href="{% url \'mc_commission_review\' %}" class="sidebar-link">{# MC_COMMISSION_V2 #}\n'
  '                <span class="icon">💳</span> MC Commission\n'
  '            </a>',
  'sidebar: Director link'),
 ('templates/base.html',
  '        <a href="{% url \'mc_renewals\' %}" class="sidebar-link">{# MC_RENEWALS_V1 #}\n'
  '            <span class="icon">🔔</span> MultiChoice Renewals\n'
  '        </a>',
  '        <a href="{% url \'mc_renewals\' %}" class="sidebar-link">{# MC_RENEWALS_V1 #}\n'
  '            <span class="icon">🔔</span> MultiChoice Renewals\n'
  '        </a>\n'
  '        <a href="{% url \'mc_commission_review\' %}" class="sidebar-link">{# MC_COMMISSION_V2 #}\n'
  '            <span class="icon">💳</span> MC Commission\n'
  '        </a>',
  'sidebar: Sub Director link')]
NEWFILES = {'core/mc_commission.py': '"""MC_COMMISSION_V2: real MultiChoice commission, found by comparing the real wallet balance\n'
                          'with the balance the system expects.\n'
                          '\n'
                          'Each week, BEFORE the first sale, the MultiChoice staff member enters the real balance shown in the\n'
                          'MultiChoice app (with a screenshot). The system compares it with what it expected\n'
                          "(last week's closing + any top-ups). A higher real balance is commission (pending until the Director\n"
                          'confirms it); a lower one is a shortage. The week then opens with the REAL balance.\n'
                          '"""\n'
                          'from datetime import timedelta\n'
                          'from decimal import Decimal\n'
                          '\n'
                          'from django.db.models import Sum\n'
                          'from django.utils import timezone\n'
                          '\n'
                          'from core import models as m\n'
                          '\n'
                          'TOLERANCE = Decimal("50")        # differences up to this (naira) count as a match\n'
                          'MAX_IMAGE_BYTES = 5 * 1024 * 1024\n'
                          '\n'
                          '\n'
                          'def _week_sales(report):\n'
                          '    return m.MultiChoiceSale.objects.filter(\n'
                          '        staff=report.staff, branch=report.branch,\n'
                          '        date__gte=report.week_start_date, date__lt=report.week_start_date + timedelta(days=7),\n'
                          '        is_voided=False,\n'
                          '    )\n'
                          '\n'
                          '\n'
                          'def needs_check(user, report):\n'
                          '    """True when the staff member must enter the real balance before recording sales."""\n'
                          '    if report is None or report.is_closed or getattr(user, "role", "") != "MULTICHOICE":\n'
                          '        return False\n'
                          '    if m.MultiChoiceBalanceCheck.objects.filter(weekly_report=report).exists():\n'
                          '        return False\n'
                          '    if _week_sales(report).exists():       # week already running (for example rollout day): no gate\n'
                          '        return False\n'
                          '    return True\n'
                          '\n'
                          '\n'
                          'def _notify_approvers(title, message):\n'
                          '    for u in m.User.objects.filter(role__in=("DIRECTOR", "SUB_DIRECTOR"), is_active=True):\n'
                          '        m.Notification.objects.create(recipient=u, notif_type="GENERAL", title=title,\n'
                          '                                      message=message, link="/director/mc-commission/")\n'
                          '\n'
                          '\n'
                          'def record_check(user, report, actual=None, screenshot=None, note="", skip_reason=""):\n'
                          '    """Save a week-start check. Returns the MultiChoiceBalanceCheck."""\n'
                          '    expected = report.opening_balance + report.additional_funds\n'
                          '    has_prev = m.MultiChoiceWeeklyReport.objects.filter(\n'
                          '        staff=report.staff, week_start_date__lt=report.week_start_date).exists()\n'
                          '    if skip_reason.strip():\n'
                          '        chk = m.MultiChoiceBalanceCheck.objects.create(\n'
                          '            staff=user, branch=report.branch, weekly_report=report, expected_balance=expected,\n'
                          '            status="SKIPPED", note=skip_reason.strip())\n'
                          '        _notify_approvers("MultiChoice balance check skipped",\n'
                          '                          "%s skipped the week-start balance check: %s" % (user.username, '
                          'skip_reason.strip()))\n'
                          '        return chk\n'
                          '    actual = Decimal(actual)\n'
                          '    diff = actual - expected\n'
                          '    if not has_prev:\n'
                          '        status = "BASELINE"\n'
                          '    elif abs(diff) <= TOLERANCE:\n'
                          '        status = "MATCHED"\n'
                          '    elif diff > 0:\n'
                          '        status = "COMMISSION"\n'
                          '    else:\n'
                          '        status = "SHORTAGE"\n'
                          '    chk = m.MultiChoiceBalanceCheck.objects.create(\n'
                          '        staff=user, branch=report.branch, weekly_report=report, expected_balance=expected,\n'
                          '        actual_balance=actual, difference=diff, status=status, screenshot=screenshot, note=(note or '
                          '"").strip())\n'
                          '    # the week opens with the REAL balance\n'
                          '    report.opening_balance = actual - report.additional_funds\n'
                          '    report.save(update_fields=["opening_balance"])\n'
                          '    if status == "COMMISSION":\n'
                          '        _notify_approvers("MultiChoice commission detected",\n'
                          '                          "%s: N%s more than expected in the wallet. Open MC Commission to confirm." % '
                          '(user.username, "{:,.2f}".format(diff)))\n'
                          '    elif status == "SHORTAGE":\n'
                          '        _notify_approvers("MultiChoice balance SHORTAGE",\n'
                          '                          "%s: wallet is N%s lower than expected. Open MC Commission to review." % '
                          '(user.username, "{:,.2f}".format(-diff)))\n'
                          '    return chk\n'
                          '\n'
                          '\n'
                          'def month_commission(user, today=None):\n'
                          '    """Confirmed commission for this staff member in the current month."""\n'
                          '    today = today or timezone.localdate()\n'
                          '    qs = m.MultiChoiceBalanceCheck.objects.filter(\n'
                          '        staff=user, status="COMMISSION_OK", checked_at__year=today.year, checked_at__month=today.month)\n'
                          '    return qs.aggregate(t=Sum("difference"))["t"] or Decimal("0")\n',
 'core/mc_commission_views.py': '"""MC_COMMISSION_V2 views."""\n'
                                'from datetime import timedelta\n'
                                'from decimal import Decimal, InvalidOperation\n'
                                '\n'
                                'from django.contrib import messages\n'
                                'from django.db.models import Sum\n'
                                'from django.shortcuts import get_object_or_404, redirect, render\n'
                                'from django.utils import timezone\n'
                                '\n'
                                'from core import mc_commission as mcc\n'
                                'from core import models as m\n'
                                'from core.utils.decorators import role_required\n'
                                '\n'
                                '\n'
                                'def _open_week(user):\n'
                                '    return m.MultiChoiceWeeklyReport.objects.filter(\n'
                                '        staff=user, branch=user.branch, is_closed=False).order_by("-id").first()\n'
                                '\n'
                                '\n'
                                '@role_required("MULTICHOICE")\n'
                                'def mc_balance_check(request):\n'
                                '    if request.method != "POST":\n'
                                '        return redirect("multichoice_dashboard")\n'
                                '    report = _open_week(request.user)\n'
                                '    if report is None or not mcc.needs_check(request.user, report):\n'
                                '        messages.info(request, "Your balance check for this week is already done.")\n'
                                '        return redirect("multichoice_dashboard")\n'
                                '    skip = (request.POST.get("skip_reason") or "").strip()\n'
                                '    if skip:\n'
                                '        mcc.record_check(request.user, report, skip_reason=skip)\n'
                                '        messages.warning(request, "Check skipped. The Director has been told. You can record sales '
                                'now.")\n'
                                '        return redirect("multichoice_dashboard")\n'
                                '    try:\n'
                                '        actual = Decimal(request.POST.get("actual_balance") or "")\n'
                                '        if actual < 0:\n'
                                '            raise InvalidOperation\n'
                                '    except InvalidOperation:\n'
                                '        messages.error(request, "Enter the balance exactly as shown in the MultiChoice app.")\n'
                                '        return redirect("multichoice_dashboard")\n'
                                '    shot = request.FILES.get("screenshot")\n'
                                '    if not shot:\n'
                                '        messages.error(request, "Please attach a screenshot of the balance in the MultiChoice app.")\n'
                                '        return redirect("multichoice_dashboard")\n'
                                '    if not (getattr(shot, "content_type", "") or "").startswith("image/") or shot.size > '
                                'mcc.MAX_IMAGE_BYTES:\n'
                                '        messages.error(request, "The screenshot must be an image under 5 MB.")\n'
                                '        return redirect("multichoice_dashboard")\n'
                                '    mcc.record_check(request.user, report, actual=actual, screenshot=shot, note=request.POST.get("note", '
                                '""))\n'
                                '    messages.success(request, "Balance saved. You can record sales now.")\n'
                                '    return redirect("multichoice_dashboard")\n'
                                '\n'
                                '\n'
                                '@role_required("DIRECTOR", "SUB_DIRECTOR")\n'
                                'def mc_commission_review(request):\n'
                                '    checks = m.MultiChoiceBalanceCheck.objects.select_related("staff", "branch", "weekly_report", '
                                '"decided_by")\n'
                                '    pending = checks.filter(status="COMMISSION").order_by("-checked_at")\n'
                                '    shortages = checks.filter(status="SHORTAGE").order_by("-checked_at")\n'
                                '    skipped = checks.filter(status="SKIPPED").order_by("-checked_at")[:20]\n'
                                '    recent = checks.exclude(status__in=("COMMISSION", "SHORTAGE")).order_by("-checked_at")[:40]\n'
                                '    monthly = {}\n'
                                '    for c in checks.filter(status="COMMISSION_OK"):\n'
                                '        key = timezone.localtime(c.checked_at).strftime("%Y-%m")\n'
                                '        row = monthly.setdefault(key, {"month": key, "total": Decimal("0"), "by_staff": {}})\n'
                                '        row["total"] += c.difference\n'
                                '        row["by_staff"][c.staff.username] = row["by_staff"].get(c.staff.username, Decimal("0")) + '
                                'c.difference\n'
                                '    months = sorted(monthly.values(), key=lambda r: r["month"], reverse=True)\n'
                                '    for r in months:\n'
                                '        r["by_staff"] = sorted(r["by_staff"].items())\n'
                                '    return render(request, "director/mc_commission.html", {\n'
                                '        "pending": pending, "shortages": shortages, "skipped": skipped, "recent": recent, "months": '
                                'months,\n'
                                '        "tolerance": mcc.TOLERANCE,\n'
                                '    })\n'
                                '\n'
                                '\n'
                                '@role_required("DIRECTOR", "SUB_DIRECTOR")\n'
                                'def mc_commission_decide(request, pk):\n'
                                '    if request.method != "POST":\n'
                                '        return redirect("mc_commission_review")\n'
                                '    chk = get_object_or_404(m.MultiChoiceBalanceCheck, pk=pk)\n'
                                '    action = request.POST.get("action")\n'
                                '    note = (request.POST.get("note") or "").strip()\n'
                                '    if chk.status == "COMMISSION" and action in ("confirm", "reject"):\n'
                                '        if action == "reject" and not note:\n'
                                '            messages.error(request, "Please say why you are rejecting it (for example, an unrecorded '
                                'top-up).")\n'
                                '            return redirect("mc_commission_review")\n'
                                '        chk.status = "COMMISSION_OK" if action == "confirm" else "REJECTED"\n'
                                '    elif chk.status == "SHORTAGE" and action == "review":\n'
                                '        chk.status = "SHORTAGE_REVIEWED"\n'
                                '    else:\n'
                                '        messages.error(request, "That entry has already been dealt with.")\n'
                                '        return redirect("mc_commission_review")\n'
                                '    chk.decided_by = request.user\n'
                                '    chk.decided_at = timezone.now()\n'
                                '    chk.decision_note = note\n'
                                '    chk.save()\n'
                                '    messages.success(request, "Saved.")\n'
                                '    return redirect("mc_commission_review")\n',
 'templates/director/mc_commission.html': '{% extends "base.html" %}\n'
                                          '{# MC_COMMISSION_V2 #}\n'
                                          '{% block content %}\n'
                                          '<style>\n'
                                          '.mk-t{font-size:1.3rem;font-weight:700;color:#004F9F;margin:0 0 .3rem}\n'
                                          '.mk-s{font-size:.85rem;color:#6b7280;margin:0 0 1.1rem}\n'
                                          '.mk-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:1rem '
                                          '1.1rem;margin-bottom:1rem;overflow-x:auto}\n'
                                          '.mk-card h3{font-size:.95rem;margin:0 0 .7rem}\n'
                                          '.mk-tb{width:100%;border-collapse:collapse;font-size:.82rem}\n'
                                          '.mk-tb th{background:#004F9F;color:#fff;padding:.5rem .6rem;text-align:left}\n'
                                          '.mk-tb td{padding:.5rem .6rem;border-bottom:1px solid #f1f5f9;vertical-align:top}\n'
                                          '.mk-b{padding:.35rem '
                                          '.7rem;border:none;border-radius:6px;font-weight:600;font-size:.78rem;cursor:pointer;color:#fff}\n'
                                          '.mk-ok{background:#16a34a}.mk-no{background:#dc2626}.mk-rv{background:#2563eb}\n'
                                          '.mk-in{padding:.3rem .5rem;border:1px solid '
                                          '#d1d5db;border-radius:6px;font-size:.78rem;width:150px}\n'
                                          '.mk-pos{color:#166534;font-weight:700}.mk-neg{color:#b91c1c;font-weight:700}\n'
                                          '</style>\n'
                                          '<h1 class="mk-t">💳 MultiChoice Commission</h1>\n'
                                          '<p class="mk-s">Each week the staff enter the real MultiChoice balance with a screenshot. A '
                                          'higher balance than expected is commission, shown here until you confirm it. Differences under '
                                          '₦{{ tolerance|floatformat:0 }} are ignored.</p>\n'
                                          '\n'
                                          '<div class="mk-card">\n'
                                          '  <h3>Commission waiting for you ({{ pending|length }})</h3>\n'
                                          '  {% if pending %}<table '
                                          'class="mk-tb"><thead><tr><th>Date</th><th>Staff</th><th>Branch</th><th>Expected</th><th>Real '
                                          'balance</th><th>Commission</th><th>Proof</th><th>Decision</th></tr></thead><tbody>\n'
                                          '  {% for c in pending %}\n'
                                          '  <tr><td>{{ c.checked_at|date:"d M Y" }}</td><td>{{ c.staff.username }}</td><td>{{ '
                                          'c.branch.name }}</td>\n'
                                          '    <td>₦{{ c.expected_balance|floatformat:2 }}</td><td>₦{{ c.actual_balance|floatformat:2 '
                                          '}}</td>\n'
                                          '    <td class="mk-pos">+₦{{ c.difference|floatformat:2 }}</td>\n'
                                          '    <td>{% if c.screenshot %}<a href="{{ c.screenshot.url }}" target="_blank" '
                                          'rel="noopener">View</a>{% else %}none{% endif %}{% if c.note %}<br><small>{{ c.note '
                                          '}}</small>{% endif %}</td>\n'
                                          '    <td><form method="POST" action="{% url \'mc_commission_decide\' c.pk %}" '
                                          'style="display:flex;gap:.3rem;flex-wrap:wrap;">{% csrf_token %}\n'
                                          '      <input class="mk-in" name="note" placeholder="Note (needed to reject)">\n'
                                          '      <button class="mk-b mk-ok" name="action" value="confirm">Confirm</button>\n'
                                          '      <button class="mk-b mk-no" name="action" value="reject">Reject</button></form></td></tr>\n'
                                          '  {% endfor %}</tbody></table>{% else %}<p class="mk-s">Nothing waiting.</p>{% endif %}\n'
                                          '</div>\n'
                                          '\n'
                                          '<div class="mk-card">\n'
                                          '  <h3>Shortages: wallet lower than expected ({{ shortages|length }})</h3>\n'
                                          '  {% if shortages %}<table '
                                          'class="mk-tb"><thead><tr><th>Date</th><th>Staff</th><th>Branch</th><th>Expected</th><th>Real '
                                          'balance</th><th>Short by</th><th>Proof</th><th></th></tr></thead><tbody>\n'
                                          '  {% for c in shortages %}\n'
                                          '  <tr><td>{{ c.checked_at|date:"d M Y" }}</td><td>{{ c.staff.username }}</td><td>{{ '
                                          'c.branch.name }}</td>\n'
                                          '    <td>₦{{ c.expected_balance|floatformat:2 }}</td><td>₦{{ c.actual_balance|floatformat:2 '
                                          '}}</td>\n'
                                          '    <td class="mk-neg">₦{{ c.difference|floatformat:2 }}</td>\n'
                                          '    <td>{% if c.screenshot %}<a href="{{ c.screenshot.url }}" target="_blank" '
                                          'rel="noopener">View</a>{% endif %}</td>\n'
                                          '    <td><form method="POST" action="{% url \'mc_commission_decide\' c.pk %}" '
                                          'style="display:flex;gap:.3rem;">{% csrf_token %}\n'
                                          '      <input class="mk-in" name="note" placeholder="What you found">\n'
                                          '      <button class="mk-b mk-rv" name="action" value="review">Mark '
                                          'reviewed</button></form></td></tr>\n'
                                          '  {% endfor %}</tbody></table>{% else %}<p class="mk-s">No shortages.</p>{% endif %}\n'
                                          '</div>\n'
                                          '\n'
                                          '<div class="mk-card">\n'
                                          '  <h3>Confirmed commission by month</h3>\n'
                                          '  {% if months %}<table class="mk-tb"><thead><tr><th>Month</th><th>Total</th><th>By '
                                          'staff</th></tr></thead><tbody>\n'
                                          '  {% for r in months %}<tr><td>{{ r.month }}</td><td class="mk-pos">₦{{ r.total|floatformat:2 '
                                          '}}</td>\n'
                                          '    <td>{% for name, amt in r.by_staff %}{{ name }}: ₦{{ amt|floatformat:2 }}{% if not '
                                          'forloop.last %}<br>{% endif %}{% endfor %}</td></tr>{% endfor %}\n'
                                          '  </tbody></table>{% else %}<p class="mk-s">No confirmed commission yet.</p>{% endif %}\n'
                                          '</div>\n'
                                          '\n'
                                          '{% if skipped %}<div class="mk-card"><h3>Skipped checks</h3><table '
                                          'class="mk-tb"><thead><tr><th>Date</th><th>Staff</th><th>Branch</th><th>Reason</th></tr></thead><tbody>\n'
                                          '{% for c in skipped %}<tr><td>{{ c.checked_at|date:"d M Y" }}</td><td>{{ c.staff.username '
                                          '}}</td><td>{{ c.branch.name }}</td><td>{{ c.note }}</td></tr>{% endfor '
                                          '%}</tbody></table></div>{% endif %}\n'
                                          '\n'
                                          '<div class="mk-card">\n'
                                          '  <h3>Recent checks</h3>\n'
                                          '  <table class="mk-tb"><thead><tr><th>Date</th><th>Staff</th><th>Result</th><th>Real '
                                          'balance</th><th>Difference</th><th>Decided by</th></tr></thead><tbody>\n'
                                          '  {% for c in recent %}<tr><td>{{ c.checked_at|date:"d M Y" }}</td><td>{{ c.staff.username '
                                          '}}</td><td>{{ c.get_status_display }}</td>\n'
                                          '    <td>{% if c.actual_balance is not None %}₦{{ c.actual_balance|floatformat:2 }}{% endif '
                                          '%}</td><td>{{ c.difference|floatformat:2 }}</td>\n'
                                          '    <td>{{ c.decided_by.username|default:"" }}{% if c.decision_note %}<br><small>{{ '
                                          'c.decision_note }}</small>{% endif %}</td></tr>\n'
                                          '  {% empty %}<tr><td colspan="6">No checks yet.</td></tr>{% endfor %}</tbody></table>\n'
                                          '</div>\n'
                                          '{% endblock %}\n'}
MIGRATION = '# MC_COMMISSION_V2\nfrom django.conf import settings\nfrom django.db import migrations, models\nimport django.db.models.deletion\n\n\nclass Migration(migrations.Migration):\n\n    dependencies = [\n        ("core", "@@LAST@@"),\n    ]\n\n    operations = [\n        migrations.CreateModel(\n            name="MultiChoiceBalanceCheck",\n            fields=[\n                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),\n                ("checked_at", models.DateTimeField(auto_now_add=True)),\n                ("expected_balance", models.DecimalField(decimal_places=2, default=0, max_digits=12)),\n                ("actual_balance", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),\n                ("difference", models.DecimalField(decimal_places=2, default=0, max_digits=12)),\n                ("status", models.CharField(choices=[("BASELINE", "First balance (starting point)"), ("MATCHED", "Matched"), ("COMMISSION", "Commission detected (waiting)"), ("COMMISSION_OK", "Commission confirmed"), ("REJECTED", "Commission rejected"), ("SHORTAGE", "Shortage (to review)"), ("SHORTAGE_REVIEWED", "Shortage reviewed"), ("SKIPPED", "Skipped")], default="MATCHED", max_length=20)),\n                ("screenshot", models.ImageField(blank=True, null=True, upload_to="mc_balance_proofs/")),\n                ("note", models.TextField(blank=True, default="")),\n                ("decided_at", models.DateTimeField(blank=True, null=True)),\n                ("decision_note", models.TextField(blank=True, default="")),\n                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="core.branch")),\n                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="mc_balance_decisions", to=settings.AUTH_USER_MODEL)),\n                ("staff", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="mc_balance_checks", to=settings.AUTH_USER_MODEL)),\n                ("weekly_report", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="balance_checks", to="core.multichoiceweeklyreport")),\n            ],\n            options={"ordering": ["-checked_at"]},\n        ),\n    ]\n'

def p(rel): return os.path.join(ROOT, *rel.split("/"))
def read(rel):
    with open(p(rel), encoding="utf-8") as f: return f.read()
if not os.path.exists(p("manage.py")) or not os.path.isdir(p("core")):
    print("ABORT: run this from the folder that contains manage.py"); sys.exit(1)
if "MC_COMMISSION_V1" not in read("core/models.py"):
    print("ABORT: apply_mc_commission_split.py has not been applied yet."); sys.exit(1)
texts, errors, plan = {}, [], []
for rel, old, new, label in PATCHES:
    if not os.path.exists(p(rel)):
        errors.append("missing file: " + rel); continue
    t = texts.get(rel) or read(rel)
    if new in t: plan.append(("SKIP", label)); texts[rel] = t; continue
    if t.count(old) != 1:
        errors.append("%s: expected 1 match for [%s], found %d" % (rel, label, t.count(old))); texts[rel] = t; continue
    texts[rel] = t.replace(old, new, 1); plan.append(("OK", label))
if errors:
    print("ABORT: nothing was changed.\n"); [print("  -", e) for e in errors]; sys.exit(1)
changed = [r for r, t in texts.items() if t != read(r)]
for rel in changed:
    b = p(rel) + ".pre_mcrecon.bak"
    if not os.path.exists(b): shutil.copy2(p(rel), b)
    with open(p(rel), "w", encoding="utf-8", newline="") as f: f.write(texts[rel])
wrote = False
for rel, content in NEWFILES.items():
    if os.path.exists(p(rel)) and read(rel) == content:
        plan.append(("SKIP", "file " + rel)); continue
    os.makedirs(os.path.dirname(p(rel)), exist_ok=True)
    with open(p(rel), "w", encoding="utf-8", newline="") as f: f.write(content)
    plan.append(("OK", "file " + rel)); wrote = True
mig_dir = p("core/migrations")
nums = sorted(f for f in os.listdir(mig_dir) if re.match(r"^\d{4}_.*\.py$", f))
if any(MARK in open(os.path.join(mig_dir, f), encoding="utf-8").read() for f in nums):
    plan.append(("SKIP", "migration"))
else:
    last = nums[-1][:-3]
    name = "%04d_mc_balance_checks.py" % (int(last[:4]) + 1)
    with open(os.path.join(mig_dir, name), "w", encoding="utf-8", newline="") as f:
        f.write(MIGRATION.replace("@@LAST@@", last))
    plan.append(("OK", "migration " + name)); wrote = True
for s, l in plan: print(("OK   " if s == "OK" else "SKIP ") + l)
print("\nDone. Next:  python manage.py migrate   then commit, push and redeploy." if (changed or wrote) else "\nNothing to do: already applied.")