from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import transaction

User = get_user_model()

class Command(BaseCommand):
    help = "Create groups/roles and sync users to their role group"

    @transaction.atomic
    def handle(self, *args, **options):
        all_perms = Permission.objects.all()
        core_perms = Permission.objects.filter(content_type__app_label="core")
        core_view_perms = Permission.objects.filter(
            content_type__app_label="core",
            codename__startswith="view_",
        )

        role_policies = {
            "Admin": all_perms,
            "Manager": core_perms,
            "Staff": core_view_perms,
        }

        for role_name, perms in role_policies.items():
            group, _ = Group.objects.get_or_create(name=role_name)
            group.permissions.set(perms)

        synced = 0
        for user in User.objects.all():
            role_value = (getattr(user, "role", "") or "").strip()
            if not role_value:
                user.groups.clear()
                continue

            group, _ = Group.objects.get_or_create(name=role_value)
            if role_value in role_policies:
                group.permissions.set(role_policies[role_value])

            user.groups.set([group])
            synced += 1

        self.stdout.write(self.style.SUCCESS(f"Roles synced for {synced} users"))