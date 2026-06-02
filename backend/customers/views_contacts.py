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
from django.db.models import Exists, OuterRef, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import generics, status, views
from rest_framework.response import Response

from accounts.models import UserRole
from accounts.permissions import (
    IsSuperAdminOrCompanyAdminForCompany,
    IsSuperAdminOrCompanyAdminOrBuildingManagerReadCustomer,
)
from accounts.scoping import building_ids_for
from config.pagination import UnboundedPagination

from .models import Contact, ContactBuildingLink, Customer
from .promotion import PromotionError, promote_contact
from .serializers_contacts import ContactSerializer


def bm_allowed_building_ids(user):
    """Sprint 14G — the building-id set a reader may see contact building
    associations for, or None when the reader sees everything.

    Only BUILDING_MANAGER is narrowed: a BM can read a multi-building
    customer's contacts (Sprint 28 Batch 12) but must NOT see building
    associations for buildings outside `building_ids_for(BM)`, nor
    contacts that are linked ONLY to buildings they do not manage.
    SUPER_ADMIN / COMPANY_ADMIN return None (no narrowing). CUSTOMER_USER
    / STAFF never reach the contact views (the permission gate rejects
    them), so they are not special-cased here.
    """
    if getattr(user, "role", None) == UserRole.BUILDING_MANAGER:
        return set(building_ids_for(user))
    return None


def scope_contacts_for_reader(queryset, user):
    """Narrow a contact queryset for a BUILDING_MANAGER reader.

    Keeps: contacts with NO building links (customer-level phone-book
    entries — no association to leak, and BM read access to them is the
    existing Batch-12 behaviour) AND contacts with at least one link in
    the manager's allowed buildings. Hides: contacts that ARE
    building-linked but to NONE of the manager's buildings. No-op for
    SUPER_ADMIN / COMPANY_ADMIN.
    """
    allowed = bm_allowed_building_ids(user)
    if allowed is None:
        return queryset
    has_any_link = ContactBuildingLink.objects.filter(contact=OuterRef("pk"))
    has_managed_link = ContactBuildingLink.objects.filter(
        contact=OuterRef("pk"), building_id__in=allowed
    )
    return queryset.annotate(
        _has_any_link=Exists(has_any_link),
        _has_managed_link=Exists(has_managed_link),
    ).filter(Q(_has_managed_link=True) | Q(_has_any_link=False))


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
        qs = (
            Contact.objects.filter(customer=customer)
            .select_related("building")
            .order_by("full_name", "id")
        )
        # Sprint 14G — narrow contacts linked only to buildings a
        # BUILDING_MANAGER does not manage (no-op for SA / CA).
        return scope_contacts_for_reader(qs, self.request.user)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # Pass the URL-bound customer down to the serializer's validate()
        # so it can enforce the customer↔building membership check on
        # create. On update, the serializer reads instance.customer.
        try:
            context["customer"] = self._get_customer()
        except Exception:  # pragma: no cover — defensive
            pass
        # Sprint 14G — the BM building-id allow-list the serializer uses
        # to narrow `linked_building_ids` + the legacy `building` field.
        context["bm_allowed_building_ids"] = bm_allowed_building_ids(
            self.request.user
        )
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
        # Sprint 14G — a BUILDING_MANAGER must not retrieve a contact that
        # is building-linked ONLY to buildings they do not manage (it
        # would otherwise leak both the contact and its associations). A
        # contact with no links at all stays visible (existing Batch-12
        # behaviour). 404 (not 403) so the contact's existence is not
        # revealed across building scopes. No-op for SA / CA.
        allowed = bm_allowed_building_ids(self.request.user)
        if allowed is not None:
            has_any_link = contact.building_links.exists()
            has_managed_link = contact.building_links.filter(
                building_id__in=allowed
            ).exists()
            if has_any_link and not has_managed_link:
                raise Http404("Contact not found.")
        return contact

    def get_serializer_context(self):
        context = super().get_serializer_context()
        try:
            context["customer"] = self._get_customer()
        except Exception:  # pragma: no cover — defensive
            pass
        # Sprint 14G — BM building-id allow-list for serializer narrowing.
        context["bm_allowed_building_ids"] = bm_allowed_building_ids(
            self.request.user
        )
        return context

    def delete(self, request, *args, **kwargs):
        contact = self.get_object()
        contact.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CustomerContactPromoteView(views.APIView):
    """Sprint 12B — POST /api/customers/<customer_id>/contacts/<contact_id>/promote-to-user/

    Promotes a phone-book Contact into an authenticated customer User.

    Provider-only gate (`IsSuperAdminOrCompanyAdminForCompany`):
    SUPER_ADMIN passes everywhere; COMPANY_ADMIN passes only for
    customers inside their own provider company; BUILDING_MANAGER /
    STAFF / CUSTOMER_USER get 403.

    Optional body fields:
      * `access_role` — desired CUBA access role (defaults to
        CUSTOMER_USER). Validated by the service.
      * `building_ids` — explicit list of building ids to grant access
        on. When omitted the service uses the union of the contact's
        building links + the legacy single-building anchor.

    Two modes:
      * INVITE (no matching User) → 201, body carries
        `{"mode": "invited", "invitation_id": ...}`. The invitation
        email is sent AFTER the service's atomic commit.
      * LINK (matching active CUSTOMER_USER) → 200, body carries
        `{"mode": "linked", "user_id": ...}`.

    The `contact` projection (ContactSerializer) is included in both
    response bodies.
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]

    def post(self, request, customer_id, contact_id):
        customer = get_object_or_404(Customer, pk=customer_id)
        # COMPANY_ADMIN acting on a customer outside their own provider
        # company → 403.
        self.check_object_permissions(request, customer)
        # ID smuggling defence: scope the lookup BY customer so a
        # cross-customer contact id yields 404, not a silent operation.
        contact = get_object_or_404(Contact, pk=contact_id, customer=customer)

        access_role = request.data.get("access_role")
        building_ids = request.data.get("building_ids")
        # Sprint 12C — optional phone supplied at promote time. When
        # absent the service falls back to the contact's stored phone;
        # either way a valid NL phone is REQUIRED to promote (the
        # service raises `contact_phone_required` / `contact_phone_invalid`).
        phone = request.data.get("phone")
        if building_ids is not None:
            if not isinstance(building_ids, list) or not all(
                isinstance(b, int) and not isinstance(b, bool)
                for b in building_ids
            ):
                return Response(
                    {"building_ids": "Must be a list of building ids."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            result = promote_contact(
                customer=customer,
                contact=contact,
                actor=request.user,
                access_role=access_role,
                building_ids=building_ids,
                phone=phone,
            )
        except PromotionError as exc:
            return Response(
                {"detail": str(exc), "code": exc.code},
                status=exc.status_code,
            )

        # Invite mode: send the email AFTER the service's atomic commit
        # (mirror accounts.views_invitations.create). A re-promote that
        # found a still-pending invitation does NOT re-send.
        raw_token = result.pop("_raw_token", None)
        if (
            result.get("mode") == "invited"
            and raw_token
            and result.get("detail") != "already_invited"
        ):
            from django.conf import settings

            from accounts.invitations import Invitation
            from notifications.services import send_invitation_email

            inv = Invitation.objects.get(pk=result["invitation_id"])
            accept_url = (
                settings.INVITATION_ACCEPT_FRONTEND_URL.format(token=raw_token)
                if settings.INVITATION_ACCEPT_FRONTEND_URL
                else ""
            )
            send_invitation_email(inv, raw_token=raw_token, accept_url=accept_url)

        contact.refresh_from_db()
        body = {
            **result,
            "contact": ContactSerializer(
                contact, context={"request": request, "customer": customer}
            ).data,
        }
        status_code = (
            status.HTTP_201_CREATED
            if result.get("mode") == "invited"
            else status.HTTP_200_OK
        )
        return Response(body, status=status_code)
