from typing import Any

MACHINE_FIELD = "machine"
MINUTES_FIELD = "minutes"


def downtime_bar_spec(downtime: dict[str, float], machine_title: str, minutes_title: str, color: str) -> dict[str, Any]:
    return {
        "data": {"values": [{MACHINE_FIELD: machine, MINUTES_FIELD: minutes} for machine, minutes in downtime.items()]},
        "mark": {"type": "bar", "color": color},
        "encoding": {
            "x": {"field": MACHINE_FIELD, "type": "nominal", "title": machine_title, "sort": None},
            "y": {
                "field": MINUTES_FIELD,
                "type": "quantitative",
                "title": minutes_title,
                "scale": {"zero": True, "domainMin": 0},
            },
            "tooltip": [
                {"field": MACHINE_FIELD, "type": "nominal", "title": machine_title},
                {"field": MINUTES_FIELD, "type": "quantitative", "title": minutes_title},
            ],
        },
    }
