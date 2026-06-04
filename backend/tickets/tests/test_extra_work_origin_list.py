"""
`extra_work_origin` on TicketListSerializer (OSIUS EW-origin-on-list).

The ticket LIST endpoint must surface the SAME `extra_work_origin`
contract the detail endpoint exposes (so the frontend
`TicketExtraWorkOrigin` type consumes both without a branch), produced
by the SHARED resolver `resolve_extra_work_origin_core` so the JSON
matches exactly for the six typed keys.

Pins:
  * an EW-spawned (INSTANT) ticket carries a POPULATED `extra_work_origin`
    on the list (id / title / status / origin / item_id / service_name),
  * a PROPOSAL-route ticket carries `origin == "PROPOSAL"` walked back
    through the proposal chain,
  * a normal (non-EW) ticket carries `null`,
  * the six shared keys are byte-identical between the list payload and
    the detail payload,
  * adding the field does NOT scale the list query count with the number
    of EW-spawned rows (no N+1).
"""
from __future__ import annotations

from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from extra_work.models import ExtraWorkStatus

from tickets.tests.test_extra_work_origin import ExtraWorkOriginFixtureMixin


SHARED_ORIGIN_KEYS = {
    "extra_work_request_id",
    "extra_work_request_title",
    "extra_work_request_status",
    "extra_work_request_item_id",
    "service_name",
    "origin",
}


def _results(response):
    return response.data.get("results", response.data)


def _find(results, ticket_id):
    for row in results:
        if row["id"] == ticket_id:
            return row
    raise AssertionError(f"ticket {ticket_id} not in list response")


class ListOriginPopulatedTests(ExtraWorkOriginFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_instant_ticket_lists_with_populated_origin(self):
        ew, item, ticket = self._make_instant_ticket()
        response = self._api(self.super_admin).get("/api/tickets/")
        self.assertEqual(response.status_code, 200, response.data)
        row = _find(_results(response), ticket.id)
        origin = row.get("extra_work_origin")
        self.assertIsNotNone(origin)
        self.assertEqual(origin["origin"], "INSTANT")
        self.assertEqual(origin["extra_work_request_id"], ew.id)
        self.assertEqual(origin["extra_work_request_title"], ew.title)
        self.assertEqual(
            origin["extra_work_request_status"],
            ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        self.assertEqual(origin["extra_work_request_item_id"], item.id)
        self.assertEqual(origin["service_name"], self.service.name)
        # The list keeps the contract minimal: exactly the six typed keys.
        self.assertEqual(set(origin.keys()), SHARED_ORIGIN_KEYS)

    def test_proposal_ticket_lists_with_proposal_origin(self):
        ew, line, ticket = self._make_proposal_ticket()
        response = self._api(self.super_admin).get("/api/tickets/")
        self.assertEqual(response.status_code, 200, response.data)
        row = _find(_results(response), ticket.id)
        origin = row.get("extra_work_origin")
        self.assertIsNotNone(origin)
        self.assertEqual(origin["origin"], "PROPOSAL")
        self.assertEqual(origin["extra_work_request_id"], ew.id)
        self.assertEqual(origin["extra_work_request_title"], ew.title)
        # Proposal spawn leaves `extra_work_request_item` unset.
        self.assertIsNone(origin["extra_work_request_item_id"])
        self.assertEqual(origin["service_name"], self.service.name)


class ListOriginNullTests(ExtraWorkOriginFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_normal_ticket_lists_with_null_origin(self):
        ticket = self._make_legacy_ticket()
        response = self._api(self.super_admin).get("/api/tickets/")
        self.assertEqual(response.status_code, 200, response.data)
        row = _find(_results(response), ticket.id)
        self.assertIn("extra_work_origin", row)
        self.assertIsNone(row["extra_work_origin"])


class ListVsDetailParityTests(ExtraWorkOriginFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_list_origin_matches_detail_for_shared_keys(self):
        ew, item, ticket = self._make_instant_ticket()
        list_resp = self._api(self.super_admin).get("/api/tickets/")
        detail_resp = self._api(self.super_admin).get(
            f"/api/tickets/{ticket.id}/"
        )
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(detail_resp.status_code, 200)

        list_origin = _find(_results(list_resp), ticket.id)["extra_work_origin"]
        detail_origin = detail_resp.data["extra_work_origin"]
        self.assertIsNotNone(list_origin)
        self.assertIsNotNone(detail_origin)
        for key in SHARED_ORIGIN_KEYS:
            self.assertEqual(
                list_origin[key],
                detail_origin[key],
                f"list/detail disagree on `{key}`",
            )


class ListOriginNoNPlusOneTests(ExtraWorkOriginFixtureMixin, TestCase):
    """Adding `extra_work_origin` to the list must not make the query
    count grow with the number of EW-spawned rows. The shared resolver
    only reads forward FKs, which the list viewset eager-loads via
    select_related, so the count is flat across page sizes."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _list_query_count(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self._api(self.super_admin).get("/api/tickets/")
            self.assertEqual(response.status_code, 200, response.data)
        return len(ctx.captured_queries)

    def test_query_count_flat_across_ew_spawned_rows(self):
        # One EW-spawned ticket.
        self._make_instant_ticket()
        baseline = self._list_query_count()

        # Several more EW-spawned tickets (mixed routes). If the origin
        # field re-queried per row, the count would climb.
        for _ in range(4):
            self._make_instant_ticket()
        self._make_proposal_ticket()
        self._make_proposal_ticket()

        grown = self._list_query_count()
        self.assertLessEqual(
            grown,
            baseline,
            "list query count scaled with EW-spawned rows (N+1 regression)",
        )
