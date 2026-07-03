import os
import django
os.environ['DJANGO_SETTINGS_MODULE'] = 'django_project.settings'
django.setup()
from django.conf import settings
print('STATICFILES_DIRS:', settings.STATICFILES_DIRS)
print('STATIC_ROOT:', settings.STATIC_ROOT)
print('BASE_DIR:', settings.BASE_DIR)
