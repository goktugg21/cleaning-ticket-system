from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        # Sprint 27F-B2 (G-B6): explicit list — appending `reason` and
        # `actor_scope` so the new audit columns surface on the read API
        # alongside the existing fields. Both are read-only (the audit
        # log is immutable from the API's perspective).
        fields = [
            "id",
            "actor",
            "actor_email",
            "action",
            "target_model",
            "target_id",
            "changes",
            "created_at",
            "request_ip",
            "request_id",
            "reason",
            "actor_scope",
        ]
        read_only_fields = fields

    def get_actor_email(self, obj):
        return obj.actor.email if obj.actor_id else None
