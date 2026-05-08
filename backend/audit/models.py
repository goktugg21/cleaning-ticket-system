from django.conf import settings
from django.db import models


class AuditAction(models.TextChoices):
    CREATE = "CREATE", "Create"
    UPDATE = "UPDATE", "Update"
    DELETE = "DELETE", "Delete"


class AuditLog(models.Model):
    """
    Immutable record of a mutation against a tracked admin model.

    Tracked models: accounts.User, companies.Company, buildings.Building,
    customers.Customer. Reads, token refresh, and password changes are
    NOT logged. Sensitive fields (password, tokens, secrets, MFA) are
    filtered out of `changes` before persistence — see audit.diff for
    the redaction rules.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        help_text="User who triggered the mutation. NULL for system writes.",
    )
    action = models.CharField(
        max_length=8,
        choices=AuditAction.choices,
    )
    target_model = models.CharField(
        max_length=100,
        help_text='"app_label.ModelName" of the mutated object.',
    )
    target_id = models.IntegerField(
        help_text="Primary key of the mutated object at the time of the event.",
    )
    changes = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            'Per-field diff: {"field": {"before": <old>, "after": <new>}}. '
            "Sensitive fields are stripped before write."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    request_ip = models.GenericIPAddressField(null=True, blank=True)
    request_id = models.CharField(max_length=128, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["target_model", "target_id"]),
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        actor_label = self.actor.email if self.actor_id else "system"
        return f"{self.action} {self.target_model}#{self.target_id} by {actor_label}"
