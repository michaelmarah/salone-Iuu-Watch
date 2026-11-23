"""Interactive dashboard.

    streamlit run app.py

Reads data/processed/*.csv (made by `python -m iuu.cli process`). Filters re-run the same scoring code as the CLI.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from iuu import analyze
from iuu.config import PROCESSED_DIR, RAW_DIR, load_config
from iuu.report import build_map, base_map

st.set_page_config(page_title="Salone IUU Watch", page_icon="🌊", layout="wide")
cfg = load_config()


# ----------------------------------------------------------------- data
@st.cache_data
def load():
    def read(name):
        p = PROCESSED_DIR / name
        return pd.read_csv(p) if p.exists() else pd.DataFrame()

    ev, sar, eff = read("events.csv"), read("sar_unmatched.csv"), read("effort_by_flag.csv")
    if not ev.empty:
        ev["start"] = pd.to_datetime(ev["start"], utc=True, format="mixed")
        ev["end"] = pd.to_datetime(ev["end"], utc=True, format="mixed")
        ev["ssvid"] = ev["ssvid"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True)
        ev["in_iez"] = ev["in_iez"].astype(bool)
        ev["mpa_ids"] = ev["mpa_ids"].fillna("")
        for c in ("gap_intentional",):
            if c in ev:
                ev[c] = ev[c].fillna(False).astype(bool)
    if not sar.empty:
        sar["date"] = pd.to_datetime(sar["date"], utc=True, format="mixed")
        sar["in_iez"] = sar["in_iez"].astype(bool)
    return ev, sar, eff


ev, sar, eff = load()
if ev.empty:
    st.error("No processed data yet. Run `python -m iuu.cli synthetic` (or `fetch`) and then "
             "`python -m iuu.cli process`.")
    st.stop()

# ----------------------------------------------------------------- sidebar
st.sidebar.title("🌊 Salone IUU Watch")
dmin, dmax = ev.start.min().date(), ev.start.max().date()
dr = st.sidebar.date_input("Date range", (dmin, dmax), min_value=dmin, max_value=dmax)
d0, d1 = (dr if isinstance(dr, tuple) and len(dr) == 2 else (dmin, dmax))
flags = sorted(ev.flag.dropna().unique())
pick_flags = st.sidebar.multiselect("Flag states", flags, placeholder="All flags")
score_slot = st.sidebar.empty()  # filled once scores are computed, so its range fits the data
st.sidebar.markdown("**Map layers**")
show = {
    "iez_fishing": st.sidebar.checkbox("Fishing inside IEZ", True),
    "mpa_fishing": st.sidebar.checkbox("Fishing in MPAs", True),
    "ais_gaps": st.sidebar.checkbox("AIS gaps", True),
    "carrier_encounters": st.sidebar.checkbox("Carrier encounters", True),
    "sar": st.sidebar.checkbox("Dark radar detections", True),
}
st.sidebar.caption("Data: Global Fishing Watch (non-commercial licence). A risk score ranks vessels "
                   "for follow-up; it is not proof of illegal activity.")

# ----------------------------------------------------------------- filter + score
lo, hi = pd.Timestamp(d0, tz="UTC"), pd.Timestamp(d1, tz="UTC") + pd.Timedelta(days=1)
f = ev[(ev.start >= lo) & (ev.start < hi)]
if pick_flags:
    f = f[f.flag.isin(pick_flags)]
s = sar[(sar.date >= lo) & (sar.date < hi)] if not sar.empty else sar

evid = analyze.evidence_tables(cfg, f)
scores = analyze.score_vessels(cfg, f, evid)
top = int(scores.risk_score.max()) + 1 if not scores.empty else 1
min_score = score_slot.slider("Minimum risk score", 0, top, 0)
scores = scores[scores.risk_score >= min_score] if not scores.empty else scores
hot = analyze.sar_hotspots(s) if not s.empty else pd.DataFrame()

# ----------------------------------------------------------------- header
st.title("Illegal fishing watch: Sierra Leone")
st.caption(f"{d0} to {d1} · {len(f):,} vessel events · "
           f"Inshore Exclusion Zone = {cfg['iez']['distance_nm']} nm from shore")
if (RAW_DIR / "SYNTHETIC").exists():
    st.warning("**Synthetic data.** Generated to test the pipeline; nothing here describes real vessels.")

g = evid.get("ais_gaps", pd.DataFrame())
k = st.columns(6)
k[0].metric("Vessels flagged", len(scores))
k[1].metric("Fishing hours in IEZ", f"{evid['iez_fishing'].hours.sum():,.0f}" if "iez_fishing" in evid else 0)
k[2].metric("Fishing hours in MPAs", f"{evid['mpa_fishing'].hours.sum():,.0f}" if "mpa_fishing" in evid else 0)
k[3].metric("AIS gaps", len(g), help=f"≥ {cfg['analysis']['min_gap_hours']} h")
k[4].metric("Carrier encounters", len(evid.get("carrier_encounters", [])))
k[5].metric("Dark radar detections", int(s.detections.sum()) if not s.empty else 0,
            help="Vessels seen by Sentinel-1 radar that were not broadcasting AIS")

# ----------------------------------------------------------------- map + top list
left, right = st.columns([2.2, 1])
with left:
    layers = {k_: v for k_, v in evid.items() if show.get(k_, False)}
    m = build_map(cfg, layers, hot if show["sar"] else pd.DataFrame())
    st_folium(m, height=560, use_container_width=True, returned_objects=[], key="main_map")
with right:
    st.subheader("Top vessels")
    if scores.empty:
        st.info("No vessels match these filters.")
    for r in scores.head(8).to_dict("records"):
        with st.container(border=True):
            st.markdown(f"**{r['vessel_name'] or 'unknown'}** · {r['flag'] or '?'} · score **{r['risk_score']:.0f}**")
            st.caption(r["reasons"])

# ----------------------------------------------------------------- tabs
t1, t2, t3, t4 = st.tabs(["Vessels", "Trends", "Who fishes here", "Download evidence"])

with t1:
    st.caption("Select a row to see that vessel's events.")
    cols = ["vessel_name", "flag", "ssvid", "vessel_type", "risk_score", "iez_fishing_hours",
            "mpa_fishing_hours", "ais_gaps", "intentional_gaps", "carrier_encounters", "reasons"]
    sel = st.dataframe(scores[cols] if not scores.empty else scores, hide_index=True,
                       use_container_width=True, on_select="rerun", selection_mode="single-row",
                       column_config={"risk_score": st.column_config.ProgressColumn(
                           "risk score", min_value=0, max_value=float(scores.risk_score.max() or 1)
                           if not scores.empty else 1.0, format="%.0f")})
    rows = sel.selection.rows if sel else []
    if rows:
        v = scores.iloc[rows[0]]
        ve = f[f.ssvid == v.ssvid].sort_values("start")
        st.markdown(f"### {v.vessel_name} ({v.flag}) · MMSI {v.ssvid}")
        a, b = st.columns([1.3, 1])
        with a:
            vm = base_map(zoom=8)
            import folium
            colors = {"fishing": "#d62728", "gaps": "#ff7f0e", "encounters": "#7b3fa0", "loitering": "#888"}
            pts = ve.dropna(subset=["lat", "lon"])
            for r in pts.to_dict("records"):
                folium.CircleMarker([r["lat"], r["lon"]], radius=5 if r["in_iez"] else 3,
                                    color=colors.get(r["kind"], "#333"), fill=True,
                                    tooltip=f"{r['kind']} · {str(r['start'])[:16]}"
                                            f"{' · INSIDE IEZ' if r['in_iez'] else ''}").add_to(vm)
            if len(pts) > 1:
                folium.PolyLine(pts[["lat", "lon"]].values.tolist(), weight=1, color="#1f3b73",
                                opacity=0.4).add_to(vm)
            st_folium(vm, height=380, use_container_width=True, returned_objects=[], key="vessel_map")
        with b:
            st.dataframe(ve[["start", "kind", "hours", "dist_shore_km", "in_iez"]], hide_index=True,
                         use_container_width=True, height=380)

with t2:
    mon = lambda d, col: d.set_index(col).resample("MS")  # noqa: E731
    tr = pd.DataFrame({
        "Fishing hours in IEZ": mon(evid["iez_fishing"], "start").hours.sum() if "iez_fishing" in evid and not evid["iez_fishing"].empty else pd.Series(dtype=float),
        "AIS gaps": mon(g, "start").size() if not g.empty else pd.Series(dtype=float),
        "Dark radar detections": mon(s, "date").detections.sum() if not s.empty else pd.Series(dtype=float),
    }).fillna(0)
    tr.index = tr.index.strftime("%Y-%m")
    c1, c2, c3 = st.columns(3)
    for c, col in zip((c1, c2, c3), tr.columns):
        c.markdown(f"**{col}** per month")
        c.bar_chart(tr[col], height=240)

with t3:
    if eff.empty:
        st.info("No fishing-effort data (run fetch).")
    else:
        e = eff.copy()
        e["share %"] = (100 * e.hours / e.hours.sum()).round(1)
        st.caption("AIS apparent fishing hours by flag state, whole period")
        st.bar_chart(e.set_index("flag")["hours"].head(12), horizontal=True, height=360)

with t4:
    st.caption("Each file lists the individual events behind the scores, for checking against licence lists and VMS.")
    for name, t in [("vessel_risk", scores), *evid.items()]:
        st.download_button(f"{name}.csv ({len(t)} rows)", t.to_csv(index=False), f"{name}.csv",
                           "text/csv", key=f"dl_{name}")
