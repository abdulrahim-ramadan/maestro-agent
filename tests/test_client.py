from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from openai import APIConnectionError, RateLimitError

from maestro.config import Settings
from maestro.llm.client import (
    HINT_WAIT_BUDGET_SECONDS,
    MAX_HINT_RETRIES,
    MAX_RATE_LIMIT_WAIT_SECONDS,
    LLMClient,
    QuotaExhaustedError,
    retry_after_seconds,
)
from maestro.llm.pacing import TokenEstimator, TokenWindow

REQUEST = httpx2.Request("POST", "https://llm.test/v1/chat/completions")
MESSAGES = [{"role": "user", "content": "Hallo"}]


def text_chunk(text: str) -> SimpleNamespace:
    delta = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def rate_limit_error(message: str = "rate limited") -> RateLimitError:
    return RateLimitError(message, response=httpx2.Response(429, request=REQUEST), body=None)


def hinted_rate_limit(wait: str) -> RateLimitError:
    return rate_limit_error(f"Rate limit reached on tokens per minute (TPM). Please try again in {wait}. Need more tokens?")


class FakeCompletions:
    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = outcomes
        self.requests: list[dict[str, Any]] = []

    def create(self, **request: Any) -> Any:
        self.requests.append(request)
        outcome = self._outcomes[len(self.requests) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeOpenAI:
    def __init__(self, outcomes: list[Any]) -> None:
        self.completions = FakeCompletions(outcomes)
        self.chat = SimpleNamespace(completions=self.completions)


class RecordingSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def make_client(fake: FakeOpenAI, sleep: RecordingSleep) -> LLMClient:
    settings = Settings(api_key="test-key", model="test-model", base_url=None)
    return LLMClient(settings, openai_client=fake, sleep=sleep)


def test_retry_succeeds_on_second_attempt_after_rate_limit() -> None:
    fake = FakeOpenAI([rate_limit_error(), iter([text_chunk("Guten "), text_chunk("Tag")])])
    sleep = RecordingSleep()
    tokens: list[str] = []

    turn = make_client(fake, sleep).stream(MESSAGES, on_token=tokens.append)

    assert turn.content == "Guten Tag"
    assert tokens == ["Guten ", "Tag"]
    assert len(fake.completions.requests) == 2
    assert sleep.delays == [1]


def test_reraises_after_third_failed_attempt() -> None:
    fake = FakeOpenAI([rate_limit_error(), APIConnectionError(request=REQUEST), rate_limit_error()])
    sleep = RecordingSleep()

    with pytest.raises(RateLimitError):
        make_client(fake, sleep).stream(MESSAGES)

    assert len(fake.completions.requests) == 3
    assert sleep.delays == [1, 2]


def test_no_retry_after_tokens_were_streamed() -> None:
    def broken_stream() -> Iterator[SimpleNamespace]:
        yield text_chunk("Guten ")
        raise APIConnectionError(request=REQUEST)

    fake = FakeOpenAI([broken_stream(), iter([text_chunk("never used")])])
    sleep = RecordingSleep()
    tokens: list[str] = []

    with pytest.raises(APIConnectionError):
        make_client(fake, sleep).stream(MESSAGES, on_token=tokens.append)

    assert tokens == ["Guten "]
    assert len(fake.completions.requests) == 1
    assert sleep.delays == []


def test_tools_argument_omitted_when_list_is_empty() -> None:
    fake = FakeOpenAI([iter([text_chunk("ok")])])

    make_client(fake, RecordingSleep()).stream(MESSAGES, tools=[])

    request = fake.completions.requests[0]
    assert "tools" not in request
    assert request["stream"] is True
    assert request["model"] == "test-model"


@pytest.mark.parametrize(
    "message, seconds",
    [
        ("Please try again in 2.5s.", 2.5),
        ("Please try again in 8m50.496s.", 530.496),
        ("Please try again in 1h2m3s.", 3723.0),
        ("Please try again in 750ms.", 0.75),
        ("rate limited", None),
    ],
)
def test_retry_after_seconds_parses_provider_hint(message: str, seconds: float | None) -> None:
    hint = retry_after_seconds(message)

    if seconds is None:
        assert hint is None
    else:
        assert hint is not None and hint[0] == pytest.approx(seconds)


def test_hint_wait_adds_half_a_second_and_retries() -> None:
    fake = FakeOpenAI([hinted_rate_limit("577.5ms"), hinted_rate_limit("7.5s"), iter([text_chunk("ok")])])
    sleep = RecordingSleep()

    turn = make_client(fake, sleep).stream(MESSAGES)

    assert turn.content == "ok"
    assert sleep.delays == pytest.approx([1.0775, 8.0])
    assert len(fake.completions.requests) == 3


def test_up_to_five_hint_retries_then_raise() -> None:
    fake = FakeOpenAI([hinted_rate_limit("1s")] * 6 + [iter([text_chunk("never")])])
    sleep = RecordingSleep()

    with pytest.raises(RateLimitError):
        make_client(fake, sleep).stream(MESSAGES)

    assert sleep.delays == [1.5] * MAX_HINT_RETRIES
    assert len(fake.completions.requests) == MAX_HINT_RETRIES + 1


def test_hint_retries_stop_at_the_total_wait_budget() -> None:
    fake = FakeOpenAI([hinted_rate_limit("40s")] * 3 + [iter([text_chunk("never")])])
    sleep = RecordingSleep()

    with pytest.raises(RateLimitError):
        make_client(fake, sleep).stream(MESSAGES)

    assert sleep.delays == [40.5, 40.5]
    assert sum(sleep.delays) <= HINT_WAIT_BUDGET_SECONDS


def test_hint_at_the_limit_is_still_retried() -> None:
    fake = FakeOpenAI([hinted_rate_limit(f"{MAX_RATE_LIMIT_WAIT_SECONDS}s"), iter([text_chunk("ok")])])
    sleep = RecordingSleep()

    make_client(fake, sleep).stream(MESSAGES)

    assert sleep.delays == [MAX_RATE_LIMIT_WAIT_SECONDS + 0.5]


def test_long_hint_fails_fast_with_quota_message() -> None:
    fake = FakeOpenAI([hinted_rate_limit("8m50.496s"), iter([text_chunk("never")])])
    sleep = RecordingSleep()

    with pytest.raises(QuotaExhaustedError, match=r"daily limit; it asks to try again in 8m50\.496s"):
        make_client(fake, sleep).stream(MESSAGES)

    assert sleep.delays == []
    assert len(fake.completions.requests) == 1


def test_default_openai_client_does_not_retry_on_its_own() -> None:
    client = LLMClient(Settings(api_key="test-key", model="test-model", base_url=None))

    assert client._client.max_retries == 0


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.delays: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)
        self.now += seconds


def usage_chunk(prompt_tokens: int, total_tokens: int) -> SimpleNamespace:
    return SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=prompt_tokens, total_tokens=total_tokens))


def paced_client(fake: FakeOpenAI, clock: FakeClock, tpm_limit: int | None = 8000, waits: list | None = None) -> LLMClient:
    settings = Settings(api_key="test-key", model="test-model", base_url=None, tpm_limit=tpm_limit)
    on_wait = (lambda seconds, reason: waits.append((seconds, reason))) if waits is not None else None
    return LLMClient(settings, openai_client=fake, sleep=clock.sleep, clock=clock, on_wait=on_wait)


def test_token_window_waits_until_old_requests_leave_the_window() -> None:
    clock = FakeClock()
    window = TokenWindow(8000, clock)
    window.record(4495)
    clock.now += 20
    window.record(2000)

    assert window.budget == 7200
    assert window.wait_seconds(700) == 0
    assert window.wait_seconds(3582) == pytest.approx(40.0)
    clock.now += 40
    assert window.wait_seconds(3582) == 0
    assert window.used() == 2000


def test_request_larger_than_the_budget_waits_for_an_empty_window() -> None:
    clock = FakeClock()
    window = TokenWindow(1000, clock)
    window.record(500)
    clock.now += 10

    assert window.wait_seconds(5000) == pytest.approx(50.0)


def test_estimator_starts_at_four_chars_per_token_and_learns_from_usage() -> None:
    estimator = TokenEstimator()

    assert estimator.estimate(4000) == 1000
    estimator.learn(request_chars=4600, prompt_tokens=2000)
    assert estimator.estimate(4600) == 2000


def test_pacing_sleeps_before_a_request_that_would_exceed_the_limit() -> None:
    clock = FakeClock()
    big_message = [{"role": "user", "content": "x" * 14_000}]
    fake = FakeOpenAI([iter([text_chunk("a"), usage_chunk(3500, 4495)]), iter([text_chunk("b"), usage_chunk(3600, 3700)])])
    waits: list[tuple[float, str]] = []
    client = paced_client(fake, clock, waits=waits)

    client.stream(big_message)
    clock.now += 5
    client.stream(big_message)

    assert clock.delays == pytest.approx([55.0])
    assert waits == [(pytest.approx(55.0), "token pacing")]
    assert all(request["stream_options"] == {"include_usage": True} for request in fake.completions.requests)


def test_real_usage_replaces_the_estimate_in_the_window() -> None:
    clock = FakeClock()
    fake = FakeOpenAI([iter([text_chunk("a"), usage_chunk(100, 150)]), iter([text_chunk("b")])])
    client = paced_client(fake, clock)

    client.stream(MESSAGES)

    assert client._window.used() == 150


def test_no_pacing_and_no_stream_options_without_a_limit() -> None:
    clock = FakeClock()
    fake = FakeOpenAI([iter([text_chunk("a")]), iter([text_chunk("b")])])
    client = paced_client(fake, clock, tpm_limit=None)

    client.stream([{"role": "user", "content": "x" * 100_000}])
    client.stream([{"role": "user", "content": "x" * 100_000}])

    assert clock.delays == []
    assert "stream_options" not in fake.completions.requests[0]


def test_on_wait_reports_hint_waits() -> None:
    clock = FakeClock()
    fake = FakeOpenAI([hinted_rate_limit("11.5s"), iter([text_chunk("ok")])])
    waits: list[tuple[float, str]] = []

    paced_client(fake, clock, tpm_limit=None, waits=waits).stream(MESSAGES)

    assert waits == [(12.0, "provider retry hint")]
    assert clock.delays == [12.0]


def test_failing_on_wait_does_not_stop_the_request() -> None:
    clock = FakeClock()
    fake = FakeOpenAI([hinted_rate_limit("1s"), iter([text_chunk("ok")])])
    settings = Settings(api_key="test-key", model="test-model", base_url=None)

    def broken_display(seconds: float, reason: str) -> None:
        raise UnicodeEncodeError("charmap", "x", 0, 1, "broken console")

    turn = LLMClient(settings, openai_client=fake, sleep=clock.sleep, clock=clock, on_wait=broken_display).stream(MESSAGES)

    assert turn.content == "ok"
    assert clock.delays == [1.5]
