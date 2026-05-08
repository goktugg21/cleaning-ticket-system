import django_filters

from .models import AuditLog


class AuditLogFilter(django_filters.FilterSet):
    target_model = django_filters.CharFilter(field_name="target_model", lookup_expr="exact")
    target_id = django_filters.NumberFilter(field_name="target_id", lookup_expr="exact")
    actor = django_filters.NumberFilter(field_name="actor_id", lookup_expr="exact")
    # date_from / date_to are inclusive on the wall-clock boundaries the
    # caller supplied. The created_at column is timezone-aware so a date
    # like "2026-05-08" is interpreted as 00:00 in the active TZ.
    date_from = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    date_to = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = AuditLog
        fields = ["target_model", "target_id", "actor", "date_from", "date_to"]
