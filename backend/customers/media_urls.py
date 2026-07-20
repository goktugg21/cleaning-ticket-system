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


def customer_contract_pdf_url(customer, request):
    """Invoicing Phase 4a — absolute URL for a customer's contract-PDF serving
    endpoint (NULL when unset). Mirrors `customer_logo_url`; the `?v=<marker>`
    is the same cache-buster keyed on the uuid stem so a replace-on-reupload
    invalidates the cached blob."""
    contract = getattr(customer, "contract_pdf", None)
    if not contract:
        return None
    path = reverse("customer-contract-pdf", kwargs={"customer_id": customer.id})
    url = f"{path}?v={Path(contract.name).stem}"
    if request is not None:
        return request.build_absolute_uri(url)
    return url
