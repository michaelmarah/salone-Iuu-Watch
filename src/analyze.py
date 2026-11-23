"""Step 3: flag suspicious activity and score vessels.

Every point in a vessel's score comes from a named, checkable signal, so a
fisheries officer or journalist can see exactly *why* a vessel is listed.
A high score means "worth investigating", not "proven illegal".
"""
from __future__ import annotations

import logging

import pandas as pd

from .config import OUTPUT_DIR
from .geo import distance_to_coast_km, iez_km

log = logging.getLogger(__name__)


def _near_shore_km(cfg, row) -> float:
    d = row.get("dist_shore_km")
    if d is not None and pd.notna(d):
        return float(d)
    lat = row.get("gap_off_lat", row.get("lat"))
    lon = row.get("gap_off_lon", row.get("lon"))
    return distance_to_coast_km(cfg, lon, lat) if pd.notna(lat) and pd.notna(lon) else float("inf")


def evidence_tables(cfg: dict, ev: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Per-signal evidence tables (one row per event)."""
    if ev.empty:
        return {}
    a = cfg["analysis"]
    fishing = ev[ev.kind == "fishing"]
    gaps = ev[ev.kind == "gaps"].copy()
    enc = ev[ev.kind == "encounters"]
    loit = ev[ev.kind == "loitering"]

    if not gaps.empty:
        gaps = gaps[gaps["gap_hours"].fillna(0) >= a["min_gap_hours"]].copy()
        gaps["near_iez"] = [
            _near_shore_km(cfg, r) <= 2 * iez_km(cfg) for r in gaps.to_dict("records")
        ]

    is_carrier = pd.Series(False, index=enc.index)
    if not enc.empty:
        is_carrier = (enc.get("enc_type", pd.Series("", index=enc.index)).fillna("").str.contains("carrier")
                      | (enc.get("other_type", pd.Series("", index=enc.index)).fillna("") == "carrier"))

    return {
        "iez_fishing": fishing[fishing.in_iez],
        "mpa_fishing": fishing[fishing.mpa_ids.fillna("") != ""],
        "ais_gaps": gaps,
        "carrier_encounters": enc[is_carrier],
        "loitering": loit,
    }


def score_vessels(cfg: dict, ev: pd.DataFrame, evid: dict[str, pd.DataFrame]) -> pd.DataFrame:
    w = cfg["scoring"]
    if ev.empty:
        return pd.DataFrame()

    ident = (ev[ev.ssvid != ""].groupby("ssvid")
             .agg(vessel_name=("vessel_name", lambda s: s.dropna().mode().iat[0] if s.notna().any() else None),
                  flag=("flag", lambda s: s.dropna().mode().iat[0] if s.notna().any() else None),
                  vessel_type=("vessel_type", lambda s: s.dropna().mode().iat[0] if s.notna().any() else None),
                  auth_seen=("has_public_auth", lambda s: s.dropna().astype(bool).any() if s.notna().any() else None)))

    def per(name, col=None, agg="size"):
        t = evid.get(name, pd.DataFrame())
        if t.empty:
            return pd.Series(dtype=float)
        g = t.groupby("ssvid")
        return g.size() if agg == "size" else g[col].sum()

    f = pd.DataFrame(index=ident.index)
    f["iez_fishing_hours"] = per("iez_fishing", "hours", "sum")
    f["iez_fishing_events"] = per("iez_fishing")
    f["mpa_fishing_hours"] = per("mpa_fishing", "hours", "sum")
    f["ais_gaps"] = per("ais_gaps")
    gaps = evid.get("ais_gaps", pd.DataFrame())
    f["intentional_gaps"] = gaps[gaps.gap_intentional].groupby("ssvid").size() if not gaps.empty else 0
    f["gaps_near_iez"] = gaps[gaps.near_iez].groupby("ssvid").size() if not gaps.empty else 0
    f["carrier_encounters"] = per("carrier_encounters")
    f["loitering_events"] = per("loitering")
    f = f.fillna(0)
    f["no_public_auth"] = (ident["auth_seen"] == False).astype(int)  # noqa: E712  (None = unknown)

    parts = {
        "iez_fishing_hours": w["iez_fishing_hour"],
        "mpa_fishing_hours": w["mpa_fishing_hour"],
        "ais_gaps": w["gap_event"],
        "intentional_gaps": w["intentional_gap_bonus"],
        "gaps_near_iez": w["gap_near_iez_bonus"],
        "carrier_encounters": w["encounter_with_carrier"],
        "loitering_events": w["loitering_event"],
        "no_public_auth": w["no_public_authorization"],
    }
    f["risk_score"] = sum(f[c] * wt for c, wt in parts.items()).round(1)

    labels = {
        "iez_fishing_hours": "{:.1f} h apparent fishing inside IEZ",
        "mpa_fishing_hours": "{:.1f} h fishing in marine protected area",
        "ais_gaps": "{:.0f} AIS gap(s)",
        "intentional_gaps": "{:.0f} likely intentional AIS shut-off(s)",
        "gaps_near_iez": "{:.0f} gap(s) starting near the IEZ",
        "carrier_encounters": "{:.0f} encounter(s) with carrier (possible transshipment)",
        "loitering_events": "{:.0f} loitering event(s)",
        "no_public_auth": "no public authorization found",
    }
    f["reasons"] = f.apply(
        lambda r: "; ".join(labels[c].format(r[c]) for c in parts if r[c] > 0), axis=1)

    out = ident.drop(columns="auth_seen").join(f).sort_values("risk_score", ascending=False)
    out = out[out.risk_score > 0]
    return out.reset_index()


def sar_hotspots(sar: pd.DataFrame, cell_deg: float = 0.05) -> pd.DataFrame:
    """Aggregate dark (unmatched) radar detections into grid cells."""
    if sar.empty:
        return sar
    s = sar.copy()
    s["cell_lat"] = (s.lat / cell_deg).round() * cell_deg
    s["cell_lon"] = (s.lon / cell_deg).round() * cell_deg
    h = (s.groupby(["cell_lat", "cell_lon"])
         .agg(detections=("detections", "sum"), days=("date", "nunique"), in_iez=("in_iez", "max"))
         .reset_index().sort_values("detections", ascending=False))
    return h


def run(cfg: dict, ev: pd.DataFrame, sar: pd.DataFrame) -> dict:
    evid = evidence_tables(cfg, ev)
    scores = score_vessels(cfg, ev, evid)
    hot = sar_hotspots(sar)

    scores.to_csv(OUTPUT_DIR / "vessel_risk.csv", index=False)
    for name, t in evid.items():
        t.to_csv(OUTPUT_DIR / f"evidence_{name}.csv", index=False)
    if not hot.empty:
        hot.to_csv(OUTPUT_DIR / "sar_dark_hotspots.csv", index=False)

    summary = {
        "vessels_flagged": len(scores),
        "iez_fishing_events": len(evid.get("iez_fishing", [])),
        "iez_fishing_hours": float(evid["iez_fishing"]["hours"].sum()) if "iez_fishing" in evid else 0.0,
        "ais_gaps": len(evid.get("ais_gaps", [])),
        "carrier_encounters": len(evid.get("carrier_encounters", [])),
        "dark_detections": int(sar["detections"].sum()) if not sar.empty else 0,
        "dark_detections_in_iez": int(sar.loc[sar.in_iez, "detections"].sum()) if not sar.empty else 0,
    }
    log.info("summary: %s", summary)
    return {"scores": scores, "evidence": evid, "hotspots": hot, "summary": summary}
