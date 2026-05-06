from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from notifications.services import send_password_reset_email

from .permissions import IsAuthenticatedAndActive
from .serializers import (
    MeSerializer,
    MeUpdateSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ScopedTokenObtainPairSerializer,
)


class ScopedTokenObtainPairView(TokenObtainPairView):
    throttle_scope = "auth_token"
    serializer_class = ScopedTokenObtainPairSerializer


class ScopedTokenRefreshView(TokenRefreshView):
    throttle_scope = "auth_token_refresh"


class MeView(APIView):
    permission_classes = [IsAuthenticated, IsAuthenticatedAndActive]

    def get(self, request):
        serializer = MeSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        # Write-side runs through MeUpdateSerializer (full_name, language only).
        # Unknown fields like role/is_active/email are silently dropped by
        # ModelSerializer rather than 400'd, so a forward-compatible client
        # PATCH stays well-behaved. The response re-serializes via MeSerializer
        # to keep the GET/PATCH shape identical.
        serializer = MeUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MeSerializer(request.user).data)


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated, IsAuthenticatedAndActive]

    def post(self, request):
        serializer = PasswordChangeSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Password updated."}, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response(
                {"refresh": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            RefreshToken(refresh).blacklist()
        except TokenError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetRequestView(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.get_user()

        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = PasswordResetTokenGenerator().make_token(user)
            reset_url = ""
            if settings.PASSWORD_RESET_FRONTEND_URL:
                reset_url = settings.PASSWORD_RESET_FRONTEND_URL.format(uid=uid, token=token)
            send_password_reset_email(user, uid=uid, token=token, reset_url=reset_url)

        return Response(
            {"detail": "If an active account exists for that email, password reset instructions have been sent."},
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Password has been reset."}, status=status.HTTP_200_OK)
