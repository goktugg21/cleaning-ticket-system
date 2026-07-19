from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAuthenticatedAndActive

from .models import Notification, NotificationPreference
from .serializers import NotificationSerializer


def _feed_queryset(user):
    """IA 2026-06-25 — THE read-side chokepoint for the notification feed.

    Message-type events (TICKET_MESSAGE / EXTRA_WORK_MESSAGE) are hidden
    from the feed and every count by DEFAULT — they duplicate the
    Berichten inbox. Two exceptions:
      * DIRECTED rows (is_directed=True — someone explicitly addressed
        this user) always show; this is also the only way a SUPER_ADMIN
        receives message notifications (the fan-out excludes SA by
        design).
      * an explicit opt-in row (muted=False) for that event type brings
        the type back — including its history, since suppression is
        read-time and rows keep being emitted.

    Every feed/count consumer (list, unread-count, mark-all-read) MUST
    route through this helper so the rule cannot drift.
    """
    qs = Notification.objects.filter(recipient=user)
    hidden_types = [
        et
        for et in NotificationPreference.USER_MUTABLE_INAPP_EVENT_TYPES
        if not NotificationPreference.objects.filter(
            user=user, event_type=et, muted=False
        ).exists()
    ]
    if hidden_types:
        qs = qs.exclude(
            Q(event_type__in=hidden_types) & Q(is_directed=False)
        )
    return qs


def _unread_count(user):
    return _feed_queryset(user).filter(read_at__isnull=True).count()


class NotificationListView(generics.ListAPIView):
    """GET /api/notifications/ — the caller's own notifications, newest first.

    Hard scoping: the queryset is filtered to `recipient=request.user`, so a
    user can only ever see their own notifications. The paginated response is
    augmented with `unread_count` for the caller. Message-type events are
    excluded per `_feed_queryset` unless directed or opted-in.
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticatedAndActive]

    def get_queryset(self):
        return (
            _feed_queryset(self.request.user)
            .select_related("actor", "ticket")
            .order_by("-created_at")
        )

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        # The default paginator returns a dict ({count, next, previous,
        # results}); inject unread_count alongside it so the FE bell does not
        # need a second round-trip on first load.
        if isinstance(response.data, dict):
            response.data["unread_count"] = _unread_count(request.user)
        return response


class NotificationUnreadCountView(APIView):
    """GET /api/notifications/unread-count/ — { "unread_count": N }."""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request):
        return Response({"unread_count": _unread_count(request.user)})


class NotificationMarkReadView(APIView):
    """POST /api/notifications/<id>/read/ — mark one of the caller's
    notifications read. 404 if it is not the caller's own."""

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request, pk):
        notification = get_object_or_404(
            Notification, pk=pk, recipient=request.user
        )
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
        return Response(NotificationSerializer(notification).data)


class NotificationMarkAllReadView(APIView):
    """POST /api/notifications/read-all/ — mark all the caller's unread
    FEED-VISIBLE notifications read; returns the number updated. Routed
    through `_feed_queryset` so "mark all read" cannot silently consume a
    hidden message notification the user might later opt back in to."""

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request):
        updated = _feed_queryset(request.user).filter(
            read_at__isnull=True
        ).update(read_at=timezone.now())
        return Response({"updated": updated})
