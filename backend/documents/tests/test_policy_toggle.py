"""Sprint 126 — the company-wide Documents policy toggle
(`CustomerCompanyPolicy.customer_users_can_manage_documents`) binds
`customer.documents.manage`.

Default True keeps the Sprint-125 behaviour (customer users manage documents
by role default). Setting it False denies the whole customer-side surface —
for an ordinary member AND for a company-wide CCA — so every documents
endpoint 404s for them, exactly like the other policy families.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from customers.models import (
    CustomerCompanyPolicy,
    CustomerUserMembership,
)
from test_utils import TenantFixtureMixin

from ._helpers import folders_url


class DocumentsPolicyToggleTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # A company-wide CCA of self.customer (no per-building rows needed).
        self.cca = self.make_user("cca-pol@example.com", "CUSTOMER_USER")
        CustomerUserMembership.objects.create(
            user=self.cca, customer=self.customer, is_company_admin=True
        )
        self.policy = CustomerCompanyPolicy.objects.get(customer=self.customer)

    def test_default_true_grants_member_and_cca(self):
        for actor in (self.customer_user, self.cca):
            self.authenticate(actor)
            self.assertEqual(
                self.client.get(folders_url(self.customer.id)).status_code,
                status.HTTP_200_OK,
            )

    def test_policy_false_denies_member(self):
        self.policy.customer_users_can_manage_documents = False
        self.policy.save(update_fields=["customer_users_can_manage_documents"])
        self.authenticate(self.customer_user)
        self.assertEqual(
            self.client.get(folders_url(self.customer.id)).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_policy_false_denies_company_wide_cca(self):
        # The company-level policy is the ONLY layer that can narrow a CCA.
        self.policy.customer_users_can_manage_documents = False
        self.policy.save(update_fields=["customer_users_can_manage_documents"])
        self.authenticate(self.cca)
        self.assertEqual(
            self.client.get(folders_url(self.customer.id)).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_me_reflects_documents_access(self):
        # The customer sidebar gate reads /auth/me/.can_manage_documents
        # (the provider-only effective-permissions endpoint 403s a customer).
        self.authenticate(self.customer_user)
        self.assertTrue(
            self.client.get("/api/auth/me/").data["can_manage_documents"]
        )
        # Turning the module off flips the signal.
        self.policy.customer_users_can_manage_documents = False
        self.policy.save(update_fields=["customer_users_can_manage_documents"])
        self.assertFalse(
            self.client.get("/api/auth/me/").data["can_manage_documents"]
        )

    def test_me_false_for_provider_role(self):
        self.authenticate(self.company_admin)
        self.assertFalse(
            self.client.get("/api/auth/me/").data["can_manage_documents"]
        )

    def test_provider_unaffected_by_policy(self):
        # The policy narrows customer users only — a provider admin still
        # reaches the documents surface regardless.
        self.policy.customer_users_can_manage_documents = False
        self.policy.save(update_fields=["customer_users_can_manage_documents"])
        self.authenticate(self.company_admin)
        self.assertEqual(
            self.client.get(folders_url(self.customer.id)).status_code,
            status.HTTP_200_OK,
        )
