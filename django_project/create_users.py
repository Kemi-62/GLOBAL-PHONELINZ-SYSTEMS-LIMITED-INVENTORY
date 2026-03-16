import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'My_project.settings')
django.setup()

from django.contrib.auth.models import User

# Create superuser (same as your Replit one)
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('SuperAdmin', 'admin@company.com', 'Password@123')
    print("✅ Admin user created!")

# Create staff users
staff_list = [
    {'username': 'staff1', 'email': 'staff1@company.com', 'password': 'staff123'},
    {'username': 'staff2', 'email': 'staff2@company.com', 'password': 'staff123'},
    {'username': 'staff3', 'email': 'staff3@company.com', 'password': 'staff123'},
]

for staff in staff_list:
    if not User.objects.filter(username=staff['username']).exists():
        User.objects.create_user(**staff)
        print(f"✅ {staff['username']} created!")