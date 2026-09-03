"""P-15 §1.1 — the contract lifecycle gets a guard.

P-14's S1 finding: `Contract.lifecycle` was a plain writable
ChoiceField — `PATCH {"lifecycle": ...}` performed ANY jump with a 200
(a CANCELLED contract back to ACTIVE; an ACTIVE one silently to DRAFT,
stopping its invoicing). Every other money-adjacent machine has an
explicit ALLOWED_TRANSITIONS guard; now this one does too. A safety
guard inside the freeze, not a model change: the allowed set mirrors
exactly the moves the UI's own buttons offered.

Pinned here: every illegal jump refused with the machine refusal shape;
the serializer field read-only; the AuditLog diff as the history row;
and §1.2's floor — a contract with invoices cannot be deleted at all.
"""
from __future__ import annotations

from datetime import date

from audit.models import AuditLog
from contracts.models import Contract, ContractInvoice, ContractLifecycle
from contracts.tests.fixtures import (
    ContractsFixture,
    contract_detail_url,
    make_contract,
)
from invoicing.models import Invoice


def transition_url(contract_id):
    return f"/api/contracts/{contract_id}/transition/"


class LifecycleMachineTests(ContractsFixture):
    def _contract(self, no, lifecycle=ContractLifecycle.DRAFT):
        return make_contract(
            company=self.company_a,
            customer=self.customer_a,
            contract_type=self.type_a,
            contract_no=no,
            buildings=[self.building_a],
            lifecycle=lifecycle,
        )

    def _move(self, user, contract, to):
        return self.api(user).post(
            transition_url(contract.id), {"lifecycle": to}, format="json"
        )

    # --- the legal moves (the UI's own buttons) -----------------------

    def test_draft_activates_through_the_door(self):
        contract = self._contract("CNT-P15-0001")
        response = self._move(self.ca_a, contract, "ACTIVE")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["lifecycle"], "ACTIVE")
        contract.refresh_from_db()
        self.assertEqual(contract.lifecycle, ContractLifecycle.ACTIVE)

    def test_draft_and_active_can_cancel(self):
        draft = self._contract("CNT-P15-0002")
        active = self._contract(
            "CNT-P15-0003", lifecycle=ContractLifecycle.ACTIVE
        )
        for contract in (draft, active):
            response = self._move(self.ca_a, contract, "CANCELLED")
            self.assertEqual(response.status_code, 200, response.data)

    # --- every illegal jump, refused with the machine shape -----------

    def test_nothing_leaves_cancelled(self):
        contract = self._contract(
            "CNT-P15-0004", lifecycle=ContractLifecycle.CANCELLED
        )
        for target in ("ACTIVE", "DRAFT"):
            response = self._move(self.ca_a, contract, target)
            self.assertEqual(response.status_code, 400, target)
            self.assertEqual(response.data["code"], "invalid_transition")
            self.assertIn("detail", response.data)
        contract.refresh_from_db()
        self.assertEqual(contract.lifecycle, ContractLifecycle.CANCELLED)

    def test_nothing_goes_back_to_draft(self):
        contract = self._contract(
            "CNT-P15-0005", lifecycle=ContractLifecycle.ACTIVE
        )
        response = self._move(self.ca_a, contract, "DRAFT")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "invalid_transition")

    def test_a_no_op_and_an_unknown_value_are_named(self):
        contract = self._contract("CNT-P15-0006")
        same = self._move(self.ca_a, contract, "DRAFT")
        self.assertEqual(same.status_code, 400)
        self.assertEqual(same.data["code"], "no_op_transition")
        unknown = self._move(self.ca_a, contract, "EXPIRED")
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(unknown.data["code"], "unknown_lifecycle")

    # --- the PATCH hole is closed -------------------------------------

    def test_patch_lifecycle_is_read_only(self):
        contract = self._contract(
            "CNT-P15-0007", lifecycle=ContractLifecycle.CANCELLED
        )
        response = self.api(self.ca_a).patch(
            contract_detail_url(contract.id),
            {"lifecycle": "ACTIVE"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        contract.refresh_from_db()
        self.assertEqual(contract.lifecycle, ContractLifecycle.CANCELLED)

    def test_create_ignores_a_supplied_lifecycle(self):
        from contracts.models import ContractNumberSequence

        # The fixture hand-writes CNT-2026-0001/0002 without touching
        # the sequence; advance it so the allocator does not collide.
        ContractNumberSequence.objects.update_or_create(
            company=self.company_a, year=2026, defaults={"last_number": 100}
        )
        response = self.api(self.ca_a).post(
            "/api/contracts/",
            {
                "customer": self.customer_a.id,
                "start_date": "2026-06-01",
                "lifecycle": "ACTIVE",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["lifecycle"], "DRAFT")

    # --- who may operate the door -------------------------------------

    def test_a_building_manager_is_refused(self):
        contract = self._contract("CNT-P15-0008")
        response = self._move(self.bm_a, contract, "ACTIVE")
        self.assertEqual(response.status_code, 403)

    def test_cross_tenant_is_a_404(self):
        contract = self._contract("CNT-P15-0009")
        response = self._move(self.ca_b, contract, "ACTIVE")
        self.assertEqual(response.status_code, 404)

    # --- the history row (the AuditLog diff IS the trail) -------------

    def test_a_move_writes_the_audit_diff(self):
        contract = self._contract("CNT-P15-0010")
        before = AuditLog.objects.filter(
            target_model="contracts.Contract", target_id=contract.id
        ).count()
        self._move(self.ca_a, contract, "ACTIVE")
        rows = AuditLog.objects.filter(
            target_model="contracts.Contract", target_id=contract.id
        )
        self.assertEqual(rows.count(), before + 1)
        row = rows.order_by("-id").first()
        self.assertIn("lifecycle", row.changes)
        self.assertEqual(row.changes["lifecycle"]["after"], "ACTIVE")

    # --- §1.2 — money-bearing rows cannot be deleted ------------------

    def test_a_contract_with_invoices_cannot_be_deleted(self):
        contract = self._contract(
            "CNT-P15-0011", lifecycle=ContractLifecycle.ACTIVE
        )
        invoice = Invoice.objects.create(
            company=self.company_a,
            customer=self.customer_a,
            status=Invoice.Status.DRAFT,
            created_by=self.ca_a,
        )
        ContractInvoice.objects.create(
            contract=contract,
            invoice=invoice,
            revision=contract.revisions.first(),
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            invoice_date=date(2026, 1, 1),
        )
        response = self.api(self.ca_a).delete(
            contract_detail_url(contract.id)
        )
        self.assertEqual(response.status_code, 400)
        detail = response.data["detail"][0]
        self.assertEqual(detail.code, "contract_has_invoices")
        self.assertTrue(Contract.objects.filter(pk=contract.pk).exists())
        # The list says why the row cannot be picked.
        listed = self.api(self.ca_a).get(
            f"/api/contracts/?search={contract.contract_no}"
        )
        row = next(
            r
            for r in listed.data["results"]
            if r["id"] == contract.id
        )
        self.assertTrue(row["has_invoices"])

    def test_an_invoiceless_contract_still_deletes(self):
        contract = self._contract("CNT-P15-0012")
        response = self.api(self.ca_a).delete(
            contract_detail_url(contract.id)
        )
        self.assertEqual(response.status_code, 204)
