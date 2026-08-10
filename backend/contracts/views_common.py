"""
Sprint 160 — helpers shared by the contracts view modules.

Small on purpose: the view layer is split by noun
(`views_contracts` / `views_types` / `views_revisions` /
`views_forecast`) per CLAUDE.md's app-scoped-file-names rule, and this
module holds only what genuinely belongs to more than one of them.

Mirrors the SHAPE of `timesheets/views_common.py` and imports nothing
from it.
"""
from __future__ import annotations

from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied

from accounts.models import UserRole
from companies.models import Company, CompanyUserMembership

from .permissions import ERR_CONTRACT_CROSS_COMPANY
from .scope import scope_company_ids_for_contracts


ERR_COMPANY_REQUIRED = "contract_company_required"


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
    """Pick the provider company a READ applies to.

    A supplied id must be inside the actor's scope. Out-of-scope reads
    as NONEXISTENT (404), not as forbidden: "that company exists but is
    not yours" is precisely the existence oracle this module is built
    to avoid.
    """
    scope = scope_company_ids_for_contracts(user)

    if supplied_company_id is not None:
        if scope is not None and supplied_company_id not in scope:
            raise NotFound(detail="Company not found.")
        company = Company.objects.filter(id=supplied_company_id).first()
        if company is None:
            raise NotFound(detail="Company not found.")
        return company

    if scope is None:
        # SUPER_ADMIN with no `?company=`: a single-tenant deployment
        # defaults; a multi-tenant one must say which (Sprint 149 — an
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
    """Pick the provider company a management WRITE applies to.

    SUPER_ADMIN supplied `company` -> use it; omitted -> the single
    Company when the deployment has exactly one, else 400
    `contract_company_required`. COMPANY_ADMIN supplied their own ->
    use it; another provider's -> 403
    `contract_cross_company_forbidden`; omitted -> their own. Anyone
    else never reaches here (`IsContractManager` rejects them).
    """
    role = getattr(user, "role", None)

    if role == UserRole.SUPER_ADMIN:
        if supplied_company is not None:
            return supplied_company
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
                            "You may only manage the contracts of your own "
                            "provider company."
                        ),
                        "code": ERR_CONTRACT_CROSS_COMPANY,
                    }
                )
            return supplied_company
        return Company.objects.get(id=own_company_ids[0])

    raise PermissionDenied(detail="Forbidden.")
