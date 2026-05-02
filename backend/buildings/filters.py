from django_filters import rest_framework as df

from .models import Building


class BuildingFilter(df.FilterSet):
    class Meta:
        model = Building
        fields = ["company", "is_active", "city", "country"]
