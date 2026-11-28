"""China-wide DJI FlySafe overlay for the map. Not a planning snapshot.

The planning path queries a small bbox and fail-closes above 100 zones.
A national set is larger than that, so this module never builds a
``ConstraintSnapshot`` and never feeds route avoidance. Only the existing
planning snapshot still hard-avoids restricted / regulatory_restricted zones.

The rectangle below is a documented display envelope for the device-geofence
query. It is not a legal boundary. ``dji-geo`` auto-splits each tile and
deduplicates within that tile. A tile that fails is omitted; its geometry is
not invented. The overlay is then marked incomplete.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from services.assistant import flysafe as flysafe_mod
from services.assistant.flysafe import FLYSAFE_SOURCE, clean_drone_slug

# West near the Pamirs, east near the Ussuri, south across Hainan, north near
# the Heilongjiang border. Stays clear of the antimeridian. Not a boundary claim.
CHINA_DISPLAY_ENVELOPE = (73.5, 18.0, 135.1, 53.6)
# Coarse tiles. Each one is handed to dji-geo, which splits it under its
# 350 km diagonal limit and deduplicates. One failed coarse tile does not
# erase the tiles that succeeded.
TILE_LNG_DEG = 8.0
TILE_LAT_DEG = 6.0
NATIONAL_RED = "#d64545"
NATIONAL_HTTP_TIMEOUT_S = 30.0
CACHE_NAME = "china.json"
CACHE_MAX_AGE_S = 24 * 60 * 60
_SCHEMA = "aeris-flysafe-national-1"


def china_display_tiles() -> list[tuple[float, float, float, float]]:
    west, south, east, north = CHINA_DISPLAY_ENVELOPE
    tiles: list[tuple[float, float, float, float]] = []
    lat = south
    while lat < north - 1e-9:
        lat2 = min(north, round(lat + TILE_LAT_DEG, 6))
        lng = west
        while lng < east - 1e-9:
            lng2 = min(east, round(lng + TILE_LNG_DEG, 6))
            tiles.append((round(lng, 6), round(lat, 6), lng2, lat2))
            lng = lng2
        lat = lat2
    return tiles


def national_cache_path(root: Path | None = None) -> Path:
    if root is not None:
        path = Path(root)
    else:
        configured = os.getenv("AERIS_FLYSAFE_CACHE_DIR", "").strip()
        path = Path(configured) if configured else Path("logs") / "flysafe-national"
    path.mkdir(parents=True, exist_ok=True)
    return path / CACHE_NAME


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load(path: Path) -> dict | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("schema") != _SCHEMA:
        return None
    collection = raw.get("feature_collection")
    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        return None
    if not isinstance(collection.get("features"), list):
        return None
    return raw


def _write(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _paint(feature: dict) -> dict | None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        return None
    gtype = geometry.get("type")
    if gtype not in {"Polygon", "MultiPolygon"}:
        return None
    props = feature.get("properties")
    if not isinstance(props, dict):
        props = {}
    else:
        props = dict(props)
    props["display_color"] = NATIONAL_RED
    props["overlay"] = "flysafe-national"
    props["reference_label"] = FLYSAFE_SOURCE
    feature_id = feature.get("id")
    if feature_id is None:
        area = props.get("area_id")
        part = props.get("part_index", 1)
        feature_id = f"{area}-{part}"
    return {
        "type": "Feature",
        "id": str(feature_id),
        "geometry": geometry,
        "properties": props,
    }


def _merge(collections: list[dict]) -> list[dict]:
    seen: set[str] = set()
    features: list[dict] = []
    for collection in collections:
        raw_features = collection.get("features") if isinstance(collection, dict) else None
        if not isinstance(raw_features, list):
            continue
        for item in raw_features:
            if not isinstance(item, dict):
                continue
            painted = _paint(item)
            if painted is None:
                continue
            feature_id = str(painted["id"])
            if feature_id in seen:
                continue
            seen.add(feature_id)
            features.append(painted)
    return features


def _honesty(*, incomplete: bool, retained: bool, failed: bool) -> str:
    base = (
        "大疆 FlySafe 厂商地理围栏参考，覆盖文档中的中国范围矩形，"
        "不是法定空域、不是 UOM / 天地图、不是飞行批准。"
        "图上这些围栏一律红色，不进入航线硬避让；"
        "硬避让仍只用起终点附近约束快照里的禁飞区。"
    )
    if retained and failed:
        return "本次全国刷新失败，地图仍显示上次成功获取的全国厂商围栏。" + base
    if incomplete:
        return "本次全国刷新不完整，失败分块没有补造几何。" + base
    return base


def _payload(
    *,
    status: str,
    features: list[dict],
    incomplete: bool,
    failure_reason: str | None,
    fetched_at: str | None,
    retained_prior: bool,
    failed_tiles: list[dict],
    skipped_refresh: bool = False,
) -> dict:
    failed = bool(failure_reason) and retained_prior
    return {
        "status": status,
        "reference_label": FLYSAFE_SOURCE,
        "envelope": list(CHINA_DISPLAY_ENVELOPE),
        "incomplete": incomplete,
        "retained_prior": retained_prior,
        "skipped_refresh": skipped_refresh,
        "failure_reason": failure_reason,
        "failed_tile_count": len(failed_tiles),
        "zone_count": len(features),
        "fetched_at": fetched_at,
        "note": _honesty(
            incomplete=incomplete, retained=failed or (retained_prior and incomplete), failed=failed
        )
        if features
        else (failure_reason or "全国 FlySafe 图层没有可显示的几何，未编造围栏。"),
        "features": {"type": "FeatureCollection", "features": features},
        "dispatch_enabled": False,
        "operationally_approved": False,
    }


def _from_record(record: dict, *, failure_reason: str | None, retained: bool, status: str) -> dict:
    collection = record["feature_collection"]
    features = [item for item in collection.get("features", []) if isinstance(item, dict)]
    incomplete = bool(record.get("incomplete"))
    return _payload(
        status=status,
        features=features,
        incomplete=incomplete,
        failure_reason=failure_reason if failure_reason is not None else record.get("failure_reason"),
        fetched_at=record.get("fetched_at"),
        retained_prior=retained,
        failed_tiles=list(record.get("failed_tiles") or []),
    )


def _cache_fresh(record: dict) -> bool:
    stamp = record.get("fetched_at")
    if not isinstance(stamp, str):
        return False
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - parsed).total_seconds()
    return age >= 0 and age < CACHE_MAX_AGE_S and not record.get("incomplete")


def live_fetch_national_tiles(
    tiles: list[tuple[float, float, float, float]],
    *,
    drone: str,
) -> list[dict | BaseException]:
    """Query each coarse tile with dji-geo. One tile error does not cancel the others."""

    if sys.version_info < (3, 12):
        raise RuntimeError("当前 Python 低于 3.12，不能安装 dji-geo，未查询全国 FlySafe")
    try:
        from dji_geo import BBox, DjiGeoClient, RetryPolicy
    except ImportError as exc:
        raise RuntimeError("未安装 dji-geo，未查询全国 FlySafe") from exc

    async def _run() -> list[dict | BaseException]:
        async with DjiGeoClient(
            default_drone=drone,
            timeout_s=NATIONAL_HTTP_TIMEOUT_S,
            retry=RetryPolicy(max_retries=2, base_delay_s=0.4, max_delay_s=2.0, jitter=False),
            max_concurrency=4,
        ) as client:
            semaphore = asyncio.Semaphore(3)

            async def one(bbox: tuple[float, float, float, float]) -> dict:
                async with semaphore:
                    west, south, east, north = bbox
                    result = await client.query_rectangle(
                        BBox(west=west, south=south, east=east, north=north),
                        drone=drone,
                        auto_tile=True,
                    )
                    return result.to_geojson(circle_segments=32)

            return list(await asyncio.gather(*(one(tile) for tile in tiles), return_exceptions=True))

    return asyncio.run(_run())


def refresh_national_overlay(
    *,
    fetcher=None,
    cache_path: Path | None = None,
    force: bool = False,
    drone: str | None = None,
) -> dict:
    """Refresh the national display overlay.

    ``fetcher`` is ``(bbox, drone) -> FeatureCollection``. Tests pass a fake.
    When live query is off and no fetcher is passed, this does not touch the network.
    """

    path = cache_path or national_cache_path()
    cached = _load(path)
    if fetcher is None and not flysafe_mod.flysafe_live_enabled():
        if cached is not None:
            body = _from_record(
                cached,
                failure_reason="本进程未开启大疆 FlySafe 实时查询（AERIS_FLYSAFE_LIVE=0），未访问大疆网络。",
                retained=True,
                status="disabled",
            )
            body["note"] = (
                "本进程未开启实时查询，地图显示上次保存的全国厂商围栏，未访问大疆网络。"
                "大疆 FlySafe 厂商地理围栏参考，不是法定空域、不是 UOM / 天地图、不是飞行批准。"
            )
            return body
        return _payload(
            status="disabled",
            features=[],
            incomplete=False,
            failure_reason="本进程未开启大疆 FlySafe 实时查询（AERIS_FLYSAFE_LIVE=0），未编造围栏。",
            fetched_at=None,
            retained_prior=False,
            failed_tiles=[],
        )
    if fetcher is None and cached is not None and not force and _cache_fresh(cached):
        body = _from_record(cached, failure_reason=None, retained=False, status="ready")
        body["skipped_refresh"] = True
        return body

    drone_slug = clean_drone_slug(drone)
    tiles = china_display_tiles()
    failed: list[dict] = []
    collections: list[dict] = []
    if fetcher is None:
        try:
            results = live_fetch_national_tiles(tiles, drone=drone_slug)
        except Exception as exc:
            reason = f"全国 FlySafe 查询没有执行：{type(exc).__name__}: {str(exc)[:180]}。未编造围栏。"
            if cached is not None:
                body = _from_record(cached, failure_reason=reason, retained=True, status="ready")
                body["incomplete"] = bool(cached.get("incomplete"))
                body["note"] = _honesty(incomplete=False, retained=True, failed=True)
                return body
            return _payload(
                status="unavailable",
                features=[],
                incomplete=False,
                failure_reason=reason,
                fetched_at=None,
                retained_prior=False,
                failed_tiles=[],
            )
        for bbox, result in zip(tiles, results, strict=True):
            if isinstance(result, BaseException):
                failed.append(
                    {
                        "bbox": list(bbox),
                        "error": f"{type(result).__name__}: {str(result)[:180]}",
                    }
                )
                continue
            if isinstance(result, dict):
                collections.append(result)
            else:
                failed.append({"bbox": list(bbox), "error": "分块结果不是 GeoJSON，已丢弃"})
    else:
        for bbox in tiles:
            try:
                collection = fetcher(bbox, drone=drone_slug)
            except Exception as exc:
                failed.append(
                    {
                        "bbox": list(bbox),
                        "error": f"{type(exc).__name__}: {str(exc)[:180]}",
                    }
                )
                continue
            if not isinstance(collection, dict):
                failed.append({"bbox": list(bbox), "error": "分块结果不是 GeoJSON，已丢弃"})
                continue
            collections.append(collection)

    features = _merge(collections)
    incomplete = bool(failed)
    if not features:
        reason = (
            "全国 FlySafe 本次没有取回任何围栏，未编造几何。"
            if not failed
            else f"全国 FlySafe 全部分块失败（{len(failed)}），未编造围栏。"
        )
        if cached is not None:
            body = _from_record(cached, failure_reason=reason, retained=True, status="ready")
            body["note"] = _honesty(incomplete=bool(cached.get("incomplete")), retained=True, failed=True)
            return body
        return _payload(
            status="unavailable",
            features=[],
            incomplete=incomplete,
            failure_reason=reason,
            fetched_at=None,
            retained_prior=False,
            failed_tiles=failed,
        )

    fetched_at = _now()
    record = {
        "schema": _SCHEMA,
        "incomplete": incomplete,
        "fetched_at": fetched_at,
        "envelope": list(CHINA_DISPLAY_ENVELOPE),
        "drone": drone_slug,
        "failed_tiles": failed,
        "failure_reason": (f"有 {len(failed)} 个分块失败，这些分块没有补造几何。" if incomplete else None),
        "feature_collection": {"type": "FeatureCollection", "features": features},
    }
    _write(path, record)
    return _payload(
        status="incomplete" if incomplete else "ready",
        features=features,
        incomplete=incomplete,
        failure_reason=record["failure_reason"],
        fetched_at=fetched_at,
        retained_prior=False,
        failed_tiles=failed,
    )


def read_national_overlay(*, cache_path: Path | None = None) -> dict:
    """Return the on-disk overlay. Never contacts DJI."""

    path = cache_path or national_cache_path()
    cached = _load(path)
    if cached is None:
        if not flysafe_mod.flysafe_live_enabled():
            return _payload(
                status="disabled",
                features=[],
                incomplete=False,
                failure_reason="本进程未开启大疆 FlySafe 实时查询（AERIS_FLYSAFE_LIVE=0），未编造围栏。",
                fetched_at=None,
                retained_prior=False,
                failed_tiles=[],
            )
        return _payload(
            status="empty",
            features=[],
            incomplete=False,
            failure_reason=None,
            fetched_at=None,
            retained_prior=False,
            failed_tiles=[],
        )
    status = "incomplete" if cached.get("incomplete") else "ready"
    return _from_record(cached, failure_reason=cached.get("failure_reason"), retained=False, status=status)
