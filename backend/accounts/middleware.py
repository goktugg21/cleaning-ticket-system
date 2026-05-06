from django.utils import translation


class UserLanguageMiddleware:
    """Activate the authenticated user's preferred language for the request.

    Sits AFTER django.contrib.auth.middleware.AuthenticationMiddleware in
    MIDDLEWARE. For session-authenticated requests, request.user is already
    populated when this middleware runs and we activate user.language. For
    anonymous requests this is a no-op and the upstream
    django.middleware.locale.LocaleMiddleware (which parses Accept-Language
    or falls back to LANGUAGE_CODE) decides the language.

    Known limitation: DRF's JWT authentication runs at the view layer, not
    in middleware, so request.user is still AnonymousUser when this
    middleware fires for /api/ endpoints. JWT-authenticated DRF views
    therefore inherit the LocaleMiddleware default ("nl") rather than
    user.language. Per-user error translation for DRF requires either a
    DRF exception handler or a view mixin and lands in a later i18n batch.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        activated = False
        if user is not None and user.is_authenticated:
            lang = getattr(user, "language", None)
            if lang in ("nl", "en"):
                translation.activate(lang)
                request.LANGUAGE_CODE = lang
                activated = True
        try:
            return self.get_response(request)
        finally:
            if activated:
                translation.deactivate()
