from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .invitations import Invitation
from .models import LoginLog, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    model = User
    list_display = ("email", "full_name", "role", "language", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff", "language")
    search_fields = ("email", "full_name")
    ordering = ("email",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("full_name", "language")}),
        ("Access", {"fields": ("role",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Soft delete", {"fields": ("deleted_at", "deleted_by")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "role", "language", "password1", "password2"),
            },
        ),
    )


@admin.register(LoginLog)
class LoginLogAdmin(admin.ModelAdmin):
    list_display = ("email", "user", "ip_address", "success", "created_at")
    list_filter = ("success", "created_at")
    search_fields = ("email", "user__email", "ip_address", "user_agent")
    readonly_fields = ("created_at",)


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "role", "created_by", "created_at", "expires_at", "accepted_at", "revoked_at")
    list_filter = ("role", "created_at", "accepted_at", "revoked_at")
    search_fields = ("email", "full_name", "created_by__email")
    readonly_fields = ("token_hash", "created_at", "accepted_at", "accepted_by", "revoked_at", "revoked_by")
    filter_horizontal = ("companies", "buildings", "customers")
