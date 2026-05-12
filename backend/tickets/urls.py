from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    TicketAttachmentDownloadView,
    TicketAttachmentListCreateView,
    TicketMessageListCreateView,
    TicketViewSet,
)
from .views_staff_assignments import (
    TicketStaffAssignmentDeleteView,
    TicketStaffAssignmentListCreateView,
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
    # Sprint 25A — admin/manager direct staff assignment endpoints.
    # `GET /<id>/assignable-staff/` lives on the viewset as a DRF
    # `@action` so the URL is auto-registered via the router; the
    # add/remove endpoints below are hand-mounted because DELETE's
    # `<user_id>` path arg is awkward to express through DRF actions.
    path(
        "<int:ticket_id>/staff-assignments/",
        TicketStaffAssignmentListCreateView.as_view(),
        name="ticket-staff-assignments",
    ),
    path(
        "<int:ticket_id>/staff-assignments/<int:user_id>/",
        TicketStaffAssignmentDeleteView.as_view(),
        name="ticket-staff-assignment-delete",
    ),
] + router.urls
