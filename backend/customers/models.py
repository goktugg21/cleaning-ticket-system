from django.conf import settings
from django.db import models


class Customer(models.Model):
    """
    Sprint 14 — model semantics changed.

    Before Sprint 14 a Customer row represented a single customer-LOCATION:
    one (company, building, name) tuple. The same logical real-world
    customer present at three buildings was three Customer rows.

    From Sprint 14 the M:N source of truth for which buildings a customer
    is linked to is `CustomerBuildingMembership`. The `building` FK below
    is now NULLABLE and is treated as DEPRECATED — kept on existing rows
    so legacy code paths and the existing data continue to work, and
    used by the migration backfill to seed the first
    CustomerBuildingMembership row for each existing customer.

    A future sprint will drop `Customer.building` and the
    `unique_together(company, building, name)` index once every caller
    has been verified independent of the legacy field. Until then:

      - DO NOT rely on `customer.building` for new code; use
        `customer.building_memberships.all()` instead.
      - For NEW customers created without an anchor building, leave
        `building=None`.
      - For existing customers, `building` continues to point at the
        legacy single-building anchor.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="customers",
    )
    # DEPRECATED in Sprint 14 — see class docstring. Kept nullable so the
    # legacy data continues to work and so the M:N CustomerBuildingMembership
    # is the new source of truth. Do not use for new logic.
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="customers",
        null=True,
        blank=True,
    )

    name = models.CharField(max_length=255)
    contact_email = models.EmailField(blank=True)
    phone = models.CharField(max_length=64, blank=True)
    language = models.CharField(max_length=8, default="nl")

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        # Legacy unique constraint kept so the data migration does not
        # have to renumber any existing row. Postgres treats NULL != NULL,
        # so a new "consolidated" customer with building=NULL does not
        # conflict with another consolidated customer of the same name.
        unique_together = [("company", "building", "name")]

    def __str__(self):
        return self.name


class CustomerBuildingMembership(models.Model):
    """
    Sprint 14 — M:N link between a customer and the buildings it operates at.

    This replaces the legacy single-building Customer.building FK as the
    source of truth for "which buildings does this customer use". Every
    pre-existing customer is backfilled with one row pointing at its
    legacy `building`. A "consolidated" customer (e.g. B Amsterdam with
    three buildings) gets one row per linked building.
    """

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="building_memberships",
    )
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="customer_memberships",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("customer", "building")]
        indexes = [
            models.Index(fields=["customer", "building"]),
        ]

    def __str__(self):
        return f"{self.customer} ↔ {self.building}"


class CustomerUserMembership(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="user_memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_memberships",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("customer", "user")]

    def __str__(self):
        return f"{self.user} → {self.customer}"


class CustomerUserBuildingAccess(models.Model):
    """
    Sprint 14 — per-customer-user, per-building access grant.

    A customer-user is linked to a customer via CustomerUserMembership;
    they additionally must hold one CustomerUserBuildingAccess row per
    building they are allowed to see/act on under that customer.

    Validation (enforced by the membership API + serializer; not by a DB
    check constraint, since the building↔customer link lives in a
    separate table):

      - `building` MUST appear in
        CustomerBuildingMembership(customer=membership.customer).
      - `membership.user.role` MUST be CUSTOMER_USER.
      - User must be active and not soft-deleted at the time of grant.
      - Building must be active at the time of grant.

    The migration backfill creates exactly ONE access row per existing
    CustomerUserMembership, pointing at the customer's legacy
    `building`. This preserves the pre-Sprint-14 behaviour for every
    pilot customer-user: their visibility is unchanged.
    """

    membership = models.ForeignKey(
        CustomerUserMembership,
        on_delete=models.CASCADE,
        related_name="building_access",
    )
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="customer_user_access",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("membership", "building")]
        indexes = [
            models.Index(fields=["membership", "building"]),
        ]

    def __str__(self):
        return f"{self.membership} @ {self.building}"
