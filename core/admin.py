from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Branch, ServiceTarget, ServiceActivity, DeviceTag, MultiChoiceSale

@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    list_display = ("username", "role", "branch")
    list_filter = ("role", "branch")
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

# admin.site.register(User, CustomUserAdmin)
admin.site.register(Branch)
admin.site.register(ServiceTarget)
admin.site.register(ServiceActivity)
admin.site.register(DeviceTag)
admin.site.register(MultiChoiceSale)
