from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import TicketAttachment, TicketMessage, TicketMessageType


@override_settings(MEDIA_ROOT="/tmp/cleaning-ticket-test-media")
class TicketAttachmentTests(TenantFixtureMixin, APITestCase):
    def upload_file(self, name="test.pdf", content=b"%PDF-1.4", content_type="application/pdf", **extra):
        data = {
            "file": SimpleUploadedFile(name, content, content_type=content_type),
            **extra,
        }
        return self.client.post(f"/api/tickets/{self.ticket.id}/attachments/", data, format="multipart")

    def test_customer_cannot_upload_hidden_attachment(self):
        self.authenticate(self.customer_user)
        response = self.upload_file(is_hidden=True)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_customer_cannot_view_hidden_attachments(self):
        hidden = TicketAttachment.objects.create(
            ticket=self.ticket,
            uploaded_by=self.manager,
            file=SimpleUploadedFile("hidden.pdf", b"%PDF-1.4", content_type="application/pdf"),
            original_filename="hidden.pdf",
            mime_type="application/pdf",
            file_size=8,
            is_hidden=True,
        )

        self.authenticate(self.customer_user)
        list_response = self.client.get(f"/api/tickets/{self.ticket.id}/attachments/")
        download_response = self.client.get(f"/api/tickets/{self.ticket.id}/attachments/{hidden.id}/download/")

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertNotIn(hidden.id, self.response_ids(list_response))
        self.assertEqual(download_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_cannot_download_attachment_linked_to_internal_message(self):
        message = TicketMessage.objects.create(
            ticket=self.ticket,
            author=self.manager,
            message="internal",
            message_type=TicketMessageType.INTERNAL_NOTE,
            is_hidden=True,
        )
        attachment = TicketAttachment.objects.create(
            ticket=self.ticket,
            message=message,
            uploaded_by=self.manager,
            file=SimpleUploadedFile("internal.pdf", b"%PDF-1.4", content_type="application/pdf"),
            original_filename="internal.pdf",
            mime_type="application/pdf",
            file_size=8,
        )

        self.authenticate(self.customer_user)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/attachments/{attachment.id}/download/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_attachment_outside_scope_is_denied(self):
        attachment = TicketAttachment.objects.create(
            ticket=self.other_ticket,
            uploaded_by=self.other_manager,
            file=SimpleUploadedFile("other.pdf", b"%PDF-1.4", content_type="application/pdf"),
            original_filename="other.pdf",
            mime_type="application/pdf",
            file_size=8,
        )

        self.authenticate(self.customer_user)
        response = self.client.get(f"/api/tickets/{self.other_ticket.id}/attachments/{attachment.id}/download/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_attachment_size_limit(self):
        self.authenticate(self.customer_user)
        response = self.upload_file(content=(b"x" * (10 * 1024 * 1024 + 1)))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_attachment_mime_and_extension_whitelist(self):
        self.authenticate(self.customer_user)
        bad_mime = self.upload_file(name="test.pdf", content_type="text/plain")
        bad_extension = self.upload_file(name="test.exe", content_type="application/pdf")

        self.assertEqual(bad_mime.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(bad_extension.status_code, status.HTTP_400_BAD_REQUEST)

    def test_randomized_stored_filename_and_original_filename_download(self):
        self.authenticate(self.customer_user)
        response = self.upload_file(name="original.pdf")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        attachment = TicketAttachment.objects.get(pk=response.data["id"])
        self.assertNotEqual(attachment.file.name.split("/")[-1], "original.pdf")

        download = self.client.get(f"/api/tickets/{self.ticket.id}/attachments/{attachment.id}/download/")
        self.assertEqual(download.status_code, status.HTTP_200_OK)
        self.assertIn("original.pdf", download["Content-Disposition"])
