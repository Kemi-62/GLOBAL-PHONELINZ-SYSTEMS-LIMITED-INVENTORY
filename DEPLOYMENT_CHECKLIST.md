# GPSL Automation — Deployment Checklist

## Pre-Deployment (Render)
- [x] `requirements.txt` with all dependencies
- [x] `settings.py` supports Render auto-detection (`DATABASE_URL`, `RENDER_EXTERNAL_HOSTNAME`)
- [x] PostgreSQL supported via `dj-database-url`
- [x] Static files with WhiteNoise
- [x] WSGI ready for Gunicorn
- [x] Environment variables via `python-decouple`
- [x] `render.yaml` with auto-generated `SECRET_KEY`
- [x] `build.sh` for manual builds
- [x] `core/fixtures/initial_data.json` for initial data

## Render Setup (UI Steps)
1. Push code to GitHub
2. In Render Dashboard → New Web Service → Connect to GitHub repo
3. Render auto-detects `render.yaml` → uses Python environment
4. Render auto-creates PostgreSQL database (`gpsl-db`)
5. Render auto-generates `SECRET_KEY` and sets `DATABASE_URL`
6. **Important**: Set `IS_PRODUCTION=True` if you want strict security
7. **Optional**: Set `ADMIN_URL` to a custom path (default: `system-admin/`)
8. Deploy

## Post-Deploy
- [ ] Login page loads
- [ ] CSS/static files working
- [ ] Dashboard accessible
- [ ] Admin panel at `/{ADMIN_URL}/` working
- [ ] Create superuser via `seed_roles` or admin panel
- [ ] Create staff users with proper passwords
- [ ] Test all user roles
- [ ] Test file uploads (media files need Cloudinary/AWS on Render free tier)

## Environment Variables for Render
| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | auto-generated | Django secret key |
| `DEBUG` | false | Enable debug mode |
| `IS_PRODUCTION` | false | Enable strict security headers |
| `ADMIN_URL` | `system-admin/` | Hidden admin URL path |
| `DATABASE_URL` | auto-set | PostgreSQL connection string |
| `EMAIL_HOST_USER` | — | SMTP email address |
| `EMAIL_HOST_PASSWORD` | — | SMTP password |
| `MONIEPOINT_ENABLED` | false | Enable POS integration |
| `WHATSAPP_ENABLED` | false | Enable WhatsApp buttons |
| `REDIS_URL` | — | Redis cache (optional) |
