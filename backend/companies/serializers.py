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

    Sprint 3B — same shape for `provider_admin_may_manage_catalog` and
    `provider_admin_may_manage_customer_prices`. Both are SA-only
    writable; non-SA writes are rejected by the matching
    `validate_*` method below. Reads are open to anyone the
    `CompanyViewSet` permission gate already admits (SA + the
    member CA of the company).
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
            "provider_admin_may_manage_catalog",
            "provider_admin_may_manage_customer_prices",
            "provider_admin_may_quote_override_start",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]

    def _require_super_admin(self, field_label: str):
        """Sprint 3B — shared SA-only policy guard. Mirrors the B5
        `validate_provider_admin_may_manage_customer_company_admins`
        error message so the three toggles read consistently to the
        operator UI."""
        request = self.context.get("request")
        actor = getattr(request, "user", None) if request else None
        if getattr(actor, "role", None) != UserRole.SUPER_ADMIN:
            raise serializers.ValidationError(
                f"Only a Super Admin may change the "
                f"`{field_label}` policy.",
            )

    def validate_provider_admin_may_manage_customer_company_admins(self, value):
        """B5 — only Super Admin may flip this toggle."""
        self._require_super_admin(
            "provider_admin_may_manage_customer_company_admins"
        )
        return value

    def validate_provider_admin_may_manage_catalog(self, value):
        """Sprint 3B — only Super Admin may flip the catalog toggle."""
        self._require_super_admin("provider_admin_may_manage_catalog")
        return value

    def validate_provider_admin_may_manage_customer_prices(self, value):
        """Sprint 3B — only Super Admin may flip the customer-price
        management toggle."""
        self._require_super_admin(
            "provider_admin_may_manage_customer_prices"
        )
        return value

    def validate_provider_admin_may_quote_override_start(self, value):
        """Sprint 14E — only Super Admin may flip the DANGEROUS
        quote-bypass grant (SoT §2.1 / §5.5). A Provider Company Admin
        with PATCH access to the rest of the Company row cannot
        self-grant this capability."""
        self._require_super_admin(
            "provider_admin_may_quote_override_start"
        )
        return value
