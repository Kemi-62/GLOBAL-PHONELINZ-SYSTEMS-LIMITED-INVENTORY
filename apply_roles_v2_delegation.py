#!/usr/bin/env python3
"""
apply_roles_v2_delegation.py   (marker: ROLES_V2)

Run AFTER apply_roles_v1.py. Lets the Sub Director do the Director's day-to-day stock
work while the Director just watches:

  * Release from the Director Safe to branches / staff (starts straight away,
    except a direct sale, which stays with the Director)
  * Stock transfer page and full transfer history
  * Add stock to the Director Safe (single, bulk CSV, new product): goes to the
    Director for confirmation first. Whoever enters stock never approves it.
  * Create products and manage the catalog (slides, products, categories)
  * Suppliers and purchase orders. Receiving a PO (by a Sub Director OR a Manager)
    no longer credits the branch safe directly; it goes to the Director for approval.
  * A Sub Director's own requests can only be approved by the Director
  * Sub Director Activity page now also counts what they REQUESTED

Stays with the Director only: backups, payroll, price floors, deleting or editing
safe stock, direct sales from the safe, user admin, logs.

Run from the project root (the folder with manage.py):

    python apply_roles_v2_delegation.py

No migration needed. Safe to run twice. All edits are checked BEFORE anything is
written; if one cannot be placed the script stops and changes nothing.
"""
import os, re, sys, shutil

MARK = "ROLES_V2"
ROOT = os.getcwd()

PATCHES = [('core/stock_approvals.py',
  'def _check_move_authority(requester, source_tier, from_branch, from_staff):\n    if is_director(requester):\n        return',
  'def _check_move_authority(requester, source_tier, from_branch, from_staff):\n'
  '    if is_approver(requester):  # ROLES_V2: the Sub Director may move stock for the Director\n'
  '        return',
  'engine: Sub Director may start stock moves'),
 ('core/stock_approvals.py',
  '        return bool(is_director(requester) and to_branch is not None and not _branch_has_manager(to_branch))',
  '        return bool(is_approver(requester) and to_branch is not None and not _branch_has_manager(to_branch))',
  'engine: Sub Director release to a manager-less branch completes at once'),
 ('core/stock_approvals.py',
  '    stage = req.approval_stage\n    if stage == "DIRECTOR":\n        return director',
  "    # ROLES_V2: a Sub Director's own requests can only be approved by the Director (or the branch manager)\n"
  '    if getattr(req.requested_by, "role", "") == "SUB_DIRECTOR" and getattr(user, "role", "") == "SUB_DIRECTOR":\n'
  '        director = False\n'
  '    stage = req.approval_stage\n'
  '    if stage == "DIRECTOR":\n'
  '        return director',
  "engine: Sub Director cannot approve another Sub Director's request"),
 ('core/stock_approvals.py',
  '        return qs.filter(director_stage | unmanaged)',
  '        result = qs.filter(director_stage | unmanaged)\n'
  '        if not is_director(user):  # ROLES_V2\n'
  '            result = result.exclude(requested_by__role="SUB_DIRECTOR")\n'
  '        return result',
  'engine: inbox hides Sub Director requests from Sub Directors'),
 ('core/stock_approvals.py',
  '        if SUB_DIRECTOR_ACTS_AT_DIRECTOR_STAGE:\n            _notify_role("SUB_DIRECTOR", headline, text)',
  '        if SUB_DIRECTOR_ACTS_AT_DIRECTOR_STAGE and getattr(req.requested_by, "role", "") != "SUB_DIRECTOR":\n'
  '            _notify_role("SUB_DIRECTOR", headline, text)',
  'engine: notices for Sub Director requests go to the Director only'),
 ('core/stock_approvals.py',
  '@transaction.atomic\ndef record_reduction(requester, product, qty, reason):',
  '@transaction.atomic\n'
  'def submit_receipt(requester, product, qty, dest_tier, to_branch=None, note="", batch_ref=""):\n'
  '    """ROLES_V2. Stock coming in from outside (a Director Safe addition, a purchase\n'
  '    order). Nothing changes until the Director level approves it."""\n'
  '    qty = _positive(qty)\n'
  '    if dest_tier not in ("DIRECTOR", "BRANCH"):\n'
  '        raise StockError("Stock can only be received into the Director Safe or a branch safe.")\n'
  '    if dest_tier == "BRANCH" and to_branch is None:\n'
  '        raise StockError("Please choose the branch.")\n'
  '    req = m.StockApprovalRequest.objects.create(\n'
  '        kind="ENTRY", source_type="MANUAL_OTHER", product=product, quantity=qty,\n'
  '        source_tier="EXTERNAL", dest_tier=dest_tier,\n'
  '        to_branch=to_branch if dest_tier == "BRANCH" else None,\n'
  '        requested_by=requester, notes=(note or "").strip(), batch_ref=batch_ref or "",\n'
  '        approval_stage="DIRECTOR", status="PENDING",\n'
  '    )\n'
  '    _event(req, requester, "SUBMITTED", "Stock received: %s into %s (%s)" % (qty, req.dest_label, (note or "no note").strip()))\n'
  '    _audit(requester, "CREATE", req, "Stock received %s" % _summary(req))\n'
  '    _notify_stage(req)\n'
  '    return req\n'
  '\n'
  '\n'
  '@transaction.atomic\n'
  'def record_reduction(requester, product, qty, reason):',
  'engine: submit_receipt for stock coming in from outside'),
 ('core/stock_approval_views.py',
  '        staff_id = request.POST.get("staff_id")\n        if not product_id:',
  '        staff_id = request.POST.get("staff_id")\n'
  '        if release_type == "sale" and request.user.role == "SUB_DIRECTOR":  # ROLES_V2\n'
  '            messages.error(request, "Direct sales from the Director Safe can only be recorded by the Director.")\n'
  '            return redirect("director_safe_stock")\n'
  '        if not product_id:',
  'release: direct sale stays with the Director'),
 ('core/views.py',
  '@role_required("DIRECTOR")\ndef director_release_stock(request):',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\ndef director_release_stock(request):',
  'release stock: Sub Director'),
 ('core/views.py',
  '@role_required("DIRECTOR", "MANAGER")\ndef stock_transfer(request):',
  '@role_required("DIRECTOR", "MANAGER", "SUB_DIRECTOR")\ndef stock_transfer(request):',
  'stock transfer: Sub Director'),
 ('core/views.py',
  '@role_required("DIRECTOR")\ndef director_safe_stock(request):',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\ndef director_safe_stock(request):',
  'director safe page: Sub Director'),
 ('core/views.py',
  '@role_required("DIRECTOR")\n'
  'def add_director_stock(request):\n'
  '    if request.method == "POST":\n'
  '        try:\n'
  '            product = get_object_or_404(Product, id=request.POST.get("product_id"))\n'
  '            qty = int(request.POST.get("quantity", 0))\n'
  '            notes = request.POST.get("notes", "")\n',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\n'
  'def add_director_stock(request):\n'
  '    if request.method == "POST":\n'
  '        try:\n'
  '            product = get_object_or_404(Product, id=request.POST.get("product_id"))\n'
  '            qty = int(request.POST.get("quantity", 0))\n'
  '            notes = request.POST.get("notes", "")\n'
  '            if request.user.role == "SUB_DIRECTOR":  # ROLES_V2: the Director confirms before it counts\n'
  '                from core import stock_approvals as _sa\n'
  '                _sa.submit_receipt(request.user, product, qty, "DIRECTOR", note=notes)\n'
  '                messages.success(request, f"Sent {qty}x {product.model_name} to the Director for confirmation. It joins the Director '
  'Safe once confirmed.")\n'
  '                return redirect("director_safe_stock")\n',
  'add to Director Safe: Sub Director goes through confirmation'),
 ('core/views.py',
  '@role_required("DIRECTOR")\ndef create_director_product(request):',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\ndef create_director_product(request):',
  'create product: Sub Director'),
 ('core/views.py',
  '            qty = int(request.POST.get("quantity", 0))\n'
  '            DirectorSafeStock.objects.create(product=product, quantity=qty, notes="Created by Director")\n'
  '            messages.success(request, f"Product created. {qty} units added to safe.")',
  '            qty = int(request.POST.get("quantity", 0))\n'
  '            if request.user.role == "SUB_DIRECTOR":  # ROLES_V2: the product is created, its stock waits for the Director\n'
  '                from core import stock_approvals as _sa\n'
  '                if qty > 0:\n'
  '                    _sa.submit_receipt(request.user, product, qty, "DIRECTOR", note="New product created by Sub Director")\n'
  '                messages.success(request, f"Product created. {qty} units sent to the Director for confirmation.")\n'
  '            else:\n'
  '                DirectorSafeStock.objects.create(product=product, quantity=qty, notes="Created by Director")\n'
  '                messages.success(request, f"Product created. {qty} units added to safe.")',
  'create product: stock waits for the Director'),
 ('core/views.py',
  '@role_required("DIRECTOR")\n'
  'def upload_director_csv(request):\n'
  '    if request.method == "POST":\n'
  '        csv_file = request.FILES.get("csv_file")',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\n'
  'def upload_director_csv(request):\n'
  '    is_sub = request.user.role == "SUB_DIRECTOR"  # ROLES_V2\n'
  '    if request.method == "POST":\n'
  '        csv_file = request.FILES.get("csv_file")',
  'director CSV: Sub Director'),
 ('core/views.py',
  '                    if not created and (cost_price or selling_price):\n'
  '                        if cost_price:\n'
  '                            product.cost_price = cost_price\n'
  '                        if selling_price:\n'
  '                            product.selling_price = selling_price\n'
  '                        product.save(update_fields=["cost_price", "selling_price"])\n'
  '\n'
  '                    # Update or create director safe stock - just add to quantity\n'
  '                    with transaction.atomic():',
  '                    if not created and not is_sub and (cost_price or selling_price):\n'
  '                        if cost_price:\n'
  '                            product.cost_price = cost_price\n'
  '                        if selling_price:\n'
  '                            product.selling_price = selling_price\n'
  '                        product.save(update_fields=["cost_price", "selling_price"])\n'
  '\n'
  '                    if is_sub:  # ROLES_V2: goes to the Director for confirmation\n'
  '                        from core import stock_approvals as _sa\n'
  '                        if quantity > 0:\n'
  '                            _sa.submit_receipt(request.user, product, quantity, "DIRECTOR", note="Bulk upload", '
  'batch_ref=_sa.batch_ref_for(request))\n'
  '                        count += 1\n'
  '                        continue\n'
  '                    # Update or create director safe stock - just add to quantity\n'
  '                    with transaction.atomic():',
  'director CSV: Sub Director cannot change prices; lines wait for the Director'),
 ('core/views.py',
  '            msg = f"Imported {count} product(s) to director safe."',
  '            msg = (f"Sent {count} line(s) to the Director for confirmation." if is_sub\n'
  '                   else f"Imported {count} product(s) to director safe.")',
  'director CSV: message'),
 ('core/views.py',
  "def supplier_list(request):\n    if request.user.role not in ['DIRECTOR', 'MANAGER']:",
  "def supplier_list(request):\n    if request.user.role not in ['DIRECTOR', 'MANAGER', 'SUB_DIRECTOR']:",
  'suppliers: Sub Director'),
 ('core/views.py',
  "def supplier_create(request):\n    if request.user.role not in ['DIRECTOR', 'MANAGER']:",
  "def supplier_create(request):\n    if request.user.role not in ['DIRECTOR', 'MANAGER', 'SUB_DIRECTOR']:",
  'new supplier: Sub Director'),
 ('core/views.py',
  "def purchase_order_list(request):\n    if request.user.role not in ['DIRECTOR', 'MANAGER']:",
  "def purchase_order_list(request):\n    if request.user.role not in ['DIRECTOR', 'MANAGER', 'SUB_DIRECTOR']:",
  'purchase orders: Sub Director'),
 ('core/views.py',
  "def purchase_order_receive(request, po_id):\n    if request.user.role not in ['DIRECTOR', 'MANAGER']:",
  "def purchase_order_receive(request, po_id):\n    if request.user.role not in ['DIRECTOR', 'MANAGER', 'SUB_DIRECTOR']:",
  'receive purchase order: Sub Director'),
 ('core/views.py',
  '        messages.warning(request, "This order has already been received.")\n        return redirect("purchase_order_list")\n',
  '        messages.warning(request, "This order has already been received.")\n'
  '        return redirect("purchase_order_list")\n'
  '\n'
  "    if request.user.role in ('MANAGER', 'SUB_DIRECTOR') and not request.user.is_superuser:  # ROLES_V2\n"
  "        # Received goods now wait for the Director's approval before they count as branch stock\n"
  '        from core import stock_approvals as _sa\n'
  '        try:\n'
  '            with transaction.atomic():\n'
  '                ref = _sa.batch_ref_for(request)\n'
  "                for item in po.items.select_related('product'):\n"
  '                    _sa.submit_receipt(request.user, item.product, item.quantity, "BRANCH", to_branch=po.branch,\n'
  '                                       note=f"Purchase order #{po.id} from {po.supplier.name}", batch_ref=ref)\n'
  "                po.status = 'RECEIVED'\n"
  '                po.date_received = date.today()\n'
  '                po.save()\n'
  '        except _sa.StockError as exc:\n'
  '            messages.error(request, str(exc))\n'
  '            return redirect("purchase_order_list")\n'
  '        messages.success(request, f"PO#{po.id} received. The stock reaches the {po.branch.name} safe when the Director approves it.")\n'
  '        return redirect("purchase_order_list")\n',
  'receive purchase order: manager and Sub Director need approval'),
 ('core/views.py',
  "def purchase_order_create(request):\n    if request.user.role not in ['DIRECTOR', 'MANAGER']:",
  "def purchase_order_create(request):\n    if request.user.role not in ['DIRECTOR', 'MANAGER', 'SUB_DIRECTOR']:",
  'new purchase order: Sub Director'),
 ('core/views.py',
  '        supplier_id = request.POST.get("supplier")\n'
  '        notes = request.POST.get("notes", "")\n'
  '        branch = request.user.branch\n',
  '        supplier_id = request.POST.get("supplier")\n'
  '        notes = request.POST.get("notes", "")\n'
  '        branch = request.user.branch\n'
  '        if request.user.role != "MANAGER" and request.POST.get("branch_id"):  # ROLES_V2: Director level picks the branch\n'
  '            branch = Branch.objects.filter(id=request.POST.get("branch_id")).first() or branch\n'
  '        if branch is None:\n'
  '            messages.error(request, "Please choose the branch this order is for.")\n'
  '            return redirect("purchase_order_create")\n',
  'new purchase order: choose the branch'),
 ('templates/suppliers/po_form.html',
  '      </div>\n    </div>\n    <div class="form-group">\n      <label>Notes</label>',
  '      </div>\n'
  '      {% if user.role != "MANAGER" %}{# ROLES_V2 #}\n'
  '      <div class="form-group">\n'
  '        <label>Branch *</label>\n'
  '        <select name="branch_id" required>\n'
  '          <option value="">— Select Branch —</option>\n'
  '          {% for b in branches %}\n'
  '          <option value="{{ b.id }}">{{ b.name }}</option>\n'
  '          {% endfor %}\n'
  '        </select>\n'
  '      </div>\n'
  '      {% endif %}\n'
  '    </div>\n'
  '    <div class="form-group">\n'
  '      <label>Notes</label>',
  'new purchase order form: branch picker'),
 ('core/views.py',
  '@role_required("DIRECTOR")\ndef catalog_management(',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\ndef catalog_management(',
  'catalog: catalog_management'),
 ('core/views.py',
  '@role_required("DIRECTOR")\ndef catalog_add_slide(',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\ndef catalog_add_slide(',
  'catalog: catalog_add_slide'),
 ('core/views.py',
  '@role_required("DIRECTOR")\ndef catalog_edit_slide(',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\ndef catalog_edit_slide(',
  'catalog: catalog_edit_slide'),
 ('core/views.py',
  '@role_required("DIRECTOR")\ndef catalog_delete_slide(',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\ndef catalog_delete_slide(',
  'catalog: catalog_delete_slide'),
 ('core/views.py',
  '@role_required("DIRECTOR")\ndef catalog_add_product(',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\ndef catalog_add_product(',
  'catalog: catalog_add_product'),
 ('core/views.py',
  '@role_required("DIRECTOR")\ndef catalog_edit_product(',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\ndef catalog_edit_product(',
  'catalog: catalog_edit_product'),
 ('core/views.py',
  '@role_required("DIRECTOR")\ndef catalog_delete_product(',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\ndef catalog_delete_product(',
  'catalog: catalog_delete_product'),
 ('core/views.py',
  '@role_required("DIRECTOR")\ndef catalog_add_category(',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\ndef catalog_add_category(',
  'catalog: catalog_add_category'),
 ('core/roles_views.py',
  '        s = summary.setdefault(who, {"approved": 0, "rejected": 0, "other": 0})',
  '        s = summary.setdefault(who, {"approved": 0, "rejected": 0, "requested": 0, "other": 0})',
  'activity: requested count'),
 ('core/roles_views.py',
  '        elif e.action == "REJECTED":\n            s["rejected"] += 1',
  '        elif e.action == "REJECTED":\n'
  '            s["rejected"] += 1\n'
  '        elif e.action == "SUBMITTED":\n'
  '            s["requested"] += 1',
  'activity: count requests'),
 ('templates/director/sub_director_activity.html',
  '<thead><tr><th>Sub Director</th><th>Approved</th><th>Rejected</th><th>Other</th></tr></thead>',
  '<thead><tr><th>Sub Director</th><th>Approved</th><th>Rejected</th><th>Requested</th><th>Other</th></tr></thead>',
  'activity: header'),
 ('templates/director/sub_director_activity.html',
  '<td>{{ s.rejected }}</td><td>{{ s.other }}</td></tr>',
  '<td>{{ s.rejected }}</td><td>{{ s.requested }}</td><td>{{ s.other }}</td></tr>',
  'activity: cells'),
 ('templates/director/sub_director_activity.html',
  '<tr><td colspan="4" style="text-align:center;color:#9ca3af;">No activity in this period.</td></tr>',
  '<tr><td colspan="5" style="text-align:center;color:#9ca3af;">No activity in this period.</td></tr>',
  'activity: empty row'),
 ('templates/director/sub_director_activity.html',
  '<p class="sd-s">Every stock request your Sub Director approved or rejected. Open Stock Audit for the full trail of any request.</p>',
  '<p class="sd-s">Everything your Sub Director requested, approved or rejected: releases, stock added, purchase orders. Items they add to '
  'the Director Safe or receive on a purchase order wait for your confirmation in Pending Approvals. Open Stock Audit for the full trail '
  'of any request.</p>',
  'activity: wording'),
 ('templates/director/sub_director_activity.html',
  '<span class="sd-pill sd-ot">{{ e.action|title }}</span>',
  '<span class="sd-pill sd-ot">{% if e.action == "SUBMITTED" %}Requested{% else %}{{ e.action|title }}{% endif %}</span>',
  'activity: label'),
 ('templates/director/director_safe.html',
  '    <details class="cg-details">\n      <summary>Show every addition (edit / delete)</summary>',
  '    {% if user.role != "SUB_DIRECTOR" %}{# ROLES_V2: only the Director edits or deletes #}\n'
  '    <details class="cg-details">\n'
  '      <summary>Show every addition (edit / delete)</summary>',
  'safe page: edit/delete only for the Director (open)'),
 ('templates/director/director_safe.html',
  '    </details>\n',
  '    </details>\n    {% endif %}\n',
  'safe page: edit/delete only for the Director (close)'),
 ('templates/director/director_safe.html',
  '          <option value="sale">Direct Sale (remove from safe)</option>',
  '          {% if user.role != "SUB_DIRECTOR" %}<option value="sale">Direct Sale (remove from safe)</option>{% endif %}',
  'safe page: direct sale only for the Director'),
 ('templates/director/director_safe.html',
  '<div class="tab-bar">\n  <button class="tab-btn active" onclick="switchTab(\'stock\',this)">📦 Current Stock</button>',
  '{% if user.role == "SUB_DIRECTOR" %}{# ROLES_V2 #}\n'
  '<div style="background:#fef3c7;color:#92400e;border-radius:8px;padding:.7rem 1rem;font-size:.84rem;margin-bottom:1rem;">\n'
  '  Releases you make start straight away. Stock you <b>add</b>, bulk upload or create is sent to the Director for confirmation and only '
  'counts once he confirms.\n'
  '</div>\n'
  '{% endif %}\n'
  '<div class="tab-bar">\n'
  '  <button class="tab-btn active" onclick="switchTab(\'stock\',this)">📦 Current Stock</button>',
  'safe page: Sub Director note'),
 ('templates/stock_transfer.html',
  '  {% if user.role == \'DIRECTOR\' %}\n  <a href="{% url \'stock_transfer_history\' %}"',
  '  {% if user.role == \'DIRECTOR\' or user.role == \'SUB_DIRECTOR\' %}\n  <a href="{% url \'stock_transfer_history\' %}"',
  'transfer page: history link'),
 ('templates/stock_transfer.html',
  '        {% if user.role == \'DIRECTOR\' %}\n        <option value="DIRECTOR_TO_BRANCH">',
  '        {% if user.role == \'DIRECTOR\' or user.role == \'SUB_DIRECTOR\' %}\n        <option value="DIRECTOR_TO_BRANCH">',
  'transfer page: Director-level options'),
 ('templates/base.html',
  '    {% elif user.role == "SUB_DIRECTOR" %}{# ROLES_V1 #}\n'
  '    <div class="sidebar-section">\n'
  '        <div class="sidebar-section-label">Oversight</div>',
  '    {% elif user.role == "SUB_DIRECTOR" %}{# ROLES_V1 #}\n'
  '    <div class="sidebar-section">\n'
  '        <div class="sidebar-section-label">Director\'s Work</div>\n'
  '        <a href="{% url \'director_safe_stock\' %}" class="sidebar-link">\n'
  '            <span class="icon">🏦</span> Director Safe\n'
  '        </a>\n'
  '        <a href="{% url \'stock_transfer\' %}" class="sidebar-link">\n'
  '            <span class="icon">🔄</span> Stock Transfer\n'
  '        </a>\n'
  '        <a href="{% url \'supplier_list\' %}" class="sidebar-link">\n'
  '            <span class="icon">🏭</span> Suppliers\n'
  '        </a>\n'
  '        <a href="{% url \'purchase_order_list\' %}" class="sidebar-link">\n'
  '            <span class="icon">📦</span> Purchase Orders\n'
  '        </a>\n'
  '        <a href="{% url \'catalog_management\' %}" class="sidebar-link">\n'
  '            <span class="icon">🛍️</span> Catalog Management\n'
  '        </a>\n'
  '    </div>\n'
  '    <div class="sidebar-divider"></div>\n'
  '    <div class="sidebar-section">\n'
  '        <div class="sidebar-section-label">Oversight</div>',
  'sidebar: Sub Director menu')]

def p(rel): return os.path.join(ROOT, *rel.split("/"))
def read(rel):
    with open(p(rel), encoding="utf-8") as f: return f.read()

if not os.path.exists(p("manage.py")) or not os.path.isdir(p("core")):
    print("ABORT: run this from the folder that contains manage.py"); sys.exit(1)
if not os.path.exists(p("core/roles.py")) or "ROLES_V1" not in read("core/stock_approvals.py"):
    print("ABORT: apply_roles_v1.py has not been applied yet. Run that first."); sys.exit(1)

texts, errors, plan = {}, [], []
for rel, old, new, label in PATCHES:
    if not os.path.exists(p(rel)):
        errors.append("missing file: " + rel); continue
    t = texts.get(rel)
    if t is None: t = read(rel)
    if new in t:
        plan.append(("SKIP", label)); texts[rel] = t; continue
    n = t.count(old)
    if n != 1:
        errors.append("%s: expected exactly 1 match for [%s], found %d" % (rel, label, n)); texts[rel] = t; continue
    texts[rel] = t.replace(old, new, 1)
    plan.append(("OK", label))
if errors:
    print("ABORT: nothing was changed.\n")
    for e in errors: print("  -", e)
    sys.exit(1)

def backup(rel):
    b = p(rel) + ".pre_roles2.bak"
    if not os.path.exists(b): shutil.copy2(p(rel), b)
changed = [r for r, t in texts.items() if t != read(r)]
for rel in changed:
    backup(rel)
    with open(p(rel), "w", encoding="utf-8", newline="") as f: f.write(texts[rel])

for status, label in plan:
    print(("OK   " if status == "OK" else "SKIP ") + label)
print()
print("Done. No migration needed. Commit, push and redeploy." if changed else "Nothing to do: already applied.")