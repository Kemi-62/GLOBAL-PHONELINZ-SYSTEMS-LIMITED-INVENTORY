"""
apply_multichoice_hardware.py
================================
Adds hardware sales recording + a personal inventory tracker to the
MultiChoice dashboard ONLY (not any other dashboard) - for decoders,
remotes, adapters, antennas, wire, etc., separate from subscription sales.

WHAT THIS SCRIPT DOES
1. core/models.py -> two new models:
   - MultiChoiceHardwareStock: a staff member's personal hardware inventory
   - MultiChoiceHardwareSale: a recorded hardware sale
2. core/migrations/0039_multichoice_hardware.py -> new migration
3. core/views.py -> record_multichoice_hardware_sale, add_multichoice_hardware_stock,
   and multichoice_dashboard() now passes hardware stock/sales to the template
4. core/urls.py -> 2 new routes
5. templates/multichoice_dashboard.html -> two new tabs:
   "Hardware Sales" (record form + today's list) and
   "Inventory" (current stock + add-stock form)

ITEM TYPES: Complete GOtv Decoder Set, Complete DStv Decoder Set, Single
Decoder, Remote, Adapter, Antenna, Wire, Other (with a text field to
specify what "Other" actually was).

Sale fields: item, quantity, amount, IUC number, customer name, customer
phone, notes.

Stock deduction on sale is best-effort: if the staff member has that exact
item tracked in their inventory, it's decremented; if not (they haven't
logged opening stock yet), the sale still records fine, nothing blocks it.

HOW TO RUN (Replit Shell)
    python apply_multichoice_hardware.py

Then:
    python manage.py makemigrations --check   # should say "No changes detected"
    python manage.py migrate
    python manage.py check
    git add . && git commit -m "Add MultiChoice hardware sales + inventory tabs" && git push

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
# 1. core/models.py
# ---------------------------------------------------------------

MODELS_MARKER = "class MultiChoiceHardwareStock"

MODELS_OLD = "class DeviceTagCommission(models.Model):"

MODELS_NEW = '''class MultiChoiceHardwareStock(models.Model):
    """A MultiChoice staff member's personal decoder/accessory inventory."""
    ITEM_CHOICES = [
        ('GOTV_DECODER_SET', 'Complete GOtv Decoder Set'),
        ('DSTV_DECODER_SET', 'Complete DStv Decoder Set'),
        ('SINGLE_DECODER',   'Single Decoder'),
        ('REMOTE',           'Remote'),
        ('ADAPTER',          'Adapter'),
        ('ANTENNA',          'Antenna'),
        ('WIRE',             'Wire'),
        ('OTHER',            'Other'),
    ]
    staff = models.ForeignKey('User', on_delete=models.CASCADE, related_name='mc_hardware_stock')
    branch = models.ForeignKey('Branch', on_delete=models.CASCADE, related_name='mc_hardware_stock')
    item_type = models.CharField(max_length=20, choices=ITEM_CHOICES)
    other_description = models.CharField(max_length=150, blank=True, default='')
    quantity = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('staff', 'item_type', 'other_description')

    def __str__(self):
        label = self.other_description if self.item_type == 'OTHER' else self.get_item_type_display()
        return f"{self.staff.username} - {label} ({self.quantity})"


class MultiChoiceHardwareSale(models.Model):
    """A hardware sale (decoder, accessory) recorded by a MultiChoice staff member."""
    ITEM_CHOICES = MultiChoiceHardwareStock.ITEM_CHOICES

    staff = models.ForeignKey('User', on_delete=models.CASCADE, related_name='mc_hardware_sales')
    branch = models.ForeignKey('Branch', on_delete=models.CASCADE, related_name='mc_hardware_sales')
    item_type = models.CharField(max_length=20, choices=ITEM_CHOICES)
    other_description = models.CharField(max_length=150, blank=True, default='')
    quantity = models.PositiveIntegerField(default=1)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    iuc_number = models.CharField(max_length=30, blank=True, default='')
    customer_name = models.CharField(max_length=150, blank=True, default='')
    customer_phone = models.CharField(max_length=20, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    def __str__(self):
        label = self.other_description if self.item_type == 'OTHER' else self.get_item_type_display()
        return f"{label} x{self.quantity} - {self.staff.username}"


class DeviceTagCommission(models.Model):'''


# ---------------------------------------------------------------
# 2. migration
# ---------------------------------------------------------------

MIGRATION_CONTENT = '''# Generated manually to match Django 5.0.2 migration style
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0038_add_online_sale_log'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MultiChoiceHardwareStock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('item_type', models.CharField(choices=[('GOTV_DECODER_SET', 'Complete GOtv Decoder Set'), ('DSTV_DECODER_SET', 'Complete DStv Decoder Set'), ('SINGLE_DECODER', 'Single Decoder'), ('REMOTE', 'Remote'), ('ADAPTER', 'Adapter'), ('ANTENNA', 'Antenna'), ('WIRE', 'Wire'), ('OTHER', 'Other')], max_length=20)),
                ('other_description', models.CharField(blank=True, default='', max_length=150)),
                ('quantity', models.IntegerField(default=0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mc_hardware_stock', to='core.branch')),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mc_hardware_stock', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='MultiChoiceHardwareSale',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('item_type', models.CharField(choices=[('GOTV_DECODER_SET', 'Complete GOtv Decoder Set'), ('DSTV_DECODER_SET', 'Complete DStv Decoder Set'), ('SINGLE_DECODER', 'Single Decoder'), ('REMOTE', 'Remote'), ('ADAPTER', 'Adapter'), ('ANTENNA', 'Antenna'), ('WIRE', 'Wire'), ('OTHER', 'Other')], max_length=20)),
                ('other_description', models.CharField(blank=True, default='', max_length=150)),
                ('quantity', models.PositiveIntegerField(default=1)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('iuc_number', models.CharField(blank=True, default='', max_length=30)),
                ('customer_name', models.CharField(blank=True, default='', max_length=150)),
                ('customer_phone', models.CharField(blank=True, default='', max_length=20)),
                ('notes', models.TextField(blank=True, default='')),
                ('date', models.DateField(auto_now_add=True)),
                ('time', models.TimeField(auto_now_add=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mc_hardware_sales', to='core.branch')),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mc_hardware_sales', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AlterUniqueTogether(
            name='multichoicehardwarestock',
            unique_together={('staff', 'item_type', 'other_description')},
        ),
    ]
'''


# ---------------------------------------------------------------
# 3. core/views.py
# ---------------------------------------------------------------

VIEWS_MARKER = "def record_multichoice_hardware_sale(request):"

VIEWS_OLD_ANCHOR = "# DEVICE COMMISSION \u2014 with history"

VIEWS_NEW_BLOCK = '''# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# MULTICHOICE HARDWARE SALES + INVENTORY
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

@role_required("MULTICHOICE")
def record_multichoice_hardware_sale(request):
    from core.models import MultiChoiceHardwareSale, MultiChoiceHardwareStock

    if request.method == "POST":
        item_type = request.POST.get("item_type", "")
        other_description = request.POST.get("other_description", "").strip()
        quantity = int(request.POST.get("quantity", 1) or 1)
        amount = request.POST.get("amount") or 0
        iuc_number = request.POST.get("iuc_number", "").strip()
        customer_name = request.POST.get("customer_name", "").strip()
        customer_phone = request.POST.get("customer_phone", "").strip()
        notes = request.POST.get("notes", "").strip()

        if item_type == "OTHER" and not other_description:
            messages.error(request, "Please specify what was sold when choosing 'Other'.")
            return redirect("multichoice_dashboard")

        MultiChoiceHardwareSale.objects.create(
            staff=request.user, branch=request.user.branch,
            item_type=item_type, other_description=other_description,
            quantity=quantity, amount=amount, iuc_number=iuc_number,
            customer_name=customer_name, customer_phone=customer_phone,
            notes=notes,
        )

        stock = MultiChoiceHardwareStock.objects.filter(
            staff=request.user, item_type=item_type, other_description=other_description
        ).first()
        if stock:
            stock.quantity = max(0, stock.quantity - quantity)
            stock.save()

        label = other_description if item_type == "OTHER" else dict(MultiChoiceHardwareSale.ITEM_CHOICES).get(item_type, item_type)
        messages.success(request, f"Hardware sale recorded: {quantity}x {label} \\u2014 \\u20a6{float(amount):,.0f}")
    return redirect("multichoice_dashboard")


@role_required("MULTICHOICE")
def add_multichoice_hardware_stock(request):
    from core.models import MultiChoiceHardwareStock

    if request.method == "POST":
        item_type = request.POST.get("item_type", "")
        other_description = request.POST.get("other_description", "").strip()
        quantity = int(request.POST.get("quantity", 0) or 0)

        if item_type == "OTHER" and not other_description:
            messages.error(request, "Please specify the item name when choosing 'Other'.")
            return redirect("multichoice_dashboard")

        stock, _ = MultiChoiceHardwareStock.objects.get_or_create(
            staff=request.user, item_type=item_type, other_description=other_description,
            defaults={"branch": request.user.branch, "quantity": 0},
        )
        stock.quantity = stock.quantity + quantity
        stock.branch = request.user.branch
        stock.save()
        messages.success(request, f"Stock updated: {stock.quantity} units now on hand.")
    return redirect("multichoice_dashboard")


# DEVICE COMMISSION \u2014 with history'''

DASH_CONTEXT_MARKER = "hardware_item_choices"

DASH_CONTEXT_OLD = '''    return render(request, "multichoice_dashboard.html", {
        "today_sales": today_sales,
        "all_sales": all_sales_page,
        "total_today": today_sales.aggregate(total=Sum("amount"))["total"] or 0,
        "weekly_report": weekly_report,
        "is_monday": today.weekday() == 0,
        "is_saturday": today.weekday() == 5,
        "weekly_total_sales": weekly_total_sales,
        "balance_history": balance_history,
        "current_balance": current_balance,
        "search_query": search_query,
        "selected_month": selected_month,
        "date_from": date_from,
        "date_to": date_to,
        "check_logs": CheckInOutLog.objects.filter(staff=request.user).order_by("-date", "-check_in_time")[:20],
        "checkinout_logs": CheckInOutLog.objects.filter(staff=request.user).order_by("-date", "-check_in_time")[:20],
    })'''

DASH_CONTEXT_NEW = '''    from core.models import MultiChoiceHardwareStock, MultiChoiceHardwareSale
    hardware_stock = MultiChoiceHardwareStock.objects.filter(staff=request.user).order_by("item_type")
    hardware_sales_today = MultiChoiceHardwareSale.objects.filter(staff=request.user, date=today).order_by("-time")

    return render(request, "multichoice_dashboard.html", {
        "today_sales": today_sales,
        "all_sales": all_sales_page,
        "total_today": today_sales.aggregate(total=Sum("amount"))["total"] or 0,
        "weekly_report": weekly_report,
        "is_monday": today.weekday() == 0,
        "is_saturday": today.weekday() == 5,
        "weekly_total_sales": weekly_total_sales,
        "balance_history": balance_history,
        "current_balance": current_balance,
        "search_query": search_query,
        "selected_month": selected_month,
        "date_from": date_from,
        "date_to": date_to,
        "check_logs": CheckInOutLog.objects.filter(staff=request.user).order_by("-date", "-check_in_time")[:20],
        "checkinout_logs": CheckInOutLog.objects.filter(staff=request.user).order_by("-date", "-check_in_time")[:20],
        "hardware_stock": hardware_stock,
        "hardware_sales_today": hardware_sales_today,
        "hardware_item_choices": MultiChoiceHardwareStock.ITEM_CHOICES,
    })'''


# ---------------------------------------------------------------
# 4. core/urls.py
# ---------------------------------------------------------------

URLS_MARKER = "record_multichoice_hardware_sale"

URLS_OLD_ANCHOR = "    path('online-sales/log/', views.log_online_sale, name='log_online_sale'),"

URLS_NEW_BLOCK = '''    path('online-sales/log/', views.log_online_sale, name='log_online_sale'),
    path('multichoice/hardware-sale/', views.record_multichoice_hardware_sale, name='record_multichoice_hardware_sale'),
    path('multichoice/hardware-stock/add/', views.add_multichoice_hardware_stock, name='add_multichoice_hardware_stock'),'''


# ---------------------------------------------------------------
# 5. templates/multichoice_dashboard.html
# ---------------------------------------------------------------

TEMPLATE_MARKER = "tab-hardware-sales"

TAB_BAR_OLD = '''  <button class="tab-btn" onclick="switchTab('checkinout',this)">\U0001F6B6 Check In/Out</button>
</div>'''

TAB_BAR_NEW = '''  <button class="tab-btn" onclick="switchTab('checkinout',this)">\U0001F6B6 Check In/Out</button>
  <button class="tab-btn" onclick="switchTab('hardware-sales',this)">\U0001F50C Hardware Sales</button>
  <button class="tab-btn" onclick="switchTab('hardware-inventory',this)">\U0001F4E6 Inventory</button>
</div>'''

PANELS_OLD = '''  </div>
</div>

<script>
function switchTab(name, btn) {'''

PANELS_NEW = '''  </div>
</div>

<!-- \u2550\u2550 TAB: HARDWARE SALES \u2550\u2550 -->
<div id="tab-hardware-sales" class="tab-panel">
  <div class="card">
    <p class="card-title">\U0001F50C Record Hardware Sale</p>
    <form method="POST" action="{% url 'record_multichoice_hardware_sale' %}" id="hw-sale-form">
      {% csrf_token %}
      <div class="form-row">
        <div class="form-group">
          <label>Item *</label>
          <select name="item_type" id="hw-sale-item" required onchange="document.getElementById('hw-sale-other-wrap').style.display = this.value === 'OTHER' ? 'block' : 'none';">
            {% for val, label in hardware_item_choices %}
            <option value="{{ val }}">{{ label }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="form-group">
          <label>Quantity *</label>
          <input type="number" name="quantity" min="1" value="1" required>
        </div>
      </div>
      <div class="form-group" id="hw-sale-other-wrap" style="display:none;">
        <label>Specify what was sold *</label>
        <input type="text" name="other_description" placeholder="e.g. HDMI splitter">
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Amount (\u20a6) *</label>
          <input type="number" name="amount" min="0" step="0.01" required>
        </div>
        <div class="form-group">
          <label>IUC Number</label>
          <input type="text" name="iuc_number" placeholder="If linked to a subscription">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Customer Name</label>
          <input type="text" name="customer_name">
        </div>
        <div class="form-group">
          <label>Customer Phone</label>
          <input type="text" name="customer_phone">
        </div>
      </div>
      <div class="form-group">
        <label>Notes</label>
        <textarea name="notes" rows="2" placeholder="Optional"></textarea>
      </div>
      <button type="submit" class="btn-sm btn-primary">Record Sale</button>
    </form>
  </div>

  <div class="card">
    <p class="card-title">\U0001F4CB Today's Hardware Sales</p>
    <div style="overflow-x:auto;">
      <table class="data-table">
        <thead><tr><th>Time</th><th>Item</th><th style="text-align:center;">Qty</th><th style="text-align:right;">Amount</th><th>Customer</th><th>IUC</th></tr></thead>
        <tbody>
          {% for s in hardware_sales_today %}
          <tr>
            <td style="font-size:.78rem;">{{ s.time|time:"H:i" }}</td>
            <td><strong>{% if s.item_type == 'OTHER' %}{{ s.other_description }}{% else %}{{ s.get_item_type_display }}{% endif %}</strong></td>
            <td style="text-align:center;">{{ s.quantity }}</td>
            <td style="text-align:right;">\u20a6{{ s.amount|floatformat:0 }}</td>
            <td>{{ s.customer_name|default:"\u2014" }}</td>
            <td>{{ s.iuc_number|default:"\u2014" }}</td>
          </tr>
          {% empty %}
          <tr><td colspan="6" style="text-align:center;color:#9ca3af;">No hardware sales recorded today.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>

<!-- \u2550\u2550 TAB: HARDWARE INVENTORY \u2550\u2550 -->
<div id="tab-hardware-inventory" class="tab-panel">
  <div class="card">
    <p class="card-title">\U0001F4E6 Add / Receive Stock</p>
    <form method="POST" action="{% url 'add_multichoice_hardware_stock' %}" id="hw-stock-form">
      {% csrf_token %}
      <div class="form-row">
        <div class="form-group">
          <label>Item *</label>
          <select name="item_type" id="hw-stock-item" required onchange="document.getElementById('hw-stock-other-wrap').style.display = this.value === 'OTHER' ? 'block' : 'none';">
            {% for val, label in hardware_item_choices %}
            <option value="{{ val }}">{{ label }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="form-group">
          <label>Quantity Received *</label>
          <input type="number" name="quantity" min="1" required>
        </div>
      </div>
      <div class="form-group" id="hw-stock-other-wrap" style="display:none;">
        <label>Specify item *</label>
        <input type="text" name="other_description" placeholder="e.g. HDMI splitter">
      </div>
      <button type="submit" class="btn-sm btn-primary">Add to Inventory</button>
    </form>
  </div>

  <div class="card">
    <p class="card-title">\U0001F4CA Current Inventory</p>
    <div style="overflow-x:auto;">
      <table class="data-table">
        <thead><tr><th>Item</th><th style="text-align:center;">Quantity On Hand</th><th>Last Updated</th></tr></thead>
        <tbody>
          {% for stock in hardware_stock %}
          <tr>
            <td><strong>{% if stock.item_type == 'OTHER' %}{{ stock.other_description }}{% else %}{{ stock.get_item_type_display }}{% endif %}</strong></td>
            <td style="text-align:center;">
              {% if stock.quantity <= 0 %}<span class="badge" style="background:#fee2e2;color:#991b1b;">{{ stock.quantity }}</span>
              {% elif stock.quantity <= 2 %}<span class="badge" style="background:#fef3c7;color:#92400e;">{{ stock.quantity }}</span>
              {% else %}<span class="badge" style="background:#dcfce7;color:#065f46;">{{ stock.quantity }}</span>{% endif %}
            </td>
            <td style="font-size:.78rem;color:#6b7280;">{{ stock.updated_at|date:"d M Y H:i" }}</td>
          </tr>
          {% empty %}
          <tr><td colspan="3" style="text-align:center;color:#9ca3af;">No inventory tracked yet \u2014 add stock above.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>

<script>
function switchTab(name, btn) {'''


def main():
    print("-- Applying MultiChoice Hardware Sales + Inventory --\n")

    patch("core/models.py", MODELS_OLD, MODELS_NEW, MODELS_MARKER,
          "models.py: MultiChoiceHardwareStock + MultiChoiceHardwareSale")

    migration_path = os.path.join(BASE_DIR, "core", "migrations", "0039_multichoice_hardware.py")
    if os.path.exists(migration_path):
        print("SKIP  migration 0039: already exists, skipping.")
    else:
        write("core/migrations/0039_multichoice_hardware.py", MIGRATION_CONTENT)
        print("OK    Created core/migrations/0039_multichoice_hardware.py")

    patch("core/views.py", VIEWS_OLD_ANCHOR, VIEWS_NEW_BLOCK, VIEWS_MARKER,
          "views.py: record_multichoice_hardware_sale + add_multichoice_hardware_stock")
    patch("core/views.py", DASH_CONTEXT_OLD, DASH_CONTEXT_NEW, DASH_CONTEXT_MARKER,
          "views.py: multichoice_dashboard context")
    patch("core/urls.py", URLS_OLD_ANCHOR, URLS_NEW_BLOCK, URLS_MARKER,
          "urls.py: 2 new routes")
    patch("templates/multichoice_dashboard.html", TAB_BAR_OLD, TAB_BAR_NEW, TEMPLATE_MARKER,
          "multichoice_dashboard.html: tab bar buttons")
    patch("templates/multichoice_dashboard.html", PANELS_OLD, PANELS_NEW, "tab-hardware-inventory",
          "multichoice_dashboard.html: tab panels")

    print("\n-- Done --")
    print("Next steps:")
    print("  python manage.py makemigrations --check   # should say 'No changes detected'")
    print("  python manage.py migrate")
    print("  python manage.py check")
    print("  git add . && git commit -m 'Add MultiChoice hardware sales + inventory' && git push")


if __name__ == "__main__":
    main()
