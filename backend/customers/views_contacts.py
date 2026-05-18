"""
Sprint 28 Batch 4 — Contact (customer phone-book) CRUD endpoints.

Routes (registered in `customers/urls.py`):

  GET    /api/customers/<customer_id>/contacts/
  POST   /api/customers/<customer_id>/contacts/
  GET    /api/customers/<customer_id>/contacts/<contact_id>/
  PATCH  /api/customers/<customer_id>/contacts/<contact_id>/
  DELETE /api/customers/<customer_id>/contacts/<contact_id>/

Permission gate is
`IsSuperAdminOrCompanyAdminOrBuildingManagerReadCustomer` — the same
gate used by the existing customer membership endpoints widened in
Sprint 28 Batch 12 to admit BUILDING_MANAGER on **safe methods only**
(GET list + GET detail) when the URL-bound customer is in
`scope_customers_for(BM)`. SUPER_ADMIN passes everything;
COMPANY_ADMIN passes only for customers inside their own provider
company; BM gets read-only access scoped to their assigned
buildings; STAFF and CUSTOMER_USER never reach the view.

Unsafe methods (POST / PATCH / DELETE) still gate to
SUPER_ADMIN + COMPANY_ADMIN only; BM gets 403 on every write path.

ID smuggling defence: the detail view re-validates that
`contact.customer_id == customer.id`. A SUPER_ADMIN could otherwise
target a contact from another customer by URL-mismatch
(`/customers/<A>/contacts/<id-of-B-contact>/`). On mismatch we return
404 — never silently mutate the other customer's row.
"""
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response

from accounts.permissions import (
    IsSuperAdminOrCompanyAdminOrBuildingManagerReadCustomer,
)
from config.pagination import UnboundedPagination

from .models import Contact, Customer
from .serializers_contacts import ContactSerializer


class CustomerContactListCreateView(generics.ListCreateAPIView):
    """GET list + POST create at /api/customers/<customer_id>/contacts/."""

    # Sprint 28 Batch 12 — BUILDING_MANAGER may GET (list/detail)
    # contacts when the URL-bound customer is in their scope; unsafe
    # methods still require admin (the gate's has_permission rejects
    # BM on POST/PATCH/DELETE).
    permission_classes = [
        IsSuperAdminOrCompanyAdminOrBuildingManagerReadCustomer
    ]
    serializer_class = ContactSerializer
    pagination_class = UnboundedPagination

    def _get_customer(self):
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        # has_object_permission resolves on the Customer model — this
        # rejects a COMPANY_ADMIN acting on a customer outside their own
        # provider company with 403.
        self.check_object_permissions(self.request, customer)
        return customer

    def get_queryset(self):
        customer = self._get_customer()
        return (
            Contact.objects.filter(customer=customer)
            .select_related("building")
            .order_by("full_name", "id")
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # Pass the URL-bound customer down to the serializer's validate()
        # so it can enforce the customer↔building membership check on
        # create. On update, the serializer reads instance.customer.
        try:
            context["customer"] = self._get_customer()
        except Exception:  # pragma: no cover — defensive
            pass
        return context

    def perform_create(self, serializer):
        customer = self._get_customer()
        serializer.save(customer=customer)


class CustomerContactDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE at /api/customers/<customer_id>/contacts/<contact_id>/."""

    # Sprint 28 Batch 12 — BUILDING_MANAGER gets GET only (read scoped
    # to their assigned-building customers); PATCH/DELETE still 403.
    permission_classes = [
        IsSuperAdminOrCompanyAdminOrBuildingManagerReadCustomer
    ]
    serializer_class = ContactSerializer

    def _get_customer(self):
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        self.check_object_permissions(self.request, customer)
        return customer

    def get_object(self):
        customer = self._get_customer()
        # Defence-in-depth: even SUPER_ADMIN may not target a contact
        # belonging to a different customer through this URL. We scope
        # the lookup BY customer so the mismatch yields 404, not a
        # silent cross-customer operation.
        contact = get_object_or_404(
            Contact, pk=self.kwargs["contact_id"], customer=customer
        )
        return contact

    def get_serializer_context(self):
        context = super().get_serializer_context()
        try:
            context["customer"] = self._get_customer()
        except Exception:  # pragma: no cover — defensive
            pass
        return context

    def delete(self, request, *args, **kwargs):
        contact = self.get_object()
        contact.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
