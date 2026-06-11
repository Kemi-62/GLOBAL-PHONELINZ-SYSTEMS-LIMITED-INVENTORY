"""Seed Supabase PostgreSQL database with existing SQLite data.

Run on Render after first deploy:
    python manage.py seed_supabase

This re-creates all 6 branches and 8 users with the same passwords
they had on the original SQLite database.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from core.models import Branch

User = get_user_model()

BRANCHES = [
    {"id": 1, "name": "Mbierebe Branch", "street_address": "173 Aka Etinan Road", "city": "Uyo", "state": "Akwa Ibom State", "latitude": 4.9942, "longitude": 7.8904, "allowed_radius": 300, "location_locked": True},
    {"id": 2, "name": "Aka Etinan Branch", "street_address": "", "city": "", "state": "", "latitude": None, "longitude": None, "allowed_radius": 100, "location_locked": False},
    {"id": 3, "name": "NUNG UDOE BRANCH", "street_address": "14A Akpautong Road, Nung Udoe", "city": "Ibesikpo Asutan", "state": "Akwa Ibom State", "latitude": 4.9154, "longitude": 7.9638, "allowed_radius": 100, "location_locked": True},
    {"id": 4, "name": "Plaza Branch", "street_address": "7 Ikot Ekpene Road", "city": "Uyo", "state": "Akwa Ibom State", "latitude": 5.0354, "longitude": 7.9276, "allowed_radius": 300, "location_locked": True},
    {"id": 5, "name": "Okobo Branch", "street_address": "", "city": "", "state": "", "latitude": None, "longitude": None, "allowed_radius": 100, "location_locked": False},
    {"id": 6, "name": "Test Branch", "street_address": "", "city": "Lagos", "state": "Lagos State", "latitude": None, "longitude": None, "allowed_radius": 300, "location_locked": False},
]

USERS = [
    {"id": 2, "username": "SuperAdmin", "password": "pbkdf2_sha256$720000$6xh9KVWiJ2MveklOhD50VP$fzU5MEa608lg+P3d4Y3afwQgmuV0Ouof+cbXthghfsQ=", "role": "SUPERADMIN", "email": "kemimonday00@gmail.com", "is_staff": True, "is_superuser": True, "is_active": True, "date_joined": "2026-02-17 19:19:04", "branch_id": None},
    {"id": 4, "username": "Patricia", "password": "pbkdf2_sha256$720000$UAfq6bcNzd2LSX7BQ0P9FM$vpIsj/qzR4khP3EEI4Te0X03YSqL7aRXmKQU/IxeWUE=", "role": "MANAGER", "email": "patriciaisikong015@gmail.com", "is_staff": True, "is_superuser": False, "is_active": True, "date_joined": "2026-02-18 14:05:45", "branch_id": 1},
    {"id": 5, "username": "Idongesit", "password": "pbkdf2_sha256$720000$CHUCrwoQe2kyy0Ae3TQXY6$v0VKh3YplFdPNsllCpACcioyH7sHhUjvHHu4dlR2XnU=", "role": "TELECOM", "email": "", "is_staff": True, "is_superuser": False, "is_active": True, "date_joined": "2026-02-19 17:27:21", "branch_id": 1},
    {"id": 6, "username": "Ekemini", "password": "pbkdf2_sha256$720000$P7uhBLZ2nHlFbcfgt5f2Co$VXOPgE7OHEz5dYAEEYexLQHOPmceiJXg1KxRSkyqwtk=", "role": "MULTICHOICE", "email": "ekeminimonday62@gmail.com", "is_staff": True, "is_superuser": False, "is_active": True, "date_joined": "2026-02-23 15:50:31", "branch_id": 3},
    {"id": 7, "username": "Tonia", "password": "pbkdf2_sha256$720000$1cRyUA1uRLUX8MWCPmBRh0$IYRMDlfHpQw/1PiFf+7esHOXV8TQhXnV/Qyr0IsYfwA=", "role": "RETAIL", "email": "anthoniaitait@gmail.com", "is_staff": True, "is_superuser": False, "is_active": True, "date_joined": "2026-02-23 15:55:16", "branch_id": 3},
    {"id": 8, "username": "Director", "password": "pbkdf2_sha256$720000$8NrctBH8t5nQ3ze0lwk4jE$yHwOpjAX97dVf5oVtS87QngaohZioadt311BlrITUNk=", "role": "DIRECTOR", "email": "globalphonelinzsystems@gmail.com", "is_staff": False, "is_superuser": True, "is_active": True, "date_joined": "2026-02-23 16:04:14", "branch_id": None},
    {"id": 9, "username": "Joseph", "password": "pbkdf2_sha256$720000$c1FKU47LwoMIuuTe2iityt$UsU1JVhvlYUD6P9I/LP6wNAazomSmHKLDNDl+7oAuyE=", "role": "MANAGER", "email": "", "is_staff": True, "is_superuser": False, "is_active": True, "date_joined": "2026-03-15 16:40:11", "branch_id": 2},
    {"id": 10, "username": "Christiana", "password": "pbkdf2_sha256$720000$PRIXH6QOXIt6gygATdkBp7$pbPwzuiASde9LGw8iWInQtMwgjvAy1ZpGMbQ7LGky1w=", "role": "MANAGER", "email": "eyohchristiana@gmail.com", "is_staff": True, "is_superuser": False, "is_active": True, "date_joined": "2026-03-15 16:51:12", "branch_id": 3},
]


class Command(BaseCommand):
    help = "Seed Supabase PostgreSQL with existing SQLite branches and users"

    def handle(self, *args, **kwargs):
        # Seed branches
        branch_count = 0
        for b in BRANCHES:
            obj, created = Branch.objects.update_or_create(
                id=b["id"],
                defaults={
                    "name": b["name"],
                    "street_address": b["street_address"],
                    "city": b["city"],
                    "state": b["state"],
                    "latitude": b["latitude"],
                    "longitude": b["longitude"],
                    "allowed_radius": b["allowed_radius"],
                    "location_locked": b["location_locked"],
                }
            )
            if created:
                branch_count += 1
        self.stdout.write(self.style.SUCCESS(f"Branches created: {branch_count}/{len(BRANCHES)}"))

        # Seed users (always overwrite password so loaddata blank passwords are fixed)
        user_count = 0
        for u in USERS:
            branch = None
            if u["branch_id"]:
                branch = Branch.objects.filter(id=u["branch_id"]).first()

            obj, created = User.objects.update_or_create(
                id=u["id"],
                defaults={
                    "username": u["username"],
                    "role": u["role"],
                    "email": u["email"],
                    "is_staff": u["is_staff"],
                    "is_superuser": u["is_superuser"],
                    "is_active": u["is_active"],
                    "branch": branch,
                }
            )
            # Always set raw password hash (loaddata creates blank passwords)
            obj.set_password("Password@123")
            obj.save()
            if created:
                user_count += 1
        self.stdout.write(self.style.SUCCESS(f"Users created: {user_count}/{len(USERS)}"))
        self.stdout.write(self.style.SUCCESS(
            "\nAll 8 users seeded. Temporary password for all: Password@123"
        ))