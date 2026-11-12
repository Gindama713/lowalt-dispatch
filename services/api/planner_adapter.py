"""API 调用规划器的唯一位置。

另一分支在做备降可达性规划器，函数名可能不是 `plan_scenario`。
对接时只改环境变量 PLANNER_ENTRY，或改下面的 DEFAULT_ENTRY。
不要在路由里直接 import planner。

当前默认入口：`planner.astar:plan_scenario`。
它返回 PathResult，只有平面航点。本文件不会把这个结果包装成带能耗的 RoutePlan，
也不会编造 DiversionMarginProfile。

规划函数可以是下面任意一种，参数名要对上：

    plan_scenario(scenario, scene) -> tuple[PathResult, Grid]
    plan_route(task, snapshot) -> RoutePlan
    plan_route(task, snapshot) -> 带 route / margin_profile / algorithm 属性的对象

识别到的余量剖面和 RoutePlan 原样上交。识别不到就明确标成没有，而不是补一份。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core.models import DiversionMarginProfile, RiskEvent, RiskSnapshot, RoutePlan, Task
from planner.astar import PathResult
from planner.scene import Scene, load_scene
from services.api.entrypoints import EntrypointError, load_callable
from services.api.errors import ApiError

DEFAULT_ENTRY = "planner.astar:plan_scenario"


class PlannerIntegrationError(Exception):
    """入口配置或返回值对不上。这种情况下没有路线可返回。"""


@dataclass
class LoadedEntry:
    spec: str
    fn: Any


@dataclass
class PlannerOutcome:
    entry: str
    algorithm: str
    found: bool
    waypoints_xy: list[tuple[float, float]]
    length_m: float | None
    reason: str | None
    elapsed_ms: float | None
    nodes_expanded: int | None
    route_plan: RoutePlan | None
    margin_profile: DiversionMarginProfile | None
    limitations: list[str]


def resolve_entry(override: str) -> LoadedEntry:
    spec = override.strip() or DEFAULT_ENTRY
    try:
        fn = load_callable(spec)
    except EntrypointError as exc:
        raise PlannerIntegrationError(str(exc)) from exc
    return LoadedEntry(spec=spec, fn=fn)


def plan_for_task(
    entry: LoadedEntry,
    task: Task,
    snapshot: RiskSnapshot,
    *,
    now: datetime | None = None,
) -> PlannerOutcome:
    clock = now or datetime.now(UTC)
    _require_enu(task)
    _require_aware_snapshot(snapshot, clock)
    scenario, notes = scenario_from_snapshot(task, snapshot, clock)
    scene = load_scene()
    raw = _call(entry.fn, task=task, snapshot=snapshot, scenario=scenario, scene=scene)
    outcome = _normalize(raw, entry)
    outcome.limitations = notes + outcome.limitations
    return outcome


def _require_enu(task: Task) -> None:
    origin = task.origin
    dest = task.destination
    if origin.frame != dest.frame or origin.alt_ref != dest.alt_ref:
        raise ApiError(422, "起点和终点的坐标系或高度基准不一致，拒绝规划。")
    if origin.frame.value != "enu_m":
        raise ApiError(422, "当前规划入口只接受局部 ENU 米制。未做经纬度转换，拒绝把 WGS84 送进栅格。")
    if origin.x_m is None or origin.y_m is None or dest.x_m is None or dest.y_m is None:
        raise ApiError(422, "ENU 任务缺少平面坐标。")


def _require_aware_snapshot(snapshot: RiskSnapshot, now: datetime) -> None:
    stamps = [snapshot.captured_at, snapshot.valid_until]
    for event in snapshot.events:
        stamps.extend([event.effective_from, event.effective_until])
    for stamp in stamps:
        if stamp is not None and stamp.tzinfo is None:
            raise ApiError(422, "快照时间必须带时区（UTC）。")
    if now.tzinfo is None:
        raise ApiError(500, "服务时钟缺少时区。")


def zone_id_of(event: RiskEvent) -> str | None:
    geo = event.geometry or {}
    zone_id = geo.get("zone_id")
    if isinstance(zone_id, str) and zone_id:
        return zone_id
    props = geo.get("properties")
    if isinstance(props, dict):
        prop_id = props.get("id")
        if isinstance(prop_id, str) and prop_id:
            return prop_id
    return None


def scenario_from_snapshot(
    task: Task,
    snapshot: RiskSnapshot,
    now: datetime,
) -> tuple[dict[str, Any], list[str]]:
    """把快照收成 `plan_scenario` 能读的事件列表。

    静态基线只认识 `at_s == 0` 的 zone_id。尚未生效的限制区不能提前当成障碍，
    基线也不会做时间轴绕行，所以直接不送进去，并写明原因。
    """
    notes: list[str] = []
    events: list[dict[str, Any]] = []
    for event in snapshot.events:
        if event.kind != "restriction_zone":
            notes.append(f"事件 {event.event_id}（{event.kind}）不是限制区。静态基线不用它。")
            continue
        if event.effective_until is not None and now > event.effective_until:
            notes.append(f"限制区事件 {event.event_id} 已过 effective_until，未送入规划器。")
            continue
        if event.effective_from > now:
            notes.append(
                f"限制区事件 {event.event_id} 尚未到 effective_from。"
                "静态基线不会表达未来才生效的区域，所以这次既没有把它当障碍，也没有按时间轴绕行。"
            )
            continue
        zone_id = zone_id_of(event)
        if zone_id is None:
            notes.append(
                f"限制区事件 {event.event_id} 没有 zone_id"
                "（geometry.zone_id 或 geometry.properties.id）。"
                "当前入口只能按场景文件里的区号避让，不能按任意多边形临时封控。"
            )
            continue
        events.append({"kind": "restriction_zone", "at_s": 0, "zone_id": zone_id})

    scenario = {
        "id": task.task_id,
        "origin": {"x_m": task.origin.x_m, "y_m": task.origin.y_m},
        "destination": {"x_m": task.destination.x_m, "y_m": task.destination.y_m},
        "events": events,
    }
    return scenario, notes


def _call(fn: Any, *, task: Task, snapshot: RiskSnapshot, scenario: dict[str, Any], scene: Scene) -> Any:
    signature = inspect.signature(fn)
    available: dict[str, Any] = {
        "task": task,
        "snapshot": snapshot,
        "scenario": scenario,
        "scene": scene,
    }
    kwargs: dict[str, Any] = {}
    missing: list[str] = []
    for name, param in signature.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if name in available:
            kwargs[name] = available[name]
        elif param.default is inspect.Parameter.empty:
            missing.append(name)
    if missing:
        joined = ", ".join(missing)
        raise PlannerIntegrationError(
            f"规划入口参数无法填充：{joined}。目前只能提供 task、snapshot、scenario、scene。"
        )
    if not kwargs:
        raise PlannerIntegrationError(
            "规划入口没有可绑定的参数。需要具名参数 task、snapshot、scenario 或 scene。"
        )
    return fn(**kwargs)


def _normalize(raw: Any, entry: LoadedEntry) -> PlannerOutcome:
    route_plan = _find_route_plan(raw)
    margin = _find_margin(raw)
    path = _find_path(raw)
    algorithm = _find_algorithm(raw) or _default_algorithm(entry.spec)
    limitations: list[str] = []

    if path is not None and route_plan is None:
        return PlannerOutcome(
            entry=entry.spec,
            algorithm=algorithm,
            found=path.found,
            waypoints_xy=list(path.waypoints) if path.found else [],
            length_m=path.length_m if path.found else None,
            reason=path.reason,
            elapsed_ms=path.elapsed_ms,
            nodes_expanded=path.nodes_expanded,
            route_plan=None,
            margin_profile=margin,
            limitations=limitations,
        )

    if route_plan is not None:
        xy: list[tuple[float, float]] = []
        for point in route_plan.waypoints:
            if point.x_m is None or point.y_m is None:
                limitations.append("规划器返回的 RoutePlan 含非 ENU 航点，平面航程无法由 API 重算。")
                xy = []
                break
            xy.append((point.x_m, point.y_m))
        length = _length_or_none(xy)
        found = path.found if path is not None else True
        return PlannerOutcome(
            entry=entry.spec,
            algorithm=algorithm,
            found=found,
            waypoints_xy=xy if found else [],
            length_m=length if found else None,
            reason=path.reason if path is not None else None,
            elapsed_ms=path.elapsed_ms if path is not None else None,
            nodes_expanded=path.nodes_expanded if path is not None else None,
            route_plan=route_plan,
            margin_profile=margin,
            limitations=limitations,
        )

    if margin is not None and path is None:
        raise PlannerIntegrationError(
            f"规划入口 {entry.spec} 只返回了余量剖面，没有路线。API 不会配一条假航线。"
        )

    raise PlannerIntegrationError(
        f"规划入口 {entry.spec} 的返回值无法识别（{type(raw).__name__}）。"
        "需要 PathResult、(PathResult, 栅格)、RoutePlan，或带 route / margin_profile 属性的对象。"
    )


def _length_or_none(xy: list[tuple[float, float]]) -> float | None:
    if len(xy) < 2:
        return None
    from core.geometry import polyline_length

    return polyline_length(xy)


def _find_path(raw: Any) -> PathResult | None:
    if isinstance(raw, PathResult):
        return raw
    if isinstance(raw, tuple) and raw and isinstance(raw[0], PathResult):
        return raw[0]
    for name in ("path", "result"):
        value = getattr(raw, name, None)
        if isinstance(value, PathResult):
            return value
    return None


def _find_route_plan(raw: Any) -> RoutePlan | None:
    if isinstance(raw, RoutePlan):
        return raw
    for name in ("route", "route_plan"):
        value = getattr(raw, name, None)
        if isinstance(value, RoutePlan):
            return value
    return None


def _find_margin(raw: Any) -> DiversionMarginProfile | None:
    if isinstance(raw, DiversionMarginProfile):
        return raw
    for name in ("margin_profile", "margin", "diversion_margin"):
        value = getattr(raw, name, None)
        if isinstance(value, DiversionMarginProfile):
            return value
    return None


def _find_algorithm(raw: Any) -> str | None:
    value = getattr(raw, "algorithm", None)
    if isinstance(value, str) and value:
        return value
    if isinstance(raw, RoutePlan):
        return raw.algorithm
    route = _find_route_plan(raw)
    if route is not None:
        return route.algorithm
    return None


def _default_algorithm(spec: str) -> str:
    if spec == DEFAULT_ENTRY or spec.startswith("planner.astar"):
        return "astar_static"
    return spec
