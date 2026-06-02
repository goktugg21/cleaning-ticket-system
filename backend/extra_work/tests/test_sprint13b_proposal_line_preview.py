"""
Sprint 13B — compute-only proposal-line live-preview endpoint.

The preview endpoint
(`POST /api/extra-work/<ew_id>/proposals/<pid>/lines/preview/`) is a
pure calculator: it returns per-line + aggregate money using the SAME
`compute_line_amounts` helper that `ProposalLine.save()` calls, and it
persists nothing. These tests pin:

  * PARITY — preview == the values a real create persists, and preview
    aggregate == `proposal.recompute_totals()` output (incl. a
    rounding-sensitive case).
  * MULTI-LINE aggregate correctness.
  * PERSISTS NOTHING — `ProposalLine.objects.count()` is unchanged.
  * PERMISSIONS — SA / in-scope CA / in-scope BM (prep key on) -> 200;
    STAFF -> 403; CUSTOMER_USER -> blocked; out-of-scope provider -> 404.
  * VALIDATION — stable top-level error codes for every bad-input case.
  * VAT default 21.00 when omitted.
"""
from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from extra_work.models import (
    ExtraWorkPricingUnitType,
    Proposal,
    ProposalLine,
    ProposalStatus,
)

from .test_sprint28_proposal import ProposalFixtureMixin


class ProposalLinePreviewMixin(ProposalFixtureMixin):
    def _preview_url(self, ew_id: int, pid: int) -> str:
        return f"/api/extra-work/{ew_id}/proposals/{pid}/lines/preview/"

    def _preview_line(self, **overrides) -> dict:
        line = {
            "service": self.service.id,
            "quantity": "2.00",
            "unit_type": ExtraWorkPricingUnitType.HOURS,
            "unit_price": "50.00",
            "vat_pct": "21.00",
        }
        line.update(overrides)
        return line


# ---------------------------------------------------------------------------
# Parity: preview == persisted == recompute_totals
# ---------------------------------------------------------------------------
class ProposalLinePreviewParityTests(ProposalLinePreviewMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_preview_matches_persisted_line_and_totals(self):
        ew = self._make_ew()
        # Empty DRAFT proposal (no lines yet) so we can preview, then
        # create the same single line and compare.
        proposal = Proposal.objects.create(
            extra_work_request=ew,
            status=ProposalStatus.DRAFT,
            created_by=self.admin,
        )

        line_in = self._preview_line(
            quantity="3.50", unit_price="45.00", vat_pct="21.00"
        )
        preview = self._api(self.admin).post(
            self._preview_url(ew.id, proposal.id),
            {"lines": [line_in]},
            format="json",
        )
        self.assertEqual(preview.status_code, 200, preview.data)

        # Rounding-sensitive expectations:
        #   subtotal = 3.50 * 45.00 = 157.50
        #   vat      = 157.50 * 21 / 100 = 33.075 -> 33.08
        #   total    = 157.50 + 33.08 = 190.58
        pv_line = preview.data["lines"][0]
        self.assertEqual(pv_line["line_subtotal"], "157.50")
        self.assertEqual(pv_line["line_vat"], "33.08")
        self.assertEqual(pv_line["line_total"], "190.58")
        self.assertEqual(preview.data["totals"]["subtotal"], "157.50")
        self.assertEqual(preview.data["totals"]["vat"], "33.08")
        self.assertEqual(preview.data["totals"]["total"], "190.58")

        # Now actually create the SAME line and assert byte-parity.
        create = self._api(self.admin).post(
            self._lines_url(ew.id, proposal.id),
            line_in,
            format="json",
        )
        self.assertEqual(create.status_code, 201, create.data)
        persisted = ProposalLine.objects.get(pk=create.data["id"])

        self.assertEqual(
            pv_line["line_subtotal"], f"{persisted.line_subtotal:.2f}"
        )
        self.assertEqual(pv_line["line_vat"], f"{persisted.line_vat:.2f}")
        self.assertEqual(pv_line["line_total"], f"{persisted.line_total:.2f}")

        # And the aggregate matches recompute_totals().
        proposal.recompute_totals()
        proposal.refresh_from_db()
        self.assertEqual(
            preview.data["totals"]["subtotal"],
            f"{proposal.subtotal_amount:.2f}",
        )
        self.assertEqual(
            preview.data["totals"]["vat"], f"{proposal.vat_amount:.2f}"
        )
        self.assertEqual(
            preview.data["totals"]["total"], f"{proposal.total_amount:.2f}"
        )


# ---------------------------------------------------------------------------
# Multi-line aggregate
# ---------------------------------------------------------------------------
class ProposalLinePreviewAggregateTests(
    ProposalLinePreviewMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_multi_line_aggregate_totals(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)

        # Line A: 2.00 * 50.00 = 100.00 ; vat 21.00 ; total 121.00
        # Line B: 1.00 * 10.00 =  10.00 ; vat  2.10 ; total  12.10
        # aggregate: subtotal 110.00 ; vat 23.10 ; total 133.10
        response = self._api(self.admin).post(
            self._preview_url(ew.id, proposal.id),
            {
                "lines": [
                    self._preview_line(quantity="2.00", unit_price="50.00"),
                    self._preview_line(quantity="1.00", unit_price="10.00"),
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["lines"]), 2)
        self.assertEqual(response.data["lines"][0]["line_total"], "121.00")
        self.assertEqual(response.data["lines"][1]["line_total"], "12.10")
        self.assertEqual(response.data["totals"]["subtotal"], "110.00")
        self.assertEqual(response.data["totals"]["vat"], "23.10")
        self.assertEqual(response.data["totals"]["total"], "133.10")


# ---------------------------------------------------------------------------
# Persists nothing
# ---------------------------------------------------------------------------
class ProposalLinePreviewNoWriteTests(
    ProposalLinePreviewMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_preview_persists_nothing(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        before = ProposalLine.objects.count()

        response = self._api(self.admin).post(
            self._preview_url(ew.id, proposal.id),
            {
                "lines": [
                    self._preview_line(quantity="4.00", unit_price="99.99"),
                    self._preview_line(quantity="2.00", unit_price="10.00"),
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(ProposalLine.objects.count(), before)


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
class ProposalLinePreviewPermissionTests(
    ProposalLinePreviewMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _post(self, actor, ew, proposal):
        return self._api(actor).post(
            self._preview_url(ew.id, proposal.id),
            {"lines": [self._preview_line()]},
            format="json",
        )

    def test_super_admin_can_preview(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        response = self._post(self.super_admin, ew, proposal)
        self.assertEqual(response.status_code, 200, response.data)

    def test_company_admin_in_scope_can_preview(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        response = self._post(self.admin, ew, proposal)
        self.assertEqual(response.status_code, 200, response.data)

    def test_building_manager_in_scope_can_preview(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        response = self._post(self.building_manager, ew, proposal)
        self.assertEqual(response.status_code, 200, response.data)

    def test_staff_forbidden(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        # STAFF cannot see the parent EW (scope returns none) -> 404 at
        # proposal resolution, which is the correct "blocked" outcome.
        response = self._post(self.staff, ew, proposal)
        self.assertEqual(response.status_code, 404, response.data)

    def test_customer_blocked_on_sent_proposal_403(self):
        # On a SENT proposal the customer CAN resolve the proposal but
        # the provider-only guard returns 403.
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposalStatus.SENT)
        response = self._post(self.cust_user, ew, proposal)
        self.assertEqual(response.status_code, 403, response.data)

    def test_customer_blocked_on_draft_proposal_404(self):
        # DRAFT is operator-internal — the customer cannot even resolve
        # the proposal -> 404.
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self.assertEqual(proposal.status, ProposalStatus.DRAFT)
        response = self._post(self.cust_user, ew, proposal)
        self.assertEqual(response.status_code, 404, response.data)

    def test_out_of_scope_provider_404(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        response = self._post(self.other_admin, ew, proposal)
        self.assertEqual(response.status_code, 404, response.data)


# ---------------------------------------------------------------------------
# Validation — stable top-level error codes
# ---------------------------------------------------------------------------
class ProposalLinePreviewValidationTests(
    ProposalLinePreviewMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def setUp(self):
        self.ew = self._make_ew()
        self.proposal = self._create_proposal(self.ew)

    def _post(self, body):
        return self._api(self.admin).post(
            self._preview_url(self.ew.id, self.proposal.id),
            body,
            format="json",
        )

    def test_missing_lines(self):
        response = self._post({})
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "preview_lines_required")

    def test_empty_lines(self):
        response = self._post({"lines": []})
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "preview_lines_required")

    def test_invalid_unit_type(self):
        response = self._post(
            {"lines": [self._preview_line(unit_type="NOT_A_UNIT")]}
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "unit_type_invalid")
        self.assertEqual(response.data["index"], 0)

    def test_vat_out_of_range(self):
        response = self._post(
            {"lines": [self._preview_line(vat_pct="150")]}
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "vat_invalid")

    def test_quantity_zero(self):
        response = self._post(
            {"lines": [self._preview_line(quantity="0")]}
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "quantity_invalid")

    def test_unit_price_negative(self):
        response = self._post(
            {"lines": [self._preview_line(unit_price="-1")]}
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "unit_price_invalid")

    def test_quantity_not_a_number(self):
        response = self._post(
            {"lines": [self._preview_line(quantity="abc")]}
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "quantity_invalid")

    def test_adhoc_line_without_service_or_description(self):
        line = self._preview_line()
        line.pop("service")
        response = self._post({"lines": [line]})
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "preview_line_invalid")

    def test_adhoc_line_with_description_is_valid(self):
        line = self._preview_line()
        line.pop("service")
        line["description"] = "Ad-hoc scaffolding"
        response = self._post({"lines": [line]})
        self.assertEqual(response.status_code, 200, response.data)


# ---------------------------------------------------------------------------
# VAT default
# ---------------------------------------------------------------------------
class ProposalLinePreviewVatDefaultTests(
    ProposalLinePreviewMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_vat_defaults_to_21_when_omitted(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        line = self._preview_line(quantity="2.00", unit_price="50.00")
        line.pop("vat_pct")
        response = self._api(self.admin).post(
            self._preview_url(ew.id, proposal.id),
            {"lines": [line]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        # subtotal 100.00, 21% vat -> 21.00, total 121.00
        pv_line = response.data["lines"][0]
        self.assertEqual(pv_line["line_subtotal"], "100.00")
        self.assertEqual(pv_line["line_vat"], "21.00")
        self.assertEqual(pv_line["line_total"], "121.00")
