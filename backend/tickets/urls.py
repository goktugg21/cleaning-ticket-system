from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    TicketAttachmentDownloadView,
    TicketAttachmentListCreateView,
    TicketAttachmentVisibilityView,
    TicketMessageListCreateView,
    TicketMessageRecipientsView,
    TicketViewSet,
)
from .views_manager_assignments import (
    TicketManagerAssignmentDeleteView,
    TicketManagerAssignmentListCreateView,
)
from .views_staff_assignments import (
    SlotCompletionRequirementsView,
    StaffAssignmentSlotAgendaView,
    TicketStaffAssignmentDetailView,
    TicketStaffAssignmentListCreateView,
)
from .views_staff_requests import StaffAssignmentRequestViewSet
from .views_work_plan import WorkPlanView
from .views_sub_tasks import (
    TicketSubTaskDetailView,
    TicketSubTaskListCreateView,
)


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

from .views_bulk_assign import (
    TicketAssignableUsersView,
    TicketBulkAssignView,
)
from .views_work_categories import (
    WorkCategoryDetailView,
    WorkCategoryListCreateView,
)

urlpatterns = [
    # Sprint 185 E §1 — the work-category catalog. Before the router for
    # the same reason `bulk-assign/` and `my-slots/` are: the router's
    # `<pk>` detail pattern would otherwise swallow the literal.
    path(
        "categories/",
        WorkCategoryListCreateView.as_view(),
        name="work-category-list",
    ),
    path(
        "categories/<int:category_id>/",
        WorkCategoryDetailView.as_view(),
        name="work-category-detail",
    ),
    # Sprint 158 §1 — bulk assign, and the picker's candidate read.
    # Before the router for the same reason `my-slots/` is: the router's
    # `<pk>` detail pattern would otherwise swallow the literal.
    path(
        "bulk-assign/",
        TicketBulkAssignView.as_view(),
        name="ticket-bulk-assign",
    ),
    path(
        "<int:pk>/assignments/candidates/",
        TicketAssignableUsersView.as_view(),
        name="ticket-assignment-candidates",
    ),
    # Sprint 14E — STAFF agenda of their own dated assignment slots.
    # Listed before the router so the `my-slots` literal is not eaten by
    # the router's `<pk>` detail pattern.
    path(
        "my-slots/",
        StaffAssignmentSlotAgendaView.as_view(),
        name="ticket-my-slots",
    ),
    # Sprint 179A — the Work Plan: one week, both sources, the §12B
    # placement rule and server-side counts. Before the router for the
    # same reason `my-slots/` is.
    path(
        "work-plan/",
        WorkPlanView.as_view(),
        name="ticket-work-plan",
    ),
    path(
        "<int:ticket_id>/attachments/<int:attachment_id>/download/",
        TicketAttachmentDownloadView.as_view(),
        name="ticket-attachment-download",
    ),
    # Sprint 191 §2.5 — promote one attachment across the customer wall
    # (provider management only). Before the list route for the same
    # reason the download route is: a longer, more specific path.
    path(
        "<int:ticket_id>/attachments/<int:attachment_id>/visibility/",
        TicketAttachmentVisibilityView.as_view(),
        name="ticket-attachment-visibility",
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
    # M1 B3 — directed-recipients picker source for the composer.
    path(
        "<int:ticket_id>/message-recipients/",
        TicketMessageRecipientsView.as_view(),
        name="ticket-message-recipients",
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
    # W3-G — what this slot must carry before it can be reported done,
    # so the completion dialog can say so before the worker fills it in.
    # Read-only; the serializer on the PATCH above is still the gate.
    path(
        "<int:ticket_id>/staff-assignments/<int:assignment_id>/"
        "completion-requirements/",
        SlotCompletionRequirementsView.as_view(),
        name="ticket-slot-completion-requirements",
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
    # Sprint 4 — SubTask CRUD nested under the ticket (same hand-mounted
    # shape as the staff-assignment endpoints; keyed by the sub-task's own
    # id on the detail route).
    path(
        "<int:ticket_id>/sub-tasks/",
        TicketSubTaskListCreateView.as_view(),
        name="ticket-sub-tasks",
    ),
    path(
        "<int:ticket_id>/sub-tasks/<int:sub_task_id>/",
        TicketSubTaskDetailView.as_view(),
        name="ticket-sub-task-detail",
    ),
] + router.urls
