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

    # Sprint 3B — Super Admin-controlled policy toggles on the
    # provider catalog + customer-specific pricing surfaces.
    #
    # When True (default — preserves pre-Sprint-3B behaviour), a
    # COMPANY_ADMIN (Provider Admin) of this provider company MAY
    # create / update / archive `extra_work.Service` and
    # `extra_work.ServiceCategory` rows owned by this provider
    # company. When False, only SUPER_ADMIN may. The catalog view
    # layer (`extra_work.views_catalog`) raises HTTP 403 with the
    # stable code `provider_admin_catalog_management_disabled` when
    # the toggle is False.
    provider_admin_may_manage_catalog = models.BooleanField(
        default=True,
        help_text=(
            "Sprint 3B — Super Admin-controlled policy. When True "
            "(default), a Provider Company Admin of this provider "
            "company may manage the provider service catalog "
            "(create/update/archive Service + ServiceCategory) for "
            "this company. When False, only Super Admin may. "
            "Building Manager / Staff / Customer-side users are "
            "blocked regardless of this toggle."
        ),
    )

    # Sprint 3B — same shape as the catalog toggle, but governs the
    # write surface on `extra_work.CustomerServicePrice` rows for
    # any customer under this provider company. Reject path returns
    # HTTP 403 with stable code
    # `provider_admin_customer_price_management_disabled`.
    provider_admin_may_manage_customer_prices = models.BooleanField(
        default=True,
        help_text=(
            "Sprint 3B — Super Admin-controlled policy. When True "
            "(default), a Provider Company Admin of this provider "
            "company may create / update / archive customer-"
            "specific service prices (CustomerServicePrice) for "
            "any customer under this provider company. When False, "
            "only Super Admin may."
        ),
    )

    # Sprint 14E — DANGEROUS Super Admin-controlled grant. Backs the
    # `provider.extra_work.quote_override_start` permission key
    # (`accounts.permissions_v2.user_has_provider_dangerous_permission`).
    #
    # When True: a COMPANY_ADMIN / BUILDING_MANAGER of this provider
    # company MAY directly publish a REQUEST_QUOTE Extra Work proposal
    # (DRAFT -> CUSTOMER_APPROVED) WITHOUT the customer's approval, via
    # the `proposals/<pid>/direct-publish/` endpoint, after entering
    # pricing. This is the SoT §5.5 dangerous quote-bypass.
    #
    # When False (default — DANGEROUS, so OFF by default per SoT §2.1):
    # only SUPER_ADMIN may quote-bypass. A Provider Admin / Building
    # Manager is blocked even if they hold the generic B6
    # `osius.building_manager.override_customer_decision` key — the
    # dedicated dangerous grant is REQUIRED and is separate from the
    # generic override. Every successful bypass writes a HIGH-severity
    # AuditLog row (`audit.models.AuditLog.severity`).
    #
    # Only SUPER_ADMIN may write this field — `CompanySerializer`'s
    # `validate_provider_admin_may_quote_override_start` rejects writes
    # from any other actor. The field is part of `Company`'s full-CRUD
    # audit coverage, so every grant / revoke lands on the AuditLog.
    provider_admin_may_quote_override_start = models.BooleanField(
        default=False,
        help_text=(
            "Sprint 14E — DANGEROUS Super Admin-controlled grant "
            "(default OFF). When True, a Provider Company Admin / "
            "Building Manager of this provider company may bypass "
            "customer quote approval and start work from a "
            "REQUEST_QUOTE proposal after entering pricing "
            "(direct-publish). When False, only Super Admin may. "
            "Backs the provider.extra_work.quote_override_start "
            "permission key; every use is HIGH-severity audited."
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
