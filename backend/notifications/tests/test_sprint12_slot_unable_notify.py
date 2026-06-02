"""Sprint 12 — a staff member reporting a dated SLOT as unable-to-complete
notifies the provider/manager side so they can reschedule / reassign.

The slot PATCH (slot_status=UNABLE_TO_COMPLETE) does NOT change ticket
status, so the existing status-change email never fires; this dedicated
TICKET_SLOT_UNABLE email is the only manager signal. Customers are never
notified (provider-internal operational follow-up), mirroring the
ticket-level unable / manager-review recipient rule.
"""
from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
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
from notifications.models import NotificationEventType, NotificationLog
from tickets.models import (
    StaffAssignmentSlotStatus,
    Ticket,
    TicketStaffAssignment,
    TicketStatus,
)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
)
class SlotUnableNotifyTests(TestCase):
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

        cls.company = Company.objects.create(name="Co A", slug="co-a-s12")
        cls.building = Building.objects.create(
            company=cls.company, name="Building S12", address="Street 1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            building=cls.building,
            name="Customer S12",
            contact_email="cust-s12@example.com",
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.company_admin = mk("admin-s12@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.company_admin, company=cls.company
        )

        cls.manager = mk("mgr-s12@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager, building=cls.building
        )

        cls.staff = mk("staff-s12@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )

        cls.customer_user = mk("cust-user-s12@example.com", UserRole.CUSTOMER_USER)
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
            title="Ticket S12",
            description="Scoped ticket S12",
        )

    def setUp(self):
        self.slot = TicketStaffAssignment.objects.create(
            ticket=self.ticket,
            user=self.staff,
            assigned_by=self.company_admin,
            scheduled_start_at=timezone.make_aware(
                datetime.datetime(2026, 6, 10, 9, 0)
            ),
            time_window_label="ochtend",
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _patch_slot(self, user, **body):
        return self._api(user).patch(
            f"/api/tickets/{self.ticket.id}/staff-assignments/{self.staff.id}/",
            body,
            format="json",
        )

    def _unable_logs(self):
        return NotificationLog.objects.filter(
            ticket=self.ticket,
            event_type=NotificationEventType.TICKET_SLOT_UNABLE,
        )

    def test_slot_unable_notifies_managers_not_customer(self):
        resp = self._patch_slot(
            self.staff,
            slot_status=StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE,
            unable_to_complete_reason="Deur op slot, geen sleutel.",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        recipients = set(self._unable_logs().values_list("recipient_email", flat=True))
        # Provider/manager side notified.
        self.assertIn(self.company_admin.email, recipients)
        self.assertIn(self.manager.email, recipients)
        # Customer never notified.
        self.assertNotIn(self.customer_user.email, recipients)

        # Reason + window appear in the body.
        body = self._unable_logs().first().body
        self.assertIn("Deur op slot, geen sleutel.", body)
        self.assertIn("ochtend", body)

    def test_slot_complete_does_not_send_unable_email(self):
        resp = self._patch_slot(
            self.staff,
            slot_status=StaffAssignmentSlotStatus.COMPLETED,
            completion_note="Klaar.",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(self._unable_logs().exists())

    def test_re_patch_unable_does_not_double_notify(self):
        first = self._patch_slot(
            self.staff,
            slot_status=StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE,
            unable_to_complete_reason="Eerste poging mislukt.",
        )
        self.assertEqual(first.status_code, 200, first.data)
        count_after_first = self._unable_logs().count()
        self.assertGreater(count_after_first, 0)

        # Re-PATCH while already UNABLE — no new transition, no new emails.
        second = self._patch_slot(
            self.staff,
            slot_status=StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE,
            unable_to_complete_reason="Nog steeds mislukt.",
        )
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(self._unable_logs().count(), count_after_first)

    def test_ticket_unable_endpoint_still_notifies(self):
        # Preserve the existing ticket-level unable flow (Sprint 13B): it
        # still notifies the provider side via the status-change email.
        self.ticket.status = TicketStatus.IN_PROGRESS
        self.ticket.save(update_fields=["status"])
        resp = self._api(self.staff).post(
            f"/api/tickets/{self.ticket.id}/unable-to-complete/",
            {"reason": "Kon niet afronden."},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.WAITING_MANAGER_REVIEW)
        self.assertTrue(
            NotificationLog.objects.filter(
                ticket=self.ticket,
                recipient_email=self.company_admin.email,
            ).exists()
        )
