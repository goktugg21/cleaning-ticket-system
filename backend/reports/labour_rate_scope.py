"""W4-R — who may reach which `EmployeeHourlyRate` rows.

A wage is personal data and the owner has drawn the line explicitly:

    SUPER_ADMIN      may see and set a rate, in any company.
    COMPANY_ADMIN    may see and set a rate, within their own company.
    BUILDING_MANAGER MAY NOT. Not the rate, and not a per-person cost
                     figure derived from one. A BM routes work and
                     oversees completion; what a colleague earns is not
                     part of that job. This exclusion is deliberate and
                     is not to be widened because a screen looks empty
                     without it.
    STAFF            may not see anyone's rate, INCLUDING their own —
                     and including inferring their own from a cost.
    CUSTOMER_USER    may not see any of it, ever.

The admit set is enforced twice, on purpose. `permissions.IsLabourRateManager`
turns everyone else away at the door with a 403; the queryset helpers
below are the second, independent floor, so a future view that forgets
the permission class still cannot serve another tenant's rows.

## Why the company / employee definitions are IMPORTED, not re-derived

`timesheets.scope` already answers both questions this module needs —
"which provider companies is this actor in"
(`scope_company_ids_for_timesheets`) and "who is an employee of a
company" (`user_ids_in_companies` / `is_eligible_employee`). Writing a
fourth definition of "employee of a company" is how the picker and the
validator come to disagree, which is the Sprint 152.1 defect this repo
already fixed once. `reports` is allowed to import `timesheets` — it
does so in `extra_work_hours.py` and `hours_comparison.py` — and the
import direction is the safe one: nothing about a WAGE travels into the
hours module.

Note the asymmetry that follows: `scope_company_ids_for_timesheets`
answers for BUILDING_MANAGER and STAFF too, because timesheets admits
them. This module never asks it on their behalf — the permission class
has already refused them — and `rate_company_ids_for` refuses them a
second time rather than relying on that.
"""
from __future__ import annotations

from typing import Optional

from accounts.models import UserRole


#: The only two roles that may read or write a wage. Named here rather
#: than inlined in the permission class so the queryset floor and the
#: door check cannot drift apart.
LABOUR_RATE_MANAGER_ROLES = (
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
)


def is_labour_rate_manager(user) -> bool:
    """True for the actors who may see and set a wage. Nobody else."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return getattr(user, "role", None) in LABOUR_RATE_MANAGER_ROLES


def rate_company_ids_for(user) -> Optional[frozenset[int]]:
    """Provider company ids whose rates `user` may reach.

    `None` for SUPER_ADMIN means "no filter" — the sentinel
    `timesheets.scope` uses, kept identical so a caller reads one
    convention. A real frozenset (possibly empty) means "filter to
    these". An empty set is a legitimate answer that yields no rows.

    Every role that is not SA or CA gets the empty set, whatever
    `timesheets.scope` would say about them: a BM has timesheet companies
    and no rate companies, and this is where that difference is stated.
    """
    if not is_labour_rate_manager(user):
        return frozenset()

    from timesheets.scope import scope_company_ids_for_timesheets

    return scope_company_ids_for_timesheets(user)


def filter_hourly_rates_for(user, queryset):
    """Scope an `EmployeeHourlyRate` queryset to the actor's companies.

    One named helper for the one noun, the convention `timesheets.scope`
    keeps, so a call site reads as what it filters.
    """
    scope = rate_company_ids_for(user)
    if scope is None:
        return queryset
    return queryset.filter(company_id__in=scope)


def rate_companies_queryset(user):
    """The `Company` rows the actor may write a rate in.

    Used as the serializer's `company` field queryset so an out-of-scope
    id reads as NONEXISTENT (DRF's `does_not_exist` 400) rather than as
    "exists but forbidden". The two answers differ, and the difference is
    an existence oracle against another tenant — the Sprint 142.1 defect
    class this repo does not reintroduce.
    """
    from companies.models import Company

    scope = rate_company_ids_for(user)
    if scope is None:
        return Company.objects.all()
    return Company.objects.filter(pk__in=scope)


def rate_employees_queryset(user):
    """The `User` rows the actor may write a rate FOR.

    Provider-employee roles only, live accounts only, and — for anyone
    but a SUPER_ADMIN — only people who are employees of a company in
    the actor's own scope. Resolved through
    `timesheets.scope.eligible_employees_queryset` so "who may hold
    hours" and "who may hold a rate" are the same set by construction
    rather than two lists that happen to agree today.

    One narrowing on top of it: that helper returns *just the actor* for
    a non-manager, because a STAFF member may file their OWN hours. A
    non-manager may not hold a rate opinion about anyone including
    themselves, so a non-manager gets nothing here.
    """
    from timesheets.scope import eligible_employees_queryset

    if not is_labour_rate_manager(user):
        from accounts.models import User

        return User.objects.none()
    return eligible_employees_queryset(user)
