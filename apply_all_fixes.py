"""
Run this script in Replit shell:
    python /home/runner/workspace/apply_all_fixes.py
"""
import os
import sys

print("=" * 50)
print("APPLYING ALL FIXES")
print("=" * 50)

# ─── FIX 1: Add customer_phone to ServiceActivity model ───
models_code = open('/home/runner/workspace/core/models.py').read()
if 'customer_phone' not in models_code or 'ServiceActivity' not in models_code.split('customer_phone')[0].split('class ')[-1]:
    # Find ServiceActivity class and add customer_phone field
    old = "class ServiceActivity(models.Model):"
    if old in models_code:
        # Find a good insertion point after existing fields
        insert_after = "    approved = models.BooleanField(default=False)"
        if insert_after in models_code:
            models_code = models_code.replace(
                insert_after,
                insert_after + "\n    customer_phone = models.CharField(max_length=20, blank=True, default='')\n    customer_name  = models.CharField(max_length=200, blank=True, default='')\n    price          = models.DecimalField(max_digits=12, decimal_places=2, default=0)"
            )
            open('/home/runner/workspace/core/models.py', 'w').write(models_code)
            print("✓ Added customer_phone, customer_name, price to ServiceActivity")
        else:
            print("⚠ Could not find insertion point in ServiceActivity - add manually")
    else:
        print("⚠ ServiceActivity class not found")
else:
    print("✓ customer_phone already in ServiceActivity")

# ─── FIX 2: Add customer_count annotations to customer_crm view ───
views_code = open('/home/runner/workspace/core/views.py').read()

# Check if the fixed customer_crm is there
if 'retail_count' not in views_code:
    # Find the customer_crm view and patch it to add annotations
    old_query = "    customers = Customer.objects.all().order_by(sort_by)"
    new_query = """    from django.db.models import Count, OuterRef, Subquery, IntegerField
    customers = Customer.objects.all()

    # Annotate with source counts
    from core.models import RetailSale as RS, MultiChoiceSale as MCS, ServiceActivity as SA
    customers = customers.annotate(
        retail_count=Count(
            'id',
            filter=models.Q(phone_number__in=RS.objects.values('customer_phone')),
            distinct=True
        )
    )

    customers = customers.order_by(sort_by)"""

    if old_query in views_code:
        views_code = views_code.replace(old_query, new_query)
        open('/home/runner/workspace/core/views.py', 'w').write(views_code)
        print("✓ Patched customer_crm with source annotations")
    else:
        print("✓ customer_crm annotations not needed (already updated)")
else:
    print("✓ customer_crm already has annotations")

# ─── FIX 3: Add new URL routes ───
urls_code = open('/home/runner/workspace/core/urls.py').read()
new_routes = [
    "    path('retail/sales-history/', views.retail_sales_history, name='retail_sales_history'),",
    "    path('telecom/activity-history/', views.telecom_activity_history, name='telecom_activity_history'),",
]
added = 0
for route in new_routes:
    name = route.split("name='")[1].rstrip("'),")
    if name not in urls_code:
        urls_code = urls_code.rstrip().rstrip(']').rstrip() + '\n' + route + '\n]\n'
        added += 1
        print(f"✓ Added URL: {name}")
    else:
        print(f"✓ URL already exists: {name}")

open('/home/runner/workspace/core/urls.py', 'w').write(urls_code)

# ─── FIX 4: Add big_fix_views to views.py ───
if os.path.exists('/home/runner/workspace/big_fix_views.py'):
    fix_code = open('/home/runner/workspace/big_fix_views.py').read()
    views_code = open('/home/runner/workspace/core/views.py').read()

    # Remove old versions of functions we are replacing
    import re
    functions_to_replace = [
        'def record_retail_sale',
        'def record_multichoice_sale',
        'def staff_dashboard',
        'def customer_crm',
        'def commission_tracking',
        'def retail_dashboard',
        'def manager_dashboard',
    ]

    lines = views_code.split('\n')
    for fn_name in functions_to_replace:
        positions = [i for i, l in enumerate(lines) if fn_name + '(' in l and l.strip().startswith('def ')]
        if len(positions) > 1:
            # Remove all but last
            for pos in reversed(positions[:-1]):
                start = pos
                while start > 0 and (lines[start-1].strip().startswith('@') or lines[start-1].strip() == ''):
                    start -= 1
                end = pos + 1
                while end < len(lines):
                    if lines[end] and not lines[end].startswith(' ') and not lines[end].startswith('\t') and lines[end].strip() and end > pos + 3:
                        break
                    end += 1
                lines = lines[:start] + lines[end:]
                print(f"✓ Removed duplicate {fn_name}")

    views_code = '\n'.join(lines)
    open('/home/runner/workspace/core/views.py', 'w').write(views_code)

    # Append new fixed views
    with open('/home/runner/workspace/core/views.py', 'a') as f:
        f.write('\n\n' + fix_code)
    print("✓ Appended big_fix_views.py")
else:
    print("⚠ big_fix_views.py not found in workspace root - upload it first")

print("\n" + "=" * 50)
print("Running django check...")
os.system("python /home/runner/workspace/manage.py check")
