"""RF-1 — the aggregated message inbox: scoped thread rows across tickets
and Extra Work, each computed PER VIEWER through the canonical five-mode
visibility matrix.

Nothing here re-implements the matrix. Visibility is delegated to:
  * tickets.permissions.filter_messages_visible_to (queryset chokepoint)
  * extra_work.message_permissions.filter_ew_messages_visible_to
and the roster is delegated to notifications.services.*_message_audience.
Scope is delegated to scope_tickets_for / scope_extra_work_for.

A thread with zero viewer-visible messages never appears.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from django.db.models import Max

from accounts.permissions import is_provider_management_role, is_super_admin


@dataclass
class InboxRow:
    kind: str  # "ticket" | "extra_work"
    thread_id: int
    last_ts: datetime
    unread_count: int
    # Filled lazily for the paginated slice only.
    title: str = ""
    customer_id: Optional[int] = None
    customer_name: str = ""
    customer_logo_url: Optional[str] = None
    building_id: Optional[int] = None
    building_name: str = ""
    last_message: Optional[dict] = None
    unread_by: Optional[list] = field(default=None)


def _receipts_visible_to(viewer) -> bool:
    # Read receipts ("who hasn't read") are provider-management-only:
    # SA / CA / BM. Customer users never see who-hasn't-read — only their
    # own unread state.
    return is_super_admin(viewer) or is_provider_management_role(viewer)


# ---------------------------------------------------------------------------
# Per-kind candidate assembly (ordering + unread), matrix-delegated.
# ---------------------------------------------------------------------------
def _ticket_candidates(viewer, cursors_by_ticket):
    """Every in-scope ticket with >=1 viewer-visible message, as InboxRows
    carrying last_ts (ordering) + unread_count. Two queries total."""
    from tickets.models import TicketMessage
    from tickets.permissions import filter_messages_visible_to
    from accounts.scoping import scope_tickets_for

    scoped_ids = list(
        scope_tickets_for(viewer).values_list("id", flat=True)
    )
    if not scoped_ids:
        return {}

    visible = filter_messages_visible_to(
        TicketMessage.objects.filter(ticket_id__in=scoped_ids), viewer
    )

    # last_ts per thread (includes the viewer's own messages — activity
    # ordering, WhatsApp-style). One aggregate query.
    last_by_thread = {
        r["ticket_id"]: r["last"]
        for r in visible.values("ticket_id").annotate(last=Max("created_at"))
    }

    rows: dict[int, InboxRow] = {}
    for tid, last_ts in last_by_thread.items():
        rows[tid] = InboxRow(
            kind="ticket", thread_id=tid, last_ts=last_ts, unread_count=0
        )

    # unread = viewer-visible messages newer than the cursor, EXCLUDING the
    # viewer's own. One query returning (ticket_id, created_at); bucketed in
    # Python against the per-thread cursor.
    for tid, ts in (
        visible.exclude(author_id=viewer.id)
        .values_list("ticket_id", "created_at")
    ):
        cursor_ts = cursors_by_ticket.get(tid)
        if cursor_ts is None or ts > cursor_ts:
            rows[tid].unread_count += 1
    return rows


def _ew_candidates(viewer, cursors_by_ew):
    from extra_work.models import ExtraWorkMessage
    from extra_work.message_permissions import filter_ew_messages_visible_to
    from extra_work.scoping import scope_extra_work_for

    scoped_ids = list(
        scope_extra_work_for(viewer).values_list("id", flat=True)
    )
    if not scoped_ids:
        return {}

    visible = filter_ew_messages_visible_to(
        ExtraWorkMessage.objects.filter(extra_work_id__in=scoped_ids), viewer
    )

    last_by_thread = {
        r["extra_work_id"]: r["last"]
        for r in visible.values("extra_work_id").annotate(last=Max("created_at"))
    }

    rows: dict[int, InboxRow] = {}
    for eid, last_ts in last_by_thread.items():
        rows[eid] = InboxRow(
            kind="extra_work", thread_id=eid, last_ts=last_ts, unread_count=0
        )

    for eid, ts in (
        visible.exclude(author_id=viewer.id)
        .values_list("extra_work_id", "created_at")
    ):
        cursor_ts = cursors_by_ew.get(eid)
        if cursor_ts is None or ts > cursor_ts:
            rows[eid].unread_count += 1
    return rows


def _load_cursors(viewer):
    from .models import MessageReadCursor

    tickets, ews = {}, {}
    for c in MessageReadCursor.objects.filter(user=viewer).values(
        "ticket_id", "extra_work_id", "last_read_at"
    ):
        if c["ticket_id"] is not None:
            tickets[c["ticket_id"]] = c["last_read_at"]
        elif c["extra_work_id"] is not None:
            ews[c["extra_work_id"]] = c["last_read_at"]
    return tickets, ews


def total_unread_count(viewer) -> int:
    """Lightweight nav-badge number: total unread across both kinds. Sums
    the per-thread unread computed exactly as the inbox does."""
    cursors_t, cursors_e = _load_cursors(viewer)
    t = _ticket_candidates(viewer, cursors_t)
    e = _ew_candidates(viewer, cursors_e)
    return sum(r.unread_count for r in t.values()) + sum(
        r.unread_count for r in e.values()
    )


# ---------------------------------------------------------------------------
# Detail hydration for the paginated slice.
# ---------------------------------------------------------------------------
def _author_payload(user, request):
    if user is None:
        return {"name": None, "photo_url": None}
    from accounts.media_urls import profile_photo_url

    return {
        "name": user.full_name or user.email.split("@")[0],
        "photo_url": profile_photo_url(user, request),
    }


def _snippet(text: str, limit: int = 140) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _hydrate_ticket_rows(rows, viewer, request):
    from tickets.models import Ticket, TicketMessage
    from tickets.permissions import filter_messages_visible_to
    from customers.media_urls import customer_logo_url

    ids = [r.thread_id for r in rows]
    tickets = {
        t.id: t
        for t in Ticket.objects.filter(id__in=ids).select_related(
            "customer", "building"
        )
    }
    for r in rows:
        ticket = tickets.get(r.thread_id)
        if ticket is None:
            continue
        r.title = ticket.title or f"#{ticket.id}"
        cust = ticket.customer
        r.customer_id = cust.id if cust else None
        r.customer_name = cust.name if cust else ""
        r.customer_logo_url = (
            customer_logo_url(cust, request) if cust else None
        )
        r.building_id = ticket.building_id
        r.building_name = ticket.building.name if ticket.building else ""

        latest = (
            filter_messages_visible_to(ticket.messages.all(), viewer)
            .select_related("author")
            .order_by("-created_at")
            .first()
        )
        if latest is not None:
            r.last_message = {
                "id": latest.id,
                "author": _author_payload(latest.author, request),
                "snippet": _snippet(latest.message),
                "message_type": latest.message_type,
                "created_at": latest.created_at,
            }
            if _receipts_visible_to(viewer):
                r.unread_by = _ticket_unread_by(ticket, latest, viewer, request)


def _hydrate_ew_rows(rows, viewer, request):
    from extra_work.models import ExtraWorkRequest
    from extra_work.message_permissions import filter_ew_messages_visible_to
    from customers.media_urls import customer_logo_url

    ids = [r.thread_id for r in rows]
    ews = {
        e.id: e
        for e in ExtraWorkRequest.objects.filter(id__in=ids).select_related(
            "customer", "building"
        )
    }
    for r in rows:
        ew = ews.get(r.thread_id)
        if ew is None:
            continue
        r.title = (ew.title or "").strip() or f"#{ew.id}"
        cust = ew.customer
        r.customer_id = cust.id if cust else None
        r.customer_name = cust.name if cust else ""
        r.customer_logo_url = (
            customer_logo_url(cust, request) if cust else None
        )
        r.building_id = ew.building_id
        r.building_name = ew.building.name if ew.building else ""

        latest = (
            filter_ew_messages_visible_to(ew.messages.all(), viewer)
            .select_related("author")
            .order_by("-created_at")
            .first()
        )
        if latest is not None:
            r.last_message = {
                "id": latest.id,
                "author": _author_payload(latest.author, request),
                "snippet": _snippet(latest.message),
                "message_type": latest.message_type,
                "created_at": latest.created_at,
            }
            if _receipts_visible_to(viewer):
                r.unread_by = _ew_unread_by(ew, latest, viewer, request)


# ---------------------------------------------------------------------------
# Read-receipt roster ("who hasn't read the latest visible message").
# Provider-management viewers only. Each roster candidate is individually
# filtered by whether THEY can see that specific message.
# ---------------------------------------------------------------------------
def _visible_to_candidate_ticket(candidate, ticket, message):
    from tickets.permissions import (
        message_type_visible_to_user,
        user_has_scope_for_ticket,
    )
    from tickets.models import TicketMessageVisibility

    if not message_type_visible_to_user(candidate, message.message_type):
        return False
    if not user_has_scope_for_ticket(candidate, ticket):
        return False
    if message.visibility_mode == TicketMessageVisibility.RESTRICTED:
        if candidate.id == message.author_id:
            return True
        return message.directed_to.filter(id=candidate.id).exists()
    return True


def _roster_split(candidates, message, viewer, request, cursor_lookup):
    """Given the visible-to-this-message candidates, split into who has
    NOT read the latest message (cursor older than the message, or no
    cursor) — that's the "who hasn't read" line. The message author is
    excluded (they wrote it)."""
    from accounts.media_urls import profile_photo_url

    unread = []
    for c in candidates:
        if c.id == message.author_id:
            continue
        read_at = cursor_lookup.get(c.id)
        has_read = read_at is not None and read_at >= message.created_at
        if not has_read:
            unread.append(
                {
                    "id": c.id,
                    "name": c.full_name or c.email.split("@")[0],
                    "photo_url": profile_photo_url(c, request),
                }
            )
    return unread


def _ticket_unread_by(ticket, message, viewer, request):
    from .models import MessageReadCursor
    from .services import ticket_message_audience

    # Roster base = the tier's read-visible audience, augmented with prior
    # posters + directed_to members; each re-checked against THIS message.
    base = {u.id: u for u in ticket_message_audience(ticket, message.message_type)}
    for author in _prior_ticket_posters(ticket, viewer):
        base.setdefault(author.id, author)
    for u in message.directed_to.all():
        base.setdefault(u.id, u)

    candidates = [
        u for u in base.values()
        if _visible_to_candidate_ticket(u, ticket, message)
    ]
    cursor_lookup = {
        c["user_id"]: c["last_read_at"]
        for c in MessageReadCursor.objects.filter(
            ticket=ticket, user_id__in=[c.id for c in candidates]
        ).values("user_id", "last_read_at")
    }
    return _roster_split(candidates, message, viewer, request, cursor_lookup)


def _prior_ticket_posters(ticket, viewer):
    from tickets.models import TicketMessage
    from tickets.permissions import filter_messages_visible_to

    author_ids = (
        filter_messages_visible_to(ticket.messages.all(), viewer)
        .exclude(author__isnull=True)
        .values_list("author_id", flat=True)
        .distinct()
    )
    from accounts.models import User

    return list(User.objects.filter(id__in=list(author_ids), is_active=True))


def _visible_to_candidate_ew(candidate, ew, message):
    from extra_work.message_permissions import ew_message_type_visible_to_user
    from extra_work.scoping import scope_extra_work_for
    from extra_work.models import ExtraWorkMessageVisibility

    if not ew_message_type_visible_to_user(candidate, message.message_type):
        return False
    if not scope_extra_work_for(candidate).filter(pk=ew.pk).exists():
        return False
    if message.visibility_mode == ExtraWorkMessageVisibility.RESTRICTED:
        if candidate.id == message.author_id:
            return True
        return message.directed_to.filter(id=candidate.id).exists()
    return True


def _ew_unread_by(ew, message, viewer, request):
    from .models import MessageReadCursor
    from .services import ew_message_audience

    base = {u.id: u for u in ew_message_audience(ew, message.message_type)}
    for u in message.directed_to.all():
        base.setdefault(u.id, u)

    candidates = [
        u for u in base.values() if _visible_to_candidate_ew(u, ew, message)
    ]
    cursor_lookup = {
        c["user_id"]: c["last_read_at"]
        for c in MessageReadCursor.objects.filter(
            extra_work=ew, user_id__in=[c.id for c in candidates]
        ).values("user_id", "last_read_at")
    }
    return _roster_split(candidates, message, viewer, request, cursor_lookup)


# ---------------------------------------------------------------------------
# Top-level assembly with filters + pagination.
# ---------------------------------------------------------------------------
def build_inbox(viewer, request, *, kind=None, date_from=None, date_to=None,
                q=None, unread_only=False, offset=0, limit=25):
    """Returns (page_rows, total_count). page_rows are hydrated InboxRows."""
    cursors_t, cursors_e = _load_cursors(viewer)

    candidates: list[InboxRow] = []
    if kind in (None, "ticket"):
        candidates.extend(_ticket_candidates(viewer, cursors_t).values())
    if kind in (None, "extra_work"):
        candidates.extend(_ew_candidates(viewer, cursors_e).values())

    # Ordering filters that only need last_ts.
    if date_from is not None:
        candidates = [r for r in candidates if r.last_ts >= date_from]
    if date_to is not None:
        candidates = [r for r in candidates if r.last_ts <= date_to]
    if unread_only:
        candidates = [r for r in candidates if r.unread_count > 0]

    # q (title / customer search) needs the thread's title + customer name.
    # Resolve those in bulk for the surviving candidates before filtering.
    if q:
        _annotate_search_fields(candidates)
        needle = q.strip().lower()
        candidates = [
            r for r in candidates
            if needle in (r.title or "").lower()
            or needle in (r.customer_name or "").lower()
        ]

    candidates.sort(key=lambda r: r.last_ts, reverse=True)
    total = len(candidates)
    page = candidates[offset : offset + limit]

    # Hydrate only the page slice with the expensive per-thread detail.
    ticket_rows = [r for r in page if r.kind == "ticket"]
    ew_rows = [r for r in page if r.kind == "extra_work"]
    if ticket_rows:
        _hydrate_ticket_rows(ticket_rows, viewer, request)
    if ew_rows:
        _hydrate_ew_rows(ew_rows, viewer, request)
    return page, total


def _annotate_search_fields(rows):
    """Bulk-fill title + customer_name on candidates (for the q filter,
    which runs before pagination)."""
    from tickets.models import Ticket
    from extra_work.models import ExtraWorkRequest

    t_ids = [r.thread_id for r in rows if r.kind == "ticket"]
    e_ids = [r.thread_id for r in rows if r.kind == "extra_work"]
    t_map = {
        t.id: t for t in Ticket.objects.filter(id__in=t_ids).select_related("customer")
    } if t_ids else {}
    e_map = {
        e.id: e
        for e in ExtraWorkRequest.objects.filter(id__in=e_ids).select_related("customer")
    } if e_ids else {}
    for r in rows:
        obj = (t_map if r.kind == "ticket" else e_map).get(r.thread_id)
        if obj is None:
            continue
        r.title = (obj.title or "").strip() or f"#{obj.id}"
        r.customer_name = obj.customer.name if obj.customer else ""


def serialize_row(row: InboxRow) -> dict:
    data = {
        "kind": row.kind,
        "id": row.thread_id,
        "title": row.title,
        "customer": (
            {
                "id": row.customer_id,
                "name": row.customer_name,
                "logo_url": row.customer_logo_url,
            }
            if row.customer_id is not None
            else None
        ),
        "building": (
            {"id": row.building_id, "name": row.building_name}
            if row.building_id is not None
            else None
        ),
        "last_message": row.last_message,
        "unread_count": row.unread_count,
    }
    # Receipts are present ONLY for provider-management viewers (set during
    # hydration); customer viewers get no `unread_by` key at all.
    if row.unread_by is not None:
        data["unread_by"] = row.unread_by
    return data
