from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerUserMembership

from .invitations import (
    Invitation,
    InvitationStatus,
    generate_invitation_token,
    hash_invitation_token,
)
from .models import User, UserRole
from .scoping import (
    building_ids_for,
    company_ids_for,
    customer_ids_for,
)
from .serializers import normalize_email


def _user_active_qs():
    return User.objects.filter(is_active=True, deleted_at__isnull=True)


class InvitationCreateSerializer(serializers.ModelSerializer):
    company_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False, default=list
    )
    building_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False, default=list
    )
    customer_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False, default=list
    )

    class Meta:
        model = Invitation
        fields = [
            "id",
            "email",
            "full_name",
            "role",
            "company_ids",
            "building_ids",
            "customer_ids",
            "created_at",
            "expires_at",
        ]
        read_only_fields = ["id", "created_at", "expires_at"]

    def validate_email(self, value):
        return normalize_email(value)

    def validate_role(self, value):
        if value not in UserRole.values:
            raise serializers.ValidationError("Unknown role.")
        return value

    def validate(self, attrs):
        request = self.context["request"]
        actor = request.user

        # Defense in depth: only SUPER_ADMIN and COMPANY_ADMIN can invite.
        # The view's permission class is the primary gate; this also rejects
        # any other role that somehow reaches here.
        if actor.role not in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN):
            raise serializers.ValidationError("You cannot create invitations.")

        email = attrs["email"]
        role = attrs["role"]
        company_ids = list(attrs.get("company_ids") or [])
        building_ids = list(attrs.get("building_ids") or [])
        customer_ids = list(attrs.get("customer_ids") or [])

        # Reject if an active User with this email already exists.
        if _user_active_qs().filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                {"email": "An active user with this email already exists."}
            )

        # Privilege escalation guard: only SUPER_ADMIN can invite SUPER_ADMIN.
        if role == UserRole.SUPER_ADMIN and actor.role != UserRole.SUPER_ADMIN:
            raise serializers.ValidationError(
                {"role": "Only a super admin can invite a super admin."}
            )

        # Role + scope shape:
        if role == UserRole.SUPER_ADMIN:
            if company_ids or building_ids or customer_ids:
                raise serializers.ValidationError(
                    "SUPER_ADMIN invitations must not specify company/building/customer scope."
                )
        elif role == UserRole.COMPANY_ADMIN:
            if len(company_ids) != 1:
                raise serializers.ValidationError(
                    {"company_ids": "COMPANY_ADMIN invitations must specify exactly one company."}
                )
            if building_ids or customer_ids:
                raise serializers.ValidationError(
                    "COMPANY_ADMIN invitations only carry a company scope."
                )
        elif role == UserRole.BUILDING_MANAGER:
            if not building_ids:
                raise serializers.ValidationError(
                    {"building_ids": "BUILDING_MANAGER invitations must specify at least one building."}
                )
            if company_ids or customer_ids:
                raise serializers.ValidationError(
                    "BUILDING_MANAGER invitations only carry a building scope."
                )
        elif role == UserRole.CUSTOMER_USER:
            if not customer_ids:
                raise serializers.ValidationError(
                    {"customer_ids": "CUSTOMER_USER invitations must specify at least one customer."}
                )
            if company_ids or building_ids:
                raise serializers.ValidationError(
                    "CUSTOMER_USER invitations only carry a customer scope."
                )

        # Resolve and authorize against actor scope.
        companies = list(Company.objects.filter(id__in=company_ids)) if company_ids else []
        buildings = list(Building.objects.filter(id__in=building_ids)) if building_ids else []
        customers = list(Customer.objects.filter(id__in=customer_ids)) if customer_ids else []

        if len(companies) != len(set(company_ids)):
            raise serializers.ValidationError({"company_ids": "Unknown company id."})
        if len(buildings) != len(set(building_ids)):
            raise serializers.ValidationError({"building_ids": "Unknown building id."})
        if len(customers) != len(set(customer_ids)):
            raise serializers.ValidationError({"customer_ids": "Unknown customer id."})

        if actor.role == UserRole.COMPANY_ADMIN:
            actor_company_ids = set(company_ids_for(actor))
            actor_building_ids = set(building_ids_for(actor))
            actor_customer_ids = set(customer_ids_for(actor))

            for c in companies:
                if c.id not in actor_company_ids:
                    raise serializers.ValidationError(
                        {"company_ids": "You can only invite into your own company."}
                    )
            for b in buildings:
                if b.id not in actor_building_ids:
                    raise serializers.ValidationError(
                        {"building_ids": "Building is outside your company scope."}
                    )
            for c in customers:
                if c.id not in actor_customer_ids:
                    raise serializers.ValidationError(
                        {"customer_ids": "Customer is outside your company scope."}
                    )

        attrs["_companies"] = companies
        attrs["_buildings"] = buildings
        attrs["_customers"] = customers
        return attrs

    def save_with_token(self):
        """
        Creates the invitation, attaches scope, and returns (invitation, raw_token).

        Auto-revokes any prior PENDING invitation for the same email so a stale
        link cannot accidentally be used after a re-invite. Wrapped in
        transaction.atomic so the auto-revoke and the new row land together.
        """
        request = self.context["request"]
        actor = request.user
        validated = self.validated_data

        raw_token, token_hash = generate_invitation_token()
        companies = validated.pop("_companies", [])
        buildings = validated.pop("_buildings", [])
        customers = validated.pop("_customers", [])
        validated.pop("company_ids", None)
        validated.pop("building_ids", None)
        validated.pop("customer_ids", None)

        with transaction.atomic():
            now = timezone.now()
            stale_qs = Invitation.objects.filter(
                email__iexact=validated["email"],
                accepted_at__isnull=True,
                revoked_at__isnull=True,
                expires_at__gt=now,
            )
            stale_qs.update(revoked_at=now, revoked_by=actor)

            invitation = Invitation.objects.create(
                created_by=actor,
                token_hash=token_hash,
                **validated,
            )
            if companies:
                invitation.companies.set(companies)
            if buildings:
                invitation.buildings.set(buildings)
            if customers:
                invitation.customers.set(customers)

        self.instance = invitation
        return invitation, raw_token


class InvitationListSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)

    class Meta:
        model = Invitation
        fields = [
            "id",
            "email",
            "full_name",
            "role",
            "status",
            "created_at",
            "expires_at",
            "created_by_email",
            "accepted_at",
            "revoked_at",
        ]
        read_only_fields = fields


class InvitationPreviewSerializer(serializers.ModelSerializer):
    inviter_email = serializers.CharField(source="created_by.email", read_only=True)
    inviter_full_name = serializers.CharField(source="created_by.full_name", read_only=True)
    company_names = serializers.SerializerMethodField()
    building_names = serializers.SerializerMethodField()
    customer_names = serializers.SerializerMethodField()

    class Meta:
        model = Invitation
        fields = [
            "email",
            "full_name",
            "role",
            "inviter_email",
            "inviter_full_name",
            "company_names",
            "building_names",
            "customer_names",
            "expires_at",
        ]
        read_only_fields = fields

    def get_company_names(self, obj):
        return list(obj.companies.values_list("name", flat=True))

    def get_building_names(self, obj):
        return list(obj.buildings.values_list("name", flat=True))

    def get_customer_names(self, obj):
        return list(obj.customers.values_list("name", flat=True))


class InvitationAcceptSerializer(serializers.Serializer):
    token = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    default_error_messages = {
        "invalid_token": "Invitation token is invalid or expired.",
    }

    def validate(self, attrs):
        token = attrs["token"]
        token_hash = hash_invitation_token(token)
        try:
            invitation = (
                Invitation.objects.select_for_update()
                .select_related("created_by")
                .get(token_hash=token_hash)
            )
        except Invitation.DoesNotExist:
            raise serializers.ValidationError(
                {"token": self.error_messages["invalid_token"]}
            )

        if invitation.status != InvitationStatus.PENDING:
            raise serializers.ValidationError(
                {"token": "Invitation is no longer valid.", "status": invitation.status},
                code="gone",
            )

        # Race-safe inside the locked transaction: re-check user existence.
        if _user_active_qs().filter(email__iexact=invitation.email).exists():
            raise serializers.ValidationError(
                {"email": "An active user with this email already exists."}
            )

        try:
            password_validation.validate_password(attrs["new_password"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)})

        attrs["invitation"] = invitation
        return attrs

    def save(self, **kwargs):
        invitation: Invitation = self.validated_data["invitation"]
        new_password: str = self.validated_data["new_password"]

        user = User.objects.create_user(
            email=invitation.email,
            password=new_password,
            full_name=invitation.full_name,
            role=invitation.role,
        )

        if invitation.role == UserRole.COMPANY_ADMIN:
            for company in invitation.companies.all():
                CompanyUserMembership.objects.get_or_create(user=user, company=company)
        elif invitation.role == UserRole.BUILDING_MANAGER:
            for building in invitation.buildings.all():
                BuildingManagerAssignment.objects.get_or_create(user=user, building=building)
        elif invitation.role == UserRole.CUSTOMER_USER:
            for customer in invitation.customers.all():
                CustomerUserMembership.objects.get_or_create(user=user, customer=customer)
        # SUPER_ADMIN: no scope rows; the role itself is global.

        now = timezone.now()
        invitation.accepted_at = now
        invitation.accepted_by = user
        invitation.save(update_fields=["accepted_at", "accepted_by"])
        return user
