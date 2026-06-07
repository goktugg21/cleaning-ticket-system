from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Read-only serializer for the in-app notification feed (M1 B1).

    The feed is entirely read-only — recipients never POST a notification;
    they only list / mark-read. Deep-link routing is derived by the FE from
    whichever source id is set: `ticket` -> /tickets/<id>,
    `extra_work` -> /extra-work/<id> (B4).
    """

    actor_id = serializers.SerializerMethodField()
    actor_name = serializers.SerializerMethodField()
    actor_email = serializers.SerializerMethodField()
    ticket_no = serializers.SerializerMethodField()
    ticket_title = serializers.SerializerMethodField()
    extra_work_title = serializers.SerializerMethodField()
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "event_type",
            "is_directed",
            "summary",
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
