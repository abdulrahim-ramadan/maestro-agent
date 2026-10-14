from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from openai import APIConnectionError, RateLimitError

from maestro.config import Settings
from maestro.llm.client import LLMClient

REQUEST = httpx2.Request("POST", "https://llm.test/v1/chat/completions")
MESSAGES = [{"role": "user", "content": "Hallo"}]


def text_chunk(text: str) -> SimpleNamespace:
    delta = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def rate_limit_error() -> RateLimitError:
    return RateLimitError("rate limited", response=httpx2.Response(429, request=REQUEST), body=None)


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
