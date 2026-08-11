"""
Sprint 152 — tenant scope helpers for the timesheets module (RBAC H-1).

Mirrors `extra_work/catalog_scope.py` in SHAPE — one
`scope_company_ids_for_timesheets(user)` answering "which provider
companies may this actor see rows for", plus one `filter_*_for(user, qs)`
per noun — but is a SEPARATE module and imports nothing from
`extra_work`. Module independence is the sprint's hard architectural
rule; sharing a scope helper would be exactly the import that makes the
timesheets app stop standing on its own.

The rule it enforces: **every queryset resolves through scope, including
the serializer's validation lookups.** An out-of-scope `employee`,
`hour_type` or `building` id must read as NONEXISTENT (DRF's
`does_not_exist` 400), never as "exists but forbidden" — the two answers
differ, and the difference is an existence oracle against another
tenant's data. That is the Sprint 142.1 defect class, and it is cheaper
to never introduce it than to find it later.

Role logic:

  * SUPER_ADMIN: all companies (sentinel `None` = do not filter). Which
    ONE company they are working in at a time is a REQUEST-level choice
    (Sprint 149/150), applied on top of this by the views' `?company=`
    handling — not a narrowing of what they are permitted to reach.
  * COMPANY_ADMIN: their `CompanyUserMembership` companies.
  * BUILDING_MANAGER: companies of the buildings they manage.
  * STAFF: companies of the buildings they have visibility on.
  * CUSTOMER_USER: NOTHING, EVER — an empty frozenset. Multipliers are
    wage-adjacent and hour records are personnel data; no customer-side
    role has any business reading either. The view layer 403s them
    first; this is the second, independent floor.

Anonymous / unauthenticated: empty scope.
"""
from __future__ import annotations

from typing import Optional

from accounts.models import UserRole


# The three provider-side employee roles. A timesheet belongs to one of
# these. SUPER_ADMIN is excluded on purpose: a platform admin is not a
# provider employee (the same line `accounts.views_roster` draws for the
# Employees directory), and CUSTOMER_USER is excluded for the reason in
# the module docstring.
PROVIDER_EMPLOYEE_ROLES = (
    UserRole.COMPANY_ADMIN,
    UserRole.BUILDING_MANAGER,
    UserRole.STAFF,
)

# Roles allowed to reach ANY timesheets endpoint at all.
TIMESHEET_ROLES = (
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
    UserRole.BUILDING_MANAGER,
    UserRole.STAFF,
)

# Roles that manage timesheets company-wide (all employees, hour types,
# week close/reopen, reporting).
TIMESHEET_MANAGER_ROLES = (
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
)


def scope_company_ids_for_timesheets(user) -> Optional[frozenset[int]]:
    """Return the `companies.Company` ids whose timesheet rows are
    visible to `user`.

    Returns `None` for SUPER_ADMIN to signal "no scope filter"; a real
    `frozenset` (possibly empty) means "filter to these ids". The empty
    set is a legitimate answer, not an error: it yields no rows.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return frozenset()

    role = getattr(user, "role", None)

    if role == UserRole.SUPER_ADMIN:
        return None

    if role == UserRole.COMPANY_ADMIN:
        from companies.models import CompanyUserMembership

        return frozenset(
            CompanyUserMembership.objects.filter(user=user).values_list(
                "company_id", flat=True
            )
        )

    if role == UserRole.BUILDING_MANAGER:
        from buildings.models import BuildingManagerAssignment

        return frozenset(
            BuildingManagerAssignment.objects.filter(user=user)
            .values_list("building__company_id", flat=True)
            .distinct()
        )

    if role == UserRole.STAFF:
        from buildings.models import BuildingStaffVisibility

        return frozenset(
            BuildingStaffVisibility.objects.filter(user=user)
            .values_list("building__company_id", flat=True)
            .distinct()
        )

    # CUSTOMER_USER and anything else: nothing.
    return frozenset()


def is_timesheet_manager(user) -> bool:
    """True for the actors who manage a whole company's timesheets
    (SUPER_ADMIN / COMPANY_ADMIN). STAFF and BUILDING_MANAGER are
    ordinary employees here — a BM manages BUILDINGS, not payroll-
    adjacent personnel records, so they get the same own-entries-only
    surface STAFF does.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return getattr(user, "role", None) in TIMESHEET_MANAGER_ROLES


def _apply(user, queryset, field="company_id"):
    scope = scope_company_ids_for_timesheets(user)
    if scope is None:
        return queryset
    return queryset.filter(**{f"{field}__in": scope})


def filter_hour_types_for(user, queryset):
    """Scope a `HourType` queryset. One named helper per noun (the
    `filter_services_for` / `filter_managed_units_for` convention) so a
    call site reads as what it filters, not as a reuse of another
    model's name.
    """
    return _apply(user, queryset)


def filter_time_entries_for(user, queryset):
    """Scope a `TimeEntry` queryset to the actor's companies.

    COMPANY-level only. The narrower "and only your OWN entries" rule
    for STAFF / BUILDING_MANAGER is applied ON TOP of this by
    `restrict_entries_to_self`, deliberately as a second step: this
    function answers the tenant question (H-1), that one answers the
    privacy question. Collapsing them would make it possible to satisfy
    one and silently lose the other.
    """
    return _apply(user, queryset)


def filter_week_locks_for(user, queryset):
    """Scope a `WeekLock` queryset."""
    return _apply(user, queryset)


def filter_buildings_for_timesheets(user, queryset):
    """Scope a `Building` queryset for the entry form's optional
    building link. Company-level, like everything else here — a STAFF
    member may file hours against any building of their own provider,
    not only the ones they hold a visibility row for. Narrowing it to
    the visibility rows would make the field unusable the moment
    somebody covers a shift elsewhere, which is precisely when an
    accurate location matters.
    """
    return _apply(user, queryset)


def restrict_entries_to_self(user, queryset):
    """Apply the own-entries-only rule for non-managers.

    Managers (SA / CA) get the queryset back unchanged; everyone else is
    narrowed to `employee=user`. Applied to EVERY entry queryset — list,
    detail, summary and export all resolve through the same pair of
    helpers, so there is no endpoint where a STAFF member can reach
    another employee's row or learn their name.
    """
    if is_timesheet_manager(user):
        return queryset
    return queryset.filter(employee=user)


def employee_company_ids(employee) -> frozenset[int]:
    """Return the provider-company ids `employee` is an employee OF.

    Uses the same three-way definition of "in a company" that
    `accounts.views_roster.ProviderEmployeesView` uses for the Employees
    directory — `CompanyUserMembership` (CA),
    `BuildingManagerAssignment.building.company` (BM),
    `BuildingStaffVisibility.building.company` (STAFF) — rather than
    inventing a fourth one that would then have to be kept in step with
    it.

    NOTE on "ACTIVE membership": `CompanyUserMembership` carries no
    `is_active` column (nor do the two assignment tables), so "active"
    here means the row exists AND the user account itself is live —
    `is_active=True`, not soft-deleted. That is checked by
    `is_eligible_employee` below rather than here, so this function
    stays a pure "which companies" answer.

    A SUPER_ADMIN gets an empty set: platform admins are not provider
    employees and cannot have hours filed against them.
    """
    if employee is None:
        return frozenset()
    role = getattr(employee, "role", None)
    if role not in PROVIDER_EMPLOYEE_ROLES:
        return frozenset()

    from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
    from companies.models import CompanyUserMembership

    ids = set(
        CompanyUserMembership.objects.filter(user=employee).values_list(
            "company_id", flat=True
        )
    )
    ids |= set(
        BuildingManagerAssignment.objects.filter(user=employee)
        .values_list("building__company_id", flat=True)
        .distinct()
    )
    ids |= set(
        BuildingStaffVisibility.objects.filter(user=employee)
        .values_list("building__company_id", flat=True)
        .distinct()
    )
    return frozenset(ids)


def user_ids_in_companies(company_ids) -> frozenset[int]:
    """`employee_company_ids` read in the other direction: which USERS
    are employees of any of `company_ids`.

    The same three-way definition (`CompanyUserMembership`,
    `BuildingManagerAssignment.building.company`,
    `BuildingStaffVisibility.building.company`), expressed once so the
    forward and reverse questions cannot answer differently. That
    matters here more than it usually would: the employee PICKER
    (`views_employees`) and the write VALIDATOR
    (`TimeEntrySerializer`) both resolve through this, so "who is
    offerable" and "who is acceptable" are the same set by
    construction — not two lists that happen to agree today.
    """
    ids = frozenset(company_ids)
    if not ids:
        return frozenset()

    from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
    from companies.models import CompanyUserMembership

    ca_ids = CompanyUserMembership.objects.filter(
        company_id__in=ids
    ).values_list("user_id", flat=True)
    bm_ids = BuildingManagerAssignment.objects.filter(
        building__company_id__in=ids
    ).values_list("user_id", flat=True)
    staff_ids = BuildingStaffVisibility.objects.filter(
        building__company_id__in=ids
    ).values_list("user_id", flat=True)
    return frozenset(set(ca_ids) | set(bm_ids) | set(staff_ids))


def employees_of_company_queryset(company_id):
    """The eligible provider employees of ONE company.

    Backs `GET /api/timesheets/employees/?company=<id>`. The base
    filter (provider roles, live account, not soft-deleted) is the same
    predicate `is_eligible_employee` applies to a single user, so a
    person the picker offers is a person the write path accepts.
    """
    from accounts.models import User

    return User.objects.filter(
        role__in=PROVIDER_EMPLOYEE_ROLES,
        is_active=True,
        deleted_at__isnull=True,
        pk__in=user_ids_in_companies({company_id}),
    )


def is_eligible_employee(employee) -> bool:
    """True iff hours may be filed against this user at all.

    Provider-side role, live account, not soft-deleted. Company
    membership is checked separately (`employee_company_ids`) because
    the caller needs to know WHICH company, not merely whether there is
    one.
    """
    if employee is None:
        return False
    if getattr(employee, "role", None) not in PROVIDER_EMPLOYEE_ROLES:
        return False
    if not getattr(employee, "is_active", False):
        return False
    if getattr(employee, "deleted_at", None) is not None:
        return False
    return True


def eligible_employees_queryset(user):
    """The `User` rows an actor may name as the `employee` of an entry.

    Scoped by construction: provider-employee roles only, live accounts
    only, and — for anyone but a SUPER_ADMIN — only users who are
    employees of a company in the actor's own scope. A non-manager sees
    exactly themselves, so the serializer's `employee` field cannot be
    used to probe for the existence of a colleague.
    """
    from accounts.models import User

    base = User.objects.filter(
        role__in=PROVIDER_EMPLOYEE_ROLES,
        is_active=True,
        deleted_at__isnull=True,
    )
    if user is None or not getattr(user, "is_authenticated", False):
        return base.none()
    if not is_timesheet_manager(user):
        return base.filter(pk=user.pk)

    scope = scope_company_ids_for_timesheets(user)
    if scope is None:
        return base

    # Sprint 152.1 — the membership fan-out moved into
    # `user_ids_in_companies` so the picker endpoint and this validator
    # queryset share ONE definition. See that helper's docstring.
    return base.filter(pk__in=user_ids_in_companies(scope))


def filter_contract_hours_for(user, queryset):
    """Scope a `ContractHours` queryset to the actor's companies.

    Sprint 167 §3. Company-level, exactly like `filter_time_entries_for`
    — and like it, CUSTOMER_USER resolves to an empty frozenset and
    therefore to no rows. A standing agreement about a worker's hours is
    personnel data; no customer-side role has any business reading it,
    and the view layer 403s them before this is even reached.
    """
    return _apply(user, queryset)
