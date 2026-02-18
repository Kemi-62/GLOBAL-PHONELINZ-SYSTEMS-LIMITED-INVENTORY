from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Branch, ServiceTarget, ServiceActivity, DeviceTag

class CustomUserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Additional Info', {
            'fields': ('role', 'branch'),
        }),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('Additional Info', {
            'fields': ('role', 'branch'),
        }),
    )

admin.site.register(User, CustomUserAdmin)
admin.site.register(Branch)
admin.site.register(ServiceTarget)
admin.site.register(ServiceActivity)
admin.site.register(DeviceTag)
