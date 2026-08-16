"""
Sprint 185 E §1 — the work-category catalog's wire shape.

Deliberately `buildings.serializers_building_types` field for field: the
same `usage_count` annotation contract, the same trim-at-the-door rule,
the same friendly duplicate check in front of the same kind of database
constraint. Sixth catalog, one shape.

`usage_count` is the number of meldingen carrying the category,
annotated by the view for the whole page rather than counted per row.
`CatalogTab` reads it to decide whether Delete is offerable at all.
"""
from __future__ import annotations

from django.db.models.functions import Lower, Trim
from rest_framework import serializers

from .models import WorkCategory

ERR_WORK_CATEGORY_NAME_NOT_UNIQUE = "work_category_name_not_unique"


def normalise_work_category_name(name: str) -> str:
    """What the operator typed, with the whitespace the DB constraint
    ignores removed on the way in.

    The constraint compares `Lower(Trim(name))`, so storing an untrimmed
    name would let " Sanitair" and "Sanitair" both exist while the
    constraint considered them equal — the row would be refused with a
    message naming a value the operator cannot see the difference from.
    Trimming at the door means stored names and compared names agree.
    """
    return (name or "").strip()


class WorkCategorySerializer(serializers.ModelSerializer):
    usage_count = serializers.SerializerMethodField()
    company_name = serializers.CharField(source="company.name", read_only=True)

    class Meta:
        model = WorkCategory
        fields = [
            "id",
            "company",
            "company_name",
            "name",
            "is_active",
            "sort_order",
            "usage_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_usage_count(self, obj) -> int:
        # The view annotates this for the page; the fallback keeps a
        # serializer used outside that view honest rather than crashing.
        annotated = getattr(obj, "annotated_usage_count", None)
        if annotated is not None:
            return annotated
        return obj.tickets.count()

    def validate_name(self, value):
        cleaned = normalise_work_category_name(value)
        if not cleaned:
            raise serializers.ValidationError("A name is required.")
        return cleaned

    def validate(self, attrs):
        """Friendly duplicate check.

        The DB constraint is the authority — this can lose a race, and
        the view catches `IntegrityError` for exactly that reason. This
        exists so the ordinary case returns a readable message with a
        stable code instead of a 500-shaped integrity error.
        """
        name = attrs.get("name", getattr(self.instance, "name", None))
        company = attrs.get("company", getattr(self.instance, "company", None))
        if not name or company is None:
            return attrs
        clash = (
            WorkCategory.objects.filter(company=company)
            .annotate(_key=Lower(Trim("name")))
            .filter(_key=normalise_work_category_name(name).lower())
        )
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                {
                    "name": [
                        "A work category with this name already exists "
                        "for this company."
                    ],
                    "code": ERR_WORK_CATEGORY_NAME_NOT_UNIQUE,
                }
            )
        return attrs
