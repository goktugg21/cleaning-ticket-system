"""
W-EW1 §1 + §2 — who may state a deadline, and the cart's ONE date.

Two changes, both on the CREATE path only, are pinned here.

**§1 — the deadline is no longer provider-only on create.** Sprint 176 §3
refused a customer-side deadline on the grounds that a deadline "is what an
operator is measured against". The model's own reading of its six date
columns is the answer: `deadline` sits in the ASKED FOR / OWED pair beside
`preferred_date` and `planned_end_date`, while what the provider is measured
against having COMMITTED to is `provider_planned_date` /
`provider_planned_end_date` — written by the plan action alone. So a
customer may say when the work is owed by; it still cannot touch what the
provider promised.

What did NOT change is the part worth guarding hardest: the two date EDIT
surfaces stay provider-only (moving a deadline afterwards is renegotiation,
not asking), and tenant scope is untouched. Lifting the gate widened WHICH
FIELD a customer-side actor may fill, never WHICH REQUESTS it may create.

**§2 — a cart line no longer carries a date of its own.** The request-level
`preferred_date` is the single date the whole cart is wished for, and the
server stamps every line from it. The COLUMN stays — it is what decides
which agreed-price window a line resolves against, and the detail payload
still renders it — but the write path closes: a stale client that still
sends a per-line date is refused with a stable code rather than having its
date silently dropped, because a silently-dropped date would price the line
against a window the caller never asked for.
"""
from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from customers.models import Department, WorkType
from extra_work.models import ExtraWorkRequest

from .test_extra_work_mvp import ExtraWorkFixtureMixin


class _Base(ExtraWorkFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _payload(self, **extra):
        """A minimal valid create cart for customer A / building A1.

        Deliberately carries NO per-line `requested_date`: that is the
        §2 shape, and every test that wants the old shape puts it back
        explicitly.
        """
        payload = {
            "company": self.provider_a.id,
            "customer": self.customer_a.id,
            "department": Department.objects.filter(
                customer=self.customer_a
            ).first().id,
            "work_type": WorkType.objects.filter(
                customer=self.customer_a
            ).first().id,
            "building": self.building_a1.id,
            "title": "Customer request",
            "description": "please",
            "line_items": [
                {"custom_description": "ad hoc work", "quantity": "1.00"}
            ],
        }
        payload.update(extra)
        return payload


class ACustomerMayStateADeadlineTests(_Base):
    """§1 — the create gate is lifted."""

    def test_a_customer_may_now_set_a_deadline_on_create(self):
        owed = timezone.localdate() + timedelta(days=9)
        response = self.api(self.cust_basic_a).post(
            "/api/extra-work/",
            self._payload(deadline=owed.isoformat()),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(str(response.data["deadline"]), owed.isoformat())
        # And it is what actually landed on the row, not just an echo.
        row = ExtraWorkRequest.objects.get(pk=response.data["id"])
        self.assertEqual(row.deadline, owed)

    def test_a_provider_may_still_set_a_deadline_on_create(self):
        owed = timezone.localdate() + timedelta(days=4)
        response = self.api(self.admin_a).post(
            "/api/extra-work/",
            # P-16 repin — P-15's intent rule: the PROVIDER's non-agreed
            # cart must choose (intent_required); the deadline rule
            # under test is unchanged.
            self._payload(
                deadline=owed.isoformat(),
                request_intent="AUTO_START_AFTER_PRICING",
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(str(response.data["deadline"]), owed.isoformat())

    def test_a_customer_may_still_state_a_preferred_date(self):
        """The wish did not stop working because the commitment started."""
        wish = timezone.localdate() + timedelta(days=6)
        response = self.api(self.cust_basic_a).post(
            "/api/extra-work/",
            self._payload(preferred_date=wish.isoformat()),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            str(response.data["preferred_date"]), wish.isoformat()
        )

    def test_the_lifted_gate_did_not_widen_tenant_scope(self):
        """H-1/H-2: a deadline still cannot reach another tenant's data.

        The customer-side actor of tenant A names tenant B's customer and
        building. Before §1 this was refused by the deadline gate, which
        would have masked a scope hole. Now the deadline is accepted as a
        field, so THIS is what proves the scope check is doing the work.
        """
        response = self.api(self.cust_basic_a).post(
            "/api/extra-work/",
            self._payload(
                customer=self.customer_b.id,
                building=self.building_b.id,
                deadline=(
                    timezone.localdate() + timedelta(days=3)
                ).isoformat(),
            ),
            format="json",
        )
        self.assertIn(response.status_code, (400, 403, 404), response.data)
        self.assertFalse(
            ExtraWorkRequest.objects.filter(
                customer=self.customer_b
            ).exists()
        )


class TheDeadlineEditSurfacesStayProviderOnlyTests(_Base):
    """§1 lifted CREATE and nothing else. Moving a date is renegotiation."""

    def _row(self):
        return ExtraWorkRequest.objects.create(
            company=self.provider_a,
            customer=self.customer_a,
            building=self.building_a1,
            title="Dated job",
            description="x",
            created_by=self.admin_a,
        )

    def test_a_customer_still_cannot_PATCH_dates(self):
        response = self.api(self.cust_basic_a).patch(
            f"/api/extra-work/{self._row().id}/dates/",
            {"deadline": timezone.localdate().isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["code"], "deadline_provider_only")

    def test_a_customer_still_cannot_bulk_set_dates(self):
        response = self.api(self.cust_basic_a).post(
            "/api/extra-work/bulk-dates/",
            {
                "ids": [self._row().id],
                "deadline": timezone.localdate().isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)


class OneDateForTheWholeCartTests(_Base):
    """§2 — the per-line date is server-derived, never client-supplied."""

    def test_a_client_supplied_per_line_date_is_refused(self):
        response = self.api(self.cust_basic_a).post(
            "/api/extra-work/",
            self._payload(
                line_items=[
                    {
                        "custom_description": "ad hoc work",
                        "quantity": "1.00",
                        "requested_date": (
                            timezone.localdate() + timedelta(days=2)
                        ).isoformat(),
                    }
                ]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "line_requested_date_not_accepted", str(response.data)
        )
        self.assertFalse(ExtraWorkRequest.objects.exists())

    def test_every_line_takes_the_request_level_preferred_date(self):
        wish = timezone.localdate() + timedelta(days=11)
        response = self.api(self.cust_basic_a).post(
            "/api/extra-work/",
            self._payload(
                preferred_date=wish.isoformat(),
                line_items=[
                    {"custom_description": "one", "quantity": "1.00"},
                    {"custom_description": "two", "quantity": "2.00"},
                ],
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        row = ExtraWorkRequest.objects.get(pk=response.data["id"])
        dates = {item.requested_date for item in row.line_items.all()}
        self.assertEqual(row.line_items.count(), 2)
        self.assertEqual(dates, {wish})

    def test_a_cart_with_no_preferred_date_falls_back_to_today(self):
        response = self.api(self.cust_basic_a).post(
            "/api/extra-work/", self._payload(), format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        row = ExtraWorkRequest.objects.get(pk=response.data["id"])
        for item in row.line_items.all():
            self.assertEqual(item.requested_date, timezone.localdate())

    def test_the_stored_date_is_still_readable_on_the_detail_payload(self):
        """The COLUMN stays, and so does the READ. Only the write closed."""
        wish = timezone.localdate() + timedelta(days=5)
        created = self.api(self.cust_basic_a).post(
            "/api/extra-work/",
            self._payload(preferred_date=wish.isoformat()),
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)

        detail = self.api(self.admin_a).get(
            f"/api/extra-work/{created.data['id']}/"
        )
        self.assertEqual(detail.status_code, 200, detail.data)
        lines = detail.data["line_items"]
        self.assertTrue(lines)
        for line in lines:
            self.assertEqual(str(line["requested_date"]), wish.isoformat())
