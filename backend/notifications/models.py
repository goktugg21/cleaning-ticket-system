from django.conf import settings
from django.db import models
from django.utils import timezone


class NotificationEventType(models.TextChoices):
    TICKET_CREATED = "TICKET_CREATED", "Ticket created"
    TICKET_STATUS_CHANGED = "TICKET_STATUS_CHANGED", "Ticket status changed"
    TICKET_ASSIGNED = "TICKET_ASSIGNED", "Ticket assigned"
    TICKET_UNASSIGNED = "TICKET_UNASSIGNED", "Ticket unassigned"
    # Sprint 12 — a staff member reported a dated SLOT as unable-to-complete
    # (slot_status=UNABLE_TO_COMPLETE on the slot PATCH). Unlike the
    # ticket-level unable flow this does NOT change ticket status, so the
    # status-change email never fires; the provider managers are notified
    # via a dedicated event so they can reschedule. Deliberately NOT in
    # USER_MUTABLE_EVENT_TYPES — operational follow-up must always reach
    # the managers.
    TICKET_SLOT_UNABLE = "TICKET_SLOT_UNABLE", "Staff slot unable to complete"
    PASSWORD_RESET = "PASSWORD_RESET", "Password reset"
    INVITATION_SENT = "INVITATION_SENT", "Invitation sent"
    # Sprint 183 §3 — the nightly invoice run finished and created
    # drafts. Sprint 182 wrote this value as a bare string constant in
    # `invoicing/tasks.py` because that agent did not own this file: the
    # rows persisted and the mails sent, but the value sat outside the
    # enum, so `get_event_type_display()` returned the raw string and any
    # label lookup showed "INVOICE_RUN_COMPLETED" instead of a name.
    #
    # Deliberately NOT in USER_MUTABLE_EVENT_TYPES: an operator who muted
    # this would stop hearing that their month's invoices were drafted,
    # and the drafts would then sit unsent. Like TICKET_SLOT_UNABLE it is
    # operational follow-up that has to arrive.
    INVOICE_RUN_COMPLETED = (
        "INVOICE_RUN_COMPLETED",
        "Invoice run completed",
    )
    # Sprint 185 §2 — an invoice was SENT and the document went out.
    #
    # Distinct from INVOICE_RUN_COMPLETED above, which says drafts were
    # created and goes to the operator. This one carries the PDF and goes
    # to the debtor's people, so "did they get it" is answered by its own
    # log rows rather than inferred from a run notification.
    #
    # Like its sibling, deliberately NOT user-mutable: a recipient who
    # muted this would stop receiving invoices and nobody would know.
    INVOICE_SENT = ("INVOICE_SENT", "Invoice sent")

    # ------------------------------------------------------------------
    # Sprint W1-B §2.7 — the TIME-DRIVEN family.
    #
    # Every event type above this line is a reaction: something happened,
    # somebody is told. "Nothing happened and it should have" was an
    # empty category — the SLA engine ran every five minutes over every
    # live ticket, wrote a status column, and notified nobody. These
    # three are the first members of that category, emitted by
    # `sla.warnings.sweep` rather than by a user action.
    #
    # All three are deliberately NOT in USER_MUTABLE_EVENT_TYPES. A
    # warning exists precisely because nobody is looking; a mute switch
    # on it would silence the one message whose whole purpose is to
    # arrive unasked.
    # ------------------------------------------------------------------
    #: Work is finished and sitting with the customer while their billing
    #: cutoff approaches. Under the cutoff rule it will be invoiced on
    #: that date whether or not their approval has landed, so this is the
    #: warning that makes the rule fair.
    SLA_APPROVAL_CUTOFF_DUE = (
        "SLA_APPROVAL_CUTOFF_DUE",
        "Customer approval due before billing cutoff",
    )
    #: Staff reported the work done and it has been waiting on a
    #: provider manager's check longer than the target.
    SLA_MANAGER_REVIEW_OVERDUE = (
        "SLA_MANAGER_REVIEW_OVERDUE",
        "Manager review overdue",
    )
    #: The planned start has passed and the work has not started.
    SLA_WORK_NOT_STARTED = (
        "SLA_WORK_NOT_STARTED",
        "Planned work has not started",
    )

    # ------------------------------------------------------------------
    # W-N1 — two more machine-sent types, spelled identically in the
    # in-app enum below for the same reason the SLA three are: the
    # cooldown query keys BOTH tables off one `event_type` string, so a
    # divergence here silently unthrottles one channel.
    # ------------------------------------------------------------------
    #: A ticket's deadline is inside the warning window and the work is
    #: not finished. Sent ONCE per ticket per person, not daily.
    TICKET_DEADLINE_APPROACHING = (
        "TICKET_DEADLINE_APPROACHING",
        "Ticket deadline approaching",
    )
    #: Somebody was put on a PART of a ticket. Not sent when they put
    #: themselves there.
    TICKET_PART_ASSIGNED = (
        "TICKET_PART_ASSIGNED",
        "Ticket part assigned",
    )

    # ------------------------------------------------------------------
    # W-LATE §2 — the ladder speaks. Three steps, each sent ONCE per
    # ticket per step (per deadline for the two L2 steps: a genuinely
    # re-planned job restarts them from its new date). Spelled
    # identically in the in-app enum below, like the SLA three, so one
    # `event_type` string keys both channels.
    # ------------------------------------------------------------------
    #: The deadline has passed and the work is not done: the ticket's
    #: ASSIGNED MANAGERS are told.
    TICKET_LATE_L2_MANAGERS = (
        "TICKET_LATE_L2_MANAGERS",
        "Deadline passed: assigned managers notified",
    )
    #: Still not done a deadline-proportional step past the deadline:
    #: the building managers AND the company admins are told.
    TICKET_LATE_L2_ESCALATED = (
        "TICKET_LATE_L2_ESCALATED",
        "Deadline still passed: managers and admins notified",
    )
    #: Thirty days past the anchor with not one hour booked: the
    #: PROVIDER ADMINS are told.
    TICKET_LATE_L3_QUARANTINE = (
        "TICKET_LATE_L3_QUARANTINE",
        "Quarantine: provider admins notified",
    )


class NotificationStatus(models.TextChoices):
    QUEUED = "QUEUED", "Queued"
    SENT = "SENT", "Sent"
    FAILED = "FAILED", "Failed"
    SKIPPED = "SKIPPED", "Skipped"


class NotificationLog(models.Model):
    ticket = models.ForeignKey(
        "tickets.Ticket",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_logs",
    )
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_notification_logs",
    )
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_notification_logs",
    )

    # Sprint W1-B §2.7 — the Extra Work this log row is about, when it is
    # about one. Mirrors the in-app `Notification.extra_work` FK, and it
    # exists for the same reason the `ticket` FK above does: the
    # time-driven warning sweep has to answer "have I already told this
    # person about THIS work today?" before it sends, and a repeating
    # task with no per-subject key would either re-send every five
    # minutes or have to match on subject text. An Extra Work that has
    # not spawned an operational ticket yet has no `ticket` to key on.
    extra_work = models.ForeignKey(
        "extra_work.ExtraWorkRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_logs",
    )

    recipient_email = models.EmailField()
    event_type = models.CharField(max_length=64, choices=NotificationEventType.choices)
    subject = models.CharField(max_length=255)
    body = models.TextField()

    status = models.CharField(
        max_length=32,
        choices=NotificationStatus.choices,
        default=NotificationStatus.SENT,
    )
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} → {self.recipient_email} ({self.status})"

    def mark_sent(self):
        self.status = NotificationStatus.SENT
        self.error_message = ""
        self.sent_at = timezone.now()
        self.save(update_fields=["status", "error_message", "sent_at"])

    def mark_failed(self, message):
        self.status = NotificationStatus.FAILED
        self.error_message = str(message)
        self.sent_at = None
        self.save(update_fields=["status", "error_message", "sent_at"])

    def mark_queued(self):
        self.status = NotificationStatus.QUEUED
        self.save(update_fields=["status"])


class NotificationType(models.TextChoices):
    """In-app (bell / message-center) notification event types.

    Deliberately SEPARATE from the email `NotificationEventType` above:
    in-app notifications are a different surface with a different lifecycle
    (no SMTP, no NotificationLog, read/unread per recipient). Overloading
    the email enum here would conflate the two channels. B1 ships
    TICKET_MESSAGE; B4 adds the Extra Work lifecycle event types below.
    """

    TICKET_MESSAGE = "TICKET_MESSAGE", "Ticket message"

    # M1 B4 — Extra Work lifecycle (in-app only; no email path is added).
    #   EXTRA_WORK_REQUESTED      a new EW request needs provider attention.
    #   EXTRA_WORK_PROPOSAL_SENT  a quote/proposal was sent; customer decides.
    #   EXTRA_WORK_DECISION       the customer approved OR rejected. ONE type:
    #     the approved-vs-rejected distinction is carried in the row `summary`
    #     (and the deep-linked EW status), not in a separate event_type. A
    #     single type keeps the FE bell/page rendering generic and avoids a
    #     migration churn pair where one would do.
    EXTRA_WORK_REQUESTED = "EXTRA_WORK_REQUESTED", "Extra work requested"
    EXTRA_WORK_PROPOSAL_SENT = (
        "EXTRA_WORK_PROPOSAL_SENT",
        "Extra work proposal sent",
    )
    EXTRA_WORK_DECISION = "EXTRA_WORK_DECISION", "Extra work decision"

    # M1 B6 — Extra Work message thread (mirrors TICKET_MESSAGE, in-app only).
    #   EXTRA_WORK_MESSAGE    a new message on an Extra Work request thread.
    #   EXTRA_WORK_PUBLISHED  item-7: a provider direct-published (quote-bypass)
    #     the customer's extra work WITHOUT a separate decision step — the
    #     customer is told it was approved/started.
    EXTRA_WORK_MESSAGE = "EXTRA_WORK_MESSAGE", "Extra work message"
    EXTRA_WORK_PUBLISHED = "EXTRA_WORK_PUBLISHED", "Extra work published"

    # ------------------------------------------------------------------
    # Sprint W4-Q §1 — the TIME-DRIVEN family reaches the bell.
    #
    # Sprint W1-B built these three as EMAIL ONLY and said so plainly:
    # the in-app feed is a different model with its own enum and its own
    # read/unread lifecycle, and bolting it on in the same sprint would
    # have meant guessing at the cooldown. This is that half.
    #
    # THE VALUES ARE DELIBERATELY IDENTICAL to their `NotificationEvent
    # Type` siblings, and they are the first three that are. One warning
    # crossing two channels is ONE event, and giving the bell copy a
    # different spelling would mean every reader — the cooldown query,
    # the feed UI, an operator reading the two tables side by side — had
    # to carry a translation table between two names for one thing.
    #
    # The one place that could bite is `NotificationPreference.
    # event_type`, which stores values from BOTH enums in a single
    # column and until now relied on them never colliding. None of these
    # three is user-mutable in EITHER direction (see
    # USER_MUTABLE_EVENT_TYPES / USER_MUTABLE_INAPP_EVENT_TYPES below),
    # so no preference row can ever exist for them and the ambiguity
    # cannot arise. `notifications/tests/test_sla_inapp.py` asserts that
    # invariant so it fails loudly the day somebody makes one mutable
    # rather than silently muting the wrong channel.
    # ------------------------------------------------------------------
    SLA_APPROVAL_CUTOFF_DUE = (
        "SLA_APPROVAL_CUTOFF_DUE",
        "Customer approval due before billing cutoff",
    )
    SLA_MANAGER_REVIEW_OVERDUE = (
        "SLA_MANAGER_REVIEW_OVERDUE",
        "Manager review overdue",
    )
    SLA_WORK_NOT_STARTED = (
        "SLA_WORK_NOT_STARTED",
        "Planned work has not started",
    )
    # W-N1 — spelled exactly as in `NotificationEventType` above.
    TICKET_DEADLINE_APPROACHING = (
        "TICKET_DEADLINE_APPROACHING",
        "Ticket deadline approaching",
    )
    TICKET_PART_ASSIGNED = (
        "TICKET_PART_ASSIGNED",
        "Ticket part assigned",
    )
    # W-LATE §2 — spelled exactly as in `NotificationEventType` above.
    TICKET_LATE_L2_MANAGERS = (
        "TICKET_LATE_L2_MANAGERS",
        "Deadline passed: assigned managers notified",
    )
    TICKET_LATE_L2_ESCALATED = (
        "TICKET_LATE_L2_ESCALATED",
        "Deadline still passed: managers and admins notified",
    )
    TICKET_LATE_L3_QUARANTINE = (
        "TICKET_LATE_L3_QUARANTINE",
        "Quarantine: provider admins notified",
    )


class NotificationSeverity(models.TextChoices):
    """W-LATE addendum 2 — THE SEVERITY ON THE NOTIFICATION ITSELF.

    Recon: `Notification` carried no level or kind of its own; the only
    "kind" was `event_type`, and the bell decided "warning or activity"
    by looking the type up in a client-side list. That is fine for a
    family whose members are all the same shade, and wrong for a ladder
    whose whole point is that L2 is not L1. So the row says which rung
    it is, and the bell, the list and the toast read the row.

    INFO is the default and what every pre-existing activity row means.
    L1 is the standard warning tone (orange) — the migration backfills
    the four time-driven types that already existed onto it, so a row
    that rendered as a warning yesterday renders as the same warning
    today for the same reason. L2 is red; L3 is dark red and its toast
    stays until dismissed.
    """

    INFO = "INFO", "Information"
    L1 = "L1", "Level 1 — plan passed"
    L2 = "L2", "Level 2 — deadline passed"
    L3 = "L3", "Level 3 — quarantine"


#: The three time-driven in-app types, for readers that need to ask "is
#: this row a warning?" without repeating the list. A MODULE constant
#: rather than a class attribute: anything hung off a `TextChoices` body
#: risks being read as a fourth choice by the metaclass, and one enum
#: with a phantom member is a migration that never stops churning.
SLA_WARNING_INAPP_TYPES = frozenset(
    {
        NotificationType.SLA_APPROVAL_CUTOFF_DUE,
        NotificationType.SLA_MANAGER_REVIEW_OVERDUE,
        NotificationType.SLA_WORK_NOT_STARTED,
    }
)

#: W-LATE §2 — the three escalation steps, for the same reason.
LATE_ESCALATION_INAPP_TYPES = frozenset(
    {
        NotificationType.TICKET_LATE_L2_MANAGERS,
        NotificationType.TICKET_LATE_L2_ESCALATED,
        NotificationType.TICKET_LATE_L3_QUARANTINE,
    }
)

#: The rows the severity backfill lifts from INFO to L1: everything
#: machine-sent before the ladder existed that the bell already rendered
#: as a warning, plus the deadline reminder, which is the same kind of
#: thing (nothing happened yet, and it is about to matter).
SEVERITY_L1_BACKFILL_TYPES = frozenset(
    SLA_WARNING_INAPP_TYPES | {NotificationType.TICKET_DEADLINE_APPROACHING}
)


class Notification(models.Model):
    """In-app notification (M1 — message center, phase B1).

    One row per (recipient, triggering event). Distinct from
    `NotificationLog`, which is the EMAIL audit/delivery log. A
    `Notification` is purely an in-app signal: it is created when a
    ticket message (B1) — and later an Extra Work event (B4) — needs the
    recipient's attention, and it is dismissed by setting `read_at`.

    Source / deep-link reference (FE route derivation): a nullable
    `ticket` FK covers both ticket and *melding* (a melding IS a ticket),
    and a nullable `extra_work` FK is added forward-compatibly for B4
    (unused in B1). The FE derives the route from whichever FK is set:
    `ticket` -> /tickets/<id>, `extra_work` -> /extra-work/<id>. Explicit
    FKs (over a (source_kind, source_id) pair) keep referential integrity
    and allow cheap select_related for the feed.
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_index=True,
        related_name="notifications",
    )
    # Who triggered the notification (message author / actor). SET_NULL so
    # deleting the actor never destroys the recipient's notification.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emitted_notifications",
    )

    event_type = models.CharField(
        max_length=32,
        choices=NotificationType.choices,
    )

    # True when this recipient was personally named in the message's
    # `directed_to` set (FE renders "directed to you"). For a NORMAL
    # message the directed recipients are a flagged subset of the audience;
    # for a RESTRICTED message they ARE the audience.
    is_directed = models.BooleanField(default=False)

    # Deep-link source. Exactly one is set in B1 (ticket). CASCADE: an
    # in-app notification is an ephemeral UX signal, not the audit trail
    # (the AuditLog / *StatusHistory rows are), so if the source row is
    # ever hard-deleted its now-dead deep-links go with it.
    ticket = models.ForeignKey(
        "tickets.Ticket",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="inapp_notifications",
    )
    extra_work = models.ForeignKey(
        "extra_work.ExtraWorkRequest",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="inapp_notifications",
    )

    # Short denormalised display line (author label + truncated body). Only
    # content the recipient is already allowed to see is stored here (the
    # recipient set is the message's visible audience), so this carries no
    # PII the recipient could not already read on the ticket.
    summary = models.CharField(max_length=500, blank=True, default="")

    # W-LATE addendum 2 — which rung, if any. See `NotificationSeverity`.
    # Additive: the default is INFO and the migration backfills the four
    # pre-existing time-driven types to L1.
    severity = models.CharField(
        max_length=4,
        choices=NotificationSeverity.choices,
        default=NotificationSeverity.INFO,
    )

    # NULL = unread. Set to now() when the recipient marks it read.
    read_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "read_at"]),
        ]

    def __str__(self):
        state = "read" if self.read_at else "unread"
        return f"{self.event_type} -> {self.recipient_id} ({state})"


class NotificationPreference(models.Model):
    """Per-user mute toggle for a notification event type.

    EMAIL types (USER_MUTABLE_EVENT_TYPES): absence of a row is the
    default (unmuted). A row with muted=True silences that event for the
    user. Transactional types (PASSWORD_RESET, INVITATION_SENT) are never
    read from this table — those mails always go out for security and
    onboarding reasons.

    IN-APP FEED types (IA 2026-06-25, USER_MUTABLE_INAPP_EVENT_TYPES):
    the polarity is INVERTED — absence of a row means MUTED. Message
    events (TICKET_MESSAGE / EXTRA_WORK_MESSAGE) left the notification
    feed by default because they duplicate the Berichten inbox; a row
    with muted=False is an explicit opt-in that brings them back.
    Suppression is READ-time (the feed/count chokepoint in views.py),
    not emit-time: rows keep being written, so an opt-in also restores
    history, no data migration was needed to cover existing users, and
    DIRECTED rows (is_directed=True — someone explicitly addressed you)
    always show regardless of this preference.
    """

    USER_MUTABLE_EVENT_TYPES = (
        NotificationEventType.TICKET_CREATED,
        NotificationEventType.TICKET_STATUS_CHANGED,
        NotificationEventType.TICKET_ASSIGNED,
        NotificationEventType.TICKET_UNASSIGNED,
    )

    # In-app feed toggles (default OFF — see docstring). Stored in the
    # same table; the NotificationType values cannot collide with the
    # email enum's values.
    USER_MUTABLE_INAPP_EVENT_TYPES = (
        NotificationType.TICKET_MESSAGE,
        NotificationType.EXTRA_WORK_MESSAGE,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    event_type = models.CharField(
        max_length=64,
        choices=(
            NotificationEventType.choices
            + [
                (NotificationType.TICKET_MESSAGE, "Ticket message (in-app feed)"),
                (
                    NotificationType.EXTRA_WORK_MESSAGE,
                    "Extra work message (in-app feed)",
                ),
            ]
        ),
    )
    muted = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "event_type")
        indexes = [
            models.Index(fields=["user", "event_type"]),
        ]

    def __str__(self):
        state = "muted" if self.muted else "unmuted"
        return f"{self.user_id}/{self.event_type} → {state}"


class MessageReadCursor(models.Model):
    """RF-1 — a per-user, per-thread high-watermark for the message inbox.

    One row = "this user has read <thread>'s messages up to
    `last_read_at`". A thread is EITHER a ticket OR an Extra Work request
    (exactly one FK set — the CheckConstraint enforces it). The inbox
    computes a thread's unread count as the number of viewer-VISIBLE
    messages newer than this cursor (excluding the viewer's own), so the
    cursor is the aggregated sibling of `Notification.read_at` (which is
    per-notification): advancing the cursor to now() marks the whole
    thread read for that user.

    Kept in the notifications app because it is the cross-cutting
    attention/read-state module (it already owns `Notification` with the
    same nullable ticket/extra_work dual-FK shape and a read_at surface).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="message_read_cursors",
    )
    ticket = models.ForeignKey(
        "tickets.Ticket",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="message_read_cursors",
    )
    extra_work = models.ForeignKey(
        "extra_work.ExtraWorkRequest",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="message_read_cursors",
    )
    last_read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            # Exactly one target — a cursor points at a ticket XOR an EW.
            models.CheckConstraint(
                name="mrc_exactly_one_target",
                check=(
                    models.Q(ticket__isnull=False, extra_work__isnull=True)
                    | models.Q(ticket__isnull=True, extra_work__isnull=False)
                ),
            ),
            # One cursor per (user, thread).
            models.UniqueConstraint(
                fields=["user", "ticket"],
                condition=models.Q(ticket__isnull=False),
                name="mrc_unique_user_ticket",
            ),
            models.UniqueConstraint(
                fields=["user", "extra_work"],
                condition=models.Q(extra_work__isnull=False),
                name="mrc_unique_user_extra_work",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "ticket"]),
            models.Index(fields=["user", "extra_work"]),
        ]

    def __str__(self):
        target = f"ticket={self.ticket_id}" if self.ticket_id else f"ew={self.extra_work_id}"
        return f"cursor u={self.user_id} {target} @ {self.last_read_at:%Y-%m-%d %H:%M}"


class SuperAdminCompanySubscription(models.Model):
    """#109 Part D — a SUPER_ADMIN's opt-in to ONE provider company's
    in-app notification stream.

    By default the in-app fan-out deliberately excludes SUPER_ADMIN
    (email-path parity; SA can read everything directly). This row is
    the explicit opt-in: while it exists, the four in-app
    provider-management emit paths (ticket messages, EW requested, EW
    decision, EW messages) union the subscribed SA into their recipient
    set for events of that company. The EMAIL path is untouched, and
    the role gate lives at the endpoint (only a SUPER_ADMIN can create
    a row for themselves) plus in `subscribed_super_admins`, which
    filters on role at read time — a stale row for a demoted user is
    inert.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sa_company_subscriptions",
    )
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="sa_subscriptions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Sprint 122 (Part C) — a SEPARATE opt-in for EMAIL delivery of the
    # provider-management emails (TICKET_CREATED / TICKET_STATUS_CHANGED /
    # TICKET_SLOT_UNABLE), owner-decided: subscribing to the in-app stream
    # above must NOT silently start emailing this SA. Defaults to False, so
    # an existing row (and a freshly created one) never emails until the SA
    # explicitly flips this on. Lives on this row deliberately — unsubscribing
    # (deleting the row) also forgets the email preference, since there is no
    # longer any subscription for it to modify.
    email_enabled = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "company"],
                name="uniq_sa_company_subscription",
            )
        ]

    def __str__(self):
        return f"SA #{self.user_id} subscribed to company #{self.company_id}"
