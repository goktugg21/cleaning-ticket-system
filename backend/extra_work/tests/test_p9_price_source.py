"""
P-9 C6 — ruling 12(a): a quote line's source tag says "Contract price"
only when the price IS the contract's; a line the operator priced says
"Your price". The screen reads `price_source` for that and never infers
it from the amount, so this module pins what the server answers on the
three paths the P-9 Pricing table walks:

  * a line the proposal SEEDED from an agreed price   -> CONTRACT
  * a line the operator PRICED from a requested line
    that has no agreed price (P-9 C3's unpriced row,
    sent with the request's own service)              -> CUSTOM
  * a free-text line the operator priced              -> CUSTOM
  * a seeded line the operator RE-PRICED              -> CUSTOM

No migrations, no serializer change: `_classify_proposal_line_source`
already answers this; the pin is here so the badge's truth is tested
where the badge reads it.
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import status

from extra_work.models import ProposalLine

from .test_b2_mixed_cart_proposal import _B2Fixture


class PriceSourceOnQuoteLinesTests(_B2Fixture):
    def _seeded_proposal(self):
        ew = self._submit_cart(
            [
                {"service": self.svc_window.id, "quantity": "50"},
                {"service": self.svc_grass.id, "quantity": "100"},
                {"custom_description": "P-9 custom line ff", "quantity": "1"},
            ]
        )
        self._move_ew_to_under_review(ew)
        response = self._api(self.admin).post(
            self._proposals_url(ew.id), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return ew, response.data

    def _lines_url(self, ew_id: int, pid: int) -> str:
        return f"/api/extra-work/{ew_id}/proposals/{pid}/lines/"

    def test_seeded_agreed_price_line_is_contract(self):
        ew, proposal = self._seeded_proposal()
        # Only the agreed-price line is seeded (the June 3 ruling).
        self.assertEqual(len(proposal["lines"]), 1)
        line = proposal["lines"][0]
        self.assertEqual(line["service"], self.svc_window.id)
        self.assertEqual(line["price_source"], "CONTRACT")
        self.assertEqual(Decimal(line["unit_price"]), Decimal("5.00"))

    def test_line_priced_from_requested_service_without_agreed_price_is_custom(self):
        ew, proposal = self._seeded_proposal()
        # P-9 C3 — the unpriced row sends the request's own service and
        # the price the operator typed.
        response = self._api(self.admin).post(
            self._lines_url(ew.id, proposal["id"]),
            {
                "service": self.svc_grass.id,
                "description": "",
                "quantity": "100",
                "unit_type": "SQUARE_METERS",
                "unit_price": "2.00",
                "vat_pct": "21.00",
                "customer_explanation": "",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["price_source"], "CUSTOM")
        self.assertIsNone(response.data["contract_unit_price"])
        self.assertEqual(response.data["service_name"], self.svc_grass.name)

    def test_free_text_line_the_operator_priced_is_custom(self):
        ew, proposal = self._seeded_proposal()
        response = self._api(self.admin).post(
            self._lines_url(ew.id, proposal["id"]),
            {
                "service": None,
                "description": "P-9 custom line ff",
                "quantity": "1",
                "unit_type": "FIXED",
                "unit_price": "40.00",
                "vat_pct": "21.00",
                "customer_explanation": "",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["price_source"], "CUSTOM")

    def test_seeded_line_repriced_by_the_operator_is_custom(self):
        ew, proposal = self._seeded_proposal()
        line_id = proposal["lines"][0]["id"]
        response = self._api(self.admin).patch(
            f"{self._lines_url(ew.id, proposal['id'])}{line_id}/",
            {"unit_price": "6.00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["price_source"], "CUSTOM")
        self.assertIsNone(response.data["contract_unit_price"])
        # The read path agrees with the write path.
        detail = self._api(self.admin).get(
            f"{self._proposals_url(ew.id)}{proposal['id']}/"
        )
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        by_id = {row["id"]: row for row in detail.data["lines"]}
        self.assertEqual(by_id[line_id]["price_source"], "CUSTOM")
        self.assertEqual(
            ProposalLine.objects.get(pk=line_id).unit_price, Decimal("6.00")
        )
