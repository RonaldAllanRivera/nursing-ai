"""The `sl_oauth` cookie: one browser's Google sign-in attempt, between the start and the callback.

It holds the attempt's state, nonce, PKCE verifier and the time it was made, and nothing about a
person: it is not a session. It is signed with a key derived from the Google client secret, so a
page on another site cannot plant an attempt of its own (a login-forgery). The signature does not
hide the contents: the cookie is httpOnly and stays on the callback's path.
"""

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

NAME = "sl_oauth"
PATH = "/api/v1/auth/google/callback"
LIFETIME = timedelta(minutes=10)


@dataclass(frozen=True)
class OAuthAttempt:
    """What the callback needs to finish the attempt this browser began."""

    state: str = field(repr=False)
    nonce: str = field(repr=False)
    verifier: str = field(repr=False)
    issued_at: datetime


def _sign(secret: str, payload: bytes) -> bytes:
    key = hashlib.sha256(b"nursing-api sl_oauth\0" + secret.encode()).digest()
    return hmac.new(key, payload, hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def seal(attempt: OAuthAttempt, *, secret: str) -> str:
    """The cookie's value for this attempt."""
    payload = json.dumps(
        {
            "s": attempt.state,
            "n": attempt.nonce,
            "v": attempt.verifier,
            "t": attempt.issued_at.timestamp(),
        },
        separators=(",", ":"),
    ).encode()
    return f"{_b64(payload)}.{_b64(_sign(secret, payload))}"


def open_seal(value: str | None, *, secret: str, now: datetime) -> OAuthAttempt | None:
    """The attempt a cookie holds, or None when it is missing, garbled, not ours or older than
    ten minutes (or from the future) by the app's clock."""
    if not value:
        return None
    try:
        body, _, signature = value.partition(".")
        payload = _unb64(body)
        if not hmac.compare_digest(_unb64(signature), _sign(secret, payload)):
            return None
        raw = json.loads(payload)
        attempt = OAuthAttempt(
            state=str(raw["s"]),
            nonce=str(raw["n"]),
            verifier=str(raw["v"]),
            issued_at=datetime.fromtimestamp(float(raw["t"]), tz=now.tzinfo),
        )
    except (ValueError, KeyError, TypeError):
        return None
    age = now - attempt.issued_at
    return attempt if timedelta(0) <= age <= LIFETIME else None
