"""
M1 B6 — Extra Work message visibility + posting authz.

Mirrors `tickets.permissions` (the B5 ticket message model) for the Extra
Work domain, MINUS the staff dimension: STAFF have no Extra Work scope and
must see / post NOTHING in EW messages.

Three channels (SA = SUPER_ADMIN, MGMT = COMPANY_ADMIN / BUILDING_MANAGER,
CUST = customer-side):

  READ-VISIBILITY (who may SEE a NORMAL EW message of each tier):
    PUBLIC_REPLY        SA y  MGMT y  CUST y
    INTERNAL_NOTE       SA y  MGMT y  CUST n
    CUSTOMER_INTERNAL   SA y  MGMT n  CUST y     (SA forensic only)
    STAFF: nothing (no row sees STAFF; staff have no EW scope anyway).

  POSTING:
    PUBLIC_REPLY = CUST + MGMT + SA;  INTERNAL_NOTE = MGMT + SA;
    CUSTOMER_INTERNAL = CUST.  STAFF: nothing.

`ew_message_type_visible_to_user` (predicate) and `filter_ew_messages_
visible_to` layer (a) (queryset excludes) are the SAME table in two forms and
MUST stay in lockstep (a parity regression test asserts it). EVERY EW-message
read / count path MUST route through `filter_ew_messages_visible_to`.
"""
from __future__ import annotations

from accounts.permissions import (
    is_customer_side,
    is_provider_management_role,
    is_staff_role,
    is_super_admin,
)


def ew_message_type_visible_to_user(user, message_type):
    """ROLE-based read visibility for an `ExtraWorkMessage.message_type`.

    The canonical READ table (three channels). This function and
    `filter_ew_messages_visible_to` layer (a) are the SAME table expressed two
    ways and MUST stay in lockstep:

      message_type        SA   MGMT  CUST
      ------------------   ---  ----  ----
      PUBLIC_REPLY          v    v     v
      INTERNAL_NOTE         v    v     -
      CUSTOMER_INTERNAL     v    -     v

    STAFF -> False (no EW scope, no EW message). SA is checked FIRST (it keeps
    a forensic read of every tier incl. CUSTOMER_INTERNAL; MGMT must NOT see
    CUSTOMER_INTERNAL). ROLE gate only — EW SCOPE (`scope_extra_work_for`) is
    checked separately by callers.
    """
    from .models import ExtraWorkMessageType

    if is_super_admin(user):
        return True  # forensic — every tier.
    if is_provider_management_role(user):  # MGMT (SA handled above).
        return message_type != ExtraWorkMessageType.CUSTOMER_INTERNAL
    if is_staff_role(user):  # STAFF — nothing in Extra Work.
        return False
    return message_type in (  # customer-side / anyone else.
        ExtraWorkMessageType.PUBLIC_REPLY,
        ExtraWorkMessageType.CUSTOMER_INTERNAL,
    )


def filter_ew_messages_visible_to(qs, user):
    """The SINGLE chokepoint for ExtraWorkMessage read visibility.

    AND-s two layers; each only ever NARROWS:

      (a) role tier filter — the SAME table `ew_message_type_visible_to_user`
          encodes, as queryset excludes:
            * SA   — every tier (forensic).
            * MGMT — every tier EXCEPT CUSTOMER_INTERNAL.
            * STAFF — NOTHING (`qs.none()`; staff have no EW scope).
            * customer-side / userless — every tier EXCEPT INTERNAL_NOTE.
      (b) RESTRICTED party filter — applied UNCONDITIONALLY so it binds EVERY
          role, SA included (SA is bound on the per-record list; its forensic
          path for restricted content is the global audit log). A RESTRICTED
          message is visible iff the viewer is the author OR a directed_to
          member. NORMAL rows are never dropped.

    A userless / unauthenticated caller is treated as customer-side in (a) and
    a non-party in (b) (NORMAL-only).
    """
    from django.db.models import Exists, OuterRef, Q

    from .models import (
        ExtraWorkMessage,
        ExtraWorkMessageType,
        ExtraWorkMessageVisibility,
    )

    user_id = getattr(user, "id", None)

    # (a) role tier filter — mirrors ew_message_type_visible_to_user exactly.
    if is_super_admin(user):
        pass  # forensic — no tier exclusion.
    elif is_provider_management_role(user):  # MGMT (SA handled above).
        qs = qs.exclude(message_type=ExtraWorkMessageType.CUSTOMER_INTERNAL)
    elif is_staff_role(user):  # STAFF — no EW messages at all.
        return qs.none()
    else:  # customer-side / userless.
        qs = qs.exclude(message_type=ExtraWorkMessageType.INTERNAL_NOTE)

    # (b) RESTRICTED party filter — unconditional, via an Exists() correlated
    # subquery (no directed_to join -> no fan-out / no .distinct()).
    if user_id is None:
        return qs.filter(visibility_mode=ExtraWorkMessageVisibility.NORMAL)

    through = ExtraWorkMessage.directed_to.through
    return qs.annotate(
        _directed_to_me=Exists(
            through.objects.filter(
                extraworkmessage_id=OuterRef("pk"), user_id=user_id
            )
        )
    ).filter(
        Q(visibility_mode=ExtraWorkMessageVisibility.NORMAL)
        | Q(author_id=user_id)
        | Q(_directed_to_me=True)
    )


def user_may_post_ew_message_type(user, message_type):
    """M1 B6 — the POSTING table (who may CREATE each EW message tier). Single
    source of truth for the message-create authz; the create-actions
    `can_post_*` flags mirror this so the composer only offers a tier the POST
    will accept:

      PUBLIC_REPLY       CUST + MGMT + SA
      INTERNAL_NOTE      MGMT + SA
      CUSTOMER_INTERNAL  CUST

    STAFF -> False for every tier (no EW scope, no EW post).
    """
    from .models import ExtraWorkMessageType

    if message_type == ExtraWorkMessageType.PUBLIC_REPLY:
        return is_customer_side(user) or is_provider_management_role(user)
    if message_type == ExtraWorkMessageType.INTERNAL_NOTE:
        return is_provider_management_role(user)
    if message_type == ExtraWorkMessageType.CUSTOMER_INTERNAL:
        return is_customer_side(user)
    return False
