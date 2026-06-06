"""
CCA-rework — single-path CCA + flag-aware effective-role filters +
new server-side filter contract.

Single-path CCA (SoT Addendum A.1): CUSTOMER_COMPANY_ADMIN is a
company-wide membership flag (`CustomerUserMembership.is_company_admin`),
NEVER a per-building `CustomerUserBuildingAccess.access_role`. The only
way to make a CCA is the company-admin flag/endpoint. A per-building CCA
grant (PATCH or POST `access_role=CCA`) is rejected for EVERY actor with
HTTP 400 + stable code `cca_is_company_wide`.

Because a flag-CCA has `is_company_admin=True` and ZERO CUBA rows, the
effective-role filters (`?access_role=`) must be flag-aware:
  * effective CCA  = membership flag OR an active per-building CCA row,
  * effective LM   = an active LM row AND NOT (flag OR CCA row),
  * effective CU   = an active CU row AND NOT (LM/CCA row OR flag).

New filter contract pinned here:
  * GET /customers/<cid>/users/      ?access_role=  ?building_id=
  * GET /customers/<cid>/contacts/   ?building_id=  (?search= is the
    DRF SearchFilter — exercised in test_search below)

No new permission keys. No migration (the flag is the #89 column).
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Contact,
    ContactBuildingLink,
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
CCA = CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
CU = CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER
CLM = CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class _Fixture(TestCase):
    """One provider company + one customer linked to two buildings.

    People:
      * flag_cca   — is_company_admin=True, ZERO CUBA rows.
      * flag_cca_with_leftover — is_company_admin=True AND a leftover
        CUSTOMER_LOCATION_MANAGER row on b1 (the mis-bucketing trap).
      * lm_user    — a CLM row on b1 only.
      * cu_user    — a CUSTOMER_USER row on b2 only.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov RW", slug="prov-rw")
        cls.b1 = Building.objects.create(company=cls.company, name="RW-B1")
        cls.b2 = Building.objects.create(company=cls.company, name="RW-B2")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer RW", building=cls.b1
        )
        for b in (cls.b1, cls.b2):
            CustomerBuildingMembership.objects.create(
                customer=cls.customer, building=b
            )

        cls.super_admin = _mk(
            "sa-rw@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("ca-rw@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        # Flag-CCA — no CUBA rows.
        cls.flag_cca = _mk("flagcca-rw@example.com", UserRole.CUSTOMER_USER)
        cls.flag_cca_mem = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.flag_cca, is_company_admin=True
        )

        # Flag-CCA WITH a leftover lower per-building row.
        cls.flag_cca_leftover = _mk(
            "flagccaleft-rw@example.com", UserRole.CUSTOMER_USER
        )
        cls.flag_cca_leftover_mem = CustomerUserMembership.objects.create(
            customer=cls.customer,
            user=cls.flag_cca_leftover,
            is_company_admin=True,
        )
        CustomerUserBuildingAccess.objects.create(
            membership=cls.flag_cca_leftover_mem,
            building=cls.b1,
            access_role=CLM,
        )

        # Pure LM.
        cls.lm_user = _mk("lm-rw@example.com", UserRole.CUSTOMER_USER)
        cls.lm_mem = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.lm_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=cls.lm_mem, building=cls.b1, access_role=CLM
        )

        # Pure CU on b2 only.
        cls.cu_user = _mk("cu-rw@example.com", UserRole.CUSTOMER_USER)
        cls.cu_mem = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cu_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=cls.cu_mem, building=cls.b2, access_role=CU
        )

    # --- helpers -----------------------------------------------------
    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _users_url(self):
        return f"/api/customers/{self.customer.id}/users/"

    def _employees_url(self):
        return f"/api/customers/{self.customer.id}/employees/"

    def _contacts_url(self):
        return f"/api/customers/{self.customer.id}/contacts/"

    def _access_url(self, user_id, building_id):
        return (
            f"/api/customers/{self.customer.id}/users/{user_id}/"
            f"access/{building_id}/"
        )

    def _user_ids(self, response):
        return {r["user_id"] for r in response.data["results"]}

    def _employee_ids(self, response):
        return {r["id"] for r in response.data["results"]}


# ---------------------------------------------------------------------------
# A1 — single-path CCA: a per-building CCA grant is impossible.
# ---------------------------------------------------------------------------
class SinglePathCcaTests(_Fixture):
    def test_patch_cca_grant_rejected_for_super_admin(self):
        response = self._api(self.super_admin).patch(
            self._access_url(self.cu_user.id, self.b2.id),
            {"access_role": CCA},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data.get("code"), "cca_is_company_wide")

    def test_patch_cca_grant_rejected_for_company_admin(self):
        response = self._api(self.admin).patch(
            self._access_url(self.cu_user.id, self.b2.id),
            {"access_role": CCA},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data.get("code"), "cca_is_company_wide")
        # Row stays at CUSTOMER_USER.
        row = CustomerUserBuildingAccess.objects.get(
            membership=self.cu_mem, building=self.b2
        )
        self.assertEqual(row.access_role, CU)

    def test_post_cca_grant_rejected_for_company_admin(self):
        # POST a NEW access row on b1 with access_role=CCA smuggled.
        response = self._api(self.admin).post(
            f"/api/customers/{self.customer.id}/users/{self.cu_user.id}/access/",
            {"building_id": self.b1.id, "access_role": CCA},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data.get("code"), "cca_is_company_wide")
        # No row materialised on b1.
        self.assertFalse(
            CustomerUserBuildingAccess.objects.filter(
                membership=self.cu_mem, building=self.b1
            ).exists()
        )

    def test_non_cca_grant_still_succeeds(self):
        # The reject is CCA-only — granting LM still works.
        response = self._api(self.admin).patch(
            self._access_url(self.cu_user.id, self.b2.id),
            {"access_role": CLM},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_200_OK, response.data
        )
        self.assertEqual(response.data["access_role"], CLM)


# ---------------------------------------------------------------------------
# A2 — flag-aware ?access_role= on /users/ (A3a) + /employees/ (A2a).
# ---------------------------------------------------------------------------
class UsersAccessRoleFilterTests(_Fixture):
    def test_flag_cca_returned_by_cca_filter(self):
        response = self._api(self.super_admin).get(
            self._users_url(), {"access_role": CCA}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self._user_ids(response)
        self.assertIn(self.flag_cca.id, ids)
        self.assertIn(self.flag_cca_leftover.id, ids)
        self.assertNotIn(self.lm_user.id, ids)
        self.assertNotIn(self.cu_user.id, ids)

    def test_flag_cca_with_leftover_excluded_from_lm_filter(self):
        response = self._api(self.super_admin).get(
            self._users_url(), {"access_role": CLM}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self._user_ids(response)
        self.assertIn(self.lm_user.id, ids)
        # The flag-CCA with a leftover CLM row must NOT be bucketed as LM.
        self.assertNotIn(self.flag_cca_leftover.id, ids)
        self.assertNotIn(self.flag_cca.id, ids)

    def test_flag_cca_excluded_from_cu_filter(self):
        response = self._api(self.super_admin).get(
            self._users_url(), {"access_role": CU}
        )
        ids = self._user_ids(response)
        self.assertIn(self.cu_user.id, ids)
        self.assertNotIn(self.flag_cca.id, ids)
        self.assertNotIn(self.flag_cca_leftover.id, ids)

    def test_invalid_access_role_returns_400(self):
        response = self._api(self.super_admin).get(
            self._users_url(), {"access_role": "NOPE"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "access_role_invalid")

    def test_employees_directory_flag_cca_in_cca_excluded_from_lm(self):
        # Mirror coverage on CustomerEmployeesView (A2a).
        cca_resp = self._api(self.super_admin).get(
            self._employees_url(), {"access_role": CCA}
        )
        self.assertIn(self.flag_cca.id, self._employee_ids(cca_resp))
        self.assertIn(self.flag_cca_leftover.id, self._employee_ids(cca_resp))

        lm_resp = self._api(self.super_admin).get(
            self._employees_url(), {"access_role": CLM}
        )
        self.assertIn(self.lm_user.id, self._employee_ids(lm_resp))
        self.assertNotIn(
            self.flag_cca_leftover.id, self._employee_ids(lm_resp)
        )


# ---------------------------------------------------------------------------
# A2b — flag-aware ?access_role= on the GLOBAL UserViewSet.
# ---------------------------------------------------------------------------
class GlobalUserViewSetAccessRoleFilterTests(_Fixture):
    URL = "/api/users/"

    def _emails(self, response):
        results = response.data.get("results", response.data)
        return {r["email"] for r in results}

    def test_flag_cca_returned_by_cca_filter(self):
        response = self._api(self.super_admin).get(
            self.URL, {"access_role": CCA}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = self._emails(response)
        self.assertIn(self.flag_cca.email, emails)
        self.assertIn(self.flag_cca_leftover.email, emails)

    def test_flag_cca_with_leftover_excluded_from_lm_filter(self):
        response = self._api(self.super_admin).get(
            self.URL, {"access_role": CLM}
        )
        emails = self._emails(response)
        self.assertIn(self.lm_user.email, emails)
        self.assertNotIn(self.flag_cca_leftover.email, emails)

    def test_flag_cca_excluded_from_cu_filter(self):
        response = self._api(self.super_admin).get(
            self.URL, {"access_role": CU}
        )
        emails = self._emails(response)
        self.assertIn(self.cu_user.email, emails)
        self.assertNotIn(self.flag_cca.email, emails)
        self.assertNotIn(self.flag_cca_leftover.email, emails)


# ---------------------------------------------------------------------------
# A3a — ?building_id= on /users/.
# ---------------------------------------------------------------------------
class UsersBuildingIdFilterTests(_Fixture):
    def test_flag_cca_matches_any_building(self):
        for b in (self.b1, self.b2):
            response = self._api(self.super_admin).get(
                self._users_url(), {"building_id": b.id}
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            ids = self._user_ids(response)
            self.assertIn(
                self.flag_cca.id,
                ids,
                f"flag-CCA must match building {b.id}",
            )

    def test_per_building_user_matches_only_its_building(self):
        # cu_user has a row on b2 only.
        b2 = self._api(self.super_admin).get(
            self._users_url(), {"building_id": self.b2.id}
        )
        self.assertIn(self.cu_user.id, self._user_ids(b2))

        b1 = self._api(self.super_admin).get(
            self._users_url(), {"building_id": self.b1.id}
        )
        self.assertNotIn(self.cu_user.id, self._user_ids(b1))
        # lm_user has a row on b1 only → matches b1, not b2.
        self.assertIn(self.lm_user.id, self._user_ids(b1))
        self.assertNotIn(self.lm_user.id, self._user_ids(b2))

    def test_non_int_building_id_returns_400(self):
        response = self._api(self.super_admin).get(
            self._users_url(), {"building_id": "abc"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "building_id_invalid")


# ---------------------------------------------------------------------------
# A3b — ?building_id= + ?search= on /contacts/.
# ---------------------------------------------------------------------------
class ContactsFilterTests(_Fixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Company-wide contact: no building link, no legacy anchor.
        cls.company_contact = Contact.objects.create(
            customer=cls.customer,
            full_name="Company Wide Contact",
            email="cw-contact@example.com",
            phone="+31612345678",
            role_label="HQ",
        )
        # Building-scoped contact via ContactBuildingLink to b1.
        cls.b1_contact = Contact.objects.create(
            customer=cls.customer,
            full_name="Building One Contact",
            email="b1-contact@example.com",
        )
        ContactBuildingLink.objects.create(
            contact=cls.b1_contact, building=cls.b1
        )
        # Legacy single-building anchor on b2.
        cls.b2_legacy_contact = Contact.objects.create(
            customer=cls.customer,
            full_name="Building Two Legacy",
            email="b2-legacy@example.com",
            building=cls.b2,
        )

    def _names(self, response):
        return {r["full_name"] for r in response.data["results"]}

    def test_company_wide_contact_matches_any_building_filter(self):
        for b in (self.b1, self.b2):
            response = self._api(self.super_admin).get(
                self._contacts_url(), {"building_id": b.id}
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn("Company Wide Contact", self._names(response))

    def test_building_scoped_contact_matches_only_its_building(self):
        b1 = self._api(self.super_admin).get(
            self._contacts_url(), {"building_id": self.b1.id}
        )
        names_b1 = self._names(b1)
        self.assertIn("Building One Contact", names_b1)
        self.assertNotIn("Building Two Legacy", names_b1)

        b2 = self._api(self.super_admin).get(
            self._contacts_url(), {"building_id": self.b2.id}
        )
        names_b2 = self._names(b2)
        # Legacy anchor on b2 matches the b2 filter.
        self.assertIn("Building Two Legacy", names_b2)
        self.assertNotIn("Building One Contact", names_b2)

    def test_non_int_building_id_is_ignored_returns_full_list(self):
        # Documented asymmetry vs /users/ (which returns 400
        # building_id_invalid): a malformed building_id on the CONTACTS
        # list is intentionally IGNORED (no narrowing) so a stray FE value
        # degrades to "no filter" rather than erroring the read. Lock it.
        response = self._api(self.super_admin).get(
            self._contacts_url(), {"building_id": "not-an-int"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = self._names(response)
        self.assertIn("Company Wide Contact", names)
        self.assertIn("Building One Contact", names)
        self.assertIn("Building Two Legacy", names)

    def test_search_matches_real_fields(self):
        response = self._api(self.super_admin).get(
            self._contacts_url(), {"search": "Company Wide"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = self._names(response)
        self.assertIn("Company Wide Contact", names)
        self.assertNotIn("Building One Contact", names)
