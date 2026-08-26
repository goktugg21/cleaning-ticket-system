"""
W16 — the EXTRA WORKS REGISTER endpoints.

    GET  /api/contracts/extra-works/<int:customer_id>/
    POST /api/contracts/extra-works/<int:customer_id>/sync/

Copied from the reference system's
`ContractController::getOrCreateExtraWorksContract` and its three
line verbs, with one deliberate difference in the verb set.

HIS four:  GET get-or-create, POST add line, PUT edit line, DELETE line.
OURS two:  GET get-or-create (which syncs on read), POST resync.

The three line verbs are absent because ours are not hand-typed. His
operator types a description and an amount onto a register line, which
is why his register drifts from his invoices — nothing links the line
to the job, so nothing can tell him when the job's price moved. Ours
mirrors the real `ExtraWorkRequest` rows through the same
`_amounts_for_state` the invoice reads, so "edit this line" would mean
"write a number the next sync overwrites". The place to change what a
register line says is the Extra Work itself, which is the one place
that number is allowed to live.

`extra_work_register.py` carries the full reasoning, including why the
register never raises an invoice.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from customers.models import Customer

from .extra_work_register import (
    _ticket_map,
    existing_register,
    get_or_create_register,
    register_extra_work,
    register_revision,
    register_summary,
    sync_extra_work_register,
)
from .permissions import IsContractManager, IsContractReader
from .scope import filter_customers_for_contracts, managed_building_ids
from .serializers import ContractLineSerializer


def _scoped_customer(user, customer_id):
    """The customer, through the actor's contract scope, or None.

    Out-of-scope reads as "no such customer", the same 404-not-403 the
    rest of the module uses: a 403 would confirm the row exists, which
    is the existence oracle H-1 forbids.
    """
    return (
        filter_customers_for_contracts(user, Customer.objects.all())
        .filter(pk=customer_id)
        .first()
    )


def _register_payload(contract, revision, ews, tickets, building_ids=None):
    """The register, its lines GROUPED BY BUILDING, and the summary.

    Grouped by building because that is the shape his screen has and
    the shape the question has: "what did we do at this address, and
    what did it come to". Buildings with no chargeable work are
    included with an empty list and a zero — his `getOrCreate...` does
    the same, and an address that silently vanishes reads as an
    address nobody visited rather than one with nothing to bill.
    """
    lines = list(
        revision.lines.select_related("building", "extra_work").order_by(
            "sort_order", "id"
        )
    )
    if building_ids is not None:
        # W-FIX1 D5 (audit F9) — a BUILDING_MANAGER reads the buildings
        # they manage. `scope_extra_work_for` and `filter_contracts_for`
        # both narrow a BM by building; this door did not, so a manager
        # of B1 read every job, amount and address of the customer's
        # other buildings.
        lines = [line for line in lines if line.building_id in building_ids]
    by_building = {}
    for line in lines:
        by_building.setdefault(line.building_id, []).append(line)

    buildings = []
    seen = set()
    customer_buildings = [
        membership.building
        for membership in contract.customer.building_memberships.select_related(
            "building"
        ).order_by("building__name", "building_id")
    ]
    for building in customer_buildings:
        if building_ids is not None and building.id not in building_ids:
            continue
        seen.add(building.id)
        rows = by_building.get(building.id, [])
        buildings.append(
            {
                "id": building.id,
                "name": building.name,
                "job_count": len(rows),
                "total_amount": sum((r.amount for r in rows), 0),
                "lines": ContractLineSerializer(rows, many=True).data,
            }
        )
    # Work on a building the customer no longer holds still has to
    # appear, or the register's total would not equal its rows.
    for building_id, rows in by_building.items():
        if building_id in seen:
            continue
        buildings.append(
            {
                "id": building_id,
                "name": rows[0].building.name if rows[0].building else "—",
                "job_count": len(rows),
                "total_amount": sum((r.amount for r in rows), 0),
                "lines": ContractLineSerializer(rows, many=True).data,
            }
        )

    return {
        "contract": {
            "id": contract.id,
            "contract_no": contract.contract_no,
            "kind": contract.kind,
            "customer": contract.customer_id,
            "customer_name": contract.customer.name,
            "revision": revision.id,
        },
        "buildings": buildings,
        "summary": register_summary(
            contract, revision, ews, tickets, building_ids
        ),
    }


def _empty_register_payload(customer, ews, building_ids=None):
    """W-FIX1 D2 — the register before anyone has synced it: the same
    shape with `contract: null`, the customer's buildings with no
    lines, and a zero summary. A GET must not make the register exist;
    the explicit sync does."""
    buildings = []
    for membership in customer.building_memberships.select_related(
        "building"
    ).order_by("building__name", "building_id"):
        building = membership.building
        if building_ids is not None and building.id not in building_ids:
            continue
        buildings.append(
            {
                "id": building.id,
                "name": building.name,
                "job_count": 0,
                "total_amount": 0,
                "lines": [],
            }
        )
    return {
        "contract": None,
        "buildings": buildings,
        "summary": {
            "job_count": 0,
            "building_count": 0,
            "total_amount": 0,
            "earned_amount": 0,
            "invoiced_amount": 0,
            "pending_sync": len(ews),
        },
    }


class ExtraWorkRegisterView(APIView):
    """GET the customer's register. A READ: it writes nothing.

    W-FIX1 D2 (audit F26) — this used to sync on read for a manager
    and get-or-create the register for everyone, so a GET was a write
    with no uniqueness guard under it: two tabs opening one customer
    could each create the missing lines. The sync is now the explicit
    `POST .../sync/` (the page calls it once when a manager opens the
    register, and its button calls it again on demand); a customer whose
    register has never been made reads an empty one with `contract:
    null` rather than causing one to exist.
    """

    permission_classes = [IsContractReader]

    def get(self, request, customer_id):
        customer = _scoped_customer(request.user, customer_id)
        if customer is None:
            return Response(
                {"detail": "No such customer.", "code": "customer_not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        building_ids = managed_building_ids(request.user)
        contract = existing_register(customer.company, customer)
        ews = register_extra_work(
            customer.company_id, customer.id, building_ids=building_ids
        )
        if contract is None:
            return Response(
                _empty_register_payload(customer, ews, building_ids)
            )
        revision = register_revision(contract)
        return Response(
            _register_payload(
                contract, revision, ews, _ticket_map(ews), building_ids
            )
        )


class ExtraWorkRegisterSyncView(APIView):
    """POST — rebuild the register and SAY WHAT CHANGED.

    The reference system's equivalent is `POST /contracts/{id}/
    recalculate`, which re-sums stored totals and answers "Contract
    totals recalculated" whether or not anything moved. Ours returns
    the counts, because "3 jobs added, 1 reprice" is an answer and
    "recalculated" is not.
    """

    permission_classes = [IsContractManager]

    def post(self, request, customer_id):
        customer = _scoped_customer(request.user, customer_id)
        if customer is None:
            return Response(
                {"detail": "No such customer.", "code": "customer_not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        changed = sync_extra_work_register(
            customer.company, customer, actor=request.user
        )
        contract = get_or_create_register(
            customer.company, customer, actor=request.user
        )
        building_ids = managed_building_ids(request.user)
        revision = register_revision(contract)
        ews = register_extra_work(
            customer.company_id, customer.id, building_ids=building_ids
        )
        payload = _register_payload(
            contract, revision, ews, _ticket_map(ews), building_ids
        )
        payload["changed"] = changed
        return Response(payload)
