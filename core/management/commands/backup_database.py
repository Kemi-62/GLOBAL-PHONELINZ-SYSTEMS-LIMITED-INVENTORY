"""Management command: backup SQLite database and email it.

Usage: python manage.py backup_database --trigger=manual
       python manage.py backup_database --send-email=your@email.com
       python manage.py backup_database --upload-supabase
"""
import os, shutil
from pathlib import Path
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.conf import settings
from django.utils import timezone
from core.models import BackupLog


class Command(BaseCommand):
    help = "Backup the SQLite database to a file and optionally email it."

    def add_arguments(self, parser):
        parser.add_argument("--trigger", default="manual", help="Who triggered: auto, manual, cron")
        parser.add_argument("--send-email", default="", help="Email address to send backup to")
        parser.add_argument("--upload-supabase", action="store_true", help="Upload backup to Supabase Storage")

    def handle(self, *args, **options):
        db_path = settings.DATABASES.get("default", {}).get("NAME", "db.sqlite3")
        if not os.path.exists(db_path):
            self.stderr.write(self.style.ERROR(f"Database not found: {db_path}"))
            return

        # Create backup dir
        backup_dir = Path("backups")
        backup_dir.mkdir(exist_ok=True)

        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"gpsl_backup_{timestamp}.db"

        shutil.copy2(db_path, backup_file)
        file_size = backup_file.stat().st_size

        log = BackupLog.objects.create(
            triggered_by=options["trigger"],
            status="SUCCESS",
            file_path=str(backup_file),
            file_size_bytes=file_size,
        )

        self.stdout.write(self.style.SUCCESS(f"Backup created: {backup_file} ({file_size:,} bytes)"))

        # Email backup
        email_to = options["send_email"] or getattr(settings, "EMAIL_HOST_USER", "")
        if email_to and settings.EMAIL_HOST_USER:
            try:
                subject = f"GPSL ERP Database Backup - {timezone.now().strftime('%d %b %Y %H:%M')}"
                dt = timezone.now().strftime('%d %b %Y %H:%M')
                size_kb = file_size / 1024
                body = (
                    f"Hello,\n\n"
                    f"Your GPSL ERP database has been backed up automatically.\n\n"
                    f"Backup details:\n"
                    f"- Date: {dt}\n"
                    f"- File size: {size_kb:.1f} KB\n"
                    f"- Records: This backup contains all your ERP data.\n\n"
                    f"To restore:\n"
                    f"1. Download this .db file\n"
                    f"2. On your server, replace the existing db.sqlite3 with this file\n"
                    f"3. Restart the application\n\n"
                    f"This is an automated backup. Keep this file safe.\n\n"
                    f"- GPSL ERP System"
                )
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

        # Upload to Supabase
        if options["upload_supabase"]:
            self._upload_to_supabase(str(backup_file), log)

        log.completed_at = timezone.now()
        log.save()

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
