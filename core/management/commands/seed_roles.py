"""Seed initial roles and a default superuser if none exist.

Run via: python manage.py seed_roles
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from core.models import Branch

User = get_user_model()


class Command(BaseCommand):
    help = "Seed default branch and superuser if none exist"

    def handle(self, *args, **kwargs):
        # Create a default branch if none exist
        if not Branch.objects.exists():
            Branch.objects.create(
                name="Head Office",
                city="Lagos",
                state="Lagos State",
                latitude=6.5244,
                longitude=3.3792,
            )
            self.stdout.write(self.style.SUCCESS("Default branch created"))
        else:
            self.stdout.write(self.style.NOTICE("Branches already exist"))

        # Create a default superuser if none exist
        if not User.objects.filter(role=User.SUPERADMIN).exists():
            from django.utils.crypto import get_random_string
            password = get_random_string(length=12)
            user = User.objects.create_superuser(
                username="admin",
                email="admin@gpsl.ng",
                password=password,
                role="SUPERADMIN",
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Superuser created: username=admin, password={password}\n"
                    "Please change this password immediately after first login!"
                )
            )
        else:
            self.stdout.write(self.style.NOTICE("Superuser already exists"))
