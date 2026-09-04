"""W13 — the owner's category list, written down once.

    Verzoek · Extra · Compliment · Melden · Storing · Ongegrond · Klacht

This module is the ONLY place those seven are named. The data migration
seeds from it, `seed_demo_data` seeds from it, and the test suite asserts
against it — so a company created next year gets the same list as one
created today, and nobody has to remember to update a second copy.

It is a SEED and not an enum. Once a company exists its rows are ordinary
catalog rows: renameable, re-orderable, archivable, and joinable by an
eighth entry the company adds itself. That is the difference between this
and the `TicketType` enum it replaces, and it is the whole point — the
old list could not be changed without a deployment.

`legacy_type` is the compatibility bridge described on the model: which
pre-W13 `Ticket.type` value each category stands in for, so the
pre-existing tickets-by-type report keeps meaning something while that
column lives. It is declared here rather than in a dict somewhere in the
serializer layer because the mapping is a property of the category.
"""
from __future__ import annotations

#: Slug -> the row to create. Order is display order (sort_order is
#: assigned from position, ten apart, so a company can slot one in
#: between without renumbering the rest).
#:
#: The order is the owner's own, not alphabetical and not
#: frequency-ranked: it is the order he said them in.
TICKET_CATEGORY_SEED: tuple[dict, ...] = (
    {
        "slug": "verzoek",
        "label_nl": "Verzoek",
        "label_en": "Request",
        "color": "#2F6FB2",
        "legacy_type": "REQUEST",
        "available_at_intake": True,
    },
    {
        "slug": "extra",
        "label_nl": "Extra",
        "label_en": "Extra",
        "color": "#6B4FA8",
        "legacy_type": "QUOTE_REQUEST",
        "available_at_intake": True,
    },
    {
        "slug": "compliment",
        "label_nl": "Compliment",
        "label_en": "Compliment",
        "color": "#2E8B57",
        "legacy_type": "OTHER",
        "available_at_intake": True,
    },
    {
        "slug": "melden",
        "label_nl": "Melden",
        "label_en": "Report",
        "color": "#5A6B7A",
        "legacy_type": "REPORT",
        "available_at_intake": True,
    },
    {
        "slug": "storing",
        "label_nl": "Storing",
        "label_en": "Malfunction",
        "color": "#C77A16",
        "legacy_type": "REPORT",
        "available_at_intake": True,
    },
    {
        # W13 §4 — a VERDICT, not a kind of request.
        #
        # Nobody raises a melding saying it is unfounded; somebody
        # decides that after reading it. So it is in the list, countable
        # and filterable like the other six, and absent from both create
        # forms. The place it CAN be set is the melding's own detail
        # page, which is where the reading happens.
        "slug": "ongegrond",
        "label_nl": "Ongegrond",
        "label_en": "Unfounded",
        "color": "#8A8F94",
        "legacy_type": "OTHER",
        "available_at_intake": False,
    },
    {
        "slug": "klacht",
        "label_nl": "Klacht",
        "label_en": "Complaint",
        "color": "#B23A3A",
        "legacy_type": "COMPLAINT",
        "available_at_intake": True,
    },
)

#: Pre-W13 `Ticket.type` -> the slug a melding carrying it becomes.
#:
#: SUGGESTION and OTHER are deliberately absent. Neither has a home in
#: the owner's seven, and inventing one would be this migration deciding
#: something the owner did not — "Compliment" is not "Suggestie". Those
#: meldingen land uncategorised, which is a state somebody can see and
#: clear, and their original `type` is still on the row.
LEGACY_TYPE_TO_SLUG: dict[str, str] = {
    "REPORT": "melden",
    "COMPLAINT": "klacht",
    "REQUEST": "verzoek",
    "QUOTE_REQUEST": "extra",
}


def seed_rows(sort_start: int = 10, step: int = 10):
    """The seed with `sort_order` filled in from position."""
    for index, row in enumerate(TICKET_CATEGORY_SEED):
        yield {**row, "sort_order": sort_start + index * step}
