from django.contrib import admin

from .models import Ticket, TicketAttachment, TicketMessage, TicketStatusHistory


class TicketMessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0
    readonly_fields = ("created_at",)


class TicketAttachmentInline(admin.TabularInline):
    model = TicketAttachment
    extra = 0
    readonly_fields = ("created_at",)


class TicketStatusHistoryInline(admin.TabularInline):
    model = TicketStatusHistory
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("ticket_no", "title", "company", "building", "customer", "type", "priority", "status", "created_at")
    list_filter = ("company", "building", "customer", "type", "priority", "status")
    search_fields = ("ticket_no", "title", "description", "room_label")
    readonly_fields = ("ticket_no", "created_at", "updated_at")
    inlines = [TicketMessageInline, TicketAttachmentInline, TicketStatusHistoryInline]


@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    list_display = ("ticket", "author", "message_type", "is_hidden", "created_at")
    list_filter = ("message_type", "is_hidden", "created_at")
    search_fields = ("ticket__ticket_no", "author__email", "message")


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "original_filename", "mime_type", "file_size", "uploaded_by", "created_at")
    list_filter = ("mime_type", "created_at")
    search_fields = ("ticket__ticket_no", "original_filename")


@admin.register(TicketStatusHistory)
class TicketStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("ticket", "old_status", "new_status", "changed_by", "created_at")
    list_filter = ("old_status", "new_status", "created_at")
    search_fields = ("ticket__ticket_no", "changed_by__email", "note")
