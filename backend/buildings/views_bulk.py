"""
Sprint 154 §I.2/§I.3/§I.4 — the buildings bulk-write family.

Three endpoints live here:

  POST /api/buildings/bulk-link/        link/unlink N buildings x M targets
  POST /api/buildings/bulk-deactivate/  archive N buildings
  POST /api/buildings/bulk-update/      patch an allow-listed field set

FOUR relations, ONE implementation, four thin specs — not four copies.
`_RELATION_SPECS` below is the single table that says, per relation,
which through-model carries the link, which FK points at the building,
which FK points at the target, how a target id is resolved to a row the
ACTOR may touch, and what makes a (building, target) pair legal. Adding
a fifth relation is a dict entry, not a fifth endpoint.

Three invariants hold for every endpoint in this file:

1. **All-or-nothing.** Every id is resolved and every pair validated
   BEFORE anything is written; one bad id rejects the whole batch inside
   a single `transaction.atomic()` with zero writes.

2. **The rejection is indistinguishable.** An id belonging to another
   tenant, an id that never existed, and a pair that would cross a
   company boundary all produce the SAME response body, with no id
   interpolated into the message. Anything else is an existence oracle
   over another tenant's ids (H-1, the Sprint 142.1 class). The tests
   assert equality of the rendered bodies, not "both are 400".

3. **Rows go through real `save()` / `objects.create()` / instance
   `.delete()`.** All four through-models are registered with audit
   signal handlers; a queryset `.update()` would write no AuditLog row
   at all (H-10).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User, UserRole
from accounts.permissions import IsSuperAdminOrCompanyAdminForCompany
from accounts.scoping import (
    manageable_user_ids_for,
    scope_buildings_for,
    scope_customers_for,
)
from audit import context as audit_context
from customers.models import (
    Contact,
    ContactBuildingLink,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
)

from .models import Building, BuildingManagerAssignment, BuildingStaffVisibility


# ---------------------------------------------------------------------------
# Shared rejection shape
# ---------------------------------------------------------------------------

ERR_BULK_LINK_INVALID = "bulk_link_target_invalid"
_BULK_LINK_INVALID_MESSAGE = (
    "One or more of the selected buildings or targets could not be "
    "resolved, or cannot be linked to each other. Nothing was changed."
)

ERR_BULK_DEACTIVATE_BUILDING_INVALID = "bulk_deactivate_building_invalid"
_BULK_DEACTIVATE_INVALID_MESSAGE = (
    "One or more of the selected buildings could not be resolved. "
    "No buildings were deactivated."
)

ERR_BULK_UPDATE_INVALID = "bulk_update_invalid"
_BULK_UPDATE_INVALID_MESSAGE = (
    "One or more of the selected rows could not be resolved. "
    "Nothing was changed."
)

ERR_BULK_UPDATE_FIELD_INVALID = "bulk_update_field_not_allowed"


def _reject(field: str, message: str, code: str):
    """Raise a 400 whose body is a CONSTANT — no id, no name, nothing
    that differs between 'not yours' and 'does not exist'."""
    raise serializers.ValidationError(
        {field: [serializers.ErrorDetail(message, code=code)]}
    )


# ---------------------------------------------------------------------------
# The relation table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RelationSpec:
    """One linkable relation between a Building and something else."""

    key: str
    through_model: type
    building_field: str
    target_field: str
    # (actor, ids) -> {id: obj} for every id the actor may act on. An id
    # missing from the returned mapping is rejected, whatever the reason.
    resolve_targets: Callable
    # (building, target) -> bool. False rejects the whole batch with the
    # same constant message as an unresolvable id.
    pair_is_legal: Callable
    # Optional extra work when a link is REMOVED (see the customers spec).
    on_unlink: Callable | None = None


def _resolve_customers(actor, ids):
    return {c.id: c for c in scope_customers_for(actor).filter(id__in=ids)}


def _resolve_users_with_role(actor, ids, role):
    """Users of one role that the actor may administer.

    `manageable_user_ids_for` returns None for a SUPER_ADMIN, meaning
    unrestricted — treating that as an empty set would lock out exactly
    the role that can do everything.
    """
    qs = User.objects.filter(
        id__in=ids, role=role, is_active=True, deleted_at__isnull=True
    )
    allowed = manageable_user_ids_for(actor)
    if allowed is not None:
        qs = qs.filter(id__in=allowed)
    return {u.id: u for u in qs}


def _resolve_managers(actor, ids):
    return _resolve_users_with_role(actor, ids, UserRole.BUILDING_MANAGER)


def _resolve_staff(actor, ids):
    return _resolve_users_with_role(actor, ids, UserRole.STAFF)


def _resolve_contacts(actor, ids):
    """A contact is reachable iff its CUSTOMER is in the actor's scope —
    the contact has no independent tenancy of its own."""
    customer_ids = scope_customers_for(actor).values_list("id", flat=True)
    return {
        c.id: c
        for c in Contact.objects.filter(
            id__in=ids, customer_id__in=customer_ids
        ).select_related("customer")
    }


def _same_company_customer(building, customer) -> bool:
    return customer.company_id == building.company_id


def _same_company_contact(building, contact) -> bool:
    # A contact belongs to a customer, and that customer's company is the
    # tenancy that must match. Deliberately NOT "the contact's customer
    # must already be linked to this building": a contact person can be
    # the site contact for a building before the commercial link is
    # recorded, and the owner asked for contacts to be manageable from
    # the building page directly.
    return contact.customer.company_id == building.company_id


def _user_company_matches(building, user) -> bool:
    """A manager / staff member may be attached to any building of a
    company they are already recognised in, OR to a building in a company
    where they have no rows yet — which is the normal case for a brand
    new manager. The tenancy gate that matters is the one already applied
    to the ACTOR: they must own the building (checked in the view via
    `scope_buildings_for` + `check_object_permissions`), and they must be
    allowed to administer the user (checked in `_resolve_users_with_role`).
    Those two together are exactly the pair of gates the single-row
    endpoints apply from their two opposite ends.
    """
    return True


def _unlink_customer_cascade(building, customer):
    """Removing a customer<->building link must ALSO revoke every
    per-user access row for that pair.

    Copied in intent from `CustomerBuildingDeleteView`, which documents
    why: an orphaned `CustomerUserBuildingAccess` row still matches the
    scope subquery, so leaving it behind silently keeps a customer user's
    visibility on a building their customer is no longer linked to. A
    bulk unlink that skipped this would be a scope leak, not a tidiness
    issue.
    """
    CustomerUserBuildingAccess.objects.filter(
        membership__customer=customer, building=building
    ).delete()


_RELATION_SPECS: dict[str, _RelationSpec] = {
    "customers": _RelationSpec(
        key="customers",
        through_model=CustomerBuildingMembership,
        building_field="building",
        target_field="customer",
        resolve_targets=_resolve_customers,
        pair_is_legal=_same_company_customer,
        on_unlink=_unlink_customer_cascade,
    ),
    "managers": _RelationSpec(
        key="managers",
        through_model=BuildingManagerAssignment,
        building_field="building",
        target_field="user",
        resolve_targets=_resolve_managers,
        pair_is_legal=_user_company_matches,
    ),
    "staff": _RelationSpec(
        key="staff",
        through_model=BuildingStaffVisibility,
        building_field="building",
        target_field="user",
        resolve_targets=_resolve_staff,
        pair_is_legal=_user_company_matches,
    ),
    "contacts": _RelationSpec(
        key="contacts",
        through_model=ContactBuildingLink,
        building_field="building",
        target_field="contact",
        resolve_targets=_resolve_contacts,
        pair_is_legal=_same_company_contact,
    ),
}


# ---------------------------------------------------------------------------
# Bulk link / unlink
# ---------------------------------------------------------------------------


class _BulkLinkInputSerializer(serializers.Serializer):
    buildings = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False
    )
    relation = serializers.ChoiceField(choices=sorted(_RELATION_SPECS))
    targets = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False
    )
    mode = serializers.ChoiceField(choices=["link", "unlink"], default="link")


class BuildingBulkLinkView(APIView):
    """POST /api/buildings/bulk-link/

    Body: {"buildings": [id,...], "relation": "customers"|"staff"|
           "managers"|"contacts", "targets": [id,...],
           "mode": "link"|"unlink"}
    Response: {"created": N, "removed": N, "already_linked": N,
               "not_linked": N}

    Every one of the N x M pairs is handled in ONE request. The
    alternative — a client-side loop of N x M POSTs — is recorded twice
    in the checklist's NEXT queue as the anti-pattern this replaces.

    Re-linking an existing pair is NOT an error: it counts as
    `already_linked`, so pressing the button twice is safe.
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]

    def post(self, request, *args, **kwargs):
        payload = _BulkLinkInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        building_ids = list(dict.fromkeys(payload.validated_data["buildings"]))
        target_ids = list(dict.fromkeys(payload.validated_data["targets"]))
        spec = _RELATION_SPECS[payload.validated_data["relation"]]
        mode = payload.validated_data["mode"]

        # (1) Buildings, through the actor's own building scope.
        buildings = {
            b.id: b
            for b in scope_buildings_for(request.user).filter(id__in=building_ids)
        }
        if len(buildings) != len(building_ids):
            _reject("buildings", _BULK_LINK_INVALID_MESSAGE, ERR_BULK_LINK_INVALID)
        for building in buildings.values():
            self.check_object_permissions(request, building)

        # (2) Targets, through THAT relation's own scoping helper.
        targets = spec.resolve_targets(request.user, target_ids)
        if len(targets) != len(target_ids):
            _reject("targets", _BULK_LINK_INVALID_MESSAGE, ERR_BULK_LINK_INVALID)

        # (3) Every pair, before any write. A cross-company pair is
        # rejected with the SAME body — creating it would produce a row
        # the single-row serializers refuse over the API.
        pairs = []
        for building in buildings.values():
            for target in targets.values():
                if not spec.pair_is_legal(building, target):
                    _reject(
                        "targets",
                        _BULK_LINK_INVALID_MESSAGE,
                        ERR_BULK_LINK_INVALID,
                    )
                pairs.append((building, target))

        try:
            audit_context.set_current_reason(f"building_bulk_{mode}_{spec.key}")
        except Exception:  # pragma: no cover - defensive
            pass

        created = removed = already_linked = not_linked = 0
        with transaction.atomic():
            for building, target in pairs:
                lookup = {
                    spec.building_field: building,
                    spec.target_field: target,
                }
                existing = spec.through_model.objects.filter(**lookup).first()
                if mode == "link":
                    if existing is not None:
                        already_linked += 1
                        continue
                    # objects.create() fires post_save, so the audit row
                    # is written. A bulk_create would not.
                    spec.through_model.objects.create(**lookup)
                    created += 1
                else:
                    if existing is None:
                        not_linked += 1
                        continue
                    if spec.on_unlink is not None:
                        spec.on_unlink(building, target)
                    # Instance .delete() fires post_delete per row.
                    existing.delete()
                    removed += 1

        return Response(
            {
                "created": created,
                "removed": removed,
                "already_linked": already_linked,
                "not_linked": not_linked,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Bulk deactivate (I.3) — mirrors CustomerBulkDeactivateView exactly
# ---------------------------------------------------------------------------


class _BulkDeactivateInputSerializer(serializers.Serializer):
    buildings = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False
    )


class BuildingBulkDeactivateView(APIView):
    """POST /api/buildings/bulk-deactivate/  {"buildings": [id,...]}
    -> {"deactivated": N}

    The building mirror of `customers.views.CustomerBulkDeactivateView`,
    down to the indistinguishable-rejection rule. "Deactivate" is
    `is_active=False`, matching `perform_destroy`; a Building is never
    hard-deleted (tickets and extra work PROTECT it).
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]

    def post(self, request, *args, **kwargs):
        payload = _BulkDeactivateInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        requested_ids = list(dict.fromkeys(payload.validated_data["buildings"]))

        scoped = {
            b.id: b
            for b in scope_buildings_for(request.user).filter(id__in=requested_ids)
        }
        if len(scoped) != len(requested_ids):
            _reject(
                "buildings",
                _BULK_DEACTIVATE_INVALID_MESSAGE,
                ERR_BULK_DEACTIVATE_BUILDING_INVALID,
            )
        for building in scoped.values():
            self.check_object_permissions(request, building)

        try:
            audit_context.set_current_reason("building_bulk_deactivate")
        except Exception:  # pragma: no cover - defensive
            pass

        deactivated = 0
        with transaction.atomic():
            for building_id in requested_ids:
                building = scoped[building_id]
                if not building.is_active:
                    continue
                building.is_active = False
                building.save(update_fields=["is_active"])
                deactivated += 1

        return Response({"deactivated": deactivated}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Bulk update (I.4)
# ---------------------------------------------------------------------------

# Explicitly allow-listed. A key outside this set is a 400, NEVER a
# silent skip: silently ignoring it means the operator believes an edit
# applied that did not.
#
# `is_active` is deliberately NOT here. It is read-only on both
# serializers and the lifecycle has its own endpoints with their own
# gates (reactivate is SUPER_ADMIN-only). Status is handled by the
# dedicated `status` key below, which routes through that same lifecycle
# path — a blind PATCH of `is_active` would be silently dropped by DRF,
# which is the exact trap Sprint 153's quick-edit dialog hit.
_BUILDING_PATCHABLE_FIELDS = frozenset({"city", "country", "postal_code"})
_CUSTOMER_PATCHABLE_FIELDS = frozenset({"language"})
_STATUS_KEY = "status"
_STATUS_VALUES = frozenset({"active", "inactive"})


class _BulkUpdateMixin:
    """Shared body of the two bulk-update endpoints."""

    id_field: str = ""
    patchable_fields: frozenset = frozenset()

    def scope(self, user):  # pragma: no cover - overridden
        raise NotImplementedError

    def _validate_patch(self, patch):
        if not isinstance(patch, dict) or not patch:
            _reject(
                "patch",
                "Provide at least one field to change.",
                ERR_BULK_UPDATE_FIELD_INVALID,
            )
        unknown = set(patch) - self.patchable_fields - {_STATUS_KEY}
        if unknown:
            # Naming the offending KEY is safe — a field name is part of
            # the caller's own request, not another tenant's data.
            _reject(
                "patch",
                (
                    "These fields cannot be changed in bulk: "
                    f"{', '.join(sorted(unknown))}."
                ),
                ERR_BULK_UPDATE_FIELD_INVALID,
            )
        if _STATUS_KEY in patch and patch[_STATUS_KEY] not in _STATUS_VALUES:
            _reject(
                "patch",
                "Status must be either 'active' or 'inactive'.",
                ERR_BULK_UPDATE_FIELD_INVALID,
            )
        return patch

    def post(self, request, *args, **kwargs):
        raw_ids = request.data.get(self.id_field)
        if not isinstance(raw_ids, list) or not raw_ids:
            _reject(
                self.id_field,
                "Select at least one row.",
                ERR_BULK_UPDATE_INVALID,
            )
        try:
            requested_ids = list(dict.fromkeys(int(i) for i in raw_ids))
        except (TypeError, ValueError):
            _reject(self.id_field, _BULK_UPDATE_INVALID_MESSAGE, ERR_BULK_UPDATE_INVALID)

        patch = self._validate_patch(request.data.get("patch"))

        scoped = {
            row.id: row for row in self.scope(request.user).filter(id__in=requested_ids)
        }
        if len(scoped) != len(requested_ids):
            _reject(
                self.id_field, _BULK_UPDATE_INVALID_MESSAGE, ERR_BULK_UPDATE_INVALID
            )
        for row in scoped.values():
            self.check_object_permissions(request, row)

        # Reactivation is SUPER_ADMIN-only everywhere else in the system
        # (`reactivate` on both viewsets), so it is here too. Without this
        # a COMPANY_ADMIN could restore rows through the bulk door that
        # the single-row door refuses them.
        wants_activate = patch.get(_STATUS_KEY) == "active"
        if wants_activate and request.user.role != UserRole.SUPER_ADMIN:
            _reject(
                "patch",
                "Only a Super Admin can reactivate.",
                ERR_BULK_UPDATE_FIELD_INVALID,
            )

        try:
            audit_context.set_current_reason(f"{self.id_field}_bulk_update")
        except Exception:  # pragma: no cover - defensive
            pass

        updated = 0
        with transaction.atomic():
            for row_id in requested_ids:
                row = scoped[row_id]
                changed = []
                for field in self.patchable_fields:
                    if field in patch:
                        setattr(row, field, patch[field])
                        changed.append(field)
                if _STATUS_KEY in patch:
                    target_active = patch[_STATUS_KEY] == "active"
                    if row.is_active != target_active:
                        row.is_active = target_active
                        changed.append("is_active")
                if not changed:
                    continue
                row.save(update_fields=changed)
                updated += 1

        return Response({"updated": updated}, status=status.HTTP_200_OK)


class BuildingBulkUpdateView(_BulkUpdateMixin, APIView):
    """POST /api/buildings/bulk-update/
    Body: {"buildings": [id,...], "patch": {"city": "...", "status": "..."}}
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]
    id_field = "buildings"
    patchable_fields = _BUILDING_PATCHABLE_FIELDS

    def scope(self, user):
        return scope_buildings_for(user)


class CustomerBulkUpdateView(_BulkUpdateMixin, APIView):
    """POST /api/customers/bulk-update/
    Body: {"customers": [id,...], "patch": {"language": "nl", "status": "..."}}

    Lives in this module rather than `customers/` so the two bulk-update
    endpoints cannot drift apart: they share `_BulkUpdateMixin` verbatim
    and differ only in their id field, their allow-list and their scope.
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]
    id_field = "customers"
    patchable_fields = _CUSTOMER_PATCHABLE_FIELDS

    def scope(self, user):
        return scope_customers_for(user)
