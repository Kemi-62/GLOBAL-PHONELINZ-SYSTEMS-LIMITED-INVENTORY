"""
EMAIL FIX + DIAGNOSTIC ENDPOINT
=================================
Run: python /home/runner/workspace/fix_email.py

1. Adds /system/email-test/ endpoint to test SMTP from browser
2. Switches to port 465 SSL as fallback
3. Adds Brevo SMTP support via env vars
"""
W = '/home/runner/workspace'

# ── Add email test view ──
views = open(f'{W}/core/views.py').read()

if 'def email_diagnostic' not in views:
    diag_view = '''

def email_diagnostic(request):
    """
    Email diagnostic endpoint - hit this URL to test SMTP.
    Only accessible with BACKUP_SECRET_KEY.
    URL: /system/email-test/?key=gpsl2026backup&to=kemimonday00@gmail.com
    """
    from django.http import JsonResponse
    from django.core.mail import send_mail, get_connection
    from django.conf import settings as _s
    from decouple import config as _cfg
    import socket

    secret = request.GET.get('key','')
    if secret != _cfg('BACKUP_SECRET_KEY', default=''):
        return JsonResponse({'error': 'unauthorized'}, status=403)

    to_email = request.GET.get('to', _s.DEFAULT_FROM_EMAIL)
    results = {}

    # Check settings
    results['EMAIL_HOST']     = _s.EMAIL_HOST
    results['EMAIL_PORT']     = _s.EMAIL_PORT
    results['EMAIL_USE_TLS']  = getattr(_s, 'EMAIL_USE_TLS', False)
    results['EMAIL_USE_SSL']  = getattr(_s, 'EMAIL_USE_SSL', False)
    results['EMAIL_HOST_USER'] = _s.EMAIL_HOST_USER
    results['DEFAULT_FROM_EMAIL'] = _s.DEFAULT_FROM_EMAIL
    results['EMAIL_TIMEOUT']  = getattr(_s, 'EMAIL_TIMEOUT', 'NOT SET')
    results['PASSWORD_SET']   = bool(_s.EMAIL_HOST_PASSWORD)

    # Test TCP connection to SMTP server
    try:
        sock = socket.create_connection((_s.EMAIL_HOST, _s.EMAIL_PORT), timeout=10)
        sock.close()
        results['tcp_connection'] = f'OK - can reach {_s.EMAIL_HOST}:{_s.EMAIL_PORT}'
    except Exception as e:
        results['tcp_connection'] = f'FAILED - {e}'
        results['diagnosis'] = 'Cannot connect to SMTP server. Render may be blocking this port/host.'
        return JsonResponse(results)

    # Try sending
    try:
        send_mail(
            subject='GPSL Email Test',
            message=f'Test email from GPSL Business Suite on Render.\\n\\nIf you see this, SMTP is working.',
            from_email=_s.DEFAULT_FROM_EMAIL,
            recipient_list=[to_email],
            fail_silently=False,
        )
        results['send_result'] = f'SUCCESS - email sent to {to_email}'
        results['diagnosis'] = 'SMTP is working correctly'
    except Exception as e:
        results['send_result'] = f'FAILED - {str(e)}'
        err = str(e).lower()
        if 'authentication' in err or '535' in err:
            results['diagnosis'] = 'Authentication failed. Check EMAIL_HOST_PASSWORD in Render env vars. Gmail app password must be 16 chars no spaces.'
        elif 'connection' in err or 'refused' in err or 'timeout' in err:
            results['diagnosis'] = 'Connection blocked. Render is blocking Gmail SMTP. Switch to Brevo SMTP (see fix below).'
        elif '550' in err or 'relay' in err:
            results['diagnosis'] = 'Relay denied. Gmail blocking sending from this server IP. Switch to Brevo SMTP.'
        else:
            results['diagnosis'] = f'Unknown error. Try switching SMTP provider.'

        results['fix'] = {
            'step1': 'Sign up free at brevo.com',
            'step2': 'Go to SMTP & API tab, copy credentials',
            'step3': 'Update Render env vars:',
            'EMAIL_HOST': 'smtp-relay.brevo.com',
            'EMAIL_PORT': '587',
            'EMAIL_HOST_USER': 'your-brevo-login',
            'EMAIL_HOST_PASSWORD': 'your-brevo-smtp-password',
        }

    return JsonResponse(results, json_dumps_params={'indent': 2})
'''
    views += diag_view
    open(f'{W}/core/views.py','w').write(views)
    print("email_diagnostic view added")

# ── Add URL ──
urls = open(f'{W}/core/urls.py').read()
if 'email_diagnostic' not in urls:
    route = "    path('system/email-test/', views.email_diagnostic, name='email_diagnostic'),"
    urls = urls.rstrip().rstrip(']').rstrip() + '\n' + route + '\n]\n'
    open(f'{W}/core/urls.py','w').write(urls)
    print("URL added: /system/email-test/")

# ── Add EMAIL_USE_SSL to settings ──
settings = open(f'{W}/django_project/settings.py').read()
if 'EMAIL_USE_SSL' not in settings:
    settings = settings.replace(
        'EMAIL_USE_TLS = True',
        'EMAIL_USE_TLS = config(\'EMAIL_USE_TLS\', default=True, cast=bool)\nEMAIL_USE_SSL = config(\'EMAIL_USE_SSL\', default=False, cast=bool)'
    )
    open(f'{W}/django_project/settings.py','w').write(settings)
    print("EMAIL_USE_SSL added to settings")

if 'EMAIL_TIMEOUT' not in settings:
    settings = open(f'{W}/django_project/settings.py').read()
    settings += '\nEMAIL_TIMEOUT = 15\n'
    open(f'{W}/django_project/settings.py','w').write(settings)
    print("EMAIL_TIMEOUT = 15 added")

import ast
try:
    ast.parse(open(f'{W}/core/views.py').read())
    print("views.py: OK")
except SyntaxError as e:
    print(f"SYNTAX ERROR: {e}")

print("\nDone. Now push:")
print("git add . && git commit -m 'Add email diagnostic endpoint' && git push")
print("\nAfter Render redeploys, visit:")
print("https://app.globalphonelinz.com/system/email-test/?key=gpsl2026backup&to=kemimonday00@gmail.com")
print("This tells you EXACTLY why emails are failing")
