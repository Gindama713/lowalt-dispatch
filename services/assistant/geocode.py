"""Forward geocoding: Photon first (reachable here), Nominatim as a backup.

Both are OSM-derived, so results carry OSM attribution. Providers are tried in
order and the first non-empty result wins; failures never raise to callers.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from services.assistant import amap

PHOTON = "https://photon.komoot.io/api/"
# Campus fallback area. Photon often omits the main campus of a Chinese
# university; Overpass finds the amenity=university polygon inside this box.
# Override with AERIS_PLACE_BBOX="south,west,north,east" for another city.
DEFAULT_BBOX = "28.40,115.60,29.00,116.20"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "Lowalt-Aeris-Console/0.2 (https://github.com/Gindama713/lowalt-dispatch)"


def _valid(lng, lat) -> bool:
    return (
        isinstance(lng, (int, float))
        and isinstance(lat, (int, float))
        and -180 <= lng <= 180
        and -85.0511 <= lat <= 85.0511
    )


def _row(name: str, address: str, lng: float, lat: float, kind: str = "") -> dict:
    return {
        "name": name[:200],
        "address": address[:200],
        "point": [lng, lat],
        "kind": kind,
        "source": "osm_search",
        "capturedAt": datetime.now(UTC).isoformat(),
    }


def _photon(query: str, limit: int) -> list[dict]:
    with httpx.Client(timeout=8, follow_redirects=False, trust_env=False) as client:
        # Photon only accepts default/de/en/fr; ``lang=zh`` returns HTTP 400 and
        # used to silently disable all place search (found 2026-11-17). OSM
        # already carries local names, so request without a language hint.
        response = client.get(
            PHOTON,
            params={"q": query, "limit": limit},
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        payload = response.json()
    rows = []
    for feature in (payload.get("features") or [])[:limit]:
        properties = feature.get("properties") or {}
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coordinates) != 2:
            continue
        lng, lat = float(coordinates[0]), float(coordinates[1])
        if not _valid(lng, lat):
            continue
        name = str(properties.get("name") or query)
        address = (
            " ".join(
                str(properties.get(key) or "") for key in ("state", "city", "district", "street")
            ).strip()
            or name
        )
        kind = "/".join(
            part for part in (properties.get("osm_key"), properties.get("osm_value")) if part
        )
        rows.append(_row(name, address, lng, lat, kind))
    return rows


def overpass_universities(name: str, limit: int = 8) -> list[dict]:
    """Find university/college polygons by name inside the configured box."""
    if len(name.strip()) < 4:
        return []
    raw = os.getenv("AERIS_PLACE_BBOX", DEFAULT_BBOX)
    try:
        south, west, north, east = (float(part) for part in raw.split(","))
    except ValueError:
        south, west, north, east = 28.40, 115.60, 29.00, 116.20
    safe = re.sub(r'["\\]', "", name)[:60]
    query = (
        '[out:json][timeout:25];'
        f'nwr["amenity"~"^(university|college)$"]["name"~"{safe}"]'
        f"({south},{west},{north},{east});out center tags {limit};"
    )
    from services.assistant.osm_obstacles import ENDPOINTS

    for endpoint in ENDPOINTS:
        try:
            with httpx.Client(timeout=httpx.Timeout(18, connect=5), trust_env=False,
                              headers={"User-Agent": USER_AGENT}) as client:
                response = client.post(endpoint, data={"data": query})
                response.raise_for_status()
                payload = response.json()
        except Exception:
            continue
        rows = []
        for element in payload.get("elements", [])[:limit]:
            tags = element.get("tags") or {}
            center = element.get("center") or {}
            lng, lat = center.get("lon"), center.get("lat")
            if not _valid(lng, lat):
                continue
            address = " ".join(
                str(tags.get(key) or "") for key in ("state", "city", "district", "street")
            ).strip()
            rows.append(
                _row(
                    str(tags.get("name") or name),
                    address or str(tags.get("name") or name),
                    float(lng),
                    float(lat),
                    f"amenity/{tags.get('amenity', 'university')}",
                )
            )
        return rows
    return []


def _nominatim(query: str, limit: int) -> list[dict]:
    with httpx.Client(timeout=8, follow_redirects=False, trust_env=False) as client:
        response = client.get(
            NOMINATIM,
            params={
                "q": query,
                "format": "jsonv2",
                "limit": limit,
                "accept-language": "zh-CN",
            },
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        payload = response.json()
    rows = []
    for row in (payload if isinstance(payload, list) else [])[:limit]:
        lng, lat = float(row["lon"]), float(row["lat"])
        if not _valid(lng, lat):
            continue
        display = str(row.get("display_name") or "")
        rows.append(_row(display or query, display, lng, lat))
    return rows


_CACHE: dict[tuple[str, int], tuple[float, list[dict], str]] = {}
_CACHE_TTL_S = 300.0


def lookup(query: str, limit: int = 5) -> tuple[list[dict], str]:
    """Return (rows, provider). An empty provider means every source failed.

    Amap comes first when a key is configured (Chinese POIs are much better), then
    Photon, then Nominatim. Amap results are already converted to WGS84.
    Photon intermittently answers an empty payload (measured 2026-11-17: the same
    query returned 5 rows, then 0, then 5), so every provider gets one retry and
    successful answers are cached briefly — otherwise the same place resolves
    differently between two tool calls in one turn.
    """
    cached = _CACHE.get((query, limit))
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_TTL_S:
        return cached[1], cached[2]

    providers: list[tuple[str, Callable[[str, int], list[dict]]]] = []
    if os.getenv("AMAP_WEB_KEY", "").strip():
        providers.append(("高德地图 / GCJ-02→WGS84", amap.lookup))
    providers += [
        ("OpenStreetMap / Photon", _photon),
        ("OpenStreetMap / Nominatim", _nominatim),
    ]
    responded = ""
    for name, provider in providers:
        for attempt in range(2):
            try:
                rows = provider(query, limit)
                responded = name
            except Exception:
                rows = []
            if rows:
                _CACHE[(query, limit)] = (now, rows, name)
                return rows, name
            if attempt == 0:
                time.sleep(0.25)
    return [], responded
