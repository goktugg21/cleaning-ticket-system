"""
M1 B6 — Extra Work message thread HTTP layer.

Endpoints (under `/api/extra-work/<ew_id>/`):
  GET/POST  messages/              list (chokepoint-filtered) + create
  GET       message-recipients/    directed_to candidates (side-aware)

Mirrors the B5 ticket message views MINUS staff. Every read routes through
`filter_ew_messages_visible_to`; posting authz + side-aware directed/RESTRICTED
live in `ExtraWorkMessageSerializer`. The parent-EW scope gate (`scope_extra_
work_for` -> 404) means STAFF (who have no EW scope) can never reach either
endpoint.
"""
from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from rest_framework import status, views
from rest_framework.response import Response

from accounts.permissions import (
    IsAuthenticatedAndActive,
    is_customer_side,
    is_provider_management_role,
)
from notifications.services import (
    emit_extra_work_message_notifications,
    ew_message_audience,
)

from .message_permissions import (
    ew_message_type_visible_to_user,
    filter_ew_messages_visible_to,
)
from .models import ExtraWorkMessage, ExtraWorkMessageType
from .scoping import scope_extra_work_for
from .serializers_messages import ExtraWorkMessageSerializer


logger = logging.getLogger(__name__)


def _resolve_ew_or_404(request, ew_id):
    """Scope-aware EW resolution. 404 if the caller cannot see the parent EW
    (STAFF always 404 — `scope_extra_work_for` returns none() for STAFF)."""
    return get_object_or_404(scope_extra_work_for(request.user), pk=ew_id)


def _ew_recipient_side(user):
    """Bucket a directed-recipient candidate: provider management or
    customer-side. EW has no staff dimension (the audience resolvers never
    return STAFF), so there is no 'staff' bucket."""
    if is_provider_management_role(user):
        return "provider"
    return "customer"


class ExtraWorkMessageListCreateView(views.APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, ew_id: int):
        extra_work = _resolve_ew_or_404(request, ew_id)
        qs = (
            ExtraWorkMessage.objects.filter(extra_work=extra_work)
            .select_related("author")
            .prefetch_related("directed_to")
        )
        # Route through the SINGLE EW-message visibility chokepoint (role tier
        # filter + the unconditional RESTRICTED party filter).
        qs = filter_ew_messages_visible_to(qs, request.user).order_by("created_at")
        data = ExtraWorkMessageSerializer(
            qs, many=True, context={"request": request}
        ).data
        return Response(data)

    def post(self, request, ew_id: int):
        extra_work = _resolve_ew_or_404(request, ew_id)
        serializer = ExtraWorkMessageSerializer(
            data=request.data,
            context={"request": request, "extra_work": extra_work},
        )
        serializer.is_valid(raise_exception=True)
        message = serializer.save(extra_work=extra_work, author=request.user)

        # M1 B6 — emit in-app notifications best-effort + logged: the message
        # is already saved, and a fan-out failure must never fail the POST.
        try:
            emit_extra_work_message_notifications(message, actor=request.user)
        except Exception:  # noqa: BLE001 — best-effort fan-out, logged below
            logger.exception(
                "Failed to emit EW message notifications for message %s",
                message.id,
            )

        return Response(
            ExtraWorkMessageSerializer(
                message, context={"request": request}
            ).data,
            status=status.HTTP_201_CREATED,
        )


class ExtraWorkMessageRecipientsView(views.APIView):
    """M1 B6 — directed-recipients source for the composer's "notify specific
    people" picker. Side-aware by CALLER (mirror of the B5
    TicketMessageRecipientsView, minus staff):
      * CUST caller -> only customer-side candidates.
      * MGMT / SA   -> the full tier audience.
    Caller is scope-gated (404 if not in `scope_extra_work_for`, which also
    excludes STAFF entirely). Payload items are `{id, full_name, side}` — no
    email.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, ew_id: int):
        extra_work = _resolve_ew_or_404(request, ew_id)
        caller = request.user
        message_type = request.query_params.get(
            "message_type", ExtraWorkMessageType.PUBLIC_REPLY
        )
        if message_type not in set(ExtraWorkMessageType.values):
            return Response(
                {"detail": "Invalid message_type.", "code": "invalid_message_type"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        caller_is_customer = is_customer_side(caller)
        results = []
        for user in ew_message_audience(extra_work, message_type):
            if user.id == caller.id:
                continue
            # Intersect with the exact predicates the serializer validates so
            # the picker can never offer a target the POST would 400.
            if not ew_message_type_visible_to_user(user, message_type):
                continue
            if not scope_extra_work_for(user).filter(pk=extra_work.pk).exists():
                continue
            side = _ew_recipient_side(user)
            # A customer composer may only direct at customer-side people.
            if caller_is_customer and side != "customer":
                continue
            results.append(
                {
                    "id": user.id,
                    "full_name": user.full_name or user.email.split("@")[0],
                    "side": side,
                }
            )
        return Response({"results": results})
