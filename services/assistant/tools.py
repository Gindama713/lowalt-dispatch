"""Read-only tools and draft proposals; no flight command tool is exposed."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from core.geometry import polyline_length
from planner.astar import plan
from planner.grid import build_grid
from planner.scene import load_scene
from services.assistant import evidence
from services.assistant.airspace_snapshot import (
    ConstraintSnapshot,
    check_route_against_snapshot,
)
from services.assistant.airspace_snapshot import (
    store as airspace_store,
)
from services.assistant.environment import EnvQuery
from services.assistant.intake import (
    ForecastQuery,
    IntakeCreate,
    PlaceEvidence,
    PlaceQuery,
    TaskIntake,
    WeatherEvidence,
)
from services.assistant.intake import (
    store as intake_store,
)
from services.assistant.knowledge import search
from services.assistant.models import DocumentQuery, Draft, DraftUpdate, NoArgs, Turn
from services.assistant.task_evidence import EvidenceQuery, read_task_evidence
from services.assistant.telemetry import STALE_SECONDS, LiveTelemetry


class VerdictQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    evidence_id: str = Field(pattern=r"^env-[0-9a-f]{12}$")


class GapsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    evidence_id: str | None = None


class TimeWindowQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    origin: tuple[float, float]
    destination: tuple[float, float]
    window_start: str
    window_hours: int = Field(default=6, ge=1, le=24)
    step_minutes: int = Field(default=60, ge=30, le=180)


class LandingQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    origin: tuple[float, float]
    destination: tuple[float, float]
    ledger_id: str | None = Field(default=None, max_length=80)


class ProvenanceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    evidence_id: str | None = None


class AirspaceAuditQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    intake_id: str | None = Field(default=None, max_length=160)


ENV_TOOL_NAMES = {
    "inspect_mission_plan",
    "assess_route_environment",
    "explain_verdict",
    "list_environment_gaps",
    "compare_departure_times",
    "check_landing_sites",
    "audit_route_provenance",
}


ROOT = Path(__file__).resolve().parents[2]
PLACES = {
    "医疗物资中转站": (150.0, 150.0),
    "北区应急中心": (2650.0, 2750.0),
    **{key: (site.x, site.y) for key, site in load_scene().sites.items()},
}
ALIASES = {"中转站": "医疗物资中转站", "北区中心": "北区应急中心", "应急中心": "北区应急中心"}
# Single source of truth for what this build actually does. The assistant panel
# renders it instead of offering clickable prompts that only produce boilerplate.
CAPABILITIES = {
    "available": [
        "竞赛冻结任务证据卡：算法路线、余量剖面、独立校验与数据缺口",
        "航线环境判定、因素矩阵、未判定项与起飞时刻对比",
        "起降点台账离线样例校核（未接运营方台账）",
        "项目文档与无人机合规知识检索（带文件、行号或来源链接）",
        "当前页面的演示或 M4 遥测查询",
        "本地合成任务状态与回执查询",
        "真实地点搜索与地图选点（WGS84）",
        "多轮任务工单：先追问、信息齐了再建单",
        "几何 A* 路线预览（ENU 仿真）",
        "WGS84 真实建筑足迹避障规划与 OSM 道路参照（公开数据可能不全）",
        "WGS84 禁飞/限制区约束快照绑定、逐航段冲突检出与重算绕行复核（支持导入或演练多边形）",
        "Open-Meteo 航路逐时预报（自定义能耗明确标记用户参数测试）",
        "配送机型库：厂家官方规格与用户自定义参数测试",
        "地形变化平面影响分析",
        "本页事件解释",
    ],
    "pending": [
        "M3 跨服务确认与审计查询",
        "机型能量参数标定",
        "含备降硬约束的动态规划",
        "真实空域数据（NOTAM / UOM 暂无公开接口）",
        "PX4 任务执行与飞控回执",
    ],
}


def resolve_place(name: str | None):
    if not name:
        return None
    return PLACES.get(ALIASES.get(name.strip(), name.strip()))


def draft_digest(draft: Draft):
    return hashlib.sha256(draft.model_dump_json().encode()).hexdigest()


@lru_cache(maxsize=1)
def baseline():
    data = json.loads((ROOT / "apps/console/public/demo-scene.json").read_text(encoding="utf-8"))
    return data["route"]


def segment_box(a, b, bounds):
    """Closed segment/rectangle intersection, including boundary contacts."""
    lo, hi = 0.0, 1.0
    for start, delta, low, high in (
        (a[0], b[0] - a[0], bounds.minX, bounds.maxX),
        (a[1], b[1] - a[1], bounds.minY, bounds.maxY),
    ):
        if abs(delta) < 1e-12:
            if start < low or start > high:
                return None
            continue
        t0, t1 = sorted(((low - start) / delta, (high - start) / delta))
        lo, hi = max(lo, t0), min(hi, t1)
        if lo > hi:
            return None
    return lo, hi


def point_at(route, progress):
    remaining = polyline_length(route) * progress
    for a, b in zip(route, route[1:], strict=False):
        length = math.dist(a, b)
        if remaining <= length:
            fraction = remaining / length if length else 0
            return [a[i] + (b[i] - a[i]) * fraction for i in range(2)]
        remaining -= length
    return list(route[-1])


def _airspace_evidence_from_snapshot(
    snapshot: ConstraintSnapshot,
    airspace_check: dict | None = None,
) -> dict:
    """Build intake ``airspace`` field from a WGS84 ConstraintSnapshot (never ENU v0)."""
    verdict = (airspace_check or {}).get("verdict_label") or (
        "未导入空域区域（空域未核对，非通过）"
        if snapshot.source_status == "not_loaded"
        else "已知快照显式为空（0 个已知限制区；非官方放行）"
        if snapshot.source_status == "known_empty"
        else f"已绑定 {snapshot.enforced_zone_count}/{snapshot.total_zone_count} 个参与避让的已知区域"
    )
    return {
        "status": (airspace_check or {}).get("status") or snapshot.source_status,
        "source_status": snapshot.source_status,
        "snapshot_id": snapshot.snapshot_id,
        "version": snapshot.version,
        "digest": snapshot.digest,
        "crs": snapshot.crs,
        "is_simulated": snapshot.is_simulated,
        "zone_buffer_m": snapshot.zone_buffer_m,
        "buffer_source": snapshot.buffer_source,
        "boundary_rule": snapshot.boundary_rule,
        "enforced_zone_count": snapshot.enforced_zone_count,
        "total_zone_count": snapshot.total_zone_count,
        "enforced_zone_ids": list(snapshot.enforced_zone_ids),
        "zones": [
            {
                "id": z.id,
                "name": z.name,
                "kind": z.kind,
                "source": z.source,
                "source_kind": z.source_kind,
                "is_simulated": z.is_simulated,
                "participates_in_avoidance": z.participates_in_avoidance,
                "buffer_m": z.buffer_m,
                "avoidance_rule": z.avoidance_rule,
            }
            for z in snapshot.zones
        ],
        "note": f"{verdict}。快照 {snapshot.snapshot_id}（{snapshot.digest[:19]}…）；未接官方 UOM/NOTAM，不代表获准飞行。",
    }


def _invoke_route_provider(
    provider: Callable[..., dict],
    origin: list[float],
    destination: list[float],
    scheduled_for: str | None,
    *,
    snapshot: ConstraintSnapshot | None = None,
    intake_id: str | None = None,
    previous_waypoints: list[list[float]] | None = None,
) -> dict:
    """Call real_route_for_intake or a 3-arg test stub, always attaching snapshot & check."""
    sig = inspect.signature(provider)
    accepts_kw = "snapshot" in sig.parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if accepts_kw:
        result = provider(
            origin,
            destination,
            scheduled_for,
            snapshot=snapshot,
            intake_id=intake_id,
            previous_waypoints=previous_waypoints,
        )
    else:
        result = provider(origin, destination, scheduled_for)

    if snapshot is not None and isinstance(result, dict):
        result = dict(result)
        result.setdefault("constraint_snapshot", snapshot.model_dump(mode="json"))
        if result.get("airspace_check") is None:
            wps = result.get("waypoints") or []
            result["airspace_check"] = check_route_against_snapshot(
                wps,
                snapshot,
                scheduled_for=scheduled_for,
            )
        if previous_waypoints and result.get("previous_route_check") is None:
            result["previous_route_check"] = check_route_against_snapshot(
                previous_waypoints,
                snapshot,
                scheduled_for=scheduled_for,
            )
    return result


def real_route_for_intake(
    origin: list[float],
    destination: list[float],
    scheduled_for: str | None,
    *,
    snapshot: ConstraintSnapshot | None = None,
    intake_id: str | None = None,
    previous_waypoints: list[list[float]] | None = None,
) -> dict:
    """Compute one real-geometry route for an intake bound to a ConstraintSnapshot; never raises."""
    from services.assistant.navigation import CandidateInput, real_candidate_routes

    bound = snapshot or airspace_store.resolve(scheduled_for=scheduled_for)
    try:
        body = CandidateInput(
            frame="WGS84",
            origin={"lng": float(origin[0]), "lat": float(origin[1])},
            destination={"lng": float(destination[0]), "lat": float(destination[1])},
            scheduled_for=scheduled_for,
            resolution_m=10,
            max_expand=1_000_000,
            snapshot_id=bound.snapshot_id,
            zone_buffer_m=bound.zone_buffer_m,
            intake_id=intake_id,
            previous_waypoints=previous_waypoints,
            include_flysafe=False,
        )
        result = real_candidate_routes(body, budget_total_s=30.0, snapshot=bound)
    except Exception as exc:  # network, OSM schema, budget — record, do not guess
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            first = exc.errors()[0]
            reason = f"输入不合法：{first.get('msg', '')}（字段 {'.'.join(map(str, first.get('loc', ())))}）"
        else:
            reason = f"{type(exc).__name__}: {str(exc)[:200]}"
        failed_check = check_route_against_snapshot([], bound, scheduled_for=scheduled_for)
        return {
            "status": "unavailable",
            "frame": "WGS84",
            "waypoints": [],
            "reason": reason,
            "geometric_generation": {
                "generated": False,
                "route_id": None,
                "waypoint_count": 0,
                "length_m": None,
                "reason": reason,
            },
            "constraint_snapshot": bound.model_dump(mode="json"),
            "airspace_check": {
                **failed_check,
                "passed_known_snapshot": None,
                "verdict_label": f"几何路线未生成（{reason}）；未完成航段空域核验",
            },
            "computed_at": datetime.now(UTC).isoformat(),
            "note": "真实航线未生成；未使用直线或仿真路线代替。",
        }
    route = result.get("route") or {}
    return {
        "status": result["status"],
        "frame": "WGS84",
        "route_id": route.get("id"),
        "route": route,
        "scene_id": result.get("scene_id"),
        "planning_result": result,
        "waypoints": route.get("waypoints") or [],
        "length_m": route.get("length_m"),
        "resolution_requested_m": result.get("resolution_requested_m"),
        "resolution_used_m": result.get("resolution_used_m"),
        "clearance_m": result.get("clearance_m"),
        "zone_buffer_m": result.get("zone_buffer_m"),
        "continuous_clearance_verified": result.get("continuous_clearance_verified", False),
        "continuous_zone_verified": result.get("continuous_zone_verified", False),
        "geometric_generation": result.get("geometric_generation"),
        "constraint_snapshot": result.get("constraint_snapshot"),
        "airspace_check": result.get("airspace_check"),
        "previous_route_check": result.get("previous_route_check"),
        "route_changed": result.get("route_changed"),
        "obstacle_source": result.get("obstacle_source"),
        "reason": (result.get("alternatives") or [{}])[0].get("reason"),
        "attempts": result.get("plan_attempts", []),
        "warnings": [
            warning
            for warning in result.get("warnings", [])
            if "空域" in warning or "OSM" in warning or "自动改用" in warning or "管制区" in warning
        ][:5],
        "computed_at": datetime.now(UTC).isoformat(),
        "note": "几何避障参考；未接真实空域、地形、线缆，不代表获准飞行。",
    }


def apply_route_update_to_intake(
    intake: dict,
    new_route: dict,
    snapshot: ConstraintSnapshot,
    *,
    store_override=None,
) -> dict:
    """Persist a newly computed route onto an intake, archiving any prior version + its conflict check."""
    history = list(intake.get("route_history") or [])
    old_route = intake.get("real_route") or {}
    old_wps = old_route.get("waypoints") or []
    old_lonlats = [
        [float(pt.get("lng", pt.get("x"))), float(pt.get("lat", pt.get("y")))]
        for pt in old_wps
        if isinstance(pt, dict) and pt.get("lng", pt.get("x")) is not None
    ]
    recheck_old = None
    if len(old_lonlats) >= 2:
        recheck_old = check_route_against_snapshot(
            old_lonlats,
            snapshot,
            scheduled_for=intake.get("scheduled_for"),
        )
        old_snap = intake.get("constraint_snapshot") or (old_route.get("planning_result") or {}).get(
            "constraint_snapshot"
        )
        prev_idx = len(history) + 1
        history.append(
            {
                "version_index": prev_idx,
                "version_label": f"v{prev_idx}",
                "route_id": old_route.get("route_id") or (old_route.get("route") or {}).get("id"),
                "waypoints": old_wps,
                "length_m": old_route.get("length_m"),
                "original_snapshot_id": (old_snap or {}).get("snapshot_id"),
                "original_snapshot_digest": (old_snap or {}).get("digest"),
                "original_airspace_check": intake.get("airspace_check")
                or check_route_against_snapshot(
                    old_lonlats, old_snap, scheduled_for=intake.get("scheduled_for")
                ),
                "rechecked_against_snapshot_id": snapshot.snapshot_id,
                "rechecked_against_snapshot_digest": snapshot.digest,
                "rechecked_airspace_check": recheck_old,
                "archived_at": datetime.now(UTC).isoformat(),
            }
        )

    version_idx = len(history) + 1
    new_wps = new_route.get("waypoints") or []
    new_lonlats = [
        [float(pt.get("lng", pt.get("x"))), float(pt.get("lat", pt.get("y")))]
        for pt in new_wps
        if isinstance(pt, dict) and pt.get("lng", pt.get("x")) is not None
    ]
    route_changed: bool | None = None
    if len(old_lonlats) >= 2 and len(new_lonlats) >= 2:
        old_norm = [[round(a, 6), round(b, 6)] for a, b in old_lonlats]
        new_norm = [[round(a, 6), round(b, 6)] for a, b in new_lonlats]
        route_changed = old_norm != new_norm

    enriched_route = {
        **new_route,
        "version_index": version_idx,
        "version_label": f"v{version_idx}",
        "constraint_snapshot": snapshot.model_dump(mode="json"),
        "previous_route_check": recheck_old or new_route.get("previous_route_check"),
        "route_changed": route_changed if route_changed is not None else new_route.get("route_changed"),
    }
    airspace_check = enriched_route.get("airspace_check") or check_route_against_snapshot(
        new_lonlats,
        snapshot,
        scheduled_for=intake.get("scheduled_for"),
    )
    enriched_route["airspace_check"] = airspace_check

    warnings = [
        item
        for item in intake.get("warnings", [])
        if "后台计算中" not in item and "真实航线未生成" not in item and "几何避障结果" not in item
    ]
    if enriched_route.get("status") == "ok":
        warnings.append(
            f"航线 {enriched_route['version_label']} 为公开地图建筑足迹 + 20 m 物理净空、"
            f"并绑定约束快照 {snapshot.snapshot_id}（{snapshot.enforced_zone_count} 个生效限制区）的几何避障结果；"
            "未接官方 UOM/NOTAM、地形、线缆，不代表获准飞行。"
        )
    else:
        warnings.append(
            "真实航线未生成：" + str(enriched_route.get("reason") or "未知原因") + "；未用直线代替。"
        )

    updated = {
        **intake,
        "real_route": enriched_route,
        "constraint_snapshot": snapshot.model_dump(mode="json"),
        "airspace_check": airspace_check,
        "airspace": _airspace_evidence_from_snapshot(snapshot, airspace_check),
        "route_history": history,
        "warnings": warnings,
    }
    target_store = store_override or intake_store
    return target_store.create(TaskIntake.model_validate(updated))


def normalize_scheduled_for(value: str | None) -> tuple[str | None, str]:
    """Coerce a model-supplied time into an ISO instant with timezone.

    Models occasionally pass ``11-17T10:40`` (no year) or a naive local time.
    That used to reach ``CandidateInput`` and blow up with a raw pydantic error
    *after* the intake was already written. Here we either return a valid instant
    plus a note explaining any assumption, or ``None`` so the caller can ask.
    """
    if not value or not str(value).strip():
        return None, ""
    raw = str(value).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=evidence.LOCAL_TZ)
            return parsed.isoformat(), f"「{raw}」未带时区，按 Asia/Shanghai 解释"
        return parsed.isoformat(), ""
    # Yearless forms the model likes: 11-17T10:40 / 11-17 10:40
    match = re.search(r"(?<!\d)(\d{1,2})-(\d{1,2})[T ]\s*(\d{1,2}):(\d{2})", raw)
    if match:
        month, day, hour, minute = (int(part) for part in match.groups())
        year = datetime.now(evidence.LOCAL_TZ).year
        try:
            parsed = datetime(year, month, day, hour, minute, tzinfo=evidence.LOCAL_TZ)
        except ValueError:
            return None, f"「{raw}」不是有效日期，未采用"
        return parsed.isoformat(), f"「{raw}」缺少年份，按 {year} 年解释（可改）"
    parsed_text, note = evidence.parse_schedule(raw)
    if parsed_text:
        return parsed_text, note + "（规则解析，待确认）"
    return None, f"「{raw}」无法解析为带时区的时刻，需用户补充"


_ROUTE_WORKERS: set[str] = set()
_ROUTE_WORKERS_LOCK = threading.Lock()
_ROUTE_SEMAPHORE = threading.Semaphore(2)


def _unavailable_route(exc: Exception) -> dict:
    from pydantic import ValidationError

    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        reason = f"输入不合法：{first.get('msg', '')}（字段 {'.'.join(map(str, first.get('loc', ())))}）"
    else:
        reason = f"{type(exc).__name__}: {str(exc)[:200]}"
    return {
        "status": "unavailable",
        "frame": "WGS84",
        "waypoints": [],
        "reason": reason,
        "computed_at": datetime.now(UTC).isoformat(),
        "note": "真实航线未生成；未使用直线或仿真路线代替。",
    }


def _compute_route_in_background(
    intake_id: str,
    provider: Callable[..., dict],
    origin: list[float],
    destination: list[float],
    scheduled_for: str | None,
    *,
    frozen_snapshot: ConstraintSnapshot | None = None,
) -> None:
    """Fill ``real_route`` after the intake is already visible, using the frozen ConstraintSnapshot."""
    with _ROUTE_WORKERS_LOCK:
        if intake_id in _ROUTE_WORKERS:
            return
        _ROUTE_WORKERS.add(intake_id)

    bound = frozen_snapshot or airspace_store.resolve(scheduled_for=scheduled_for)

    def worker() -> None:
        try:
            with _ROUTE_SEMAPHORE:
                try:
                    result = _invoke_route_provider(
                        provider,
                        origin,
                        destination,
                        scheduled_for,
                        snapshot=bound,
                        intake_id=intake_id,
                    )
                except Exception as exc:  # never lose the intake
                    result = _unavailable_route(exc)
                    result["constraint_snapshot"] = bound.model_dump(mode="json")
                    result["airspace_check"] = {
                        **check_route_against_snapshot([], bound, scheduled_for=scheduled_for),
                        "passed_known_snapshot": None,
                        "verdict_label": f"几何路线未生成（{result.get('reason') or '未知原因'}）",
                    }
            record = intake_store.get(intake_id)
            used_snapshot = (
                ConstraintSnapshot.model_validate(result["constraint_snapshot"])
                if isinstance(result.get("constraint_snapshot"), dict)
                else bound
            )
            apply_route_update_to_intake(record, result, used_snapshot)
        except Exception:
            # The intake itself is already persisted; a failed refresh must not
            # surface as a turn error.
            pass
        finally:
            with _ROUTE_WORKERS_LOCK:
                _ROUTE_WORKERS.discard(intake_id)

    threading.Thread(target=worker, name=f"intake-route-{intake_id[:8]}", daemon=True).start()


class Toolset:
    SPECS = {
        "inspect_mission_plan": (
            "读取当前选中 AI 工单的实际规划记录，综合展示几何、绑定空域快照、沿实际航点采样的天气/风向、能耗与备降缺口；不借用演示数据，不重新调用外部服务。",
            NoArgs,
        ),
        "get_task_evidence": (
            "读取竞赛冻结任务的算法证据。main 为 S1-02 通过例，contrast 为 S1-01 拒绝例；"
            "含路线、余量剖面、独立校验与缺口，仅示例参数，不是当前业务工单或飞控结果。",
            EvidenceQuery,
        ),
        "search_project_docs": (
            "查找项目规则、接口和操作说明，返回原文、文件位置和内容版本。",
            DocumentQuery,
        ),
        "get_flight_status": ("读取当前界面遥测、时间和来源，不作适航或备降安全判断。", NoArgs),
        "get_task_status": ("查询联调面板选中的本地合成任务，读取规划、回执和独立执行状态。", NoArgs),
        "list_events": ("读取本次页面会话的事件记录并按类型统计。", NoArgs),
        "list_places": (
            "仅列出 v0 虚拟场景的 6 个 ENU 登记点（医疗物资中转站、北区应急中心等），"
            "与真实地名无关。用户提到真实城市/学校/机场等名称时必须用 resolve_real_place，"
            "不要用本工具答真实地点。",
            NoArgs,
        ),
        "update_task_draft": ("仅更新用户明确提供的任务草稿字段；可多轮补充，缺失值保留未知。", DraftUpdate),
        "plan_task_preview": ("用现有几何A*计算草稿路线预览；不验证能量/备降，不下发。", NoArgs),
        "inspect_terrain_risk": (
            "检测最近地形变化包围框与当前基线航线的平面交叠，区分已过/剩余航段。",
            NoArgs,
        ),
        "get_capabilities": ("说明实际接入能力、待连接项和下发边界。", NoArgs),
        "resolve_real_place": (
            "把地点名解析为坐标；解析不出就标 unresolved，绝不猜坐标。",
            PlaceQuery,
        ),
        "get_weather_forecast": (
            "按经纬度和时间取 Open-Meteo 逐时预报（温度/湿度/风速/阵风/降水/能见度）；"
            "不可达时返回 unavailable，不填任何数字。",
            ForecastQuery,
        ),
        "get_airspace_zones": (
            "读取当前工作区 WGS84 空域约束快照（若在 ENU 演示模式且未载入真实区域，则说明 v0 草稿边界且不混用）。",
            NoArgs,
        ),
        "inspect_airspace_constraints": (
            "读取当前任务/工单或地图规划路线绑定的空域约束快照、逐航段冲突复核记录、重算前后路线对比与未判定缺口。"
            "用户问'有没有考虑禁飞区''用了哪些限制区''原路线为什么冲突''空域核对了吗'时必须调用本工具。",
            AirspaceAuditQuery,
        ),
        "get_intake_overview": (
            "给图表用的真实工单数据：最近工单的航线状态计数、载荷、以及最新一条航线的"
            "累计距离采样（最多12点）。用户要求画折线/饼图/柱状图且与 AI 工单相关时调用。",
            NoArgs,
        ),
        "create_task_intake": (
            "把用户原话、起终点、时间与已收集的证据落成一张任务工单；只记录，不下发、不执行。",
            IntakeCreate,
        ),
        "assess_route_environment": (
            "对整条航线做环境判定：沿航线等弧长采样、按预计到达时刻取模式预报，"
            "返回 verdict（pass/degraded/blocked/unknown）、逐因素矩阵、缺口清单和来源时间。"
            "用户问'这条线能不能飞''中间天气怎么样''有什么风险'时必须先调用本工具；"
            "只回答了端点、没有整条航线的结论，视为未完成。"
            "不得用 get_weather_forecast 代替本工具回答航线级问题。",
            EnvQuery,
        ),
        "explain_verdict": (
            "解释一个已有环境判定的由来：哪一段、哪个因素、阈值来自哪里、为什么是这个 verdict。"
            "只能解释 evidence_id 对应的既有结果，不得重新计算或改动结论。"
            "用户问'为什么判定为 blocked/degraded''哪一段有问题'时调用。",
            VerdictQuery,
        ),
        "list_environment_gaps": (
            "列出当前环境判定里'没有判定'的项目及原因、以及补什么才能判定。"
            "用户问'还有什么没考虑''你确定吗''有没有漏掉什么'时调用。"
            "回答里必须逐条转述，不得概括成'基本都覆盖了'。",
            GapsQuery,
        ),
        "compare_departure_times": (
            "比较同一条航线在不同起飞时刻的环境结论，回答'晚点起飞会不会好一点'。"
            "只在用户明确提出改时间、或当前 verdict 为 blocked 且用户问'什么时候能飞'时调用。"
            "不得据此推荐'最佳起飞时间'——只能给出各时刻的判定与差异，选择权在用户。",
            TimeWindowQuery,
        ),
        "check_landing_sites": (
            "检查是否已有运营方确认的起降点台账。没有台账时返回 unavailable，"
            "不得据此判断'不能飞'，只能说明'该项未判定'。"
            "道路和 OSM 标签只是线索。用户问'出问题能落哪''有没有备降'时调用。",
            LandingQuery,
        ),
        "audit_route_provenance": (
            "返回结论的数据血统：障碍快照 id 与抓取时间、气象模型与抓取时间、"
            "投影方式、建筑高度已知比例、数据分级。用户问'数据哪来的''是不是实时'时调用。",
            ProvenanceQuery,
        ),
    }

    def __init__(
        self,
        turn: Turn,
        read_dispatch_task: Callable[[str], dict] | None = None,
        real_route_provider: Callable[..., dict] | None = None,
        route_background: bool = True,
        require_confirmation: bool = False,
        actor_id: str = "local",
        checkpoint: Callable[[], None] = lambda: None,
        read_live_telemetry: Callable[[], LiveTelemetry | None] | None = None,
    ):
        self.turn = turn
        self.read_dispatch_task = read_dispatch_task
        self.real_route_provider = real_route_provider
        self.route_background = route_background
        self.require_confirmation = require_confirmation
        self.actor_id = actor_id
        self.checkpoint = checkpoint
        self.read_live_telemetry = read_live_telemetry
        self.tool_cache: dict[str, dict] = {}
        self.draft = turn.draft
        self.results: dict[str, dict] = {}
        self.place_results: list[dict] = []
        self.terminal = False

    @classmethod
    def schemas(cls, *, enable_env_tools: bool = True):
        specs = (
            cls.SPECS
            if enable_env_tools
            else {key: value for key, value in cls.SPECS.items() if key not in ENV_TOOL_NAMES}
        )
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": schema.model_json_schema(),
                },
            }
            for name, (description, schema) in specs.items()
        ]

    def execute(self, name: str, arguments: dict):
        if name not in self.SPECS:
            raise ValueError("Tool is not available")
        # The same tool+args called again in one turn must not re-hit the
        # network. Repeated weather calls used to cost 8 s each and pushed the
        # turn into the step limit without producing an answer.
        cache_key = ""
        if name not in {
            "create_task_intake",
            "update_task_draft",
            "get_flight_status",
            "get_task_status",
            "inspect_airspace_constraints",
        }:
            cache_key = name + "|" + json.dumps(arguments, sort_keys=True, ensure_ascii=False)
            if name == "plan_task_preview":
                cache_key += "|" + (draft_digest(self.draft) if self.draft else "no-draft")
            if cache_key in self.tool_cache:
                self.results[name] = self.tool_cache[cache_key]
                return {
                    **self.tool_cache[cache_key],
                    "_cached": True,
                    "_cache_note": "本轮已用相同参数调用过，直接返回上次结果，不要重复调用。",
                }
        validated = self.SPECS[name][1].model_validate(arguments)
        result = getattr(self, name)(validated)
        self.results[name] = result
        if cache_key:
            self.tool_cache[cache_key] = result
        return result

    def search_project_docs(self, args: DocumentQuery):
        excerpts = search(args.query)
        return {
            "status": "ok" if excerpts else "no_match",
            "source": "仓库项目文档",
            "retrievers": sorted({item.get("retriever", "keyword") for item in excerpts}),
            "excerpts": excerpts,
        }

    def get_flight_status(self, _args):
        ctx = self.turn.context
        if ctx.telemetry_mode == "planning":
            route = ctx.active_route
            return {
                "telemetry_mode": "planning",
                "source": "当前页面规划上下文（未连接执行遥测）",
                "task_id": ctx.task_id,
                "sampled_at": ctx.sampled_at.isoformat(),
                "stale": False,
                "telemetry": None,
                "progress_pct": None,
                "route": route.model_dump(mode="json") if route else None,
                "reason": f"当前路线 {route.route_id if route else '尚未生成'}；仅规划参考，当前没有对应任务的电量、位置或执行进度。",
            }
        if ctx.telemetry_mode == "live":
            frame = self.read_live_telemetry() if self.read_live_telemetry else ctx.live_telemetry
            age = frame.age_seconds() if frame else None
            return {
                "telemetry_mode": "live",
                "evidence_origin": "server_file" if self.read_live_telemetry else "browser_context",
                "source": frame.source if frame else "M4 遥测",
                "sampled_at": frame.captured_at.isoformat() if frame else None,
                "age_s": round(age, 1) if age is not None else None,
                "stale": age is None or not -STALE_SECONDS <= age < STALE_SECONDS,
                "is_simulated": frame.is_simulated if frame else None,
                "task_id": frame.task_id if frame else None,
                "telemetry": frame.model_dump(mode="json") if frame else None,
            }
        assert ctx.telemetry is not None
        age = (datetime.now(UTC) - ctx.sampled_at).total_seconds()
        return {
            "source": "浏览器演示遥测快照；非飞控数据",
            "sampled_at": ctx.sampled_at.isoformat(),
            "age_s": round(age, 1),
            "stale": age > 15 or age < -5,
            "is_simulated": True,
            "task_id": ctx.task_id,
            "progress_pct": round(ctx.progress * 100, 1),
            "telemetry": ctx.telemetry.model_dump(),
            "point": point_at(baseline(), ctx.progress),
        }

    def get_task_evidence(self, args: EvidenceQuery):
        return read_task_evidence(args.case)

    def get_task_status(self, _args):
        ctx = self.turn.context
        if ctx.selected_intake_id:
            try:
                item = intake_store.get(ctx.selected_intake_id)
            except (KeyError, ValueError):
                return {"status": "unavailable", "reason": "当前选中工单不可用，请重新选择。"}
            route = item.get("real_route") or {}
            airspace_check = item.get("airspace_check") or route.get("airspace_check") or {}
            verdict_suffix = (
                f"（{airspace_check['verdict_label']}）" if airspace_check.get("verdict_label") else ""
            )
            label = {"ok": "工单几何路线已生成", "pending": "工单路线计算中"}.get(
                route.get("status"), "工单路线尚不可用"
            )
            return {
                "status": "ok",
                "source": "服务端工单记录",
                "task_id": ctx.selected_intake_id,
                "scenario_id": "WGS84",
                "label": label,
                "planning_label": label + verdict_suffix,
                "execution_label": "仅工单，未下发",
                "ack_accepted": None,
                "plan_version": route.get("route_id"),
                "constraint_snapshot_id": (item.get("constraint_snapshot") or {}).get("snapshot_id"),
                "constraint_digest": (item.get("constraint_snapshot") or {}).get("digest"),
                "reason": label + verdict_suffix + "；未下发飞控，不能推断配送或备降完成。",
            }
        if ctx.telemetry_mode == "planning":
            return {"status": "not_selected", "reason": "当前是几何规划预览，没有对应的执行任务或回执。"}
        selected = self.turn.context.selected_task_id
        if selected is None:
            return {"status": "not_selected", "reason": "请先在「本地任务联调」选择要查询的任务。"}
        if self.read_dispatch_task is None:
            return {"status": "unavailable", "reason": "本地任务联调服务暂不可用。"}

        task_id = str(selected)
        try:
            task = self.read_dispatch_task(task_id)
        except KeyError:
            return {"status": "unknown_task", "reason": "找不到当前选中的任务，请在联调面板重新选择。"}

        result = task["result"] or {}
        command = result.get("command")
        execution = task["execution"]
        ack = result.get("ack")

        def matches_command(record):
            return (
                command
                and record
                and (record["task_id"], record["command_id"], record["plan_version"])
                == (
                    task_id,
                    command["command_id"],
                    command["plan_version"],
                )
            )

        ack_accepted = ack["accepted"] if matches_command(ack) else None
        execution_state = execution["state"] if matches_command(execution) else None
        planning_status = str(task["planning_status"])
        planning_label = {
            "awaiting_confirmation": "等待确认",
            "waiting_ack": "等待执行回执，结果待对账",
            "acknowledged": "执行端已受理",
            "blocked": "独立校验拦截",
            "rejected": "执行端拒绝",
            "reconcile_required": "待恢复任务审计",
            "error": "规划流程异常",
        }.get(planning_status, "规划处理中")
        execution_label = {
            "accepted": "执行端已接收",
            "executing": "合成执行中",
            "completed": "合成执行完成",
            "recovering": "待人工对账",
            "rejected": "执行端拒绝",
            "failed": "合成执行失败",
        }.get(execution_state)
        has_execution = execution_label and (
            ack_accepted is True or execution_state in {"failed", "recovering"}
        )

        return {
            "status": "ok",
            "source": "本地任务联调 · 合成执行",
            "task_id": task_id,
            "scenario_id": task["scenario_id"],
            "planning_status": planning_status,
            "planning_label": planning_label,
            "execution_state": execution_state,
            "execution_label": execution_label,
            "ack_accepted": ack_accepted,
            "plan_version": command["plan_version"] if command else None,
            "command_id": command["command_id"] if command else None,
            "label": execution_label if has_execution else planning_label,
            "reason": (execution.get("reason") if has_execution else task["reason"]) or None,
        }

    def list_events(self, _args):
        events = self.turn.context.events
        return {
            "source": "当前浏览器会话事件；不是完整M3审计或飞行记录",
            "total": len(events),
            "warnings": sum(e.type == "warning" for e in events),
            "events": [e.model_dump() for e in events[:30]],
            "is_simulated": True,
        }

    def list_places(self, _args):
        return {
            "source": "仓库虚拟S1-01场景与landing_sites.geojson",
            "crs": "local ENU / m",
            "places": [{"name": name, "point": list(point)} for name, point in PLACES.items()],
            "aliases": ALIASES,
        }

    def update_task_draft(self, args: DraftUpdate):
        previous = self.draft or Draft()
        self.draft = Draft.model_validate({**previous.model_dump(), **args.model_dump(exclude_unset=True)})
        if self.draft != previous:
            self.results.pop("plan_task_preview", None)
        missing = [
            key
            for key in ("origin", "destination", "payload_kg")
            if getattr(self.draft, key) is None or getattr(self.draft, key) == ""
        ]
        unresolved = [
            name
            for name in (self.draft.origin, self.draft.destination)
            if name and resolve_place(name) is None
        ]
        return {
            "source": "用户输入形成的待确认草稿",
            "draft": self.draft.model_dump(),
            "digest": draft_digest(self.draft),
            "missing_fields": missing,
            "unresolved_places": unresolved,
            "requires_confirmation": True,
            "dispatch_enabled": False,
        }

    def plan_task_preview(self, _args):
        if self.draft is None:
            return {"status": "blocked", "reason": "请先创建任务草稿。"}
        review = self.update_task_draft(DraftUpdate())
        if review["missing_fields"] or review["unresolved_places"]:
            return {"status": "blocked", "reason": "请补全载荷和起终点，并使用已登记地点。", "review": review}
        start, destination = resolve_place(self.draft.origin), resolve_place(self.draft.destination)
        if start == destination:
            return {"status": "blocked", "reason": "起点与终点相同，请重新选择。"}
        scene = load_scene()
        grid = build_grid(scene.obstacles + [zone.polygon for zone in scene.zones.values()])
        route = plan(grid, start, destination, max_expand=90000)
        if not route.found or route.snapped:
            return {
                "status": "blocked",
                "reason": "现有静态约束下无可用几何路线，或端点需要人工调整。",
                "snapped": route.snapped,
            }
        return {
            "status": "geometry_only",
            "source": "planner.astar.plan / 现有仓库算法实际计算",
            "route_id": "preview-" + draft_digest(self.draft)[:12],
            "draft_digest": draft_digest(self.draft),
            "waypoints": route.waypoints,
            "length_m": round(route.length_m, 1),
            "waypoint_count": len(route.waypoints),
            "algorithm": "astar_static",
            "checks": {
                "energy": "pending_vehicle_parameters",
                "diversion_reachability": "not_implemented_in_search",
                "dynamic_constraints": "not_checked",
                "flight_execution": "not_connected",
            },
            "linked_checks": {
                "time_varying_nfz": "planner.diversion.hard_constraint_report",
                "weather_and_obstacles": "assess_route_environment",
                "scope_note": (
                    "本预览只做 v0 场景的静态几何，不代替另外两条验收。"
                    "at_s>0 限制区由 planner.diversion.hard_constraint_report 按到达时刻复算，"
                    "并已接入 eval 规划验收；天气与障碍物只看 assess_route_environment（WGS84）。"
                    "缺数据不得判通过。两条都不构成飞行批准。"
                ),
            },
            "assumptions": "保守地将场景全部限制区作为静态障碍；地形、能耗、动态时效未加入这条预览搜索。",
            "dispatch_enabled": False,
            "is_simulated": True,
        }

    def inspect_terrain_risk(self, _args):
        if self.turn.context.telemetry_mode == "planning":
            return {
                "status": "no_change_data",
                "source": "当前规划上下文",
                "reason": "当前规划路线没有绑定同坐标与高度基准的地形快照；未借用 S1-01 演示地形分析。",
                "dispatch_enabled": False,
            }
        if self.turn.context.telemetry_mode == "live":
            return {
                "status": "no_change_data",
                "source": "M4 遥测",
                "reason": "实时遥测尚未关联可用于地形比对的航线。",
                "dispatch_enabled": False,
            }
        change = self.turn.context.terrain
        if not change or not change.count or not change.bounds:
            return {
                "status": "no_change_data",
                "source": "页面地形变更记录",
                "reason": "当前没有可分析的显著地形变化，不能据此判断航线安全。",
                "dispatch_enabled": False,
            }
        route = baseline()
        total = polyline_length(route)
        cursor, travelled = total * self.turn.context.progress, 0.0
        affected, remaining = [], []
        for index, (a, b) in enumerate(zip(route, route[1:], strict=False)):
            length = math.dist(a, b)
            hit = segment_box(a, b, change.bounds)
            if hit is not None:
                interval = [round(travelled + hit[0] * length, 1), round(travelled + hit[1] * length, 1)]
                affected.append({"segment": index, "distance_m": interval})
                if interval[1] >= cursor:
                    remaining.append(index)
            travelled += length
        age = (datetime.now(UTC) - change.capturedAt).total_seconds()
        return {
            "status": "review_required"
            if remaining
            else "past_segments_only"
            if affected
            else "outside_footprint",
            "source": "DEM变化包围框与S1-01航线逐线段闭区间几何求交",
            "terrain_revision": change.revision,
            "terrain_source": change.source,
            "captured_at": change.capturedAt.isoformat(),
            "data_age_s": round(age, 1),
            "stale": age > 120 or age < -5,
            "route_id": "S1-01-baseline",
            "affected_segments": affected,
            "remaining_segment_count": len(remaining),
            "max_delta_m": change.maxDelta,
            "bounds": change.bounds.model_dump(),
            "focus_point": [
                (change.bounds.minX + change.bounds.maxX) / 2,
                (change.bounds.minY + change.bounds.maxY) / 2,
            ],
            "limitation": "仅包围框平面交叠，可能包含未变化区域；未计算垂向净空、能量和备降可达，不能判定实际碰撞或安全。",
            "dispatch_enabled": False,
        }

    def get_capabilities(self, _args):
        return {**CAPABILITIES, "dispatch_enabled": False, "is_simulated": True}

    def resolve_real_place(self, args: PlaceQuery):
        result = evidence.resolve_place(args.name, local_places=PLACES, aliases=ALIASES)
        self.place_results.append(result)
        return result

    def get_weather_forecast(self, args: ForecastQuery):
        return evidence.fetch_weather_forecast(args.latitude, args.longitude, args.scheduled_for)

    def get_airspace_zones(self, _args):
        ctx = self.turn.context
        active = (
            airspace_store.resolve(snapshot_id=ctx.airspace_snapshot_id)
            if ctx.airspace_snapshot_id
            else airspace_store.get_active()
        )
        if active is not None or ctx.telemetry_mode == "planning":
            snap = active or airspace_store.get_active_or_unloaded()
            return {
                "status": snap.source_status,
                "snapshot_id": snap.snapshot_id,
                "version": snap.version,
                "digest": snap.digest,
                "crs": snap.crs,
                "is_simulated": snap.is_simulated,
                "enforced_zone_count": snap.enforced_zone_count,
                "total_zone_count": snap.total_zone_count,
                "zone_buffer_m": snap.zone_buffer_m,
                "buffer_source": snap.buffer_source,
                "zones": [
                    {
                        "id": z.id,
                        "name": z.name,
                        "kind": z.kind,
                        "source": z.source,
                        "source_kind": z.source_kind,
                        "is_simulated": z.is_simulated,
                        "participates_in_avoidance": z.participates_in_avoidance,
                        "buffer_m": z.buffer_m,
                        "avoidance_rule": z.avoidance_rule,
                    }
                    for z in snap.zones
                ],
                "source": (
                    "大疆 FlySafe 厂商地理围栏参考"
                    if snap.source_status == "manufacturer_reference"
                    else "服务端 WGS84 空域约束快照（不会混入本地 ENU v0 草稿）"
                ),
                "note": (
                    "数据源是大疆 FlySafe 厂商地理围栏参考，不是法定空域，不是 UOM / 国家地图官网 / 天地图，"
                    "也不代表获准飞行。通过检查只表示通过本次已知区域检查。"
                    if snap.source_status == "manufacturer_reference"
                    else (
                        f"大疆 FlySafe 不可用或为空（{snap.failure_reason or '未知'}）。"
                        "空域未知，不是放行，未编造围栏。"
                        if snap.source_status == "unavailable"
                        else (
                            "仅代表当前工作区已知导入/演练区域，未接入官方 UOM/NOTAM；"
                            "本地 ENU 演示区域 scenarios/v0/zones.geojson 已隔离，不套用于真实 WGS84 地点。"
                        )
                    )
                ),
            }
        return evidence.list_airspace_zones()

    def inspect_airspace_constraints(self, args: AirspaceAuditQuery):
        ctx = self.turn.context
        target_intake_id = args.intake_id or ctx.selected_intake_id
        if target_intake_id:
            try:
                item = intake_store.get(target_intake_id)
            except (KeyError, ValueError):
                return {
                    "status": "unavailable",
                    "source": "服务端工单记录",
                    "reason": f"找不到工单 {target_intake_id}，无法读取其空域约束快照。",
                    "dispatch_enabled": False,
                }
            route = item.get("real_route") or {}
            snap_dict = item.get("constraint_snapshot") or (route.get("planning_result") or {}).get(
                "constraint_snapshot"
            )
            check = item.get("airspace_check") or route.get("airspace_check")
            if check is None:
                check = check_route_against_snapshot(
                    route.get("waypoints") or [],
                    snap_dict,
                    scheduled_for=item.get("scheduled_for"),
                )
            active_snap = (
                airspace_store.resolve(
                    snapshot_id=ctx.airspace_snapshot_id, scheduled_for=item.get("scheduled_for")
                )
                if ctx.airspace_snapshot_id
                else airspace_store.get_active()
            )
            stale_against_workspace = bool(
                active_snap is not None
                and snap_dict is not None
                and active_snap.digest != snap_dict.get("digest")
            )
            live_workspace_recheck = (
                check_route_against_snapshot(
                    route.get("waypoints") or [],
                    active_snap,
                    scheduled_for=item.get("scheduled_for"),
                )
                if stale_against_workspace and (route.get("waypoints") or [])
                else None
            )
            history = item.get("route_history") or []
            latest_prev = history[-1] if history else None
            return {
                "status": "ok",
                "scope": "intake",
                "source": "服务端工单绑定约束快照与独立连续航段复核",
                "intake_id": item["intake_id"],
                "origin": (item.get("origin") or {}).get("name"),
                "destination": (item.get("destination") or {}).get("name"),
                "route_status": route.get("status") or "not_planned",
                "route_id": route.get("route_id") or (route.get("route") or {}).get("id"),
                "route_version": route.get("version_label")
                or ("v1" if route.get("status") == "ok" else None),
                "waypoint_count": len(route.get("waypoints") or []),
                "length_m": route.get("length_m"),
                "route_changed": route.get("route_changed"),
                "constraint_snapshot": snap_dict,
                "airspace_check": check,
                "stale_against_workspace": stale_against_workspace,
                "workspace_active_snapshot_id": active_snap.snapshot_id if active_snap else None,
                "workspace_active_snapshot_digest": active_snap.digest if active_snap else None,
                "workspace_recheck": live_workspace_recheck,
                "previous_version": latest_prev,
                "honesty_boundary": {
                    "known_zone_avoidance": "已执行二维全高度保守避让与独立逐航段复核"
                    if snap_dict and snap_dict.get("enforced_zone_count", 0) > 0
                    else "当前绑定快照无生效限制区或尚未绑定快照",
                    "simulation_demo": (
                        "包含演练标识区域，仅作确定性演示复核"
                        if snap_dict and snap_dict.get("is_simulated")
                        else (
                            "大疆 FlySafe 厂商地理围栏参考，不是法定空域或飞行批准"
                            if snap_dict and snap_dict.get("source_status") == "manufacturer_reference"
                            else "用户导入坐标边界（未经官方真伪核验）"
                        )
                    ),
                    "official_airspace_verification": "未接入官方 UOM / NOTAM 实时空域核验",
                    "flight_execution": "未连接真实飞控执行（dispatch_enabled=false）",
                },
                "dispatch_enabled": False,
                "operationally_approved": False,
            }

        if ctx.active_route and ctx.active_route.frame == "WGS84":
            snap_id = ctx.active_route.constraint_snapshot_id or ctx.airspace_snapshot_id
            snap = airspace_store.resolve(snapshot_id=snap_id)
            check = check_route_against_snapshot(ctx.active_route.waypoints, snap)
            active_ws = (
                airspace_store.resolve(snapshot_id=ctx.airspace_snapshot_id)
                if ctx.airspace_snapshot_id
                else airspace_store.get_active()
            )
            stale = bool(active_ws and active_ws.digest != snap.digest)
            ws_recheck = (
                check_route_against_snapshot(ctx.active_route.waypoints, active_ws) if stale else None
            )
            return {
                "status": "ok",
                "scope": "active_route",
                "source": "当前地图规划航线与服务端约束快照实时核查",
                "intake_id": ctx.active_route.task_id,
                "route_status": "ok",
                "route_id": ctx.active_route.route_id,
                "route_version": "current",
                "waypoint_count": len(ctx.active_route.waypoints),
                "length_m": None,
                "constraint_snapshot": snap.model_dump(mode="json"),
                "airspace_check": check,
                "stale_against_workspace": stale,
                "workspace_active_snapshot_id": active_ws.snapshot_id if active_ws else None,
                "workspace_active_snapshot_digest": active_ws.digest if active_ws else None,
                "workspace_recheck": ws_recheck,
                "previous_version": None,
                "honesty_boundary": {
                    "known_zone_avoidance": "对当前绑定快照做了逐航段闭区间几何复核",
                    "simulation_demo": (
                        "大疆 FlySafe 厂商地理围栏参考，不是法定空域或飞行批准"
                        if snap.source_status == "manufacturer_reference"
                        else "演练/导入参考图层，非官方许可"
                    ),
                    "official_airspace_verification": "未接入官方 UOM / NOTAM 实时空域核验",
                    "flight_execution": "未连接真实飞控执行（dispatch_enabled=false）",
                },
                "dispatch_enabled": False,
                "operationally_approved": False,
            }

        snap = (
            airspace_store.resolve(snapshot_id=ctx.airspace_snapshot_id)
            if ctx.airspace_snapshot_id
            else airspace_store.get_active_or_unloaded()
        )
        check = check_route_against_snapshot([], snap)
        return {
            "status": "ok",
            "scope": "workspace_snapshot",
            "source": "服务端工作区空域约束快照（当前尚未选中具体 WGS84 航线或工单）",
            "intake_id": None,
            "route_status": "not_selected",
            "route_id": None,
            "route_version": None,
            "waypoint_count": 0,
            "length_m": None,
            "constraint_snapshot": snap.model_dump(mode="json"),
            "airspace_check": check,
            "stale_against_workspace": False,
            "workspace_recheck": None,
            "previous_version": None,
            "honesty_boundary": {
                "known_zone_avoidance": "尚未选定真实航线；新建工单或点击计算航线时将自动冻结并应用当前快照",
                "simulation_demo": "本地 ENU 演示场景与真实 WGS84 空域快照严格隔离，禁止混用",
                "official_airspace_verification": "未接入官方 UOM / NOTAM 实时空域核验",
                "flight_execution": "未连接真实飞控执行（dispatch_enabled=false）",
            },
            "dispatch_enabled": False,
            "operationally_approved": False,
        }

    def get_intake_overview(self, _args):
        """Real series for charts: status counts, payloads, latest route profile."""
        from planner.georef import distance_m

        items = intake_store.list(limit=12)
        counts = {"航线已生成": 0, "后台计算中": 0, "未生成": 0}
        payloads: list[dict] = []
        latest_route = None
        for item in items:
            route = item.get("real_route") or {}
            status = route.get("status")
            counts["航线已生成" if status == "ok" else "后台计算中" if status == "pending" else "未生成"] += 1
            if item.get("payload_kg") is not None and len(payloads) < 8:
                origin = (item.get("origin") or {}).get("name", "起点")[:8]
                destination = (item.get("destination") or {}).get("name", "终点")[:8]
                payloads.append({"label": f"{origin}→{destination}", "value": float(item["payload_kg"])})
            if latest_route is None and status == "ok":
                waypoints = route.get("waypoints") or []
                if len(waypoints) >= 2:
                    cumulative, total = [], 0.0
                    previous = (waypoints[0].get("lng"), waypoints[0].get("lat"))
                    for index, point in enumerate(waypoints):
                        current = (point.get("lng"), point.get("lat"))
                        if index:
                            total += distance_m(previous, current)
                        previous = current
                        cumulative.append(total)
                    step = max(1, math.ceil((len(cumulative) - 1) / 11))
                    sampled = list(range(0, len(cumulative), step))
                    if sampled[-1] != len(cumulative) - 1:
                        sampled.append(len(cumulative) - 1)
                    latest_route = {
                        "origin": (item.get("origin") or {}).get("name"),
                        "destination": (item.get("destination") or {}).get("name"),
                        "length_km": round(total / 1000, 2),
                        "waypoint_count": len(cumulative),
                        "profile": [
                            {"label": str(index + 1), "value": round(cumulative[index] / 1000, 2)}
                            for index in sampled
                        ][:12],
                    }
        return {
            "status": "ok",
            "source": "logs/intakes 本机工单文件",
            "count": len(items),
            "scope": "最近 12 张工单",
            "status_counts": [{"label": label, "value": value} for label, value in counts.items()],
            "payloads": payloads,
            "latest_route": latest_route,
            "note": "航线为 OSM 建筑足迹的几何避障结果，非飞行实测；可直接用于 chart 代码块。",
        }

    def create_task_intake(self, args: IntakeCreate):
        confirmation = self.turn.confirmation
        explicit_confirm = not self.require_confirmation or confirmation is not None
        if confirmation is not None:
            args = confirmation.as_input(self.turn.text)
        stated = evidence.extract_confirmations(args.text)
        if stated:
            args = args.model_copy(
                update={
                    key: value for key, value in stated.items() if getattr(args, key) in (None, False, "")
                }
            )
        normalized, normalization_note = normalize_scheduled_for(args.scheduled_for)
        if normalized is None:
            parsed, parsed_note = evidence.parse_schedule(args.text)
            args = args.model_copy(
                update={
                    "scheduled_for": parsed,
                    "schedule_note": (
                        parsed_note + "（规则解析，待用户确认）" if parsed else "未识别到时间，需用户补充"
                    ),
                }
            )
        else:
            merged_note = "；".join(part for part in (args.schedule_note, normalization_note) if part)
            args = args.model_copy(update={"scheduled_for": normalized, "schedule_note": merged_note})
        fingerprint = hashlib.sha256(
            json.dumps(
                args.model_dump(
                    include={
                        "origin",
                        "destination",
                        "origin_point",
                        "destination_point",
                        "scheduled_for",
                        "payload_kg",
                        "priority",
                    }
                ),
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        operation_id = confirmation.confirmation_id if confirmation else self.turn.request_id
        request_key = f"{self.actor_id}:{operation_id}"
        if explicit_confirm:
            self.checkpoint()
            saved = intake_store.replay(request_key, fingerprint)
            if saved is not None:
                self.terminal = True
                return self._created_result(saved)
        places = {item["name"]: item for item in self.place_results}

        def locate(name, point):
            if confirmation is not None:
                return {
                    "name": name,
                    "point": point,
                    "crs": "EPSG:4326",
                    "status": "ok",
                    "source": "用户确认卡",
                    "is_simulated": False,
                }
            return places.get(name) or evidence.resolve_place(name, local_places=PLACES, aliases=ALIASES)

        origin = locate(args.origin, args.origin_point)
        destination = locate(args.destination, args.destination_point)
        # A map pin that is hundreds of km away from the named place is a stale
        # selection, not a preference. Never write it into the intake; ask with
        # two explicit options instead of silently choosing one.
        from planner.georef import distance_m

        conflicts = {}
        for field, point, item, label in (
            ("origin", args.origin_point, origin, "起点"),
            ("destination", args.destination_point, destination, "终点"),
        ):
            if not point or item.get("crs") != "EPSG:4326" or not item.get("point"):
                continue
            gap = distance_m(tuple(point), tuple(item["point"]))
            if gap > 50_000:
                conflicts[field] = gap
                conflicts[f"{field}_question"] = {
                    "field": field,
                    "question": (
                        f"你在地图上点的{label}距「{item['name']}」约 {gap / 1000:.0f} km，明显不是同一地点。"
                        f"是用地名坐标，还是坚持用点选坐标并改名？"
                    ),
                    "options": [
                        {
                            "label": f"A · 用「{item['name']}」的坐标",
                            "value": (
                                f"用A方案：{label}采用「{item['name']}」的地图解析坐标 "
                                f"{item['point'][0]:.6f},{item['point'][1]:.6f}，重新建单"
                            ),
                        },
                        {
                            "label": "B · 用我点的坐标",
                            "value": (
                                f"用B方案：保留我在地图上点的{label}坐标，"
                                "但请先告诉我这两个点附近的实际地点名称"
                            ),
                        },
                    ],
                }

        for field, point in (("origin", args.origin_point), ("destination", args.destination_point)):
            if not point or field in conflicts:
                continue
            current = origin if field == "origin" else destination
            updated = {
                **current,
                "point": point,
                "crs": "EPSG:4326",
                "source": "用户在地图上确认",
                "status": "ok",
                "is_simulated": False,
            }
            if field == "origin":
                origin = updated
            else:
                destination = updated

        map_pins, questions = [], []
        for field, item, label in (("origin", origin, "起点"), ("destination", destination, "终点")):
            pin = {
                "field": field,
                "name": item["name"],
                "point": item.get("point"),
                "crs": item.get("crs"),
                "source": item.get("source"),
                "address": item.get("address", ""),
                "candidates": item.get("candidates", []),
                "confirmed": args.places_confirmed,
                "note": (
                    "已在地图上定位，请确认是不是这个位置"
                    if item.get("point")
                    else "暂时无法自动定位，请在地图上手动选点（不猜坐标）"
                ),
            }
            map_pins.append(pin)
            if field in conflicts:
                # Conflict already carries a clearer A/B question; do not ask
                # the generic "is this the place?" on top of it.
                continue
            if not explicit_confirm or not item.get("point"):
                candidates = [
                    candidate for candidate in (item.get("candidates") or []) if candidate.get("point")
                ]
                if not item.get("point") and candidates:
                    question = {
                        "field": field,
                        "question": f"{label}「{item['name']}」有 {len(candidates)} 个候选，选一个：",
                        "map_pin": pin,
                        "options": [
                            {
                                "label": candidate["name"],
                                "value": (
                                    f"选{candidate['name']}，坐标 "
                                    f"{candidate['point'][0]:.6f},{candidate['point'][1]:.6f}"
                                ),
                            }
                            for candidate in candidates[:4]
                        ],
                    }
                else:
                    question = {
                        "field": field,
                        "question": (
                            f"{label}：{item['name']}（{item['point'][0]:.6f}, {item['point'][1]:.6f}）"
                            if item.get("point") and item.get("crs") == "EPSG:4326"
                            else f"{label}「{item['name']}」还没解析出坐标，请在地图上点选。"
                        ),
                        "map_pin": pin,
                    }
                questions.append(question)
        for field in ("origin", "destination"):
            if f"{field}_question" in conflicts:
                questions.append(conflicts[f"{field}_question"])

        if not explicit_confirm or not args.schedule_confirmed or not args.scheduled_for:
            if args.scheduled_for:
                schedule_question = {
                    "field": "scheduled_for",
                    "question": (
                        f"时间：{args.scheduled_for}"
                        + (f"（{args.schedule_note}）" if args.schedule_note else "")
                    ),
                    "current": args.scheduled_for,
                    "options": [
                        {"label": "A · 就用这个时间", "value": f"时间确认：{args.scheduled_for}，按这个建单"},
                        {"label": "B · 我重说时间", "value": "时间改成：____年__月__日 __:__"},
                    ],
                }
            else:
                schedule_question = {
                    "field": "scheduled_for",
                    "question": "还没识别到起飞时间。请给出年月日、时刻和时区（例如 2026-11-20 09:00 +08:00）。",
                    "current": None,
                }
            questions.insert(0, schedule_question)
        if args.payload_kg is None:
            questions.append(
                {"field": "payload_kg", "question": "这次运送的载荷重量是多少公斤？（0–100 kg）"}
            )
        if args.priority is None:
            questions.append({"field": "priority", "question": "优先级按 P1（应急/紧急）还是 P2（常规）？"})

        point = origin.get("point") if origin.get("crs") == "EPSG:4326" else None
        weather_feasibility = (
            {
                "status": "available_if_date_in_window",
                "latitude": point[1],
                "longitude": point[0],
                "note": (
                    "已拿到地图定位，可按指定时刻取 Open-Meteo 逐时预报（最多未来 16 天，"
                    f"含风速/温度/湿度/阵风/降水/能见度）；{args.scheduled_for} 需在窗口内。"
                ),
            }
            if point
            else {
                "status": "needs_map_pin",
                "note": "天气预报需要 WGS84 地图定位后才能取；请先在地图上确认起点位置。",
            }
        )

        if questions:
            lines = []
            if all(p.get("point") and p.get("crs") == "EPSG:4326" for p in (origin, destination)):
                lines.append(
                    f"已解析：{origin['name']}（{origin['point'][0]:.6f}, {origin['point'][1]:.6f}）"
                    f" → {destination['name']}（{destination['point'][0]:.6f}, {destination['point'][1]:.6f}）。"
                )
            else:
                lines.append("地点还没完全解析，先看下面的地图定位。")
            if args.scheduled_for:
                lines.append(
                    f"时间：{args.scheduled_for}"
                    + (f"（{args.schedule_note}）" if args.schedule_note else "")
                )
            facts = []
            if args.payload_kg is not None:
                facts.append(f"载荷 {args.payload_kg} kg")
            if args.priority:
                facts.append(args.priority)
            if facts:
                lines.append(" · ".join(facts))
            missing = [
                name
                for name, value in (("载荷", args.payload_kg), ("优先级", args.priority))
                if value is None
            ]
            if missing:
                lines.append("还差：" + "、".join(missing) + "，补一下即可建单。")
            lines.append("地点或时间不对，直接在下面卡片里改；没问题就点「确认并创建任务工单」。")
            self.terminal = True
            return {
                "status": "needs_clarification",
                "source": "信息未齐，先追问确认",
                "questions": questions,
                "map_pins": map_pins,
                "draft_values": {
                    "scheduled_for": args.scheduled_for,
                    "payload_kg": args.payload_kg,
                    "priority": args.priority,
                },
                "weather_feasibility": weather_feasibility,
                "summary": "\n".join(lines),
                "is_simulated": True,
                "dispatch_enabled": False,
            }

        def as_evidence(value):
            payload = {key: value.get(key) for key in ("name", "point", "crs", "source", "is_simulated")}
            payload["address"] = str(value.get("address") or "")
            return PlaceEvidence.model_validate(payload)

        weather = self.results.get("get_weather_forecast")
        if weather is not None:
            valid_time = weather.get("valid_for")
            same_time = False
            try:
                same_time = datetime.fromisoformat(
                    valid_time.replace("Z", "+00:00")
                ) == datetime.fromisoformat(args.scheduled_for)
            except (AttributeError, ValueError, TypeError):
                pass
            if weather.get("requested_point") != origin.get("point") or not same_time:
                weather = None
        if weather is not None:
            # Tool-level dedup marks repeats with _cached/_cache_note; strict
            # evidence models forbid extra keys.
            weather = {key: value for key, value in weather.items() if not key.startswith("_")}
        if weather is None:
            point = origin.get("point")
            if origin.get("crs") == "EPSG:4326" and point:
                weather = evidence.fetch_weather_forecast(point[1], point[0], args.scheduled_for)
            else:
                weather = evidence.unavailable_weather(
                    "起终点未解析为 WGS84 坐标，未取预报", args.scheduled_for
                )
        is_wgs84_mission = (
            origin.get("crs") == "EPSG:4326"
            and bool(origin.get("point"))
            and destination.get("crs") == "EPSG:4326"
            and bool(destination.get("point"))
        )
        frozen_snapshot: ConstraintSnapshot | None = None
        bound_airspace_check: dict | None = None
        if is_wgs84_mission:
            frozen_snapshot = airspace_store.resolve(
                snapshot_id=self.turn.context.airspace_snapshot_id,
                scheduled_for=args.scheduled_for,
            )
            from services.assistant.flysafe import refresh_planning_snapshot

            refreshed = refresh_planning_snapshot(
                list(origin["point"]),
                list(destination["point"]),
                zone_buffer_m=frozen_snapshot.zone_buffer_m,
                scheduled_for=args.scheduled_for,
                prior=frozen_snapshot,
            )
            if refreshed is not None:
                frozen_snapshot = refreshed
            airspace_store.save(frozen_snapshot, set_active=refreshed is not None)
            airspace = _airspace_evidence_from_snapshot(frozen_snapshot)
        else:
            airspace = self.results.get("get_airspace_zones") or evidence.list_airspace_zones()

        preview = self.results.get("plan_task_preview")
        route_preview = preview if preview and preview.get("status") == "geometry_only" else None

        real_route = None
        route_needs_background = False
        route_inputs: tuple[list[float], list[float], str | None] | None = None
        if is_wgs84_mission and list(origin["point"]) != list(destination["point"]):
            assert frozen_snapshot is not None
            provider = self.real_route_provider or real_route_for_intake
            route_inputs = (
                list(origin["point"]),
                list(destination["point"]),
                args.scheduled_for,
            )
            if self.route_background:
                real_route = {
                    "status": "pending",
                    "frame": "WGS84",
                    "version_index": 1,
                    "version_label": "v1",
                    "frozen_snapshot_id": frozen_snapshot.snapshot_id,
                    "frozen_snapshot_digest": frozen_snapshot.digest,
                    "waypoints": [],
                    "reason": None,
                    "requested_at": datetime.now(UTC).isoformat(),
                    "note": (
                        f"真实航线后台计算中（已冻结空域约束快照 {frozen_snapshot.snapshot_id}，"
                        f"{frozen_snapshot.enforced_zone_count} 个生效限制区）；完成后刷新工单查看。"
                    ),
                }
                bound_airspace_check = {
                    **check_route_against_snapshot([], frozen_snapshot, scheduled_for=args.scheduled_for),
                    "passed_known_snapshot": None,
                    "verdict_label": f"后台计算中（已冻结快照 {frozen_snapshot.snapshot_id}）",
                }
                route_needs_background = True
            else:
                try:
                    real_route = _invoke_route_provider(
                        provider,
                        *route_inputs,
                        snapshot=frozen_snapshot,
                    )
                except Exception as exc:  # a provider bug must not lose the intake
                    real_route = _unavailable_route(exc)
                    real_route["constraint_snapshot"] = frozen_snapshot.model_dump(mode="json")
                real_route.setdefault("version_index", 1)
                real_route.setdefault("version_label", "v1")
                bound_airspace_check = real_route.get("airspace_check") or check_route_against_snapshot(
                    real_route.get("waypoints") or [],
                    frozen_snapshot,
                    scheduled_for=args.scheduled_for,
                )
                real_route["airspace_check"] = bound_airspace_check
                airspace = _airspace_evidence_from_snapshot(frozen_snapshot, bound_airspace_check)

        warnings = [
            "天气预报不是实测值；风速未进入能耗或绕路计算。",
            (
                f"空域约束采用本次绑定快照 {frozen_snapshot.snapshot_id}（{frozen_snapshot.source_status}），"
                "未接入官方 UOM/NOTAM，不能作为获准飞行结论。"
                if frozen_snapshot is not None
                else "限制区来自仿真草稿，不是实测空域，不能用于安全判定。"
            ),
            "工单不是 core.models.Task，不进入 M3 状态机，不产生飞控指令。",
        ]
        if real_route and real_route.get("status") == "ok":
            warnings.append(
                "航线为公开地图建筑足迹 + 20 m 物理净空及本次已知限制区快照的几何避障结果；"
                "未接真实空域、地形、线缆，不代表获准飞行。"
            )
        elif real_route and real_route.get("status") == "pending":
            warnings.append(
                "真实航线在后台计算中（已冻结启动时刻的空域约束快照）；完成后刷新工单查看，失败会写明原因。"
            )
        elif real_route:
            warnings.append(
                "真实航线未生成：" + str(real_route.get("reason") or "未知原因") + "；未用直线代替。"
            )
        if weather.get("status") != "ok":
            warnings.append("气象数据未取到：" + str(weather.get("reason") or "未提供"))
        if route_preview is None and real_route is None:
            warnings.append("未生成几何路线预览：起终点不是可用 WGS84 坐标，未用直线代替。")
        for item in (origin, destination):
            if item.get("status") == "unresolved":
                warnings.append(f"地点「{item['name']}」未解析出坐标，未猜坐标。")

        record = TaskIntake.build(
            args,
            origin=as_evidence(origin),
            destination=as_evidence(destination),
            weather=WeatherEvidence.model_validate(weather),
            airspace=airspace,
            route_preview=route_preview,
            real_route=real_route,
            constraint_snapshot=frozen_snapshot.model_dump(mode="json") if frozen_snapshot else None,
            airspace_check=bound_airspace_check,
            warnings=warnings,
        )
        self.checkpoint()
        stored, newly_created = intake_store.create_once(record, request_key, fingerprint)
        if newly_created and route_needs_background and route_inputs is not None:
            _compute_route_in_background(
                stored["intake_id"],
                self.real_route_provider or real_route_for_intake,
                *route_inputs,
                frozen_snapshot=frozen_snapshot,
            )
        self.terminal = True
        return self._created_result(stored)

    @staticmethod
    def _created_result(stored):
        origin, destination = stored["origin"], stored["destination"]
        # Keep the model's view small: the full record (including the long
        # warnings list) lives in the store and the console reads it by id. If
        # warnings are returned here the model tends to paste all of them.
        public_record = {
            key: stored[key]
            for key in (
                "intake_id",
                "origin",
                "destination",
                "scheduled_for",
                "payload_kg",
                "priority",
                "real_route",
                "constraint_snapshot",
                "airspace_check",
                "is_simulated",
                "dispatch_enabled",
            )
            if key in stored
        }
        return {
            "status": "created",
            "source": "自然语言任务工单（服务端 JSON，非执行任务）",
            "intake_id": stored["intake_id"],
            "intake": public_record,
            "summary": (
                f"AI 工单已创建：{origin['name']} → {destination['name']}；"
                f"{stored['scheduled_for'] or '时间待确认'}；载荷 {stored['payload_kg']} kg；"
                "航线结果可在工单中查看。"
            ),
            "location_review": [
                {
                    "field": field,
                    "name": place["name"],
                    "point": place.get("point"),
                    "address": place.get("address", ""),
                }
                for field, place in (("origin", origin), ("destination", destination))
            ],
            "limits": ["不进入 M3 状态机", "不产生飞控指令", "真实空域需人工核对"],
            "is_simulated": True,
            "dispatch_enabled": False,
        }

    def inspect_mission_plan(self, _args):
        """Explain the selected intake's saved planning evidence without inventing a new route or forecast."""
        from services.assistant.environment import assess_route_environment
        from services.assistant.landing_sites import assess_landing
        from services.assistant.route_weather import _select_wind

        intake_id = self.turn.context.selected_intake_id
        if not intake_id:
            return {
                "status": "not_selected",
                "reason": "请先从 AI 工单点击地图查看，再检查该工单的天气、风向、禁飞区和备降依据。",
                "dispatch_enabled": False,
            }
        try:
            item = intake_store.get(intake_id)
        except (KeyError, ValueError):
            return {
                "status": "unavailable",
                "reason": "当前工单不可用，请重新选择。",
                "dispatch_enabled": False,
            }
        route = item.get("real_route") or {}
        planning = route.get("planning_result") or {}
        points = [(p.get("lng", p.get("x")), p.get("lat", p.get("y"))) for p in route.get("waypoints", [])]
        if route.get("status") != "ok" or len(points) < 2:
            return {
                "status": route.get("status", "not_planned"),
                "summary": f"工单 {intake_id} 的航线尚未生成；{route.get('reason') or '请等待后台计算或重新规划'}。尚不能据此评估沿线天气与备降。",
                "dispatch_enabled": False,
            }
        active = self.turn.context.active_route
        if active and (active.route_id != route.get("route_id") or active.waypoints != points):
            return {
                "status": "route_mismatch",
                "summary": "地图当前航线与工单保存的航线不同，请重新打开工单；未借用其他路线的天气与备降结果。",
                "dispatch_enabled": False,
            }
        snapshot = item.get("constraint_snapshot") or planning.get("constraint_snapshot") or {}
        weather = planning.get("weather") or {
            "status": "unavailable",
            "samples": [],
            "reason": "历史工单没有保存沿线天气，未用端点天气或演示数据替代。",
        }
        query = EnvQuery(
            origin=points[0],
            destination=points[-1],
            waypoints=points,
            scheduled_for=item.get("scheduled_for"),
            payload_kg=item.get("payload_kg"),
            airspace_snapshot_id=snapshot.get("snapshot_id"),
        )
        environment = assess_route_environment(query, weather=weather, turn_id=str(self.turn.request_id))
        airspace = self.inspect_airspace_constraints(AirspaceAuditQuery(intake_id=intake_id))
        landing = assess_landing(points[0], points[-1])
        samples = weather.get("samples") or []
        valid = sum(s.get("status") == "ok" for s in samples)
        has_wind = any(s.get("status") == "ok" and _select_wind(s.get("values")) is not None for s in samples)
        rows = [
            ["路线版本", route.get("version_label") or "历史版本"],
            [
                "建筑避障",
                f"{len(points)} 航点；"
                + (
                    "保存结果已通过建筑足迹连续净空检查"
                    if route.get("continuous_clearance_verified")
                    else "保存结果缺少建筑足迹连续净空通过证据"
                ),
            ],
            ["禁飞区", (airspace.get("airspace_check") or {}).get("verdict_label") or "未核对"],
            ["沿线天气", f"{valid}/{len(samples)} 个采样点有预报；不是实测"],
            [
                "风向与侧风",
                "使用沿实际航点的保存风场事后评估；未按风场重新优化几何路线"
                if has_wind
                else "没有可用沿线风场，风向/侧风未判定",
            ],
            [
                "能耗",
                (weather.get("energy") or {}).get("reason")
                or (weather.get("energy") or {}).get("status")
                or "无标定参数，未判定",
            ],
            ["备降点", landing["reason"]],
            ["备降余量", "WGS84 任务缺少核实场点和标定能耗，未计算可执行备降余量"],
        ]
        if airspace.get("stale_against_workspace"):
            rows.append(["约束版本失效", "工作区区域已更新，需重新规划"])
        return {
            "status": "ok",
            "source": "当前工单保存的规划结果（复核，不重新取天气）",
            "intake_id": intake_id,
            "route_id": route.get("route_id"),
            "computed_at": route.get("computed_at"),
            "environment": environment,
            "airspace": airspace,
            "landing": landing,
            "rows": rows,
            "summary": f"已复核工单 {intake_id} 的保存结果：几何路线已生成，环境结论 {environment['verdict']}，天气 {valid}/{len(samples)} 点有数据；禁飞区依据、风向与备降缺口见卡片。风未参与几何寻路，备降可达与余量未判定，不构成飞行批准。",
            "dispatch_enabled": False,
        }

    def assess_route_environment(self, args: EnvQuery):
        from services.assistant.environment import assess_route_environment
        from services.assistant.route_weather import _distance

        updates: dict = {}
        route = self.turn.context.active_route
        if (
            route
            and route.frame == "WGS84"
            and (
                _distance(route.waypoints[0], args.origin) <= 1
                and _distance(route.waypoints[-1], args.destination) <= 1
            )
        ):
            updates["waypoints"] = route.waypoints
            if route.constraint_snapshot_id and not args.airspace_snapshot_id:
                updates["airspace_snapshot_id"] = route.constraint_snapshot_id
        if not args.airspace_snapshot_id and "airspace_snapshot_id" not in updates:
            if self.turn.context.airspace_snapshot_id:
                updates["airspace_snapshot_id"] = self.turn.context.airspace_snapshot_id
            elif self.turn.context.selected_intake_id:
                try:
                    item = intake_store.get(self.turn.context.selected_intake_id)
                    snap_id = (item.get("constraint_snapshot") or {}).get("snapshot_id")
                    if snap_id:
                        updates["airspace_snapshot_id"] = snap_id
                except (KeyError, ValueError):
                    pass
        if updates:
            args = EnvQuery.model_validate({**args.model_dump(), **updates})

        return assess_route_environment(args, turn_id=str(self.turn.request_id))

    def explain_verdict(self, args: VerdictQuery):
        from services.assistant.environment import explain_verdict

        return explain_verdict(args.evidence_id)

    def list_environment_gaps(self, args: GapsQuery):
        from services.assistant.environment import list_environment_gaps

        return list_environment_gaps(args.evidence_id)

    def compare_departure_times(self, args: TimeWindowQuery):
        from datetime import timedelta

        from services.assistant.environment import EnvQuery as Query

        start = datetime.fromisoformat(args.window_start.replace("Z", "+00:00"))
        options = []
        steps = max(1, int(args.window_hours * 60 / args.step_minutes))
        for index in range(steps):
            self.checkpoint()
            moment = start + timedelta(minutes=args.step_minutes * index)
            result = self.assess_route_environment(
                Query(origin=args.origin, destination=args.destination, scheduled_for=moment.isoformat())
            )
            options.append(
                {
                    "scheduled_for": moment.isoformat(),
                    "verdict": result["verdict"],
                    "reason": result["verdict_reason"],
                    "evidence_id": result["evidence_id"],
                }
            )
        counts: dict[str, int] = {}
        for option in options:
            counts[option["verdict"]] = counts.get(option["verdict"], 0) + 1
        summary = "、".join(f"{count} 个 {name}" for name, count in counts.items())
        return {
            "options": options,
            "no_improvement": "pass" not in counts,
            "statement": f"{len(options)} 个时刻中 {summary}；没有推荐起飞时刻。",
            "caveat": "预报时效与模式误差未量化；时间窗内天气演变不代表实际飞行时段。",
            "dispatch_enabled": False,
        }

    def check_landing_sites(self, args: LandingQuery):
        from services.assistant.landing_sites import assess_landing

        return assess_landing(args.origin, args.destination, args.ledger_id)

    def audit_route_provenance(self, args: ProvenanceQuery):
        from services.assistant.environment import get_evidence

        found = get_evidence(args.evidence_id) if args.evidence_id else None
        if found is None:
            return {"status": "unavailable", "reason": "没有可审计的 evidence_id", "dispatch_enabled": False}
        provenance = found.get("provenance") or {}
        weather_stats = provenance.get("weather_request_stats") or []
        return {
            "status": "ok",
            "evidence_id": args.evidence_id,
            "weather": {
                "model": provenance.get("model"),
                "fetched_at": next(
                    (item.get("fetched_at") for item in found.get("samples") or [] if item.get("fetched_at")),
                    None,
                ),
                "time_basis": provenance.get("time_basis"),
                "speed_source": provenance.get("speed_source"),
                "request_count": len(weather_stats),
                "proxy_used": next(
                    (item.get("proxy_used") for item in weather_stats if item.get("proxy_used")), None
                ),
            },
            "obstacle": {
                "snapshot_id": None,
                "fetched_at": None,
                "source": None,
                "reason": "本次环境判定没有读取障碍快照",
            },
            "geometry": {"height_known_ratio": None, "projection": None},
            "grades": {
                "forecast": "A" if found.get("status") == "ok" else "unavailable",
                "geometry": None,
                "height": None,
            },
            "statement": "气象模型名和网格分辨率在接口未返回时为 null；障碍快照未参与本次判定。",
            "dispatch_enabled": False,
        }
