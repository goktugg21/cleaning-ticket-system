"""
Sprint 160 — contract list / detail / stats / picker-options endpoints.

    GET  / POST            /api/contracts/
    GET  / PATCH / DELETE  /api/contracts/<int:contract_id>/
    GET                    /api/contracts/stats/
    GET                    /api/contracts/options/

Reads admit SA / CA / BM (`IsContractReader`); BUILDING_MANAGER is
narrowed to the contracts covering a building they manage by
`scope.filter_contracts_for` and is read-only because
`IsContractManager` never admits them. STAFF and every customer-side
role are 403'd on every method.

**Query cost is constant in the page size.** The active revision of
every contract on the page is resolved in ONE query
(`revisions.display_revision_ids`), its totals arrive as annotations
rather than per-row aggregates, and the buildings and lines are
prefetched. `tests/test_query_counts.py` pins this: a 10-row page costs
exactly what a 2-row page costs.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, Sum, When
from django.db.models.functions import Coalesce, Lower, Trim
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from audit import context as audit_context
from buildings.models import Building
from companies.models import Company
from config.pagination import StandardResultsSetPagination
from customers.models import Customer

from .billing import money
from .models import (
    MONTHS_PER_PERIOD,
    Contract,
    ContractKind,
    ContractLifecycle,
    ContractRevision,
    ContractStatus,
    ContractType,
)
from .permissions import IsContractManager, IsContractReader, enforce_contract_management
from .revisions import annotate_revision_totals, display_revision_ids
from .standard_types import (
    normalise_name as normalise_type_name,
    slot_aliases,
    standard_contract_types,
)
from .scope import (
    filter_buildings_for_contracts,
    filter_contract_types_for,
    filter_contracts_for,
    filter_customers_for_contracts,
)
from .serializers import (
    ContractSerializer,
    ContractTypeSerializer,
    create_contract,
    sync_contract_buildings,
)
from .views_common import (
    parse_bool_param,
    parse_int_param,
    resolve_target_company,
    resolve_view_company,
)


# Sort keys the list endpoint accepts, mapped to real ORM orderings.
# An allow-list rather than passing `?ordering=` through, so a client
# cannot order by an unindexed or unintended column.
SORT_FIELDS = {
    "contract_no": ["contract_no"],
    "customer": ["customer__name", "contract_no"],
    "type": ["contract_type__name", "contract_no"],
    "start_date": ["start_date", "contract_no"],
    "end_date": ["end_date", "contract_no"],
    "status": ["lifecycle", "end_date", "contract_no"],
}


def status_filter_q(value, today):
    """Translate a DERIVED status into a queryset predicate.

    The mapping lives here, once, so the list filter, the stat tiles
    and `Contract.status` cannot answer differently about the same row.
    EXPIRED is the interesting one: it is `lifecycle=ACTIVE` plus a
    past end date, never a stored value.
    """
    if value == ContractStatus.DRAFT:
        return Q(lifecycle=ContractLifecycle.DRAFT)
    if value == ContractStatus.CANCELLED:
        return Q(lifecycle=ContractLifecycle.CANCELLED)
    if value == ContractStatus.EXPIRED:
        return Q(lifecycle=ContractLifecycle.ACTIVE) & Q(
            end_date__isnull=False, end_date__lt=today
        )
    if value == ContractStatus.ACTIVE:
        return Q(lifecycle=ContractLifecycle.ACTIVE) & (
            Q(end_date__isnull=True) | Q(end_date__gte=today)
        )
    return None


def apply_contract_filters(queryset, params, today):
    """The `?search= / ?customer= / ?building= / ?status= / ?type=`
    filters, applied BEFORE scoping so no parameter can widen what an
    actor sees.
    """
    search = (params.get("search") or "").strip()
    if search:
        queryset = queryset.filter(
            Q(contract_no__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(description__icontains=search)
            | Q(building_links__building__name__icontains=search)
        ).distinct()

    customer_id = parse_int_param(params.get("customer"))
    if customer_id is not None:
        queryset = queryset.filter(customer_id=customer_id)

    building_id = parse_int_param(params.get("building"))
    if building_id is not None:
        queryset = queryset.filter(
            building_links__building_id=building_id
        ).distinct()

    type_id = parse_int_param(params.get("type"))
    if type_id is not None:
        queryset = queryset.filter(contract_type_id=type_id)

    status_param = (params.get("status") or "").strip().upper()
    if status_param:
        predicate = status_filter_q(status_param, today)
        if predicate is None:
            # An unrecognised status yields nothing rather than being
            # ignored — silently returning everything would read as
            # "the filter is off" when the user believes it is on.
            queryset = queryset.none()
        else:
            queryset = queryset.filter(predicate)

    return queryset


def contract_list_context(contracts, request):
    """Build the serializer context that makes a page cost a constant
    number of queries: `{contract_id: active_revision}`, with the
    revision's totals annotated and its lines prefetched.
    """
    ids = [contract.id for contract in contracts]
    # The DISPLAY rule, not the strict one: a contract starting next
    # March has nothing in force today, and its card must still say
    # what it is worth. See `revisions.display_revision`.
    resolved = display_revision_ids(ids)
    revisions = (
        annotate_revision_totals(
            ContractRevision.objects.filter(id__in=list(resolved.values()))
        )
        .select_related("contract")
        .prefetch_related("lines__building", "lines__department")
    )
    by_id = {revision.id: revision for revision in revisions}
    return {
        "request": request,
        "active_revisions": {
            contract_id: by_id.get(revision_id)
            for contract_id, revision_id in resolved.items()
        },
    }


class ContractListCreateView(generics.ListCreateAPIView):
    """GET (list) + POST (create) at /api/contracts/.

    Paginated with the STANDARD page size, not `UnboundedPagination`:
    contracts are a growing server collection and the list page has
    real pagination UI. (Sprint 134/135's lesson — a list endpoint's
    pagination_class is a contract with every caller. The pickers that
    need everything have their own endpoint, `/options/`, rather than
    loosening this one.)
    """

    serializer_class = ContractSerializer
    pagination_class = StandardResultsSetPagination

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsContractReader()]
        return [IsContractManager()]

    def get_queryset(self):
        today = timezone.localdate()
        qs = Contract.objects.select_related(
            "company", "customer", "contract_type"
        ).prefetch_related("building_links__building")

        company_id = parse_int_param(self.request.query_params.get("company"))
        if company_id is not None:
            qs = qs.filter(company_id=company_id)

        qs = apply_contract_filters(qs, self.request.query_params, today)
        qs = filter_contracts_for(self.request.user, qs)
        # W16 — the EXTRA WORK registers are not in this list, and not
        # in these numbers. They are a different kind of object: one per
        # customer, auto-created, mirroring work that is invoiced by the
        # Extra Work run. Counting them here would put a "contract" a
        # nobody signed in the list and add ad-hoc spend to a figure
        # that means "recurring fees we have agreed". The reference
        # system hides its own the same way, by excluding `status_id=4`
        # from `index()` (`ContractController.php:37`) and summing only
        # ACTIVE rows in `statistics()`.
        qs = qs.exclude(kind=ContractKind.EXTRA_WORK)


        sort = (self.request.query_params.get("sort") or "").strip()
        descending = sort.startswith("-")
        key = sort[1:] if descending else sort
        fields = SORT_FIELDS.get(key)
        if fields:
            if descending:
                fields = [f"-{f}" for f in fields]
            return qs.order_by(*fields)
        return qs.order_by("-start_date", "-id")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # `self._page_contracts` is set by `list()` below; on the POST
        # path there is no page and the serializer falls back to
        # resolving one contract's revision directly.
        contracts = getattr(self, "_page_contracts", None)
        if contracts is None:
            return context
        context.update(contract_list_context(contracts, self.request))
        return context

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            self._page_contracts = page
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        rows = list(queryset)
        self._page_contracts = rows
        serializer = self.get_serializer(rows, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = resolve_target_company(
            request.user, serializer.validated_data.get("company")
        )
        enforce_contract_management(request.user, company)
        serializer.validate_company_consistency(
            company, serializer.validated_data
        )
        contract = create_contract(
            serializer=serializer, company=company, user=request.user
        )
        output = self.get_serializer(contract)
        return Response(output.data, status=status.HTTP_201_CREATED)


class ContractDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE at /api/contracts/<id>/.

    The queryset is scoped on EVERY method, so an out-of-scope id is a
    404 before any handler runs — the same answer a fictional id gets.
    """

    serializer_class = ContractSerializer
    lookup_url_kwarg = "contract_id"

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsContractReader()]
        return [IsContractManager()]

    def get_queryset(self):
        return filter_contracts_for(
            self.request.user,
            Contract.objects.select_related(
                "company", "customer", "contract_type"
            ).prefetch_related("building_links__building"),
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        obj = getattr(self, "_contract", None)
        if obj is not None:
            context.update(contract_list_context([obj], self.request))
        return context

    def get_object(self):
        obj = super().get_object()
        self._contract = obj
        return obj

    def perform_update(self, serializer):
        contract = serializer.instance
        supplied_company = serializer.validated_data.get("company")
        company = supplied_company or contract.company
        enforce_contract_management(self.request.user, company)
        serializer.validate_company_consistency(
            company, serializer.validated_data
        )
        buildings = serializer.validated_data.pop("building_ids", None)
        serializer.validated_data.pop("initial_revision_label", None)
        with transaction.atomic():
            serializer.save()
            if buildings is not None:
                sync_contract_buildings(serializer.instance, buildings)

    def perform_destroy(self, instance):
        enforce_contract_management(self.request.user, instance.company)
        instance.delete()


class ContractStatsView(APIView):
    """GET /api/contracts/stats/ — the list page's stat tiles.

    Computed over the SAME filtered, scoped queryset the list reads, so
    the tiles describe what the table is showing rather than the whole
    tenant. Four counts arrive in one aggregate; the two money figures
    need the per-contract billing period to normalise, so they resolve
    the active revisions in two further queries and normalise in
    Python. Three queries, independent of how many contracts match.
    """

    permission_classes = [IsContractReader]

    def get(self, request):
        today = timezone.localdate()
        qs = Contract.objects.all()
        company_id = parse_int_param(request.query_params.get("company"))
        if company_id is not None:
            qs = qs.filter(company_id=company_id)
        qs = apply_contract_filters(qs, request.query_params, today)
        qs = filter_contracts_for(request.user, qs)
        # See `ContractListCreateView.get_queryset` — same exclusion, so
        # the tiles count exactly the rows the list shows.
        qs = qs.exclude(kind=ContractKind.EXTRA_WORK)

        def count_when(predicate):
            return Count(
                Case(When(predicate, then=1), output_field=IntegerField()),
                distinct=False,
            )

        counts = qs.aggregate(
            total=Count("id", distinct=True),
            draft=count_when(status_filter_q(ContractStatus.DRAFT, today)),
            active=count_when(status_filter_q(ContractStatus.ACTIVE, today)),
            expired=count_when(status_filter_q(ContractStatus.EXPIRED, today)),
            cancelled=count_when(
                status_filter_q(ContractStatus.CANCELLED, today)
            ),
        )

        periods = dict(qs.values_list("id", "billing_period"))
        # Same display rule the list uses, so the tiles total exactly
        # what the table shows rather than quietly dropping the
        # contracts that have not started yet.
        resolved = display_revision_ids(list(periods.keys()))
        amounts = dict(
            ContractRevision.objects.filter(id__in=list(resolved.values()))
            .values_list("id")
            .annotate(
                total=Coalesce(Sum("lines__amount"), Decimal("0.00"))
            )
            .values_list("id", "total")
        )

        monthly = Decimal("0.00")
        for contract_id, billing_period in periods.items():
            revision_id = resolved.get(contract_id)
            if revision_id is None:
                continue
            period_amount = amounts.get(revision_id, Decimal("0.00"))
            months = MONTHS_PER_PERIOD[billing_period]
            monthly += period_amount / Decimal(months)

        return Response(
            {
                "total": counts["total"],
                "active": counts["active"],
                "draft": counts["draft"],
                "expired": counts["expired"],
                "cancelled": counts["cancelled"],
                "monthly_total": money(monthly),
                "yearly_total": money(monthly * Decimal(12)),
            }
        )


class ContractOptionsView(APIView):
    """GET /api/contracts/options/?company=<id> — everything the
    contract form's pickers need, in one call.

    Its own endpoint rather than a `page_size` on the shared
    `/api/customers/` and `/api/buildings/` lists, for the Sprint
    134/135 reason: those endpoints' pagination is a contract with
    every other caller, and loosening it to feed a picker broke the
    admin list pages that read `count`/`next`. This endpoint has no
    pagination UI and never will.

    It reads the SAME scoped querysets the serializer validates
    against, so an option offered here is an option the write path
    accepts, and one it does not offer is rejected as `does_not_exist`.
    """

    permission_classes = [IsContractManager]

    def get(self, request):
        company = resolve_view_company(
            request.user, parse_int_param(request.query_params.get("company"))
        )
        customers = filter_customers_for_contracts(
            request.user, Customer.objects.filter(company=company)
        ).order_by("name", "id")
        buildings = filter_buildings_for_contracts(
            request.user, Building.objects.filter(company=company)
        ).order_by("name", "id")
        types = filter_contract_types_for(
            request.user,
            ContractType.objects.filter(company=company, is_active=True),
        ).order_by("sort_order", "name", "id")

        return Response(
            {
                "company": {"id": company.id, "name": company.name},
                "customers": [
                    {"id": row.id, "name": row.name} for row in customers
                ],
                "buildings": [
                    {"id": row.id, "name": row.name} for row in buildings
                ],
                # Sprint 169 §4 — the slot travels with the name so the
                # picker reads in the operator's language too. A dialog
                # that offers "Schoonmaak" while the list shows
                # "Cleaning" is the drift this exists to prevent.
                "contract_types": [
                    {
                        "id": row.id,
                        "name": row.name,
                        "standard_slot": row.standard_slot,
                    }
                    for row in types
                ],
            }
        )


class ContractTypeStandardSetView(APIView):
    """POST /api/contracts/types/standard-set/ — seed the four for a
    company that has none.

    The `timesheets/hour-types/standard-set/` shape, and idempotent for
    the same reason: the skip test is the same `Lower(Trim(...))`
    comparison the uniqueness constraint uses, so the view and the
    database agree on what "already there" means. Pressing it twice
    creates nothing the second time, and the response names what was
    created and what was skipped rather than returning a bare count.
    """

    permission_classes = [IsContractManager]

    def post(self, request, *args, **kwargs):
        supplied = parse_int_param(request.data.get("company"))
        company_obj = (
            Company.objects.filter(id=supplied).first()
            if supplied is not None
            else None
        )
        # One place decides "which company does this write apply to",
        # for every management write in this app — including the
        # cross-company 403 a COMPANY_ADMIN must get.
        company = resolve_target_company(request.user, company_obj)
        enforce_contract_management(request.user, company)

        # Sprint 169 §4 — the skip test asks the SLOT first, then falls
        # back to the name ALIASES. Idempotent across languages, which
        # is the part that needs saying: comparing only the name about
        # to be created would hand a Dutch-seeded company four English
        # duplicates the first time an English-profile operator pressed
        # the button, and the per-company uniqueness constraint would
        # not object because "Meerwerk" and "Extra Works" genuinely are
        # different strings.
        rows = list(
            ContractType.objects.filter(company=company).values_list(
                "name", "standard_slot"
            )
        )
        taken_slots = {slot for _name, slot in rows if slot}
        existing_names = {normalise_type_name(name) for name, _slot in rows}

        wanted = standard_contract_types(getattr(request.user, "language", None))
        aliases = slot_aliases()

        created, skipped = [], []
        audit_context.set_current_reason("contract_type_standard_set")
        try:
            with transaction.atomic():
                for (slot, name, sort_order), slot_names in zip(wanted, aliases):
                    if slot in taken_slots or (slot_names & existing_names):
                        skipped.append(name)
                        continue
                    # save() per row, not bulk_create: the audit
                    # receivers are post_save (H-10), and `save()` is
                    # also where `standard_slot` is derived.
                    ContractType.objects.create(
                        company=company, name=name, sort_order=sort_order
                    )
                    created.append(name)
        finally:
            audit_context.set_current_reason(None)

        return Response(
            {"created": created, "skipped": skipped},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ContractTypeListCreateView(generics.ListCreateAPIView):
    """GET (list) + POST (create) at /api/contracts/types/."""

    serializer_class = ContractTypeSerializer
    pagination_class = None

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsContractReader()]
        return [IsContractManager()]

    def get_queryset(self):
        qs = ContractType.objects.select_related("company").annotate(
            annotated_contract_count=Count("contracts", distinct=True)
        )
        company_id = parse_int_param(self.request.query_params.get("company"))
        if company_id is not None:
            qs = qs.filter(company_id=company_id)
        flag = parse_bool_param(self.request.query_params.get("is_active"))
        if flag is not None:
            qs = qs.filter(is_active=flag)
        qs = filter_contract_types_for(self.request.user, qs)
        return qs.order_by("sort_order", "name", "id")

    def perform_create(self, serializer):
        from django.db import IntegrityError
        from rest_framework import serializers as drf_serializers

        from .serializers import ERR_CONTRACT_TYPE_NAME_NOT_UNIQUE

        company = resolve_target_company(
            self.request.user, serializer.validated_data.get("company")
        )
        enforce_contract_management(self.request.user, company)
        try:
            # The inner atomic() is load-bearing, not decorative:
            # without a savepoint boundary Postgres refuses every
            # further command in the surrounding transaction after an
            # IntegrityError, even though Python catches it. Same
            # rationale as HourTypeListCreateView.perform_create.
            with transaction.atomic():
                serializer.save(company=company)
        except IntegrityError:
            raise drf_serializers.ValidationError(
                {
                    "name": [
                        drf_serializers.ErrorDetail(
                            "A contract type with this name already exists "
                            "for this company.",
                            code=ERR_CONTRACT_TYPE_NAME_NOT_UNIQUE,
                        )
                    ]
                }
            )


class ContractTypeDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE at /api/contracts/types/<id>/."""

    serializer_class = ContractTypeSerializer
    lookup_url_kwarg = "type_id"

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsContractReader()]
        return [IsContractManager()]

    def get_queryset(self):
        return filter_contract_types_for(
            self.request.user,
            ContractType.objects.select_related("company").annotate(
                annotated_contract_count=Count("contracts", distinct=True)
            ),
        )

    def perform_update(self, serializer):
        enforce_contract_management(
            self.request.user, serializer.instance.company
        )
        serializer.save()

    def perform_destroy(self, instance):
        from django.db.models import ProtectedError
        from rest_framework import serializers as drf_serializers

        enforce_contract_management(self.request.user, instance.company)
        try:
            instance.delete()
        except ProtectedError:
            raise drf_serializers.ValidationError(
                {
                    "detail": [
                        drf_serializers.ErrorDetail(
                            "This contract type is in use and cannot be "
                            "deleted. Archive it instead.",
                            code="contract_type_protected",
                        )
                    ]
                }
            )


# ---------------------------------------------------------------------------
# W23 — the year×week planning grid.
#
#     GET /api/contracts/<int:contract_id>/planning/?year=2026
#
# A READ, shaped like `ContractForecastView`: per active-revision
# contract line, the linked RecurringJobs' PlannedOccurrences bucketed
# by ISO week. Editing stays on the job's calendar (`planned_work`'s
# idempotent per-date actions) — this endpoint computes and writes
# nothing, which is what keeps the occurrence machinery the ONE
# planner. Tenant-scoped by construction: `get_scoped_contract` gates
# the contract, and only lines OF THIS CONTRACT's active revision are
# walked, so no other tenant's jobs or occurrences are reachable
# whatever ids are guessed.
# ---------------------------------------------------------------------------


# Dominance order for a week's cell colour when a week holds mixed
# statuses: the most frequent wins, ties break on this list (done beats
# pending beats abandoned).
_PLANNING_STATUS_DOMINANCE = [
    "COMPLETED",
    "TICKET_CREATED",
    "PLANNED",
    "RESCHEDULED",
    "MISSED",
    "SKIPPED",
    "CANCELLED",
]

# Dates that are not performances: they fill no cell tint priority and
# do not count against `frequency_per_year`.
_PLANNING_NON_PERFORMANCE = {"SKIPPED", "CANCELLED"}


class ContractPlanningView(APIView):
    """The planning grid for one contract and one ISO year."""

    permission_classes = [IsContractReader]

    def get(self, request, contract_id):
        from datetime import date as date_cls

        from planned_work.models import PlannedOccurrence

        from .revisions import active_revision
        from .serializers import ContractPlanningSerializer
        from .views_revisions import get_scoped_contract

        contract = get_scoped_contract(request.user, contract_id)
        # W23 §3 — a register (kind=EXTRA_WORK) mirrors chargeable jobs;
        # it has no standing lines to plan. The frontend never asks; a
        # hand-rolled request gets the reason, not an empty grid that
        # looks like an unplanned year.
        if contract.kind == ContractKind.EXTRA_WORK:
            return Response(
                {
                    "detail": "An extra-work register has no planning.",
                    "code": "register_has_no_planning",
                },
                status=400,
            )
        year = parse_int_param(request.query_params.get("year"))
        if year is None or not (1970 <= year <= 2999):
            year = timezone.localdate().year

        revision = active_revision(contract)
        lines = (
            list(revision.lines.order_by("sort_order", "id"))
            if revision is not None
            else []
        )
        line_ids = [line.id for line in lines]

        # One query for the whole grid. The date window over-fetches the
        # ISO-year boundary days (Dec 29 – Jan 3) and the isocalendar
        # check keeps exactly the requested ISO year, so week 1 and week
        # 52/53 bucket correctly at both edges.
        rows = PlannedOccurrence.objects.filter(
            recurring_job__contract_line_id__in=line_ids,
            planned_date__gte=date_cls(year - 1, 12, 29),
            planned_date__lte=date_cls(year + 1, 1, 3),
        ).values_list(
            "recurring_job__contract_line_id",
            "recurring_job_id",
            "planned_date",
            "status",
        )

        per_line: dict[int, dict] = {
            line.id: {"weeks": {}, "jobs": set(), "planned": 0}
            for line in lines
        }
        for line_id, job_id, planned_date, status in rows:
            iso = planned_date.isocalendar()
            if iso[0] != year:
                continue
            bucket = per_line[line_id]
            bucket["jobs"].add(job_id)
            if status not in _PLANNING_NON_PERFORMANCE:
                bucket["planned"] += 1
            week = bucket["weeks"].setdefault(
                iso[1], {"count": 0, "statuses": {}, "job_id": job_id}
            )
            week["count"] += 1
            week["statuses"][status] = week["statuses"].get(status, 0) + 1

        def dominant(statuses: dict) -> str:
            return min(
                statuses,
                key=lambda s: (
                    -statuses[s],
                    _PLANNING_STATUS_DOMINANCE.index(s)
                    if s in _PLANNING_STATUS_DOMINANCE
                    else len(_PLANNING_STATUS_DOMINANCE),
                ),
            )

        payload = {
            "year": year,
            "lines": [
                {
                    "line_id": line.id,
                    "name": line.name,
                    "frequency_per_year": line.frequency_per_year,
                    "planned_count": per_line[line.id]["planned"],
                    "job_ids": sorted(per_line[line.id]["jobs"]),
                    "weeks": [
                        {
                            "week": week_no,
                            "count": data["count"],
                            "status": dominant(data["statuses"]),
                            "job_id": data["job_id"],
                        }
                        for week_no, data in sorted(
                            per_line[line.id]["weeks"].items()
                        )
                    ],
                }
                for line in lines
            ],
        }
        return Response(ContractPlanningSerializer(payload).data)
