from django.contrib import admin

from .models import Building, BuildingManagerAssignment


class BuildingManagerAssignmentInline(admin.TabularInline):
    model = BuildingManagerAssignment
    extra = 1


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "city", "country", "is_active")
    list_filter = ("company", "city", "country", "is_active")
    search_fields = ("name", "address", "city", "country", "postal_code")
    inlines = [BuildingManagerAssignmentInline]


@admin.register(BuildingManagerAssignment)
class BuildingManagerAssignmentAdmin(admin.ModelAdmin):
    list_display = ("building", "user", "assigned_at")
    list_filter = ("building__company",)
    search_fields = ("building__name", "user__email", "user__full_name")
