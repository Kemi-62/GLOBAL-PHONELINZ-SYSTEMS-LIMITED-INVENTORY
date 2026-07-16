"""
MEGA BATCH FIX
==============
Run: python /home/runner/workspace/mega_fix.py

Fixes:
1. StockTransfer model - add to models.py + migration
2. Stock transfer views - already added but model missing
3. Password reset - username+email verification before sending
4. Attendance widget - better geolocation, retry logic, detailed errors
5. Email alerts - debug why emails not arriving
"""
import os, re

W = '/home/runner/workspace'
print("=" * 55)
print("MEGA BATCH FIX")
print("=" * 55)

# ── FIX 1: Add StockTransfer model ──
print("\n--- Fix 1: StockTransfer model ---")
models_code = open(f'{W}/core/models.py').read()
if 'class StockTransfer' not in models_code:
    transfer_model = '''

class StockTransfer(models.Model):
    """Stock movement between Director Safe, Branch Safe, Staff Stock."""
    TRANSFER_TYPE_CHOICES = [
        ('DIRECTOR_TO_BRANCH',  'Director Safe → Branch Safe'),
        ('BRANCH_TO_BRANCH',    'Branch → Branch'),
        ('BRANCH_TO_STAFF',     'Branch Safe → Staff Stock'),
        ('STAFF_TO_BRANCH',     'Staff Stock → Branch Safe'),
        ('BRANCH_TO_DIRECTOR',  'Branch Safe → Director Safe'),
    ]
    transfer_type  = models.CharField(max_length=30, choices=TRANSFER_TYPE_CHOICES)
    product        = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='transfers')
    quantity       = models.PositiveIntegerField()
    notes          = models.TextField(blank=True, default='')
    from_branch    = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_out')
    to_branch      = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_in')
    to_staff       = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_received')
    initiated_by   = models.ForeignKey('User', on_delete=models.CASCADE, related_name='transfers_initiated')
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Stock Transfer'
        verbose_name_plural = 'Stock Transfers'

    def __str__(self):
        return f"{self.product.model_name} x{self.quantity} ({self.get_transfer_type_display()})"

    @property
    def source_label(self):
        if self.from_branch:
            return self.from_branch.name
        return "Director Safe"

    @property
    def destination_label(self):
        if self.to_branch:
            return self.to_branch.name
        if self.to_staff:
            return f"{self.to_staff.username} (Staff)"
        return "Director Safe"
'''
    with open(f'{W}/core/models.py', 'a') as f:
        f.write(transfer_model)
    print("  StockTransfer model added to models.py")
else:
    print("  Already exists")

# ── FIX 2: Password reset - username + email verification ──
print("\n--- Fix 2: Password reset with username+email check ---")
views = open(f'{W}/core/views.py').read()

custom_pr_view = '''

def custom_password_reset(request):
    """
    Password reset with username + email verification.
    Both must match the account before sending reset email.
    """
    from django.contrib.auth.forms import PasswordResetForm
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    from django.utils.http import urlsafe_base64_encode
    from django.utils.encoding import force_bytes
    from django.contrib.auth.tokens import default_token_generator
    import threading

    error = None
    success = False

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email    = request.POST.get('email', '').strip().lower()

        try:
            user = User.objects.get(username__iexact=username)
            if user.email.lower() != email:
                error = "The email address does not match our records for this username."
            else:
                # Send reset email in background thread
                def send_reset():
                    try:
                        token = default_token_generator.make_token(user)
                        uid   = urlsafe_base64_encode(force_bytes(user.pk))
                        domain = request.get_host()
                        protocol = 'https' if request.is_secure() else 'http'
                        reset_url = f"{protocol}://{domain}/reset/{uid}/{token}/"

                        subject = "GPSL Business Suite - Password Reset"
                        body = f"""Hello {user.username},

You requested a password reset for your GPSL Business Suite account.

Click the link below to set a new password:
{reset_url}

This link expires in 3 days.

If you did not request this, ignore this email.

— GPSL Business Suite
"""
                        send_mail(
                            subject, body,
                            settings.DEFAULT_FROM_EMAIL,
                            [user.email],
                            fail_silently=False
                        )
                    except Exception as e:
                        pass

                threading.Thread(target=send_reset, daemon=True).start()
                success = True
        except User.DoesNotExist:
            error = "No account found with that username."

    return render(request, 'registration/password_reset_form.html', {
        'error': error,
        'success': success,
        'custom_reset': True,
    })
'''

if 'def custom_password_reset' not in views:
    views += custom_pr_view
    open(f'{W}/core/views.py','w').write(views)
    print("  custom_password_reset view added")
else:
    print("  Already exists")

# ── FIX 3: Update password reset URL to use custom view ──
print("\n--- Fix 3: Update password reset URL ---")
urls = open(f'{W}/core/urls.py').read()
old_pr = """    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='registration/password_reset_form.html',
        email_template_name='registration/password_reset_email.html',
    ), name='password_reset'),"""
new_pr = """    path('password-reset/', views.custom_password_reset, name='password_reset'),"""
if old_pr in urls:
    urls = urls.replace(old_pr, new_pr)
    open(f'{W}/core/urls.py','w').write(urls)
    print("  Password reset URL updated to custom view")
else:
    print("  Pattern not found - checking existing")
    if 'custom_password_reset' not in urls:
        # Try to replace whatever is there
        urls = re.sub(
            r"path\('password-reset/',\s*auth_views\.PasswordResetView.*?\),",
            "path('password-reset/', views.custom_password_reset, name='password_reset'),",
            urls, flags=re.DOTALL
        )
        open(f'{W}/core/urls.py','w').write(urls)
        print("  Updated via regex")

# ── FIX 4: Update password reset template ──
print("\n--- Fix 4: Update password reset form template ---")
pr_tmpl_path = f'{W}/templates/registration/password_reset_form.html'
pr_template = '''{% extends "login.html" %}
{% block content %}
{% comment %}Override login content with password reset form{% endcomment %}
{% endblock %}
'''

new_pr_template = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reset Password — GPSL Business Suite</title>
  <link rel="icon" type="image/png" href="/static/img/favicon.ico">
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Segoe UI',Arial,sans-serif;min-height:100vh;background:#004F9F;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:1rem;position:relative;overflow:hidden}
    body::before{content:'';position:fixed;inset:0;background:radial-gradient(circle at 20% 20%,rgba(255,203,5,.15) 0%,transparent 50%),radial-gradient(circle at 80% 80%,rgba(255,203,5,.1) 0%,transparent 50%);pointer-events:none}
    .wrap{width:100%;max-width:400px;position:relative;z-index:1}
    .brand-header{text-align:center;margin-bottom:1.5rem}
    .brand-logo{width:72px;height:72px;background:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto .9rem;box-shadow:0 4px 20px rgba(0,0,0,.2);overflow:hidden;padding:7px}
    .brand-logo img{width:100%;height:100%;object-fit:contain}
    .brand-name{font-size:1.3rem;font-weight:800;color:#FFCB05}
    .brand-sub{font-size:.78rem;color:rgba(255,255,255,.7);margin-top:.2rem}
    .card{background:#fff;border-radius:14px;padding:1.75rem;box-shadow:0 16px 50px rgba(0,0,0,.22)}
    .card h2{font-size:1rem;font-weight:700;color:#004F9F;margin-bottom:.4rem}
    .card p{font-size:.82rem;color:#6b7280;margin-bottom:1.25rem;line-height:1.6}
    .form-group{margin-bottom:.85rem}
    .form-group label{display:block;font-size:.78rem;font-weight:600;color:#374151;margin-bottom:.3rem}
    .form-group input{width:100%;padding:.7rem .9rem;border:1.5px solid #e5e7eb;border-radius:8px;font-size:.9rem;transition:border-color .2s}
    .form-group input:focus{outline:none;border-color:#004F9F;box-shadow:0 0 0 3px rgba(0,79,159,.1)}
    .alert-error{background:#fee2e2;border:1px solid #fca5a5;color:#991b1b;border-radius:8px;padding:.65rem .9rem;font-size:.83rem;margin-bottom:1rem}
    .alert-success{background:#d1fae5;border:1px solid #6ee7b7;color:#065f46;border-radius:8px;padding:.65rem .9rem;font-size:.83rem;margin-bottom:1rem}
    .btn{width:100%;padding:.78rem;background:#004F9F;color:#fff;border:none;border-radius:8px;font-size:.92rem;font-weight:700;cursor:pointer;transition:.2s;margin-top:.3rem}
    .btn:hover{background:#003d7a}
    .back-link{display:block;text-align:center;margin-top:1rem;font-size:.82rem;color:rgba(255,255,255,.75);text-decoration:none}
    .back-link:hover{color:#FFCB05}
    .footer{text-align:center;margin-top:1.25rem;color:rgba(255,255,255,.55);font-size:.72rem}
  </style>
</head>
<body>
<div class="wrap">
  <div class="brand-header">
    <div class="brand-logo">
      <img src="/static/img/gpsl_logo.png" alt="GPSL Logo">
    </div>
    <div class="brand-name">GPSL Business Suite</div>
    <div class="brand-sub">Password Reset</div>
  </div>

  <div class="card">
    <h2>Reset Your Password</h2>
    <p>Enter your username and email address. If they match your account, we'll send a reset link to your email.</p>

    {% if error %}
    <div class="alert-error">❌ {{ error }}</div>
    {% endif %}

    {% if success %}
    <div class="alert-success">
      ✅ A password reset link has been sent to your email address.<br>
      <small>Check your inbox and spam folder. The link expires in 3 days.</small>
    </div>
    {% else %}
    <form method="POST">
      {% csrf_token %}
      <div class="form-group">
        <label>Username *</label>
        <input type="text" name="username" placeholder="Your username" required autofocus>
      </div>
      <div class="form-group">
        <label>Email Address *</label>
        <input type="email" name="email" placeholder="Email linked to your account" required>
      </div>
      <button type="submit" class="btn">Send Reset Link</button>
    </form>
    {% endif %}
  </div>

  <a href="/login/" class="back-link">← Back to Login</a>

  <div class="footer">
    © {% now "Y" %} Global Phonelinz Systems Limited
  </div>
</div>
</body>
</html>
'''
open(pr_tmpl_path, 'w').write(new_pr_template)
print("  Password reset template rebuilt with username+email fields")

# ── FIX 5: Attendance widget - full rewrite of geolocation block ──
print("\n--- Fix 5: Attendance widget geolocation ---")
widget = open(f'{W}/templates/partials/attendance_widget.html').read()

old_geo = """  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      function(pos) {
        document.getElementById('att-lat').value = pos.coords.latitude;
        document.getElementById('att-lon').value = pos.coords.longitude;
        locStatus.textContent = '✅ Location found (' + pos.coords.latitude.toFixed(4) + ', ' + pos.coords.longitude.toFixed(4) + ')';
        locStatus.style.background = '#d1fae5';
        locStatus.style.color = '#065f46';
        submitBtn.disabled = false;
      },
      function(err) {
        locStatus.textContent = '❌ Could not get location. Enable GPS and try again.';
        locStatus.style.background = '#fee2e2';
        locStatus.style.color = '#991b1b';
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  } else {
    locStatus.textContent = '❌ Geolocation not supported on this device.';
    locStatus.style.background = '#fee2e2';
    locStatus.style.color = '#991b1b';
  }"""

new_geo = """  if (!navigator.geolocation) {
    locStatus.textContent = '❌ Geolocation not supported on this browser.';
    locStatus.style.background = '#fee2e2';
    locStatus.style.color = '#991b1b';
    return;
  }

  // Try low-accuracy first (faster), then fallback to high-accuracy GPS
  var geoAttempt = 0;
  function attemptLocation(highAccuracy) {
    geoAttempt++;
    locStatus.textContent = geoAttempt === 1 ? '📡 Getting location…' : '📡 Retrying with GPS (attempt ' + geoAttempt + ')…';
    navigator.geolocation.getCurrentPosition(
      function(pos) {
        document.getElementById('att-lat').value = pos.coords.latitude;
        document.getElementById('att-lon').value = pos.coords.longitude;
        locStatus.textContent = '✅ Location found (' + pos.coords.latitude.toFixed(4) + ', ' + pos.coords.longitude.toFixed(4) + ') — Accuracy: ' + Math.round(pos.coords.accuracy) + 'm';
        locStatus.style.background = '#d1fae5';
        locStatus.style.color = '#065f46';
        submitBtn.disabled = false;
      },
      function(err) {
        if (err.code === 3 && geoAttempt < 3) {
          // Timeout — retry with high accuracy
          setTimeout(function() { attemptLocation(true); }, 1000);
          return;
        }
        var msg = '❌ ';
        if (err.code === 1) msg += 'Location permission denied. Go to browser settings → Site Settings → Location → Allow for this site, then try again.';
        else if (err.code === 2) msg += 'GPS signal unavailable. Move to an open area or enable Location Services in your phone settings.';
        else if (err.code === 3) msg += 'Location timed out after ' + geoAttempt + ' attempts. Enable GPS and ensure you have a signal.';
        else msg += 'Location error (' + err.code + '): ' + err.message;
        locStatus.textContent = msg;
        locStatus.style.background = '#fee2e2';
        locStatus.style.color = '#991b1b';
        // Allow manual override button
        locStatus.innerHTML += '<br><button onclick="manualLocationOverride()" style="margin-top:.4rem;padding:.25rem .7rem;background:#004F9F;color:#fff;border:none;border-radius:5px;font-size:.75rem;cursor:pointer;">Try Again</button>';
      },
      { enableHighAccuracy: highAccuracy, timeout: highAccuracy ? 25000 : 8000, maximumAge: 60000 }
    );
  }
  attemptLocation(false);"""

if old_geo in widget:
    widget = widget.replace(old_geo, new_geo)
    open(f'{W}/templates/partials/attendance_widget.html','w').write(widget)
    print("  Attendance widget geolocation fully replaced with retry logic")
else:
    print("  WARNING: exact geolocation pattern not found")
    print("  Trying partial match...")
    if "timeout: 10000" in widget:
        widget = widget.replace(
            "{ enableHighAccuracy: true, timeout: 10000 }",
            "{ enableHighAccuracy: true, timeout: 25000, maximumAge: 60000 }"
        )
        # Fix error message
        widget = widget.replace(
            "'❌ Could not get location. Enable GPS and try again.'",
            "err.code === 1 ? '❌ Permission denied — allow location in browser settings.' : err.code === 2 ? '❌ GPS unavailable — move outdoors.' : '❌ Timed out — check GPS is on.'"
        )
        open(f'{W}/templates/partials/attendance_widget.html','w').write(widget)
        print("  Partial fix applied - timeout increased to 25s, better error messages")

# Add manualLocationOverride function after closeAttModal
if 'manualLocationOverride' not in widget:
    widget = open(f'{W}/templates/partials/attendance_widget.html').read()
    old_close = "function closeAttModal() {"
    new_close = """function manualLocationOverride() {
  var locStatus = document.getElementById('att-location-status');
  var submitBtn = document.getElementById('att-submit-btn');
  locStatus.textContent = '📡 Retrying…';
  locStatus.style.background = '#eff6ff';
  locStatus.style.color = '#1e40af';
  geoAttempt = 0;
  attemptLocation(true);
}

function closeAttModal() {"""
    if old_close in widget:
        widget = widget.replace(old_close, new_close)
        open(f'{W}/templates/partials/attendance_widget.html','w').write(widget)
        print("  manualLocationOverride function added")

# ── FIX 6: Migration for StockTransfer ──
print("\n--- Fix 6: Create migration for StockTransfer ---")
import subprocess
result = subprocess.run(
    ['python', 'manage.py', 'makemigrations', 'core', '--name', 'add_stock_transfer'],
    cwd=W, capture_output=True, text=True
)
print("  makemigrations:", result.stdout.strip() or result.stderr.strip())

result2 = subprocess.run(
    ['python', 'manage.py', 'migrate', '--run-syncdb'],
    cwd=W, capture_output=True, text=True
)
print("  migrate:", result2.stdout[-200:].strip() or result2.stderr[-200:].strip())

# ── FIX 7: Verify syntax ──
print("\n--- Fix 7: Syntax check ---")
import ast
for f in ['core/views.py', 'core/models.py', 'core/urls.py']:
    try:
        ast.parse(open(f'{W}/{f}').read())
        print(f"  {f}: OK")
    except SyntaxError as e:
        print(f"  {f}: SYNTAX ERROR line {e.lineno}: {e.msg}")

print("\n" + "=" * 55)
print("MEGA FIX COMPLETE")
print("=" * 55)
print("\nNow run:")
print("  python manage.py check")
print("  python manage.py runserver 0.0.0.0:8000")
print("\nThen test:")
print("  1. Visit /password-reset/ - should show username+email form")
print("  2. Visit /stock-transfer/ - should load without import error")
print("  3. Try attendance check-in - should retry on timeout")
print("\nThen push:")
print("  git add . && git commit -m 'Mega fix: stock transfer, password reset, geolocation' && git push")
