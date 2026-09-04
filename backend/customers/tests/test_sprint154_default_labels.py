"""
Sprint 154 §I.7 — every customer has an "Algemeen" Department and
WorkType, and every Extra Work ends up carrying both.

The owner's requirement was "Department and Work Type must be required,
and if a customer has none defined, an option called General must be
selectable". These tests pin the half that makes the other half safe: a
customer with an EMPTY label list is exactly the case that would make a
required field un-fillable, so the guarantee is that the list is never
empty.
"""
from rest_framework import status
from rest_framework.test import APITestCase

from customers.models import Customer, Department, WorkType
from customers.signals import DEFAULT_LABEL_NAME, ensure_default_labels
from test_utils import TenantFixtureMixin


class DefaultLabelProvisioningTests(TenantFixtureMixin, APITestCase):
    def test_a_new_customer_gets_both_default_labels(self):
        customer = Customer.objects.create(company=self.company, name="Fresh BV")
        self.assertTrue(
            Department.objects.filter(
                customer=customer, name=DEFAULT_LABEL_NAME
            ).exists()
        )
        self.assertTrue(
            WorkType.objects.filter(
                customer=customer, name=DEFAULT_LABEL_NAME
            ).exists()
        )

    def test_the_shared_fixture_customers_have_them_too(self):
        """The signal fires for every Customer.objects.create, including
        the ones the test fixtures build — so no test has to know about
        this feature to benefit from it."""
        for customer in (self.customer, self.other_customer):
            self.assertEqual(
                Department.objects.filter(
                    customer=customer, name=DEFAULT_LABEL_NAME
                ).count(),
                1,
            )

    def test_ensure_default_labels_is_idempotent(self):
        """Called twice, it must not create a second row — the model's
        `UniqueConstraint(Lower(Trim(name)), customer)` would reject it,
        so a non-idempotent helper would be a 500 waiting to happen."""
        customer = Customer.objects.create(company=self.company, name="Twice BV")
        ensure_default_labels(customer)
        ensure_default_labels(customer)
        self.assertEqual(
            Department.objects.filter(customer=customer).count(), 1
        )
        self.assertEqual(WorkType.objects.filter(customer=customer).count(), 1)

    def test_an_existing_lowercase_algemeen_is_reused_not_duplicated(self):
        """Case-insensitive, matching the DB constraint. A tenant that
        already calls their catch-all "algemeen" keeps that row."""
        customer = Customer.objects.create(company=self.company, name="Case BV")
        Department.objects.filter(customer=customer).delete()
        Department.objects.create(customer=customer, name="algemeen")

        ensure_default_labels(customer)
        self.assertEqual(
            list(
                Department.objects.filter(customer=customer).values_list(
                    "name", flat=True
                )
            ),
            ["algemeen"],
        )

    def test_a_renamed_default_is_not_recreated_alongside(self):
        """If an operator renames Algemeen to something of their own, the
        helper provisions a fresh Algemeen rather than renaming theirs
        back — but it must not blow up, and the operator's row survives."""
        customer = Customer.objects.create(company=self.company, name="Renamed BV")
        row = Department.objects.get(customer=customer)
        row.name = "Hoofdkantoor"
        row.save(update_fields=["name"])

        ensure_default_labels(customer)
        names = set(
            Department.objects.filter(customer=customer).values_list(
                "name", flat=True
            )
        )
        self.assertIn("Hoofdkantoor", names)
        self.assertIn(DEFAULT_LABEL_NAME, names)


class ExtraWorkAlwaysLabelledTests(TenantFixtureMixin, APITestCase):
    """§I.7 — the data invariant: no unlabelled Extra Work, on any write
    path."""

    def _cart_payload(self, **extra):
        payload = {
            "customer": self.customer.id,
            "building": self.building.id,
            "title": "Deep clean",
            "description": "After the event",
            # P-16 repin — two rules that postdate this fixture: the
            # per-line requested_date was retired (P-8 §4; the
            # request-level preferred_date is the cart's date), and a
            # PROVIDER's non-agreed cart must choose its intent (P-15,
            # intent_required). The label defaults under test are
            # unchanged.
            "preferred_date": "2026-06-15",
            "request_intent": "AUTO_START_AFTER_PRICING",
            "line_items": [
                {
                    "custom_description": "Ad-hoc line",
                    "quantity": "1.00",
                    "unit_price": "100.00",
                }
            ],
        }
        payload.update(extra)
        return payload

    def test_omitting_both_labels_fills_in_algemeen(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            "/api/extra-work/", self._cart_payload(), format="json"
        )
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.data
        )
        self.assertEqual(response.data["department_name"], DEFAULT_LABEL_NAME)
        self.assertEqual(response.data["work_type_name"], DEFAULT_LABEL_NAME)

    def test_an_explicit_label_always_wins(self):
        own = Department.objects.create(customer=self.customer, name="Event")
        self.authenticate(self.company_admin)
        response = self.client.post(
            "/api/extra-work/",
            self._cart_payload(department=own.id),
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.data
        )
        self.assertEqual(response.data["department_name"], "Event")
        # ...and the omitted one still gets the default.
        self.assertEqual(response.data["work_type_name"], DEFAULT_LABEL_NAME)

    def test_a_label_from_another_customer_is_still_rejected(self):
        """The Sprint 127 same-customer invariant must survive the new
        fallback — filling a gap must never become a way to smuggle
        another customer's label in."""
        foreign = Department.objects.create(
            customer=self.other_customer, name="Foreign Dept"
        )
        self.authenticate(self.super_admin)
        response = self.client.post(
            "/api/extra-work/",
            self._cart_payload(department=foreign.id),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        codes = [
            getattr(err, "code", None)
            for err in response.data.get("department", [])
        ]
        self.assertIn("department_customer_mismatch", codes)
