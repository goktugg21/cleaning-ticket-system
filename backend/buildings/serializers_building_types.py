"""
Sprint 178 §1 — the building-type catalog's wire shape.

`usage_count` is the number of buildings carrying the type, annotated by
the view for the whole page rather than counted per row. `CatalogTab`
reads it to decide whether Delete is offerable at all.
"""
from __future__ import annotations

from django.db.models.functions import Lower, Trim
from rest_framework import serializers

from .models import BuildingType

ERR_BUILDING_TYPE_NAME_NOT_UNIQUE = "building_type_name_not_unique"


def normalise_building_type_name(name: str) -> str:
    """What the operator typed, with the whitespace the DB constraint
    ignores removed on the way in.

    The constraint compares `Lower(Trim(name))`, so storing an untrimmed
    name would let " Kantoor" and "Kantoor" both exist while the
    constraint considered them equal — the row would be refused with a
    message naming a value the operator cannot see the difference from.
    Trimming at the door means stored names and compared names agree.
    """
    return (name or "").strip()


class BuildingTypeSerializer(serializers.ModelSerializer):
    usage_count = serializers.SerializerMethodField()
    company_name = serializers.CharField(source="company.name", read_only=True)

    class Meta:
        model = BuildingType
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
        return obj.buildings.count()

    def validate_name(self, value):
        cleaned = normalise_building_type_name(value)
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
            BuildingType.objects.filter(company=company)
            .annotate(_key=Lower(Trim("name")))
            .filter(_key=normalise_building_type_name(name).lower())
        )
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                {
                    "name": [
                        "A building type with this name already exists "
                        "for this company."
                    ],
                    "code": ERR_BUILDING_TYPE_NAME_NOT_UNIQUE,
                }
            )
        return attrs
