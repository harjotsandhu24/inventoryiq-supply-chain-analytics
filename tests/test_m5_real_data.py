"""Checks against the licensed M5 files. Skipped automatically when data/raw is absent (e.g. CI)."""

from __future__ import annotations

import json

import pytest

from inventoryiq import config as C
from tests.conftest import requires_m5

pytestmark = [pytest.mark.m5, requires_m5]


def _report():
    p = C.REPORTS_DIR / "m5" / "data_validation.json"
    if not p.exists():
        pytest.skip("run `python -m inventoryiq.pipeline --source m5` first")
    return json.loads(p.read_text())


def test_m5_dimensions():
    s = _report()["summary"]
    assert s["series"] == 30490
    assert s["items"] == 3049
    assert len(s["stores"]) == 10
    assert s["observed_days"] == 1941
    assert s["calendar_days"] == 1969
    assert s["first_date"] == "2011-01-29" and s["last_observed_date"] == "2016-05-22"
    assert s["holdout"] == {
        "start_day": 1914,
        "end_day": 1941,
        "start_date": "2016-04-25",
        "end_date": "2016-05-22",
    }
    assert s["passed"]


def test_m5_demo_scope():
    lines = json.loads((C.APP_DATA_DIR / "lines.json").read_text())
    manifest = json.loads((C.APP_DATA_DIR / "manifest.json").read_text())
    if manifest["source"] != "m5":
        pytest.skip("app data currently built from synthetic source")
    assert len(lines) == 300
    assert {x["store"] for x in lines} == {"CA_1", "CA_2"}
    assert {x["cat"] for x in lines} == {"FOODS", "HOBBIES", "HOUSEHOLD"}
    assert len({x["pattern"] for x in lines}) >= 3
