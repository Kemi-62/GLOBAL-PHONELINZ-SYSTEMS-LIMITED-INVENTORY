"""
apply_sidebar_cleanup.py
==========================
Full sidebar audit results and fixes.

WHAT I CHECKED
- Every {% url %} tag in templates/base.html's sidebar (73 total) against
  every registered URL name in core/urls.py -> zero broken/unresolvable
  names, zero missing required path parameters.
- Every sidebar link's target view against its @role_required decorator,
  cross-checked against which role's sidebar section it sits in.

WHAT WAS ACTUALLY WRONG

1. DEAD LINK (403 for every Telecom staff member):
   "Monthly Summary" in the Telecom sidebar points to `staff_monthly_activity`,
   which is decorated @role_required("MANAGER") only, and even renders
   manager_dashboard.html — it's whole-branch data meant for a Manager, not
   an individual Telecom staffer's own page. It was never meant to be here.
   FIX: removed from the Telecom sidebar.

2. REDUNDANT DUPLICATE LINKS (not broken, just confusing clutter):
   Several sidebar entries had different labels implying different
   destinations, but all pointed to the exact same URL with no anchor —
   clicking any of them does the identical thing (reload the dashboard from
   the top), so the extra labels were misleading, not useful shortcuts:
     - Manager: "Targets & Activities" and "Safe Stock & Releases" were both
       just `manager_dashboard` again (same as "Dashboard")
     - Retail: "My Catalog & Stock" and "Sales History" were both just
       `retail_dashboard` again
     - MultiChoice: "Subscription History" was just `multichoice_dashboard`
       again
   FIX: removed the redundant duplicates, kept one clear "Dashboard" link
   per section. (Telecom's "Device Stock & Sales" was NOT touched — it
   correctly uses a `#devices` anchor to jump to a specific tab, that one's
   a legitimate shortcut, not a duplicate.)

Nothing else in the sidebar needed touching — every other link resolves
correctly and matches its role.

HOW TO RUN (Replit Shell)
    python apply_sidebar_cleanup.py

Then:
    python manage.py check
    git add . && git commit -m "Sidebar: remove dead Telecom link + redundant duplicates" && git push

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
    if marker not in content:
        # marker absent could mean either "not yet applied" (old text still there)
        # or "file changed" -- distinguish by checking for old text
        if old not in content:
            print("SKIP  " + label + ": target text not found (already removed, or file changed) - skipping.")
            return
        content = content.replace(old, new, 1)
        write(path, content)
        print("OK    " + label + ": patched " + path)
    else:
        print("SKIP  " + label + ": already applied, skipping.")


PATH = "templates/base.html"

# 1. Remove dead "Monthly Summary" link from Telecom sidebar
TELECOM_OLD = '''        <a href="{% url 'record_physical_product' %}" class="sidebar-link">
            <span class="icon">📝</span> Record Activity
        </a>
        <a href="{% url 'staff_monthly_activity' %}" class="sidebar-link">
            <span class="icon">📊</span> Monthly Summary
        </a>
            <a href="{% url 'staff_dashboard' %}#devices" class="sidebar-link">'''

TELECOM_NEW = '''        <a href="{% url 'record_physical_product' %}" class="sidebar-link">
            <span class="icon">📝</span> Record Activity
        </a>
            <a href="{% url 'staff_dashboard' %}#devices" class="sidebar-link">'''

TELECOM_MARKER = "TELECOM_SIDEBAR_CLEANED"

# 2. Manager: remove the 2 duplicate manager_dashboard links
MANAGER_OLD = '''        <a href="{% url 'manager_dashboard' %}" class="sidebar-link">
            <span class="icon">📡</span> Targets & Activities
        </a>
        <a href="{% url 'add_device_commission' %}" class="sidebar-link">'''

MANAGER_NEW = '''        <a href="{% url 'add_device_commission' %}" class="sidebar-link">'''

MANAGER_MARKER_1 = "MANAGER_SIDEBAR_CLEANED_1"

MANAGER_OLD_2 = '''        <a href="{% url 'manager_dashboard' %}" class="sidebar-link">
            <span class="icon">📦</span> Safe Stock & Releases
        </a>
        <a href="{% url 'upload_manager_csv' %}" class="sidebar-link">'''

MANAGER_NEW_2 = '''        <a href="{% url 'upload_manager_csv' %}" class="sidebar-link">'''

MANAGER_MARKER_2 = "MANAGER_SIDEBAR_CLEANED_2"

# 3. Retail: remove the 2 duplicate retail_dashboard links
RETAIL_OLD = '''        <a href="{% url 'retail_dashboard' %}" class="sidebar-link">
            <span class="icon">📦</span> My Catalog & Stock
        </a>
        <a href="{% url 'retail_dashboard' %}" class="sidebar-link">
            <span class="icon">📋</span> Sales History
        </a>
    </div>
    <div class="sidebar-divider"></div>
    <div class="sidebar-section">
        <div class="sidebar-section-label">Stock</div>
        <a href="{% url 'staff_create_product' %}" class="sidebar-link">'''

RETAIL_NEW = '''    </div>
    <div class="sidebar-divider"></div>
    <div class="sidebar-section">
        <div class="sidebar-section-label">Stock</div>
        <a href="{% url 'staff_create_product' %}" class="sidebar-link">'''

RETAIL_MARKER = "RETAIL_SIDEBAR_CLEANED"

# 4. MultiChoice: remove the 1 duplicate multichoice_dashboard link
MC_OLD = '''        <a href="{% url 'multichoice_dashboard' %}" class="sidebar-link">
            <span class="icon">📋</span> Subscription History
        </a>
        <a href="{% url 'record_balance' %}" class="sidebar-link">'''

MC_NEW = '''        <a href="{% url 'record_balance' %}" class="sidebar-link">'''

MC_MARKER = "MC_SIDEBAR_CLEANED"


def main():
    print("-- Applying Sidebar Cleanup --\n")

    content = read(PATH)

    changes = [
        (TELECOM_OLD, TELECOM_NEW, "Telecom: removed dead 'Monthly Summary' (403) link"),
        (MANAGER_OLD, MANAGER_NEW, "Manager: removed duplicate 'Targets & Activities' link"),
        (MANAGER_OLD_2, MANAGER_NEW_2, "Manager: removed duplicate 'Safe Stock & Releases' link"),
        (RETAIL_OLD, RETAIL_NEW, "Retail: removed duplicate 'My Catalog & Stock' + 'Sales History' links"),
        (MC_OLD, MC_NEW, "MultiChoice: removed duplicate 'Subscription History' link"),
    ]

    any_applied = False
    for old, new, label in changes:
        if new in content and old not in content:
            print("SKIP  " + label + ": already applied.")
            continue
        if old not in content:
            print("FAIL  " + label + ": couldn't find the expected text — base.html may have changed.")
            print("      Send me the current templates/base.html and I'll regenerate this script.")
            sys.exit(1)
        content = content.replace(old, new, 1)
        print("OK    " + label)
        any_applied = True

    if any_applied:
        write(PATH, content)
        print("\nOK    templates/base.html saved.")
    else:
        print("\nNothing to do — all changes already applied.")

    print("\n-- Done --")
    print("Next steps:")
    print("  python manage.py check")
    print("  git add . && git commit -m 'Sidebar: remove dead link + redundant duplicates' && git push")


if __name__ == "__main__":
    main()
