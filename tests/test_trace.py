from datetime import datetime
from pathlib import Path

import pytest

from maestro.core import trace as trace_module
from maestro.core.trace import EventKind, Trace

FIXED_NOW = datetime(2026, 10, 14, 11, 30, 0, 123456)


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None) -> datetime:
        return FIXED_NOW


def test_traces_saved_in_same_second_get_different_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trace_module, "datetime", FrozenDatetime)
    first, second = Trace(), Trace()
    first.add(0, EventKind.TASK, {"task": "first"})
    second.add(0, EventKind.TASK, {"task": "second"})

    first_path = first.save(tmp_path)
    second_path = second.save(tmp_path)

    assert first_path != second_path
    assert first_path.name.startswith("trace_20261014_113000_123_")
    assert second_path.name.startswith("trace_20261014_113000_123_")
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted([first_path.name, second_path.name])
