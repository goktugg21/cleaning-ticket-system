"""
Sprint 187 §1 — the quote cache, written by the Proposal route.

`ExtraWorkRequest.subtotal_amount` / `vat_amount` / `total_amount` are the
columns every list, dashboard widget, report KPI, CSV export and detail
header reads (through `rowAmounts()` in `frontend/src/lib/billing.ts`,
whose quoted fallback IS `total_amount`). Until this sprint the only
writer was `recompute_totals()`, driven exclusively from the legacy
`/pricing-items/` views, so an Extra Work priced at EUR 484.00 through a
Proposal — approved, ticket spawned, work under way — read EUR 0,00
everywhere.

What these tests pin, in order of how badly each would hurt if it broke:

  1. Approval WRITES the quote cache, on every route that can approve a
     proposal (customer decision, provider override, direct-publish, and
     Sprint 6B auto-start-after-pricing). One helper serves all four; a
     regression that moved the call would silently restore EUR 0,00.
  2. The quote uses the ORDERED quantity and the final amount uses the
     DELIVERED one. This is the entire distinction between
     `recompute_quoted_totals` and `recompute_final_amounts`, and it is
     invisible until an hourly line's `actual_hours` differs from what
     was ordered — at which point using the wrong one silently rewrites
     the customer's agreed quote.
  3. The two functions agree when nothing was re-measured, because they
     share the line resolution and the rounding.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from accounts.models import UserRole
from extra_work.final_amounts import (
    quoted_totals,
    recompute_final_amounts,
    recompute_quoted_totals,
)
from extra_work.models import (
    ExtraWorkCategory,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestIntent,
    ExtraWorkStatus,
    Proposal,
    ProposalLine,
    ProposalStatus,
    Service,
    ServiceCategory,
)
from extra_work.proposal_state_machine import apply_proposal_transition


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class _QuotedTotalsFixture(TestCase):
    """One provider company, one customer who can approve, and a helper
    that builds a SENT proposal ready for a decision."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov 187", slug="prov-187")
        cls.building = Building.objects.create(
            company=cls.company, name="Building-187"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer-187", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-187@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-187@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        cls.cust_user = _mk("cust-187@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        # LOCATION_MANAGER so the customer may approve a quote.
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
            ),
        )

        cls.service = Service.objects.create(
            category=ServiceCategory.objects.create(
                company=cls.company, name="Cat-187"
            ),
            company=cls.company,
            name="Sprint 187 service",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

    def _api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _make_ew(
        self,
        *,
        status=ExtraWorkStatus.PRICING_PROPOSED,
        request_intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
    ) -> ExtraWorkRequest:
        return ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="Sprint 187 EW",
            description="quoted-totals fixture",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=status,
            request_intent=request_intent,
        )

    def _make_proposal(
        self,
        ew: ExtraWorkRequest,
        *,
        status=ProposalStatus.SENT,
        quantity=Decimal("4.00"),
        unit_price=Decimal("121.00"),
        vat_pct=Decimal("21.00"),
    ) -> Proposal:
        proposal = Proposal.objects.create(
            extra_work_request=ew,
            status=status,
            created_by=self.admin,
        )
        ProposalLine.objects.create(
            proposal=proposal,
            service=self.service,
            description="Quoted line",
            quantity=quantity,
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=unit_price,
            vat_pct=vat_pct,
            customer_explanation="",
            internal_note="",
            is_approved_for_spawn=True,
        )
        proposal.recompute_totals()
        proposal.refresh_from_db()
        return proposal


class QuotedTotalsArithmeticTests(_QuotedTotalsFixture):
    """The formula itself, with no HTTP in the way."""

    def test_quoted_totals_sums_the_approved_proposal_lines(self):
        ew = self._make_ew()
        proposal = self._make_proposal(
            ew, status=ProposalStatus.CUSTOMER_APPROVED
        )

        subtotal, vat, total = quoted_totals(ew)
        # 4 x 121.00 = 484.00 net; 21% VAT = 101.64.
        self.assertEqual(subtotal, Decimal("484.00"))
        self.assertEqual(vat, Decimal("101.64"))
        self.assertEqual(total, Decimal("585.64"))
        # Reading must not write.
        ew.refresh_from_db()
        self.assertEqual(ew.total_amount, Decimal("0.00"))
        self.assertEqual(proposal.total_amount, Decimal("585.64"))

    def test_recompute_persists_what_quoted_totals_computes(self):
        ew = self._make_ew()
        self._make_proposal(ew, status=ProposalStatus.CUSTOMER_APPROVED)

        expected = quoted_totals(ew)
        recompute_quoted_totals(ew)
        ew.refresh_from_db()
        self.assertEqual(
            (ew.subtotal_amount, ew.vat_amount, ew.total_amount), expected
        )

    def test_recompute_is_idempotent(self):
        ew = self._make_ew()
        self._make_proposal(ew, status=ProposalStatus.CUSTOMER_APPROVED)

        recompute_quoted_totals(ew)
        ew.refresh_from_db()
        once = ew.total_amount
        recompute_quoted_totals(ew)
        ew.refresh_from_db()
        self.assertEqual(ew.total_amount, once)

    def test_quote_uses_ORDERED_quantity_and_final_uses_DELIVERED(self):
        """The one line that differs between the two functions.

        A quote is what was ORDERED; a final amount is what was
        DELIVERED. Four hours were ordered and quoted; three were worked.
        The quote must still read 484.00 — the customer agreed to that
        number — while the final amount drops to 363.00.

        If `recompute_quoted_totals` ever reached for `billable_quantity`
        the two numbers would collapse into one and the agreed quote
        would be silently rewritten by whatever hours the provider
        entered afterwards. That is what this asserts.
        """
        ew = self._make_ew()
        proposal = self._make_proposal(ew, status=ProposalStatus.CUSTOMER_APPROVED)
        line = proposal.lines.get()

        recompute_quoted_totals(ew)
        ew.refresh_from_db()
        self.assertEqual(ew.subtotal_amount, Decimal("484.00"))

        # The provider measures the work: three hours, not four.
        line.actual_hours = Decimal("3.00")
        line.save(update_fields=["actual_hours"])

        recompute_final_amounts(ew)
        ew.refresh_from_db()
        self.assertEqual(ew.final_subtotal_amount, Decimal("363.00"))
        # ...and the QUOTE is untouched by the re-measurement.
        self.assertEqual(ew.subtotal_amount, Decimal("484.00"))
        self.assertEqual(ew.total_amount, Decimal("585.64"))

    def test_quote_and_final_agree_when_nothing_was_re_measured(self):
        """They share the line resolution and the two-places rounding, so
        an untouched hourly line must produce identical numbers. A
        divergence here would mean the quote and the invoice disagree by
        rounding on every single job."""
        ew = self._make_ew()
        self._make_proposal(
            ew,
            status=ProposalStatus.CUSTOMER_APPROVED,
            quantity=Decimal("3.33"),
            unit_price=Decimal("77.77"),
            vat_pct=Decimal("9.00"),
        )
        recompute_quoted_totals(ew)
        recompute_final_amounts(ew)
        ew.refresh_from_db()
        self.assertEqual(ew.subtotal_amount, ew.final_subtotal_amount)
        self.assertEqual(ew.vat_amount, ew.final_vat_amount)
        self.assertEqual(ew.total_amount, ew.final_total_amount)


class QuotedTotalsFrozenAtApprovalTests(_QuotedTotalsFixture):
    """Every route that approves a proposal must leave the quote cache
    populated. Four routes, one helper — these tests are what says so."""

    def test_customer_approval_writes_the_quote_cache(self):
        ew = self._make_ew()
        proposal = self._make_proposal(ew)
        self.assertEqual(ew.total_amount, Decimal("0.00"))

        response = self._api(self.cust_user).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)
        self.assertEqual(ew.subtotal_amount, Decimal("484.00"))
        self.assertEqual(ew.vat_amount, Decimal("101.64"))
        self.assertEqual(ew.total_amount, Decimal("585.64"))

    def test_provider_override_approval_writes_the_quote_cache(self):
        ew = self._make_ew()
        proposal = self._make_proposal(ew)

        response = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {
                "to_status": ProposalStatus.CUSTOMER_APPROVED,
                "is_override": True,
                "override_reason": "Approved verbally on the phone.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        ew.refresh_from_db()
        self.assertEqual(ew.total_amount, Decimal("585.64"))

    def test_direct_publish_writes_the_quote_cache(self):
        self.company.provider_admin_may_quote_override_start = True
        self.company.save(
            update_fields=["provider_admin_may_quote_override_start"]
        )
        ew = self._make_ew(status=ExtraWorkStatus.UNDER_REVIEW)
        proposal = self._make_proposal(ew, status=ProposalStatus.DRAFT)

        response = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}"
            f"/direct-publish/",
            {"override_reason": "Customer confirmed in writing by email."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)
        self.assertEqual(ew.total_amount, Decimal("585.64"))

    def test_auto_start_after_pricing_writes_the_quote_cache(self):
        """Sprint 6B — SEND auto-approves and spawns, with no customer
        decision step. It reaches the same parent-advance helper, which
        is why one call site covers it."""
        ew = self._make_ew(
            status=ExtraWorkStatus.UNDER_REVIEW,
            request_intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
        )
        proposal = self._make_proposal(ew, status=ProposalStatus.DRAFT)

        apply_proposal_transition(proposal, self.admin, ProposalStatus.SENT)

        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposalStatus.CUSTOMER_APPROVED)
        ew.refresh_from_db()
        self.assertEqual(ew.total_amount, Decimal("585.64"))

    def test_rejection_does_NOT_write_the_quote_cache(self):
        """A rejected quote never became the price of anything. Writing
        it would put a number on a list beside a request nobody agreed
        to."""
        ew = self._make_ew()
        proposal = self._make_proposal(ew)

        response = self._api(self.cust_user).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {"to_status": ProposalStatus.CUSTOMER_REJECTED},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_REJECTED)
        self.assertEqual(ew.total_amount, Decimal("0.00"))


class QuotedTotalsBackfillCommandTests(_QuotedTotalsFixture):
    """The command the owner runs on crmtest. A `--dry-run` that writes,
    or a live run that misses the rows, is the whole point of having it."""

    def _run(self, *args) -> str:
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("backfill_quoted_totals", *args, stdout=out)
        return out.getvalue()

    def _stale_row(self) -> ExtraWorkRequest:
        """An EW in the exact shape crmtest has: an approved proposal and
        a quote cache still sitting at zero."""
        ew = self._make_ew(status=ExtraWorkStatus.CUSTOMER_APPROVED)
        self._make_proposal(ew, status=ProposalStatus.CUSTOMER_APPROVED)
        ew.refresh_from_db()
        self.assertEqual(ew.total_amount, Decimal("0.00"))
        return ew

    def test_dry_run_reports_the_row_and_writes_nothing(self):
        ew = self._stale_row()
        output = self._run("--dry-run")
        self.assertIn(str(ew.id), output)
        self.assertIn("585.64", output)
        self.assertIn("WOULD change", output)
        ew.refresh_from_db()
        self.assertEqual(ew.total_amount, Decimal("0.00"))

    def test_live_run_writes_the_row(self):
        ew = self._stale_row()
        output = self._run()
        self.assertIn("Wrote 1 row", output)
        ew.refresh_from_db()
        self.assertEqual(ew.total_amount, Decimal("585.64"))

    def test_a_row_with_a_nonzero_total_is_left_alone_by_default(self):
        """The command repairs an ABSENCE. A total someone already put
        there is not its to arbitrate."""
        ew = self._stale_row()
        ew.total_amount = Decimal("10.00")
        ew.save(update_fields=["total_amount"])

        self._run()
        ew.refresh_from_db()
        self.assertEqual(ew.total_amount, Decimal("10.00"))

        # ...and --include-nonzero is the escape hatch for exactly that.
        self._run("--include-nonzero")
        ew.refresh_from_db()
        self.assertEqual(ew.total_amount, Decimal("585.64"))

    def test_a_row_with_no_approved_proposal_is_never_touched(self):
        ew = self._make_ew()
        self._make_proposal(ew, status=ProposalStatus.SENT)
        self._run()
        ew.refresh_from_db()
        self.assertEqual(ew.total_amount, Decimal("0.00"))


class QuotedTotalsReadEndpointTests(_QuotedTotalsFixture):
    """The columns are only worth writing if the API hands them over —
    this is the surface the lists and the CSV export actually read."""

    def test_detail_endpoint_reports_the_frozen_quote(self):
        ew = self._make_ew()
        proposal = self._make_proposal(ew)
        self._api(self.cust_user).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )

        response = self._api(self.admin).get(f"/api/extra-work/{ew.id}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["total_amount"], "585.64")
        self.assertEqual(response.data["subtotal_amount"], "484.00")
        self.assertEqual(response.data["vat_amount"], "101.64")


class QuotedTotalsUnpricedRouteTests(_QuotedTotalsFixture):
    """A guard on the shape that made this bug possible in the first
    place: a request with no priced lines at all must resolve to zero
    rather than raise, because `active_priced_lines` falls back through
    three routes and only one of them is the proposal."""

    def test_no_lines_anywhere_resolves_to_zero(self):
        ew = self._make_ew()
        self.assertEqual(
            quoted_totals(ew),
            (Decimal("0.00"), Decimal("0.00"), Decimal("0.00")),
        )
