from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    TicketAttachmentDownloadView,
    TicketAttachmentListCreateView,
    TicketMessageListCreateView,
    TicketViewSet,
)
from .views_staff_requests import StaffAssignmentRequestViewSet


router = DefaultRouter()
router.register(r"", TicketViewSet, basename="ticket")

# Sprint 23A — staff-initiated assignment requests live under
# `/api/staff-assignment-requests/`. Mounted on its own router so
# the path is independent of the tickets router prefix.
staff_request_router = DefaultRouter()
staff_request_router.register(
    r"staff-assignment-requests",
    StaffAssignmentRequestViewSet,
    basename="staff-assignment-request",
)

urlpatterns = [
    path(
        "<int:ticket_id>/attachments/<int:attachment_id>/download/",
        TicketAttachmentDownloadView.as_view(),
        name="ticket-attachment-download",
    ),
    path(
        "<int:ticket_id>/attachments/",
        TicketAttachmentListCreateView.as_view(),
        name="ticket-attachments",
    ),
    path(
        "<int:ticket_id>/messages/",
        TicketMessageListCreateView.as_view(),
        name="ticket-messages",
    ),
] + router.urls
