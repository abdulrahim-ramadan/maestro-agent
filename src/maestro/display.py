import json
import math
import os
import re

MAX_ARGUMENT_CHARS = 70
SECRET_PATTERN = re.compile(r"(?:sk-|gsk_|AIza)[\w*\-]+")
API_KEY_VARIABLE = "LLM_API_KEY"
MIN_REDACTED_KEY_CHARS = 8
REDACTED = "<redacted>"


def short_arguments(raw_arguments: str) -> str:
    try:
        text = json.dumps(json.loads(raw_arguments or "{}"), ensure_ascii=False, separators=(",", ":"))
    except json.JSONDecodeError:
        text = raw_arguments
    return text if len(text) <= MAX_ARGUMENT_CHARS else text[: MAX_ARGUMENT_CHARS - 3] + "..."


def redact_secrets(message: str) -> str:
    api_key = os.environ.get(API_KEY_VARIABLE, "").strip()
    if len(api_key) >= MIN_REDACTED_KEY_CHARS:
        message = message.replace(api_key, REDACTED)
    return SECRET_PATTERN.sub(REDACTED, message)


def wait_message(seconds: float, reason: str) -> str:
    return f"waiting {math.ceil(seconds)} s for the rate limit ({reason})"
