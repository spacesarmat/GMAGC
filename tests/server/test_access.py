import string

import pytest

from gmagc_common.protocol import CODE_ALPHABET, CODE_LENGTH, is_valid_code
from gmagc_desktop.service.access import RateLimiter, codes_equal, generate_code


def test_generated_codes_are_valid_and_differ():
    codes = {generate_code() for _ in range(20)}
    assert len(codes) == 20
    assert all(len(code) == CODE_LENGTH and set(code) <= set(CODE_ALPHABET) and is_valid_code(code) for code in codes)
    assert not set(string.ascii_lowercase) & set("".join(codes))


def test_codes_equal_ignores_case_and_dashes_but_never_matches_an_empty_code():
    assert codes_equal("ABCD2345", "abcd-2345")
    assert not codes_equal("ABCD2345", "ABCD2346")
    assert not codes_equal("", "")
    assert not codes_equal("", "ABCD2345")
    assert not codes_equal("ABCD2345", "")
    assert not codes_equal("ABCD2345", "ЖЖЖЖ2345")


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_rate_limiter_blocks_after_five_failures_and_recovers():
    clock = FakeClock()
    limiter = RateLimiter(max_failures=5, block_seconds=30.0, clock=clock)

    for _ in range(4):
        limiter.failure("1.1.1.1")
        assert limiter.retry_after("1.1.1.1") == 0
    limiter.failure("1.1.1.1")

    assert limiter.retry_after("1.1.1.1") == 30
    assert limiter.retry_after("2.2.2.2") == 0
    clock.now += 10.2
    assert limiter.retry_after("1.1.1.1") == 20
    clock.now += 20
    assert limiter.retry_after("1.1.1.1") == 0
    limiter.failure("1.1.1.1")
    assert limiter.retry_after("1.1.1.1") == 0  # счётчик начат заново


def test_success_resets_the_failure_counter():
    limiter = RateLimiter(max_failures=3, block_seconds=30.0, clock=FakeClock())
    limiter.failure("a")
    limiter.failure("a")
    limiter.success("a")
    limiter.failure("a")
    limiter.failure("a")
    assert limiter.retry_after("a") == 0


@pytest.mark.parametrize("bad", [0, -1])
def test_rate_limiter_rejects_a_non_positive_limit(bad):
    with pytest.raises(ValueError):
        RateLimiter(max_failures=bad)
