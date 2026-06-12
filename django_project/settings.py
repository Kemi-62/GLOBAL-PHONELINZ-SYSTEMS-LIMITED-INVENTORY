"""
Django settings for django_project project.
RENDER-FIRST VERSION — optimized for Render deployment with no custom domain.
"""

import os
from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

# ═══════════════════════════════════════════════════════
# RENDER DETECTION
# ═════════════════════0═══════════════════════════════

IS_RENDER = os.environ.get('RENDER') == 'true' or os.environ.get('RENDER_EXTERNAL_HOSTNAME') is not None
IS_REPLIT = os.environ.get('REPL_ID') is not None
IS_PRODUCTION = config('IS_PRODUCTION', default=False, cast=bool) or IS_RENDER

# ═══════════════════════════════════════════════════════
# SECURITY — RELAXED FOR RENDER (no custom domain yet)
# When you get a custom domain, set IS_PRODUCTION=True and set ALLOWED_HOSTS.
# ═══════════════════════════════════════════════════════

# SECRET_KEY: Use environment on Render; dev fallback for local development.
# Generate a new one for Render: python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
SECRET_KEY = config('SECRET_KEY', default='django-insecure-dev-change-on-render')

DEBUG = config('DEBUG', default=not IS_PRODUCTION, cast=bool)

# ALLOWED_HOSTS: Render auto-detects hostname; Replit uses wildcard; production uses explicit list.
if IS_RENDER:
    render_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '')
    ALLOWED_HOSTS = [render_host] if render_host else ['*']
elif IS_REPLIT:
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

# CSRF: Render uses HTTPS so cookies can be secure. Replit uses HTTP so keep cookies non-secure.
CSRF_COOKIE_HTTPONLY = True
CSRF_USE_SESSIONS = True
CSRF_COOKIE_SAMESITE = 'Lax' if not IS_PRODUCTION else 'Strict'
CSRF_COOKIE_SECURE = IS_PRODUCTION
SESSION_COOKIE_SECURE = IS_PRODUCTION
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax' if not IS_PRODUCTION else 'Strict'

# Session: 8 hours on Render, 2 hours locally
SESSION_COOKIE_AGE = 28800 if IS_PRODUCTION else 7200
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# Security Headers: Always apply basic ones; strict ones only in production
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_SSL_REDIRECT = IS_PRODUCTION
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000 if IS_PRODUCTION else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = IS_PRODUCTION
SECURE_HSTS_PRELOAD = IS_PRODUCTION

# Proxy header for HTTPS detection behind Render
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# CSRF Trusted Origins: Render domains, Replit domains
_default_csrf = []
if IS_RENDER:
    render_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    if render_host:
        _default_csrf.append(f'https://{render_host}')
if IS_REPLIT:
    _default_csrf.extend([
        'https://*.replit.dev',
        'https://*.repl.co',
        'https://*.replit.app',
    ])
if not _default_csrf:
    _default_csrf = ['https://localhost']

CSRF_TRUSTED_ORIGINS = config(
    'CSRF_TRUSTED_ORIGINS',
    default=','.join(_default_csrf),
    cast=Csv()
)

CSRF_FAILURE_VIEW = 'core.views.csrf_failure'

# ═══════════════════════════════════════════════════════
# ADMIN PANEL — HIDDEN URL (change on Render!)
# ═══════════════════════════════════════════════════════
ADMIN_URL = config('ADMIN_URL', default='system-admin/')

# ═══════════════════════════════════════════════════════
# APPLICATION
# ═══════════════════════════════════════════════════════

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'core',
]

AUTH_USER_MODEL = 'core.User'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'core.middleware.SecurityHeadersMiddleware',
    'core.middleware.RateLimitMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.middleware.SessionTimeoutMiddleware',
    'core.middleware.AdminAccessLogMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'django_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'django_project.wsgi.application'

# ═══════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════

# Render DATABASE_URL (PostgreSQL) takes priority unless explicitly overridden
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and config('DB_ENGINE', default='auto') != 'sqlite':
    import dj_database_url
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL, conn_max_age=60)
    }
elif config('DB_ENGINE', default='sqlite') == 'postgresql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME'),
            'USER': config('DB_USER'),
            'PASSWORD': config('DB_PASSWORD'),
            'HOST': config('DB_HOST'),
            'PORT': '5432',
            'CONN_MAX_AGE': 60,
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ═══════════════════════════════════════════════════════
# PASSWORD VALIDATION
# ═══════════════════════════════════════════════════════

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ═══════════════════════════════════════════════════════
# INTERNATIONALIZATION
# ═══════════════════════════════════════════════════════

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Lagos'
USE_I18N = True
USE_TZ = True

# ═══════════════════════════════════════════════════════
# STATIC & MEDIA
# ═══════════════════════════════════════════════════════

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# ═══════════════════════════════════════════════════════
# EMAIL
# ═══════════════════════════════════════════════════════

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER)

# ═══════════════════════════════════════════════════════
# RATE LIMITING
# ═══════════════════════════════════════════════════════

RATE_LIMIT_LOGIN_ATTEMPTS = 5
RATE_LIMIT_LOGIN_WINDOW = 300
RATE_LIMIT_LOGIN_BLOCK = 1800

# ═══════════════════════════════════════════════════════
# MONIEPOINT
# ═══════════════════════════════════════════════════════

MONIEPOINT_ENABLED = config('MONIEPOINT_ENABLED', default=False, cast=bool)
MONIEPOINT_MERCHANT_ID = config('MONIEPOINT_MERCHANT_ID', default='')
MONIEPOINT_API_KEY = config('MONIEPOINT_API_KEY', default='')

# ═══════════════════════════════════════════════════════
# WHATSAPP
# ═══════════════════════════════════════════════════════

WHATSAPP_ENABLED = config('WHATSAPP_ENABLED', default=False, cast=bool)
WHATSAPP_API_KEY = config('WHATSAPP_API_KEY', default='')
WHATSAPP_PHONE_NUMBER_ID = config('WHATSAPP_PHONE_NUMBER_ID', default='')

# ═══════════════════════════════════════════════════════
# CACHING
# ═══════════════════════════════════════════════════════

# Use Redis on Render if available, otherwise LocMem
if os.environ.get('REDIS_URL'):
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': os.environ.get('REDIS_URL'),
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            }
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'gpsl-cache',
        }
    }

# ═══════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'level': 'WARNING',
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django.request': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# ═══════════════════════════════════════════════════════
# MISC
# ═══════════════════════════════════════════════════════

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CONN_MAX_AGE = 60
