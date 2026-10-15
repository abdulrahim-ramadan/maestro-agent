import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 42
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SHIFT_START = datetime(2026, 10, 14, 6, 0)
SHIFT_END = datetime(2026, 10, 14, 14, 0)
RANDOM_EVENT_COUNT = 26

ERROR_CODES: dict[str, dict[str, str]] = {
    "E101": {"title": "Wire feed jam", "category": "mechanical", "likely_cause": "Worn feed rollers or kinked welding wire liner", "severity": "critical"},
    "E102": {"title": "Weld current out of tolerance", "category": "process", "likely_cause": "Dirty contact tip or unstable ground connection", "severity": "warning"},
    "E103": {"title": "Torch collision detected", "category": "safety", "likely_cause": "Part misplaced in fixture or drifted robot path", "severity": "critical"},
    "E104": {"title": "Tip dressing overdue", "category": "maintenance", "likely_cause": "Tip dresser cycle skipped or counter not reset", "severity": "info"},
    "E201": {"title": "Conveyor belt slip", "category": "mechanical", "likely_cause": "Low belt tension or worn drive pulley lagging", "severity": "warning"},
    "E202": {"title": "Part jam at transfer point", "category": "mechanical", "likely_cause": "Misaligned guide rail or deformed part carrier", "severity": "critical"},
    "E203": {"title": "Drive motor overtemperature", "category": "electrical", "likely_cause": "Blocked motor fan or sustained overload", "severity": "warning"},
    "E301": {"title": "Hydraulic pressure low", "category": "hydraulic", "likely_cause": "Leak in hydraulic line or worn pump", "severity": "critical"},
    "E302": {"title": "Tonnage monitor deviation", "category": "process", "likely_cause": "Incorrect die height or material thickness variation", "severity": "warning"},
    "E303": {"title": "Die lubrication low", "category": "maintenance", "likely_cause": "Lubricant reservoir below minimum level", "severity": "info"},
    "E401": {"title": "Torque out of range", "category": "process", "likely_cause": "Worn screwdriver bit or wrong screw batch", "severity": "warning"},
    "E402": {"title": "Screw feeder empty", "category": "material", "likely_cause": "Feeder bowl not refilled in time", "severity": "info"},
}

MACHINE_CODES: dict[str, list[str]] = {
    "ROB-01": ["E101", "E102", "E103", "E104"],
    "ROB-02": ["E101", "E102", "E103", "E104"],
    "CNV-01": ["E201", "E202", "E203"],
    "PRS-01": ["E301", "E302", "E303"],
    "SCR-01": ["E401", "E402"],
}

DURATION_MINUTES: dict[str, tuple[int, int]] = {
    "info": (0, 0),
    "warning": (2, 10),
    "critical": (12, 40),
}

OUTCOMES: dict[str, list[str]] = {
    "info": ["logged for next maintenance window", "operator notified"],
    "warning": ["operator acknowledged, auto-reset", "cleared after visual check"],
    "critical": ["machine stopped, maintenance called", "machine stopped, repaired by maintenance"],
}

FIXED_EVENTS: list[tuple[str, str, datetime, datetime]] = [
    ("PRS-01", "E301", datetime(2026, 10, 14, 5, 40), datetime(2026, 10, 14, 6, 25)),
    ("ROB-01", "E101", datetime(2026, 10, 14, 9, 10), datetime(2026, 10, 14, 9, 40)),
    ("ROB-01", "E103", datetime(2026, 10, 14, 9, 25), datetime(2026, 10, 14, 9, 55)),
    ("ROB-02", "E102", datetime(2026, 10, 14, 11, 0), datetime(2026, 10, 14, 11, 8)),
    ("ROB-02", "E101", datetime(2026, 10, 14, 11, 5), datetime(2026, 10, 14, 11, 30)),
]


def random_event(rng: random.Random) -> tuple[str, str, datetime, datetime]:
    machine_id = rng.choice(sorted(MACHINE_CODES))
    code = rng.choice(MACHINE_CODES[machine_id])
    shift_minutes = int((SHIFT_END - SHIFT_START).total_seconds() // 60)
    start = SHIFT_START + timedelta(minutes=rng.randrange(0, shift_minutes - 10))
    low, high = DURATION_MINUTES[ERROR_CODES[code]["severity"]]
    return machine_id, code, start, start + timedelta(minutes=rng.randint(low, high))


def build_rows(rng: random.Random) -> list[dict[str, str]]:
    events = FIXED_EVENTS + [random_event(rng) for _ in range(RANDOM_EVENT_COUNT)]
    events.sort(key=lambda event: (event[2], event[0]))
    rows = []
    for number, (machine_id, code, start, end) in enumerate(events, start=1):
        entry = ERROR_CODES[code]
        rows.append(
            {
                "event_id": f"EV-{number:04d}",
                "start_time": start.isoformat(sep=" "),
                "end_time": end.isoformat(sep=" "),
                "machine_id": machine_id,
                "error_code": code,
                "severity": entry["severity"],
                "message": f"{entry['title']}: {rng.choice(OUTCOMES[entry['severity']])}",
            }
        )
    return rows


def main() -> None:
    rng = random.Random(SEED)
    DATA_DIR.mkdir(exist_ok=True)
    rows = build_rows(rng)

    with (DATA_DIR / "fault_log.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    content = json.dumps(ERROR_CODES, ensure_ascii=False, indent=2) + "\n"
    (DATA_DIR / "error_codes.json").write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {len(rows)} events and {len(ERROR_CODES)} error codes to {DATA_DIR}")


if __name__ == "__main__":
    main()
