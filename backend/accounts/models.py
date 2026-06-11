from pathlib import Path as FilePath
from uuid import uuid4

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class UserRole(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
    COMPANY_ADMIN = "COMPANY_ADMIN", "Company Admin"
    BUILDING_MANAGER = "BUILDING_MANAGER", "Building Manager"
    # Sprint 23A: service-provider-side field staff. Sees tickets
    # they are assigned to via TicketStaffAssignment; also sees
    # tickets in any building where they hold a
    # BuildingStaffVisibility row.
    STAFF = "STAFF", "Staff"
    CUSTOMER_USER = "CUSTOMER_USER", "Customer User"


class LanguageChoices(models.TextChoices):
    DUTCH = "nl", "Dutch"
    ENGLISH = "en", "English"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email address is required.")

        email = self.normalize_email(email)
        user = self.model(email=email, username=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", UserRole.CUSTOMER_USER)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", UserRole.SUPER_ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")

        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = models.CharField(max_length=150, blank=True)
    email = models.EmailField(unique=True)

    full_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(
        max_length=32,
        choices=UserRole.choices,
        default=UserRole.CUSTOMER_USER,
    )
    language = models.CharField(
        max_length=8,
        choices=LanguageChoices.choices,
        default=LanguageChoices.DUTCH,
    )

    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_users",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        name = self.full_name or ""
        if name:
            return f"{self.email} — {name} — {self.role}"
        return f"{self.email} — {self.role}"

    @property
    def is_soft_deleted(self):
        return self.deleted_at is not None

    def soft_delete(self, deleted_by=None):
        self.is_active = False
        self.deleted_at = timezone.now()
        self.deleted_by = deleted_by
        self.save(update_fields=["is_active", "deleted_at", "deleted_by"])


class StaffProfile(models.Model):
    """
    Sprint 23A — extended profile for service-provider field staff.

    One-to-one with User where User.role == UserRole.STAFF. Holds
    contact details that customers may or may not see (gated by
    Customer.show_assigned_staff_* flags) and an internal note the
    OSIUS admin can use for scheduling notes etc.

    `is_active=False` disables the staff member without removing
    audit history. `can_request_assignment` is a per-staff flag
    that gates the "I want to do this work" flow; it can also be
    revoked per-building via BuildingStaffVisibility.
    """

    class EmploymentType(models.TextChoices):
        # Sprint 13C — provider field-worker employment category. The
        # default `INTERNAL_STAFF` preserves existing behaviour (every
        # pre-13C StaffProfile is backfilled as internal by the column
        # default, so the migration is a plain AddField with no data
        # backfill needed).
        INTERNAL_STAFF = "INTERNAL_STAFF", "Internal staff"
        ZZP = "ZZP", "ZZP (self-employed)"
        INHUUR = "INHUUR", "Inhuur (hired-in)"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_profile",
    )
    phone = models.CharField(max_length=64, blank=True)
    internal_note = models.TextField(blank=True)
    can_request_assignment = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    # Sprint 13C — employee category. DRF derives a strict ChoiceField
    # from these choices on the write serializer, so an out-of-enum value
    # returns the standard 400. Default INTERNAL_STAFF backfills every
    # existing row via the column default.
    employment_type = models.CharField(
        max_length=20,
        choices=EmploymentType.choices,
        default=EmploymentType.INTERNAL_STAFF,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"StaffProfile<{self.user.email}>"


class LoginLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="login_logs",
    )
    email = models.EmailField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    success = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        result = "success" if self.success else "failed"
        return f"{self.email or self.user} - {result}"


# ---------------------------------------------------------------------------
# M2 P2 — staff credentials & custom profile properties (SoT Addendum A.3).
# Data model only; serializers, views, audit registration and the
# visibility resolver are Phase P3.
# ---------------------------------------------------------------------------


class VisibilityLevel(models.TextChoices):
    """
    Visibility ceiling for credential / custom-property rows.

    Conceptually a ladder (PA_SA_ONLY is the most restrictive,
    CUSTOMER_VISIBLE the widest), but stored as a plain enum — the
    P3 resolver owns all comparison logic.
    """

    PA_SA_ONLY = "PA_SA_ONLY", "Provider admin / super admin only"
    PROVIDER_ONLY = "PROVIDER_ONLY", "Any provider-side role"
    CUSTOMER_VISIBLE = "CUSTOMER_VISIBLE", "Visible to granted customers"


def staff_credential_upload_path(instance, filename):
    ext = FilePath(filename).suffix.lower()
    return f"staff_credentials/{instance.staff_profile_id}/{uuid4().hex}{ext}"


def profile_property_upload_path(instance, filename):
    ext = FilePath(filename).suffix.lower()
    return f"profile_properties/{instance.user_id}/{uuid4().hex}{ext}"


# Credential / property documents are PDF-only. Mirrors the extension-MIME
# pairing discipline of tickets.serializers.ALLOWED_EXTENSION_MIME_MAP
# (deliberately NOT imported — accounts must not depend on tickets): the
# declared filename must carry the .pdf extension AND the declared MIME
# type must be application/pdf. Both, not either — scan.pdf declared as
# image/jpeg and scan.jpg declared as application/pdf are both rejected.
ALLOWED_DOCUMENT_EXTENSION = ".pdf"
ALLOWED_DOCUMENT_MIME = "application/pdf"


def _document_pairing_errors(document, original_filename, mime_type, file_size):
    """
    Shared clean() helper for the PDF-only document rule.

    The metadata fields (original_filename, mime_type, file_size) are
    required whenever a document is attached and must be empty/null when
    it is not. Returns a {field: message} dict (empty when valid) so
    callers can merge it with their own validation errors.
    """
    errors = {}
    if document:
        if not original_filename:
            errors["original_filename"] = (
                "original_filename is required when a document is attached."
            )
        elif not original_filename.lower().endswith(ALLOWED_DOCUMENT_EXTENSION):
            errors["original_filename"] = (
                "Only PDF documents are allowed (.pdf extension)."
            )
        if not mime_type:
            errors["mime_type"] = (
                "mime_type is required when a document is attached."
            )
        elif mime_type != ALLOWED_DOCUMENT_MIME:
            errors["mime_type"] = (
                "Only PDF documents are allowed (application/pdf)."
            )
        if file_size is None or file_size <= 0:
            errors["file_size"] = (
                "file_size must be a positive integer when a document"
                " is attached."
            )
    else:
        if original_filename:
            errors["original_filename"] = (
                "original_filename must be empty when no document is attached."
            )
        if mime_type:
            errors["mime_type"] = (
                "mime_type must be empty when no document is attached."
            )
        if file_size is not None:
            errors["file_size"] = (
                "file_size must be null when no document is attached."
            )
    return errors


class StaffCredential(models.Model):
    """
    M2 P2 (SoT Addendum A.3.1) — a work-eligibility credential on a
    provider field-staff profile: residence permit, EU national ID,
    or VCA safety certificate.

    RESIDENCE_PERMIT and EU_NATIONAL_ID are singletons per staff
    member (DB-enforced); a staff member may hold any number of VCA
    rows.

    EU_NATIONAL_ID is a compliance hard block, in code rather than a
    toggle: the row is pinned to visibility_level=PA_SA_ONLY with
    document_customer_visible=False in clean() AND force-overwritten
    in save(), and it can never be granted to a customer (see
    CredentialCustomerVisibility).
    """

    class CredentialType(models.TextChoices):
        RESIDENCE_PERMIT = "RESIDENCE_PERMIT", "Residence permit"
        EU_NATIONAL_ID = "EU_NATIONAL_ID", "EU national ID"
        VCA = "VCA", "VCA certificate"

    staff_profile = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="credentials",
    )
    credential_type = models.CharField(
        max_length=32,
        choices=CredentialType.choices,
    )
    permit_number = models.CharField(max_length=120, blank=True)
    expiry_date = models.DateField(null=True, blank=True)

    document = models.FileField(
        upload_to=staff_credential_upload_path, null=True, blank=True
    )
    original_filename = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=120, blank=True)
    file_size = models.PositiveIntegerField(null=True, blank=True)

    visibility_level = models.CharField(
        max_length=32,
        choices=VisibilityLevel.choices,
        default=VisibilityLevel.PA_SA_ONLY,
    )
    # Only meaningful for RESIDENCE_PERMIT ("show the photocopy too?").
    # For VCA the document follows the credential's own visibility; for
    # EU_NATIONAL_ID it must always be False.
    document_customer_visible = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["staff_profile", "credential_type"],
                condition=models.Q(
                    credential_type__in=["RESIDENCE_PERMIT", "EU_NATIONAL_ID"]
                ),
                name="uniq_staff_singleton_credential",
            ),
            # M2 P3 — the A.3.1 compliance hard block, DATABASE-enforced.
            # clean() + save() already pin EU national IDs to
            # PA_SA_ONLY / not-customer-visible, but QuerySet.update()
            # and bulk_create() bypass Model.save(); this constraint
            # closes that residual at the SQL layer.
            models.CheckConstraint(
                condition=(
                    ~models.Q(credential_type="EU_NATIONAL_ID")
                    | (
                        models.Q(visibility_level="PA_SA_ONLY")
                        & models.Q(document_customer_visible=False)
                    )
                ),
                name="eu_id_hard_block",
            ),
        ]

    def __str__(self):
        return (
            f"StaffCredential<{self.staff_profile_id}:{self.credential_type}>"
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.credential_type == self.CredentialType.EU_NATIONAL_ID:
            if self.visibility_level != VisibilityLevel.PA_SA_ONLY:
                errors["visibility_level"] = (
                    "EU national ID credentials are restricted to provider"
                    " admins (PA_SA_ONLY)."
                )
            if self.document_customer_visible:
                errors["document_customer_visible"] = (
                    "EU national ID documents can never be customer-visible."
                )
        elif (
            self.document_customer_visible
            and self.credential_type != self.CredentialType.RESIDENCE_PERMIT
        ):
            errors["document_customer_visible"] = (
                "Only residence-permit documents can be marked"
                " customer-visible."
            )
        errors.update(
            _document_pairing_errors(
                self.document,
                self.original_filename,
                self.mime_type,
                self.file_size,
            )
        )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Defense-in-depth for the A.3.1 compliance hard block: even a
        # code path that skips full_clean() cannot persist an EU national
        # ID above PA_SA_ONLY or with a customer-visible document.
        if self.credential_type == self.CredentialType.EU_NATIONAL_ID:
            self.visibility_level = VisibilityLevel.PA_SA_ONLY
            self.document_customer_visible = False
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {
                    "visibility_level",
                    "document_customer_visible",
                }
        super().save(*args, **kwargs)


class CustomProfileProperty(models.Model):
    """
    M2 P2 (SoT Addendum A.3.2) — free-form name/value property on a
    user profile, with an optional PDF document.

    Deliberately User-level rather than StaffProfile-level: provider
    field staff AND customer users carry custom properties. The name
    is intentionally NOT unique per user — repeats are allowed; any
    dedup is a frontend concern.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile_properties",
    )
    name = models.CharField(max_length=120)
    value = models.TextField(blank=True)

    document = models.FileField(
        upload_to=profile_property_upload_path, null=True, blank=True
    )
    original_filename = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=120, blank=True)
    file_size = models.PositiveIntegerField(null=True, blank=True)

    visibility_level = models.CharField(
        max_length=32,
        choices=VisibilityLevel.choices,
        default=VisibilityLevel.PA_SA_ONLY,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"CustomProfileProperty<{self.user_id}:{self.name}>"

    def clean(self):
        super().clean()
        errors = _document_pairing_errors(
            self.document,
            self.original_filename,
            self.mime_type,
            self.file_size,
        )
        if errors:
            raise ValidationError(errors)


class CredentialCustomerVisibility(models.Model):
    """
    M2 P2 — per-customer share grant for a staff credential.

    A grant may only be CREATED while the credential's ceiling is
    CUSTOMER_VISIBLE. Lowering the ceiling afterwards deliberately
    does NOT delete existing grant rows — they become inert (the P3
    resolver gates on the ceiling) and spring back if the ceiling is
    raised again. EU national ID credentials are never grantable, in
    any state.
    """

    credential = models.ForeignKey(
        StaffCredential,
        on_delete=models.CASCADE,
        related_name="customer_grants",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["credential", "customer"],
                name="uniq_credential_customer_grant",
            ),
        ]

    def __str__(self):
        return (
            f"CredentialCustomerVisibility<credential={self.credential_id}"
            f" customer={self.customer_id}>"
        )

    def clean(self):
        super().clean()
        if self.credential_id is None:
            return
        if (
            self.credential.credential_type
            == StaffCredential.CredentialType.EU_NATIONAL_ID
        ):
            raise ValidationError(
                {
                    "credential": (
                        "EU national ID credentials can never be shared"
                        " with customers."
                    )
                }
            )
        if (
            self._state.adding
            and self.credential.visibility_level
            != VisibilityLevel.CUSTOMER_VISIBLE
        ):
            raise ValidationError(
                {
                    "credential": (
                        "A share grant can only be created while the"
                        " credential is CUSTOMER_VISIBLE."
                    )
                }
            )

    def save(self, *args, **kwargs):
        # Defense-in-depth twin of the A.3.1 hard block: a grant row
        # pointing at an EU national ID must not be persistable even by
        # code that skips full_clean().
        if (
            self.credential_id is not None
            and self.credential.credential_type
            == StaffCredential.CredentialType.EU_NATIONAL_ID
        ):
            raise ValidationError(
                {
                    "credential": (
                        "EU national ID credentials can never be shared"
                        " with customers."
                    )
                }
            )
        super().save(*args, **kwargs)


class PropertyCustomerVisibility(models.Model):
    """
    M2 P2 — per-customer share grant for a custom profile property.

    Grants are only valid on properties owned by provider field staff
    (the owning user must have a StaffProfile). Same create-time
    ceiling rule and inert-on-lower asymmetry as
    CredentialCustomerVisibility.
    """

    property = models.ForeignKey(
        CustomProfileProperty,
        on_delete=models.CASCADE,
        related_name="customer_grants",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["property", "customer"],
                name="uniq_property_customer_grant",
            ),
        ]

    def __str__(self):
        return (
            f"PropertyCustomerVisibility<property={self.property_id}"
            f" customer={self.customer_id}>"
        )

    def clean(self):
        super().clean()
        if self.property_id is None:
            return
        if not hasattr(self.property.user, "staff_profile"):
            raise ValidationError(
                {
                    "property": (
                        "Share grants are only valid on properties owned"
                        " by provider field staff."
                    )
                }
            )
        if (
            self._state.adding
            and self.property.visibility_level
            != VisibilityLevel.CUSTOMER_VISIBLE
        ):
            raise ValidationError(
                {
                    "property": (
                        "A share grant can only be created while the"
                        " property is CUSTOMER_VISIBLE."
                    )
                }
            )
