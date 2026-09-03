"""
Sprint 158 §1 — who may be assigned to work at a building, and as what.

ONE definition, used by three callers: the extra-work assign endpoint,
the extra-work candidate READ, and the ticket assign endpoint. That is
the point of the module — Sprint 152.1 §1a is the standing lesson here:
when "who is offerable" and "who is acceptable" are computed in two
places they drift, and the operator gets a picker full of options that
always fail.

It lives in `buildings/` rather than in either consumer because the rule
is derived from BUILDING relations, and both `extra_work` and `tickets`
already depend on `buildings`. Putting it in one of them would make the
other import across a module boundary it has no other reason to cross.

**The rule.** Eligibility comes from the request's / ticket's BUILDING,
never from the company:

  WORKER  — holds `BuildingStaffVisibility` on that building.
  MANAGER — holds `BuildingManagerAssignment` on that building, OR is a
            COMPANY_ADMIN of that building's company.

Sprint 157 used ONE set `{STAFF, BUILDING_MANAGER, COMPANY_ADMIN}` for
both roles, so a field worker could be made the MANAGER of a request.
The owner's words: managers are assigned differently from staff,
according to the authorised people at that building.

**Why COMPANY_ADMIN counts as a manager candidate.** A COMPANY_ADMIN is
authoritative over every building of their company by construction —
`scope_buildings_for` hands them all of it — so excluding them would mean
a provider's own administrator could not be named responsible for a job
in their own company while a building manager one level down could. They
are NOT admitted as WORKER candidates: doing the work on site is a
different claim from being answerable for it, and nothing about the
admin role implies the first.

`TicketManagerAssignment`'s own docstring already stated this precondition
for tickets ("Holding [BuildingManagerAssignment] is the eligibility
precondition for being added here"). This module makes the same rule
executable and shares it with extra work.
"""
from __future__ import annotations

from django.db.models import Q

from accounts.models import User, UserRole
from accounts.scoping import manageable_user_ids_for


# The two assignment roles, as plain strings so this module imports
# nothing from `extra_work` or `tickets` — both define their own enum and
# both use these values.
ROLE_WORKER = "WORKER"
ROLE_MANAGER = "MANAGER"


def eligible_users_for_building(building, role: str, actor=None):
    """Everyone who may be assigned to `building` in `role`.

    `actor` narrows the result to people that actor may administer, so a
    picker never offers somebody the caller could not assign anyway. Pass
    None for the raw eligibility set (used by the automatic
    manager-carry-over on ticket spawn, which acts on the system's behalf
    rather than a user's).

    Inactive and soft-deleted accounts are excluded everywhere: assigning
    a departed employee is never the intent, and offering them is noise.
    """
    if role == ROLE_MANAGER:
        # A named building manager, or an admin of the building's own
        # company. See the module docstring for why the second is in.
        eligible = Q(building_assignments__building=building) | Q(
            role=UserRole.COMPANY_ADMIN,
            company_memberships__company_id=building.company_id,
        )
    elif role == ROLE_WORKER:
        eligible = Q(building_visibility__building=building)
    else:  # pragma: no cover - the callers validate the choice first
        return User.objects.none()

    qs = User.objects.filter(
        is_active=True, deleted_at__isnull=True
    ).filter(eligible)

    if actor is not None:
        if getattr(actor, "role", None) == UserRole.BUILDING_MANAGER:
            # P-15 (P-14's S2 finding, repro ticket 311 / users 6-5-12)
            # — a building manager ADMINISTERS nobody
            # (`manageable_user_ids_for` answers an empty set for the
            # role), but assignment eligibility is a BUILDING fact and
            # the write validators judge the TARGET against the
            # building alone. Narrowing this read by user-
            # administration emptied the BM's picker on tickets they
            # can staff — picker ⊂ validator, the Sprint 152.1 §1a
            # class. A BM assigned to THIS building reads the raw
            # building set (exactly what the validator accepts); one
            # who is not assigned gets nothing.
            from .models import BuildingManagerAssignment

            if not BuildingManagerAssignment.objects.filter(
                user=actor, building=building
            ).exists():
                return User.objects.none()
        else:
            allowed = manageable_user_ids_for(actor)
            # `None` means unrestricted (SUPER_ADMIN). Treating it as an
            # empty set would lock out exactly the role that can do
            # everything — the trap this helper's siblings documented.
            if allowed is not None:
                qs = qs.filter(id__in=allowed)

    # `distinct()` is load-bearing: a manager of one building matched
    # through two link rows, or an admin matching both legs of the OR,
    # would otherwise appear twice in the picker and be counted twice.
    return qs.distinct().order_by("full_name", "email")


def resolve_assignable_users(building, role: str, ids, actor=None) -> dict:
    """`{id: user}` for every id in `ids` that is eligible.

    An id missing from the result is rejected by the caller, whatever the
    reason — not eligible, out of the actor's reach, inactive, or simply
    not a real id. Collapsing those into one answer is deliberate: a user
    who exists but is not eligible must be indistinguishable from an id
    that does not exist (H-1, the Sprint 142.1 oracle class), and the
    only way to guarantee that is for the caller to have no way to tell
    them apart in the first place.
    """
    return {
        user.id: user
        for user in eligible_users_for_building(building, role, actor).filter(
            id__in=ids
        )
    }
