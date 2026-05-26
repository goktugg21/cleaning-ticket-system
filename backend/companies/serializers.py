from rest_framework import serializers

from accounts.models import UserRole

from .models import Company


class CompanySerializer(serializers.ModelSerializer):
    """
    Read+write serializer. Slug is optional on create; the view auto-generates
    it from the name with a collision suffix when omitted. Slug is also
    explicitly settable; rename does NOT auto-update the slug.

    B5 — `provider_admin_may_manage_customer_company_admins` is writable on the
    Company but only by Super Admin. The validator
    `validate_provider_admin_may_manage_customer_company_admins` rejects writes
    from any other actor (including the Provider Company Admin who
    otherwise has PATCH access to the rest of the Company row via
    `CompanyViewSet`). This keeps the toggle SA-controlled without
    introducing a dedicated endpoint or a new permission key.
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
            "provider_admin_may_manage_customer_company_admins",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]

    def validate_provider_admin_may_manage_customer_company_admins(self, value):
        """B5 — only Super Admin may flip this toggle."""
        request = self.context.get("request")
        actor = getattr(request, "user", None) if request else None
        if getattr(actor, "role", None) != UserRole.SUPER_ADMIN:
            raise serializers.ValidationError(
                "Only a Super Admin may change the "
                "`provider_admin_may_manage_customer_company_admins` policy.",
            )
        return value
