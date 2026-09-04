"""
Sprint 160 — contract revision + line endpoints.

    GET  / POST            /api/contracts/<int:contract_id>/revisions/
    GET  / PATCH / DELETE  /api/contracts/revisions/<int:revision_id>/
    GET  / POST            /api/contracts/revisions/<int:revision_id>/lines/
    PATCH / DELETE         /api/contracts/lines/<int:line_id>/

The rule these enforce: **a revision whose effective date has arrived
is closed.** Its lines cannot be added to, edited or removed, and the
revision itself cannot be re-dated or deleted. A correction to a past
agreement is a NEW revision — the same discipline that makes a SENT
invoice correctable only by reversal, and the reason a revision is
worth having at all: if history could be edited, last month's invoice
total would silently change when this month's price did.

A future-dated revision stays fully editable, which is the point of
being able to author one ahead of time.
"""
from __future__ import annotations

from django.db import transaction
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from .models import Contract, ContractLine, ContractRevision
from .permissions import (
    IsContractManager,
    IsContractReader,
    enforce_contract_management,
)
from .revisions import annotate_revision_totals, display_revision
from .scope import filter_contracts_for, filter_lines_for, filter_revisions_for
from .serializers import (
    ContractLineSerializer,
    ContractRevisionSerializer,
    assert_revision_editable,
)


def get_scoped_contract(user, contract_id):
    """Fetch a contract through the actor's scope, or 404.

    Out-of-scope is a 404, identical to a fictional id — the same
    answer `ContractDetailView` gives, because these nested routes are
    another door onto the same resource and must not answer
    differently.
    """
    contract = filter_contracts_for(
        user, Contract.objects.select_related("company")
    ).filter(id=contract_id).first()
    if contract is None:
        raise NotFound(detail="Contract not found.")
    return contract


class ContractRevisionListCreateView(generics.ListCreateAPIView):
    """GET (list) + POST (create) at
    /api/contracts/<contract_id>/revisions/.

    Unpaginated by domain reality: a contract accumulates a handful of
    revisions over its life (a price change a year, at most), not a
    growing collection. The Revision History tab still renders them
    through a bounded list on the frontend.
    """

    serializer_class = ContractRevisionSerializer
    pagination_class = None

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsContractReader()]
        return [IsContractManager()]

    def get_queryset(self):
        contract = get_scoped_contract(
            self.request.user, self.kwargs["contract_id"]
        )
        return (
            annotate_revision_totals(
                ContractRevision.objects.filter(contract=contract)
            )
            .select_related("contract", "created_by")
            .prefetch_related(
                "lines__building",
                "lines__department",
                # P-12 C3 - the line's recurring rules, one prefetch so the
                # nested serializer's `recurring` field costs no per-row query
                # (test_query_counts pins the page cost).
                "lines__recurring_jobs",
            )
            .order_by("-effective_from", "-id")
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        contract = get_scoped_contract(
            self.request.user, self.kwargs["contract_id"]
        )
        # The DISPLAY rule, so the revision the header card calls active
        # is the one flagged active in this list. Two rules would let
        # the two halves of the same page disagree.
        current = display_revision(contract)
        context["active_revision_id"] = current.id if current else None
        return context

    def create(self, request, *args, **kwargs):
        """Author a new revision.

        By default it COPIES the currently active revision's lines, so
        "raise one price from March" is an edit of a copy rather than
        retyping every project. Pass `copy_lines=false` to start empty.
        The copy is what makes forward-dating usable; without it the
        cheapest path to a small change would be editing history, which
        is exactly what this model exists to prevent.
        """
        contract = get_scoped_contract(request.user, self.kwargs["contract_id"])
        enforce_contract_management(request.user, contract.company)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        copy_lines = str(
            request.data.get("copy_lines", "true")
        ).strip().lower() not in {"false", "0", "no", "n"}

        with transaction.atomic():
            revision = ContractRevision.objects.create(
                contract=contract,
                label=serializer.validated_data["label"],
                effective_from=serializer.validated_data["effective_from"],
                notes=serializer.validated_data.get("notes", ""),
                created_by=request.user,
            )
            if copy_lines:
                source = (
                    ContractRevision.objects.filter(contract=contract)
                    .exclude(pk=revision.pk)
                    .order_by("-effective_from", "-id")
                    .first()
                )
                if source is not None:
                    for line in source.lines.all():
                        ContractLine.objects.create(
                            revision=revision,
                            name=line.name,
                            building=line.building,
                            sort_order=line.sort_order,
                            hours=line.hours,
                            area_m2=line.area_m2,
                            amount=line.amount,
                            vat_pct=line.vat_pct,
                        )

        output = self.get_serializer(revision)
        return Response(output.data, status=status.HTTP_201_CREATED)


class ContractRevisionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE at /api/contracts/revisions/<id>/."""

    serializer_class = ContractRevisionSerializer
    lookup_url_kwarg = "revision_id"

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsContractReader()]
        return [IsContractManager()]

    def get_queryset(self):
        return filter_revisions_for(
            self.request.user,
            annotate_revision_totals(ContractRevision.objects.all())
            .select_related("contract", "contract__company", "created_by")
            .prefetch_related(
                "lines__building",
                "lines__department",
                # P-12 C3 - the line's recurring rules, one prefetch so the
                # nested serializer's `recurring` field costs no per-row query
                # (test_query_counts pins the page cost).
                "lines__recurring_jobs",
            ),
        )

    def perform_update(self, serializer):
        revision = serializer.instance
        enforce_contract_management(self.request.user, revision.contract.company)
        assert_revision_editable(revision)
        serializer.save()

    def perform_destroy(self, instance):
        enforce_contract_management(self.request.user, instance.contract.company)
        assert_revision_editable(instance)
        if instance.contract.revisions.count() <= 1:
            from rest_framework import serializers as drf_serializers

            # A contract is never revision-less — deleting the only
            # revision would leave a contract that reads as zero money
            # with no way to say what it is worth.
            raise drf_serializers.ValidationError(
                {
                    "detail": [
                        drf_serializers.ErrorDetail(
                            "A contract must keep at least one revision.",
                            code="contract_needs_a_revision",
                        )
                    ]
                }
            )
        instance.delete()


class ContractLineListCreateView(generics.ListCreateAPIView):
    """GET (list) + POST (create) at
    /api/contracts/revisions/<revision_id>/lines/."""

    serializer_class = ContractLineSerializer
    pagination_class = None

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsContractReader()]
        return [IsContractManager()]

    def _revision(self):
        revision = (
            filter_revisions_for(
                self.request.user,
                ContractRevision.objects.select_related(
                    "contract", "contract__company"
                ),
            )
            .filter(id=self.kwargs["revision_id"])
            .first()
        )
        if revision is None:
            raise NotFound(detail="Revision not found.")
        return revision

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["revision"] = self._revision()
        return context

    def get_queryset(self):
        revision = self._revision()
        return (
            ContractLine.objects.filter(revision=revision)
            .select_related("building", "department")
            .order_by("sort_order", "id")
        )

    def perform_create(self, serializer):
        revision = self._revision()
        enforce_contract_management(self.request.user, revision.contract.company)
        assert_revision_editable(revision)
        serializer.save(revision=revision)


class ContractLineDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE at /api/contracts/lines/<id>/."""

    serializer_class = ContractLineSerializer
    lookup_url_kwarg = "line_id"

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsContractReader()]
        return [IsContractManager()]

    def get_queryset(self):
        return filter_lines_for(
            self.request.user,
            ContractLine.objects.select_related(
                "building",
                "department",
                "revision",
                "revision__contract",
                "revision__contract__company",
            ),
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.method in {"PATCH", "PUT"}:
            obj = getattr(self, "_line", None)
            if obj is not None:
                context["revision"] = obj.revision
        return context

    def get_object(self):
        obj = super().get_object()
        self._line = obj
        return obj

    def perform_update(self, serializer):
        revision = serializer.instance.revision
        enforce_contract_management(self.request.user, revision.contract.company)
        assert_revision_editable(revision)
        serializer.save()

    def perform_destroy(self, instance):
        enforce_contract_management(
            self.request.user, instance.revision.contract.company
        )
        assert_revision_editable(instance.revision)
        instance.delete()
