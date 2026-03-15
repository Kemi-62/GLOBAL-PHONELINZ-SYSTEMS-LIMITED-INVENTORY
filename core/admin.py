from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import *

@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    list_display = ("username", "role", "branch", "is_locked")
    list_filter = ("role", "branch", "is_locked")
    search_fields = ("username", "email")
    fieldsets = BaseUserAdmin.fieldsets + (
        ('GPSL Info', {
            'fields': ('role', 'branch', 'failed_login_count', 'is_locked'),
        }),
    )

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("model_name", "product_name", "cost_price", "selling_price", "imei_serial")
    list_filter = ("subcategory__category",)
    search_fields = ("model_name", "product_name", "imei_serial")
    readonly_fields = ("imei_serial",)

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "latitude", "longitude", "allowed_radius", "location_locked")
    search_fields = ("name",)

@admin.register(RetailSale)
class RetailSaleAdmin(admin.ModelAdmin):
    list_display = ("product", "staff", "quantity", "selling_price", "date", "payment_method")
    list_filter = ("date", "branch", "payment_method")
    search_fields = ("staff__username", "product__model_name")
    readonly_fields = ("date", "time")

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("user", "branch", "check_in_time", "is_late", "is_absent", "date")
    list_filter = ("date", "is_late", "is_absent", "branch")
    search_fields = ("user__username",)
    readonly_fields = ("date", "check_in_time", "distance_from_branch")

@admin.register(DirectorSafeStock)
class DirectorSafeStockAdmin(admin.ModelAdmin):
    list_display = ("product", "quantity", "date_added")
    search_fields = ("product__model_name",)
    readonly_fields = ("date_added",)

@admin.register(BranchSafeStock)
class BranchSafeStockAdmin(admin.ModelAdmin):
    list_display = ("branch", "product", "quantity")
    list_filter = ("branch",)
    search_fields = ("product__model_name",)

@admin.register(ServiceActivity)
class ServiceActivityAdmin(admin.ModelAdmin):
    list_display = ("staff", "branch", "service_type", "quantity", "date")
    list_filter = ("date", "branch", "service_type")
    search_fields = ("staff__username",)

# Simple registrations
admin.site.register(ServiceTarget)
admin.site.register(DeviceTag)
admin.site.register(MultiChoiceSale)
admin.site.register(RetailCategory)
admin.site.register(RetailSubCategory)
admin.site.register(RetailSubSubCategory)
admin.site.register(StaffStock)
admin.site.register(Expense)
admin.site.register(StockRequest)
admin.site.register(MultiChoiceWeeklyReport)
admin.site.register(StockMovement)
