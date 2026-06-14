"""One-step command: create schema in Supabase + sync all data from SQLite.

Usage: python manage.py setup_supabase --host=db.xxx.supabase.co --password=your-password

What it does:
  1. Connects to Supabase PostgreSQL
  2. Runs Django migrations (creates all tables)
  3. Copies every row from SQLite to PostgreSQL
  4. Resets auto-increment sequences

After running this, your Supabase database has the same data as Replit.
Just deploy to Render with DB_ENGINE=postgresql.
"""
import os
import sys
import sqlite3
import psycopg2
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Create Supabase schema + sync all SQLite data in one step"

    def add_arguments(self, parser):
        parser.add_argument("--host", required=True, help="Supabase host (e.g., db.xxx.supabase.co)")
        parser.add_argument("--password", required=True, help="Supabase database password")
        parser.add_argument("--user", default="postgres", help="User (default: postgres)")
        parser.add_argument("--dbname", default="postgres", help="DB name (default: postgres)")
        parser.add_argument("--port", default="6543", help="Port (default: 6543 for Supabase pooler, use 5432 for direct)")

    def handle(self, *args, **options):
        host = options["host"]
        password = options["password"]
        user = options["user"]
        dbname = options["dbname"]
        port = options["port"]

        # Build connection string
        pg_url = f"postgresql://{user}:{password}@{host}:{port}/{dbname}?sslmode=require"

        self.stdout.write("=" * 60)
        self.stdout.write("STEP 1: Run migrations on Supabase")
        self.stdout.write("=" * 60)

        # Temporarily override DATABASES to point to PostgreSQL
        original_databases = settings.DATABASES.copy()
        settings.DATABASES["default"] = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": dbname,
            "USER": user,
            "PASSWORD": password,
            "HOST": host,
            "PORT": port,
            "OPTIONS": {"sslmode": "require"},
        }

        # Create tables via migrations
        try:
            call_command("migrate", verbosity=1)
            self.stdout.write(self.style.SUCCESS("Migrations complete."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Migration failed: {e}"))
            settings.DATABASES = original_databases
            return

        # Restore original SQLite config
        settings.DATABASES = original_databases

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("STEP 2: Sync SQLite data to Supabase")
        self.stdout.write("=" * 60)

        sqlite_path = settings.DATABASES.get("default", {}).get("NAME", "db.sqlite3")
        sqlite_conn = sqlite3.connect(str(sqlite_path))
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cur = sqlite_conn.cursor()

        pg_conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password, sslmode="require")
        pg_cur = pg_conn.cursor()

        sqlite_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [row[0] for row in sqlite_cur.fetchall()]
        total_rows = 0

        for table in tables:
            try:
                sqlite_cur.execute(f"PRAGMA table_info({table})")
                cols = [row[1] for row in sqlite_cur.fetchall()]
                if not cols:
                    continue

                sqlite_cur.execute(f"SELECT * FROM {table}")
                rows = sqlite_cur.fetchall()
                count = len(rows)

                if count == 0:
                    self.stdout.write(f"  {table}: 0 rows — skipped")
                    continue

                # Truncate then insert
                pg_cur.execute(f"TRUNCATE TABLE {table} CASCADE")
                col_str = ", ".join(f'"{c}"' for c in cols)
                placeholders = ", ".join(["%s"] * len(cols))
                insert_sql = f'INSERT INTO {table} ({col_str}) VALUES ({placeholders})'

                batch_size = 500
                for i in range(0, count, batch_size):
                    batch = rows[i:i+batch_size]
                    pg_cur.executemany(insert_sql, batch)
                    pg_conn.commit()

                # Reset sequence
                if "id" in cols:
                    try:
                        pg_cur.execute(f"SELECT setval('{table}_id_seq', (SELECT MAX(id) FROM {table}), true)")
                        pg_conn.commit()
                    except:
                        pass

                self.stdout.write(self.style.SUCCESS(f"  {table}: {count} rows synced"))
                total_rows += count

            except Exception as e:
                self.stderr.write(self.style.ERROR(f"  {table}: {e}"))
                pg_conn.rollback()

        pg_conn.close()
        sqlite_conn.close()

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS(f"DONE! {total_rows:,} rows synced to Supabase."))
        self.stdout.write("=" * 60)
        self.stdout.write("\nRender Environment Variables to add:")
        self.stdout.write(f"  DB_ENGINE=postgresql")
        self.stdout.write(f"  DB_NAME={dbname}")
        self.stdout.write(f"  DB_USER={user}")
        self.stdout.write(f"  DB_PASSWORD={password}")
        self.stdout.write(f"  DB_HOST={host}")
        self.stdout.write("\nRender Build Command:")
        self.stdout.write("  pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate")
