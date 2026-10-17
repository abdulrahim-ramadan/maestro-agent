from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from openai import APIConnectionError, RateLimitError

from maestro.config import Settings
from maestro.llm.client import MAX_RATE_LIMIT_WAIT_SECONDS, LLMClient, QuotaExhaustedError, retry_after_seconds

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


def test_short_hint_waits_that_long_and_retries_once() -> None:
    fake = FakeOpenAI([hinted_rate_limit("7.5s"), iter([text_chunk("ok")])])
    sleep = RecordingSleep()

    turn = make_client(fake, sleep).stream(MESSAGES)

    assert turn.content == "ok"
    assert sleep.delays == [7.5]
    assert len(fake.completions.requests) == 2


def test_second_hinted_rate_limit_is_raised() -> None:
    fake = FakeOpenAI([hinted_rate_limit("3s"), hinted_rate_limit("3s"), iter([text_chunk("never")])])
    sleep = RecordingSleep()

    with pytest.raises(RateLimitError):
        make_client(fake, sleep).stream(MESSAGES)

    assert sleep.delays == [3]
    assert len(fake.completions.requests) == 2


def test_hint_at_the_limit_is_still_retried() -> None:
    fake = FakeOpenAI([hinted_rate_limit(f"{MAX_RATE_LIMIT_WAIT_SECONDS}s"), iter([text_chunk("ok")])])
    sleep = RecordingSleep()

    make_client(fake, sleep).stream(MESSAGES)

    assert sleep.delays == [MAX_RATE_LIMIT_WAIT_SECONDS]


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
