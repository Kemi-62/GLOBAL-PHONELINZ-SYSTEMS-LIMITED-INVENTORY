#!/usr/bin/env python3
"""
apply_catalog_redesign.py  --  Retail dashboard "My Catalog" redesign

Run from the project root (the folder with manage.py):
    python apply_catalog_redesign.py

What changes (safe to run twice; the second run prints SKIP):
  * My Catalog tab is now grouped Category > Sub-category, with counts,
    "jump to" links, and product cards (mobile friendly) instead of one wide table.
  * Search now actually works (it was wired to nothing before). It searches
    name, colour and IMEI.
  * Quick filters: All / In stock / Low (1-2 left) / Out, each with a count.
  * Every card has a Sell button: it jumps to Record Sale with that product
    already in the sale (tapping Sell again adds one more unit).
  * Price is shown on every card.
  * Fixes the "Total Units" tile on the dashboard (it showed a stray 0 in front
    of the number, e.g. "011", and counted product lines, not units).
No database changes. Files touched: templates/retail_dashboard.html, core/views.py
(retail_dashboard function only: ordering + one extra number).
"""
import os, re, sys

MARK = "CATALOG_REDESIGN_V1"
TPL = "templates/retail_dashboard.html"
VIEWS = "core/views.py"

if not (os.path.exists("manage.py") and os.path.exists(TPL) and os.path.exists(VIEWS)):
    sys.exit("Run this from the project root (the folder that contains manage.py).")

def read(p):
    with open(p, encoding="utf-8", newline="") as f:
        return f.read()

def write(p, s):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)

def backup(p, s):
    b = p + ".pre_catalog.bak"
    if not os.path.exists(b):
        write(b, s)

CSS = r"""
/* CATALOG_REDESIGN_V1 */
.cg-head{display:flex;justify-content:space-between;align-items:center;gap:.6rem;flex-wrap:wrap;margin-bottom:.8rem}
.cg-search{padding:.5rem .8rem;border:1px solid #d1d5db;border-radius:8px;font-size:.88rem;width:100%;max-width:320px;box-sizing:border-box}
.cg-search:focus{outline:none;border-color:#004F9F;box-shadow:0 0 0 2px rgba(0,79,159,.12)}
.cg-chips{display:flex;gap:.45rem;flex-wrap:wrap;margin-bottom:.7rem}
.cg-chip{border:1px solid #d1d5db;background:#fff;color:#374151;border-radius:999px;padding:.35rem .8rem;font-size:.8rem;font-weight:600;cursor:pointer}
.cg-chip.active{background:#004F9F;border-color:#004F9F;color:#fff}
.cg-chip .cg-count{display:inline-block;margin-left:.25rem;font-weight:700;opacity:.85}
.cg-jump{display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:1rem;padding-bottom:.8rem;border-bottom:1px solid #f3f4f6}
.cg-jumplink{font-size:.78rem;color:#004F9F;background:#eff6ff;border-radius:6px;padding:.25rem .6rem;text-decoration:none;font-weight:600}
.cg-jumplink span{color:#6b7280;font-weight:700;margin-left:.2rem}
.cg-cat{margin-bottom:1.4rem;scroll-margin-top:70px}
.cg-cat-title{font-size:1rem;font-weight:800;color:#111827;margin:0 0 .5rem;padding-bottom:.3rem;border-bottom:2px solid #004F9F}
.cg-sub-title{font-size:.82rem;font-weight:700;color:#4b5563;margin:.8rem 0 .5rem;text-transform:uppercase;letter-spacing:.04em}
.cg-cat-count,.cg-sub-count{display:inline-block;margin-left:.35rem;background:#f3f4f6;color:#374151;border-radius:999px;padding:.05rem .5rem;font-size:.72rem;font-weight:700;letter-spacing:0}
.cg-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:.7rem}
.cg-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:.8rem .9rem;display:flex;flex-direction:column;gap:.35rem}
.cg-card[data-qty="0"]{background:#fafafa}
.cg-top{display:flex;align-items:flex-start;justify-content:space-between;gap:.4rem}
.cg-name{font-weight:700;font-size:.9rem;color:#111827;line-height:1.25;word-break:break-word}
.cg-color{flex-shrink:0;font-size:.68rem;font-weight:700;background:#f3f4f6;color:#4b5563;border-radius:6px;padding:.12rem .4rem}
.cg-price{font-size:1.05rem;font-weight:800;color:#004F9F}
.cg-imei{font-size:.72rem;color:#9ca3af;font-family:monospace;word-break:break-all}
.cg-actions{display:flex;gap:.4rem;margin-top:.3rem}
.cg-actions .btn-sm{flex:1;padding:.45rem .5rem;font-size:.8rem;text-align:center}
.cg-actions .btn-sm[disabled]{opacity:.4;cursor:not-allowed}
.cg-empty{text-align:center;color:#9ca3af;padding:2rem 0}
@media(max-width:480px){.cg-grid{grid-template-columns:1fr 1fr;gap:.5rem}.cg-card{padding:.65rem}.cg-search{max-width:none}}
"""

NEW_TAB = r"""<!-- CATALOG_REDESIGN_V1 -->
<!-- ══════════ TAB: MY CATALOG ══════════ -->
<div id="tab-catalog" class="tab-panel">
  <div class="card">
    <div class="cg-head">
      <p class="card-title" style="margin:0;">📦 Your Product Catalog</p>
      <input type="search" id="catalog-search" class="cg-search" placeholder="Search name, colour or IMEI…" oninput="filterCatalog()" autocomplete="off">
    </div>
    {% if staff_stock %}
    <div class="cg-chips" id="cg-status-chips">
      <button type="button" class="cg-chip active" onclick="setCatalogStatus('all',this)">All <span class="cg-count" id="cg-n-all">0</span></button>
      <button type="button" class="cg-chip" onclick="setCatalogStatus('instock',this)">In stock <span class="cg-count" id="cg-n-instock">0</span></button>
      <button type="button" class="cg-chip" onclick="setCatalogStatus('low',this)">Low (1-2) <span class="cg-count" id="cg-n-low">0</span></button>
      <button type="button" class="cg-chip" onclick="setCatalogStatus('out',this)">Out <span class="cg-count" id="cg-n-out">0</span></button>
    </div>
    {% regroup staff_stock by product.subcategory.category as cat_groups %}
    <div class="cg-jump">
      {% for cg in cat_groups %}<a href="#" class="cg-jumplink" onclick="jumpCatalog('cg-cat-{{ cg.grouper.id }}');return false;">{{ cg.grouper.name }}<span>{{ cg.list|length }}</span></a>{% endfor %}
    </div>
    <div id="cg-list">
      {% for cg in cat_groups %}
      <section class="cg-cat" id="cg-cat-{{ cg.grouper.id }}">
        <h3 class="cg-cat-title">{{ cg.grouper.name }}<span class="cg-cat-count">{{ cg.list|length }}</span></h3>
        {% regroup cg.list by product.subcategory as sub_groups %}
        {% for sg in sub_groups %}
        <div class="cg-sub">
          <h4 class="cg-sub-title">{{ sg.grouper.name }}<span class="cg-sub-count">{{ sg.list|length }}</span></h4>
          <div class="cg-grid">
            {% for stock in sg.list %}
            <div class="cg-card" data-qty="{{ stock.quantity }}" data-name="{{ stock.product.model_name|lower }} {{ stock.product.color|default:''|lower }} {{ stock.product.imei_serial|default:''|lower }}">
              <div class="cg-top">
                <span class="cg-name">{{ stock.product.model_name }}</span>
                {% if stock.product.color %}<span class="cg-color">{{ stock.product.color }}</span>{% endif %}
              </div>
              <div class="cg-price">₦{{ stock.product.selling_price|floatformat:"0g" }}</div>
              <div>
                <span class="badge {% if stock.quantity == 0 %}badge-red{% elif stock.quantity <= 2 %}badge-amber{% else %}badge-green{% endif %}">{% if stock.quantity == 0 %}Out of stock{% elif stock.quantity <= 2 %}Low · {{ stock.quantity }} left{% else %}{{ stock.quantity }} in stock{% endif %}</span>
              </div>
              {% if stock.product.imei_serial %}<div class="cg-imei">IMEI {{ stock.product.imei_serial }}</div>{% endif %}
              <div class="cg-actions">
                <button type="button" class="btn-sm btn-primary"{% if stock.quantity == 0 %} disabled{% endif %} onclick="sellFromCatalog({{ stock.product.id }})">Sell</button>
                <button type="button" class="btn-sm btn-outline" onclick="editQuantity({{ stock.id }}, {{ stock.quantity }})">Edit Qty</button>
              </div>
            </div>
            {% endfor %}
          </div>
        </div>
        {% endfor %}
      </section>
      {% endfor %}
      <p id="cg-empty" class="cg-empty" style="display:none;">No products match your search or filter.</p>
    </div>
    {% else %}
    <p class="cg-empty">No products in your catalog yet. Add some in the Add Products tab.</p>
    {% endif %}
  </div>
</div>

"""

NEW_JS = r"""// CATALOG_REDESIGN_V1: grouped catalog (search, status chips, jump, sell)
var catalogStatus = 'all';
function catalogStatusOf(q) {
  q = parseInt(q, 10) || 0;
  return q === 0 ? 'out' : (q <= 2 ? 'low' : 'instock');
}
function setCatalogStatus(status, btn) {
  catalogStatus = status;
  document.querySelectorAll('#cg-status-chips .cg-chip').forEach(function (b) { b.classList.remove('active'); });
  if (btn) btn.classList.add('active');
  filterCatalog();
}
function updateCatalogChipCounts() {
  var all = 0, instock = 0, low = 0, out = 0;
  document.querySelectorAll('.cg-card').forEach(function (c) {
    var s = catalogStatusOf(c.dataset.qty);
    all++;
    if (s === 'out') out++; else instock++;
    if (s === 'low') low++;
  });
  var set = function (id, n) { var el = document.getElementById(id); if (el) el.textContent = n; };
  set('cg-n-all', all); set('cg-n-instock', instock); set('cg-n-low', low); set('cg-n-out', out);
}
function filterCatalog() {
  var input = document.getElementById('catalog-search');
  if (!input) return;
  var q = input.value.trim().toLowerCase();
  var shown = 0;
  document.querySelectorAll('.cg-card').forEach(function (card) {
    var s = catalogStatusOf(card.dataset.qty);
    var okStatus = catalogStatus === 'all' ||
      (catalogStatus === 'instock' ? s !== 'out' : s === catalogStatus);
    var okText = !q || card.dataset.name.indexOf(q) !== -1;
    var vis = okStatus && okText;
    card.style.display = vis ? '' : 'none';
    card.dataset.vis = vis ? '1' : '0';
    if (vis) shown++;
  });
  document.querySelectorAll('.cg-sub').forEach(function (sub) {
    var n = sub.querySelectorAll('.cg-card[data-vis="1"]').length;
    sub.style.display = n ? '' : 'none';
    var badge = sub.querySelector('.cg-sub-count');
    if (badge) badge.textContent = n;
  });
  document.querySelectorAll('.cg-cat').forEach(function (cat) {
    var n = cat.querySelectorAll('.cg-card[data-vis="1"]').length;
    cat.style.display = n ? '' : 'none';
    var badge = cat.querySelector('.cg-cat-count');
    if (badge) badge.textContent = n;
  });
  var empty = document.getElementById('cg-empty');
  if (empty) empty.style.display = shown ? 'none' : 'block';
}
function jumpCatalog(id) {
  var el = document.getElementById(id);
  if (el && el.style.display !== 'none') el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function sellFromCatalog(pid) {
  pid = String(pid);
  var salesBtn = document.querySelector('[onclick*="switchTab(\'sales\'"]');
  if (salesBtn) switchTab('sales', salesBtn);
  var rows = document.querySelectorAll('#sale-items-body tr');
  var existing = null, empty = null;
  rows.forEach(function (r) {
    var sel = r.querySelector('.sale-product');
    if (!sel) return;
    if (sel.value === pid && !existing) existing = r;
    if (!sel.value && !empty) empty = r;
  });
  if (existing) {
    var id0 = parseInt(existing.id.replace('sale-row-', ''), 10);
    var qtyInput = existing.querySelector('.sale-qty');
    var max = (typeof productData !== 'undefined' && productData[pid]) ? productData[pid].qty : 1;
    var cur = parseInt(qtyInput.value, 10) || 0;
    if (cur < max) qtyInput.value = cur + 1;
    else alert('Only ' + max + ' in stock for this product.');
    rowTotal(id0);
  } else {
    var target = empty;
    if (!target) { addSaleRow(); target = document.getElementById('sale-row-' + rowCount); }
    var id = parseInt(target.id.replace('sale-row-', ''), 10);
    var select = target.querySelector('.sale-product');
    var ts = select.tomselect || select.tomSelectInstance;
    if (ts) { ts.setValue(pid); } else { select.value = pid; }
    rowPrice(id);
  }
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
document.addEventListener('DOMContentLoaded', updateCatalogChipCounts);
"""

# ---------------- view ----------------
v = read(VIEWS)
if MARK in v:
    print("SKIP     %s already applied" % VIEWS)
else:
    fs = v.find("def retail_dashboard(request):")
    if fs < 0:
        sys.exit("ERROR: could not find retail_dashboard in %s (template already changed; re-run after fixing)" % VIEWS)
    fe = v.find("\n\n\n", fs)
    fe = fe if fe > 0 else len(v)
    body = v[fs:fe]
    old_q = ('    staff_stock = StaffStock.objects.filter(\n'
             '        staff=staff\n'
             '    ).select_related("product", "product__subcategory")\n')
    new_q = ('    # CATALOG_REDESIGN_V1: ordered so the catalog can group by category / sub-category\n'
             '    staff_stock = StaffStock.objects.filter(\n'
             '        staff=staff\n'
             '    ).select_related("product", "product__subcategory", "product__subcategory__category").order_by(\n'
             '        "product__subcategory__category__name", "product__subcategory__category__id",\n'
             '        "product__subcategory__name", "product__subcategory__id", "product__model_name", "id",\n'
             '    )\n')
    old_ctx = '        "staff_stock": staff_stock,\n'
    new_ctx = ('        "staff_stock": staff_stock,\n'
               '        "total_units": sum(s.quantity for s in staff_stock),\n')
    if old_q not in body or old_ctx not in body:
        sys.exit("ERROR: retail_dashboard() looks different from what this script expects. "
                 "Nothing was changed in core/views.py. Send me the function and I will adjust.")
    body2 = body.replace(old_q, new_q, 1).replace(old_ctx, new_ctx, 1)
    backup(VIEWS, v)
    write(VIEWS, v[:fs] + body2 + v[fe:])
    print("APPLIED  %s (retail_dashboard ordering + total_units)" % VIEWS)

# ---------------- template ----------------
t = read(TPL)
if MARK in t:
    print("SKIP     %s already applied" % TPL)
    tpl_done = True
else:
    tpl_done = False
    o = t
    # 1) CSS
    i = o.find("</style>")
    if i < 0:
        sys.exit("ERROR: could not find </style> in %s (nothing changed)" % TPL)
    o = o[:i] + CSS + o[i:]
    # 2) tab html
    a = o.find("<!-- ══════════ TAB: MY CATALOG ══════════ -->")
    b = o.find("<!-- ══════════ TAB: ADD PRODUCTS ══════════ -->")
    if a < 0 or b < 0 or b < a:
        sys.exit("ERROR: could not find the My Catalog tab markers in %s (nothing changed)" % TPL)
    o = o[:a] + NEW_TAB + o[b:]
    # 3) js
    m = re.search(r"function filterCatalog\(\) \{.*?\n\}\n", o, re.S)
    if not m:
        sys.exit("ERROR: could not find filterCatalog() in %s (nothing changed)" % TPL)
    o = o[:m.start()] + NEW_JS + o[m.end():]
    # 4) total units tile
    old_tile = "{% for s in staff_stock %}{% if forloop.first %}0{% endif %}{% endfor %}{{ staff_stock|length }}"
    if old_tile in o:
        o = o.replace(old_tile, "{{ total_units }}")
    else:
        print("NOTE     Total Units tile text not found (already changed?) - left alone")
    backup(TPL, t)
    write(TPL, o)
    print("APPLIED  %s (catalog tab, search, chips, sell button, Total Units tile)" % TPL)

print("\nDone. Restart the app / hard-refresh the Retail dashboard (Ctrl+Shift+R).")