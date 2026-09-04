"""W13 — the ticket-category catalog's wire shape.

Replaces `serializers_work_categories`. Same contract as the five sibling
catalogs (`usage_count` annotated by the view, trim-at-the-door, a
friendly duplicate check in front of the database constraint), with the
fields the owner's list actually needs: two labels, a colour, an order,
an archive flag, and the intake flag that keeps a VERDICT out of a create
form.

`label` is a read-only, language-resolved convenience so a client that
just wants to print the row does not have to know the fallback rule. The
rule itself lives in `TicketCategory.label_for()` and nowhere else --
see the model for why a second copy is the bug this shape avoids.
"""
from __future__ import annotations

from django.db.models.functions import Lower, Trim
from rest_framework import serializers

from .models import TicketCategory

ERR_TICKET_CATEGORY_LABEL_NOT_UNIQUE = "ticket_category_label_not_unique"
ERR_TICKET_CATEGORY_SLUG_NOT_UNIQUE = "ticket_category_slug_not_unique"


def reader_language(request) -> str | None:
    """THE READER'S LANGUAGE, resolved in ONE place.

    W14 §1 -- W13-FIX taught THIS serializer to read `user.language`
    instead of `Accept-Language`, and left the OTHER resolver alone.
    `serializers.TicketCategoryFieldsMixin` -- which prints the category
    on every ticket LIST row and on the ticket DETAIL page -- went on
    reading the header, so one screen printed one row two ways: the
    picker said "Malfunction" (the user's language) while the chip
    beside it said "Storing" (the browser's).

    Measured on crmtest before the fix, as user 9 whose `language` is
    `en`:

        GET /api/tickets/?page_size=5                -> "Storing"
        GET /api/tickets/?page_size=5  (nl-NL hdr)   -> "Storing"
        GET /api/tickets/?page_size=5  (en-GB hdr)   -> "Malfunction"
        GET /api/tickets/categories/                 -> "Malfunction"

    Nothing in `frontend/src` sets `Accept-Language`, so the header is
    the BROWSER's locale and never the app's. The app's language is
    `user.language`, the field `i18n/useLanguageSync.ts` reads from
    `/auth/me/` and hands to i18next -- the same value the rest of the
    page is rendered in, and therefore the only one that can agree with
    it.

    The header stays as the fallback for an anonymous or tokenless read;
    `TicketCategory.label_for` falls back to Dutch after that.

    Both call sites import THIS function. A second copy is what produced
    the defect above, and the reference system's own audit of its
    `OvertimeType` records the identical failure: "the same overtime
    type is named differently on two screens."
    """
    if request is None:
        return None
    user = getattr(request, "user", None)
    return getattr(user, "language", None) or request.headers.get(
        "Accept-Language"
    )


def normalise_label(value: str) -> str:
    """What the operator typed, with the whitespace the DB constraint
    ignores removed on the way in.

    The constraint compares `Lower(Trim(label_nl))`, so storing an
    untrimmed label would let " Klacht" and "Klacht" both exist while
    the constraint considered them equal -- the row would be refused
    with a message naming a value the operator cannot see the difference
    from.
    """
    return (value or "").strip()


class TicketCategorySerializer(serializers.ModelSerializer):
    usage_count = serializers.SerializerMethodField()
    company_name = serializers.CharField(source="company.name", read_only=True)
    label = serializers.SerializerMethodField()

    class Meta:
        model = TicketCategory
        fields = [
            "id",
            "company",
            "company_name",
            "slug",
            "label",
            "label_nl",
            "label_en",
            "color",
            "sort_order",
            "is_active",
            "available_at_intake",
            "legacy_type",
            "usage_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_label(self, obj) -> str:
        """The row in the READER's language.

        W13-FIX §3 — THE READER'S LANGUAGE IS THE ONE THEY CHOSE.

        The rule, and why it is not `Accept-Language`, lives in
        `reader_language` above -- one resolver, because W14 §1 found
        the second copy of it had drifted.
        """
        return obj.label_for(reader_language(self.context.get("request")))

    def get_usage_count(self, obj) -> int:
        # The view annotates this for the page; the fallback keeps a
        # serializer used outside that view honest rather than crashing.
        annotated = getattr(obj, "annotated_usage_count", None)
        if annotated is not None:
            return annotated
        return obj.tickets.count()

    def validate_label_nl(self, value):
        cleaned = normalise_label(value)
        if not cleaned:
            raise serializers.ValidationError("A Dutch label is required.")
        return cleaned

    def validate_label_en(self, value):
        return normalise_label(value)

    def validate_color(self, value):
        """Empty, or exactly '#RRGGBB'.

        Checked because the value is written straight into a style
        attribute: a colour the browser cannot parse renders as no
        colour at all, which looks like the field silently ignored what
        the operator typed.
        """
        cleaned = (value or "").strip()
        if cleaned == "":
            return ""
        if len(cleaned) != 7 or not cleaned.startswith("#"):
            raise serializers.ValidationError("Use '#RRGGBB', or leave it empty.")
        try:
            int(cleaned[1:], 16)
        except ValueError:
            raise serializers.ValidationError("Use '#RRGGBB', or leave it empty.")
        return cleaned.lower()

    def validate(self, attrs):
        """Friendly duplicate checks, on both unique keys.

        The DB constraints are the authority -- these can lose a race,
        and the view catches `IntegrityError` for exactly that reason.
        These exist so the ordinary case returns a readable message with
        a stable code instead of a 500-shaped integrity error.
        """
        current = self.instance
        company = attrs.get("company", getattr(current, "company", None))
        if company is None:
            return attrs

        label = attrs.get("label_nl", getattr(current, "label_nl", None))
        if label:
            clash = (
                TicketCategory.objects.filter(company=company)
                .annotate(_key=Lower(Trim("label_nl")))
                .filter(_key=normalise_label(label).lower())
            )
            if current is not None:
                clash = clash.exclude(pk=current.pk)
            if clash.exists():
                raise serializers.ValidationError(
                    {
                        "label_nl": [
                            "A category with this Dutch label already "
                            "exists for this company."
                        ],
                        "code": ERR_TICKET_CATEGORY_LABEL_NOT_UNIQUE,
                    }
                )

        slug = attrs.get("slug", getattr(current, "slug", None))
        if slug:
            slug_clash = TicketCategory.objects.filter(company=company, slug=slug)
            if current is not None:
                slug_clash = slug_clash.exclude(pk=current.pk)
            if slug_clash.exists():
                raise serializers.ValidationError(
                    {
                        "slug": [
                            "A category with this key already exists for "
                            "this company."
                        ],
                        "code": ERR_TICKET_CATEGORY_SLUG_NOT_UNIQUE,
                    }
                )
        return attrs
