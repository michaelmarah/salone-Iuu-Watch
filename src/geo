"""Geography helpers: area of interest, Inshore Exclusion Zone (IEZ), distances.

Distances use a local equirectangular projection centred on Sierra Leone
(~8N). Error is well under 1% at this scale, which is fine for flagging.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, Point, box, shape

NM_TO_KM = 1.852
_LAT0 = 8.0
_KX = 111.320 * math.cos(math.radians(_LAT0))  # km per degree lon
_KY = 110.574                                   # km per degree lat


def to_km(geom):
    """Project lon/lat geometry to a local km plane."""
    return shapely.transform(geom, lambda c: c * np.array([_KX, _KY]))


def aoi_polygon(cfg: dict):
    return box(*cfg["aoi"]["bbox"])


def aoi_geojson_geometry(cfg: dict) -> dict:
    return json.loads(json.dumps(aoi_polygon(cfg).__geo_interface__))


def aoi_feature_collection(cfg: dict) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": aoi_geojson_geometry(cfg)}],
    }


@lru_cache(maxsize=4)
def _coastline_km(coords: tuple):
    return to_km(LineString(coords))


def distance_to_coast_km(cfg: dict, lon: float, lat: float) -> float:
    """Distance from a point to the APPROXIMATE coastline in config."""
    coords = tuple(tuple(c) for c in cfg["iez"]["coastline_approx"])
    return _coastline_km(coords).distance(to_km(Point(lon, lat)))


def iez_km(cfg: dict) -> float:
    return cfg["iez"]["distance_nm"] * NM_TO_KM


@lru_cache(maxsize=4)
def _load_iez_polygon(path: str):
    with open(path) as f:
        gj = json.load(f)
    if gj.get("type") == "FeatureCollection":
        gj = gj["features"][0]["geometry"]
    elif gj.get("type") == "Feature":
        gj = gj["geometry"]
    return shape(gj)


def in_iez(cfg: dict, lon: float, lat: float, distance_from_shore_km: float | None = None) -> bool:
    """Is this position inside the IEZ?

    Priority: official IEZ polygon (if configured) > GFW's distance-from-shore
    value (accurate, comes with events) > approximate coastline.
    """
    poly_path = cfg["iez"].get("geojson")
    if poly_path and Path(poly_path).exists():
        return _load_iez_polygon(str(poly_path)).contains(Point(lon, lat))
    if distance_from_shore_km is not None and not math.isnan(distance_from_shore_km):
        return distance_from_shore_km <= iez_km(cfg)
    return distance_to_coast_km(cfg, lon, lat) <= iez_km(cfg)
