from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.conf import settings
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

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_profile",
    )
    phone = models.CharField(max_length=64, blank=True)
    internal_note = models.TextField(blank=True)
    can_request_assignment = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

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
