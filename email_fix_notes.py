"""
EMAIL FIX — Run these commands in Replit shell ONE AT A TIME

The problem: Django's password reset requires a valid email on the
User account. If the staff's email field is blank or wrong, Django
throws SMTPSenderRefused instead of gracefully saying "email not found".

TWO FIXES NEEDED:
1. Set up real Gmail credentials in .env
2. Override PasswordResetView to handle missing emails gracefully
"""

# ── STEP 1: Add to your .env file ──
# Open .env in Replit and add these lines:
"""
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=yourgmail@gmail.com
EMAIL_HOST_PASSWORD=your16digitapppassword
DEFAULT_FROM_EMAIL=yourgmail@gmail.com
"""

# ── STEP 2: Run this in shell to update settings.py ──
"""
python -c "
code = open('/home/runner/workspace/django_project/settings.py').read()
if 'EMAIL_BACKEND' not in code:
    extra = '''
# Email
EMAIL_BACKEND    = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST       = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT       = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS    = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER  = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('EMAIL_HOST_USER', default='noreply@gpsl.com')
'''
    open('/home/runner/workspace/django_project/settings.py','a').write(extra)
    print('Email settings added')
else:
    print('Already there')
"
"""

# ── STEP 3: Custom PasswordResetView to handle missing emails ──
# This is added to views.py — catches the case where staff email
# is blank or wrong and shows a friendly message instead of crashing

CUSTOM_RESET_VIEW = '''
from django.contrib.auth.views import PasswordResetView as DjangoPasswordResetView
from django.contrib import messages as dj_messages

class CustomPasswordResetView(DjangoPasswordResetView):
    template_name = "registration/password_reset_form.html"

    def form_valid(self, form):
        email = form.cleaned_data.get("email", "")
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if not User.objects.filter(email=email).exists():
            dj_messages.warning(
                self.request,
                "No account found with that email address. "
                "Please contact your director to reset your password."
            )
            from django.shortcuts import redirect
            return redirect("login")
        try:
            return super().form_valid(form)
        except Exception:
            dj_messages.error(
                self.request,
                "Email could not be sent. Please check email settings or "
                "contact your director directly."
            )
            from django.shortcuts import redirect
            return redirect("login")
'''
