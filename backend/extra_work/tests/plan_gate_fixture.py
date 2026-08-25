"""W-PLAN test fixture — make an EW pass the pricing plan gate.

THE LAW (owner): planning gates pricing. The gate
(`planning.check_pricing_plan_gate`) binds at the three pricing doors,
so every test that opens pricing through the API needs a plan first:
>=1 WORKER, >=1 MANAGER, a committed start date, planned hours > 0.

ONE helper, called by every module that hits a pricing door, so "what
is the minimum lawful plan" has one answer in the test suite. It works
at the ORM layer on purpose — these modules are testing PRICING, not
planning, and walking each of them through the plan API would couple
every pricing test to the planning surface.

`ew.created_by` wears both hats: a person may be BOTH worker and
manager on one request (the model docstring says so), and every EW has
a creator, so no module needs to invent users it does not have.
"""
from decimal import Decimal

from django.utils import timezone

from extra_work.models import ExtraWorkAssignment, ExtraWorkAssignmentRole


def make_plan_complete(ew, *, worker=None, manager=None):
    """Satisfy the four W-PLAN requirements minimally. Idempotent."""
    worker = worker or ew.created_by
    manager = manager or ew.created_by
    ExtraWorkAssignment.objects.get_or_create(
        extra_work_request=ew,
        user=worker,
        role=ExtraWorkAssignmentRole.WORKER,
        defaults={"assigned_by": worker},
    )
    ExtraWorkAssignment.objects.get_or_create(
        extra_work_request=ew,
        user=manager,
        role=ExtraWorkAssignmentRole.MANAGER,
        defaults={"assigned_by": manager},
    )
    update = []
    if ew.provider_planned_date is None:
        ew.provider_planned_date = timezone.localdate()
        update.append("provider_planned_date")
    if not ew.budget_hours or ew.budget_hours <= 0:
        ew.budget_hours = Decimal("1.00")
        update.append("budget_hours")
    if update:
        ew.save(update_fields=update + ["updated_at"])
    return ew
