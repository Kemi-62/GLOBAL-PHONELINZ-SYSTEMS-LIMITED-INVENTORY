"""
MASTER FIX SCRIPT
=================
Run: python /home/runner/workspace/master_fix_all.py

Fixes:
1. Removes old broken manager_dashboard (line 264)
2. Adds offline_page and pwa_manifest views
3. Adds URLs for offline, manifest, keepalive, daily summary
4. Fixes attendance widget CSRF issue
"""
import os
import re

WORKSPACE = '/home/runner/workspace'
VIEWS = f'{WORKSPACE}/core/views.py'
URLS  = f'{WORKSPACE}/core/urls.py'
WIDGET = f'{WORKSPACE}/templates/partials/attendance_widget.html'

# ─── FIX 1: Remove ALL duplicate manager_dashboard definitions except the last ───
print("=== FIX 1: Removing duplicate manager_dashboard ===")
code = open(VIEWS).read()
lines = code.split('\n')

fn_name = 'def manager_dashboard(request):'
positions = [i for i,l in enumerate(lines) if fn_name in l and l.strip().startswith('def ')]
print(f"Found manager_dashboard at lines: {[p+1 for p in positions]}")

if len(positions) > 1:
    for pos in reversed(positions[:-1]):
        # Find decorator start
        start = pos
        while start > 0 and (lines[start-1].strip().startswith('@') or lines[start-1].strip() == ''):
            start -= 1
        # Find end (next top-level def or class)
        end = pos + 1
        while end < len(lines):
            l = lines[end]
            if l and not l.startswith(' ') and not l.startswith('\t') and l.strip() and end > pos + 3:
                break
            end += 1
        print(f"Removing duplicate at lines {start+1}-{end}")
        lines = lines[:start] + lines[end:]
        # Recalculate after removal
        positions = [i for i,l in enumerate(lines) if fn_name in l and l.strip().startswith('def ')]

code = '\n'.join(lines)

# Also remove duplicate check_in, check_out keeping only the last
for fn in ['def check_in(request):', 'def check_out(request):']:
    lines = code.split('\n')
    positions = [i for i,l in enumerate(lines) if fn in l and l.strip().startswith('def ')]
    if len(positions) > 1:
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
            lines = lines[:start] + lines[end:]
        code = '\n'.join(lines)
        print(f"Removed duplicate {fn}")

open(VIEWS, 'w').write(code)
print("Duplicates removed")

# ─── FIX 2: Add missing views ───
print("\n=== FIX 2: Adding missing views ===")
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


def daily_summary_trigger(request):
    """Triggered by cron-job.org daily at 8pm to email director summary."""
    from django.http import JsonResponse as _JR
    from decouple import config as _cfg
    secret = request.GET.get("key", "")
    expected = _cfg("BACKUP_SECRET_KEY", default="")
    if expected and secret != expected:
        return _JR({"error": "unauthorized"}, status=403)
    try:
        result = send_daily_summary_email()
        return _JR(result)
    except Exception as e:
        return _JR({"status": "error", "detail": str(e)})
'''

if 'def offline_page' not in code:
    code += new_views
    open(VIEWS, 'w').write(code)
    print("Added offline_page, pwa_manifest, keepalive_ping, daily_summary_trigger")
else:
    print("Views already exist")

# ─── FIX 3: Add missing URLs ───
print("\n=== FIX 3: Adding missing URLs ===")
urls_code = open(URLS).read()
routes = [
    ("system/keepalive/",     "views.keepalive_ping",       "keepalive_ping"),
    ("system/daily-summary/", "views.daily_summary_trigger","daily_summary_trigger"),
    ("offline/",              "views.offline_page",          "offline_page"),
    ("manifest.json",         "views.pwa_manifest",          "pwa_manifest"),
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
open(URLS, 'w').write(urls_code)
print(f"URLs: {added} added")

# ─── FIX 4: Fix attendance widget CSRF ───
print("\n=== FIX 4: Fixing attendance widget CSRF ===")
widget = open(WIDGET).read()

old_fetch = """fetch(form.action, {
    method: 'POST',
    body: data,
    headers: { 'X-Requested-With': 'XMLHttpRequest' }
  })"""

new_fetch = """function getCsrf() {
    let v = document.cookie.match('(^|;) ?csrftoken=([^;]*)(;|$)');
    return v ? v[2] : '';
  }
  fetch(form.action, {
    method: 'POST',
    body: data,
    headers: {
      'X-Requested-With': 'XMLHttpRequest',
      'X-CSRFToken': getCsrf()
    },
    credentials: 'same-origin'
  })"""

if old_fetch in widget:
    widget = widget.replace(old_fetch, new_fetch)
    open(WIDGET, 'w').write(widget)
    print("CSRF fix applied to attendance widget")
else:
    # Try to find the fetch call and patch it
    if 'X-CSRFToken' not in widget:
        widget = widget.replace(
            "headers: { 'X-Requested-With': 'XMLHttpRequest' }",
            "headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': (document.cookie.match('(^|;) ?csrftoken=([^;]*)')||[])[2]||'' }, credentials: 'same-origin'"
        )
        open(WIDGET, 'w').write(widget)
        print("CSRF fix applied (alternative method)")
    else:
        print("CSRF already fixed")

# ─── FIX 5: Create offline.html if missing ───
print("\n=== FIX 5: Creating offline.html ===")
offline_path = f'{WORKSPACE}/templates/offline.html'
if not os.path.exists(offline_path):
    offline_content = '''{% extends "base.html" %}
{% block content %}
<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:60vh;text-align:center;padding:2rem;">
  <div style="font-size:4rem;margin-bottom:1rem;">📵</div>
  <h1 style="font-size:1.5rem;font-weight:700;color:#004F9F;margin:0 0 .8rem;">You are offline</h1>
  <p style="color:#6b7280;max-width:320px;line-height:1.6;margin:0 0 1.5rem;">No internet connection. Please check your network and try again.</p>
  <button onclick="window.location.reload()" style="padding:.7rem 1.5rem;background:#004F9F;color:#fff;border:none;border-radius:8px;font-weight:600;cursor:pointer;">Try Again</button>
  <p style="font-size:.78rem;color:#9ca3af;margin-top:1rem;">GPSL ERP — Global Phonelinz Systems Ltd</p>
</div>
{% endblock %}'''
    open(offline_path, 'w').write(offline_content)
    print("offline.html created")
else:
    print("offline.html already exists")

# ─── FIX 6: Create generate_icons.py ───
print("\n=== FIX 6: Creating generate_icons.py ===")
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
open(f'{WORKSPACE}/generate_icons.py', 'w').write(icons_script)
print("generate_icons.py created")

print("\n=== ALL FIXES APPLIED ===")
print("Now run: python manage.py check")
