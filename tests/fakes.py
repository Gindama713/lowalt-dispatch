"""给 API 测试用的桩。

这里的能量和余量是测试自己填的常数，用来确认接口原样转发。
它们不是机型参数，也不是服务在缺数据时补出来的结果。
"""

from __future__ import annotations

from types import SimpleNamespace

from core.models import DiversionMarginProfile, DiversionMarginSample, RoutePlan

CALLS: list[object] = []


def diversion_plan(task, snapshot):
    route = RoutePlan(
        route_id="from-planner",
        plan_version="v9",
        snapshot_id=snapshot.snapshot_id,
        algorithm="astar_diversion",
        waypoints=[task.origin, task.destination],
        energy_budget_wh=12.5,
        diversion_site_id="L2",
    )
    profile = DiversionMarginProfile(
        route_id="from-planner",
        plan_version="v9",
        reserve_wh=task.reserve_energy_wh,
        samples=[
            DiversionMarginSample(s_m=0, t_s=0, margin_wh=10.0, nearest_site_id="L1"),
            DiversionMarginSample(s_m=10, t_s=1, margin_wh=5.0, nearest_site_id="L2"),
        ],
    )
    return SimpleNamespace(route=route, margin_profile=profile, algorithm="astar_diversion")


def agent_tries_to_rewrite(ctx):
    CALLS.append(ctx)
    return {"waypoints": [{"x_m": 0.0, "y_m": 0.0}]}


def agent_raises(ctx):
    raise RuntimeError("桩：拒绝改写路线")
