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
    Contact,
    ContactBuildingLink,
    Customer,
    CustomerBuildingMembership,
    CustomerCompanyPolicy,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from extra_work.models import (
    CustomerServicePrice,
    ExtraWorkRequestItem,
    Proposal,
    ProposalLine,
    Service,
    ServiceCategory,
)
from planned_work.models import (
    PlannedOccurrence,
    RecurringJob,
    RecurringJobDefaultManager,
    RecurringJobDefaultStaff,
)
from tickets.models import (
    StaffAssignmentRequest,
    TicketAttachment,
    TicketManagerAssignment,
    TicketMessage,
    TicketStaffAssignment,
)

from . import context
from .diff import (
    compute_create_changes,
    compute_delete_changes,
    compute_update_changes,
    serialize_value,
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
        # Sprint 27F-B2 (G-B6): every audit row records the operator-supplied
        # reason (default "") + a JSON snapshot of the actor's role + scope
        # anchors at write time (default {}). Reason is opt-in per-view via
        # `audit.context.set_current_reason`; actor_scope is seeded by the
        # middleware but resolved lazily here against the live request.user
        # because DRF JWT auth populates request.user at the VIEW layer
        # (after middleware fired with AnonymousUser).
        actor = context.get_current_actor()
        actor_scope = context.get_current_actor_scope() or {}
        if not actor_scope and actor is not None:
            actor_scope = context.snapshot_actor_scope(actor) or {}
        AuditLog.objects.create(
            actor=actor,
            action=action,
            target_model=_label(instance),
            target_id=instance.pk,
            changes=changes or {},
            request_ip=context.get_current_request_ip(),
            request_id=context.get_current_request_id(),
            reason=context.get_current_reason(),
            actor_scope=actor_scope,
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
        #
        # B6: `BuildingManagerAssignment` now also has a dedicated
        # UPDATE-diff handler
        # (`_on_building_manager_assignment_post_save_update`) for its
        # new `permission_overrides` JSONField. Skip the same way so
        # an override flip lands as exactly one AuditLog UPDATE row,
        # not two.
        # Sprint 14E: `TicketStaffAssignment` now carries editable slot
        # fields (schedule / window / status / completion). Its UPDATE
        # diff is owned by the dedicated handler
        # (`_on_ticket_staff_assignment_post_save_update`) below — skip
        # the membership-fallback UPDATE here so a slot edit lands as
        # exactly one AuditLog row, not two. CREATE / DELETE still flow
        # through the membership handlers (the shape is unchanged).
        if sender.__name__ in {
            "BuildingStaffVisibility",
            "BuildingManagerAssignment",
            "TicketStaffAssignment",
        }:
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
# Sprint 28 Batch 10 adds `visibility_level` to the tracked tuple — the
# UPDATE-only handler below iterates this tuple and emits a single
# AuditLog row covering whichever fields changed.
# Sprint 28 Batch 11 adds `staff_completion_routes_to_customer` — the
# per-staff-per-building routing flag for STAFF completions. Same
# handler iterates the tuple, so the flip lands as a one-row UPDATE
# diff alongside any other tracked-field change in the same PATCH.
_BSV_TRACKED_FIELDS = (
    "can_request_assignment",
    "visibility_level",
    "staff_completion_routes_to_customer",
)


# B6 — `BuildingManagerAssignment.permission_overrides` is the per-(BM,
# building) override map for the two BM-revocable osius.* keys
# (`osius.building_manager.override_customer_decision`,
# `osius.building_manager.prepare_extra_work_proposal`). The model is
# already on the membership-style CREATE / DELETE handlers above; the
# pair below adds the UPDATE-diff coverage for the new field so each
# override flip lands as a single AuditLog row with before/after JSON.
# Mirrors the BSV UPDATE-only pattern.
_BMA_TRACKED_FIELDS = ("permission_overrides",)


def _bma_snapshot_for_pre_save(instance):
    """Snapshot the B6 editable field on BuildingManagerAssignment."""
    if instance.pk is None:
        return None
    from buildings.models import BuildingManagerAssignment

    try:
        previous = BuildingManagerAssignment.objects.get(pk=instance.pk)
    except BuildingManagerAssignment.DoesNotExist:
        return None
    return {field: getattr(previous, field) for field in _BMA_TRACKED_FIELDS}


def _on_building_manager_assignment_pre_save(sender, instance, **kwargs):
    """Snapshot the pre-update state so post_save can diff it."""
    try:
        snapshot = _bma_snapshot_for_pre_save(instance)
        _state_map()[
            ("buildings.BuildingManagerAssignment", instance.pk)
        ] = snapshot
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "audit: BuildingManagerAssignment pre_save snapshot failed for #%s",
            getattr(instance, "pk", None),
        )


def _on_building_manager_assignment_post_save_update(
    sender, instance, created, **kwargs
):
    """UPDATE-only handler: emit a CRUD UPDATE row with the diff of
    the tracked field. CREATE is intentionally a no-op here — the
    membership handler already emits the rich CREATE payload."""
    if created:
        return
    try:
        snapshot = _state_map().pop(
            ("buildings.BuildingManagerAssignment", instance.pk), None
        )
        if snapshot is None:
            return
        diff = {}
        for field in _BMA_TRACKED_FIELDS:
            before = snapshot[field]
            after = getattr(instance, field)
            if before != after:
                diff[field] = {"before": before, "after": after}
        if not diff:
            return
        _create_log(instance, AuditAction.UPDATE, diff)
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "audit: BuildingManagerAssignment post_save UPDATE failed for #%s",
            getattr(instance, "pk", None),
        )


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


# Sprint 14E — `TicketStaffAssignment` slot fields. The model is on the
# membership-style CREATE / DELETE handlers (the slot CREATE = "staff
# assigned"; DELETE = "slot removed"). This pair adds the UPDATE-diff
# coverage for the new dated-slot fields (schedule / window / note /
# status / completion). Mirrors the BMA / BSV UPDATE-only pattern, but
# uses `serialize_value` because the tracked tuple includes datetimes
# and a FK id that are not natively JSON-serialisable.
_TSA_TRACKED_FIELDS = (
    "scheduled_start_at",
    "scheduled_end_at",
    "time_window_label",
    "assignment_note",
    "slot_status",
    "completion_note",
    "completed_at",
    "completed_by_id",
    "unable_to_complete_reason",
)


def _tsa_snapshot_for_pre_save(instance):
    if instance.pk is None:
        return None
    from tickets.models import TicketStaffAssignment

    try:
        previous = TicketStaffAssignment.objects.get(pk=instance.pk)
    except TicketStaffAssignment.DoesNotExist:
        return None
    return {
        field: serialize_value(getattr(previous, field))
        for field in _TSA_TRACKED_FIELDS
    }


def _on_ticket_staff_assignment_pre_save(sender, instance, **kwargs):
    try:
        snapshot = _tsa_snapshot_for_pre_save(instance)
        _state_map()[
            ("tickets.TicketStaffAssignment", instance.pk)
        ] = snapshot
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "audit: TicketStaffAssignment pre_save snapshot failed for #%s",
            getattr(instance, "pk", None),
        )


def _on_ticket_staff_assignment_post_save_update(
    sender, instance, created, **kwargs
):
    """UPDATE-only handler: emit a CRUD UPDATE row with the diff of the
    tracked slot fields. CREATE is a no-op here — the membership handler
    already emits the CREATE payload."""
    if created:
        return
    try:
        snapshot = _state_map().pop(
            ("tickets.TicketStaffAssignment", instance.pk), None
        )
        if snapshot is None:
            return
        diff = {}
        for field in _TSA_TRACKED_FIELDS:
            before = snapshot[field]
            after = serialize_value(getattr(instance, field))
            if before != after:
                diff[field] = {"before": before, "after": after}
        if not diff:
            return
        _create_log(instance, AuditAction.UPDATE, diff)
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "audit: TicketStaffAssignment post_save UPDATE failed for #%s",
            getattr(instance, "pk", None),
        )


# ===========================================================================
# Sprint 12 — PlannedOccurrence per-occurrence price / schedule-window
# override. The occurrence is intentionally NOT in the generic CRUD trio:
# its STATUS lifecycle (PLANNED/TICKET_CREATED/COMPLETED/...) is the H-11
# workflow trail recorded on PlannedOccurrenceStatusHistory, and generation
# CREATEs are system writes we don't want to spam the audit feed with. This
# dedicated UPDATE-ONLY handler tracks ONLY the manager-editable pricing +
# window fields, so a per-occurrence override lands as exactly one AuditLog
# UPDATE row, while status/date changes (generation, reconcile) never emit a
# generic CRUD row here (they own the status-history trail). No double-write.
# ===========================================================================
_PO_TRACKED_FIELDS = (
    "pricing_mode",
    "fixed_price",
    "vat_pct",
    "preferred_start_time",
    "time_window_label",
)


def _po_snapshot_for_pre_save(instance):
    if instance.pk is None:
        return None
    try:
        previous = PlannedOccurrence.objects.get(pk=instance.pk)
    except PlannedOccurrence.DoesNotExist:
        return None
    return {
        field: serialize_value(getattr(previous, field))
        for field in _PO_TRACKED_FIELDS
    }


def _on_planned_occurrence_pre_save(sender, instance, **kwargs):
    try:
        snapshot = _po_snapshot_for_pre_save(instance)
        _state_map()[("planned_work.PlannedOccurrence", instance.pk)] = snapshot
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "audit: PlannedOccurrence pre_save snapshot failed for #%s",
            getattr(instance, "pk", None),
        )


def _on_planned_occurrence_post_save_update(sender, instance, created, **kwargs):
    """UPDATE-only handler: emit a CRUD UPDATE row with the diff of the
    tracked pricing/window fields. CREATE (generation) is a no-op; status /
    date changes (reconcile) leave the tracked fields untouched so the diff
    is empty and no row is written."""
    if created:
        return
    try:
        snapshot = _state_map().pop(
            ("planned_work.PlannedOccurrence", instance.pk), None
        )
        if snapshot is None:
            return
        diff = {}
        for field in _PO_TRACKED_FIELDS:
            before = snapshot[field]
            after = serialize_value(getattr(instance, field))
            if before != after:
                diff[field] = {"before": before, "after": after}
        if not diff:
            return
        _create_log(instance, AuditAction.UPDATE, diff)
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "audit: PlannedOccurrence post_save UPDATE failed for #%s",
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
        # Sprint 28 Batch 4 — customer-side phone-book Contact rows.
        # Editable fields (full_name / email / phone / role_label /
        # notes / building) produce meaningful UPDATE diffs, so the
        # full CRUD trio is the right shape.
        Contact,
        # Sprint 28 Batch 5 — provider service catalog
        # (ServiceCategory + Service) and per-customer contract
        # prices (CustomerServicePrice). All three carry editable
        # fields (e.g. is_active toggles, price / VAT updates,
        # validity-window changes) that need full CRUD audit.
        ServiceCategory,
        Service,
        CustomerServicePrice,
        # Sprint 28 Batch 6 — cart line items on ExtraWorkRequest.
        # Each row has editable fields (quantity, requested_date,
        # customer_note) so the full CRUD trio is the right shape:
        # CREATE / UPDATE / DELETE all produce meaningful diffs.
        # NB: parent `ExtraWorkRequest` is intentionally NOT registered
        # in Batch 6 — adding it (in particular tracking the new
        # `routing_decision` field) is scope creep for this batch and
        # is left to a follow-up that designs the right shape (full
        # CRUD vs targeted-field UPDATE diff) for the request itself.
        ExtraWorkRequestItem,
        # Sprint 28 Batch 8 — provider-built proposal flow. Both the
        # parent `Proposal` row (status, totals, override_*) and the
        # `ProposalLine` rows (quantity, prices, dual-note fields,
        # is_approved_for_spawn) carry editable fields that produce
        # meaningful diffs.
        #
        # NB: `ProposalStatusHistory` and `ProposalTimelineEvent` are
        # intentionally NOT registered here — those history rows ARE
        # the workflow-override audit trail per H-11 (the status row
        # carries `is_override` + `override_reason` itself). Adding
        # them to the generic AuditLog would double-write the same
        # fact and break the H-11 separation between permission
        # changes and workflow transitions.
        Proposal,
        ProposalLine,
        # Sprint 11B — recurring-job templates (full CRUD; editable fields).
        #
        # NB: `PlannedOccurrence` and `PlannedOccurrenceStatusHistory` are
        # intentionally NOT registered — the status-history row IS the H-11
        # workflow audit trail for planned work; registering it in the
        # generic AuditLog would double-write the same fact.
        RecurringJob,
        # Sprint 14E — ticket notes + attachments. TicketMessage CREATE =
        # "note added (with type)"; UPDATE = a future hide/edit; DELETE =
        # a future hard delete. TicketAttachment CREATE = "attachment
        # uploaded"; DELETE = a future remove. Both carry editable fields
        # that produce meaningful diffs. Audit reads are SUPER_ADMIN-only
        # (AuditLogViewSet) / provider-only (ticket timeline), so internal
        # note bodies never reach a customer-visible audit surface
        # (there is none). GET / download endpoints write NO audit — read
        # access logging is deliberately not added (SoT §9.1 marks it
        # "where relevant"; the default is no-write-on-read).
        #
        # NB: `TicketStatusHistory` is intentionally NOT registered — it
        # IS the H-11 workflow audit trail (status + is_override +
        # override_reason live on the row); a generic AuditLog
        # registration would double-write the lifecycle fact.
        TicketMessage,
        TicketAttachment,
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
        # Sprint 10B — explicit per-ticket responsible-manager M:N.
        # Same lightweight CREATE/DELETE shape as TicketStaffAssignment
        # (no editable fields, no UPDATE diff). Not added to
        # `_MEMBERSHIP_ENTITY_ATTR` for the same reason TicketStaffAssignment
        # is not: the `Ticket` entity has no `.name`, so the row is audited
        # with the correct target_model / target_id / actor and an empty
        # `changes` payload — byte-identical audit behaviour to staff
        # assignments.
        TicketManagerAssignment,
        # Sprint 11B — recurring-job default crew (membership-shape
        # CREATE/DELETE, no UPDATE diff; the RecurringJob entity has no
        # .name, identical to TicketStaffAssignment).
        RecurringJobDefaultStaff,
        RecurringJobDefaultManager,
        # Sprint 12B — contact↔building links (membership-shape
        # CREATE/DELETE). Contact itself stays in the full-CRUD trio; the
        # new user/contact_type/is_primary fields are auto-introspected.
        ContactBuildingLink,
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

    # B6: UPDATE-diff handler for the new `permission_overrides`
    # JSONField on BuildingManagerAssignment. CREATE/DELETE shape stays
    # on the existing membership handlers registered above; this pair
    # adds the missing UPDATE coverage so each override flip lands on
    # the audit feed.
    pre_save.connect(
        _on_building_manager_assignment_pre_save,
        sender=BuildingManagerAssignment,
        weak=False,
        dispatch_uid="audit:bma:pre:BuildingManagerAssignment",
    )
    post_save.connect(
        _on_building_manager_assignment_post_save_update,
        sender=BuildingManagerAssignment,
        weak=False,
        dispatch_uid="audit:bma:post_update:BuildingManagerAssignment",
    )

    # Sprint 14E: UPDATE-diff handler for the new dated-slot fields on
    # TicketStaffAssignment. CREATE/DELETE shape stays on the membership
    # handlers registered above (the membership UPDATE-fallback now skips
    # TicketStaffAssignment, see _on_membership_post_save) so each slot
    # edit lands as exactly one AuditLog UPDATE row.
    pre_save.connect(
        _on_ticket_staff_assignment_pre_save,
        sender=TicketStaffAssignment,
        weak=False,
        dispatch_uid="audit:tsa:pre:TicketStaffAssignment",
    )
    post_save.connect(
        _on_ticket_staff_assignment_post_save_update,
        sender=TicketStaffAssignment,
        weak=False,
        dispatch_uid="audit:tsa:post_update:TicketStaffAssignment",
    )

    # Sprint 12: UPDATE-diff handler for the per-occurrence price / window
    # override fields on PlannedOccurrence. The occurrence is NOT in the
    # generic CRUD trio (its status lifecycle is the H-11 status-history
    # trail), so this UPDATE-only pair is the ONLY generic-AuditLog coverage
    # for it — a manager price/window override lands as one AuditLog UPDATE
    # row; generation CREATEs and reconcile status/date writes never emit
    # one (the tracked fields don't change there).
    pre_save.connect(
        _on_planned_occurrence_pre_save,
        sender=PlannedOccurrence,
        weak=False,
        dispatch_uid="audit:po:pre:PlannedOccurrence",
    )
    post_save.connect(
        _on_planned_occurrence_post_save_update,
        sender=PlannedOccurrence,
        weak=False,
        dispatch_uid="audit:po:post_update:PlannedOccurrence",
    )


_connect()
