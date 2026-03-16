import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'My_project.settings')
django.setup()

from django.contrib.auth.models import User

# Create superuser
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@company.com', 'admin123')
    print("✅ Admin created!")
else:
    print("Admin already exists")

# Create staff users
staff_users = [
    {'username': 'staff1', 'email': 'staff1@company.com', 'password': 'staff123'},
    {'username': 'staff2', 'email': 'staff2@company.com', 'password': 'staff123'},
]

for staff in staff_users:
    if not User.objects.filter(username=staff['username']).exists():
        User.objects.create_user(**staff)
        print(f"✅ {staff['username']} created!")