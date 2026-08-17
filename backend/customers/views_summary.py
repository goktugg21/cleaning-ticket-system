"""
Sprint 153 §2.4 — the customer overview dashboard read.

GET /api/customers/<id>/summary/

ONE endpoint instead of the overview page firing six list calls and
counting array lengths. Every number is scoped to the one customer AND
independently re-scoped to the ACTOR, so a COMPANY_ADMIN never sees a
count that includes rows they could not open.

Three rules hold for every block below:

  1. Scope is resolved through the module's OWN scoping helper
     (`scope_tickets_for`, `scope_extra_work_for`, `scope_invoices_for` /
     `scope_customer_invoices_for`) — never re-derived here.
  2. A module the caller cannot read at all degrades to `null`, not to
     `0` and not to a 500. `0` means "you can see this module and it is
     empty"; `null` means "this is not yours to see". The frontend
     renders `null` as an unlinked em dash.
  3. Every block is individually wrapped, so one module raising cannot
     take the whole page down.

"Terminal" ticket statuses come from `tickets.models
.TERMINAL_TICKET_STATUSES` — the exported frozenset that
`views_sub_tasks` and `views_staff_assignments` already share. See
`_open_ticket_qs` for why that module, and not `state_machine`, is the
authority.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive
from accounts.scoping import scope_customers_for, scope_tickets_for

from .models import Customer


# Roles that can reach the provider-side invoicing module at all.
# Mirrors the role branches of `invoicing.selectors.scope_invoices_for`,
# which returns `.none()` for everyone else — indistinguishable from
# "this customer has no invoices" unless we check the role first.
_INVOICE_PROVIDER_ROLES = (
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
    UserRole.BUILDING_MANAGER,
)


class CustomerSummaryView(APIView):
    """Read-only operational counts for one customer.

    Permission is deliberately the SAME gate as `GET /api/customers/<id>/`:
    `IsAuthenticatedAndActive` plus the `scope_customers_for` queryset.
    A customer outside the caller's scope 404s — it must not 403, because
    a 403 would confirm the row exists (H-1).
    """

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, customer_id: int, *args, **kwargs):
        customer = get_object_or_404(
            scope_customers_for(request.user), pk=customer_id
        )

        data = {}
        data.update(self._customer_counts(customer))
        data.update(self._pricing_counts(request.user, customer))
        data.update(self._ticket_counts(request.user, customer))
        data.update(self._extra_work_counts(request.user, customer))
        data.update(self._invoice_totals(request.user, customer))
        return Response(data, status=status.HTTP_200_OK)

    # -- customer-local counts ------------------------------------------
    #
    # These three are the same numbers the list table shows. They are
    # properties of the customer row itself: reaching the customer at all
    # (the get_object_or_404 above) is the only gate they need.
    @staticmethod
    def _customer_counts(customer: Customer) -> dict:
        try:
            aggregated = (
                Customer.objects.filter(pk=customer.pk)
                .annotate(
                    n_buildings=Count("building_memberships", distinct=True),
                    n_users=Count("user_memberships", distinct=True),
                    n_contacts=Count("contacts", distinct=True),
                )
                .values("n_buildings", "n_users", "n_contacts")
                .first()
            ) or {}
            return {
                "linked_building_count": aggregated.get("n_buildings"),
                "user_count": aggregated.get("n_users"),
                "contact_count": aggregated.get("n_contacts"),
            }
        except Exception:  # pragma: no cover - defensive
            return {
                "linked_building_count": None,
                "user_count": None,
                "contact_count": None,
            }

    # -- pricing ---------------------------------------------------------
    @staticmethod
    def _pricing_counts(user, customer: Customer) -> dict:
        """Active contract-price rows (`CustomerServicePrice`).

        Counts what the Pricing sub-page manages, so the chip and the
        page it links to agree. Provider-side surface only: the pricing
        list view is `IsSuperAdminOrCompanyAdminForCustomerProvider`, so
        a customer-side or staff caller gets `null`, not `0`.
        """
        if user.role not in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN):
            return {"pricing_rule_count": None}
        try:
            from extra_work.models import CustomerServicePrice

            if user.role == UserRole.COMPANY_ADMIN:
                from companies.models import CompanyUserMembership

                in_company = CompanyUserMembership.objects.filter(
                    user=user, company_id=customer.company_id
                ).exists()
                if not in_company:
                    return {"pricing_rule_count": None}
            return {
                "pricing_rule_count": CustomerServicePrice.objects.filter(
                    customer=customer, is_active=True
                ).count()
            }
        except Exception:  # pragma: no cover - defensive
            return {"pricing_rule_count": None}

    # -- tickets ---------------------------------------------------------
    @staticmethod
    def _ticket_counts(user, customer: Customer) -> dict:
        """Total + open tickets for this customer, in the actor's scope.

        `TERMINAL_TICKET_STATUSES` is imported rather than re-listed. It
        lives in `tickets.models`, NOT in `tickets.state_machine`: the
        state machine's only terminal set is a two-element local
        (`{APPROVED, CLOSED}`) inside the extra-work auto-sync helper,
        which is a narrower question ("has this ticket's work finished")
        than "has this ticket left every operational queue". The exported
        four-element frozenset in `tickets.models` is the one
        `views_sub_tasks` and `views_staff_assignments` already share,
        and it is the definition an operator means by "open".
        """
        try:
            from tickets.models import TERMINAL_TICKET_STATUSES

            scoped = scope_tickets_for(user).filter(customer=customer)
            terminal = [str(s) for s in TERMINAL_TICKET_STATUSES]
            return {
                "ticket_count": scoped.count(),
                "open_ticket_count": scoped.exclude(
                    status__in=terminal
                ).count(),
            }
        except Exception:  # pragma: no cover - defensive
            return {"ticket_count": None, "open_ticket_count": None}

    # -- extra work ------------------------------------------------------
    @staticmethod
    def _extra_work_counts(user, customer: Customer) -> dict:
        """Total + open extra-work requests, in the actor's scope.

        STAFF gets `null`: `scope_extra_work_for` returns `.none()` for
        STAFF by deliberate privacy design (they never reach a parent EW
        record), and reporting `0` would misrepresent that as "there is
        no extra work".
        """
        if user.role == UserRole.STAFF:
            return {"extra_work_count": None, "open_extra_work_count": None}
        try:
            from extra_work.scoping import scope_extra_work_for
            from extra_work.views import EXTRA_WORK_TERMINAL_STATUSES

            scoped = scope_extra_work_for(user).filter(customer=customer)
            return {
                "extra_work_count": scoped.count(),
                "open_extra_work_count": scoped.exclude(
                    status__in=list(EXTRA_WORK_TERMINAL_STATUSES)
                ).count(),
            }
        except Exception:  # pragma: no cover - defensive
            return {"extra_work_count": None, "open_extra_work_count": None}

    # -- invoices --------------------------------------------------------
    @staticmethod
    def _invoice_totals(user, customer: Customer) -> dict:
        """Outstanding invoices for this customer.

        "Outstanding" = SENT, not itself a reversal, and not reversed by
        a later credit note. The `invoice__reversed_by__isnull=True`
        liveness predicate is the one CLAUDE.md §2A says to preserve;
        excluding `is_reversal` rows on top of it stops a SENT credit
        note from subtracting a total whose original has ALREADY been
        dropped from the set.

        The amount is `Invoice.total_amount` — the frozen money cache
        that `invoicing/models.py` calls "the SOURCE OF TRUTH once
        issued". It is not recomputed here; recomputing it from the
        extra-work earned rule would contradict that freeze, which is
        the whole point of issuing an invoice.

        Scope: provider roles read through `scope_invoices_for`; a
        CUSTOMER_USER reads their own SENT invoices through the separate
        `scope_customer_invoices_for`. STAFF reach neither module and get
        `null`.
        """
        try:
            from invoicing.models import Invoice
            from invoicing.selectors import (
                scope_customer_invoices_for,
                scope_invoices_for,
            )

            if user.role in _INVOICE_PROVIDER_ROLES:
                scoped = scope_invoices_for(user).filter(status=Invoice.Status.SENT)
            elif user.role == UserRole.CUSTOMER_USER:
                # This helper already pins status=SENT + membership scope.
                scoped = scope_customer_invoices_for(user)
            else:
                return {"unpaid_invoice_count": None, "unpaid_invoice_total": None}

            outstanding = scoped.filter(
                customer=customer,
                is_reversal=False,
                reversed_by__isnull=True,
            )
            aggregated = outstanding.aggregate(
                n=Count("id"), total=Sum("total_amount")
            )
            total = aggregated["total"] or Decimal("0.00")
            return {
                "unpaid_invoice_count": aggregated["n"] or 0,
                # Decimal string, so the frontend formats it without ever
                # putting money through a float.
                "unpaid_invoice_total": f"{total:.2f}",
            }
        except Exception:  # pragma: no cover - defensive
            return {"unpaid_invoice_count": None, "unpaid_invoice_total": None}
