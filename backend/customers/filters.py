from django_filters import rest_framework as df

from .models import Customer


class CustomerFilter(df.FilterSet):
    class Meta:
        model = Customer
        fields = [
            "company",
            "building",
            "is_active",
            "language",
            # Sprint 185 §3 — filter the list by where the relationship
            # is. The one an operator actually reaches for is NOTICE:
            # "who is leaving, and are we still serving them properly".
            #
            # `is_active` stays in this list and stays a separate
            # question. They are independent axes and filtering by one
            # must never imply the other.
            "lifecycle",
        ]
