from pathlib import Path as FilePath
from uuid import uuid4

from django.conf import settings
from django.db import models, transaction
from django.db.models.functions import Lower, Trim
from django.utils import timezone


class TicketType(models.TextChoices):
    REPORT = "REPORT", "Melding / Report"
    COMPLAINT = "COMPLAINT", "Klacht / Complaint"
    REQUEST = "REQUEST", "Verzoek / Request"
    SUGGESTION = "SUGGESTION", "Suggestie / Suggestion"
    QUOTE_REQUEST = "QUOTE_REQUEST", "Offerteaanvraag / Quote Request"
    # Sprint 143 §2 — the catch-all the operators asked for. Additive:
    # `AlterField` on the choices only, no data change.
    OTHER = "OTHER", "Overig / Other"


class TicketCategory(models.Model):
    """
    W13 — THE classification of a melding. One list, replacing two.

    ## What this replaces, and why both had to go

    Until now a melding carried two overlapping classifications:

      * `TicketType`, a hardcoded enum (REPORT / COMPLAINT / REQUEST /
        SUGGESTION / QUOTE_REQUEST / OTHER), whose field the create form
        labelled **"Category"**;
      * `WorkCategory` (Sprint 185 E §1), a per-company catalog of KINDS
        OF WORK (sanitair, glasbewassing), whose field the same form
        labelled **"Work category"**.

    Sprint 185's own docstring admitted the collision it was creating:
    "the label above reads 'category' and holds the message type, which
    is exactly the confusion this catalog exists to end." It did not end
    it; it added a second field with a nearly identical label.

    A programmer of twenty years opened the ticket page and asked
    "Where is its category? It has to be there -- is it a complaint, a
    request, a compliment?" He was looking at two fields that both said
    category and neither of which held his answer.

    So there is now ONE, and it is the owner's own list:

        Verzoek - Extra - Compliment - Melden - Storing - Ongegrond -
        Klacht

    `WorkCategory` is deleted outright. `Ticket.type` keeps its column
    (see `legacy_type` below) but no screen offers it any more.

    ## The reference system's shape, trimmed to what has a consumer

    `app/Models/TicketCategory.php` carries slug, label, label_tr,
    label_en, label_bg, label_nl, icon, color, sort_order, is_active,
    metadata. Copied here: `slug`, `label_nl`, `label_en`, `color`,
    `sort_order`, `is_active`.

    Deliberately NOT copied:

      * `label_tr` / `label_bg` -- this product ships nl and en.
      * the bare `label` beside `label_{locale}`. The reference's own
        audit of the sibling `OvertimeType` records what that pair does:
        "`label` vs `label_nl` disagree on ids 2 and 3, and different
        endpoints pick different ones -- the same overtime type is named
        differently on two screens." Two columns holding one fact is the
        bug, not the shape. There is one label per language and one
        resolver, `label_for()`.
      * `icon` and `metadata` -- nothing here renders an icon and
        nothing writes a metadata bag. A column no screen shows and no
        code reads is decoration, and this sprint is about removing
        decoration.

    ## Per COMPANY, unlike the reference

    The reference's copy is a global lookup because its ticket subsystem
    was deleted and the table survives only as a foreign key for extra
    work. Ours is a live tenant catalog, so it carries the `company` FK
    every other catalog here carries -- H-1 is not negotiable, and a
    company that wants an eighth category must be able to add one
    without touching another tenant's list.

    Seeded with the owner's seven for every company, so no tenant starts
    with an empty picker. Editable afterwards: this is a catalog, not an
    enum, which is the whole reason it is a table.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="ticket_categories",
        help_text=(
            "Provider company that owns this category. PROTECT mirrors "
            "every sibling catalog: a Company cannot be hard-deleted "
            "while it still owns categories."
        ),
    )
    slug = models.SlugField(
        max_length=64,
        help_text=(
            "Stable machine key, e.g. 'klacht'. What code and seeds "
            "match on, so renaming the label a company shows never "
            "breaks a mapping. Unique per company."
        ),
    )
    label_nl = models.CharField(
        max_length=128,
        help_text="Dutch label. The primary language (CLAUDE.md).",
    )
    label_en = models.CharField(
        max_length=128,
        help_text="English label.",
    )
    color = models.CharField(
        max_length=7,
        blank=True,
        default="",
        help_text=(
            "'#RRGGBB', or empty. Rendered as the chip colour in the "
            "meldingen list and the category report, which is what makes "
            "the groups visible at a glance rather than readable one "
            "row at a time."
        ),
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        help_text="Ascending order in every picker; ties break on label_nl.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Archived categories stay on the meldingen that carry them "
            "but are not offerable for new ones."
        ),
    )
    available_at_intake = models.BooleanField(
        default=True,
        help_text=(
            "W13 §4 -- may this be chosen when the melding is CREATED? "
            "False for 'Ongegrond', which is a VERDICT: nobody raises a "
            "melding saying it is unfounded, somebody decides that "
            "afterwards. A category with this off is absent from both "
            "create forms and present on the detail page, where the "
            "verdict is actually reached."
        ),
    )
    legacy_type = models.CharField(
        max_length=32,
        choices=TicketType.choices,
        default=TicketType.OTHER,
        help_text=(
            "W13 -- which pre-W13 `Ticket.type` value this category "
            "stands in for. A COMPATIBILITY BRIDGE and nothing else: "
            "`Ticket.type` is a NOT NULL column whose removal needs "
            "owner sign-off, and the pre-existing tickets-by-type "
            "report reads it. Declaring the mapping on the category row "
            "keeps it in ONE place, visible and editable, instead of "
            "hidden in a dict in a serializer. Delete this column with "
            "`Ticket.type`."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "label_nl", "id"]
        verbose_name = "ticket category"
        verbose_name_plural = "ticket categories"
        constraints = [
            models.UniqueConstraint(
                "company",
                "slug",
                name="uniq_ticket_category_slug_per_company",
            ),
            # The house rule for every catalog here: Trim() first so
            # whitespace cannot bypass a Lower()-only dedupe, Lower() for
            # case. On the Dutch label, because that is the one operators
            # type and read.
            models.UniqueConstraint(
                Lower(Trim("label_nl")),
                "company",
                name="uniq_ticket_category_label_nl_per_company_ci",
            ),
        ]

    def label_for(self, language: str | None) -> str:
        """The label in the reader's language, with one fallback rule.

        The ONE resolver. Every surface -- serializer, CSV, PDF, report
        -- comes through here, so the reference's "same row named
        differently on two screens" cannot happen: there is nowhere else
        that decides.

        Dutch is primary, so an English label that was never filled in
        falls back to Dutch rather than rendering blank.
        """
        if (language or "").lower().startswith("en"):
            return self.label_en or self.label_nl
        return self.label_nl or self.label_en

    def __str__(self):
        return self.label_nl


class TicketPriority(models.TextChoices):
    NORMAL = "NORMAL", "Normal"
    HIGH = "HIGH", "High"
    URGENT = "URGENT", "Urgent"


class TicketScheduleStatus(models.TextChoices):
    """
    Sprint 9B — operational scheduling lifecycle on a Ticket.

    Additive to the existing `TicketStatus` workflow: scheduling is an
    orthogonal axis (when is the work planned) that never changes the
    workflow status and never disturbs SLA (SLA stays anchored on
    `created_at`). A ticket is UNSCHEDULED until a provider operator
    sets a `scheduled_start_at`; rescheduling an already-scheduled
    ticket records the prior start + a mandatory reason and lands the
    row in RESCHEDULED. Clearing the schedule returns it to UNSCHEDULED.
    """

    UNSCHEDULED = "UNSCHEDULED", "Unscheduled"
    SCHEDULED = "SCHEDULED", "Scheduled"
    RESCHEDULED = "RESCHEDULED", "Rescheduled"


class TicketStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    # W10 §1 — SEEN AND SCHEDULED, NOT STARTED.
    #
    # The gap this closes is the operator's, not the model's: opening a
    # September job in August, the only honest options were to leave it
    # at OPEN (which reads to the customer as ignored) or to move it to
    # IN_PROGRESS (which claims work that has not begun). ACKNOWLEDGED is
    # the true third answer — a human has seen it, it is scheduled, and
    # nobody has started.
    #
    # It is a WORKFLOW status and nothing else. WHEN the work is due is
    # already owned by `scheduled_start_at` and is not duplicated here;
    # this says only that somebody has taken responsibility for it.
    ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    # W10 §2 — STALLED ON SOMETHING WE DO NOT CONTROL.
    #
    # Waiting on a part, on access, on the customer to clear a room. Not
    # cancelled, not in progress, and deliberately NOT terminal: it is in
    # `ALLOWED_TRANSITIONS` with a way back to IN_PROGRESS, it is not in
    # `TERMINAL_TICKET_STATUSES`, and `inTicketList` is true in the
    # frontend spec, so a job parked here is still a chip somebody has to
    # work. That combination is what stops it becoming a hiding place —
    # a status you can enter and never leave is a bin, not a state.
    ON_HOLD = "ON_HOLD", "On Hold"
    # Sprint 28 Batch 11 — STAFF default completion route. When a STAFF
    # user marks their work done, the ticket lands here for BM review.
    # BM accepts -> WAITING_CUSTOMER_APPROVAL, or rejects -> IN_PROGRESS.
    # The per-(staff, building) `BuildingStaffVisibility
    # .staff_completion_routes_to_customer` flag can opt a staff out of
    # this default and route directly to WAITING_CUSTOMER_APPROVAL.
    WAITING_MANAGER_REVIEW = "WAITING_MANAGER_REVIEW", "Waiting Manager Review"
    WAITING_CUSTOMER_APPROVAL = "WAITING_CUSTOMER_APPROVAL", "Waiting Customer Approval"
    REJECTED = "REJECTED", "Rejected"
    APPROVED = "APPROVED", "Approved"
    CLOSED = "CLOSED", "Closed"
    REOPENED_BY_ADMIN = "REOPENED_BY_ADMIN", "Reopened by Admin"
    # Sprint 7B — terminal status for a normal ticket that a provider
    # converted into an Extra Work request. The original ticket is
    # SUPERSEDED (it leaves every operational queue); a NEW operational
    # ticket is spawned later by the Sprint 6A/6B machinery anchored to
    # the new ExtraWorkRequest — the original is NOT reused. This status
    # is intentionally absent from `ALLOWED_TRANSITIONS` in
    # `state_machine.py`, keeping it terminal: no transition leaves it.
    CONVERTED_TO_EXTRA_WORK = "CONVERTED_TO_EXTRA_WORK", "Converted to Extra Work"


# Sprint 4 — terminal ticket statuses, mirroring the schedule control's
# `_SCHEDULE_TERMINAL_STATUSES` (tickets/views.py). Sub-task mutation,
# placing an assignment into a sub-task, and flipping
# `auto_complete_on_subtasks` are all blocked when the ticket is terminal.
TERMINAL_TICKET_STATUSES = frozenset(
    {
        TicketStatus.APPROVED,
        TicketStatus.REJECTED,
        TicketStatus.CLOSED,
        TicketStatus.CONVERTED_TO_EXTRA_WORK,
    }
)


class TicketMessageType(models.TextChoices):
    """
    B7 + M1 B5 — five-channel note taxonomy (`docs/product/system-
    business-logic-and-workflows.md` §9). Each `TicketMessage` carries one
    value; the enum value IS the canonical visibility classification.
    Read-visibility per tier (SA = Super Admin, MGMT = Company Admin /
    Building Manager, STAFF = field staff, CUST = customer-side):

      * `PUBLIC_REPLY` — visible to SA + MGMT + CUST. M1 B5: STAFF DROPPED
        (a field worker has no customer-conversation channel; their only
        customer-facing channel is STAFF_COMPLETION, one-way status).
      * `INTERNAL_NOTE` — PROVIDER_INTERNAL. Visible to SA + MGMT only.
        NOT STAFF, NOT CUST. The literal `"INTERNAL_NOTE"` is preserved so
        legacy rows keep their semantic without a data migration.
      * `STAFF_OPERATIONAL` — visible to SA + MGMT + STAFF. NOT CUST.
        Operational instructions field staff need (e.g. "bring a ladder").
      * `STAFF_COMPLETION` — completion evidence. Visible to SA + MGMT +
        STAFF + CUST (customer-visible proof of work).
      * `CUSTOMER_INTERNAL` (M1 B5, NEW) — the customer side's OWN internal
        note. Visible to CUST + SA (forensic) ONLY. NOT MGMT, NOT STAFF —
        the provider never sees the customer's internal deliberation. The
        mirror image of INTERNAL_NOTE.

    Posting (who may CREATE each tier) is enforced separately in
    `tickets.serializers.TicketMessageSerializer` (the POSTING table):
    PUBLIC_REPLY = CUST + MGMT + SA (not STAFF); STAFF_COMPLETION = STAFF
    (+ provider-side); STAFF_OPERATIONAL = STAFF + MGMT + SA; INTERNAL_NOTE
    = MGMT + SA; CUSTOMER_INTERNAL = CUST.
    """

    PUBLIC_REPLY = "PUBLIC_REPLY", "Public Reply"
    INTERNAL_NOTE = "INTERNAL_NOTE", "Internal Note (provider-internal)"
    STAFF_OPERATIONAL = "STAFF_OPERATIONAL", "Staff Operational Note"
    STAFF_COMPLETION = "STAFF_COMPLETION", "Staff Completion Note"
    # M1 B5 — the customer side's own internal note (CUST + SA forensic only).
    CUSTOMER_INTERNAL = "CUSTOMER_INTERNAL", "Customer Internal Note"


class TicketMessageVisibility(models.TextChoices):
    """M1 B1 — message visibility mode, orthogonal to `message_type`.

    `message_type` classifies the AUDIENCE TIER (who may ever see this
    kind of note). `visibility_mode` narrows WITHIN that tier:

      * NORMAL (default) — the message is visible to its full
        message_type audience (the existing behaviour; every pre-B1 row
        is NORMAL). `directed_to` here is an attention hint only.
      * RESTRICTED — the message is visible only to the users named in
        `directed_to` (still within the message_type audience). B1 adds
        the field and computes notification recipients correctly for
        RESTRICTED; the READ-SIDE hiding (queryset filter) is enforced
        in B2, not here.
    """

    NORMAL = "NORMAL", "Normal"
    RESTRICTED = "RESTRICTED", "Restricted"


def ticket_attachment_upload_path(instance, filename):
    extension = FilePath(filename).suffix.lower()
    return f"tickets/{instance.ticket_id}/{uuid4().hex}{extension}"


class Ticket(models.Model):
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="tickets",
    )
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="tickets",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_tickets",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )

    ticket_no = models.CharField(max_length=32, unique=True, null=True, blank=True)

    title = models.CharField(max_length=255)
    description = models.TextField()
    room_label = models.CharField(max_length=255, blank=True)

    type = models.CharField(
        max_length=32,
        choices=TicketType.choices,
        default=TicketType.REPORT,
    )
    # W13 — THE classification of this melding, and the only one any
    # screen offers. Was a `WorkCategory` (kind of work) beside `type`
    # (kind of message); both are superseded by the owner's single list.
    #
    # NULLABLE, and that is a real state rather than an oversight: it
    # means "nobody has said yet". The migration puts every pre-W13
    # melding somewhere, but the two legacy `type` values with no home
    # in the owner's list (SUGGESTION, OTHER) land here on purpose,
    # visible and clearable, instead of being forced into a category
    # nobody chose.
    #
    # SET_NULL rather than PROTECT: the melding outlives its
    # classification. The endpoint refuses to delete a category still in
    # use and points the operator at archiving, so this only fires for
    # paths that bypass it.
    category = models.ForeignKey(
        "tickets.TicketCategory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="tickets",
        help_text=(
            "W13 — what kind of melding this is, from the company's "
            "catalog: Verzoek / Extra / Compliment / Melden / Storing / "
            "Ongegrond / Klacht."
        ),
    )
    priority = models.CharField(
        max_length=32,
        choices=TicketPriority.choices,
        default=TicketPriority.NORMAL,
    )
    status = models.CharField(
        max_length=64,
        choices=TicketStatus.choices,
        default=TicketStatus.OPEN,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Soft-delete (Sprint 12). The TicketViewSet's DESTROY action sets
    # both fields and the row stays in the database; scope_tickets_for
    # / tickets_for_scope filter rows where deleted_at IS NOT NULL out
    # of every list, detail, and report query. The internal
    # ticket-status history, messages, and attachments are preserved
    # so an operator can audit the row even after a soft delete.
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_tickets",
    )

    # ------------------------------------------------------------------
    # W-H §1 — THE ARCHIVE. One act, not a review cycle.
    #
    # The owner's father, after twenty minutes on the ticket page: "All
    # the tickets from five years ago can sit in Closed. You need an
    # archive." And on how it should feel: "I put a button saying my job
    # on this ticket is finished."
    #
    # ## Why ONE act and not request / approve / reject
    #
    # The system we are closing the gap against carries six archive
    # columns that look like a review cycle — requested / approved /
    # rejected, each with a `_by`. It is not one. Its own reference
    # notes record that there is **no request-archive endpoint
    # anywhere**: `approveArchive` back-fills `archive_requested_at` with
    # `?? now()` in the same statement that approves it, and a real row
    # (476) has the two timestamps equal to the second. So the "request"
    # half is a fiction written by the approve half, and copying it here
    # would be copying an artefact.
    #
    # What that system actually has is what we implement: one act that
    # files finished work away, and one act that brings it back with a
    # reason. Nothing waits on anybody.
    #
    # ## Archived is NOT a status
    #
    # `TicketStatus` says what is happening to the work; this says
    # whether we are still looking at it. Making it a status would put
    # one fact in two places (a CLOSED ticket that is archived is still
    # closed) and would need a transition into and out of every terminal
    # state. A nullable timestamp has one owner and one meaning: set is
    # archived, null is not.
    #
    # Only a ticket in `TERMINAL_TICKET_STATUSES` may be archived —
    # filing live work away is how work gets lost.
    # ------------------------------------------------------------------
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archived_tickets",
    )
    #: Optional. The reason a job was filed away is almost always "it is
    #: finished", which the status already says; this is for the times it
    #: is not. Bringing a ticket BACK requires a reason and that reason
    #: lands on the AuditLog, which is where a decision somebody has to
    #: answer for belongs.
    archive_note = models.TextField(blank=True, default="")

    first_response_at = models.DateTimeField(null=True, blank=True)
    sent_for_approval_at = models.DateTimeField(null=True, blank=True)
    # Sprint 28 Batch 11 — stamped when the ticket enters
    # WAITING_MANAGER_REVIEW (the STAFF default completion route).
    # Loop semantics mirror the rest of the timestamp cluster: a BM
    # rejection back to IN_PROGRESS followed by another STAFF completion
    # overwrites the value.
    manager_review_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # ------------------------------------------------------------------
    # Sprint 184 §3 — THE CUSTOMER'S WANTED DATE. A WISH, NOT A DEADLINE.
    #
    # A customer opening a melding can now say when they would like it
    # done, the same way they already can on an extra work.
    #
    # The distinction this system settled in Sprint 176 §3 and must keep:
    #
    #   a WISH     is the customer's — "I would like it around then".
    #              `ExtraWorkRequest.preferred_date` is the same thing on
    #              the extra work; this is its melding counterpart.
    #   a DEADLINE is a PROVIDER COMMITMENT — "it will be finished by".
    #              It stays provider-only and is deliberately NOT added
    #              here: a customer who could type a deadline would be
    #              setting the provider's commitment, and the overdue
    #              rule reads deadlines.
    #
    # So this field never feeds `is_overdue` and never decides late. It
    # records what the customer asked for, so the provider can see it and
    # so it survives conversion into `ExtraWorkRequest.preferred_date`
    # (`extra_work/conversion.py`) — a date a customer typed that
    # vanishes at conversion is worse than never having asked for it.
    # ------------------------------------------------------------------
    customer_wanted_date = models.DateField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Sprint 184 — the date the CUSTOMER would like this done. A "
            "wish, not a commitment: it never decides whether the ticket "
            "is late. Carried into ExtraWorkRequest.preferred_date on "
            "conversion."
        ),
    )

    # Sprint 28 Batch 7 — link back to the ExtraWorkRequestItem this
    # Ticket was spawned from. NULL for tickets created by any other
    # path (legacy creation, direct API submission, etc.). SET_NULL on
    # the EW side's delete so a Ticket survives if the cart line is
    # later removed — the operational job has already been scheduled
    # / executed and dropping it would lose audit history.
    extra_work_request_item = models.ForeignKey(
        "extra_work.ExtraWorkRequestItem",
        on_delete=models.SET_NULL,
        related_name="spawned_tickets",
        null=True,
        blank=True,
        default=None,
    )

    # Sprint 28 Batch 8 — link back to the ProposalLine this Ticket
    # was spawned from. NULL on tickets that came through the instant
    # route (Batch 7), the legacy ticket-create path, or any other
    # surface. SET_NULL so a Ticket survives if the proposal / line
    # is later deleted — the operational job has audit history we
    # don't want to lose.
    #
    # Sprint 6A — retained for back-compat of the origin payload's
    # `extra_work_request_item_id` / `service_name` keys. NOT the
    # canonical EW link anymore: a request now spawns exactly ONE
    # ticket and the canonical parent is `extra_work_request` below.
    # The instant / legacy helpers set `extra_work_request_item` to the
    # FIRST cart line; the proposal helper sets `proposal_line` to the
    # FIRST is_approved_for_spawn line — purely so the origin payload
    # can surface a representative service name.
    proposal_line = models.ForeignKey(
        "extra_work.ProposalLine",
        on_delete=models.SET_NULL,
        related_name="spawned_tickets_for_proposal_line",
        null=True,
        blank=True,
        default=None,
    )

    # Sprint 6A — CANONICAL parent Extra Work request. One
    # ExtraWorkRequest spawns exactly ONE operational Ticket; this FK
    # is that link. SET_NULL so the operational job survives if the
    # parent EW is later soft/hard-deleted. No DB unique constraint:
    # historical data carries multiple tickets per request, so a
    # unique index would fail the backfill. Idempotency
    # (one-ticket-per-request) is enforced in the spawn helpers + tests.
    extra_work_request = models.ForeignKey(
        "extra_work.ExtraWorkRequest",
        on_delete=models.SET_NULL,
        related_name="operational_tickets",
        null=True,
        blank=True,
        default=None,
    )

    # Sprint 11B origin link — the operational Ticket spawned from a
    # recurring / planned occurrence. OneToOne so one occurrence has at
    # most one ticket (idempotency, DB-enforced) and `occurrence.ticket`
    # resolves the reverse. SET_NULL so the ticket survives if the
    # occurrence is hard-deleted. This is the THIRD origin axis next to
    # `extra_work_request` for report separation (planned vs ad-hoc vs
    # Extra Work).
    planned_occurrence = models.OneToOneField(
        "planned_work.PlannedOccurrence",
        on_delete=models.SET_NULL,
        related_name="ticket",
        null=True,
        blank=True,
        default=None,
    )

    # SLA tracking. Engine lives in backend/sla/. sla_first_breached_at is a
    # permanent marker that survives reopens; the rest are recomputed by the
    # engine and the periodic reconciliation task.
    sla_due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    sla_started_at = models.DateTimeField(null=True, blank=True)
    sla_completed_at = models.DateTimeField(null=True, blank=True)
    sla_paused_at = models.DateTimeField(null=True, blank=True)
    sla_paused_seconds = models.PositiveIntegerField(default=0)
    sla_first_breached_at = models.DateTimeField(null=True, blank=True)
    sla_status = models.CharField(
        max_length=16,
        choices=[
            ("ON_TRACK", "On track"),
            ("AT_RISK", "At risk"),
            ("BREACHED", "Breached"),
            ("COMPLETED", "Completed"),
            ("HISTORICAL", "Historical"),
        ],
        default="ON_TRACK",
        db_index=True,
    )

    # Sprint 9B — operational scheduling (additive; orthogonal to the
    # workflow `status` field and to SLA). `scheduled_start_at` is the
    # planned start of the on-site work; `scheduled_end_at` is the
    # optional planned end; `time_window_label` is a free-text window
    # hint ("morning", "08:00-10:00"). `schedule_status` tracks the
    # UNSCHEDULED / SCHEDULED / RESCHEDULED lifecycle. On a reschedule,
    # `rescheduled_from` keeps the prior start and `reschedule_reason`
    # holds the mandatory operator explanation. SLA is NOT affected:
    # the schedule endpoints save with an explicit `update_fields` set
    # that excludes `status`, so the SLA post_save signal sees no
    # status change and never recomputes `sla_*`.
    scheduled_start_at = models.DateTimeField(
        null=True, blank=True, db_index=True, default=None
    )
    scheduled_end_at = models.DateTimeField(null=True, blank=True, default=None)
    time_window_label = models.CharField(max_length=64, blank=True, default="")
    schedule_status = models.CharField(
        max_length=16,
        choices=TicketScheduleStatus.choices,
        default=TicketScheduleStatus.UNSCHEDULED,
    )
    rescheduled_from = models.DateTimeField(null=True, blank=True, default=None)
    reschedule_reason = models.TextField(blank=True, default="")

    # Sprint 4 — sub-task auto-complete opt-in. When True AND the ticket
    # has >=1 SubTask, completing the final outstanding slot auto-advances
    # the ticket IN_PROGRESS -> WAITING_MANAGER_REVIEW (best-effort
    # roll-up; see tickets/sub_task_rollup.py). Default False keeps the
    # existing manager/staff-confirm completion flow. Settable only by
    # PA / SA via the dedicated auto-complete-flag endpoint.
    auto_complete_on_subtasks = models.BooleanField(default=False)

    # Sprint 191 §2.5 — the per-work photo-visibility setting.
    #
    # Default False: a staff upload on this ticket lands INTERNAL
    # (`AttachmentVisibility.INTERNAL`) and stays provider-side until a
    # provider manager promotes it. Set True for the customers who have
    # asked to see the work as it happens — then a staff upload on THIS
    # ticket is customer-visible the moment it is uploaded, with no
    # promote step.
    #
    # It changes only the DEFAULT applied at upload. It does not
    # retro-promote what is already stored, it grants nobody a new
    # permission, and it has no effect on the completion-evidence gate
    # (which reads `is_hidden`, never `visibility`). Settable only by
    # PA / SA through the dedicated attachment-visibility-policy
    # endpoint, mirroring `auto_complete_on_subtasks`.
    staff_uploads_customer_visible = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.ticket_no or self.id} - {self.title}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if not is_new:
            super().save(*args, **kwargs)
            return

        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.ticket_no:
                self.ticket_no = f"TCK-{self.created_at.year}-{self.id:06d}"
                type(self).objects.filter(pk=self.pk).update(ticket_no=self.ticket_no)

    def mark_first_response_if_needed(self):
        if not self.first_response_at:
            self.first_response_at = timezone.now()
            self.save(update_fields=["first_response_at"])


class SubTask(models.Model):
    """
    Sprint 4 — a named operational work-unit under a Ticket.

    A ticket may carry many sub-tasks; each sub-task carries 1..N staff
    assignments via the nullable `TicketStaffAssignment.sub_task` FK (a
    slot with sub_task=NULL is the ticket's default un-split work). Sub-
    tasks are OPTIONAL and LAYERED: a ticket with no sub-tasks, and any
    assignment with sub_task=NULL, behaves exactly as before this sprint.

    Sub-tasks are NOT priced — billing stays per-occurrence/per-ticket;
    this layer adds no pricing columns. Deleting a sub-task SET_NULLs its
    slots back to the loose pool (see TicketStaffAssignment.sub_task), so
    it NEVER destroys a staff assignment or its completion evidence.
    """

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="sub_tasks",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    ordering = models.PositiveIntegerField(default=0)
    # W-LATE §3a — the part's OWN window. Optional, and three shapes: a
    # day (start only), a range (start and end), a day with a clock hint
    # (`time_window_label`, the same free-text hint the ticket and the
    # slot already carry — "08:00-10:00", "ochtend"). The server refuses
    # a window outside the ticket's own window (`part_windows.py`); a
    # part with no window behaves exactly as before this wave.
    planned_start_date = models.DateField(null=True, blank=True, default=None)
    planned_end_date = models.DateField(null=True, blank=True, default=None)
    time_window_label = models.CharField(max_length=64, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sub_tasks_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ordering", "id"]

    def __str__(self):
        return f"SubTask #{self.pk} of ticket {self.ticket_id}: {self.title}"

    def is_done(self) -> bool:
        """A sub-task is done iff it has >=1 staff assignment AND every one
        of those assignments is COMPLETED. An empty sub-task is NOT done
        (avoids the vacuous-truth bug in the auto-complete roll-up).

        Iterates `staff_assignments.all()` so a prefetched detail render
        uses the cache; the roll-up path issues one bounded query."""
        assignments = list(self.staff_assignments.all())
        if not assignments:
            return False
        return all(
            a.slot_status == StaffAssignmentSlotStatus.COMPLETED
            for a in assignments
        )

    def window_state(self, today=None) -> str:
        """W-LATE §3b — where this part stands against its own window:
        NONE / OPEN / LAST_DAY / MISSED / DONE, from the one rule in
        `tickets/lateness.py`."""
        from . import lateness

        return lateness.part_state(
            planned_start=self.planned_start_date,
            planned_end=self.planned_end_date,
            is_done=self.is_done(),
            today=today or timezone.localdate(),
        )


class TicketMessage(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_messages",
    )

    message = models.TextField()
    message_type = models.CharField(
        max_length=32,
        choices=TicketMessageType.choices,
        default=TicketMessageType.PUBLIC_REPLY,
    )

    # M1 B1 — attention / notification target. Distinct from
    # `visibility_mode`: naming a user here does NOT make the message
    # private (a NORMAL message stays visible to its whole audience). It
    # marks who the message is "directed to" so they get a flagged
    # in-app notification. Validation (serializer) keeps every directed
    # user inside the message_type's visible audience so directing can
    # never leak a note to someone who could not otherwise see it.
    directed_to = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="directed_ticket_messages",
    )
    # M1 B1 — NORMAL (default, full back-compat) | RESTRICTED. See
    # TicketMessageVisibility. B1 stores it + uses it to scope
    # notification recipients; the read-side hiding for RESTRICTED is B2.
    visibility_mode = models.CharField(
        max_length=16,
        choices=TicketMessageVisibility.choices,
        default=TicketMessageVisibility.NORMAL,
        db_index=True,
    )

    is_hidden = models.BooleanField(default=False)
    hidden_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hidden_ticket_messages",
    )
    hidden_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.ticket} - {self.author}"


class AttachmentVisibility(models.TextChoices):
    """
    Sprint 191 §2.5 — WHO may see an attachment, as its own axis.

    Addendum A §A.3.3: every artefact carries a visibility level and it
    defaults to the most restrictive one. For a ticket attachment that
    is INTERNAL — provider-side only.

    This is deliberately NOT the same thing as any of the three flags it
    sits beside, and the difference is the whole point of the field:

      * `is_hidden` is MODERATION (B7). It hides a row from everybody
        below provider management, STAFF included. A worker cannot set
        it and a worker cannot see what carries it.
      * `visibility` is the CUSTOMER wall. INTERNAL keeps a row on the
        provider side (management AND the staff who did the work);
        CUSTOMER releases it across the wall. Nothing a worker uploads
        crosses it until a provider manager promotes it, or the work
        carries `Ticket.staff_uploads_customer_visible`.
      * `phase` is a LABEL (before / after). It never decides who sees
        anything. The reference system's bug is exactly this conflation:
        its "draft" phase bucket renders to the customer under a "Draft
        Images" heading, so labelling a photo publishes it. Here the two
        axes are independent in both directions — a BEFORE photo can be
        customer-visible and an AFTER photo can be internal.

    THE COMPLETION-EVIDENCE GATE DOES NOT READ THIS FIELD, and must not
    start. `state_machine._ticket_has_visible_attachment` and the
    per-slot gate in `views_staff_assignments.py` both count
    `is_hidden=False` rows: a photo a worker uploaded as proof still
    satisfies the gate while it is INTERNAL. The customer not seeing it
    yet does not mean the work did not happen.
    """

    INTERNAL = "INTERNAL", "Internal (provider side only)"
    CUSTOMER = "CUSTOMER", "Customer visible"


class AttachmentPhase(models.TextChoices):
    """
    Sprint 191 §2.5 — WHEN in the job the file was taken. A label, and
    only a label: no queryset filters on it, no permission reads it, and
    changing it moves nothing across the customer wall. See
    `AttachmentVisibility` for why that separation is load-bearing.
    """

    UNSPECIFIED = "UNSPECIFIED", "Unspecified"
    BEFORE = "BEFORE", "Before"
    AFTER = "AFTER", "After"


class UploadVisibilitySource(models.TextChoices):
    """
    W4-P — WHICH level of the resolution ladder decided this row's
    `visibility` at upload time.

    Recorded so an operator can answer "why is this photo internal?"
    without reading code, and so a reviewer can tell a deliberate
    manager choice apart from a default that nobody ever touched. It is
    a record of a past decision, written once at upload and never
    recomputed: changing a grant afterwards does NOT rewrite it, exactly
    as changing `Ticket.staff_uploads_customer_visible` does not
    retro-promote what is already stored.

    `UNRECORDED` (the blank default) is every row that existed before
    this column did. It means "we do not know", not "default".
    """

    UNRECORDED = "", "Unrecorded (pre-W4-P row)"
    UPLOADER_CHOICE = "UPLOADER_CHOICE", "Chosen by the uploader"
    CUSTOMER_UPLOAD = "CUSTOMER_UPLOAD", "The customer's own upload"
    TICKET_GRANT = "TICKET_GRANT", "Per-ticket permission"
    STANDING_GRANT = "STANDING_GRANT", "Standing permission"
    WORK_SETTING = "WORK_SETTING", "Per-work setting"
    DEFAULT_INTERNAL = "DEFAULT_INTERNAL", "Default (internal)"
    MANUAL = "MANUAL", "Changed by hand afterwards"


class TicketAttachment(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    message = models.ForeignKey(
        TicketMessage,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )
    # Sprint 12 — optional link to a specific staff slot, so a completion
    # PHOTO can serve as per-slot evidence (the slot completion gate accepts
    # a non-empty completion_note OR a linked non-hidden photo). String
    # forward-ref because TicketStaffAssignment is defined later in this
    # module. SET_NULL: removing a slot must not delete the customer's
    # uploaded evidence (the attachment stays on the ticket).
    staff_assignment = models.ForeignKey(
        "TicketStaffAssignment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attachments",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_attachments",
    )

    file = models.FileField(upload_to=ticket_attachment_upload_path)
    original_filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120)
    file_size = models.PositiveIntegerField()
    is_hidden = models.BooleanField(default=False)

    # Sprint 191 §2.5 — the customer wall (see `AttachmentVisibility`).
    # Model default is the most restrictive value per Addendum A §A.3.3;
    # `TicketAttachmentListCreateView.perform_create` is what decides the
    # value an actual upload gets (a customer's own upload is CUSTOMER —
    # it must not be hidden from the person who uploaded it).
    #
    # Migration 0027 backfills every pre-existing row to the level it was
    # ALREADY being served at, so the field changes nothing about what
    # anybody could see before it existed: is_hidden rows -> INTERNAL,
    # everything else -> CUSTOMER.
    visibility = models.CharField(
        max_length=16,
        choices=AttachmentVisibility.choices,
        default=AttachmentVisibility.INTERNAL,
    )
    # Sprint 191 §2.5 — before / after. A label with no behaviour.
    phase = models.CharField(
        max_length=16,
        choices=AttachmentPhase.choices,
        default=AttachmentPhase.UNSPECIFIED,
    )

    # W4-P — WHICH rung of the resolution ladder produced `visibility`
    # at upload time. See `UploadVisibilitySource`. Written once, at
    # create; the promote endpoint stamps MANUAL because a hand change
    # is exactly the thing an operator most needs to be able to tell
    # apart from a rule. Blank on every pre-W4-P row, which reads
    # "unrecorded" and never "default".
    visibility_source = models.CharField(
        max_length=24,
        choices=UploadVisibilitySource.choices,
        default=UploadVisibilitySource.UNRECORDED,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.original_filename


class UploadVisibilityGrant(models.Model):
    """
    W4-P — the standing / per-ticket permission that lets a named
    person's uploads land customer-visible without a manager promoting
    each photo by hand.

    ONE model, TWO scopes, told apart by `ticket`:

      * `ticket IS NULL`  — STANDING. This person's uploads on EVERY
        ticket. Granted on the person's admin page. SUPER_ADMIN /
        COMPANY_ADMIN only.
      * `ticket IS NOT NULL` — PER-TICKET. This person's uploads on THIS
        ticket only. Granted on the ticket's Assignment card. Provider
        management (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER)
        holding scope on the ticket.

    `uploads_customer_visible` is an EXPLICIT decision in both
    directions and the row's existence is what makes it explicit:

      * row absent      — no decision at this level; the resolver falls
                          through to the next one down.
      * value True      — a grant. Uploads land CUSTOMER.
      * value False     — a refusal. Uploads land INTERNAL even if a
                          less specific level said yes.

    That three-state shape is deliberately the one this codebase already
    uses for `BuildingManagerAssignment.permission_overrides` (absence =
    fall through to the default, an explicit entry = a decision), and
    the row-per-grant shape is `CredentialCustomerVisibility`'s. It is
    not a sixth bespoke mechanism; it is the fifth one's two patterns
    put together, with a nullable scope column so one table answers both
    questions.

    WHAT IT DOES NOT DO. It grants nobody the right to SEE anything: the
    customer wall, `scope_tickets_for` and the per-role attachment
    filters are untouched, so a photo still reaches only the customer of
    its own ticket. It never rewrites a stored row — it changes the
    level the NEXT upload lands at. And it is invisible to the
    completion-evidence gates, which read `is_hidden` and never
    `visibility`.

    See `tickets/attachment_visibility.py` for the resolution order this
    feeds, written out in full.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="upload_visibility_grants",
        help_text="The person whose uploads this decides.",
    )
    # NULL is the STANDING scope, and the two partial unique constraints
    # below are why it has to be modelled this way rather than as a
    # plain `unique_together`: Postgres treats NULLs as distinct, so
    # `unique_together(user, ticket)` alone would happily store five
    # standing rows for one person.
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="upload_visibility_grants",
        help_text="NULL = standing (every ticket). Set = this ticket only.",
    )
    uploads_customer_visible = models.BooleanField(
        help_text=(
            "True = this person's uploads land customer-visible at this "
            "scope. False = they stay internal at this scope, overriding "
            "anything less specific. No default: the row exists only "
            "when somebody decided."
        ),
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="upload_visibility_grants_made",
    )
    reason = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # One decision per (person, ticket) ...
            models.UniqueConstraint(
                fields=["user", "ticket"],
                condition=models.Q(ticket__isnull=False),
                name="uniq_upload_visibility_grant_per_ticket",
            ),
            # ... and exactly one standing decision per person.
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(ticket__isnull=True),
                name="uniq_upload_visibility_grant_standing",
            ),
        ]
        indexes = [
            models.Index(fields=["ticket", "user"]),
        ]

    def __str__(self):
        scope = "standing" if self.ticket_id is None else f"ticket={self.ticket_id}"
        state = "visible" if self.uploads_customer_visible else "internal"
        return f"UploadVisibilityGrant<user={self.user_id} {scope} {state}>"


class TicketStatusHistory(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="status_history",
    )

    old_status = models.CharField(max_length=64, blank=True)
    new_status = models.CharField(max_length=64)
    # Sprint 180 §1 — nullable for SYSTEM-driven transitions.
    #
    # `changed_by IS NULL` means "no person drove this row, the system
    # did", which is exactly what the customer-approval auto-close is
    # (`tickets/auto_close.py`). The rest of the codebase was already
    # written for it and only the column was still NOT NULL:
    # `TicketStatusHistorySerializer.to_representation` documents "rows
    # whose `changed_by` is None (system transitions)", and
    # `audit/views_ticket_timeline.py` already emits
    # `changed_by_email: None` for such a row.
    # `ExtraWorkStatusHistory.changed_by` has been nullable for the
    # same reason since Sprint 29 Batch 29.8.
    #
    # `on_delete` stays PROTECT (deliberately unchanged): a real actor
    # still cannot be hard-deleted out from under their own history.
    # NULL is only ever WRITTEN by the system path, never by a cascade.
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ticket_status_changes",
    )
    note = models.TextField(blank=True)
    # Sprint 27F-B1 — workflow override flag. Mirrors
    # `ExtraWorkStatusHistory.is_override` / `override_reason`. Set
    # when a provider operator drives a customer-decision transition
    # (WAITING_CUSTOMER_APPROVAL -> APPROVED/REJECTED) — the reason
    # is the operator's audit-trail explanation. Distinct from
    # `note` (which is a generic transition note that may be empty
    # on non-override transitions). H-11 invariant: workflow
    # override is separate from permission override.
    is_override = models.BooleanField(default=False)
    override_reason = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name_plural = "Ticket status history"

    def __str__(self):
        return f"{self.ticket}: {self.old_status} → {self.new_status}"


class StaffAssignmentSlotStatus(models.TextChoices):
    """
    Sprint 14E — per-assignment operational slot lifecycle.

    Additive to the ticket's `TicketStatus` workflow: a slot is one
    staff member's dated/time-windowed piece of work on a ticket. Slot
    status is NOT a ticket status — completing a slot does NOT move the
    ticket through its own state machine. The ticket still completes via
    the existing STAFF-completion -> manager-review double-check flow
    (the safer workflow per SoT §4.4 + the transcript "menajer kontrol
    ettim" double-check). Slot status is operational metadata the
    frontend renders per card.
    """

    ASSIGNED = "ASSIGNED", "Assigned"
    COMPLETED = "COMPLETED", "Completed"
    UNABLE_TO_COMPLETE = "UNABLE_TO_COMPLETE", "Unable to complete"
    CANCELLED = "CANCELLED", "Cancelled"


class TicketStaffAssignment(models.Model):
    """
    Sprint 23A — additive M:N between Ticket and STAFF user.

    The existing single `Ticket.assigned_to` FK stays as the legacy
    "primary assignee" the existing UI and tests read. This new
    through-style table lets a ticket carry multiple assigned
    staff at the same time (per the OSIUS workflow: "a job may have
    multiple staff; any one completing it moves it to manager
    review").

    Sprint 14E — DATED OPERATIONAL SLOTS (transcript: same planned
    work/day may carry a morning task for Ahmet and an evening task for
    Mehmet; each staff sees their own dated job, and the manager can
    split work into dated/time-window staff assignments). Each row now
    carries optional schedule metadata (`scheduled_start_at` /
    `scheduled_end_at` / `time_window_label`), an `assignment_note`, an
    assignment-level `slot_status`, and assignment-level completion
    evidence (`completion_note` / `completed_at` / `completed_by` /
    `unable_to_complete_reason`).

    Multi-slot per staff — the SAME staff member may now hold MULTIPLE
    dated slots on one ticket (transcript: Ahmet 09:00-11:00 AND Ahmet
    15:00-17:00). The old `unique_together(ticket, user)` constraint is
    therefore DROPPED: each slot is its own row keyed by `id`, and the
    detail / PATCH / DELETE endpoint is keyed by that slot `id`, not by
    the user. Both indexes are kept (the ticket+user list lookup and the
    user+scheduled_start_at "my slots" agenda query). Ahmet and Mehmet
    on the same date stay two rows exactly as before — that case never
    needed the constraint.

    Validation (enforced at serializer level, not via a DB check):
      - user.role MUST be UserRole.STAFF.
      - The user MUST hold BuildingStaffVisibility for ticket.building
        (or the assignment was created by a manager who can override).
    """

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="staff_assignments",
    )
    # Sprint 4 — optional placement into a named SubTask on the SAME
    # ticket. NULL = the ticket's default un-split work (today's
    # behaviour, full back-compat). on_delete=SET_NULL so deleting a
    # sub-task returns its slots (completion evidence intact) to the loose
    # pool — it NEVER deletes a staff assignment.
    sub_task = models.ForeignKey(
        "SubTask",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_assignments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ticket_staff_assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_assignments_made",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    # Sprint 14E — optional dated slot metadata. NULL/blank preserves the
    # pre-14E "flat assignment" semantics for every existing row + flow.
    scheduled_start_at = models.DateTimeField(null=True, blank=True, default=None)
    scheduled_end_at = models.DateTimeField(null=True, blank=True, default=None)
    time_window_label = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Free-text window hint, e.g. morning / afternoon / evening / 08:00-10:00.",
    )
    assignment_note = models.TextField(blank=True, default="")

    # Assignment-level lifecycle + completion evidence (additive; does
    # NOT drive the ticket state machine).
    slot_status = models.CharField(
        max_length=24,
        choices=StaffAssignmentSlotStatus.choices,
        default=StaffAssignmentSlotStatus.ASSIGNED,
    )
    completion_note = models.TextField(blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True, default=None)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_slots_completed",
    )
    unable_to_complete_reason = models.TextField(blank=True, default="")
    # W-VIEWER §10 — WHY SOMEBODY ELSE CLOSED THIS.
    #
    # A provider operator may finish a worker's slot for them (the
    # manager's part door, `views_sub_tasks.TicketSubTaskDoneView`, and
    # the slot PATCH). `completed_by` already records WHO pressed it;
    # this records WHY, and it is REQUIRED on that route. A worker
    # completing their own slot leaves it empty — they are not acting on
    # anybody's behalf and asking them for a reason would be asking them
    # to justify doing their job.
    #
    # Deliberately NOT `completion_note`: that field is the worker's own
    # evidence of a visit (the completion gate reads it), and an
    # operator's justification for closing a slot they did not work is a
    # different statement. Overloading one field with both is how a
    # completion gate ends up satisfied by an excuse.
    completed_on_behalf_reason = models.TextField(blank=True, default="")

    class Meta:
        # Multi-slot per staff — the (ticket, user) uniqueness was DROPPED
        # so one staff member can hold several dated slots on a ticket
        # (AM/PM / repeated windows). Each slot is its own row keyed by id;
        # the detail endpoint is keyed by the slot id. Both indexes stay.
        indexes = [
            models.Index(fields=["ticket", "user"]),
            # Sprint 14E — the staff agenda / "my slots" query is
            # (user, scheduled_start_at); index it.
            models.Index(fields=["user", "scheduled_start_at"]),
        ]

    def __str__(self):
        return f"{self.user.email} → {self.ticket}"


class TicketManagerAssignment(models.Model):
    """
    Sprint 10B — EXPLICIT per-ticket responsible-manager M:N (SoT §4.2).

    Mirrors `TicketStaffAssignment` exactly: a ticket may carry more
    than one responsible BUILDING_MANAGER at the same time, with each
    assignment recording who made it and when.

    Relationship to the two neighbouring concepts (do NOT conflate):

      * `Ticket.assigned_to` stays the LEGACY / compat single "primary
        manager" pointer. This new table does not change its meaning,
        does not remove it, and is not a replacement for it — the two
        coexist (the single pointer is still what the existing UI and
        the `assign` endpoint read/write).
      * `BuildingManagerAssignment` (buildings app) remains the
        BUILDING-LEVEL authority / visibility grant. Holding it is the
        eligibility precondition for being added here, but it is NOT
        itself per-ticket responsibility — a BM can be authoritative on
        a building without being a named responsible manager on a given
        ticket.

    Removal is a hard delete (mirrors `TicketStaffAssignment`): there is
    no soft-remove column, matching the existing membership pattern.

    Validation (enforced at the endpoint / serializer layer, not via a
    DB check, mirroring `TicketStaffAssignment`):
      - user.role MUST be UserRole.BUILDING_MANAGER.
      - The user MUST hold a `BuildingManagerAssignment` for
        ticket.building.
    """

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="manager_assignments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ticket_manager_assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manager_assignments_made",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("ticket", "user")]
        indexes = [models.Index(fields=["ticket", "user"])]

    def __str__(self):
        return f"{self.user.email} ⇒ {self.ticket}"


class AssignmentRequestStatus(models.TextChoices):
    """Sprint 23A — lifecycle of a staff-initiated assignment request."""

    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


class StaffAssignmentRequest(models.Model):
    """
    Sprint 23A — a STAFF user's "I want to do this work / assign me
    to this" request, awaiting BUILDING_MANAGER (or higher) review.

    Internal to the service-provider side. Never serialized for
    CUSTOMER_USER. A BUILDING_MANAGER may approve or reject
    requests for buildings they hold a BuildingManagerAssignment
    in; COMPANY_ADMIN and SUPER_ADMIN can act on any request.
    """

    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assignment_requests",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="assignment_requests",
    )
    status = models.CharField(
        max_length=16,
        choices=AssignmentRequestStatus.choices,
        default=AssignmentRequestStatus.PENDING,
    )

    requested_at = models.DateTimeField(auto_now_add=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_assignment_requests",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["status", "ticket"]),
            models.Index(fields=["staff", "status"]),
        ]

    def __str__(self):
        return f"{self.staff.email} → {self.ticket} ({self.status})"


class TicketEscalationStep(models.TextChoices):
    """W-LATE §2 — the three steps the ladder can speak."""

    #: The deadline has passed and the work is not done. Once per
    #: (ticket, deadline): the assigned managers.
    L2_MANAGERS = "L2_MANAGERS", "Deadline passed: assigned managers"
    #: Still not done a deadline-proportional step past the deadline.
    #: Once per (ticket, deadline): the building managers and the
    #: company admins.
    L2_ESCALATED = "L2_ESCALATED", "Deadline still passed: managers and admins"
    #: Thirty days past the anchor with not one hour booked. Once per
    #: ticket, ever: the provider admins. W-PLANTRUTH §1c renamed the
    #: rung "never done"; the STORED value and its label keep the old
    #: spelling on purpose — a changed choice is a schema migration, and
    #: this wave ships none. Only the attribute is renamed.
    L3_NEVER_DONE = "L3_QUARANTINE", "Quarantine: provider admins"


class TicketEscalation(models.Model):
    """W-LATE §2 — ONE ROW PER STEP THE LADDER HAS SPOKEN, per ticket.

    This is the escalation-state tracking the brief allowed: one small
    table, additive. It answers two questions nothing else could —

      * "has this step already fired for this ticket?" — the once-ever
        rule. The deadline reminder answers its equivalent by asking the
        notification tables ("was this person ever told about this
        ticket's deadline?"), and says in its own docstring what that
        costs: moving the deadline cannot re-arm it, because nothing
        recorded WHICH deadline was warned about. This row records it.
        `anchor_date` is the deadline the L2 steps were measured
        against, so a genuinely re-planned job (a new deadline) is a new
        (ticket, step, anchor) and fires again; the same deadline never
        fires twice. L3 carries no anchor: its clock only resets when
        hours land, and once hours land the rung itself is gone.

      * "when was the admin told, and who?" — the never-done modal's own
        line. `recipient_ids` is the list the step actually reached, so
        the bar renders the names of the people who were told, resolved
        at render time. Ids in a DATA row, never in code: recipients are
        resolved by ROLE inside the ticket's provider company every time
        the sweep runs.

    Deliberately NOT audited through `audit/signals.py`: the row IS the
    record of the event, in the same way a `*StatusHistory` row is, and a
    generic AuditLog beside it would be the doubling H-11 warns about.
    """

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="escalations",
    )
    step = models.CharField(max_length=16, choices=TicketEscalationStep.choices)
    #: The deadline the two L2 steps were measured against; NULL for L3.
    anchor_date = models.DateField(null=True, blank=True)
    notified_at = models.DateTimeField(default=timezone.now)
    #: The user ids the step reached, in the order they were told.
    recipient_ids = models.JSONField(default=list, blank=True)
    recipient_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            # The two L2 steps: once per ticket per deadline. Postgres
            # treats NULLs as distinct in a unique index, so this does
            # not bind the L3 row — `escalations.py` guards that one by
            # (ticket, step) in code, which is also the only writer.
            models.UniqueConstraint(
                fields=["ticket", "step", "anchor_date"],
                name="ticket_escalation_once_per_step_and_anchor",
            ),
        ]
        indexes = [models.Index(fields=["ticket", "step"])]
        ordering = ["notified_at", "id"]

    def __str__(self):
        return f"{self.step} for ticket {self.ticket_id} at {self.notified_at:%Y-%m-%d}"
