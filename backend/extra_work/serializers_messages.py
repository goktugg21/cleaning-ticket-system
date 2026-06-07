"""
M1 B6 — Extra Work message serializer.

Mirrors `tickets.serializers.TicketMessageSerializer` (the B5 ticket message
model) MINUS the staff dimension. Read/write authz is enforced server-side:
posting authz via `user_may_post_ew_message_type`, side-aware directed_to /
RESTRICTED validation, and the read chokepoint
(`filter_ew_messages_visible_to`) on every list path.
"""
from __future__ import annotations

from rest_framework import serializers

from accounts.models import User
from accounts.permissions import is_customer_side

from .message_permissions import (
    ew_message_type_visible_to_user,
    user_may_post_ew_message_type,
)
from .models import (
    ExtraWorkMessage,
    ExtraWorkMessageType,
    ExtraWorkMessageVisibility,
)
from .scoping import scope_extra_work_for


class ExtraWorkMessageSerializer(serializers.ModelSerializer):
    author_email = serializers.CharField(source="author.email", read_only=True)
    directed_to = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=User.objects.all(),
        required=False,
        default=list,
    )
    directed_to_detail = serializers.SerializerMethodField()

    # Upper bound on attention targets (query-amplification guard) — mirrors
    # the B5 ticket cap.
    MAX_DIRECTED_TO = 50

    class Meta:
        model = ExtraWorkMessage
        fields = [
            "id",
            "extra_work",
            "author",
            "author_email",
            "message",
            "message_type",
            "directed_to",
            "directed_to_detail",
            "visibility_mode",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "extra_work",
            "author",
            "author_email",
            "created_at",
        ]

    def get_directed_to_detail(self, obj):
        # Display label list for the thread chips. Rendered only on rows the
        # chokepoint already admitted, so it never widens who can see a
        # RESTRICTED message.
        return [
            {
                "id": user.id,
                "full_name": user.full_name or user.email.split("@")[0],
            }
            for user in obj.directed_to.all()
        ]

    def to_internal_value(self, data):
        # Cap directed_to on the RAW input, before DRF resolves each PK.
        directed = data.get("directed_to") if hasattr(data, "get") else None
        if isinstance(directed, (list, tuple)) and len(directed) > self.MAX_DIRECTED_TO:
            raise serializers.ValidationError(
                {
                    "directed_to": [
                        serializers.ErrorDetail(
                            f"At most {self.MAX_DIRECTED_TO} directed "
                            "recipients are allowed.",
                            code="too_many_directed_recipients",
                        )
                    ]
                }
            )
        return super().to_internal_value(data)

    def validate_message_type(self, value):
        # POSTING authz for an EXPLICIT tier. The complete gate (incl. the
        # defaulted-field path) lives in validate().
        request = self.context.get("request")
        user = request.user if request else None
        if not user_may_post_ew_message_type(user, value):
            raise serializers.ValidationError(
                serializers.ErrorDetail(
                    "Your role is not allowed to post this message type.",
                    code="ew_message_type_not_allowed",
                )
            )
        return value

    def validate(self, attrs):
        extra_work = self.context["extra_work"]
        user = self.context["request"].user

        # EW SCOPE — the author must be able to read the parent EW.
        if not scope_extra_work_for(user).filter(pk=extra_work.pk).exists():
            raise serializers.ValidationError(
                "You do not have access to this extra work request."
            )

        message_type = attrs.get(
            "message_type", ExtraWorkMessageType.PUBLIC_REPLY
        )
        directed_to = attrs.get("directed_to") or []
        visibility_mode = attrs.get(
            "visibility_mode", ExtraWorkMessageVisibility.NORMAL
        )

        # POSTING authz on the EFFECTIVE tier (covers the defaulted-field path
        # that skips per-field validators — e.g. a staff POST with no
        # message_type defaults PUBLIC_REPLY, which staff may not author).
        if not user_may_post_ew_message_type(user, message_type):
            raise serializers.ValidationError(
                {
                    "message_type": [
                        serializers.ErrorDetail(
                            "Your role is not allowed to post this message "
                            "type.",
                            code="ew_message_type_not_allowed",
                        )
                    ]
                }
            )

        # A RESTRICTED message with no target is a black hole — reject it.
        if (
            visibility_mode == ExtraWorkMessageVisibility.RESTRICTED
            and not directed_to
        ):
            raise serializers.ValidationError(
                {
                    "directed_to": [
                        serializers.ErrorDetail(
                            "A restricted message must name at least one "
                            "recipient.",
                            code="restricted_requires_target",
                        )
                    ]
                }
            )

        # A CUSTOMER-side author may make a message RESTRICTED ONLY on the
        # CUSTOMER_INTERNAL tier (they may notify customer-side people on a
        # PUBLIC_REPLY, but cannot make a PUBLIC_REPLY private).
        if (
            is_customer_side(user)
            and visibility_mode == ExtraWorkMessageVisibility.RESTRICTED
            and message_type != ExtraWorkMessageType.CUSTOMER_INTERNAL
        ):
            raise serializers.ValidationError(
                {
                    "visibility_mode": [
                        serializers.ErrorDetail(
                            "A customer-side user can only make a Customer "
                            "Internal note private.",
                            code="restricted_only_for_customer_internal",
                        )
                    ]
                }
            )

        # A CUSTOMER-side author may NEVER direct a message at a provider-side
        # user (on ANY tier, including SUPER_ADMIN — who can read
        # CUSTOMER_INTERNAL, so the visibility check below alone would not
        # catch them).
        if is_customer_side(user):
            for target in directed_to:
                if not is_customer_side(target):
                    raise serializers.ValidationError(
                        {
                            "directed_to": [
                                serializers.ErrorDetail(
                                    "A customer-side user can only notify "
                                    "other customer-side people.",
                                    code="directed_to_must_be_customer_side",
                                )
                            ]
                        }
                    )

        # Every directed user must (a) have EW scope AND (b) be allowed to see
        # this tier — directing can never widen the tier audience.
        for target in directed_to:
            in_scope = scope_extra_work_for(target).filter(
                pk=extra_work.pk
            ).exists()
            if not in_scope or not ew_message_type_visible_to_user(
                target, message_type
            ):
                raise serializers.ValidationError(
                    {
                        "directed_to": [
                            serializers.ErrorDetail(
                                "You cannot direct this message to a user who "
                                "cannot see it.",
                                code="directed_to_not_visible",
                            )
                        ]
                    }
                )
        return attrs
