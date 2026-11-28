"""Forward geocoding: Photon first (reachable here), Nominatim as a backup.

Both are OSM-derived, so results carry OSM attribution. Providers are tried in
order and the first non-empty result wins; failures never raise to callers.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from services.assistant import amap

PHOTON = "https://photon.komoot.io/api/"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "Lowalt-Aeris-Console/0.2 (https://github.com/Gindama713/lowalt-dispatch)"


def _valid(lng: float, lat: float) -> bool:
    return -180 <= lng <= 180 and -85.0511 <= lat <= 85.0511


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
