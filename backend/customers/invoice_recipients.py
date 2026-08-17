"""
Sprint 185 §2 — who receives a customer's invoices.

One question, answered once. The Contact rows carrying
`receives_invoices` are the answer; this module is where "the invoice
recipients of customer X" is resolved so the send path, the API and any
future reminder cannot each grow their own version of it.

## What was actually there before this sprint

Nothing, and the shape of the nothing matters:

  * **No invoice mail path exists at all.** `invoicing.models` says so in
    as many words — "SEND = customer-portal visibility only. EMAIL
    DELIVERY IS EXPLICITLY DEFERRED to a later version". Sending an
    invoice makes it VISIBLE in the customer portal; it has never put a
    document in anyone's inbox.
  * The only invoice-adjacent mail is `invoicing.tasks._notify_run`,
    which tells the OPERATOR that a nightly run produced drafts. It
    carries no PDF and goes to the actor, not the customer.
  * Every notification recipient in this system is a USER ACCOUNT.
    `Contact` was read by two display screens and written to by nobody.

So "add recipients to the existing invoice mail" could not be done as
written: there was no invoice mail to add them to. What this sprint does
instead is the honest version of the same instruction — it builds the
recipient list and extends the ONE existing logged sender
(`notifications.services.send_logged_email`) to carry the document, so
that when the send is wired up there is still exactly one sender and one
log. It does NOT add a second mail path, which is the thing the
instruction was actually protecting.
"""
from __future__ import annotations

from .models import Contact


def invoice_contact_recipients(customer) -> list[Contact]:
    """The contacts flagged to receive `customer`'s invoices.

    Only contacts with an e-mail address are returned — a recipient with
    no address is not a recipient. `skipped_invoice_contacts` reports the
    others rather than letting them disappear, because "I ticked the box
    and they got nothing" is exactly the silence this feature exists to
    remove.

    Ordered by name so a log line, a test and a UI list agree.
    """
    if customer is None:
        return []
    return list(
        Contact.objects.filter(customer=customer, receives_invoices=True)
        .exclude(email="")
        .order_by("full_name", "id")
    )


def skipped_invoice_contacts(customer) -> list[Contact]:
    """Flagged to receive invoices, but with no e-mail address.

    Surfaced deliberately. A contact ticked as an invoice recipient who
    cannot be sent anything is an operator mistake worth reporting at the
    moment it costs something, not a row to filter out quietly.
    """
    if customer is None:
        return []
    return list(
        Contact.objects.filter(
            customer=customer, receives_invoices=True, email=""
        ).order_by("full_name", "id")
    )
