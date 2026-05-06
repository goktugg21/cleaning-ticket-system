"""
High-level SLA engine transitions, called from the Ticket post_save signal.

All public functions mutate the in-memory ticket instance only; persistence is
the caller's responsibility (the signal handler in signals.py uses
Ticket.objects.filter(pk=).update(...) to bypass signal recursion).

Status semantics:
- HISTORICAL: pre-engine ticket, never reconciled, no due date.
- ON_TRACK / AT_RISK / BREACHED: live states reconciled by elapsed/target ratio.
- COMPLETED: ticket reached a terminal status (APPROVED, REJECTED, CLOSED).
- Paused tickets (sla_paused_at != None) freeze at their current status.
"""
from __future__ import annotations

import datetime
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from tickets.models import Ticket, TicketStatus

from . import business_hours


TERMINAL_STATUSES = frozenset(
    (TicketStatus.APPROVED, TicketStatus.REJECTED, TicketStatus.CLOSED)
)
PAUSED_STATUS = TicketStatus.WAITING_CUSTOMER_APPROVAL

ON_TRACK = "ON_TRACK"
AT_RISK = "AT_RISK"
BREACHED = "BREACHED"
COMPLETED = "COMPLETED"
HISTORICAL = "HISTORICAL"


def _engine_start_date_utc() -> datetime.datetime:
    iso = settings.SLA_ENGINE_START_DATE
    local_date = datetime.date.fromisoformat(iso)
    tz = ZoneInfo(settings.TIME_ZONE)
    local_dt = datetime.datetime.combine(local_date, datetime.time(0, 0), tzinfo=tz)
    return local_dt.astimezone(dt_timezone.utc)


def _target_seconds() -> int:
    return int(settings.SLA_DEFAULT_TARGET_BUSINESS_SECONDS)


def _at_risk_threshold() -> float:
    return float(settings.SLA_AT_RISK_THRESHOLD)


def on_ticket_created(ticket: Ticket) -> None:
    """Initialize SLA fields on a newly created ticket. Mutates in place."""
    if ticket.created_at is None:
        return
    if ticket.created_at < _engine_start_date_utc():
        ticket.sla_status = HISTORICAL
        ticket.sla_started_at = None
        ticket.sla_due_at = None
        ticket.sla_paused_at = None
        ticket.sla_paused_seconds = 0
        ticket.sla_completed_at = None
        return

    ticket.sla_started_at = ticket.created_at
    ticket.sla_paused_at = None
    ticket.sla_paused_seconds = 0
    ticket.sla_completed_at = None
    ticket.sla_due_at = business_hours.add_business_seconds(
        ticket.created_at, _target_seconds()
    )
    ticket.sla_status = ON_TRACK


def on_ticket_status_changed(
    ticket: Ticket,
    old_status: str,
    new_status: str,
    when: datetime.datetime | None = None,
) -> None:
    """Drive engine transitions on a status change. Mutates in place."""
    if ticket.sla_status == HISTORICAL:
        return
    if when is None:
        when = timezone.now()

    became_paused = old_status != PAUSED_STATUS and new_status == PAUSED_STATUS
    left_paused = old_status == PAUSED_STATUS and new_status != PAUSED_STATUS
    became_terminal = (
        old_status not in TERMINAL_STATUSES and new_status in TERMINAL_STATUSES
    )
    left_terminal = (
        old_status in TERMINAL_STATUSES and new_status not in TERMINAL_STATUSES
    )

    # Order matters: a single transition can both leave PAUSED and become
    # terminal (WAITING_CUSTOMER_APPROVAL → APPROVED). Resume first so paused
    # seconds are recorded; then mark complete.
    if left_paused:
        _on_resume(ticket, when)
    if became_paused:
        _on_pause(ticket, when)
    if left_terminal:
        _on_reopen(ticket, when)
    if became_terminal:
        _on_complete(ticket, when)


def _on_pause(ticket: Ticket, when: datetime.datetime) -> None:
    ticket.sla_paused_at = when


def _on_resume(ticket: Ticket, when: datetime.datetime) -> None:
    if ticket.sla_paused_at is None or ticket.sla_started_at is None:
        return
    paused_for = business_hours.business_seconds_between(
        ticket.sla_paused_at, when
    )
    ticket.sla_paused_seconds = int(ticket.sla_paused_seconds or 0) + paused_for
    ticket.sla_due_at = business_hours.add_business_seconds(
        ticket.sla_started_at,
        _target_seconds() + int(ticket.sla_paused_seconds),
    )
    ticket.sla_paused_at = None
    reconcile(ticket, now=when)


def _on_complete(ticket: Ticket, when: datetime.datetime) -> None:
    ticket.sla_completed_at = when
    ticket.sla_status = COMPLETED


def _on_reopen(ticket: Ticket, when: datetime.datetime) -> None:
    # Restart the active clock. sla_first_breached_at is a permanent marker
    # and is never cleared.
    ticket.sla_started_at = when
    ticket.sla_paused_at = None
    ticket.sla_paused_seconds = 0
    ticket.sla_completed_at = None
    ticket.sla_due_at = business_hours.add_business_seconds(
        when, _target_seconds()
    )
    ticket.sla_status = ON_TRACK
    reconcile(ticket, now=when)


def reconcile(ticket: Ticket, now: datetime.datetime | None = None) -> bool:
    """Recompute sla_status based on elapsed business time. Returns True if changed."""
    if ticket.sla_status == HISTORICAL:
        return False
    if ticket.status in TERMINAL_STATUSES:
        return False
    if ticket.sla_paused_at is not None:
        return False
    if ticket.sla_started_at is None or ticket.sla_due_at is None:
        return False

    if now is None:
        now = timezone.now()

    target = _target_seconds() + int(ticket.sla_paused_seconds or 0)
    if target <= 0:
        return False

    elapsed = business_hours.business_seconds_between(ticket.sla_started_at, now)
    pct = elapsed / target

    if pct >= 1.0:
        new_status = BREACHED
        new_first = (
            ticket.sla_first_breached_at
            if ticket.sla_first_breached_at is not None
            else now
        )
    elif pct >= _at_risk_threshold():
        new_status = AT_RISK
        new_first = ticket.sla_first_breached_at
    else:
        new_status = ON_TRACK
        new_first = ticket.sla_first_breached_at

    changed = False
    if new_status != ticket.sla_status:
        ticket.sla_status = new_status
        changed = True
    if new_first != ticket.sla_first_breached_at:
        ticket.sla_first_breached_at = new_first
        changed = True
    return changed
