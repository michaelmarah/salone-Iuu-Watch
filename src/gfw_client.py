"""Thin Global Fishing Watch API v3 client.

Docs: https://globalfishingwatch.org/our-apis/documentation
Tokens: https://globalfishingwatch.org/our-apis/tokens (non-commercial use only)

Handles auth, retries/backoff, pagination for /events, and the 4Wings report
quirks (one report per token at a time -> 429; long reports -> 524, recovered
from /4wings/last-report).
"""
from __future__ import annotations

import json
import logging
import os
import time

import requests

log = logging.getLogger(__name__)


class GFWError(RuntimeError):
    pass


class GFWClient:
    def __init__(self, cfg: dict, token: str | None = None):
        g = cfg["gfw"]
        self.base = g["base_url"].rstrip("/")
        self.timeout = g.get("timeout_s", 120)
        self.max_retries = g.get("max_retries", 5)
        self.page_limit = g.get("page_limit", 500)
        token = token or os.environ.get(g.get("token_env", "GFW_API_TOKEN"))
        if not token:
            raise GFWError(
                f"No API token. Get one at https://globalfishingwatch.org/our-apis/tokens "
                f"and run: export {g.get('token_env', 'GFW_API_TOKEN')}=<token>"
            )
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Content-Language": "en-EN"})

    # ------------------------------------------------------------------ core
    def _request(self, method: str, path: str, **kw) -> requests.Response:
        url = f"{self.base}/{path.lstrip('/')}"
        for attempt in range(self.max_retries):
            try:
                r = self.s.request(method, url, timeout=self.timeout, **kw)
            except requests.RequestException as e:
                wait = 2 ** attempt
                log.warning("network error %s, retry in %ss", e, wait)
                time.sleep(wait)
                continue
            if r.status_code in (429, 503):
                wait = min(60, 5 * 2 ** attempt)
                log.warning("%s from GFW (busy/rate-limited), retry in %ss", r.status_code, wait)
                time.sleep(wait)
                continue
            if r.status_code == 524 and "4wings/report" in path:
                log.warning("report timed out at gateway; polling last-report")
                return self._poll_last_report()
            if r.status_code >= 400:
                raise GFWError(f"{method} {url} -> {r.status_code}: {r.text[:500]}")
            return r
        raise GFWError(f"Gave up after {self.max_retries} retries: {method} {url}")

    def _poll_last_report(self, tries: int = 20, wait: int = 15) -> requests.Response:
        for _ in range(tries):
            time.sleep(wait)
            r = self.s.get(f"{self.base}/4wings/last-report", timeout=self.timeout)
            if r.status_code == 200:
                return r
            log.info("last-report not ready (%s)", r.status_code)
        raise GFWError("4Wings report never became available via last-report")

    # ---------------------------------------------------------------- events
    def events(self, dataset: str, start: str, end: str, geometry: dict | None = None,
               region: dict | None = None) -> list[dict]:
        """All events of one dataset in a date range and area (paginated POST)."""
        body = {"datasets": [dataset], "startDate": start, "endDate": end}
        if geometry:
            body["geometry"] = geometry
        if region:
            body["region"] = region
        out, offset = [], 0
        while True:
            r = self._request("POST", "events", params={"offset": offset, "limit": self.page_limit},
                              json=body)
            js = r.json()
            entries = js.get("entries", [])
            out.extend(entries)
            log.info("%s: %d events (total %s)", dataset, len(out), js.get("total"))
            nxt = js.get("nextOffset")
            if not entries or nxt is None or nxt <= offset:
                break
            offset = nxt
        return out

    # --------------------------------------------------------------- 4Wings
    def report(self, dataset: str, start: str, end: str, feature_collection: dict,
               temporal: str = "DAILY", spatial: str = "HIGH", group_by: str | None = None,
               filters: str | None = None) -> list[dict]:
        """4Wings gridded report over a custom polygon. Returns flat rows."""
        params = {
            "format": "JSON",
            "temporal-resolution": temporal,
            "spatial-resolution": spatial,
            "spatial-aggregation": "false",
            "datasets[0]": dataset,
            "date-range": f"{start},{end}",
        }
        if group_by:
            params["group-by"] = group_by
        if filters:
            params["filters[0]"] = filters
        # Docs: body has a `geojson` property holding the FeatureCollection.
        try:
            r = self._request("POST", "4wings/report", params=params,
                              json={"geojson": json.dumps(feature_collection)})
        except GFWError as e:
            if "422" not in str(e):
                raise
            log.info("retrying report with geojson as object rather than string")
            r = self._request("POST", "4wings/report", params=params,
                              json={"geojson": feature_collection})
        return flatten_report(r.json())


def flatten_report(js) -> list[dict]:
    """4Wings responses come either as entries=[{row}, ...] (each with a
    'dataset' field) or entries=[{"<dataset-id>": [rows]}]. Normalise both."""
    entries = js.get("entries", js) if isinstance(js, dict) else js
    rows: list[dict] = []
    for e in entries or []:
        if isinstance(e, dict) and all(isinstance(v, list) for v in e.values()) and e:
            for ds, items in e.items():
                for it in items:
                    rows.append({"dataset": ds, **it})
        elif isinstance(e, dict):
            rows.append(e)
    return rows
