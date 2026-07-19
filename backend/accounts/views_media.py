"""RF-1 — profile-photo upload / delete / serve.

  GET    /api/users/<user_id>/photo/   serve the avatar blob (any active user)
  POST   /api/users/<user_id>/photo/   upload  (self OR SUPER_ADMIN)
  DELETE /api/users/<user_id>/photo/   remove  (self OR SUPER_ADMIN)

Serving is deliberately open to any authenticated active user: avatars
surface all over the app (message authors, inbox rows, assigned staff)
and carry no sensitive content — the sensitive control is WHO MAY SET a
photo, which is the hardcoded rule enforced on write. The gate mirrors
the credential-download shape: a failed WRITE gate is 403 (the caller
knows the target exists — they're managing it); a missing file on GET is
404 (no existence leak, same as attachment downloads).

Audit: `User` is covered by the generic audit trio, so the save/clear of
`profile_photo` is diffed automatically; we set a reason for the row.
"""
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from audit import context as audit_context

from .image_uploads import ImageUploadSerializer
from .models import User, UserRole
from .permissions import IsAuthenticatedAndActive


def _may_manage_photo(actor, target: User) -> bool:
    # Hardcoded rule: any user sets their OWN photo; SUPER_ADMIN sets any.
    return actor.id == target.id or actor.role == UserRole.SUPER_ADMIN


class UserPhotoView(APIView):
    permission_classes = [IsAuthenticatedAndActive]
    parser_classes = [MultiPartParser, FormParser]

    def _target(self, user_id) -> User:
        return get_object_or_404(
            User, pk=user_id, deleted_at__isnull=True
        )

    def get(self, request, user_id):
        target = self._target(user_id)
        if not target.profile_photo:
            raise Http404("No photo.")
        return FileResponse(target.profile_photo.open("rb"))

    def post(self, request, user_id):
        target = self._target(user_id)
        if not _may_manage_photo(request.user, target):
            return Response(
                {"detail": "You may not change this photo."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = ImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        audit_context.set_current_reason("profile_photo_upload")
        # Drop any prior file so we don't orphan storage on replace.
        if target.profile_photo:
            target.profile_photo.delete(save=False)
        target.profile_photo = serializer.validated_data["file"]
        target.save(update_fields=["profile_photo"])
        return Response(
            {"profile_photo_url": _photo_url(request, target)},
            status=status.HTTP_200_OK,
        )

    def delete(self, request, user_id):
        target = self._target(user_id)
        if not _may_manage_photo(request.user, target):
            return Response(
                {"detail": "You may not change this photo."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if target.profile_photo:
            audit_context.set_current_reason("profile_photo_remove")
            target.profile_photo.delete(save=False)
            target.profile_photo = None
            target.save(update_fields=["profile_photo"])
        return Response(status=status.HTTP_204_NO_CONTENT)


def _photo_url(request, user: User):
    from .media_urls import profile_photo_url

    return profile_photo_url(user, request)
