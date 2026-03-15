# Deployment Guide: GPSL Automation to Render

## Prerequisites
- A Render.com account
- PostgreSQL database on Render
- This repository pushed to GitHub

## Step 1: Create PostgreSQL Database on Render

1. Go to Render Dashboard → Create → PostgreSQL
2. Name: `gpsl-db` (or your choice)
3. Copy connection details:
   - Host
   - Database name
   - User
   - Password

## Step 2: Create Web Service on Render

1. Go to Render Dashboard → Create → Web Service
2. Connect your GitHub repository
3. Configure settings:
   - **Name**: `gpsl-automation`
   - **Environment**: Python
   - **Region**: Choose closest to you
   - **Branch**: main

## Step 3: Build & Start Commands

- **Build Command**: 
  ```
  pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate
  ```

- **Start Command**: 
  ```
  gunicorn django_project.wsgi:application
  ```

## Step 4: Environment Variables

Add these in Render Dashboard → Environment:

```
SECRET_KEY=your-secret-key-here (generate a new one: python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')
DEBUG=False
DB_ENGINE=postgresql
DB_NAME=your_database_name
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_HOST=your_database_host
```

## Step 5: Install Gunicorn

Add `gunicorn` to `requirements.txt`:
```bash
pip install gunicorn
pip freeze > requirements.txt
```

## Step 6: Collect Static Files

The build command automatically runs:
```bash
python manage.py collectstatic --noinput
```

This collects all static files to `staticfiles/` directory.

## Step 7: Deploy

1. Push changes to GitHub
2. Render automatically deploys on push
3. Check deployment logs: Render Dashboard → Logs
4. Visit your deployed app: `https://your-service-name.onrender.com`

## Step 8: Create Superuser (One-time)

After first deployment, SSH into Render and run:
```bash
python manage.py createsuperuser
```

Or set up via Django admin panel after deployment.

## Post-Deployment Checklist

- [ ] Database connected and migrated
- [ ] Static files serving correctly (CSS, images visible)
- [ ] Login page loads
- [ ] Create test user account
- [ ] Test all dashboard features
- [ ] Verify admin panel at `/admin/`

## Troubleshooting

**502 Bad Gateway**: Check logs for errors
```
Render → Logs → Check for Python/Django errors
```

**Static files not loading**: Ensure `collectstatic` ran
```
python manage.py collectstatic --noinput
```

**Database connection error**: Verify environment variables match PostgreSQL credentials

**Port binding error**: Render automatically assigns port via `$PORT` variable

## Rolling Back

1. Go to Render Dashboard → Deployments
2. Click previous successful deployment
3. Click "Deploy" button to rollback

---

**App is now production-ready!** 🚀
