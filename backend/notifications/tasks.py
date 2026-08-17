import logging

from celery import shared_task
from django.conf import settings

from . import services
from .models import NotificationLog

logger = logging.getLogger(__name__)


def send_mail(*args, **kwargs):
    """
    Thin wrapper that delegates to services.send_mail.

    Exposed at module level so test code can patch notifications.tasks.send_mail
    directly. Because the wrapper looks up services.send_mail through the
    services module at call time, patching notifications.services.send_mail
    also flows through to the task. This keeps both patch paths effective.
    """
    return services.send_mail(*args, **kwargs)


@shared_task(
    bind=True,
    retry_backoff=10,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=3,
)
def send_email_task(
    self, *, log_id, recipient_email, subject, body, attachment=None
):
    """
    Send an email synchronously inside the worker.

    Recipient filtering, dedup, and actor exclusion all happen in
    services._send_to_users before this task is enqueued. This task only
    knows the final recipient and the matching NotificationLog row.

    Retry policy: in production the task self-retries on any exception with
    exponential backoff up to max_retries, then marks the log FAILED. In
    eager mode (used by manage.py test) we skip the retry loop because
    Celery's eager harness propagates the Retry exception instead of
    re-running the task; we mark FAILED on the first exception so the test
    suite can observe the terminal state without hangs or Retry leakage.
    """
    try:
        log = NotificationLog.objects.get(pk=log_id)
    except NotificationLog.DoesNotExist:
        logger.warning("send_email_task: NotificationLog %s vanished", log_id)
        return

    try:
        if attachment is None:
            sent_count = send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient_email],
                fail_silently=False,
            )
        else:
            # Sprint 185 §2 — the SAME sender, carrying a document.
            #
            # `send_mail` cannot attach, so an attachment takes the
            # EmailMessage path. Deliberately still inside this task and
            # still against this NotificationLog row: a second sender is
            # how two systems start disagreeing about what was sent, and
            # the log is the answer to "did they get it".
            #
            # `attachment` is (filename, base64_content, mimetype) —
            # plain JSON-safe data, because this project leaves Celery's
            # task serializer at its default of JSON and raw `bytes`
            # cannot cross that boundary. `send_logged_email` does the
            # encoding; this undoes it.
            import base64

            from django.core.mail import EmailMessage

            filename, encoded, mimetype = attachment
            content = base64.b64decode(encoded)
            message = EmailMessage(
                subject=subject,
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient_email],
            )
            message.attach(filename, content, mimetype)
            sent_count = message.send(fail_silently=False)
    except Exception as exc:
        retries_exhausted = self.request.retries >= self.max_retries
        if retries_exhausted or self.app.conf.task_always_eager:
            log.mark_failed(exc)
            logger.error(
                "send_email_task: log %s failed after %s retries: %s",
                log_id, self.request.retries, exc,
            )
            return
        raise self.retry(exc=exc)

    if sent_count:
        log.mark_sent()
    else:
        log.mark_failed("Email backend returned 0 sent messages.")
