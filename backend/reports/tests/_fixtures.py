from datetime import datetime, timezone

from tickets.models import Ticket


def aware(year, month, day, hour=12, minute=0):
    """Convenience for tz-aware datetime in tests (UTC)."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def make_ticket_at(when, **kwargs):
    """
    Create a Ticket then force its created_at to `when` (a tz-aware datetime).
    Bypasses auto_now_add by saving then updating, then refreshes the
    instance so the returned object reflects the override.
    """
    ticket = Ticket.objects.create(**kwargs)
    Ticket.objects.filter(pk=ticket.pk).update(created_at=when)
    ticket.refresh_from_db()
    return ticket


def resolve_ticket_at(ticket, when):
    """
    Set resolved_at directly on a ticket. Does not touch status. Tests should
    set status separately if needed.
    """
    Ticket.objects.filter(pk=ticket.pk).update(resolved_at=when)
    ticket.refresh_from_db()
    return ticket


def set_status(ticket, status):
    """Force the ticket's status without going through the state machine."""
    Ticket.objects.filter(pk=ticket.pk).update(status=status)
    ticket.refresh_from_db()
    return ticket


def assign_to(ticket, user):
    """Force the ticket's assigned_to without going through the state machine."""
    Ticket.objects.filter(pk=ticket.pk).update(assigned_to=user)
    ticket.refresh_from_db()
    return ticket
