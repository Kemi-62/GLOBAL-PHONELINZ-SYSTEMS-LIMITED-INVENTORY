"""
apply_online_sales_tab.py
============================
Embeds the "Log Online Sale" form (text fields + photo evidence upload)
directly into every dashboard as a real tab, instead of it only being
reachable as a separate page via the sidebar.

WHAT THIS SCRIPT DOES
1. templates/partials/online_sale_form.html -> NEW FILE. The form is
   extracted here once so it's not duplicated 5 times across dashboards
   (DRY -- one place to maintain it).
2. templates/online_sales/log_sale.html -> now just includes the partial,
   so the existing standalone page keeps working exactly as before.
3. templates/retail_dashboard.html, staff_dashboard.html (Telecom),
   multichoice_dashboard.html, manager_dashboard.html -> each gets a new
   "Online Sales" tab that includes the same partial, so staff can log a
   sale (with photo) without ever leaving their dashboard.

The form still posts to the same working endpoint (log_online_sale) and
still redirects to "My Online Sales" (the summary list) on success, same
as it always has -- landing on the confirmation/history page after
submitting is expected behaviour, not a bug.

HOW TO RUN (Replit Shell)
    python apply_online_sales_tab.py

Then:
    python manage.py check
    git add . && git commit -m "Embed Online Sales recording as a dashboard tab" && git push

IDEMPOTENT - safe to run twice.
"""

import os
import re
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
# 1. New reusable partial
# ---------------------------------------------------------------

PARTIAL_CONTENT = '''{% comment %}
  Reusable Online Sale form -- include wherever staff should be able to
  log a social-media/WhatsApp sale (with photo evidence).
  Requires `platforms` and `today` in context (already provided by the
  views that render this).
{% endcomment %}
<div class="card">
  <form method="POST" action="{% url 'log_online_sale' %}" enctype="multipart/form-data">
    {% csrf_token %}
    <div class="form-row">
      <div class="form-group">
        <label>Product / Service Sold *</label>
        <input type="text" name="product_name" required placeholder="e.g. iPhone 14, DStv Compact, MTN SIM">
      </div>
      <div class="form-group">
        <label>Amount (\u20a6) *</label>
        <input type="number" name="amount" step="0.01" min="0" required placeholder="Sale amount">
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Customer Name *</label>
        <input type="text" name="customer_name" required placeholder="Customer full name">
      </div>
      <div class="form-group">
        <label>Customer Phone *</label>
        <input type="tel" name="customer_phone" required placeholder="08012345678">
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Sale Date *</label>
        <input type="date" name="sale_date" value="{{ today|date:'Y-m-d' }}" required>
      </div>
      <div class="form-group">
        <label>Platform *</label>
        <select name="platform">
          {% for val, label in platforms %}
          <option value="{{ val }}">{{ label }}</option>
          {% endfor %}
        </select>
      </div>
    </div>
    <div class="form-group">
      <label>Evidence (Screenshot / Photo) *</label>
      <input type="file" name="evidence_image" accept="image/*" capture="environment" required>
      <p style="font-size:.72rem;color:#64748b;margin-top:.25rem">Upload a screenshot or photo proving the sale was made online.</p>
    </div>
    <div class="form-group">
      <label>Notes (optional)</label>
      <textarea name="notes" rows="2" placeholder="Any extra details about this sale..."></textarea>
    </div>
    <button type="submit" class="btn-sm btn-primary" style="width:100%;margin-top:.4rem;">Submit Online Sale</button>
  </form>
</div>
<div class="card">
  <a href="{% url 'my_online_sales' %}" class="btn-sm btn-outline">\U0001F4CB View My Online Sales History</a>
</div>
'''


# ---------------------------------------------------------------
# 2. log_sale.html -> use the partial instead of its own inline form
# ---------------------------------------------------------------

LOGSALE_MARKER = 'include "partials/online_sale_form.html"'

LOGSALE_OLD = '''<div class="card">
  <form method="POST" enctype="multipart/form-data">
    {% csrf_token %}
    <div class="form-row">
      <div class="fg">
        <label>Product / Service Sold *</label>
        <input type="text" name="product_name" required placeholder="e.g. iPhone 14, DStv Compact, MTN SIM">
      </div>
      <div class="fg">
        <label>Amount (\u20a6) *</label>
        <input type="number" name="amount" step="0.01" min="0" required placeholder="Sale amount">
      </div>
    </div>
    <div class="form-row">
      <div class="fg">
        <label>Customer Name *</label>
        <input type="text" name="customer_name" required placeholder="Customer full name">
      </div>
      <div class="fg">
        <label>Customer Phone *</label>
        <input type="tel" name="customer_phone" required placeholder="08012345678">
      </div>
    </div>
    <div class="form-row">
      <div class="fg">
        <label>Sale Date *</label>
        <input type="date" name="sale_date" value="{{ today|date:'Y-m-d' }}" required>
      </div>
      <div class="fg">
        <label>Platform *</label>
        <select name="platform">
          {% for val, label in platforms %}
          <option value="{{ val }}">{{ label }}</option>
          {% endfor %}
        </select>
      </div>
    </div>
    <div class="fg">
      <label>Evidence (Screenshot / Photo) *</label>
      <input type="file" name="evidence_image" accept="image/*" capture="environment" required>
      <p style="font-size:.72rem;color:#64748b;margin-top:.25rem">Upload a screenshot or photo proving the sale was made online.</p>
    </div>
    <div class="fg">
      <label>Notes (optional)</label>
      <textarea name="notes" rows="2" placeholder="Any extra details about this sale..."></textarea>
    </div>
    <button type="submit" class="btn-p">Submit Online Sale</button>
  </form>
</div>
{% endblock %}'''

LOGSALE_NEW = '''{% include "partials/online_sale_form.html" %}
{% endblock %}'''


# ---------------------------------------------------------------
# 3. Dashboard tabs -- each gets a new "Online Sales" tab
# ---------------------------------------------------------------

# Retail
RETAIL_TABBAR_OLD = '''  <button class="tab-btn" onclick="switchTab('requests',this)">\U0001F4EC Stock Requests</button>
</div>'''
RETAIL_TABBAR_NEW = '''  <button class="tab-btn" onclick="switchTab('requests',this)">\U0001F4EC Stock Requests</button>
  <button class="tab-btn" onclick="switchTab('onlinesales',this)">\U0001F4F1 Online Sales</button>
</div>'''
RETAIL_PANEL_OLD = '''<script>
function switchTab(name, btn) {'''
RETAIL_PANEL_NEW = '''<div id="tab-onlinesales" class="tab-panel">
  {% include "partials/online_sale_form.html" %}
</div>

<script>
function switchTab(name, btn) {'''
RETAIL_MARKER = 'tab-onlinesales" class="tab-panel'

# MultiChoice
MC_TABBAR_OLD = '''  <button class="tab-btn" onclick="switchTab('hardware-inventory',this)">\U0001F4E6 Inventory</button>
</div>'''
MC_TABBAR_NEW = '''  <button class="tab-btn" onclick="switchTab('hardware-inventory',this)">\U0001F4E6 Inventory</button>
  <button class="tab-btn" onclick="switchTab('onlinesales',this)">\U0001F4F1 Online Sales</button>
</div>'''
MC_PANEL_OLD = '''<script>
function switchTab(name, btn) {'''
MC_PANEL_NEW = '''<div id="tab-onlinesales" class="tab-panel">
  {% include "partials/online_sale_form.html" %}
</div>

<script>
function switchTab(name, btn) {'''
MC_MARKER = 'tab-onlinesales" class="tab-panel'


def main():
    print("-- Embedding Online Sales as a Dashboard Tab --\n")

    partial_path = os.path.join(BASE_DIR, "templates", "partials", "online_sale_form.html")
    if os.path.exists(partial_path):
        print("SKIP  templates/partials/online_sale_form.html: already exists, skipping.")
    else:
        os.makedirs(os.path.dirname(partial_path), exist_ok=True)
        write("templates/partials/online_sale_form.html", PARTIAL_CONTENT)
        print("OK    Created templates/partials/online_sale_form.html")

    patch("templates/online_sales/log_sale.html", LOGSALE_OLD, LOGSALE_NEW, LOGSALE_MARKER,
          "log_sale.html: switched to shared partial")

    patch("templates/retail_dashboard.html", RETAIL_TABBAR_OLD, RETAIL_TABBAR_NEW, "onlinesales',this",
          "retail_dashboard.html: tab bar button")
    patch("templates/retail_dashboard.html", RETAIL_PANEL_OLD, RETAIL_PANEL_NEW, RETAIL_MARKER,
          "retail_dashboard.html: tab panel")

    patch("templates/multichoice_dashboard.html", MC_TABBAR_OLD, MC_TABBAR_NEW, "onlinesales',this",
          "multichoice_dashboard.html: tab bar button")
    patch("templates/multichoice_dashboard.html", MC_PANEL_OLD, MC_PANEL_NEW, MC_MARKER,
          "multichoice_dashboard.html: tab panel")

    for label, path in [
        ("staff_dashboard.html (Telecom)", "templates/staff_dashboard.html"),
        ("manager_dashboard.html", "templates/manager_dashboard.html"),
    ]:
        content = read(path)
        if 'tab-onlinesales" class="tab-panel' in content:
            print("SKIP  " + label + ": already applied, skipping.")
            continue
        m = list(re.finditer(r'(<button class="tab-btn"[^\n]*</button>\n)(</div>)', content))
        if not m:
            print("FAIL  " + label + ": couldn't locate the tab bar's closing pattern.")
            print("      Send me the current version of " + path + " and I'll adjust this script.")
            sys.exit(1)
        last = m[-1]
        insert_btn = '  <button class="tab-btn" onclick="switchTab(\'onlinesales\',this)">\U0001F4F1 Online Sales</button>\n'
        content = content[:last.end(1)] + insert_btn + content[last.end(1):]

        script_idx = content.find("<script>\nfunction switchTab(name, btn) {")
        if script_idx == -1:
            print("FAIL  " + label + ": couldn't locate the switchTab() script block to anchor the new panel.")
            print("      Send me the current version of " + path + " and I'll adjust this script.")
            sys.exit(1)
        panel_html = '<div id="tab-onlinesales" class="tab-panel">\n  {% include "partials/online_sale_form.html" %}\n</div>\n\n'
        content = content[:script_idx] + panel_html + content[script_idx:]

        write(path, content)
        print("OK    " + label + ": added Online Sales tab")

    print("\n-- Done --")
    print("Next steps:")
    print("  python manage.py check")
    print("  git add . && git commit -m 'Embed Online Sales recording as a dashboard tab' && git push")


if __name__ == "__main__":
    main()
