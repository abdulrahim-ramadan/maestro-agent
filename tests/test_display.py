import pytest

from maestro.display import wait_message


@pytest.mark.parametrize(
    "seconds, reason, expected",
    [
        (11.6, "token pacing", "waiting 12 s for the rate limit (token pacing)"),
        (0.4, "provider retry hint", "waiting 1 s for the rate limit (provider retry hint)"),
        (60.0, "token pacing", "waiting 60 s for the rate limit (token pacing)"),
    ],
)
def test_wait_message_rounds_up_to_whole_seconds(seconds: float, reason: str, expected: str) -> None:
    assert wait_message(seconds, reason) == expected
