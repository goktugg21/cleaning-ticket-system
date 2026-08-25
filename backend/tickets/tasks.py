"""Periodic ticket tasks.

Wired in `CELERY_BEAT_SCHEDULE` and run by the dedicated `beat` container,
the same arrangement `sla.tasks` and `planned_work.tasks` already use.

Kept as its own module rather than folded into `sla.tasks` because the
subject is different: the SLA sweep measures clocks the SLA engine owns,
this one reads a ticket's deadline and its own roster. They fail
differently and an operator will want to disable one without the other —
the argument `sla/tasks.py` makes for splitting its own two tasks.
"""
import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def sweep_deadline_reminders(now=None):
    """Remind each live ticket's people once, when its deadline nears.

    Never raises. A periodic task that dies on one bad row stops
    reminding about every other row too, which is the exact silence this
    exists to end — `sweep_sla_warnings` guards itself the same way and
    for the same reason.

    `now` (an ISO datetime string) exists for tests and for an operator
    re-running a missed window by hand; the beat schedule never passes it.
    """
    from datetime import datetime

    from . import deadline_reminders

    when = datetime.fromisoformat(now) if now else timezone.now()
    try:
        return deadline_reminders.sweep(now=when)
    except Exception:  # noqa: BLE001 — see the docstring
        logger.exception("sweep_deadline_reminders failed")
        return {"told": 0, "failed": 0, "error": True}
