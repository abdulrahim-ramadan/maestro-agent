from maestro.charts import MACHINE_FIELD, MINUTES_FIELD, downtime_bar_spec

DOWNTIME = {"CNV-01": 92.0, "PRS-01": 66.0, "ROB-01": 106.0, "ROB-02": 30.0, "SCR-01": 17.0}


def spec() -> dict:
    return downtime_bar_spec(DOWNTIME, "Maschine", "Stillstand (min)", "#F59E0B")


def test_y_scale_starts_at_zero() -> None:
    y = spec()["encoding"]["y"]

    assert y["scale"]["zero"] is True
    assert y["scale"]["domainMin"] == 0
    assert y["type"] == "quantitative"


def test_every_machine_with_downtime_gets_a_bar() -> None:
    chart = spec()
    bars = {row[MACHINE_FIELD]: row[MINUTES_FIELD] for row in chart["data"]["values"]}

    assert chart["mark"]["type"] == "bar"
    assert bars == DOWNTIME
    assert all(minutes > 0 for minutes in bars.values())
    assert min(bars.values()) >= chart["encoding"]["y"]["scale"]["domainMin"]


def test_machines_keep_their_order_and_titles() -> None:
    chart = spec()

    assert [row[MACHINE_FIELD] for row in chart["data"]["values"]] == list(DOWNTIME)
    assert chart["encoding"]["x"]["sort"] is None
    assert chart["encoding"]["x"]["title"] == "Maschine"
    assert chart["encoding"]["y"]["title"] == "Stillstand (min)"
    assert chart["mark"]["color"] == "#F59E0B"


def test_machine_without_downtime_is_still_listed() -> None:
    chart = downtime_bar_spec({"CNV-01": 0.0, "PRS-01": 12.5}, "Machine", "Downtime (min)", "#F59E0B")

    assert [row[MINUTES_FIELD] for row in chart["data"]["values"]] == [0.0, 12.5]
