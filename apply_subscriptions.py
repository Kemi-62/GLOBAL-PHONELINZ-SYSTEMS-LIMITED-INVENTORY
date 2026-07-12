"""
SUBSCRIPTION FEATURES APPLY SCRIPT
====================================
Run: python /home/runner/workspace/apply_subscriptions.py

Adds:
1. RouterSubscription model to models.py
2. expiry_date + days_to_expiry to MultiChoiceSale
3. 3 new views to views.py
4. 8 new URLs to urls.py
5. Updated stock_alert_email.py
6. Templates for router subs and MC retention
7. Sidebar links for new pages
"""
import os, shutil

W = '/home/runner/workspace'

print("=" * 55)
print("SUBSCRIPTION FEATURES SETUP")
print("=" * 55)

# ── 1. Add RouterSubscription model ──
print("\n--- Adding RouterSubscription model ---")
models_code = open(f'{W}/core/models.py').read()
if 'class RouterSubscription' not in models_code:
    addition = '''

class RouterSubscription(models.Model):
    """
    Tracks 4G/5G Router subscriptions sold by Telecom staff.
    Policy: every router sale must have 2 months subscription recorded.
    Each month = 30 days. Staff must renew before expiry.
    """
    ROUTER_TYPE_CHOICES = [
        ('4G', '4G Router'),
        ('5G', '5G Router'),
    ]
    staff             = models.ForeignKey('User', on_delete=models.CASCADE, related_name='router_subs')
    branch            = models.ForeignKey('Branch', on_delete=models.CASCADE, related_name='router_subs')
    customer_name     = models.CharField(max_length=150)
    customer_phone    = models.CharField(max_length=20)
    alt_phone         = models.CharField(max_length=20, blank=True, default='')
    router_number     = models.CharField(max_length=100, help_text='Router serial / SIM number')
    router_type       = models.CharField(max_length=20, choices=ROUTER_TYPE_CHOICES, default='4G')
    network           = models.CharField(max_length=50, blank=True, default='MTN')
    subscription_date = models.DateField(null=True, blank=True)
    expiry_date       = models.DateField(null=True, blank=True, help_text='Auto-set to subscription_date + 30 days')
    month_number      = models.PositiveIntegerField(default=1, help_text='1 = first month, 2 = second month')
    amount            = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active         = models.BooleanField(default=True)
    notes             = models.TextField(blank=True, default='')
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['expiry_date']
        verbose_name = 'Router Subscription'
        verbose_name_plural = 'Router Subscriptions'

    def save(self, *args, **kwargs):
        from datetime import date, timedelta
        if not self.subscription_date:
            self.subscription_date = date.today()
        if not self.expiry_date:
            self.expiry_date = self.subscription_date + timedelta(days=30)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.customer_name} — {self.router_number} (expires {self.expiry_date})"

    @property
    def days_to_expiry(self):
        from datetime import date
        if self.expiry_date:
            return (self.expiry_date - date.today()).days
        return 999

    @property
    def is_expired(self):
        return self.days_to_expiry < 0

    @property
    def expiry_status(self):
        days = self.days_to_expiry
        if days < 0: return 'expired'
        if days <= 3: return 'critical'
        if days <= 7: return 'warning'
        return 'active'
'''
    with open(f'{W}/core/models.py', 'a') as f:
        f.write(addition)
    print("  RouterSubscription model added")
else:
    print("  Already exists")

# ── 2. Add expiry_date to MultiChoiceSale ──
print("\n--- Adding expiry_date to MultiChoiceSale ---")
models_code = open(f'{W}/core/models.py').read()
if 'expiry_date' not in models_code or 'MultiChoiceSale' not in models_code.split('expiry_date')[0]:
    # Add expiry_date field after 'time' field in MultiChoiceSale
    old_mc = "    date = models.DateField(auto_now_add=True)\n    time = models.TimeField(auto_now_add=True)\n\n    def __str__(self):\n        return f\"{self.customer_name} - {self.package_type}\""
    new_mc = """    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)
    expiry_date = models.DateField(null=True, blank=True, help_text='Auto-set to date + 30 days')

    def save(self, *args, **kwargs):
        from datetime import date, timedelta
        if not self.expiry_date:
            today = date.today()
            self.expiry_date = today + timedelta(days=30)
        super().save(*args, **kwargs)

    @property
    def days_to_expiry(self):
        from datetime import date
        if self.expiry_date:
            return (self.expiry_date - date.today()).days
        return None

    @property
    def is_expired(self):
        from datetime import date
        return self.expiry_date and self.expiry_date < date.today()

    @property
    def expiry_status(self):
        days = self.days_to_expiry
        if days is None: return 'unknown'
        if days < 0: return 'expired'
        if days <= 3: return 'critical'
        if days <= 7: return 'warning'
        return 'active'

    def __str__(self):
        return f"{self.customer_name} - {self.package_type}\""""
    if old_mc in models_code:
        models_code = models_code.replace(old_mc, new_mc)
        open(f'{W}/core/models.py', 'w').write(models_code)
        print("  expiry_date added to MultiChoiceSale")
    else:
        print("  WARNING: MultiChoiceSale pattern not found - add expiry_date manually")
else:
    print("  expiry_date already exists")

# ── 3. Add views ──
print("\n--- Adding views ---")
views_code = open(f'{W}/core/views.py').read()
if 'def router_subscriptions' not in views_code:
    views_addition = open(f'{W}/subscription_views.py').read()
    with open(f'{W}/core/views.py', 'a') as f:
        f.write('\n\n' + views_addition)
    print("  router_subscriptions, router_subscriptions_overview, mc_subscription_retention added")
else:
    print("  Views already exist")

# ── 4. Add URLs ──
print("\n--- Adding URLs ---")
urls_code = open(f'{W}/core/urls.py').read()
routes = [
    ("telecom/router-subscriptions/",             "views.router_subscriptions",           "router_subscriptions"),
    ("director/router-subscriptions/",            "views.router_subscriptions_overview",  "router_subscriptions_overview"),
    ("director/mc-retention/",                    "views.mc_subscription_retention",      "mc_subscription_retention"),
    ("manager/router-subscriptions/",             "views.router_subscriptions_overview",  "manager_router_subscriptions"),
]
added = 0
for path, view, name in routes:
    if name not in urls_code:
        route_line = f"    path('{path}', {view}, name='{name}'),"
        urls_code = urls_code.rstrip().rstrip(']').rstrip() + '\n' + route_line + '\n]\n'
        added += 1
        print(f"  Added: {name}")
    else:
        print(f"  Exists: {name}")
open(f'{W}/core/urls.py', 'w').write(urls_code)

# ── 5. Copy stock_alert_email.py ──
print("\n--- Updating stock_alert_email.py ---")
src = f'{W}/stock_alert_email.py'
dst = f'{W}/core/management/commands/stock_alert_email.py'
if os.path.exists(src):
    shutil.copy(src, dst)
    print("  stock_alert_email.py replaced with subscription-aware version")

# ── 6. Copy templates ──
print("\n--- Copying templates ---")
os.makedirs(f'{W}/templates/telecom', exist_ok=True)
os.makedirs(f'{W}/templates/director', exist_ok=True)

# router_subscriptions.html (telecom)
src = f'{W}/router_subscriptions.html'
if os.path.exists(src):
    shutil.copy(src, f'{W}/templates/telecom/router_subscriptions.html')
    print("  router_subscriptions.html -> templates/telecom/")

# mc_retention.html (director)
src = f'{W}/mc_retention.html'
if os.path.exists(src):
    shutil.copy(src, f'{W}/templates/director/mc_retention.html')
    print("  mc_retention.html -> templates/director/")

# router_subscriptions_overview.html (director/manager)
src = f'{W}/router_subscriptions_overview.html'
if os.path.exists(src):
    shutil.copy(src, f'{W}/templates/director/router_subscriptions_overview.html')
    print("  router_subscriptions_overview.html -> templates/director/")

# ── 7. Add sidebar links ──
print("\n--- Adding sidebar links ---")
base = open(f'{W}/templates/base.html').read()

# Telecom sidebar link
if 'router_subscriptions' not in base:
    base = base.replace(
        "{% if user.role == 'TELECOM' %}",
        "{% if user.role == 'TELECOM' %}\n            <a href=\"{% url 'router_subscriptions' %}\" class=\"sidebar-link\">\n                <span class=\"icon\">📡</span> Router Subscriptions\n            </a>",
        1
    )
    print("  Router Subscriptions added to Telecom sidebar")

# Director sidebar links
if 'mc_subscription_retention' not in base:
    base = base.replace(
        "{% url 'commission_tracking' %}",
        "{% url 'commission_tracking' %}"
    )
    # Find a good anchor in director sidebar
    if "{% url 'catalog_management' %}" in base:
        base = base.replace(
            "{% url 'catalog_management' %}",
            "{% url 'catalog_management' %}"
        )
        # Add after catalog management
        old_link = "🛍️</span> Catalog Management\n            </a>"
        new_links = "🛍️</span> Catalog Management\n            </a>\n            <a href=\"{% url 'mc_subscription_retention' %}\" class=\"sidebar-link\">\n                <span class=\"icon\">📺</span> MC Retention\n            </a>\n            <a href=\"{% url 'router_subscriptions_overview' %}\" class=\"sidebar-link\">\n                <span class=\"icon\">📡</span> Router Subs\n            </a>"
        if old_link in base:
            base = base.replace(old_link, new_links)
            print("  MC Retention + Router Subs added to Director sidebar")

open(f'{W}/templates/base.html', 'w').write(base)

print("\n" + "=" * 55)
print("DONE. Now run:")
print("  python manage.py makemigrations")
print("  python manage.py migrate")
print("  python manage.py check")
print("  python manage.py runserver 0.0.0.0:8000")
print("\nThen push:")
print("  git add . && git commit -m 'Add router subs, MC expiry, subscription alerts' && git push")
