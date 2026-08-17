"""
Sprint 154 §M — enter a whole week of hours in one request.

    POST /api/timesheets/entries/bulk-week/

Ramazan works by week, not by entry: today filing a normal week means
opening a modal five to twenty times. This endpoint takes the whole grid
at once.

Body::

    {
      "employee": 12,                     # DEFAULT for cells that omit one
      "iso_year": 2026,
      "iso_week": 32,
      "company": 3,                       # optional disambiguator
      "cells": [
        {"hour_type": 4, "building": 9, "date": "2026-08-03", "hours": "8.00"},
        {"employee": 15, "hour_type": 4, "date": "2026-08-04", "hours": "6"},
        ...
      ]
    }

Response::

    {"created": N, "updated": N, "deleted": N}

Sprint 155 §5 — a cell may carry its OWN `employee`, so ONE request can
file a week for SEVERAL people. The top-level `employee` stays exactly
what it was and is now the default for cells that omit one, so every
Sprint 154 client keeps working unchanged.

That multi-employee shape is the whole point of the change: Sprint 154's
grid used the page's employee FILTER as both "whose rows am I looking
at" and "whose week am I writing", which meant an operator could not
enter two people's weeks without changing the filter in between — and
changing the filter silently changed the write target. One request per
employee would also break the all-or-nothing property below, which is
the reason this is a widening of the existing endpoint rather than a
loop in the client.

THE GRID IS THE AUTHORITY for the cells it sends, and only for those.
`hours: 0` means "this cell is empty" and DELETES any existing row for
that (employee, date, hour type, building) — that is what makes clearing
a typo possible. A cell the grid does not send is left untouched, so
this endpoint can never silently wipe a row entered through some other
surface.

Two properties this file exists to guarantee:

1. **Every row goes through the NORMAL `TimeEntrySerializer` +
   `TimeEntry.save()` path.** `multiplier_snapshot` and the derived
   `iso_year` / `iso_week` are the immutability core of this module — a
   bulk insert that bypassed `save()` would leave the snapshot null and
   silently break every weighted total, and would let a row's stored
   week contradict its date and so escape the lock that governs it.
   Reusing the serializer also means the week lock, the hour-type
   ownership check, the employee-eligibility rule and the H-1 scoped
   querysets are enforced here by construction rather than by a second
   copy that can drift.

2. **All-or-nothing.** One `transaction.atomic()` around the whole grid.
   A week that half-saved would be worse than one that did not save at
   all, because the operator would have to work out which half.

Module architecture (Sprint 152, held): `timesheets` imports nothing
from `tickets`, `extra_work` or `planned_work`, and this endpoint does
not change that.
"""
from __future__ import annotations

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import HourSource
from .permissions import (
    ERR_TIMESHEET_EMPLOYEE_FORBIDDEN,
    IsTimesheetUser,
    _enforce_timesheet_management,
)
from .scope import is_timesheet_manager
from .serializers import TimeEntrySerializer, snapshot_multiplier
from .weeks import iso_week_of, week_bounds


ERR_WEEK_GRID_DATE_OUTSIDE = "week_grid_date_outside_week"


class _WeekCellSerializer(serializers.Serializer):
    # Sprint 155 §5 — per-cell employee. Deliberately a plain IntegerField
    # and NOT a PrimaryKeyRelatedField: resolution happens inside
    # `TimeEntrySerializer`, whose `employee` queryset is scoped to
    # `eligible_employees_queryset(actor)`. Resolving it here as well
    # would be a SECOND resolution path that could drift from the scoped
    # one, and a `PrimaryKeyRelatedField` over an unscoped queryset is
    # exactly the existence oracle H-1 forbids — "this id exists but is
    # not yours" and "this id does not exist" must be the same answer.
    employee = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    hour_type = serializers.IntegerField(min_value=1)
    building = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    date = serializers.DateField()
    hours = serializers.DecimalField(max_digits=4, decimal_places=2)
    # Sprint 174 §2 — the SOURCE, set by the flow that logged the hour
    # rather than typed by the operator. Optional and validated against
    # the enum: an unrecognised value is a 400 rather than a silently
    # stored string, because a source nobody can filter on is worse
    # than no source.
    source_type = serializers.ChoiceField(
        choices=HourSource.choices, required=False, allow_blank=True
    )
    source_id = serializers.IntegerField(
        min_value=1, required=False, allow_null=True
    )


class _WeekGridInputSerializer(serializers.Serializer):
    # The DEFAULT employee for cells that do not name one. Sprint 154 sent
    # only this; Sprint 155 clients send it per cell. Both shapes work.
    employee = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    company = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    iso_year = serializers.IntegerField(min_value=1970, max_value=4000)
    iso_week = serializers.IntegerField(min_value=1, max_value=53)
    cells = serializers.ListField(child=_WeekCellSerializer(), allow_empty=False)


class TimeEntryWeekGridView(APIView):
    """POST /api/timesheets/entries/bulk-week/ — see the module docstring."""

    permission_classes = [IsTimesheetUser]

    def post(self, request, *args, **kwargs):
        payload = _WeekGridInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        iso_year = data["iso_year"]
        iso_week = data["iso_week"]
        try:
            monday, sunday = week_bounds(iso_year, iso_week)
        except ValueError:
            # e.g. week 53 of a 52-week year. Caught here so it is a 400
            # with a field, not a 500 out of the date library.
            raise serializers.ValidationError(
                {
                    "iso_week": [
                        serializers.ErrorDetail(
                            "That ISO week does not exist in that year.",
                            code=ERR_WEEK_GRID_DATE_OUTSIDE,
                        )
                    ]
                }
            )

        # A non-manager may only ever write their own hours. Checked
        # BEFORE anything else and phrased so it leaks nothing: it says
        # "not you", never whether the id names a real user. Mirrors
        # `TimeEntryListCreateView.initial`.
        #
        # Sprint 155 — the check now covers the DEFAULT employee AND
        # every per-cell one. A guard that only looked at the top-level
        # field would be trivially bypassed by putting the other
        # person's id on the cells instead, which is the whole new
        # surface this sprint opened.
        supplied_employee = data.get("employee")
        if not is_timesheet_manager(request.user):
            named = {
                cell.get("employee")
                for cell in data["cells"]
                if cell.get("employee") not in (None, "")
            }
            if supplied_employee not in (None, ""):
                named.add(supplied_employee)
            if any(str(value) != str(request.user.pk) for value in named):
                raise PermissionDenied(
                    detail={
                        "detail": "You may only record your own hours.",
                        "code": ERR_TIMESHEET_EMPLOYEE_FORBIDDEN,
                    }
                )
            supplied_employee = request.user.pk

        # Every cell's date must fall inside the week the caller named.
        # Without this a grid could file Monday's hours into last week
        # and the row would still be internally consistent — its derived
        # iso_week would just disagree with the grid the operator was
        # looking at.
        for cell in data["cells"]:
            if not (monday <= cell["date"] <= sunday):
                raise serializers.ValidationError(
                    {
                        "cells": [
                            serializers.ErrorDetail(
                                (
                                    f"Every date must fall inside week "
                                    f"{iso_year}-W{iso_week:02d} "
                                    f"({monday} to {sunday})."
                                ),
                                code=ERR_WEEK_GRID_DATE_OUTSIDE,
                            )
                        ]
                    }
                )
            # Defence in depth: the ISO week DERIVED from the date must
            # agree with the one named. The bounds check above already
            # implies it, but the two are computed independently, so a
            # future change to either cannot drift unnoticed. Not an
            # `assert` — asserts vanish under `python -O`, and this is a
            # data-integrity gate, not a debugging aid.
            if iso_week_of(cell["date"]) != (iso_year, iso_week):
                raise serializers.ValidationError(
                    {
                        "cells": [
                            serializers.ErrorDetail(
                                "A date's ISO week does not match the week "
                                "being saved.",
                                code=ERR_WEEK_GRID_DATE_OUTSIDE,
                            )
                        ]
                    }
                )

        created = updated = deleted = 0

        # ONE transaction around the whole grid. Every serializer call
        # inside it does its own full validation, so an invalid cell
        # raises and rolls the entire week back.
        with transaction.atomic():
            for cell in data["cells"]:
                # Sprint 155 — the cell's own employee wins; the top-level
                # one is the default. Both may be None, in which case the
                # serializer resolves "me", exactly as a single-entry POST
                # does.
                cell_employee = cell.get("employee") or supplied_employee
                result = self._apply_cell(request, cell, cell_employee, data)
                if result == "created":
                    created += 1
                elif result == "updated":
                    updated += 1
                elif result == "deleted":
                    deleted += 1

        return Response(
            {"created": created, "updated": updated, "deleted": deleted},
            status=status.HTTP_200_OK,
        )

    def _existing_row(self, request, cell, employee_id):
        """The row this cell addresses, if any.

        Keyed on (employee, date, hour type, building, SOURCE) — the
        grid's own coordinates. Scoped through the same base queryset the
        detail endpoint uses, so a row the caller may not touch is simply
        not found and the cell is treated as a create, which the
        serializer then refuses on its own terms.

        ## Sprint 179B §2 — why the source is part of the key

        Sprint 177 §7 taught the week wizard to seed one row per JOB, and
        the grid keys its rows on `(hour_type, building, source_type,
        source_id)` for a stated reason: hours on the stairwell repaint
        and hours on nothing in particular are two facts and must not be
        summed onto one line.

        This lookup did not key on the source, so the two sides disagreed
        about what a row IS. Pick two jobs at one building in the wizard,
        put 4 hours on each, press Save: the first cell created a row,
        the second found that row — same employee, date, hour type and
        building — and took the UPDATE branch. One `TimeEntry` survived,
        carrying 4 hours instead of 8 and the second job's source. The
        operator saw two rows go in and got one row back, silently.

        A cell that names no source addresses the UNTAGGED row: `OTHER`
        with no id, which is the column's own default and therefore what
        every row written before Sprint 173 carries. So an untagged cell
        can still update the row it always updated, and can no longer
        overwrite a job-tagged one.
        """
        from .views_entries import _base_entry_queryset

        qs = _base_entry_queryset(request.user).filter(
            date=cell["date"], hour_type_id=cell["hour_type"]
        )
        if employee_id is not None:
            qs = qs.filter(employee_id=employee_id)
        building_id = cell.get("building")
        qs = (
            qs.filter(building_id=building_id)
            if building_id is not None
            else qs.filter(building__isnull=True)
        )
        source_type = cell.get("source_type") or HourSource.OTHER
        source_id = cell.get("source_id") if cell.get("source_type") else None
        qs = qs.filter(source_type=source_type)
        qs = (
            qs.filter(source_id=source_id)
            if source_id is not None
            else qs.filter(source_id__isnull=True)
        )
        return qs.first()

    def _apply_cell(self, request, cell, employee_id, data):
        existing = self._existing_row(request, cell, employee_id)
        is_empty = cell["hours"] is None or cell["hours"] <= 0

        if is_empty:
            if existing is None:
                return "skipped"
            # A closed week refuses a deletion exactly as it refuses an
            # edit — removing an entry changes the week's totals as much
            # as changing one does. Same call the detail endpoint makes.
            from .weeks import enforce_week_open

            if is_timesheet_manager(request.user):
                _enforce_timesheet_management(request.user, existing.company)
            enforce_week_open(existing.company_id, existing.date)
            existing.delete()
            return "deleted"

        body = {
            "date": cell["date"].isoformat(),
            "hour_type": cell["hour_type"],
            "hours": str(cell["hours"]),
            "building": cell.get("building"),
        }
        if employee_id is not None:
            body["employee"] = employee_id
        # Sprint 174 §2 — the source travels with the cell. Set by the
        # flow that logged the hour, never typed twice by the operator.
        if cell.get("source_type"):
            body["source_type"] = cell["source_type"]
            body["source_id"] = cell.get("source_id")
        if data.get("company") is not None and existing is None:
            # `company` is a disambiguator on create only; the serializer
            # makes it read-only once an instance exists, because the
            # tenant anchor never moves after create.
            body["company"] = data["company"]

        serializer = TimeEntrySerializer(
            instance=existing, data=body, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        employee = serializer.validated_data.get("employee") or request.user
        company = serializer.validated_data.get("company") or (
            existing.company if existing is not None else None
        )
        if is_timesheet_manager(request.user) and company is not None:
            _enforce_timesheet_management(request.user, company)
        hour_type = serializer.validated_data.get("hour_type") or (
            existing.hour_type if existing is not None else None
        )

        save_kwargs = {
            "employee": employee,
            # Re-snapshot on every write, create or update — the rule is
            # "the snapshot reflects the type at write time", and a rule
            # with an exception is one somebody forgets.
            "multiplier_snapshot": snapshot_multiplier(hour_type),
        }
        if existing is None:
            save_kwargs["company"] = company
            save_kwargs["created_by"] = request.user

        serializer.save(**save_kwargs)
        return "updated" if existing is not None else "created"
