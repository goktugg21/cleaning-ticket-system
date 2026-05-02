from django_filters import rest_framework as df

from .models import Customer


class CustomerFilter(df.FilterSet):
    class Meta:
        model = Customer
        fields = ["company", "building", "is_active", "language"]
