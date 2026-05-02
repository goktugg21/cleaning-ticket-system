from django.contrib import admin

from .models import Customer, CustomerUserMembership


class CustomerUserMembershipInline(admin.TabularInline):
    model = CustomerUserMembership
    extra = 1


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "building", "contact_email", "language", "is_active")
    list_filter = ("company", "building", "language", "is_active")
    search_fields = ("name", "contact_email", "phone")
    inlines = [CustomerUserMembershipInline]


@admin.register(CustomerUserMembership)
class CustomerUserMembershipAdmin(admin.ModelAdmin):
    list_display = ("customer", "user", "created_at")
    list_filter = ("customer__company", "customer__building")
    search_fields = ("customer__name", "user__email", "user__full_name")
