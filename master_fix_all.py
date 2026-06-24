"""
MASTER FIX SCRIPT — for the pre-update GitHub export
=====================================================
Run: python /home/runner/workspace/master_fix_all.py

Fixes, in order:
1. Removes 14 duplicate view function definitions (keeps the LAST/working one each time)
2. Locks price server-side in record_retail_sale (removes price-override vulnerability)
3. Makes settings.py ssl_require conditional (prevents Helium/SQLite SSL crash)
4. Adds CSRF token to attendance_widget.html fetch (prevents check-in/out network error)
5. Adds offline_page, pwa_manifest, keepalive_ping views if missing
6. Adds matching URLs if missing
7. Fixes stock_alert_email.py reorder_threshold field error
8. Creates templates/offline.html and generate_icons.py if missing
"""
import os
import re

WORKSPACE = '/home/runner/workspace'
VIEWS    = f'{WORKSPACE}/core/views.py'
URLS     = f'{WORKSPACE}/core/urls.py'
SETTINGS = f'{WORKSPACE}/django_project/settings.py'
WIDGET   = f'{WORKSPACE}/templates/partials/attendance_widget.html'
STOCK_ALERT_CMD = f'{WORKSPACE}/core/management/commands/stock_alert_email.py'

DUPLICATE_FUNCTIONS = [
    'add_device_commission', 'add_director_stock', 'attendance_history',
    'commission_tracking', 'customer_crm', 'daily_sales_report',
    'manager_dashboard', 'manager_sales_today', 'multichoice_dashboard',
    'record_multichoice_sale', 'record_retail_sale', 'retail_dashboard',
    'staff_dashboard', 'stock_movement_log',
]

print("=" * 60)
print("MASTER FIX — Starting")
print("=" * 60)

# ─── FIX 1: Remove duplicate function definitions ───
print("\n--- FIX 1: Removing duplicate view functions ---")
code = open(VIEWS).read()
lines = code.split('\n')

for fn in DUPLICATE_FUNCTIONS:
    fn_marker = f'def {fn}(request):'
    positions = [i for i, l in enumerate(lines) if fn_marker in l and l.strip().startswith('def ')]
    if len(positions) > 1:
        print(f"  {fn}: found {len(positions)} definitions at lines {[p+1 for p in positions]}")
        for pos in reversed(positions[:-1]):
            start = pos
            while start > 0 and (lines[start-1].strip().startswith('@') or lines[start-1].strip() == ''):
                start -= 1
            end = pos + 1
            while end < len(lines):
                l = lines[end]
                if l and not l.startswith(' ') and not l.startswith('\t') and l.strip() and end > pos + 3:
                    break
                end += 1
            print(f"    removing lines {start+1}-{end}")
            lines = lines[:start] + lines[end:]
            positions = [i for i, l in enumerate(lines) if fn_marker in l and l.strip().startswith('def ')]
    else:
        print(f"  {fn}: OK (only 1 definition)")

code = '\n'.join(lines)
open(VIEWS, 'w').write(code)
print("Duplicates removed.")

# ─── FIX 2: Lock price in record_retail_sale ───
print("\n--- FIX 2: Locking price in record_retail_sale ---")
code = open(VIEWS).read()

old_block = '''def record_retail_sale(request):
    if request.method == "POST":
        product_id = request.POST.get("product")
        quantity = int(request.POST.get("quantity", 0))
        selling_price = Decimal(request.POST.get("selling_price", 0))
        payment_method = request.POST.get("payment_method", "CASH")

        product = get_object_or_404(Product, id=product_id)'''

new_block = '''def record_retail_sale(request):
    if request.method == "POST":
        product_id = request.POST.get("product")
        quantity = int(request.POST.get("quantity", 0))
        payment_method = request.POST.get("payment_method", "CASH")

        product = get_object_or_404(Product, id=product_id)
        # PRICE LOCK: always use the approved product price, ignore any form input
        selling_price = product.selling_price'''

if old_block in code:
    code = code.replace(old_block, new_block)
    open(VIEWS, 'w').write(code)
    print("  Price lock applied successfully.")
else:
    print("  WARNING: exact block not found (may already be fixed, or wording differs).")
    print("  Manually verify record_retail_sale uses product.selling_price, not request.POST price.")

# ─── FIX 3: Conditional SSL in settings.py ───
print("\n--- FIX 3: Fixing ssl_require in settings.py ---")
settings_code = open(SETTINGS).read()

old_ssl = "ssl_require=True,"
new_ssl = "ssl_require='supabase.com' in _db_url,"

if old_ssl in settings_code and "ssl_require='supabase.com'" not in settings_code:
    settings_code = settings_code.replace(old_ssl, new_ssl, 1)
    open(SETTINGS, 'w').write(settings_code)
    print("  ssl_require made conditional on Supabase host.")
else:
    print("  SKIPPED (already fixed or pattern not found - verify manually).")

# ─── FIX 4: CSRF token in attendance widget ───
print("\n--- FIX 4: Fixing attendance widget CSRF ---")
if os.path.exists(WIDGET):
    widget = open(WIDGET).read()
    if 'X-CSRFToken' not in widget:
        if "headers: { 'X-Requested-With': 'XMLHttpRequest' }" in widget:
            widget = widget.replace(
                "headers: { 'X-Requested-With': 'XMLHttpRequest' }",
                "headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': (document.cookie.match('(^|;) ?csrftoken=([^;]*)')||[])[2]||'' }, credentials: 'same-origin'"
            )
            open(WIDGET, 'w').write(widget)
            print("  CSRF header added to fetch call.")
        elif 'fetch(form.action' in widget and 'headers:' in widget:
            widget = widget.replace(
                "fetch(form.action, {",
                "fetch(form.action, {\n    credentials: 'same-origin',",
                1
            )
            widget = re.sub(
                r"headers:\s*\{([^}]*)\}",
                lambda m: "headers: {" + m.group(1) + ", 'X-CSRFToken': (document.cookie.match('(^|;) ?csrftoken=([^;]*)')||[])[2]||''}",
                widget,
                count=1
            )
            open(WIDGET, 'w').write(widget)
            print("  CSRF header inserted (generic method). VERIFY the widget still works.")
        else:
            print("  WARNING: could not auto-patch. Add X-CSRFToken header manually.")
    else:
        print("  Already has CSRF token. Skipped.")
else:
    print("  WARNING: attendance_widget.html not found at expected path.")

# ─── FIX 5: Add missing PWA/system views ───
print("\n--- FIX 5: Adding offline_page, pwa_manifest, keepalive_ping ---")
code = open(VIEWS).read()

new_views = '''

def offline_page(request):
    """PWA offline fallback page."""
    return render(request, "offline.html")


def pwa_manifest(request):
    """Serve PWA manifest.json."""
    import json as _json
    from django.http import HttpResponse as _HR
    manifest = {
        "name": "GPSL ERP",
        "short_name": "GPSL",
        "description": "Global Phonelinz Systems Limited",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#004F9F",
        "theme_color": "#004F9F",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"}
        ]
    }
    return _HR(_json.dumps(manifest), content_type="application/manifest+json")


def keepalive_ping(request):
    """Keep Render and Supabase awake. Ping from cron-job.org every 4 days."""
    from django.http import JsonResponse as _JR
    try:
        from django.db import connection as _conn
        with _conn.cursor() as c:
            c.execute("SELECT 1")
        return _JR({"status": "ok", "time": str(timezone.now())})
    except Exception as e:
        return _JR({"status": "error", "detail": str(e)}, status=500)
'''

if 'def offline_page' not in code:
    code += new_views
    open(VIEWS, 'w').write(code)
    print("  Added offline_page, pwa_manifest, keepalive_ping.")
else:
    print("  Already present. Skipped.")

# ─── FIX 6: Add matching URLs ───
print("\n--- FIX 6: Adding missing URLs ---")
urls_code = open(URLS).read()
routes = [
    ("system/keepalive/", "views.keepalive_ping", "keepalive_ping"),
    ("offline/",          "views.offline_page",    "offline_page"),
    ("manifest.json",     "views.pwa_manifest",     "pwa_manifest"),
]
for path, view, name in routes:
    if name not in urls_code:
        route_line = f"    path('{path}', {view}, name='{name}'),"
        urls_code = urls_code.rstrip().rstrip(']').rstrip() + '\n' + route_line + '\n]\n'
        print(f"  Added: {name}")
    else:
        print(f"  Already exists: {name}")
open(URLS, 'w').write(urls_code)

# ─── FIX 7: Fix stock_alert_email.py reorder_threshold field error ───
print("\n--- FIX 7: Fixing stock_alert_email.py field error ---")
if os.path.exists(STOCK_ALERT_CMD):
    cmd_code = open(STOCK_ALERT_CMD).read()
    if 'reorder_threshold' in cmd_code:
        fixed_cmd = '''"""Management command: send stock reorder alerts via email.

Usage: python manage.py stock_alert_email --email=director@company.com
"""
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.conf import settings
from core.models import BranchSafeStock

LOW_STOCK_THRESHOLD = 1


class Command(BaseCommand):
    help = "Send stock reorder alert emails to director."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Email address to send alerts to")

    def handle(self, *args, **options):
        email = options["email"]

        low_stock = BranchSafeStock.objects.filter(
            quantity__lte=LOW_STOCK_THRESHOLD
        ).select_related("product", "branch")

        if not low_stock.exists():
            self.stdout.write(self.style.SUCCESS("No stock alerts needed."))
            return

        lines = []
        for item in low_stock:
            status = "OUT OF STOCK" if item.quantity == 0 else "LOW STOCK"
            lines.append(
                f"  - [{status}] {item.product.model_name} @ {item.branch.name}: "
                f"{item.quantity} remaining"
            )

        lines_text = "\\n".join(lines)

        subject = "GPSL Stock Reorder Alert"
        body = f"""GPSL AUTOMATION - Stock Reorder Alert

The following items are at or below the reorder threshold ({LOW_STOCK_THRESHOLD} units):

{lines_text}

Please review and restock as needed.

- GPSL ERP System
"""
        try:
            msg = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [email])
            msg.send()
            self.stdout.write(self.style.SUCCESS(f"Stock alert sent to {email}"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to send stock alert: {e}"))
'''
        open(STOCK_ALERT_CMD, 'w').write(fixed_cmd)
        print("  Replaced with fixed-threshold version (no phantom field).")
    else:
        print("  Already fixed. Skipped.")
else:
    print("  WARNING: stock_alert_email.py not found at expected path.")

# ─── FIX 8: Create offline.html and generate_icons.py if missing ───
print("\n--- FIX 8: Creating offline.html and generate_icons.py ---")
offline_path = f'{WORKSPACE}/templates/offline.html'
if not os.path.exists(offline_path):
    offline_content = '''{% extends "base.html" %}
{% block content %}
<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:60vh;text-align:center;padding:2rem;">
  <div style="font-size:4rem;margin-bottom:1rem;">[offline]</div>
  <h1 style="font-size:1.5rem;font-weight:700;color:#004F9F;margin:0 0 .8rem;">You are offline</h1>
  <p style="color:#6b7280;max-width:320px;line-height:1.6;margin:0 0 1.5rem;">No internet connection. Please check your network and try again.</p>
  <button onclick="window.location.reload()" style="padding:.7rem 1.5rem;background:#004F9F;color:#fff;border:none;border-radius:8px;font-weight:600;cursor:pointer;">Try Again</button>
  <p style="font-size:.78rem;color:#9ca3af;margin-top:1rem;">GPSL ERP - Global Phonelinz Systems Ltd</p>
</div>
{% endblock %}'''
    open(offline_path, 'w').write(offline_content)
    print("  offline.html created.")
else:
    print("  Already exists. Skipped.")

icons_script_path = f'{WORKSPACE}/generate_icons.py'
if not os.path.exists(icons_script_path):
    icons_script = '''import os
from PIL import Image, ImageDraw, ImageFont
sizes = [72,96,128,144,152,192,384,512]
os.makedirs("static/icons", exist_ok=True)
for s in sizes:
    img = Image.new("RGB", (s,s), color="#004F9F")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", s//4)
    except:
        font = ImageFont.load_default()
    text = "GPSL"
    bbox = draw.textbbox((0,0), text, font=font)
    x = (s-(bbox[2]-bbox[0]))//2
    y = (s-(bbox[3]-bbox[1]))//2
    draw.text((x,y), text, fill="#FFCB05", font=font)
    img.save(f"static/icons/icon-{s}.png")
    print(f"icon-{s}.png created")
print("All icons done")
'''
    open(icons_script_path, 'w').write(icons_script)
    print("  generate_icons.py created.")
else:
    print("  Already exists. Skipped.")

print("\n" + "=" * 60)
print("MASTER FIX COMPLETE")
print("=" * 60)
print("\nNext steps:")
print("1. python manage.py check")
print("2. python generate_icons.py")
print("3. python manage.py test core")
print("4. git add . && git commit -m 'Master fix' && git push")
