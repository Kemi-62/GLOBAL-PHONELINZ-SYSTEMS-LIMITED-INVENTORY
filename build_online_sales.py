"""
ONLINE SALES LOG — Full Feature Build
=======================================
Run: python /home/runner/workspace/build_online_sales.py

Adds:
1. OnlineSaleLog model
2. Migration
3. Views: log_online_sale, my_online_sales, online_sales_overview (director)
4. URLs
5. Templates: online_sale_form.html, online_sales_mine.html, online_sales_overview.html
6. Sidebar links for all roles
"""
import os, ast, subprocess

W = '/home/runner/workspace'

print("=" * 55)
print("BUILDING ONLINE SALES LOG")
print("=" * 55)

# ── STEP 1: Model ──
print("\n--- Step 1: OnlineSaleLog model ---")
models_code = open(f'{W}/core/models.py').read()

if 'class OnlineSaleLog' not in models_code:
    model = '''

class OnlineSaleLog(models.Model):
    """
    Staff online/social media sales log.
    Any staff member can log a sale made via social media.
    Director sees all logs with leaderboard.
    """
    PLATFORM_CHOICES = [
        ('whatsapp',   'WhatsApp'),
        ('facebook',   'Facebook'),
        ('instagram',  'Instagram'),
        ('tiktok',     'TikTok'),
        ('twitter',    'Twitter/X'),
        ('referral',   'Referral'),
        ('other',      'Other'),
    ]

    staff            = models.ForeignKey('User', on_delete=models.CASCADE, related_name='online_sales')
    branch           = models.ForeignKey('Branch', on_delete=models.CASCADE, related_name='online_sales')
    product_name     = models.CharField(max_length=200, help_text='Name of product/service sold')
    customer_name    = models.CharField(max_length=150)
    customer_phone   = models.CharField(max_length=20)
    platform         = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default='whatsapp')
    amount           = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sale_date        = models.DateField()
    evidence_image   = models.ImageField(
        upload_to='online_sales/', null=True, blank=True,
        help_text='Screenshot or photo evidence of sale'
    )
    notes            = models.TextField(blank=True, default='')
    is_verified      = models.BooleanField(default=False, help_text='Director/Manager verified this sale')
    verified_by      = models.ForeignKey(
        'User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='verified_online_sales'
    )
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sale_date', '-created_at']
        verbose_name = 'Online Sale Log'
        verbose_name_plural = 'Online Sale Logs'

    def __str__(self):
        return f"{self.staff.username} — {self.product_name} ({self.sale_date})"

    @property
    def image_url(self):
        try:
            if self.evidence_image:
                return self.evidence_image.url
        except Exception:
            pass
        return None
'''
    with open(f'{W}/core/models.py', 'a') as f:
        f.write(model)
    print("  OnlineSaleLog model added")
else:
    print("  Already exists")

# ── STEP 2: Migration ──
print("\n--- Step 2: Migration ---")
result = subprocess.run(
    ['python', 'manage.py', 'makemigrations', 'core', '--name', 'add_online_sale_log'],
    cwd=W, capture_output=True, text=True
)
out = result.stdout.strip() or result.stderr.strip()
print(" ", out[-300:] if len(out) > 300 else out)

result2 = subprocess.run(
    ['python', 'manage.py', 'migrate'],
    cwd=W, capture_output=True, text=True
)
out2 = result2.stdout.strip()
print(" ", out2[-200:] if len(out2) > 200 else out2)

# ── STEP 3: Views ──
print("\n--- Step 3: Views ---")
views = open(f'{W}/core/views.py').read()

new_views = '''

# ─────────────────────────────────────────
# ONLINE SALES LOG
# ─────────────────────────────────────────

@login_required
def log_online_sale(request):
    """Any staff can log an online/social media sale."""
    from core.models import OnlineSaleLog
    from datetime import date

    if request.method == 'POST':
        try:
            image = request.FILES.get('evidence_image')
            sale = OnlineSaleLog(
                staff=request.user,
                branch=request.user.branch,
                product_name=request.POST.get('product_name', '').strip(),
                customer_name=request.POST.get('customer_name', '').strip(),
                customer_phone=request.POST.get('customer_phone', '').strip(),
                platform=request.POST.get('platform', 'whatsapp'),
                amount=request.POST.get('amount', 0) or 0,
                sale_date=request.POST.get('sale_date') or date.today(),
                notes=request.POST.get('notes', '').strip(),
            )
            if image:
                sale.evidence_image = image
            sale.save()
            messages.success(request, f"Online sale logged successfully — {sale.product_name}")
        except Exception as e:
            messages.error(request, f"Error: {e}")
        return redirect('my_online_sales')

    return render(request, 'online_sales/log_sale.html', {
        'today': date.today(),
        'platforms': OnlineSaleLog.PLATFORM_CHOICES,
    })


@login_required
def my_online_sales(request):
    """Staff sees their own online sales log."""
    from core.models import OnlineSaleLog
    from django.db.models import Sum, Count
    from datetime import date

    sales = OnlineSaleLog.objects.filter(
        staff=request.user
    ).order_by('-sale_date', '-created_at')

    # Stats
    total_sales = sales.count()
    total_amount = sales.aggregate(t=Sum('amount'))['t'] or 0
    verified = sales.filter(is_verified=True).count()
    this_month = sales.filter(
        sale_date__month=date.today().month,
        sale_date__year=date.today().year
    )
    month_amount = this_month.aggregate(t=Sum('amount'))['t'] or 0

    # Filter
    platform_flt = request.GET.get('platform', '')
    if platform_flt:
        sales = sales.filter(platform=platform_flt)

    from core.models import OnlineSaleLog as OSL
    return render(request, 'online_sales/my_sales.html', {
        'sales': sales,
        'total_sales': total_sales,
        'total_amount': total_amount,
        'verified': verified,
        'month_amount': month_amount,
        'month_count': this_month.count(),
        'platforms': OSL.PLATFORM_CHOICES,
        'platform_flt': platform_flt,
        'today': date.today(),
    })


@role_required('DIRECTOR', 'MANAGER')
def online_sales_overview(request):
    """Director/Manager sees all online sales with leaderboard."""
    from core.models import OnlineSaleLog, Branch
    from django.db.models import Sum, Count
    from datetime import date

    today = date.today()

    # Filters
    staff_flt    = request.GET.get('staff', '')
    branch_flt   = request.GET.get('branch', '')
    platform_flt = request.GET.get('platform', '')
    date_from    = request.GET.get('date_from', '')
    date_to      = request.GET.get('date_to', '')
    verified_flt = request.GET.get('verified', '')

    sales = OnlineSaleLog.objects.select_related(
        'staff', 'branch', 'verified_by'
    ).order_by('-sale_date', '-created_at')

    # Managers see their branch only
    if request.user.role == 'MANAGER' and request.user.branch:
        sales = sales.filter(branch=request.user.branch)
    elif branch_flt:
        sales = sales.filter(branch_id=branch_flt)

    if staff_flt:
        sales = sales.filter(staff_id=staff_flt)
    if platform_flt:
        sales = sales.filter(platform=platform_flt)
    if date_from:
        sales = sales.filter(sale_date__gte=date_from)
    if date_to:
        sales = sales.filter(sale_date__lte=date_to)
    if verified_flt == '1':
        sales = sales.filter(is_verified=True)
    elif verified_flt == '0':
        sales = sales.filter(is_verified=False)

    # Leaderboard — top staff by count and amount this month
    leaderboard = OnlineSaleLog.objects.filter(
        sale_date__month=today.month,
        sale_date__year=today.year,
    )
    if request.user.role == 'MANAGER' and request.user.branch:
        leaderboard = leaderboard.filter(branch=request.user.branch)

    leaderboard = leaderboard.values(
        'staff__username', 'staff__id', 'branch__name'
    ).annotate(
        count=Count('id'),
        total=Sum('amount'),
        verified=Count('id', filter=Q(is_verified=True))
    ).order_by('-count')[:10]

    # Verify/unverify action
    if request.method == 'POST' and request.user.role in ['DIRECTOR', 'MANAGER']:
        sale_id = request.POST.get('sale_id')
        action  = request.POST.get('action')
        try:
            sale = OnlineSaleLog.objects.get(id=sale_id)
            if action == 'verify':
                sale.is_verified = True
                sale.verified_by = request.user
                sale.save()
                messages.success(request, f"Sale verified — {sale.product_name}")
            elif action == 'unverify':
                sale.is_verified = False
                sale.verified_by = None
                sale.save()
                messages.success(request, "Verification removed.")
        except OnlineSaleLog.DoesNotExist:
            messages.error(request, "Sale not found.")
        return redirect(request.get_full_path())

    # Totals
    total_count  = sales.count()
    total_amount = sales.aggregate(t=Sum('amount'))['t'] or 0
    verified_count = sales.filter(is_verified=True).count()

    branches   = Branch.objects.all()
    staff_list = User.objects.filter(
        role__in=['RETAIL', 'TELECOM', 'MULTICHOICE', 'MANAGER']
    ).order_by('username')
    if request.user.role == 'MANAGER' and request.user.branch:
        staff_list = staff_list.filter(branch=request.user.branch)

    from core.models import OnlineSaleLog as OSL
    return render(request, 'online_sales/overview.html', {
        'sales': sales[:100],
        'leaderboard': leaderboard,
        'total_count': total_count,
        'total_amount': total_amount,
        'verified_count': verified_count,
        'branches': branches,
        'staff_list': staff_list,
        'platforms': OSL.PLATFORM_CHOICES,
        'staff_flt': staff_flt,
        'branch_flt': branch_flt,
        'platform_flt': platform_flt,
        'date_from': date_from,
        'date_to': date_to,
        'verified_flt': verified_flt,
        'today': today,
    })
'''

if 'def log_online_sale' not in views:
    views += new_views
    open(f'{W}/core/views.py', 'w').write(views)
    print("  3 views added")
else:
    print("  Already exist")

# ── STEP 4: URLs ──
print("\n--- Step 4: URLs ---")
urls = open(f'{W}/core/urls.py').read()
routes = [
    ("online-sales/log/",      "views.log_online_sale",       "log_online_sale"),
    ("online-sales/mine/",     "views.my_online_sales",       "my_online_sales"),
    ("online-sales/overview/", "views.online_sales_overview", "online_sales_overview"),
]
for path, view, name in routes:
    if name not in urls:
        route = f"    path('{path}', {view}, name='{name}'),"
        urls = urls.rstrip().rstrip(']').rstrip() + '\n' + route + '\n]\n'
        print(f"  Added: {name}")
    else:
        print(f"  Exists: {name}")
open(f'{W}/core/urls.py', 'w').write(urls)

# ── STEP 5: Templates ──
print("\n--- Step 5: Templates ---")
os.makedirs(f'{W}/templates/online_sales', exist_ok=True)

# ── Log sale form (all staff) ──
log_tmpl = '''{% extends "base.html" %}
{% block content %}
<style>
.page-title{font-size:1.2rem;font-weight:700;color:#004F9F;margin:0}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1.2rem 1.4rem;margin-bottom:1rem}
.form-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:.75rem}
.fg{margin-bottom:.75rem}
.fg label{font-size:.75rem;font-weight:600;color:#374151;display:block;margin-bottom:.3rem}
.fg input,.fg select,.fg textarea{width:100%;padding:.55rem .8rem;border:1.5px solid #e2e8f0;border-radius:7px;font-size:.85rem;box-sizing:border-box;font-family:inherit}
.fg input:focus,.fg select:focus,.fg textarea:focus{outline:none;border-color:#004F9F;box-shadow:0 0 0 3px rgba(0,79,159,.08)}
.btn-p{background:#004F9F;color:#fff;padding:.65rem 1.4rem;border:none;border-radius:8px;font-size:.88rem;font-weight:700;cursor:pointer;width:100%;margin-top:.4rem}
.btn-p:hover{background:#003d7a}
.platform-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem;margin-bottom:.75rem}
.plat-btn{border:1.5px solid #e2e8f0;background:#fff;border-radius:8px;padding:.5rem;text-align:center;cursor:pointer;transition:.15s;font-size:.78rem;font-weight:600}
.plat-btn:hover,.plat-btn.active{border-color:#004F9F;background:#eff6ff;color:#004F9F}
</style>

<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.75rem;margin-bottom:1.25rem">
  <h1 class="page-title">📱 Log Online Sale</h1>
  <a href="{% url 'my_online_sales' %}" style="font-size:.82rem;color:#004F9F;text-decoration:none;">← My Sales Log</a>
</div>

{% if messages %}{% for m in messages %}
<div style="background:{% if m.tags == 'error' %}#fee2e2{% else %}#dcfce7{% endif %};border-radius:7px;padding:.65rem 1rem;font-size:.83rem;margin-bottom:1rem;">{{ m }}</div>
{% endfor %}{% endif %}

<div class="card">
  <form method="POST" enctype="multipart/form-data">
    {% csrf_token %}
    <div class="form-row">
      <div class="fg">
        <label>Product / Service Sold *</label>
        <input type="text" name="product_name" required placeholder="e.g. iPhone 14, DStv Compact, MTN SIM">
      </div>
      <div class="fg">
        <label>Amount (₦) *</label>
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

open(f'{W}/templates/online_sales/log_sale.html', 'w').write(log_tmpl)
print("  log_sale.html created")

# ── My sales (staff view) ──
my_tmpl = '''{% extends "base.html" %}
{% block content %}
<style>
.page-title{font-size:1.2rem;font-weight:700;color:#004F9F;margin:0}
.stat-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:.75rem;margin-bottom:1.2rem}
.stat{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:.85rem;text-align:center}
.stat-n{font-size:1.4rem;font-weight:800;line-height:1}
.stat-l{font-size:.7rem;color:#64748b;margin-top:.2rem}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1.1rem 1.3rem;margin-bottom:1rem}
.table{width:100%;border-collapse:collapse;font-size:.82rem}
.table th{background:#004F9F;color:#fff;padding:.5rem .8rem;text-align:left;font-weight:600}
.table td{padding:.55rem .8rem;border-bottom:1px solid #f1f5f9;vertical-align:middle}
.table tr:hover td{background:#f8fafc}
.badge{display:inline-block;padding:.18rem .55rem;border-radius:999px;font-size:.68rem;font-weight:700}
.b-green{background:#dcfce7;color:#166534}
.b-yellow{background:#fef9c3;color:#854d0e}
.btn-sm{padding:.38rem .8rem;font-size:.78rem;border-radius:6px;border:none;cursor:pointer;font-weight:600;text-decoration:none;display:inline-block}
.btn-primary{background:#004F9F;color:#fff}
</style>

<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.75rem;margin-bottom:1.25rem">
  <h1 class="page-title">📱 My Online Sales</h1>
  <a href="{% url 'log_online_sale' %}" class="btn-sm btn-primary">+ Log New Sale</a>
</div>

{% if messages %}{% for m in messages %}
<div style="background:{% if m.tags == 'error' %}#fee2e2{% else %}#dcfce7{% endif %};border-radius:7px;padding:.65rem 1rem;font-size:.83rem;margin-bottom:1rem;">{{ m }}</div>
{% endfor %}{% endif %}

<div class="stat-row">
  <div class="stat"><div class="stat-n" style="color:#004F9F">{{ total_sales }}</div><div class="stat-l">Total Logs</div></div>
  <div class="stat"><div class="stat-n" style="color:#22c55e">{{ month_count }}</div><div class="stat-l">This Month</div></div>
  <div class="stat"><div class="stat-n" style="color:#004F9F;font-size:1rem">₦{{ month_amount|floatformat:0 }}</div><div class="stat-l">Month Amount</div></div>
  <div class="stat"><div class="stat-n" style="color:#eab308">{{ verified }}</div><div class="stat-l">Verified</div></div>
</div>

<div class="card">
  <form method="GET" style="display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1rem;align-items:flex-end;">
    <div>
      <label style="font-size:.72rem;font-weight:600;display:block;margin-bottom:.2rem">Platform</label>
      <select name="platform" style="padding:.4rem .7rem;border:1.5px solid #e2e8f0;border-radius:7px;font-size:.82rem;">
        <option value="">All Platforms</option>
        {% for val, label in platforms %}
        <option value="{{ val }}" {% if platform_flt == val %}selected{% endif %}>{{ label }}</option>
        {% endfor %}
      </select>
    </div>
    <button type="submit" style="padding:.42rem .9rem;background:#004F9F;color:#fff;border:none;border-radius:7px;font-size:.82rem;font-weight:600;cursor:pointer;align-self:flex-end">Filter</button>
    <a href="{% url 'my_online_sales' %}" style="padding:.42rem .9rem;border:1px solid #d1d5db;border-radius:7px;font-size:.82rem;font-weight:600;text-decoration:none;color:#374151;align-self:flex-end">Clear</a>
  </form>

  {% if sales %}
  <div style="overflow-x:auto">
    <table class="table">
      <thead><tr><th>Date</th><th>Product</th><th>Customer</th><th>Phone</th><th>Platform</th><th>Amount</th><th>Evidence</th><th>Status</th></tr></thead>
      <tbody>
        {% for s in sales %}
        <tr>
          <td style="font-size:.75rem;color:#64748b">{{ s.sale_date|date:"d M Y" }}</td>
          <td><strong>{{ s.product_name }}</strong></td>
          <td>{{ s.customer_name }}</td>
          <td>{{ s.customer_phone }}</td>
          <td><span class="badge b-yellow">{{ s.get_platform_display }}</span></td>
          <td style="font-weight:700;color:#004F9F">₦{{ s.amount|floatformat:0 }}</td>
          <td>
            {% if s.image_url %}
            <a href="{{ s.image_url }}" target="_blank" style="color:#004F9F;font-size:.75rem;text-decoration:none;">📷 View</a>
            {% else %}—{% endif %}
          </td>
          <td>
            {% if s.is_verified %}
            <span class="badge b-green">✅ Verified</span>
            {% else %}
            <span class="badge" style="background:#f1f5f9;color:#64748b;">Pending</span>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <p style="color:#94a3b8;text-align:center;padding:2rem">No online sales logged yet. <a href="{% url 'log_online_sale' %}" style="color:#004F9F">Log your first sale →</a></p>
  {% endif %}
</div>
{% endblock %}'''

open(f'{W}/templates/online_sales/my_sales.html', 'w').write(my_tmpl)
print("  my_sales.html created")

# ── Director/Manager overview ──
overview_tmpl = '''{% extends "base.html" %}
{% block content %}
<style>
.page-title{font-size:1.2rem;font-weight:700;color:#004F9F;margin:0}
.stat-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:.75rem;margin-bottom:1.2rem}
.stat{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:.85rem;text-align:center}
.stat-n{font-size:1.5rem;font-weight:800;line-height:1}
.stat-l{font-size:.7rem;color:#64748b;margin-top:.2rem}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1.1rem 1.3rem;margin-bottom:1rem}
.card-title{font-size:.92rem;font-weight:700;margin:0 0 .85rem}
.table{width:100%;border-collapse:collapse;font-size:.82rem}
.table th{background:#004F9F;color:#fff;padding:.5rem .8rem;text-align:left;font-weight:600}
.table td{padding:.55rem .8rem;border-bottom:1px solid #f1f5f9;vertical-align:middle}
.table tr:hover td{background:#f8fafc}
.badge{display:inline-block;padding:.18rem .55rem;border-radius:999px;font-size:.68rem;font-weight:700}
.b-green{background:#dcfce7;color:#166534}
.b-yellow{background:#fef9c3;color:#854d0e}
.b-pend{background:#f1f5f9;color:#64748b}
.filter-bar{display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1.2rem;align-items:flex-end}
.filter-bar select,.filter-bar input{padding:.42rem .7rem;border:1.5px solid #e2e8f0;border-radius:7px;font-size:.82rem}
.btn-sm{padding:.35rem .75rem;font-size:.75rem;border-radius:6px;border:none;cursor:pointer;font-weight:600;text-decoration:none;display:inline-block}
.btn-verify{background:#22c55e;color:#fff}
.btn-unverify{background:#f97316;color:#fff}
.rank-1{color:#f59e0b;font-weight:800;font-size:1rem}
.rank-2{color:#94a3b8;font-weight:700}
.rank-3{color:#cd7c3a;font-weight:700}
</style>

<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.75rem;margin-bottom:1.25rem">
  <h1 class="page-title">📱 Online Sales Overview</h1>
  <span style="font-size:.8rem;color:#64748b">{{ today|date:"F Y" }} Leaderboard</span>
</div>

{% if messages %}{% for m in messages %}
<div style="background:{% if m.tags == 'error' %}#fee2e2{% else %}#dcfce7{% endif %};border-radius:7px;padding:.65rem 1rem;font-size:.83rem;margin-bottom:1rem;">{{ m }}</div>
{% endfor %}{% endif %}

<div class="stat-row">
  <div class="stat"><div class="stat-n" style="color:#004F9F">{{ total_count }}</div><div class="stat-l">Total Logs</div></div>
  <div class="stat"><div class="stat-n" style="color:#22c55e;font-size:1rem">₦{{ total_amount|floatformat:0 }}</div><div class="stat-l">Total Amount</div></div>
  <div class="stat"><div class="stat-n" style="color:#22c55e">{{ verified_count }}</div><div class="stat-l">Verified</div></div>
  <div class="stat"><div class="stat-n" style="color:#f97316">{{ total_count|add:"-"|add:verified_count }}</div><div class="stat-l">Pending</div></div>
</div>

<!-- LEADERBOARD -->
<div class="card" style="border-color:#fde68a;background:linear-gradient(135deg,#fff 80%,#fefce8)">
  <p class="card-title">🏆 This Month's Leaderboard</p>
  {% if leaderboard %}
  <table class="table">
    <thead><tr><th>#</th><th>Staff</th><th>Branch</th><th>Sales</th><th>Verified</th><th>Amount</th></tr></thead>
    <tbody>
      {% for item in leaderboard %}
      <tr>
        <td>
          {% if forloop.counter == 1 %}<span class="rank-1">🥇 1</span>
          {% elif forloop.counter == 2 %}<span class="rank-2">🥈 2</span>
          {% elif forloop.counter == 3 %}<span class="rank-3">🥉 3</span>
          {% else %}{{ forloop.counter }}{% endif %}
        </td>
        <td><strong>{{ item.staff__username }}</strong></td>
        <td style="font-size:.78rem;color:#64748b">{{ item.branch__name }}</td>
        <td><span class="badge" style="background:#dbeafe;color:#1e40af">{{ item.count }}</span></td>
        <td><span class="badge b-green">{{ item.verified }}</span></td>
        <td style="font-weight:700;color:#004F9F">₦{{ item.total|floatformat:0 }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p style="color:#94a3b8;text-align:center;padding:1.5rem">No online sales logged this month yet.</p>
  {% endif %}
</div>

<!-- FILTERS -->
<form method="GET" class="filter-bar">
  <div><label style="font-size:.72rem;font-weight:600;display:block;margin-bottom:.2rem">Staff</label>
    <select name="staff"><option value="">All Staff</option>
    {% for s in staff_list %}<option value="{{ s.id }}" {% if staff_flt == s.id|stringformat:"s" %}selected{% endif %}>{{ s.username }}</option>{% endfor %}
    </select>
  </div>
  {% if user.role == 'DIRECTOR' %}
  <div><label style="font-size:.72rem;font-weight:600;display:block;margin-bottom:.2rem">Branch</label>
    <select name="branch"><option value="">All Branches</option>
    {% for b in branches %}<option value="{{ b.id }}" {% if branch_flt == b.id|stringformat:"s" %}selected{% endif %}>{{ b.name }}</option>{% endfor %}
    </select>
  </div>
  {% endif %}
  <div><label style="font-size:.72rem;font-weight:600;display:block;margin-bottom:.2rem">Platform</label>
    <select name="platform"><option value="">All Platforms</option>
    {% for val, label in platforms %}<option value="{{ val }}" {% if platform_flt == val %}selected{% endif %}>{{ label }}</option>{% endfor %}
    </select>
  </div>
  <div><label style="font-size:.72rem;font-weight:600;display:block;margin-bottom:.2rem">From</label>
    <input type="date" name="date_from" value="{{ date_from }}">
  </div>
  <div><label style="font-size:.72rem;font-weight:600;display:block;margin-bottom:.2rem">To</label>
    <input type="date" name="date_to" value="{{ date_to }}">
  </div>
  <div><label style="font-size:.72rem;font-weight:600;display:block;margin-bottom:.2rem">Status</label>
    <select name="verified">
      <option value="">All</option>
      <option value="1" {% if verified_flt == '1' %}selected{% endif %}>Verified Only</option>
      <option value="0" {% if verified_flt == '0' %}selected{% endif %}>Pending Only</option>
    </select>
  </div>
  <button type="submit" style="padding:.44rem .9rem;background:#004F9F;color:#fff;border:none;border-radius:7px;font-size:.82rem;font-weight:600;cursor:pointer;align-self:flex-end">Filter</button>
  <a href="{% url 'online_sales_overview' %}" style="padding:.44rem .9rem;border:1px solid #d1d5db;border-radius:7px;font-size:.82rem;font-weight:600;text-decoration:none;color:#374151;align-self:flex-end">Clear</a>
</form>

<!-- ALL SALES TABLE -->
<div class="card">
  <p class="card-title">All Online Sales ({{ total_count }})</p>
  {% if sales %}
  <div style="overflow-x:auto">
    <table class="table">
      <thead><tr><th>Date</th><th>Staff</th><th>Branch</th><th>Product</th><th>Customer</th><th>Phone</th><th>Platform</th><th>Amount</th><th>Evidence</th><th>Status</th><th>Action</th></tr></thead>
      <tbody>
        {% for s in sales %}
        <tr>
          <td style="font-size:.75rem;color:#64748b">{{ s.sale_date|date:"d M Y" }}</td>
          <td><strong>{{ s.staff.username }}</strong></td>
          <td style="font-size:.75rem;color:#64748b">{{ s.branch.name }}</td>
          <td>{{ s.product_name }}</td>
          <td>{{ s.customer_name }}</td>
          <td>{{ s.customer_phone }}</td>
          <td><span class="badge b-yellow">{{ s.get_platform_display }}</span></td>
          <td style="font-weight:700;color:#004F9F">₦{{ s.amount|floatformat:0 }}</td>
          <td>{% if s.image_url %}<a href="{{ s.image_url }}" target="_blank" style="color:#004F9F;font-size:.75rem">📷 View</a>{% else %}—{% endif %}</td>
          <td>{% if s.is_verified %}<span class="badge b-green">✅ Verified</span>{% else %}<span class="badge b-pend">Pending</span>{% endif %}</td>
          <td>
            <form method="POST" style="display:inline">
              {% csrf_token %}
              <input type="hidden" name="sale_id" value="{{ s.id }}">
              {% if s.is_verified %}
              <input type="hidden" name="action" value="unverify">
              <button type="submit" class="btn-sm btn-unverify">Unverify</button>
              {% else %}
              <input type="hidden" name="action" value="verify">
              <button type="submit" class="btn-sm btn-verify">Verify</button>
              {% endif %}
            </form>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <p style="color:#94a3b8;text-align:center;padding:2rem">No online sales found with current filters.</p>
  {% endif %}
</div>
{% endblock %}'''

open(f'{W}/templates/online_sales/overview.html', 'w').write(overview_tmpl)
print("  overview.html created")

# ── STEP 6: Sidebar links for ALL roles ──
print("\n--- Step 6: Sidebar links for all roles ---")
base = open(f'{W}/templates/base.html').read()
changed = False

role_anchors = {
    'DIRECTOR':    ("{% url 'catalog_management' %}",   'online_sales_overview', '📱', 'Online Sales'),
    'MANAGER':     ("{% url 'manager_sales_today' %}",  'online_sales_overview', '📱', 'Online Sales'),
    'RETAIL':      ("{% url 'staff_dashboard' %}",      'my_online_sales',       '📱', 'Online Sales'),
    'TELECOM':     ("{% url 'staff_dashboard' %}",      'my_online_sales',       '📱', 'Online Sales'),
    'MULTICHOICE': ("{% url 'multichoice_dashboard' %}", 'my_online_sales',      '📱', 'Online Sales'),
}

for role, (anchor, url_name, icon, label) in role_anchors.items():
    link = f"{{% url '{url_name}' %}}"
    if url_name not in base and anchor in base:
        idx = base.find(anchor)
        end = base.find('</a>', idx) + 4
        insert = f'\n            <a href="{{% url \'{url_name}\' %}}" class="sidebar-link">\n                <span class="icon">{icon}</span> {label}\n            </a>'
        base = base[:end] + insert + base[end:]
        print(f"  Added Online Sales link to {role} sidebar")
        changed = True
    elif url_name in base:
        print(f"  {role}: already has link")
    else:
        print(f"  WARNING: {role} anchor not found in base.html")

if changed:
    open(f'{W}/templates/base.html', 'w').write(base)

# ── STEP 7: Syntax check ──
print("\n--- Step 7: Syntax check ---")
for fn in ['core/views.py', 'core/urls.py', 'core/models.py']:
    try:
        ast.parse(open(f'{W}/{fn}').read())
        print(f"  {fn}: OK")
    except SyntaxError as e:
        print(f"  {fn}: ERROR line {e.lineno}: {e.msg}")

print("\n" + "=" * 55)
print("DONE — Online Sales Log built")
print("=" * 55)
print("\nRun:")
print("  python manage.py check")
print("  python manage.py runserver 0.0.0.0:8000")
print("\nTest:")
print("  Log in as any staff → sidebar → 📱 Online Sales")
print("  Log a test sale with a photo")
print("  Log in as Director → 📱 Online Sales → see leaderboard")
print("\nPush:")
print("  git add . && git commit -m 'Add online sales log with leaderboard' && git push")
