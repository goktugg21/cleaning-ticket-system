"""RF-1 Part A — profile photo upload / delete / serve.

Covers the hardcoded write rule (own photo self-service; SUPER_ADMIN may
change any; everyone else 403) plus the shared image validator's
content/MIME/size rejections (this is the primary validator test — the
customer/company logo suites reuse the same validator, so they only
sanity-check one rejection each).
"""
from __future__ import annotations

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User, UserRole
from test_utils import TenantFixtureMixin, make_fake_upload, make_image_upload


def photo_url(user_id):
    return f"/api/users/{user_id}/photo/"


class ProfilePhotoPermissionTests(TenantFixtureMixin, APITestCase):
    def test_user_can_set_own_photo(self):
        self.authenticate(self.customer_user)
        resp = self.client.post(
            photo_url(self.customer_user.id),
            {"file": make_image_upload()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["profile_photo_url"])
        self.customer_user.refresh_from_db()
        self.assertTrue(self.customer_user.profile_photo)

    def test_user_cannot_set_another_users_photo(self):
        self.authenticate(self.customer_user)
        resp = self.client.post(
            photo_url(self.company_admin.id),
            {"file": make_image_upload()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.company_admin.refresh_from_db()
        self.assertFalse(self.company_admin.profile_photo)

    def test_super_admin_can_set_any_photo(self):
        self.authenticate(self.super_admin)
        resp = self.client.post(
            photo_url(self.company_admin.id),
            {"file": make_image_upload()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.company_admin.refresh_from_db()
        self.assertTrue(self.company_admin.profile_photo)

    def test_company_admin_cannot_set_another_users_photo(self):
        self.authenticate(self.company_admin)
        resp = self.client.post(
            photo_url(self.manager.id),
            {"file": make_image_upload()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_delete_own_photo(self):
        self.customer_user.profile_photo = make_image_upload()
        self.customer_user.save(update_fields=["profile_photo"])
        self.authenticate(self.customer_user)
        resp = self.client.delete(photo_url(self.customer_user.id))
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.customer_user.refresh_from_db()
        self.assertFalse(self.customer_user.profile_photo)

    def test_other_user_cannot_delete_photo(self):
        self.company_admin.profile_photo = make_image_upload()
        self.company_admin.save(update_fields=["profile_photo"])
        self.authenticate(self.customer_user)
        resp = self.client.delete(photo_url(self.company_admin.id))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.company_admin.refresh_from_db()
        self.assertTrue(self.company_admin.profile_photo)


class ProfilePhotoServingTests(TenantFixtureMixin, APITestCase):
    def test_serve_returns_the_blob(self):
        self.customer_user.profile_photo = make_image_upload()
        self.customer_user.save(update_fields=["profile_photo"])
        # Any authenticated active user may fetch an avatar.
        self.authenticate(self.other_customer_user)
        resp = self.client.get(photo_url(self.customer_user.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_serve_missing_photo_is_404_not_403(self):
        self.authenticate(self.other_customer_user)
        resp = self.client.get(photo_url(self.customer_user.id))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_serve_requires_auth(self):
        resp = self.client.get(photo_url(self.customer_user.id))
        self.assertIn(
            resp.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_me_endpoint_exposes_photo_url(self):
        self.customer_user.profile_photo = make_image_upload()
        self.customer_user.save(update_fields=["profile_photo"])
        self.authenticate(self.customer_user)
        resp = self.client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["profile_photo_url"])
        self.assertIn("/photo/", resp.data["profile_photo_url"])

    def test_me_endpoint_null_when_no_photo(self):
        self.authenticate(self.customer_user)
        resp = self.client.get("/api/auth/me/")
        self.assertIsNone(resp.data["profile_photo_url"])


class ImageValidatorRejectionTests(TenantFixtureMixin, APITestCase):
    def _post(self, upload):
        self.authenticate(self.customer_user)
        return self.client.post(
            photo_url(self.customer_user.id),
            {"file": upload},
            format="multipart",
        )

    def test_accepts_jpeg_and_webp(self):
        for fmt, ct, name in (
            ("JPEG", "image/jpeg", "a.jpg"),
            ("WEBP", "image/webp", "a.webp"),
        ):
            resp = self._post(make_image_upload(name=name, fmt=fmt, content_type=ct))
            self.assertEqual(
                resp.status_code, status.HTTP_200_OK, f"{fmt} should be accepted"
            )

    def test_rejects_disallowed_extension(self):
        resp = self._post(make_image_upload(name="a.gif", content_type="image/gif"))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_pdf_renamed_as_png(self):
        # Declared image/png + .png, but the bytes are not an image.
        resp = self._post(make_fake_upload("evil.png", "image/png", b"%PDF-1.4 fake"))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("file", resp.data)

    def test_rejects_extension_mime_mismatch(self):
        # A real PNG announced as .jpg — extension/MIME disagree.
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="PNG")
        upload = SimpleUploadedFile("a.jpg", buf.getvalue(), content_type="image/jpeg")
        resp = self._post(upload)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_oversize(self):
        # Unit-level: the multipart client recomputes `size` from the real
        # bytes, so the size gate is exercised against the validator
        # directly (it checks size before decoding any content).
        from rest_framework import serializers as drf_serializers

        from accounts.image_uploads import MAX_IMAGE_SIZE, validate_image_upload

        oversized = make_image_upload()
        oversized.size = MAX_IMAGE_SIZE + 1
        with self.assertRaises(drf_serializers.ValidationError) as ctx:
            validate_image_upload(oversized)
        self.assertEqual(ctx.exception.detail[0].code, "image_too_large")
