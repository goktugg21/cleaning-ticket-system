"""P-15 §0.1 / H-12 — who may COMMIT an invoice.

Addendum B §B.8 gates every `InvoiceViewSet` write on the provider
OPERATOR set (SA / CA / BM). P-14's owner question — "a building
manager is a full invoice operator; is that wanted?" — was answered by
the 0.1 ruling: **issuing, sending, un-issuing and reversing an
invoice are company-level acts (CA / SA only).** Sending allocates the
gapless number and emails the customer — a company act, not a building
act. A building manager KEEPS the building-level half: drafts,
preview, draft edits/lines, delete-draft, PDF, the lists.

Un-issue and reverse ride the same tier: un-issue is the undo of a
company-level act, and a reversal is a committed, numbered
counter-document.

One helper and one stable code, read by BOTH layers of the deliberate
double gate (the view's `_forbid_non_admin` and the state machine's
re-checks) so they cannot drift.
"""
from __future__ import annotations

from accounts.models import UserRole


#: Stable refusal code — the frontend renders its own sentence per code
#: (the P-8 error-body law).
ERR_INVOICE_ADMIN_ONLY = "invoice_admin_only"

#: The refusal sentence, addressed to the building manager whose draft
#: is fine and whose next actor is the company admin.
INVOICE_ADMIN_ONLY_DETAIL = (
    "Sending is done by the company admin. Your draft is ready for them."
)


def is_invoice_admin(user) -> bool:
    """SA / CA — the roles that may issue, send, un-issue or reverse."""
    return getattr(user, "role", None) in (
        UserRole.SUPER_ADMIN,
        UserRole.COMPANY_ADMIN,
    )
