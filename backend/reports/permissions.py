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


class IsPlannedHoursConsumer(BasePermission):
    """W7 — who may read planned hours beside worked hours for one job.

    Every provider-side role: SUPER_ADMIN, COMPANY_ADMIN,
    BUILDING_MANAGER **and STAFF**. Every customer-side role is refused.

    ## Why STAFF are IN here and OUT of `IsRevenueReportConsumer`

    That class guards responses that carry money, and the staff-privacy
    floor keeps STAFF away from commercial amounts. This response has no
    money in it — no rate, no cost, no amount, no budget — by the rule
    written on `ExtraWorkPlannedHours` itself: planned hours reach no
    price anywhere. What is left is how long somebody was asked to work
    and how long they did, which is that person's own working life.

    Admission is to the SURFACE, not to the rows — the shape this app
    already uses. `reports.planned_vs_actual` then narrows a
    non-manager to their own line through `restrict_entries_to_self`
    and the matching plan filter, so a STAFF or BUILDING_MANAGER caller
    is admitted and sees exactly one person: themselves.

    ## Why customers are refused

    Planned hours are an internal staffing decision. A customer buys an
    outcome and is quoted a price; how many people we put on it, and
    whether we guessed their hours right, is not part of that bargain.
    Letting it leak would also hand a customer a lever in a pricing
    conversation that the SoT never gave them.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.role in {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
            UserRole.STAFF,
        }


class IsLabourRateManager(BasePermission):
    """W4-R — who may reach an `EmployeeHourlyRate` at all.

    SUPER_ADMIN and COMPANY_ADMIN. Nobody else, and the exclusions are
    the point rather than a side effect:

      * **BUILDING_MANAGER is refused.** They are admitted to every
        other reports surface by `IsRevenueReportConsumer`, and this
        class exists so that habit cannot spread here. A BM routes work
        and oversees completion; what a colleague earns is not part of
        that job, and the owner decided this explicitly.
      * **STAFF is refused**, including for their own rate. A worker
        reading their own wage from a reporting endpoint is a payroll
        surface nobody designed, and the same refusal is what stops
        anyone inferring a colleague's.
      * **Every customer-side role is refused**, always. A provider's
        wage bill is not a customer's business in any form.

    NOT a subclass of, and not derived from, `IsRevenueReportConsumer`:
    the two admit sets differ by exactly one role, and expressing this
    one as "that one minus BM" would make a future widening of that
    class silently widen this one. The admit tuple lives in
    `reports.labour_rate_scope.LABOUR_RATE_MANAGER_ROLES`, shared with
    the queryset floor so the door and the rows cannot drift apart.
    """

    def has_permission(self, request, view):
        from .labour_rate_scope import is_labour_rate_manager

        return is_labour_rate_manager(request.user)
