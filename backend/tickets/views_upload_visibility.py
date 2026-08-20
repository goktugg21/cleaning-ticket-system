"""
W4-P — the two permission scopes for staff photo uploads.

The owner's ask, verbatim: *"sometimes the provider or the manager
should be able to give permissions to the staff to not need this. for
example give pre permission to ahmet and from then his uploaded photos
are in the pool. this should be in the permissions page and ticket
assignment page as well. permission page is for all of the tickets. and
the tickets assignment is that spesific ticket. and this should be
clearly stated."*

Two scopes, one model (`UploadVisibilityGrant`), one resolution order
(`tickets/attachment_visibility.py`), and two endpoints:

  STANDING — every ticket, forever.
    GET   /api/tickets/upload-visibility/standing/
    PATCH /api/tickets/upload-visibility/standing/<user_id>/
          {"uploads_customer_visible": true | false | null}

  PER-TICKET — this ticket only.
    GET   /api/tickets/<ticket_id>/upload-visibility/
    PATCH /api/tickets/<ticket_id>/upload-visibility/<user_id>/
          {"uploads_customer_visible": true | false | null}

`null` CLEARS the decision at that scope (the row is deleted) and lets
the next rung down answer again. It is NOT the same as `false`, which is
an explicit refusal that outranks everything less specific. A caller
must say which of the three they mean — the key is required.

GRANTING IS PRIVILEGED, and the rule is short:

  * NEVER THE PERSON RECEIVING IT. An actor may not grant, refuse, or
    clear their own uploads at either scope. Checked before anything
    else that could leak, and checked at both endpoints.
  * STANDING is SUPER_ADMIN / COMPANY_ADMIN only. It spans every ticket
    of every customer the person will ever work on, which is above a
    building manager's pay grade — the same line
    `attachment-visibility-policy` already draws for the per-work
    setting. A COMPANY_ADMIN may only touch a person inside their own
    provider company (`manageable_user_ids_for`); a SUPER_ADMIN is
    unrestricted. Anyone else: 403.
  * PER-TICKET is provider management (SUPER_ADMIN / COMPANY_ADMIN /
    BUILDING_MANAGER) holding scope on the ticket. It is precisely a
    pre-authorised version of the promote action they can already
    perform photo by photo, so it draws the same line
    `TicketAttachmentVisibilityView` draws. Out-of-scope ticket: 404.

TENANT SCOPING — the P0. A grant changes the LEVEL an upload lands at.
It changes nothing about who may read a stored row: the customer wall in
`TicketAttachmentListCreateView.get_queryset`, the twin check in
`TicketAttachmentDownloadView` and `scope_tickets_for` all still run
untouched, so a released photo still reaches only the customer of its
own ticket and no other. There is no code path here by which a grant
widens a queryset.

AUDIT — H-10. Every create / change / clear writes one AuditLog row by
hand, in the shape `_audit_ticket_flag` uses for the per-work switch:
`UploadVisibilityGrant` is deliberately NOT registered in the generic
CRUD trio, because a clear is a DELETE and the row that says WHAT was
cleared has to carry the scope, which the generic differ would not know
to include.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.response import Response

from accounts.models import User, UserRole
from accounts.permissions import (
    IsAuthenticatedAndActive,
    is_provider_management_role,
)
from accounts.scoping import manageable_user_ids_for, scope_tickets_for
from audit import context as audit_context
from audit.models import AuditAction, AuditLog

from .attachment_visibility import (
    resolve_upload_visibility,
    standing_grant,
)
from .models import (
    Ticket,
    TicketStaffAssignment,
    UploadVisibilityGrant,
)


logger = logging.getLogger(__name__)


ERR_SELF = "upload_visibility_self_grant_forbidden"
ERR_FORBIDDEN = "upload_visibility_forbidden"


class UploadVisibilityGrantWriteSerializer(serializers.Serializer):
    """The whole body: one tri-state.

    `allow_null` plus `required` is the shape `TicketCategorySerializer`
    already uses for its nullable pk, and it says the same thing here:
    omitting the key is not a third way of saying "clear it". A caller
    states which of grant / refuse / clear they mean.
    """

    uploads_customer_visible = serializers.BooleanField(allow_null=True)
    reason = serializers.CharField(
        required=False, allow_blank=True, max_length=2000
    )


def _grant_payload(grant, *, user_id, ticket_id):
    """What one scope currently says. `uploads_customer_visible` is null
    when there is no row — the same tri-state the write side takes."""
    return {
        "user_id": user_id,
        "ticket_id": ticket_id,
        "uploads_customer_visible": (
            None if grant is None else grant.uploads_customer_visible
        ),
        "reason": "" if grant is None else grant.reason,
        "granted_by_id": None if grant is None else grant.granted_by_id,
        "updated_at": None if grant is None else grant.updated_at,
    }


def _effective_payload(ticket, user):
    """What the NEXT upload by this person on this ticket would land at,
    and which rung says so. Computed by calling the resolver — this
    module never re-implements a rung."""
    resolved = resolve_upload_visibility(ticket, user)
    return {
        "effective_visibility": resolved.visibility,
        "effective_source": resolved.source,
    }


def _audit_grant(request, *, target_user, ticket, before, after, reason):
    """One AuditLog row per real change (H-10). Best-effort: a failure is
    logged and never blocks the write, mirroring `_audit_ticket_flag`."""
    try:
        scope = audit_context.get_current_actor_scope() or {}
        if not scope:
            scope = audit_context.snapshot_actor_scope(request.user) or {}
        AuditLog.objects.create(
            actor=request.user,
            action=AuditAction.UPDATE,
            target_model="tickets.UploadVisibilityGrant",
            target_id=target_user.id,
            changes={
                "scope": "STANDING" if ticket is None else "TICKET",
                "ticket_id": None if ticket is None else ticket.id,
                "target_user_id": target_user.id,
                "uploads_customer_visible": {
                    "before": before,
                    "after": after,
                },
                "reason": reason,
            },
            request_ip=audit_context.get_current_request_ip(),
            request_id=audit_context.get_current_request_id(),
            reason=audit_context.get_current_reason(),
            actor_scope=scope,
        )
    except Exception:  # pragma: no cover - audit must never block
        logger.exception("Failed to write upload-visibility grant audit row")


def _refuse_self(actor, target):
    """Granting is privileged and the first rule is that it is never
    self-service. Returns a 403 Response, or None."""
    if actor.id == target.id:
        return Response(
            {
                "detail": "You cannot decide the visibility of your own "
                "uploads.",
                "code": ERR_SELF,
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


@transaction.atomic
def _apply(request, *, target_user, ticket, value, reason):
    """Write / update / delete the one row for this (person, scope), and
    audit a real change. Shared by both endpoints so the two scopes
    cannot drift apart."""
    existing = UploadVisibilityGrant.objects.filter(
        user=target_user, ticket=ticket
    ).first()
    before = None if existing is None else existing.uploads_customer_visible

    if value is None:
        if existing is not None:
            existing.delete()
    elif existing is None:
        UploadVisibilityGrant.objects.create(
            user=target_user,
            ticket=ticket,
            uploads_customer_visible=value,
            granted_by=request.user,
            reason=reason,
        )
    else:
        existing.uploads_customer_visible = value
        existing.granted_by = request.user
        existing.reason = reason
        existing.save(
            update_fields=[
                "uploads_customer_visible",
                "granted_by",
                "reason",
                "updated_at",
            ]
        )

    if before != value:
        _audit_grant(
            request,
            target_user=target_user,
            ticket=ticket,
            before=before,
            after=value,
            reason=reason,
        )

    return UploadVisibilityGrant.objects.filter(
        user=target_user, ticket=ticket
    ).first()


# ---------------------------------------------------------------------------
# STANDING — the permissions screen. Every ticket.
# ---------------------------------------------------------------------------


class StandingUploadVisibilityView(generics.GenericAPIView):
    """
    `GET  /api/tickets/upload-visibility/standing/?user_id=<id>`
    `PATCH /api/tickets/upload-visibility/standing/<user_id>/`

    SUPER_ADMIN / COMPANY_ADMIN only, never on yourself, and a
    COMPANY_ADMIN only inside their own provider company.

    The GET with `?user_id=` answers ONE person's standing state so the
    admin card can render without a list endpoint; without it, it lists
    every standing row the actor may administer.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def _gate_actor(self, request):
        if request.user.role not in (
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
        ):
            return Response(
                {
                    "detail": "Only a provider admin can change a standing "
                    "upload-visibility permission.",
                    "code": ERR_FORBIDDEN,
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def _resolve_target(self, request, user_id):
        """404 for a user outside the actor's company, so the endpoint is
        not an existence oracle (H-1)."""
        manageable = manageable_user_ids_for(request.user)
        target = get_object_or_404(
            User, pk=user_id, is_active=True, deleted_at__isnull=True
        )
        if manageable is not None and target.id not in manageable:
            raise Http404("User not found.")
        return target

    def get(self, request, user_id=None):
        gate = self._gate_actor(request)
        if gate is not None:
            return gate

        # Both routes land here: the collection route reads `?user_id=`,
        # the detail route gets it from the path. One method rather than
        # two views because the answer is identical either way, and a
        # bare `def get(self, request)` would 500 on the detail URL
        # instead of answering it.
        raw_user_id = user_id or request.query_params.get("user_id")
        if raw_user_id:
            target = self._resolve_target(request, raw_user_id)
            grant = UploadVisibilityGrant.objects.filter(
                user=target, ticket__isnull=True
            ).first()
            return Response(
                _grant_payload(grant, user_id=target.id, ticket_id=None),
                status=status.HTTP_200_OK,
            )

        manageable = manageable_user_ids_for(request.user)
        rows = UploadVisibilityGrant.objects.filter(
            ticket__isnull=True
        ).select_related("user")
        if manageable is not None:
            rows = rows.filter(user_id__in=manageable)
        return Response(
            [
                {
                    **_grant_payload(row, user_id=row.user_id, ticket_id=None),
                    "user_email": row.user.email,
                    "user_full_name": row.user.full_name,
                }
                for row in rows.order_by("user__email")
            ],
            status=status.HTTP_200_OK,
        )

    def patch(self, request, user_id=None):
        # The collection route carries no user id. Django would call this
        # with `user_id=None` and the row write would silently target
        # nobody, so refuse it as the wrong URL rather than guess.
        if user_id is None:
            return Response(
                {
                    "detail": "PATCH the per-user route: "
                    "/api/tickets/upload-visibility/standing/<user_id>/.",
                    "code": "upload_visibility_user_required",
                },
                status=status.HTTP_405_METHOD_NOT_ALLOWED,
            )
        gate = self._gate_actor(request)
        if gate is not None:
            return gate

        target = self._resolve_target(request, user_id)
        refusal = _refuse_self(request.user, target)
        if refusal is not None:
            return refusal

        ser = UploadVisibilityGrantWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        grant = _apply(
            request,
            target_user=target,
            ticket=None,
            value=ser.validated_data["uploads_customer_visible"],
            reason=ser.validated_data.get("reason", ""),
        )
        return Response(
            _grant_payload(grant, user_id=target.id, ticket_id=None),
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# PER-TICKET — the Assignment card. This ticket only.
# ---------------------------------------------------------------------------


class TicketUploadVisibilityView(generics.GenericAPIView):
    """
    `GET   /api/tickets/<ticket_id>/upload-visibility/`
    `PATCH /api/tickets/<ticket_id>/upload-visibility/<user_id>/`

    Provider management holding scope on the ticket, never on yourself.

    The GET is the Assignment card's read: one entry per DISTINCT person
    holding a staff slot on this ticket (a person may hold several dated
    slots — the permission is about the person, not the slot), each
    carrying all four rungs so the card can state plainly which one is
    currently deciding and what the next upload would do.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def _resolve(self, request, ticket_id):
        if not is_provider_management_role(request.user):
            return (
                Response(
                    {
                        "detail": "Only provider management can change a "
                        "per-ticket upload-visibility permission.",
                        "code": ERR_FORBIDDEN,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                ),
                None,
            )
        ticket = get_object_or_404(Ticket, pk=ticket_id)
        if not scope_tickets_for(request.user).filter(pk=ticket.pk).exists():
            raise Http404("Ticket not found.")
        return None, ticket

    def get(self, request, ticket_id, user_id=None):
        # The detail route accepts GET too and answers the same list; a
        # bare `def get(self, request, ticket_id)` would 500 on it.
        early, ticket = self._resolve(request, ticket_id)
        if early is not None:
            return early

        seen: dict[int, User] = {}
        for slot in (
            TicketStaffAssignment.objects.filter(ticket=ticket)
            .select_related("user")
            .order_by("user__email", "id")
        ):
            seen.setdefault(slot.user_id, slot.user)

        grants = {
            row.user_id: row
            for row in UploadVisibilityGrant.objects.filter(ticket=ticket)
        }

        return Response(
            {
                "ticket_id": ticket.id,
                "staff_uploads_customer_visible": (
                    ticket.staff_uploads_customer_visible
                ),
                "people": [
                    {
                        **_grant_payload(
                            grants.get(user_id),
                            user_id=user_id,
                            ticket_id=ticket.id,
                        ),
                        "user_email": user.email,
                        "user_full_name": user.full_name,
                        "standing_uploads_customer_visible": standing_grant(
                            user
                        ),
                        **_effective_payload(ticket, user),
                    }
                    for user_id, user in seen.items()
                ],
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request, ticket_id, user_id=None):
        if user_id is None:
            return Response(
                {
                    "detail": "PATCH the per-user route: "
                    "/api/tickets/<ticket_id>/upload-visibility/<user_id>/.",
                    "code": "upload_visibility_user_required",
                },
                status=status.HTTP_405_METHOD_NOT_ALLOWED,
            )
        early, ticket = self._resolve(request, ticket_id)
        if early is not None:
            return early

        # The target must hold a staff slot on THIS ticket. That is the
        # tenant boundary on the write side: a per-ticket grant for a
        # person with no work here would be a decision about somebody
        # else's tenant reachable through this URL.
        target = get_object_or_404(
            User, pk=user_id, is_active=True, deleted_at__isnull=True
        )
        if not TicketStaffAssignment.objects.filter(
            ticket=ticket, user=target
        ).exists():
            raise Http404("That person holds no assignment on this ticket.")

        refusal = _refuse_self(request.user, target)
        if refusal is not None:
            return refusal

        ser = UploadVisibilityGrantWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        grant = _apply(
            request,
            target_user=target,
            ticket=ticket,
            value=ser.validated_data["uploads_customer_visible"],
            reason=ser.validated_data.get("reason", ""),
        )
        return Response(
            {
                **_grant_payload(
                    grant, user_id=target.id, ticket_id=ticket.id
                ),
                "user_email": target.email,
                "user_full_name": target.full_name,
                "standing_uploads_customer_visible": standing_grant(target),
                **_effective_payload(ticket, target),
            },
            status=status.HTTP_200_OK,
        )
