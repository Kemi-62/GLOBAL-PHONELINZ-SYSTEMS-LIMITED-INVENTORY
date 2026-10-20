#!/usr/bin/env python3
"""
apply_catalog_manager_director.py -- grouped stock catalog for Manager and Director

Run from the project root (the folder with manage.py):
    python apply_catalog_manager_director.py

Safe to run twice (second run prints SKIP). No database changes.

What you get
  MANAGER  -> "Retail & Stock" tab: Safe Stock Levels becomes a grouped catalog
              (Category > Sub-category), search, All/In stock/Low/Out filters,
              prices, and what each retail staff member is holding. A Release
              button on each card fills in the Release Stock form for you.
  DIRECTOR -> All Branch Stock page rebuilt the same way: one card per product with
              its total and a per-branch breakdown (Safe vs staff). Branch filter
              now keeps its selection; the broken "Value" column is fixed.
  DIRECTOR -> Director Safe > Current Stock: grouped overview on top (totals per
              product across all additions) with a Release button that opens the
              Release tab with the product chosen. The old per-addition table
              (edit / delete) is still there, inside "Show every addition".
  Also fixes a small bug on the Director Safe page: opening it with a #tab in the
  address (e.g. #release) threw a JavaScript error.

Files: core/catalog_ui.py (new), templates/partials/catalog_assets.html (new),
templates/partials/catalog_cards.html (new), templates/director/all_branch_stock.html,
templates/director/director_safe.html, templates/manager_dashboard.html, core/views.py
"""
import os, re, sys

MARK = "CATALOG_ROLES_V1"
FILES = ["manage.py", "core/views.py", "templates/director/all_branch_stock.html",
         "templates/director/director_safe.html", "templates/manager_dashboard.html"]
for f in FILES:
    if not os.path.exists(f):
        sys.exit("Missing %s. Run this from the project root (the folder that contains manage.py)." % f)
os.makedirs("templates/partials", exist_ok=True)

def read(p):
    with open(p, encoding="utf-8", newline="") as fh:
        return fh.read()

def write(p, s):
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(s)

def backup(p, s):
    b = p + ".pre_catroles.bak"
    if not os.path.exists(b):
        write(b, s)

def new_file(path, text, label):
    if os.path.exists(path) and MARK in read(path):
        print("SKIP     %s already applied" % path)
        return
    write(path, text)
    print("APPLIED  %s (%s)" % (path, label))

# =============================================================== catalog_ui.py
CATALOG_UI = r'''# CATALOG_ROLES_V1
"""Shared helper: turn a flat list of stock items into Category > Sub-category groups
for the grouped catalog (partials/catalog_cards.html)."""


def _status(q):
    q = int(q or 0)
    return "out" if q <= 0 else ("low" if q <= 2 else "instock")


def build_catalog(items, prefix="cg", value_label="Value"):
    """items: list of dicts with keys
         pid, name, color, price, qty, imei, cat_id, cat_name, sub_id, sub_name,
         lines (list of {"label","value"}), extra (extra words to search), value (optional)
    Returns dict: groups, counts, total_units, total_value, value_label, empty
    """
    cats = {}
    counts = {"all": 0, "instock": 0, "low": 0, "out": 0}
    total_units = 0
    total_value = 0
    for it in items:
        st = _status(it.get("qty"))
        it = dict(it)
        it["status"] = st
        it["search"] = " ".join(
            str(x) for x in (it.get("name") or "", it.get("color") or "", it.get("imei") or "", it.get("extra") or "")
        ).lower()
        counts["all"] += 1
        if st != "out":
            counts["instock"] += 1
        if st == "low":
            counts["low"] += 1
        if st == "out":
            counts["out"] += 1
        total_units += int(it.get("qty") or 0)
        if it.get("value") is not None:
            total_value += it["value"]
        ckey = (it.get("cat_name") or "Uncategorised", it.get("cat_id") or 0)
        skey = (it.get("sub_name") or "Other", it.get("sub_id") or 0)
        cats.setdefault(ckey, {}).setdefault(skey, []).append(it)

    groups = []
    for (cname, cid) in sorted(cats, key=lambda k: (k[0].lower(), k[1])):
        subs = []
        n_cat = 0
        for (sname, sid) in sorted(cats[(cname, cid)], key=lambda k: (k[0].lower(), k[1])):
            its = sorted(cats[(cname, cid)][(sname, sid)], key=lambda i: ((i.get("name") or "").lower(), (i.get("color") or "").lower()))
            subs.append({"id": sid, "name": sname, "count": len(its), "items": its})
            n_cat += len(its)
        groups.append({"anchor": "%s-cat-%s" % (prefix, cid), "name": cname, "count": n_cat, "subs": subs})
    return {
        "groups": groups, "counts": counts, "total_units": total_units,
        "total_value": total_value, "value_label": value_label, "empty": not items,
    }
'''

# =============================================================== assets partial
ASSETS = r'''{# CATALOG_ROLES_V1 #}
<style>
.cg-head{display:flex;justify-content:space-between;align-items:center;gap:.6rem;flex-wrap:wrap;margin-bottom:.8rem}
.cg-search{padding:.5rem .8rem;border:1px solid #d1d5db;border-radius:8px;font-size:.88rem;width:100%;max-width:340px;box-sizing:border-box}
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
.cg-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:.7rem}
.cg-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:.8rem .9rem;display:flex;flex-direction:column;gap:.35rem}
.cg-card[data-status="out"]{background:#fafafa}
.cg-top{display:flex;align-items:flex-start;justify-content:space-between;gap:.4rem}
.cg-name{font-weight:700;font-size:.9rem;color:#111827;line-height:1.25;word-break:break-word}
.cg-color{flex-shrink:0;font-size:.68rem;font-weight:700;background:#f3f4f6;color:#4b5563;border-radius:6px;padding:.12rem .4rem}
.cg-price{font-size:1.05rem;font-weight:800;color:#004F9F}
.cg-value{font-size:.74rem;color:#6b7280}
.cg-imei{font-size:.72rem;color:#9ca3af;font-family:monospace;word-break:break-all}
.cg-lines{border-top:1px dashed #e5e7eb;padding-top:.35rem;display:flex;flex-direction:column;gap:.15rem}
.cg-line{display:flex;justify-content:space-between;gap:.5rem;font-size:.74rem;color:#4b5563}
.cg-line strong{color:#111827;text-align:right}
.cg-actions{display:flex;gap:.4rem;margin-top:.3rem}
.cg-actions .btn-sm{flex:1;padding:.45rem .5rem;font-size:.8rem;text-align:center}
.cg-actions .btn-sm[disabled]{opacity:.4;cursor:not-allowed}
.cg-empty{text-align:center;color:#9ca3af;padding:2rem 0}
.cg-details{margin-top:1rem;border-top:1px solid #f3f4f6;padding-top:.8rem}
.cg-details summary{cursor:pointer;font-weight:700;font-size:.85rem;color:#004F9F;margin-bottom:.8rem}
@media(max-width:480px){.cg-grid{grid-template-columns:1fr 1fr;gap:.5rem}.cg-card{padding:.65rem}.cg-search{max-width:none}}
</style>
<script>
window.CG = window.CG || (function () {
  function apply(root) {
    var q = (root.querySelector('.cg-search') || {value: ''}).value.trim().toLowerCase();
    var status = root.dataset.status || 'all';
    var shown = 0;
    root.querySelectorAll('.cg-card').forEach(function (card) {
      var s = card.dataset.status;
      var okS = status === 'all' || (status === 'instock' ? s !== 'out' : s === status);
      var okQ = !q || card.dataset.search.indexOf(q) !== -1;
      var vis = okS && okQ;
      card.style.display = vis ? '' : 'none';
      card.dataset.vis = vis ? '1' : '0';
      if (vis) shown++;
    });
    root.querySelectorAll('.cg-sub').forEach(function (sub) {
      var n = sub.querySelectorAll('.cg-card[data-vis="1"]').length;
      sub.style.display = n ? '' : 'none';
      var b = sub.querySelector('.cg-sub-count'); if (b) b.textContent = n;
    });
    root.querySelectorAll('.cg-cat').forEach(function (cat) {
      var n = cat.querySelectorAll('.cg-card[data-vis="1"]').length;
      cat.style.display = n ? '' : 'none';
      var b = cat.querySelector('.cg-cat-count'); if (b) b.textContent = n;
    });
    var e = root.querySelector('.cg-nomatch'); if (e) e.style.display = shown ? 'none' : 'block';
  }
  return {
    filter: function (input) { var r = input.closest('.cg-root'); if (r) apply(r); },
    status: function (btn, s) {
      var r = btn.closest('.cg-root'); if (!r) return;
      r.dataset.status = s;
      r.querySelectorAll('.cg-chip').forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      apply(r);
    },
    jump: function (id) {
      var el = document.getElementById(id);
      if (el && el.style.display !== 'none') el.scrollIntoView({behavior: 'smooth', block: 'start'});
    },
    setSelect: function (sel, val) {
      if (!sel) return;
      var ts = sel.tomselect || sel.tomSelectInstance;
      if (ts) { ts.setValue(String(val)); } else { sel.value = String(val); }
      sel.dispatchEvent(new Event('change', {bubbles: true}));
    }
  };
})();
</script>
'''

# =============================================================== cards partial
CARDS = r'''{# CATALOG_ROLES_V1  usage: {% include "partials/catalog_cards.html" with catalog=X action_label="Release" action_fn="myFn" %} #}
{% if catalog and not catalog.empty %}
<div class="cg-root" data-status="all">
  <div class="cg-head">
    <input type="search" class="cg-search" placeholder="Search name, colour, IMEI or holder…" oninput="CG.filter(this)" autocomplete="off">
  </div>
  <div class="cg-chips">
    <button type="button" class="cg-chip active" onclick="CG.status(this,'all')">All <span class="cg-count">{{ catalog.counts.all }}</span></button>
    <button type="button" class="cg-chip" onclick="CG.status(this,'instock')">In stock <span class="cg-count">{{ catalog.counts.instock }}</span></button>
    <button type="button" class="cg-chip" onclick="CG.status(this,'low')">Low (1-2) <span class="cg-count">{{ catalog.counts.low }}</span></button>
    <button type="button" class="cg-chip" onclick="CG.status(this,'out')">Out <span class="cg-count">{{ catalog.counts.out }}</span></button>
  </div>
  <div class="cg-jump">
    {% for g in catalog.groups %}<a href="#" class="cg-jumplink" onclick="CG.jump('{{ g.anchor }}');return false;">{{ g.name }}<span>{{ g.count }}</span></a>{% endfor %}
  </div>
  {% for g in catalog.groups %}
  <section class="cg-cat" id="{{ g.anchor }}">
    <h3 class="cg-cat-title">{{ g.name }}<span class="cg-cat-count">{{ g.count }}</span></h3>
    {% for sub in g.subs %}
    <div class="cg-sub">
      <h4 class="cg-sub-title">{{ sub.name }}<span class="cg-sub-count">{{ sub.count }}</span></h4>
      <div class="cg-grid">
        {% for it in sub.items %}
        <div class="cg-card" data-status="{{ it.status }}" data-search="{{ it.search }}">
          <div class="cg-top">
            <span class="cg-name">{{ it.name }}</span>
            {% if it.color %}<span class="cg-color">{{ it.color }}</span>{% endif %}
          </div>
          <div class="cg-price">₦{{ it.price|floatformat:"0g" }}</div>
          <div>
            <span class="badge {% if it.status == 'out' %}badge-red{% elif it.status == 'low' %}badge-amber{% else %}badge-green{% endif %}">{% if it.status == 'out' %}Out of stock{% elif it.status == 'low' %}Low · {{ it.qty }} left{% else %}{{ it.qty }} in stock{% endif %}</span>
          </div>
          {% if it.value is not None %}<div class="cg-value">{{ catalog.value_label }} ₦{{ it.value|floatformat:"0g" }}</div>{% endif %}
          {% if it.imei %}<div class="cg-imei">IMEI {{ it.imei }}</div>{% endif %}
          {% if it.lines %}<div class="cg-lines">{% for ln in it.lines %}<div class="cg-line"><span>{{ ln.label }}</span><strong>{{ ln.value }}</strong></div>{% endfor %}</div>{% endif %}
          {% if action_fn %}
          <div class="cg-actions">
            <button type="button" class="btn-sm btn-primary"{% if it.status == 'out' %} disabled{% endif %} onclick="{{ action_fn }}({{ it.pid }})">{{ action_label|default:"Select" }}</button>
          </div>
          {% endif %}
        </div>
        {% endfor %}
      </div>
    </div>
    {% endfor %}
  </section>
  {% endfor %}
  <p class="cg-empty cg-nomatch" style="display:none;">No products match your search or filter.</p>
</div>
{% else %}
<p class="cg-empty">No stock yet.</p>
{% endif %}
'''

# =============================================================== all branch stock page
ALL_STOCK = r'''{% extends "base.html" %}
{% block content %}
{# CATALOG_ROLES_V1 #}
{% include "partials/catalog_assets.html" %}
<style>
.page-title{font-size:1.3rem;font-weight:700;color:#004F9F;margin:0 0 1.5rem}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem;margin-bottom:1.5rem}
.kpi{background:#fff;border-radius:10px;border:1px solid #e5e7eb;padding:1rem 1.2rem}
.kpi-label{font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:#6b7280;margin:0 0 .3rem}
.kpi-value{font-size:1.4rem;font-weight:700;color:#111827;margin:0}
.kpi.green{border-left:4px solid #10b981}.kpi.blue{border-left:4px solid #3b82f6}.kpi.amber{border-left:4px solid #f59e0b}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:1.2rem 1.4rem;margin-bottom:1.2rem}
.badge{display:inline-block;padding:.2rem .55rem;border-radius:999px;font-size:.72rem;font-weight:700}
.badge-green{background:#d1fae5;color:#065f46}.badge-amber{background:#fef3c7;color:#92400e}.badge-red{background:#fee2e2;color:#991b1b}
.filter-bar{display:flex;gap:.6rem;flex-wrap:wrap;align-items:flex-end;margin-bottom:1.2rem}
.filter-bar select{padding:.45rem .7rem;border:1px solid #d1d5db;border-radius:6px;font-size:.83rem}
.btn-sm{padding:.45rem .9rem;font-size:.82rem;border-radius:6px;border:none;cursor:pointer;font-weight:600;text-decoration:none;display:inline-block}
.btn-primary{background:#004F9F;color:#fff}.btn-outline{background:transparent;border:1px solid #d1d5db;color:#374151}
</style>

<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:1rem;margin-bottom:1.5rem;">
  <h1 class="page-title" style="margin:0;">🏪 All Branch Stock</h1>
  <div style="display:flex;gap:.5rem;flex-wrap:wrap;">
    <a href="{% url 'stock_transfer' %}" class="btn-sm btn-primary">⇄ Transfer Stock</a>
    <a href="{% url 'director_dashboard' %}" class="btn-sm btn-outline">← Director Dashboard</a>
  </div>
</div>

<div class="kpi-grid">
  <div class="kpi green"><p class="kpi-label">Total Units{% if selected_branch %} (this branch){% else %} (all branches){% endif %}</p><p class="kpi-value">{{ total_units }}</p></div>
  <div class="kpi blue"><p class="kpi-label">Retail Value</p><p class="kpi-value">₦{{ total_value|floatformat:"0g" }}</p></div>
  <div class="kpi amber"><p class="kpi-label">Products</p><p class="kpi-value">{{ catalog.counts.all }}</p></div>
</div>

<div class="card">
  <form method="GET" class="filter-bar">
    <div>
      <label style="font-size:.75rem;font-weight:600;color:#374151;display:block;margin-bottom:.2rem;">Branch</label>
      <select name="branch" onchange="this.form.submit()">
        <option value="">All Branches</option>
        {% for b in branches %}<option value="{{ b.id }}" {% if selected_branch == b.id|stringformat:"s" %}selected{% endif %}>{{ b.name }}</option>{% endfor %}
      </select>
    </div>
    {% if selected_branch %}<a href="{% url 'director_all_branch_stock' %}" class="btn-sm btn-outline">Clear</a>{% endif %}
  </form>
  <p style="font-size:.82rem;color:#6b7280;margin:0 0 1rem;">One card per product. Each card shows the total and where the units are (branch safe vs staff).</p>
  {% include "partials/catalog_cards.html" with catalog=catalog %}
</div>
{% endblock %}
'''

# =============================================================== views.py pieces
ALL_STOCK_VIEW = r'''def director_all_branch_stock(request):
    # CATALOG_ROLES_V1: one card per product, with a per-branch breakdown
    from core.catalog_ui import build_catalog
    branch_filter = request.GET.get("branch", "")
    if not str(branch_filter).isdigit():
        branch_filter = ""

    safe_qs = BranchSafeStock.objects.filter(quantity__gt=0).select_related(
        "branch", "product", "product__subcategory", "product__subcategory__category")
    staff_qs = StaffStock.objects.filter(quantity__gt=0).select_related(
        "staff", "staff__branch", "product", "product__subcategory", "product__subcategory__category")
    if branch_filter:
        safe_qs = safe_qs.filter(branch_id=branch_filter)
        staff_qs = staff_qs.filter(staff__branch_id=branch_filter)

    by_product = {}

    def _entry(p):
        e = by_product.get(p.id)
        if e is None:
            sub = p.subcategory
            cat = sub.category if sub else None
            e = by_product[p.id] = {
                "pid": p.id, "name": p.model_name, "color": p.color or "", "price": p.selling_price,
                "qty": 0, "imei": p.imei_serial or "",
                "cat_id": cat.id if cat else 0, "cat_name": cat.name if cat else "Uncategorised",
                "sub_id": sub.id if sub else 0, "sub_name": sub.name if sub else "Other",
                "branches": {}, "words": set(),
            }
        return e

    for s in safe_qs:
        e = _entry(s.product)
        e["qty"] += s.quantity
        b = e["branches"].setdefault(s.branch.name, {"safe": 0, "staff": []})
        b["safe"] += s.quantity
        e["words"].add(s.branch.name)
    for s in staff_qs:
        e = _entry(s.product)
        e["qty"] += s.quantity
        bname = s.staff.branch.name if s.staff.branch else "No branch"
        b = e["branches"].setdefault(bname, {"safe": 0, "staff": []})
        b["staff"].append((s.staff.username, s.quantity))
        e["words"].add(bname)
        e["words"].add(s.staff.username)

    items = []
    for e in by_product.values():
        lines = []
        for bname in sorted(e["branches"]):
            b = e["branches"][bname]
            parts = []
            if b["safe"]:
                parts.append("Safe %d" % b["safe"])
            for uname, q in sorted(b["staff"]):
                parts.append("%s %d" % (uname, q))
            lines.append({"label": bname, "value": " · ".join(parts)})
        items.append({
            "pid": e["pid"], "name": e["name"], "color": e["color"], "price": e["price"], "qty": e["qty"],
            "imei": e["imei"], "cat_id": e["cat_id"], "cat_name": e["cat_name"],
            "sub_id": e["sub_id"], "sub_name": e["sub_name"], "lines": lines,
            "extra": " ".join(sorted(e["words"])), "value": e["qty"] * (e["price"] or 0),
        })
    catalog = build_catalog(items, prefix="dir", value_label="Retail value")

    return render(request, "director/all_branch_stock.html", {
        "catalog": catalog,
        "branches": Branch.objects.all(),
        "selected_branch": branch_filter,
        "total_units": catalog["total_units"],
        "total_value": catalog["total_value"],
    })
'''

SAFE_CTX_CODE = r'''    # CATALOG_ROLES_V1: grouped overview of what the Director Safe holds right now (all dates)
    from core.catalog_ui import build_catalog as _bc
    _agg = {}
    for _s in DirectorSafeStock.objects.filter(product__isnull=False).select_related(
            "product", "product__subcategory", "product__subcategory__category"):
        _p = _s.product
        _sub = _p.subcategory
        _cat = _sub.category if _sub else None
        _e = _agg.setdefault(_p.id, {
            "pid": _p.id, "name": _p.model_name, "color": _p.color or "", "price": _p.selling_price,
            "qty": 0, "imei": _p.imei_serial or "",
            "cat_id": _cat.id if _cat else 0, "cat_name": _cat.name if _cat else "Uncategorised",
            "sub_id": _sub.id if _sub else 0, "sub_name": _sub.name if _sub else "Other",
            "lines": [], "extra": "", "value": 0,
        })
        _e["qty"] += _s.quantity
        _e["value"] += _s.quantity * _p.cost_price
    safe_catalog = _bc([e for e in _agg.values() if e["qty"] > 0], prefix="safe", value_label="Cost value")

'''

MGR_CTX_CODE = r'''    # CATALOG_ROLES_V1: grouped Safe Stock Levels with what each retail staff member holds
    from core.catalog_ui import build_catalog as _bc
    _held = {}
    for _st in StaffStock.objects.filter(
            staff__branch=branch, staff__role="RETAIL", quantity__gt=0).select_related("staff"):
        _held.setdefault(_st.product_id, []).append((_st.staff.username, _st.quantity))
    _items = []
    for _s in BranchSafeStock.objects.filter(branch=branch).select_related(
            "product", "product__subcategory", "product__subcategory__category"):
        _p = _s.product
        _sub = _p.subcategory
        _cat = _sub.category if _sub else None
        _h = sorted(_held.get(_p.id, []))
        _items.append({
            "pid": _p.id, "name": _p.model_name, "color": _p.color or "", "price": _p.selling_price,
            "qty": _s.quantity, "imei": _p.imei_serial or "",
            "cat_id": _cat.id if _cat else 0, "cat_name": _cat.name if _cat else "Uncategorised",
            "sub_id": _sub.id if _sub else 0, "sub_name": _sub.name if _sub else "Other",
            "lines": [{"label": "With " + u, "value": q} for u, q in _h],
            "extra": " ".join(u for u, q in _h), "value": None,
        })
    manager_catalog = _bc(_items, prefix="mgr")

'''

# --------------------------------------------------------------- 1. new files
new_file("core/catalog_ui.py", CATALOG_UI, "shared helper")
new_file("templates/partials/catalog_assets.html", ASSETS, "styles + search/filter script")
new_file("templates/partials/catalog_cards.html", CARDS, "grouped cards partial")

# --------------------------------------------------------------- 2. views.py (check everything BEFORE writing anything)
v = read("core/views.py")
if MARK in v:
    print("SKIP     core/views.py already applied")
else:
    # (a) all branch stock
    a = v.find("def director_all_branch_stock(request):")
    if a < 0:
        sys.exit("ERROR: director_all_branch_stock not found in core/views.py (nothing changed)")
    m = re.search(r"\n\n\n# ─", v[a:])
    if not m:
        sys.exit("ERROR: could not find the end of director_all_branch_stock (nothing changed)")
    a_end = a + m.start()
    v2 = v[:a] + ALL_STOCK_VIEW.rstrip("\n") + v[a_end:]

    # (b) director safe context
    s0 = v2.find("def director_safe_stock(request):")
    old_ctx = '    return render(request, "director/director_safe.html", {\n        "stocks": all_stocks,\n'
    i = v2.find(old_ctx, s0)
    if s0 < 0 or i < 0:
        sys.exit("ERROR: director_safe_stock() looks different than expected (nothing changed)")
    v2 = v2[:i] + SAFE_CTX_CODE + old_ctx + '        "safe_catalog": safe_catalog,\n' + v2[i + len(old_ctx):]

    # (c) manager context
    m0 = v2.find("def manager_dashboard(request):")
    old_r = '    return render(request, "manager_dashboard.html", {\n        "target_data": target_data,\n'
    j = v2.find(old_r, m0)
    if m0 < 0 or j < 0:
        sys.exit("ERROR: manager_dashboard() looks different than expected (nothing changed)")
    v2 = v2[:j] + MGR_CTX_CODE + old_r + '        "manager_catalog": manager_catalog,\n' + v2[j + len(old_r):]
    if "StaffStock" not in v.split("def manager_dashboard")[0] and "StaffStock" not in v[:3000]:
        pass  # StaffStock/DirectorSafeStock/BranchSafeStock are already imported in views.py
    backup("core/views.py", v)
    write("core/views.py", v2)
    print("APPLIED  core/views.py (all-branch stock, director safe overview, manager overview)")

# --------------------------------------------------------------- 3. templates
t = read("templates/director/all_branch_stock.html")
if MARK in t:
    print("SKIP     templates/director/all_branch_stock.html already applied")
else:
    backup("templates/director/all_branch_stock.html", t)
    write("templates/director/all_branch_stock.html", ALL_STOCK)
    print("APPLIED  templates/director/all_branch_stock.html (rebuilt)")

d = read("templates/director/director_safe.html")
if MARK in d:
    print("SKIP     templates/director/director_safe.html already applied")
else:
    o = d
    # include assets right after the content block opens
    k = o.find("{% block content %}")
    if k < 0:
        sys.exit("ERROR: no content block in director_safe.html (nothing changed)")
    k += len("{% block content %}")
    o = o[:k] + '\n{# CATALOG_ROLES_V1 #}\n{% include "partials/catalog_assets.html" %}' + o[k:]
    # catalog + collapse the old per-addition table
    anchor = '    <form method="GET" class="filter-bar">'
    p = o.find(anchor, o.find('<div id="tab-stock"'))
    if p < 0:
        sys.exit("ERROR: tab-stock filter form not found (nothing changed)")
    block = ('    {% include "partials/catalog_cards.html" with catalog=safe_catalog action_label="Release" action_fn="releaseFromSafe" %}\n'
             '    <details class="cg-details">\n'
             '      <summary>Show every addition (edit / delete)</summary>\n')
    o = o[:p] + block + o[p:]
    tail_old = '    {% endif %}\n  </div>\n</div>\n\n<div id="tab-release" class="tab-panel">'
    q = o.find(tail_old)
    if q < 0:
        sys.exit("ERROR: end of the stock tab not found (nothing changed)")
    o = o[:q] + '    {% endif %}\n    </details>\n  </div>\n</div>\n\n<div id="tab-release" class="tab-panel">' + o[q + len(tail_old):]
    # JS: release helper + fix stray brace in the #tab restore selector
    fn = ('function releaseFromSafe(pid) {\n'
          '  var btn = document.querySelector(\'[onclick*="switchTab(\\\'release\\\'"]\');\n'
          '  if (btn) switchTab(\'release\', btn);\n'
          '  var sel = document.querySelector(\'select[name="product_id"]\');\n'
          '  if (sel) { sel.value = String(pid); updateAvailable(sel); }\n'
          '  window.scrollTo({top: 0, behavior: \'smooth\'});\n'
          '}\n')
    r = o.find("function toggleReleaseTarget()")
    if r < 0:
        sys.exit("ERROR: toggleReleaseTarget not found (nothing changed)")
    o = o[:r] + fn + o[r:]
    bad = "+ hash + '\\'\"]}')"
    good = "+ hash + '\\'\"]')"
    if bad in o:
        o = o.replace(bad, good)
    backup("templates/director/director_safe.html", d)
    write("templates/director/director_safe.html", o)
    print("APPLIED  templates/director/director_safe.html (overview + release button + #tab fix)")

mg = read("templates/manager_dashboard.html")
if MARK in mg:
    print("SKIP     templates/manager_dashboard.html already applied")
else:
    title = '<p class="card-title">📦 Safe Stock Levels</p>'
    i = mg.find(title)
    if i < 0:
        sys.exit("ERROR: Safe Stock Levels card not found in manager_dashboard.html (nothing changed)")
    start = mg.rfind('<div class="card">', 0, i)
    end_marker = '<div class="card">\n        <p class="card-title">➕ Add Stock to Safe</p>'
    e = mg.find(end_marker, i)
    if start < 0 or e < 0:
        sys.exit("ERROR: could not find the card boundaries in manager_dashboard.html (nothing changed)")
    newcard = ('<div class="card">\n'
               '        {# CATALOG_ROLES_V1 #}\n'
               '        {% include "partials/catalog_assets.html" %}\n'
               '        <p class="card-title">📦 Safe Stock Levels</p>\n'
               '        {% include "partials/catalog_cards.html" with catalog=manager_catalog action_label="Release" action_fn="releaseFromManagerSafe" %}\n'
               '        <script>\n'
               '        function releaseFromManagerSafe(pid) {\n'
               '          var form = document.querySelector(\'form[action$="/release-stock/"]\');\n'
               '          if (!form) return;\n'
               '          CG.setSelect(form.querySelector(\'select[name="product"]\'), pid);\n'
               '          form.scrollIntoView({behavior: \'smooth\', block: \'center\'});\n'
               '          var qty = form.querySelector(\'input[name="quantity"]\'); if (qty) qty.focus();\n'
               '        }\n'
               '        </script>\n'
               '      </div>\n\n'
               '      ')
    backup("templates/manager_dashboard.html", mg)
    write("templates/manager_dashboard.html", mg[:start] + newcard + mg[e:])
    print("APPLIED  templates/manager_dashboard.html (Safe Stock Levels is now the grouped catalog)")

print("\nDone. Restart the app and hard-refresh (Ctrl+Shift+R).")