"""Planned-work Celery tasks (Sprint 11B Batch 2)."""
from celery import shared_task

from .constants import DEFAULT_GENERATION_DAYS_AHEAD


@shared_task
def run_daily_planned_work(days_ahead=DEFAULT_GENERATION_DAYS_AHEAD):
    """Daily driver: materialize occurrences + spawn tickets inside the
    horizon, then flip past-due occurrences to MISSED."""
    # Local imports keep task module import cheap and avoid pulling the
    # generation / lifecycle dependency graph at worker import time.
    from .generation import generate_occurrences
    from .lifecycle import mark_missed_occurrences

    gen = generate_occurrences(days_ahead=days_ahead)
    missed = mark_missed_occurrences()
    return {"generated": gen, "missed_marked": missed}
