import re
import time
from collections.abc import Callable, Iterable
from typing import Any

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

from maestro.config import Settings
from maestro.llm.stream import StreamAccumulator
from maestro.llm.types import AssistantTurn

MAX_ATTEMPTS = 3
RETRYABLE_ERRORS = (RateLimitError, APIConnectionError, APITimeoutError)
MAX_RATE_LIMIT_WAIT_SECONDS = 60
RETRY_HINT_PATTERN = re.compile(r"try again in ((?:\d+(?:\.\d+)?(?:h|ms|m|s))+)", re.IGNORECASE)
DURATION_PART_PATTERN = re.compile(r"(\d+(?:\.\d+)?)(h|ms|m|s)")
UNIT_SECONDS = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}


class QuotaExhaustedError(Exception):
    def __init__(self, wait_hint: str) -> None:
        super().__init__(
            f"the provider token quota is exhausted, probably the daily limit; it asks to try again in {wait_hint}. "
            f"Waits over {MAX_RATE_LIMIT_WAIT_SECONDS} s are not retried."
        )


def retry_after_seconds(message: str) -> tuple[float, str] | None:
    match = RETRY_HINT_PATTERN.search(message)
    if match is None:
        return None
    hint = match.group(1)
    seconds = sum(float(value) * UNIT_SECONDS[unit.lower()] for value, unit in DURATION_PART_PATTERN.findall(hint.lower()))
    return seconds, hint


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        openai_client: OpenAI | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._client = openai_client or OpenAI(api_key=settings.api_key, base_url=settings.base_url, max_retries=0)
        self._sleep = sleep

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> AssistantTurn:
        request: dict[str, Any] = {
            "model": self._settings.model,
            "messages": messages,
            "temperature": self._settings.temperature,
            "stream": True,
        }
        if tools:
            request["tools"] = tools

        accumulator = StreamAccumulator()
        for chunk in self._create_with_retries(request):
            text = accumulator.feed(chunk)
            if text and on_token is not None:
                on_token(text)
        return accumulator.result()

    def _create_with_retries(self, request: dict[str, Any]) -> Iterable[Any]:
        attempt = 0
        waited_for_hint = False
        while True:
            attempt += 1
            try:
                return self._client.chat.completions.create(**request)
            except RETRYABLE_ERRORS as error:
                hint = retry_after_seconds(str(error)) if isinstance(error, RateLimitError) else None
                if hint is None:
                    if attempt >= MAX_ATTEMPTS:
                        raise
                    self._sleep(2 ** (attempt - 1))
                    continue
                seconds, text = hint
                if seconds > MAX_RATE_LIMIT_WAIT_SECONDS:
                    raise QuotaExhaustedError(text) from error
                if waited_for_hint:
                    raise
                waited_for_hint = True
                self._sleep(seconds)
