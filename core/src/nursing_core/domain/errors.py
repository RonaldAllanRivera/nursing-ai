"""Domain errors. No message ever quotes note text, names or keys."""

from nursing_core.domain.notes import GenerationInfo


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


class BilledError(DomainError):
    """A failure that can follow an answer the AI service already billed.

    `generation` is what that answer cost (None when no answer with usage arrived), so the spend
    still counts against the monthly cap. It is never part of the message.
    """

    def __init__(self, message: str = "", *, generation: GenerationInfo | None = None) -> None:
        super().__init__(message)
        self.generation = generation


class ModelRefused(BilledError):
    pass


class InvalidModelOutput(BilledError):
    pass


class ProviderUnavailable(DomainError):
    pass


class ReplayMissing(DomainError):
    """Replay mode has no recording for this request."""


class PhiLeak(DomainError):
    """A known identity string reached a provider. The message never says which one."""


class EmailTaken(DomainError):
    """An invite for an email that already belongs to someone."""


class IdentityMismatch(DomainError):
    """The email is already bound to another Google account (a recycled or moved address)."""


class AlreadyDrafted(DomainError):
    """The rough note already has a draft: trying again would make a second note."""


class NotRetryable(DomainError):
    """The draft failed in a way a new attempt would repeat (a refusal, no recording, no budget)."""


class DailyCapReached(DomainError):
    """The author already has the capped number of draft jobs in the last 24 hours."""


class DatabaseWaking(DomainError):
    """The database is resuming from a pause (or didn't answer in time): try again shortly."""
