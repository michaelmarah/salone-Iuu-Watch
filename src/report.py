"""Step 4: a single self-contained HTML report (map + flagged vessels)."""
from __future__ import annotations

import html
from datetime import datetime, timezone

import folium
import pandas as pd

from .config import OUTPUT_DIR

COLORS = {"iez": "#d62728", "gap": "#ff7f0e", "enc": "#7b3fa0", "sar": "#1f3b73", "mpa": "#2ca02c"}


def _popup(r: dict, extra: str = "") -> str:
    return (f"<b>{html.escape(str(r.get('vessel_name') or 'unknown'))}</b> "
            f"({html.escape(str(r.get('flag') or '?'))})<br>MMSI {r.get('ssvid')}<br>"
            f"{str(r.get('start'))[:16]} UTC<br>{extra}")


ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/{}/MapServer/tile/{{z}}/{{y}}/{{x}}"
BASEMAPS = [
    # (name, url, attribution). OpenStreetMap's own servers refuse pages opened
    # from disk (file://), so we use providers that allow it.
    ("Ocean", ESRI.format("Ocean/World_Ocean_Base"), "Tiles &copy; Esri, GEBCO, NOAA, Garmin"),
    ("Satellite", ESRI.format("World_Imagery"), "Tiles &copy; Esri, Maxar, Earthstar Geographics"),
    ("Light", "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
     "&copy; OpenStreetMap contributors &copy; CARTO"),
]


def base_map(zoom: int = 8) -> folium.Map:
    m = folium.Map(location=[7.9, -13.2], zoom_start=zoom, tiles=None)
    for i, (name, url, attr) in enumerate(BASEMAPS):
        folium.TileLayer(url, attr=attr, name=name, max_zoom=16, overlay=False, control=True,
                         show=(i == 0)).add_to(m)
    return m


def build_map(cfg: dict, evid: dict, hot: pd.DataFrame) -> folium.Map:
    m = base_map()

def build_report(cfg: dict, res: dict, effort: pd.DataFrame | None = None, synthetic: bool = False) -> str:
    s, scores = res["summary"], res["scores"]
    m = build_map(cfg, res["evidence"], res["hotspots"])
    cards = [
        ("Vessels flagged", s["vessels_flagged"]),
        ("Fishing events inside IEZ", s["iez_fishing_events"]),
        ("Hours fishing inside IEZ", f"{s['iez_fishing_hours']:.0f}"),
        ("AIS gaps", s["ais_gaps"]),
        ("Carrier encounters", s["carrier_encounters"]),
        ("Dark radar detections", s["dark_detections"]),
    ]
    cards_html = "".join(f"<div class=card><div class=v>{v}</div><div class=k>{k}</div></div>" for k, v in cards)

    cols = ["vessel_name", "flag", "ssvid", "vessel_type", "risk_score", "reasons"]
    top = scores.head(25)[cols] if not scores.empty else pd.DataFrame(columns=cols)
    rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(r[c]) if pd.notna(r[c]) else '')}</td>" for c in cols) + "</tr>"
        for r in top.to_dict("records"))

    eff = ""
    if effort is not None and not effort.empty:
        tot = effort.hours.sum()
        eff = "<h2>Who fishes here (AIS apparent fishing hours by flag)</h2><table><tr><th>Flag</th><th>Hours</th><th>Share</th></tr>" + "".join(
            f"<tr><td>{html.escape(str(r['flag']))}</td><td>{r['hours']:.0f}</td><td>{100 * r['hours'] / tot:.0f}%</td></tr>"
            for r in effort.head(10).to_dict("records")) + "</table>"

    banner = ("<div class=warn><b>SYNTHETIC DATA.</b> This report was generated from simulated records "
              "to test the pipeline. Nothing here describes real vessels.</div>") if synthetic else ""
    dr = cfg["date_range"]
    return f"""<!DOCTYPE html><html><head><meta charset=utf-8><title>Sierra Leone IUU fishing watch</title>
<style>
body{{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#1d2433}}
h1{{margin-bottom:4px}} .sub{{color:#5b6475;margin-top:0}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}}
.card{{border:1px solid #e2e6ee;border-radius:10px;padding:12px}} .v{{font-size:26px;font-weight:650}} .k{{color:#5b6475;font-size:13px}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-bottom:24px}} td,th{{border-bottom:1px solid #eceff4;padding:6px;text-align:left;vertical-align:top}}
.warn{{background:#fff4e5;border:1px solid #f5c27a;padding:10px 12px;border-radius:8px}}
.note{{color:#5b6475;font-size:13px}}
</style></head><body>
<h1>Sierra Leone IUU fishing watch</h1>
<p class=sub>{dr['start']} to {dr['end']} &middot; generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC &middot; data: Global Fishing Watch</p>
{banner}
<div class=cards>{cards_html}</div>
<h2>Map</h2>{m._repr_html_()}
<h2>Vessels worth investigating</h2>
<p class=note>Score = weighted sum of the listed signals. It ranks vessels for follow-up; it is not proof of illegal activity.
Fishing positions come from AIS and Global Fishing Watch's fishing-detection model; check each case against licence lists and VMS.</p>
<table><tr>{''.join(f'<th>{c}</th>' for c in cols)}</tr>{rows}</table>
{eff}
</body></html>"""


def write_report(cfg, res, effort=None, synthetic=False):
    p = OUTPUT_DIR / "report.html"
    p.write_text(build_report(cfg, res, effort, synthetic))
    build_map(cfg, res["evidence"], res["hotspots"]).save(str(OUTPUT_DIR / "map.html"))
    return p
