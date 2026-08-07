"""
Sprint 152 — helpers shared by the timesheets view modules.

Small on purpose: the app's view layer is split by noun
(`views_hour_types` / `views_entries` / `views_weeks` /
`views_summary`), per CLAUDE.md's app-scoped-file-names rule, and this
module holds only what genuinely belongs to more than one of them.
"""
from __future__ import annotations

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from accounts.models import UserRole
from companies.models import Company, CompanyUserMembership


ERR_COMPANY_REQUIRED = "timesheet_company_required"
ERR_TIMESHEET_CROSS_COMPANY = "timesheet_cross_company_forbidden"


def parse_bool_param(value):
    """Parse a `?is_active=true|false` query-string value. Returns
    True / False on a recognised value, None when absent or
    unparseable (the caller falls back to "no filter").
    """
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes", "y"}:
        return True
    if lowered in {"false", "0", "no", "n"}:
        return False
    return None


def parse_int_param(value):
    """Parse an optional integer query param. Returns None on absent or
    unparseable input so a caller can turn it into an empty result
    rather than a 500.
    """
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_view_company(user, supplied_company_id):
    """Pick the provider company a READ applies to, for any provider-side
    role including STAFF / BUILDING_MANAGER.

    Distinct from `resolve_target_company`, which answers the same
    question for a management WRITE and is SA/CA-only. This one resolves
    through `scope_company_ids_for_timesheets`, so it works for an
    employee who is in a company through a building assignment rather
    than a `CompanyUserMembership` — the case the write helper never has
    to handle.

    A supplied id must be inside the actor's scope. Out-of-scope reads
    as nonexistent (404), not as forbidden: this is a read path, and
    "that company exists but is not yours" is the existence oracle the
    whole module is built to avoid.
    """
    from rest_framework.exceptions import NotFound

    from .scope import scope_company_ids_for_timesheets

    scope = scope_company_ids_for_timesheets(user)

    if supplied_company_id is not None:
        if scope is not None and supplied_company_id not in scope:
            raise NotFound(detail="Company not found.")
        company = Company.objects.filter(id=supplied_company_id).first()
        if company is None:
            raise NotFound(detail="Company not found.")
        return company

    if scope is None:
        # SUPER_ADMIN with no `?company=`: the single-tenant deployment
        # defaults, a multi-tenant one must say which (Sprint 149 — an
        # SA works in ONE company at a time).
        candidates = list(Company.objects.order_by("id")[:2])
        if len(candidates) == 1:
            return candidates[0]
        raise serializers.ValidationError(
            {
                "company": [
                    serializers.ErrorDetail(
                        "`company` is required when more than one provider "
                        "Company exists.",
                        code=ERR_COMPANY_REQUIRED,
                    )
                ]
            }
        )

    ordered = sorted(scope)
    if len(ordered) == 1:
        return Company.objects.get(id=ordered[0])
    if not ordered:
        raise NotFound(detail="Company not found.")
    raise serializers.ValidationError(
        {
            "company": [
                serializers.ErrorDetail(
                    "`company` is required when you belong to more than one "
                    "provider company.",
                    code=ERR_COMPANY_REQUIRED,
                )
            ]
        }
    )


def resolve_target_company(user, supplied_company):
    """Pick the provider company a management write applies to.

    Mirrors `extra_work.views_catalog._resolve_catalog_create_company`:

      * SUPER_ADMIN supplied `company` -> use it. Omitted: default to
        the single Company when the deployment has exactly one (the
        single-tenant path), otherwise 400 `timesheet_company_required`
        — an SA works in ONE company at a time (Sprint 149) and must say
        which.
      * COMPANY_ADMIN supplied their own -> use it; supplied another
        provider's -> 403 `timesheet_cross_company_forbidden`; omitted
        -> their own (lowest-id membership if they somehow hold
        several).
      * Anyone else never reaches here — `IsTimesheetManager` rejects
        them at the endpoint.

    The 403 for a foreign company is the reason `HourTypeSerializer`
    leaves its `company` field queryset UNSCOPED: the uniqueness
    pre-check is what had to be scoped (it would otherwise answer
    differently depending on whether the rival owns the name), and with
    that scoped, BOTH foreign cases arrive here and get the same 403.
    Scoping the field as well would replace that single answer with a
    `does_not_exist` 400 — no less safe, but it would leave this gate
    unreachable and the two modules' shapes divergent for no gain.
    """
    role = getattr(user, "role", None)

    if role == UserRole.SUPER_ADMIN:
        if supplied_company is not None:
            return supplied_company
        candidates = list(Company.objects.all()[:2])
        if len(candidates) == 1:
            return candidates[0]
        raise serializers.ValidationError(
            {
                "company": [
                    serializers.ErrorDetail(
                        "`company` is required when more than one provider "
                        "Company exists.",
                        code=ERR_COMPANY_REQUIRED,
                    )
                ]
            }
        )

    if role == UserRole.COMPANY_ADMIN:
        own_company_ids = list(
            CompanyUserMembership.objects.filter(user=user)
            .order_by("company_id")
            .values_list("company_id", flat=True)
        )
        if not own_company_ids:
            # Defensive: a COMPANY_ADMIN with zero memberships should
            # not reach a management endpoint at all.
            raise PermissionDenied(detail="Forbidden.")
        if supplied_company is not None:
            if supplied_company.id not in own_company_ids:
                raise PermissionDenied(
                    detail={
                        "detail": (
                            "You may only manage the hours of your own "
                            "provider company."
                        ),
                        "code": ERR_TIMESHEET_CROSS_COMPANY,
                    }
                )
            return supplied_company
        return Company.objects.get(id=own_company_ids[0])

    raise PermissionDenied(detail="Forbidden.")
