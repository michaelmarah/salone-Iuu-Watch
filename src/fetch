##########################################################################
#### Step 1: Download raw data from Global Fishing Watch into data/raw/ as JSON.
########################################################################
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from .config import RAW_DIR
from .geo import aoi_feature_collection, aoi_geojson_geometry
from .gfw_client import GFWClient

log = logging.getLogger(__name__)


def month_chunks(start: str, end: str):
    """Split [start, end] into calendar-month pieces (keeps 4Wings reports small)."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    cur = s
    while cur <= e:
        nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        stop = min(e, nxt - timedelta(days=1))
        yield cur.isoformat(), stop.isoformat()
        cur = nxt


def _save(name: str, obj) -> None:
    p = RAW_DIR / name
    p.write_text(json.dumps(obj))
    log.info("saved %s (%d records)", p.name, len(obj) if hasattr(obj, "__len__") else -1)


def fetch_events(cfg: dict, client: GFWClient) -> None:
    start, end = cfg["date_range"]["start"], cfg["date_range"]["end"]
    geom = aoi_geojson_geometry(cfg)
    for kind, ds in cfg["datasets"]["events"].items():
        rows = []
        for s, e in month_chunks(start, end):
            rows.extend(client.events(ds, s, e, geometry=geom))
        _save(f"events_{kind}.json", rows)


def fetch_sar(cfg: dict, client: GFWClient) -> None:
    """Radar detections with NO matching AIS signal: candidate 'dark' vessels."""
    start, end = cfg["date_range"]["start"], cfg["date_range"]["end"]
    fc = aoi_feature_collection(cfg)
    rows = []
    for s, e in month_chunks(start, end):
        rows.extend(client.report(cfg["datasets"]["sar"], s, e, fc, temporal="DAILY",
                                  spatial="HIGH", filters=cfg["analysis"]["sar_unmatched_filter"]))
    _save("sar_unmatched.json", rows)


def fetch_effort(cfg: dict, client: GFWClient) -> None:
    """AIS apparent fishing effort by flag, monthly. Context for 'who fishes here'."""
    start, end = cfg["date_range"]["start"], cfg["date_range"]["end"]
    fc = aoi_feature_collection(cfg)
    rows = []
    for s, e in month_chunks(start, end):
        rows.extend(client.report(cfg["datasets"]["effort"], s, e, fc, temporal="MONTHLY",
                                  spatial="LOW", group_by="FLAG"))
    _save("effort_by_flag.json", rows)


def fetch_all(cfg: dict) -> None:
    client = GFWClient(cfg)
    fetch_events(cfg, client)
    for fn in (fetch_sar, fetch_effort):
        try:
            fn(cfg, client)
        except Exception as e:  # keep going: events alone already give useful flags
            log.error("%s failed: %s", fn.__name__, e)
