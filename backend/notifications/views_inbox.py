"""RF-1 — the message inbox HTTP surface.

  GET  /api/inbox/               paginated thread rows (both kinds)
  GET  /api/inbox/unread-count/  { "unread_count": N } for the nav badge
  POST /api/inbox/mark-read/     advance this user's cursor for a thread
"""
from __future__ import annotations

from datetime import datetime, time

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAuthenticatedAndActive

from . import inbox as inbox_logic
from .models import MessageReadCursor

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


def _parse_boundary(value, *, end_of_day):
    """Accept an ISO datetime OR a plain date. A plain date maps to the
    start (date_from) or end (date_to) of that day, in the current tz."""
    if not value:
        return None
    dt = parse_datetime(value)
    if dt is None:
        d = parse_date(value)
        if d is None:
            return None
        dt = datetime.combine(d, time.max if end_of_day else time.min)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


class InboxListView(APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request):
        params = request.query_params
        kind = params.get("kind") or None
        if kind not in (None, "ticket", "extra_work"):
            return Response(
                {"detail": "kind must be 'ticket' or 'extra_work'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            limit = int(params.get("page_size", DEFAULT_PAGE_SIZE))
            offset = int(params.get("offset", 0))
        except (TypeError, ValueError):
            return Response(
                {"detail": "page_size / offset must be integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        offset = max(0, offset)

        rows, total = inbox_logic.build_inbox(
            request.user,
            request,
            kind=kind,
            date_from=_parse_boundary(params.get("date_from"), end_of_day=False),
            date_to=_parse_boundary(params.get("date_to"), end_of_day=True),
            q=params.get("q"),
            unread_only=params.get("unread_only") in ("1", "true", "True"),
            offset=offset,
            limit=limit,
        )
        return Response(
            {
                "count": total,
                "offset": offset,
                "page_size": limit,
                "results": [inbox_logic.serialize_row(r) for r in rows],
            }
        )


class InboxUnreadCountView(APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request):
        return Response(
            {"unread_count": inbox_logic.total_unread_count(request.user)}
        )


class InboxMarkReadView(APIView):
    """POST { "kind": "ticket"|"extra_work", "id": N } — advance this
    user's read cursor for the thread to now(). Idempotent. Only a thread
    the caller can scope (see) may be marked read (else 404, no existence
    leak)."""

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request):
        kind = request.data.get("kind")
        thread_id = request.data.get("id")
        if kind not in ("ticket", "extra_work") or thread_id in (None, ""):
            return Response(
                {"detail": "kind and id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            thread_id = int(thread_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "id must be an integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        viewer = request.user
        now = timezone.now()
        if kind == "ticket":
            from accounts.scoping import scope_tickets_for

            if not scope_tickets_for(viewer).filter(pk=thread_id).exists():
                return Response(status=status.HTTP_404_NOT_FOUND)
            cursor, _ = MessageReadCursor.objects.get_or_create(
                user=viewer, ticket_id=thread_id,
                defaults={"last_read_at": now},
            )
        else:
            from extra_work.scoping import scope_extra_work_for

            if not scope_extra_work_for(viewer).filter(pk=thread_id).exists():
                return Response(status=status.HTTP_404_NOT_FOUND)
            cursor, _ = MessageReadCursor.objects.get_or_create(
                user=viewer, extra_work_id=thread_id,
                defaults={"last_read_at": now},
            )
        # Advance (never regress) the watermark.
        if cursor.last_read_at < now:
            cursor.last_read_at = now
            cursor.save(update_fields=["last_read_at"])
        return Response(
            {"unread_count": inbox_logic.total_unread_count(viewer)},
            status=status.HTTP_200_OK,
        )


class InboxMarkAllReadView(APIView):
    """POST /api/inbox/mark-all-read/ — advance (or create) this user's
    read cursor to now() for EVERY thread currently visible in their
    inbox. Reuses the inbox thread enumeration (scope + the canonical
    visibility chokepoints), so a caller can only ever mark threads they
    can see; idempotent — a second call just re-advances watermarks.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request):
        viewer = request.user
        now = timezone.now()

        cursors_t, cursors_e = inbox_logic._load_cursors(viewer)
        ticket_ids = set(
            inbox_logic._ticket_candidates(viewer, cursors_t).keys()
        )
        ew_ids = set(inbox_logic._ew_candidates(viewer, cursors_e).keys())

        # Advance every existing cursor for these threads in one UPDATE...
        MessageReadCursor.objects.filter(
            user=viewer, ticket_id__in=ticket_ids
        ).update(last_read_at=now)
        MessageReadCursor.objects.filter(
            user=viewer, extra_work_id__in=ew_ids
        ).update(last_read_at=now)

        # ...and create the missing ones in one bulk_create. Recomputing
        # "existing" AFTER the update keeps the create set race-tight.
        have_t = set(
            MessageReadCursor.objects.filter(
                user=viewer, ticket_id__in=ticket_ids
            ).values_list("ticket_id", flat=True)
        )
        have_e = set(
            MessageReadCursor.objects.filter(
                user=viewer, extra_work_id__in=ew_ids
            ).values_list("extra_work_id", flat=True)
        )
        MessageReadCursor.objects.bulk_create(
            [
                MessageReadCursor(user=viewer, ticket_id=tid, last_read_at=now)
                for tid in ticket_ids - have_t
            ]
            + [
                MessageReadCursor(user=viewer, extra_work_id=eid, last_read_at=now)
                for eid in ew_ids - have_e
            ]
        )
        return Response(
            {"unread_count": inbox_logic.total_unread_count(viewer)},
            status=status.HTTP_200_OK,
        )
