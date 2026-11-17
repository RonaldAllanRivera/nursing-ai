"""Google sign-in, the PIN and the session gate (the auth lane builds them)."""

from nursing_api.auth.google import AuthlibGoogleOidc
from nursing_api.auth.oidc import GoogleOidc
from nursing_api.settings import Settings


def build_google(settings: Settings) -> GoogleOidc | None:
    """The Google client for these settings, or None while Google sign-in is off.

    The Authlib client is returned when `settings.google_sign_in`; `create_app(google=...)` gives
    a test its own.
    """
    client_id, client_secret = settings.google_client_id, settings.google_client_secret
    if not settings.google_sign_in or client_id is None or client_secret is None:
        return None
    return AuthlibGoogleOidc(client_id, client_secret.get_secret_value())
