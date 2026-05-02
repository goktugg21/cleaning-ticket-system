from django_filters import rest_framework as df

from .models import Company


class CompanyFilter(df.FilterSet):
    class Meta:
        model = Company
        fields = ["is_active", "default_language"]
