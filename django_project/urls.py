from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static
from core import views as core_views

admin_url = getattr(settings, 'ADMIN_URL', 'admin/').rstrip('/') + '/'

urlpatterns = [
    path(admin_url, admin.site.urls),
    path('favicon.ico', RedirectView.as_view(url='/static/img/favicon.ico', permanent=False)),
    path('accounts/login/', core_views.custom_login, name='account_login'),
    path('', include('core.urls')),
]

# Serve media files in ALL environments (development and production)
# This is needed for selfie images to display in the dashboard
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
