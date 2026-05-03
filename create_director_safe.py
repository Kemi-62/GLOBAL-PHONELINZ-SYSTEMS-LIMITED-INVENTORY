import os

content = '''{% extends "base.html" %}
{% block content %}
<style>
.page-title{font-size:1.3rem;font-weight:700;color:#004F9F;margin:0 0 1.5rem}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem;margin-bottom:1.5rem}
.kpi{background:#fff;border-radius:10px;border:1px solid #e5e7eb;padding:1rem 1.2rem}
.kpi-label{font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:#6b7280;margin:0 0 .3rem}
.kpi-value{font-size:1.5rem;font-weight:700;color:#111827;margin:0}
.kpi.green{border-left:4px solid #10b981}.kpi.blue{border-left:4px solid #3b82f6}.kpi.amber{border-left:4px solid #f59e0b}
.tab-bar{display:flex;gap:.4rem;overflow-x:auto;padding:.4rem 0;margin-bottom:1.5rem;border-bottom:2px solid #e5e7eb}
.tab-btn{flex-shrink:0;padding:.55rem 1.1rem;border:none;border-radius:8px 8px 0 0;background:transparent;color:#6b7280;font-size:.85rem;font-weight:600;cursor:pointer;white-space:nowrap;border-bottom:3px solid transparent;margin-bottom:-2px}
.tab-btn:hover{background:#f3f4f6;color:#111}
.tab-btn.active{color:#004F9F;border-bottom-color:#004F9F;background:#eff6ff}
.tab-panel{display:none}.tab-panel.active{display:block}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:1.2rem 1.4rem;margin-bottom:1.2rem}
.card-title{font-size:1rem;font-weight:700;color:#111827;margin:0 0 1rem}
.badge{display:inline-block;padding:.2rem .55rem;border-radius:999px;font-size:.72rem;font-weight:700}
.badge-green{background:#d1fae5;color:#065f46}.badge-red{background:#fee2e2;color:#991b1b}
.badge-amber{background:#fef3c7;color:#92400e}.badge-blue{background:#dbeafe;color:#1e40af}
.data-table{width:100%;border-collapse:collapse;font-size:.85rem}
.data-table th{background:#f9fafb;color:#374151;font-weight:600;padding:.65rem .9rem;text-align:left;border-bottom:1px solid #e5e7eb}
.data-table td{padding:.6rem .9rem;border-bottom:1px solid #f3f4f6;color:#374151;vertical-align:top}
.data-table tr:last-child td{border-bottom:none}
.data-table tr:hover td{background:#fafafa}
.form-group{margin-bottom:.8rem}
.form-group label{font-size:.78rem;font-weight:600;color:#374151;display:block;margin-bottom:.3rem}
.form-group input,.form-group select,.form-group textarea{width:100%;padding:.5rem .75rem;border:1px solid #d1d5db;border-radius:6px;font-size:.88rem;color:#111;background:#fff;box-sizing:border-box}
.form-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.8rem}
.btn-sm{padding:.5rem 1rem;font-size:.85rem;border-radius:6px;border:none;cursor:pointer;font-weight:600;display:inline-block;text-decoration:none}
.btn-primary{background:#004F9F;color:#fff}.btn-success{background:#10b981;color:#fff}
.btn-danger{background:#ef4444;color:#fff}.btn-outline{background:transparent;border:1px solid #d1d5db;color:#374151}
.btn-sm:hover{opacity:.88}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:1.2rem}
@media(max-width:700px){.two-col{grid-template-columns:1fr}}
.filter-bar{display:flex;gap:.6rem;flex-wrap:wrap;align-items:flex-end;margin-bottom:1rem}
.filter-bar input,.filter-bar select{padding:.45rem .7rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem}
.filter-label{font-size:.75rem;font-weight:600;color:#374151;display:block;margin-bottom:.2rem}
.release-target{display:none;margin-top:.6rem}
.release-target.show{display:block}
pre{background:#f5f5f5;padding:.8rem;border-radius:6px;font-size:.75rem;overflow-x:auto;line-height:1.5}
</style>

<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.8rem;margin-bottom:1.5rem;">
  <h1 class="page-title" style="margin:0;">🏦 Director Safe Stock</h1>
  <a href="{% url \'director_dashboard\' %}" class="btn-sm btn-outline">← Dashboard</a>
</div>

<div class="kpi-grid">
  <div class="kpi green"><p class="kpi-label">Total Units</p><p class="kpi-value">{{ total_quantity }}</p></div>
  <div class="kpi blue"><p class="kpi-label">Total Value</p><p class="kpi-value">&#8358;{{ total_value|floatformat:0 }}</p></div>
  <div class="kpi amber"><p class="kpi-label">Products</p><p class="kpi-value">{{ stocks|length }}</p></div>
</div>

<div class="tab-bar">
  <button class="tab-btn active" onclick="switchTab(\'stock\',this)">📦 Current Stock</button>
  <button class="tab-btn" onclick="switchTab(\'release\',this)">📤 Release Stock</button>
  <button class="tab-btn" onclick="switchTab(\'history\',this)">📋 Release History</button>
  <button class="tab-btn" onclick="switchTab(\'add\',this)">➕ Add Stock</button>
  <button class="tab-btn" onclick="switchTab(\'csv\',this)">📂 Bulk Upload</button>
  <button class="tab-btn" onclick="switchTab(\'new\',this)">🆕 Create Product</button>
</div>

<div id="tab-stock" class="tab-panel active">
  <div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem;margin-bottom:1rem;">
      <p class="card-title" style="margin:0;">📦 Director Safe Inventory</p>
      <a href="?date_from={{ date_from }}&date_to={{ date_to }}&export=pdf" class="btn-sm btn-success">📥 Download PDF</a>
    </div>
    <form method="GET" class="filter-bar">
      <div><span class="filter-label">From Date</span><input type="date" name="date_from" value="{{ date_from }}"></div>
      <div><span class="filter-label">To Date</span><input type="date" name="date_to" value="{{ date_to }}"></div>
      <button type="submit" class="btn-sm btn-primary" style="align-self:flex-end;">Filter</button>
      <a href="{% url \'director_safe_stock\' %}" class="btn-sm btn-outline" style="align-self:flex-end;">Clear</a>
    </form>
    {% if stocks %}
    <div style="overflow-x:auto;">
      <table class="data-table">
        <thead><tr><th>Product</th><th>Category</th><th>Cost Price</th><th>Sell Price</th><th style="text-align:center;">Qty</th><th style="text-align:right;">Total Value</th><th>Date Added</th><th>Actions</th></tr></thead>
        <tbody>
          {% for stock in stocks %}
          <tr>
            <td><strong>{{ stock.product.model_name }}</strong></td>
            <td style="color:#9ca3af;">{{ stock.product.subcategory.category.name|default:"—" }}</td>
            <td>&#8358;{{ stock.product.cost_price|floatformat:0 }}</td>
            <td>&#8358;{{ stock.product.selling_price|floatformat:0 }}</td>
            <td style="text-align:center;"><span class="badge {% if stock.quantity == 0 %}badge-red{% elif stock.quantity < 3 %}badge-amber{% else %}badge-green{% endif %}">{{ stock.quantity }}</span></td>
            <td style="text-align:right;">&#8358;{{ stock.total_value|floatformat:0 }}</td>
            <td style="color:#9ca3af;font-size:.78rem;">{{ stock.date_added|date:"d M Y H:i" }}</td>
            <td>
              <div style="display:flex;gap:.4rem;flex-wrap:wrap;">
                <button onclick="editStock({{ stock.id }}, \'{{ stock.product.model_name }}\', {{ stock.quantity }})" class="btn-sm btn-outline" style="font-size:.75rem;padding:.3rem .6rem;">Edit Qty</button>
                <form method="POST" action="{% url \'delete_director_stock\' stock.id %}" style="display:inline;" onsubmit="return confirm(\'Delete?\');">
                  {% csrf_token %}<button type="submit" class="btn-sm btn-danger" style="font-size:.75rem;padding:.3rem .6rem;">Delete</button>
                </form>
              </div>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
    <p style="text-align:center;color:#9ca3af;padding:2rem 0;">No stock in director safe yet.</p>
    {% endif %}
  </div>
</div>

<div id="tab-release" class="tab-panel">
  <div class="card">
    <p class="card-title">📤 Release Stock from Director Safe</p>
    <p style="font-size:.83rem;color:#6b7280;margin-bottom:1rem;">Stock released to a branch safe adds to existing branch stock. Stock released to staff adds to their existing stock.</p>
    <form method="POST" action="{% url \'director_release_stock\' %}">
      {% csrf_token %}
      <div class="form-group">
        <label>Product to Release *</label>
        <select name="product_id" required onchange="updateAvailable(this)">
          <option value="">— Select Product —</option>
          {% for stock in stocks %}
          <option value="{{ stock.product.id }}" data-qty="{{ stock.quantity }}" data-name="{{ stock.product.model_name }}">{{ stock.product.model_name }} — {{ stock.quantity }} available</option>
          {% endfor %}
        </select>
      </div>
      <div id="avail-info" style="display:none;background:#eff6ff;padding:.5rem .9rem;border-radius:6px;font-size:.82rem;color:#1e40af;margin-bottom:.8rem;"></div>
      <div class="form-group">
        <label>Release Type *</label>
        <select name="release_type" id="release_type" required onchange="toggleReleaseTarget()">
          <option value="">— Select Release Type —</option>
          <option value="branch_safe">To Branch Safe (Manager distributes to staff)</option>
          <option value="staff">Directly to Staff Member</option>
          <option value="sale">Direct Sale (remove from safe)</option>
        </select>
      </div>
      <div id="branch-target" class="release-target">
        <div class="form-group">
          <label>Select Branch *</label>
          <select name="branch_id">
            <option value="">— Select Branch —</option>
            {% for branch in all_branches %}<option value="{{ branch.id }}">{{ branch.name }}</option>{% endfor %}
          </select>
        </div>
      </div>
      <div id="staff-target" class="release-target">
        <div class="form-group">
          <label>Select Staff Member *</label>
          <select name="staff_id">
            <option value="">— Select Staff —</option>
            {% for s in all_staff %}<option value="{{ s.id }}">{{ s.username }} — {{ s.branch.name|default:"No branch" }} ({{ s.role }})</option>{% endfor %}
          </select>
        </div>
      </div>
      <div class="form-group" style="margin-top:.6rem;">
        <label>Quantity *</label>
        <input type="number" name="quantity" min="1" required placeholder="How many units?">
      </div>
      <button type="submit" class="btn-sm btn-success" style="width:100%;margin-top:.5rem;">Release Stock</button>
    </form>
  </div>
</div>

<div id="tab-history" class="tab-panel">
  <div class="card">
    <p class="card-title">📋 Stock Release History</p>
    <form method="GET" class="filter-bar">
      <input type="hidden" name="tab" value="history">
      <div><span class="filter-label">From Date</span><input type="date" name="date_from" value="{{ date_from }}"></div>
      <div><span class="filter-label">To Date</span><input type="date" name="date_to" value="{{ date_to }}"></div>
      <button type="submit" class="btn-sm btn-primary" style="align-self:flex-end;">Filter</button>
      <a href="{% url \'director_safe_stock\' %}" class="btn-sm btn-outline" style="align-self:flex-end;">Clear</a>
    </form>
    <div style="overflow-x:auto;">
      <table class="data-table">
        <thead><tr><th>Date</th><th>Time</th><th>Action</th><th>Details</th><th>Done By</th></tr></thead>
        <tbody>
          {% for log in safe_logs %}
          <tr>
            <td style="white-space:nowrap;color:#9ca3af;">{{ log.timestamp|date:"d M Y" }}</td>
            <td style="color:#9ca3af;">{{ log.timestamp|time:"H:i" }}</td>
            <td><span class="badge {% if log.action == \'CREATE\' %}badge-green{% elif log.action == \'DELETE\' %}badge-red{% else %}badge-amber{% endif %}">{{ log.action }}</span></td>
            <td style="max-width:350px;font-size:.82rem;line-height:1.5;">{{ log.description }}</td>
            <td><strong>{{ log.user.username|default:"System" }}</strong></td>
          </tr>
          {% empty %}
          <tr><td colspan="5" style="text-align:center;color:#9ca3af;padding:2rem 0;">No release history found.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% if safe_logs.has_other_pages %}
    <div style="display:flex;justify-content:center;gap:.5rem;margin-top:1rem;flex-wrap:wrap;">
      {% if safe_logs.has_previous %}<a href="?log_page={{ safe_logs.previous_page_number }}&date_from={{ date_from }}&date_to={{ date_to }}" class="btn-sm btn-outline">← Prev</a>{% endif %}
      <span style="padding:.5rem 1rem;font-size:.85rem;color:#6b7280;">Page {{ safe_logs.number }} of {{ safe_logs.paginator.num_pages }}</span>
      {% if safe_logs.has_next %}<a href="?log_page={{ safe_logs.next_page_number }}&date_from={{ date_from }}&date_to={{ date_to }}" class="btn-sm btn-outline">Next →</a>{% endif %}
    </div>
    {% endif %}
  </div>
</div>

<div id="tab-add" class="tab-panel">
  <div class="card">
    <p class="card-title">➕ Add Existing Product to Director Safe</p>
    <form method="POST" action="{% url \'add_director_stock\' %}">
      {% csrf_token %}
      <div class="form-group"><label>Product *</label>
        <select name="product_id" required>
          <option value="">— Select Product —</option>
          {% for p in products %}<option value="{{ p.id }}">{{ p.model_name }}</option>{% endfor %}
        </select>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Quantity *</label><input type="number" name="quantity" min="1" required></div>
        <div class="form-group"><label>Notes</label><input type="text" name="notes" placeholder="Optional notes"></div>
      </div>
      <button type="submit" class="btn-sm btn-primary">Add to Director Safe</button>
    </form>
  </div>
</div>

<div id="tab-csv" class="tab-panel">
  <div class="card">
    <p class="card-title">📂 Bulk Upload via CSV</p>
    <form method="POST" action="{% url \'upload_director_csv\' %}" enctype="multipart/form-data">
      {% csrf_token %}
      <div class="form-group"><label>Select CSV File *</label><input type="file" name="csv_file" accept=".csv" required></div>
      <button type="submit" class="btn-sm btn-success" style="margin-bottom:1rem;">📤 Upload</button>
    </form>
    <pre>model_name,category,subcategory,cost_price,selling_price,quantity
iPhone 15 Pro,Phones,Smartphones,600000,850000,5
S24 Ultra,Phones,Android,500000,700000,3</pre>
  </div>
</div>

<div id="tab-new" class="tab-panel">
  <div class="card">
    <p class="card-title">🆕 Create New Product and Add to Safe</p>
    <form method="POST" action="{% url \'create_director_product\' %}">
      {% csrf_token %}
      <div class="form-row">
        <div class="form-group"><label>Category *</label>
          <select name="category_id" required>
            <option value="new">+ Create New</option>
            {% for cat in categories %}<option value="{{ cat.id }}">{{ cat.name }}</option>{% endfor %}
          </select>
        </div>
        <div class="form-group"><label>New Category Name</label><input type="text" name="new_category_name" placeholder="e.g. Phones"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Sub Category *</label><input type="text" name="subcategory_name" required placeholder="e.g. Smartphones"></div>
        <div class="form-group"><label>Model Name *</label><input type="text" name="model_name" required placeholder="e.g. iPhone 15 Pro"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Cost Price (N) *</label><input type="number" step="0.01" name="cost_price" required></div>
        <div class="form-group"><label>Selling Price (N) *</label><input type="number" step="0.01" name="selling_price" required></div>
        <div class="form-group"><label>Quantity *</label><input type="number" name="quantity" min="1" required></div>
      </div>
      <div class="form-group"><label>IMEI / Serial</label><input type="text" name="imei_serial" placeholder="Leave blank for accessories"></div>
      <div class="form-group"><label>Description</label><textarea name="description" rows="2"></textarea></div>
      <button type="submit" class="btn-sm btn-primary">Create and Add to Safe</button>
    </form>
  </div>
</div>

<script>
function switchTab(name, btn) {
  document.querySelectorAll(\'.tab-panel\').forEach(p => p.classList.remove(\'active\'));
  document.querySelectorAll(\'.tab-btn\').forEach(b => b.classList.remove(\'active\'));
  document.getElementById(\'tab-\' + name).classList.add(\'active\');
  btn.classList.add(\'active\');
  history.replaceState(null, \'\', \'#\' + name);
}
document.addEventListener(\'DOMContentLoaded\', function() {
  const hash = location.hash.replace(\'#\',\'\');
  if (hash) { const btn = document.querySelector(\'[onclick*="switchTab(\\\'\' + hash + \'\\\'"]}\'); if (btn) switchTab(hash, btn); }
});
function toggleReleaseTarget() {
  const type = document.getElementById(\'release_type\').value;
  document.getElementById(\'branch-target\').classList.toggle(\'show\', type === \'branch_safe\' || type === \'sale\');
  document.getElementById(\'staff-target\').classList.toggle(\'show\', type === \'staff\');
}
function updateAvailable(sel) {
  const opt = sel.options[sel.selectedIndex];
  const qty = opt.dataset.qty; const name = opt.dataset.name;
  const info = document.getElementById(\'avail-info\');
  if (qty && name) { info.style.display=\'block\'; info.textContent=\'Available: \' + qty + \' unit(s) of \' + name; }
  else { info.style.display=\'none\'; }
}
function editStock(id, name, qty) {
  const newQty = prompt(\'Edit quantity for \' + name + \' (current: \' + qty + \'):\', qty);
  if (newQty !== null && !isNaN(newQty) && newQty >= 0) { window.location.href = \'/edit-director-stock/\' + id + \'/?quantity=\' + newQty; }
}
</script>
{% endblock %}'''

os.makedirs('/home/runner/workspace/templates/director', exist_ok=True)
open('/home/runner/workspace/templates/director/director_safe.html', 'w').write(content)
print('Template created successfully')
