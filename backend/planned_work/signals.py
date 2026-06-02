"""Planned-work signal handlers (Sprint 11B Batch 2).

The single handler keeps a planned occurrence in sync with its linked
operational ticket WITHOUT coupling the tickets app to planned_work:

  * Cheap no-op for non-planned tickets — `reconcile_occurrence_from_
    ticket` returns immediately when `planned_occurrence_id` is None,
    so the overwhelming majority of ticket saves cost one attribute
    read.
  * Catches BOTH completion (ticket -> APPROVED/CLOSED -> occurrence
    COMPLETED) and reschedule (ticket schedule_status -> RESCHEDULED ->
    occurrence RESCHEDULED) from one place.
  * NEVER breaks a ticket save — the reconcile helper wraps its body in
    try/except and logs on failure.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from tickets.models import Ticket

from .lifecycle import reconcile_occurrence_from_ticket

logger = logging.getLogger("planned_work")


@receiver(post_save, sender=Ticket, dispatch_uid="planned_work:ticket_sync")
def _ticket_post_save_sync(sender, instance, **kwargs):
    # reconcile_occurrence_from_ticket itself never raises.
    reconcile_occurrence_from_ticket(instance)
