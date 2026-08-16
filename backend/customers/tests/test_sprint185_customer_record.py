"""
Sprint 185 D — the customer record: an address, a billing contact, a life.

Every new field is asserted through a RENDERED endpoint, not through the
model: a field that exists and is not in `fields` is invisible to every
screen, and a model-level test never notices (Sprint 173 took a whole
page down that way).

The three claims, and the shape of each:

  §1 the invoice carries the CUSTOMER's address — including the proof
     that adding one LATER cannot alter a document already sent, which
     is worth more than the feature if it turns out to be false;
  §2 a contact can be marked to receive invoices, the recipients resolve,
     and the document goes out through the ONE existing logged sender —
     with a NotificationLog row, because "did they get it" needs an
     answer;
  §3 the lifecycle is DESCRIPTIVE: it appears, it filters, and it does
     not touch anybody's access.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.invoice_recipients import (
    invoice_contact_recipients,
    skipped_invoice_contacts,
)
from customers.models import (
    Contact,
    Customer,
    CustomerBuildingMembership,
    CustomerLifecycle,
    CustomerUserMembership,
)
from notifications.models import NotificationLog


User = get_user_model()
PASSWORD = "StrongerTestPassword185!"

CUSTOMERS_URL = "/api/customers/"


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-185")
        cls.building = Building.objects.create(
            company=cls.company, name="B", address="Werfstraat 9"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name="Van Dijk Vastgoed B.V.",
            building=cls.building,
            address="Keizersgracht 12",
            postal_code="1015 CW",
            city="Amsterdam",
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.admin = User.objects.create_user(
            email="ca-185@example.com",
            password=PASSWORD,
            role=UserRole.COMPANY_ADMIN,
            full_name="CA",
        )
        CompanyUserMembership.objects.create(user=cls.admin, company=cls.company)

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def customer_row(self, customer=None):
        target = customer or self.customer
        response = self.api(self.admin).get(f"{CUSTOMERS_URL}{target.pk}/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.data


# ---------------------------------------------------------------------------
# §1 — the address
# ---------------------------------------------------------------------------


class CustomerAddressEndpointTests(_Fixture):
    def test_the_detail_endpoint_carries_every_address_field(self):
        row = self.customer_row()
        for field in ("address", "postal_code", "city", "country"):
            with self.subTest(field=field):
                self.assertIn(field, row)
        self.assertEqual(row["address"], "Keizersgracht 12")
        self.assertEqual(row["postal_code"], "1015 CW")
        self.assertEqual(row["city"], "Amsterdam")

    def test_the_list_endpoint_carries_them_too(self):
        response = self.api(self.admin).get(CUSTOMERS_URL)
        self.assertEqual(response.status_code, 200)
        rows = response.data.get("results", response.data)
        self.assertTrue(rows)
        self.assertIn("address", rows[0])
        self.assertIn("has_billing_address", rows[0])

    def test_the_address_is_writable(self):
        response = self.api(self.admin).patch(
            f"{CUSTOMERS_URL}{self.customer.pk}/",
            {"address": "Herengracht 1", "city": "Utrecht"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.address, "Herengracht 1")
        self.assertEqual(self.customer.city, "Utrecht")

    def test_has_billing_address_needs_a_street_and_a_city(self):
        """One definition, so the screen's warning and any send-time
        guard cannot disagree. A postcode alone is not an addressee."""
        self.assertTrue(self.customer.has_billing_address)
        for address, city, expected in (
            ("", "Amsterdam", False),
            ("Keizersgracht 12", "", False),
            ("   ", "Amsterdam", False),
            ("", "", False),
            ("Keizersgracht 12", "Amsterdam", True),
        ):
            with self.subTest(address=address, city=city):
                self.customer.address = address
                self.customer.city = city
                self.assertEqual(self.customer.has_billing_address, expected)

    def test_country_is_optional_and_absent_by_default(self):
        """A domestic Dutch invoice carries no country; printing one
        would make every normal invoice look like an export."""
        self.assertEqual(self.customer.country, "")
        self.assertTrue(self.customer.has_billing_address)


class InvoicePdfCarriesTheCustomerAddressTests(_Fixture):
    """The address reaches the DOCUMENT, not just the database."""

    def _invoice(self, **extra):
        from invoicing.models import Invoice, InvoiceLine

        invoice = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            building=extra.pop("building", None),
            status=Invoice.Status.DRAFT,
            period_year=2026,
            period_month=5,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
            created_by=self.admin,
            **extra,
        )
        InvoiceLine.objects.create(
            invoice=invoice,
            ordering=0,
            description="Werk",
            line_subtotal=Decimal("100.00"),
            line_vat=Decimal("21.00"),
            line_total=Decimal("121.00"),
        )
        return invoice

    @staticmethod
    def _text(data: bytes) -> str:
        from io import BytesIO

        from pypdf import PdfReader

        return "\n".join(
            page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages
        )

    def test_the_pdf_prints_the_customer_address(self):
        from invoicing.invoice_pdf import render_invoice_pdf

        text = self._text(render_invoice_pdf(self._invoice()))
        self.assertIn("Keizersgracht 12", text)
        self.assertIn("Amsterdam", text)

    def test_a_per_building_invoice_still_prints_the_CUSTOMER_address(self):
        """The owner's decision, asserted: a building's address is the
        WORK SITE. It must not become the billing address just because
        the invoice is scoped to that building."""
        from invoicing.invoice_pdf import render_invoice_pdf

        text = self._text(render_invoice_pdf(self._invoice(building=self.building)))
        self.assertIn("Keizersgracht 12", text)
        self.assertNotIn("Werfstraat 9", text)

    def test_an_address_less_customer_renders_no_empty_label(self):
        """An absent address is absent, not a blank labelled row that
        reads as a broken template."""
        from invoicing.invoice_pdf import render_invoice_pdf

        bare = Customer.objects.create(
            company=self.company, name="No Address BV"
        )
        invoice = self._invoice()
        invoice.customer = bare
        invoice.save(update_fields=["customer"])
        text = self._text(render_invoice_pdf(invoice))
        self.assertIn("No Address BV", text)
        self.assertNotIn("Adres:", text)

    def test_every_annex_page_names_the_addressee(self):
        """§1 asked for the address "wherever the header repeats".

        The repeated annex header used to carry the PROVIDER's brand and
        the invoice number and nothing about who the invoice was billed
        to, so a page that came loose could not be put back on the right
        pile. Asserted per page, not on the joined text: a claim about
        every page cannot be proved by a document-wide substring.
        """
        from io import BytesIO

        from pypdf import PdfReader

        from invoicing.invoice_pdf import render_invoice_pdf
        from invoicing.models import InvoiceLine

        invoice = self._invoice()
        # Enough detail to force the annex onto more than one page.
        for index in range(70):
            InvoiceLine.objects.create(
                invoice=invoice,
                ordering=index + 1,
                description=f"Extra werk regel {index}",
                line_subtotal=Decimal("1.00"),
                line_vat=Decimal("0.21"),
                line_total=Decimal("1.21"),
            )
        pages = PdfReader(BytesIO(render_invoice_pdf(invoice))).pages
        self.assertGreater(len(pages), 2, "expected a multi-page annex")
        for number, page in enumerate(pages[1:], start=2):
            with self.subTest(page=number):
                self.assertIn(self.customer.name, page.extract_text() or "")


@override_settings(MEDIA_ROOT="/tmp/sprint185-invoice-media")
class TheFrozenDocumentIsNotRewrittenTests(_Fixture):
    """§1's most important claim.

    A sent invoice's PDF is FROZEN (Sprint 180 §1). Adding an address
    afterwards must not, and cannot, change a document already sent. If
    freezing turned out to be bypassable that would be a finding worth
    more than this whole feature, so it is asserted rather than assumed.
    """

    def _sent_invoice_for(self, customer):
        from invoicing.models import Invoice, InvoiceLine
        from invoicing.state_machine import issue_invoice, send_invoice

        invoice = Invoice.objects.create(
            company=self.company,
            customer=customer,
            status=Invoice.Status.DRAFT,
            period_year=2026,
            period_month=5,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
            created_by=self.admin,
        )
        InvoiceLine.objects.create(
            invoice=invoice,
            ordering=0,
            description="Werk",
            line_subtotal=Decimal("100.00"),
            line_vat=Decimal("21.00"),
            line_total=Decimal("121.00"),
        )
        return send_invoice(self.admin, issue_invoice(self.admin, invoice))

    def test_adding_an_address_later_does_not_change_a_sent_document(self):
        from invoicing.invoice_pdf import invoice_pdf_bytes

        bare = Customer.objects.create(
            company=self.company, name="Later Address BV"
        )
        sent = self._sent_invoice_for(bare)
        before = invoice_pdf_bytes(sent)
        digest_before = hashlib.sha256(before).hexdigest()
        self.assertEqual(digest_before, sent.pdf_sha256)

        # Fill the address in AFTER the invoice was sent.
        bare.address = "Nieuwezijds Voorburgwal 3"
        bare.city = "Amsterdam"
        bare.save(update_fields=["address", "city"])

        after = invoice_pdf_bytes(
            type(sent).objects.get(pk=sent.pk)
        )
        self.assertEqual(after, before)
        self.assertEqual(hashlib.sha256(after).hexdigest(), digest_before)
        self.assertNotIn(
            "Nieuwezijds Voorburgwal 3",
            InvoicePdfCarriesTheCustomerAddressTests._text(after),
        )

    def test_a_fresh_render_of_the_same_row_DOES_change(self):
        """The control. Without it the assertion above would also pass
        for a renderer that ignored the address entirely."""
        from invoicing.invoice_pdf import render_invoice_pdf

        bare = Customer.objects.create(
            company=self.company, name="Control BV"
        )
        sent = self._sent_invoice_for(bare)
        bare.address = "Singel 5"
        bare.city = "Amsterdam"
        bare.save(update_fields=["address", "city"])
        text = InvoicePdfCarriesTheCustomerAddressTests._text(
            render_invoice_pdf(type(sent).objects.get(pk=sent.pk))
        )
        self.assertIn("Singel 5", text)


# ---------------------------------------------------------------------------
# §2 — the invoice contact
# ---------------------------------------------------------------------------


class ContactReceivesInvoicesTests(_Fixture):
    def _contact(self, name, email="", **extra):
        return Contact.objects.create(
            customer=self.customer, full_name=name, email=email, **extra
        )

    def test_the_contact_endpoint_carries_the_flag(self):
        contact = self._contact("Anna", "anna@example.com")
        response = self.api(self.admin).get(
            f"{CUSTOMERS_URL}{self.customer.pk}/contacts/"
        )
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.data.get("results", response.data)
        row = next(r for r in rows if r["id"] == contact.pk)
        self.assertIn("receives_invoices", row)
        self.assertFalse(row["receives_invoices"])

    def test_the_flag_is_writable(self):
        contact = self._contact("Anna", "anna@example.com")
        response = self.api(self.admin).patch(
            f"{CUSTOMERS_URL}{self.customer.pk}/contacts/{contact.pk}/",
            {"receives_invoices": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        contact.refresh_from_db()
        self.assertTrue(contact.receives_invoices)

    def test_a_customer_may_have_more_than_one(self):
        self._contact("Anna", "anna@example.com", receives_invoices=True)
        self._contact("Bram", "bram@example.com", receives_invoices=True)
        self._contact("Chris", "chris@example.com")
        self.assertEqual(
            [c.full_name for c in invoice_contact_recipients(self.customer)],
            ["Anna", "Bram"],
        )

    def test_a_flagged_contact_with_no_email_is_reported_not_dropped(self):
        """"I ticked the box and they got nothing" is the silence this
        feature exists to remove."""
        self._contact("No Mail", "", receives_invoices=True)
        self.assertEqual(invoice_contact_recipients(self.customer), [])
        self.assertEqual(
            [c.full_name for c in skipped_invoice_contacts(self.customer)],
            ["No Mail"],
        )

    def test_billing_contact_type_does_not_imply_receiving_invoices(self):
        """Two different facts: what the person DOES, and what they
        RECEIVE. A customer can have three billing contacts and want one
        of them to get the document."""
        self._contact("Billing Person", "b@example.com", contact_type="BILLING")
        self.assertEqual(invoice_contact_recipients(self.customer), [])


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class InvoiceMailGoesThroughTheOneSenderTests(_Fixture):
    def test_it_sends_the_pdf_and_logs_every_recipient(self):
        from django.core import mail

        from notifications.services import send_invoice_to_contacts
        from invoicing.models import Invoice

        Contact.objects.create(
            customer=self.customer,
            full_name="Anna",
            email="anna@example.com",
            receives_invoices=True,
        )
        Contact.objects.create(
            customer=self.customer,
            full_name="Bram",
            email="bram@example.com",
            receives_invoices=True,
        )
        invoice = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.SENT,
            number="2026-0001",
            year=2026,
            total_amount=Decimal("121.00"),
            created_by=self.admin,
        )

        mail.outbox = []
        logs, skipped = send_invoice_to_contacts(
            invoice, b"%PDF-1.4 fake", actor=self.admin
        )

        self.assertEqual(len(logs), 2)
        self.assertEqual(skipped, [])
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            {m.to[0] for m in mail.outbox},
            {"anna@example.com", "bram@example.com"},
        )
        # ONE document, several recipients.
        for message in mail.outbox:
            self.assertEqual(len(message.attachments), 1)
            filename, content, mimetype = message.attachments[0]
            self.assertEqual(filename, "factuur-2026-0001.pdf")
            self.assertEqual(mimetype, "application/pdf")

        # Logged the way every other send is logged, so "did they get
        # it" has an answer.
        rows = NotificationLog.objects.filter(event_type="INVOICE_SENT")
        self.assertEqual(rows.count(), 2)

    def test_the_attached_bytes_arrive_intact(self):
        """The attachment is the DOCUMENT. Asserting only that one exists
        would pass for a renderer that attached an empty file."""
        from django.core import mail

        from notifications.services import send_invoice_to_contacts
        from invoicing.models import Invoice

        Contact.objects.create(
            customer=self.customer,
            full_name="Anna",
            email="anna@example.com",
            receives_invoices=True,
        )
        invoice = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.SENT,
            number="2026-0002",
            year=2026,
            total_amount=Decimal("121.00"),
            created_by=self.admin,
        )
        # Bytes that are NOT valid UTF-8, because a real PDF is not and a
        # naive `.decode()` anywhere on the path would only fail on those.
        payload = b"%PDF-1.4\n\x00\x80\xfe\xff binary \x01\x02"

        mail.outbox = []
        send_invoice_to_contacts(invoice, payload, actor=self.admin)

        _filename, content, _mimetype = mail.outbox[0].attachments[0]
        self.assertEqual(
            content if isinstance(content, bytes) else content.encode("latin-1"),
            payload,
        )

    def test_the_queued_arguments_survive_a_real_json_round_trip(self):
        """The bug this test exists for.

        The send path hands the document to a Celery task, and this
        project leaves `task_serializer` at Celery's default of JSON.
        Raw `bytes` are not JSON-serialisable, so an earlier version of
        this code raised `EncodeError` the moment it met a real worker —
        and every test above still passed, because the suite runs with
        `CELERY_TASK_ALWAYS_EAGER`, where arguments are handed over
        in-process and never serialised at all.

        So this asserts the thing eager mode cannot: that what gets
        queued would actually cross the wire, and that the bytes come
        back identical on the other side.
        """
        import base64
        import json
        from unittest.mock import patch

        from notifications.services import send_logged_email

        payload = b"%PDF-1.4\n\x00\x80\xfe\xff binary \x01\x02"
        with patch("notifications.tasks.send_email_task.delay") as delay:
            send_logged_email(
                recipient_email="anna@example.com",
                subject="Factuur",
                body="Beste Anna",
                event_type="INVOICE_SENT",
                attachment=("factuur.pdf", payload, "application/pdf"),
            )

        kwargs = delay.call_args.kwargs
        # Would raise TypeError on raw bytes — which is exactly the
        # failure a real broker produces and eager mode hides.
        revived = json.loads(json.dumps(kwargs))
        filename, encoded, mimetype = revived["attachment"]
        self.assertEqual(filename, "factuur.pdf")
        self.assertEqual(mimetype, "application/pdf")
        self.assertEqual(base64.b64decode(encoded), payload)

    def test_no_flagged_contacts_means_no_mail_and_no_log(self):
        from django.core import mail

        from notifications.services import send_invoice_to_contacts
        from invoicing.models import Invoice

        invoice = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.SENT,
            number="2026-0002",
            year=2026,
            total_amount=Decimal("121.00"),
            created_by=self.admin,
        )
        mail.outbox = []
        logs, skipped = send_invoice_to_contacts(invoice, b"%PDF-1.4 fake")
        self.assertEqual(logs, [])
        self.assertEqual(skipped, [])
        self.assertEqual(mail.outbox, [])
        self.assertEqual(
            NotificationLog.objects.filter(event_type="INVOICE_SENT").count(), 0
        )


# ---------------------------------------------------------------------------
# §3 — the lifecycle
# ---------------------------------------------------------------------------


class CustomerLifecycleTests(_Fixture):
    def test_the_endpoint_carries_it_and_it_defaults_to_active(self):
        row = self.customer_row()
        self.assertIn("lifecycle", row)
        self.assertEqual(row["lifecycle"], CustomerLifecycle.ACTIVE)

    def test_it_is_writable_and_every_proposed_state_is_accepted(self):
        for value in (
            CustomerLifecycle.PROSPECT,
            CustomerLifecycle.ONBOARDING,
            CustomerLifecycle.NOTICE,
            CustomerLifecycle.CHURNED,
            CustomerLifecycle.ACTIVE,
        ):
            with self.subTest(value=value):
                response = self.api(self.admin).patch(
                    f"{CUSTOMERS_URL}{self.customer.pk}/",
                    {"lifecycle": value},
                    format="json",
                )
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.data["lifecycle"], value)

    def test_an_unknown_state_is_refused(self):
        response = self.api(self.admin).patch(
            f"{CUSTOMERS_URL}{self.customer.pk}/",
            {"lifecycle": "SOMETHING_ELSE"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_it_is_filterable(self):
        other = Customer.objects.create(
            company=self.company,
            name="Leaving BV",
            lifecycle=CustomerLifecycle.NOTICE,
        )
        response = self.api(self.admin).get(
            CUSTOMERS_URL, {"lifecycle": CustomerLifecycle.NOTICE}
        )
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.data.get("results", response.data)
        ids = {r["id"] for r in rows}
        self.assertIn(other.pk, ids)
        self.assertNotIn(self.customer.pk, ids)

    def test_lifecycle_does_not_touch_access(self):
        """THE rule. A lifecycle value must never revoke a login — that
        is a permission change wearing a status costume, and this repo
        has a hard rule against it. `is_active` remains the only thing
        access is decided by.
        """
        member = User.objects.create_user(
            email="cu-185@example.com",
            password=PASSWORD,
            role=UserRole.CUSTOMER_USER,
            full_name="Customer User",
        )
        CustomerUserMembership.objects.create(
            user=member, customer=self.customer
        )
        self.customer.lifecycle = CustomerLifecycle.CHURNED
        self.customer.save(update_fields=["lifecycle"])

        # Still active, so still in scope: the customer can still reach
        # their own surfaces.
        self.assertTrue(self.customer.is_active)
        response = self.api(member).get("/api/tickets/")
        self.assertEqual(response.status_code, 200, response.content)

    def test_is_active_and_lifecycle_are_independent(self):
        self.customer.is_active = False
        self.customer.lifecycle = CustomerLifecycle.ACTIVE
        self.customer.save(update_fields=["is_active", "lifecycle"])
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertEqual(self.customer.lifecycle, CustomerLifecycle.ACTIVE)


class LifecycleBackfillTests(TestCase):
    """The migration's promise: every existing row migrates FAITHFULLY,
    and nobody's access changes.

    Asserted against the migrated database rather than by re-running the
    migration: the fixture rows below are created through the current
    model, so what this pins is the RULE the backfill implements —
    active -> ACTIVE, inactive -> CHURNED — which is what a reviewer
    needs to be able to check against the data after deploy.
    """

    def test_active_rows_read_active_and_inactive_rows_read_churned(self):
        company = Company.objects.create(name="Prov B", slug="prov-b-185")
        live = Customer.objects.create(
            company=company, name="Live", is_active=True
        )
        dead = Customer.objects.create(
            company=company, name="Dead", is_active=False,
            lifecycle=CustomerLifecycle.CHURNED,
        )
        self.assertEqual(live.lifecycle, CustomerLifecycle.ACTIVE)
        self.assertEqual(dead.lifecycle, CustomerLifecycle.CHURNED)
        # And neither one's access flag was touched by the state.
        self.assertTrue(live.is_active)
        self.assertFalse(dead.is_active)
