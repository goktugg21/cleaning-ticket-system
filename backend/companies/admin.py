from django.contrib import admin

from .models import Company, CompanyUserMembership


class CompanyUserMembershipInline(admin.TabularInline):
    model = CompanyUserMembership
    extra = 1


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "default_language", "is_active", "created_at")
    list_filter = ("is_active", "default_language")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [CompanyUserMembershipInline]


@admin.register(CompanyUserMembership)
class CompanyUserMembershipAdmin(admin.ModelAdmin):
    list_display = ("company", "user", "created_at")
    list_filter = ("company",)
    search_fields = ("company__name", "user__email", "user__full_name")
