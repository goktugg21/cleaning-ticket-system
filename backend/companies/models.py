from django.conf import settings
from django.db import models


class Company(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    default_language = models.CharField(max_length=8, default="nl")
    is_active = models.BooleanField(default=True)

    # B5 — Super Admin-controlled policy toggle.
    #
    # When True (default): a COMPANY_ADMIN (Provider Admin) of this
    # provider company MAY fully manage CUSTOMER_COMPANY_ADMIN-tier
    # users on any customer under this provider company — create,
    # grant, promote, edit, demote, revoke, delete membership/access.
    # This preserves the post-B4 default documented in
    # `docs/product/system-business-logic-and-workflows.md` §4.5.
    #
    # When False: only SUPER_ADMIN may manage CCA-tier users. The
    # CCA-grant serializer leg
    # (`customers.serializers_memberships.
    # CustomerUserBuildingAccessUpdateSerializer.validate_access_role`)
    # rejects Provider Admin's grant attempts at HTTP 400; the view-
    # layer helpers in `customers.views_memberships`
    # (`_company_admin_cca_policy_blocks_target` and
    # `_company_admin_cca_policy_blocks_access_row`) reject the edit /
    # demote / revoke / extend-reach paths at HTTP 403 with stable
    # code `cca_policy_disabled`. Provider Admin's ability to manage
    # LOWER customer users (B4 — Customer User / Customer Location
    # Manager + their `permission_overrides`) is NOT affected by
    # this toggle; only CCA-tier management is.
    #
    # Only Super Admin may write this field — `CompanySerializer` has
    # a validator that rejects writes from any other actor.
    provider_admin_may_manage_customer_company_admins = models.BooleanField(
        default=True,
        help_text=(
            "Super Admin-controlled policy. When True (default), a "
            "Provider Company Admin of this provider company may "
            "manage Customer Company Admin users on this company's "
            "customers (create, grant, promote, edit, demote, "
            "revoke, delete). When False, only Super Admin may. "
            "B4 lower-user management (Customer User / Customer "
            "Location Manager) is not affected by this toggle."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Companies"

    def __str__(self):
        return self.name


class CompanyUserMembership(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="user_memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="company_memberships",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("company", "user")]

    def __str__(self):
        return f"{self.user} → {self.company}"
