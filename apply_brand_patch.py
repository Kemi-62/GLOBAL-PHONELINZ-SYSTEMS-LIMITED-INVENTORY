"""
BRAND + DOMAIN SETTINGS PATCH
===============================
Run: python /home/runner/workspace/apply_brand_patch.py

This script:
1. Renames "GPSL ERP" to "GPSL Business Suite" everywhere in views.py
2. Updates settings.py with brand constants and domain settings
3. Updates base.html with logo, new brand name, favicon
4. Updates PDF generation to use new brand name
"""
import os
import re

WORKSPACE = '/home/runner/workspace'

print("=" * 60)
print("BRAND + DOMAIN PATCH")
print("=" * 60)

# ─── FIX 1: Update views.py - GPSL ERP -> GPSL Business Suite ───
print("\n--- FIX 1: Updating brand name in views.py ---")
views = open(f'{WORKSPACE}/core/views.py').read()
old_count = views.count('GPSL ERP')
views = views.replace('GPSL ERP', 'GPSL Business Suite')
views = views.replace('Global Phonelinz Systems Limited\nStaff Attendance', 'GPSL Business Suite\nStaff Attendance')
open(f'{WORKSPACE}/core/views.py', 'w').write(views)
print(f"  Replaced {old_count} instances of 'GPSL ERP' in views.py")

# ─── FIX 2: Add brand constants to settings.py ───
print("\n--- FIX 2: Adding brand constants to settings.py ---")
settings = open(f'{WORKSPACE}/django_project/settings.py').read()

brand_block = '''
# ─── BRAND SETTINGS ───
SITE_NAME = "GPSL Business Suite"
SITE_URL = "https://app.globalphonelinz.com"
COMPANY_NAME = "Global Phonelinz Systems Limited"
COMPANY_TAGLINE = "Your Trusted Technology Partner"
COMPANY_EMAIL = "globalphonelinzsystems@gmail.com"
COMPANY_PHONE = "+234 XXX XXX XXXX"
COMPANY_WHATSAPP = "+234 XXX XXX XXXX"
COMPANY_ADDRESS = "Uyo, Akwa Ibom State, Nigeria"
'''

if 'SITE_NAME' not in settings:
    settings += brand_block
    open(f'{WORKSPACE}/django_project/settings.py', 'w').write(settings)
    print("  Brand constants added to settings.py")
else:
    print("  Brand constants already present")

# ─── FIX 3: Update ALLOWED_HOSTS logic for custom domain ───
print("\n--- FIX 3: Updating ALLOWED_HOSTS for custom domain ---")
settings = open(f'{WORKSPACE}/django_project/settings.py').read()

old_hosts = """if IS_RENDER:
    render_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '')
    ALLOWED_HOSTS = [render_host] if render_host else ['*']
elif IS_REPLIT:
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())"""

new_hosts = """if IS_RENDER:
    render_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '')
    custom_hosts = config('ALLOWED_HOSTS', default='', cast=Csv())
    base_hosts = [render_host] if render_host else []
    ALLOWED_HOSTS = list(set(base_hosts + list(custom_hosts) + [
        'globalphonelinz.com',
        'www.globalphonelinz.com',
        'app.globalphonelinz.com',
    ])) if render_host or custom_hosts else ['*']
elif IS_REPLIT:
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())"""

old_csrf = """if IS_RENDER:
    render_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    if render_host:
        _default_csrf.append(f'https://{render_host}')"""

new_csrf = """if IS_RENDER:
    render_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    if render_host:
        _default_csrf.append(f'https://{render_host}')
    _default_csrf.extend([
        'https://globalphonelinz.com',
        'https://www.globalphonelinz.com',
        'https://app.globalphonelinz.com',
    ])"""

if old_hosts in settings:
    settings = settings.replace(old_hosts, new_hosts)
    print("  ALLOWED_HOSTS updated for custom domain")
else:
    print("  ALLOWED_HOSTS pattern not found - update manually")

if old_csrf in settings:
    settings = settings.replace(old_csrf, new_csrf)
    print("  CSRF_TRUSTED_ORIGINS updated for custom domain")
else:
    print("  CSRF pattern not found - update manually")

open(f'{WORKSPACE}/django_project/settings.py', 'w').write(settings)

# ─── FIX 4: Update base.html - logo, brand name, favicon ───
print("\n--- FIX 4: Updating base.html ---")
base = open(f'{WORKSPACE}/templates/base.html').read()

# Update title tag
if '<title>GPSL ERP</title>' in base:
    base = base.replace('<title>GPSL ERP</title>', '<title>GPSL Business Suite</title>')
    print("  Title updated")
elif 'GPSL ERP' in base[:500]:
    base = base.replace('GPSL ERP', 'GPSL Business Suite', 1)
    print("  Title updated (first occurrence)")

# Update all remaining GPSL ERP text
count = base.count('GPSL ERP')
base = base.replace('GPSL ERP', 'GPSL Business Suite')
print(f"  Replaced {count} more 'GPSL ERP' references")

# Add favicon if not present
if 'favicon' not in base:
    old_meta = '<meta name="viewport"'
    new_meta = '''<link rel="icon" type="image/png" href="/static/img/favicon.ico">
  <link rel="apple-touch-icon" href="/static/img/apple-touch-icon.png">
  <meta name="viewport"'''
    if old_meta in base:
        base = base.replace(old_meta, new_meta)
        print("  Favicon tags added")

# Update logo in sidebar if it shows text only
if 'gpsl_logo' not in base and 'sidebar-logo' not in base:
    # Find the sidebar brand area and add logo
    old_brand = '''<div class="sidebar-brand">'''
    new_brand = '''<div class="sidebar-brand">
      <img src="/static/img/gpsl_logo.png" alt="GPSL" style="width:36px;height:36px;border-radius:50%;background:#fff;padding:3px;object-fit:contain;margin-right:.5rem;vertical-align:middle;">'''
    if old_brand in base:
        base = base.replace(old_brand, new_brand, 1)
        print("  Logo added to sidebar")

# Update manifest name
base = base.replace('"GPSL ERP"', '"GPSL Business Suite"')

open(f'{WORKSPACE}/templates/base.html', 'w').write(base)
print("  base.html updated")

# ─── FIX 5: Copy logo and icons to static folder ───
print("\n--- FIX 5: Setting up static assets ---")
import shutil

static_img = f'{WORKSPACE}/static/img'
static_icons = f'{WORKSPACE}/static/icons'
os.makedirs(static_img, exist_ok=True)
os.makedirs(static_icons, exist_ok=True)

# Copy logo
logo_src = f'{WORKSPACE}/gpsl_logo.png'
if os.path.exists(logo_src):
    shutil.copy(logo_src, f'{static_img}/gpsl_logo.png')
    print("  Logo copied to static/img/gpsl_logo.png")
else:
    print("  WARNING: gpsl_logo.png not in workspace root - upload it first")

# Copy favicon
fav_src = f'{WORKSPACE}/favicon.ico'
if os.path.exists(fav_src):
    shutil.copy(fav_src, f'{static_img}/favicon.ico')
    print("  Favicon copied to static/img/favicon.ico")

# Copy apple touch icon
touch_src = f'{WORKSPACE}/apple-touch-icon.png'
if os.path.exists(touch_src):
    shutil.copy(touch_src, f'{static_img}/apple-touch-icon.png')
    print("  Apple touch icon copied")

# Copy PWA icons
for size in [72, 96, 128, 144, 152, 192, 384, 512]:
    icon_src = f'{WORKSPACE}/icon-{size}.png'
    if os.path.exists(icon_src):
        shutil.copy(icon_src, f'{static_icons}/icon-{size}.png')
print("  PWA icons copied to static/icons/")

# ─── FIX 6: Update manifest.json brand name ───
print("\n--- FIX 6: Updating manifest.json ---")
manifest_path = f'{WORKSPACE}/static/manifest.json'
if os.path.exists(manifest_path):
    import json
    manifest = json.load(open(manifest_path))
    manifest['name'] = 'GPSL Business Suite'
    manifest['short_name'] = 'GPSL'
    manifest['description'] = 'Global Phonelinz Systems Limited Business Suite'
    manifest['start_url'] = '/'
    json.dump(manifest, open(manifest_path, 'w'), indent=2)
    print("  manifest.json updated")
else:
    # Create manifest.json
    manifest = {
        "name": "GPSL Business Suite",
        "short_name": "GPSL",
        "description": "Global Phonelinz Systems Limited Business Suite",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#004F9F",
        "theme_color": "#004F9F",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"}
        ]
    }
    os.makedirs(f'{WORKSPACE}/static', exist_ok=True)
    json.dump(manifest, open(manifest_path, 'w'), indent=2)
    print("  manifest.json created")

# ─── FIX 7: Move landing page index.html to correct location ───
print("\n--- FIX 7: Landing page setup ---")
landing_src = f'{WORKSPACE}/index.html'
if os.path.exists(landing_src):
    # Create a templates version for Django to serve
    landing_tmpl = f'{WORKSPACE}/templates/landing.html'
    shutil.copy(landing_src, landing_tmpl)
    print("  Landing page copied to templates/landing.html")
    print("  NOTE: Add this URL to urls.py:")
    print("    path('', views.landing_page, name='landing_page'),")
    print("  And this view to views.py:")
    print("    def landing_page(request):")
    print("        return render(request, 'landing.html')")
else:
    print("  index.html not found in workspace root - upload it first")

print("\n" + "=" * 60)
print("BRAND PATCH COMPLETE")
print("=" * 60)
print("\nNext steps:")
print("1. Upload these files to Replit root:")
print("   - gpsl_logo.png")
print("   - favicon.ico")
print("   - apple-touch-icon.png")
print("   - icon-72.png through icon-512.png")
print("   - index.html")
print("   - login.html")
print("")
print("2. Run: python manage.py check")
print("3. Run: python manage.py collectstatic --no-input")
print("4. Update login.html template location:")
print("   cp /home/runner/workspace/login.html /home/runner/workspace/templates/login.html")
print("")
print("5. In Render environment variables, add/update:")
print("   ALLOWED_HOSTS=app.globalphonelinz.com,globalphonelinz.com,www.globalphonelinz.com")
print("   CSRF_TRUSTED_ORIGINS=https://app.globalphonelinz.com,https://globalphonelinz.com")
print("")
print("6. In Render dashboard -> Settings -> Custom Domains:")
print("   Add: app.globalphonelinz.com")
print("   Add the CNAME record to your domain registrar DNS")
print("")
print("7. For globalphonelinz.com landing page:")
print("   Deploy index.html as a separate static site on Netlify (free)")
print("   or Render Static Site pointing to root domain")
print("")
print("8. git add . && git commit -m 'Brand update: GPSL Business Suite, logo, domain' && git push")
