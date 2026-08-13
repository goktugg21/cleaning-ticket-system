from django_filters import rest_framework as df

from .models import Building


class BuildingFilter(df.FilterSet):
    class Meta:
        model = Building
        # Sprint 178 §1 — `building_type` is the entire point of the
        # owner's example: a company invents "health building", one
        # building carries it, and it must appear in the FILTERS. A
        # catalog whose values do not reach the filters is a dropdown,
        # not a taxonomy.
        fields = [
            "company",
            "is_active",
            "city",
            "country",
            "building_type",
        ]
