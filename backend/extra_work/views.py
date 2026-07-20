"""
Sprint 26B — Extra Work HTTP layer.

Endpoints (all under `/api/extra-work/`):

  GET    /api/extra-work/                              list (scoped)
  POST   /api/extra-work/                              create -> REQUESTED
  GET    /api/extra-work/<id>/                         retrieve (scoped, role-aware)
  POST   /api/extra-work/<id>/transition/              drive status transition
  GET    /api/extra-work/<id>/status-history/          read-only audit log
  GET    /api/extra-work/<id>/pricing-items/           list line items
  POST   /api/extra-work/<id>/pricing-items/           create line item (provider)
  PATCH  /api/extra-work/<id>/pricing-items/<lid>/     update line item (provider)
  DELETE /api/extra-work/<id>/pricing-items/<lid>/     delete line item (provider)

Customer users CAN reach list / detail / status-history for rows
in their scope and POST a transition (approve/reject pricing).
Provider users CAN additionally manage pricing line items.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive
from accounts.permissions_v2 import user_has_osius_permission
from notifications.services import emit_extra_work_requested_notifications

from .classification import (
    IntentValidationError,
    classify_cart,
    classify_line,
    derive_default_intent,
    validate_intent_for_cart,
)
from .filters import ExtraWorkRequestFilter
from .models import (
    ExtraWorkLinePriceSource,
    ExtraWorkPricingLineItem,
    ExtraWorkRequest,
    ExtraWorkRequestIntent,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
)
from .scoping import scope_extra_work_for
from .serializers import (
    ActualHoursEntrySerializer,
    ExtraWorkPreviewSerializer,
    ExtraWorkPricingLineItemCustomerSerializer,
    ExtraWorkPricingLineItemSerializer,
    ExtraWorkRequestCreateSerializer,
    ExtraWorkRequestDetailSerializer,
    ExtraWorkRequestListSerializer,
    ExtraWorkStatusHistorySerializer,
    ExtraWorkTransitionSerializer,
    derive_actor_kind,
)
from .state_machine import TransitionError, apply_transition


logger = logging.getLogger(__name__)


# Sprint 5 — stable order of intents in the preview `allowed_intents`
# list. Matches the enum declaration order in models.py.
_PREVIEW_INTENT_ORDER = (
    ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
    ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
    ExtraWorkRequestIntent.REQUEST_QUOTE,
)


def _decimal_str(value) -> str | None:
    """Render a Decimal like DRF's DecimalField (str, 2dp); None-safe."""
    if value is None:
        return None
    return f"{value:.2f}"


PROVIDER_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
    UserRole.BUILDING_MANAGER,
}


# Sprint 28 Batch 9 — bucket definitions for the Extra Work stats
# endpoints. Kept as module-level constants so the `stats` /
# `stats/by-building` actions share a single source of truth.
#
# String literals (not `ExtraWorkStatus.X.value`) match the style of
# `tickets.views.stats` and keep the Q-filter call sites readable.
# Sprint 29 Batch 29.8 — CUSTOMER_APPROVED is no longer terminal:
# it is the entry point of the operational segment (IN_PROGRESS /
# COMPLETED). The dashboard "active EW" count now includes
# customer-approved rows, matching what operators see in the field.
EXTRA_WORK_TERMINAL_STATUSES = (
    "COMPLETED",
    "CUSTOMER_REJECTED",
    "CANCELLED",
)
EXTRA_WORK_AWAITING_PRICING_STATUSES = ("REQUESTED", "UNDER_REVIEW")


def _is_provider_operator(user) -> bool:
    return user.role in PROVIDER_ROLES


def _parse_invoice_run_params(data):
    """Returns (company_id, year, month) or None if invalid."""
    try:
        company_id = int(data["company"])
        year = int(data["year"])
        month = int(data["month"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (1 <= month <= 12):
        return None
    return (company_id, year, month)


class ExtraWorkRequestViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticatedAndActive]
    # `filterset_class` runs AFTER `get_queryset`, so the scope helper
    # narrows the queryset first and the filter can only narrow further.
    # A CUSTOMER_USER passing `?customer=<id>` for a customer they have
    # no access to gets zero rows (scope removed them before the filter
    # ran). Non-integer values are rejected with HTTP 400 by django-
    # filter's NumberFilter.
    filterset_class = ExtraWorkRequestFilter

    def get_queryset(self):
        return scope_extra_work_for(self.request.user).select_related(
            "company", "building", "customer", "created_by"
        )

    def get_serializer_class(self):
        if self.action == "list":
            return ExtraWorkRequestListSerializer
        if self.action == "create":
            return ExtraWorkRequestCreateSerializer
        return ExtraWorkRequestDetailSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()

        # M1 B4 — emit the in-app "new extra-work request" notification to
        # provider management (action needed). Fires for every intent
        # (instant / auto-start / request-quote). Best-effort + logged: the
        # EW is already saved, so a notification fan-out failure must never
        # fail the create. The error is logged (not silently swallowed) so a
        # real bug stays visible.
        try:
            emit_extra_work_requested_notifications(
                instance, actor=instance.created_by
            )
        except Exception:  # noqa: BLE001 — best-effort fan-out, logged below
            logger.exception(
                "Failed to emit extra-work requested notification for EW %s",
                instance.pk,
            )

        # Read it back through the detail serializer so the
        # response shape matches what the GET /<id>/ endpoint
        # returns. The actor's role decides whether provider-
        # internal fields appear.
        detail = ExtraWorkRequestDetailSerializer(
            instance, context={"request": request}
        )
        return Response(detail.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request):
        """
        Sprint 5 — non-mutating cart preview / classification.

        Mirrors the create cart's scope + permission gate and the
        single source of truth in `extra_work.classification`. Zero DB
        writes: no ExtraWorkRequest / ExtraWorkRequestItem is created.

        HARD INVARIANT: provider default prices NEVER appear. Only the
        customer's OWN agreed contract price (the classification
        snapshot) is returned, and only for AGREED_CUSTOMER_PRICE
        lines. NEEDS_PROVIDER_PRICING / AD_HOC lines carry
        agreed_unit_price=null, agreed_vat_pct=null.
        """
        serializer = ExtraWorkPreviewSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        customer = data["customer"]
        building = data["building"]
        line_items = data["line_items"]
        supplied_intent = data.get("request_intent")

        actor_kind = derive_actor_kind(request.user, customer, building)

        per_line = [
            classify_line(
                service=line.get("service"),
                customer=customer,
                requested_date=line["requested_date"],
                custom_description=(line.get("custom_description") or ""),
            )
            for line in line_items
        ]
        cart = classify_cart(per_line)

        lines_payload = []
        for index, (line, classification) in enumerate(
            zip(line_items, per_line)
        ):
            service = line.get("service")
            is_agreed = (
                classification.source
                == ExtraWorkLinePriceSource.AGREED_CUSTOMER_PRICE
            )
            lines_payload.append(
                {
                    "index": index,
                    "service": service.id if service is not None else None,
                    "custom_description": (
                        line.get("custom_description") or ""
                    ),
                    "requested_date": line["requested_date"],
                    "quantity": _decimal_str(line["quantity"]),
                    "price_source": classification.source,
                    "service_name": classification.snapshot_service_name,
                    "service_category_name": (
                        classification.snapshot_service_category_name
                    ),
                    # Customer's OWN agreed price only — provider default
                    # prices are never serialized here.
                    "agreed_unit_price": (
                        _decimal_str(classification.snapshot_unit_price)
                        if is_agreed
                        else None
                    ),
                    "agreed_vat_pct": (
                        _decimal_str(classification.snapshot_vat_pct)
                        if is_agreed
                        else None
                    ),
                }
            )

        allowed_intents = []
        for intent in _PREVIEW_INTENT_ORDER:
            try:
                validate_intent_for_cart(
                    intent=intent, cart=cart, actor_kind=actor_kind
                )
            except IntentValidationError:
                continue
            allowed_intents.append(intent)

        payload = {
            "customer": customer.id,
            "building": building.id,
            "actor_kind": actor_kind,
            "lines": lines_payload,
            "cart": {
                "all_agreed": cart.all_agreed,
                "has_non_agreed": cart.has_non_agreed,
                "has_ad_hoc": cart.has_ad_hoc,
            },
            "allowed_intents": allowed_intents,
            "default_intent": derive_default_intent(cart),
        }

        if supplied_intent:
            payload["requested_intent"] = supplied_intent
            try:
                validate_intent_for_cart(
                    intent=supplied_intent,
                    cart=cart,
                    actor_kind=actor_kind,
                )
            except IntentValidationError as exc:
                payload["requested_intent_allowed"] = False
                payload["requested_intent_error"] = {
                    "code": exc.code,
                    "detail": exc.message,
                }
            else:
                payload["requested_intent_allowed"] = True

        return Response(payload, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="transition")
    def transition(self, request, pk=None):
        extra_work = self.get_object()  # 404 if out-of-scope
        payload = ExtraWorkTransitionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        to_status = data["to_status"]
        is_override = data.get("is_override", False)
        note = data.get("note", "")
        customer_reject_reason = data.get(
            "customer_reject_reason", ""
        ).strip()

        # Sprint 28 Batch 15.4 — a customer-driven PRICING_PROPOSED ->
        # CUSTOMER_REJECTED transition MUST carry a non-blank reason.
        # The provider override path bypasses this rule because it has
        # its own mandatory `override_reason` (state-machine layer
        # raises `override_reason_required` when missing).
        if (
            to_status == ExtraWorkStatus.CUSTOMER_REJECTED
            and not is_override
            and request.user.role == UserRole.CUSTOMER_USER
            and not customer_reject_reason
        ):
            return Response(
                {
                    "customer_reject_reason": (
                        "A reject reason is required."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Thread the customer reason into the status-history note so it
        # surfaces on the existing timeline UI. If the client also sent
        # a free-text `note`, prefix the reject reason so both pieces
        # are visible.
        if customer_reject_reason:
            if note:
                note = f"[Reject reason] {customer_reject_reason}\n\n{note}"
            else:
                note = f"[Reject reason] {customer_reject_reason}"

        try:
            updated = apply_transition(
                extra_work,
                request.user,
                to_status,
                note=note,
                is_override=is_override,
                override_reason=data.get("override_reason", ""),
            )
        except TransitionError as exc:
            return Response(
                {"detail": str(exc), "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            ExtraWorkRequestDetailSerializer(
                updated, context={"request": request}
            ).data
        )

    @action(detail=True, methods=["post"], url_path="actual-hours")
    def actual_hours(self, request, pk=None):
        """
        Sprint 8B — provider-only entry of actual hours on hourly Extra
        Work lines.

        Body: ``{"lines": [{"line_id": <id>, "actual_hours": "3.50"}, ...]}``

        Role gate runs BEFORE the object lookup so STAFF / customer-side
        actors get a stable 403 `actual_hours_forbidden` instead of a
        scope-driven 404 (STAFF scopes to `.none()`, so a post-lookup
        check would 404). Mirrors the Sprint 7B conversion endpoint
        shape.

        On success: stamps `actual_hours` + entered_by/at on each named
        line, recomputes the parent EW's `final_*`, writes one
        `ExtraWorkStatusHistory` annotation row, and returns the EW
        through the role-aware detail serializer (now carrying the
        `final_*` fields). Idempotent — re-submitting overwrites until
        the operational ticket is APPROVED/CLOSED (then 400
        `final_amount_locked`).
        """
        from decimal import Decimal, InvalidOperation

        from django.db import transaction
        from django.utils import timezone

        from rest_framework.exceptions import ErrorDetail

        from tickets.models import Ticket, TicketStatus

        from .final_amounts import active_priced_lines
        from .models import ExtraWorkPricingUnitType, ExtraWorkStatusHistory

        user = request.user

        # Role gate FIRST (before get_object) — blocks STAFF +
        # customer-side with a stable 403.
        if user.role not in PROVIDER_ROLES:
            return Response(
                {
                    "detail": "This role cannot enter actual hours.",
                    "code": "actual_hours_forbidden",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        extra_work = self.get_object()  # 404 if out-of-scope

        # Provider scope: SUPER_ADMIN passes; COMPANY_ADMIN /
        # BUILDING_MANAGER must hold provider-side building scope.
        if user.role != UserRole.SUPER_ADMIN and not user_has_osius_permission(
            user,
            "osius.ticket.view_building",
            building_id=extra_work.building_id,
        ):
            return Response(
                {
                    "detail": "You do not have provider-side scope for "
                    "this Extra Work request.",
                    "code": "actual_hours_forbidden",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Lock: once the operational ticket is APPROVED/CLOSED, the
        # final amount is frozen. Reopen required to edit further.
        locked_statuses = {
            str(TicketStatus.APPROVED),
            str(TicketStatus.CLOSED),
        }
        if (
            Ticket.objects.filter(extra_work_request=extra_work)
            .filter(status__in=list(locked_statuses))
            .exists()
        ):
            return Response(
                {
                    "detail": "Final amount is locked: the operational "
                    "ticket has been approved or closed. Reopen it to "
                    "edit actual hours.",
                    "code": "final_amount_locked",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = ActualHoursEntrySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        body_lines = payload.validated_data["lines"]

        # Resolve the active priced-line set; index by id for O(1)
        # membership + target lookup.
        kind, active_lines = active_priced_lines(extra_work)
        by_id = {line.id: line for line in active_lines}

        # Validate every body line against the active set BEFORE
        # mutating anything (all-or-nothing).
        targets: list = []
        for entry in body_lines:
            line_id = entry["line_id"]
            target = by_id.get(line_id)
            if target is None:
                return Response(
                    {
                        "detail": ErrorDetail(
                            f"Line {line_id} is not part of this Extra "
                            "Work request's active priced lines.",
                            code="actual_hours_invalid",
                        ),
                        "code": "actual_hours_invalid",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if str(target.unit_type) != ExtraWorkPricingUnitType.HOURS:
                return Response(
                    {
                        "detail": ErrorDetail(
                            f"Line {line_id} is not an hourly line; "
                            "actual hours cannot be entered.",
                            code="actual_hours_not_hourly",
                        ),
                        "code": "actual_hours_not_hourly",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            hours = entry["actual_hours"]
            try:
                hours = Decimal(hours)
            except (InvalidOperation, TypeError):
                return Response(
                    {
                        "detail": ErrorDetail(
                            f"Line {line_id} actual_hours is not a valid "
                            "number.",
                            code="actual_hours_invalid",
                        ),
                        "code": "actual_hours_invalid",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if hours <= Decimal("0"):
                return Response(
                    {
                        "detail": ErrorDetail(
                            f"Line {line_id} actual_hours must be greater "
                            "than zero.",
                            code="actual_hours_invalid",
                        ),
                        "code": "actual_hours_invalid",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            targets.append((target, hours))

        now = timezone.now()
        old_final_total = extra_work.final_total_amount
        trace_parts: list[str] = []
        with transaction.atomic():
            for target, hours in targets:
                old_hours = target.actual_hours
                target.actual_hours = hours
                target.actual_hours_entered_by = user
                target.actual_hours_entered_at = now
                target.save(
                    update_fields=[
                        "actual_hours",
                        "actual_hours_entered_by",
                        "actual_hours_entered_at",
                        "updated_at",
                    ]
                )
                trace_parts.append(
                    f"line {target.id}: "
                    f"{old_hours if old_hours is not None else '-'} -> "
                    f"{hours}"
                )

            extra_work.recompute_final_amounts()
            extra_work.refresh_from_db(fields=["final_total_amount"])

            note = (
                f"Actual hours entered by {user.email} "
                f"({kind} lines): " + "; ".join(trace_parts) + ". "
                f"final_total_amount "
                f"{old_final_total if old_final_total is not None else '-'} "
                f"-> {extra_work.final_total_amount}."
            )
            ExtraWorkStatusHistory.objects.create(
                extra_work=extra_work,
                old_status=extra_work.status,
                new_status=extra_work.status,
                changed_by=user,
                note=note,
                is_override=False,
            )

        return Response(
            ExtraWorkRequestDetailSerializer(
                extra_work, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["patch"], url_path="billing")
    def billing(self, request, *args, **kwargs):
        # Provider-only: set or clear this EW's invoice_date (billing month).
        # invoice_date is provider-internal (see _PROVIDER_ONLY_FIELDS) and
        # decoupled from customer_decided_at — work done May 31 / approved
        # Jun 7 still bills in May once the provider sets May here.
        ew = self.get_object()  # already tenant-scoped via the viewset queryset
        if not _is_provider_operator(request.user):
            return Response(
                {"detail": "Only provider operators can set the billing month."},
                status=status.HTTP_403_FORBIDDEN,
            )
        # Validate: a date, or null to clear. "invoice_date" key required.
        if "invoice_date" not in request.data:
            return Response(
                {"invoice_date": ["This field is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            parsed = serializers.DateField(allow_null=True).run_validation(
                request.data.get("invoice_date")
            )
        except serializers.ValidationError as exc:
            return Response(
                {"invoice_date": exc.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ew.invoice_date = parsed
        ew.save(update_fields=["invoice_date", "updated_at"])
        return Response(
            ExtraWorkRequestDetailSerializer(
                ew, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], url_path="status-history")
    def status_history(self, request, pk=None):
        extra_work = self.get_object()  # 404 if out-of-scope
        rows = ExtraWorkStatusHistory.objects.filter(extra_work=extra_work)
        # B1 — pass request context so the serializer's customer-side
        # note redaction (see ExtraWorkStatusHistorySerializer.get_note)
        # can fire. Without context the serializer cannot tell the
        # caller's role and would surface every note unfiltered.
        return Response(
            ExtraWorkStatusHistorySerializer(
                rows, many=True, context={"request": request}
            ).data
        )

    @action(detail=True, methods=["post"], url_path="spawn")
    def spawn(self, request, pk=None):
        """
        Sprint 30 Batch 30.1 — provider-only retry of the legacy
        pricing-flow ticket spawn.

        Recovers an EW that landed in CUSTOMER_APPROVED before this
        fix shipped (no tickets spawned at approval time) by firing
        the spawn helper manually. Not customer-callable.

        Preconditions:
          * Actor MUST be SUPER_ADMIN or COMPANY_ADMIN (the broader
            BUILDING_MANAGER scope is intentionally NOT admitted —
            this is a corrective admin action).
          * EW MUST be in CUSTOMER_APPROVED.
          * EW MUST have zero spawned tickets across BOTH spawn
            paths (cart-item FK + proposal-line FK chain).
        """
        extra_work = self.get_object()  # 404 if out-of-scope

        if request.user.role not in {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
        }:
            return Response(
                {
                    "detail": (
                        "Only SUPER_ADMIN or COMPANY_ADMIN may retry "
                        "Extra Work ticket spawn."
                    ),
                    "code": "spawn_forbidden_role",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # COMPANY_ADMIN must own the EW's company (mirrors the
        # provider-scope rule the rest of the EW endpoints use).
        if request.user.role == UserRole.COMPANY_ADMIN:
            if not user_has_osius_permission(
                request.user,
                "osius.ticket.view_building",
                building_id=extra_work.building_id,
            ):
                return Response(
                    {
                        "detail": "Not in scope for this Extra Work request.",
                        "code": "spawn_forbidden_scope",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        if extra_work.status != ExtraWorkStatus.CUSTOMER_APPROVED:
            return Response(
                {
                    "detail": (
                        "Retry spawn requires the Extra Work request "
                        "to be in CUSTOMER_APPROVED "
                        f"(current={extra_work.status})."
                    ),
                    "code": "spawn_wrong_status",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        from tickets.models import Ticket

        # Sprint 6A — request-level idempotency. A request spawns
        # exactly ONE operational Ticket; when it already exists, return
        # 200 with the existing id(s) instead of a 400 error so the
        # retry endpoint is safe to re-fire.
        existing_ids = list(
            Ticket.objects.filter(
                extra_work_request=extra_work
            ).values_list("id", flat=True)
        )
        if existing_ids:
            return Response(
                {
                    "spawned_ticket_ids": existing_ids,
                    "count": len(existing_ids),
                    "already_spawned": True,
                },
                status=status.HTTP_200_OK,
            )

        # Lazy import to keep view-module import cheap and avoid
        # the proposal_tickets <-> state_machine cycle at load time.
        from .proposal_tickets import spawn_tickets_for_extra_work_request

        from django.db import transaction

        with transaction.atomic():
            tickets = spawn_tickets_for_extra_work_request(
                extra_work, actor=request.user
            )

        return Response(
            {
                "spawned_ticket_ids": [t.id for t in tickets],
                "count": len(tickets),
                "already_spawned": False,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        """
        Sprint 28 Batch 9 — aggregate Extra Work stats scoped per role.

        Shape:
          {
            "total": int,
            "by_status": {status: count, ...},
            "by_routing": {"INSTANT": int, "PROPOSAL": int},
            "by_urgency": {"NORMAL": int, "HIGH": int, "URGENT": int},
            "active": int,                      # NOT in terminal set
            "awaiting_pricing": int,            # routing=PROPOSAL + REQUESTED/UNDER_REVIEW
            "awaiting_customer_approval": int,  # status == PRICING_PROPOSED
            "urgent": int,                      # URGENT urgency, not in terminal set
          }

        STAFF naturally gets all-zeros because `scope_extra_work_for`
        returns `.none()` for STAFF — operational visibility for STAFF
        lives on the spawned Ticket, not the parent EW (P0 staff-
        privacy decision, 2026-05-20 A4).
        """
        scoped = scope_extra_work_for(request.user)

        status_counts = {
            row["status"]: row["c"]
            for row in scoped.values("status").annotate(c=Count("id"))
        }
        routing_counts = {
            row["routing_decision"]: row["c"]
            for row in scoped.values("routing_decision").annotate(c=Count("id"))
        }
        urgency_counts = {
            row["urgency"]: row["c"]
            for row in scoped.values("urgency").annotate(c=Count("id"))
        }

        terminal_states = set(EXTRA_WORK_TERMINAL_STATUSES)
        active = sum(
            c for s, c in status_counts.items() if s not in terminal_states
        )
        awaiting_pricing = scoped.filter(
            routing_decision="PROPOSAL",
            status__in=list(EXTRA_WORK_AWAITING_PRICING_STATUSES),
        ).count()
        awaiting_customer_approval = status_counts.get("PRICING_PROPOSED", 0)
        urgent = (
            scoped.filter(urgency="URGENT")
            .exclude(status__in=list(EXTRA_WORK_TERMINAL_STATUSES))
            .count()
        )
        total = sum(status_counts.values())

        return Response(
            {
                "total": total,
                "by_status": status_counts,
                "by_routing": routing_counts,
                "by_urgency": urgency_counts,
                "active": active,
                "awaiting_pricing": awaiting_pricing,
                "awaiting_customer_approval": awaiting_customer_approval,
                "urgent": urgent,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="stats/by-building")
    def stats_by_building(self, request):
        """
        Sprint 28 Batch 9 — per-building Extra Work breakdown scoped
        per role.

        Returns a list ordered by building name. Buildings with no
        Extra Work rows in scope are skipped naturally by the GROUP BY
        (no padding rows). STAFF gets `[]` for the same reason `stats`
        zeroes out for them.
        """
        scoped = scope_extra_work_for(request.user)
        terminal = list(EXTRA_WORK_TERMINAL_STATUSES)
        awaiting_pricing_statuses = list(EXTRA_WORK_AWAITING_PRICING_STATUSES)

        rows = (
            scoped.values("building_id", "building__name")
            .annotate(
                total=Count("id"),
                active=Count("id", filter=~Q(status__in=terminal)),
                awaiting_pricing=Count(
                    "id",
                    filter=Q(routing_decision="PROPOSAL")
                    & Q(status__in=awaiting_pricing_statuses),
                ),
                awaiting_customer_approval=Count(
                    "id", filter=Q(status="PRICING_PROPOSED")
                ),
                urgent=Count(
                    "id",
                    filter=Q(urgency="URGENT") & ~Q(status__in=terminal),
                ),
            )
            .order_by("building__name")
        )

        return Response(
            [
                {
                    "building_id": row["building_id"],
                    "building_name": row["building__name"],
                    "total": row["total"],
                    "active": row["active"],
                    "awaiting_pricing": row["awaiting_pricing"],
                    "awaiting_customer_approval": row[
                        "awaiting_customer_approval"
                    ],
                    "urgent": row["urgent"],
                }
                for row in rows
            ],
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="mark-invoiced")
    def mark_invoiced(self, request):
        # DEPRECATED NO-OP (Invoicing Option 1, Phase 2a). The invoice is now
        # the SINGLE source of "invoiced" — a row is invoiced iff it is
        # claimed by a live InvoiceLine (see invoicing/selectors.py +
        # services.generate_draft_invoices). This legacy bulk run therefore
        # no longer mutates is_invoiced/invoiced_at. The route + provider gate
        # + response SHAPE are kept ONLY so the deployed Facturen page keeps
        # working; this endpoint and that page are removed together in Phase 4.
        if not _is_provider_operator(request.user):
            return Response(
                {"detail": "Only provider operators can run invoicing."},
                status=status.HTTP_403_FORBIDDEN,
            )
        parsed = _parse_invoice_run_params(request.data)
        if parsed is None:
            return Response(
                {"detail": "company (int), year (int), month (1-12) are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # No mutation — return the same shape with a zero count.
        return Response(
            {"invoiced_count": 0, "ew_ids": []},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="clear-invoiced")
    def clear_invoiced(self, request):
        # DEPRECATED NO-OP (Invoicing Option 1, Phase 2a) — see mark_invoiced.
        # Superseded by the invoice flow: releasing/deleting a draft invoice
        # is what returns EW to the unbilled pool now. Route + gate + response
        # SHAPE kept for the deployed Facturen page; removed in Phase 4.
        if not _is_provider_operator(request.user):
            return Response(
                {"detail": "Only provider operators can run invoicing."},
                status=status.HTTP_403_FORBIDDEN,
            )
        parsed = _parse_invoice_run_params(request.data)
        if parsed is None:
            return Response(
                {"detail": "company (int), year (int), month (1-12) are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # No mutation — return the same shape with a zero count.
        return Response(
            {"cleared_count": 0, "ew_ids": []},
            status=status.HTTP_200_OK,
        )


def _resolve_extra_work_or_404(request, ew_id: int) -> ExtraWorkRequest:
    qs = scope_extra_work_for(request.user)
    return get_object_or_404(qs, pk=ew_id)


def _require_provider_pricing_permission(request, extra_work):
    """Pricing line items can only be mutated by SUPER_ADMIN /
    COMPANY_ADMIN inside the company / BUILDING_MANAGER assigned
    to the building. Customer users get 403 (the scoping already
    let them GET the row, so we explicitly refuse mutation here)."""
    if not _is_provider_operator(request.user):
        return Response(
            {"detail": "Customer users cannot edit pricing line items."},
            status=status.HTTP_403_FORBIDDEN,
        )
    if request.user.role == UserRole.SUPER_ADMIN:
        return None
    if not user_has_osius_permission(
        request.user,
        "osius.ticket.view_building",
        building_id=extra_work.building_id,
    ):
        return Response(
            {"detail": "Not in scope for this building."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


class ExtraWorkPricingLineItemListCreateView(generics.GenericAPIView):
    """
    GET  -> list (any user in scope, customer serializer strips
            internal_cost_note)
    POST -> provider-only create + recompute aggregate totals
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, ew_id: int):
        extra_work = _resolve_extra_work_or_404(request, ew_id)
        rows = extra_work.pricing_line_items.all()
        if request.user.role == UserRole.CUSTOMER_USER:
            data = ExtraWorkPricingLineItemCustomerSerializer(
                rows, many=True
            ).data
        else:
            data = ExtraWorkPricingLineItemSerializer(rows, many=True).data
        return Response(data)

    def post(self, request, ew_id: int):
        extra_work = _resolve_extra_work_or_404(request, ew_id)
        guard = _require_provider_pricing_permission(request, extra_work)
        if guard is not None:
            return guard
        serializer = ExtraWorkPricingLineItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = serializer.save(extra_work=extra_work)
        extra_work.recompute_totals()
        return Response(
            ExtraWorkPricingLineItemSerializer(item).data,
            status=status.HTTP_201_CREATED,
        )


class ExtraWorkPricingLineItemDetailView(generics.GenericAPIView):
    """
    PATCH/DELETE for an individual pricing line item. Provider-only.
    Aggregates on the parent row are recomputed after every change.
    """

    permission_classes = [IsAuthenticated]

    def _resolve(self, request, ew_id: int, lid: int):
        extra_work = _resolve_extra_work_or_404(request, ew_id)
        item = get_object_or_404(
            ExtraWorkPricingLineItem, pk=lid, extra_work=extra_work
        )
        return extra_work, item

    def patch(self, request, ew_id: int, lid: int):
        extra_work, item = self._resolve(request, ew_id, lid)
        guard = _require_provider_pricing_permission(request, extra_work)
        if guard is not None:
            return guard
        serializer = ExtraWorkPricingLineItemSerializer(
            item, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        extra_work.recompute_totals()
        return Response(ExtraWorkPricingLineItemSerializer(item).data)

    def delete(self, request, ew_id: int, lid: int):
        extra_work, item = self._resolve(request, ew_id, lid)
        guard = _require_provider_pricing_permission(request, extra_work)
        if guard is not None:
            return guard
        item.delete()
        extra_work.recompute_totals()
        return Response(status=status.HTTP_204_NO_CONTENT)
