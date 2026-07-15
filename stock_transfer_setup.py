"""
STOCK TRANSFER VIEWS + TEMPLATE SNIPPETS
==========================================
After running fix_three.py, append these views to core/views.py
And follow the template insertion instructions below.
"""

# ── ADD TO core/views.py ──

VIEWS_TO_ADD = '''

# ─────────────────────────────────────────
# STOCK TRANSFER — Branch to Branch, Director, Staff
# ─────────────────────────────────────────

@role_required("DIRECTOR", "MANAGER")
def stock_transfer(request):
    """Record a stock transfer between any two parties."""
    from core.models import (
        StockTransfer, DirectorSafeStock, BranchSafeStock,
        StaffStock, Product, Branch
    )
    from django.utils import timezone as _tz

    branches = Branch.objects.all()
    products = Product.objects.all().order_by('model_name')
    staff_list = User.objects.filter(
        role__in=['RETAIL', 'TELECOM', 'MULTICHOICE']
    ).order_by('username')

    # For managers, limit to their branch
    if request.user.role == 'MANAGER':
        staff_list = staff_list.filter(branch=request.user.branch)

    if request.method == 'POST':
        try:
            transfer_type = request.POST.get('transfer_type')
            product_id    = request.POST.get('product')
            quantity      = int(request.POST.get('quantity', 0))
            notes         = request.POST.get('notes', '').strip()
            from_branch_id = request.POST.get('from_branch') or None
            to_branch_id   = request.POST.get('to_branch') or None
            to_staff_id    = request.POST.get('to_staff') or None

            product  = get_object_or_404(Product, id=product_id)
            from_branch = Branch.objects.get(id=from_branch_id) if from_branch_id else None
            to_branch   = Branch.objects.get(id=to_branch_id) if to_branch_id else None
            to_staff    = User.objects.get(id=to_staff_id) if to_staff_id else None

            if quantity <= 0:
                messages.error(request, 'Quantity must be greater than 0.')
                return redirect('stock_transfer')

            # Deduct from source
            if transfer_type == 'DIRECTOR_TO_BRANCH':
                src = DirectorSafeStock.objects.filter(product=product).first()
                if not src or src.quantity < quantity:
                    messages.error(request, f'Insufficient stock in Director Safe. Available: {src.quantity if src else 0}')
                    return redirect('stock_transfer')
                src.quantity -= quantity
                src.save()
                # Add to branch
                dst, _ = BranchSafeStock.objects.get_or_create(product=product, branch=to_branch)
                dst.quantity += quantity
                dst.save()

            elif transfer_type == 'BRANCH_TO_BRANCH':
                src = BranchSafeStock.objects.filter(product=product, branch=from_branch).first()
                if not src or src.quantity < quantity:
                    messages.error(request, f'Insufficient stock in {from_branch.name}. Available: {src.quantity if src else 0}')
                    return redirect('stock_transfer')
                src.quantity -= quantity
                src.save()
                dst, _ = BranchSafeStock.objects.get_or_create(product=product, branch=to_branch)
                dst.quantity += quantity
                dst.save()

            elif transfer_type == 'BRANCH_TO_STAFF':
                src = BranchSafeStock.objects.filter(product=product, branch=from_branch).first()
                if not src or src.quantity < quantity:
                    messages.error(request, f'Insufficient stock in {from_branch.name}. Available: {src.quantity if src else 0}')
                    return redirect('stock_transfer')
                src.quantity -= quantity
                src.save()
                dst, _ = StaffStock.objects.get_or_create(product=product, staff=to_staff)
                dst.quantity += quantity
                dst.save()

            elif transfer_type == 'BRANCH_TO_DIRECTOR':
                src = BranchSafeStock.objects.filter(product=product, branch=from_branch).first()
                if not src or src.quantity < quantity:
                    messages.error(request, f'Insufficient stock in {from_branch.name}. Available: {src.quantity if src else 0}')
                    return redirect('stock_transfer')
                src.quantity -= quantity
                src.save()
                dst, _ = DirectorSafeStock.objects.get_or_create(product=product)
                dst.quantity += quantity
                dst.save()

            elif transfer_type == 'STAFF_TO_BRANCH':
                src = StaffStock.objects.filter(product=product, staff=to_staff).first()
                if not src or src.quantity < quantity:
                    messages.error(request, f'Insufficient stock with {to_staff.username}. Available: {src.quantity if src else 0}')
                    return redirect('stock_transfer')
                src.quantity -= quantity
                src.save()
                dst, _ = BranchSafeStock.objects.get_or_create(product=product, branch=to_branch)
                dst.quantity += quantity
                dst.save()

            # Record transfer
            StockTransfer.objects.create(
                transfer_type=transfer_type,
                product=product,
                quantity=quantity,
                status='COMPLETED',
                notes=notes,
                from_branch=from_branch,
                to_branch=to_branch,
                to_staff=to_staff,
                initiated_by=request.user,
                approved_by=request.user,
                completed_at=_tz.now(),
            )

            # Audit log
            try:
                AuditLog.objects.create(
                    user=request.user,
                    action='TRANSFER',
                    model_name='StockTransfer',
                    description=f"Transferred {quantity}x {product.model_name}: {from_branch.name if from_branch else 'Director'} → {to_branch.name if to_branch else (to_staff.username if to_staff else 'Director')}"
                )
            except Exception:
                pass

            messages.success(request, f"Transfer complete: {quantity}x {product.model_name} moved successfully.")
        except Exception as e:
            messages.error(request, f"Transfer failed: {e}")
        return redirect('stock_transfer')

    # Recent transfers
    transfers = StockTransfer.objects.select_related(
        'product', 'from_branch', 'to_branch', 'to_staff', 'initiated_by'
    ).order_by('-created_at')[:50]

    if request.user.role == 'MANAGER':
        transfers = transfers.filter(
            Q(from_branch=request.user.branch) | Q(to_branch=request.user.branch)
        )

    return render(request, 'stock_transfer.html', {
        'branches': branches,
        'products': products,
        'staff_list': staff_list,
        'transfers': transfers,
        'today': timezone.now().date(),
    })


@role_required("DIRECTOR")
def stock_transfer_history(request):
    """Director - full stock transfer history with filters."""
    from core.models import StockTransfer
    date_from   = request.GET.get('date_from', '')
    date_to     = request.GET.get('date_to', '')
    branch_flt  = request.GET.get('branch', '')
    type_flt    = request.GET.get('type', '')

    transfers = StockTransfer.objects.select_related(
        'product', 'from_branch', 'to_branch', 'to_staff', 'initiated_by'
    ).order_by('-created_at')

    if date_from:
        transfers = transfers.filter(created_at__date__gte=date_from)
    if date_to:
        transfers = transfers.filter(created_at__date__lte=date_to)
    if branch_flt:
        transfers = transfers.filter(
            Q(from_branch_id=branch_flt) | Q(to_branch_id=branch_flt)
        )
    if type_flt:
        transfers = transfers.filter(transfer_type=type_flt)

    from core.models import Branch
    return render(request, 'director/stock_transfer_history.html', {
        'transfers': transfers[:200],
        'branches': Branch.objects.all(),
        'date_from': date_from,
        'date_to': date_to,
        'branch_flt': branch_flt,
        'type_flt': type_flt,
        'transfer_types': StockTransfer.TRANSFER_TYPE_CHOICES,
    })
'''

# ── TEMPLATE: stock_transfer.html ──
STOCK_TRANSFER_TEMPLATE = '''{% extends "base.html" %}
{% block content %}
<style>
.page-title{font-size:1.2rem;font-weight:700;color:#004F9F;margin:0}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1.1rem 1.3rem;margin-bottom:1rem}
.card-title{font-size:.92rem;font-weight:700;margin:0 0 .85rem}
.form-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:.75rem}
.form-group{margin-bottom:.75rem}
.form-group label{font-size:.75rem;font-weight:600;color:#374151;display:block;margin-bottom:.25rem}
.form-group input,.form-group select,.form-group textarea{width:100%;padding:.5rem .75rem;border:1.5px solid #e2e8f0;border-radius:7px;font-size:.85rem;box-sizing:border-box}
.btn-sm{padding:.45rem .9rem;font-size:.82rem;border-radius:6px;border:none;cursor:pointer;font-weight:600;text-decoration:none;display:inline-block}
.btn-primary{background:#004F9F;color:#fff}.btn-outline{background:transparent;border:1px solid #d1d5db;color:#374151}
.table{width:100%;border-collapse:collapse;font-size:.82rem}
.table th{background:#004F9F;color:#fff;padding:.55rem .8rem;text-align:left;font-weight:600}
.table td{padding:.55rem .8rem;border-bottom:1px solid #f1f5f9;vertical-align:middle}
.badge{display:inline-block;padding:.18rem .55rem;border-radius:999px;font-size:.68rem;font-weight:700}
.b-blue{background:#dbeafe;color:#1e40af}
.arrow{color:#004F9F;font-weight:700}
</style>

<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.75rem;margin-bottom:1.25rem">
  <h1 class="page-title">🔄 Stock Transfer</h1>
  {% if user.role == 'DIRECTOR' %}
  <a href="{% url 'stock_transfer_history' %}" class="btn-sm btn-outline">📋 Full History</a>
  {% endif %}
</div>

{% if messages %}{% for m in messages %}
<div style="background:{% if m.tags == 'error' %}#fee2e2{% else %}#dcfce7{% endif %};border-radius:7px;padding:.65rem 1rem;font-size:.83rem;margin-bottom:1rem;">{{ m }}</div>
{% endfor %}{% endif %}

<div class="card">
  <p class="card-title">New Transfer</p>
  <form method="POST" id="transfer-form">
    {% csrf_token %}
    <div class="form-group">
      <label>Transfer Type *</label>
      <select name="transfer_type" id="transfer_type" onchange="updateFields()" required>
        <option value="">— Select Type —</option>
        {% if user.role == 'DIRECTOR' %}
        <option value="DIRECTOR_TO_BRANCH">Director Safe → Branch Safe</option>
        <option value="BRANCH_TO_DIRECTOR">Branch Safe → Director Safe (Return)</option>
        {% endif %}
        <option value="BRANCH_TO_BRANCH">Branch → Branch</option>
        <option value="BRANCH_TO_STAFF">Branch Safe → Staff Stock</option>
        <option value="STAFF_TO_BRANCH">Staff Stock → Branch Safe (Return)</option>
      </select>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Product *</label>
        <select name="product" required>
          <option value="">— Select Product —</option>
          {% for p in products %}<option value="{{ p.id }}">{{ p.model_name }}</option>{% endfor %}
        </select>
      </div>
      <div class="form-group">
        <label>Quantity *</label>
        <input type="number" name="quantity" min="1" required placeholder="How many units">
      </div>
    </div>

    <div class="form-row">
      <div class="form-group" id="from_branch_wrap" style="display:none">
        <label>From Branch</label>
        <select name="from_branch" id="from_branch">
          <option value="">— Select Source Branch —</option>
          {% for b in branches %}<option value="{{ b.id }}">{{ b.name }}</option>{% endfor %}
        </select>
      </div>
      <div class="form-group" id="to_branch_wrap" style="display:none">
        <label>To Branch</label>
        <select name="to_branch" id="to_branch">
          <option value="">— Select Destination Branch —</option>
          {% for b in branches %}<option value="{{ b.id }}">{{ b.name }}</option>{% endfor %}
        </select>
      </div>
      <div class="form-group" id="to_staff_wrap" style="display:none">
        <label>Staff Member</label>
        <select name="to_staff" id="to_staff">
          <option value="">— Select Staff —</option>
          {% for s in staff_list %}<option value="{{ s.id }}">{{ s.username }} ({{ s.branch.name|default:"No branch" }})</option>{% endfor %}
        </select>
      </div>
    </div>

    <div class="form-group">
      <label>Notes (optional)</label>
      <textarea name="notes" rows="2" placeholder="Reason for transfer, any remarks..."></textarea>
    </div>
    <button type="submit" class="btn-sm btn-primary" style="width:100%">Complete Transfer</button>
  </form>
</div>

<div class="card">
  <p class="card-title">Recent Transfers</p>
  {% if transfers %}
  <div style="overflow-x:auto">
    <table class="table">
      <thead><tr><th>Date</th><th>Product</th><th>Qty</th><th>From</th><th></th><th>To</th><th>By</th><th>Type</th></tr></thead>
      <tbody>
        {% for t in transfers %}
        <tr>
          <td style="font-size:.75rem">{{ t.created_at|date:"d M Y H:i" }}</td>
          <td><strong>{{ t.product.model_name }}</strong></td>
          <td><strong>{{ t.quantity }}</strong></td>
          <td>{{ t.source_label }}</td>
          <td class="arrow">→</td>
          <td>{{ t.destination_label }}</td>
          <td style="font-size:.75rem;color:#64748b">{{ t.initiated_by.username }}</td>
          <td><span class="badge b-blue" style="font-size:.62rem">{{ t.get_transfer_type_display }}</span></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <p style="color:#94a3b8;text-align:center;padding:2rem">No transfers recorded yet.</p>
  {% endif %}
</div>

<script>
function updateFields() {
  const type = document.getElementById('transfer_type').value;
  const fromBranch = document.getElementById('from_branch_wrap');
  const toBranch = document.getElementById('to_branch_wrap');
  const toStaff = document.getElementById('to_staff_wrap');

  fromBranch.style.display = 'none';
  toBranch.style.display = 'none';
  toStaff.style.display = 'none';

  if (type === 'DIRECTOR_TO_BRANCH') {
    toBranch.style.display = '';
  } else if (type === 'BRANCH_TO_BRANCH') {
    fromBranch.style.display = '';
    toBranch.style.display = '';
  } else if (type === 'BRANCH_TO_STAFF') {
    fromBranch.style.display = '';
    toStaff.style.display = '';
  } else if (type === 'BRANCH_TO_DIRECTOR') {
    fromBranch.style.display = '';
  } else if (type === 'STAFF_TO_BRANCH') {
    toStaff.style.display = '';
    toBranch.style.display = '';
  }
}
</script>
{% endblock %}'''

# Write templates
import os
W = '/home/runner/workspace'

# Write views addition
with open(f'{W}/stock_transfer_views.py', 'w') as f:
    f.write(VIEWS_TO_ADD)

# Write template
os.makedirs(f'{W}/templates', exist_ok=True)
with open(f'{W}/stock_transfer_template.html', 'w') as f:
    f.write(STOCK_TRANSFER_TEMPLATE)

print("Files written:")
print("  stock_transfer_views.py - append to core/views.py")
print("  stock_transfer_template.html - copy to templates/stock_transfer.html")
