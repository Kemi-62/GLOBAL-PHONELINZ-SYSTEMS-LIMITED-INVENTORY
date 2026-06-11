"""
Force connect to Supabase and reset all passwords.
Run with: python /home/runner/workspace/run_seed.py
"""
import os

# Force these BEFORE django loads - overrides everything in settings.py
os.environ['DATABASE_URL'] = 'postgresql://postgres.fnpjxcbraxkltdtaoiqq:Minak6462Gpsl@aws-0-eu-west-1.pooler.supabase.com:5432/postgres'
os.environ['DJANGO_SETTINGS_MODULE'] = 'django_project.settings'
os.environ['RENDER'] = 'true'  # Tricks settings.py into using the DATABASE_URL above

import django
django.setup()

from django.db import connection

# Confirm we are on Supabase
host = connection.settings_dict.get('HOST', '')
print(f"Connected to: {host}")
if 'supabase' not in host and 'pooler' not in host:
    print("ERROR: Still not on Supabase. Check your DATABASE_URL above.")
    exit(1)

from django.contrib.auth import get_user_model
from core.models import Branch

User = get_user_model()

print(f"\nUsers found: {User.objects.count()}")
print(f"Branches found: {Branch.objects.count()}")

# Reset all user passwords
print("\nResetting passwords...")
for u in User.objects.all():
    u.set_password('Password@123')
    u.failed_login_count = 0
    u.is_locked = False
    u.save()
    print(f"  Reset: {u.username} ({u.role})")

print("\nDone. All users can now log in with: Password@123")
print("\nLogin credentials:")
for u in User.objects.all():
    print(f"  {u.username} / Password@123  [{u.role}]")