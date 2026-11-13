"""Domain errors. No message ever quotes note text, names or keys."""


class DomainError(Exception):
    """Base class for every error the API maps to a problem response."""


class NotFound(DomainError):
    pass


class StaleVersion(DomainError):
    """The caller's version (If-Match) is older than the stored one."""


class NoteLocked(DomainError):
    """The note is signed or discarded, so it can't change."""


class ReviewIncomplete(DomainError):
    """Lines still need the nurse before she can sign."""

    def __init__(self, line_ids: list[str]) -> None:
        super().__init__(f"{len(line_ids)} line(s) need review")
        self.line_ids = line_ids


class IdempotencyConflict(DomainError):
    """The same Idempotency-Key came back with a different body."""


class Forbidden(DomainError):
    """The signed-in role may not do this."""


class AiBudgetReached(DomainError):
    """The monthly AI cap (ours or the Console's) is reached. Never retried."""


class ModelRefused(DomainError):
    pass


class InvalidModelOutput(DomainError):
    pass


class ProviderUnavailable(DomainError):
    pass


class ReplayMissing(DomainError):
    """Replay mode has no recording for this request."""


class PhiLeak(DomainError):
    """A known identity string reached a provider. The message never says which one."""
