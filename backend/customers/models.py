from pathlib import Path as FilePath
from uuid import uuid4

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower, Trim


def customer_logo_upload_path(instance, filename):
    # RF-1 — per-customer logo. uuid filename (never trust the client name).
    ext = FilePath(filename).suffix.lower()
    return f"customer_logos/{instance.pk}/{uuid4().hex}{ext}"


def customer_contract_upload_path(instance, filename):
    # Invoicing Phase 1 — informational contract PDF. uuid filename (never
    # trust the client name); always `.pdf`. Mirrors customer_logo_upload_path.
    return f"customer_contracts/{instance.pk}/{uuid4().hex}.pdf"


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

    # RF-1 — customer company logo, shown as the inbox avatar for this
    # customer's threads. Additive/nullable; set only via the authed
    # logo-upload endpoint (that customer's CUSTOMER_COMPANY_ADMIN or
    # SUPER_ADMIN).
    logo = models.ImageField(
        upload_to=customer_logo_upload_path,
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(default=True)

    # Sprint 23A — assigned-staff contact-visibility policy. Default
    # is "show everything" so existing pilot behaviour is unchanged
    # and customer users see the assigned staff's name/email/phone.
    # OSIUS Admin can flip any of these to False per-customer to
    # anonymise the team behind a "Assigned to the OSIUS team" label
    # at the ticket-detail serializer layer. The architecture doc
    # records that this can be extracted into its own
    # CustomerContactVisibilityPolicy table later without changing
    # the ticket-serializer contract.
    show_assigned_staff_name = models.BooleanField(default=True)
    show_assigned_staff_email = models.BooleanField(default=True)
    show_assigned_staff_phone = models.BooleanField(default=True)

    # ---- Invoicing Phase 1 (data model only) ----
    # Billing schedule is a simple INFORMATIONAL setting: it drives the
    # Phase 4 "who's due" list and gates NOTHING. There is no contract
    # entity and no recurring contract-fee amount anywhere in the system.
    class InvoiceDayRule(models.TextChoices):
        FIRST_OF_MONTH = "FIRST_OF_MONTH", "First of month"
        LAST_OF_MONTH = "LAST_OF_MONTH", "Last of month"

    class InvoiceGranularity(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Customer-level"
        PER_BUILDING = "PER_BUILDING", "Per building"
        # Sprint 132 — one level finer: Building + Department + Work Type
        # (reproduces the owner's father's reference invoicing tool). Each
        # invoice covers exactly one (building, department, work_type)
        # combination; Extra Work with no department and/or no work type
        # groups into its own untagged invoice rather than being dropped.
        PER_BUILDING_DEPARTMENT_WORK_TYPE = (
            "PER_BUILDING_DEPARTMENT_WORK_TYPE",
            "Per building, department & work type",
        )

    # blank (default "") = schedule unset.
    invoice_day_rule = models.CharField(
        max_length=16,
        choices=InvoiceDayRule.choices,
        blank=True,
        default="",
        help_text="Informational billing-day rule; drives the 'who's due' list, gates nothing.",
    )
    # Arbitrary billing day: when set (1..28), it is THE billing day-of-month
    # and takes precedence over invoice_day_rule. Capped at 28 so the day
    # exists in every month (use LAST_OF_MONTH for a month-end schedule). NULL
    # = fall back to invoice_day_rule (FIRST/LAST) or, if that is blank too,
    # schedule unset. Informational only — drives the 'who's due' list, gates
    # nothing (mirrors invoice_day_rule).
    invoice_day_of_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(28)],
        help_text=(
            "Specific billing day-of-month (1..28); takes precedence over "
            "invoice_day_rule. NULL falls back to the first/last rule."
        ),
    )
    invoice_granularity_default = models.CharField(
        # Sprint 132 — widened 16 -> 40 to fit
        # "PER_BUILDING_DEPARTMENT_WORK_TYPE" (33 chars); additive, no
        # existing value is affected (CUSTOMER / PER_BUILDING are shorter).
        max_length=40,
        choices=InvoiceGranularity.choices,
        default=InvoiceGranularity.CUSTOMER,
        help_text="Default invoice granularity for Phase 2 generation.",
    )
    # Informational contract PDF: ZERO behavioural effect. One active PDF,
    # replace-on-reupload, NO version history (mirrors the `logo` pattern).
    contract_pdf = models.FileField(
        upload_to=customer_contract_upload_path,
        null=True,
        blank=True,
        help_text="Informational contract PDF only; zero behavioural effect.",
    )

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
    # SoT Addendum A.1 — Customer Company Admin is a COMPANY-WIDE status,
    # not a per-building access_role. A membership with this flag set is
    # admin across ALL the customer's buildings (present + future), needs
    # NO per-building CustomerUserBuildingAccess rows, and NO per-building
    # row may downgrade it. The forward-only 0010 migration collapses the
    # legacy per-building CUSTOMER_COMPANY_ADMIN CUBA rows into this flag.
    is_company_admin = models.BooleanField(
        default=False,
        help_text=(
            "Company-wide Customer Company Admin: admin across ALL the "
            "customer's buildings; per-building access rows do not apply."
        ),
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

    # Sprint 23A — per-building access role for a customer-side
    # user. Defaults to CUSTOMER_USER so every pre-Sprint-23A row
    # backfills with the same effective permissions Sprint 14
    # already documented. LOCATION_MANAGER and COMPANY_ADMIN add
    # broader visibility / approval rights at the customer's
    # location level. The customer-side global User.role stays
    # CUSTOMER_USER; this field is the per-building role.
    class AccessRole(models.TextChoices):
        CUSTOMER_USER = "CUSTOMER_USER", "Customer user"
        CUSTOMER_LOCATION_MANAGER = (
            "CUSTOMER_LOCATION_MANAGER",
            "Customer location manager",
        )
        CUSTOMER_COMPANY_ADMIN = (
            "CUSTOMER_COMPANY_ADMIN",
            "Customer company admin",
        )

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
    # Sprint 23A: per-building role on the customer side.
    access_role = models.CharField(
        max_length=32,
        choices=AccessRole.choices,
        default=AccessRole.CUSTOMER_USER,
    )
    # Sprint 23A: free-form { permission_key: bool } overrides on
    # top of the role default. True grants, False revokes, missing
    # falls back to the role default. The full key list lives in
    # docs/archive/2026-05-sprints/sprint-23a-domain-permissions-foundation.md
    # and the resolver lives in customers/permissions.py.
    permission_overrides = models.JSONField(default=dict, blank=True)
    # Sprint 23A: lets an admin temporarily disable an access grant
    # without deleting the row (preserves audit trail).
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("membership", "building")]
        indexes = [
            models.Index(fields=["membership", "building"]),
        ]

    def __str__(self):
        return f"{self.membership} @ {self.building}"


class CustomerCompanyPolicy(models.Model):
    """
    Sprint 27C — one-to-one customer-company policy carrier
    (starts RBAC gap G-B5).

    Holds the booleans an OSIUS Admin / Provider Company Admin can
    flip per customer organisation to shape what its users see and
    do. The two groups of fields:

      Visibility policy — copied 1:1 from the existing fields on
      Customer (`show_assigned_staff_{name,email,phone}`). Those
      legacy fields stay in place this sprint so the ticket-detail
      serializer contract is unchanged. A future sprint will
      migrate the runtime read path here and drop the Customer
      copies.

      Permission policy — new in Sprint 27C, no runtime consumer
      yet. These toggles will become the data backbone of the
      Sprint 27E permission-management UI:

        * customer_users_can_create_tickets
        * customer_users_can_approve_ticket_completion
        * customer_users_can_create_extra_work
        * customer_users_can_approve_extra_work_pricing

    Every default is True so backfilling on existing customers
    preserves today's behaviour.

    Each new Customer automatically gets a policy row via the
    accounts/signals.py CREATE signal. Pre-existing customers are
    handled by the matching data migration that ships with this
    model.
    """

    customer = models.OneToOneField(
        Customer,
        on_delete=models.CASCADE,
        related_name="policy",
    )

    # Visibility policy (mirror of legacy Customer.show_assigned_staff_*
    # fields; both sets live in parallel during Sprint 27C).
    show_assigned_staff_name = models.BooleanField(default=True)
    show_assigned_staff_email = models.BooleanField(default=True)
    show_assigned_staff_phone = models.BooleanField(default=True)

    # Permission policy (new). The runtime resolver does NOT consume
    # these yet — the field shape is locked in 27C so the editor
    # surface (27E) can write to them, and a follow-up sprint can
    # introduce the lookup in the customer permission resolver.
    customer_users_can_create_tickets = models.BooleanField(default=True)
    customer_users_can_approve_ticket_completion = models.BooleanField(
        default=True
    )
    customer_users_can_create_extra_work = models.BooleanField(default=True)
    customer_users_can_approve_extra_work_pricing = models.BooleanField(
        default=True
    )
    # Sprint 126 — company-wide toggle for the customer Documents module
    # (the "Documenten" module card). Default True: existing customers keep
    # the role-default grant of `customer.documents.manage`. Setting it False
    # denies that key for every customer user of this customer, the company-
    # wide CCA included (see permissions._POLICY_FAMILY_FIELD).
    customer_users_can_manage_documents = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "customer company policy"
        verbose_name_plural = "customer company policies"

    def __str__(self):
        return f"Policy for {self.customer}"


class ContactType(models.TextChoices):
    GENERAL = "GENERAL", "General"
    OPERATIONS = "OPERATIONS", "Operations"
    BILLING = "BILLING", "Billing"
    EMERGENCY = "EMERGENCY", "Emergency"


class Contact(models.Model):
    """
    Sprint 28 Batch 4 — customer-side phone-book entry.

    Distinct from Users (spec docs/product/requirements-meeting-2026-05-15.md §1):

      * Contact = a person listed only for communication (name, phone,
        email, free-text role label, notes). It is NOT an authenticated
        principal — there is no `user` FK, no password, no UserRole,
        no scope rows and no permission overrides. Promoting a Contact
        to a User is an explicit future-sprint flow, never a side-effect
        of editing a Contact.
      * Customer.contact_email (see Customer above) is the single
        *primary* email for the customer organisation as a whole. The
        Contact rows here are the full phone book of people you may
        want to contact at that customer (operations lead, building
        super, facility receptionist, etc.). The two live in parallel;
        Sprint 28 Batch 4 does not collapse `Customer.contact_email`.

    `building` is optional and, when provided, MUST refer to a building
    the customer is linked to via `CustomerBuildingMembership` (the
    serializer enforces this). The FK is `SET_NULL` on building
    deletion so the contact row survives a building soft-delete /
    decommission, but `CASCADE` on customer deletion because a
    contact is owned by its customer.
    """

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="contacts",
    )
    # Sprint 12B — DEPRECATED single-building anchor; multi-building is now
    # ContactBuildingLink. Kept (nullable) for back-compat + the 12B backfill source.
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.SET_NULL,
        related_name="customer_contacts",
        null=True,
        blank=True,
    )

    full_name = models.CharField(max_length=255)
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=64, blank=True, default="")
    role_label = models.CharField(max_length=128, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    # Sprint 12B — contact taxonomy + primary flag.
    contact_type = models.CharField(
        max_length=16,
        choices=ContactType.choices,
        default=ContactType.GENERAL,
    )
    is_primary = models.BooleanField(default=False)

    # Sprint 12B promote-to-user bridge. NULL = not promoted. SET_NULL so
    # deleting the User leaves the person record intact. Set ONLY by the
    # promote/link flow, never by a plain Contact edit (the serializer keeps
    # it read-only).
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_contacts",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name", "id"]
        constraints = [
            # One Contact per User within a customer. Postgres allows many
            # NULLs so unpromoted contacts are unconstrained.
            models.UniqueConstraint(
                fields=["customer", "user"],
                condition=Q(user__isnull=False),
                name="uniq_contact_user_per_customer",
            ),
        ]

    def __str__(self):
        return self.full_name


class ContactBuildingLink(models.Model):
    """Sprint 12B — M:N Contact↔Building. One contact can serve multiple
    buildings under the same customer. Mirrors CustomerBuildingMembership.
    Backfilled from the legacy Contact.building."""

    contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        related_name="building_links",
    )
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="contact_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("contact", "building")]
        indexes = [
            models.Index(fields=["contact", "building"]),
        ]

    def __str__(self):
        return f"{self.contact} ↔ {self.building}"


class _CustomerLabelList(models.Model):
    """Sprint 127 — abstract base for a customer's Extra Work label lists.

    Two concrete lists inherit this shape unchanged today: `Department`
    (a sub-client / segment of the customer — B Amsterdam's Algemeen /
    Event / Member, or another customer's twelve medical practices) and
    `WorkType` (the kind of job — Eindschoonmaak / Opleverschoonmaak /
    Bouw schoonmaak / ...). Both are PURE labels: no state machine, no
    permissions of their own, no derived behaviour. They are picked from a
    dropdown, saved onto an `ExtraWorkRequest`, then grouped / filtered by.

    Why an abstract base and NOT one shared table with a `kind`
    discriminator: the two lists are independently optional (one real
    customer has twelve departments and ZERO work types) and each backs a
    SEPARATE nullable FK on `ExtraWorkRequest`. Two concrete tables make it
    structurally impossible to tag the `work_type` slot with a `Department`
    row (the FK targets differ), which a single `kind`-tagged table could
    not prevent without a check on every read. The base only shares field
    DEFINITIONS; it creates no shared rows and no coupling between the two.

    The case-insensitive per-customer uniqueness mirrors the `extra_work`
    `ManagedUnit` precedent (migration 0018): `Lower(Trim(name))` +
    `customer`, built by Postgres as a real expression index so a race or a
    direct-ORM write cannot create "Event" and "event " as two rows. The
    serializer strips `name` on write, so the Trim only ever matters as a
    DB-level backstop.
    """

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="%(class)ss",
        help_text=(
            "Customer that owns this label. CASCADE: the label list is "
            "pure per-customer metadata with no independent lifecycle, so "
            "it is removed with the customer."
        ),
    )
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Archiving (is_active=False) retires a label from the everyday "
            "picker WITHOUT breaking Extra Work rows that already reference "
            "it — the soft-retire path when a hard delete is refused by the "
            "PROTECT on ExtraWorkRequest."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                Lower(Trim("name")),
                "customer",
                name="uniq_%(app_label)s_%(class)s_name_per_customer_ci",
            ),
        ]

    def __str__(self):
        return f"{self.customer_id}: {self.name}"


class Department(_CustomerLabelList):
    """Sprint 127 — a customer's Department list. See `_CustomerLabelList`.

    NOT a department in the org-chart sense: it is a sub-client / segment
    of the customer (Algemeen / Event / Member; or twelve medical
    practices). Consumed only by `ExtraWorkRequest.department`.
    """

    class Meta(_CustomerLabelList.Meta):
        verbose_name = "department"
        verbose_name_plural = "departments"


class WorkType(_CustomerLabelList):
    """Sprint 127 — a customer's Work Type list. See `_CustomerLabelList`.

    The kind of job (Eindschoonmaak / Opleverschoonmaak / Bouw schoonmaak
    / Extra werkzaamheden / Overige). Distinct from the fixed-choice
    `ExtraWorkRequest.category` enum: that classifies one ad-hoc request
    from a global list; this is a per-customer, operator-curated label
    used for reporting and invoice grouping. Consumed only by
    `ExtraWorkRequest.work_type`.
    """

    class Meta(_CustomerLabelList.Meta):
        verbose_name = "work type"
        verbose_name_plural = "work types"
