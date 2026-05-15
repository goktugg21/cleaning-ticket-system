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

from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerCompanyPolicy,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from tickets.models import StaffAssignmentRequest, TicketStaffAssignment

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


# ===========================================================================
# Sprint 7 — membership / assignment scope changes.
#
# CompanyUserMembership / BuildingManagerAssignment / CustomerUserMembership
# rows are scope-changing: creating one grants a user access to a tenant
# entity; deleting one revokes it. The default diff engine would only emit
# bare FK pks ({"user": 42, "company": 7}); for compliance purposes the
# audit row needs the user's email and the entity's name in plain text so
# the operator does not have to cross-reference pks.
#
# These handlers therefore build a hand-crafted changes payload for the
# three M:N junction models and emit through the same _create_log helper as
# the rest of the file. There is no UPDATE path on memberships (no editable
# fields), so we only listen to post_save (created=True) and post_delete.
# ===========================================================================


# Map membership/assignment model -> ("entity attr name", "verb-form label").
_MEMBERSHIP_ENTITY_ATTR = {
    CompanyUserMembership: "company",
    BuildingManagerAssignment: "building",
    CustomerUserMembership: "customer",
}


def _membership_changes(membership, *, action: str) -> dict:
    """
    Build a meaningful changes dict for a membership / assignment row.

    Always includes user_id + user_email and the matching entity id + name,
    so audit rows are human-readable without a cross-lookup. CREATE puts
    the values in `after`; DELETE puts them in `before`.
    """
    entity_attr = _MEMBERSHIP_ENTITY_ATTR.get(type(membership))
    if entity_attr is None:
        return {}
    user = membership.user
    entity = getattr(membership, entity_attr, None)
    user_id = user.id if user is not None else None
    user_email = getattr(user, "email", None) if user is not None else None
    entity_id = entity.id if entity is not None else None
    entity_name = getattr(entity, "name", None) if entity is not None else None

    if action == AuditAction.CREATE:
        sentinel_before, sentinel_after = None, "after"
    else:  # DELETE
        sentinel_before, sentinel_after = "before", None

    def _pair(value):
        # CREATE: {"before": None, "after": value}
        # DELETE: {"before": value, "after": None}
        if sentinel_after == "after":
            return {"before": None, "after": value}
        return {"before": value, "after": None}

    return {
        "user_id": _pair(user_id),
        "user_email": _pair(user_email),
        f"{entity_attr}_id": _pair(entity_id),
        f"{entity_attr}_name": _pair(entity_name),
    }


def _on_membership_post_save(sender, instance, created, **kwargs):
    if not created:
        # Sprint 27B: `BuildingStaffVisibility` has its own dedicated
        # UPDATE-diff handler below (`_on_building_staff_visibility_post_save_update`)
        # so the field change on `can_request_assignment` lands as a
        # proper diff row, not as the CREATE-shape fallback this branch
        # emits. Skip the fallback for that model so we don't write two
        # AuditLog rows per UPDATE. CREATE and DELETE on BSV still go
        # through the membership shape — only UPDATE is delegated.
        if sender.__name__ == "BuildingStaffVisibility":
            return

        # Other membership rows have no editable fields; an UPDATE would
        # be a surprise but we still want to know about it. Emit an
        # UPDATE log with the same shape as a CREATE so the row stays
        # inspectable.
        try:
            _create_log(
                instance,
                AuditAction.UPDATE,
                _membership_changes(instance, action=AuditAction.CREATE),
            )
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "audit: membership post_save (update) failed for %s",
                _label(instance),
            )
        return
    try:
        _create_log(
            instance,
            AuditAction.CREATE,
            _membership_changes(instance, action=AuditAction.CREATE),
        )
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "audit: membership post_save (create) failed for %s",
            _label(instance),
        )


def _on_membership_post_delete(sender, instance, **kwargs):
    try:
        _create_log(
            instance,
            AuditAction.DELETE,
            _membership_changes(instance, action=AuditAction.DELETE),
        )
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "audit: membership post_delete failed for %s", _label(instance)
        )


# ===========================================================================
# Sprint 14 — CustomerBuildingMembership and CustomerUserBuildingAccess.
#
# These rows are scope-changing (they grant or revoke a customer's link to
# a building, or a customer-user's per-building access), so they need
# audit coverage. Their shape differs from the Sprint-7 membership models:
#
#   CustomerBuildingMembership:  (customer, building)             — no user
#   CustomerUserBuildingAccess:  (membership, building)            — user via membership.user
#
# We emit through the same _create_log helper but with hand-crafted
# changes payloads so an operator scrolling the audit feed sees the
# customer name + building name without a cross-lookup.
# ===========================================================================


def _customer_building_link_changes(link, *, action: str) -> dict:
    customer = link.customer
    building = link.building
    payload = {
        "customer_id": (customer.id if customer else None),
        "customer_name": (getattr(customer, "name", None) if customer else None),
        "building_id": (building.id if building else None),
        "building_name": (getattr(building, "name", None) if building else None),
    }
    if action == AuditAction.CREATE:
        return {k: {"before": None, "after": v} for k, v in payload.items()}
    return {k: {"before": v, "after": None} for k, v in payload.items()}


def _customer_user_access_changes(access, *, action: str) -> dict:
    membership = access.membership
    user = getattr(membership, "user", None)
    customer = getattr(membership, "customer", None)
    building = access.building
    payload = {
        "user_id": (user.id if user else None),
        "user_email": (getattr(user, "email", None) if user else None),
        "customer_id": (customer.id if customer else None),
        "customer_name": (getattr(customer, "name", None) if customer else None),
        "building_id": (building.id if building else None),
        "building_name": (getattr(building, "name", None) if building else None),
    }
    if action == AuditAction.CREATE:
        return {k: {"before": None, "after": v} for k, v in payload.items()}
    return {k: {"before": v, "after": None} for k, v in payload.items()}


def _on_customer_building_link_post_save(sender, instance, created, **kwargs):
    if not created:
        return  # No editable fields; ignore non-create saves.
    try:
        _create_log(
            instance,
            AuditAction.CREATE,
            _customer_building_link_changes(instance, action=AuditAction.CREATE),
        )
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "audit: CustomerBuildingMembership post_save failed for #%s",
            getattr(instance, "pk", None),
        )


def _on_customer_building_link_post_delete(sender, instance, **kwargs):
    try:
        _create_log(
            instance,
            AuditAction.DELETE,
            _customer_building_link_changes(instance, action=AuditAction.DELETE),
        )
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "audit: CustomerBuildingMembership post_delete failed for #%s",
            getattr(instance, "pk", None),
        )


# Sprint 23A: per-instance UPDATE diffing for the editable fields on
# CustomerUserBuildingAccess. The identity fields (membership/building)
# are not mutable through the admin UI — they belong to the CREATE/
# DELETE shape captured by `_customer_user_access_changes`. The
# trio of mutable fields below is captured separately so an UPDATE
# log records only what actually changed.
_CUBA_TRACKED_FIELDS = ("access_role", "permission_overrides", "is_active")


def _cuba_snapshot_for_pre_save(instance):
    """Snapshot only the Sprint 23A editable fields."""
    if instance.pk is None:
        return None
    from customers.models import CustomerUserBuildingAccess

    try:
        previous = CustomerUserBuildingAccess.objects.get(pk=instance.pk)
    except CustomerUserBuildingAccess.DoesNotExist:
        return None
    return {field: getattr(previous, field) for field in _CUBA_TRACKED_FIELDS}


def _on_customer_user_access_pre_save(sender, instance, **kwargs):
    """Snapshot the pre-update state so post_save can diff it."""
    try:
        snapshot = _cuba_snapshot_for_pre_save(instance)
        _state_map()[("customers.CustomerUserBuildingAccess", instance.pk)] = snapshot
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "audit: CustomerUserBuildingAccess pre_save snapshot failed for #%s",
            getattr(instance, "pk", None),
        )


def _on_customer_user_access_post_save(sender, instance, created, **kwargs):
    try:
        if created:
            _create_log(
                instance,
                AuditAction.CREATE,
                _customer_user_access_changes(instance, action=AuditAction.CREATE),
            )
            return
        # Sprint 23A: log UPDATE when any of the editable trio
        # (access_role / permission_overrides / is_active) changed.
        snapshot = _state_map().pop(
            ("customers.CustomerUserBuildingAccess", instance.pk), None
        )
        if snapshot is None:
            return
        diff = {}
        for field in _CUBA_TRACKED_FIELDS:
            before = snapshot[field]
            after = getattr(instance, field)
            if before != after:
                diff[field] = {"before": before, "after": after}
        if not diff:
            # Nothing tracked changed (e.g. only a downstream save
            # rewrote created_at-only context). Suppress noise.
            return
        _create_log(instance, AuditAction.UPDATE, diff)
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "audit: CustomerUserBuildingAccess post_save failed for #%s",
            getattr(instance, "pk", None),
        )


def _on_customer_user_access_post_delete(sender, instance, **kwargs):
    try:
        _create_log(
            instance,
            AuditAction.DELETE,
            _customer_user_access_changes(instance, action=AuditAction.DELETE),
        )
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "audit: CustomerUserBuildingAccess post_delete failed for #%s",
            getattr(instance, "pk", None),
        )


# Sprint 27B (closes gap G-B4 from docs/architecture/sprint-27-rbac-matrix.md):
# `BuildingStaffVisibility` is still registered with the membership-only
# CREATE/DELETE handlers above — that shape is unchanged. But its single
# editable field, `can_request_assignment`, is a per-building permission
# toggle whose changes need to land on the audit feed just like the
# CustomerUserBuildingAccess editable trio.
#
# The pattern below mirrors the Sprint 23A CUBA UPDATE diff: a tiny
# pre_save snapshot of just the tracked field, plus a post_save handler
# that fires UPDATE-only (CREATE is left to the existing membership
# handler so the rich payload doesn't get duplicated).
_BSV_TRACKED_FIELDS = ("can_request_assignment",)


def _bsv_snapshot_for_pre_save(instance):
    """Snapshot the Sprint 27B editable field on BuildingStaffVisibility."""
    if instance.pk is None:
        return None
    from buildings.models import BuildingStaffVisibility

    try:
        previous = BuildingStaffVisibility.objects.get(pk=instance.pk)
    except BuildingStaffVisibility.DoesNotExist:
        return None
    return {field: getattr(previous, field) for field in _BSV_TRACKED_FIELDS}


def _on_building_staff_visibility_pre_save(sender, instance, **kwargs):
    """Snapshot the pre-update state so post_save can diff it."""
    try:
        snapshot = _bsv_snapshot_for_pre_save(instance)
        _state_map()[
            ("buildings.BuildingStaffVisibility", instance.pk)
        ] = snapshot
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "audit: BuildingStaffVisibility pre_save snapshot failed for #%s",
            getattr(instance, "pk", None),
        )


def _on_building_staff_visibility_post_save_update(
    sender, instance, created, **kwargs
):
    """UPDATE-only handler: emit a CRUD UPDATE row with the diff of
    the tracked field. CREATE is intentionally a no-op here — the
    membership handler already emits the rich CREATE payload."""
    if created:
        return
    try:
        snapshot = _state_map().pop(
            ("buildings.BuildingStaffVisibility", instance.pk), None
        )
        if snapshot is None:
            return
        diff = {}
        for field in _BSV_TRACKED_FIELDS:
            before = snapshot[field]
            after = getattr(instance, field)
            if before != after:
                diff[field] = {"before": before, "after": after}
        if not diff:
            return
        _create_log(instance, AuditAction.UPDATE, diff)
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "audit: BuildingStaffVisibility post_save UPDATE failed for #%s",
            getattr(instance, "pk", None),
        )


def _connect():
    User = _user_model()
    # Lazy import: StaffProfile lives in accounts and would create a
    # circular import at module-load time if pulled at the top of
    # this file (accounts.signals → audit.signals → accounts.models
    # via _user_model).
    from accounts.models import StaffProfile

    # Full CRUD trio — models with editable fields and meaningful
    # UPDATE diffs. Sprint 23A adds StaffProfile and
    # StaffAssignmentRequest here.
    for model in (
        User,
        Company,
        Building,
        Customer,
        # Sprint 27C — CustomerCompanyPolicy joins the full-CRUD audit
        # trio so every visibility / permission-policy toggle lands
        # on the AuditLog with the before/after diff.
        CustomerCompanyPolicy,
        StaffProfile,
        StaffAssignmentRequest,
    ):
        pre_save.connect(_on_pre_save, sender=model, weak=False, dispatch_uid=f"audit:pre:{model.__name__}")
        post_save.connect(_on_post_save, sender=model, weak=False, dispatch_uid=f"audit:post:{model.__name__}")
        post_delete.connect(_on_post_delete, sender=model, weak=False, dispatch_uid=f"audit:del:{model.__name__}")
    for model in (
        CompanyUserMembership,
        BuildingManagerAssignment,
        CustomerUserMembership,
        # Sprint 23A — staff visibility + multi-staff ticket
        # assignment use the same lightweight CREATE/DELETE shape
        # as the other membership tables. StaffProfile uses the
        # full CRUD trio (see below) because it has editable
        # fields.
        BuildingStaffVisibility,
        TicketStaffAssignment,
    ):
        # Memberships use a different handler set — see comment above.
        # No pre_save (no editable fields, no UPDATE shape).
        post_save.connect(
            _on_membership_post_save,
            sender=model,
            weak=False,
            dispatch_uid=f"audit:membership:post:{model.__name__}",
        )
        post_delete.connect(
            _on_membership_post_delete,
            sender=model,
            weak=False,
            dispatch_uid=f"audit:membership:del:{model.__name__}",
        )

    # Sprint 14 — customer↔building link and per-user-per-building
    # access. Different shape from the Sprint-7 trio above, so they
    # use dedicated handlers. CREATE and DELETE are recorded with
    # rich payloads.
    post_save.connect(
        _on_customer_building_link_post_save,
        sender=CustomerBuildingMembership,
        weak=False,
        dispatch_uid="audit:customer_building:post:CustomerBuildingMembership",
    )
    post_delete.connect(
        _on_customer_building_link_post_delete,
        sender=CustomerBuildingMembership,
        weak=False,
        dispatch_uid="audit:customer_building:del:CustomerBuildingMembership",
    )
    # Sprint 23A: pre_save snapshot is required so post_save can
    # emit a meaningful UPDATE log for access_role / permission_
    # overrides / is_active mutations. CREATE / DELETE shapes are
    # unchanged and still go through the dedicated handlers above.
    pre_save.connect(
        _on_customer_user_access_pre_save,
        sender=CustomerUserBuildingAccess,
        weak=False,
        dispatch_uid="audit:customer_access:pre:CustomerUserBuildingAccess",
    )
    post_save.connect(
        _on_customer_user_access_post_save,
        sender=CustomerUserBuildingAccess,
        weak=False,
        dispatch_uid="audit:customer_access:post:CustomerUserBuildingAccess",
    )
    post_delete.connect(
        _on_customer_user_access_post_delete,
        sender=CustomerUserBuildingAccess,
        weak=False,
        dispatch_uid="audit:customer_access:del:CustomerUserBuildingAccess",
    )

    # Sprint 27B (closes G-B4): UPDATE-diff handler for the per-building
    # `can_request_assignment` toggle on BuildingStaffVisibility. The
    # CREATE/DELETE shape stays on the existing membership handlers
    # registered above; this pair adds the missing UPDATE coverage.
    pre_save.connect(
        _on_building_staff_visibility_pre_save,
        sender=BuildingStaffVisibility,
        weak=False,
        dispatch_uid="audit:bsv:pre:BuildingStaffVisibility",
    )
    post_save.connect(
        _on_building_staff_visibility_post_save_update,
        sender=BuildingStaffVisibility,
        weak=False,
        dispatch_uid="audit:bsv:post_update:BuildingStaffVisibility",
    )


_connect()
