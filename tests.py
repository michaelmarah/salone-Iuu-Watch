"""Run with:  python -m pytest -q"""
import pandas as pd

from iuu import analyze, normalize
from iuu.config import load_config
from iuu.geo import in_iez, iez_km
from iuu.gfw_client import flatten_report
from iuu.synthetic import generate

CFG = load_config()


def test_iez_rule_uses_gfw_distance_first():
    assert in_iez(CFG, -13.0, 7.5, distance_from_shore_km=5.0)
    assert not in_iez(CFG, -13.0, 7.5, distance_from_shore_km=iez_km(CFG) + 0.5)


def test_iez_fallback_coastline():
    assert in_iez(CFG, -13.31, 8.47)          # just off Freetown peninsula
    assert not in_iez(CFG, -14.5, 7.0)        # far offshore


def test_flatten_report_both_shapes():
    keyed = {"entries": [{"ds:v1": [{"lat": 1, "lon": 2, "detections": 3}]}]}
    flat = {"entries": [{"dataset": "ds", "lat": 1, "lon": 2, "detections": 3}]}
    assert flatten_report(keyed)[0]["detections"] == 3
    assert flatten_report(flat)[0]["lat"] == 1
    assert flatten_report([{"lat": 1, "lon": 2}])[0]["lon"] == 2


def test_end_to_end_synthetic():
    generate(CFG, seed=1)
    ev = normalize.normalize_events(CFG)
    sar = normalize.normalize_sar(CFG)
    res = analyze.run(CFG, ev, sar)
    s = res["scores"]
    assert not s.empty and s.risk_score.is_monotonic_decreasing
    assert res["summary"]["iez_fishing_events"] > 0
    # every IEZ-fishing evidence row really is within the IEZ distance
    iez = res["evidence"]["iez_fishing"]
    assert (iez.dist_shore_km <= iez_km(CFG)).all()
    # every flagged vessel has at least one human-readable reason
    assert (s.reasons.str.len() > 0).all()


def test_missing_fields_do_not_crash():
    row = normalize.event_row({"id": "x", "start": "2026-01-01T00:00:00Z", "end": "2026-01-01T02:00:00Z",
                               "position": {"lat": 7.5, "lon": -13.0}}, "gaps", CFG)
    assert row["hours"] == 2 and row["gap_intentional"] is False
    assert isinstance(pd.DataFrame([row]), pd.DataFrame)

