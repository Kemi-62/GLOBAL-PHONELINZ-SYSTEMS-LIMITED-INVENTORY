"""
Apply catalog + slideshow to your ERP
Run: python /home/runner/workspace/apply_catalog.py
"""
import os
import re

W = '/home/runner/workspace'

print("=" * 55)
print("CATALOG + SLIDESHOW SETUP")
print("=" * 55)

# 1. Add models to models.py
print("\n--- Adding models ---")
models_code = open(f'{W}/core/models.py').read()
if 'SlideShowItem' not in models_code:
    addition = open(f'{W}/catalog_models.py').read()
    with open(f'{W}/core/models.py','a') as f:
        f.write('\n\n' + addition)
    print("  SlideShowItem, CatalogCategory, CatalogProduct added")
else:
    print("  Models already exist")

# 2. Add views to views.py
print("\n--- Adding views ---")
views_code = open(f'{W}/core/views.py').read()
if 'catalog_management' not in views_code:
    # Read the views from the admin file
    admin_content = open(f'{W}/catalog_views_admin.py').read()
    # Extract just the VIEWS_CODE part
    start = admin_content.find("VIEWS_CODE = '''") + len("VIEWS_CODE = '''")
    end   = admin_content.rfind("'''")
    views_addition = admin_content[start:end]
    with open(f'{W}/core/views.py','a') as f:
        f.write('\n\n' + views_addition)
    print("  Catalog views added")
else:
    print("  Views already exist")

# 3. Add admin registrations
print("\n--- Adding admin registrations ---")
admin_path = f'{W}/core/admin.py'
admin_code = open(admin_path).read() if os.path.exists(admin_path) else 'from django.contrib import admin\n'
if 'SlideShowItem' not in admin_code:
    admin_content = open(f'{W}/catalog_views_admin.py').read()
    start = admin_content.find("ADMIN_CODE = '''") + len("ADMIN_CODE = '''")
    end   = admin_content.find("'''", start)
    admin_addition = admin_content[start:end]
    with open(admin_path,'a') as f:
        f.write('\n\n' + admin_addition)
    print("  Admin registrations added")
else:
    print("  Admin already registered")

# 4. Add URLs
print("\n--- Adding URLs ---")
urls_code = open(f'{W}/core/urls.py').read()
routes = [
    ("catalog/",                      "views.catalog_management",    "catalog_management"),
    ("catalog/slide/add/",            "views.catalog_add_slide",     "catalog_add_slide"),
    ("catalog/slide/<int:slide_id>/edit/",   "views.catalog_edit_slide",    "catalog_edit_slide"),
    ("catalog/slide/<int:slide_id>/delete/", "views.catalog_delete_slide",  "catalog_delete_slide"),
    ("catalog/product/add/",          "views.catalog_add_product",   "catalog_add_product"),
    ("catalog/product/<int:product_id>/edit/",   "views.catalog_edit_product",  "catalog_edit_product"),
    ("catalog/product/<int:product_id>/delete/", "views.catalog_delete_product","catalog_delete_product"),
    ("catalog/category/add/",         "views.catalog_add_category",  "catalog_add_category"),
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
open(f'{W}/core/urls.py','w').write(urls_code)
print(f"  {added} URLs added")

# 5. Copy templates
print("\n--- Copying templates ---")
import shutil
os.makedirs(f'{W}/templates/director', exist_ok=True)

# catalog_management.html
src = f'{W}/catalog_management.html'
if os.path.exists(src):
    shutil.copy(src, f'{W}/templates/director/catalog_management.html')
    print("  catalog_management.html -> templates/director/")

# landing.html
src2 = f'{W}/landing_final.html'
if os.path.exists(src2):
    shutil.copy(src2, f'{W}/templates/landing.html')
    print("  landing_final.html -> templates/landing.html")
else:
    print("  WARNING: landing_final.html not in root")

# 6. Add catalog link to director sidebar in base.html
print("\n--- Adding catalog link to director sidebar ---")
base = open(f'{W}/templates/base.html').read()
if 'catalog_management' not in base:
    base = base.replace(
        "{% url 'manage_price_floors' %}",
        "{% url 'manage_price_floors' %}"
    )
    # Find commission tracking link in director sidebar and add after
    old_link = "{% url 'commission_tracking' %}"
    if old_link in base:
        idx = base.find(old_link)
        end = base.find('</a>', idx) + 4
        insert = '\n            <a href="{% url \'catalog_management\' %}" class="sidebar-link">\n                <span class="icon">🛍️</span> Catalog Management\n            </a>'
        base = base[:end] + insert + base[end:]
        open(f'{W}/templates/base.html','w').write(base)
        print("  Catalog link added to director sidebar")
    else:
        print("  Could not find sidebar anchor - add manually")
else:
    print("  Already in sidebar")

print("\n" + "=" * 55)
print("DONE. Now run:")
print("  python manage.py makemigrations")
print("  python manage.py migrate")
print("  python manage.py check")
print("  python manage.py runserver 0.0.0.0:8000")
print("\nThen push:")
print("  git add . && git commit -m 'Add catalog, slideshow, product management' && git push")
