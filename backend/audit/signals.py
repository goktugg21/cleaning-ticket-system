"""
Signal handlers that emit AuditLog rows for the four tracked admin
models: accounts.User, companies.Company, buildings.Building,
customers.Customer.

Lifecycle:
- pre_save snapshots the *current DB state* of an existing instance
  into a thread-local map keyed by (model_label, pk). For new rows
  (no pk yet) we record None so post_save knows it's a CREATE.
- post_save reads that snapshot and writes a CREATE or UPDATE log.
- post_delete writes a DELETE log with a snapshot of the row.

Safety:
- Every handler is wrapped in try/except. Logging audit failures must
  never fail the original mutation. We record the exception via the
  stdlib logger so Sentry's LoggingIntegration (Sprint 1.3) picks it
  up automatically when configured, without this module ever importing
  sentry_sdk.
- AuditLog itself is never audited (the tracked-models tuple does not
  include it), so there is no recursion risk.

Actor capture:
- Resolved lazily via audit.context.get_current_actor(). When the
  middleware ran (HTTP request path), DRF's view-layer JWT auth has
  already populated request.user by the time post_save fires —
  authenticated callers therefore land in the audit row, not None.
- Background / Celery / management-command writes do not have a
  thread-local request, so actor=None — that is the correct semantics
  for system writes.
"""
from __future__ import annotations

import logging
import threading

from django.db.models.signals import post_delete, post_save, pre_save

from buildings.models import Building
from companies.models import Company
from customers.models import Customer

from . import context
from .diff import (
    compute_create_changes,
    compute_delete_changes,
    compute_update_changes,
    snapshot_for_pre_save,
)
from .models import AuditAction, AuditLog


logger = logging.getLogger(__name__)


# Lazy User import to avoid circular imports during app loading. The
# accounts app declares the AUTH_USER_MODEL = "accounts.User" string
# in settings; we resolve the concrete class once at module load.
def _user_model():
    from accounts.models import User
    return User


# (model_label, pk) -> pre-save snapshot dict. Thread-local so
# concurrent requests cannot cross-pollinate snapshots.
_pre_save_state = threading.local()


def _state_map():
    if not hasattr(_pre_save_state, "snapshots"):
        _pre_save_state.snapshots = {}
    return _pre_save_state.snapshots


def _label(instance) -> str:
    meta = instance._meta
    return f"{meta.app_label}.{meta.object_name}"


def _create_log(instance, action: str, changes: dict) -> None:
    """Write one AuditLog row. Swallows all exceptions."""
    try:
        AuditLog.objects.create(
            actor=context.get_current_actor(),
            action=action,
            target_model=_label(instance),
            target_id=instance.pk,
            changes=changes or {},
            request_ip=context.get_current_request_ip(),
            request_id=context.get_current_request_id(),
        )
    except Exception:  # pragma: no cover — defensive; never fail the caller
        logger.exception(
            "audit: failed to record %s on %s#%s",
            action,
            _label(instance),
            getattr(instance, "pk", None),
        )


def _on_pre_save(sender, instance, **kwargs):
    try:
        if instance.pk is None:
            _state_map()[(_label(instance), id(instance))] = None
            return
        try:
            db_instance = sender.objects.get(pk=instance.pk)
        except sender.DoesNotExist:
            _state_map()[(_label(instance), instance.pk)] = None
            return
        _state_map()[(_label(instance), instance.pk)] = snapshot_for_pre_save(db_instance)
    except Exception:  # pragma: no cover — defensive
        logger.exception("audit: pre_save snapshot failed for %s", _label(instance))


def _on_post_save(sender, instance, created, **kwargs):
    try:
        if created:
            key = (_label(instance), id(instance))
            _state_map().pop(key, None)
            _create_log(instance, AuditAction.CREATE, compute_create_changes(instance))
            return
        old_snapshot = _state_map().pop((_label(instance), instance.pk), None)
        if old_snapshot is None:
            # First time we are seeing this row in this thread (e.g.
            # pre_save did not fire because the row was created via
            # bulk_create, or a programmatic .save() bypassed the
            # signal somehow). Treat it as an UPDATE with empty diff
            # rather than skip — the row mutation still happened.
            changes = {}
        else:
            changes = compute_update_changes(old_snapshot, instance)
        if not changes:
            # Nothing meaningful changed (e.g. only updated_at moved).
            # Skip the log to avoid noise.
            return
        _create_log(instance, AuditAction.UPDATE, changes)
    except Exception:  # pragma: no cover — defensive
        logger.exception("audit: post_save failed for %s", _label(instance))


def _on_post_delete(sender, instance, **kwargs):
    try:
        _create_log(instance, AuditAction.DELETE, compute_delete_changes(instance))
    except Exception:  # pragma: no cover — defensive
        logger.exception("audit: post_delete failed for %s", _label(instance))


def _connect():
    User = _user_model()
    for model in (User, Company, Building, Customer):
        pre_save.connect(_on_pre_save, sender=model, weak=False, dispatch_uid=f"audit:pre:{model.__name__}")
        post_save.connect(_on_post_save, sender=model, weak=False, dispatch_uid=f"audit:post:{model.__name__}")
        post_delete.connect(_on_post_delete, sender=model, weak=False, dispatch_uid=f"audit:del:{model.__name__}")


_connect()
