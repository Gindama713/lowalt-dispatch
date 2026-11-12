"""A* 基线（`astar_static`）。

这一版**只做几何可达**：避开建筑和"起飞时已知"的限制区，找一条最短路径。
不听时间、不算能量、不考虑备降——那些在 `planner/diversion.py`。
g 和启发都用米；以前 g 用格数、启发用米，最短路保证是坏的。

故意保持"笨"：它是基线 1，用来证明后面加的东西确实改变了结果。
基线如果自己就很聪明，消融实验就没有说服力了。

用法：
    python -m planner.astar                # 跑全部 20 个场景，打印对照表
    python -m planner.astar S2-01          # 只跑一个
"""

from __future__ import annotations

import heapq
import itertools
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from core.console import ensure_utf8_stdout
from core.geometry import polyline_length
from planner.grid import DEFAULT_CLEARANCE_M, DEFAULT_RES_M, Grid, build_grid, snap_to_free
from planner.scene import endpoint_xy, load_scene, load_suite, zones_known_at_t0

SQRT2 = math.sqrt(2.0)
NEIGHBORS = (
    (-1, 0, 1.0),
    (1, 0, 1.0),
    (0, -1, 1.0),
    (0, 1, 1.0),
    (-1, -1, SQRT2),
    (-1, 1, SQRT2),
    (1, -1, SQRT2),
    (1, 1, SQRT2),
)


@dataclass
class PathResult:
    found: bool
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    length_m: float = 0.0
    nodes_expanded: int = 0
    elapsed_ms: float = 0.0
    reason: str | None = None
    snapped: bool = False
    pruned: int = 0
    prune_counts: dict[str, int] = field(default_factory=dict)


# accept_state(cell, g_m) 返回 None 表示这个状态可以搜索；返回字符串则剪枝。
# 字符串是原因类别（如 "diversion"），由调用方翻译成可读说明。
AcceptState = Callable[[tuple[int, int], float], str | None]


def _heuristic(dy: int, dx: int, res_m: float) -> float:
    """八邻域可采纳启发：octile 距离，单位米。必须和 g 用同一单位。"""
    ady, adx = abs(dy), abs(dx)
    return res_m * ((ady + adx) + (SQRT2 - 2.0) * min(ady, adx))


def plan(
    grid: Grid,
    start_xy: tuple[float, float],
    goal_xy: tuple[float, float],
    *,
    max_expand: int = 500_000,
    initial_g_m: float = 0.0,
    accept_state: AcceptState | None = None,
) -> PathResult:
    t0 = time.perf_counter()

    def done(**kw) -> PathResult:
        return PathResult(elapsed_ms=(time.perf_counter() - t0) * 1000.0, **kw)

    s = snap_to_free(grid, *start_xy)
    g = snap_to_free(grid, *goal_xy)
    if s is None:
        return done(found=False, reason="起点周围没有可用单元（可能整块被障碍或限制区覆盖）")
    if g is None:
        return done(found=False, reason="终点周围没有可用单元（目的地可能在限制区内）")
    snapped = s != grid.to_ij(*start_xy) or g != grid.to_ij(*goal_xy)
    prune_counts: dict[str, int] = {}

    def reject(node: tuple[int, int], g_m: float) -> str | None:
        if accept_state is None:
            return None
        reason = accept_state(node, g_m)
        if reason is None:
            return None
        prune_counts[reason] = prune_counts.get(reason, 0) + 1
        return reason

    if s == g:
        g_exact = math.hypot(goal_xy[0] - start_xy[0], goal_xy[1] - start_xy[1])
        bad = reject(s, max(initial_g_m, g_exact))
        if bad is not None:
            return done(
                found=False,
                reason=f"起点不满足约束：{bad}",
                snapped=snapped,
                pruned=sum(prune_counts.values()),
                prune_counts=prune_counts,
            )
        return done(
            found=True,
            waypoints=[start_xy, goal_xy],
            length_m=polyline_length([start_xy, goal_xy]),
            snapped=snapped,
        )

    bad = reject(s, initial_g_m)
    if bad is not None:
        return done(
            found=False,
            reason=f"起点不满足约束：{bad}",
            snapped=snapped,
            pruned=sum(prune_counts.values()),
            prune_counts=prune_counts,
        )

    counter = itertools.count()
    h0 = _heuristic(g[0] - s[0], g[1] - s[1], grid.res_m)
    open_heap: list[tuple[float, float, int, int, int]] = [
        (initial_g_m + h0, initial_g_m, next(counter), s[0], s[1])
    ]
    g_score: dict[tuple[int, int], float] = {s: initial_g_m}
    parent: dict[tuple[int, int], tuple[int, int]] = {}
    closed: set[tuple[int, int]] = set()
    expanded = 0

    while open_heap:
        _, cost, _, iy, ix = heapq.heappop(open_heap)
        node = (iy, ix)
        if node in closed:
            continue
        if cost > g_score.get(node, math.inf):
            continue
        closed.add(node)
        expanded += 1

        if node == g:
            cells = [node]
            while cells[-1] in parent:
                cells.append(parent[cells[-1]])
            cells.reverse()
            pts = [grid.center(*c) for c in cells]
            pts[0] = start_xy
            pts[-1] = goal_xy
            return done(
                found=True,
                waypoints=pts,
                length_m=polyline_length(pts),
                nodes_expanded=expanded,
                snapped=snapped,
                pruned=sum(prune_counts.values()),
                prune_counts=prune_counts,
            )

        if expanded >= max_expand:
            return done(
                found=False,
                nodes_expanded=expanded,
                pruned=sum(prune_counts.values()),
                prune_counts=prune_counts,
                reason=f"超出扩展上限 {max_expand} 个节点，放弃",
            )

        for dy, dx, step in NEIGHBORS:
            ny, nx = iy + dy, ix + dx
            if not grid.free(ny, nx):
                continue
            if dy and dx:
                # 禁止切角：对角移动要求两个正交邻格也可用。
                # 否则两个单元中心之间的直线会擦着障碍拐角过去，
                # 栅格里看着"没碰"，连续几何里已经侵入净空。
                if not grid.free(iy + dy, ix) or not grid.free(iy, ix + dx):
                    continue
            nxt = (ny, nx)
            if nxt in closed:
                continue
            # g 用米。早期版本这里只加了 1 或 √2（格），启发却是米，
            # 等价于把启发放大了 res_m 倍，不再保证最短路。基线已改回同一单位。
            tentative = cost + step * grid.res_m
            if tentative >= g_score.get(nxt, math.inf):
                continue
            if reject(nxt, tentative) is not None:
                # 记下这次失败的到达代价，更长的路径不必再试；
                # 更短的路径仍会因为 tentative 更小而重新检查。
                g_score[nxt] = tentative
                continue
            g_score[nxt] = tentative
            parent[nxt] = node
            f = tentative + _heuristic(g[0] - ny, g[1] - nx, grid.res_m)
            heapq.heappush(open_heap, (f, tentative, next(counter), ny, nx))

    reason = "搜索空间耗尽，无可行路线"
    if prune_counts:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(prune_counts.items()))
        reason = f"无可行路线（约束剪枝：{detail}）"
    return done(
        found=False,
        nodes_expanded=expanded,
        pruned=sum(prune_counts.values()),
        prune_counts=prune_counts,
        reason=reason,
    )


# --------------------------------------------------------------------------- #
# 场景级封装：给一个场景，产出基线路线
# --------------------------------------------------------------------------- #
def plan_scenario(
    scenario: dict,
    scene,
    *,
    res_m: float = DEFAULT_RES_M,
    clearance_m: float = DEFAULT_CLEARANCE_M,
) -> tuple[PathResult, Grid]:
    blockers = list(scene.obstacles) + [z.polygon for z in zones_known_at_t0(scenario, scene)]
    grid = build_grid(blockers, res_m=res_m, clearance_m=clearance_m)
    start = endpoint_xy(scenario, "origin")
    goal = endpoint_xy(scenario, "destination")
    return plan(grid, start, goal), grid


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdout()
    import sys

    args = argv if argv is not None else sys.argv[1:]
    wanted = set(args) if args else None

    scene = load_scene()
    suite = load_suite()

    print("=" * 78)
    print("  A* 基线（astar_static）—— 仅几何可达：避建筑 + 避开起飞时已知的限制区")
    print("  不判时限、不算能量、不考虑备降。这些由后续版本加。")
    print("=" * 78)
    header = f"{'场景':<9}{'找到':>6}{'航程m':>9}{'直线m':>9}{'绕行':>8}{'扩展':>8}{'耗时ms':>8}  说明"
    print(header)
    print("-" * 78)

    n_found = 0
    total = 0
    for sc in suite["scenarios"]:
        if wanted is not None and sc["id"] not in wanted:
            continue
        total += 1
        res, _grid = plan_scenario(sc, scene)
        sx, sy = endpoint_xy(sc, "origin")
        gx, gy = endpoint_xy(sc, "destination")
        straight = math.hypot(gx - sx, gy - sy)
        if res.found:
            n_found += 1
            detour = res.length_m / straight - 1.0 if straight > 0 else 0.0
            print(
                f"{sc['id']:<9}{'是':>6}{res.length_m:>9.0f}{straight:>9.0f}"
                f"{detour * 100:>7.0f}%{res.nodes_expanded:>8}{res.elapsed_ms:>8.0f}  —"
            )
        else:
            print(
                f"{sc['id']:<9}{'否':>6}{'-':>9}{straight:>9.0f}{'-':>8}"
                f"{res.nodes_expanded:>8}{res.elapsed_ms:>8.0f}  {res.reason}"
            )

    print("-" * 78)
    print(f"找到路线 {n_found}/{total}")
    print("\n注意：S4-02（时限 90 s）与 S4-03（备降点全关）在本版本仍会返回路线——")
    print("      基线不认识时间和备降，这正是带约束版本要补的缺口，不是 bug。")
    print("对照：python -m planner.diversion")
    print("      默认使用 scenarios/vehicles/example_not_real.yaml，示例参数，不是真实平台数据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
