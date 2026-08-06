"""
Sprint 152.1 — the employee picker for the admin hours form.

    GET /api/timesheets/employees/?company=<id>

Why this lives in `timesheets` rather than reusing
`/api/employees/` (`accounts.views_roster.ProviderEmployeesView`):

  * That endpoint takes no `?company=` — it scopes by VIEWER — and its
    payload carries no company either. For a SUPER_ADMIN on a
    multi-tenant deployment it therefore mixes several providers'
    people into one dropdown, where every wrong pick 400s on
    `timesheet_employee_not_in_company`. A picker that offers invalid
    options is not a picker.
  * Adding a `?company=` param there is not the fix. It is another
    module's contract, shared with the Employees page, and this module
    is deliberately independent of the rest of the system.

The load-bearing reason, though, is not routing: this view and
`TimeEntrySerializer`'s `employee` field both resolve eligibility
through `scope.user_ids_in_companies` / the same base predicate, so
"who is offerable" and "who is acceptable" are one set by construction.
Two lists maintained separately would agree on the day they were
written and drift afterwards.

SUPER_ADMIN users never appear in the result: `PROVIDER_EMPLOYEE_ROLES`
excludes them, because a platform admin is not a provider employee and
hours cannot be filed against one (§2 of this round removes their
"Mijn uren" page for the same reason).
"""
from __future__ import annotations

from rest_framework import generics, serializers

from config.pagination import UnboundedPagination

from .permissions import IsTimesheetManager
from .scope import employees_of_company_queryset
from .views_common import parse_int_param, resolve_view_company


class TimesheetEmployeeSerializer(serializers.Serializer):
    """The four fields a picker needs. Deliberately NOT the full user
    payload: this endpoint exists to fill a dropdown, and the privacy
    floor the provider-directory serializers hold (no internal_note, no
    phone, no customer linkage) is easiest to hold by not selecting the
    columns at all.
    """

    id = serializers.IntegerField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    role = serializers.CharField(read_only=True)


class TimesheetEmployeeListView(generics.ListAPIView):
    """GET /api/timesheets/employees/ — the employees hours may be filed
    against, for ONE provider company.

    `IsTimesheetManager` (SA / CA): this is a management surface, and a
    STAFF member has no use for a colleague list here — their own entry
    form never names anyone but themselves. CUSTOMER_* are 403'd like
    every other endpoint in the module.

    `resolve_view_company` owns the `?company=` handling, so an
    out-of-scope company id reads as a 404 rather than "exists but
    forbidden" — the same no-oracle rule as the rest of the module.

    `UnboundedPagination`: a provider company's workforce is bounded by
    domain reality (hundreds, not tens of thousands) and this fills a
    single `<select>`. The response keeps the standard
    `{count, next, previous, results}` shape, so the client reads
    `results` exactly as it does for the hour-type list.
    """

    serializer_class = TimesheetEmployeeSerializer
    permission_classes = [IsTimesheetManager]
    pagination_class = UnboundedPagination

    def get_queryset(self):
        company = resolve_view_company(
            self.request.user,
            parse_int_param(self.request.query_params.get("company")),
        )
        return employees_of_company_queryset(company.id).order_by(
            "full_name", "email", "id"
        )
