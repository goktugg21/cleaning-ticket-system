"""
Sprint 2.2 audit-log infrastructure tests.

Coverage matrix:
- Diff engine respects sensitive-field redaction (password etc.).
- API mutations on Company / Building / Customer / User produce audit
  rows with the correct actor, action, target_model, target_id.
- The /api/audit-logs/ endpoint is super-admin-only with working
  filters and no detail/write routes.
- A failure inside the audit pipeline never propagates to the API
  caller (the original mutation still succeeds).
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from audit.models import AuditAction, AuditLog
from buildings.models import Building
from companies.models import Company
from customers.models import Customer
from test_utils import TenantFixtureMixin


class AuditLogBaseTest(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # Drop the rows the fixture's create() calls just produced so each
        # test starts from a clean slate. The signals are still wired.
        AuditLog.objects.all().delete()


class AuditCompanyMutationTests(AuditLogBaseTest):
    URL = "/api/companies/"

    def test_company_create_via_api_writes_create_audit_log(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.URL,
            {"name": "Acme Inc"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        logs = AuditLog.objects.filter(target_model="companies.Company")
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.action, AuditAction.CREATE)
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.target_id, response.data["id"])
        self.assertIn("name", log.changes)
        self.assertEqual(log.changes["name"]["after"], "Acme Inc")
        self.assertIsNone(log.changes["name"]["before"])

    def test_company_update_via_api_writes_update_audit_log(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            f"{self.URL}{self.company.id}/",
            {"name": "Renamed Company"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        log = AuditLog.objects.filter(
            target_model="companies.Company",
            target_id=self.company.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        # Only the changed field is in the diff. slug/default_language
        # were untouched and must not appear.
        self.assertEqual(set(log.changes.keys()), {"name"})
        self.assertEqual(log.changes["name"]["before"], "Company A")
        self.assertEqual(log.changes["name"]["after"], "Renamed Company")

    def test_company_delete_via_api_soft_deletes_and_records_update_log(self):
        # CompanyViewSet.perform_destroy soft-deletes by flipping
        # is_active=False (rows are kept so historical tickets stay
        # attached). The audit row is therefore an UPDATE that captures
        # the is_active flip — there is no hard DELETE through the API.
        self.authenticate(self.super_admin)
        response = self.client.delete(f"{self.URL}{self.company.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        log = AuditLog.objects.filter(
            target_model="companies.Company",
            target_id=self.company.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.changes["is_active"]["before"], True)
        self.assertEqual(log.changes["is_active"]["after"], False)

    def test_company_hard_delete_writes_delete_audit_log(self):
        # The API path is soft-delete (see test above), but the audit
        # signal stack must still produce DELETE rows when the ORM
        # actually removes a row — e.g. a management command or a
        # manual cleanup. Exercise the post_delete handler directly.
        target = Company.objects.create(name="Ephemeral", slug="ephemeral")
        target_id = target.id
        AuditLog.objects.all().delete()  # drop the CREATE row above

        target.delete()

        log = AuditLog.objects.filter(
            target_model="companies.Company",
            target_id=target_id,
            action=AuditAction.DELETE,
        ).get()
        self.assertEqual(log.changes["name"]["before"], "Ephemeral")
        self.assertIsNone(log.changes["name"]["after"])


class AuditBuildingMutationTests(AuditLogBaseTest):
    URL_TMPL = "/api/buildings/{id}/"

    def test_building_update_via_api_writes_update_audit_log(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.URL_TMPL.format(id=self.building.id),
            {"city": "Amsterdam"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        log = AuditLog.objects.filter(
            target_model="buildings.Building",
            target_id=self.building.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.changes["city"]["before"], "")
        self.assertEqual(log.changes["city"]["after"], "Amsterdam")


class AuditCustomerMutationTests(AuditLogBaseTest):
    URL_TMPL = "/api/customers/{id}/"

    def test_customer_update_via_api_writes_update_audit_log(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.URL_TMPL.format(id=self.customer.id),
            {"phone": "+31201234567"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        log = AuditLog.objects.filter(
            target_model="customers.Customer",
            target_id=self.customer.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.changes["phone"]["before"], "")
        self.assertEqual(log.changes["phone"]["after"], "+31201234567")


class AuditUserMutationTests(AuditLogBaseTest):
    URL_TMPL = "/api/users/{id}/"

    def test_user_create_via_orm_writes_create_audit_log_no_password_in_changes(self):
        # The User API does not expose POST (users come in via the
        # invitation flow, which itself calls create_user). We exercise
        # the signal directly. actor will be None because the call is
        # outside an HTTP request — that is the documented "system
        # write" behavior.
        get_user_model().objects.create_user(
            email="brand-new@example.com",
            password=self.password,
            role=UserRole.CUSTOMER_USER,
        )

        log = AuditLog.objects.filter(target_model="accounts.User").get()
        self.assertEqual(log.action, AuditAction.CREATE)
        # Sensitive-field redaction: no password / hash / token columns
        # may appear in the diff, ever.
        forbidden_substrings = ("password", "token", "secret", "hash", "otp", "mfa")
        for key in log.changes:
            lowered = key.lower()
            for forbidden in forbidden_substrings:
                self.assertNotIn(
                    forbidden,
                    lowered,
                    f"Sensitive field {key!r} leaked into audit changes",
                )
        # And the auditable fields we DO want must be present.
        self.assertEqual(log.changes["email"]["after"], "brand-new@example.com")
        self.assertEqual(log.changes["role"]["after"], UserRole.CUSTOMER_USER)

    def test_user_update_via_api_writes_update_audit_log_with_actor(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.URL_TMPL.format(id=self.customer_user.id),
            {"full_name": "Customer Renamed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        log = AuditLog.objects.filter(
            target_model="accounts.User",
            target_id=self.customer_user.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(set(log.changes.keys()), {"full_name"})
        self.assertEqual(log.changes["full_name"]["before"], "customer-a")
        self.assertEqual(log.changes["full_name"]["after"], "Customer Renamed")

    def test_user_delete_via_api_soft_deletes_and_records_update_log(self):
        # The user API performs a soft delete (perform_destroy ->
        # instance.soft_delete which flips is_active and stamps
        # deleted_at). Because the row is updated rather than removed,
        # the audit row is an UPDATE that captures the flip.
        self.authenticate(self.super_admin)
        response = self.client.delete(self.URL_TMPL.format(id=self.customer_user.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        log = AuditLog.objects.filter(
            target_model="accounts.User",
            target_id=self.customer_user.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.changes["is_active"]["before"], True)
        self.assertEqual(log.changes["is_active"]["after"], False)
        # deleted_at flipped from None -> ISO timestamp string
        self.assertIsNone(log.changes["deleted_at"]["before"])
        self.assertIsInstance(log.changes["deleted_at"]["after"], str)


class AuditAPIPermissionTests(AuditLogBaseTest):
    URL = "/api/audit-logs/"

    def _seed_one_log(self):
        self.authenticate(self.super_admin)
        self.client.patch(
            f"/api/companies/{self.company.id}/",
            {"name": "Renamed for filter"},
            format="json",
        )
        # Re-clear test client auth so the next request starts fresh
        self.client.force_authenticate(user=None)

    def test_company_admin_cannot_list_audit_logs(self):
        self._seed_one_log()
        self.authenticate(self.company_admin)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_caller_cannot_list_audit_logs(self):
        self._seed_one_log()
        response = self.client.get(self.URL)
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_audit_endpoint_has_no_detail_route(self):
        self._seed_one_log()
        log = AuditLog.objects.first()
        self.assertIsNotNone(log)
        self.authenticate(self.super_admin)
        response = self.client.get(f"{self.URL}{log.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class AuditAPIListAndFilterTests(AuditLogBaseTest):
    URL = "/api/audit-logs/"

    def test_super_admin_lists_and_filters_audit_logs(self):
        # Generate three audit rows on different targets / models.
        self.authenticate(self.super_admin)
        self.client.patch(
            f"/api/companies/{self.company.id}/",
            {"name": "Filter Co"},
            format="json",
        )
        self.client.patch(
            f"/api/buildings/{self.building.id}/",
            {"city": "Rotterdam"},
            format="json",
        )
        self.client.patch(
            f"/api/users/{self.customer_user.id}/",
            {"full_name": "Filter User"},
            format="json",
        )

        # Plain list: 3 rows, newest first.
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 3)
        # Strictly descending created_at on the page.
        timestamps = [row["created_at"] for row in response.data["results"]]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

        # target_model + target_id filter narrows to the company row.
        response = self.client.get(
            self.URL,
            {"target_model": "companies.Company", "target_id": self.company.id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["target_model"], "companies.Company")

        # actor filter narrows to logs by super_admin (all of them).
        response = self.client.get(self.URL, {"actor": self.super_admin.id})
        self.assertEqual(len(response.data["results"]), 3)

        # actor filter for a different user returns nothing.
        response = self.client.get(self.URL, {"actor": self.company_admin.id})
        self.assertEqual(len(response.data["results"]), 0)

        # date_from in the future returns nothing.
        future = (timezone.now() + timedelta(days=1)).isoformat()
        response = self.client.get(self.URL, {"date_from": future})
        self.assertEqual(len(response.data["results"]), 0)

        # date_to in the past returns nothing.
        past = (timezone.now() - timedelta(days=1)).isoformat()
        response = self.client.get(self.URL, {"date_to": past})
        self.assertEqual(len(response.data["results"]), 0)

        # Both bounds straddling now return all 3.
        response = self.client.get(
            self.URL,
            {"date_from": past, "date_to": (timezone.now() + timedelta(days=1)).isoformat()},
        )
        self.assertEqual(len(response.data["results"]), 3)

    def test_audit_serializer_exposes_actor_email_and_request_metadata(self):
        self.authenticate(self.super_admin)
        self.client.patch(
            f"/api/companies/{self.company.id}/",
            {"name": "Serializer Co"},
            format="json",
            HTTP_X_REQUEST_ID="req-abc-123",
            HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1",
        )
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = response.data["results"][0]
        self.assertEqual(row["actor_email"], self.super_admin.email)
        self.assertEqual(row["request_id"], "req-abc-123")
        self.assertEqual(row["request_ip"], "203.0.113.7")


class AuditNonBlockingTests(AuditLogBaseTest):
    """A failure inside the audit pipeline must never bubble up to the API."""

    def test_audit_failure_does_not_block_mutation(self):
        original_create = AuditLog.objects.create

        def boom(*args, **kwargs):
            raise RuntimeError("simulated audit-log write failure")

        with patch.object(AuditLog.objects, "create", side_effect=boom) as mocked:
            self.authenticate(self.super_admin)
            response = self.client.patch(
                f"/api/companies/{self.company.id}/",
                {"name": "Should-still-rename"},
                format="json",
            )
            # The original mutation still succeeds — the audit failure
            # was swallowed and logged.
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.company.refresh_from_db()
            self.assertEqual(self.company.name, "Should-still-rename")
            self.assertTrue(mocked.called)

        # And once the patch is gone, follow-up writes audit normally —
        # we have not corrupted any signal connections.
        AuditLog.objects.create = original_create
        self.client.patch(
            f"/api/companies/{self.company.id}/",
            {"name": "Renamed-again"},
            format="json",
        )
        self.assertTrue(
            AuditLog.objects.filter(target_id=self.company.id).exists(),
            "Audit logging must resume after a transient failure",
        )
