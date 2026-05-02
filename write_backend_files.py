from pathlib import Path

files = {
    "backend/accounts/models.py": r'''
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.conf import settings
from django.db import models
from django.utils import timezone


class UserRole(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
    COMPANY_ADMIN = "COMPANY_ADMIN", "Company Admin"
    BUILDING_MANAGER = "BUILDING_MANAGER", "Building Manager"
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
        return self.full_name or self.email

    @property
    def is_soft_deleted(self):
        return self.deleted_at is not None

    def soft_delete(self, deleted_by=None):
        self.is_active = False
        self.deleted_at = timezone.now()
        self.deleted_by = deleted_by
        self.save(update_fields=["is_active", "deleted_at", "deleted_by"])


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
''',

    "backend/companies/models.py": r'''
from django.conf import settings
from django.db import models


class Company(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    default_language = models.CharField(max_length=8, default="nl")
    is_active = models.BooleanField(default=True)

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
''',

    "backend/buildings/models.py": r'''
from django.conf import settings
from django.db import models


class Building(models.Model):
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="buildings",
    )

    name = models.CharField(max_length=255)
    address = models.CharField(max_length=500, blank=True)
    city = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=32, blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("company", "name")]

    def __str__(self):
        return self.name


class BuildingManagerAssignment(models.Model):
    building = models.ForeignKey(
        Building,
        on_delete=models.CASCADE,
        related_name="manager_assignments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="building_assignments",
    )

    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("building", "user")]

    def __str__(self):
        return f"{self.user} → {self.building}"
''',

    "backend/customers/models.py": r'''
from django.conf import settings
from django.db import models


class Customer(models.Model):
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="customers",
    )
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="customers",
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
        unique_together = [("company", "building", "name")]

    def __str__(self):
        return self.name


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
''',

    "backend/tickets/models.py": r'''
from django.conf import settings
from django.db import models
from django.utils import timezone


class TicketType(models.TextChoices):
    REPORT = "REPORT", "Melding / Report"
    COMPLAINT = "COMPLAINT", "Klacht / Complaint"
    REQUEST = "REQUEST", "Verzoek / Request"
    SUGGESTION = "SUGGESTION", "Suggestie / Suggestion"
    QUOTE_REQUEST = "QUOTE_REQUEST", "Offerteaanvraag / Quote Request"


class TicketPriority(models.TextChoices):
    NORMAL = "NORMAL", "Normal"
    HIGH = "HIGH", "High"
    URGENT = "URGENT", "Urgent"


class TicketStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    WAITING_CUSTOMER_APPROVAL = "WAITING_CUSTOMER_APPROVAL", "Waiting Customer Approval"
    REJECTED = "REJECTED", "Rejected"
    APPROVED = "APPROVED", "Approved"
    CLOSED = "CLOSED", "Closed"
    REOPENED_BY_ADMIN = "REOPENED_BY_ADMIN", "Reopened by Admin"


class TicketMessageType(models.TextChoices):
    PUBLIC_REPLY = "PUBLIC_REPLY", "Public Reply"
    INTERNAL_NOTE = "INTERNAL_NOTE", "Internal Note"


def ticket_attachment_upload_path(instance, filename):
    return f"tickets/{instance.ticket_id}/{filename}"


class Ticket(models.Model):
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="tickets",
    )
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="tickets",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_tickets",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )

    ticket_no = models.CharField(max_length=32, unique=True, blank=True)

    title = models.CharField(max_length=255)
    description = models.TextField()
    room_label = models.CharField(max_length=255, blank=True)

    type = models.CharField(
        max_length=32,
        choices=TicketType.choices,
        default=TicketType.REPORT,
    )
    priority = models.CharField(
        max_length=32,
        choices=TicketPriority.choices,
        default=TicketPriority.NORMAL,
    )
    status = models.CharField(
        max_length=64,
        choices=TicketStatus.choices,
        default=TicketStatus.OPEN,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    first_response_at = models.DateTimeField(null=True, blank=True)
    sent_for_approval_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.ticket_no or self.id} - {self.title}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new and not self.ticket_no:
            self.ticket_no = f"TCK-{self.created_at.year}-{self.id:06d}"
            super().save(update_fields=["ticket_no"])

    def mark_first_response_if_needed(self):
        if not self.first_response_at:
            self.first_response_at = timezone.now()
            self.save(update_fields=["first_response_at"])


class TicketMessage(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_messages",
    )

    message = models.TextField()
    message_type = models.CharField(
        max_length=32,
        choices=TicketMessageType.choices,
        default=TicketMessageType.PUBLIC_REPLY,
    )

    is_hidden = models.BooleanField(default=False)
    hidden_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hidden_ticket_messages",
    )
    hidden_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.ticket} - {self.author}"


class TicketAttachment(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    message = models.ForeignKey(
        TicketMessage,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_attachments",
    )

    file = models.FileField(upload_to=ticket_attachment_upload_path)
    original_filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120)
    file_size = models.PositiveIntegerField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.original_filename


class TicketStatusHistory(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="status_history",
    )

    old_status = models.CharField(max_length=64, blank=True)
    new_status = models.CharField(max_length=64)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_status_changes",
    )
    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name_plural = "Ticket status history"

    def __str__(self):
        return f"{self.ticket}: {self.old_status} → {self.new_status}"
''',

    "backend/accounts/admin.py": r'''
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import LoginLog, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    model = User
    list_display = ("email", "full_name", "role", "language", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff", "language")
    search_fields = ("email", "full_name")
    ordering = ("email",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("full_name", "language")}),
        ("Access", {"fields": ("role",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Soft delete", {"fields": ("deleted_at", "deleted_by")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "role", "language", "password1", "password2"),
            },
        ),
    )


@admin.register(LoginLog)
class LoginLogAdmin(admin.ModelAdmin):
    list_display = ("email", "user", "ip_address", "success", "created_at")
    list_filter = ("success", "created_at")
    search_fields = ("email", "user__email", "ip_address", "user_agent")
    readonly_fields = ("created_at",)
''',

    "backend/companies/admin.py": r'''
from django.contrib import admin

from .models import Company, CompanyUserMembership


class CompanyUserMembershipInline(admin.TabularInline):
    model = CompanyUserMembership
    extra = 1


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "default_language", "is_active", "created_at")
    list_filter = ("is_active", "default_language")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [CompanyUserMembershipInline]


@admin.register(CompanyUserMembership)
class CompanyUserMembershipAdmin(admin.ModelAdmin):
    list_display = ("company", "user", "created_at")
    list_filter = ("company",)
    search_fields = ("company__name", "user__email", "user__full_name")
''',

    "backend/buildings/admin.py": r'''
from django.contrib import admin

from .models import Building, BuildingManagerAssignment


class BuildingManagerAssignmentInline(admin.TabularInline):
    model = BuildingManagerAssignment
    extra = 1


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "city", "country", "is_active")
    list_filter = ("company", "city", "country", "is_active")
    search_fields = ("name", "address", "city", "country", "postal_code")
    inlines = [BuildingManagerAssignmentInline]


@admin.register(BuildingManagerAssignment)
class BuildingManagerAssignmentAdmin(admin.ModelAdmin):
    list_display = ("building", "user", "assigned_at")
    list_filter = ("building__company",)
    search_fields = ("building__name", "user__email", "user__full_name")
''',

    "backend/customers/admin.py": r'''
from django.contrib import admin

from .models import Customer, CustomerUserMembership


class CustomerUserMembershipInline(admin.TabularInline):
    model = CustomerUserMembership
    extra = 1


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "building", "contact_email", "language", "is_active")
    list_filter = ("company", "building", "language", "is_active")
    search_fields = ("name", "contact_email", "phone")
    inlines = [CustomerUserMembershipInline]


@admin.register(CustomerUserMembership)
class CustomerUserMembershipAdmin(admin.ModelAdmin):
    list_display = ("customer", "user", "created_at")
    list_filter = ("customer__company", "customer__building")
    search_fields = ("customer__name", "user__email", "user__full_name")
''',

    "backend/tickets/admin.py": r'''
from django.contrib import admin

from .models import Ticket, TicketAttachment, TicketMessage, TicketStatusHistory


class TicketMessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0
    readonly_fields = ("created_at",)


class TicketAttachmentInline(admin.TabularInline):
    model = TicketAttachment
    extra = 0
    readonly_fields = ("created_at",)


class TicketStatusHistoryInline(admin.TabularInline):
    model = TicketStatusHistory
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("ticket_no", "title", "company", "building", "customer", "type", "priority", "status", "created_at")
    list_filter = ("company", "building", "customer", "type", "priority", "status")
    search_fields = ("ticket_no", "title", "description", "room_label")
    readonly_fields = ("ticket_no", "created_at", "updated_at")
    inlines = [TicketMessageInline, TicketAttachmentInline, TicketStatusHistoryInline]


@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    list_display = ("ticket", "author", "message_type", "is_hidden", "created_at")
    list_filter = ("message_type", "is_hidden", "created_at")
    search_fields = ("ticket__ticket_no", "author__email", "message")


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "original_filename", "mime_type", "file_size", "uploaded_by", "created_at")
    list_filter = ("mime_type", "created_at")
    search_fields = ("ticket__ticket_no", "original_filename")


@admin.register(TicketStatusHistory)
class TicketStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("ticket", "old_status", "new_status", "changed_by", "created_at")
    list_filter = ("old_status", "new_status", "created_at")
    search_fields = ("ticket__ticket_no", "changed_by__email", "note")
''',

    "backend/config/urls.py": r'''
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path


urlpatterns = [
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
''',
}

for path, content in files.items():
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content.strip() + "\n", encoding="utf-8")

print("Backend files written successfully.")
