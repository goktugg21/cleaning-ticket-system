"""RF-1 — absolute URL for a customer's logo serving endpoint. See
`accounts.media_urls` for the `?v=<marker>` cache-busting rationale.
"""
from pathlib import Path

from django.urls import reverse


def customer_logo_url(customer, request):
    logo = getattr(customer, "logo", None)
    if not logo:
        return None
    path = reverse("customer-logo", kwargs={"customer_id": customer.id})
    url = f"{path}?v={Path(logo.name).stem}"
    if request is not None:
        return request.build_absolute_uri(url)
    return url
