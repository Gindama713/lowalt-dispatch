"""Query DJI FlySafe device geofences and bind them as a ConstraintSnapshot.

The published PyPI package ``dji-geo`` (https://github.com/mochenya/dji-geo) is
the client. This module does not vendor that source tree. As of the 0.1.0
release uploaded on 2026-11-20, the upstream repository had no LICENSE file and
the wheel metadata does not declare one.

Results are labeled 大疆 FlySafe 厂商地理围栏参考. They are not statutory
airspace, not UOM / 国家地图官网 / 天地图 data, and not a flight approval.
An empty response or a failed fetch becomes ``source_status="unavailable"``
with no invented geometry. A route that clears the returned zones has only
passed this known manufacturer-reference snapshot.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
import sys
from datetime import UTC, datetime

from planner.georef import enu_to_wgs84, wgs84_to_enu
from services.assistant.airspace_snapshot import ConstraintSnapshot, ConstraintZone

FLYSAFE_SOURCE = "大疆 FlySafe 厂商地理围栏参考"
DEFAULT_DRONE = "dji-mini-3"
QUERY_PADDING_M = 800.0
MAX_ZONES = 100
_DRONE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")

# Upstream category -> existing seven-class kind. Only restricted zones (and
# the manufacturer's regulatory-restricted class, treated conservatively as
# restricted) enter hard avoidance. Altitude and warning classes stay on the
# map; phase-1 does not invent a vertical clearance from an unverified height.
_CATEGORY_KIND = {
    "warning": "warning",
    "authorization": "authorization",
    "restricted": "restricted",
    "altitude": "altitude",
    "enhanced_warning": "enhanced_warning",
    "recommended": "suitable",
    "regulatory_restricted": "restricted",
    "approved": "suitable",
    "special_height": "altitude",
    "unknown": "warning",
}


def flysafe_live_enabled() -> bool:
    """Live FlySafe calls are on unless the process sets ``AERIS_FLYSAFE_LIVE=0``.

    Tests and the Playwright assistant set the flag to ``0`` so CI never
    contacts flysafe-api.dji.com. A disabled process returns no snapshot
    instead of an empty success.
    """

    return os.getenv("AERIS_FLYSAFE_LIVE", "1") != "0"


def clean_drone_slug(value: str | None) -> str:
    slug = (value or DEFAULT_DRONE).strip().lower()
    if not _DRONE_SLUG.match(slug):
        raise ValueError("机型查询标识无效；未使用该值请求大疆 FlySafe")
    return slug


def planning_bbox(
    origin: list[float] | tuple[float, float],
    destination: list[float] | tuple[float, float],
    *,
    padding_m: float = QUERY_PADDING_M,
) -> tuple[float, float, float, float]:
    """WGS84 bbox around the two endpoints, padded in the local ENU frame.

    ``padding_m`` is a planning query margin (default 800 m), not a regulatory
    buffer and not the project zone buffer used by conflict checks.
    """

    start = (float(origin[0]), float(origin[1]))
    goal = (float(destination[0]), float(destination[1]))
    if not all(math.isfinite(v) for v in (*start, *goal, padding_m)) or padding_m < 0:
        raise ValueError("起终点坐标无效，未查询大疆 FlySafe")
    reference = ((start[0] + goal[0]) / 2.0, (start[1] + goal[1]) / 2.0)
    lngs: list[float] = []
    lats: list[float] = []
    for lng, lat in (start, goal):
        east, north = wgs84_to_enu(reference, (lng, lat))
        for dx in (-padding_m, padding_m):
            for dy in (-padding_m, padding_m):
                padded_lng, padded_lat = enu_to_wgs84(reference, (east + dx, north + dy))
                lngs.append(padded_lng)
                lats.append(padded_lat)
    west, east = min(lngs), max(lngs)
    south, north = min(lats), max(lats)
    if west >= east or south >= north or east - west > 170 or west < -180 or east > 180:
        raise ValueError("规划范围无效或跨过 180° 经线，未查询大疆 FlySafe")
    return (west, south, east, north)


def _unavailable(
    reason: str,
    *,
    zone_buffer_m: float,
    scheduled_for: str | None,
) -> ConstraintSnapshot:
    return ConstraintSnapshot.build(
        zones=[],
        source_status="unavailable",
        zone_buffer_m=zone_buffer_m,
        scheduled_for=scheduled_for,
        failure_reason=reason[:500],
    )


def _aware_stamp(value: object) -> str:
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            return parsed.isoformat()
    return datetime.now(UTC).isoformat()


def _optional_window(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.isoformat()


def _close_ring(ring: object) -> list[list[float]]:
    if not isinstance(ring, list):
        raise ValueError("多边形环不是坐标数组")
    cleaned: list[list[float]] = []
    for pt in ring:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            raise ValueError("多边形顶点无效")
        lng, lat = round(float(pt[0]), 7), round(float(pt[1]), 7)
        if not cleaned or cleaned[-1] != [lng, lat]:
            cleaned.append([lng, lat])
    if len(cleaned) >= 3 and cleaned[0] != cleaned[-1]:
        cleaned.append(list(cleaned[0]))
    return cleaned


def _geometry_from_feature(geometry: object) -> dict:
    if not isinstance(geometry, dict):
        raise ValueError("缺少 geometry")
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Polygon":
        if not isinstance(coords, list) or not coords:
            raise ValueError("Polygon 坐标为空")
        rings = [_close_ring(ring) for ring in coords]
        return {"type": "Polygon", "coordinates": rings}
    if gtype == "MultiPolygon":
        if not isinstance(coords, list) or not coords:
            raise ValueError("MultiPolygon 坐标为空")
        polygons = []
        for poly in coords:
            if not isinstance(poly, list) or not poly:
                raise ValueError("MultiPolygon 成员无效")
            polygons.append([_close_ring(ring) for ring in poly])
        return {"type": "MultiPolygon", "coordinates": polygons}
    raise ValueError(f"不支持的几何类型 {gtype}；圆形须先由 dji-geo 离散为多边形")


def _zone_from_feature(feature: dict, *, drone: str, stamp: str) -> ConstraintZone:
    props = feature.get("properties")
    if not isinstance(props, dict):
        raise ValueError("要素缺少 properties")
    category = str(props.get("category") or "unknown")
    kind = _CATEGORY_KIND.get(category, "warning")
    area_id = props.get("area_id")
    part_index = props.get("part_index", 1)
    try:
        area_text = str(int(area_id))
        part_text = str(int(part_index))
    except (TypeError, ValueError) as exc:
        raise ValueError("区域缺少 area_id / part_index") from exc
    zone_id = f"flysafe-{area_text}-{part_text}"
    name = str(props.get("name") or "").strip() or f"FlySafe {area_text}-{part_text}"
    height = props.get("height_m")
    height_note = ""
    if isinstance(height, (int, float)) and not isinstance(height, bool):
        height_note = f"上游高度字段 {height:g} m，高度基准未核实，未作为放行或越顶依据。"
    circle_note = ""
    if props.get("circle_polygon_approximation") is True:
        radius = props.get("radius_m")
        circle_note = (
            f"圆形围栏已按 dji-geo 离散为多边形"
            f"{f'（半径约 {radius:g} m）' if isinstance(radius, (int, float)) and not isinstance(radius, bool) else ''}。"
        )
    category_note = {
        "regulatory_restricted": "上游类别为法规限制区参考，按禁飞区保守避让；不是官方 UOM 数据。",
        "recommended": "上游类别为推荐区，只作地图参考，不是法定适飞空域。",
        "approved": "上游类别为厂商适飞/批准区参考，不是行政许可。",
        "unknown": "上游类别未知，只作警示展示，未纳入硬避让。",
        "altitude": "限高区只作地图参考；未核验高度基准，不能据此越顶。",
        "special_height": "特殊限高只作地图参考；未核验高度基准，不能据此越顶。",
    }.get(category, "")
    description = " ".join(
        part
        for part in (
            "大疆 FlySafe 厂商地理围栏参考，不是法定空域，也不是飞行批准。",
            category_note,
            height_note,
            circle_note,
            f"查询机型标识 {drone}。坐标按 dji-geo 的 WGS-84 假设，尚未独立核验。",
        )
        if part
    )
    return ConstraintZone(
        id=zone_id,
        name=name[:200],
        kind=kind,
        geometry=_geometry_from_feature(feature.get("geometry")),
        source=FLYSAFE_SOURCE,
        source_ref=(
            f"dji-geo==0.1.0;drone={drone};area={area_text};part={part_text};"
            f"category={category};crs_verified=false"
        )[:1000],
        source_kind="manufacturer",
        is_simulated=False,
        fetched_at=stamp,
        updated_at=stamp,
        effective_from=_optional_window(props.get("effective_from")),
        effective_until=_optional_window(props.get("effective_until")),
        altitude_ref=None,
        max_height_m=None,
        description=description[:1500],
    )


def prior_supplements(prior: ConstraintSnapshot | None) -> list[ConstraintZone]:
    """Keep manual imports and drill corridors. Drop previously fetched FlySafe zones."""

    if prior is None:
        return []
    return [zone for zone in prior.zones if zone.source != FLYSAFE_SOURCE]


def retain_prior_flysafe(
    failed: ConstraintSnapshot,
    prior: ConstraintSnapshot | None,
    *,
    scheduled_for: str | None,
) -> ConstraintSnapshot:
    """Keep the last successful FlySafe polygons when a later refresh fails.

    Does not invent geometry. A prior ``manufacturer_reference`` snapshot that
    already contains FlySafe zones stays that status, including manual or drill
    supplements. ``fetched_at`` stays the prior success time. With no such
    geometry, the failed snapshot is returned unchanged.
    """

    if failed.source_status != "unavailable" or prior is None:
        return failed
    if prior.source_status != "manufacturer_reference":
        return failed
    flysafe_zones = [zone for zone in prior.zones if zone.source == FLYSAFE_SOURCE]
    if not flysafe_zones:
        return failed
    seen = {zone.id for zone in flysafe_zones}
    supplements = [zone for zone in prior_supplements(prior) if zone.id not in seen]
    detail = (failed.failure_reason or "").strip()
    note = "本次刷新失败，地图仍显示上次成功获取的大疆 FlySafe 厂商地理围栏。"
    reason = f"{note}{detail}" if detail else note
    return ConstraintSnapshot.build(
        zones=[*flysafe_zones, *supplements],
        source_status="manufacturer_reference",
        zone_buffer_m=failed.zone_buffer_m,
        scheduled_for=scheduled_for,
        fetched_at=prior.fetched_at,
        failure_reason=reason[:1500],
    )


def _with_supplements(
    snapshot: ConstraintSnapshot,
    supplements: list[ConstraintZone],
    *,
    scheduled_for: str | None,
) -> ConstraintSnapshot:
    existing_ids = {zone.id for zone in snapshot.zones}
    supplements = [zone for zone in supplements if zone.id not in existing_ids]
    if not supplements:
        return snapshot
    if len(snapshot.zones) + len(supplements) > MAX_ZONES:
        return _unavailable(
            f"大疆 FlySafe 与已有附加区合计超过 {MAX_ZONES}，未截断冒充完整快照",
            zone_buffer_m=snapshot.zone_buffer_m,
            scheduled_for=scheduled_for,
        )
    return ConstraintSnapshot.build(
        zones=[*snapshot.zones, *supplements],
        source_status=snapshot.source_status,
        zone_buffer_m=snapshot.zone_buffer_m,
        scheduled_for=scheduled_for,
        fetched_at=snapshot.fetched_at,
        failure_reason=snapshot.failure_reason,
    )


def snapshot_from_flysafe_collection(
    collection: dict,
    *,
    drone: str,
    zone_buffer_m: float = 0.0,
    scheduled_for: str | None = None,
    prior: ConstraintSnapshot | None = None,
) -> ConstraintSnapshot:
    """Convert a dji-geo GeoJSON FeatureCollection into a constraint snapshot.

    Fail closed: a bad feature, an empty collection, or more than 100 zones
    yields ``unavailable`` and no geometry. Drill-corridor zones already on
    ``prior`` (``source_ref`` starting with ``simulation:``) are appended and
    stay labeled as exercises. Manual imports are not promoted to the primary
    source.
    """

    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        return _unavailable(
            "大疆 FlySafe 返回不是 GeoJSON FeatureCollection，未编造围栏",
            zone_buffer_m=zone_buffer_m,
            scheduled_for=scheduled_for,
        )
    features = collection.get("features")
    if not isinstance(features, list):
        return _unavailable(
            "大疆 FlySafe 返回缺少 features，未编造围栏",
            zone_buffer_m=zone_buffer_m,
            scheduled_for=scheduled_for,
        )
    if len(features) == 0:
        return _unavailable(
            "大疆 FlySafe 返回 0 个区域，空域未知，不是放行",
            zone_buffer_m=zone_buffer_m,
            scheduled_for=scheduled_for,
        )
    supplements = prior_supplements(prior)
    if len(features) > MAX_ZONES or len(features) + len(supplements) > MAX_ZONES:
        return _with_supplements(
            _unavailable(
                f"大疆 FlySafe 返回 {len(features)} 个区域，连同附加区超过 {MAX_ZONES}，未截断冒充完整快照",
                zone_buffer_m=zone_buffer_m,
                scheduled_for=scheduled_for,
            ),
            supplements if len(supplements) <= MAX_ZONES else [],
            scheduled_for=scheduled_for,
        )
    stamp = _aware_stamp((collection.get("dji_source") or {}).get("queried_at_utc"))
    try:
        zones = [_zone_from_feature(feature, drone=drone, stamp=stamp) for feature in features]
        seen: set[str] = set()
        unique: list[ConstraintZone] = []
        for zone in zones:
            zone_id = zone.id
            suffix = 2
            while zone_id in seen:
                zone_id = f"{zone.id}-{suffix}"
                suffix += 1
            seen.add(zone_id)
            unique.append(zone if zone_id == zone.id else zone.model_copy(update={"id": zone_id}))
        built = ConstraintSnapshot.build(
            zones=unique,
            source_status="manufacturer_reference",
            zone_buffer_m=zone_buffer_m,
            scheduled_for=scheduled_for,
            fetched_at=stamp,
        )
        return _with_supplements(built, supplements, scheduled_for=scheduled_for)
    except (TypeError, ValueError) as exc:
        return _unavailable(
            f"大疆 FlySafe 几何无法绑定为约束快照：{exc}。未编造替代围栏",
            zone_buffer_m=zone_buffer_m,
            scheduled_for=scheduled_for,
        )


def live_fetch_feature_collection(
    bbox: tuple[float, float, float, float],
    *,
    drone: str,
) -> dict:
    """Call ``dji-geo`` once. Tests must not use this; pass a fake fetcher."""

    if sys.version_info < (3, 12):
        raise RuntimeError("当前 Python 低于 3.12，不能安装 dji-geo，未查询大疆 FlySafe")
    try:
        from dji_geo import BBox, DjiGeoClient, RetryPolicy
    except ImportError as exc:
        raise RuntimeError("未安装 dji-geo，未查询大疆 FlySafe") from exc

    west, south, east, north = bbox

    async def _run() -> dict:
        async with DjiGeoClient(
            default_drone=drone,
            timeout_s=12.0,
            retry=RetryPolicy(max_retries=1, base_delay_s=0.2, max_delay_s=0.5, jitter=False),
        ) as client:
            result = await client.query_rectangle(
                BBox(west=west, south=south, east=east, north=north),
                drone=drone,
            )
            return result.to_geojson(circle_segments=32)

    return asyncio.run(_run())


def refresh_planning_snapshot(
    origin: list[float] | tuple[float, float],
    destination: list[float] | tuple[float, float],
    *,
    zone_buffer_m: float = 0.0,
    scheduled_for: str | None = None,
    prior: ConstraintSnapshot | None = None,
    drone: str | None = None,
    fetcher=None,
) -> ConstraintSnapshot | None:
    """Query the planning bbox and return a snapshot, or None when live query is off.

    ``None`` means this process did not attempt a query (tests / Playwright).
    A failed or empty query is ``unavailable`` with no new geometry. If ``prior``
    is already a manufacturer snapshot that contains FlySafe zones, those zones
    are kept and ``failure_reason`` records that this refresh failed.
    """

    def emit(snapshot: ConstraintSnapshot, *, with_supplements: bool = False) -> ConstraintSnapshot:
        if snapshot.source_status == "unavailable" and with_supplements:
            snapshot = _with_supplements(
                snapshot,
                prior_supplements(prior),
                scheduled_for=scheduled_for,
            )
        if snapshot.source_status != "unavailable":
            return snapshot
        return retain_prior_flysafe(snapshot, prior, scheduled_for=scheduled_for)

    if fetcher is None and not flysafe_live_enabled():
        return None
    try:
        drone_slug = clean_drone_slug(drone)
        bbox = planning_bbox(origin, destination)
    except ValueError as exc:
        return emit(_unavailable(str(exc), zone_buffer_m=zone_buffer_m, scheduled_for=scheduled_for))
    fetch = fetcher or live_fetch_feature_collection
    try:
        collection = fetch(bbox, drone=drone_slug)
    except Exception as exc:
        return emit(
            _unavailable(
                f"大疆 FlySafe 查询失败：{type(exc).__name__}: {str(exc)[:180]}。未编造围栏",
                zone_buffer_m=zone_buffer_m,
                scheduled_for=scheduled_for,
            )
        )
    if not isinstance(collection, dict):
        return emit(
            _unavailable(
                "大疆 FlySafe 查询结果为空，未编造围栏",
                zone_buffer_m=zone_buffer_m,
                scheduled_for=scheduled_for,
            )
        )
    snapshot = snapshot_from_flysafe_collection(
        collection,
        drone=drone_slug,
        zone_buffer_m=zone_buffer_m,
        scheduled_for=scheduled_for,
        prior=prior,
    )
    return emit(snapshot, with_supplements=True)
