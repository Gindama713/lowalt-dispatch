"""几何原语：只有数学，没有判定。

放在 `core/` 而不是 `planner/` 是有意的：规划器和校验器必须用**同一把尺子**
（同一个多边形判定、同一套长度计算），否则两边算出的东西没法比。
但**判定逻辑必须各写一遍**——共享尺子，不共享结论。

这里不允许出现"这条路线可行吗"这类问题的答案。
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np

Point = tuple[float, float]
Polygon = list[Point]

# 栅格离散化参数。规划器与独立校验器必须共用同一组数字，否则同一段几何会
# 被量出两个长度，校验结论就失去了可比性。
# GRID_CLEARANCE_M = 20 m 物理净空 + 10 m 离散化裕量（半格误差 + 八邻域切角），
# 推导见 planner/grid.py 的模块 docstring。
GRID_RES_M = 10.0
GRID_CLEARANCE_M = 30.0
GRID_BOUNDS = (0.0, 0.0, 3000.0, 3000.0)  # x0, y0, x1, y1


# --------------------------------------------------------------------------- #
# 多边形
# --------------------------------------------------------------------------- #
def rect_polygon(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    """左下-右上角点转成逆时针四边形。"""
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def rect_from_center(cx: float, cy: float, half: float) -> Polygon:
    return rect_polygon(cx - half, cy - half, cx + half, cy + half)


def polygon_mask(xs: np.ndarray, ys: np.ndarray, poly: Polygon) -> np.ndarray:
    """向量化的射线交叉法：xs/ys 为同形状网格点坐标，返回同形状 bool 掩膜。"""
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    inside = np.zeros(xs.shape, dtype=bool)
    n = len(poly)
    for k in range(n):
        x1, y1 = poly[k]
        x2, y2 = poly[(k + 1) % n]
        if y1 == y2:
            continue
        straddles = (y1 > ys) != (y2 > ys)
        x_cross = x1 + (ys - y1) * (x2 - x1) / (y2 - y1)
        inside ^= straddles & (xs < x_cross)
    return inside


def point_in_polygon(x: float, y: float, poly: Polygon) -> bool:
    """单点版本。校验器应该用这个而不是复用网格掩膜——
    网格是规划器的中间结果，校验器要自己判。"""
    n = len(poly)
    inside = False
    for k in range(n):
        x1, y1 = poly[k]
        x2, y2 = poly[(k + 1) % n]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def polygon_bbox(poly: Polygon) -> tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _dist_point_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0.0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    return ((px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2) ** 0.5


def distance_point_to_polygon(x: float, y: float, poly: Polygon) -> float:
    """点到多边形边界的最小距离；点在多边形内部时返回 0（内部视为距离零）。

    校验器用它来判断安全净空。注意这类"距离"是几何事实，
    至于"小于多少算违规"是判定，必须由调用方自己定。
    """
    if point_in_polygon(x, y, poly):
        return 0.0
    n = len(poly)
    return min(
        _dist_point_to_segment(x, y, poly[k][0], poly[k][1], poly[(k + 1) % n][0], poly[(k + 1) % n][1])
        for k in range(n)
    )


def bbox_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


# --------------------------------------------------------------------------- #
# 折线
# --------------------------------------------------------------------------- #
def polyline_length(pts: list[Point]) -> float:
    return sum(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 for (x1, y1), (x2, y2) in pairwise(pts))


def sample_polyline(pts: list[Point], step_m: float) -> list[tuple[float, Point]]:
    """按弧长采样，返回 [(s, (x, y)), ...]。s 是累计距离，首个点 s=0。

    规划器和校验器都能用这个遍历路线，但**各自决定采多密、采完之后干什么**。
    """
    if step_m <= 0:
        raise ValueError("step_m 必须为正")
    if len(pts) < 2:
        return [(0.0, pts[0])] if pts else []

    out: list[tuple[float, Point]] = [(0.0, pts[0])]
    s = 0.0
    next_s = step_m
    for (x1, y1), (x2, y2) in pairwise(pts):
        seg = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        if seg == 0:
            continue
        while next_s <= s + seg:
            t = (next_s - s) / seg
            out.append((next_s, (x1 + t * (x2 - x1), y1 + t * (y2 - y1))))
            next_s += step_m
        s += seg
    return out


# --------------------------------------------------------------------------- #
# 栅格位移与膨胀（供 planner 用，validator 不该依赖它）
# --------------------------------------------------------------------------- #
def shift_mask(mask: np.ndarray, di: int, dj: int) -> np.ndarray:
    """out[i, j] = mask[i - di, j - dj]，越界补 False。"""
    out = np.zeros_like(mask)
    ny, nx = mask.shape
    i_src = slice(max(0, -di), min(ny, ny - di))
    i_dst = slice(max(0, di), min(ny, ny + di))
    j_src = slice(max(0, -dj), min(nx, nx - dj))
    j_dst = slice(max(0, dj), min(nx, nx + dj))
    out[i_dst, j_dst] = mask[i_src, j_src]
    return out


def dilate_circular(mask: np.ndarray, radius_cells: int) -> np.ndarray:
    """圆形结构元膨胀，用于把障碍按安全净空加厚。"""
    if radius_cells <= 0:
        return mask.copy()
    out = np.zeros_like(mask)
    r = int(radius_cells)
    for di in range(-r, r + 1):
        for dj in range(-r, r + 1):
            if di * di + dj * dj > r * r:
                continue
            out |= shift_mask(mask, di, dj)
    return out
