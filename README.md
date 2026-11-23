# Sierra Leone IUU Fishing Watch

Flags likely illegal, unreported and unregulated (IUU) fishing in Sierra Leone's
waters using open data from [Global Fishing Watch](https://globalfishingwatch.org)
(AIS vessel tracks, GFW's fishing-detection model, and Sentinel-1 radar detections).

The goal is **evidence that someone can act on**: every flagged vessel comes with
the specific events behind it (where, when, how long), exported as CSVs and an
HTML map report.

## What it detects (v0.1)

| Signal | Why it matters | Source |
|---|---|---|
| Apparent fishing **inside the Inshore Exclusion Zone** (~6 nm, reserved for artisanal fishers) | Industrial vessels raiding canoe fishing grounds | GFW fishing events + distance-from-shore |
| Fishing inside **marine protected areas** | e.g. Yawri Bay | GFW fishing events, MPA regions |
| **AIS gaps** (vessel switches its transponder off) | Hiding activity; GFW flags likely-intentional gaps | GFW gap events |
| **Encounters with carrier vessels** | Possible at-sea transshipment (laundering catch) | GFW encounter events |
| **Dark radar detections** (vessel on Sentinel-1 radar with no AIS) | Boats not broadcasting at all | GFW SAR presence, `matched='false'` |
| No public authorization found | Weak signal only: licences may simply not be published | GFW vessel info |

Signals combine into a transparent **risk score** (weights in `config.yaml`). A high
score means *worth investigating*, not *proven illegal*.

## Pipeline

```
fetch (GFW API) -> data/raw/*.json        raw responses kept for traceability
normalize       -> data/processed/*.csv   tidy tables, IEZ/EEZ tagging
analyze         -> outputs/vessel_risk.csv, outputs/evidence_*.csv, sar_dark_hotspots.csv
report          -> outputs/report.html, outputs/map.html
```

## Quick start

```bash
pip install -r requirements.txt

# 1. Test offline with synthetic data (no token needed)
python -m iuu.cli synthetic
python -m iuu.cli process          # open outputs/report.html
python -m pytest -q

# 2. Real data
#    Get a free non-commercial token: https://globalfishingwatch.org/our-apis/tokens
export GFW_API_TOKEN=your_token
python -m iuu.cli fetch
python -m iuu.cli discover-eez     # paste Sierra Leone's EEZ id into config.yaml
python -m iuu.cli process
```

## Before you trust the output: known gaps

1. **First real run.** The parsers were built from GFW's v3 docs and tested on
   synthetic data shaped like those responses. Check the field fill rates in
   `data/processed/events.csv`, especially gap and encounter fields, and adjust
   `iuu/normalize.py` if GFW names something differently.
2. **IEZ boundary.** For events, the IEZ check uses GFW's distance-from-shore
   (good). For radar detections, it uses a rough hand-drawn coastline in
   `config.yaml`. Replace it with the official IEZ coordinates (First Schedule,
   Fisheries and Aquaculture Regulations 2019) as a GeoJSON and set `iez.geojson`.
3. **AOI box** overlaps Guinea and Liberia until you set `aoi.eez_region_ids`.
4. **Licensed vs unlicensed.** Cross-check flagged vessels against the Ministry of
   Fisheries and Marine Resources licence list. That's the most valuable data join
   you can add.
5. AIS fishing detection is a model and can be wrong (slow transits look like
   fishing). Treat single short events cautiously; repeated patterns are stronger.

## Roadmap

- **v0.2 data:** official IEZ polygon, licence list join, vessel identity history (flag/name changes).
- **v0.3 ML:** learn from confirmed cases (arrests, fines, observer reports) to replace
  hand-set weights; anomaly detection on vessel tracks; classify dark radar
  detections (industrial trawler vs canoe) by size.
- **v0.4 delivery:** monthly automated run plus a short Krio/English bulletin for
  fishermen's unions, journalists and the ministry.

Data: Global Fishing Watch API, non-commercial licence. Credit GFW in anything you publish.

