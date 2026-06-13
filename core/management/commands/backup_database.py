"""Management command: backup database and email it.

Supports SQLite (copy .db file) and PostgreSQL (pg_dump to .sql).

Usage: python manage.py backup_database --trigger=manual
       python manage.py backup_database --send-email=your@email.com
       python manage.py backup_database --upload-supabase
"""
import os, shutil, subprocess
from pathlib import Path
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.conf import settings
from django.utils import timezone
from core.models import BackupLog


class Command(BaseCommand):
    help = "Backup the database and optionally email it."

    def add_arguments(self, parser):
        parser.add_argument("--trigger", default="manual", help="Who triggered: auto, manual, cron")
        parser.add_argument("--send-email", default="", help="Email address to send backup to")
        parser.add_argument("--upload-supabase", action="store_true", help="Upload backup to Supabase Storage")

    def handle(self, *args, **options):
        db = settings.DATABASES.get("default", {})
        engine = db.get("ENGINE", "")
        backup_dir = Path("backups")
        backup_dir.mkdir(exist_ok=True)
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")

        if "postgresql" in engine:
            # PostgreSQL backup via pg_dump
            backup_file = self._backup_postgresql(db, backup_dir, timestamp)
        else:
            # SQLite backup (copy file)
            backup_file = self._backup_sqlite(db, backup_dir, timestamp)

        if not backup_file:
            return

        file_size = backup_file.stat().st_size
        log = BackupLog.objects.create(
            triggered_by=options["trigger"],
            status="SUCCESS",
            file_path=str(backup_file),
            file_size_bytes=file_size,
        )

        self.stdout.write(self.style.SUCCESS(f"Backup created: {backup_file} ({file_size:,} bytes)"))

        # Email backup
        email_to = options["send_email"] or getattr(settings, "BACKUP_EMAIL", "") or getattr(settings, "EMAIL_HOST_USER", "")
        if email_to and settings.EMAIL_HOST_USER:
            self._email_backup(backup_file, file_size, email_to, log, "postgresql" in engine)

        # Upload to Supabase (only if requested)
        if options["upload_supabase"]:
            self._upload_to_supabase(str(backup_file), log)

        log.completed_at = timezone.now()
        log.save()

    def _backup_sqlite(self, db, backup_dir, timestamp):
        db_path = db.get("NAME", "db.sqlite3")
        if not os.path.exists(db_path):
            self.stderr.write(self.style.ERROR(f"Database not found: {db_path}"))
            return None
        backup_file = backup_dir / f"gpsl_backup_{timestamp}.db"
        shutil.copy2(db_path, backup_file)
        return backup_file

    def _backup_postgresql(self, db, backup_dir, timestamp):
        backup_file = backup_dir / f"gpsl_backup_{timestamp}.sql"
        env = os.environ.copy()
        env["PGPASSWORD"] = db.get("PASSWORD", "")
        cmd = [
            "pg_dump",
            "-h", db.get("HOST", "localhost"),
            "-p", str(db.get("PORT", 5432)),
            "-U", db.get("USER", "postgres"),
            "-d", db.get("NAME", "postgres"),
            "-f", str(backup_file),
        ]
        if db.get("OPTIONS", {}).get("sslmode"):
            env["PGSSLMODE"] = db["OPTIONS"]["sslmode"]
        try:
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                self.stderr.write(self.style.ERROR(f"pg_dump failed: {result.stderr}"))
                return None
            return backup_file
        except FileNotFoundError:
            self.stderr.write(self.style.ERROR("pg_dump not found. Install PostgreSQL client tools."))
            return None
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Backup failed: {e}"))
            return None

    def _email_backup(self, backup_file, file_size, email_to, log, is_postgres):
        try:
            dt = timezone.now().strftime('%d %b %Y %H:%M')
            size_kb = file_size / 1024
            if is_postgres:
                restore_steps = (
                    "1. Download this .sql file\n"
                    "2. Create a new PostgreSQL database\n"
                    "3. Run: psql -d your_db -f gpsl_backup_xxxx.sql\n"
                    "4. Update your app to connect to the new database"
                )
                file_type = "SQL dump"
            else:
                restore_steps = (
                    "1. Download this .db file\n"
                    "2. Replace the existing db.sqlite3 with this file\n"
                    "3. Restart the application"
                )
                file_type = "SQLite database"

            body = (
                f"Hello,\n\n"
                f"Your GPSL ERP database has been backed up automatically.\n\n"
                f"Backup details:\n"
                f"- Date: {dt}\n"
                f"- Type: {file_type}\n"
                f"- File size: {size_kb:.1f} KB\n"
                f"- Records: This backup contains all your ERP data.\n\n"
                f"To restore:\n"
                f"{restore_steps}\n\n"
                f"This is an automated backup. Keep this file safe.\n\n"
                f"- GPSL ERP System"
            )
            subject = f"GPSL ERP Database Backup - {dt}"
            msg = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [email_to])
            msg.attach_file(str(backup_file))
            msg.send()
            log.email_sent = True
            log.email_recipient = email_to
            self.stdout.write(self.style.SUCCESS(f"Backup emailed to {email_to}"))
        except Exception as e:
            log.email_sent = False
            log.email_error = str(e)
            self.stderr.write(self.style.ERROR(f"Email failed: {e}"))

    def _upload_to_supabase(self, file_path, log):
        """Upload backup to Supabase Storage if configured."""
        try:
            from core.supabase_client import upload_file
            result = upload_file(file_path, folder="backups")
            if result.get("ok"):
                log.supabase_uploaded = True
                self.stdout.write(self.style.SUCCESS("Backup uploaded to Supabase"))
            else:
                log.supabase_uploaded = False
                log.supabase_error = result.get("error", "Unknown error")
                self.stderr.write(self.style.ERROR(f"Supabase upload failed: {log.supabase_error}"))
        except ImportError:
            log.supabase_error = "Supabase client not configured"
            self.stderr.write(self.style.WARNING("Supabase not configured. Skipping upload."))
        except Exception as e:
            log.supabase_error = str(e)
            self.stderr.write(self.style.ERROR(f"Supabase upload failed: {e}"))
