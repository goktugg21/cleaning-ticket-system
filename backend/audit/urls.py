from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AuditLogViewSet
from .views_ticket_timeline import TicketAuditTimelineView


router = DefaultRouter()
router.register(r"audit-logs", AuditLogViewSet, basename="audit-log")

# Sprint 14A — unified read-only ticket audit timeline. Non-router path so
# the existing SUPER_ADMIN-only AuditLogViewSet is untouched.
urlpatterns = router.urls + [
    path(
        "audit/tickets/<int:ticket_id>/timeline/",
        TicketAuditTimelineView.as_view(),
        name="ticket-audit-timeline",
    ),
]
