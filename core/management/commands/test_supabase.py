"""Test Supabase PostgreSQL connection.

Usage: python manage.py test_supabase --host=db.xxx.supabase.co --password=your-password
"""
import psycopg2
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Test connection to Supabase PostgreSQL"

    def add_arguments(self, parser):
        parser.add_argument("--host", required=True, help="Supabase host")
        parser.add_argument("--password", required=True, help="Password")
        parser.add_argument("--user", default="postgres", help="User (default: postgres)")
        parser.add_argument("--dbname", default="postgres", help="DB name (default: postgres)")
        parser.add_argument("--port", default="5432", help="Port (default: 5432)")

    def handle(self, *args, **options):
        try:
            conn = psycopg2.connect(
                host=options["host"],
                port=options["port"],
                dbname=options["dbname"],
                user=options["user"],
                password=options["password"],
                sslmode="require",
            )
            cur = conn.cursor()
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'")
            table_count = cur.fetchone()[0]
            conn.close()
            self.stdout.write(self.style.SUCCESS("Connected!"))
            self.stdout.write(f"PostgreSQL version: {version}")
            self.stdout.write(f"Tables in public schema: {table_count}")
            self.stdout.write("\nYou can now run:")
            self.stdout.write("  python manage.py sync_to_supabase --host=... --password=...")
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Connection failed: {e}"))
