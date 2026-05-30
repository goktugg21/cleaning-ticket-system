"""
Sprint 2A — Extra Work cart classification + intent validation.

Single source of truth for the per-line "is this line agreed,
needs-pricing, or ad-hoc?" question and the cart-level
"which `request_intent` values are valid here for this actor?"
question.

Public surface:

  * classify_line(*, service, customer, requested_date,
                  custom_description) -> LineClassification
        Per-line classification. The serializer + a future
        preview/classification endpoint MUST call this — frontend
        must never infer the source label client-side.
  * classify_cart(lines, customer) -> CartClassification
        Aggregate across N lines.
  * validate_intent_for_cart(*, intent, cart, actor_kind) -> None
        Raises `IntentValidationError` on rejection with a stable
        `code` matching the Sprint 2A error-code list:
            intent_requires_all_agreed
            intent_requires_non_agreed_line
            intent_forbidden_for_role
            intent_forbidden_for_provider
        (`intent_required` and the per-line
        `line_requires_service_or_description` /
        `ad_hoc_line_requires_provider_pricing` codes live in the
        serializer layer where the raw payload is parsed.)

`actor_kind` is a coarse classification: "PROVIDER" / "CUSTOMER_USER"
/ "CUSTOMER_LOCATION_MANAGER" / "CUSTOMER_COMPANY_ADMIN" / "STAFF".
The serializer derives it from `User.role` + the actor's
`CustomerUserBuildingAccess.access_role` for the target
(customer, building). Centralising the role plumbing here would
re-import accounts + customers from this leaf module; we deliberately
keep that concern in the serializer so this module stays a pure
business-rules helper.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, List, Optional

from .models import (
    CustomerServicePrice,
    ExtraWorkLinePriceSource,
    ExtraWorkRequestIntent,
    Service,
)
from .pricing import resolve_price


# Coarse actor kinds (see module docstring).
ACTOR_PROVIDER = "PROVIDER"
ACTOR_STAFF = "STAFF"
ACTOR_CUSTOMER_USER = "CUSTOMER_USER"
ACTOR_CUSTOMER_LOCATION_MANAGER = "CUSTOMER_LOCATION_MANAGER"
ACTOR_CUSTOMER_COMPANY_ADMIN = "CUSTOMER_COMPANY_ADMIN"

_CUSTOMER_SIDE_ACTORS = {
    ACTOR_CUSTOMER_USER,
    ACTOR_CUSTOMER_LOCATION_MANAGER,
    ACTOR_CUSTOMER_COMPANY_ADMIN,
}
# Customer-side actors that may pre-authorise AUTO_START. The
# baseline CUSTOMER_USER access role is excluded by the SoT (only
# Customer Location Manager and Customer Company Admin may use
# AUTO_START_AFTER_PRICING).
_AUTO_START_ELIGIBLE_CUSTOMER_ACTORS = {
    ACTOR_CUSTOMER_LOCATION_MANAGER,
    ACTOR_CUSTOMER_COMPANY_ADMIN,
}


class IntentValidationError(Exception):
    """Raised by validate_intent_for_cart on rejection. The
    serializer translates this to a DRF ValidationError with the
    same stable `code` attribute."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LineClassification:
    """Result of classifying one cart line."""

    source: str  # ExtraWorkLinePriceSource value
    contract: Optional[CustomerServicePrice]
    # Snapshot fields the create serializer copies onto
    # ExtraWorkRequestItem when source == AGREED_CUSTOMER_PRICE.
    snapshot_unit_price: Optional[object] = None
    snapshot_vat_pct: Optional[object] = None
    snapshot_service_name: str = ""
    snapshot_service_category_name: str = ""


@dataclass(frozen=True)
class CartClassification:
    """Aggregate cart-level classification booleans."""

    line_classifications: List[LineClassification]
    all_agreed: bool
    has_non_agreed: bool  # NEEDS_PROVIDER_PRICING or AD_HOC line present
    has_ad_hoc: bool


def classify_line(
    *,
    service: Optional[Service],
    customer,
    requested_date: date,
    custom_description: str,
) -> LineClassification:
    """Classify one cart line.

    Rule (matches `ExtraWorkLinePriceSource` docstring):
      * service is None ⇒ AD_HOC (no catalog row → provider must
        enter a price; SoT §5.6 says ad-hoc lines always count as
        needs-provider-pricing).
      * service is set + `resolve_price()` returns a contract row
        ⇒ AGREED_CUSTOMER_PRICE with snapshot.
      * service is set + resolver returns None ⇒
        NEEDS_PROVIDER_PRICING.
    """
    if service is None:
        # Ad-hoc / free-text line. `custom_description` is the
        # operator-facing label and is captured on the line; we do
        # not need to surface it on the classification result
        # because the serializer already has the raw value.
        return LineClassification(
            source=ExtraWorkLinePriceSource.AD_HOC,
            contract=None,
        )

    contract = resolve_price(service, customer, on=requested_date)
    if contract is None:
        return LineClassification(
            source=ExtraWorkLinePriceSource.NEEDS_PROVIDER_PRICING,
            contract=None,
            snapshot_service_name=service.name,
            snapshot_service_category_name=service.category.name,
        )
    return LineClassification(
        source=ExtraWorkLinePriceSource.AGREED_CUSTOMER_PRICE,
        contract=contract,
        snapshot_unit_price=contract.unit_price,
        snapshot_vat_pct=contract.vat_pct,
        snapshot_service_name=service.name,
        snapshot_service_category_name=service.category.name,
    )


def classify_cart(lines: Iterable[LineClassification]) -> CartClassification:
    """Aggregate per-line classifications into the cart-level
    booleans used by `validate_intent_for_cart`."""
    line_list = list(lines)
    sources = {c.source for c in line_list}
    all_agreed = bool(line_list) and sources == {
        ExtraWorkLinePriceSource.AGREED_CUSTOMER_PRICE
    }
    has_non_agreed = bool(
        sources
        & {
            ExtraWorkLinePriceSource.NEEDS_PROVIDER_PRICING,
            ExtraWorkLinePriceSource.AD_HOC,
        }
    )
    has_ad_hoc = ExtraWorkLinePriceSource.AD_HOC in sources
    return CartClassification(
        line_classifications=line_list,
        all_agreed=all_agreed,
        has_non_agreed=has_non_agreed,
        has_ad_hoc=has_ad_hoc,
    )


def derive_default_intent(cart: CartClassification) -> str:
    """Sprint 2A — backward-compat: when a caller does not send
    `request_intent`, infer the safest historical value:
      * all-agreed cart ⇒ DIRECT_AGREED_PRICE_ORDER (matches the
        legacy INSTANT routing decision's effective behaviour).
      * any non-agreed line ⇒ REQUEST_QUOTE (the only option that
        ALWAYS requires customer approval before spawning work; the
        AUTO_START path would silently skip customer approval and
        must be opt-in explicitly).
    """
    if cart.all_agreed:
        return ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER
    return ExtraWorkRequestIntent.REQUEST_QUOTE


def validate_intent_for_cart(
    *,
    intent: str,
    cart: CartClassification,
    actor_kind: str,
) -> None:
    """Validate a caller-supplied `request_intent` against the cart
    and actor. Raises `IntentValidationError` on rejection.

    Rule set (SoT §5.1–§5.5):
      * DIRECT_AGREED_PRICE_ORDER
          - cart.all_agreed must be True.
          - cart must contain at least one line.
          - allowed for provider and customer actors.
      * AUTO_START_AFTER_PRICING
          - cart.has_non_agreed must be True.
          - allowed actors: PROVIDER,
            CUSTOMER_LOCATION_MANAGER, CUSTOMER_COMPANY_ADMIN.
          - basic CUSTOMER_USER is forbidden.
          - STAFF is forbidden.
      * REQUEST_QUOTE
          - cart.has_non_agreed must be True.
          - forbidden for PROVIDER (the SoT says the provider does
            not ask itself for a quote).
          - STAFF is forbidden.
          - allowed for all customer-side actors.
    """
    if intent == ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER:
        if not cart.line_classifications:
            # Empty cart is rejected at the serializer layer with a
            # different error (line_items required); this branch is
            # a defensive belt-and-braces.
            raise IntentValidationError(
                "intent_requires_all_agreed",
                "Direct agreed-price order requires at least one line.",
            )
        if not cart.all_agreed:
            raise IntentValidationError(
                "intent_requires_all_agreed",
                "Direct agreed-price order requires every line to "
                "resolve to a customer-specific agreed price.",
            )
        if actor_kind == ACTOR_STAFF:
            raise IntentValidationError(
                "intent_forbidden_for_role",
                "STAFF cannot create Extra Work.",
            )
        return

    if intent == ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING:
        if not cart.has_non_agreed:
            raise IntentValidationError(
                "intent_requires_non_agreed_line",
                "Auto-start after pricing requires at least one "
                "non-agreed or ad-hoc line.",
            )
        if actor_kind == ACTOR_STAFF:
            raise IntentValidationError(
                "intent_forbidden_for_role",
                "STAFF cannot create Extra Work.",
            )
        if actor_kind == ACTOR_PROVIDER:
            # Provider on behalf of customer is allowed (SoT §5.3
            # last bullet: "Provider can open Extra Work on behalf
            # of customer using direct agreed-price order or
            # auto-start-after-pricing").
            return
        if actor_kind not in _AUTO_START_ELIGIBLE_CUSTOMER_ACTORS:
            # Basic CUSTOMER_USER lands here. SoT §5.3 + §2.7
            # require the minimum customer-side role to be
            # Customer Location Manager.
            raise IntentValidationError(
                "intent_forbidden_for_role",
                "Auto-start after pricing requires Customer Location "
                "Manager or Customer Company Admin.",
            )
        return

    if intent == ExtraWorkRequestIntent.REQUEST_QUOTE:
        if not cart.has_non_agreed:
            raise IntentValidationError(
                "intent_requires_non_agreed_line",
                "Request a quote requires at least one non-agreed "
                "or ad-hoc line. An all-agreed cart must use direct "
                "agreed-price order.",
            )
        if actor_kind == ACTOR_PROVIDER:
            raise IntentValidationError(
                "intent_forbidden_for_provider",
                "Provider cannot use Request a quote for itself.",
            )
        if actor_kind == ACTOR_STAFF:
            raise IntentValidationError(
                "intent_forbidden_for_role",
                "STAFF cannot create Extra Work.",
            )
        if actor_kind not in _CUSTOMER_SIDE_ACTORS:
            raise IntentValidationError(
                "intent_forbidden_for_role",
                "Only customer-side actors may use Request a quote.",
            )
        return

    # Unknown intent string (defensive — the serializer's ChoiceField
    # already filters this before we are called).
    raise IntentValidationError(
        "intent_required",
        f"Unknown request intent: {intent!r}.",
    )
