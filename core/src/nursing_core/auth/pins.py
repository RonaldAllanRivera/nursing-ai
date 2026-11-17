"""The six-digit signing PIN: what is allowed, how it is stored and how it is checked.

A PIN is only ever stored as an Argon2id hash. Nothing here puts a PIN or a hash in an error
message or a log line.
"""

import re
from itertools import pairwise
from typing import Final, Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MAX_PIN_TRIES: Final = 5
"""Wrong tries before a PIN locks."""

_PIN_FORMAT: Final = re.compile(r"[0-9]{6}")
_HASHER: Final = PasswordHasher()


class PinRefused(ValueError):
    """A new PIN was not accepted. `reason` says why; the message never contains the PIN."""

    def __init__(self, reason: Literal["format", "weak"]) -> None:
        super().__init__(
            "A PIN is six digits." if reason == "format" else "That PIN is too easy to guess."
        )
        self.reason: Literal["format", "weak"] = reason


def check_new_pin(pin: str) -> None:
    """Refuse a PIN that is not six ASCII digits, or is all one digit or a straight run.

    A run goes up or down by one each digit and does not wrap (`890123` is allowed).
    """
    if _PIN_FORMAT.fullmatch(pin) is None:
        raise PinRefused("format")
    steps = {int(b) - int(a) for a, b in pairwise(pin)}
    if steps in ({0}, {1}, {-1}):
        raise PinRefused("weak")


def hash_pin(pin: str) -> str:
    """Hash a PIN with Argon2id (argon2-cffi defaults); each call uses a fresh salt."""
    return _HASHER.hash(pin)


def verify_pin(pin_hash: str, pin: str) -> bool:
    """True only when `pin` matches `pin_hash`; a wrong PIN or a malformed hash is False."""
    try:
        return _HASHER.verify(pin_hash, pin)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
