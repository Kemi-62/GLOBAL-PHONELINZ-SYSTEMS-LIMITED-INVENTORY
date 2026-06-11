"""
GPSL ERP — Database Keepalive + Backup System
==============================================
This file handles:
1. Supabase keepalive (prevents free tier pausing)
2. Automated database backup to a file
3. Email the backup to director

HOW TO SET UP:
--------------
Upload this file to your Replit root.
Then follow the steps below.
"""

import os
import sys
import gzip
import subprocess
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from datetime import datetime

# ─────────────────────────────────────────
# CONFIG — reads from environment variables
# ─────────────────────────────────────────

DATABASE_URL   = os.environ.get("DATABASE_URL", "")
EMAIL_USER     = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_PASS     = os.environ.get("EMAIL_HOST_PASSWORD", "")
BACKUP_EMAIL   = os.environ.get("kemimonday00@gmail.com", EMAIL_USER)  # where to send backup
BACKUP_DIR     = os.path.join(os.path.dirname(__file__), "backups")


def keepalive():
    """
    Ping the Supabase database to prevent it from pausing.
    Run this every 3-4 days via Replit cron or any scheduler.
    """
    try:
        import django
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_project.settings")
        django.setup()
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] Keepalive ping successful: {result}")
        return True
    except Exception as e:
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] Keepalive FAILED: {e}")
        return False


def backup_database():
    """
    Create a compressed SQL dump of the entire database.
    Saves to /backups/ folder and optionally emails it.
    """
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set in environment.")
        return None

    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename   = f"gpsl_backup_{timestamp}.sql.gz"
    filepath   = os.path.join(BACKUP_DIR, filename)

    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Starting database backup...")

    try:
        # Run pg_dump and compress output
        dump_process = subprocess.Popen(
            ["pg_dump", DATABASE_URL, "--no-password", "--clean", "--if-exists"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        sql_data, errors = dump_process.communicate()

        if dump_process.returncode != 0:
            print(f"pg_dump failed: {errors.decode()}")
            return None

        # Compress with gzip
        with gzip.open(filepath, "wb") as f:
            f.write(sql_data)

        size_kb = os.path.getsize(filepath) / 1024
        print(f"Backup created: {filename} ({size_kb:.1f} KB)")
        return filepath

    except FileNotFoundError:
        print("pg_dump not found. Install with: apt-get install postgresql-client")
        # Fallback: use Django's dumpdata for a JSON backup
        return backup_django_json(timestamp)
    except Exception as e:
        print(f"Backup failed: {e}")
        return None


def backup_django_json(timestamp=None):
    """
    Fallback backup using Django's dumpdata (JSON format).
    Works without pg_dump installed.
    """
    if not timestamp:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    os.makedirs(BACKUP_DIR, exist_ok=True)
    filename = f"gpsl_backup_{timestamp}.json.gz"
    filepath = os.path.join(BACKUP_DIR, filename)

    try:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_project.settings")
        import django
        django.setup()

        from django.core.management import call_command
        import io

        buffer = io.StringIO()
        call_command(
            "dumpdata",
            "--natural-foreign",
            "--natural-primary",
            "--exclude=contenttypes",
            "--exclude=auth.permission",
            "--exclude=admin.logentry",
            stdout=buffer,
        )
        json_data = buffer.getvalue().encode("utf-8")

        with gzip.open(filepath, "wb") as f:
            f.write(json_data)

        size_kb = os.path.getsize(filepath) / 1024
        print(f"JSON backup created: {filename} ({size_kb:.1f} KB)")
        return filepath

    except Exception as e:
        print(f"JSON backup failed: {e}")
        return None


def email_backup(filepath):
    """
    Email the backup file to BACKUP_EMAIL.
    """
    if not filepath or not os.path.exists(filepath):
        print("No backup file to email.")
        return False

    if not EMAIL_USER or not EMAIL_PASS:
        print("Email credentials not set. Skipping email.")
        return False

    filename  = os.path.basename(filepath)
    size_kb   = os.path.getsize(filepath) / 1024
    timestamp = datetime.now().strftime("%d %B %Y at %H:%M")

    msg = MIMEMultipart()
    msg["From"]    = EMAIL_USER
    msg["To"]      = BACKUP_EMAIL
    msg["Subject"] = f"GPSL ERP Database Backup — {timestamp}"

    body = f"""
GPSL ERP Automated Database Backup

Date: {timestamp}
File: {filename}
Size: {size_kb:.1f} KB

This backup was generated automatically.
To restore: gunzip the file and run psql [DATABASE_URL] < backup.sql
Or for JSON: python manage.py loaddata backup.json

Keep this email safe.
— GPSL ERP System
    """.strip()

    msg.attach(MIMEText(body, "plain"))

    # Attach the backup file
    with open(filepath, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{filename}"'
        )
        msg.attach(part)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, BACKUP_EMAIL, msg.as_string())
        print(f"Backup emailed to {BACKUP_EMAIL}")
        return True
    except Exception as e:
        print(f"Email failed: {e}")
        return False


def cleanup_old_backups(keep=5):
    """
    Keep only the most recent N backups to save disk space.
    """
    if not os.path.exists(BACKUP_DIR):
        return
    files = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.startswith("gpsl_backup_")],
        reverse=True
    )
    for old_file in files[keep:]:
        os.remove(os.path.join(BACKUP_DIR, old_file))
        print(f"Deleted old backup: {old_file}")


def run_full_backup():
    """
    Full backup routine: create + email + cleanup.
    Call this weekly.
    """
    print("=" * 50)
    print(f"GPSL ERP BACKUP — {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 50)

    filepath = backup_database()
    if filepath:
        email_backup(filepath)
        cleanup_old_backups(keep=5)
        print("Backup complete.")
    else:
        print("Backup failed.")


# ─────────────────────────────────────────
# REPLIT CRON SETUP INSTRUCTIONS
# ─────────────────────────────────────────
"""
In Replit, go to Tools → Scheduled Jobs (or use .replit file).

Add these two jobs:

JOB 1 — Keepalive (every 4 days):
    Command: python /home/runner/workspace/cron.py keepalive
    Schedule: Every 4 days

JOB 2 — Weekly Backup (every Sunday at 2am):
    Command: python /home/runner/workspace/cron.py backup
    Schedule: Weekly on Sunday

If Replit scheduled jobs are not available on your plan,
use cron-job.org (free) to hit a URL that triggers the job,
or set up a simple GitHub Actions workflow.
"""

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "help"

    if command == "keepalive":
        keepalive()

    elif command == "backup":
        run_full_backup()

    elif command == "backup-now":
        # Quick backup without email (for testing)
        filepath = backup_database()
        if filepath:
            print(f"Backup saved: {filepath}")
            cleanup_old_backups(keep=5)

    elif command == "email-last":
        # Email the most recent backup
        if os.path.exists(BACKUP_DIR):
            files = sorted(
                [f for f in os.listdir(BACKUP_DIR) if f.startswith("gpsl_backup_")],
                reverse=True
            )
            if files:
                email_backup(os.path.join(BACKUP_DIR, files[0]))
            else:
                print("No backups found. Run: python cron.py backup-now first.")

    else:
        print("""
GPSL ERP Cron Script
====================
Usage:
  python cron.py keepalive     — Ping database (run every 4 days)
  python cron.py backup        — Full backup + email (run weekly)
  python cron.py backup-now    — Quick backup, no email (for testing)
  python cron.py email-last    — Email the most recent backup
        """)
