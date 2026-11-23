"""Step 2: turn raw GFW JSON into tidy tables (data/processed/*.csv).

Parsing is defensive: GFW fields are read with .get() so a missing or renamed
field produces blanks, not crashes. 
"""
from __future__ import annotations

import json
import logging

import pandas as pd

from .config import PROCESSED_DIR, RAW_DIR
from .geo import in_iez
from .gfw_client import flatten_report

log = logging.getLogger(__name__)


def _load(name: str):
    p = RAW_DIR / name
    if not p.exists():
        log.warning("missing %s, skipping", p.name)
        return []
    return json.loads(p.read_text())


def _ids(regions: dict | None, key: str) -> list[str]:
    vals = (regions or {}).get(key) or []
    return [str(v.get("id", v)) if isinstance(v, dict) else str(v) for v in vals]


def _has_auth(vessel: dict) -> bool | None:
    auths = vessel.get("publicAuthorizations")
    if auths is None:
        return None
    return any(a.get("hasPublicVesselAuthorization") for a in auths if isinstance(a, dict))


def event_row(e: dict, kind: str, cfg: dict) -> dict:
    v = e.get("vessel") or {}
    pos = e.get("position") or {}
    dist = (e.get("distances") or {}).get("startDistanceFromShoreKm")
    start, end = pd.to_datetime(e.get("start"), utc=True), pd.to_datetime(e.get("end"), utc=True)
    lat, lon = pos.get("lat"), pos.get("lon")
    row = {
        "event_id": e.get("id"),
        "kind": kind,
        "start": start,
        "end": end,
        "hours": (end - start).total_seconds() / 3600 if pd.notna(start) and pd.notna(end) else None,
        "lat": lat,
        "lon": lon,
        "dist_shore_km": dist,
        "ssvid": str(v.get("ssvid") or ""),
        "vessel_id": v.get("id"),
        "vessel_name": v.get("name"),
        "flag": v.get("flag"),
        "vessel_type": v.get("type"),
        "has_public_auth": _has_auth(v),
        "eez_ids": ";".join(_ids(e.get("regions"), "eez")),
        "mpa_ids": ";".join(_ids(e.get("regions"), "mpa")),
    }
    row["in_iez"] = bool(lat is not None and lon is not None and in_iez(cfg, lon, lat, dist))

    if kind == "gaps":
        g = e.get("gap") or {}
        off = g.get("offPosition") or pos
        row.update({
            "gap_hours": g.get("durationHours", row["hours"]),
            "gap_intentional": bool(g.get("intentionalDisabling", False)),
            "gap_distance_km": g.get("distanceKm"),
            "gap_off_lat": off.get("lat"),
            "gap_off_lon": off.get("lon"),
        })
    elif kind == "encounters":
        enc = e.get("encounter") or {}
        ov = enc.get("vessel") or {}
        row.update({
            "enc_type": enc.get("type"),
            "other_ssvid": str(ov.get("ssvid") or ""),
            "other_name": ov.get("name"),
            "other_flag": ov.get("flag"),
            "other_type": ov.get("type"),
            "enc_median_km": enc.get("medianDistanceKilometers"),
        })
    return row


def normalize_events(cfg: dict) -> pd.DataFrame:
    rows = []
    for kind in cfg["datasets"]["events"]:
        rows += [event_row(e, kind, cfg) for e in _load(f"events_{kind}.json")]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    eez = [str(x) for x in cfg["aoi"].get("eez_region_ids") or []]
    if eez:
        keep = df["eez_ids"].fillna("").apply(lambda s: bool(set(s.split(";")) & set(eez)))
        log.info("EEZ filter keeps %d/%d events", keep.sum(), len(df))
        df = df[keep]
    df = df.drop_duplicates("event_id")
    log.info("events by kind:\n%s", df["kind"].value_counts().to_string())
    df.to_csv(PROCESSED_DIR / "events.csv", index=False)
    return df


def normalize_sar(cfg: dict) -> pd.DataFrame:
    df = pd.DataFrame(flatten_report(_load("sar_unmatched.json")))
    if df.empty:
        return df
    df["detections"] = pd.to_numeric(df.get("detections", 1), errors="coerce").fillna(1)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["in_iez"] = [in_iez(cfg, lo, la) for lo, la in zip(df["lon"], df["lat"])]
    df.to_csv(PROCESSED_DIR / "sar_unmatched.csv", index=False)
    return df


def normalize_effort(cfg: dict) -> pd.DataFrame:
    df = pd.DataFrame(_load("effort_by_flag.json"))
    if df.empty:
        return df
    df["hours"] = pd.to_numeric(df["hours"], errors="coerce")
    out = df.groupby("flag", dropna=False)["hours"].sum().sort_values(ascending=False).reset_index()
    out.to_csv(PROCESSED_DIR / "effort_by_flag.csv", index=False)
    return out


def eez_candidates(cfg: dict) -> pd.DataFrame:
    """Which EEZ ids show up for events close to Sierra Leone's coast?
    The dominant one near Freetown/Sherbro is Sierra Leone's."""
    rows = []
    for kind in cfg["datasets"]["events"]:
        for e in _load(f"events_{kind}.json"):
            pos = e.get("position") or {}
            lat, lon = pos.get("lat"), pos.get("lon")
            if lat is None or not (7.0 <= lat <= 8.8 and -13.8 <= lon <= -12.0):
                continue
            for i in _ids(e.get("regions"), "eez"):
                rows.append(i)
    return pd.Series(rows, dtype=str).value_counts().rename_axis("eez_id").reset_index(name="events")
