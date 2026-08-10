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
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from buildings.models import Building
from config.pagination import StandardResultsSetPagination
from customers.models import Customer

from .billing import money
from .models import (
    MONTHS_PER_PERIOD,
    Contract,
    ContractLifecycle,
    ContractRevision,
    ContractStatus,
    ContractType,
)
from .permissions import IsContractManager, IsContractReader, enforce_contract_management
from .revisions import annotate_revision_totals, display_revision_ids
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
        .prefetch_related("lines__building")
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
                "contract_types": [
                    {"id": row.id, "name": row.name} for row in types
                ],
            }
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
