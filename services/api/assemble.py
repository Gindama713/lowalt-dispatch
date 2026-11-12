"""把规划器的返回值收成可存储的路线记录。

缺什么就标 unavailable。不调用 sim.energy，也不用任务单上的初始能量冒充预算。
"""

from __future__ import annotations

from core.models import Position, Task
from services.api.envelopes import MarginView, RouteRecord
from services.api.planner_adapter import PlannerOutcome

TIMING_NOTE = "elapsed_ms 是规划函数内部的搜索耗时，不是事件到飞控确认的端到端时延。"
SIMULATION_NOTE = (
    "航线几何来自 scenarios/v0 草稿场景（GeoJSON 标为仿真，status=draft）。"
    "即使任务单把 is_simulated 写成 false，这条路线仍然是仿真几何，不能写成实测。"
)
BASELINE_LIMIT = (
    "astar_static 只做几何可达：避开建筑，以及快照里已经生效、且能对应到区号的限制区。"
    "不判时限、不算能量、不做备降可达性剪枝。"
)


def margin_view(record: RouteRecord) -> MarginView:
    profile = record.margin_profile
    if record.margin_status != "available" or profile is None:
        return MarginView(
            task_id=record.task_id,
            route_id=record.route_id,
            status="unavailable",
            detail=record.margin_detail,
            profile=None,
            min_margin_wh=None,
            negative_sample_count=None,
            is_feasible=None,
        )
    return MarginView(
        task_id=record.task_id,
        route_id=record.route_id,
        status="available",
        detail=record.margin_detail,
        profile=profile,
        min_margin_wh=profile.min_margin_wh,
        negative_sample_count=profile.negative_sample_count,
        is_feasible=profile.is_feasible,
    )


def assemble_route(
    task: Task,
    *,
    route_id: str,
    plan_version: str,
    snapshot_id: str,
    outcome: PlannerOutcome,
    requested_algorithm: str | None,
) -> RouteRecord:
    limitations = list(outcome.limitations)
    if outcome.algorithm == "astar_static":
        limitations.append(BASELINE_LIMIT)
    if requested_algorithm and requested_algorithm != outcome.algorithm:
        limitations.append(
            f"请求里的算法名是 {requested_algorithm}，实际入口是 {outcome.entry}，"
            f"记录使用 {outcome.algorithm}。请求名不会被当成另一个规划器。"
        )

    if outcome.route_plan is not None:
        waypoints = list(outcome.route_plan.waypoints)
        altitude_note = "航点来自规划器返回的 RoutePlan，API 未改写。"
        route_plan_status = "available"
        route_plan_detail = "规划入口返回了 RoutePlan。API 没有改写 waypoints、energy_budget_wh 或 checks。"
        route_plan = outcome.route_plan
    else:
        waypoints, altitude_note = _waypoints(task, outcome.waypoints_xy, limitations)
        route_plan = None
        route_plan_status = "unavailable"
        if outcome.found:
            route_plan_detail = (
                "不可用：规划入口只给了平面航点，没有 energy_budget_wh，因此不能构成 RoutePlan。"
                "API 不用任务的 initial_energy_wh 填这个字段，也不另算能耗。"
            )
        else:
            route_plan_detail = "不可用：没有可行路线，因此没有 RoutePlan。"

    if outcome.margin_profile is not None:
        margin_status = "available"
        margin_detail = "规划入口返回了备降余量剖面，采样点保持原样。"
        margin_profile = outcome.margin_profile
    else:
        margin_status = "unavailable"
        margin_detail = "未实现：当前规划入口没有备降余量剖面。这里没有采样点，也没有用 0 或假曲线代替。"
        margin_profile = None

    return RouteRecord(
        task_id=task.task_id,
        route_id=route_id,
        plan_version=plan_version,
        snapshot_id=snapshot_id,
        algorithm=outcome.algorithm,
        planner_entry=outcome.entry,
        found=outcome.found,
        reason=outcome.reason,
        length_m=outcome.length_m,
        elapsed_ms=outcome.elapsed_ms,
        nodes_expanded=outcome.nodes_expanded,
        timing_note=TIMING_NOTE,
        waypoints=waypoints,
        altitude_note=altitude_note,
        route=route_plan,
        route_plan_status=route_plan_status,
        route_plan_detail=route_plan_detail,
        margin_status=margin_status,
        margin_detail=margin_detail,
        margin_profile=margin_profile,
        limitations=limitations,
        is_simulated=True,
        simulation_note=SIMULATION_NOTE,
    )


def _same_xy(point: Position, x: float, y: float) -> bool:
    return (
        point.x_m is not None
        and point.y_m is not None
        and abs(point.x_m - x) < 1e-4
        and abs(point.y_m - y) < 1e-4
    )


def _waypoints(
    task: Task,
    xy: list[tuple[float, float]],
    limitations: list[str],
) -> tuple[list[Position], str]:
    if not xy:
        return [], "规划器没有返回航点。"

    points: list[Position] = []
    last = len(xy) - 1
    copied_altitude = False
    for index, (x, y) in enumerate(xy):
        if index == 0 and _same_xy(task.origin, x, y):
            points.append(task.origin)
            continue
        if index == last and _same_xy(task.destination, x, y):
            points.append(task.destination)
            continue
        points.append(
            Position(
                frame=task.origin.frame,
                x_m=x,
                y_m=y,
                alt_m=task.origin.alt_m,
                alt_ref=task.origin.alt_ref,
            )
        )
        copied_altitude = True
        if index in (0, last):
            limitations.append("规划器返回的端点与任务坐标不一致。该点高度沿用起点，不是测得的飞行高度。")

    if copied_altitude and len(xy) > 2:
        note = (
            "中间航点的 alt_m 与 alt_ref 复制起点，只为满足 Position 的必填字段，不是规划器算出的高度剖面。"
        )
    elif copied_altitude:
        note = "有航点的高度沿用起点。A* 基线不规划高度。"
    else:
        note = "航点就是任务起终点，没有由 API 插值的高度。"
    return points, note
