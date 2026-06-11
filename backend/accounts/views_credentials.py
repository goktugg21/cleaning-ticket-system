"""
M2 P3 — admin endpoints for staff credentials + custom profile
properties (SoT Addendum A.3), mounted under the existing
`/api/users/<user_id>/` prefix alongside the Sprint 24A staff-* views.

  /api/users/<user_id>/credentials/                       GET, POST
  /api/users/<user_id>/credentials/<pk>/                  PATCH, DELETE
  /api/users/<user_id>/credentials/<pk>/download/         GET
  /api/users/<user_id>/credentials/<pk>/grants/           GET, POST
  /api/users/<user_id>/credentials/<pk>/grants/<grant_id>/  DELETE
  /api/users/<user_id>/properties/...                     (same shape)

Gates:
  - credentials/* — `CanManageStaffMember` unchanged (SA / PA only,
    target must be STAFF, company-scoped via `_user_in_actor_company`).
  - properties/*  — `CanManageUserProperties` (SA / PA, any target user
    in company scope; staff AND customer users carry properties).
  - The admin endpoints are a pure management surface: customer-side
    roles never pass. The ONLY customer-facing reads are the ticket
    payload (tickets/serializers.py `_assigned_staff_payload`) and the
    download endpoints below, which admit a CUSTOMER_USER strictly
    through the resolver's DOCUMENT sub-rule.

Download gating (404 — never 403 — when the gate fails, mirroring the
ticket-attachment download's no-existence-leak rule):
  - provider viewers: `credential_document_visible_to_user` (the
    resolver table) AND company scope (H-1 — the resolver is a pure
    role/field table; without the extra scope check a COMPANY_ADMIN or
    BUILDING_MANAGER of another provider could fetch this tenant's
    documents by URL).
  - CUSTOMER_USER viewers: the document sub-rule must pass for a
    customer they hold a CustomerUserMembership for — the context
    customer is resolved from their memberships against the grant rows.

Audit: all writes are covered by the dedicated audit/signals.py
handlers (CREATE/DELETE + tracked-field UPDATE diffs, HIGH severity on
sensitive-visibility changes). The views write no AuditLog rows
directly. Downloads (reads) are deliberately not audited — same
no-write-on-read default as ticket attachments.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response

from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
from companies.models import CompanyUserMembership
from customers.models import Customer, CustomerUserMembership

from .models import (
    CredentialCustomerVisibility,
    CustomProfileProperty,
    PropertyCustomerVisibility,
    StaffCredential,
    StaffProfile,
    User,
    UserRole,
)
from .permissions import (
    CanManageStaffMember,
    CanManageUserProperties,
    IsAuthenticatedAndActive,
)
from .serializers_credentials import (
    CredentialGrantSerializer,
    CustomProfilePropertySerializer,
    CustomProfilePropertyWriteSerializer,
    PropertyGrantSerializer,
    StaffCredentialSerializer,
    StaffCredentialWriteSerializer,
)
from .visibility import (
    credential_document_visible_to_user,
    property_document_visible_to_user,
)


def _resolve_target_staff_profile(view, request, user_id):
    """Resolve the URL-bound STAFF user + profile and run the
    management gate. Mirrors views_staff._get_target_staff (incl. the
    auto-create of a missing profile). Returns (early_response, profile)."""
    target = get_object_or_404(User, pk=user_id, deleted_at__isnull=True)
    if target.role != UserRole.STAFF:
        return (
            Response(
                {"detail": "User is not a STAFF user."},
                status=status.HTTP_400_BAD_REQUEST,
            ),
            None,
        )
    view.check_object_permissions(request, target)
    profile, _ = StaffProfile.objects.get_or_create(user=target)
    return None, profile


def _resolve_target_user(view, request, user_id):
    """Resolve the URL-bound user (ANY role — properties live on staff
    and customer users alike) and run the management gate."""
    target = get_object_or_404(User, pk=user_id, deleted_at__isnull=True)
    view.check_object_permissions(request, target)
    return target


def _customer_in_actor_scope(actor, customer) -> bool:
    """Grant-target scope: the customer must belong to the actor's
    provider-company scope. SUPER_ADMIN passes any customer."""
    if actor.role == UserRole.SUPER_ADMIN:
        return True
    return CompanyUserMembership.objects.filter(
        user=actor, company_id=customer.company_id
    ).exists()


def _target_linked_to_companies(target_user, company_ids) -> bool:
    """The `_user_in_actor_company` union (CompanyUserMembership /
    BuildingManagerAssignment / CustomerUserMembership /
    BuildingStaffVisibility), parameterized by an explicit company-id
    set — written as a sibling rather than modifying the original,
    because the BM download path resolves its companies via building
    assignments, not CompanyUserMembership."""
    if not company_ids:
        return False
    if CompanyUserMembership.objects.filter(
        user=target_user, company_id__in=company_ids
    ).exists():
        return True
    if BuildingManagerAssignment.objects.filter(
        user=target_user, building__company_id__in=company_ids
    ).exists():
        return True
    if CustomerUserMembership.objects.filter(
        user=target_user, customer__company_id__in=company_ids
    ).exists():
        return True
    if BuildingStaffVisibility.objects.filter(
        user=target_user, building__company_id__in=company_ids
    ).exists():
        return True
    return False


def _provider_download_scope_ok(actor, target_user) -> bool:
    """H-1 company scoping layered ON TOP of the resolver's document
    sub-rule for provider viewers of the download endpoints."""
    if actor.role == UserRole.SUPER_ADMIN:
        return True
    if actor.role == UserRole.COMPANY_ADMIN:
        from .scoping import _user_in_actor_company

        return _user_in_actor_company(actor, target_user)
    if actor.role == UserRole.BUILDING_MANAGER:
        company_ids = list(
            BuildingManagerAssignment.objects.filter(user=actor).values_list(
                "building__company_id", flat=True
            )
        )
        return _target_linked_to_companies(target_user, company_ids)
    return False


def _grant_create(request, *, parent_field, parent, grant_model, read_serializer):
    """Shared grant-create body: validate customer_id, scope-check the
    target customer, idempotent on duplicates, surface model
    ValidationErrors (EU-ID block, ceiling rule, staff-owned rule) as
    400 rather than 500."""
    customer_id = request.data.get("customer_id")
    if not customer_id:
        return Response(
            {"customer_id": "This field is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        customer_id = int(customer_id)
    except (TypeError, ValueError):
        return Response(
            {"customer_id": "A valid integer is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    customer = get_object_or_404(Customer, pk=customer_id)
    if not _customer_in_actor_scope(request.user, customer):
        # Mirrors the staff-visibility cross-company guard's 400 shape.
        return Response(
            {"customer_id": "Customer is not in your company."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    existing = grant_model.objects.filter(
        **{parent_field: parent, "customer": customer}
    ).first()
    if existing is not None:
        return Response(
            read_serializer(existing).data, status=status.HTTP_200_OK
        )
    grant = grant_model(**{parent_field: parent, "customer": customer})
    try:
        grant.full_clean()
    except DjangoValidationError as exc:
        detail = getattr(exc, "message_dict", None) or {"detail": exc.messages}
        return Response(detail, status=status.HTTP_400_BAD_REQUEST)
    grant.save()
    return Response(read_serializer(grant).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Credentials (target: STAFF users; gate: CanManageStaffMember)
# ---------------------------------------------------------------------------


class UserCredentialListCreateView(generics.GenericAPIView):
    """GET / POST /api/users/<user_id>/credentials/"""

    permission_classes = [CanManageStaffMember]

    def get(self, request, user_id):
        early, profile = _resolve_target_staff_profile(self, request, user_id)
        if early is not None:
            return early
        credentials = (
            profile.credentials.select_related("staff_profile")
            .prefetch_related("customer_grants__customer")
            .order_by("credential_type", "id")
        )
        return Response(
            StaffCredentialSerializer(
                credentials, many=True, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request, user_id):
        early, profile = _resolve_target_staff_profile(self, request, user_id)
        if early is not None:
            return early
        serializer = StaffCredentialWriteSerializer(
            data=request.data,
            context={"request": request, "staff_profile": profile},
        )
        serializer.is_valid(raise_exception=True)
        credential = serializer.save()
        return Response(
            StaffCredentialSerializer(
                credential, context={"request": request}
            ).data,
            status=status.HTTP_201_CREATED,
        )


class UserCredentialDetailView(generics.GenericAPIView):
    """PATCH / DELETE /api/users/<user_id>/credentials/<pk>/"""

    permission_classes = [CanManageStaffMember]

    def _resolve(self, request, user_id, pk):
        early, profile = _resolve_target_staff_profile(self, request, user_id)
        if early is not None:
            return early, None
        credential = get_object_or_404(
            StaffCredential, pk=pk, staff_profile=profile
        )
        return None, credential

    def patch(self, request, user_id, pk):
        early, credential = self._resolve(request, user_id, pk)
        if early is not None:
            return early
        serializer = StaffCredentialWriteSerializer(
            credential,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        credential = serializer.save()
        return Response(
            StaffCredentialSerializer(
                credential, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )

    def delete(self, request, user_id, pk):
        early, credential = self._resolve(request, user_id, pk)
        if early is not None:
            return early
        credential.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserCredentialDownloadView(generics.GenericAPIView):
    """GET /api/users/<user_id>/credentials/<pk>/download/

    Resolver-gated FileResponse. 404 (never 403) when the gate fails —
    the document's existence must not leak (mirrors the ticket-
    attachment download)."""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, user_id, pk):
        credential = get_object_or_404(
            StaffCredential.objects.select_related("staff_profile__user"),
            pk=pk,
            staff_profile__user_id=user_id,
            staff_profile__user__deleted_at__isnull=True,
        )
        viewer = request.user
        if viewer.role == UserRole.CUSTOMER_USER:
            # Resolve the context customer from the viewer's memberships
            # against the grant rows: the document sub-rule must pass for
            # at least one customer the viewer belongs to.
            allowed = any(
                credential_document_visible_to_user(
                    credential, viewer, membership.customer
                )
                for membership in CustomerUserMembership.objects.filter(
                    user=viewer
                ).select_related("customer")
            )
        else:
            allowed = credential_document_visible_to_user(
                credential, viewer, None
            ) and _provider_download_scope_ok(
                viewer, credential.staff_profile.user
            )
        if not allowed or not credential.document:
            raise Http404("Document not found.")
        return FileResponse(
            credential.document.open("rb"),
            as_attachment=True,
            filename=credential.original_filename,
        )


class UserCredentialGrantListCreateView(generics.GenericAPIView):
    """GET / POST /api/users/<user_id>/credentials/<pk>/grants/"""

    permission_classes = [CanManageStaffMember]

    def _resolve(self, request, user_id, pk):
        early, profile = _resolve_target_staff_profile(self, request, user_id)
        if early is not None:
            return early, None
        credential = get_object_or_404(
            StaffCredential, pk=pk, staff_profile=profile
        )
        return None, credential

    def get(self, request, user_id, pk):
        early, credential = self._resolve(request, user_id, pk)
        if early is not None:
            return early
        grants = credential.customer_grants.select_related("customer").order_by(
            "customer__name"
        )
        return Response(
            CredentialGrantSerializer(grants, many=True).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request, user_id, pk):
        early, credential = self._resolve(request, user_id, pk)
        if early is not None:
            return early
        return _grant_create(
            request,
            parent_field="credential",
            parent=credential,
            grant_model=CredentialCustomerVisibility,
            read_serializer=CredentialGrantSerializer,
        )


class UserCredentialGrantDeleteView(generics.GenericAPIView):
    """DELETE /api/users/<user_id>/credentials/<pk>/grants/<grant_id>/"""

    permission_classes = [CanManageStaffMember]

    def delete(self, request, user_id, pk, grant_id):
        early, profile = _resolve_target_staff_profile(self, request, user_id)
        if early is not None:
            return early
        credential = get_object_or_404(
            StaffCredential, pk=pk, staff_profile=profile
        )
        grant = get_object_or_404(
            CredentialCustomerVisibility, pk=grant_id, credential=credential
        )
        grant.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Custom profile properties (target: ANY user; gate: CanManageUserProperties)
# ---------------------------------------------------------------------------


class UserPropertyListCreateView(generics.GenericAPIView):
    """GET / POST /api/users/<user_id>/properties/"""

    permission_classes = [CanManageUserProperties]

    def get(self, request, user_id):
        target = _resolve_target_user(self, request, user_id)
        properties = (
            target.profile_properties.prefetch_related(
                "customer_grants__customer"
            ).order_by("name", "id")
        )
        return Response(
            CustomProfilePropertySerializer(
                properties, many=True, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request, user_id):
        target = _resolve_target_user(self, request, user_id)
        serializer = CustomProfilePropertyWriteSerializer(
            data=request.data,
            context={"request": request, "target_user": target},
        )
        serializer.is_valid(raise_exception=True)
        prop = serializer.save()
        return Response(
            CustomProfilePropertySerializer(
                prop, context={"request": request}
            ).data,
            status=status.HTTP_201_CREATED,
        )


class UserPropertyDetailView(generics.GenericAPIView):
    """PATCH / DELETE /api/users/<user_id>/properties/<pk>/"""

    permission_classes = [CanManageUserProperties]

    def _resolve(self, request, user_id, pk):
        target = _resolve_target_user(self, request, user_id)
        return get_object_or_404(CustomProfileProperty, pk=pk, user=target)

    def patch(self, request, user_id, pk):
        prop = self._resolve(request, user_id, pk)
        serializer = CustomProfilePropertyWriteSerializer(
            prop, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        prop = serializer.save()
        return Response(
            CustomProfilePropertySerializer(
                prop, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )

    def delete(self, request, user_id, pk):
        prop = self._resolve(request, user_id, pk)
        prop.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserPropertyDownloadView(generics.GenericAPIView):
    """GET /api/users/<user_id>/properties/<pk>/download/ — same gate
    shape as the credential download (404 on every gate failure)."""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, user_id, pk):
        prop = get_object_or_404(
            CustomProfileProperty.objects.select_related("user"),
            pk=pk,
            user_id=user_id,
            user__deleted_at__isnull=True,
        )
        viewer = request.user
        if viewer.role == UserRole.CUSTOMER_USER:
            allowed = any(
                property_document_visible_to_user(
                    prop, viewer, membership.customer
                )
                for membership in CustomerUserMembership.objects.filter(
                    user=viewer
                ).select_related("customer")
            )
        else:
            allowed = property_document_visible_to_user(
                prop, viewer, None
            ) and _provider_download_scope_ok(viewer, prop.user)
        if not allowed or not prop.document:
            raise Http404("Document not found.")
        return FileResponse(
            prop.document.open("rb"),
            as_attachment=True,
            filename=prop.original_filename,
        )


class UserPropertyGrantListCreateView(generics.GenericAPIView):
    """GET / POST /api/users/<user_id>/properties/<pk>/grants/"""

    permission_classes = [CanManageUserProperties]

    def _resolve(self, request, user_id, pk):
        target = _resolve_target_user(self, request, user_id)
        return get_object_or_404(CustomProfileProperty, pk=pk, user=target)

    def get(self, request, user_id, pk):
        prop = self._resolve(request, user_id, pk)
        grants = prop.customer_grants.select_related("customer").order_by(
            "customer__name"
        )
        return Response(
            PropertyGrantSerializer(grants, many=True).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request, user_id, pk):
        prop = self._resolve(request, user_id, pk)
        return _grant_create(
            request,
            parent_field="property",
            parent=prop,
            grant_model=PropertyCustomerVisibility,
            read_serializer=PropertyGrantSerializer,
        )


class UserPropertyGrantDeleteView(generics.GenericAPIView):
    """DELETE /api/users/<user_id>/properties/<pk>/grants/<grant_id>/"""

    permission_classes = [CanManageUserProperties]

    def delete(self, request, user_id, pk, grant_id):
        target = _resolve_target_user(self, request, user_id)
        prop = get_object_or_404(CustomProfileProperty, pk=pk, user=target)
        grant = get_object_or_404(
            PropertyCustomerVisibility, pk=grant_id, property=prop
        )
        grant.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
