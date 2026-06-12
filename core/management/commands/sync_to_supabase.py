"""Management command: sync SQLite data to Supabase PostgreSQL.

Usage: python manage.py sync_to_supabase --host=db.xxx.supabase.co --password=your-password

This command copies ALL data from the current SQLite database to Supabase PostgreSQL.
You must create a Supabase project first, then run this command.

Steps:
1. Create project at supabase.com
2. Go to Database → Settings → Database → copy the connection string
3. Run this command with your connection details
4. Set DB_ENGINE=postgresql in Render environment variables
"""
import sqlite3
import psycopg2
from psycopg2.extras import execute_values
from django.core.management.base import BaseCommand
from django.conf import settings
from django.apps import apps


class Command(BaseCommand):
    help = "Sync SQLite data to Supabase PostgreSQL"

    def add_arguments(self, parser):
        parser.add_argument("--host", required=True, help="Supabase host (e.g., db.xxx.supabase.co)")
        parser.add_argument("--password", required=True, help="Supabase database password")
        parser.add_argument("--user", default="postgres", help="Database user (default: postgres)")
        parser.add_argument("--dbname", default="postgres", help="Database name (default: postgres)")
        parser.add_argument("--port", default="5432", help="Port (default: 5432)")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
        parser.add_argument("--table", default="", help="Sync only one table (e.g., core_user)")

    def handle(self, *args, **options):
        host = options["host"]
        password = options["password"]
        user = options["user"]
        dbname = options["dbname"]
        port = options["port"]
        dry_run = options["dry_run"]
        single_table = options["table"]

        # Get SQLite path
        sqlite_path = settings.DATABASES.get("default", {}).get("NAME", "db.sqlite3")
        self.stdout.write(f"SQLite source: {sqlite_path}")
        self.stdout.write(f"Supabase target: {user}@{host}:{port}/{dbname}")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no data will be written"))

        # Connect
        pg_conn = psycopg2.connect(
            host=host, port=port, dbname=dbname, user=user, password=password,
            sslmode="require"
        )
        pg_cur = pg_conn.cursor()

        sqlite_conn = sqlite3.connect(str(sqlite_path))
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cur = sqlite_conn.cursor()

        # Get all tables from SQLite
        sqlite_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [row[0] for row in sqlite_cur.fetchall()]

        if single_table:
            tables = [t for t in tables if t == single_table]
            if not tables:
                self.stderr.write(self.style.ERROR(f"Table '{single_table}' not found in SQLite"))
                return

        for table in tables:
            try:
                # Get column names from SQLite
                sqlite_cur.execute(f"PRAGMA table_info({table})")
                cols = [row[1] for row in sqlite_cur.fetchall()]
                if not cols:
                    continue

                # Read data from SQLite
                sqlite_cur.execute(f"SELECT * FROM {table}")
                rows = sqlite_cur.fetchall()
                count = len(rows)

                if count == 0:
                    self.stdout.write(f"  {table}: 0 rows — skipped")
                    continue

                self.stdout.write(f"  {table}: {count} rows")

                if dry_run:
                    continue

                # Truncate PostgreSQL table
                pg_cur.execute(f"TRUNCATE TABLE {table} CASCADE")

                # Build INSERT
                col_str = ", ".join(f'"{c}"' for c in cols)
                placeholders = ", ".join(["%s"] * len(cols))
                insert_sql = f'INSERT INTO {table} ({col_str}) VALUES ({placeholders})'

                # Insert in batches
                batch_size = 500
                for i in range(0, count, batch_size):
                    batch = rows[i:i+batch_size]
                    pg_cur.executemany(insert_sql, batch)
                    pg_conn.commit()

                # Reset sequence if id column exists
                if "id" in cols:
                    pg_cur.execute(f"SELECT setval('{table}_id_seq', (SELECT MAX(id) FROM {table}), true)")
                    pg_conn.commit()

                self.stdout.write(self.style.SUCCESS(f"    ✓ {table}: synced {count} rows"))

            except Exception as e:
                self.stderr.write(self.style.ERROR(f"    ✗ {table}: {e}"))
                pg_conn.rollback()

        pg_conn.close()
        sqlite_conn.close()
        self.stdout.write(self.style.SUCCESS("\nSync complete!"))
        self.stdout.write("\nNext steps:")
        self.stdout.write("  1. Set DB_ENGINE=postgresql in your environment")
        self.stdout.write("  2. Add DB_HOST, DB_NAME, DB_USER, DB_PASSWORD to your environment")
        self.stdout.write("  3. Deploy to Render — your data is already in Supabase")
