"""Planned-work serializers (Sprint 11B Batch 3).

Provider-only surface. The write serializer mirrors the Extra Work
create serializer's `validate()` shape: same-company building/customer
check + provider-side scope via `user_has_osius_permission(
"osius.ticket.view_building", building_id=...)`. Crew (default staff /
managers) is supplied as optional write-only id lists and persisted into
the RecurringJobDefaultStaff / RecurringJobDefaultManager join tables,
with per-building eligibility validation.
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from accounts.models import UserRole
from accounts.permissions_v2 import user_has_osius_permission
from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
from tickets.models import Ticket

from .models import (
    PlannedOccurrence,
    PricingMode,
    RecurringJob,
    RecurringJobDefaultManager,
    RecurringJobDefaultStaff,
)


def _two_places(value):
    """Quantize to 2 decimal places — consistent with
    `extra_work.models._two_places` so planned-work money math matches the
    Extra Work / proposal money math exactly."""
    return value.quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# RecurringJob — read
# ---------------------------------------------------------------------------
class RecurringJobReadSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.name", read_only=True)
    building_name = serializers.CharField(
        source="building.name", read_only=True
    )
    customer_name = serializers.CharField(
        source="customer.name", read_only=True
    )
    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True
    )
    default_staff_ids = serializers.SerializerMethodField()
    default_manager_ids = serializers.SerializerMethodField()
    occurrences_count = serializers.SerializerMethodField()

    class Meta:
        model = RecurringJob
        fields = [
            "id",
            "company",
            "company_name",
            "building",
            "building_name",
            "customer",
            "customer_name",
            "title",
            "description",
            "frequency",
            "start_date",
            "end_date",
            "preferred_start_time",
            "time_window_label",
            "pricing_mode",
            "fixed_price",
            "vat_pct",
            "is_active",
            "archived_at",
            "created_by",
            "created_by_email",
            "created_at",
            "updated_at",
            "default_staff_ids",
            "default_manager_ids",
            "occurrences_count",
        ]
        read_only_fields = fields

    def get_default_staff_ids(self, obj):
        return [s.user_id for s in obj.default_staff.all()]

    def get_default_manager_ids(self, obj):
        return [m.user_id for m in obj.default_managers.all()]

    def get_occurrences_count(self, obj):
        return obj.occurrences.count()


def _user_role_is(user_id: int, role: str) -> bool:
    """True iff a user with `user_id` exists and holds `role`."""
    from accounts.models import User

    return User.objects.filter(pk=user_id, role=role).exists()


# ---------------------------------------------------------------------------
# RecurringJob — write (create / update)
# ---------------------------------------------------------------------------
class RecurringJobWriteSerializer(serializers.ModelSerializer):
    default_staff_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
    )
    default_manager_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
    )

    class Meta:
        model = RecurringJob
        fields = [
            "building",
            "customer",
            "title",
            "description",
            "frequency",
            "start_date",
            "end_date",
            "preferred_start_time",
            "time_window_label",
            "pricing_mode",
            "fixed_price",
            "vat_pct",
            "is_active",
            "default_staff_ids",
            "default_manager_ids",
        ]

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user
        instance = getattr(self, "instance", None)

        # On PATCH, building / customer may be absent — fall back to the
        # instance's current values so the same-company + scope checks
        # still anchor on the effective pair.
        building = attrs.get("building") or getattr(instance, "building", None)
        customer = attrs.get("customer") or getattr(instance, "customer", None)

        if building is None or customer is None:
            raise serializers.ValidationError(
                {
                    "building": serializers.ErrorDetail(
                        "Building and customer are required.",
                        code="building_customer_required",
                    )
                }
            )

        # Single-company invariant: the building and customer must belong
        # to the same provider company.
        if building.company_id != customer.company_id:
            raise serializers.ValidationError(
                {
                    "customer": serializers.ErrorDetail(
                        "Building and customer must belong to the same "
                        "company.",
                        code="company_mismatch",
                    )
                }
            )

        # Provider-side scope. SUPER_ADMIN is global; COMPANY_ADMIN and
        # BUILDING_MANAGER are gated through the same building-scoped
        # `osius.ticket.view_building` key used by the Extra Work create
        # path.
        #
        # H-1 / H-2 hard-isolation: `osius.ticket.view_building` resolves
        # universally True for COMPANY_ADMIN (the key is not in
        # `_PROVIDER_MANAGEMENT_KEYS`), so on its own it would let a
        # company-A admin write a recurring job into company B. The
        # explicit company-membership anchor below closes that
        # cross-provider write hole — COMPANY_ADMIN must hold a
        # `CompanyUserMembership` for the building's own company.
        if user.role == UserRole.COMPANY_ADMIN:
            from companies.models import CompanyUserMembership

            in_company = CompanyUserMembership.objects.filter(
                user=user, company_id=building.company_id
            ).exists()
            if not in_company:
                raise serializers.ValidationError(
                    {
                        "building": serializers.ErrorDetail(
                            "You do not have provider-side scope to manage "
                            "planned work in this building.",
                            code="forbidden_scope",
                        )
                    }
                )
        elif user.role != UserRole.SUPER_ADMIN and not user_has_osius_permission(
            user,
            "osius.ticket.view_building",
            building_id=building.id,
        ):
            raise serializers.ValidationError(
                {
                    "building": serializers.ErrorDetail(
                        "You do not have provider-side scope to manage "
                        "planned work in this building.",
                        code="forbidden_scope",
                    )
                }
            )

        # Pricing mode: 11B ships NO hourly finalization for planned work.
        effective_pricing_mode = attrs.get(
            "pricing_mode", getattr(instance, "pricing_mode", None)
        )
        if (
            "pricing_mode" in attrs
            and attrs["pricing_mode"] == PricingMode.HOURLY
        ):
            raise serializers.ValidationError(
                {
                    "pricing_mode": serializers.ErrorDetail(
                        "Hourly planned work is not supported yet.",
                        code="pricing_mode_not_supported",
                    )
                }
            )

        # Fixed-price jobs require a fixed_price.
        effective_fixed_price = attrs.get(
            "fixed_price", getattr(instance, "fixed_price", None)
        )
        if (
            effective_pricing_mode == PricingMode.FIXED
            and effective_fixed_price is None
        ):
            raise serializers.ValidationError(
                {
                    "fixed_price": serializers.ErrorDetail(
                        "Fixed-price jobs require a fixed_price.",
                        code="fixed_price_required",
                    )
                }
            )

        # end_date (when provided) must not precede start_date.
        effective_start_date = attrs.get(
            "start_date", getattr(instance, "start_date", None)
        )
        end_date = attrs.get("end_date", getattr(instance, "end_date", None))
        if (
            end_date is not None
            and effective_start_date is not None
            and end_date < effective_start_date
        ):
            raise serializers.ValidationError(
                {
                    "end_date": serializers.ErrorDetail(
                        "end_date must be on or after start_date.",
                        code="end_before_start",
                    )
                }
            )

        # Default staff eligibility: each id must be an existing STAFF
        # user with a BuildingStaffVisibility row for this building.
        for staff_id in attrs.get("default_staff_ids", []) or []:
            if (
                not _user_role_is(staff_id, UserRole.STAFF)
                or not BuildingStaffVisibility.objects.filter(
                    user_id=staff_id, building=building
                ).exists()
            ):
                raise serializers.ValidationError(
                    {
                        "default_staff_ids": serializers.ErrorDetail(
                            "Each default staff member must be a STAFF "
                            "user with visibility on this building.",
                            code="staff_not_eligible",
                        )
                    }
                )

        # Default manager eligibility: each id must be an existing
        # BUILDING_MANAGER with a BuildingManagerAssignment for this
        # building.
        for manager_id in attrs.get("default_manager_ids", []) or []:
            if (
                not _user_role_is(manager_id, UserRole.BUILDING_MANAGER)
                or not BuildingManagerAssignment.objects.filter(
                    user_id=manager_id, building=building
                ).exists()
            ):
                raise serializers.ValidationError(
                    {
                        "default_manager_ids": serializers.ErrorDetail(
                            "Each default manager must be a BUILDING_MANAGER "
                            "assigned to this building.",
                            code="manager_not_eligible",
                        )
                    }
                )

        return attrs

    def create(self, validated_data):
        staff_ids = validated_data.pop("default_staff_ids", None)
        manager_ids = validated_data.pop("default_manager_ids", None)

        building = validated_data["building"]
        validated_data["company"] = building.company
        validated_data["created_by"] = self.context["request"].user

        job = super().create(validated_data)

        for staff_id in staff_ids or []:
            RecurringJobDefaultStaff.objects.create(
                recurring_job=job, user_id=staff_id
            )
        for manager_id in manager_ids or []:
            RecurringJobDefaultManager.objects.create(
                recurring_job=job, user_id=manager_id
            )
        return job

    def update(self, instance, validated_data):
        # A key being PRESENT means "replace this crew set" — including
        # an empty list, which clears it. A key being ABSENT leaves the
        # existing crew rows untouched.
        replace_staff = "default_staff_ids" in validated_data
        replace_managers = "default_manager_ids" in validated_data
        staff_ids = validated_data.pop("default_staff_ids", None)
        manager_ids = validated_data.pop("default_manager_ids", None)

        instance = super().update(instance, validated_data)

        # H-1/H-2: `company` is a denormalized copy of building.company and
        # is NOT on the wire (not in Meta.fields). `building` IS writable,
        # so a PATCH that moves the job to another building (hence another
        # provider company) must re-anchor `company`; otherwise it drifts
        # stale, breaking scope (scope_recurring_jobs_for filters on
        # company_id) and stamping cross-tenant spawned tickets. validate()
        # already guarantees building.company_id == customer.company_id.
        if instance.company_id != instance.building.company_id:
            instance.company = instance.building.company
            instance.save(update_fields=["company", "updated_at"])

        if replace_staff:
            instance.default_staff.all().delete()
            for staff_id in staff_ids or []:
                RecurringJobDefaultStaff.objects.create(
                    recurring_job=instance, user_id=staff_id
                )
        if replace_managers:
            instance.default_managers.all().delete()
            for manager_id in manager_ids or []:
                RecurringJobDefaultManager.objects.create(
                    recurring_job=instance, user_id=manager_id
                )
        return instance


# ---------------------------------------------------------------------------
# PlannedOccurrence — read-only
# ---------------------------------------------------------------------------
class PlannedOccurrenceSerializer(serializers.ModelSerializer):
    recurring_job_title = serializers.CharField(
        source="recurring_job.title", read_only=True
    )
    building_name = serializers.CharField(
        source="building.name", read_only=True
    )
    customer_name = serializers.CharField(
        source="customer.name", read_only=True
    )
    ticket_id = serializers.SerializerMethodField()
    # Sprint 12 — per-occurrence billable amounts derived from the
    # snapshotted price fields. Null unless the occurrence is FIXED-priced
    # with a fixed_price set (CONTRACT_INCLUDED / HOURLY carry no separate
    # per-occurrence billing). `fixed_price` is VAT-exclusive.
    subtotal_ex_vat = serializers.SerializerMethodField()
    vat_amount = serializers.SerializerMethodField()
    total_inc_vat = serializers.SerializerMethodField()

    class Meta:
        model = PlannedOccurrence
        fields = [
            "id",
            "recurring_job",
            "recurring_job_title",
            "company",
            "building",
            "customer",
            "building_name",
            "customer_name",
            "planned_date",
            "actual_date",
            "status",
            "ticket_id",
            # Sprint 12 — per-occurrence pricing + schedule snapshot.
            "pricing_mode",
            "fixed_price",
            "vat_pct",
            "preferred_start_time",
            "time_window_label",
            "subtotal_ex_vat",
            "vat_amount",
            "total_inc_vat",
            "completed_at",
            "missed_at",
            "cancelled_at",
            "skipped_at",
            "generated_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_ticket_id(self, obj):
        # The occurrence<->ticket link is a OneToOne declared on the
        # Ticket side (reverse accessor `obj.ticket`). Resolve via a
        # filter so a missing link is a clean None rather than a
        # RelatedObjectDoesNotExist.
        return (
            Ticket.objects.filter(planned_occurrence=obj)
            .values_list("id", flat=True)
            .first()
        )

    def _amounts(self, obj):
        """(subtotal, vat, total) as quantized Decimals, or three Nones
        when the occurrence is not separately billable."""
        if obj.pricing_mode != PricingMode.FIXED or obj.fixed_price is None:
            return None, None, None
        subtotal = _two_places(obj.fixed_price)
        vat = _two_places(obj.fixed_price * obj.vat_pct / Decimal("100"))
        total = _two_places(subtotal + vat)
        return subtotal, vat, total

    def get_subtotal_ex_vat(self, obj):
        subtotal, _, _ = self._amounts(obj)
        return str(subtotal) if subtotal is not None else None

    def get_vat_amount(self, obj):
        _, vat, _ = self._amounts(obj)
        return str(vat) if vat is not None else None

    def get_total_inc_vat(self, obj):
        _, _, total = self._amounts(obj)
        return str(total) if total is not None else None


# ---------------------------------------------------------------------------
# PlannedOccurrence — override (provider manager per-occurrence price /
# schedule-window override). Identity / status / date fields are NOT
# writable here; only the snapshotted pricing + window fields.
# ---------------------------------------------------------------------------
class PlannedOccurrenceOverrideSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlannedOccurrence
        fields = [
            "pricing_mode",
            "fixed_price",
            "vat_pct",
            "preferred_start_time",
            "time_window_label",
        ]

    def validate(self, attrs):
        instance = self.instance
        effective_mode = attrs.get(
            "pricing_mode", getattr(instance, "pricing_mode", None)
        )

        # 11B/12: planned work ships NO hourly finalization.
        if (
            "pricing_mode" in attrs
            and attrs["pricing_mode"] == PricingMode.HOURLY
        ):
            raise serializers.ValidationError(
                {
                    "pricing_mode": serializers.ErrorDetail(
                        "Hourly planned work is not supported yet.",
                        code="pricing_mode_not_supported",
                    )
                }
            )

        effective_fixed_price = attrs.get(
            "fixed_price", getattr(instance, "fixed_price", None)
        )
        if (
            effective_mode == PricingMode.FIXED
            and effective_fixed_price is None
        ):
            raise serializers.ValidationError(
                {
                    "fixed_price": serializers.ErrorDetail(
                        "Fixed-price occurrences require a fixed_price.",
                        code="fixed_price_required",
                    )
                }
            )
        return attrs


# ---------------------------------------------------------------------------
# Occurrence skip / cancel action body
# ---------------------------------------------------------------------------
class OccurrenceActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, allow_blank=False)
