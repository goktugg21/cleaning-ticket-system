"""
Sprint 160 — the Invoice Preview endpoint.

    GET /api/contracts/<int:contract_id>/forecast/?year=2026

A READ. It computes what WOULD be invoiced and writes nothing — no
`Invoice`, no `InvoiceLine`, no state. Sprint 158 is what turns a due
row into a real invoice; keeping this endpoint a pure calculation is
what makes that a small step instead of a rewrite.

Only GET is routed. That is not an oversight: there is no POST here to
"generate" anything, and adding one belongs to the sprint that owns
`invoicing/`.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from .billing import build_forecast
from .permissions import IsContractReader
from .serializers import ContractForecastSerializer
from .views_common import parse_int_param
from .views_revisions import get_scoped_contract


# How far either side of the contract's own life the year stepper may
# roam. A forecast for 1804 is not a question anyone is asking, and an
# unbounded year lets a caller walk the period generator for nothing.
MIN_YEAR = 1970
MAX_YEAR = 2999


class ContractForecastView(APIView):
    """GET the planned invoices for one contract and one year.

    `?year=` defaults to the current year. An unparseable or
    out-of-range year falls back to the default rather than 500ing —
    the year stepper is a UI affordance, and a bad value should show
    the current year, not an error page.
    """

    permission_classes = [IsContractReader]

    def get(self, request, contract_id):
        contract = get_scoped_contract(request.user, contract_id)
        year = parse_int_param(request.query_params.get("year"))
        if year is None or not (MIN_YEAR <= year <= MAX_YEAR):
            year = timezone.localdate().year
        forecast = build_forecast(contract, year)
        return Response(ContractForecastSerializer(forecast).data)
