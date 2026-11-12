"""读取 scenarios/v0 草稿几何，收成核心模型能表达的部分。

障碍物没有对应的 RiskEvent.kind，所以只出现在场景文档里，不塞进快照。
限制区在调用方点名之后才变成 RiskEvent。不点名就不算“起飞时已知”。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from core.models import (
    AltitudeReference,
    DataProvenance,
    Frame,
    LandingSite,
    Position,
    RiskEvent,
    RiskSnapshot,
)
from planner.scene import SCENARIO_DIR
from services.api.envelopes import SceneBindRequest, SceneBindResult, SceneDocument
from services.api.errors import ApiError

SCENE_ID = "v0"


def _read_collection(filename: str) -> dict[str, Any]:
    path = SCENARIO_DIR / filename
    if not path.is_file():
        raise ApiError(500, f"场景文件不存在：{path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _first_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "字段不合法"
    return str(errors[0].get("msg") or "字段不合法")


def _features(collection: dict[str, Any]) -> list[dict[str, Any]]:
    features = collection.get("features")
    if not isinstance(features, list):
        raise ApiError(500, "场景 GeoJSON 缺少 features")
    return features


def _provenance(props: dict[str, Any], captured_at: datetime, *, extra: str) -> DataProvenance:
    flagged = props.get("is_simulated")
    if flagged is None:
        simulated = True
        gap = "文件未写 is_simulated，按仿真处理。"
    else:
        simulated = bool(flagged)
        gap = ""
    source = props.get("source") or "sim:scenario_v0"
    return DataProvenance(
        source=str(source),
        version="v0-draft",
        captured_at=captured_at,
        is_simulated=simulated,
        uncertainty_note=("草稿几何，不是实测场地。" + gap + extra).strip(),
    )


def _landing_site(feature: dict[str, Any], captured_at: datetime, *, occupied: bool) -> LandingSite:
    props = feature.get("properties") or {}
    site_id = props.get("id")
    if not isinstance(site_id, str) or not site_id:
        raise ApiError(500, "备降点缺少 properties.id")
    coords = (feature.get("geometry") or {}).get("coordinates")
    if not isinstance(coords, list) or len(coords) < 2:
        raise ApiError(500, f"备降点 {site_id} 坐标不完整")
    if "radius_m" not in props:
        raise ApiError(500, f"备降点 {site_id} 缺少 radius_m，拒绝填一个默认半径")
    vehicles = props.get("compatible_vehicle_types")
    if not isinstance(vehicles, list):
        raise ApiError(500, f"备降点 {site_id} 缺少 compatible_vehicle_types")
    try:
        return LandingSite(
            site_id=site_id,
            position=Position(
                frame=Frame.ENU_M,
                x_m=float(coords[0]),
                y_m=float(coords[1]),
                alt_m=0.0,
                alt_ref=AltitudeReference.AGL,
            ),
            radius_m=float(props["radius_m"]),
            compatible_vehicle_types=[str(item) for item in vehicles],
            occupied=occupied,
            provenance=_provenance(
                props,
                captured_at,
                extra="二维点没有测量高度。alt_m=0 且 alt_ref=agl 表示按地面理解，不是缺失值占位。",
            ),
        )
    except ValidationError as exc:
        raise ApiError(500, f"备降点 {site_id} 无法构成 LandingSite：{_first_error(exc)}") from exc


def _zone_index(features: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for feature in features:
        props = feature.get("properties") or {}
        zone_id = props.get("id")
        if isinstance(zone_id, str) and zone_id:
            found[zone_id] = feature
    return found


def load_scene_document(scene_id: str) -> SceneDocument:
    if scene_id != SCENE_ID:
        raise ApiError(404, f"没有场景 {scene_id}。当前只有草稿场景 v0。")

    obstacles_fc = _read_collection("obstacles.geojson")
    zones_fc = _read_collection("zones.geojson")
    sites_fc = _read_collection("landing_sites.geojson")
    captured_at = datetime.now(UTC)
    obstacles = _features(obstacles_fc)
    zones = _features(zones_fc)
    sites = [_landing_site(feature, captured_at, occupied=False) for feature in _features(sites_fc)]
    status = str(obstacles_fc.get("status") or zones_fc.get("status") or "unknown")
    return SceneDocument(
        scene_id=SCENE_ID,
        is_simulated=True,
        geometry_status=status,
        crs_note=str(obstacles_fc.get("crs_note") or ""),
        note=str(obstacles_fc.get("note") or ""),
        obstacles=obstacles,
        restriction_zones=zones,
        landing_sites=sites,
        counts={
            "obstacles": len(obstacles),
            "restriction_zones": len(zones),
            "landing_sites": len(sites),
        },
    )


def bind_scene(task_id: str, request: SceneBindRequest, *, snapshot_id: str) -> SceneBindResult:
    if request.scene_id != SCENE_ID:
        raise ApiError(404, f"没有场景 {request.scene_id}。当前只有草稿场景 v0。")

    zones_fc = _read_collection("zones.geojson")
    sites_fc = _read_collection("landing_sites.geojson")
    zones = _zone_index(_features(zones_fc))
    site_features = _features(sites_fc)
    known_sites = {
        str((feature.get("properties") or {}).get("id"))
        for feature in site_features
        if (feature.get("properties") or {}).get("id")
    }

    unknown_zones = [zone_id for zone_id in request.active_zone_ids if zone_id not in zones]
    if unknown_zones:
        known = "、".join(sorted(zones))
        raise ApiError(422, f"未知限制区 {', '.join(unknown_zones)}。场景里有：{known}")
    unknown_sites = [site_id for site_id in request.occupied_site_ids if site_id not in known_sites]
    if unknown_sites:
        raise ApiError(422, f"未知备降点 {', '.join(unknown_sites)}")

    captured_at = datetime.now(UTC)
    occupied = set(request.occupied_site_ids)
    landing_sites = [
        _landing_site(
            feature,
            captured_at,
            occupied=str((feature.get("properties") or {}).get("id")) in occupied,
        )
        for feature in site_features
    ]
    events: list[RiskEvent] = []
    for zone_id in request.active_zone_ids:
        feature = zones[zone_id]
        props = feature.get("properties") or {}
        alt_min = props.get("alt_min_m")
        alt_max = props.get("alt_max_m")
        events.append(
            RiskEvent(
                event_id=f"zone-{zone_id}",
                kind="restriction_zone",
                geometry={
                    "type": "Feature",
                    "geometry": feature.get("geometry") or {},
                    "properties": {"id": zone_id},
                    "zone_id": zone_id,
                },
                alt_min_m=float(alt_min) if alt_min is not None else None,
                alt_max_m=float(alt_max) if alt_max is not None else None,
                effective_from=captured_at,
                provenance=_provenance(props, captured_at, extra="由加载场景时点名，视为当前已经生效。"),
            )
        )

    active = "、".join(request.active_zone_ids) if request.active_zone_ids else "无"
    note = (
        "仿真草稿。几何来自 scenarios/v0（status=draft，is_simulated=true），不是实测空域。"
        "障碍物不在 RiskSnapshot 里，规划时仍从 obstacles.geojson 读取。"
        f"本次标为已生效的限制区：{active}。"
    )
    try:
        snapshot = RiskSnapshot(
            snapshot_id=snapshot_id,
            captured_at=captured_at,
            landing_sites=landing_sites,
            events=events,
            note=note,
        )
    except ValidationError as exc:
        raise ApiError(500, f"场景无法构成 RiskSnapshot：{_first_error(exc)}") from exc
    return SceneBindResult(snapshot=snapshot, scene_id=SCENE_ID, is_simulated=True, note=note)
