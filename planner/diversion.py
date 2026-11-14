"""备降余量与搜索期硬约束（astar_diversion）。

基线 `planner.astar.plan` 只回答“能不能绕开障碍走到终点”。
这里多问一句：走到这一格时，剩下的能量扣掉保留量，还够不够飞到一个
**当前有效**的备降点。不够的状态不进队列。终点因此不可达时，返回
明确的无解原因，不把那条会飞进负余量的路线交出去。

近似（v0，写在这里是为了让后面的人不要把它说满）
------------------------------------------------
1. 备降路径和主航线用同一张占用栅格：建筑 + **起飞时已经生效**（at_s == 0）
   的限制区，再按净空做圆形膨胀。穿过膨胀后障碍的格子不可走。
   路径代价是八邻域折线长度（米），不是欧氏直线，也不是带转弯半径的连续轨迹。
2. 多源 Dijkstra 从每个备降点半径内的可飞格出发，半径内代价记 0
   （进入降落盘即视为到达）。每个格子记下能量意义上最近的那个备降点。
   直线更近但被墙挡住的点，不会赢过绕路更短的点。
3. 能耗 = 一次爬升（爬升时间 × 悬停功率；下降按能量模型记 0）
   + 单位距离能耗 × 水平距离。不计风、不计转弯。场景里的 wind_profile
   标签因此不会改变结果。
4. 搜索检查的是到达代价再加一格对角线（`res_m * √2`）。这 1 格是端点贴格、
   对角线抄角带来的保守量，避免网格上刚过线、折线采样又变成负数。
5. 目的地不是备降点。飞行中才关闭的备降点（`landing_site_changes` 里 `at_s > 0`
   的 `closed`）已进入本版：搜索按到达时刻的有效备降点集合换距离场，余量剖面
   按同样的时刻复算。at_s > 0 的限制区仍当还没发生——那是动态重规划的事，
   `astar_dynamic` 仍是 mock。

`E_left - E_reserve - E_need >= 0` 才算这个状态还能搜。
E_need 是上面这张距离场乘单位距离能耗；没有几何可达备降点时，
不把余量算成 0，nearest_site_id 留空，margin 用哨兵负数。
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from core.geometry import polyline_length, sample_polyline
from core.models import DiversionMarginProfile, DiversionMarginSample
from planner.astar import plan
from planner.grid import DEFAULT_CLEARANCE_M, DEFAULT_RES_M, Grid, build_grid, snap_to_free
from planner.scene import LandingSite, Scene, endpoint_xy
from sim.energy import VehicleProfile, climb_energy_wh, cruise_energy_wh, cruise_time_s

# 无几何可达备降点时写入剖面的 margin。只表示“没有退出路径”，不是能量缺口。
UNREACHABLE_MARGIN_WH = -1.0e6
MARGIN_TOL_WH = 1.0e-6
SAMPLE_STEP_M = 50.0
_GRID_CACHE: dict[tuple, Grid] = {}
_FIELD_CACHE: dict[tuple, DiversionField] = {}
_SCENE: Scene | None = None

APPROXIMATION_NOTE = (
    "备降路径近似：与主航线相同的占用栅格（障碍 + at_s=0 的限制区，圆形净空膨胀），"
    "八邻域最短路，进入备降半径即到达；能耗为一次爬升加无风巡航，不计转弯。"
    "搜索比折线采样多扣一格对角线。目的地不算备降点；飞行中关闭的备降点按到达时刻生效，"
    "at_s>0 的限制区仍不进入本版。示例机型参数不是真实平台数据。"
)


@dataclass(frozen=True)
class MarginQuery:
    """某个状态下的备降余量。energy_left_wh 由调用方按“已经飞到这里”给入。"""

    distance_m: float
    energy_need_wh: float | None
    margin_wh: float
    nearest_site_id: str | None
    geometrically_reachable: bool

    @property
    def satisfies_constraint(self) -> bool:
        return self.geometrically_reachable and self.margin_wh >= -MARGIN_TOL_WH


@dataclass
class DiversionField:
    """每个格子到最近可达备降点的路径长度（米）。不可达为 inf，索引为 -1。"""

    dist_m: object  # np.ndarray
    nearest_index: object  # np.ndarray
    site_ids: list[str]

    def lookup(self, grid: Grid, x: float, y: float) -> tuple[float, str | None]:
        dist = self.dist_m
        nearest = self.nearest_index
        iy, ix = grid.to_ij(x, y)
        if not grid.free(iy, ix):
            snapped = snap_to_free(grid, x, y, max_rings=2)
            if snapped is None:
                return math.inf, None
            iy, ix = snapped
        d = float(dist[iy, ix])
        if not math.isfinite(d):
            return math.inf, None
        si = int(nearest[iy, ix])
        if si < 0:
            return math.inf, None
        return d, self.site_ids[si]


@dataclass
class ScenarioPlan:
    algorithm: str
    found: bool
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    length_m: float = 0.0
    energy_used_wh: float = 0.0
    elapsed_ms: float = 0.0
    reason: str | None = None
    profile: DiversionMarginProfile | None = None
    expanded: int = 0
    pruned: int = 0
    rejection_kind: str = "geometry"
    initial_energy_wh: float = 0.0
    reserve_wh: float = 0.0


@dataclass(frozen=True)
class HardReport:
    feasible: bool
    hard_violations: int
    negative_margin_samples: int
    reason: str
    flight_time_s: float | None
    energy_used_wh: float


def shared_scene() -> Scene:
    global _SCENE
    if _SCENE is None:
        from planner.scene import load_scene

        _SCENE = load_scene()
    return _SCENE


def zones_active_at_planning_time(scenario: dict, scene: Scene):
    """只拿 at_s == 0 的限制区。飞行中才出现的区域，本版规划器当还不知道。"""
    out = []
    for ev in scenario.get("events") or []:
        if ev.get("kind") != "restriction_zone":
            continue
        if float(ev.get("at_s", 0) or 0) != 0.0:
            continue
        zone = scene.zones.get(ev.get("zone_id"))
        if zone is not None:
            out.append(zone)
    return out


def blockers_at_t0(scenario: dict, scene: Scene):
    return list(scene.obstacles) + [z.polygon for z in zones_active_at_planning_time(scenario, scene)]


def closed_site_ids_at_t0(scenario: dict) -> set[str]:
    closed: set[str] = set()
    for change in scenario.get("landing_site_changes") or []:
        if str(change.get("change")) != "closed":
            continue
        if float(change.get("at_s", 0) or 0) != 0.0:
            continue
        closed.add(str(change["site_id"]))
    return closed


def site_closure_schedule(scenario: dict) -> tuple[tuple[float, str], ...]:
    """飞行中才关闭的备降点，按生效秒数排序。

    t=0 的关闭已由 `active_landing_sites` 过滤掉，这里只处理 `at_s > 0` 的。
    场景里的 `landing_site_changes` 是现成数据，不需要任何编造的风场或机型参数。
    """
    out: list[tuple[float, str]] = []
    for change in scenario.get("landing_site_changes") or []:
        if str(change.get("change")) != "closed":
            continue
        at_s = float(change.get("at_s", 0) or 0)
        if at_s <= 0:
            continue
        out.append((at_s, str(change["site_id"])))
    return tuple(sorted(out))


def sites_available_at(
    sites: list[LandingSite],
    schedule: tuple[tuple[float, str], ...],
    t_s: float,
) -> list[LandingSite]:
    """t_s 时刻仍有效的备降点。v0 只建模 `closed`，关闭后不恢复。"""
    closed = {sid for at_s, sid in schedule if at_s <= t_s}
    if not closed:
        return sites
    return [s for s in sites if s.site_id not in closed]


def make_field_at(grid: Grid, sites: list[LandingSite], schedule: tuple[tuple[float, str], ...]):
    """按到达时刻返回对应的备降距离场；该时刻无有效备降点则返回 None。

    不同的有效备降点集合各建一张距离场并缓存。集合数等于关闭事件数 + 1，
    不会随着采样点数量增长。
    """
    cache: dict[tuple[str, ...], DiversionField] = {}

    def field_at(t_s: float) -> DiversionField | None:
        subset = sites_available_at(sites, schedule, t_s)
        if not subset:
            return None
        key = tuple(s.site_id for s in subset)
        if key not in cache:
            cache[key] = build_diversion_field(grid, subset)
        return cache[key]

    return field_at


def active_landing_sites(
    scene: Scene,
    scenario: dict,
    vehicle: VehicleProfile,
) -> tuple[list[LandingSite], list[str]]:
    """当前有效备降点。不适配、被占用、t=0 已关闭、半径内无可飞格的，都不算。

    半径内是否可飞要等栅格建好才能知道，这里先做属性过滤。
    """
    keys = {vehicle.vehicle_key}
    if vehicle.draft_geometry_vehicle_alias:
        keys.add(vehicle.draft_geometry_vehicle_alias)
    closed = closed_site_ids_at_t0(scenario)
    usable: list[LandingSite] = []
    notes: list[str] = []
    for site in scene.sites.values():
        if site.site_id in closed:
            notes.append(f"{site.site_id} 在 t=0 关闭")
            continue
        if site.occupied:
            notes.append(f"{site.site_id} 被占用")
            continue
        if not site.compatible_vehicle_types:
            notes.append(f"{site.site_id} 没有适用机型")
            continue
        if keys.isdisjoint(site.compatible_vehicle_types):
            notes.append(f"{site.site_id} 不适配 {vehicle.vehicle_key}")
            continue
        usable.append(site)
    usable.sort(key=lambda s: s.site_id)
    return usable, notes


def resolve_energy(scenario: dict, vehicle: VehicleProfile) -> tuple[float, float]:
    """任务单上的能量优先；缺了才回落到机型参数。回落不等于那组参数是实测。"""
    initial = scenario.get("initial_energy_wh", vehicle.usable_battery_wh)
    reserve = scenario.get("reserve_energy_wh", vehicle.reserve_policy_wh)
    return float(initial), float(reserve)


def climb_delta_m(scenario: dict) -> float:
    origin = float(scenario["origin"].get("alt_m", 0.0))
    dest = float(scenario["destination"].get("alt_m", 0.0))
    return dest - origin


def _poly_key(polys) -> tuple:
    return tuple(tuple((float(x), float(y)) for x, y in poly) for poly in polys)


def cached_grid(
    blockers,
    *,
    res_m: float = DEFAULT_RES_M,
    clearance_m: float = DEFAULT_CLEARANCE_M,
) -> Grid:
    key = (res_m, clearance_m, _poly_key(blockers))
    grid = _GRID_CACHE.get(key)
    if grid is None:
        grid = build_grid(list(blockers), res_m=res_m, clearance_m=clearance_m)
        _GRID_CACHE[key] = grid
    return grid


def _pad_cells(grid: Grid, site: LandingSite) -> list[tuple[int, int]]:
    if site.radius_m <= 0:
        return []
    r = site.radius_m
    ix0 = int(math.floor((site.x - r - grid.x0) / grid.res_m))
    ix1 = int(math.floor((site.x + r - grid.x0) / grid.res_m))
    iy0 = int(math.floor((site.y - r - grid.y0) / grid.res_m))
    iy1 = int(math.floor((site.y + r - grid.y0) / grid.res_m))
    cells: list[tuple[int, int]] = []
    r2 = r * r
    for iy in range(max(0, iy0), min(grid.ny, iy1 + 1)):
        for ix in range(max(0, ix0), min(grid.nx, ix1 + 1)):
            if not grid.free(iy, ix):
                continue
            cx, cy = grid.center(iy, ix)
            if (cx - site.x) ** 2 + (cy - site.y) ** 2 <= r2:
                cells.append((iy, ix))
    return cells


def build_diversion_field(grid: Grid, sites: list[LandingSite]) -> DiversionField:
    """多源 Dijkstra。代价是米。同一代价时保留 site_id 字典序更小的那个（sites 已排序）。"""
    import heapq

    import numpy as np

    from planner.astar import NEIGHBORS

    dist = np.full((grid.ny, grid.nx), np.inf, dtype=np.float64)
    nearest = np.full((grid.ny, grid.nx), -1, dtype=np.int32)
    heap: list[tuple[float, int, int]] = []
    site_ids = [s.site_id for s in sites]
    for si, site in enumerate(sites):
        for iy, ix in _pad_cells(grid, site):
            if dist[iy, ix] <= 0.0:
                continue
            dist[iy, ix] = 0.0
            nearest[iy, ix] = si
            heapq.heappush(heap, (0.0, iy, ix))

    res = grid.res_m
    blocked = grid.blocked
    ny, nx = grid.ny, grid.nx
    while heap:
        d, iy, ix = heapq.heappop(heap)
        if d != dist[iy, ix]:
            continue
        sid = int(nearest[iy, ix])
        for dy, dx, step in NEIGHBORS:
            ny_, nx_ = iy + dy, ix + dx
            if not (0 <= ny_ < ny and 0 <= nx_ < nx) or blocked[ny_, nx_]:
                continue
            nd = d + step * res
            if nd < dist[ny_, nx_]:
                dist[ny_, nx_] = nd
                nearest[ny_, nx_] = sid
                heapq.heappush(heap, (nd, ny_, nx_))
    return DiversionField(dist_m=dist, nearest_index=nearest, site_ids=site_ids)


def cached_field(grid: Grid, sites: list[LandingSite]) -> DiversionField:
    key = (id(grid), tuple((s.site_id, s.x, s.y, s.radius_m) for s in sites))
    field_ = _FIELD_CACHE.get(key)
    if field_ is None:
        field_ = build_diversion_field(grid, sites)
        _FIELD_CACHE[key] = field_
    return field_


def query_margin(
    *,
    field_: DiversionField,
    grid: Grid,
    x: float,
    y: float,
    energy_left_wh: float,
    reserve_wh: float,
    vehicle: VehicleProfile,
) -> MarginQuery:
    """给定到达 (x, y) 后的剩余能量，计算到最近可达备降点的能耗和余量。

    最近是路径能耗最小，不是欧氏距离最小。障碍和限制区已经烧进 field_。
    """
    dist, site_id = field_.lookup(grid, x, y)
    if site_id is None or not math.isfinite(dist):
        return MarginQuery(
            distance_m=math.inf,
            energy_need_wh=None,
            margin_wh=UNREACHABLE_MARGIN_WH,
            nearest_site_id=None,
            geometrically_reachable=False,
        )
    energy_need = cruise_energy_wh(vehicle, dist)
    margin = energy_left_wh - reserve_wh - energy_need
    return MarginQuery(
        distance_m=dist,
        energy_need_wh=energy_need,
        margin_wh=margin,
        nearest_site_id=site_id,
        geometrically_reachable=True,
    )


def profile_along_route(
    *,
    route_id: str,
    waypoints: list[tuple[float, float]],
    grid: Grid,
    field_: DiversionField,
    vehicle: VehicleProfile,
    initial_energy_wh: float,
    reserve_wh: float,
    climb_delta: float,
    plan_version: str = "v1",
    sample_step_m: float = SAMPLE_STEP_M,
    field_at: Callable[[float], DiversionField | None] | None = None,
) -> DiversionMarginProfile:
    """沿折线采样。爬升能耗在 s=0 一次扣完，之后只加水平巡航。

    `field_at` 给出到达时刻 t_s 的有效备降距离场；不传则用同一张静态 `field_`。
    两者必须与搜索阶段用同一套，否则剖面会复算出一个搜索时没判过的结论。
    """
    if len(waypoints) < 2:
        raise ValueError("剖面至少需要两个航点")
    climb_wh = climb_energy_wh(vehicle, climb_delta)
    climb_time = (climb_delta / vehicle.climb_rate_mps) if climb_delta > 0 else 0.0
    sampled = sample_polyline(waypoints, sample_step_m)
    total = polyline_length(waypoints)
    if not sampled or sampled[-1][0] < total - 1e-6:
        sampled.append((total, waypoints[-1]))

    samples: list[DiversionMarginSample] = []
    for s_m, (x, y) in sampled:
        t_s = climb_time + cruise_time_s(vehicle, s_m)
        active_field = field_at(t_s) if field_at is not None else field_
        if active_field is None:
            samples.append(
                DiversionMarginSample(
                    s_m=s_m,
                    t_s=t_s,
                    margin_wh=UNREACHABLE_MARGIN_WH,
                    nearest_site_id=None,
                    energy_need_wh=None,
                )
            )
            continue
        energy_left = initial_energy_wh - climb_wh - cruise_energy_wh(vehicle, s_m)
        queried = query_margin(
            field_=active_field,
            grid=grid,
            x=x,
            y=y,
            energy_left_wh=energy_left,
            reserve_wh=reserve_wh,
            vehicle=vehicle,
        )
        samples.append(
            DiversionMarginSample(
                s_m=s_m,
                t_s=t_s,
                margin_wh=queried.margin_wh,
                nearest_site_id=queried.nearest_site_id,
                energy_need_wh=queried.energy_need_wh,
            )
        )
    return DiversionMarginProfile(
        route_id=route_id,
        plan_version=plan_version,
        reserve_wh=reserve_wh,
        samples=samples,
    )


def _energy_used(vehicle: VehicleProfile, length_m: float, climb_delta: float) -> float:
    return climb_energy_wh(vehicle, climb_delta) + cruise_energy_wh(vehicle, length_m)


def _flight_time_s(vehicle: VehicleProfile, length_m: float, climb_delta: float) -> float:
    climb_time = (climb_delta / vehicle.climb_rate_mps) if climb_delta > 0 else 0.0
    return climb_time + cruise_time_s(vehicle, length_m)


def _empty_plan(
    algorithm: str,
    *,
    reason: str,
    kind: str,
    elapsed_ms: float,
    initial: float,
    reserve: float,
    pruned: int = 0,
    expanded: int = 0,
) -> ScenarioPlan:
    return ScenarioPlan(
        algorithm=algorithm,
        found=False,
        elapsed_ms=elapsed_ms,
        reason=reason,
        rejection_kind=kind,
        initial_energy_wh=initial,
        reserve_wh=reserve,
        pruned=pruned,
        expanded=expanded,
    )


def _explain_prune(path_reason: str | None, prune_counts: dict[str, int]) -> tuple[str, str]:
    if path_reason and path_reason.startswith("起点不满足约束："):
        cat = path_reason.split("：", 1)[1]
        text = {
            "diversion": "起点不满足备降可达：剩余能量扣除保留量后，到不了任何当前有效备降点",
            "no_exit": "起点没有几何可达的当前有效备降点（障碍或限制区挡住了所有备降点）",
            "time": "起点已超出任务时限",
        }.get(cat, path_reason)
        kind = {"time": "time", "no_exit": "no_site", "diversion": "diversion"}.get(cat, "diversion")
        return text, kind

    parts: list[str] = []
    kind = "diversion"
    if prune_counts.get("diversion"):
        parts.append(f"{prune_counts['diversion']} 个状态因剩余能量扣掉保留量后到不了备降点而被剪枝")
        kind = "diversion"
    if prune_counts.get("no_exit"):
        parts.append(f"{prune_counts['no_exit']} 个状态没有几何可达的备降点")
        kind = "no_site" if not prune_counts.get("diversion") and not prune_counts.get("time") else kind
    if prune_counts.get("no_site"):
        parts.append(f"{prune_counts['no_site']} 个状态在到达时已无当前有效备降点（飞行中关闭）")
        kind = "no_site"
    if prune_counts.get("time"):
        parts.append(f"{prune_counts['time']} 个状态超出任务时限")
        if not any(prune_counts.get(k) for k in ("diversion", "no_exit", "no_site")):
            kind = "time"
    if parts:
        return "无可行路线：" + "；".join(parts) + "。未返回放宽约束后的路线。", kind
    if path_reason and ("终点" in path_reason or "起点周围" in path_reason or "上限" in path_reason):
        return path_reason, "geometry"
    return path_reason or "无可行路线", "geometry"


def _accept_state(
    grid: Grid,
    field_: DiversionField,
    vehicle: VehicleProfile,
    *,
    initial_energy_wh: float,
    reserve_wh: float,
    climb_wh: float,
    climb_time_s: float,
    time_limit_s: float | None,
    field_at: Callable[[float], DiversionField | None] | None = None,
):
    slack_m = grid.res_m * math.sqrt(2.0)
    speed = vehicle.cruise_speed_mps

    def accept(node: tuple[int, int], g_m: float) -> str | None:
        g_chk = g_m + slack_m
        t_s = climb_time_s + g_chk / speed
        if time_limit_s is not None and t_s > time_limit_s:
            return "time"
        active_field = field_at(t_s) if field_at is not None else field_
        if active_field is None:
            return "no_site"
        dist = float(active_field.dist_m[node[0], node[1]])
        if not math.isfinite(dist):
            return "no_exit"
        energy_left = initial_energy_wh - climb_wh - cruise_energy_wh(vehicle, g_chk)
        margin = energy_left - reserve_wh - cruise_energy_wh(vehicle, dist)
        if margin < -MARGIN_TOL_WH:
            return "diversion"
        return None

    return accept


def plan_scenario_with_diversion(
    scenario: dict,
    scene: Scene,
    vehicle: VehicleProfile,
    *,
    res_m: float = DEFAULT_RES_M,
    clearance_m: float = DEFAULT_CLEARANCE_M,
    sample_step_m: float = SAMPLE_STEP_M,
) -> ScenarioPlan:
    """带备降硬约束的场景规划。无解时 waypoints 为空，reason 说明原因。"""
    t0 = time.perf_counter()
    algorithm = "astar_diversion"
    initial, reserve = resolve_energy(scenario, vehicle)
    climb_delta = climb_delta_m(scenario)

    def elapsed() -> float:
        return (time.perf_counter() - t0) * 1000.0

    payload = scenario.get("payload_kg")
    if payload is not None and float(payload) > vehicle.max_payload_kg:
        return _empty_plan(
            algorithm,
            reason=(
                f"载荷 {float(payload):.2f} kg 超出机型最大载荷 {vehicle.max_payload_kg:.2f} kg，"
                "任务在规划阶段即不可行"
            ),
            kind="payload",
            elapsed_ms=elapsed(),
            initial=initial,
            reserve=reserve,
        )
    if initial < reserve:
        return _empty_plan(
            algorithm,
            reason=(
                f"初始能量 {initial:.1f} Wh 低于策略保留量 {reserve:.1f} Wh，"
                "起飞前已不满足备降约束（E_left - E_reserve < 0）"
            ),
            kind="energy",
            elapsed_ms=elapsed(),
            initial=initial,
            reserve=reserve,
        )

    sites, notes = active_landing_sites(scene, scenario, vehicle)
    grid = cached_grid(blockers_at_t0(scenario, scene), res_m=res_m, clearance_m=clearance_m)
    schedule = site_closure_schedule(scenario)
    field_at = make_field_at(grid, sites, schedule)
    field_ = field_at(0.0)
    pads = 0 if field_ is None else sum(len(_pad_cells(grid, site)) for site in sites)
    if pads == 0:
        detail = "；".join(notes) if notes else "没有备降点，或降落半径内没有可飞单元"
        return _empty_plan(
            algorithm,
            reason=f"无当前有效备降点。{detail}。不会返回一条没有退出方案的路线。",
            kind="no_site",
            elapsed_ms=elapsed(),
            initial=initial,
            reserve=reserve,
        )

    start = endpoint_xy(scenario, "origin")
    goal = endpoint_xy(scenario, "destination")
    start_cell = snap_to_free(grid, *start)
    initial_g = 0.0
    if start_cell is not None:
        cx, cy = grid.center(*start_cell)
        initial_g = math.hypot(start[0] - cx, start[1] - cy)
    climb_wh = climb_energy_wh(vehicle, climb_delta)
    climb_time = (climb_delta / vehicle.climb_rate_mps) if climb_delta > 0 else 0.0
    limit = scenario.get("time_limit_s")
    time_limit = None if limit is None else float(limit)

    path = plan(
        grid,
        start,
        goal,
        initial_g_m=initial_g,
        accept_state=_accept_state(
            grid,
            field_,
            vehicle,
            initial_energy_wh=initial,
            reserve_wh=reserve,
            climb_wh=climb_wh,
            climb_time_s=climb_time,
            time_limit_s=time_limit,
            field_at=field_at,
        ),
    )
    if not path.found:
        text, kind = _explain_prune(path.reason, path.prune_counts)
        return _empty_plan(
            algorithm,
            reason=text,
            kind=kind,
            elapsed_ms=elapsed(),
            initial=initial,
            reserve=reserve,
            pruned=path.pruned,
            expanded=path.nodes_expanded,
        )

    profile = profile_along_route(
        route_id=f"{scenario.get('id', 'adhoc')}:{algorithm}",
        waypoints=path.waypoints,
        grid=grid,
        field_=field_,
        vehicle=vehicle,
        initial_energy_wh=initial,
        reserve_wh=reserve,
        climb_delta=climb_delta,
        sample_step_m=sample_step_m,
        field_at=field_at,
    )
    if not profile.is_feasible:
        worst = profile.min_margin_wh
        return _empty_plan(
            algorithm,
            reason=(
                "航线在栅格搜索里通过了剪枝，但沿折线复算备降余量仍为负或出现无退出路径的采样点，"
                f"按无解处理，不返回该航线。最小余量 {worst} Wh"
            ),
            kind="diversion",
            elapsed_ms=elapsed(),
            initial=initial,
            reserve=reserve,
            pruned=path.pruned,
            expanded=path.nodes_expanded,
        )
    flight_time = _flight_time_s(vehicle, path.length_m, climb_delta)
    if time_limit is not None and flight_time > time_limit:
        return _empty_plan(
            algorithm,
            reason=f"预计飞行 {flight_time:.0f} s，超过时限 {time_limit:.0f} s，不返回超时航线",
            kind="time",
            elapsed_ms=elapsed(),
            initial=initial,
            reserve=reserve,
            pruned=path.pruned,
            expanded=path.nodes_expanded,
        )

    return ScenarioPlan(
        algorithm=algorithm,
        found=True,
        waypoints=path.waypoints,
        length_m=path.length_m,
        energy_used_wh=_energy_used(vehicle, path.length_m, climb_delta),
        elapsed_ms=elapsed(),
        reason=None,
        profile=profile,
        expanded=path.nodes_expanded,
        pruned=path.pruned,
        rejection_kind="",
        initial_energy_wh=initial,
        reserve_wh=reserve,
    )


def plan_baseline_annotated(
    scenario: dict,
    scene: Scene,
    vehicle: VehicleProfile,
    *,
    res_m: float = DEFAULT_RES_M,
    clearance_m: float = DEFAULT_CLEARANCE_M,
    sample_step_m: float = SAMPLE_STEP_M,
) -> ScenarioPlan:
    """几何基线。路线照旧返回；剖面可以是负的，调用方不要把它当成已通过约束。"""
    t0 = time.perf_counter()
    initial, reserve = resolve_energy(scenario, vehicle)
    climb_delta = climb_delta_m(scenario)
    sites, _notes = active_landing_sites(scene, scenario, vehicle)
    grid = cached_grid(blockers_at_t0(scenario, scene), res_m=res_m, clearance_m=clearance_m)
    schedule = site_closure_schedule(scenario)
    field_at = make_field_at(grid, sites, schedule)
    field_ = field_at(0.0) or cached_field(grid, sites)
    start = endpoint_xy(scenario, "origin")
    goal = endpoint_xy(scenario, "destination")
    path = plan(grid, start, goal)
    profile = None
    if path.found:
        profile = profile_along_route(
            route_id=f"{scenario.get('id', 'adhoc')}:astar_static",
            waypoints=path.waypoints,
            grid=grid,
            field_=field_,
            vehicle=vehicle,
            initial_energy_wh=initial,
            reserve_wh=reserve,
            climb_delta=climb_delta,
            sample_step_m=sample_step_m,
            field_at=field_at,
        )
    return ScenarioPlan(
        algorithm="astar_static",
        found=path.found,
        waypoints=path.waypoints if path.found else [],
        length_m=path.length_m if path.found else 0.0,
        energy_used_wh=_energy_used(vehicle, path.length_m, climb_delta) if path.found else 0.0,
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        reason=None if path.found else path.reason,
        profile=profile,
        expanded=path.nodes_expanded,
        pruned=0,
        rejection_kind="" if path.found else "geometry",
        initial_energy_wh=initial,
        reserve_wh=reserve,
    )


def hard_constraint_report(
    plan_out: ScenarioPlan,
    scenario: dict,
    vehicle: VehicleProfile,
) -> HardReport:
    """对一条已经生成的航线再算一遍硬约束。不读取规划器自报的 checks。

    这和搜索用的是同一套距离场（同一把尺子），还不是另一个人写的独立校验器。
    """
    if not plan_out.found:
        hard = 0 if plan_out.rejection_kind == "geometry" else 1
        return HardReport(
            feasible=False,
            hard_violations=hard,
            negative_margin_samples=0,
            reason=plan_out.reason or "无可行路线",
            flight_time_s=None,
            energy_used_wh=0.0,
        )

    reasons: list[str] = []
    categories = 0
    payload = scenario.get("payload_kg")
    if payload is not None and float(payload) > vehicle.max_payload_kg:
        categories += 1
        reasons.append(f"载荷 {float(payload):.2f} kg 超出机型最大载荷 {vehicle.max_payload_kg:.2f} kg")
    flight_time = _flight_time_s(vehicle, plan_out.length_m, climb_delta_m(scenario))
    limit = scenario.get("time_limit_s")
    if limit is not None and flight_time > float(limit):
        categories += 1
        reasons.append(f"预计飞行 {flight_time:.0f} s，超过时限 {float(limit):.0f} s")

    negative = 0
    if plan_out.profile is None or not plan_out.profile.is_feasible:
        categories += 1
        negative = 0 if plan_out.profile is None else plan_out.profile.negative_sample_count
        worst = None if plan_out.profile is None else plan_out.profile.min_margin_wh
        reasons.append(f"备降余量剖面不可行（负余量样本 {negative}，最小余量 {worst} Wh）")

    return HardReport(
        feasible=categories == 0,
        hard_violations=categories,
        negative_margin_samples=negative,
        reason="；".join(reasons),
        flight_time_s=flight_time,
        energy_used_wh=plan_out.energy_used_wh,
    )


def profile_record(scenario_id: str, plan_out: ScenarioPlan) -> dict:
    profile = plan_out.profile
    samples = []
    if profile is not None:
        for sample in profile.samples:
            samples.append(
                {
                    "s_m": round(sample.s_m, 3),
                    "t_s": round(sample.t_s, 3),
                    "margin_wh": round(sample.margin_wh, 4),
                    "energy_need_wh": None
                    if sample.energy_need_wh is None
                    else round(sample.energy_need_wh, 4),
                    "nearest_site_id": sample.nearest_site_id,
                }
            )
    return {
        "scenario_id": scenario_id,
        "algorithm": plan_out.algorithm,
        "found": plan_out.found,
        "reason": plan_out.reason,
        "length_m": round(plan_out.length_m, 3),
        "energy_used_wh": round(plan_out.energy_used_wh, 4),
        "min_margin_wh": None
        if profile is None or profile.min_margin_wh is None
        else round(profile.min_margin_wh, 4),
        "negative_sample_count": 0 if profile is None else profile.negative_sample_count,
        "is_feasible": False if profile is None else profile.is_feasible,
        "reserve_wh": plan_out.reserve_wh,
        "initial_energy_wh": plan_out.initial_energy_wh,
        "samples": samples,
    }


def main(argv: list[str] | None = None) -> int:
    """对照打印。默认使用示例机型，并在第一行标明不是真实平台数据。"""
    import sys
    from pathlib import Path

    from planner.scene import load_suite
    from sim.energy import load_vehicle

    example = Path(__file__).resolve().parents[1] / "scenarios" / "vehicles" / "example_not_real.yaml"
    args = argv if argv is not None else sys.argv[1:]
    vehicle_path = example
    selected: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--vehicle":
            vehicle_path = Path(args[i + 1])
            i += 2
            continue
        selected.append(args[i])
        i += 1
    wanted = set(selected) if selected else None

    vehicle = load_vehicle(vehicle_path)
    scene = shared_scene()
    suite = load_suite()
    print("=" * 88)
    if vehicle.is_example:
        print("  示例参数，非真实平台数据 —— 下面的能耗和余量不能写成实测或适航结论")
    else:
        print("  机型文件未声明 is_example。调用者自行对参数来源负责。")
    print(f"  机型 {vehicle.vehicle_key}  ·  {vehicle_path}")
    print("  基线只做几何；astar_diversion 在扩展时剪掉备降不可达的状态")
    print("=" * 88)
    header = f"{'场景':<8}{'基线m':>8}{'基线余量':>10}{'约束m':>8}{'约束余量':>10}  约束结论"
    print(header)
    n_both = 0
    n_base_only = 0
    n_div = 0
    for sc in suite["scenarios"]:
        if wanted is not None and sc["id"] not in wanted:
            continue
        base = plan_baseline_annotated(sc, scene, vehicle)
        div = plan_scenario_with_diversion(sc, scene, vehicle)
        base_len = f"{base.length_m:.0f}" if base.found else "-"
        div_len = f"{div.length_m:.0f}" if div.found else "-"
        base_m = (
            "-"
            if base.profile is None or base.profile.min_margin_wh is None
            else f"{base.profile.min_margin_wh:.1f}"
        )
        div_m = (
            "-"
            if div.profile is None or div.profile.min_margin_wh is None
            else f"{div.profile.min_margin_wh:.1f}"
        )
        if div.found:
            n_div += 1
            conclusion = "可行"
        else:
            conclusion = div.reason or "无解"
        if base.found and div.found:
            n_both += 1
        elif base.found and not div.found:
            n_base_only += 1
        print(f"{sc['id']:<8}{base_len:>8}{base_m:>10}{div_len:>8}{div_m:>10}  {conclusion}")
    print("-" * 88)
    print(f"约束搜索给出航线 {n_div}；两者都有航线 {n_both}；仅基线有航线（约束判无解或未采用）{n_base_only}")
    print(APPROXIMATION_NOTE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
