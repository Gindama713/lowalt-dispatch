"""Server-persisted WGS84 airspace constraint snapshots and continuous polyline checks.

This module binds manual planning, AI intake background routing, intake
recalculation, navigation candidates, assistant Q&A, and JSON exports to a
single auditable ``ConstraintSnapshot`` contract.

Hard boundaries:
- Only explicitly declared WGS84 / EPSG:4326 geometries are accepted; ENU demo
  zones, GCJ-02, BD-09, or ambiguous coordinate systems are rejected rather than
  guessed or silently mixed.
- Phase-1 avoidance uses conservative 2D full-height exclusion for non-expired
  ``restricted`` and ``internal`` zones; boundary contact counts as conflict.
- Passing checks against user-imported or simulated snapshots only means
  "passed against this known snapshot", never official UOM/NOTAM clearance or
  flight approval.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Literal

import shapely
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, shape

from planner.georef import distance_m, enu_to_wgs84, wgs84_to_enu

ROOT = Path(__file__).resolve().parents[2]

AirspaceKind = Literal[
    "suitable",
    "internal",
    "restricted",
    "altitude",
    "authorization",
    "enhanced_warning",
    "warning",
]
SourceKind = Literal["official", "manufacturer", "team"]
AltitudeRef = Literal["agl", "amsl", "rel_takeoff"]
SnapshotSourceStatus = Literal[
    "not_loaded",
    "known_empty",
    "user_imported",
    "simulation_preset",
    "query_failed",
    "manufacturer_reference",
    "unavailable",
]
AirspaceCheckStatus = Literal[
    "passed_known_snapshot",
    "conflict",
    "known_empty_snapshot",
    "no_enforced_zones_in_snapshot",
    "snapshot_not_loaded",
    "query_failed",
    "unavailable",
    "not_checked_legacy",
]

AVOIDANCE_KINDS: frozenset[str] = frozenset({"restricted", "internal"})
BUFFER_SOURCE_NOTE = "项目保守几何参数（非民航法定安全间隔）"
BOUNDARY_RULE_ID = "closed_touch_is_conflict"
BOUNDARY_RULE_NOTE = "闭区间判定：多边形内部穿越、缓冲带侵入及边界擦边接触（距离 = 缓冲值）均判为冲突。"
CONSERVATIVE_2D_NOTE = (
    "第一阶段采用二维全高度保守避让：时效或高度信息不完整、尚未到达生效时刻或标有高度上限时，"
    "均不允许越顶、穿越或等待后通过。"
)
STANDARD_AIRSPACE_GAPS: tuple[str, ...] = (
    "未接入官方 UOM / NOTAM 实时管制与临时空域通告接口",
    "第一阶段按二维全高度保守避让，未做三维高度层放行核验",
    "导入或演练多边形仅代表本次已知边界，不构成现实无禁飞区证明或飞行批准",
)
FLYSAFE_REFERENCE_GAP = (
    "本次区域来自大疆 FlySafe 厂商地理围栏参考，不是法定空域、"
    "不是官方 UOM / 国家地图官网 / 天地图数据，也不构成飞行批准"
)


def _parse_aware_iso(value: str, field_name: str = "时刻") -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name}必须包含时区偏移")
    return parsed


def validate_wgs84_declaration(
    crs_value: str | None, *, raw_crs_object: object = None
) -> Literal["EPSG:4326"]:
    """Reject ENU, GCJ-02, BD-09, missing, or ambiguous CRS declarations."""
    if raw_crs_object is not None:
        raise ValueError("拒绝含糊的 GeoJSON crs 字段；请明确声明 coordinate_system: WGS84（EPSG:4326）")
    if crs_value is None or not str(crs_value).strip():
        raise ValueError("缺少坐标系声明：必须明确为 WGS84 / EPSG:4326，拒绝猜测坐标基准")
    normalized = str(crs_value).strip().upper()
    if normalized in {"WGS84", "EPSG:4326"}:
        return "EPSG:4326"
    if "ENU" in normalized or "LOCAL" in normalized:
        raise ValueError("拒绝混用坐标系：不能将本地 ENU 仿真区域直接当成真实 WGS84 地点的禁飞区")
    if "GCJ" in normalized or "BD09" in normalized or "BD-09" in normalized:
        raise ValueError(f"拒绝未校准坐标系 {crs_value}：仅接受 WGS84 / EPSG:4326，未做偏置猜测转换")
    raise ValueError(f"不支持的坐标系 {crs_value}：仅接受 WGS84 / EPSG:4326")


def validate_polygon_geojson(geometry: dict) -> dict:
    """Validate Polygon / MultiPolygon structure, WGS84 bounds, closure, and topology."""
    if not isinstance(geometry, dict):
        raise ValueError("区域几何必须为 GeoJSON 对象")
    gtype = geometry.get("type")
    if gtype not in {"Polygon", "MultiPolygon"}:
        raise ValueError("区域几何仅支持 Polygon 或 MultiPolygon")
    coords = geometry.get("coordinates")
    polygons = [coords] if gtype == "Polygon" else coords
    if (
        not isinstance(polygons, list)
        or not polygons
        or len(polygons) > 100
        or any(not isinstance(poly, list) or not poly or len(poly) > 30 for poly in polygons)
    ):
        raise ValueError("区域多边形轮廓集合为空或结构无效")
    total_vertices = 0
    cleaned_polygons: list[list[list[list[float]]]] = []
    for poly in polygons:
        cleaned_rings: list[list[list[float]]] = []
        for ring in poly:
            if not isinstance(ring, list) or len(ring) < 4 or len(ring) > 2000:
                raise ValueError("区域多边形环必须闭合且包含 4–2000 个顶点")
            total_vertices += len(ring)
            if total_vertices > 20_000:
                raise ValueError("区域总顶点数不能超过 20000")
            cleaned_ring: list[list[float]] = []
            for idx, pt in enumerate(ring):
                if (
                    not isinstance(pt, (list, tuple))
                    or len(pt) != 2
                    or any(
                        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                        for v in pt
                    )
                ):
                    raise ValueError("区域坐标必须为二维有限数值 [lng, lat]，不含高度值")
                lng, lat = float(pt[0]), float(pt[1])
                if not (-180.0 <= lng <= 180.0 and -85.0511 <= lat <= 85.0511):
                    raise ValueError(
                        f"区域坐标 [{lng}, {lat}] 超出 WGS84 经纬度范围（疑似混入 ENU 米制坐标），已拒绝"
                    )
                if idx > 0 and abs(lng - cleaned_ring[-1][0]) > 180.0:
                    raise ValueError("跨 180° 经线的区域请拆分后再导入")
                cleaned_ring.append([round(lng, 7), round(lat, 7)])
            if cleaned_ring[0] != cleaned_ring[-1]:
                raise ValueError("区域多边形环首尾顶点必须严格闭合")
            cleaned_rings.append(cleaned_ring)
        cleaned_polygons.append(cleaned_rings)

    normalized = {
        "type": gtype,
        "coordinates": cleaned_polygons[0] if gtype == "Polygon" else cleaned_polygons,
    }
    geom = shape(normalized)
    if geom.is_empty or not geom.is_valid or geom.area <= 1e-14:
        raise ValueError("区域多边形拓扑无效（存在自相交或面积为零）")
    return normalized


class ConstraintZone(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=200)
    kind: AirspaceKind
    geometry: dict
    source: str = Field(min_length=1, max_length=300)
    source_ref: str = Field(default="", max_length=1000)
    source_kind: SourceKind = "team"
    is_simulated: bool = True
    fetched_at: str
    updated_at: str
    effective_from: str | None = None
    effective_until: str | None = None
    altitude_ref: AltitudeRef | None = None
    max_height_m: float | None = Field(default=None, ge=-500, le=10000)
    description: str = Field(default="", max_length=1500)
    participates_in_avoidance: bool = False
    buffer_m: float = Field(default=0.0, ge=0.0, le=500.0)
    avoidance_rule: str = ""

    @field_validator("fetched_at", "updated_at")
    @classmethod
    def check_required_timestamps(cls, value: str) -> str:
        _parse_aware_iso(value, "区域获取/更新时间")
        return value

    @model_validator(mode="after")
    def check_geometry_and_window(self):
        self.geometry = validate_polygon_geojson(self.geometry)
        if self.max_height_m is not None and self.altitude_ref is None:
            raise ValueError("提供高度上限 max_height_m 时必须同时声明 altitude_ref")
        start_dt = _parse_aware_iso(self.effective_from, "effective_from") if self.effective_from else None
        end_dt = _parse_aware_iso(self.effective_until, "effective_until") if self.effective_until else None
        if start_dt and end_dt and end_dt <= start_dt:
            raise ValueError("区域失效时间必须晚于生效时间")
        return self


def evaluate_zone_for_schedule(
    zone: ConstraintZone,
    *,
    scheduled_for: str | None = None,
    zone_buffer_m: float = 0.0,
) -> ConstraintZone:
    """Apply phase-1 conservative 2D avoidance participation rules for a mission instant."""
    departure = _parse_aware_iso(scheduled_for, "起飞时刻") if scheduled_for else None
    if zone.kind not in AVOIDANCE_KINDS:
        return zone.model_copy(
            update={
                "participates_in_avoidance": False,
                "buffer_m": 0.0,
                "avoidance_rule": f"类别为 {zone.kind}（提示/参考图层），仅地图展示，不纳入禁飞硬避让。",
            }
        )
    if departure is not None and zone.effective_until is not None:
        until_dt = _parse_aware_iso(zone.effective_until, "effective_until")
        if until_dt <= departure:
            return zone.model_copy(
                update={
                    "participates_in_avoidance": False,
                    "buffer_m": 0.0,
                    "avoidance_rule": (
                        f"区域失效时刻（{zone.effective_until}）早于或等于起飞时刻（{scheduled_for}），本次不纳入避让。"
                    ),
                }
            )

    notes = ["二维全高度保守避让，禁止穿越、边界接触、越顶或等待后通过"]
    if zone.effective_from is None or zone.effective_until is None or departure is None:
        notes.append("时效或起飞时刻不完整，按全时段生效保守处理")
    else:
        from_dt = _parse_aware_iso(zone.effective_from, "effective_from")
        if from_dt > departure:
            notes.append("虽尚未到达所填生效时刻，仍按保守策略纳入避让")
    if zone.max_height_m is not None:
        notes.append(f"标注高度上限 {zone.max_height_m:g} m（{zone.altitude_ref}），不做越顶放行")
    notes.append(f"项目边界缓冲 {zone_buffer_m:g} m（{BUFFER_SOURCE_NOTE}）")
    return zone.model_copy(
        update={
            "participates_in_avoidance": True,
            "buffer_m": float(zone_buffer_m),
            "avoidance_rule": "；".join(notes) + "。",
        }
    )


def _compute_snapshot_identity(
    source_status: SnapshotSourceStatus,
    crs: str,
    zone_buffer_m: float,
    zones: Sequence[ConstraintZone],
    failure_reason: str = "",
) -> tuple[str, str, str]:
    canonical = {
        "crs": crs,
        "source_status": source_status,
        "zone_buffer_m": round(float(zone_buffer_m), 3),
        "boundary_rule": BOUNDARY_RULE_ID,
        "failure_reason": failure_reason if source_status == "query_failed" else "",
        "zones": [
            {
                "id": z.id,
                "name": z.name,
                "kind": z.kind,
                "geometry": z.geometry,
                "source": z.source,
                "source_ref": z.source_ref,
                "source_kind": z.source_kind,
                "is_simulated": z.is_simulated,
                "effective_from": z.effective_from,
                "effective_until": z.effective_until,
                "altitude_ref": z.altitude_ref,
                "max_height_m": z.max_height_m,
            }
            for z in zones
        ],
    }
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    hex_digest = hashlib.sha256(raw).hexdigest()
    return f"air-{hex_digest[:12]}", f"v1-{hex_digest[:8]}", f"sha256:{hex_digest}"


class ConstraintSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    snapshot_id: str = Field(min_length=4, max_length=64)
    version: str = Field(min_length=2, max_length=64)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    crs: Literal["EPSG:4326"] = "EPSG:4326"
    coordinate_system: Literal["WGS84"] = "WGS84"
    source_status: SnapshotSourceStatus
    is_simulated: bool = True
    fetched_at: str
    zone_buffer_m: float = Field(default=0.0, ge=0.0, le=500.0)
    buffer_source: str = BUFFER_SOURCE_NOTE
    boundary_rule: str = BOUNDARY_RULE_ID
    boundary_rule_note: str = BOUNDARY_RULE_NOTE
    conservative_rule: str = CONSERVATIVE_2D_NOTE
    failure_reason: str = ""
    total_zone_count: int = Field(ge=0)
    enforced_zone_count: int = Field(ge=0)
    enforced_zone_ids: list[str] = Field(default_factory=list)
    zones: list[ConstraintZone] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def check_unique_ids(self):
        seen: set[str] = set()
        for zone in self.zones:
            if zone.id in seen:
                raise ValueError(f"约束快照中存在重复的区域 ID：{zone.id}")
            seen.add(zone.id)
        return self

    @classmethod
    def build(
        cls,
        *,
        zones: Sequence[ConstraintZone],
        source_status: SnapshotSourceStatus,
        zone_buffer_m: float = 0.0,
        scheduled_for: str | None = None,
        fetched_at: str | None = None,
        failure_reason: str = "",
    ) -> ConstraintSnapshot:
        stamp = fetched_at or datetime.now(UTC).isoformat()
        evaluated = [
            evaluate_zone_for_schedule(z, scheduled_for=scheduled_for, zone_buffer_m=zone_buffer_m)
            for z in zones
        ]
        enforced_ids = [z.id for z in evaluated if z.participates_in_avoidance]
        snapshot_id, version, digest = _compute_snapshot_identity(
            source_status, "EPSG:4326", zone_buffer_m, evaluated, failure_reason
        )
        is_sim = True if not evaluated else any(z.is_simulated for z in evaluated)
        return cls(
            snapshot_id=snapshot_id,
            version=version,
            digest=digest,
            crs="EPSG:4326",
            coordinate_system="WGS84",
            source_status=source_status,
            is_simulated=is_sim,
            fetched_at=stamp,
            zone_buffer_m=float(zone_buffer_m),
            failure_reason=failure_reason,
            total_zone_count=len(evaluated),
            enforced_zone_count=len(enforced_ids),
            enforced_zone_ids=enforced_ids,
            zones=evaluated,
        )

    def for_schedule(self, scheduled_for: str | None) -> ConstraintSnapshot:
        """Re-evaluate time-dependent participation for a specific departure time."""
        return ConstraintSnapshot.build(
            zones=self.zones,
            source_status=self.source_status,
            zone_buffer_m=self.zone_buffer_m,
            scheduled_for=scheduled_for,
            fetched_at=self.fetched_at,
            failure_reason=self.failure_reason,
        )

    def to_exclusions_fc(self, *, scheduled_for: str | None = None) -> dict:
        bound = self.for_schedule(scheduled_for) if scheduled_for is not None else self
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "id": z.id,
                        "name": z.name,
                        "kind": z.kind,
                        "buffer_m": z.buffer_m,
                    },
                    "geometry": z.geometry,
                }
                for z in bound.zones
                if z.participates_in_avoidance
            ],
        }

    def summary_dict(self) -> dict:
        sources = sorted({z.source for z in self.zones})
        return {
            "snapshot_id": self.snapshot_id,
            "version": self.version,
            "digest": self.digest,
            "crs": self.crs,
            "coordinate_system": self.coordinate_system,
            "source_status": self.source_status,
            "is_simulated": self.is_simulated,
            "fetched_at": self.fetched_at,
            "zone_buffer_m": self.zone_buffer_m,
            "buffer_source": self.buffer_source,
            "boundary_rule": self.boundary_rule,
            "total_zone_count": self.total_zone_count,
            "enforced_zone_count": self.enforced_zone_count,
            "enforced_zone_ids": list(self.enforced_zone_ids),
            "sources": sources,
        }


def snapshot_from_geojson(
    payload: dict,
    *,
    zone_buffer_m: float = 0.0,
    scheduled_for: str | None = None,
    source_status: SnapshotSourceStatus | None = None,
) -> ConstraintSnapshot:
    """Parse a user-imported or preset WGS84 GeoJSON FeatureCollection into a ConstraintSnapshot."""
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError("空域快照必须为 GeoJSON FeatureCollection")
    validate_wgs84_declaration(
        payload.get("coordinate_system"),
        raw_crs_object=payload.get("crs"),
    )
    features = payload.get("features")
    if not isinstance(features, list) or len(features) > 100:
        raise ValueError("空域 FeatureCollection 须包含 0–100 个区域要素")
    now_iso = datetime.now(UTC).isoformat()
    zones: list[ConstraintZone] = []
    for idx, feat in enumerate(features):
        if not isinstance(feat, dict) or feat.get("type") != "Feature":
            raise ValueError(f"第 {idx + 1} 个区域不是合法的 GeoJSON Feature")
        props = feat.get("properties")
        geom = feat.get("geometry")
        if not isinstance(props, dict) or not isinstance(geom, dict):
            raise ValueError(f"第 {idx + 1} 个区域缺少 properties 或 geometry")
        if props.get("crs") is not None:
            validate_wgs84_declaration(str(props.get("crs")))
        updated_at = props.get("updated_at")
        fetched_at = props.get("fetched_at") or updated_at or now_iso
        if not isinstance(updated_at, str) or not updated_at.strip():
            raise ValueError(f"区域 {props.get('id', idx)} 缺少带时区的 updated_at")
        if not isinstance(props.get("is_simulated"), bool):
            raise ValueError(f"区域 {props.get('id', idx)} 必须显式声明布尔型 is_simulated")
        zones.append(
            ConstraintZone(
                id=str(props.get("id") or "").strip(),
                name=str(props.get("name") or "").strip(),
                kind=props.get("kind"),
                geometry=geom,
                source=str(props.get("source") or "").strip(),
                source_ref=str(props.get("source_ref") or "").strip(),
                source_kind=props.get("source_kind", "team"),
                is_simulated=props["is_simulated"],
                fetched_at=str(fetched_at),
                updated_at=updated_at.strip(),
                effective_from=props.get("effective_from"),
                effective_until=props.get("effective_until"),
                altitude_ref=props.get("altitude_ref"),
                max_height_m=props.get("max_height_m"),
                description=str(props.get("description") or "").strip(),
            )
        )
    if not zones:
        resolved_status: SnapshotSourceStatus = source_status or "known_empty"
    elif source_status is not None:
        resolved_status = source_status
    elif all(z.is_simulated for z in zones) and all(
        str(z.source_ref).startswith("simulation:") for z in zones
    ):
        resolved_status = "simulation_preset"
    else:
        resolved_status = "user_imported"
    return ConstraintSnapshot.build(
        zones=zones,
        source_status=resolved_status,
        zone_buffer_m=zone_buffer_m,
        scheduled_for=scheduled_for,
        fetched_at=now_iso,
    )


def snapshot_from_avoid_regions(
    avoid_regions: Sequence[dict],
    *,
    zone_buffer_m: float = 0.0,
    scheduled_for: str | None = None,
    source_status: SnapshotSourceStatus | None = None,
) -> ConstraintSnapshot:
    """Canonicalize legacy ``CandidateInput.avoid_regions`` into a ConstraintSnapshot."""
    now_iso = datetime.now(UTC).isoformat()
    if not avoid_regions:
        return ConstraintSnapshot.build(
            zones=[],
            source_status=source_status or "not_loaded",
            zone_buffer_m=zone_buffer_m,
            scheduled_for=scheduled_for,
            fetched_at=now_iso,
        )
    zones: list[ConstraintZone] = []
    for item in avoid_regions:
        data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        stamp = data.get("updated_at") or data.get("fetched_at") or "2026-01-01T00:00:00+00:00"
        zones.append(
            ConstraintZone(
                id=data["id"],
                name=data.get("name") or data["id"],
                kind=data["kind"],
                geometry=data["geometry"],
                source=data["source"],
                source_ref=data.get("source_ref") or "avoid_regions",
                source_kind=data.get("source_kind") or "team",
                is_simulated=bool(data.get("is_simulated", True)),
                fetched_at=data.get("fetched_at") or stamp,
                updated_at=stamp,
                effective_from=data.get("effective_from"),
                effective_until=data.get("effective_until"),
                altitude_ref=data.get("altitude_ref"),
                max_height_m=data.get("max_height_m"),
                description=data.get("description") or "",
            )
        )
    return ConstraintSnapshot.build(
        zones=zones,
        source_status=source_status or "user_imported",
        zone_buffer_m=zone_buffer_m,
        scheduled_for=scheduled_for,
        fetched_at=now_iso,
    )


def _extract_lonlat_pairs(waypoints: Sequence[object]) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for pt in waypoints:
        if isinstance(pt, dict):
            lng = pt.get("lng", pt.get("x"))
            lat = pt.get("lat", pt.get("y"))
        elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
            lng, lat = pt[0], pt[1]
        else:
            raise ValueError("航点格式无效，无法执行空域几何复核")
        if lng is None or lat is None:
            raise ValueError("航点缺少经纬度数值")
        lng_f, lat_f = float(lng), float(lat)
        if not (-180.0 <= lng_f <= 180.0 and -85.0511 <= lat_f <= 85.0511):
            raise ValueError("航点坐标超出 WGS84 范围，拒绝与 WGS84 约束快照混用")
        pairs.append((lng_f, lat_f))
    return pairs


def _project_zone_enu(geometry: dict, reference: tuple[float, float]) -> Polygon | MultiPolygon:
    gtype = geometry["type"]
    polygons = [geometry["coordinates"]] if gtype == "Polygon" else geometry["coordinates"]
    projected = []
    for rings in polygons:
        enu_rings = [[wgs84_to_enu(reference, (pt[0], pt[1])) for pt in ring] for ring in rings]
        projected.append(Polygon(enu_rings[0], enu_rings[1:]))
    return projected[0] if gtype == "Polygon" else MultiPolygon(projected)


def check_route_against_snapshot(
    waypoints: Sequence[object],
    snapshot: ConstraintSnapshot | dict | None,
    *,
    scheduled_for: str | None = None,
) -> dict:
    """Independently check every polyline segment and endpoint against a ConstraintSnapshot.

    Never conflates missing official data, query failure, unloaded snapshot, or
    known-empty snapshot into a generic 'airspace approved' verdict.
    """
    gaps = list(STANDARD_AIRSPACE_GAPS)
    if snapshot is None:
        return {
            "status": "not_checked_legacy",
            "passed_known_snapshot": None,
            "operationally_approved": False,
            "verdict_label": "历史建筑避障结果，空域未核对",
            "snapshot_id": None,
            "snapshot_version": None,
            "snapshot_digest": None,
            "crs": "EPSG:4326",
            "source_status": "not_loaded",
            "enforced_zone_count": 0,
            "total_zone_count": 0,
            "enforced_zone_ids": [],
            "zone_buffer_m": None,
            "buffer_source": BUFFER_SOURCE_NOTE,
            "boundary_rule": BOUNDARY_RULE_ID,
            "conflicts": [],
            "conflicting_zone_ids": [],
            "conflicting_segment_indices": [],
            "checked_segment_count": max(0, len(waypoints) - 1),
            "gaps": ["该路线缺少空域约束快照，仅包含历史建筑避障结果，须重新计算并核对", *gaps],
            "checked_at": datetime.now(UTC).isoformat(),
        }

    model = (
        snapshot if isinstance(snapshot, ConstraintSnapshot) else ConstraintSnapshot.model_validate(snapshot)
    )
    if scheduled_for is not None:
        model = model.for_schedule(scheduled_for)
    if model.source_status == "manufacturer_reference":
        gaps.insert(0, FLYSAFE_REFERENCE_GAP)
    elif model.source_status == "unavailable":
        gaps.insert(0, "大疆 FlySafe 查询不可用或结果为空：空域未知，不是放行，未编造围栏")

    points = _extract_lonlat_pairs(waypoints) if waypoints else []
    base = {
        "operationally_approved": False,
        "snapshot_id": model.snapshot_id,
        "snapshot_version": model.version,
        "snapshot_digest": model.digest,
        "crs": model.crs,
        "source_status": model.source_status,
        "is_simulated_snapshot": model.is_simulated,
        "enforced_zone_count": model.enforced_zone_count,
        "total_zone_count": model.total_zone_count,
        "enforced_zone_ids": list(model.enforced_zone_ids),
        "zone_buffer_m": model.zone_buffer_m,
        "buffer_source": model.buffer_source,
        "boundary_rule": model.boundary_rule,
        "conflicts": [],
        "conflicting_zone_ids": [],
        "conflicting_segment_indices": [],
        "checked_segment_count": max(0, len(points) - 1),
        "checked_at": datetime.now(UTC).isoformat(),
    }

    if model.source_status == "query_failed":
        return base | {
            "status": "query_failed",
            "passed_known_snapshot": None,
            "verdict_label": "空域约束读取失败（空域未核对，非通过）",
            "gaps": [f"空域约束源读取失败：{model.failure_reason or '原因未知'}", *gaps],
        }
    if model.source_status == "unavailable":
        return base | {
            "status": "unavailable",
            "passed_known_snapshot": None,
            "verdict_label": "大疆 FlySafe 厂商地理围栏不可用或为空（空域未知，不是放行）",
            "gaps": [f"大疆 FlySafe：{model.failure_reason or '原因未知'}", *gaps],
        }
    if model.source_status == "not_loaded":
        return base | {
            "status": "snapshot_not_loaded",
            "passed_known_snapshot": None,
            "verdict_label": "未导入空域区域（空域未核对，非通过）",
            "gaps": ["当前未载入任何用户导入或演练限制区快照，仅完成建筑几何避障", *gaps],
        }
    if model.source_status == "known_empty":
        return base | {
            "status": "known_empty_snapshot",
            "passed_known_snapshot": True,
            "verdict_label": "本次已知快照显式为空（0 个已知限制区；未接官方空域，不等同获准飞行）",
            "gaps": ["本次绑定的已知空域快照包含 0 个区域，现实禁限飞仍需人工核查官方 UOM / NOTAM", *gaps],
        }

    enforced_zones = [z for z in model.zones if z.participates_in_avoidance]
    if not enforced_zones:
        no_enforced_label = "快照中无生效禁飞/内部管制区（仅含提示类或已过有效期区域；非官方放行）"
        if model.source_status == "manufacturer_reference":
            no_enforced_label = (
                "通过本次已知区域检查（大疆 FlySafe 厂商地理围栏参考中无生效禁飞区；"
                "非法定空域，不代表获准飞行）"
            )
        return base | {
            "status": "no_enforced_zones_in_snapshot",
            "passed_known_snapshot": True,
            "verdict_label": no_enforced_label,
            "gaps": [
                f"已载入 {model.total_zone_count} 个区域，但当前时段无参与硬避让的禁飞区/内部管制区",
                *gaps,
            ],
        }

    if len(points) < 2:
        return base | {
            "status": "passed_known_snapshot",
            "passed_known_snapshot": False,
            "verdict_label": "尚未生成有效几何航线，无法完成逐航段空域复核",
            "gaps": ["未生成 >=2 航点的几何路线", *gaps],
        }

    reference = ((points[0][0] + points[-1][0]) / 2.0, (points[0][1] + points[-1][1]) / 2.0)
    pts_enu = [wgs84_to_enu(reference, p) for p in points]
    projected_zones = [(z, _project_zone_enu(z.geometry, reference)) for z in enforced_zones]

    conflicts: list[dict] = []
    for seg_idx, (a_enu, b_enu) in enumerate(pairwise(pts_enu)):
        seg = LineString([a_enu, b_enu]) if a_enu != b_enu else Point(a_enu)
        a_wgs, b_wgs = points[seg_idx], points[seg_idx + 1]
        for zone, poly in projected_zones:
            buf = float(zone.buffer_m)
            hit = poly.intersects(seg) if buf <= 0.0 else bool(shapely.dwithin(seg, poly, buf))
            if not hit:
                continue
            dist = float(poly.distance(seg))
            start_hit = (
                poly.intersects(Point(a_enu))
                if buf <= 0.0
                else bool(shapely.dwithin(Point(a_enu), poly, buf))
            )
            end_hit = (
                poly.intersects(Point(b_enu))
                if buf <= 0.0
                else bool(shapely.dwithin(Point(b_enu), poly, buf))
            )
            if seg_idx == 0 and start_hit:
                ctype = "origin_inside"
                reason = f"起点位于限制区「{zone.name}」（{zone.id}）或其缓冲范围内"
            elif seg_idx == len(pts_enu) - 2 and end_hit:
                ctype = "destination_inside"
                reason = f"终点位于限制区「{zone.name}」（{zone.id}）或其缓冲范围内"
            elif isinstance(seg, LineString) and poly.touches(seg):
                ctype = "boundary_contact"
                reason = f"第 {seg_idx + 1} 航段与限制区「{zone.name}」（{zone.id}）边界擦边接触（闭区间规则判冲突）"
            elif dist <= 1e-7:
                ctype = "segment_crosses"
                reason = f"第 {seg_idx + 1} 航段穿越限制区「{zone.name}」（{zone.id}）"
            else:
                ctype = "buffer_intrusion"
                reason = (
                    f"第 {seg_idx + 1} 航段距限制区「{zone.name}」（{zone.id}）仅 {dist:.1f} m，"
                    f"小于或等于项目缓冲 {buf:g} m"
                )
            conflicts.append(
                {
                    "zone_id": zone.id,
                    "zone_name": zone.name,
                    "zone_kind": zone.kind,
                    "is_simulated": zone.is_simulated,
                    "segment_index": seg_idx,
                    "segment_number": seg_idx + 1,
                    "segment_start": [round(a_wgs[0], 6), round(a_wgs[1], 6)],
                    "segment_end": [round(b_wgs[0], 6), round(b_wgs[1], 6)],
                    "conflict_type": ctype,
                    "distance_m": round(dist, 2),
                    "buffer_m": buf,
                    "reason": reason,
                }
            )

    conflict_zone_ids = sorted({item["zone_id"] for item in conflicts})
    conflict_segments = sorted({item["segment_index"] for item in conflicts})
    if conflicts:
        return base | {
            "status": "conflict",
            "passed_known_snapshot": False,
            "verdict_label": (
                f"与本次已知限制区冲突（涉及 {len(conflict_zone_ids)} 个区域、"
                f"{len(conflict_segments)} 个冲突航段）"
            ),
            "conflicts": conflicts,
            "conflicting_zone_ids": conflict_zone_ids,
            "conflicting_segment_indices": conflict_segments,
            "gaps": gaps,
        }

    if model.source_status == "manufacturer_reference":
        sim_tag = "（大疆 FlySafe 厂商地理围栏参考"
        if model.is_simulated:
            sim_tag += "，并含演练附加区"
        sim_tag += "；非法定空域，不代表获准飞行）"
    elif model.is_simulated:
        sim_tag = "（含演练区域）"
    else:
        sim_tag = "（用户导入区域）"
    return base | {
        "status": "passed_known_snapshot",
        "passed_known_snapshot": True,
        "verdict_label": f"通过本次已知区域检查{sim_tag}（非官方空域许可，不代表获准飞行）",
        "gaps": gaps,
    }


def build_corridor_simulation_zone(
    origin: Sequence[float],
    destination: Sequence[float],
    waypoints: Sequence[object] | None = None,
    *,
    existing_zones: Sequence[ConstraintZone] | None = None,
) -> ConstraintZone:
    """Create a deterministic, explicitly labeled simulated restricted polygon across a route's midpoint.

    Guarantees:
    - Positioned on the middle arc-length point of ``waypoints`` (or straight line
      if ``waypoints`` is empty) so the original route deterministically crosses it.
    - Clamped well away from ``origin`` and ``destination`` so endpoints stay valid.
    - Sized within the 1000 m local search corridor so ``plan_real_route`` can
      genuinely detour around it when an unobstructed corridor exists.
    """
    start = (float(origin[0]), float(origin[1]))
    goal = (float(destination[0]), float(destination[1]))
    total_direct = distance_m(start, goal)
    if total_direct < 40.0:
        raise ValueError("起终点距离过近（< 40 m），无法在保持端点净空的前提下构造中段演练禁飞区")

    pts = _extract_lonlat_pairs(waypoints) if waypoints and len(waypoints) >= 2 else [start, goal]
    reference = ((start[0] + goal[0]) / 2.0, (start[1] + goal[1]) / 2.0)
    pts_enu = [wgs84_to_enu(reference, p) for p in pts]
    start_enu, goal_enu = pts_enu[0], pts_enu[-1]

    seg_lengths = [math.dist(a, b) for a, b in pairwise(pts_enu)]
    route_total = sum(seg_lengths)
    target = route_total * 0.5
    mid_enu = ((start_enu[0] + goal_enu[0]) / 2.0, (start_enu[1] + goal_enu[1]) / 2.0)
    tx, ty = goal_enu[0] - start_enu[0], goal_enu[1] - start_enu[1]
    norm = math.hypot(tx, ty) or 1.0
    tx, ty = tx / norm, ty / norm
    acc = 0.0
    for (a, b), seg_len in zip(pairwise(pts_enu), seg_lengths, strict=True):
        if seg_len <= 1e-6:
            continue
        if acc + seg_len >= target:
            ratio = (target - acc) / seg_len
            mid_enu = (a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio)
            tx, ty = (b[0] - a[0]) / seg_len, (b[1] - a[1]) / seg_len
            break
        acc += seg_len

    nx, ny = -ty, tx
    min_end_dist = min(math.dist(mid_enu, start_enu), math.dist(mid_enu, goal_enu))
    half_along = min(130.0, max(28.0, total_direct * 0.07), max(15.0, min_end_dist * 0.42))
    half_across = min(210.0, max(65.0, total_direct * 0.13), max(25.0, min_end_dist * 0.65))

    corners_enu = [
        (mid_enu[0] - tx * half_along - nx * half_across, mid_enu[1] - ty * half_along - ny * half_across),
        (mid_enu[0] + tx * half_along - nx * half_across, mid_enu[1] + ty * half_along - ny * half_across),
        (mid_enu[0] + tx * half_along + nx * half_across, mid_enu[1] + ty * half_along + ny * half_across),
        (mid_enu[0] - tx * half_along + nx * half_across, mid_enu[1] - ty * half_along + ny * half_across),
    ]
    ring_wgs = [
        [round(lng, 6), round(lat, 6)] for lng, lat in (enu_to_wgs84(reference, c) for c in corners_enu)
    ]
    ring_wgs.append(list(ring_wgs[0]))

    existing_ids = {z.id for z in (existing_zones or [])}
    idx = 1
    while f"sim-corridor-nfz-{idx}" in existing_ids:
        idx += 1
    stamp = datetime.now(UTC).isoformat()
    return ConstraintZone(
        id=f"sim-corridor-nfz-{idx}",
        name=f"走廊中段演练禁飞区 #{idx}（仿真）",
        kind="restricted",
        geometry={"type": "Polygon", "coordinates": [ring_wgs]},
        source="AERIS 本地走廊演练生成器（非官方空域）",
        source_ref="simulation:corridor-midpoint-v1",
        source_kind="team",
        is_simulated=True,
        fetched_at=stamp,
        updated_at=stamp,
        effective_from=None,
        effective_until=None,
        altitude_ref=None,
        max_height_m=None,
        description="基于当前任务航线中点自动生成的确定性演练禁飞区，用于验证冲突检出与重算绕行；非真实管制数据。",
    )


class AirspaceSnapshotStore:
    """Thread-safe JSON store for immutable ConstraintSnapshots + active workspace pointer."""

    def __init__(self, root: Path | None = None):
        self.root = root or Path(os.getenv("AERIS_AIRSPACE_DIR", str(ROOT / "logs/airspace_snapshots")))
        self._lock = threading.RLock()

    def _snapshot_path(self, snapshot_id: str) -> Path:
        if (
            not snapshot_id
            or "/" in snapshot_id
            or "\\" in snapshot_id
            or ".." in snapshot_id
            or not snapshot_id.startswith("air-")
        ):
            raise KeyError(snapshot_id)
        return self.root / f"{snapshot_id}.json"

    def _active_path(self) -> Path:
        return self.root / "_active.json"

    def save(self, snapshot: ConstraintSnapshot, *, set_active: bool = True) -> ConstraintSnapshot:
        payload = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2)
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self._snapshot_path(snapshot.snapshot_id)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
            if set_active:
                active_tmp = self._active_path().with_suffix(".json.tmp")
                active_tmp.write_text(
                    json.dumps(
                        {
                            "snapshot_id": snapshot.snapshot_id,
                            "updated_at": datetime.now(UTC).isoformat(),
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                active_tmp.replace(self._active_path())
        return snapshot

    def clear_active(self, *, zone_buffer_m: float = 0.0) -> ConstraintSnapshot:
        unloaded = ConstraintSnapshot.build(
            zones=[],
            source_status="not_loaded",
            zone_buffer_m=zone_buffer_m,
        )
        with self._lock:
            self.save(unloaded, set_active=False)
            if self._active_path().exists():
                self._active_path().unlink()
        return unloaded

    def get(self, snapshot_id: str) -> ConstraintSnapshot:
        path = self._snapshot_path(snapshot_id)
        with self._lock:
            if not path.exists():
                raise KeyError(snapshot_id)
            return ConstraintSnapshot.model_validate_json(path.read_text(encoding="utf-8"))

    def get_active(self) -> ConstraintSnapshot | None:
        with self._lock:
            active = self._active_path()
            if not active.exists():
                return None
            try:
                pointer = json.loads(active.read_text(encoding="utf-8"))
                snapshot_id = pointer.get("snapshot_id")
                if not snapshot_id:
                    return None
                return self.get(snapshot_id)
            except (OSError, ValueError, KeyError):
                return None

    def get_active_or_unloaded(self, *, scheduled_for: str | None = None) -> ConstraintSnapshot:
        active = self.get_active()
        if active is not None:
            return active.for_schedule(scheduled_for) if scheduled_for is not None else active
        unloaded = ConstraintSnapshot.build(
            zones=[],
            source_status="not_loaded",
            zone_buffer_m=0.0,
            scheduled_for=scheduled_for,
        )
        return self.save(unloaded, set_active=False)

    def resolve(
        self,
        *,
        snapshot_id: str | None = None,
        avoid_regions: Sequence[object] | None = None,
        zone_buffer_m: float = 0.0,
        scheduled_for: str | None = None,
    ) -> ConstraintSnapshot:
        """Resolve task-bound snapshot by explicit ID, inline regions, or active workspace snapshot."""
        if snapshot_id:
            try:
                loaded = self.get(snapshot_id)
            except KeyError as exc:
                raise ValueError(f"指定的空域约束快照 {snapshot_id} 不存在，请刷新区域后重试") from exc
            if abs(loaded.zone_buffer_m - float(zone_buffer_m)) > 1e-6:
                loaded = ConstraintSnapshot.build(
                    zones=loaded.zones,
                    source_status=loaded.source_status,
                    zone_buffer_m=zone_buffer_m,
                    scheduled_for=scheduled_for,
                    fetched_at=loaded.fetched_at,
                    failure_reason=loaded.failure_reason,
                )
                return self.save(loaded, set_active=False)
            return loaded.for_schedule(scheduled_for) if scheduled_for is not None else loaded

        if avoid_regions:
            built = snapshot_from_avoid_regions(
                avoid_regions,
                zone_buffer_m=zone_buffer_m,
                scheduled_for=scheduled_for,
                source_status="user_imported",
            )
            return self.save(built, set_active=False)

        active = self.get_active()
        if active is not None:
            rebound = ConstraintSnapshot.build(
                zones=active.zones,
                source_status=active.source_status,
                zone_buffer_m=zone_buffer_m if zone_buffer_m else active.zone_buffer_m,
                scheduled_for=scheduled_for,
                fetched_at=active.fetched_at,
                failure_reason=active.failure_reason,
            )
            return self.save(rebound, set_active=False)

        unloaded = ConstraintSnapshot.build(
            zones=[],
            source_status="not_loaded",
            zone_buffer_m=zone_buffer_m,
            scheduled_for=scheduled_for,
        )
        return self.save(unloaded, set_active=False)


store = AirspaceSnapshotStore()
