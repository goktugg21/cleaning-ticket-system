from django.contrib import admin

from .models import NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = (
        "event_type",
        "recipient_email",
        "ticket",
        "status",
        "triggered_by",
        "sent_at",
        "created_at",
    )
    list_filter = ("event_type", "status", "created_at", "sent_at")
    search_fields = (
        "recipient_email",
        "subject",
        "body",
        "ticket__ticket_no",
        "ticket__title",
    )
    readonly_fields = (
        "ticket",
        "recipient_user",
        "triggered_by",
        "recipient_email",
        "event_type",
        "subject",
        "body",
        "status",
        "error_message",
        "sent_at",
        "created_at",
    )
