# GPSL Automation - Deployment Checklist

## Pre-Deployment
- [x] requirements.txt generated with all dependencies
- [x] settings.py configured for production
- [x] Database supports both SQLite and PostgreSQL
- [x] Static files configuration with WhiteNoise
- [x] WSGI application ready
- [x] Environment variable support via python-decouple
- [x] CSRF and CORS settings updated for production domains

## Production Settings
- [x] DEBUG = False (via environment variable)
- [x] SECRET_KEY = from environment (via decouple)
- [x] ALLOWED_HOSTS = '*' (production should specify)
- [x] CSRF_TRUSTED_ORIGINS includes *.onrender.com
- [x] DATABASES support PostgreSQL
- [x] STATIC_ROOT and STATICFILES_STORAGE configured
- [x] WhiteNoiseMiddleware added

## Render Deployment Steps
1. [ ] Create PostgreSQL database on Render
2. [ ] Create Web Service connected to GitHub
3. [ ] Set environment variables in Render
4. [ ] Configure build command: `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
5. [ ] Configure start command: `gunicorn django_project.wsgi:application`
6. [ ] Deploy and verify logs
7. [ ] Create superuser via Django admin or SSH
8. [ ] Test all features in production

## Post-Deployment Verification
- [ ] Login page loads
- [ ] CSS/static files displaying
- [ ] Dashboard accessible
- [ ] Database tables migrated
- [ ] Admin panel working
- [ ] All user roles functioning
- [ ] File uploads working (media files)

## Important Notes
- Generate new SECRET_KEY: `python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'`
- Install Gunicorn before deployment: `pip install gunicorn`
- Keep .env file secure (not in git)
- Use RENDER_DEPLOY.md as reference
