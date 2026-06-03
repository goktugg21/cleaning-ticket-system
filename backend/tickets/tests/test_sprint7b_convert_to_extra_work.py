"""
Sprint 7B — convert a normal Ticket / melding into an Extra Work request.

A provider operator converts an inbound ticket into chargeable Extra
Work. The source ticket is superseded to the terminal status
CONVERTED_TO_EXTRA_WORK (leaving every operational queue); a NEW
operational ticket is spawned by the existing Sprint 6A/6B machinery
anchored to the new ExtraWorkRequest. The original ticket is NOT reused
and its assignments / attachments / messages are left intact (not
copied).

All three EW intents are allowed on conversion, including REQUEST_QUOTE
— which the normal provider create path still forbids. That exception
is conversion-only (test 7 proves it).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from extra_work.models import (
    CustomerServicePrice,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestIntent,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
    ProposalStatus,
    Service,
    ServiceCategory,
)
from tickets.models import (
    Ticket,
    TicketAttachment,
    TicketMessage,
    TicketStatus,
    TicketStatusHistory,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
CONVERT_URL = "/api/tickets/{ticket_id}/convert-to-extra-work/"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class ConvertFixtureMixin:
    @classmethod
    def _setup_fixture(cls):
        cls.company = Company.objects.create(
            name="Sprint7B Provider", slug="sprint7b"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Building-7B"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer-7B", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        # --- provider-side principals -----------------------------------
        cls.super_admin = _mk(
            "super-7b@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-7b@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.bm = _mk("bm-7b@example.com", UserRole.BUILDING_MANAGER)
        CompanyUserMembership.objects.create(user=cls.bm, company=cls.company)
        BuildingManagerAssignment.objects.create(
            user=cls.bm, building=cls.building
        )
        cls.staff = _mk("staff-7b@example.com", UserRole.STAFF)
        CompanyUserMembership.objects.create(
            user=cls.staff, company=cls.company
        )

        # --- customer-side principals ------------------------------------
        cls.cust_user = _mk("cust-7b@example.com", UserRole.CUSTOMER_USER)
        m_user = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m_user,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
            is_active=True,
        )
        # A customer actor permitted to approve a proposal at the pair
        # (LOCATION_MANAGER carries approve_location by default).
        cls.cust_loc = _mk("cust-loc-7b@example.com", UserRole.CUSTOMER_USER)
        m_loc = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_loc
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m_loc,
            building=cls.building,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
            ),
            is_active=True,
        )

        # --- catalog -----------------------------------------------------
        cls.cat = ServiceCategory.objects.create(name="Cat-7B")
        cls.service_agreed = Service.objects.create(
            category=cls.cat,
            company=cls.company,
            name="Agreed service",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )
        CustomerServicePrice.objects.create(
            service=cls.service_agreed,
            customer=cls.customer,
            unit_price=Decimal("48.50"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            valid_to=None,
            is_active=True,
        )
        cls.service_unpriced = Service.objects.create(
            category=cls.cat,
            company=cls.company,
            name="No-contract service",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("40.00"),
        )

        # --- a second, foreign provider for cross-scope checks -----------
        cls.other_company = Company.objects.create(
            name="Other Provider", slug="sprint7b-other"
        )
        cls.other_building = Building.objects.create(
            company=cls.other_company, name="Other-Building"
        )
        cls.other_customer = Customer.objects.create(
            company=cls.other_company,
            name="Other-Customer",
            building=cls.other_building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.other_customer, building=cls.other_building
        )
        cls.other_admin = _mk(
            "other-admin-7b@example.com", UserRole.COMPANY_ADMIN
        )
        CompanyUserMembership.objects.create(
            user=cls.other_admin, company=cls.other_company
        )
        # A BM in our company but NOT assigned to cls.building.
        cls.bm_unassigned = _mk(
            "bm-unassigned-7b@example.com", UserRole.BUILDING_MANAGER
        )
        CompanyUserMembership.objects.create(
            user=cls.bm_unassigned, company=cls.company
        )
        cls.building_2 = Building.objects.create(
            company=cls.company, name="Building-7B-2"
        )
        BuildingManagerAssignment.objects.create(
            user=cls.bm_unassigned, building=cls.building_2
        )

    # -- helpers ---------------------------------------------------------
    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _make_ticket(self, *, status=TicketStatus.OPEN, customer=None,
                     building=None, company=None):
        return Ticket.objects.create(
            company=company or self.company,
            building=building or self.building,
            customer=customer or self.customer,
            created_by=self.cust_user,
            title="Original melding",
            description="Customer reported an issue",
            status=status,
        )

    def _svc_line(self, service, *, qty="2.00"):
        return {
            "service": service.id,
            "quantity": qty,
            "requested_date": "2026-06-15",
            "customer_note": "",
        }

    def _adhoc_line(self, *, qty="2.00"):
        return {
            "custom_description": "Free-text special task",
            "quantity": qty,
            "requested_date": "2026-06-15",
            "customer_note": "",
        }

    def _convert(self, *, actor, ticket, intent, lines):
        return self._api(actor).post(
            CONVERT_URL.format(ticket_id=ticket.id),
            {"request_intent": intent, "line_items": lines},
            format="json",
        )

    def _ticket_count(self, ew):
        return Ticket.objects.filter(extra_work_request=ew).count()

    def _enter_pricing_and_send(self, ew, *, actor=None):
        """Provider moves the EW to UNDER_REVIEW, auto-seeds a proposal,
        prices any zero-priced line, and SENDs it. Mirrors the Sprint 6B
        helper. Returns (proposal_id, send_response)."""
        actor = actor or self.admin
        api = self._api(actor)

        resp = api.post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.UNDER_REVIEW},
            format="json",
        )
        assert resp.status_code == 200, resp.data

        resp = api.post(
            f"/api/extra-work/{ew.id}/proposals/", {}, format="json"
        )
        assert resp.status_code == 201, resp.data
        proposal_id = resp.data["id"]

        # Add the custom / no-contract cart lines the auto-seed skipped.
        # Auto-seed (2026-06-03 owner decision) only seeds AGREED-priced
        # cart lines; non-contract lines are added by the operator via
        # the composer. Mirror that here so an all-unpriced converted
        # cart still yields a sendable proposal.
        seeded = api.get(
            f"/api/extra-work/{ew.id}/proposals/{proposal_id}/lines/"
        ).data
        seeded_service_ids = {
            line.get("service") for line in seeded if line.get("service")
        }
        for item in ew.line_items.all().order_by("id"):
            if item.service_id and item.service_id in seeded_service_ids:
                continue
            body = {
                "quantity": str(item.quantity),
                "unit_type": item.unit_type,
                "unit_price": "55.00",
                "vat_pct": "21.00",
            }
            if item.service_id:
                body["service"] = item.service_id
            else:
                body["description"] = "Provider-priced custom line"
            add = api.post(
                f"/api/extra-work/{ew.id}/proposals/{proposal_id}/lines/",
                body,
                format="json",
            )
            assert add.status_code == 201, add.data

        lines = api.get(
            f"/api/extra-work/{ew.id}/proposals/{proposal_id}/lines/"
        ).data
        for line in lines:
            if Decimal(str(line["unit_price"])) <= 0:
                body = {"unit_price": "55.00", "vat_pct": "21.00"}
                if not line.get("service") and not (
                    line.get("description") or ""
                ).strip():
                    body["description"] = "Provider-priced custom line"
                patch = api.patch(
                    f"/api/extra-work/{ew.id}/proposals/"
                    f"{proposal_id}/lines/{line['id']}/",
                    body,
                    format="json",
                )
                assert patch.status_code == 200, patch.data

        send = api.post(
            f"/api/extra-work/{ew.id}/proposals/{proposal_id}/transition/",
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        return proposal_id, send


# ---------------------------------------------------------------------------
# 1. DIRECT conversion (all-agreed lines) — INSTANT route.
# ---------------------------------------------------------------------------
class DirectConversionTests(ConvertFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_direct_conversion_spawns_one_ticket_and_supersedes_source(self):
        ticket = self._make_ticket()
        resp = self._convert(
            actor=self.admin,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.service_agreed)],
        )
        self.assertEqual(resp.status_code, 201, resp.data)

        ticket.refresh_from_db()
        self.assertEqual(
            ticket.status, TicketStatus.CONVERTED_TO_EXTRA_WORK
        )
        self.assertEqual(
            resp.data["source_ticket"]["status"],
            TicketStatus.CONVERTED_TO_EXTRA_WORK,
        )

        ew = ExtraWorkRequest.objects.get(
            id=resp.data["extra_work_request"]["id"]
        )
        self.assertEqual(ew.source_ticket_id, ticket.id)
        self.assertEqual(
            ew.routing_decision, ExtraWorkRoutingDecision.INSTANT
        )

        # Exactly one operational ticket spawned, and it is NOT the source.
        spawned = Ticket.objects.filter(extra_work_request=ew)
        self.assertEqual(spawned.count(), 1)
        spawned_ticket = spawned.first()
        self.assertNotEqual(spawned_ticket.id, ticket.id)
        self.assertEqual(
            resp.data["operational_ticket_ids"], [spawned_ticket.id]
        )

    def test_super_admin_and_bm_can_convert(self):
        for actor in (self.super_admin, self.bm):
            ticket = self._make_ticket()
            resp = self._convert(
                actor=actor,
                ticket=ticket,
                intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
                lines=[self._svc_line(self.service_agreed)],
            )
            self.assertEqual(resp.status_code, 201, resp.data)


# ---------------------------------------------------------------------------
# 2. REQUEST_QUOTE conversion — PROPOSAL route, customer decides.
# ---------------------------------------------------------------------------
class RequestQuoteConversionTests(ConvertFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_request_quote_conversion_customer_accept_spawns_one(self):
        ticket = self._make_ticket()
        resp = self._convert(
            actor=self.admin,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
            lines=[self._svc_line(self.service_unpriced)],
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        ticket.refresh_from_db()
        self.assertEqual(
            ticket.status, TicketStatus.CONVERTED_TO_EXTRA_WORK
        )

        ew = ExtraWorkRequest.objects.get(
            id=resp.data["extra_work_request"]["id"]
        )
        self.assertEqual(
            ew.routing_decision, ExtraWorkRoutingDecision.PROPOSAL
        )
        # No operational ticket at conversion.
        self.assertEqual(self._ticket_count(ew), 0)
        self.assertEqual(resp.data["operational_ticket_ids"], [])

        # Provider builds + sends proposal — still 0.
        proposal_id, send = self._enter_pricing_and_send(ew)
        self.assertEqual(send.status_code, 200, send.data)
        self.assertEqual(send.data["status"], ProposalStatus.SENT)
        self.assertEqual(self._ticket_count(ew), 0)

        # Customer accepts -> exactly one.
        approve = self._api(self.cust_loc).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal_id}/transition/",
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(approve.status_code, 200, approve.data)
        self.assertEqual(self._ticket_count(ew), 1)

    def test_request_quote_conversion_customer_reject_spawns_zero(self):
        ticket = self._make_ticket()
        resp = self._convert(
            actor=self.admin,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
            lines=[self._svc_line(self.service_unpriced)],
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        ew = ExtraWorkRequest.objects.get(
            id=resp.data["extra_work_request"]["id"]
        )
        proposal_id, send = self._enter_pricing_and_send(ew)
        self.assertEqual(send.status_code, 200, send.data)

        reject = self._api(self.cust_loc).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal_id}/transition/",
            {
                "to_status": ProposalStatus.CUSTOMER_REJECTED,
                "customer_reject_reason": "not needed",
            },
            format="json",
        )
        self.assertEqual(reject.status_code, 200, reject.data)
        self.assertEqual(self._ticket_count(ew), 0)


# ---------------------------------------------------------------------------
# 3. AUTO_START conversion — PROPOSAL route, provider send spawns one.
# ---------------------------------------------------------------------------
class AutoStartConversionTests(ConvertFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_auto_start_conversion_spawns_one_on_send(self):
        ticket = self._make_ticket()
        resp = self._convert(
            actor=self.admin,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
            lines=[self._svc_line(self.service_unpriced)],
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        ew = ExtraWorkRequest.objects.get(
            id=resp.data["extra_work_request"]["id"]
        )
        self.assertEqual(
            ew.routing_decision, ExtraWorkRoutingDecision.PROPOSAL
        )
        self.assertEqual(self._ticket_count(ew), 0)

        _pid, send = self._enter_pricing_and_send(ew)
        self.assertEqual(send.status_code, 200, send.data)
        self.assertEqual(self._ticket_count(ew), 1)


# ---------------------------------------------------------------------------
# 4. Source leaves operational queues (stats / by-building).
# ---------------------------------------------------------------------------
class SourceLeavesQueuesTests(ConvertFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_converted_source_not_counted_open_in_stats(self):
        ticket = self._make_ticket()

        before = self._api(self.admin).get("/api/tickets/stats/")
        self.assertEqual(before.status_code, 200)
        open_before = before.data["my_open"]
        self.assertGreaterEqual(open_before, 1)  # the source counts as open

        resp = self._convert(
            actor=self.admin,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
            lines=[self._svc_line(self.service_unpriced)],
        )
        self.assertEqual(resp.status_code, 201, resp.data)

        after = self._api(self.admin).get("/api/tickets/stats/")
        self.assertEqual(after.status_code, 200)
        # The source leaves the open queue (terminal CONVERTED) and the
        # PROPOSAL route spawns no operational ticket, so my_open drops
        # by exactly one.
        self.assertEqual(after.data["my_open"], open_before - 1)
        self.assertNotIn(
            TicketStatus.CONVERTED_TO_EXTRA_WORK,
            {
                s
                for s, c in after.data["by_status"].items()
                if s
                in {"OPEN", "IN_PROGRESS", "REOPENED_BY_ADMIN"}
            },
        )

    def test_converted_source_not_counted_open_by_building(self):
        ticket = self._make_ticket()
        self._convert(
            actor=self.admin,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
            lines=[self._svc_line(self.service_unpriced)],
        )
        resp = self._api(self.admin).get("/api/tickets/stats/by-building/")
        self.assertEqual(resp.status_code, 200)
        rows = {r["building_id"]: r for r in resp.data}
        row = rows.get(self.building.id)
        self.assertIsNotNone(row)
        # The converted source contributes neither to open nor in_progress.
        self.assertEqual(row["open"], 0)
        self.assertEqual(row["in_progress"], 0)


# ---------------------------------------------------------------------------
# 5. Idempotency — re-convert a converted ticket is rejected.
# ---------------------------------------------------------------------------
class IdempotencyTests(ConvertFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_reconvert_already_converted_is_rejected(self):
        ticket = self._make_ticket()
        first = self._convert(
            actor=self.admin,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.service_agreed)],
        )
        self.assertEqual(first.status_code, 201, first.data)
        ew_count_after_first = ExtraWorkRequest.objects.filter(
            source_ticket=ticket
        ).count()
        op_count_after_first = Ticket.objects.filter(
            extra_work_request__source_ticket=ticket
        ).count()

        second = self._convert(
            actor=self.admin,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.service_agreed)],
        )
        self.assertEqual(second.status_code, 400, second.data)
        self.assertEqual(second.data["code"], "ticket_already_converted")

        # No 2nd EW and no duplicate operational ticket.
        self.assertEqual(
            ExtraWorkRequest.objects.filter(source_ticket=ticket).count(),
            ew_count_after_first,
        )
        self.assertEqual(
            Ticket.objects.filter(
                extra_work_request__source_ticket=ticket
            ).count(),
            op_count_after_first,
        )

    def test_not_convertible_status_rejected(self):
        ticket = self._make_ticket(status=TicketStatus.APPROVED)
        resp = self._convert(
            actor=self.admin,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.service_agreed)],
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data["code"], "ticket_not_convertible")


# ---------------------------------------------------------------------------
# 6. Permissions — role + scope gates.
# ---------------------------------------------------------------------------
class PermissionTests(ConvertFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_staff_forbidden_for_role(self):
        ticket = self._make_ticket()
        resp = self._convert(
            actor=self.staff,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.service_agreed)],
        )
        self.assertEqual(resp.status_code, 403, resp.data)
        self.assertEqual(resp.data["code"], "conversion_forbidden_for_role")

    def test_customer_user_forbidden_for_role(self):
        ticket = self._make_ticket()
        resp = self._convert(
            actor=self.cust_user,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.service_agreed)],
        )
        # Role gate fires before the object lookup -> stable 403.
        self.assertEqual(resp.status_code, 403, resp.data)
        self.assertEqual(resp.data["code"], "conversion_forbidden_for_role")

    def test_company_admin_out_of_scope_other_company(self):
        ticket = self._make_ticket()
        resp = self._convert(
            actor=self.other_admin,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.service_agreed)],
        )
        # Out-of-company ticket is out of scope -> 404 at get_object().
        self.assertEqual(resp.status_code, 404, resp.data)

    def test_building_manager_unassigned_building_forbidden_scope(self):
        ticket = self._make_ticket()
        resp = self._convert(
            actor=self.bm_unassigned,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.service_agreed)],
        )
        # The BM is in the company (so the ticket may be visible) but not
        # assigned to the building. The scope gate yields 403; if the
        # scoping helper hides the ticket entirely it is 404. Either is a
        # valid block — assert the conversion did NOT happen.
        self.assertIn(resp.status_code, (403, 404), resp.data)
        ticket.refresh_from_db()
        self.assertNotEqual(
            ticket.status, TicketStatus.CONVERTED_TO_EXTRA_WORK
        )


# ---------------------------------------------------------------------------
# 7. Provider REQUEST_QUOTE exception is conversion-only.
# ---------------------------------------------------------------------------
class ProviderRequestQuoteExceptionTests(ConvertFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_conversion_allows_provider_request_quote(self):
        ticket = self._make_ticket()
        resp = self._convert(
            actor=self.admin,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
            lines=[self._svc_line(self.service_unpriced)],
        )
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_normal_provider_create_still_rejects_request_quote(self):
        resp = self._api(self.admin).post(
            "/api/extra-work/",
            {
                "customer": self.customer.id,
                "building": self.building.id,
                "title": "Provider EW",
                "description": "should be rejected",
                "category": "DEEP_CLEANING",
                "request_intent": ExtraWorkRequestIntent.REQUEST_QUOTE,
                "line_items": [self._svc_line(self.service_unpriced)],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        codes = [
            getattr(e, "code", None)
            for e in resp.data.get("request_intent", [])
        ]
        self.assertIn("intent_forbidden_for_provider", codes)


# ---------------------------------------------------------------------------
# 8. Audit / history rows + no attachment/message duplication.
# ---------------------------------------------------------------------------
class HistoryAndNoDuplicationTests(ConvertFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_history_rows_and_no_copy_of_attachments_or_messages(self):
        ticket = self._make_ticket()

        # Seed an attachment + a message on the source BEFORE conversion.
        msg = TicketMessage.objects.create(
            ticket=ticket,
            author=self.cust_user,
            message="customer note",
        )
        TicketAttachment.objects.create(
            ticket=ticket,
            message=msg,
            uploaded_by=self.cust_user,
            file=SimpleUploadedFile("a.txt", b"data"),
            original_filename="a.txt",
            mime_type="text/plain",
            file_size=4,
        )
        msg_count_before = TicketMessage.objects.filter(ticket=ticket).count()
        att_count_before = TicketAttachment.objects.filter(
            ticket=ticket
        ).count()

        resp = self._convert(
            actor=self.admin,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.service_agreed)],
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        ew = ExtraWorkRequest.objects.get(
            id=resp.data["extra_work_request"]["id"]
        )

        # Source TicketStatusHistory carries old->CONVERTED with EW id.
        conv_row = TicketStatusHistory.objects.filter(
            ticket=ticket,
            new_status=TicketStatus.CONVERTED_TO_EXTRA_WORK,
        ).first()
        self.assertIsNotNone(conv_row)
        self.assertEqual(conv_row.old_status, TicketStatus.OPEN)
        self.assertIn(str(ew.id), conv_row.note)
        self.assertFalse(conv_row.is_override)

        # EW-side ExtraWorkStatusHistory mentions the source ticket.
        ew_row = ExtraWorkStatusHistory.objects.filter(
            extra_work=ew, new_status=ExtraWorkStatus.REQUESTED
        ).first()
        self.assertIsNotNone(ew_row)
        self.assertIn(
            str(ticket.ticket_no or ticket.id), ew_row.note
        )

        # Source attachments/messages unchanged; EW carries none copied.
        self.assertEqual(
            TicketMessage.objects.filter(ticket=ticket).count(),
            msg_count_before,
        )
        self.assertEqual(
            TicketAttachment.objects.filter(ticket=ticket).count(),
            att_count_before,
        )
        # The spawned operational ticket is independent (no copied
        # attachments / messages from the source).
        spawned = Ticket.objects.get(extra_work_request=ew)
        self.assertEqual(
            TicketAttachment.objects.filter(ticket=spawned).count(), 0
        )
        self.assertEqual(
            TicketMessage.objects.filter(ticket=spawned).count(), 0
        )


# ---------------------------------------------------------------------------
# 9. Extra Work origin linkage on the spawned ticket + back-link.
# ---------------------------------------------------------------------------
class ExtraWorkOriginLinkTests(ConvertFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_spawned_ticket_origin_and_source_back_link(self):
        ticket = self._make_ticket()
        resp = self._convert(
            actor=self.admin,
            ticket=ticket,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.service_agreed)],
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        ew = ExtraWorkRequest.objects.get(
            id=resp.data["extra_work_request"]["id"]
        )
        spawned = Ticket.objects.get(extra_work_request=ew)

        detail = self._api(self.super_admin).get(
            f"/api/tickets/{spawned.id}/"
        )
        self.assertEqual(detail.status_code, 200, detail.data)
        origin = detail.data.get("extra_work_origin")
        self.assertIsNotNone(origin)
        self.assertEqual(origin["extra_work_request_id"], ew.id)

        # EW links back to the original ticket.
        ew.refresh_from_db()
        self.assertEqual(ew.source_ticket_id, ticket.id)
