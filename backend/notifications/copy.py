"""P-16 Part D — the notification copy catalogue (§D.13.3, the hybrid).

ONE mechanism for every notification's words: a keyed catalogue, two
languages, rendered server-side. Email renders at SEND time in the
RECIPIENT's language and the rendered text is stored on the
`NotificationLog` row — the audit record stays verbatim, exactly what
was sent. The bell renders at READ time in the VIEWER's language: the
`Notification` row stores `template_key` + `params` beside its rendered
`summary` cache, and the serializer re-renders per viewer. Old rows
without a key keep printing their stored text.

RULES OF THE CATALOGUE
----------------------
* Params carry NAMES and NUMBERS, never ids that can vanish. A date
  crosses as an ISO string (`*_iso`) and is formatted per language at
  render time; a status/priority/type crosses as its stable enum code
  and is resolved through the label maps below.
* nl is primary. The Dutch strings are byte-identical to what the
  pre-catalogue composers produced (fifteen tests pin fragments of
  them); the English strings mirror the Dutch in the voice of the
  guidance standard — talks like a person, §D.2 words only.
* Rendering must NEVER raise: a missing param renders as an empty
  string (`_SafeParams`), a malformed date prints as its raw value, an
  unknown key returns None and the caller falls back to the stored
  text. A bell feed that 500s over one old row is worse than a blank
  line in it.

Every value under a key is either a `{"nl": ..., "en": ...}` template
pair or a callable `(params, lang) -> str` for the bodies that need
conditional lines or row lists. `render_summary` / `render_email` /
`title_for_event` are the only doors.
"""
from __future__ import annotations

import datetime
import logging

logger = logging.getLogger(__name__)

LANGS = ("nl", "en")


def resolve_lang(value) -> str:
    """Collapse anything to one of the two supported languages."""
    return "en" if value == "en" else "nl"


class _SafeParams(dict):
    """format_map source that renders a missing key as an empty string
    rather than raising — an old row must never break the feed."""

    def __missing__(self, key):  # noqa: D105 — trivial
        return ""


# ---------------------------------------------------------------------------
# Label maps — the stable enum codes cross in params; the words live here.
# The NL ticket-status words come from `status_labels.py` (byte-identical
# to the frontend bundle, test-pinned); the EN mirror lives beside it.
# ---------------------------------------------------------------------------

_ROLE_LABELS = {
    "nl": {
        "SUPER_ADMIN": "Superbeheerder",
        "COMPANY_ADMIN": "Bedrijfsbeheerder",
        "BUILDING_MANAGER": "Beheerder",
        "CUSTOMER_USER": "Klant",
        "STAFF": "Medewerker",
    },
    "en": {
        "SUPER_ADMIN": "Super admin",
        "COMPANY_ADMIN": "Company admin",
        "BUILDING_MANAGER": "Manager",
        "CUSTOMER_USER": "Customer",
        "STAFF": "Employee",
    },
}

_TYPE_LABELS = {
    "nl": {
        "REPORT": "Melding",
        "COMPLAINT": "Klacht",
        "REQUEST": "Verzoek",
        "SUGGESTION": "Suggestie",
        "QUOTE_REQUEST": "Offerteaanvraag",
    },
    "en": {
        "REPORT": "Report",
        "COMPLAINT": "Complaint",
        "REQUEST": "Request",
        "SUGGESTION": "Suggestion",
        "QUOTE_REQUEST": "Quote request",
    },
}

_PRIORITY_LABELS = {
    "nl": {"NORMAL": "Normaal", "HIGH": "Hoog", "URGENT": "Urgent"},
    "en": {"NORMAL": "Normal", "HIGH": "High", "URGENT": "Urgent"},
}


def status_label(value, lang: str) -> str:
    from .status_labels import ticket_status_label
    return ticket_status_label(value, lang)


def role_label(value, lang: str) -> str:
    return _ROLE_LABELS[resolve_lang(lang)].get(str(value), str(value))


def type_label(value, lang: str) -> str:
    return _TYPE_LABELS[resolve_lang(lang)].get(str(value), str(value))


def priority_label(value, lang: str) -> str:
    return _PRIORITY_LABELS[resolve_lang(lang)].get(str(value), str(value))


# ---------------------------------------------------------------------------
# Date and plural helpers
# ---------------------------------------------------------------------------

_MONTHS = {
    "nl": ["jan", "feb", "mrt", "apr", "mei", "jun",
           "jul", "aug", "sep", "okt", "nov", "dec"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}


def _parse_date(iso):
    try:
        return datetime.date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return None


def _dmy(iso) -> str:
    """`2026-08-20` -> `20-08-2026` (the format the pinned mails use)."""
    day = _parse_date(iso)
    return day.strftime("%d-%m-%Y") if day else str(iso or "")


def _dm(iso) -> str:
    """`2026-08-20` -> `20-08` (the weekly summary's short format)."""
    day = _parse_date(iso)
    return day.strftime("%d-%m") if day else str(iso or "")


def _day_month(iso, lang: str) -> str:
    """`2026-08-20` -> `20 aug` / `20 Aug` (the ladder's format)."""
    day = _parse_date(iso)
    if day is None:
        return str(iso or "")
    return f"{day.day} {_MONTHS[resolve_lang(lang)][day.month - 1]}"


def _days_phrase(n, lang: str) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 0
    if resolve_lang(lang) == "en":
        return f"{n} day" if n == 1 else f"{n} days"
    return f"{n} dag" if n == 1 else f"{n} dagen"


# ---------------------------------------------------------------------------
# Shared blocks
# ---------------------------------------------------------------------------

_SIGN_OFF = {
    "nl": [
        "",
        "Met vriendelijke groet,",
        "het CleanOps-team",
        "",
        "Deze e-mail is automatisch verzonden. U kunt niet rechtstreeks reageren op dit bericht.",
    ],
    "en": [
        "",
        "Kind regards,",
        "the CleanOps team",
        "",
        "This e-mail was sent automatically. You cannot reply to it directly.",
    ],
}

_FACT_LABELS = {
    "nl": {
        "ticket": "Ticket",
        "subject": "Onderwerp",
        "status": "Status",
        "priority": "Prioriteit",
        "type": "Type",
        "company": "Bedrijf",
        "building": "Gebouw",
        "customer": "Klant",
        "room": "Ruimte",
        "assigned_to": "Toegewezen aan",
        "description": "Omschrijving:",
    },
    "en": {
        "ticket": "Ticket",
        "subject": "Subject",
        "status": "Status",
        "priority": "Priority",
        "type": "Type",
        "company": "Company",
        "building": "Building",
        "customer": "Customer",
        "room": "Room",
        "assigned_to": "Assigned to",
        "description": "Description:",
    },
}


def ticket_facts_params(ticket) -> dict:
    """The ticket facts every lifecycle mail carries, as plain values.

    Names and codes only — the words for the codes are resolved per
    language at render time. This is the params half of the old
    `_ticket_summary`; `_facts_block` below is the render half.
    """
    return {
        "ticket_no": ticket.ticket_no,
        "ticket_title": ticket.title,
        "status": str(ticket.status),
        "priority": str(ticket.priority),
        "type": str(ticket.type),
        "company_name": ticket.company.name,
        "building_name": ticket.building.name,
        "customer_name": ticket.customer.name,
        "room_label": ticket.room_label or "",
        "assigned_to_email": (
            ticket.assigned_to.email if ticket.assigned_to_id else ""
        ),
        "description": ticket.description,
    }


def _facts_block(params, lang: str) -> str:
    labels = _FACT_LABELS[lang]
    lines = [
        f"{labels['ticket']}: {params.get('ticket_no', '')}",
        f"{labels['subject']}: {params.get('ticket_title', '')}",
        f"{labels['status']}: {status_label(params.get('status'), lang)}",
        f"{labels['priority']}: {priority_label(params.get('priority'), lang)}",
        f"{labels['type']}: {type_label(params.get('type'), lang)}",
        f"{labels['company']}: {params.get('company_name', '')}",
        f"{labels['building']}: {params.get('building_name', '')}",
        f"{labels['customer']}: {params.get('customer_name', '')}",
    ]
    if params.get("room_label"):
        lines.append(f"{labels['room']}: {params['room_label']}")
    if params.get("assigned_to_email"):
        lines.append(f"{labels['assigned_to']}: {params['assigned_to_email']}")
    lines.extend(["", labels["description"], params.get("description", "")])
    return "\n".join(lines)


# The billing-cutoff paragraph (W1-B item 14) — the rule stated in the
# same mail that asks the customer to approve.
_BILLING_CUTOFF = {
    "nl": [
        "",
        "Let op — facturatie:",
        "Werk dat vóór uw facturatiedatum is afgerond, komt op de "
        "eerstvolgende factuur te staan, ook als uw goedkeuring op dat "
        "moment nog niet binnen is. Zo staat het werk op de factuur van de "
        "maand waarin het echt is uitgevoerd.",
        "Keurt u het werk daarna alsnog af? Dan draaien wij de factuur terug "
        "met een creditnota en verdwijnt het werk weer van uw rekening.",
    ],
    "en": [
        "",
        "Please note — invoicing:",
        "Work finished before your billing date goes on the next invoice, "
        "even if your approval has not come in by then. That way the work "
        "is on the invoice of the month it was really done in.",
        "If you reject the work afterwards, we reverse the invoice with a "
        "credit note and the work disappears from your bill again.",
    ],
}


# ---------------------------------------------------------------------------
# Bodies that need conditional lines or row lists
# ---------------------------------------------------------------------------

def _body_ticket_created(params, lang):
    intro = {
        "nl": "Er is een nieuwe ticket aangemaakt.",
        "en": "A new ticket has been created.",
    }
    return "\n".join(
        [intro[lang], "", _facts_block(params, lang)] + _SIGN_OFF[lang]
    )


def _body_ticket_status_changed(params, lang):
    labels = {
        "nl": ("De status van een ticket is gewijzigd.",
               "Oude status", "Nieuwe status"),
        "en": ("The status of a ticket has changed.",
               "Old status", "New status"),
    }[lang]
    lines = [
        labels[0],
        "",
        f"{labels[1]}: {status_label(params.get('old_status'), lang)}",
        f"{labels[2]}: {status_label(params.get('new_status'), lang)}",
        "",
        _facts_block(params, lang),
    ]
    if params.get("with_billing_cutoff"):
        lines.extend(_BILLING_CUTOFF[lang])
    return "\n".join(lines + _SIGN_OFF[lang])


def _decision_word(params, lang):
    approved = bool(params.get("approved"))
    if lang == "en":
        return "Approved" if approved else "Rejected"
    return "Goedgekeurd" if approved else "Afgewezen"


def _subject_decided_on_behalf(params, lang):
    word = _decision_word(params, lang)
    if lang == "en":
        return (
            f"[{params.get('ticket_no', '')}] {word} on the customer's "
            f"behalf by {params.get('actor_label', '')}"
        )
    return (
        f"[{params.get('ticket_no', '')}] {word} namens de klant door "
        f"{params.get('actor_label', '')}"
    )


def _body_decided_on_behalf(params, lang):
    word = _decision_word(params, lang).lower()
    actor = params.get("actor_label", "")
    if lang == "en":
        lines = [
            f"This ticket was {word} on the customer's behalf by {actor}.",
            "",
            f"Old status: {status_label(params.get('old_status'), 'en')}",
            f"New status: {status_label(params.get('new_status'), 'en')}",
            "",
            "Are you the customer for this ticket and do you disagree with "
            "this decision? Reply on the ticket or contact your facility "
            "manager.",
            "",
            _facts_block(params, "en"),
        ]
    else:
        lines = [
            f"Deze ticket is {word} namens de klant door {actor}.",
            "",
            f"Oude status: {status_label(params.get('old_status'), 'nl')}",
            f"Nieuwe status: {status_label(params.get('new_status'), 'nl')}",
            "",
            "Bent u de klant voor deze ticket en bent u het niet eens met deze beslissing? "
            "Reageer dan op de ticket of neem contact op met uw facilitair beheerder.",
            "",
            _facts_block(params, "nl"),
        ]
    return "\n".join(lines + _SIGN_OFF[lang])


def _body_ticket_assigned(params, lang):
    intro = {
        "nl": "Er is een ticket aan u toegewezen.",
        "en": "A ticket has been assigned to you.",
    }
    return "\n".join(
        [intro[lang], "", _facts_block(params, lang)] + _SIGN_OFF[lang]
    )


def _body_ticket_unassigned(params, lang):
    intro = {
        "nl": "U bent niet langer toegewezen aan deze ticket.",
        "en": "You are no longer assigned to this ticket.",
    }
    return "\n".join(
        [intro[lang], "", _facts_block(params, lang)] + _SIGN_OFF[lang]
    )


def _slot_unable_fallbacks(params, lang):
    """The three per-language fallbacks the old composer hardcoded."""
    staff = params.get("staff_label") or (
        "an employee" if lang == "en" else "een medewerker"
    )
    window = params.get("window") or (
        "no specific time slot" if lang == "en" else "geen specifiek tijdvak"
    )
    reason = params.get("reason") or (
        "(no reason given)" if lang == "en" else "(geen reden opgegeven)"
    )
    return staff, window, reason


def _body_slot_unable(params, lang):
    staff, window, reason = _slot_unable_fallbacks(params, lang)
    if lang == "en":
        lines = [
            f"{staff} marked a planned task as 'not completed'.",
            "",
            f"Time slot: {window}",
            f"Reason: {reason}",
            "",
            "Replan this task or assign another employee.",
            "",
            _facts_block(params, "en"),
        ]
    else:
        lines = [
            f"{staff} heeft een geplande taak gemarkeerd als "
            "'niet afgerond'.",
            "",
            f"Tijdvak: {window}",
            f"Reden: {reason}",
            "",
            "Plan deze taak opnieuw in of wijs een andere medewerker toe.",
            "",
            _facts_block(params, "nl"),
        ]
    return "\n".join(lines + _SIGN_OFF[lang])


def _body_password_reset(params, lang):
    if lang == "en":
        lines = [
            "A request was made to reset the password of your account.",
            "",
            f"UID: {params.get('uid', '')}",
            f"Token: {params.get('token', '')}",
        ]
        if params.get("reset_url"):
            lines.extend(["", f"Reset link: {params['reset_url']}"])
        lines.extend(
            ["", "Did you not make this request yourself? Then you can "
             "ignore this e-mail."]
        )
    else:
        lines = [
            "Er is een verzoek ingediend om het wachtwoord van uw account opnieuw in te stellen.",
            "",
            f"UID: {params.get('uid', '')}",
            f"Token: {params.get('token', '')}",
        ]
        if params.get("reset_url"):
            lines.extend(["", f"Herstelkoppeling: {params['reset_url']}"])
        lines.extend(
            ["", "Heeft u dit verzoek niet zelf gedaan? Dan kunt u deze e-mail negeren."]
        )
    return "\n".join(lines + _SIGN_OFF[lang])


def _body_invitation(params, lang):
    inviter = params.get("inviter_label", "")
    role = role_label(params.get("role"), lang)
    if lang == "en":
        lines = [
            "Hello,",
            "",
            f"{inviter} has invited you to join CleanOps as {role}.",
        ]
        scope = []
        if params.get("company_names"):
            scope.append("Companies: " + ", ".join(params["company_names"]))
        if params.get("building_names"):
            scope.append("Buildings: " + ", ".join(params["building_names"]))
        if params.get("customer_names"):
            scope.append("Customers: " + ", ".join(params["customer_names"]))
        if scope:
            lines.append("")
            lines.extend(scope)
        lines.extend([
            "",
            "Accept this invitation through the link below. The link expires "
            f"on {params.get('expires_label', '')}.",
            "",
            params.get("accept_url")
            or "(administrator: set INVITATION_ACCEPT_FRONTEND_URL)",
            "",
            "Were you not expecting this invitation? Then you can ignore "
            "this e-mail.",
        ])
    else:
        lines = [
            "Hallo,",
            "",
            f"{inviter} heeft u uitgenodigd om deel te nemen aan CleanOps als {role}.",
        ]
        scope = []
        if params.get("company_names"):
            scope.append("Bedrijven: " + ", ".join(params["company_names"]))
        if params.get("building_names"):
            scope.append("Gebouwen: " + ", ".join(params["building_names"]))
        if params.get("customer_names"):
            scope.append("Klanten: " + ", ".join(params["customer_names"]))
        if scope:
            lines.append("")
            lines.extend(scope)
        lines.extend([
            "",
            f"Accepteer deze uitnodiging via onderstaande link. De link verloopt op "
            f"{params.get('expires_label', '')}.",
            "",
            params.get("accept_url")
            or "(beheerder: stel INVITATION_ACCEPT_FRONTEND_URL in)",
            "",
            "Heeft u deze uitnodiging niet verwacht? Dan kunt u deze e-mail negeren.",
        ])
    return "\n".join(lines + _SIGN_OFF[lang])


def _body_invoice_sent(params, lang):
    if lang == "en":
        return "\n".join([
            f"Dear {params.get('contact_name', '')},",
            "",
            f"Attached you will find invoice {params.get('number', '')}.",
            "",
            f"Total: {params.get('total', '')}",
            "",
            "This e-mail was sent automatically.",
        ])
    return "\n".join([
        f"Beste {params.get('contact_name', '')},",
        "",
        f"In de bijlage vindt u factuur {params.get('number', '')}.",
        "",
        f"Totaal: {params.get('total', '')}",
        "",
        "Deze e-mail is automatisch verzonden.",
    ])


def _body_invoice_run(params, lang):
    count = params.get("count", 0)
    customer = params.get("customer_name", "")
    rows = params.get("rows") or []
    if lang == "en":
        lines = [
            f"The invoicing job created {count} draft invoice(s) "
            f"for {customer}.",
            "",
            f"Total: {params.get('total', '')}",
            "",
        ]
        for row in rows:
            where = (
                "customer level" if row.get("level") == "customer"
                else "per building"
            )
            lines.append(
                f"  - draft #{row.get('ref', '')} ({where}): {row.get('amount', '')}"
            )
        lines += [
            "",
            "These drafts have not been sent yet; review them under Invoices.",
            "",
            "This e-mail was sent automatically.",
        ]
    else:
        lines = [
            f"De facturatietaak heeft {count} conceptfactuur/-facturen "
            f"aangemaakt voor {customer}.",
            "",
            f"Totaal: {params.get('total', '')}",
            "",
        ]
        for row in rows:
            where = (
                "klantniveau" if row.get("level") == "customer"
                else "per gebouw"
            )
            lines.append(
                f"  - concept #{row.get('ref', '')} ({where}): {row.get('amount', '')}"
            )
        lines += [
            "",
            "Deze concepten zijn nog niet verstuurd; controleer ze in Facturen.",
            "",
            "Deze e-mail is automatisch verzonden.",
        ]
    return "\n".join(lines)


_AT_RISK_STAGES = {
    "nl": {
        "WAITING_REVIEW": "wacht op controle",
        "SLOT_DONE": "klaar gemeld, niet afgerond",
        "BLOCKED": "vastgelopen",
        "PAST_DEADLINE": "deadline verstreken",
    },
    "en": {
        "WAITING_REVIEW": "waiting for review",
        "SLOT_DONE": "reported done, not settled",
        "BLOCKED": "stuck",
        "PAST_DEADLINE": "deadline passed",
    },
}


def _body_at_risk(params, lang):
    groups = params.get("groups") or []
    if lang == "en":
        lines = [
            "This work falls in the open billing month (or earlier), but it",
            "is not fully finished. As long as that stays true, it will NOT",
            "be on this month's invoice.",
            "",
        ]
    else:
        lines = [
            "Dit werk valt in de open factuurmaand (of eerder), maar de",
            "afronding is niet compleet. Zolang dat zo blijft, komt het NIET",
            "op de factuur van deze maand.",
            "",
        ]
    for group in groups:
        lines.append(f"{group.get('customer_name', '')}:")
        for row in group.get("rows") or []:
            stage = _AT_RISK_STAGES[lang].get(
                row.get("stage", ""), row.get("stage", "")
            )
            where = (
                f" ({row['building_name']})" if row.get("building_name") else ""
            )
            if lang == "en":
                tail = f"{stage}, {_days_phrase(row.get('age_days'), 'en')}"
            else:
                tail = f"{stage}, {row.get('age_days', 0)} dag(en)"
            lines.append(
                f"  - {row.get('ref', '')} · {row.get('title', '')}{where} — {tail}"
            )
        lines.append("")
    if lang == "en":
        lines += [
            "Finishing, replanning or cancelling happens in the system itself;",
            "this e-mail changes nothing.",
            "",
            "This e-mail was sent automatically.",
        ]
    else:
        lines += [
            "Afronden, herplannen of annuleren gebeurt in het systeem zelf;",
            "deze e-mail wijzigt niets.",
            "",
            "Deze e-mail is automatisch verzonden.",
        ]
    return "\n".join(lines)


_WEEKLY_SUMMARY_LABELS = {
    "nl": {
        "SLA_APPROVAL_CUTOFF_DUE": "Klantgoedkeuring voor de facturatiedatum",
        "SLA_MANAGER_REVIEW_OVERDUE": "Afgerond werk nog niet gecontroleerd",
        "SLA_WORK_NOT_STARTED": "Werk niet op tijd gestart",
    },
    "en": {
        "SLA_APPROVAL_CUTOFF_DUE": "Customer approval before the billing date",
        "SLA_MANAGER_REVIEW_OVERDUE": "Finished work not yet reviewed",
        "SLA_WORK_NOT_STARTED": "Work not started on time",
    },
}


def _body_weekly_summary(params, lang):
    since = _dmy(params.get("since_iso"))
    until = _dmy(params.get("until_iso"))
    rows = params.get("rows") or []
    if lang == "en":
        lines = [
            "Overview of the automatic warnings of the past week",
            f"({since} through {until}).",
            "",
        ]
        if not rows:
            lines.append("No warnings were sent this week.")
            return "\n".join(lines)
    else:
        lines = [
            "Overzicht van de automatische waarschuwingen van de afgelopen week",
            f"({since} t/m {until}).",
            "",
        ]
        if not rows:
            lines.append("Er zijn deze week geen waarschuwingen verstuurd.")
            return "\n".join(lines)
    by_type: dict = {}
    for row in rows:
        by_type.setdefault(row.get("event_type", ""), []).append(row)
    unit = "message(s)" if lang == "en" else "bericht(en)"
    for event_type, group in by_type.items():
        label = _WEEKLY_SUMMARY_LABELS[lang].get(event_type, event_type)
        lines.append(f"{label} - {len(group)} {unit}")
        for row in group:
            lines.append(
                f"  - {row.get('when', '')}  {row.get('subject', '')}  "
                f"-> {row.get('recipient', '')}"
            )
        lines.append("")
    return "\n".join(lines)


# --- SLA warnings ----------------------------------------------------------

def _body_sla_approval_cutoff(params, lang):
    cutoff = _dmy(params.get("cutoff_iso"))
    days_left = params.get("days_left", 0)
    if lang == "en":
        lines = [
            "The work below is finished and waiting for your approval.",
            "",
            f"Your billing date is {cutoff} "
            f"(in {days_left} day(s)).",
            "",
            "Important: work finished before your billing date goes on the "
            "next invoice, even if your approval has not come in by then. "
            "That way the work is on the invoice of the month it was really "
            "done in.",
            "",
            "Do you disagree with the work? Then reject it or contact your "
            "manager. If it has already been invoiced, we reverse the "
            "invoice with a credit note and the work disappears from your "
            "bill again.",
            "",
            f"Extra work: {params.get('ew_title', '')}",
            f"Ticket: {params.get('ticket_no', '')} - {params.get('ticket_title', '')}",
        ]
    else:
        lines = [
            "Het werk hieronder is afgerond en wacht op uw goedkeuring.",
            "",
            f"Uw facturatiedatum is {cutoff} "
            f"(over {days_left} dag(en)).",
            "",
            "Belangrijk: werk dat vóór uw facturatiedatum is "
            "afgerond, komt op de eerstvolgende factuur te staan, "
            "ook als uw goedkeuring dan nog niet binnen is. Zo "
            "staat het werk op de factuur van de maand waarin het "
            "echt is uitgevoerd.",
            "",
            "Bent u het niet eens met het werk? Keur het dan af of "
            "neem contact op met uw beheerder. Is het al "
            "gefactureerd, dan draaien wij de factuur terug met een "
            "creditnota en verdwijnt het werk weer van uw rekening.",
            "",
            f"Meerwerk: {params.get('ew_title', '')}",
            f"Ticket: {params.get('ticket_no', '')} - {params.get('ticket_title', '')}",
        ]
    return "\n".join(lines + _SIGN_OFF[lang])


def _body_sla_manager_review(params, lang):
    hours = params.get("hours", 0)
    if lang == "en":
        lines = [
            "An employee reported this work as done. It is now waiting for "
            "your review and has not been sent to the customer yet.",
            "",
            f"Waiting time: {hours} working hours.",
            "",
            "As long as it sits here, the customer does not see it and it "
            "cannot be invoiced.",
            "",
            f"Ticket: {params.get('ticket_no', '')} - {params.get('ticket_title', '')}",
        ]
    else:
        lines = [
            "Een medewerker heeft dit werk als uitgevoerd gemeld. "
            "Het wacht nu op uw controle en is nog niet naar de "
            "klant gestuurd.",
            "",
            f"Wachttijd: {hours} werkuren.",
            "",
            "Zolang het hier staat, ziet de klant het niet en kan "
            "het niet gefactureerd worden.",
            "",
            f"Ticket: {params.get('ticket_no', '')} - {params.get('ticket_title', '')}",
        ]
    return "\n".join(lines + _SIGN_OFF[lang])


def _body_sla_not_started_ticket(params, lang):
    if lang == "en":
        lines = [
            "This work should have begun and is still marked as not started.",
            "",
            f"Planned start: {params.get('planned_label', '')}.",
            f"Elapsed: {params.get('hours', 0)} working hours.",
            "",
            f"Ticket: {params.get('ticket_no', '')} - {params.get('ticket_title', '')}",
        ]
    else:
        lines = [
            "Dit werk had moeten beginnen en staat nog steeds op "
            "niet gestart.",
            "",
            f"Geplande start: {params.get('planned_label', '')}.",
            f"Verstreken: {params.get('hours', 0)} werkuren.",
            "",
            f"Ticket: {params.get('ticket_no', '')} - {params.get('ticket_title', '')}",
        ]
    return "\n".join(lines + _SIGN_OFF[lang])


def _body_sla_not_started_ew(params, lang):
    planned = _dmy(params.get("planned_iso"))
    if lang == "en":
        lines = [
            "This extra work is approved and planned, but no execution has "
            "started yet.",
            "",
            f"Planned date: {planned}.",
            f"Elapsed: {params.get('hours', 0)} working hours.",
            "",
            f"Extra work: {params.get('ew_title', '')}",
        ]
    else:
        lines = [
            "Dit meerwerk is goedgekeurd en ingepland, maar er is "
            "nog geen uitvoering gestart.",
            "",
            f"Geplande datum: {planned}.",
            f"Verstreken: {params.get('hours', 0)} werkuren.",
            "",
            f"Meerwerk: {params.get('ew_title', '')}",
        ]
    return "\n".join(lines + _SIGN_OFF[lang])


# --- the deadline reminder and the part assignment -------------------------

def _body_deadline_approaching(params, lang):
    label = params.get("label", "")
    word = "Deadline" if lang == "en" else "Deadline"
    return (
        f"{label} — {params.get('ticket_title', '')}\n"
        f"{word}: {params.get('deadline_iso', '')}\n\n"
        + _facts_block(params, lang)
    )


def _body_part_assigned(params, lang):
    label = params.get("label", "")
    part = params.get("part_title", "")
    if lang == "en":
        return f"{label} — {params.get('ticket_title', '')}\nPart: {part}\n"
    return f"{label} — {params.get('ticket_title', '')}\nOnderdeel: {part}\n"


# --- the late ladder -------------------------------------------------------

def _late_summary(step, params, lang):
    """The fact and the promise broken, as one line (W-LATE §2)."""
    head = f"{params.get('ticket_title', '')} — {params.get('label', '')}"
    if step == "l3":
        n = params.get("anchor_days") or 0
        anchored_on_deadline = bool(params.get("anchored_on_deadline"))
        anchor_day = _day_month(params.get("anchor_iso"), lang)
        if lang == "en":
            what = "the deadline" if anchored_on_deadline else "the planned day"
            return (
                f"{head}: {_days_phrase(n, 'en')} past {what} ({anchor_day}) "
                "without a single hour worked"
            )
        what = "de deadline" if anchored_on_deadline else "de geplande dag"
        return (
            f"{head}: {_days_phrase(n, 'nl')} voorbij {what} ({anchor_day}) "
            "zonder één gewerkt uur"
        )
    n = params.get("deadline_days_late") or 0
    when = _day_month(params.get("deadline_iso"), lang)
    if step == "l2_escalated":
        if lang == "en":
            return (
                f"{head}: deadline {when} is {_days_phrase(n, 'en')} past "
                "and the work is still not done"
            )
        return (
            f"{head}: deadline {when} is {_days_phrase(n, 'nl')} overschreden "
            "en het werk is nog niet af"
        )
    if lang == "en":
        return f"{head}: deadline {when} is {_days_phrase(n, 'en')} past"
    return f"{head}: deadline {when} is {_days_phrase(n, 'nl')} overschreden"


def _late_body(step):
    def _render(params, lang):
        return (
            _late_summary(step, params, lang)
            + "\n\n"
            + _facts_block(params, lang)
            + "\n"
            + "\n".join(_SIGN_OFF[lang])
        )
    return _render


# ---------------------------------------------------------------------------
# THE CATALOGUE — one key per notification kind.
# ---------------------------------------------------------------------------

CATALOGUE: dict[str, dict] = {
    # -- ticket lifecycle emails -------------------------------------------
    "ticket_created": {
        "subject": {
            "nl": "[{ticket_no}] Nieuwe ticket aangemaakt: {ticket_title}",
            "en": "[{ticket_no}] New ticket created: {ticket_title}",
        },
        "body": _body_ticket_created,
    },
    "ticket_status_changed": {
        "subject": lambda params, lang: (
            f"[{params.get('ticket_no', '')}] "
            + ("Status changed: " if lang == "en" else "Status gewijzigd: ")
            + f"{status_label(params.get('old_status'), lang)} → "
            + f"{status_label(params.get('new_status'), lang)}"
        ),
        "body": _body_ticket_status_changed,
    },
    "ticket_decided_on_behalf": {
        "subject": _subject_decided_on_behalf,
        "body": _body_decided_on_behalf,
    },
    "ticket_assigned": {
        "subject": {
            "nl": "[{ticket_no}] Ticket aan u toegewezen: {ticket_title}",
            "en": "[{ticket_no}] Ticket assigned to you: {ticket_title}",
        },
        "body": _body_ticket_assigned,
    },
    "ticket_unassigned": {
        "subject": {
            "nl": "[{ticket_no}] Toewijzing ingetrokken: {ticket_title}",
            "en": "[{ticket_no}] Assignment withdrawn: {ticket_title}",
        },
        "body": _body_ticket_unassigned,
    },
    "ticket_slot_unable": {
        "subject": lambda params, lang: (
            f"[{params.get('ticket_no', '')}] "
            + ("Task not completed by" if lang == "en" else "Taak niet afgerond door")
            + f" {_slot_unable_fallbacks(params, lang)[0]}"
        ),
        "body": _body_slot_unable,
    },
    # -- account emails -----------------------------------------------------
    "password_reset": {
        "subject": {
            "nl": "Wachtwoord opnieuw instellen voor CleanOps",
            "en": "Reset your CleanOps password",
        },
        "body": _body_password_reset,
    },
    "invitation": {
        "subject": lambda params, lang: (
            f"Invitation to CleanOps as {role_label(params.get('role'), 'en')}"
            if lang == "en"
            else f"Uitnodiging voor CleanOps als {role_label(params.get('role'), 'nl')}"
        ),
        "body": _body_invitation,
    },
    # -- invoicing emails ---------------------------------------------------
    "invoice_sent": {
        "subject": {
            "nl": "Factuur {number} van {company_name}",
            "en": "Invoice {number} from {company_name}",
        },
        "body": _body_invoice_sent,
    },
    "invoice_run_completed": {
        "subject": {
            "nl": "[Facturatie] {count} concept(en) aangemaakt voor {customer_name}",
            "en": "[Invoicing] {count} draft(s) created for {customer_name}",
        },
        "body": _body_invoice_run,
    },
    "billing_month_at_risk": {
        "subject": {
            "nl": "[Facturatie] Deze factuurmaand loopt risico — {total} openstaand ({month})",
            "en": "[Invoicing] This billing month is at risk — {total} outstanding ({month})",
        },
        "body": _body_at_risk,
    },
    # -- the time-driven warnings (email + bell) ---------------------------
    "sla_approval_cutoff": {
        "subject": lambda params, lang: (
            f"[{params.get('ticket_no', '')}] Your approval is expected "
            f"before the billing date {_dmy(params.get('cutoff_iso'))}"
            if lang == "en"
            else f"[{params.get('ticket_no', '')}] Uw goedkeuring wordt verwacht voor "
            f"de facturatiedatum {_dmy(params.get('cutoff_iso'))}"
        ),
        "body": _body_sla_approval_cutoff,
        "summary": lambda params, lang: (
            f"{params.get('ew_title', '')} - {params.get('ticket_no', '')} - "
            + ("billing date" if lang == "en" else "facturatiedatum")
            + f" {_dmy(params.get('cutoff_iso'))} "
            + f"({params.get('days_left', 0)} "
            + ("day(s))" if lang == "en" else "dag(en))")
        ),
    },
    "sla_manager_review": {
        "subject": {
            "nl": "[{ticket_no}] Wacht op uw controle ({hours} werkuren)",
            "en": "[{ticket_no}] Waiting for your review ({hours} working hours)",
        },
        "body": _body_sla_manager_review,
        "summary": {
            "nl": "{ticket_no} - {ticket_title} - {hours} werkuren",
            "en": "{ticket_no} - {ticket_title} - {hours} working hours",
        },
    },
    "sla_not_started_ticket": {
        "subject": {
            "nl": "[{ticket_no}] Nog niet gestart ({hours} werkuren na de planning)",
            "en": "[{ticket_no}] Not started yet ({hours} working hours after the plan)",
        },
        "body": _body_sla_not_started_ticket,
        "summary": {
            "nl": "{ticket_no} - {ticket_title} - gepland {planned_label}, "
                  "{hours} werkuren verstreken",
            "en": "{ticket_no} - {ticket_title} - planned {planned_label}, "
                  "{hours} working hours elapsed",
        },
    },
    "sla_not_started_extra_work": {
        "subject": lambda params, lang: (
            f"[{params.get('ew_ref', '')}] Not started yet "
            f"(planned on {_dmy(params.get('planned_iso'))})"
            if lang == "en"
            else f"[{params.get('ew_ref', '')}] Nog niet gestart "
            f"(gepland op {_dmy(params.get('planned_iso'))})"
        ),
        "body": _body_sla_not_started_ew,
        "summary": lambda params, lang: (
            f"{params.get('ew_title', '')} - "
            + ("planned" if lang == "en" else "gepland")
            + f" {_dmy(params.get('planned_iso'))}, {params.get('hours', 0)} "
            + ("working hours elapsed" if lang == "en" else "werkuren verstreken")
        ),
    },
    "sla_weekly_summary": {
        "subject": lambda params, lang: (
            (
                "Weekly overview of automatic warnings "
                if lang == "en"
                else "Weekoverzicht automatische waarschuwingen "
            )
            + f"({_dm(params.get('since_iso'))} "
            + ("through" if lang == "en" else "t/m")
            + f" {_dmy(params.get('until_iso'))})"
        ),
        "body": _body_weekly_summary,
    },
    # -- the deadline reminder + the part assignment -----------------------
    "ticket_deadline_approaching": {
        "subject": {
            "nl": "Deadline nadert: {label}",
            "en": "Deadline approaching: {label}",
        },
        "body": _body_deadline_approaching,
        "summary": {
            "nl": "{label} moet af op {deadline_iso}",
            "en": "{label} is due {deadline_iso}",
        },
    },
    "ticket_part_assigned": {
        "subject": {
            "nl": "U bent ingedeeld op een deel van {label}",
            "en": "You were assigned a part of {label}",
        },
        "body": _body_part_assigned,
        "summary": lambda params, lang: (
            (
                f"{params.get('label', '')} — you are on "
                f"“{params.get('part_title', '')}”"
                if lang == "en"
                else f"{params.get('label', '')} — u bent ingedeeld op "
                f"“{params.get('part_title', '')}”"
            )
            if params.get("part_title")
            else params.get("label", "")
        ),
    },
    # -- the late ladder ----------------------------------------------------
    "ticket_late_l2_managers": {
        "subject": {
            "nl": "Deadline verstreken: {label}",
            "en": "Deadline passed: {label}",
        },
        "body": _late_body("l2_managers"),
        "summary": lambda params, lang: _late_summary("l2_managers", params, lang),
    },
    "ticket_late_l2_escalated": {
        "subject": {
            "nl": "Deadline verstreken en nog niet af: {label}",
            "en": "Deadline passed and still not done: {label}",
        },
        "body": _late_body("l2_escalated"),
        "summary": lambda params, lang: _late_summary("l2_escalated", params, lang),
    },
    "ticket_late_l3_never_done": {
        "subject": {
            "nl": "Nooit uitgevoerd — dertig dagen zonder gewerkt uur: {label}",
            "en": "Never done — thirty days without an hour worked: {label}",
        },
        "body": _late_body("l3"),
        "summary": lambda params, lang: _late_summary("l3", params, lang),
    },
    # -- bell-only kinds ----------------------------------------------------
    "ticket_message": {
        # Facts only (author + their words); identical in both languages.
        "summary": {
            "nl": "{author}: {text}",
            "en": "{author}: {text}",
        },
    },
    "ticket_message_unattributed": {
        "summary": {"nl": "{text}", "en": "{text}"},
    },
    "extra_work_requested": {
        "summary": lambda params, lang: (
            (
                f"New extra-work request: {params['title']}"
                if lang == "en"
                else f"Nieuwe meerwerkaanvraag: {params['title']}"
            )
            if params.get("title")
            else (
                "New extra-work request" if lang == "en"
                else "Nieuwe meerwerkaanvraag"
            )
        ),
    },
    "extra_work_proposal_sent": {
        "summary": lambda params, lang: (
            (
                f"Quote ready: {params['title']}"
                if lang == "en"
                else f"Offerte klaar: {params['title']}"
            )
            if params.get("title")
            else ("Quote ready" if lang == "en" else "Offerte klaar")
        ),
    },
    "extra_work_approved": {
        "summary": lambda params, lang: (
            (
                f"{params['decider']} approved {params.get('title', '')}".strip()
                if lang == "en"
                else f"{params['decider']} heeft {params.get('title', '')} goedgekeurd".strip()
            )
            if params.get("decider")
            else (
                f"Extra work approved: {params.get('title', '')}".strip()
                if lang == "en"
                else f"Meerwerk goedgekeurd: {params.get('title', '')}".strip()
            )
        ),
    },
    "extra_work_rejected": {
        "summary": lambda params, lang: (
            (
                f"{params['decider']} rejected {params.get('title', '')}".strip()
                if lang == "en"
                else f"{params['decider']} heeft {params.get('title', '')} afgewezen".strip()
            )
            if params.get("decider")
            else (
                f"Extra work rejected: {params.get('title', '')}".strip()
                if lang == "en"
                else f"Meerwerk afgewezen: {params.get('title', '')}".strip()
            )
        ),
    },
    "extra_work_message": {
        "summary": {
            "nl": "{author}: {text}",
            "en": "{author}: {text}",
        },
    },
    "extra_work_message_unattributed": {
        "summary": {"nl": "{text}", "en": "{text}"},
    },
    "extra_work_published": {
        "summary": lambda params, lang: (
            (
                f"Extra work approved: {params['title']}"
                if lang == "en"
                else f"Meerwerk goedgekeurd: {params['title']}"
            )
            if params.get("title")
            else (
                "Extra work approved" if lang == "en"
                else "Meerwerk goedgekeurd"
            )
        ),
    },
}


# The bell headline per EVENT TYPE, in the viewer's language — this is
# the server-side replacement for the frontend's `notifications.sla.*`
# map (which the SPA drops: the API resolves it). Exactly the six kinds
# the bell titles today; every other row's headline stays the job's own
# name, resolved by the frontend from the row's facts.
_EVENT_TITLES = {
    "SLA_APPROVAL_CUTOFF_DUE": {
        "nl": "Goedkeuring nodig voor de facturatiedatum",
        "en": "Approval needed before the billing date",
    },
    "SLA_MANAGER_REVIEW_OVERDUE": {
        "nl": "Wacht te lang op controle",
        "en": "Waiting too long for review",
    },
    "SLA_WORK_NOT_STARTED": {
        "nl": "Nog niet gestart",
        "en": "Not started yet",
    },
    "TICKET_LATE_L2_MANAGERS": {
        "nl": "Deadline verstreken",
        "en": "Deadline passed",
    },
    "TICKET_LATE_L2_ESCALATED": {
        "nl": "Deadline verstreken en nog niet af",
        "en": "Deadline passed and still not done",
    },
    "TICKET_LATE_L3_QUARANTINE": {
        "nl": "Nooit uitgevoerd: dertig dagen zonder gewerkt uur",
        "en": "Never done: thirty days without an hour worked",
    },
}


# ---------------------------------------------------------------------------
# The doors
# ---------------------------------------------------------------------------

def _render_part(entry, part, params, lang):
    spec = entry.get(part)
    if spec is None:
        return None
    params = params or {}
    if callable(spec):
        return spec(params, lang)
    template = spec.get(lang) or spec.get("nl") or ""
    return template.format_map(_SafeParams(params))


def render_summary(key, params, lang) -> str | None:
    """The bell line for `key` in `lang`, or None when the key is
    unknown / has no summary — the caller falls back to stored text."""
    lang = resolve_lang(lang)
    entry = CATALOGUE.get(key)
    if not entry:
        return None
    try:
        return _render_part(entry, "summary", params, lang)
    except Exception:  # noqa: BLE001 — never break the feed over copy.
        logger.exception("notification copy: summary render failed for %s", key)
        return None


def render_email(key, params, lang) -> tuple[str, str]:
    """The (subject, body) for `key` in `lang`. Raises KeyError for an
    unknown key — an EMAIL composer asking for a key that does not exist
    is a programming error and must fail in tests, not silently send an
    empty mail."""
    lang = resolve_lang(lang)
    entry = CATALOGUE[key]
    subject = _render_part(entry, "subject", params, lang) or ""
    body = _render_part(entry, "body", params, lang) or ""
    return subject, body


def title_for_event(event_type, lang) -> str | None:
    """The warning headline for a row of `event_type`, or None for the
    kinds whose headline is the job's own name."""
    spec = _EVENT_TITLES.get(str(event_type))
    if not spec:
        return None
    return spec[resolve_lang(lang)]
