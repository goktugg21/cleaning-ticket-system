from rest_framework.permissions import BasePermission

from accounts.models import UserRole


class IsReportsConsumer(BasePermission):
    """
    Reports are visible to SUPER_ADMIN, COMPANY_ADMIN, and BUILDING_MANAGER.
    CUSTOMER_USER is denied (returns 403). Unauthenticated requests return 401
    (handled by DRF's IsAuthenticated combined upstream).
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.role in {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        }


class IsRevenueReportConsumer(BasePermission):
    """
    Commercial Extra Work revenue report (Sprint 14A).

    Provider-management only — SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER.
    STAFF and CUSTOMER_USER are BOTH denied (403): the report exposes
    commercial amounts, which STAFF must never see (privacy floor) and
    which are provider-internal to every customer-side role.

    The admit set is intentionally identical to `IsReportsConsumer` (which
    already excludes STAFF + CUSTOMER_USER); this dedicated class documents
    the stricter commercial-amount intent so a future widening of the
    general reports admit set cannot silently leak revenue to STAFF.

    ## What BUILDING_MANAGER admission does and does not mean (Sprint 182 §1)

    This class also gates the HOURS reports, and admitting a BM there
    looked like it contradicted `timesheets.permissions.IsTimesheetManager`,
    which deliberately excludes them from the same rows. It did not — but
    only because of a rule the reports were not applying.

    **Admission is to the SURFACE, not to the rows.** It is the same shape
    the timesheets module already has: `IsTimesheetUser` admits every
    provider role to the entries list, and `restrict_entries_to_self` then
    narrows a non-manager to their own entries. The hours reports now do
    exactly that — a BM may open them, and sees their own hours in them.
    An empty Worker Hour Report for a BM with no hours of their own is the
    correct answer, not a broken page.

    So the two modules now say ONE thing: SA and CA see the company's
    hours; STAFF and BUILDING_MANAGER see their own, wherever they read
    them from. Building-level AGGREGATES (the hours-comparison totals) are
    not personnel rows and stay whole — a BM manages buildings.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.role in {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        }
