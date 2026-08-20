"""W2-D / W4-O — plan many Extra Works in one call.

    GET  /api/extra-work/bulk-plan/?requests=1,2,3   what they say now
    POST /api/extra-work/bulk-plan/                  write, all or nothing

A crew agreed for the same week is the normal case, not an edge one: an
operator staffs six jobs off one phone call, and typing the same budget
and the same window six times is how one of them ends up different by
accident.

W4-O — ONE CALL, ONE SET OF VALUES PER WORK
-------------------------------------------
The first version of this endpoint took ONE plan payload and copied it
onto every id. That is the right shape for "same window, same budget,
six jobs" and the wrong shape for everything else: work A could not be
given four hours while work B got six, and PLANNED HOURS PER PERSON were
unusable in bulk at all — they validate against the crew of EACH work,
so one shared distribution was only ever valid when the identical crew
was on every selected job, and offering the field would have produced a
400 that reads as a broken dialog.

**One endpoint, one meaning, two ways to say it.** The body may be
either of these and NEVER a mixture:

    {"requests": [258, 257], "budget_hours": "4", ...}        (shared)
    {"items": [{"request": 258, "budget_hours": "4", ...},    (per work)
               {"request": 257, "budget_hours": "6",
                "planned_hours": [{"user": 9, "hours": "6"}]}]}

The shared form is not a second endpoint and not a second code path: it
is NORMALISED, at the door, into exactly the per-work list it is
shorthand for — the same work repeated. `_normalise` below is the only
place that knows the difference, and everything after it sees one list
of `(id, payload)` pairs. There is therefore no way for the two shapes
to disagree about what a field means, which was the condition on
keeping the old one alive at all.

Why keep it alive rather than migrate. Two reasons, and the second is
the one that decided it. (1) `bulk-dates` and `bulk-assign` next door
both take `{"requests": [...], ...shared}`; deleting that spelling here
would make this the one bulk endpoint in the family with its own
dialect. (2) A caller that means "same window on all six" should be able
to say so once — repeating an identical block six times is a shape that
invites the fifth copy to be different by accident, which is the exact
data-entry failure this endpoint was built against.

MIXING IS REFUSED, LOUDLY. `items` together with any shared plan field
would need a precedence rule ("does the row's budget beat the shared
one?"), and a precedence rule is a thing an operator has to learn and a
thing a client can get wrong silently. There is no such rule here:
sending both is a 400 with its own code. The dialog fills every row
instead — see `BulkPlanDialog.tsx`, where "apply to all" writes the
value INTO each row rather than sending a shared field.

THE ONE THING THIS ENDPOINT EXISTS TO GET RIGHT
-----------------------------------------------
**Bulk plan carries the completion flags, and carries them by PRESENCE.**

In the reference system neither flag survives a plan write at all: the
plan modal sends `upload_is_required` and `notes_is_required`, the
config-driven update persists only the fields in its own allow-list,
neither is in it, and both are silently discarded — 0 of 78 live records
has either set to true
(`docs/reference/osius-reference-system/01-extra-work.md` §1.6, §3.6).
The gap-closing brief states the same failure from the operator's side,
as "bulk plan writes both to false on every selected work". The
mechanism differs; the consequence is the same, and it is the one to
avoid: a plan path that accepts a flag, does not carry it, and says
nothing.

We cannot have that bug, because there is only one plan payload
(`ExtraWorkPlanSerializer`) and one writer (`planning.apply_plan`), and
both read every field — the booleans included — by KEY PRESENCE:

    absent   -> left exactly as it was on that work
    present  -> written to that work

Per-work rows do not weaken this; they sharpen it. A row is a payload
like any other, so a row that mentions only `budget_hours` cannot touch
that work's flags, and a row that mentions neither flag while its
neighbour sets both is a perfectly ordinary batch.
`test_w2d_bulk_plan.py` and `test_w4o_bulk_plan_per_work.py` pin both.

THE THREE PROPERTIES BORROWED FROM THE BULK FAMILY NEXT DOOR
------------------------------------------------------------
Deliberately the same as `views_dates.py` / `views_assignments.py`,
because a caller should not have to learn a third dialect:

1. **All-or-nothing.** Every id is resolved through the caller's own
   `scope_extra_work_for` BEFORE any write, and one unresolvable id
   rejects the whole batch with zero writes. A partial bulk plan is
   worse than a failed one — the operator cannot see which half landed.
   Per-work values do not change this: the twelve rows are still one
   transaction, and an invalid ninth row rolls back the eight before it.
2. **An out-of-scope id is refused with the SAME body as one that does
   not exist.** A distinguishable answer would let a caller enumerate
   which extra work exists in other tenants (H-1).
3. **Provider-only, at the door.** `scope_extra_work_for` would already
   narrow what a customer-side user can see, but planning is a provider
   action end to end and the refusal belongs at the door rather than
   emerging from an empty resolution.

Property (2) is why an invalid PERSON is reported differently from an
invalid WORK, and the line between them is worth stating. A work id that
does not resolve gets the constant body: the caller has not proved it
may see that work, so anything specific is an oracle. A person named on
a work that DID resolve gets a body naming the row and echoing the id
the caller sent: the caller has already proved it may see that work, the
body carries nothing the request did not, and the three causes (not
assigned / not visible / not real) still read identically. See
`planning.PLANNED_HOURS_INVALID_IN_BATCH_MESSAGE`.

WHAT THE GET IS FOR
-------------------
A per-work table has to be SEEDED, or every row opens blank and saving
looks like it wiped what was there. The list payload carries none of the
planning fields (they are provider-only detail fields) and none of the
crew, so the dialog would otherwise need one detail fetch per selected
work. `GET` answers the whole selection in two queries: what each work
plans now, and who is on it.

It is the same view, the same door and the same scope resolution as the
POST, on purpose — a read that could see a work the write could not
touch would be a second, weaker gate on the same data.

WHAT IS REPORTED BACK
---------------------
Per work: whether it started, and if not, why not. A bulk plan over
twelve works where four already have a ticket driving their status is a
normal outcome, not a failure — but an operator who is not told which
four learns nothing from a bare "12 updated".

Nothing here imports from `tickets`.
"""
from __future__ import annotations

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive
from accounts.permissions_v2 import user_has_osius_permission
from audit import context as audit_context

from .models import ExtraWorkAssignment, ExtraWorkPlannedHours
from .planning import PlanRejected, apply_plan, distributed_hours, hours_overrun
from .scoping import scope_extra_work_for
from .serializers import ExtraWorkPlanSerializer


ERR_BULK_PLAN_INVALID = "extra_work_bulk_plan_invalid"
ERR_BULK_PLAN_PROVIDER_ONLY = "plan_provider_only"
#: The body is neither shape, or is both. A CLIENT bug, not a data one —
#: it says nothing about which works exist, so it is free to be specific.
ERR_BULK_PLAN_SHAPE = "extra_work_bulk_plan_shape_invalid"

# ONE constant message for every rejection reason — see property (2).
_BULK_PLAN_INVALID_MESSAGE = (
    "One or more of the selected works could not be resolved. Nothing "
    "was changed."
)


def _reject():
    raise serializers.ValidationError(
        {
            "detail": [
                serializers.ErrorDetail(
                    _BULK_PLAN_INVALID_MESSAGE, code=ERR_BULK_PLAN_INVALID
                )
            ],
            "code": ERR_BULK_PLAN_INVALID,
        }
    )


def _reject_shape(detail: str):
    """A shape refusal, as a ready-to-return 400 body.

    `PlanRejected`, NOT `serializers.ValidationError`, and the reason is
    concrete rather than stylistic: an error raised from a serializer's
    `validate()` is re-normalised by DRF (`as_serializer_error` wraps
    every non-list dict value in a list), so `"code": "..."` reaches the
    client as `"code": ["..."]` and every consumer has to unwrap it.
    Caught live against the dev backend before it shipped. The bulk
    family's own `_reject()` above keeps `ValidationError` because it is
    raised from the VIEW, where nothing re-normalises it.
    """
    raise PlanRejected(
        {"detail": detail, "code": ERR_BULK_PLAN_SHAPE}
    )


class _BulkPlanItemSerializer(ExtraWorkPlanSerializer):
    """ONE work's own plan, inside an `items` list.

    SUBCLASSED for the same reason its sibling below is: every field the
    single plan action accepts is a field a row accepts, BY
    CONSTRUCTION. A row is a plan payload with an id bolted on and
    nothing else, so "what may a row set" can never drift from "what may
    a plan set".
    """

    request = serializers.IntegerField(min_value=1)


class _BulkPlanInputSerializer(ExtraWorkPlanSerializer):
    """The bulk body, in either of its two spellings.

    SUBCLASSED, not re-declared. Every field the single plan action
    accepts is a field this one accepts, BY CONSTRUCTION rather than by
    two lists being kept in step. A second declaration here is all it
    would take for the bulk table to quietly stop carrying a field the
    single form offers, and nothing would fail — the payload would
    validate, the write would land, and the field would be gone.

    The inherited plan fields are the SHARED spelling's values. In the
    per-work spelling they must be absent — see `_normalise` and the
    module docstring for why there is no precedence rule.
    """

    requests = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        required=False,
    )
    items = _BulkPlanItemSerializer(many=True, required=False, allow_empty=False)

    # NO `validate()`. The which-spelling checks live in `_normalise`
    # below, called by the view — see `_reject_shape` for why: DRF
    # re-normalises anything raised from `validate()` and would turn a
    # scalar `code` into a one-element list on its way out.


def _normalise(validated: dict) -> list[tuple[int, dict]]:
    """The ONE place that knows the two spellings apart.

    Returns `[(extra_work_id, plan_payload), ...]` — a fresh dict per
    work, because `apply_plan` is free to consume its payload and two
    works sharing one dict is the kind of aliasing that shows up as a
    field landing on the first row only.

    Raises `PlanRejected` when the body is neither spelling, both at
    once, or names the same work twice.

    KEY PRESENCE SURVIVES THIS. Every plan field is `required=False`, so
    DRF's validated data contains exactly the keys the caller sent, and
    copying that dict per work copies the absences too. If this function
    ever grew a `.setdefault()` it would rebuild the reference system's
    flag-wipe from the inside.
    """
    has_requests = "requests" in validated
    has_items = "items" in validated
    if has_requests and has_items:
        _reject_shape(
            'Send either "requests" (one plan for all of them) or '
            '"items" (a plan per work), never both.'
        )
    if not has_requests and not has_items:
        _reject_shape(
            'Send "requests" with the works to plan, or "items" with a '
            "plan per work."
        )

    if has_items:
        shared = [
            key for key in validated if key not in ("requests", "items")
        ]
        if shared:
            # No precedence rule, deliberately. See the module docstring:
            # a rule about which value wins is a thing an operator has to
            # learn and a client can get wrong in silence.
            _reject_shape(
                "A per-work body carries its values inside each item. "
                "Move " + ", ".join(sorted(shared)) + " into the items "
                "that need it."
            )
        rows = []
        seen: set[int] = set()
        for item in validated["items"]:
            payload = dict(item)
            work_id = payload.pop("request")
            if work_id in seen:
                _reject_shape(
                    "Work #%d appears twice in the batch. Each work gets "
                    "one row." % work_id
                )
            seen.add(work_id)
            rows.append((work_id, payload))
        return rows
    shared = {
        key: value
        for key, value in validated.items()
        if key not in ("requests", "items")
    }
    return [
        (extra_work_id, dict(shared))
        for extra_work_id in dict.fromkeys(validated["requests"])
    ]


def _parse_id_query(raw: list[str]) -> list[int]:
    """`?requests=1,2,3`, `?requests=1&requests=2`, or both mixed.

    Both spellings because both are things a client legitimately
    produces — axios serialises an array as repeated keys, hand-built
    URLs and the browser bar use the comma. Accepting one and silently
    ignoring the other is how a selection of twelve becomes a context
    fetch for one.

    A malformed id is the SHAPE error, not the constant work refusal:
    "abc" is not an id anybody could be probing for, so saying so leaks
    nothing and saves the caller guessing.
    """
    ids: list[int] = []
    for chunk in raw:
        for piece in str(chunk).split(","):
            piece = piece.strip()
            if not piece:
                continue
            try:
                value = int(piece)
            except ValueError:
                _reject_shape(
                    '"requests" takes extra-work ids, comma-separated or '
                    "repeated."
                )
            if value < 1:
                _reject_shape(
                    '"requests" takes extra-work ids, comma-separated or '
                    "repeated."
                )
            ids.append(value)
    if not ids:
        _reject_shape(
            'Name the works to read with "requests", e.g. '
            "?requests=258,257."
        )
    return list(dict.fromkeys(ids))


def _planning_context(works: list) -> list[dict]:
    """What each selected work plans NOW, and who is on it.

    TWO QUERIES FOR THE WHOLE SELECTION, whatever its size. The obvious
    implementation calls the detail serializer's `_serialize_planned_hours`
    per work, which is two queries EACH — a selection of forty would be
    eighty round trips to open a dialog. The wire shape is deliberately
    identical to that function's so the bulk table and the detail page
    render the same facts from the same key names.

    A PERSON WITH HOURS WHO IS NO LONGER ASSIGNED STAYS IN THE LIST,
    flagged `is_assigned: false`, and stays in the total. That is the
    deliberate opposite of the reference system, where the grid is built
    from the assignment list and hours are matched onto it — so a removed
    worker's hours vanish from the screen while still counting in every
    total, and the screen and the total disagree with nothing on screen
    to explain it (`docs/reference/osius-reference-system/` §4.4). The
    dialog cannot re-send such a row (the write refuses hours for anyone
    not assigned), so it says so on the row instead of dropping it.

    `user_phone` is deliberately absent, matching
    `serializers._serialize_planned_hours`: this list exists to plan
    hours, not to publish a staff directory.
    """
    ids = [work.id for work in works]

    crew: dict[int, list[dict]] = {work_id: [] for work_id in ids}
    assigned: dict[int, set[int]] = {work_id: set() for work_id in ids}
    for row in (
        ExtraWorkAssignment.objects.filter(extra_work_request_id__in=ids)
        .select_related("user")
        .order_by("role", "user__full_name", "user__email")
    ):
        crew[row.extra_work_request_id].append(
            {
                "user_id": row.user_id,
                "user_email": row.user.email,
                "user_full_name": row.user.full_name,
                "user_role": row.user.role,
                "assignment_role": row.role,
            }
        )
        assigned[row.extra_work_request_id].add(row.user_id)

    planned: dict[int, list[dict]] = {work_id: [] for work_id in ids}
    for row in (
        ExtraWorkPlannedHours.objects.filter(extra_work_request_id__in=ids)
        .select_related("user", "hour_type")
        .order_by("user__full_name", "user__email", "date", "hour_type_id")
    ):
        planned[row.extra_work_request_id].append(
            {
                "user_id": row.user_id,
                "user_email": row.user.email,
                "user_full_name": row.user.full_name,
                "user_role": row.user.role,
                # W6-H — the day, or NULL for "day not decided".
                "date": row.date,
                # W7 — the kind of hour, or NULL for ordinary hours.
                # Same shape the detail serializer emits, because the
                # bulk table and the detail grid render the same row.
                "hour_type": row.hour_type_id,
                "hour_type_name": (
                    row.hour_type.name if row.hour_type_id else None
                ),
                "hours": f"{row.hours:.2f}",
                "is_assigned": row.user_id
                in assigned[row.extra_work_request_id],
                "set_at": row.set_at,
            }
        )

    out = []
    for work in works:
        # Reuse the ONE overrun rule rather than re-deriving it here;
        # `hours_overrun` reads `work.planned_hours`, so the two figures
        # on this payload cannot disagree with the detail page's.
        out.append(
            {
                "extra_work": work.id,
                "title": work.title,
                "building_name": work.building.name,
                "status": work.status,
                "budget_hours": (
                    None
                    if work.budget_hours is None
                    else f"{work.budget_hours:.2f}"
                ),
                "provider_planned_date": work.provider_planned_date,
                "provider_planned_end_date": work.provider_planned_end_date,
                # What the CUSTOMER asked for, read-only context. A plan
                # never writes these (see `planning.py`), and an operator
                # setting our window without seeing the deadline it is
                # measured against is planning blind.
                "preferred_date": work.preferred_date,
                "deadline": work.deadline,
                "file_upload_required": work.file_upload_required,
                "completion_notes_required": work.completion_notes_required,
                "crew": crew[work.id],
                "planned_hours": planned[work.id],
                "planned_hours_total": f"{distributed_hours(work):.2f}",
                "planned_hours_overrun": hours_overrun(work),
            }
        )
    return out


class ExtraWorkBulkPlanView(APIView):
    """GET / POST /api/extra-work/bulk-plan/ — see the module docstring."""

    permission_classes = [IsAuthenticatedAndActive]
    # JSON ONLY. DRF's `BooleanField.get_value` reads a boolean that is
    # ABSENT from HTML form input as `False` (an unchecked checkbox
    # sends nothing), so with the default parser set a form-encoded bulk
    # plan that never mentioned the completion flags would write both to
    # False on every selected work — the reference system's defect,
    # rebuilt here by a framework default. Pinned at the door, on both
    # plan endpoints, and pinned by a test.
    #
    # W4-O: the per-work shape makes this pin STRONGER, not weaker. A
    # nested `items` list has no form-data spelling at all, so a client
    # that fell back to a form encoding would not merely wipe two flags
    # — it would lose the per-work structure entirely and land whatever
    # DRF made of the flattened keys.
    parser_classes = [JSONParser]

    _PROVIDER_ROLES = frozenset(
        {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        }
    )

    def _provider_only(self, request):
        """The door. Returns a 403 Response, or None to continue.

        GET and POST share it because a read that could see a work the
        write could not touch would be a second, weaker gate on exactly
        the same data.
        """
        if request.user.role not in self._PROVIDER_ROLES:
            return Response(
                {
                    "detail": "This role cannot plan Extra Work. Planning "
                    "is a provider action.",
                    "code": ERR_BULK_PLAN_PROVIDER_ONLY,
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def _resolve(
        self, request, request_ids: list[int], *, with_hours: bool = False
    ) -> dict:
        """Every id, through the actor's OWN scope, BEFORE anything else.

        Raises the constant refusal (property 2) on the first id that
        does not resolve or that this actor may see but not act on.
        Returns `{id: ExtraWorkRequest}`.

        `with_hours` prefetches the distribution so the READ path can
        call `planning.hours_overrun` — the ONE overrun rule — once per
        work without one query per work. The WRITE path leaves it off:
        `apply_plan` mutates those rows, and a prefetch cache filled
        before the write is a stale answer waiting to be read.
        """
        queryset = scope_extra_work_for(request.user).select_related("building")
        if with_hours:
            queryset = queryset.prefetch_related("planned_hours")
        requests = {row.id: row for row in queryset.filter(id__in=request_ids)}
        if len(requests) != len(request_ids):
            _reject()

        # Provider-side BUILDING scope, per row and BEFORE any write —
        # the same check the single plan action makes.
        # `scope_extra_work_for` already answered "may this actor SEE
        # it"; this answers "may this actor ACT on it", which for a
        # COMPANY_ADMIN or a BUILDING_MANAGER is a narrower question. A
        # row that fails is refused with the same body as one that does
        # not exist.
        if request.user.role != UserRole.SUPER_ADMIN:
            for extra_work in requests.values():
                if not user_has_osius_permission(
                    request.user,
                    "osius.ticket.view_building",
                    building_id=extra_work.building_id,
                ):
                    _reject()
        return requests

    # -- GET: what the selection says right now ------------------------

    def get(self, request, *args, **kwargs):
        denied = self._provider_only(request)
        if denied is not None:
            return denied

        try:
            request_ids = _parse_id_query(
                request.query_params.getlist("requests")
            )
        except PlanRejected as exc:
            return Response(exc.body, status=status.HTTP_400_BAD_REQUEST)
        requests = self._resolve(request, request_ids, with_hours=True)
        works = [requests[i] for i in sorted(requests)]
        return Response(
            {"works": _planning_context(works)}, status=status.HTTP_200_OK
        )

    # -- POST: the write -----------------------------------------------

    def post(self, request, *args, **kwargs):
        denied = self._provider_only(request)
        if denied is not None:
            return denied

        payload = _BulkPlanInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            rows = _normalise(dict(payload.validated_data))
        except PlanRejected as exc:
            return Response(exc.body, status=status.HTTP_400_BAD_REQUEST)

        requests = self._resolve(request, [row_id for row_id, _ in rows])

        try:
            audit_context.set_current_reason("extra_work_bulk_plan")
        except Exception:  # pragma: no cover - defensive
            pass

        results: list[dict] = []
        moved: list[int] = []
        kept_own_date: list[int] = []

        # One transaction for the batch, and `PlanRejected` propagates
        # out of it so a refusal on the ninth row rolls back the eight
        # before it — property (1). Ordered by id so the batch is
        # deterministic and a test can read the results positionally;
        # per-work values ride along with their id rather than being
        # re-derived from position.
        try:
            with transaction.atomic():
                for extra_work_id, plan in sorted(rows, key=lambda r: r[0]):
                    extra_work = requests[extra_work_id]
                    result = apply_plan(
                        extra_work,
                        plan,
                        actor=request.user,
                        # A batch has a "which row" question a single
                        # work does not.
                        name_the_work=True,
                    )
                    moved.extend(result["tickets_moved"])
                    kept_own_date.extend(result["tickets_kept_own_date"])
                    results.append(
                        {
                            "extra_work": extra_work.id,
                            "warnings": result["warnings"],
                            "started": result["started"],
                            "start_skipped": result["start_skipped"],
                        }
                    )
        except PlanRejected as exc:
            return Response(exc.body, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "updated": len(results),
                "results": results,
                "tickets_moved": moved,
                "tickets_kept_own_date": kept_own_date,
            },
            status=status.HTTP_200_OK,
        )
