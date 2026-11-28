"""Local WGS84 routes through fetched building footprints and restriction zones, never v0 geometry.

Buildings and enforced restriction zones are avoided horizontally at every height:
tagged or estimated heights and incomplete zone altitude/time metadata do not grant
permission to overfly or penetrate them. Missing official airspace and terrain
remain explicit limitations in the service. No flight commands are produced.
"""

from __future__ import annotations

import math
import time
from itertools import pairwise

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.strtree import STRtree

from core.geometry import geographic_grid_clearance_m, polyline_length
from planner.astar import plan
from planner.georef import distance_m, enu_to_wgs84, wgs84_to_enu
from planner.grid import Grid

MAX_GRID_CELLS = 8_000_000
PLANNING_BUDGET_S = 28.0


def _check_deadline(deadline):
    if deadline is not None and time.perf_counter() >= deadline:
        raise TimeoutError("真实几何规划达到处理时间预算，未发布未完成校验的路线")


def _project_geometry(geometry: dict, origin: tuple[float, float], *, label: str = "建筑"):
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    if kind not in {"Polygon", "MultiPolygon"} or not coords:
        raise ValueError(f"{label}几何必须为非空 Polygon 或 MultiPolygon")
    polygons = [coords] if kind == "Polygon" else coords
    converted = []
    for rings in polygons:
        projected = [[wgs84_to_enu(origin, tuple(p[:2])) for p in ring] for ring in rings]
        if any(len(ring) < 4 or ring[0] != ring[-1] for ring in projected):
            raise ValueError(f"{label}环未闭合或顶点不足，拒绝忽略该障碍物")
        converted.append(Polygon(projected[0], projected[1:]))
    result = converted[0] if kind == "Polygon" else MultiPolygon(converted)
    if result.is_empty or not result.is_valid:
        raise ValueError(f"{label}几何无效，需修复数据后再规划")
    return result


def _mark_blocked(blocked, polygons, bounds, resolution_m, exclusion_m, *, deadline=None):
    x0, y0, _x1, _y1 = bounds
    ny, nx = blocked.shape
    for index, polygon in enumerate(polygons):
        if index % 64 == 0:
            _check_deadline(deadline)
        left, bottom, right, top = polygon.bounds
        ix0 = max(0, math.floor((left - exclusion_m - x0) / resolution_m))
        ix1 = min(nx, math.ceil((right + exclusion_m - x0) / resolution_m))
        iy0 = max(0, math.floor((bottom - exclusion_m - y0) / resolution_m))
        iy1 = min(ny, math.ceil((top + exclusion_m - y0) / resolution_m))
        if ix0 >= ix1 or iy0 >= iy1:
            continue
        xs = x0 + (np.arange(ix0, ix1) + 0.5) * resolution_m
        # Bound vectorized batches as well as total cells: a single large
        # footprint must not allocate millions of Shapely points or hide a
        # deadline overrun until its entire rasterization has completed.
        rows_per_batch = max(1, min(128, 65536 // (ix1 - ix0)))
        for row in range(iy0, iy1, rows_per_batch):
            _check_deadline(deadline)
            stop = min(row + rows_per_batch, iy1)
            ys = y0 + (np.arange(row, stop) + 0.5) * resolution_m
            xx, yy = np.meshgrid(xs, ys)
            # Measure original geometry: even a 1 m building between centres
            # contributes to the mask; holes retain their actual geometry.
            blocked[row:stop, ix0:ix1] |= shapely.dwithin(shapely.points(xx, yy), polygon, exclusion_m)


def _rasterize(
    building_polygons,
    bounds,
    resolution_m,
    building_exclusion_m,
    *,
    zone_polygons=(),
    zone_exclusion_m: float = 0.0,
    deadline=None,
):
    x0, y0, x1, y1 = bounds
    nx, ny = math.floor((x1 - x0) / resolution_m), math.floor((y1 - y0) / resolution_m)
    if nx <= 0 or ny <= 0 or nx * ny > MAX_GRID_CELLS:
        raise ValueError("真实场景超出网格预算，请缩短任务范围或调整分辨率")
    blocked = np.zeros((ny, nx), dtype=bool)
    _mark_blocked(blocked, building_polygons, bounds, resolution_m, building_exclusion_m, deadline=deadline)
    if zone_polygons:
        _mark_blocked(blocked, zone_polygons, bounds, resolution_m, zone_exclusion_m, deadline=deadline)
    _check_deadline(deadline)
    return Grid(resolution_m, x0, y0, building_exclusion_m, blocked)


def _collapse(points):
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


def _zone_hits(geometry, zone_tree: STRtree | None, zone_buffer_m: float):
    """Closed zone conflict check: boundary touch and interior/buffer intrusion both conflict."""
    if zone_tree is None:
        return ()
    if zone_buffer_m <= 0.0:
        return zone_tree.query(geometry, predicate="intersects")
    return zone_tree.query(geometry, predicate="dwithin", distance=zone_buffer_m)


def _segment_clear(
    segment: LineString,
    building_tree: STRtree,
    coverage,
    building_clearance_m: float,
    zone_tree: STRtree | None,
    zone_buffer_m: float,
) -> bool:
    if not coverage.covers(segment):
        return False
    if len(building_tree.query(segment, predicate="dwithin", distance=building_clearance_m)):
        return False
    if len(_zone_hits(segment, zone_tree, zone_buffer_m)):
        return False
    return True


def _simplify_visible(
    points,
    building_tree,
    coverage,
    clearance_m,
    *,
    zone_tree: STRtree | None = None,
    zone_buffer_m: float = 0.0,
    deadline=None,
):
    """Remove turns only when the complete replacement segment is verified.

    A linear greedy visibility pass keeps long staircase grid routes readable;
    unlike Douglas-Peucker it cannot cut a corner through a building or
    restriction zone. It is conservative: visibility need not be monotonic.
    """
    if len(points) < 3:
        return points
    output = [points[0]]
    previous = points[1]
    for index, point in enumerate(points[2:]):
        if index % 64 == 0:
            _check_deadline(deadline)
        segment = LineString([output[-1], point])
        if not _segment_clear(segment, building_tree, coverage, clearance_m, zone_tree, zone_buffer_m):
            output.append(previous)
        previous = point
    if previous != output[-1]:
        output.append(previous)
    return output


def _connect_endpoint(
    grid,
    point,
    building_tree,
    coverage,
    clearance_m,
    *,
    zone_tree: STRtree | None = None,
    zone_buffer_m: float = 0.0,
):
    """Connect a physically clear exact endpoint to the conservative grid.

    This does not relocate the endpoint: the verified connector is prepended or
    appended to the returned route. A coarse exclusion mask can otherwise reject
    a location that meets physical clearance solely due to discretization.
    """
    iy, ix = grid.to_ij(*point)
    if grid.free(iy, ix):
        centre = grid.center(iy, ix)
        connector = LineString([point, centre])
        if _segment_clear(connector, building_tree, coverage, clearance_m, zone_tree, zone_buffer_m):
            return centre
    candidates = []
    for dy in range(-4, 5):
        for dx in range(-4, 5):
            if not grid.free(iy + dy, ix + dx):
                continue
            centre = grid.center(iy + dy, ix + dx)
            candidates.append((math.dist(point, centre), centre))
    for _, centre in sorted(candidates):
        line = LineString([point, centre])
        if _segment_clear(line, building_tree, coverage, clearance_m, zone_tree, zone_buffer_m):
            return centre
    return None


def plan_real_route(
    origin: tuple[float, float],
    destination: tuple[float, float],
    obstacles_fc: dict,
    *,
    resolution_m: float = 10.0,
    physical_clearance_m: float = 20.0,
    zone_buffer_m: float = 0.0,
    max_expand: int = 500_000,
    heuristic_weight: float = 1.50,
    budget_s: float = PLANNING_BUDGET_S,
    exclusions_fc: dict | None = None,
) -> dict:
    """Plan with exact endpoints, then independently verify continuous clearance.

    ``bbox`` is WGS84 [west,south,east,north] for the successfully fetched data.
    The search rectangle is endpoint bounds + 1000 m intersected with that bbox,
    inset by the exclusion radius so an unobserved building outside the fetched
    area cannot be treated as known empty space. No snapping or straight-line
    fallback is permitted. Weighted A* deliberately makes no shortest-path claim.
    """
    began = time.perf_counter()
    if not math.isfinite(budget_s) or budget_s <= 0:
        raise ValueError("规划时间预算必须为有限正数")
    if not math.isfinite(zone_buffer_m) or zone_buffer_m < 0 or zone_buffer_m > 500:
        raise ValueError("限制区项目缓冲距离须在 0 至 500 米之间")
    deadline = began + budget_s
    stage_started = began
    stage_name = "geometry_projection"
    stage_timings = {}

    def next_stage(name):
        nonlocal stage_started, stage_name
        now = time.perf_counter()
        stage_timings[stage_name] = (now - stage_started) * 1000
        stage_started, stage_name = now, name

    exclusion_m = geographic_grid_clearance_m(resolution_m, physical_clearance_m)
    zone_exclusion_m = (
        geographic_grid_clearance_m(resolution_m, zone_buffer_m)
        if zone_buffer_m > 0
        else math.hypot(resolution_m / 2.0, resolution_m / 2.0)
    ) + 1e-6
    length = distance_m(origin, destination)
    if length < 10 or length > 100_000:
        raise ValueError("真实任务起终点距离须在 10 米至 100 千米之间")
    if abs(origin[0] - destination[0]) > 180:
        raise ValueError("当前局部规划不支持跨日界线航线")
    reference = ((origin[0] + destination[0]) / 2, (origin[1] + destination[1]) / 2)
    start, goal = wgs84_to_enu(reference, origin), wgs84_to_enu(reference, destination)
    bbox = obstacles_fc.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError("缺少真实障碍物覆盖 bbox，无法证明搜索区域已获取数据")
    west, south = wgs84_to_enu(reference, (bbox[0], bbox[1]))
    east, north = wgs84_to_enu(reference, (bbox[2], bbox[3]))
    if west >= east or south >= north:
        raise ValueError("障碍物覆盖 bbox 非法")
    bounds = (
        max(min(start[0], goal[0]) - 1000, west + exclusion_m),
        max(min(start[1], goal[1]) - 1000, south + exclusion_m),
        min(max(start[0], goal[0]) + 1000, east - exclusion_m),
        min(max(start[1], goal[1]) + 1000, north - exclusion_m),
    )
    building_features = obstacles_fc.get("features")
    if obstacles_fc.get("type") != "FeatureCollection" or not isinstance(building_features, list):
        raise ValueError("障碍物必须为 FeatureCollection")
    zone_features: list[dict] = []
    if exclusions_fc is not None:
        if exclusions_fc.get("type") != "FeatureCollection" or not isinstance(
            exclusions_fc.get("features"), list
        ):
            raise ValueError("限制区必须为 FeatureCollection")
        zone_features = list(exclusions_fc["features"])
    coverage_status = obstacles_fc.get("coverage_status")
    warnings = [
        "全部建筑按足迹保守绕行；高度标签和估算高度均不用于允许越顶。",
        "局部等距圆柱投影为近似米制坐标；加权 A* 不保证最短路线。",
        "仅避让已获取的 OSM 建筑；OSM 覆盖完整性、地形、线缆及官方空域未验证。",
    ]
    if zone_features:
        warnings.append(
            f"本次纳入 {len(zone_features)} 个禁飞/内部管制区作二维全高度保守避让"
            f"（项目边界缓冲 {zone_buffer_m:g} m，边界接触判为冲突；非民航法定标准）。"
        )
    if coverage_status == "queried_empty":
        warnings.append("本次查询成功但范围内没有 OSM 已登记建筑；这不是现场无障碍，也不能作为运营通过。")
    elif not building_features:
        warnings.append("该覆盖范围未返回建筑记录；不代表现实中没有建筑。")
    base = {
        "found": False,
        "waypoints": [],
        "length_m": 0.0,
        "clearance_m": physical_clearance_m,
        "grid_clearance_m": exclusion_m,
        "zone_buffer_m": zone_buffer_m,
        "zone_grid_clearance_m": zone_exclusion_m if zone_features else 0.0,
        "enforced_zone_count": len(zone_features),
        "resolution_m": resolution_m,
        "nodes_expanded": 0,
        "elapsed_ms": 0.0,
        "reason": None,
        "warnings": warnings,
        "projection_origin": reference,
        "heuristic_weight": heuristic_weight,
    }

    def done(**changes):
        now = time.perf_counter()
        return (
            base
            | changes
            | {
                "elapsed_ms": (now - began) * 1000,
                "stage_timings_ms": stage_timings | {stage_name: (now - stage_started) * 1000},
            }
        )

    if coverage_status in {"partial", "timeout", "expired", "not_queried"}:
        warnings.append("局部失效、超时、过期或未查询不能以空障碍列表产生通过结果。")
        return done(reason="障碍覆盖不完整、过期、超时或未查询，拒绝以空列表发布可通过结果")

    building_polygons = []
    for index, feature in enumerate(building_features):
        if index % 64 == 0 and time.perf_counter() >= deadline:
            return done(reason="建筑几何投影达到处理时间预算，未使用部分障碍数据规划")
        try:
            building_polygons.append(_project_geometry(feature["geometry"], reference, label="建筑"))
        except (ValueError, TypeError, KeyError) as exc:
            identity = (feature.get("properties") or {}).get("id", f"feature-{index}")
            raise ValueError(f"建筑 {identity} 的真实几何不可用：{exc}") from exc

    zone_polygons = []
    zone_meta = []
    for index, feature in enumerate(zone_features):
        if index % 32 == 0 and time.perf_counter() >= deadline:
            return done(reason="限制区几何投影达到处理时间预算，未使用部分约束规划")
        props = feature.get("properties") or {}
        zid = str(props.get("id") or f"zone-{index}")
        zname = str(props.get("name") or zid)
        try:
            zone_polygons.append(_project_geometry(feature["geometry"], reference, label="限制区"))
            zone_meta.append({"id": zid, "name": zname, "kind": props.get("kind", "restricted")})
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"限制区 {zid} 的几何不可用：{exc}") from exc

    next_stage("spatial_index")
    building_tree = STRtree(building_polygons)
    zone_tree = STRtree(zone_polygons) if zone_polygons else None
    if time.perf_counter() >= deadline:
        return done(reason="空间索引达到处理时间预算，未发布未经完整处理的路线")
    coverage = box(*bounds)
    if any(not coverage.contains(Point(p)) for p in (start, goal)):
        return done(reason="起终点超出已获取障碍物覆盖范围（含净空边界），需重新获取数据")

    if zone_tree is not None:
        for endpoint_key, endpoint_label, pt in (
            ("origin", "起点", start),
            ("destination", "终点", goal),
        ):
            hits = _zone_hits(Point(pt), zone_tree, zone_buffer_m)
            if len(hits):
                zinfo = zone_meta[int(hits[0])]
                return done(
                    reason=(
                        f"{endpoint_label}位于限制区「{zinfo['name']}」（{zinfo['id']}）"
                        "或其项目缓冲范围内，拒绝规划；未移动端点"
                    ),
                    endpoint_zone_conflict={"endpoint": endpoint_key, **zinfo},
                )

    if any(
        len(building_tree.query(Point(p), predicate="dwithin", distance=physical_clearance_m))
        for p in (start, goal)
    ):
        return done(reason="起点或终点位于建筑足迹或物理净空内，请选择实际可用的起降点；未移动端点")

    next_stage("rasterization")
    try:
        grid = _rasterize(
            building_polygons,
            bounds,
            resolution_m,
            exclusion_m,
            zone_polygons=zone_polygons,
            zone_exclusion_m=zone_exclusion_m,
            deadline=deadline,
        )
    except TimeoutError as exc:
        return done(reason=str(exc))
    next_stage("endpoint_connectors")
    search_start = _connect_endpoint(
        grid,
        start,
        building_tree,
        coverage,
        physical_clearance_m,
        zone_tree=zone_tree,
        zone_buffer_m=zone_buffer_m,
    )
    search_goal = _connect_endpoint(
        grid,
        goal,
        building_tree,
        coverage,
        physical_clearance_m,
        zone_tree=zone_tree,
        zone_buffer_m=zone_buffer_m,
    )
    if search_start is None or search_goal is None:
        return done(
            reason="端点无法以满足物理净空与限制区边界的连续线段接入网格，请选择开阔起降点或更细分辨率；未移动端点"
        )
    connector_lengths = [math.dist(start, search_start), math.dist(goal, search_goal)]
    if any(connector_lengths):
        warnings.append("端点以连续几何验证的连接段接入保守网格；航线仍保留原始起终点，未移动地点。")
    remaining = deadline - time.perf_counter()
    if remaining <= 0:
        return done(reason="障碍栅格化超出时间预算，请缩小任务范围")
    next_stage("astar_search")
    result = plan(
        grid,
        search_start,
        search_goal,
        max_expand=max_expand,
        heuristic_weight=heuristic_weight,
        max_seconds=remaining,
    )
    if not result.found or result.snapped:
        reason = result.reason or "端点被占用；未移动端点"
        if zone_polygons and ("无可行" in reason or "耗尽" in reason):
            reason = f"受限制区与建筑约束阻断，无可行绕行通道（{reason}）；未使用直线替代，未移动端点"
        return done(nodes_expanded=result.nodes_expanded, reason=reason)
    next_stage("route_simplification")
    points = result.waypoints
    if search_start != start:
        points = [start, *points]
    if search_goal != goal:
        points = [*points, goal]
    try:
        _check_deadline(deadline)
        route = _simplify_visible(
            _collapse(points),
            building_tree,
            coverage,
            physical_clearance_m,
            zone_tree=zone_tree,
            zone_buffer_m=zone_buffer_m,
            deadline=deadline,
        )
    except TimeoutError as exc:
        return done(nodes_expanded=result.nodes_expanded, reason=str(exc))
    if len(route) > 1000:
        return done(
            nodes_expanded=result.nodes_expanded,
            reason="航路超过 1000 个航点，请缩小范围或分段规划；未截断路线",
        )
    next_stage("continuous_validation")
    # Independent continuous check, including both exact endpoint connectors.
    for index, (a, b) in enumerate(pairwise(route)):
        if index % 64 == 0 and time.perf_counter() >= deadline:
            return done(
                nodes_expanded=result.nodes_expanded,
                reason="连续净空复核达到处理时间预算，未发布部分校验路线",
            )
        line = LineString([a, b])
        if not coverage.covers(line) or len(
            building_tree.query(line, predicate="dwithin", distance=physical_clearance_m - 1e-7)
        ):
            return done(
                nodes_expanded=result.nodes_expanded, reason="独立连续几何净空复核失败，未发布候选路线"
            )
        zone_hit = _zone_hits(line, zone_tree, zone_buffer_m)
        if len(zone_hit):
            zinfo = zone_meta[int(zone_hit[0])]
            return done(
                nodes_expanded=result.nodes_expanded,
                reason=f"独立连续空域边界复核失败：航段与限制区「{zinfo['name']}」（{zinfo['id']}）冲突，未发布路线",
            )
    geographic_route = [enu_to_wgs84(reference, p) for p in route]
    geographic_route[0], geographic_route[-1] = origin, destination
    return done(
        found=True,
        waypoints=geographic_route,
        length_m=polyline_length(route),
        nodes_expanded=result.nodes_expanded,
        continuous_clearance_verified=True,
        continuous_zone_verified=True,
        grid_shape=[grid.ny, grid.nx],
        endpoint_connector_lengths_m=connector_lengths,
    )
