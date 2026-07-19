"""RF-1 — absolute URL for a company's logo serving endpoint. See
`accounts.media_urls` for the `?v=<marker>` cache-busting rationale.
"""
from pathlib import Path

from django.urls import reverse


def company_logo_url(company, request):
    logo = getattr(company, "logo", None)
    if not logo:
        return None
    path = reverse("company-logo", kwargs={"company_id": company.id})
    url = f"{path}?v={Path(logo.name).stem}"
    if request is not None:
        return request.build_absolute_uri(url)
    return url
