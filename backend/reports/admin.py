"""W4-R — the Django admin for the per-person hourly rate.

The Django admin is a SUPER_ADMIN / platform surface (`is_staff`), not
the operator UI: a COMPANY_ADMIN sets rates through
`/api/reports/employee-hourly-rates/` and the screen over it. This
registration exists for the same reason the other platform-level ones
do — a support case where somebody has to look at the stored row and
its history without going through the app.

It is deliberately READ-MOSTLY in shape: `created_by`, `created_at` and
`updated_at` are not editable here, so a row written through the admin
still records who wrote it (`save_model` below) rather than leaving the
author blank.
"""
from django.contrib import admin

from .models import EmployeeHourlyRate


@admin.register(EmployeeHourlyRate)
class EmployeeHourlyRateAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "company",
        "hourly_rate",
        "valid_from",
        "created_by",
        "created_at",
    )
    # `valid_from` descending is the reading order of a rate history:
    # what is it now, and what was it before.
    ordering = ("company", "employee", "-valid_from")
    list_filter = ("company",)
    search_fields = ("employee__full_name", "employee__email", "note")
    list_select_related = ("employee", "company", "created_by")
    autocomplete_fields = ("employee", "company", "created_by")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "valid_from"

    def save_model(self, request, obj, form, change):
        # A rate written here still names its author. Without this the
        # PROTECT'd FK would simply refuse the save, which is a worse
        # answer than recording the admin who typed it.
        if obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
