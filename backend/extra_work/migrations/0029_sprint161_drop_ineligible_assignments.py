# Sprint 161 §6 — remove the assignment rows that predate eligibility.
#
# Before Sprint 158 any provider role could be assigned as any role, so
# `ExtraWorkAssignment` still holds rows that the current rule would
# refuse — crmtest has STAFF users stored as MANAGER on requests 68 and
# 69. Sprint 158 closed the door; this closes the rows already inside.
#
# `buildings.assignment_eligibility` is the AUTHORITY, imported rather
# than restated. A migration that reimplemented the rule would be a
# second copy of it, and the copy is what drifts — the same reasoning
# CLAUDE.md gives for the render-order array.
#
# Two properties this deliberately has:
#
#   * It removes ONLY rows whose user fails eligibility for the role
#     they hold, evaluated against the REQUEST'S OWN BUILDING. A row
#     that is still legitimate is never touched.
#   * It LOGS every removal with the request, the user and the role,
#     because a silent delete of somebody's assignment is exactly the
#     kind of change that surfaces weeks later as "who took me off
#     this".
#
# Not reversible in the meaningful sense: the reverse is a no-op, and it
# says so. Re-creating rows the current rule forbids is not something a
# rollback should do, and pretending otherwise would be worse than
# admitting it.

import logging

from django.db import migrations


logger = logging.getLogger(__name__)


def drop_ineligible_assignments(apps, schema_editor):
    # The eligibility helper reads the REAL models (it needs the User
    # manager and the related querysets), which is safe here because it
    # is pure read logic with no migration-state dependency of its own.
    from buildings.assignment_eligibility import (
        ROLE_MANAGER,
        ROLE_WORKER,
        eligible_users_for_building,
    )
    from buildings.models import Building

    ExtraWorkAssignment = apps.get_model("extra_work", "ExtraWorkAssignment")

    rows = list(
        ExtraWorkAssignment.objects.select_related(
            "extra_work_request"
        ).all()
    )

    # One eligibility query per (building, role) pair rather than per
    # row: the answer is the same for every row sharing them, and a
    # migration that fans out per row is the one that times out on a
    # real database.
    cache: dict = {}
    doomed = []
    for row in rows:
        building_id = getattr(row.extra_work_request, "building_id", None)
        if building_id is None:
            # Unreachable today — `ExtraWorkRequest.building` is NOT
            # NULL, which a test proved by failing to construct the
            # case. Kept as belt and braces rather than deleted: if that
            # column is ever loosened, the right behaviour is to leave
            # the row alone, because this migration removes rows it can
            # PROVE are wrong and never rows it merely cannot judge.
            continue
        role = ROLE_MANAGER if row.role == "MANAGER" else ROLE_WORKER
        key = (building_id, role)
        if key not in cache:
            building = Building.objects.filter(pk=building_id).first()
            cache[key] = (
                set(
                    eligible_users_for_building(
                        building, role, actor=None
                    ).values_list("id", flat=True)
                )
                if building is not None
                else None
            )
        eligible_ids = cache[key]
        if eligible_ids is None:
            continue
        if row.user_id not in eligible_ids:
            doomed.append(row)

    for row in doomed:
        logger.warning(
            "Sprint 161 §6: removing ineligible ExtraWorkAssignment "
            "#%s - user #%s held %s on request #%s (building #%s)",
            row.pk,
            row.user_id,
            row.role,
            row.extra_work_request_id,
            getattr(row.extra_work_request, "building_id", None),
        )
    if doomed:
        ExtraWorkAssignment.objects.filter(
            pk__in=[row.pk for row in doomed]
        ).delete()
    logger.warning(
        "Sprint 161 §6: examined %s assignment rows, removed %s",
        len(rows),
        len(doomed),
    )


def noop_reverse(apps, schema_editor):
    """Deliberately does nothing.

    Rolling this back cannot mean "put the ineligible rows back": the
    current rule forbids them, and re-creating them would leave the
    database in a state the application refuses to produce.
    """
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("extra_work", "0028_sprint157_extra_work_assignment"),
        ("buildings", "0005_buildingmanagerassignment_permission_overrides"),
    ]

    operations = [
        migrations.RunPython(drop_ineligible_assignments, noop_reverse),
    ]
