import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

WINDOW_SECONDS = 60.0
HEADROOM = 0.9
DEFAULT_CHARS_PER_TOKEN = 4.0
ESTIMATE_PRECISION = 6


@dataclass
class WindowEntry:
    sent_at: float
    tokens: int


class TokenWindow:
    def __init__(self, tokens_per_minute: int, clock: Callable[[], float]) -> None:
        self._budget = int(tokens_per_minute * HEADROOM)
        self._clock = clock
        self._entries: list[WindowEntry] = []

    @property
    def budget(self) -> int:
        return self._budget

    def used(self) -> int:
        self._prune()
        return sum(entry.tokens for entry in self._entries)

    def wait_seconds(self, tokens: int) -> float:
        self._prune()
        now = self._clock()
        excess = self.used() + tokens - self._budget
        if excess <= 0 or not self._entries:
            return 0.0
        freed = 0
        for entry in self._entries:
            freed += entry.tokens
            if freed >= excess:
                return entry.sent_at + WINDOW_SECONDS - now
        return self._entries[-1].sent_at + WINDOW_SECONDS - now

    def record(self, tokens: int) -> WindowEntry:
        entry = WindowEntry(self._clock(), tokens)
        self._entries.append(entry)
        return entry

    def _prune(self) -> None:
        oldest_allowed = self._clock() - WINDOW_SECONDS
        self._entries = [entry for entry in self._entries if entry.sent_at > oldest_allowed]


class TokenEstimator:
    def __init__(self) -> None:
        self._chars_per_token = DEFAULT_CHARS_PER_TOKEN

    @staticmethod
    def request_chars(request: dict[str, Any]) -> int:
        payload = {"messages": request.get("messages", []), "tools": request.get("tools", [])}
        return len(json.dumps(payload, ensure_ascii=False))

    def estimate(self, request_chars: int) -> int:
        return math.ceil(round(request_chars / self._chars_per_token, ESTIMATE_PRECISION))

    def learn(self, request_chars: int, prompt_tokens: int) -> None:
        if prompt_tokens > 0 and request_chars > 0:
            self._chars_per_token = request_chars / prompt_tokens
