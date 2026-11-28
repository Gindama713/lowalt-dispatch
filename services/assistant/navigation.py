"""Geometric alternatives with explicit ENU simulation and real WGS84 data."""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from planner.astar import plan
from planner.grid import build_grid
from planner.scene import load_scene
from services.assistant import route_weather
from services.assistant.airspace_snapshot import (
    ConstraintSnapshot,
    check_route_against_snapshot,
)
from services.assistant.airspace_snapshot import (
    store as airspace_store,
)
from services.assistant.vehicles import VehicleSelection, evaluate_vehicle


class ScenePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float = Field(ge=10, le=2990)
    y: float = Field(ge=10, le=2990)


class GeographicPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-80, le=80)


class AvoidRegion(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=160)
    name: str | None = Field(default=None, max_length=200)
    kind: Literal["restricted", "internal"]
    geometry: dict
    source: str = Field(min_length=1, max_length=300)
    source_ref: str = Field(default="", max_length=1000)
    source_kind: Literal["official", "manufacturer", "team"] = "team"
    is_simulated: bool = True
    updated_at: str | None = None
    fetched_at: str | None = None
    effective_from: str | None = None
    effective_until: str | None = None
    altitude_ref: Literal["agl", "amsl", "rel_takeoff"] | None = None
    max_height_m: float | None = Field(default=None, ge=-500, le=10000)
    description: str = Field(default="", max_length=1500)

    @model_validator(mode="after")
    def valid(self):
        from shapely.geometry import shape

        if self.geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("限制区仅支持 Polygon/MultiPolygon")
        rings = self.geometry.get("coordinates", [])
        polygons = [rings] if self.geometry["type"] == "Polygon" else rings
        if (
            not isinstance(polygons, list)
            or not polygons
            or any(not isinstance(p, list) or not p for p in polygons)
        ):
            raise ValueError("限制区多边形结构无效")
        if any(
            not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1] for p in polygons for ring in p
        ):
            raise ValueError("限制区环必须闭合且至少四点")
        vertices = [p for polygon in polygons for ring in polygon for p in ring]
        if (
            not vertices
            or len(vertices) > 5000
            or any(
                not isinstance(p, list)
                or len(p) != 2
                or not all(
                    isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in p
                )
                or not (-180 <= p[0] <= 180 and -80 <= p[1] <= 80)
                for p in vertices
            )
        ):
            raise ValueError("限制区坐标无效或顶点过多")
        geom = shape(self.geometry)
        if geom.is_empty or not geom.is_valid:
            raise ValueError("限制区拓扑无效")
        for value in (self.effective_from, self.effective_until, self.updated_at, self.fetched_at):
            if value is not None and datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                raise ValueError("限制区时刻须包含时区")
        if (
            self.effective_from
            and self.effective_until
            and datetime.fromisoformat(self.effective_until.replace("Z", "+00:00"))
            <= datetime.fromisoformat(self.effective_from.replace("Z", "+00:00"))
        ):
            raise ValueError("限制区时间范围无效")
        return self


class CandidateInput(VehicleSelection):
    model_config = ConfigDict(extra="forbid")
    origin: ScenePoint | GeographicPoint
    destination: ScenePoint | GeographicPoint
    frame: Literal["ENU", "WGS84"]
    scheduled_for: str | None = None
    resolution_m: Literal[10, 20, 30] = 10
    max_expand: int = Field(default=500_000, ge=1000, le=1_000_000)
    avoid_regions: list[AvoidRegion] = Field(default_factory=list, max_length=100)
    snapshot_id: str | None = Field(default=None, max_length=64)
    include_flysafe: bool = True
    zone_buffer_m: float = Field(default=0.0, ge=0.0, le=500.0)
    intake_id: str | None = Field(default=None, max_length=160)
    previous_waypoints: list[list[float]] | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def distinct(self):
        if self.scheduled_for is not None:
            instant = datetime.fromisoformat(self.scheduled_for.replace("Z", "+00:00"))
            if instant.tzinfo is None:
                raise ValueError("起飞时刻须包含时区")
        if self.frame == "WGS84":
            from planner.georef import distance_m

            if not isinstance(self.origin, GeographicPoint) or not isinstance(
                self.destination, GeographicPoint
            ):
                raise ValueError("WGS84 起终点须使用 lng、lat，经度在前")
            start = (self.origin.lng, self.origin.lat)
            goal = (self.destination.lng, self.destination.lat)
            distance = distance_m(start, goal)
            if abs(start[0] - goal[0]) > 180 or distance > 80_000:
                raise ValueError("真实航线限80km局部区域，跨日期变更线请分段规划")
            if self.previous_waypoints is not None:
                if len(self.previous_waypoints) < 2 or any(
                    not isinstance(p, list)
                    or len(p) != 2
                    or not all(
                        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                        for v in p
                    )
                    or not (-180 <= p[0] <= 180 and -85.0511 <= p[1] <= 85.0511)
                    for p in self.previous_waypoints
                ):
                    raise ValueError("原对比路线航点必须为有效 WGS84 [lng, lat] 序列")
        else:
            if self.avoid_regions or self.snapshot_id or self.zone_buffer_m > 0:
                raise ValueError("WGS84 导入限制区或约束快照不能绑定到 ENU 演示锚点，请使用真实坐标规划")
            if not isinstance(self.origin, ScenePoint) or not isinstance(self.destination, ScenePoint):
                raise ValueError("ENU 起终点须使用固定仿真场景 x、y")
            distance = (
                (self.origin.x - self.destination.x) ** 2 + (self.origin.y - self.destination.y) ** 2
            ) ** 0.5
        if distance < 10:
            raise ValueError("起终点至少相距10米")
        return self


@lru_cache(maxsize=2)
def scene_grid(clearance):
    scene = load_scene()
    return build_grid(scene.obstacles + [z.polygon for z in scene.zones.values()], clearance_m=clearance)


def candidate_routes(body: CandidateInput):
    if body.frame == "WGS84":
        return real_candidate_routes(body)
    start = (body.origin.x, body.origin.y)
    goal = (body.destination.x, body.destination.y)
    signature = hashlib.sha256(json.dumps([start, goal]).encode()).hexdigest()[:12]
    alternatives = []
    for clearance, title in ((30, "标准净空 · 几何A*"), (60, "加宽净空 · 几何A*")):
        result = plan(scene_grid(clearance), start, goal, max_expand=90000)
        available = result.found and not result.snapped
        alternatives.append(
            {
                "id": f"nav-{signature}-{clearance}",
                "title": title,
                "available": available,
                "clearance_m": route_weather.truncate_reported(clearance, 1),
                "reason": None if available else "该净空下无可用路线或端点被占用，需人工调整；未移动端点。",
                "route": {
                    "id": f"nav-{signature}-{clearance}",
                    "title": title,
                    "source": "planner.astar.plan · 固定场景静态几何计算",
                    "frame": "ENU",
                    "altitude_ref": None,
                    "is_simulated": True,
                    "task_id": None,
                    "plan_version": None,
                    "waypoints": [{"x": x, "y": y} for x, y in collapse_collinear(result.waypoints)],
                }
                if available
                else None,
            }
        )
    return {
        "alternatives": alternatives,
        "dispatch_enabled": False,
        "is_simulated": True,
        "precision_note": route_weather.PRECISION_NOTE,
        "limitation": "仅固定3km ENU场景。30/60m为栅格膨胀参数，不是实测净空；全部限制区保守静态避让。"
        "未校验高度、机型、风、时效、能耗与备降可达，不能用于真实地点或直接飞行。",
    }


def real_candidate_routes(
    body: CandidateInput,
    *,
    budget_total_s: float = 42.0,
    snapshot: ConstraintSnapshot | None = None,
):
    from planner.real import plan_real_route
    from services.assistant.osm_obstacles import fetch_obstacles
    from services.assistant.route_weather import assess_route_weather

    if not math.isfinite(budget_total_s) or budget_total_s <= 0:
        raise ValueError("真实航线总时间预算必须为有限正数")
    start = (body.origin.lng, body.origin.lat)
    goal = (body.destination.lng, body.destination.lat)

    bound_snapshot = (
        snapshot.for_schedule(body.scheduled_for)
        if snapshot is not None
        else airspace_store.resolve(
            snapshot_id=body.snapshot_id,
            avoid_regions=body.avoid_regions,
            zone_buffer_m=body.zone_buffer_m,
            scheduled_for=body.scheduled_for,
        )
    )
    # Callers that already froze a snapshot (intake background / route refresh)
    # pass it in and set include_flysafe false. Direct planning refreshes here.
    promote_active = False
    if body.include_flysafe and snapshot is None:
        from services.assistant.flysafe import refresh_planning_snapshot

        refreshed = refresh_planning_snapshot(
            start,
            goal,
            zone_buffer_m=bound_snapshot.zone_buffer_m,
            scheduled_for=body.scheduled_for,
            prior=bound_snapshot,
        )
        if refreshed is not None:
            bound_snapshot = refreshed
            promote_active = True
    airspace_store.save(bound_snapshot, set_active=promote_active)
    exclusions = bound_snapshot.to_exclusions_fc(scheduled_for=body.scheduled_for)
    enforced_zones = [z for z in bound_snapshot.zones if z.participates_in_avoidance]

    # Leave the rest of the caller budget for rasterization and search.
    fetch_budget = min(18.0, max(1.0, budget_total_s * 0.45))
    dataset = fetch_obstacles(start, goal, margin_m=1000, budget_s=fetch_budget, max_workers=2)
    metadata = dict(dataset["metadata"])

    # Coarse resolutions (20/30 m) carry a larger half-cell margin, so dense
    # urban corridors can be sealed even when a 10 m grid is traversable. That is
    # a safety-margin consequence, not a search bug. We therefore retry at 10 m
    # and report every attempt instead of silently changing the clearance or
    # claiming the coarse request succeeded.
    plan_attempts = []
    result = None
    attempt = None
    resolution_used = body.resolution_m
    deadline = time.perf_counter() + budget_total_s
    for resolution in sorted({body.resolution_m, 10}, reverse=True):
        remaining = deadline - time.perf_counter()
        if remaining <= 2:
            plan_attempts.append(
                {
                    "resolution_m": resolution,
                    "found": False,
                    "reason": "总时间预算耗尽，未尝试该分辨率",
                    "nodes_expanded": 0,
                    "elapsed_ms": 0,
                    "length_m": None,
                }
            )
            continue
        attempt = plan_real_route(
            start,
            goal,
            dataset["obstacles"],
            exclusions_fc=exclusions,
            zone_buffer_m=bound_snapshot.zone_buffer_m,
            resolution_m=resolution,
            max_expand=body.max_expand,
            budget_s=min(28.0, remaining),
        )
        plan_attempts.append(
            {
                "resolution_m": resolution,
                "found": attempt["found"],
                "reason": attempt.get("reason"),
                "nodes_expanded": attempt["nodes_expanded"],
                "elapsed_ms": round(attempt["elapsed_ms"], 1),
                "length_m": round(attempt["length_m"], 1) if attempt["found"] else None,
            }
        )
        if attempt["found"]:
            result, resolution_used = attempt, resolution
            break
    if result is None:
        if attempt is None:
            raise RuntimeError("真实航线规划没有可用时间预算，未开始任何搜索")
        # Keep the coarsest failure as the headline result; attempts carry detail.
        result = attempt

    found = bool(result["found"])
    # Independent airspace check against the exact bound snapshot (separate from geometric generation).
    if found:
        airspace_check = check_route_against_snapshot(
            result["waypoints"],
            bound_snapshot,
            scheduled_for=body.scheduled_for,
        )
        if airspace_check["status"] == "conflict":
            found = False
            result = {
                **result,
                "found": False,
                "waypoints": [],
                "reason": "独立连续空域复核检出限制区冲突，拒绝发布候选航线",
            }
    else:
        endpoint_check = check_route_against_snapshot(
            [start, goal],
            bound_snapshot,
            scheduled_for=body.scheduled_for,
        )
        if result.get("endpoint_zone_conflict") is not None:
            ep_conflicts = [
                c
                for c in endpoint_check.get("conflicts", [])
                if c.get("conflict_type") in {"origin_inside", "destination_inside"}
            ]
            airspace_check = {
                **endpoint_check,
                "status": "conflict",
                "passed_known_snapshot": False,
                "verdict_label": result.get("reason") or "起终点位于限制区内，拒绝规划",
                "conflicts": ep_conflicts or endpoint_check.get("conflicts", []),
            }
        else:
            airspace_check = {
                **endpoint_check,
                "conflicts": [],
                "conflicting_zone_ids": [],
                "conflicting_segment_indices": [],
                "checked_segment_count": 0,
                "passed_known_snapshot": None,
                "verdict_label": "几何路线未生成，未形成可核验航段（"
                + str(result.get("reason") or "无可行通道")
                + "）",
            }

    previous_route_check = (
        check_route_against_snapshot(
            body.previous_waypoints,
            bound_snapshot,
            scheduled_for=body.scheduled_for,
        )
        if body.previous_waypoints
        else None
    )
    route_changed: bool | None = None
    if body.previous_waypoints and found:
        prev_norm = [[round(float(p[0]), 6), round(float(p[1]), 6)] for p in body.previous_waypoints]
        curr_norm = [[round(float(lng), 6), round(float(lat), 6)] for lng, lat in result["waypoints"]]
        route_changed = prev_norm != curr_norm

    warnings = list(dataset.get("warnings", [])) + list(result.get("warnings", []))
    if resolution_used != body.resolution_m and found:
        warnings.append(
            f"请求分辨率 {body.resolution_m:g} m 在 20 m 物理净空下无可行通道，已自动改用 "
            f"{resolution_used:g} m 重新搜索；净空标准未降低。"
        )
    if bound_snapshot.source_status == "manufacturer_reference":
        airspace_warning = (
            "已载入大疆 FlySafe 厂商地理围栏参考，不是法定空域，不是 UOM / 国家地图官网 / 天地图数据，"
            "也不代表获准飞行。官方 NOTAM / UOM 仍须人工核对。"
        )
    elif bound_snapshot.source_status == "unavailable":
        airspace_warning = (
            "大疆 FlySafe 本次不可用或为空，空域未知，不是放行，未编造围栏。"
            "NOTAM / UOM 仍须人工核对；此结果不代表获准飞行。"
        )
    else:
        airspace_warning = (
            "真实空域未接入，NOTAM / UOM 及机场、人口密集区限制须人工核对；此结果不代表获准飞行。"
        )
    warnings += [
        airspace_warning,
        "只验证所下载建筑足迹的水平避障；未验证地形、电线、塔吊、移动障碍和垂直航路。",
        "道路来自 OSM，仅作地理参照，未视作获准飞行走廊。",
    ]
    weather = (
        assess_route_weather(
            result["waypoints"],
            body.scheduled_for,
            vehicle_key=body.vehicle_key,
            custom_vehicle=body.custom_vehicle,
            obstacles=dataset["obstacles"],
        )
        if found
        else {
            "status": "unavailable",
            "source": "Open-Meteo / hourly forecast",
            "warnings": ["未找到几何航线，未请求航路天气"],
            "energy": {"status": "unavailable", "reason": "无几何航线"},
        }
    )
    warnings += weather.get("warnings", [])
    signature = hashlib.sha256(
        json.dumps(
            [
                start,
                goal,
                metadata.get("fetched_at"),
                bound_snapshot.digest,
                resolution_used,
                result.get("heuristic_weight"),
                result["waypoints"],
            ]
        ).encode()
    ).hexdigest()[:12]
    title = (
        f"几何 A* · OSM 建筑 + {len(enforced_zones)} 个已知限制区避让 · 官方空域待核对"
        if enforced_zones
        else "几何 A* · OSM 真实建筑足迹 · 空域待人工核对"
    )
    route = (
        {
            "id": f"real-{signature}",
            "title": title,
            "frame": "WGS84",
            "altitude_ref": None,
            "is_simulated": False,
            "source": f"{metadata['source']} · planner.real · 水平几何参考",
            "task_id": body.intake_id,
            "plan_version": bound_snapshot.version,
            "constraint_snapshot_id": bound_snapshot.snapshot_id,
            "constraint_digest": bound_snapshot.digest,
            "waypoints": [{"x": lng, "y": lat, "lng": lng, "lat": lat} for lng, lat in result["waypoints"]],
            "length_m": route_weather.truncate_reported(result["length_m"], 1),
        }
        if found
        else None
    )
    plan_stages = result.get("stage_timings_ms") or {}
    metadata["plan_stage_timings_ms"] = {
        "rasterization": plan_stages.get("rasterization"),
        "astar_search": plan_stages.get("astar_search"),
    }
    reported_clearance = route_weather.truncate_reported(result["clearance_m"], 1)
    reported_length = route["length_m"] if route is not None else None
    assessment = evaluate_vehicle(body, reported_length)
    estimate = assessment.get("estimate")
    duration = estimate.get("duration_s") if isinstance(estimate, dict) else None
    if isinstance(duration, (int, float)) and not isinstance(duration, bool):
        estimate["duration_s"] = route_weather.truncate_reported(duration, 1)

    geometric_generation = {
        "generated": found,
        "route_id": route["id"] if route else None,
        "waypoint_count": len(result["waypoints"]) if found else 0,
        "length_m": reported_length,
        "resolution_requested_m": body.resolution_m,
        "resolution_used_m": resolution_used if found else None,
        "continuous_building_clearance_verified": result.get("continuous_clearance_verified", False),
        "continuous_zone_clearance_verified": result.get("continuous_zone_verified", False),
        "reason": result.get("reason"),
    }

    legacy_airspace_status = (
        "user_exclusions_applied"
        if enforced_zones
        else "known_empty_snapshot"
        if bound_snapshot.source_status == "known_empty"
        else "query_failed"
        if bound_snapshot.source_status == "query_failed"
        else "unavailable"
        if bound_snapshot.source_status == "unavailable"
        else "manual_review_required"
    )
    sources_label = (
        "；".join(sorted({z.source for z in bound_snapshot.zones}))
        if bound_snapshot.zones
        else "大疆 FlySafe 厂商地理围栏参考（本次不可用或为空，不是放行）"
        if bound_snapshot.source_status == "unavailable"
        else "未导入空域边界；官方空域未接入"
    )
    return {
        "status": "ok" if found else "no_route",
        "frame": "WGS84",
        "alternatives": [
            {
                "id": f"real-{signature}",
                "title": title,
                "available": found,
                "clearance_m": reported_clearance,
                "reason": result.get("reason"),
                "route": route,
            }
        ],
        "route": route,
        "scene_id": metadata.get("scene_id"),
        "dispatch_enabled": False,
        "is_simulated": False,
        "geometric_available": found,
        "geometric_generation": geometric_generation,
        "constraint_snapshot": bound_snapshot.model_dump(mode="json"),
        "airspace_check": airspace_check,
        "previous_route_check": previous_route_check,
        "route_changed": route_changed,
        "operationally_approved": False,
        "continuous_clearance_verified": result.get("continuous_clearance_verified", False),
        "continuous_zone_verified": result.get("continuous_zone_verified", False),
        "flight_feasibility": weather.get("flight_feasibility", {"status": "unavailable"}),
        "vehicle_assessment": assessment,
        "obstacle_source": metadata["source"],
        "weather_source": weather["source"],
        "airspace": {
            "status": legacy_airspace_status,
            "check_status": airspace_check["status"],
            "verdict_label": airspace_check["verdict_label"],
            "snapshot_id": bound_snapshot.snapshot_id,
            "snapshot_digest": bound_snapshot.digest,
            "source": sources_label,
            "enforced_ids": [z.id for z in enforced_zones],
            "zone_buffer_m": bound_snapshot.zone_buffer_m,
            "buffer_source": bound_snapshot.buffer_source,
            "dispatch_enabled": False,
            "note": (
                f"{airspace_check['verdict_label']}。对尚未过期的禁飞/内部管制多边形保守作二维全高度避让"
                "（含未来生效、时效或高度未知，边界接触判为冲突）；其他类别仅展示。"
                "大疆 FlySafe 只是厂商地理围栏参考，未接官方 UOM / NOTAM，不代表获准飞行。"
            ),
            "reference_label": (
                "大疆 FlySafe 厂商地理围栏参考"
                if bound_snapshot.source_status in {"manufacturer_reference", "unavailable"}
                else None
            ),
        },
        "avoid_regions": [
            {
                "id": z.id,
                "name": z.name,
                "kind": z.kind,
                "geometry": z.geometry,
                "source": z.source,
                "source_ref": z.source_ref,
                "source_kind": z.source_kind,
                "is_simulated": z.is_simulated,
                "updated_at": z.updated_at,
                "fetched_at": z.fetched_at,
                "effective_from": z.effective_from,
                "effective_until": z.effective_until,
                "altitude_ref": z.altitude_ref,
                "max_height_m": z.max_height_m,
                "description": z.description,
            }
            for z in enforced_zones
        ],
        "clearance_m": reported_clearance,
        "zone_buffer_m": bound_snapshot.zone_buffer_m,
        "precision_note": route_weather.PRECISION_NOTE,
        "grid_clearance_m": result.get("grid_clearance_m"),
        "resolution_m": result["resolution_m"],
        "resolution_requested_m": body.resolution_m,
        "resolution_used_m": resolution_used,
        "plan_attempts": plan_attempts,
        "heuristic_weight": result.get("heuristic_weight"),
        "nodes_expanded": result["nodes_expanded"],
        "elapsed_ms": result["elapsed_ms"],
        "stage_timings_ms": result.get("stage_timings_ms", {}),
        "data": metadata,
        "weather": weather,
        "warnings": list(dict.fromkeys(warnings)),
        "limitation": "真实建筑、道路来自公开地图，可能漏测；高度含标签推算或未知，不作越顶依据。真实空域、垂直净空、平台能耗须另行核验。",
    }


def collapse_collinear(points):
    """Remove grid samples on the same straight segment without changing geometry."""
    result = []
    for point in points:
        while len(result) >= 2:
            a, b = result[-2:]
            u, v = (b[0] - a[0], b[1] - a[1]), (point[0] - b[0], point[1] - b[1])
            if abs(u[0] * v[1] - u[1] * v[0]) > 1e-7 or u[0] * v[0] + u[1] * v[1] <= 0:
                break
            result.pop()
        result.append(point)
    return result
