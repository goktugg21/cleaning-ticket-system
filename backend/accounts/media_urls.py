"""RF-1 — absolute-URL builders for the authed photo/logo serving
endpoints, surfaced by the serializers the frontend already consumes.

Each URL carries a `?v=<marker>` derived from the stored file name (a
uuid that changes on every replace). The serving view ignores it; it
exists purely so the frontend's object-URL cache can key on entity+marker
and refetch exactly once after a change, never on every render.
"""
from pathlib import Path

from django.urls import reverse


def _versioned(request, route_name, kwargs, file_field):
    if not file_field:
        return None
    path = reverse(route_name, kwargs=kwargs)
    marker = Path(file_field.name).stem  # the uuid; changes on replace
    url = f"{path}?v={marker}"
    if request is not None:
        return request.build_absolute_uri(url)
    return url


def profile_photo_url(user, request):
    return _versioned(
        request,
        "user-photo",
        {"user_id": user.id},
        getattr(user, "profile_photo", None),
    )
