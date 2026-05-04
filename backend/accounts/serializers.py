from datetime import timedelta

from django.contrib.auth import password_validation
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework import serializers

from .models import LoginLog, User
from .scoping import building_ids_for, company_ids_for, customer_ids_for


FAILED_LOGIN_LIMIT = 5
FAILED_LOGIN_WINDOW = timedelta(minutes=15)


def normalize_email(value):
    return User.objects.normalize_email((value or "").strip()).lower()


def _client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _user_agent(request):
    return request.META.get("HTTP_USER_AGENT", "")[:2000]


def _log_login_attempt(request, email, user=None, success=False):
    LoginLog.objects.create(
        user=user,
        email=email or "",
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
        success=success,
    )


class ScopedTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = "email"

    def validate(self, attrs):
        request = self.context.get("request")
        email = normalize_email(attrs.get(self.username_field))
        user = User.objects.filter(email__iexact=email).first()

        cutoff = timezone.now() - FAILED_LOGIN_WINDOW
        failed_count = LoginLog.objects.filter(
            email=email,
            success=False,
            created_at__gte=cutoff,
        ).count()
        if failed_count >= FAILED_LOGIN_LIMIT:
            if request:
                _log_login_attempt(request, email, user=user, success=False)
            raise AuthenticationFailed(
                "Too many failed login attempts. Please try again later.",
                code="too_many_failed_attempts",
            )

        try:
            data = super().validate({**attrs, self.username_field: email})
        except Exception:
            if request:
                _log_login_attempt(request, email, user=user, success=False)
            raise

        if request:
            _log_login_attempt(request, email, user=self.user, success=True)
        return data


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "full_name", "role", "language", "is_active"]
        read_only_fields = fields


class MeSerializer(serializers.ModelSerializer):
    company_ids = serializers.SerializerMethodField()
    building_ids = serializers.SerializerMethodField()
    customer_ids = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "role",
            "language",
            "is_active",
            "company_ids",
            "building_ids",
            "customer_ids",
        ]
        read_only_fields = fields

    def get_company_ids(self, obj):
        return list(company_ids_for(obj))

    def get_building_ids(self, obj):
        return list(building_ids_for(obj))

    def get_customer_ids(self, obj):
        return list(customer_ids_for(obj))


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def get_user(self):
        email = normalize_email(self.validated_data["email"])
        return User.objects.filter(
            email__iexact=email,
            is_active=True,
            deleted_at__isnull=True,
        ).first()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    default_error_messages = {
        "invalid_token": "Password reset token is invalid or expired.",
    }

    def validate(self, attrs):
        try:
            user_id = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(
                pk=user_id,
                is_active=True,
                deleted_at__isnull=True,
            )
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError(
                {"token": self.error_messages["invalid_token"]}
            )

        if not PasswordResetTokenGenerator().check_token(user, attrs["token"]):
            raise serializers.ValidationError(
                {"token": self.error_messages["invalid_token"]}
            )

        try:
            password_validation.validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)})
        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user
