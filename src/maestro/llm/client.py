import time
from collections.abc import Callable, Iterable
from typing import Any

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

from maestro.config import Settings
from maestro.llm.stream import StreamAccumulator
from maestro.llm.types import AssistantTurn

MAX_ATTEMPTS = 3
RETRYABLE_ERRORS = (RateLimitError, APIConnectionError, APITimeoutError)


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = OpenAI(api_key=settings.api_key, base_url=settings.base_url)

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
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self._client.chat.completions.create(**request)
            except RETRYABLE_ERRORS:
                if attempt == MAX_ATTEMPTS:
                    raise
                time.sleep(2 ** (attempt - 1))
        raise AssertionError("unreachable")
