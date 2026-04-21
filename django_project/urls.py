from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from core import views as core_views
 
urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', core_views.custom_login, name='account_login'),
    path('', include('core.urls')),
]