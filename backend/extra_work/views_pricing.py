"""
Sprint 28 Batch 5 — per-customer pricing CRUD endpoints
(`CustomerServicePrice`).

Routes (registered in `customers/urls.py`, mounted under
`/api/customers/<customer_id>/pricing/`):

  GET / POST    /api/customers/<customer_id>/pricing/
  GET / PATCH / DELETE  /api/customers/<customer_id>/pricing/<int:price_id>/

Permission gate: `IsSuperAdminOrCompanyAdminForCompany`. The object
check resolves on the Customer model — SUPER_ADMIN passes for any
customer; COMPANY_ADMIN passes only for customers inside their own
provider company; BUILDING_MANAGER / STAFF / CUSTOMER_USER never
reach the view.

ID-smuggling defence: the detail view re-scopes the lookup BY the
URL-bound customer (`customer=customer`). A SUPER_ADMIN asking for
price-B under customer-A's URL therefore 404s instead of silently
acting on the other customer's row — the same pattern Batch 4 used
for Contact.
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response

from accounts.permissions import IsSuperAdminOrCompanyAdminForCompany
from config.pagination import UnboundedPagination
from customers.models import Customer

from .models import CustomerServicePrice
from .serializers_catalog import CustomerServicePriceSerializer


class CustomerServicePriceListCreateView(generics.ListCreateAPIView):
    """GET (list) + POST (create) at
    /api/customers/<customer_id>/pricing/."""

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]
    serializer_class = CustomerServicePriceSerializer
    pagination_class = UnboundedPagination

    def _get_customer(self):
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        # has_object_permission resolves on the Customer model. A
        # COMPANY_ADMIN acting on a customer outside their own
        # provider company gets 403 here.
        self.check_object_permissions(self.request, customer)
        return customer

    def get_queryset(self):
        customer = self._get_customer()
        qs = (
            CustomerServicePrice.objects.filter(customer=customer)
            .select_related("service", "service__category", "customer")
        )
        service = self.request.query_params.get("service")
        if service:
            try:
                qs = qs.filter(service_id=int(service))
            except (TypeError, ValueError):
                qs = qs.none()
        # Default ordering: latest valid_from first so the active row
        # is at the top of the list page (mirrors the resolver's
        # preference order).
        return qs.order_by("-valid_from", "-id")

    def perform_create(self, serializer):
        customer = self._get_customer()
        serializer.save(customer=customer)


class CustomerServicePriceDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE at
    /api/customers/<customer_id>/pricing/<int:price_id>/."""

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]
    serializer_class = CustomerServicePriceSerializer

    def _get_customer(self):
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        self.check_object_permissions(self.request, customer)
        return customer

    def get_object(self):
        customer = self._get_customer()
        # Defence-in-depth: scope the price lookup BY the URL-bound
        # customer so a price belonging to another customer is a
        # clean 404, never a silent cross-customer operation.
        price = get_object_or_404(
            CustomerServicePrice,
            pk=self.kwargs["price_id"],
            customer=customer,
        )
        return price

    def delete(self, request, *args, **kwargs):
        price = self.get_object()
        price.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
