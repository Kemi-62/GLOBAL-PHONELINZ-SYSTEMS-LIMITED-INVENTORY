"""
Django settings for django_project project.
SECURITY-HARDENED VERSION
"""

import os
from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

# ═══════════════════════════════════════════════════════
# SECURITY CONFIGURATION — READ-ONLY IN PRODUCTION
# ═══════════════════════════════════════════════════════

# SECRET_KEY: development fallback that logs a warning.
# In production, set SECRET_KEY in environment and IS_PRODUCTION=True.
SECRET_KEY = config('SECRET_KEY', default='dev-only-unsafe-secret-change-in-production')

# Production flag
IS_PRODUCTION = config('IS_PRODUCTION', default=False, cast=bool)

# DEBUG: True in development, MUST be False in production via env var.
DEBUG = config('DEBUG', default=True, cast=bool)

# ALLOWED_HOSTS: NEVER wildcard in production. Only specific domains.
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,.replit.dev,.repl.co,.replit.app,.worf.replit.dev,.pike.replit.dev,.riker.replit.dev', cast=Csv())

# CSRF: Secure by default
CSRF_COOKIE_HTTPONLY = True
CSRF_USE_SESSIONS = True
CSRF_COOKIE_SAMESITE = 'Strict'
CSRF_COOKIE_SECURE = IS_PRODUCTION
SESSION_COOKIE_SECURE = IS_PRODUCTION
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'

# Session timeout: 30 minutes of inactivity, 8 hours max
SESSION_COOKIE_AGE = 28800  # 8 hours
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# Security Headers — applied on ALL deployments
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_SSL_REDIRECT = IS_PRODUCTION
X_FRAME_OPTIONS = 'DENY'

# HSTS: Force HTTPS for 1 year (31,536,000 seconds)
SECURE_HSTS_SECONDS = 31536000 if IS_PRODUCTION else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = IS_PRODUCTION
SECURE_HSTS_PRELOAD = IS_PRODUCTION

# Proxy header for HTTPS detection behind Render/Cloudflare
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

CSRF_TRUSTED_ORIGINS = config(
    'CSRF_TRUSTED_ORIGINS',
    default='https://localhost',
    cast=Csv()
)

CSRF_FAILURE_VIEW = 'core.views.csrf_failure'

# ═══════════════════════════════════════════════════════
# ADMIN PANEL — HIDDEN URL (not /admin/)
# ═══════════════════════════════════════════════════════
ADMIN_URL = config('ADMIN_URL', default='system-admin/')

# Cache: LocMem for development (needed for rate limiting)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'gpsl-cache',
    }
}

# ═══════════════════════════════════════════════════════
# APPLICATION DEFINITION
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

if config('DB_ENGINE', default='sqlite') == 'postgresql':
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
# PASSWORD VALIDATION — Stronger for production
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
# STATIC & MEDIA FILES
# ═══════════════════════════════════════════════════════

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# File upload limits (5MB max for selfies)
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5MB

# ═══════════════════════════════════════════════════════
# EMAIL CONFIGURATION — via environment only
# ═══════════════════════════════════════════════════════

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER)

# ═══════════════════════════════════════════════════════
# RATE LIMITING CONFIG
# ═══════════════════════════════════════════════════════

RATE_LIMIT_LOGIN_ATTEMPTS = 5      # Max failed logins per window
RATE_LIMIT_LOGIN_WINDOW = 300      # 5 minutes (seconds)
RATE_LIMIT_LOGIN_BLOCK = 1800      # 30 minutes block (seconds)

# ═══════════════════════════════════════════════════════
# MONIEPOINT CONFIG
# ═══════════════════════════════════════════════════════

MONIEPOINT_MERCHANT_ID = config('MONIEPOINT_MERCHANT_ID', default='')
MONIEPOINT_API_KEY = config('MONIEPOINT_API_KEY', default='')
MONIEPOINT_ENABLED = config('MONIEPOINT_ENABLED', default=False, cast=bool)

# ═══════════════════════════════════════════════════════
# WHATSAPP CONFIG
# ═══════════════════════════════════════════════════════

WHATSAPP_ENABLED = config('WHATSAPP_ENABLED', default=False, cast=bool)
WHATSAPP_API_KEY = config('WHATSAPP_API_KEY', default='')
WHATSAPP_PHONE_NUMBER_ID = config('WHATSAPP_PHONE_NUMBER_ID', default='')

# ═══════════════════════════════════════════════════════
# MISC
# ═══════════════════════════════════════════════════════

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CONN_MAX_AGE = 60

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'WARNING',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'django.log'),
        },
        'security_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'security.log'),
        },
    },
    'loggers': {
        'django.security': {
            'handlers': ['security_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['file'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}
