"""独立校验器自己的「可飞最短逃逸距离」距离场。

为什么自己再写一份，而不是 import planner 的距离场
--------------------------------------------------
`validator/checks.py` 的独立性要求里明写「不复用规划器的栅格」。但
「从某个位置飞到最近可用备降点、避开障碍之后要走多远」是**几何事实**，
不是判定结论：它必须和规划器用同一个口径（障碍约束下的最短可飞路径），
否则校验器拿欧氏直线穿过建筑，会系统性低估备降能耗，把不安全的航线
判成安全（实测最大低估 189.7 m，见事实文档 2026-11-15 节）。

所以这里用 `core.geometry` 的多边形原语自己建栅格、自己跑多源 Dijkstra，
不 import `planner` 的任何实现。共享的只有几何原语和栅格常数；
采样密度、时窗、余量公式、通过与否的判定仍在 `checks.py` 里各写一遍。
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np

from core.geometry import (
    GRID_BOUNDS,
    GRID_CLEARANCE_M,
    GRID_RES_M,
    Polygon,
    dilate_circular,
    polygon_mask,
)

_NEIGHBORS = (
    (-1, 0, 1.0),
    (1, 0, 1.0),
    (0, -1, 1.0),
    (0, 1, 1.0),
    (-1, -1, math.sqrt(2.0)),
    (-1, 1, math.sqrt(2.0)),
    (1, -1, math.sqrt(2.0)),
    (1, 1, math.sqrt(2.0)),
)


@dataclass(frozen=True)
class EscapeSite:
    """一个备降点的几何信息。时窗与占用状态由调用方判，这里只管几何。"""

    site_id: str
    x_m: float
    y_m: float
    radius_m: float
    alt_m: float = 0.0


@dataclass
class EscapeField:
    dist_m: np.ndarray
    nearest_index: np.ndarray
    site_ids: list[str]
    blocked: np.ndarray
    x0: float
    y0: float
    res_m: float

    @property
    def nx(self) -> int:
        return self.blocked.shape[1]

    @property
    def ny(self) -> int:
        return self.blocked.shape[0]

    def lookup(self, x: float, y: float) -> tuple[float, int]:
        """返回 (到最近可达备降点的可飞距离 m, 站点下标)；不可达为 (inf, -1)。"""
        iy = int((y - self.y0) // self.res_m)
        ix = int((x - self.x0) // self.res_m)
        if not (0 <= iy < self.ny and 0 <= ix < self.nx):
            return math.inf, -1
        if self.blocked[iy, ix]:
            cell = self._snap_to_free(iy, ix)
            if cell is None:
                return math.inf, -1
            iy, ix = cell
        d = float(self.dist_m[iy, ix])
        idx = int(self.nearest_index[iy, ix])
        if idx < 0 or not math.isfinite(d):
            return math.inf, -1
        return d, idx

    def _snap_to_free(self, iy: int, ix: int, max_rings: int = 2) -> tuple[int, int] | None:
        for r in range(1, max_rings + 1):
            best: tuple[int, int, int] | None = None
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dy), abs(dx)) != r:
                        continue
                    cy, cx = iy + dy, ix + dx
                    if not (0 <= cy < self.ny and 0 <= cx < self.nx) or self.blocked[cy, cx]:
                        continue
                    score = dy * dy + dx * dx
                    if best is None or score < best[0]:
                        best = (score, cy, cx)
            if best is not None:
                return best[1], best[2]
        return None


def _pad_cells(
    shape: tuple[int, int],
    x0: float,
    y0: float,
    res_m: float,
    blocked: np.ndarray,
    site: EscapeSite,
) -> list[tuple[int, int]]:
    ny, nx = shape
    if site.radius_m <= 0:
        return []
    r = site.radius_m
    ix0 = int(math.floor((site.x_m - r - x0) / res_m))
    ix1 = int(math.floor((site.x_m + r - x0) / res_m))
    iy0 = int(math.floor((site.y_m - r - y0) / res_m))
    iy1 = int(math.floor((site.y_m + r - y0) / res_m))
    cells: list[tuple[int, int]] = []
    r2 = r * r
    for iy in range(max(0, iy0), min(ny, iy1 + 1)):
        for ix in range(max(0, ix0), min(nx, ix1 + 1)):
            if blocked[iy, ix]:
                continue
            cx = x0 + (ix + 0.5) * res_m
            cy = y0 + (iy + 0.5) * res_m
            if (cx - site.x_m) ** 2 + (cy - site.y_m) ** 2 <= r2:
                cells.append((iy, ix))
    return cells


def build_escape_field(
    blockers: list[Polygon],
    sites: list[EscapeSite],
    *,
    res_m: float = GRID_RES_M,
    clearance_m: float = GRID_CLEARANCE_M,
    bounds: tuple[float, float, float, float] = GRID_BOUNDS,
) -> EscapeField:
    """多源 Dijkstra：每个格子记下到最近可达备降点的八邻域最短路长度（米）。

    进入降落半径即视为到达，代价记 0 —— 与规划器同一口径。
    `blockers` 由调用方决定（校验器传建筑 + 限制区），本函数不做任何判定。
    """
    if res_m <= 0:
        raise ValueError("res_m 必须为正")
    x0, y0, x1, y1 = bounds
    nx = int(round((x1 - x0) / res_m))
    ny = int(round((y1 - y0) / res_m))
    if nx <= 0 or ny <= 0:
        raise ValueError("栅格尺寸非法")

    xs = x0 + (np.arange(nx) + 0.5) * res_m
    ys = y0 + (np.arange(ny) + 0.5) * res_m
    xg, yg = np.meshgrid(xs, ys)
    raw = np.zeros((ny, nx), dtype=bool)
    for poly in blockers:
        raw |= polygon_mask(xg, yg, poly)
    radius_cells = int(np.ceil(clearance_m / res_m))
    blocked = dilate_circular(raw, radius_cells) if blockers else raw

    dist = np.full((ny, nx), np.inf, dtype=np.float64)
    nearest = np.full((ny, nx), -1, dtype=np.int32)
    heap: list[tuple[float, int, int]] = []
    site_ids: list[str] = []
    for si, site in enumerate(sites):
        site_ids.append(site.site_id)
        for iy, ix in _pad_cells((ny, nx), x0, y0, res_m, blocked, site):
            if dist[iy, ix] <= 0.0:
                continue
            dist[iy, ix] = 0.0
            nearest[iy, ix] = si
            heapq.heappush(heap, (0.0, iy, ix))

    while heap:
        d, iy, ix = heapq.heappop(heap)
        if d != dist[iy, ix]:
            continue
        sid = int(nearest[iy, ix])
        for dy, dx, step in _NEIGHBORS:
            cy, cx = iy + dy, ix + dx
            if not (0 <= cy < ny and 0 <= cx < nx) or blocked[cy, cx]:
                continue
            nd = d + step * res_m
            if nd < dist[cy, cx]:
                dist[cy, cx] = nd
                nearest[cy, cx] = sid
                heapq.heappush(heap, (nd, cy, cx))

    return EscapeField(
        dist_m=dist,
        nearest_index=nearest,
        site_ids=site_ids,
        blocked=blocked,
        x0=x0,
        y0=y0,
        res_m=res_m,
    )
