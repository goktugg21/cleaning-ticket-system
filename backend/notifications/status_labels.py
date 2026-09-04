"""
Sprint 184 §1 — the Dutch status vocabulary the CUSTOMER reads in email.

## Why this file exists rather than a dict inside `services.py`

The owner has asked three times that one status read one way everywhere.
The screens were fixed; email was not, because it kept its own
hand-written list. Three of eight words disagreed with the app:

    email said                      the screen says
    Wacht op goedkeuring            Wacht op klant
    Goedgekeurd                     Werk akkoord
    Wacht op controle beheerder     Wacht op beheerder

"Goedgekeurd" is the exact word that was deliberately replaced for being
ambiguous — a ticket's APPROVED means the customer accepted the finished
WORK — and the customer was still receiving it. The list was also
missing CONVERTED_TO_EXTRA_WORK, and `_status_label` fell back to
`str(value)`, so a customer could receive the literal text
`CONVERTED_TO_EXTRA_WORK` in an email.

## Why the backend cannot simply READ the frontend bundle

The vocabulary's home is `frontend/src/i18n/nl/common.json`. The backend
image is built from `backend/` alone (`docker-compose.yml` mounts
`./backend:/app`; the prod Dockerfile copies the same), so that file does
not exist at runtime — not in dev, not on crmtest. One line, as the
sprint asked for.

So this module is the backend's copy, and `tests/test_sprint184_status_
vocabulary.py` is what stops it becoming a second vocabulary again:

  * a test that runs EVERYWHERE asserts the map covers every member of
    `TicketStatus` — that is the half that let CONVERTED_TO_EXTRA_WORK
    leak as a raw code;
  * a test that runs WHEREVER THE REPO IS CHECKED OUT WHOLE — which is
    CI, the gate that matters — asserts every string is byte-identical
    to the frontend bundle's `ticket_status.*` block. That is the half
    that let three words drift.

Keep the two in step by editing the frontend bundle first and this file
second; the test names the file and the key when they disagree.
"""
from __future__ import annotations

from tickets.models import TicketStatus

# The i18n key each status is spelled by, so the divergence test can name
# the exact key that drifted rather than only the status.
STATUS_I18N_KEY = {
    TicketStatus.OPEN: "ticket_status.open",
    TicketStatus.IN_PROGRESS: "ticket_status.in_progress",
    TicketStatus.WAITING_MANAGER_REVIEW: "ticket_status.waiting_manager_review",
    TicketStatus.WAITING_CUSTOMER_APPROVAL: "ticket_status.waiting_customer_approval",
    TicketStatus.APPROVED: "ticket_status.approved",
    TicketStatus.REJECTED: "ticket_status.rejected",
    TicketStatus.CLOSED: "ticket_status.closed",
    TicketStatus.REOPENED_BY_ADMIN: "ticket_status.reopened_by_admin",
    TicketStatus.CONVERTED_TO_EXTRA_WORK: "ticket_status.converted_to_extra_work",
    # W-N1 — both maps grow together. The sibling test asserts their key
    # sets are equal precisely so one growing alone cannot make the
    # byte-identity check silently skip a status instead of failing.
    TicketStatus.ACKNOWLEDGED: "ticket_status.acknowledged",
    TicketStatus.ON_HOLD: "ticket_status.on_hold",
}

# The strings themselves, copied from `frontend/src/i18n/nl/common.json`.
TICKET_STATUS_LABEL_NL = {
    TicketStatus.OPEN: "Open",
    TicketStatus.IN_PROGRESS: "In behandeling",
    TicketStatus.WAITING_MANAGER_REVIEW: "Wacht op beheerder",
    TicketStatus.WAITING_CUSTOMER_APPROVAL: "Wacht op klant",
    TicketStatus.APPROVED: "Werk akkoord",
    TicketStatus.REJECTED: "Afgewezen",
    TicketStatus.CLOSED: "Gesloten",
    TicketStatus.REOPENED_BY_ADMIN: "Heropend",
    TicketStatus.CONVERTED_TO_EXTRA_WORK: "Geconverteerd naar meerwerk",
    # W-N1 — ACKNOWLEDGED and ON_HOLD reached `TicketStatus` without
    # reaching this map, so `_status_label` fell back to `str(value)`
    # and a customer whose ticket was put on hold could be emailed the
    # literal text `ON_HOLD`. Byte-identical to `ticket_status.*` in
    # `frontend/src/i18n/nl/common.json`, which is what the sibling test
    # asserts wherever the repo is checked out whole.
    TicketStatus.ACKNOWLEDGED: "Ingepland, nog niet gestart",
    TicketStatus.ON_HOLD: "In wacht",
}

# P-16 Part D — the English mirror, copied from
# `frontend/src/i18n/en/common.json`'s `ticket_status.*` block. Same
# contract as the Dutch map above: the catalogue test asserts it covers
# every member of `TicketStatus`, and (where the repo is checked out
# whole) that every string is byte-identical to the en bundle. Keep the
# two in step by editing the frontend bundle first and this file second.
TICKET_STATUS_LABEL_EN = {
    TicketStatus.OPEN: "Open",
    TicketStatus.IN_PROGRESS: "In progress",
    TicketStatus.WAITING_MANAGER_REVIEW: "Waiting for the manager",
    TicketStatus.WAITING_CUSTOMER_APPROVAL: "Waiting for the customer",
    TicketStatus.APPROVED: "Work approved",
    TicketStatus.REJECTED: "Rejected",
    TicketStatus.CLOSED: "Closed",
    TicketStatus.REOPENED_BY_ADMIN: "Reopened",
    TicketStatus.CONVERTED_TO_EXTRA_WORK: "Converted to extra work",
    TicketStatus.ACKNOWLEDGED: "Scheduled, not started",
    TicketStatus.ON_HOLD: "On hold",
}

# What a status nobody has a word for renders as. NOT the raw code: a
# customer receiving `CONVERTED_TO_EXTRA_WORK` in an email learns nothing
# and is shown the inside of the machine. The completeness test makes
# this unreachable for a real status; it exists for a value that is not
# one at all.
UNKNOWN_STATUS_LABEL_NL = "Onbekende status"
UNKNOWN_STATUS_LABEL_EN = "Unknown status"


def ticket_status_label_nl(value) -> str:
    """The Dutch word for a ticket status, for email subjects and bodies."""
    try:
        return TICKET_STATUS_LABEL_NL[TicketStatus(value)]
    except (ValueError, KeyError):
        return UNKNOWN_STATUS_LABEL_NL


def ticket_status_label(value, lang: str) -> str:
    """The word for a ticket status in `lang` (P-16 Part D — the
    catalogue renders per recipient/viewer language)."""
    if lang == "en":
        try:
            return TICKET_STATUS_LABEL_EN[TicketStatus(value)]
        except (ValueError, KeyError):
            return UNKNOWN_STATUS_LABEL_EN
    return ticket_status_label_nl(value)
