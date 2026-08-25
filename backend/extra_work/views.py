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
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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
    ExtraWorkRequestItem,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
    Proposal,
    ProposalStatus,
)
from .scoping import scope_extra_work_for
from .label_validation import (
    issued_invoice_locking_labels,
    validate_labels_for_customer,
)
from .dates import apply_extra_work_dates
from .planning import PlanRejected, apply_plan
from .serializers import (
    ERR_DEADLINE_PROVIDER_ONLY,
    ActualHoursEntrySerializer,
    ExtraWorkDatesSerializer,
    ExtraWorkLabelsSerializer,
    ExtraWorkPlanSerializer,
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
from .views_financials import is_priced_expression


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

# W2-D — one code for both refusals on the plan action (wrong role, and
# right role without provider-side scope on this building). Same shape
# as `ERR_DEADLINE_PROVIDER_ONLY`: the caller learns it may not plan
# this work, and learns nothing about the work itself.
ERR_PLAN_PROVIDER_ONLY = "plan_provider_only"


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
        from tickets.models import Ticket

        # Sprint 180 §1 — "has an operational ticket been born from this
        # extra work?" is the ONE question the two list tracks split on,
        # and it is answered by the CANONICAL FK (`Ticket.
        # extra_work_request`) alone — the same definition
        # `extra_work.billing.build_ticket_map` and
        # `reports.dimensions` already use to decide what is earned and
        # what may be invoiced. `tickets.filters` unions two more legacy
        # chains for its `?extra_work_request=` filter; where the two
        # disagree, the money definition wins.
        #
        # ONE EXISTS subquery for the whole page, not a query per row —
        # the `views_catalog.ServiceListCreateView` precedent
        # (`annotated_has_price_rows`). Soft-deleted tickets are
        # excluded, mirroring `build_ticket_map`: a deleted ticket
        # cannot make work "started".
        spawned = Ticket.objects.filter(
            extra_work_request_id=OuterRef("pk"), deleted_at__isnull=True
        )
        # Sprint 188 — "has anyone put a price on this yet?", so a list can
        # print an em dash instead of EUR 0,00 for work nobody has priced.
        # Zero is a LEGAL price (free work, a goodwill line); the two must
        # not render the same.
        #
        # W1-C moved the expression itself to `views_financials.
        # is_priced_expression` when the money strip needed the same
        # answer over an aggregate. One definition, two callers: a second
        # copy would be a second opinion, and only one of them would be
        # the one the money rule agrees with.
        is_priced = is_priced_expression()
        return (
            scope_extra_work_for(self.request.user)
            .select_related(
                # Sprint 127 — department / work_type joined so the list
                # serializer's `*_name` fields never trigger a per-row
                # lookup.
                "company", "building", "customer", "created_by",
                "department", "work_type",
                # W5-B — the day-by-day series, so the list serializer's
                # `group` block does not fetch the group per row. The
                # per-page memo in `get_group` covers the member COUNTS;
                # this covers the group row itself.
                "group",
            )
            .annotate(
                annotated_has_operational_ticket=Exists(spawned),
                annotated_is_priced=is_priced,
            )
            .prefetch_related(
                # Sprint 180 §2 — the spawned ticket(s) themselves, so
                # the list can print the ticket number and link to it
                # without a fetch per row. `.only()` because the list
                # needs four columns of a ticket, not a ticket.
                Prefetch(
                    "operational_tickets",
                    queryset=Ticket.objects.filter(
                        deleted_at__isnull=True
                    )
                    .only("id", "ticket_no", "status", "extra_work_request_id")
                    .order_by("id"),
                    to_attr="prefetched_operational_tickets",
                ),
                # Sprint 180 §2 — kills a REAL N+1 that predates this
                # sprint: `started_before_plan` is declared on the list
                # serializer and its model property read the status
                # history per row. The property now iterates
                # `status_history.all()`, which this prefetch answers
                # once for the whole page.
                "status_history",
            )
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
                # Sprint 137 item 6 — orderable per-customer custom
                # price. Classifies AD_HOC exactly as create does.
                custom_price=line.get("custom_price"),
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
            line_custom_price = line.get("custom_price")
            lines_payload.append(
                {
                    "index": index,
                    "service": service.id if service is not None else None,
                    # Sprint 137 item 6 — a custom-price line stays
                    # AD_HOC (`price_source` above is untouched), but
                    # its amount IS known, so it is returned rather than
                    # rendered as "to be priced by the provider". These
                    # three keys are null on every other line kind.
                    "custom_price": (
                        line_custom_price.id
                        if line_custom_price is not None
                        else None
                    ),
                    "custom_price_unit_price": (
                        _decimal_str(classification.snapshot_unit_price)
                        if line_custom_price is not None
                        else None
                    ),
                    "custom_price_vat_pct": (
                        _decimal_str(classification.snapshot_vat_pct)
                        if line_custom_price is not None
                        else None
                    ),
                    "custom_description": (
                        classification.custom_description
                        or line.get("custom_description")
                        or ""
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

        # W-PLAN — the workflow card's direct UNDER_REVIEW ->
        # PRICING_PROPOSED leg is a pricing door too (the proposal
        # views are the other two). Same gate, same bypass. At the
        # VIEW, not in `apply_transition` — the primitive walks states
        # for seeders and tests, and W13-FIX's lesson stands: a
        # form-completeness rule on the primitive is the wrong layer.
        if to_status == ExtraWorkStatus.PRICING_PROPOSED:
            from .planning import check_pricing_plan_gate

            gate = check_pricing_plan_gate(
                extra_work, request.data, actor=request.user
            )
            if gate is not None:
                return Response(
                    gate, status=status.HTTP_400_BAD_REQUEST
                )
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

    @action(detail=True, methods=["patch"], url_path="labels")
    def labels(self, request, pk=None):
        """Sprint 127.1 — provider relabel: set / clear `department` +
        `work_type` on an existing Extra Work AFTER creation.

        The create serializer is the only OTHER writer of these fields, so
        without this action a ticket-converted EW (built by
        `conversion.py`'s direct ORM create) could never be labelled, and a
        mislabel could never be corrected — the report / invoice grouping
        these fields drive would have nothing to group on.

        Provider-side operational classification, so PROVIDER_ROLES only —
        the same audience the actual-hours / conversion endpoints use
        (SUPER_ADMIN global; COMPANY_ADMIN / BUILDING_MANAGER need
        provider-side building scope on the EW's building). A customer user
        gets 403; a cross-tenant id 404s through the viewset's own scope
        helper (no bespoke check). Relabelling an already-invoiced EW is
        ALLOWED — the invoice is an issued document, unaffected; the audit
        row records who changed it.
        """
        user = request.user

        # Role gate FIRST (before get_object) so customer-side / STAFF get a
        # stable 403 rather than a scope-driven 404. Mirrors actual_hours.
        if user.role not in PROVIDER_ROLES:
            return Response(
                {
                    "detail": "This role cannot relabel Extra Work.",
                    "code": "relabel_forbidden",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        extra_work = self.get_object()  # 404 if out-of-scope (cross-tenant)

        # Provider scope: SUPER_ADMIN global; COMPANY_ADMIN / BUILDING_MANAGER
        # must hold provider-side building scope on this EW's building.
        if user.role != UserRole.SUPER_ADMIN and not user_has_osius_permission(
            user,
            "osius.ticket.view_building",
            building_id=extra_work.building_id,
        ):
            return Response(
                {
                    "detail": "You do not have provider-side scope for this "
                    "Extra Work request.",
                    "code": "relabel_forbidden",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        payload = ExtraWorkLabelsSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        # Key presence distinguishes "sent as null" (clear) from "absent"
        # (leave unchanged); an empty body changes nothing → 400.
        if "department" not in data and "work_type" not in data:
            return Response(
                {
                    "detail": "Provide department and/or work_type to set or "
                    "clear.",
                    "code": "no_labels_provided",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Sprint 127.2 — once this EW's work sits on an ISSUED invoice its
        # labels are immutable (set OR clear), so the Department Report and
        # issued invoices stay reconcilable. Correcting a mislabel means
        # credit the invoice, relabel, re-invoice. The message names the
        # document to credit. NB: keyed on the live issued-invoice link, NOT
        # `is_invoiced` (that claim flag is set at DRAFT gen — the draft
        # window stays open).
        locking_invoice = issued_invoice_locking_labels(extra_work)
        if locking_invoice is not None:
            # Sprint 129 §2b — no "CONCEPT" literal. Name the number when the
            # invoice has one (SENT); otherwise say "an issued invoice"
            # (ISSUED-but-unsent has no number yet). The frontend maps the
            # `labels_locked_by_invoice` code to its own localized message;
            # this `detail` is the fallback and must stay language-neutral of
            # that string.
            if locking_invoice.number:
                detail = (
                    f"This Extra Work is on issued invoice "
                    f"{locking_invoice.number}; its department / work type are "
                    f"locked. Credit that invoice, relabel, then re-invoice."
                )
            else:
                detail = (
                    "This Extra Work is on an issued invoice; its department / "
                    "work type are locked. Credit that invoice, relabel, then "
                    "re-invoice."
                )
            return Response(
                {"detail": detail, "code": "labels_locked_by_invoice"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # THE one invariant — the SAME validator the create serializer runs,
        # so the two label-write paths cannot drift. Skips null (a clear).
        validate_labels_for_customer(
            extra_work.customer,
            department=data.get("department"),
            work_type=data.get("work_type"),
        )

        update_fields = []
        if "department" in data:
            extra_work.department = data["department"]
            update_fields.append("department")
        if "work_type" in data:
            extra_work.work_type = data["work_type"]
            update_fields.append("work_type")
        # `updated_at` (auto_now) + the changed FK(s); the save fires the
        # ExtraWorkRequest audit handler, which now tracks the label FKs.
        update_fields.append("updated_at")
        extra_work.save(update_fields=update_fields)

        return Response(
            ExtraWorkRequestDetailSerializer(
                extra_work, context={"request": request}
            ).data
        )

    @action(detail=True, methods=["patch"], url_path="dates")
    def dates(self, request, pk=None):
        """Sprint 176 §3 — set / clear `deadline` and `planned_end_date` on
        an existing Extra Work AFTER creation.

        Until now both were write-once on the create form, which is the
        wrong shape for a deadline: a deadline is exactly the kind of thing
        agreed after the fact, on the phone, once someone has looked at the
        job. Sprint 173 put the fields in the database and Sprint 174 put
        them on the create form; neither gave anyone a way to change one.

        Deliberately the SAME shape as the `labels` action above rather
        than a new update mixin — the ViewSet has no update action by
        design, and adding one just to move two dates would expose every
        field on the model to PATCH.

        Role gate FIRST (before `get_object`) so customer-side / STAFF get
        a stable 403 rather than a scope-driven 404, exactly as `labels`
        and `actual_hours` do. That gate IS the §3 decision: the customer's
        wish is `preferred_date`; the deadline is the provider's
        commitment.

        Unlike the labels, an issued invoice does NOT lock these. A date is
        an operational fact about when the work was due, not a billing fact
        on the document — moving it changes no amount and no invoice line.
        """
        user = request.user

        if user.role not in PROVIDER_ROLES:
            return Response(
                {
                    "detail": "This role cannot set Extra Work dates. A "
                    "deadline is a provider commitment.",
                    "code": ERR_DEADLINE_PROVIDER_ONLY,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        extra_work = self.get_object()  # 404 if out-of-scope (cross-tenant)

        # Provider scope, identical to `labels`: SUPER_ADMIN global;
        # COMPANY_ADMIN / BUILDING_MANAGER need provider-side building
        # scope on this EW's building.
        if user.role != UserRole.SUPER_ADMIN and not user_has_osius_permission(
            user,
            "osius.ticket.view_building",
            building_id=extra_work.building_id,
        ):
            return Response(
                {
                    "detail": "You do not have provider-side scope for this "
                    "Extra Work request.",
                    "code": ERR_DEADLINE_PROVIDER_ONLY,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        payload = ExtraWorkDatesSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        # Key presence distinguishes "sent as null" (clear) from "absent"
        # (leave unchanged) — the convention the bulk dialog's "leave
        # unchanged" default depends on. An empty body changes nothing.
        if (
            "deadline" not in data
            and "planned_end_date" not in data
            and "provider_planned_date" not in data
        ):
            return Response(
                {
                    "detail": "Provide deadline, planned_end_date and/or "
                    "provider_planned_date to set or clear.",
                    "code": "no_dates_provided",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        error = apply_extra_work_dates(extra_work, data)
        if error is not None:
            return Response(error, status=status.HTTP_400_BAD_REQUEST)

        payload = ExtraWorkRequestDetailSerializer(
            extra_work, context={"request": request}
        ).data
        # Sprint 184 §1 — say what happened to the spawned tickets.
        #
        # Planning an extra work for a day moves its tickets onto that
        # day, EXCEPT any a person rescheduled by hand with a written
        # reason — those keep their own date. Reported alongside the row
        # rather than swallowed: an operator who plans a job and later
        # finds its ticket still on the old day deserves to be told why,
        # at the moment they did it.
        ticket_result = getattr(
            extra_work, "planned_date_ticket_result", None
        )
        if ticket_result is not None:
            payload["tickets_moved"] = ticket_result["moved"]
            payload["tickets_kept_own_date"] = ticket_result["kept_own_date"]
        return Response(payload)

    @action(
        detail=True,
        methods=["post"],
        url_path="plan",
        # JSON ONLY, and this is a correctness fix rather than a
        # preference. DRF's `BooleanField.get_value` treats a boolean
        # that is ABSENT from HTML form input as `False` — because an
        # unchecked checkbox sends nothing — so with the default parser
        # set a form-encoded plan that never mentioned
        # `file_upload_required` would silently write it to False on
        # every work it touched. That is precisely the reference
        # system's defect, rebuilt in our own code by a framework
        # default. The payload carries a nested list (`planned_hours`)
        # that form encoding cannot express anyway.
        parser_classes=[JSONParser],
    )
    def plan(self, request, pk=None):
        """W2-D — plan the work, and start it. One action, one call.

        Body (every field optional; ABSENT MEANS LEAVE UNCHANGED):

            {"budget_hours": "8.00",
             "provider_planned_date": "2026-09-01",
             "provider_planned_end_date": "2026-09-03",
             "planned_hours": [{"user": 12, "hours": "4.00"}, ...],
             "file_upload_required": true,
             "completion_notes_required": false,
             "start": true}

        The rules and the evidence behind them are in
        `extra_work.planning`; the three that decide how this endpoint
        BEHAVES are worth repeating where somebody reads the HTTP layer:

        * **Overrun warns, it never blocks.** Distributing more hours
          than the budget returns 200 with a `hours_overrun` warning in
          the `plan` block. The save has already happened.
        * **A start that cannot happen is reported, not raised.** Once
          the work has an operational ticket its status follows that
          ticket (Sprint 181 §1), so `started` comes back false with
          `start_skipped: "operational_status_follows_ticket"` and the
          plan still lands. Throwing away a correct plan because of a
          state the operator can see on their screen would be the wrong
          trade.
        * **The customer's dates are not touched.** `preferred_date`,
          `planned_end_date` and `deadline` have their own endpoint
          (`/dates/`); this one writes the provider's committed window
          only, so planning can never move the date we are measured
          against.

        Role gate FIRST (before `get_object`), exactly as `dates` and
        `actual_hours` do, so a customer-side or STAFF actor gets a
        stable 403 instead of a scope-driven 404.
        """
        user = request.user

        if user.role not in PROVIDER_ROLES:
            return Response(
                {
                    "detail": "This role cannot plan Extra Work. "
                    "Planning is a provider action.",
                    "code": ERR_PLAN_PROVIDER_ONLY,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        extra_work = self.get_object()  # 404 if out-of-scope (cross-tenant)

        if user.role != UserRole.SUPER_ADMIN and not user_has_osius_permission(
            user,
            "osius.ticket.view_building",
            building_id=extra_work.building_id,
        ):
            return Response(
                {
                    "detail": "You do not have provider-side scope for this "
                    "Extra Work request.",
                    "code": ERR_PLAN_PROVIDER_ONLY,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        payload = ExtraWorkPlanSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        # `PlanRejected` propagates OUT of the atomic block on purpose:
        # caught inside it, a refusal would commit whatever had already
        # been written. `apply_plan` resolves everything before it
        # writes anything, so this is belt and braces — but the belt is
        # what makes it true regardless of how `apply_plan` changes.
        try:
            with transaction.atomic():
                result = apply_plan(
                    extra_work, payload.validated_data, actor=user
                )
        except PlanRejected as exc:
            return Response(exc.body, status=status.HTTP_400_BAD_REQUEST)

        data = ExtraWorkRequestDetailSerializer(
            extra_work, context={"request": request}
        ).data
        data["plan"] = result
        return Response(data, status=status.HTTP_200_OK)

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

        # Sprint 182 §1 — THE INVOICE LOCK, on the money path.
        #
        # Checked BEFORE the ticket-status lock below, and that order is
        # the point. The ticket lock's own message invites the operator
        # to "reopen it to edit actual hours" — and reopening a ticket
        # was a legitimate thing to do until you notice that the work is
        # already on an invoice the customer has been sent. Doing it
        # then rewrites the amount behind a document that has left the
        # building. Offering that instruction on a row we already know
        # is invoiced is the defect, so this check gets there first and
        # says something else.
        #
        # `issued_invoice_locking_labels` is the SAME predicate the
        # label lock uses (ISSUED/SENT, not soft-deleted, not reversed;
        # a DRAFT deliberately does not lock, because the draft window
        # is the correction window). Reused rather than re-expressed:
        # "may this extra work still change" must not have two answers,
        # and money is the half that was missing.
        #
        # The way out is the same as for a mislabel and it is the
        # correct business action rather than a workaround: reverse the
        # invoice, which releases the extra work, then edit, then
        # re-invoice.
        locking_invoice = issued_invoice_locking_labels(extra_work)
        if locking_invoice is not None:
            return Response(
                {
                    "detail": (
                        "Actual hours are locked: this extra work is on "
                        f"invoice {locking_invoice.number or 'CONCEPT'}, "
                        "which has been issued. Reverse that invoice "
                        "first if the amount is wrong."
                    ),
                    "code": "actual_hours_invoice_locked",
                    "invoice_id": locking_invoice.id,
                    "invoice_number": locking_invoice.number,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Lock: once the operational ticket is APPROVED/CLOSED, the
        # final amount is frozen. Reopen required to edit further.
        #
        # Sprint 182 §4 — `deleted_at__isnull=True`: a soft-deleted
        # ticket is not an operational ticket, and letting one hold this
        # lock froze the amount of an extra work that no longer had a
        # live ticket at all.
        locked_statuses = {
            str(TicketStatus.APPROVED),
            str(TicketStatus.CLOSED),
        }
        if (
            Ticket.objects.filter(
                extra_work_request=extra_work, deleted_at__isnull=True
            )
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
        #
        # Sprint 182 §4 — `deleted_at__isnull=True`. Without it a
        # SOFT-DELETED ticket still occupied the slot: the retry button
        # reported "already spawned" and handed back the id of a ticket
        # nobody can open, so an extra work whose ticket had been
        # deleted could never get another one. The delete is refused
        # outright now (`tickets/views.py` destroy), but this query was
        # wrong on its own terms and a guard elsewhere is not a reason
        # to leave it that way.
        existing_ids = list(
            Ticket.objects.filter(
                extra_work_request=extra_work, deleted_at__isnull=True
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


class ExtraWorkCategoryOptionsView(APIView):
    """Sprint 143 §6 — the options for the Extra Work list's category
    filter, split into what still exists and what only survives in
    history.

    The client cannot compute the second group: it needs the set of
    `ExtraWorkRequestItem.snapshot_service_category_name` values that no
    longer match any live `ServiceCategory`, and it never sees line items
    on the list endpoint. Hence one small server-side view.

    Both lists are derived from the SCOPED Extra Work queryset
    (`scope_extra_work_for`), so a filter option can never reveal a
    category name from a company the actor cannot see — the same rule
    Sprint 142 established for the catalog itself, applied to the
    dropdown that filters over it.

    `live` is what the actor's own catalog currently offers, ACTIVE only:
    the filter should not offer a retired category as if it were current
    (it will still appear under `historical` if any shipped request used
    it, which is exactly where a retired category belongs).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        from .catalog_scope import filter_categories_for
        from .models import ServiceCategory

        live_qs = filter_categories_for(
            request.user, ServiceCategory.objects.filter(is_active=True)
        )
        live = sorted({c.name for c in live_qs})
        live_normalized = {n.strip().lower() for n in live}

        scoped = scope_extra_work_for(request.user)
        used = (
            ExtraWorkRequestItem.objects.filter(extra_work_request__in=scoped)
            .exclude(snapshot_service_category_name="")
            .values_list("snapshot_service_category_name", flat=True)
            .distinct()
        )
        # A name is "historical" when nothing live matches it — the
        # category was renamed, archived or deleted after the order was
        # placed. Deduped case-insensitively so two spellings of the same
        # retired name do not both appear.
        historical = {}
        for raw in used:
            key = (raw or "").strip().lower()
            if not key or key in live_normalized:
                continue
            historical.setdefault(key, raw)

        return Response(
            {
                "live": live,
                "historical": sorted(historical.values()),
            },
            status=status.HTTP_200_OK,
        )


def _resolve_extra_work_or_404(request, ew_id: int) -> ExtraWorkRequest:
    qs = scope_extra_work_for(request.user)
    return get_object_or_404(qs, pk=ew_id)


def _require_legacy_pricing_is_the_owner(extra_work):
    """Sprint 188 — the legacy `/pricing-items/` surface must not
    overwrite a quote the Proposal route froze.

    `ExtraWorkRequest.recompute_totals()` and
    `final_amounts.recompute_quoted_totals()` write the SAME three
    columns from DIFFERENT line sets. Sprint 187 gave the proposal route
    a writer without noticing the legacy one already had the pen: with a
    CUSTOMER_APPROVED proposal in place, `active_priced_lines` resolves
    to that proposal's lines, so posting one legacy pricing row here
    would replace an approved EUR 484.00 quote with the sum of whatever
    was posted — no override recorded, no history row, and the customer
    still approved the old number.

    Once a proposal is approved it owns the money. Corrections go
    through the proposal, not around it.
    """
    if extra_work.proposals.filter(
        status=ProposalStatus.CUSTOMER_APPROVED
    ).exists():
        return Response(
            {
                "detail": (
                    "This extra work is priced by an approved proposal. "
                    "Change the price on the proposal; the legacy pricing "
                    "lines no longer decide what it costs."
                ),
                "code": "legacy_pricing_locked_by_proposal",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    return None


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
        locked = _require_legacy_pricing_is_the_owner(extra_work)
        if locked is not None:
            return locked
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
        locked = _require_legacy_pricing_is_the_owner(extra_work)
        if locked is not None:
            return locked
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
        locked = _require_legacy_pricing_is_the_owner(extra_work)
        if locked is not None:
            return locked
        item.delete()
        extra_work.recompute_totals()
        return Response(status=status.HTTP_204_NO_CONTENT)
