# replit.md

## Overview

This is a Django-based **Service Performance Tracking ERP System** for a telecom/retail business. It tracks employee service activities (SIM registrations, SIM swaps, NIN linking, MiFi sales, etc.) against branch-level targets. The system supports multiple user roles (Super Admin, Director, Manager, Telecom Staff, Retail Staff, MultiChoice Staff) with role-based dashboards and an approval workflow for activities that exceed targets.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Framework & Language
- **Django 5.0** with Python
- Server-rendered templates (no frontend JS framework)
- SQLite database by default (Django's default; may need PostgreSQL for production)

### Project Structure
- `django_project/` — Django project config (settings, urls, wsgi, asgi)
- `core/` — Main application containing all models, views, URLs, and admin config
- `templates/` — HTML templates at the project root level (not inside the app)
- `manage.py` — Standard Django management entry point

### Custom User Model
- Extends `AbstractUser` with additional fields: `role`, `branch`, `failed_login_count`, `is_locked`
- `AUTH_USER_MODEL` should be set to `core.User` in settings
- Six roles: SUPERADMIN, DIRECTOR, MANAGER, TELECOM, RETAIL, MULTICHOICE
- Account locking mechanism after failed login attempts

### Key Models
- **Branch** — Business locations/branches
- **User** — Custom user with role and branch assignment
- **DeviceTag** — Tags for devices used in SIM registration, linked to branches
- **ServiceTarget** — Monthly/daily targets per branch, service type, and optional device tag (unique together constraint)
- **ServiceActivity** — Staff-submitted service records with approval workflow (`requires_approval`, `approved` fields)
- **Product, RetailCategory, RetailSubCategory, BranchSafeStock** — Retail inventory management models (added in later migrations)

### Role-Based Dashboards
- **Staff Dashboard** (`/staff/`) — Submit service activities, view monthly summary and pending approvals
- **Manager Dashboard** (`/manager/`) — View target performance, approve activities that exceed targets
- **Director Dashboard** (`/director/`) — Analytics with branch performance summaries, device tag filtering
- **Retail Dashboard** (`/retail/`) — Phones & Accessories staff (placeholder)
- **MultiChoice Dashboard** (`/multichoice/`) — MultiChoice staff (placeholder)

### Authentication & Authorization
- Custom login view at root URL (`/`) that routes users to role-specific dashboards
- Login auto-logs out already-authenticated users on GET (forces fresh login)
- Failed login counting with account locking
- `@login_required` decorator on dashboard views
- Manager approval workflow for service activities exceeding targets

### CSRF & Security Configuration
- Configured for Replit deployment with trusted origins for `*.replit.dev`, `*.repl.co`, `*.replit.app`
- `SECURE_PROXY_SSL_HEADER` set for reverse proxy support
- Custom CSRF failure view at `core.views.csrf_failure`
- `DEBUG = True` (development mode)
- `ALLOWED_HOSTS = ['*']`

### Running the Application
- Start with: `python manage.py runserver 0.0.0.0:5000`
- Apply migrations first: `python manage.py migrate`
- Create superuser: `python manage.py createsuperuser`
- Admin panel available at `/admin/`

### Important Notes
- The `core/models.py` file appears truncated — the `ServiceTarget` and `ServiceActivity` model definitions are cut off but referenced in migrations
- The `core/views.py` file is also truncated — several view functions are incomplete
- Some templates are incomplete (truncated HTML)
- The settings file is truncated — `INSTALLED_APPS`, `MIDDLEWARE`, `TEMPLATES`, `DATABASES`, and `AUTH_USER_MODEL` configurations may need verification

## External Dependencies

### Python Packages
- **Django 5.0.x** — Web framework
- Standard Django built-in packages (auth, admin, sessions, messages, contenttypes)

### Database
- Currently using **SQLite** (Django default) — no explicit database configuration visible in the truncated settings
- May need migration to **PostgreSQL** for production deployment

### Deployment
- Configured for **Replit** hosting with appropriate CSRF trusted origins
- WSGI and ASGI entry points configured

### No External APIs or Third-Party Services
- No external API integrations detected
- No third-party Python packages beyond Django core
- No JavaScript frameworks or CDN dependencies in templates