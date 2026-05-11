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


class BuildingStaffVisibility(models.Model):
    """
    Sprint 23A — grants a STAFF user read visibility on every
    ticket / work item in a building.

    A staff user without any visibility row only sees tickets where
    they are explicitly listed in TicketStaffAssignment. A row here
    adds full-building read access (still cannot complete a ticket
    they are not assigned to without an extra permission). With
    `can_request_assignment=True` the staff user can also POST a
    StaffAssignmentRequest for an unassigned ticket in this
    building.
    """

    building = models.ForeignKey(
        Building,
        on_delete=models.CASCADE,
        related_name="staff_visibility",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="building_visibility",
    )
    can_request_assignment = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("building", "user")]

    def __str__(self):
        return f"{self.user} 👁 {self.building}"
