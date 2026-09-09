"""
apply_mc_balance_carryforward.py
===================================
Fixes two real gaps in the MultiChoice weekly balance flow:

1. AUTO CARRY-FORWARD OPENING BALANCE
   Previously, every Monday, staff had to manually TYPE an opening
   balance to start their new week -- nothing carried over from the
   previous week's closing balance. Now "Start This Week" auto-fills the
   opening balance from last week's closing balance automatically -- no
   typing needed.

2. ADD FUNDS MID-WEEK
   Previously, "Additional Funds" could only be entered once, at the
   moment a new week started. Now there's a dedicated "Add Funds" button,
   usable any day of an open week, that adds to that week's
   additional_funds total (the commission math at week-close already
   correctly accounts for additional_funds, so this flows through
   automatically).

WHAT THIS SCRIPT DOES
1. core/views.py:
   - start_weekly_report: auto-computes opening_balance from the last
     closed week instead of requiring manual entry
   - new view: add_weekly_funds -- mid-week top-up
2. core/urls.py: the add_weekly_funds route
3. core/templatetags/mc_balance_tags.py -> NEW: a small tag that shows
   the carried-forward amount before the staff starts their week
4. templates/multichoice_dashboard.html:
   - "Start This Week" form: manual opening balance input removed,
     replaced with a read-only display of the carried-forward amount
   - New "Add Funds" mini-form in the balance banner (visible whenever
     a week is open, any day)

HOW TO RUN (Replit Shell)
    python apply_mc_balance_carryforward.py

Then:
    python manage.py check
    git add . && git commit -m "MultiChoice: auto carry-forward opening balance + mid-week fund top-ups" && git push

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
        print("      Your file may have changed since this script was written.")
        print("      Send the current version of that file and ask for a regenerated script.")
        sys.exit(1)
    content = content.replace(old, new, 1)
    write(path, content)
    print("OK    " + label + ": patched " + path)


VIEWS_MARKER = "Opening balance (carried forward):"

VIEWS_OLD = '''@login_required
def start_weekly_report(request):
    if request.method == "POST" and request.user.role == "MULTICHOICE":
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
        # Safely parse decimal values \u2014 default to 0 if empty
        try:
            opening_balance = Decimal(request.POST.get("opening_balance") or "0")
        except Exception:
            opening_balance = Decimal("0")
        try:
            additional_funds = Decimal(request.POST.get("additional_funds") or "0")
        except Exception:
            additional_funds = Decimal("0")

        obj, created = MultiChoiceWeeklyReport.objects.get_or_create(
            staff=request.user,
            branch=request.user.branch,
            week_start_date=week_start,
            defaults={
                "opening_balance": opening_balance,
                "additional_funds": additional_funds,
            }
        )
        if created:
            messages.success(request, f"Weekly report started. Opening balance: \u20a6{opening_balance:,.2f}")
        else:
            messages.info(request, "A weekly report already exists for this week.")
    return redirect("multichoice_dashboard")'''

VIEWS_NEW = '''@login_required
def start_weekly_report(request):
    if request.method == "POST" and request.user.role == "MULTICHOICE":
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())

        # Auto carry-forward: this week's opening balance is whatever was
        # left as the closing balance of the last closed week -- no manual
        # typing needed. First-ever week (no prior closed report) starts at 0.
        last_closed = MultiChoiceWeeklyReport.objects.filter(
            staff=request.user, branch=request.user.branch, is_closed=True
        ).order_by("-week_start_date").first()
        if last_closed and last_closed.closing_balance is not None:
            opening_balance = last_closed.closing_balance
        else:
            opening_balance = Decimal("0")

        try:
            additional_funds = Decimal(request.POST.get("additional_funds") or "0")
        except Exception:
            additional_funds = Decimal("0")

        obj, created = MultiChoiceWeeklyReport.objects.get_or_create(
            staff=request.user,
            branch=request.user.branch,
            week_start_date=week_start,
            defaults={
                "opening_balance": opening_balance,
                "additional_funds": additional_funds,
            }
        )
        if created:
            messages.success(request, f"Weekly report started. Opening balance (carried forward): \u20a6{opening_balance:,.2f}")
        else:
            messages.info(request, "A weekly report already exists for this week.")
    return redirect("multichoice_dashboard")


@role_required("MULTICHOICE")
def add_weekly_funds(request):
    """Add funds to the CURRENT open week at any point during the week --
    not just at Monday's start. Used when a staff member runs low before
    the week closes and gets topped up."""
    if request.method == "POST":
        weekly_report = MultiChoiceWeeklyReport.objects.filter(
            staff=request.user, branch=request.user.branch, is_closed=False
        ).order_by("-id").first()
        if not weekly_report:
            messages.error(request, "No active weekly report \u2014 start your week first.")
            return redirect("multichoice_dashboard")
        try:
            amount = Decimal(request.POST.get("amount") or "0")
        except Exception:
            amount = Decimal("0")
        if amount <= 0:
            messages.error(request, "Enter a valid amount to add.")
            return redirect("multichoice_dashboard")
        weekly_report.additional_funds = (weekly_report.additional_funds or Decimal("0")) + amount
        weekly_report.save(update_fields=["additional_funds"])
        messages.success(
            request,
            f"\u20a6{amount:,.2f} added. Total additional funds this week: \u20a6{weekly_report.additional_funds:,.2f}"
        )
    return redirect("multichoice_dashboard")'''


URLS_MARKER = "add_weekly_funds"

URLS_OLD_ANCHOR = "    path('my-customers/export/', views.export_my_customers_csv, name='export_my_customers_csv'),\n]"

URLS_NEW_BLOCK = '''    path('my-customers/export/', views.export_my_customers_csv, name='export_my_customers_csv'),
    path('multichoice/add-weekly-funds/', views.add_weekly_funds, name='add_weekly_funds'),
]'''


TAGS_CONTENT = '''from django import template

register = template.Library()


@register.simple_tag
def mc_carried_forward_balance(user):
    from core.models import MultiChoiceWeeklyReport
    last_closed = MultiChoiceWeeklyReport.objects.filter(
        staff=user, is_closed=True
    ).order_by("-week_start_date").first()
    if last_closed and last_closed.closing_balance is not None:
        return last_closed.closing_balance
    return 0
'''


STARTWEEK_MARKER = "mc_carried_forward_balance"

STARTWEEK_OLD = '''  <form method="POST" action="{% url 'start_weekly_report' %}" style="margin-top:.8rem;">
    {% csrf_token %}
    <div class="form-row">
      <div class="form-group"><label>Opening Balance (\u20a6) *</label><input type="number" name="opening_balance" step="0.01" min="0" placeholder="Cash/balance you start with" required></div>
      <div class="form-group"><label>Additional Funds (\u20a6)</label><input type="number" name="additional_funds" step="0.01" min="0" placeholder="0.00"></div>
    </div>
    <button type="submit" class="btn-sm btn-success">\u25B6 Start This Week</button>
  </form>'''

STARTWEEK_NEW = '''  {% load mc_balance_tags %}
  {% mc_carried_forward_balance request.user as cfb %}
  <form method="POST" action="{% url 'start_weekly_report' %}" style="margin-top:.8rem;">
    {% csrf_token %}
    <p style="font-size:.85rem;color:#374151;margin:0 0 .6rem;">
      Opening balance (carried forward from last week's close): <strong>\u20a6{{ cfb|floatformat:2 }}</strong>
    </p>
    <div class="form-row">
      <div class="form-group"><label>Additional Funds Now (\u20a6)</label><input type="number" name="additional_funds" step="0.01" min="0" placeholder="0.00 (optional)"></div>
    </div>
    <button type="submit" class="btn-sm btn-success">\u25B6 Start This Week</button>
  </form>'''

BANNER_MARKER = "add_weekly_funds"

BANNER_OLD = '''<div class="balance-banner">
  <div>
    <p class="balance-label">Current Running Balance</p>
    <p class="balance-value">\u20a6{{ current_balance|floatformat:2 }}</p>
    <p class="balance-sub">Reduces with each subscription cost. Commission detected at week close.</p>
  </div>
  <div style="text-align:right;">
    <p style="font-size:.78rem;opacity:.75;margin:0 0 .2rem;">Week started</p>
    <p style="font-size:1rem;font-weight:700;margin:0;">{{ weekly_report.week_start_date|date:"d M Y" }}</p>
    <p style="font-size:.78rem;opacity:.65;margin:.2rem 0 0;">Opening: \u20a6{{ weekly_report.opening_balance|floatformat:2 }}</p>
  </div>
</div>'''

BANNER_NEW = '''<div class="balance-banner">
  <div>
    <p class="balance-label">Current Running Balance</p>
    <p class="balance-value">\u20a6{{ current_balance|floatformat:2 }}</p>
    <p class="balance-sub">Reduces with each subscription cost. Commission detected at week close.</p>
    <form method="POST" action="{% url 'add_weekly_funds' %}" style="margin-top:.6rem;display:flex;gap:.4rem;align-items:center;">
      {% csrf_token %}
      <input type="number" name="amount" step="0.01" min="0.01" placeholder="Amount" required
             style="width:110px;padding:.35rem .5rem;border-radius:6px;border:1px solid rgba(255,255,255,.4);background:rgba(255,255,255,.15);color:#fff;font-size:.8rem;">
      <button type="submit" style="padding:.35rem .8rem;border-radius:6px;border:none;background:#fff;color:#004F9F;font-weight:700;font-size:.8rem;cursor:pointer;">+ Add Funds</button>
    </form>
    <p style="font-size:.72rem;opacity:.65;margin:.4rem 0 0;">Additional funds so far this week: \u20a6{{ weekly_report.additional_funds|floatformat:2 }}</p>
  </div>
  <div style="text-align:right;">
    <p style="font-size:.78rem;opacity:.75;margin:0 0 .2rem;">Week started</p>
    <p style="font-size:1rem;font-weight:700;margin:0;">{{ weekly_report.week_start_date|date:"d M Y" }}</p>
    <p style="font-size:.78rem;opacity:.65;margin:.2rem 0 0;">Opening: \u20a6{{ weekly_report.opening_balance|floatformat:2 }}</p>
  </div>
</div>'''


def main():
    print("-- Applying MultiChoice Balance Carry-Forward + Mid-Week Top-Ups --\n")

    patch("core/views.py", VIEWS_OLD, VIEWS_NEW, VIEWS_MARKER,
          "views.py: auto carry-forward + add_weekly_funds view")
    patch("core/urls.py", URLS_OLD_ANCHOR, URLS_NEW_BLOCK, URLS_MARKER,
          "urls.py: add_weekly_funds route")

    tags_path = os.path.join(BASE_DIR, "core", "templatetags", "mc_balance_tags.py")
    if os.path.exists(tags_path):
        print("SKIP  core/templatetags/mc_balance_tags.py: already exists, skipping.")
    else:
        os.makedirs(os.path.dirname(tags_path), exist_ok=True)
        write("core/templatetags/mc_balance_tags.py", TAGS_CONTENT)
        print("OK    Created core/templatetags/mc_balance_tags.py")

    patch("templates/multichoice_dashboard.html", STARTWEEK_OLD, STARTWEEK_NEW, STARTWEEK_MARKER,
          "multichoice_dashboard.html: Start This Week form (carry-forward display)")
    patch("templates/multichoice_dashboard.html", BANNER_OLD, BANNER_NEW, BANNER_MARKER,
          "multichoice_dashboard.html: Add Funds mid-week form")

    print("\n-- Done --")
    print("Next steps:")
    print("  python manage.py check")
    print("  git add . && git commit -m 'MultiChoice: auto carry-forward opening balance + mid-week top-ups' && git push")


if __name__ == "__main__":
    main()

