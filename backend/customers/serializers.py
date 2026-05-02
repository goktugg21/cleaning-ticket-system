from rest_framework import serializers

from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            "id",
            "company",
            "building",
            "name",
            "contact_email",
            "phone",
            "language",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
