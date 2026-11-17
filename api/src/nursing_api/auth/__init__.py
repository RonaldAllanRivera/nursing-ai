"""Google sign-in, the PIN and the session gate (the auth lane builds them)."""

from nursing_api.auth.oidc import GoogleOidc
from nursing_api.settings import Settings


def build_google(settings: Settings) -> GoogleOidc | None:
    """The Google client for these settings, or None while Google sign-in is off.

    It stays None until the auth lane builds the Authlib client (returned when
    `settings.google_sign_in`); `create_app(google=...)` gives a test its own.
    """
    return None
