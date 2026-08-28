"""
WP-1 G4 — the billing-month guard's HTTP surface.

    GET /api/invoices/at-risk/

Read-only, provider-operator gated with the same double gate the rest
of the invoicing surface uses (`_forbid_non_operator`'s underlying
check, reused rather than re-implemented), scoped through
`accounts.scoping.scope_customers_for` — the exact scope the /due/
panel next to it reads through, so the two panels can never disagree
about whose customers they describe.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAuthenticatedAndActive
from accounts.scoping import scope_customers_for

# Reuse (do NOT re-implement) — the same operator predicate
# `invoicing/views.py` gates every invoice action on.
from extra_work.views import _is_provider_operator

from .at_risk import at_risk_groups


class BillingMonthAtRiskView(APIView):
    """The "Deze factuurmaand loopt risico" list. A read; it can make a
    human act, it cannot act itself."""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, *args, **kwargs):
        if not _is_provider_operator(request.user):
            return Response(
                {"detail": "Only provider operators can read this."},
                status=status.HTTP_403_FORBIDDEN,
            )
        customers = scope_customers_for(request.user).filter(is_active=True)
        return Response(at_risk_groups(customers), status=status.HTTP_200_OK)
