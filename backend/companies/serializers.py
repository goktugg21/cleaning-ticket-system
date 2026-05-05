from rest_framework import serializers

from .models import Company


class CompanySerializer(serializers.ModelSerializer):
    """
    Read+write serializer. Slug is optional on create; the view auto-generates
    it from the name with a collision suffix when omitted. Slug is also
    explicitly settable; rename does NOT auto-update the slug.
    """

    slug = serializers.SlugField(required=False, allow_blank=False, max_length=255)

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "slug",
            "default_language",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]
