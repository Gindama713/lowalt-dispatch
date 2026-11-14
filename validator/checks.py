"""独立路线校验器（M2 的"安全校验"部分）。

## 独立性怎么保证（答辩一定会问，写在这里免得后来人猜）

1. **只读 `RoutePlan.waypoints`，绝不读 `route.checks`。** 规划器自报的结论不进入任何判定。
2. **不复用规划器的栅格。** 规划器在 10 m 栅格上搜索，这里按自己的步长重新采样折线；
   备降距离场也由 `validator/escape.py` 自建，不 import planner 的实现。
3. **时间轴与能量口径由本模块决定**，不接收规划器传来的中间结果。
4. 报告带 `route_digest`，绑定到这一条航线的**内容**；航线被改过一个字节就绑不上。
5. 「到最近备降点的可飞最短距离」与规划器同口径（障碍约束下的最短路），但由本模块
   自己算。用欧氏直线会默认可以穿墙，系统性低估备降能耗，把不安全航线判成安全。

共享的只有 `core.geometry` 的几何原语与栅格常数、`sim.energy` 的物理模型——这些是
"尺子"，两边必须一样；判定逻辑各写一遍，才是独立性。

## 关于"无法判定"

机型参数缺失时，能量与备降两项**拒绝估算**，输出 `passed=False` 且理由以"无法判定"开头。
这不是保守，是唯一诚实的选项：随便填一组参数，整份报告就是假的。

## 依赖方向

`ValidationReport` 定义在 `agent/contracts.py`——那是"工具接口"的所有权方，
本模块是 `verify_route` 的实现方，实现依赖接口是正常方向，不构成循环。
`route_digest` 在 `core`，因为它是 `RoutePlan` 自身的属性。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import hypot

from agent.contracts import ValidationReport
from core.geometry import distance_point_to_polygon, point_in_polygon, sample_polyline
from core.models import (
    ConstraintCheck,
    Frame,
    RiskEvent,
    RiskSnapshot,
    RoutePlan,
    Task,
    route_digest,
)
from planner.scene import Scene
from sim.energy import VehicleProfile, leg_energy_wh
from validator.escape import EscapeField, EscapeSite, build_escape_field

UNAVAILABLE = "无法判定"

DEFAULT_CLEARANCE_M = 20.0
DEFAULT_SAMPLE_STEP_M = 10.0


# --------------------------------------------------------------------------- #
# 采样
# --------------------------------------------------------------------------- #
def _route_points(route: RoutePlan) -> list[tuple[float, float, float]]:
    pts: list[tuple[float, float, float]] = []
    for p in route.waypoints:
        if p.frame is not Frame.ENU_M or p.x_m is None or p.y_m is None:
            raise ValueError("校验器 v0 只支持 ENU 坐标；WGS84 航线必须先转换并在报告中留下转换记录")
        pts.append((p.x_m, p.y_m, p.alt_m))
    return pts


def _cumulative(pts: list[tuple[float, float, float]]) -> list[float]:
    cum = [0.0]
    for (x1, y1, _), (x2, y2, _) in zip(pts, pts[1:], strict=False):
        cum.append(cum[-1] + hypot(x2 - x1, y2 - y1))
    return cum


def _alt_at(pts: list[tuple[float, float, float]], cum: list[float], s: float) -> float:
    if s <= 0.0:
        return pts[0][2]
    if s >= cum[-1]:
        return pts[-1][2]
    lo, hi = 0, len(cum) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if cum[mid] <= s:
            lo = mid
        else:
            hi = mid
    seg = cum[hi] - cum[lo]
    frac = (s - cum[lo]) / seg if seg > 0 else 0.0
    return pts[lo][2] + frac * (pts[hi][2] - pts[lo][2])


# --------------------------------------------------------------------------- #
# 单项检查
# --------------------------------------------------------------------------- #
def _check_endpoints(route: RoutePlan, task: Task) -> ConstraintCheck:
    first, last = route.waypoints[0], route.waypoints[-1]
    same = (
        first.x_m == task.origin.x_m
        and first.y_m == task.origin.y_m
        and last.x_m == task.destination.x_m
        and last.y_m == task.destination.y_m
    )
    if not same:
        return ConstraintCheck(
            name="endpoint_binding",
            passed=False,
            detail=(
                f"航线起终点与任务不符："
                f"({first.x_m},{first.y_m})→({last.x_m},{last.y_m})，"
                f"任务要求 ({task.origin.x_m},{task.origin.y_m})→({task.destination.x_m},{task.destination.y_m})"
            ),
        )
    return ConstraintCheck(name="endpoint_binding", passed=True, detail="起终点与任务一致")


def _check_clearance(
    samples: list[tuple[float, tuple[float, float]]],
    scene: Scene,
    clearance_m: float,
) -> ConstraintCheck:
    """航路点到所有建筑的最小距离必须 ≥ clearance_m。限制区不在这里判，它有生效时间。"""
    if not scene.obstacles:
        return ConstraintCheck(name="clearance", passed=True, detail="场景无建筑障碍，跳过净空检查")

    worst = float("inf")
    worst_at: tuple[float, float] = (0.0, 0.0)
    for _s, (x, y) in samples:
        for poly in scene.obstacles:
            d = distance_point_to_polygon(x, y, poly)
            if d < worst:
                worst, worst_at = d, (x, y)
            if d <= 0.0:
                return ConstraintCheck(
                    name="clearance",
                    passed=False,
                    detail=f"航路点 ({x:.0f},{y:.0f}) 落在建筑内部",
                )
    if worst < clearance_m:
        return ConstraintCheck(
            name="clearance",
            passed=False,
            detail=(
                f"净空不足：({worst_at[0]:.0f},{worst_at[1]:.0f}) 距建筑 {worst:.1f} m "
                f"< 要求 {clearance_m:.0f} m"
            ),
        )
    return ConstraintCheck(
        name="clearance", passed=True, detail=f"全程最小净空 {worst:.1f} m ≥ {clearance_m:.0f} m"
    )


def _event_polygon(event: RiskEvent, scene: Scene) -> list[tuple[float, float]] | None:
    """事件几何兼容两种写法：GeoJSON 的 [[ [x,y], ... ]] 和 build_snapshot 造的 [ (x,y), ... ]。"""
    coords = (event.geometry or {}).get("coordinates")
    if coords:
        first = coords[0]
        ring = first if isinstance(first[0], (list, tuple)) else coords
        return [(float(x), float(y)) for x, y in ring]
    zone = scene.zones.get(event.event_id)
    return zone.polygon if zone else None


def _check_restriction(
    samples: list[tuple[float, tuple[float, float]]],
    pts: list[tuple[float, float, float]],
    cum: list[float],
    snapshot: RiskSnapshot,
    scene: Scene,
    speed_mps: float | None,
) -> ConstraintCheck:
    if speed_mps is None:
        return ConstraintCheck(
            name="restriction_zone",
            passed=False,
            detail=f"{UNAVAILABLE}：缺少巡航速度，无法把航程换算成到达时刻，"
            "就无法判断限制区在那一刻是否真的生效",
        )

    events = [e for e in snapshot.events if e.kind == "restriction_zone"]
    if not events:
        return ConstraintCheck(name="restriction_zone", passed=True, detail="本快照无限制区事件")

    for s, (x, y) in samples:
        t = snapshot.captured_at + timedelta(seconds=s / speed_mps)
        alt = _alt_at(pts, cum, s)
        for ev in events:
            if t < ev.effective_from:
                continue
            if ev.effective_until is not None and t >= ev.effective_until:
                continue
            if ev.alt_min_m is not None and alt < ev.alt_min_m:
                continue
            if ev.alt_max_m is not None and alt > ev.alt_max_m:
                continue
            poly = _event_polygon(ev, scene)
            if poly and point_in_polygon(x, y, poly):
                return ConstraintCheck(
                    name="restriction_zone",
                    passed=False,
                    detail=(
                        f"侵入限制区 {ev.event_id}：t=+{(t - snapshot.captured_at).total_seconds():.0f}s "
                        f"位于 ({x:.0f},{y:.0f}) 高度 {alt:.0f} m；"
                        f"该区自 +{(ev.effective_from - snapshot.captured_at).total_seconds():.0f}s 生效"
                    ),
                )
    return ConstraintCheck(
        name="restriction_zone",
        passed=True,
        detail=f"{len(events)} 个限制区事件按生效时刻逐一比对，全程未侵入",
    )


def _energy_to(
    pts: list[tuple[float, float, float]],
    cum: list[float],
    profile: VehicleProfile,
    s: float,
) -> float:
    alt = _alt_at(pts, cum, s)
    return leg_energy_wh(profile, s, alt - pts[0][2])


def _check_energy(
    pts: list[tuple[float, float, float]],
    cum: list[float],
    route: RoutePlan,
    task: Task,
    profile: VehicleProfile | None,
) -> ConstraintCheck:
    if task.initial_energy_wh <= task.reserve_energy_wh:
        return ConstraintCheck(
            name="energy",
            passed=False,
            detail=(
                f"初始能量 {task.initial_energy_wh:.1f} Wh 不高于保留量 "
                f"{task.reserve_energy_wh:.1f} Wh，起飞前即不可行"
            ),
        )
    if profile is None:
        return ConstraintCheck(
            name="energy",
            passed=False,
            detail=f"{UNAVAILABLE}：机型参数缺失（见 scenarios/vehicles/），拒绝估算能耗",
        )
    total = _energy_to(pts, cum, profile, cum[-1])
    available = task.initial_energy_wh - task.reserve_energy_wh
    if total > available:
        return ConstraintCheck(
            name="energy",
            passed=False,
            detail=(
                f"能耗超预算：全段需 {total:.1f} Wh，可用 {available:.1f} Wh "
                f"（初始 {task.initial_energy_wh:.1f} 扣保留 {task.reserve_energy_wh:.1f}）"
            ),
        )
    if route.energy_budget_wh < total:
        return ConstraintCheck(
            name="energy",
            passed=False,
            detail=(f"规划器申报预算不足：申报 {route.energy_budget_wh:.1f} Wh，独立复算需 {total:.1f} Wh"),
        )
    return ConstraintCheck(
        name="energy",
        passed=True,
        detail=f"全段 {total:.1f} Wh ≤ 可用 {available:.1f} Wh（余 {available - total:.1f}）",
    )


def _valid_sites(snapshot: RiskSnapshot, task: Task, t: datetime) -> list:
    out = []
    for site in snapshot.landing_sites:
        if site.occupied:
            continue
        if site.compatible_vehicle_types and task.vehicle_type not in site.compatible_vehicle_types:
            continue
        if site.available_from is not None and t < site.available_from:
            continue
        if site.available_until is not None and t >= site.available_until:
            continue
        out.append(site)
    return out


def _escape_blockers(snapshot: RiskSnapshot, scene: Scene) -> list:
    """备降路径要绕开的几何：建筑 + 快照时刻已生效的限制区。

    与规划器 `blockers_at_t0` 同口径。飞行中才生效的限制区不进距离场——
    那是动态重规划的事，而且主航线的时间轴违规已由 `_check_restriction` 独立判。
    """
    out: list = list(scene.obstacles)
    for ev in snapshot.events:
        if ev.kind != "restriction_zone" or ev.effective_from > snapshot.captured_at:
            continue
        poly = _event_polygon(ev, scene)
        if poly:
            out.append(poly)
    return out


def _check_diversion(
    samples: list[tuple[float, tuple[float, float]]],
    pts: list[tuple[float, float, float]],
    cum: list[float],
    task: Task,
    snapshot: RiskSnapshot,
    profile: VehicleProfile | None,
    scene: Scene,
) -> ConstraintCheck:
    """按「障碍约束下的最短可飞路径」复算备降余量。

    这里曾经用欧氏直线到备降点，等于默认可以穿墙飞过去，会系统性低估备降能耗
    （实测最大 189.7 m）。现在用 validator/escape.py 自建距离场：与规划器同一
    口径（可飞最短路），但不复用它的栅格；限制区一律绕开，是保守方向。
    """
    if profile is None:
        return ConstraintCheck(
            name="diversion_reachability",
            passed=False,
            detail=f"{UNAVAILABLE}：机型参数缺失，无法计算备降余量",
        )
    if not snapshot.landing_sites:
        return ConstraintCheck(
            name="diversion_reachability",
            passed=False,
            detail="快照内没有任何可用备降点，全程不存在有效退出路径",
        )

    blockers = _escape_blockers(snapshot, scene)
    all_sites: dict[str, EscapeSite] = {}
    for site in snapshot.landing_sites:
        pos = site.position
        if pos.frame is not Frame.ENU_M or pos.x_m is None or pos.y_m is None:
            continue  # 坐标缺失不能当成原点，否则会凭空造出一条退出路径
        all_sites[site.site_id] = EscapeSite(
            site_id=site.site_id,
            x_m=pos.x_m,
            y_m=pos.y_m,
            radius_m=site.radius_m,
            alt_m=pos.alt_m,
        )

    field_cache: dict[tuple[str, ...], EscapeField] = {}
    worst_margin = float("inf")
    worst_at = (0.0, 0.0, 0.0)
    for s, (x, y) in samples:
        t = snapshot.captured_at + timedelta(seconds=s / profile.cruise_speed_mps)
        sites = _valid_sites(snapshot, task, t)
        if not sites:
            return ConstraintCheck(
                name="diversion_reachability",
                passed=False,
                detail=f"在 s={s:.0f} m 处（t=+{(t - snapshot.captured_at).total_seconds():.0f}s）无任何可用备降点",
            )
        valid_ids = tuple(sorted(s.site_id for s in sites if s.site_id in all_sites))
        if not valid_ids:
            return ConstraintCheck(
                name="diversion_reachability",
                passed=False,
                detail=f"在 s={s:.0f} m 处可用备降点缺少 ENU 坐标，无法判定退出路径",
            )
        field = field_cache.get(valid_ids)
        if field is None:
            field = build_escape_field(blockers, [all_sites[i] for i in valid_ids])
            field_cache[valid_ids] = field
        dist_m, idx = field.lookup(x, y)
        if idx < 0:
            return ConstraintCheck(
                name="diversion_reachability",
                passed=False,
                detail=(
                    f"在 s={s:.0f} m 处位于 ({x:.0f},{y:.0f})，"
                    "建筑或限制区阻断了所有当前有效备降点，没有几何可达的退出路径"
                ),
            )
        used = _energy_to(pts, cum, profile, s)
        remaining = task.initial_energy_wh - used - task.reserve_energy_wh
        alt = _alt_at(pts, cum, s)
        nearest = all_sites[field.site_ids[idx]]
        need = leg_energy_wh(profile, dist_m, max(0.0, nearest.alt_m - alt))
        margin = remaining - need
        if margin < worst_margin:
            worst_margin, worst_at = margin, (x, y, s)

    if worst_margin < 0:
        x, y, s = worst_at
        return ConstraintCheck(
            name="diversion_reachability",
            passed=False,
            detail=(
                f"备降余量为负：最差点 s={s:.0f} m 位于 ({x:.0f},{y:.0f})，"
                f"余量 {worst_margin:.1f} Wh —— 按可飞最短路复算后无法抵达任何有效备降点"
            ),
        )
    return ConstraintCheck(
        name="diversion_reachability",
        passed=True,
        detail=f"全程备降余量最小值 {worst_margin:.1f} Wh ≥ 0（按可飞最短路复算）",
    )


def _check_payload(task: Task, profile: VehicleProfile | None) -> ConstraintCheck:
    if profile is None:
        return ConstraintCheck(
            name="payload_limit", passed=False, detail=f"{UNAVAILABLE}：机型参数缺失，无法判断载荷是否超限"
        )
    if task.payload_kg > profile.max_payload_kg:
        return ConstraintCheck(
            name="payload_limit",
            passed=False,
            detail=f"载荷 {task.payload_kg:.1f} kg 超过机型上限 {profile.max_payload_kg:.1f} kg",
        )
    return ConstraintCheck(
        name="payload_limit",
        passed=True,
        detail=f"载荷 {task.payload_kg:.1f} kg ≤ 上限 {profile.max_payload_kg:.1f} kg",
    )


def _check_time(cum: list[float], task: Task, profile: VehicleProfile | None) -> ConstraintCheck:
    if profile is None:
        return ConstraintCheck(
            name="time_limit", passed=False, detail=f"{UNAVAILABLE}：机型参数缺失，无法计算飞行时间"
        )
    assert task.time_limit_s is not None
    flight_s = cum[-1] / profile.cruise_speed_mps
    if flight_s > task.time_limit_s:
        return ConstraintCheck(
            name="time_limit",
            passed=False,
            detail=f"飞行 {flight_s:.0f} s 超过任务时限 {task.time_limit_s:.0f} s",
        )
    return ConstraintCheck(
        name="time_limit",
        passed=True,
        detail=f"飞行 {flight_s:.0f} s ≤ 时限 {task.time_limit_s:.0f} s",
    )


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def validate_route(
    route: RoutePlan,
    task: Task,
    snapshot: RiskSnapshot,
    scene: Scene,
    *,
    profile: VehicleProfile | None = None,
    clearance_m: float = DEFAULT_CLEARANCE_M,
    sample_step_m: float = DEFAULT_SAMPLE_STEP_M,
    now: datetime | None = None,
) -> ValidationReport:
    """对一条航线做五项独立检查，返回带内容摘要的报告。

    `profile=None` 时能量与备降两项会明确标为"无法判定"并通过 `passed=False` 拦住下发——
    这是有意为之，不是缺口。
    """
    verified_at = now or datetime.now(UTC)

    if route.snapshot_id != snapshot.snapshot_id:
        raise ValueError(
            f"航线用的是快照 {route.snapshot_id}，校验拿的是 {snapshot.snapshot_id}；不能跨快照校验"
        )

    pts = _route_points(route)
    cum = _cumulative(pts)
    samples = sample_polyline([(x, y) for x, y, _ in pts], sample_step_m)
    speed = profile.cruise_speed_mps if profile else None

    checks: list[ConstraintCheck] = [
        _check_endpoints(route, task),
        _check_payload(task, profile),
        _check_clearance(samples, scene, clearance_m),
        _check_restriction(samples, pts, cum, snapshot, scene, speed),
        _check_energy(pts, cum, route, task, profile),
        _check_diversion(samples, pts, cum, task, snapshot, profile, scene),
    ]
    if task.time_limit_s is not None:
        checks.append(_check_time(cum, task, profile))

    return ValidationReport(
        task_id=task.task_id,
        route_id=route.route_id,
        plan_version=route.plan_version,
        snapshot_id=snapshot.snapshot_id,
        route_digest=route_digest(route),
        verified_at=verified_at,
        vehicle_state_ts=None,
        checks=checks,
    )


def summarize(report: ValidationReport) -> tuple[bool, str]:
    """人可读的一行结论。`passed=False` 且理由以"无法判定"开头时，单独说明。"""
    failed = [c for c in report.checks if not c.passed]
    unknown = [c for c in failed if c.detail.startswith(UNAVAILABLE)]
    if not failed:
        return True, "全部通过"
    parts = []
    if unknown:
        parts.append(f"{len(unknown)} 项无法判定（{'、'.join(c.name for c in unknown)}）")
    real = [c for c in failed if not c.detail.startswith(UNAVAILABLE)]
    if real:
        parts.append(f"{len(real)} 项不通过（{'、'.join(c.name for c in real)}）")
    return False, "不可下发：" + "，".join(parts)


__all__ = [
    "DEFAULT_CLEARANCE_M",
    "DEFAULT_SAMPLE_STEP_M",
    "UNAVAILABLE",
    "summarize",
    "validate_route",
]
