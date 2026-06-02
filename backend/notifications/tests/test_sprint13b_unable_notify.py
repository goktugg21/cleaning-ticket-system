"""
Sprint 13B — unable-to-complete / manager-review must not email the customer.

WAITING_MANAGER_REVIEW is an internal provider/manager-review state. It is
reached two ways, both staff-side:

  - the STAFF default-completion route (IN_PROGRESS -> WAITING_MANAGER_REVIEW
    via the generic status endpoint), and
  - the unable-to-complete action (POST /api/tickets/<id>/unable-to-complete/).

The customer must never be emailed about it (Ramazan: the unable /
manager-review issue notifies the provider/manager side, not the customer).
This is enforced status-driven in `send_ticket_status_changed_email` so BOTH
callers are covered. Customer-facing decisions
(WAITING_CUSTOMER_APPROVAL / APPROVED / REJECTED) stay customer-facing.

A defensive Dutch label ("Wacht op controle beheerder") guarantees the raw
enum token can never leak into a rendered email subject/body.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from notifications.models import NotificationLog
from notifications.services import send_ticket_status_changed_email
from tickets.models import Ticket, TicketStaffAssignment, TicketStatus
from test_utils import TenantFixtureMixin


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ManagerReviewEmailRecipientTests(TenantFixtureMixin, TestCase):
    """Service-level proof, covering BOTH callers via the shared status guard."""

    def test_manager_review_notifies_provider_side(self):
        logs = send_ticket_status_changed_email(
            self.ticket,
            old_status="IN_PROGRESS",
            new_status="WAITING_MANAGER_REVIEW",
            actor=self.manager,
        )

        recipients = {log.recipient_email for log in logs}
        # The BUILDING_MANAGER of the building and the COMPANY_ADMIN of the
        # company are the provider/manager side. The manager is the actor here
        # (self-excluded), so assert on the company admin.
        self.assertIn(self.company_admin.email, recipients)

    def test_manager_review_does_not_email_customer_user(self):
        logs = send_ticket_status_changed_email(
            self.ticket,
            old_status="IN_PROGRESS",
            new_status="WAITING_MANAGER_REVIEW",
            actor=self.manager,
        )

        recipients = {log.recipient_email for log in logs}
        # The CUSTOMER_USER member of the customer (and creator of the ticket)
        # must NOT receive a manager-review email.
        self.assertNotIn(self.customer_user.email, recipients)

    def test_manager_review_body_uses_dutch_label_not_raw_token(self):
        logs = send_ticket_status_changed_email(
            self.ticket,
            old_status="IN_PROGRESS",
            new_status="WAITING_MANAGER_REVIEW",
            actor=self.manager,
        )

        self.assertTrue(logs)
        for log in logs:
            # The raw enum token must never leak into a rendered email.
            self.assertNotIn("WAITING_MANAGER_REVIEW", log.subject)
            self.assertNotIn("WAITING_MANAGER_REVIEW", log.body)
            # The defensive Dutch label is used instead.
            self.assertIn("Wacht op controle beheerder", log.body)
            # No unable reason is carried in the status-change email.
            self.assertNotIn("UNABLE TO COMPLETE", log.body)

    def test_customer_facing_transition_still_emails_customer(self):
        # Regression guard: a customer-facing decision still reaches the
        # customer. Actor is the company admin (NOT the customer) so the
        # customer is not self-excluded.
        logs = send_ticket_status_changed_email(
            self.ticket,
            old_status="IN_PROGRESS",
            new_status="WAITING_CUSTOMER_APPROVAL",
            actor=self.company_admin,
        )

        recipients = {log.recipient_email for log in logs}
        self.assertIn(self.customer_user.email, recipients)

    def test_approved_transition_still_emails_customer(self):
        logs = send_ticket_status_changed_email(
            self.ticket,
            old_status="WAITING_CUSTOMER_APPROVAL",
            new_status="APPROVED",
            actor=self.company_admin,
        )

        recipients = {log.recipient_email for log in logs}
        self.assertIn(self.customer_user.email, recipients)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class UnableToCompleteEndpointEmailTests(TestCase):
    """End-to-end proof through POST /api/tickets/<id>/unable-to-complete/.

    Self-contained hermetic fixture: one company, one building, one customer
    with a CUSTOMER_USER member, one STAFF member assigned to both the building
    (BuildingStaffVisibility) and the ticket (TicketStaffAssignment), plus a
    BUILDING_MANAGER and COMPANY_ADMIN on the provider side.
    """

    PASSWORD = "StrongerTestPassword123!"

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        def mk(email, role, **extra):
            return User.objects.create_user(
                email=email,
                password=cls.PASSWORD,
                role=role,
                full_name=email.split("@")[0],
                **extra,
            )

        cls.company = Company.objects.create(name="Co A", slug="co-a-13b")
        cls.building = Building.objects.create(
            company=cls.company, name="Building 13B", address="Street 1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            building=cls.building,
            name="Customer 13B",
            contact_email="cust-13b@example.com",
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.company_admin = mk("admin-13b@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.company_admin, company=cls.company
        )

        cls.manager = mk("mgr-13b@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager, building=cls.building
        )

        cls.staff = mk("staff-13b@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )

        cls.customer_user = mk("cust-user-13b@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            user=cls.customer_user, customer=cls.customer
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership, building=cls.building
        )

        cls.ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.customer_user,
            title="Ticket 13B",
            description="Scoped ticket 13B",
        )

    def setUp(self):
        # ticket starts IN_PROGRESS with the staff member assigned, so the
        # unable-to-complete leg (IN_PROGRESS -> WAITING_MANAGER_REVIEW) is
        # valid for the assigned STAFF actor.
        self.ticket.status = TicketStatus.IN_PROGRESS
        self.ticket.save(update_fields=["status"])
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff, assigned_by=self.company_admin
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_unable_to_complete_does_not_email_customer(self):
        client = self._api(self.staff)
        response = client.post(
            f"/api/tickets/{self.ticket.id}/unable-to-complete/",
            {"reason": "Locked out, no key available"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.status, TicketStatus.WAITING_MANAGER_REVIEW
        )

        # No NotificationLog row was created for the customer user.
        self.assertFalse(
            NotificationLog.objects.filter(
                ticket=self.ticket,
                recipient_email=self.customer_user.email,
            ).exists()
        )
        # The provider/manager side WAS notified (company admin at minimum;
        # the manager is also notified, the staff actor is self-excluded).
        self.assertTrue(
            NotificationLog.objects.filter(
                ticket=self.ticket,
                recipient_email=self.company_admin.email,
            ).exists()
        )

    def test_unable_reason_is_redacted_from_customer_status_history(self):
        # Drive the unable-to-complete flow so a [UNABLE TO COMPLETE] note is
        # written on the status-history row by the STAFF actor.
        staff_client = self._api(self.staff)
        unable = staff_client.post(
            f"/api/tickets/{self.ticket.id}/unable-to-complete/",
            {"reason": "Sensitive internal reason"},
            format="json",
        )
        self.assertEqual(unable.status_code, 200, unable.data)

        # The CUSTOMER_USER reading the ticket detail must NOT see the unable
        # reason: the note rides on a STAFF-authored history row and is
        # redacted to "" by the in-app serializer.
        cust_client = self._api(self.customer_user)
        detail = cust_client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(detail.status_code, 200, detail.data)

        for row in detail.data.get("status_history", []):
            self.assertNotIn("Sensitive internal reason", row.get("note") or "")
            self.assertNotIn("UNABLE TO COMPLETE", row.get("note") or "")
