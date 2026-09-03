from rest_framework import serializers

from .copy import render_summary, resolve_lang, title_for_event
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Read-only serializer for the in-app notification feed (M1 B1).

    The feed is entirely read-only — recipients never POST a notification;
    they only list / mark-read. Deep-link routing is derived by the FE from
    whichever source id is set: `ticket` -> /tickets/<id>,
    `extra_work` -> /extra-work/<id> (B4).

    P-16 Part D (§D.13.3) — the copy is resolved HERE, per viewer:
    `summary` re-renders from the row's `template_key` + `params` in the
    VIEWER's language (falling back to the stored cache for old rows or
    a failed render), and `title` is the warning headline the frontend
    used to translate client-side. The SPA never composes copy from
    parts (SoT §11.1).
    """

    actor_id = serializers.SerializerMethodField()
    actor_name = serializers.SerializerMethodField()
    actor_email = serializers.SerializerMethodField()
    ticket_no = serializers.SerializerMethodField()
    ticket_title = serializers.SerializerMethodField()
    extra_work_title = serializers.SerializerMethodField()
    is_read = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "event_type",
            "is_directed",
            "summary",
            # P-16 Part D — the warning headline, resolved per viewer
            # (null for the kinds whose headline is the job's own name).
            "title",
            # W-LATE addendum 2 — the rung, so the bell and the list can
            # colour the row without a client-side lookup table.
            "severity",
            "ticket",
            "ticket_no",
            "ticket_title",
            "extra_work",
            "extra_work_title",
            "actor_id",
            "actor_name",
            "actor_email",
            "read_at",
            "is_read",
            "created_at",
        ]
        read_only_fields = fields

    def _viewer_lang(self):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return resolve_lang(getattr(user, "language", "nl"))

    def get_summary(self, obj):
        # A keyed row re-renders in the viewer's language; a row without
        # a key (pre-P-16) keeps printing its stored text, and so does a
        # keyed row whose render fails — the cache is the floor.
        if obj.template_key:
            rendered = render_summary(
                obj.template_key, obj.params or {}, self._viewer_lang()
            )
            if rendered:
                return rendered
        return obj.summary

    def get_title(self, obj):
        return title_for_event(obj.event_type, self._viewer_lang())

    def get_actor_id(self, obj):
        return obj.actor_id

    def get_actor_name(self, obj):
        actor = obj.actor
        if not actor:
            return None
        return actor.full_name or (actor.email.split("@")[0] if actor.email else None)

    def get_actor_email(self, obj):
        return obj.actor.email if obj.actor else None

    def get_ticket_no(self, obj):
        return obj.ticket.ticket_no if obj.ticket_id else None

    def get_ticket_title(self, obj):
        return obj.ticket.title if obj.ticket_id else None

    def get_extra_work_title(self, obj):
        return obj.extra_work.title if obj.extra_work_id else None

    def get_is_read(self, obj):
        return obj.read_at is not None
