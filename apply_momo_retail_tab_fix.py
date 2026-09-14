"""
apply_momo_retail_tab_fix.py
===============================
Fixes a real gap found after testing in production: Retail's dashboard
has its OWN separate, bespoke check-in/out form inside its "Check
In/Out" tab -- different code from the shared attendance_widget.html
partial that all other dashboards use. Both forms post to the same
/check-out/ URL, but only the shared widget (in the header) got the
Momo fields added -- this bespoke tab form did not. Other dashboards
(Telecom, MultiChoice, Manager) don't have this duplicate form at all,
so they were unaffected.

Net effect before this fix: a Retail staff member who checks out using
the "Check In/Out" TAB (instead of the quick header button) would hit
the server-side Momo requirement with no field to actually enter it --
a confusing dead end. This script adds the same Momo fields to that
form too, so it works identically no matter which checkout path a
Retail staff member uses.

WHAT THIS SCRIPT DOES
    templates/retail_dashboard.html -> adds Momo closing balance +
    additional funds fields to the tab-based checkout form, and updates
    startAttendance() to make the closing balance required when the
    staff member already has Momo history (same rule as everywhere else).

HOW TO RUN (Replit Shell)
    python apply_momo_retail_tab_fix.py

Then:
    python manage.py check
    git add . && git commit -m "Fix: add Momo fields to Retail's tab-based checkout form" && git push

PREREQUISITE: apply_momo_tracking.py must already be applied.

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


PREREQ_MARKER = "window.HAS_MOMO_HISTORY"


def check_prereq():
    content = read("templates/partials/attendance_widget.html")
    if PREREQ_MARKER not in content:
        print("XX This script builds on top of apply_momo_tracking.py,")
        print("   which doesn't look like it's been applied yet.")
        print("   Run that one first: python apply_momo_tracking.py")
        sys.exit(1)


FORM_MARKER = "momo-closing-input-tab"

FORM_OLD = '''        <form method="POST" action="{% url 'check_out' %}" enctype="multipart/form-data" id="checkout-form-el">
          {% csrf_token %}
          <input type="hidden" name="latitude" id="co-lat">
          <input type="hidden" name="longitude" id="co-lon">
          <div class="form-group" style="margin-top:.8rem;">
            <label>Selfie Photo *</label>
            <input type="file" name="selfie" accept="image/*" capture="user" required>
          </div>
          <button type="submit" class="btn-sm btn-danger" style="width:100%;">Submit Check-Out</button>
        </form>'''

FORM_NEW = '''        <form method="POST" action="{% url 'check_out' %}" enctype="multipart/form-data" id="checkout-form-el">
          {% csrf_token %}
          <input type="hidden" name="latitude" id="co-lat">
          <input type="hidden" name="longitude" id="co-lon">
          <div class="form-group" style="margin-top:.8rem;">
            <label>Selfie Photo *</label>
            <input type="file" name="selfie" accept="image/*" capture="user" required>
          </div>
          <div style="margin:.8rem 0;padding:.7rem;background:#f9fafb;border-radius:8px;">
            <label style="font-size:.78rem;font-weight:600;color:#374151;display:block;margin-bottom:.3rem;" id="momo-closing-label-tab">Momo Closing Balance (\u20a6)</label>
            <input type="number" name="momo_closing_balance" id="momo-closing-input-tab" step="0.01" min="0" placeholder="Your Momo balance right now"
                   style="width:100%;padding:.4rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem;margin-bottom:.5rem;">
            <label style="font-size:.78rem;font-weight:600;color:#374151;display:block;margin-bottom:.3rem;">Additional Funds Received Today (\u20a6)</label>
            <input type="number" name="momo_additional_funds" step="0.01" min="0" placeholder="0.00 (if you received a top-up today)"
                   style="width:100%;padding:.4rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem;">
            <p style="font-size:.72rem;color:#9ca3af;margin:.4rem 0 0;">If you don't carry a Momo float, leave this blank.</p>
          </div>
          <button type="submit" class="btn-sm btn-danger" style="width:100%;">Submit Check-Out</button>
        </form>'''


JS_MARKER = "if (momoInputTab)"

JS_OLD = '''function startAttendance(type) {
  const formId = type === 'in' ? 'checkin-form' : 'checkout-form';
  const latId = type === 'in' ? 'ci-lat' : 'co-lat';
  const lonId = type === 'in' ? 'ci-lon' : 'co-lon';
  document.getElementById(formId).style.display = 'block';
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(function(pos) {
      document.getElementById(latId).value = pos.coords.latitude;
      document.getElementById(lonId).value = pos.coords.longitude;
    }, function() {
      alert('Could not get your location. Please enable GPS and try again.');
    });
  } else {
    alert('Geolocation is not supported by your browser.');
  }
}'''

JS_NEW = '''function startAttendance(type) {
  const formId = type === 'in' ? 'checkin-form' : 'checkout-form';
  const latId = type === 'in' ? 'ci-lat' : 'co-lat';
  const lonId = type === 'in' ? 'ci-lon' : 'co-lon';
  document.getElementById(formId).style.display = 'block';
  if (type === 'out') {
    var momoInputTab = document.getElementById('momo-closing-input-tab');
    var momoLabelTab = document.getElementById('momo-closing-label-tab');
    if (momoInputTab) {
      if (window.HAS_MOMO_HISTORY) {
        momoInputTab.required = true;
        momoLabelTab.textContent = 'Momo Closing Balance (\\u20a6) *';
      } else {
        momoInputTab.required = false;
        momoLabelTab.textContent = 'Momo Closing Balance (\\u20a6)';
      }
    }
  }
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(function(pos) {
      document.getElementById(latId).value = pos.coords.latitude;
      document.getElementById(lonId).value = pos.coords.longitude;
    }, function() {
      alert('Could not get your location. Please enable GPS and try again.');
    });
  } else {
    alert('Geolocation is not supported by your browser.');
  }
}'''


def main():
    print("-- Applying Retail Tab Checkout Momo Fix --\n")

    check_prereq()

    patch("templates/retail_dashboard.html", FORM_OLD, FORM_NEW, FORM_MARKER,
          "retail_dashboard.html: Momo fields added to tab checkout form")
    patch("templates/retail_dashboard.html", JS_OLD, JS_NEW, JS_MARKER,
          "retail_dashboard.html: startAttendance() sets required flag")

    print("\n-- Done --")
    print("Next steps:")
    print("  python manage.py check")
    print("  git add . && git commit -m 'Fix: add Momo fields to Retail tab checkout form' && git push")


if __name__ == "__main__":
    main()

