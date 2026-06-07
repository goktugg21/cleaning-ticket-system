from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAuthenticatedAndActive

from .models import Notification
from .serializers import NotificationSerializer


def _unread_count(user):
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()


class NotificationListView(generics.ListAPIView):
    """GET /api/notifications/ — the caller's own notifications, newest first.

    Hard scoping: the queryset is filtered to `recipient=request.user`, so a
    user can only ever see their own notifications. The paginated response is
    augmented with `unread_count` for the caller.
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticatedAndActive]

    def get_queryset(self):
        return (
            Notification.objects.filter(recipient=self.request.user)
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
    notifications read; returns the number updated."""

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request):
        updated = Notification.objects.filter(
            recipient=request.user, read_at__isnull=True
        ).update(read_at=timezone.now())
        return Response({"updated": updated})
