import os
import django

os.environ['DJANGO_SETTINGS_MODULE'] = 'django_project.settings'
django.setup()

from django.core.mail import send_mail
from django.conf import settings

try:
    result = send_mail(
        'GPSL Test Email',
        'This is a test to confirm SMTP works.',
        settings.DEFAULT_FROM_EMAIL,
        ['kemimonday00@gmail.com'],
        fail_silently=False,
    )
    print('Result:', result)
except Exception as e:
    print('ERROR:', e)
