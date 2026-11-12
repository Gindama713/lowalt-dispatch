"""Read-only tools and draft proposals; no flight command tool is exposed."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from core.geometry import polyline_length
from planner.astar import plan
from planner.grid import build_grid
from planner.scene import load_scene
from services.assistant.knowledge import search
from services.assistant.models import DocumentQuery, Draft, DraftUpdate, NoArgs, Turn
from services.assistant.telemetry import STALE_SECONDS

ROOT = Path(__file__).resolve().parents[2]
PLACES = {
    "医疗物资中转站": (150.0, 150.0),
    "北区应急中心": (2650.0, 2750.0),
    **{key: (site.x, site.y) for key, site in load_scene().sites.items()},
}
ALIASES = {"中转站": "医疗物资中转站", "北区中心": "北区应急中心", "应急中心": "北区应急中心"}


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


class Toolset:
    SPECS = {
        "search_project_docs": (
            "查找项目规则、接口和操作说明，返回原文、文件位置和内容版本。",
            DocumentQuery,
        ),
        "get_flight_status": ("读取当前界面遥测、时间和来源，不作适航或备降安全判断。", NoArgs),
        "get_task_status": ("查询联调面板选中的本地合成任务，读取规划、回执和独立执行状态。", NoArgs),
        "list_events": ("读取本次页面会话的事件记录并按类型统计。", NoArgs),
        "list_places": ("列出虚拟场景登记地点和局部ENU坐标，未知名称不能猜坐标。", NoArgs),
        "update_task_draft": ("仅更新用户明确提供的任务草稿字段；可多轮补充，缺失值保留未知。", DraftUpdate),
        "plan_task_preview": ("用现有几何A*计算草稿路线预览；不验证能量/备降，不下发。", NoArgs),
        "inspect_terrain_risk": (
            "检测最近地形变化包围框与当前基线航线的平面交叠，区分已过/剩余航段。",
            NoArgs,
        ),
        "get_capabilities": ("说明实际接入能力、待连接项和下发边界。", NoArgs),
    }

    def __init__(self, turn: Turn, read_dispatch_task: Callable[[str], dict] | None = None):
        self.turn = turn
        self.read_dispatch_task = read_dispatch_task
        self.draft = turn.draft
        self.results: dict[str, dict] = {}

    @classmethod
    def schemas(cls):
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": schema.model_json_schema(),
                },
            }
            for name, (description, schema) in cls.SPECS.items()
        ]

    def execute(self, name: str, arguments: dict):
        if name not in self.SPECS:
            raise ValueError("Tool is not available")
        validated = self.SPECS[name][1].model_validate(arguments)
        result = getattr(self, name)(validated)
        self.results[name] = result
        return result

    def search_project_docs(self, args: DocumentQuery):
        excerpts = search(args.query)
        return {
            "status": "ok" if excerpts else "no_match",
            "source": "仓库项目文档",
            "excerpts": excerpts,
        }

    def get_flight_status(self, _args):
        ctx = self.turn.context
        if ctx.telemetry_mode == "live":
            frame = ctx.live_telemetry
            age = frame.age_seconds() if frame else None
            return {
                "telemetry_mode": "live",
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

    def get_task_status(self, _args):
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
            "assumptions": "保守地将场景全部限制区作为静态障碍；地形、能耗、动态时效未加入搜索。",
            "dispatch_enabled": False,
            "is_simulated": True,
        }

    def inspect_terrain_risk(self, _args):
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
        return {
            "available": [
                "项目文档检索与原文出处",
                "当前页面的演示或 M4 遥测查询",
                "本地合成任务状态与回执查询",
                "虚拟地点查询",
                "多轮任务草稿",
                "实际几何A*路线预览",
                "地形变化平面影响分析",
                "本页事件解释",
            ],
            "pending": [
                "M3跨服务确认与审计查询",
                "机型能量参数",
                "含备降硬约束的动态规划",
                "PX4 任务执行与飞控回执",
            ],
            "dispatch_enabled": False,
            "is_simulated": True,
        }
