"""P-5 S0 — THE SEND-TO-CUSTOMER REFUSAL NAMES ITS REASON.

The owner, on crmtest TCK-2026-000385 (meerwerk EW 89, an hourly "regie
uren" line): "Send it to the customer" answered "That was not accepted.
Check what you entered and try again." from the button AND from
Advanced, and he closed the laptop. The machine was refusing under
`actual_hours_required` (Sprint 8B: no customer approval before the
hours are in) — a perfectly good reason that never reached a screen,
because `transition-requirements` did not report it and the page
flattened every 400 into one sentence.

Two things are law now, and these tests hold them:

  1. The requirements endpoint reports `actual_hours` for a move into
     WAITING_CUSTOMER_APPROVAL on a meerwerk ticket, so the modal can
     say so and point at the hours BEFORE the press.
  2. THE ERROR-BODY LAW: every refusal of `POST /tickets/<id>/status/`
     names its reason in the body — a `detail` sentence, or a per-field
     message. The frontend's generic sentence is for a truly detail-
     less 5xx/network failure and nothing else.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from extra_work.models import (
    ExtraWorkCategory,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
    Service,
    ServiceCategory,
)
from test_utils import TenantFixtureMixin
from tickets.models import TicketStatus
from tickets.transition_requirements import (
    ERR_TRANSITION_REQUIREMENTS,
    REQ_ACTUAL_HOURS,
    REQ_ASSIGNEE,
    REQ_SCHEDULE,
    phrase_for,
)


def _names_its_reason(body) -> bool:
    """The error-body law, as a predicate over a refusal body."""
    if not isinstance(body, dict):
        return False
    detail = body.get("detail")
    if isinstance(detail, str) and detail.strip():
        return True
    for key, value in body.items():
        if key in {"code", "unmet", "field", "days"}:
            continue
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and any(
            isinstance(v, str) and v.strip() for v in value
        ):
            return True
    return False


class SendToCustomerNamesItsReasonTests(TenantFixtureMixin, APITestCase):
    """TCK-2026-000385, rebuilt: a meerwerk ticket with one HOURS line
    whose actual hours are still empty, waiting for the manager's check."""

    def setUp(self):
        super().setUp()
        category = ServiceCategory.objects.create(
            company=self.company, name="Extra Werk op regie"
        )
        self.service = Service.objects.create(
            category=category,
            company=self.company,
            name="Extra werk regie uren",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("31.48"),
        )
        self.ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Extra werk regie uren +1",
            description="",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.IN_PROGRESS,
            routing_decision=ExtraWorkRoutingDecision.INSTANT,
        )
        self.line = ExtraWorkRequestItem.objects.create(
            extra_work_request=self.ew,
            service=self.service,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 9, 10),
            customer_note="",
        )
        self.ticket.extra_work_request = self.ew
        self.ticket.extra_work_request_item = self.line
        self.ticket.status = TicketStatus.WAITING_MANAGER_REVIEW
        self.ticket.save(
            update_fields=[
                "extra_work_request",
                "extra_work_request_item",
                "status",
                "updated_at",
            ]
        )
        self.make_workable()

    def _requirements(self, to_status=TicketStatus.WAITING_CUSTOMER_APPROVAL):
        return self.client.get(
            f"/api/tickets/{self.ticket.id}/transition-requirements/",
            {"to_status": to_status},
        )

    def _send_to_customer(self, note="done"):
        return self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": TicketStatus.WAITING_CUSTOMER_APPROVAL, "note": note},
            format="json",
        )

    def test_the_modal_is_told_about_the_hours_before_the_press(self):
        self.authenticate(self.company_admin)
        response = self._requirements()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn(REQ_ACTUAL_HOURS, response.data["unmet"])
        self.assertIn(
            {"key": REQ_ACTUAL_HOURS, "satisfied": False},
            response.data["requirements"],
        )

    def test_the_refusal_names_the_hours_and_the_replay_then_succeeds(self):
        self.authenticate(self.company_admin)

        refused = self._send_to_customer()
        self.assertEqual(refused.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(refused.data["code"], "actual_hours_required")
        self.assertTrue(_names_its_reason(refused.data), refused.data)
        self.assertIn("hours", str(refused.data["detail"]).lower())
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.WAITING_MANAGER_REVIEW)

        # The owner's missing step: the hours, entered where the modal
        # now points.
        entered = self.client.post(
            f"/api/extra-work/{self.ew.id}/actual-hours/",
            {"lines": [{"line_id": self.line.id, "actual_hours": "3.00"}]},
            format="json",
        )
        self.assertEqual(entered.status_code, status.HTTP_200_OK, entered.data)

        again = self._requirements()
        self.assertNotIn(REQ_ACTUAL_HOURS, again.data["unmet"])
        self.assertIn(
            {"key": REQ_ACTUAL_HOURS, "satisfied": True},
            again.data["requirements"],
        )

        sent = self._send_to_customer()
        self.assertEqual(sent.status_code, status.HTTP_200_OK, sent.data)
        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )

    def test_a_ticket_without_meerwerk_is_not_asked_for_hours(self):
        self.ticket.extra_work_request = None
        self.ticket.extra_work_request_item = None
        self.ticket.save(
            update_fields=["extra_work_request", "extra_work_request_item"]
        )
        self.authenticate(self.company_admin)
        response = self._requirements()
        keys = [r["key"] for r in response.data["requirements"]]
        self.assertNotIn(REQ_ACTUAL_HOURS, keys)


class EveryRefusalNamesItsReasonTests(TenantFixtureMixin, APITestCase):
    """The error-body law over the status endpoint's refusal paths."""

    def _post(self, actor, ticket=None, **payload):
        self.authenticate(actor)
        return self.client.post(
            f"/api/tickets/{(ticket or self.ticket).id}/status/",
            payload,
            format="json",
        )

    def assertNamesReason(self, response):
        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertTrue(_names_its_reason(response.data), response.data)

    def test_missing_requirements_are_named_in_words_and_listed(self):
        response = self._post(self.manager, to_status=TicketStatus.IN_PROGRESS)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], ERR_TRANSITION_REQUIREMENTS)
        self.assertEqual(
            sorted(response.data["unmet"]), sorted([REQ_ASSIGNEE, REQ_SCHEDULE])
        )
        self.assertIn(phrase_for(REQ_ASSIGNEE), response.data["detail"])
        self.assertIn(phrase_for(REQ_SCHEDULE), response.data["detail"])
        # Never the raw key.
        self.assertNotIn("completion_evidence", response.data["detail"])

    def test_a_no_op_move_names_itself(self):
        self.assertNamesReason(self._post(self.manager, to_status=TicketStatus.OPEN))

    def test_an_unknown_status_names_the_field(self):
        response = self._post(self.manager, to_status="BANANA")
        self.assertNamesReason(response)
        self.assertIn("to_status", response.data)

    def test_a_customer_pressing_a_staff_move_is_told_so(self):
        response = self._post(self.customer_user, to_status=TicketStatus.IN_PROGRESS)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNamesReason(response)

    def test_a_forbidden_move_names_the_move(self):
        self.ticket.status = TicketStatus.OPEN
        self.ticket.save(update_fields=["status"])
        response = self._post(self.customer_user, to_status=TicketStatus.APPROVED)
        self.assertNamesReason(response)
        self.assertEqual(response.data["code"], "forbidden_transition")

    def test_sending_back_without_a_note_names_the_note(self):
        self.ticket.status = TicketStatus.WAITING_MANAGER_REVIEW
        self.ticket.save(update_fields=["status"])
        response = self._post(self.manager, to_status=TicketStatus.IN_PROGRESS)
        self.assertNamesReason(response)
        self.assertIn("note", response.data)

    def test_an_override_without_a_reason_names_the_reason(self):
        self.move_ticket_to_customer_approval()
        response = self._post(self.company_admin, to_status=TicketStatus.APPROVED)
        self.assertNamesReason(response)
        self.assertEqual(response.data["code"], "override_reason_required")
