from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status, views
from rest_framework.response import Response

from notifications.services import send_invitation_email

from .invitations import Invitation, InvitationStatus, hash_invitation_token
from .models import UserRole
from .permissions import IsAuthenticatedAndActive
from .scoping import company_ids_for
from .serializers_invitations import (
    InvitationAcceptSerializer,
    InvitationCreateSerializer,
    InvitationListSerializer,
    InvitationPreviewSerializer,
)


class CanCreateInvitations(IsAuthenticatedAndActive):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.user.role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN)


class InvitationListCreateView(generics.ListCreateAPIView):
    permission_classes = [CanCreateInvitations]

    def get_queryset(self):
        user = self.request.user
        qs = Invitation.objects.all().select_related("created_by")
        if user.role == UserRole.SUPER_ADMIN:
            return qs.order_by("-created_at")
        # COMPANY_ADMIN sees their own invitations and any invitation that
        # targets a company they are a member of.
        actor_company_ids = list(company_ids_for(user))
        return (
            qs.filter(Q(created_by=user) | Q(companies__in=actor_company_ids))
            .distinct()
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return InvitationCreateSerializer
        return InvitationListSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation, raw_token = serializer.save_with_token()
        accept_url = ""
        if settings.INVITATION_ACCEPT_FRONTEND_URL:
            accept_url = settings.INVITATION_ACCEPT_FRONTEND_URL.format(token=raw_token)
        send_invitation_email(invitation, raw_token=raw_token, accept_url=accept_url)
        # Response uses the list serializer so the raw token never leaks back
        # to the API caller; the only place the raw token leaves the system is
        # the email body.
        return Response(
            InvitationListSerializer(invitation).data,
            status=status.HTTP_201_CREATED,
        )


class InvitationPreviewView(views.APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        raw_token = request.query_params.get("token", "")
        if not raw_token:
            return Response(
                {"detail": "token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        invitation = Invitation.objects.filter(
            token_hash=hash_invitation_token(raw_token),
        ).first()
        if invitation is None:
            return Response(
                {"detail": "Invitation not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if invitation.status != InvitationStatus.PENDING:
            return Response(
                {
                    "detail": "Invitation is no longer valid.",
                    "status": invitation.status,
                },
                status=status.HTTP_410_GONE,
            )
        return Response(InvitationPreviewSerializer(invitation).data)


class InvitationAcceptView(views.APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        # The serializer's validate() uses select_for_update so the row is
        # locked for the duration of this transaction.
        with transaction.atomic():
            serializer = InvitationAcceptSerializer(data=request.data)
            try:
                serializer.is_valid(raise_exception=True)
            except Exception as exc:
                # If the serializer attached a "gone" code, surface 410 instead
                # of 400. Otherwise re-raise so DRF returns 400.
                detail = getattr(exc, "detail", None)
                if isinstance(detail, dict) and detail.get("token", None):
                    token_errors = detail.get("token")
                    if isinstance(token_errors, list):
                        token_errors = token_errors[0] if token_errors else ""
                    if (
                        isinstance(token_errors, str)
                        and "no longer valid" in token_errors.lower()
                    ):
                        return Response(detail, status=status.HTTP_410_GONE)
                raise
            serializer.save()
        return Response(
            {"detail": "Account created. Please sign in."},
            status=status.HTTP_201_CREATED,
        )


class InvitationRevokeView(views.APIView):
    permission_classes = [CanCreateInvitations]

    def post(self, request, pk):
        invitation = get_object_or_404(Invitation, pk=pk)
        if (
            request.user.role != UserRole.SUPER_ADMIN
            and invitation.created_by_id != request.user.id
        ):
            return Response(
                {"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN
            )
        if invitation.status == InvitationStatus.ACCEPTED:
            return Response(
                {"detail": "Cannot revoke an accepted invitation."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if invitation.status == InvitationStatus.REVOKED:
            return Response(
                InvitationListSerializer(invitation).data,
                status=status.HTTP_200_OK,
            )
        invitation.revoked_at = timezone.now()
        invitation.revoked_by = request.user
        invitation.save(update_fields=["revoked_at", "revoked_by"])
        return Response(
            InvitationListSerializer(invitation).data,
            status=status.HTTP_200_OK,
        )
