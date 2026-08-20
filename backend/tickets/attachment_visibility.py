"""
W4-P — WHERE A PHOTO LANDS, and the one place that decides it.

A staff photo's visibility is decided by up to four things: the
uploader's per-ticket permission, their standing permission, the
per-work `staff_uploads_customer_visible` setting, and the default.
The rule is:

    MOST SPECIFIC WINS.  per-ticket  >  standing  >  per-work setting
    >  default
    ANY EXPLICIT GRANT MAKES THE PHOTO CUSTOMER-VISIBLE.
    INTERNAL IS THE DEFAULT when nothing has been granted at any level.

So a per-ticket "no" beats a standing "yes" for that ticket, and a
standing "yes" beats the absence of a per-work setting.

Read the ladder top-down and stop at the first rung that has an opinion:

  1. PER-TICKET GRANT — an `UploadVisibilityGrant` row for this uploader
     with `ticket=this ticket`. True -> CUSTOMER, False -> INTERNAL.
     No row -> next rung.
  2. STANDING GRANT — an `UploadVisibilityGrant` row for this uploader
     with `ticket=NULL`. True -> CUSTOMER, False -> INTERNAL. No row ->
     next rung.
  3. PER-WORK SETTING — `Ticket.staff_uploads_customer_visible`. True ->
     CUSTOMER. False is NOT a refusal: the column's default is False and
     "nobody ever opened this work up" is an absence, not a decision, so
     False -> next rung. This is the one rung that speaks in only one
     direction, and it is worth knowing why: a boolean with a default
     cannot tell "off" from "never set", and reading its default as a
     veto would make the standing grant unusable on every work in the
     system.
  4. DEFAULT — INTERNAL. Nothing a worker uploads crosses the customer
     wall until somebody says so.

TWO THINGS SIT ABOVE THE LADDER and are not part of it:

  * A CUSTOMER-SIDE UPLOADER's own file is always CUSTOMER. Hiding a
    file from the person who just uploaded it would be a bug, not a
    privacy win, and it was never internal in the first place.
  * PROVIDER MANAGEMENT MAY TYPE A VALUE at upload time. A person who
    states a visibility outranks a rule that guesses one. STAFF and
    customer-side callers cannot (the serializer 400s them), so they get
    the ladder.

WHAT THIS DOES NOT DECIDE. Not who may SEE a stored row — that is the
customer wall in `TicketAttachmentListCreateView.get_queryset` and
`TicketAttachmentDownloadView`, both of which still run, and neither of
which a grant can widen past the ticket's own customer. Not whether a
photo counts as completion evidence — the gates read `is_hidden` and
never `visibility`, so a worker's INTERNAL photo is still proof the work
happened. And not anything about a row that already exists: a grant
changes the level the NEXT upload lands at and never rewrites history.

WHO MAY GRANT is in `views_upload_visibility.py`, and the short version
is: never the person receiving it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from accounts.permissions import is_staff_role

from .models import (
    AttachmentVisibility,
    UploadVisibilityGrant,
    UploadVisibilitySource,
)


@dataclass(frozen=True)
class ResolvedVisibility:
    """The answer plus the rung that produced it.

    The rung is not decoration: it is stored on the attachment
    (`TicketAttachment.visibility_source`) and shown in the UI, so an
    operator asking "why is this internal?" gets an answer from the
    product instead of from a developer.
    """

    visibility: str
    source: str

    @property
    def is_customer_visible(self) -> bool:
        return self.visibility == AttachmentVisibility.CUSTOMER


def _grant_value(user_id: int, ticket_id: Optional[int]) -> Optional[bool]:
    """The explicit decision at ONE rung, or None for "no opinion".

    `ticket_id=None` reads the standing rung. Returning None rather than
    False for a missing row is the whole three-state shape — see
    `UploadVisibilityGrant`.
    """
    row = (
        UploadVisibilityGrant.objects.filter(
            user_id=user_id, ticket_id=ticket_id
        )
        .values_list("uploads_customer_visible", flat=True)
        .first()
    )
    return row


def per_ticket_grant(user, ticket) -> Optional[bool]:
    """Rung 1. None = this person has no per-ticket decision here."""
    return _grant_value(user.id, ticket.id)


def standing_grant(user) -> Optional[bool]:
    """Rung 2. None = this person has no standing decision."""
    return _grant_value(user.id, None)


def resolve_upload_visibility(ticket, uploader) -> ResolvedVisibility:
    """Run the ladder for an upload that did not carry a chosen value.

    This is THE default. `TicketAttachmentListCreateView` calls it and
    nothing else re-implements it; the per-ticket / standing endpoints
    call it only to PREVIEW what the next upload would do, never to
    write a second copy of the rule.
    """
    # Above the ladder: a customer's own file.
    if not is_staff_role(uploader):
        return ResolvedVisibility(
            AttachmentVisibility.CUSTOMER,
            UploadVisibilitySource.CUSTOMER_UPLOAD,
        )

    # 1. Per-ticket.
    decision = per_ticket_grant(uploader, ticket)
    if decision is not None:
        return ResolvedVisibility(
            AttachmentVisibility.CUSTOMER
            if decision
            else AttachmentVisibility.INTERNAL,
            UploadVisibilitySource.TICKET_GRANT,
        )

    # 2. Standing.
    decision = standing_grant(uploader)
    if decision is not None:
        return ResolvedVisibility(
            AttachmentVisibility.CUSTOMER
            if decision
            else AttachmentVisibility.INTERNAL,
            UploadVisibilitySource.STANDING_GRANT,
        )

    # 3. Per-work setting. True only; see the module docstring for why
    #    False falls through instead of vetoing.
    if ticket.staff_uploads_customer_visible:
        return ResolvedVisibility(
            AttachmentVisibility.CUSTOMER,
            UploadVisibilitySource.WORK_SETTING,
        )

    # 4. Default.
    return ResolvedVisibility(
        AttachmentVisibility.INTERNAL,
        UploadVisibilitySource.DEFAULT_INTERNAL,
    )
