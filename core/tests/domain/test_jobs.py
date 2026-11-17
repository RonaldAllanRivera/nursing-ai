"""Which failed drafts offer "Try drafting again"."""

import pytest
from nursing_core.domain.jobs import RETRYABLE_FAILURES, JobFailure, is_retryable


def test_retryable_failures_are_provider_error_and_invalid_output() -> None:
    assert frozenset({JobFailure.PROVIDER_ERROR, JobFailure.INVALID_OUTPUT}) == RETRYABLE_FAILURES


@pytest.mark.parametrize("failure", list(JobFailure))
def test_is_retryable_follows_the_set(failure: JobFailure) -> None:
    # A refusal, a missing recording or a spent budget would fail the same way again.
    assert is_retryable(failure) is (failure in RETRYABLE_FAILURES)


def test_a_job_with_no_failure_is_not_retryable() -> None:
    assert is_retryable(None) is False
