from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import TicketMessage, TicketMessageType


class TicketScopingTests(TenantFixtureMixin, APITestCase):
    def test_super_admin_sees_all_tickets(self):
        self.authenticate(self.super_admin)
        response = self.client.get("/api/tickets/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(response), {self.ticket.id, self.other_ticket.id})

    def test_company_admin_only_sees_own_company_tickets(self):
        self.authenticate(self.company_admin)
        response = self.client.get("/api/tickets/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(response), {self.ticket.id})

    def test_building_manager_only_sees_assigned_building_tickets(self):
        self.authenticate(self.manager)
        response = self.client.get("/api/tickets/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(response), {self.ticket.id})

    def test_customer_user_only_sees_linked_customer_tickets(self):
        self.authenticate(self.customer_user)
        response = self.client.get("/api/tickets/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(response), {self.ticket.id})

    def test_cross_company_ticket_detail_is_not_visible(self):
        self.authenticate(self.company_admin)
        response = self.client.get(f"/api/tickets/{self.other_ticket.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_customer_cannot_view_internal_notes(self):
        TicketMessage.objects.create(
            ticket=self.ticket,
            author=self.manager,
            message="internal",
            message_type=TicketMessageType.INTERNAL_NOTE,
            is_hidden=True,
        )
        TicketMessage.objects.create(
            ticket=self.ticket,
            author=self.customer_user,
            message="public",
            message_type=TicketMessageType.PUBLIC_REPLY,
            is_hidden=False,
        )

        self.authenticate(self.customer_user)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/messages/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        messages = response.data.get("results", response.data)
        self.assertEqual([item["message"] for item in messages], ["public"])

    def test_out_of_scope_messages_are_404(self):
        self.authenticate(self.customer_user)
        response = self.client.get(f"/api/tickets/{self.other_ticket.id}/messages/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_customer_search_does_not_match_description_words(self):
        # Two tickets exist for the customer's company. A second ticket in
        # the customer's scope contains a unique word in its description.
        from tickets.models import Ticket

        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Routine cleaning",
            description="bluepenguin reference word",
        )

        self.authenticate(self.customer_user)
        response = self.client.get("/api/tickets/", {"search": "bluepenguin"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Customer must not be able to substring-search the description.
        results = response.data.get("results", response.data)
        self.assertEqual(results, [])

    def test_staff_search_still_matches_description_words(self):
        from tickets.models import Ticket

        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Routine cleaning",
            description="bluepenguin reference word",
        )

        self.authenticate(self.manager)
        response = self.client.get("/api/tickets/", {"search": "bluepenguin"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)

    # Sprint 9 — defence-in-depth: deleting a membership / assignment
    # row must immediately remove the de-scoped user's visibility into
    # the affected tickets. The earlier suite proves the membership
    # row is gone; these tests prove the *security consequence* —
    # if scope_tickets_for is ever rewritten against a denormalised
    # field, these tests catch the regression.

    def test_company_admin_loses_ticket_visibility_after_membership_delete(self):
        from companies.models import CompanyUserMembership

        self.authenticate(self.company_admin)
        before = self.client.get("/api/tickets/")
        self.assertEqual(before.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(before), {self.ticket.id})

        CompanyUserMembership.objects.filter(
            user=self.company_admin, company=self.company
        ).delete()

        after = self.client.get("/api/tickets/")
        self.assertEqual(after.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(after), set())

    def test_building_manager_loses_ticket_visibility_after_assignment_delete(self):
        from buildings.models import BuildingManagerAssignment

        self.authenticate(self.manager)
        before = self.client.get("/api/tickets/")
        self.assertEqual(self.response_ids(before), {self.ticket.id})

        BuildingManagerAssignment.objects.filter(
            user=self.manager, building=self.building
        ).delete()

        after = self.client.get("/api/tickets/")
        self.assertEqual(after.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(after), set())

    def test_customer_user_loses_ticket_visibility_after_membership_delete(self):
        from customers.models import CustomerUserMembership

        self.authenticate(self.customer_user)
        before = self.client.get("/api/tickets/")
        self.assertEqual(self.response_ids(before), {self.ticket.id})

        CustomerUserMembership.objects.filter(
            user=self.customer_user, customer=self.customer
        ).delete()

        after = self.client.get("/api/tickets/")
        self.assertEqual(after.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(after), set())

    # Sprint 9 — the view forces message_type=PUBLIC_REPLY for non-staff
    # at perform_create, which masks the serializer-level rejection. This
    # test pins the serializer-level guard so a future refactor that
    # removes the view-side override does not silently allow customers
    # to post internal notes.
    def test_customer_cannot_post_internal_note_message_type(self):
        from tickets.models import TicketMessage, TicketMessageType

        self.authenticate(self.customer_user)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/messages/",
            {
                "message": "secret",
                "message_type": TicketMessageType.INTERNAL_NOTE,
            },
            format="json",
        )

        # Either the serializer rejects with 400 (preferred), or the
        # view normalises to PUBLIC_REPLY. EITHER WAY, no internal
        # note row may be created from this request.
        self.assertNotIn(response.status_code, (500,))
        self.assertFalse(
            TicketMessage.objects.filter(
                ticket=self.ticket,
                author=self.customer_user,
                message_type=TicketMessageType.INTERNAL_NOTE,
            ).exists()
        )
