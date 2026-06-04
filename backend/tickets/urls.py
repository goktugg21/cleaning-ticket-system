from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    TicketAttachmentDownloadView,
    TicketAttachmentListCreateView,
    TicketMessageListCreateView,
    TicketViewSet,
)
from .views_manager_assignments import (
    TicketManagerAssignmentDeleteView,
    TicketManagerAssignmentListCreateView,
)
from .views_staff_assignments import (
    StaffAssignmentSlotAgendaView,
    TicketStaffAssignmentDetailView,
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
    # Sprint 14E — STAFF agenda of their own dated assignment slots.
    # Listed before the router so the `my-slots` literal is not eaten by
    # the router's `<pk>` detail pattern.
    path(
        "my-slots/",
        StaffAssignmentSlotAgendaView.as_view(),
        name="ticket-my-slots",
    ),
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
    # Multi-slot per staff — keyed by the slot's OWN id (assignment id),
    # not by user_id: a staff member can hold several slots on one ticket,
    # so user_id no longer identifies a single row.
    path(
        "<int:ticket_id>/staff-assignments/<int:assignment_id>/",
        TicketStaffAssignmentDetailView.as_view(),
        name="ticket-staff-assignment-detail",
    ),
    # Sprint 10B — explicit per-ticket responsible-manager M:N. Same
    # hand-mounted shape as the staff-assignment endpoints above (the
    # DELETE `<user_id>` path arg is awkward through a DRF action).
    path(
        "<int:ticket_id>/manager-assignments/",
        TicketManagerAssignmentListCreateView.as_view(),
        name="ticket-manager-assignments",
    ),
    path(
        "<int:ticket_id>/manager-assignments/<int:user_id>/",
        TicketManagerAssignmentDeleteView.as_view(),
        name="ticket-manager-assignment-delete",
    ),
] + router.urls
