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

from notifications.models import NotificationEventType, NotificationPreference

from .models import LoginLog, User
from .scoping import scope_buildings_for, scope_companies_for, scope_customers_for


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

    # Routed through scope_*_for so /api/auth/me/ returns the same id sets the
    # matching list endpoints expose. After CHANGE-6, those scope helpers
    # filter inactive entities for non-super-admin users; super admins still
    # see archived rows because scope_*_for falls through to .all() for them.
    def get_company_ids(self, obj):
        return list(scope_companies_for(obj).values_list("id", flat=True))

    def get_building_ids(self, obj):
        return list(scope_buildings_for(obj).values_list("id", flat=True))

    def get_customer_ids(self, obj):
        return list(scope_customers_for(obj).values_list("id", flat=True))


class MeUpdateSerializer(serializers.ModelSerializer):
    """
    Write-side serializer for PATCH /auth/me/. Kept separate from MeSerializer
    so the read-side stays an honest read-only shape (its read_only_fields
    cover the full payload). Only full_name and language are writable here;
    role / is_active / email changes go through admin endpoints or are not
    yet implemented.
    """

    class Meta:
        model = User
        fields = ["full_name", "language"]

    def validate_full_name(self, value):
        cleaned = (value or "").strip()
        if not cleaned:
            raise serializers.ValidationError("Full name cannot be empty.")
        return cleaned


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        user = self.context["request"].user
        try:
            password_validation.validate_password(value, user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


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


_EVENT_TYPE_LABELS = dict(NotificationEventType.choices)


class NotificationPreferenceEntrySerializer(serializers.Serializer):
    """Single entry in the read or write payload for /auth/notification-preferences/.

    The label is read-only and derived from NotificationEventType.choices so
    the UI can render a human-readable name without re-encoding the enum
    on the frontend.
    """

    event_type = serializers.ChoiceField(
        choices=[(value, value) for value in NotificationPreference.USER_MUTABLE_EVENT_TYPES],
    )
    label = serializers.SerializerMethodField()
    muted = serializers.BooleanField()

    def get_label(self, obj):
        return _EVENT_TYPE_LABELS.get(obj["event_type"], obj["event_type"])


class NotificationPreferencesUpdateSerializer(serializers.Serializer):
    """Write-side payload: a list of {event_type, muted} entries to upsert.

    Entries with an event_type outside USER_MUTABLE_EVENT_TYPES are rejected
    with a 400. Each entry is upserted into the (user, event_type) row via
    update_or_create so repeat patches do not create duplicates and do not
    require unique_together to fault as a fallback safety net.
    """

    preferences = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=True,
    )

    def validate_preferences(self, value):
        cleaned = []
        for index, entry in enumerate(value):
            event_type = entry.get("event_type")
            muted = entry.get("muted")
            if event_type not in NotificationPreference.USER_MUTABLE_EVENT_TYPES:
                raise serializers.ValidationError(
                    f"preferences[{index}].event_type "
                    f"'{event_type}' is not a user-mutable notification type."
                )
            if not isinstance(muted, bool):
                raise serializers.ValidationError(
                    f"preferences[{index}].muted must be a boolean."
                )
            cleaned.append({"event_type": event_type, "muted": muted})
        return cleaned

    def save(self, **kwargs):
        user = self.context["request"].user
        for entry in self.validated_data["preferences"]:
            NotificationPreference.objects.update_or_create(
                user=user,
                event_type=entry["event_type"],
                defaults={"muted": entry["muted"]},
            )
        return user


def serialize_notification_preferences(user):
    """Build the GET payload — one entry per USER_MUTABLE event type.

    Missing rows fill in muted=False so the client always sees the full set
    and never has to know which event types exist. Stored rows take
    precedence over the default.
    """
    stored = {
        pref.event_type: pref.muted
        for pref in NotificationPreference.objects.filter(
            user=user,
            event_type__in=NotificationPreference.USER_MUTABLE_EVENT_TYPES,
        )
    }
    entries = [
        {
            "event_type": event_type,
            "label": _EVENT_TYPE_LABELS.get(event_type, event_type),
            "muted": stored.get(event_type, False),
        }
        for event_type in NotificationPreference.USER_MUTABLE_EVENT_TYPES
    ]
    return {"preferences": entries}
