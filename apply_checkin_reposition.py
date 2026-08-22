"""
apply_checkin_reposition.py
==============================
Moves the check-in/out widget to the same spot on every staff dashboard
that you like on the Manager dashboard: right in the header, visible
immediately after login, no tab-clicking needed.

WHAT I FOUND
- Manager: widget already in the header (this is the position you like).
- MultiChoice: widget was buried inside the "Attendance" tab — you had to
  click into a tab to see it. Moved to the header; the header's separate
  "Attendance" button (which just linked to the history page) was removed
  since the widget itself already has a "History" button built in.
- Telecom: same issue, widget was buried inside its "Attendance" tab.
  Moved to the header.
- Retail: doesn't use the shared widget at all — it has its own separate,
  custom-built check-in/out UI inside a "Check In/Out" tab (different code,
  with its own selfie-capture flow). I did NOT touch or remove that, since
  it's more elaborate and I don't want to risk breaking it. Instead, the
  same shared header widget you like from Manager is ADDED to Retail's
  header too, so retail staff get the same fast one-tap access at the top
  — the tab-based version stays as-is underneath, untouched.

Net result: check-in/out is one glance away at the top of EVERY dashboard,
no dashboard has it duplicated on-screen at the same time (except Retail,
which intentionally gets both the quick header version AND keeps its
existing detailed tab).

HOW TO RUN (Replit Shell)
    python apply_checkin_reposition.py

Then:
    python manage.py check
    git add . && git commit -m "Reposition check-in/out widget to dashboard header on all roles" && git push

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


# ---------------------------------------------------------------
# 1. MultiChoice: move widget from Attendance tab -> header
# ---------------------------------------------------------------

MC_HEADER_OLD = '''  <div style="display:flex;gap:.6rem;flex-wrap:wrap;">
    <a href="{% url 'my_commissions' %}" class="btn-sm btn-purple">\U0001F4B0 My Commissions</a>
    <a href="{% url 'attendance_history' %}" class="btn-sm btn-outline">\U0001F4CB Attendance</a>
  </div>
</div>'''

MC_HEADER_NEW = '''  <div style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;">
    <a href="{% url 'my_commissions' %}" class="btn-sm btn-purple">\U0001F4B0 My Commissions</a>
    {% include "partials/attendance_widget.html" %}
  </div>
</div>'''

MC_TAB_OLD = '''<div id="tab-attendance" class="tab-panel">
  {% include "partials/attendance_widget.html" %}
  <div class="card">
    <p class="card-title">\U0001F4C5 Recent Attendance</p>'''

MC_TAB_NEW = '''<div id="tab-attendance" class="tab-panel">
  <div class="card">
    <p class="card-title">\U0001F4C5 Recent Attendance</p>'''

MC_MARKER = "MC_CHECKIN_REPOSITIONED"


# ---------------------------------------------------------------
# 2. Telecom (staff_dashboard.html): move widget from Attendance tab -> header
# ---------------------------------------------------------------

TC_HEADER_OLD = '''<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:1rem;margin-bottom:1.5rem;">
  <div>
    <h1 class="dash-title">Telecom Dashboard</h1>
    <p class="dash-sub">{{ request.user.username }} &nbsp;\u00b7&nbsp; {{ request.user.branch.name }} &nbsp;\u00b7&nbsp; {% now "D, d M Y" %}</p>
  </div>
</div>'''

TC_HEADER_NEW = '''<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:1rem;margin-bottom:1.5rem;">
  <div>
    <h1 class="dash-title">Telecom Dashboard</h1>
    <p class="dash-sub">{{ request.user.username }} &nbsp;\u00b7&nbsp; {{ request.user.branch.name }} &nbsp;\u00b7&nbsp; {% now "D, d M Y" %}</p>
  </div>
  <div style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;">
    {% include "partials/attendance_widget.html" %}
  </div>
</div>'''

TC_TAB_OLD = '''<div id="tab-attendance" class="tab-panel">
  {% include "partials/attendance_widget.html" %}
  <div class="card">
    <p class="card-title">\U0001F4C5 Recent Attendance</p>'''

TC_TAB_NEW = '''<div id="tab-attendance" class="tab-panel">
  <div class="card">
    <p class="card-title">\U0001F4C5 Recent Attendance</p>'''

TC_MARKER = "TELECOM_CHECKIN_REPOSITIONED"


# ---------------------------------------------------------------
# 3. Retail: add widget fresh into header (existing tab UI untouched)
# ---------------------------------------------------------------

RETAIL_HEADER_OLD = '''<div class="dash-header">
  <div>
    <h1 class="dash-title">Retail Dashboard</h1>
    <p class="dash-sub">{{ request.user.username }} &nbsp;\u00b7&nbsp; {{ request.user.branch.name }} &nbsp;\u00b7&nbsp; {% now "D, d M Y" %}</p>
  </div>
</div>'''

RETAIL_HEADER_NEW = '''<div class="dash-header">
  <div>
    <h1 class="dash-title">Retail Dashboard</h1>
    <p class="dash-sub">{{ request.user.username }} &nbsp;\u00b7&nbsp; {{ request.user.branch.name }} &nbsp;\u00b7&nbsp; {% now "D, d M Y" %}</p>
  </div>
  <div style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;">
    {% include "partials/attendance_widget.html" %}
  </div>
</div>'''

RETAIL_MARKER = "RETAIL_CHECKIN_HEADER_ADDED"


def main():
    print("-- Repositioning Check-In/Out Widget --\n")

    patch("templates/multichoice_dashboard.html", MC_HEADER_OLD, MC_HEADER_NEW, MC_HEADER_NEW,
          "multichoice_dashboard.html: widget moved to header")
    patch("templates/multichoice_dashboard.html", MC_TAB_OLD, MC_TAB_NEW, MC_TAB_NEW,
          "multichoice_dashboard.html: removed duplicate from Attendance tab")

    patch("templates/staff_dashboard.html", TC_HEADER_OLD, TC_HEADER_NEW, TC_HEADER_NEW,
          "staff_dashboard.html: widget moved to header")
    patch("templates/staff_dashboard.html", TC_TAB_OLD, TC_TAB_NEW, TC_TAB_NEW,
          "staff_dashboard.html: removed duplicate from Attendance tab")

    patch("templates/retail_dashboard.html", RETAIL_HEADER_OLD, RETAIL_HEADER_NEW, RETAIL_HEADER_NEW,
          "retail_dashboard.html: widget added to header")

    print("\n-- Done --")
    print("Next steps:")
    print("  python manage.py check")
    print("  git add . && git commit -m 'Reposition check-in/out widget to header on all dashboards' && git push")


if __name__ == "__main__":
    main()
