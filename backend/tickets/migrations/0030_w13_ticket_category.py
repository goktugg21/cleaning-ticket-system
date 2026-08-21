"""W13 — one classification replaces two.

Creates `TicketCategory`, seeds the owner's seven per company, moves every
melding onto the new catalog, then drops `WorkCategory`.

## This migration is DESTRUCTIVE, and that is the instruction

CLAUDE.md §3 forbids a destructive schema change "without explicit owner
sign-off". The sign-off is the sprint brief, in the owner's words: "THE
OWNER HAS DECIDED: HIS LIST REPLACES OURS. Not beside it," and "REPLACE
the existing work-category taxonomy rather than adding a sibling ... one
of them disappears." Adding a third taxonomy beside the two that already
confuse people is the thing being corrected, so a sibling was not an
option.

## Nothing loses its classification

Three groups of melding, three outcomes, all counted and logged:

  1. carries a `WorkCategory` -- that name is a deliberate operator
     choice about a real melding. The category is recreated as an
     ARCHIVED `TicketCategory` (is_active=False, not offerable, sorted
     below the seven) and the melding points at it. The operator sees
     the old word, can still filter and count by it, and can re-map it
     to one of the seven whenever they get to it.
  2. no `WorkCategory`, but a `type` with a home in the owner's list --
     mapped (REPORT->Melden, COMPLAINT->Klacht, REQUEST->Verzoek,
     QUOTE_REQUEST->Extra).
  3. no `WorkCategory`, and `type` is SUGGESTION or OTHER -- left
     uncategorised on purpose. Neither has a home in the seven and
     inventing one would be this migration classifying meldingen the
     owner never classified. `Ticket.type` is untouched on the row, so
     the original value is still there to re-read.

Reversible: the reverse recreates `WorkCategory` and restores the
archived legacy names onto it. Groups 2 and 3 had no `WorkCategory` to
begin with, so reversing correctly leaves them with none.
"""
from django.db import migrations, models
from django.db.models.functions import Lower, Trim
import django.db.models.deletion


def _slugify_legacy(name):
    """A slug for a preserved legacy work-category name.

    Prefixed `legacy-` so it can never collide with one of the owner's
    seven, and truncated to the column width. Uniqueness inside a
    company is guaranteed by the caller, which dedupes on the name.
    """
    from django.utils.text import slugify

    base = slugify(name) or "unnamed"
    return f"legacy-{base}"[:64]


def seed_and_migrate(apps, schema_editor):
    from tickets.category_seed import LEGACY_TYPE_TO_SLUG, seed_rows

    Company = apps.get_model("companies", "Company")
    TicketCategory = apps.get_model("tickets", "TicketCategory")
    Ticket = apps.get_model("tickets", "Ticket")

    # ---- the owner's seven, for every company ----------------------
    by_company_slug = {}
    for company in Company.objects.all():
        for row in seed_rows():
            category = TicketCategory.objects.create(company_id=company.id, **row)
            by_company_slug[(company.id, row["slug"])] = category.id

    # ---- group 1: preserve every legacy work-category name ---------
    #
    # One archived row per (company, name) actually carried by a
    # melding. A `WorkCategory` nobody ever used is not recreated: it
    # holds no classification, so preserving it would be preserving an
    # empty catalog entry into a list this sprint exists to shorten.
    legacy_pairs = (
        Ticket.objects.filter(category__isnull=False)
        .values_list("company_id", "category__name")
        .distinct()
    )
    legacy_lookup = {}
    sort_at = 900
    for company_id, name in legacy_pairs:
        if company_id is None or not name:
            continue
        if (company_id, name) in legacy_lookup:
            continue
        category = TicketCategory.objects.create(
            company_id=company_id,
            slug=_slugify_legacy(name),
            label_nl=name,
            label_en=name,
            color="",
            sort_order=sort_at,
            is_active=False,
            available_at_intake=False,
            legacy_type="OTHER",
        )
        legacy_lookup[(company_id, name)] = category.id
        sort_at += 10

    preserved = 0
    for (company_id, name), new_id in legacy_lookup.items():
        preserved += Ticket.objects.filter(
            company_id=company_id, category__name=name
        ).update(new_category_id=new_id)

    # ---- group 2: map from the legacy `type` -----------------------
    mapped = 0
    for legacy_type, slug in LEGACY_TYPE_TO_SLUG.items():
        for company in Company.objects.all():
            target = by_company_slug.get((company.id, slug))
            if target is None:
                continue
            mapped += Ticket.objects.filter(
                company_id=company.id,
                type=legacy_type,
                category__isnull=True,
                new_category__isnull=True,
            ).update(new_category_id=target)

    # ---- group 3: whatever is left is uncategorised, on purpose ----
    uncategorised = Ticket.objects.filter(new_category__isnull=True).count()

    # Printed, not silent: the sprint brief asks for these three numbers
    # and a migration that moved every melding in the database without
    # saying how many is a migration nobody can check.
    print(
        f"\n  W13 ticket categories: {preserved} melding(en) kept a legacy "
        f"work category (archived), {mapped} mapped from their type, "
        f"{uncategorised} left uncategorised."
    )


def restore_work_categories(apps, schema_editor):
    """Reverse: put the preserved legacy names back on `WorkCategory`.

    Only the archived rows carry a name that ever lived on a
    `WorkCategory`; the owner's seven never did, so a melding mapped
    from its `type` correctly comes out of this with no work category,
    exactly as it went in.
    """
    TicketCategory = apps.get_model("tickets", "TicketCategory")
    WorkCategory = apps.get_model("tickets", "WorkCategory")
    Ticket = apps.get_model("tickets", "Ticket")

    for legacy in TicketCategory.objects.filter(slug__startswith="legacy-"):
        restored = WorkCategory.objects.create(
            company_id=legacy.company_id,
            name=legacy.label_nl,
            is_active=True,
            sort_order=legacy.sort_order,
        )
        Ticket.objects.filter(new_category_id=legacy.id).update(
            category_id=restored.id
        )


class Migration(migrations.Migration):

    dependencies = [
        ("companies", "0001_initial"),
        ("tickets", "0029_w10_acknowledged_and_on_hold"),
    ]

    operations = [
        migrations.CreateModel(
            name="TicketCategory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "slug",
                    models.SlugField(
                        help_text=(
                            "Stable machine key, e.g. 'klacht'. What code and "
                            "seeds match on, so renaming the label a company "
                            "shows never breaks a mapping. Unique per company."
                        ),
                        max_length=64,
                    ),
                ),
                (
                    "label_nl",
                    models.CharField(
                        help_text="Dutch label. The primary language (CLAUDE.md).",
                        max_length=128,
                    ),
                ),
                (
                    "label_en",
                    models.CharField(help_text="English label.", max_length=128),
                ),
                (
                    "color",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text=(
                            "'#RRGGBB', or empty. Rendered as the chip colour "
                            "in the meldingen list and the category report, "
                            "which is what makes the groups visible at a "
                            "glance rather than readable one row at a time."
                        ),
                        max_length=7,
                    ),
                ),
                (
                    "sort_order",
                    models.PositiveIntegerField(
                        default=0,
                        help_text=(
                            "Ascending order in every picker; ties break on "
                            "label_nl."
                        ),
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text=(
                            "Archived categories stay on the meldingen that "
                            "carry them but are not offerable for new ones."
                        ),
                    ),
                ),
                (
                    "available_at_intake",
                    models.BooleanField(
                        default=True,
                        help_text=(
                            "W13 §4 -- may this be chosen when the melding is "
                            "CREATED? False for 'Ongegrond', which is a "
                            "VERDICT: nobody raises a melding saying it is "
                            "unfounded, somebody decides that afterwards. A "
                            "category with this off is absent from both create "
                            "forms and present on the detail page, where the "
                            "verdict is actually reached."
                        ),
                    ),
                ),
                (
                    "legacy_type",
                    models.CharField(
                        choices=[
                            ("REPORT", "Melding / Report"),
                            ("COMPLAINT", "Klacht / Complaint"),
                            ("REQUEST", "Verzoek / Request"),
                            ("SUGGESTION", "Suggestie / Suggestion"),
                            ("QUOTE_REQUEST", "Offerteaanvraag / Quote Request"),
                            ("OTHER", "Overig / Other"),
                        ],
                        default="OTHER",
                        help_text=(
                            "W13 -- which pre-W13 `Ticket.type` value this "
                            "category stands in for. A COMPATIBILITY BRIDGE "
                            "and nothing else: `Ticket.type` is a NOT NULL "
                            "column whose removal needs owner sign-off, and "
                            "the pre-existing tickets-by-type report reads "
                            "it. Declaring the mapping on the category row "
                            "keeps it in ONE place, visible and editable, "
                            "instead of hidden in a dict in a serializer. "
                            "Delete this column with `Ticket.type`."
                        ),
                        max_length=32,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "company",
                    models.ForeignKey(
                        help_text=(
                            "Provider company that owns this category. PROTECT "
                            "mirrors every sibling catalog: a Company cannot be "
                            "hard-deleted while it still owns categories."
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ticket_categories",
                        to="companies.company",
                    ),
                ),
            ],
            options={
                "verbose_name": "ticket category",
                "verbose_name_plural": "ticket categories",
                "ordering": ["sort_order", "label_nl", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="ticketcategory",
            constraint=models.UniqueConstraint(
                models.F("company"),
                models.F("slug"),
                name="uniq_ticket_category_slug_per_company",
            ),
        ),
        migrations.AddConstraint(
            model_name="ticketcategory",
            constraint=models.UniqueConstraint(
                Lower(Trim("label_nl")),
                models.F("company"),
                name="uniq_ticket_category_label_nl_per_company_ci",
            ),
        ),
        # A second FK alongside the old one, so the data move can read
        # the old value and write the new in the same transaction. It is
        # renamed onto `category` once the old column is gone.
        migrations.AddField(
            model_name="ticket",
            name="new_category",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tickets_pending",
                to="tickets.ticketcategory",
            ),
        ),
        migrations.RunPython(seed_and_migrate, restore_work_categories),
        migrations.RemoveField(model_name="ticket", name="category"),
        migrations.RenameField(
            model_name="ticket", old_name="new_category", new_name="category"
        ),
        migrations.AlterField(
            model_name="ticket",
            name="category",
            field=models.ForeignKey(
                blank=True,
                default=None,
                help_text=(
                    "W13 — what kind of melding this is, from the company's "
                    "catalog: Verzoek / Extra / Compliment / Melden / Storing "
                    "/ Ongegrond / Klacht."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tickets",
                to="tickets.ticketcategory",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="workcategory",
            name="uniq_work_category_name_per_company_ci",
        ),
        migrations.DeleteModel(name="WorkCategory"),
    ]
