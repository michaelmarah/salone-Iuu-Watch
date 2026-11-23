"""Command line entry point.

  python -m iuu.cli fetch          # download from Global Fishing Watch (needs GFW_API_TOKEN)
  python -m iuu.cli process        # normalise -> analyse -> outputs/report.html
  python -m iuu.cli all            # fetch + process
  python -m iuu.cli discover-eez   # find Sierra Leone's EEZ id in downloaded data
  python -m iuu.cli synthetic      # generate fake raw data to test the pipeline offline
"""
from __future__ import annotations

import argparse
import logging

from . import analyze, normalize, report
from .config import RAW_DIR, load_config

log = logging.getLogger("iuu")


def process(cfg):
    ev = normalize.normalize_events(cfg)
    sar = normalize.normalize_sar(cfg)
    effort = normalize.normalize_effort(cfg)
    res = analyze.run(cfg, ev, sar)
    synthetic = (RAW_DIR / "SYNTHETIC").exists()
    path = report.write_report(cfg, res, effort, synthetic=synthetic)
    print(f"\nReport: {path}")
    print("Top flagged vessels:")
    if not res["scores"].empty:
        print(res["scores"][["vessel_name", "flag", "risk_score", "reasons"]].head(10).to_string(index=False))
    return res


def main(argv=None):
    p = argparse.ArgumentParser(prog="iuu")
    p.add_argument("command", choices=["fetch", "process", "all", "discover-eez", "synthetic"])
    p.add_argument("--config", default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config(a.config)

    if a.command in ("fetch", "all"):
        from .fetch import fetch_all
        (RAW_DIR / "SYNTHETIC").unlink(missing_ok=True)
        fetch_all(cfg)
    if a.command == "synthetic":
        from .synthetic import generate
        generate(cfg)
        print("Synthetic raw data written. Now run: python -m iuu.cli process")
    if a.command in ("process", "all"):
        process(cfg)
    if a.command == "discover-eez":
        c = normalize.eez_candidates(cfg)
        print(c.head(10).to_string(index=False) if not c.empty else "No events with EEZ ids yet; run fetch first.")
        print("\nPut Sierra Leone's id (usually the top one) in config.yaml -> aoi.eez_region_ids")


if __name__ == "__main__":
    main()
