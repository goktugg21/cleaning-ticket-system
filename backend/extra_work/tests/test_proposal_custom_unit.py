"""
#108 Part B — `custom_unit_label` on ProposalLine.

The composer's "Custom…" unit entry stores an operator-supplied unit
name on the line (additive column, mirroring RF-2 on
CustomerCustomPrice). Serializer rules under test:

* OTHER + non-empty label -> persisted (stripped).
* OTHER + blank/absent label -> legal (plain "Other" stays an option —
  owner decision; differs from the catalog rule, where OTHER requires
  a label).
* OTHER + whitespace-only label -> 400 with the stable code
  `custom_unit_label_required` (an attempted custom name that
  collapses to nothing).
* Any concrete unit type -> label forced blank (a stale label can
  never contradict its unit).
* The customer read path carries the label (it is customer-visible
  unit text — it renders on the proposal PDF).
"""
from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from extra_work.models import ProposalLine, ProposalStatus

from .test_sprint28_proposal import ProposalFixtureMixin


class ProposalLineCustomUnitTest(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _draft_proposal(self):
        ew = self._make_ew()
        api = self._api(self.admin)
        resp = api.post(self._proposals_url(ew.id), {"lines": []}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        return ew, resp.data["id"]

    def _line_payload(self, **overrides):
        payload = {
            "description": "Custom-unit line",
            "quantity": "2.00",
            "unit_type": "OTHER",
            "unit_price": "10.00",
            "vat_pct": "21.00",
        }
        payload.update(overrides)
        return payload

    def test_other_with_label_persists_stripped(self):
        ew, pid = self._draft_proposal()
        api = self._api(self.admin)
        resp = api.post(
            self._lines_url(ew.id, pid),
            self._line_payload(custom_unit_label="  m³  "),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["custom_unit_label"], "m³")
        line = ProposalLine.objects.get(id=resp.data["id"])
        self.assertEqual(line.custom_unit_label, "m³")

    def test_other_with_blank_label_stays_legal(self):
        ew, pid = self._draft_proposal()
        api = self._api(self.admin)
        for payload in (
            self._line_payload(),  # key absent
            self._line_payload(custom_unit_label=""),  # explicit blank
        ):
            resp = api.post(self._lines_url(ew.id, pid), payload, format="json")
            self.assertEqual(resp.status_code, 201, resp.content)
            self.assertEqual(resp.data["custom_unit_label"], "")

    def test_other_with_whitespace_only_label_rejected(self):
        ew, pid = self._draft_proposal()
        api = self._api(self.admin)
        resp = api.post(
            self._lines_url(ew.id, pid),
            self._line_payload(custom_unit_label="   "),
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(
            resp.data["custom_unit_label"][0].code,
            "custom_unit_label_required",
        )

    def test_concrete_unit_forces_label_blank(self):
        ew, pid = self._draft_proposal()
        api = self._api(self.admin)
        resp = api.post(
            self._lines_url(ew.id, pid),
            self._line_payload(unit_type="HOURS", custom_unit_label="m³"),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["custom_unit_label"], "")
        line = ProposalLine.objects.get(id=resp.data["id"])
        self.assertEqual(line.custom_unit_label, "")

    def test_customer_read_carries_label_after_send(self):
        ew, pid = self._draft_proposal()
        api = self._api(self.admin)
        resp = api.post(
            self._lines_url(ew.id, pid),
            self._line_payload(custom_unit_label="pallet"),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        resp = api.post(
            self._transition_url(ew.id, pid),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        cust = self._api(self.cust_user)
        resp = cust.get(self._proposal_url(ew.id, pid))
        self.assertEqual(resp.status_code, 200, resp.content)
        lines = resp.data["lines"]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["custom_unit_label"], "pallet")
        # The provider-only note stays absent on the customer read —
        # adding the label must not disturb the privacy shape.
        self.assertNotIn("internal_note", lines[0])

    def test_nested_create_path_accepts_label(self):
        ew = self._make_ew()
        api = self._api(self.admin)
        resp = api.post(
            self._proposals_url(ew.id),
            {
                "lines": [
                    self._line_payload(custom_unit_label="krat"),
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        line = ProposalLine.objects.get(proposal_id=resp.data["id"])
        self.assertEqual(line.custom_unit_label, "krat")
        self.assertEqual(line.quantity, Decimal("2.00"))
