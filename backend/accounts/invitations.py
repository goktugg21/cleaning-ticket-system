import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import UserRole


def generate_invitation_token():
    """
    Returns (raw_token, token_hash). The raw token is sent in the email link
    and never persisted. Only the hash lives in the DB so a leaked DB row
    alone cannot be used to accept an invitation.
    """
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, token_hash


def hash_invitation_token(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def default_expires_at():
    return timezone.now() + timedelta(days=settings.INVITATION_TTL_DAYS)


class InvitationStatus:
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Invitation(models.Model):
    email = models.EmailField()
    full_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=32, choices=UserRole.choices)

    # Scope at creation time. The accept handler turns these into
    # CompanyUserMembership / BuildingManagerAssignment / CustomerUserMembership
    # rows based on `role`.
    companies = models.ManyToManyField("companies.Company", blank=True, related_name="invitations")
    buildings = models.ManyToManyField("buildings.Building", blank=True, related_name="invitations")
    customers = models.ManyToManyField("customers.Customer", blank=True, related_name="invitations")

    # Token: raw is never stored. Only the sha256 hash.
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)

    # Lifecycle
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invitations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=default_expires_at)

    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_invitation",
    )

    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_invitations",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email"]),
        ]

    def __str__(self):
        return f"{self.email} ({self.role}) invited by {self.created_by_id}"

    @property
    def status(self):
        if self.accepted_at:
            return InvitationStatus.ACCEPTED
        if self.revoked_at:
            return InvitationStatus.REVOKED
        if timezone.now() > self.expires_at:
            return InvitationStatus.EXPIRED
        return InvitationStatus.PENDING

    @property
    def is_consumable(self):
        return self.status == InvitationStatus.PENDING
