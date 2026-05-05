from django.db.models import Q
from django.utils import timezone
from django_filters import rest_framework as df

from .invitations import Invitation, InvitationStatus


class InvitationFilter(df.FilterSet):
    status = df.CharFilter(method="filter_status")

    class Meta:
        model = Invitation
        fields = ["status"]

    def filter_status(self, queryset, name, value):
        # Status is a derived property from accepted_at/revoked_at/expires_at;
        # translate the requested terminal status into the equivalent ORM
        # filter at request time so we get server-side filtering without
        # backfilling a status column. Comma-separated values are accepted
        # for symmetry with the role filter on /api/users/.
        now = timezone.now()
        wanted = {v.strip().upper() for v in value.split(",") if v.strip()}
        valid = {
            InvitationStatus.PENDING,
            InvitationStatus.ACCEPTED,
            InvitationStatus.REVOKED,
            InvitationStatus.EXPIRED,
        }
        wanted &= valid
        if not wanted:
            return queryset.none()

        clauses = []
        if InvitationStatus.PENDING in wanted:
            clauses.append(
                Q(accepted_at__isnull=True)
                & Q(revoked_at__isnull=True)
                & Q(expires_at__gt=now)
            )
        if InvitationStatus.ACCEPTED in wanted:
            clauses.append(Q(accepted_at__isnull=False))
        if InvitationStatus.REVOKED in wanted:
            clauses.append(
                Q(accepted_at__isnull=True) & Q(revoked_at__isnull=False)
            )
        if InvitationStatus.EXPIRED in wanted:
            clauses.append(
                Q(accepted_at__isnull=True)
                & Q(revoked_at__isnull=True)
                & Q(expires_at__lte=now)
            )
        combined = clauses[0]
        for clause in clauses[1:]:
            combined |= clause
        return queryset.filter(combined)
