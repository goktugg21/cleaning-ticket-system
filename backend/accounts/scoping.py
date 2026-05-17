from django.db import models
from django.db.models import Exists, OuterRef

from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from tickets.models import Ticket

from .models import UserRole


def _is_anonymous(user):
    return user is None or not getattr(user, "is_authenticated", False)


def company_ids_for(user):
    if _is_anonymous(user):
        return Company.objects.none().values_list("id", flat=True)

    if user.role == UserRole.SUPER_ADMIN:
        return Company.objects.values_list("id", flat=True)

    if user.role == UserRole.COMPANY_ADMIN:
        return CompanyUserMembership.objects.filter(user=user).values_list("company_id", flat=True)

    if user.role == UserRole.BUILDING_MANAGER:
        return BuildingManagerAssignment.objects.filter(user=user).values_list("building__company_id", flat=True)

    if user.role == UserRole.CUSTOMER_USER:
        return CustomerUserMembership.objects.filter(user=user).values_list("customer__company_id", flat=True)

    return Company.objects.none().values_list("id", flat=True)


def building_ids_for(user):
    if _is_anonymous(user):
        return Building.objects.none().values_list("id", flat=True)

    if user.role == UserRole.SUPER_ADMIN:
        return Building.objects.values_list("id", flat=True)

    if user.role == UserRole.COMPANY_ADMIN:
        company_ids = CompanyUserMembership.objects.filter(user=user).values_list("company_id", flat=True)
        return Building.objects.filter(company_id__in=company_ids).values_list("id", flat=True)

    if user.role == UserRole.BUILDING_MANAGER:
        return BuildingManagerAssignment.objects.filter(user=user).values_list("building_id", flat=True)

    if user.role == UserRole.STAFF:
        # Sprint 23A: a STAFF user sees a building if they hold a
        # BuildingStaffVisibility row for it. Per-ticket visibility
        # via TicketStaffAssignment is enforced inside
        # scope_tickets_for, but the BUILDING list intentionally
        # stays narrower (the ticket might be in a building the
        # staff has no read-access for outside that assignment).
        #
        # Sprint 28 Batch 10 — intentional asymmetry: this helper
        # returns every BSV building_id regardless of the new
        # `visibility_level` field. An ASSIGNED_ONLY row still surfaces
        # the building in building dropdowns / selectors so the STAFF
        # user can see "I operate here" — they just don't see other
        # people's tickets at that building (that narrowing lives in
        # `scope_tickets_for`).
        from buildings.models import BuildingStaffVisibility

        return BuildingStaffVisibility.objects.filter(user=user).values_list(
            "building_id", flat=True
        )

    if user.role == UserRole.CUSTOMER_USER:
        # Sprint 14: a customer-user only sees buildings explicitly granted
        # via CustomerUserBuildingAccess, never the customer's legacy
        # `building` FK. A customer-user with a CustomerUserMembership but
        # zero access rows sees zero buildings.
        #
        # Sprint 23A: only active access rows count.
        return CustomerUserBuildingAccess.objects.filter(
            membership__user=user, is_active=True
        ).values_list("building_id", flat=True)

    return Building.objects.none().values_list("id", flat=True)


def customer_ids_for(user):
    if _is_anonymous(user):
        return Customer.objects.none().values_list("id", flat=True)

    if user.role == UserRole.SUPER_ADMIN:
        return Customer.objects.values_list("id", flat=True)

    if user.role == UserRole.COMPANY_ADMIN:
        company_ids = CompanyUserMembership.objects.filter(user=user).values_list("company_id", flat=True)
        return Customer.objects.filter(company_id__in=company_ids).values_list("id", flat=True)

    if user.role == UserRole.BUILDING_MANAGER:
        # Sprint 14: a building manager sees a customer if any of the
        # customer's M:N building links is one of the manager's assigned
        # buildings. We OR with the legacy single-building anchor so a
        # customer that has not yet been re-linked through the new admin
        # UI still appears for managers (the backfill covers existing
        # rows; this is defence in depth).
        building_ids = list(
            BuildingManagerAssignment.objects.filter(user=user).values_list(
                "building_id", flat=True
            )
        )
        via_membership = CustomerBuildingMembership.objects.filter(
            building_id__in=building_ids
        ).values_list("customer_id", flat=True)
        via_legacy = Customer.objects.filter(
            building_id__in=building_ids
        ).values_list("id", flat=True)
        return Customer.objects.filter(
            id__in=list(via_membership) + list(via_legacy)
        ).values_list("id", flat=True)

    if user.role == UserRole.CUSTOMER_USER:
        return CustomerUserMembership.objects.filter(user=user).values_list("customer_id", flat=True)

    return Customer.objects.none().values_list("id", flat=True)


def scope_companies_for(user):
    if _is_anonymous(user):
        return Company.objects.none()
    if user.role == UserRole.SUPER_ADMIN:
        return Company.objects.all()
    # Non-super-admin reads are limited to active tenants. Super admins still
    # see archived rows so they can re-activate or audit them.
    return Company.objects.filter(
        id__in=list(company_ids_for(user)),
        is_active=True,
    ).distinct()


def scope_buildings_for(user):
    if _is_anonymous(user):
        return Building.objects.none()
    if user.role == UserRole.SUPER_ADMIN:
        return Building.objects.all()
    return Building.objects.filter(
        id__in=list(building_ids_for(user)),
        is_active=True,
    ).distinct()


def scope_customers_for(user):
    if _is_anonymous(user):
        return Customer.objects.none()
    if user.role == UserRole.SUPER_ADMIN:
        return Customer.objects.all()
    return Customer.objects.filter(
        id__in=list(customer_ids_for(user)),
        is_active=True,
    ).distinct()


def scope_tickets_for(user):
    """
    Return the queryset of tickets visible to `user`.

    Sprint 12: every code path filters `deleted_at__isnull=True`. A
    soft-deleted ticket disappears from list, detail, search, messages,
    attachments, stats, and reports for every role.

    Sprint 14: CUSTOMER_USER scoping is now the *intersection* of
    customer membership and per-building access. A user with
    CustomerUserMembership(customer=X) and CustomerUserBuildingAccess
    rows pointing at buildings B1, B3 sees tickets only where
    `(ticket.customer, ticket.building) == (X, B1)` or `(X, B3)` —
    not `(X, B2)`, even though B2 might be linked to customer X via
    CustomerBuildingMembership for some other user. The pair-check is
    enforced by an Exists subquery so a multi-customer user with
    different building access per customer cannot accidentally see a
    ticket whose pair isn't theirs.

    Sprint 23A — two changes on top of the Sprint 14 behaviour:

      1. The CUSTOMER_USER branch now also unions in:
         - tickets where the user holds an active
           CustomerUserBuildingAccess row of access_role
           CUSTOMER_LOCATION_MANAGER for `(customer, building)`;
         - every ticket of the customer when the user holds at
           least one active CUSTOMER_COMPANY_ADMIN access row
           against that customer (cross-building visibility).
         All access rows with is_active=False are ignored.

      2. A new STAFF branch: returns the union of
         - tickets where the user appears in
           TicketStaffAssignment; and
         - tickets in any building where the user holds a
           BuildingStaffVisibility row.

    Customer isolation is preserved: every customer-side path
    still filters by `customer_id` membership before union-ing
    location-manager or company-admin rows, so a user under
    customer A can never see customer B's tickets even at
    CUSTOMER_COMPANY_ADMIN level.
    """
    if _is_anonymous(user):
        return Ticket.objects.none()

    if user.role == UserRole.SUPER_ADMIN:
        return Ticket.objects.filter(deleted_at__isnull=True)

    if user.role == UserRole.COMPANY_ADMIN:
        company_ids = CompanyUserMembership.objects.filter(user=user).values_list("company_id", flat=True)
        return Ticket.objects.filter(deleted_at__isnull=True, company_id__in=company_ids)

    if user.role == UserRole.BUILDING_MANAGER:
        building_ids = BuildingManagerAssignment.objects.filter(user=user).values_list("building_id", flat=True)
        return Ticket.objects.filter(deleted_at__isnull=True, building_id__in=building_ids)

    if user.role == UserRole.STAFF:
        # Sprint 23A: STAFF sees tickets they are listed on PLUS
        # tickets in buildings where they hold visibility.
        #
        # Sprint 28 Batch 10: only BSV rows with `visibility_level`
        # of BUILDING_READ or BUILDING_READ_AND_ASSIGN contribute the
        # building-wide branch. ASSIGNED_ONLY rows recognise the STAFF
        # user at the building (e.g. for direct-assignment eligibility
        # via `_validate_target_staff`) but do NOT widen ticket
        # visibility beyond their TicketStaffAssignment rows. The H-4
        # floor (STAFF always sees tickets they're assigned to) is
        # preserved by leaving the `Q(_assigned=True)` branch
        # unchanged — it has no dependency on `visibility_level`.
        from tickets.models import TicketStaffAssignment
        from buildings.models import BuildingStaffVisibility

        assignment_exists = TicketStaffAssignment.objects.filter(
            ticket_id=OuterRef("pk"), user=user
        )
        visibility_building_ids = BuildingStaffVisibility.objects.filter(
            user=user,
            visibility_level__in=(
                BuildingStaffVisibility.VisibilityLevel.BUILDING_READ,
                BuildingStaffVisibility.VisibilityLevel.BUILDING_READ_AND_ASSIGN,
            ),
        ).values_list("building_id", flat=True)
        return (
            Ticket.objects.filter(deleted_at__isnull=True)
            .annotate(_assigned=Exists(assignment_exists))
            .filter(
                models.Q(_assigned=True)
                | models.Q(building_id__in=list(visibility_building_ids))
            )
        )

    if user.role == UserRole.CUSTOMER_USER:
        # Sprint 23A (corrected before PR #50): resolve customer-side
        # visibility in Python so the `permission_overrides` JSON is
        # honoured. Each active access row resolves to one of three
        # outcomes:
        #
        #   - view_company → grants visibility on EVERY ticket of the
        #     customer, regardless of building. (CUSTOMER_COMPANY_ADMIN
        #     default, or any override granting `customer.ticket.view_company`.)
        #   - view_location → grants visibility on every ticket at the
        #     (customer, building) pair. (CUSTOMER_LOCATION_MANAGER
        #     default, or any override granting view_location.)
        #   - view_own → grants visibility on tickets at (customer,
        #     building) only when the user is `created_by`. (Plain
        #     CUSTOMER_USER default. Sprint 22 / earlier 23A leaked
        #     other-user tickets at the same pair.)
        #
        # An inactive access row resolves every key to False (handled
        # by customers.permissions.access_has_permission) so it
        # never contributes to scope.
        from customers.permissions import access_has_permission

        view_company_customers = set()  # {customer_id}
        view_location_pairs = set()  # {(customer_id, building_id)}
        view_own_pairs = set()  # {(customer_id, building_id)}
        for access in (
            CustomerUserBuildingAccess.objects.filter(
                membership__user=user, is_active=True
            )
            .select_related("membership")
            .only(
                "id",
                "access_role",
                "permission_overrides",
                "is_active",
                "building_id",
                "membership__customer_id",
            )
        ):
            cid = access.membership.customer_id
            bid = access.building_id
            if access_has_permission(access, "customer.ticket.view_company"):
                view_company_customers.add(cid)
            elif access_has_permission(access, "customer.ticket.view_location"):
                view_location_pairs.add((cid, bid))
            elif access_has_permission(access, "customer.ticket.view_own"):
                view_own_pairs.add((cid, bid))

        if not (view_company_customers or view_location_pairs or view_own_pairs):
            return Ticket.objects.none()

        q = models.Q()
        if view_company_customers:
            q |= models.Q(customer_id__in=view_company_customers)
        for cid, bid in view_location_pairs:
            q |= models.Q(customer_id=cid, building_id=bid)
        if view_own_pairs:
            own_filter = models.Q()
            for cid, bid in view_own_pairs:
                own_filter |= models.Q(customer_id=cid, building_id=bid)
            q |= own_filter & models.Q(created_by=user)

        return Ticket.objects.filter(deleted_at__isnull=True).filter(q)

    return Ticket.objects.none()


def _user_in_actor_company(actor, target_user):
    """
    True if `target_user` has any membership in any of `actor`'s companies.

    Used by CanManageUser. Encapsulates the company-overlap check so callers
    do not duplicate the union-of-three-membership-types query.

    Sprint 24A — adds BuildingStaffVisibility to the union so a STAFF
    user is in a company-admin's scope as soon as they hold visibility
    on at least one of that company's buildings. Without this, the
    new staff profile / visibility admin endpoints could not authorize
    a COMPANY_ADMIN against the company's own seeded STAFF persona
    (Ahmet for Osius, Noah for Bright), and the UserViewSet list would
    silently drop STAFF rows for non-super-admin actors.
    """
    actor_company_ids = list(
        CompanyUserMembership.objects.filter(user=actor).values_list("company_id", flat=True)
    )
    if not actor_company_ids:
        return False

    if CompanyUserMembership.objects.filter(
        user=target_user, company_id__in=actor_company_ids
    ).exists():
        return True
    if BuildingManagerAssignment.objects.filter(
        user=target_user, building__company_id__in=actor_company_ids
    ).exists():
        return True
    if CustomerUserMembership.objects.filter(
        user=target_user, customer__company_id__in=actor_company_ids
    ).exists():
        return True
    # Sprint 24A — STAFF users are in scope via BuildingStaffVisibility.
    from buildings.models import BuildingStaffVisibility

    if BuildingStaffVisibility.objects.filter(
        user=target_user, building__company_id__in=actor_company_ids
    ).exists():
        return True
    return False
