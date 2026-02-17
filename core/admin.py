from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Branch, ServiceTarget, ServiceActivity, DeviceTag

# Register Custom User
admin.site.register(User, UserAdmin)

# Register other models
admin.site.register(Branch)
admin.site.register(ServiceTarget)
admin.site.register(ServiceActivity)
admin.site.register(DeviceTag)
