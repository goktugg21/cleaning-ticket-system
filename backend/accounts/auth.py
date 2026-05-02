from rest_framework_simplejwt.exceptions import AuthenticationFailed


def user_authentication_rule(user):
    if user is None:
        return False
    if not user.is_active:
        return False
    if getattr(user, "deleted_at", None) is not None:
        raise AuthenticationFailed("User has been deactivated.", code="user_inactive")
    return True
