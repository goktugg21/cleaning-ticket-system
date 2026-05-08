from rest_framework import mixins, viewsets

from accounts.permissions import IsSuperAdmin

from .filters import AuditLogFilter
from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Read-only super-admin-only audit log feed.

    GET /api/audit-logs/?target_model=accounts.User&target_id=42&actor=1
                       &date_from=2026-05-01&date_to=2026-05-08

    No detail / create / update / delete endpoints are exposed — audit
    rows are immutable once written. The viewset uses ListModelMixin
    only; mixins.RetrieveModelMixin is intentionally NOT inherited so
    /api/audit-logs/<id>/ returns 404.
    """

    queryset = AuditLog.objects.select_related("actor").all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsSuperAdmin]
    filterset_class = AuditLogFilter
    ordering = ["-created_at"]
