"""独立校验器的测试。

最要紧的一条是 `test_planner_clearance_matches_validator`：
规划器在栅格上按 30 m 加厚障碍，校验器按连续几何判 20 m，两者必须**始终**一致。
如果哪天有人把栅格净空改小，或去掉 A* 的禁止切角，这条测试会先炸，
而不是等到答辩现场被评委量出来。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent.guards import report_failures
from core.models import RoutePlan, route_digest
from planner.assemble import build_snapshot, build_task, route_from_path
from planner.astar import plan_scenario
from planner.scene import load_scene, load_suite
from sim.energy import VehicleProfile
from validator.checks import UNAVAILABLE, summarize, validate_route

T0 = datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC)
INITIAL_WH = 400.0
RESERVE_WH = 80.0

TOY = VehicleProfile(
    vehicle_key="toy",
    max_payload_kg=2.0,
    cruise_speed_mps=15.0,
    climb_rate_mps=3.0,
    energy_per_meter_wh=0.02,
    energy_per_second_hover_wh=0.6,
    usable_battery_wh=400.0,
    reserve_policy_wh=80.0,
    source="测试用合成参数",
)


@pytest.fixture(scope="module")
def scene():
    return load_scene()


@pytest.fixture(scope="module")
def suite():
    return {s["id"]: s for s in load_suite()["scenarios"]}


def _build(scenario, scene, *, profile=TOY, initial_wh=INITIAL_WH):
    path, _ = plan_scenario(scenario, scene)
    if not path.found:
        return None, None, None
    task = build_task(
        scenario,
        T0,
        vehicle_type="placeholder",
        initial_energy_wh=float(scenario.get("initial_energy_wh", initial_wh)),
        reserve_energy_wh=RESERVE_WH,
    )
    snapshot = build_snapshot(scenario, scene, T0)
    route = route_from_path(path, task, snapshot, energy_budget_wh=INITIAL_WH - RESERVE_WH)
    return task, snapshot, route


def _check(report, name):
    return next(c for c in report.checks if c.name == name)


# --------------------------------------------------------------------------- #
# 两把尺子对齐
# --------------------------------------------------------------------------- #
def test_planner_clearance_matches_validator(scene, suite) -> None:
    """规划器产出的每一条航线都必须过校验器的净空检查。"""
    failures = []
    for sid, sc in suite.items():
        task, snapshot, route = _build(sc, scene)
        if route is None:
            continue
        report = validate_route(route, task, snapshot, scene, profile=TOY, now=T0)
        clearance = _check(report, "clearance")
        if not clearance.passed:
            failures.append(f"{sid}: {clearance.detail}")
    assert not failures, "栅格净空与连续几何净空不一致：\n" + "\n".join(failures)


# --------------------------------------------------------------------------- #
# 该拒的必须拒
# --------------------------------------------------------------------------- #
def test_baseline_blind_spot_is_caught(scene, suite) -> None:
    """S2-01 的 R01 在 +40 s 才生效，基线不知道；校验器按时间轴必须抓到。"""
    task, snapshot, route = _build(suite["S2-01"], scene)
    report = validate_route(route, task, snapshot, scene, profile=TOY, now=T0)
    rz = _check(report, "restriction_zone")
    assert not rz.passed
    assert "R01" in rz.detail
    assert "生效" in rz.detail


def test_route_through_building_is_rejected(scene, suite) -> None:
    """人为造一条穿楼的直线，净空检查必须拒绝。"""
    sc = suite["S1-01"]
    task, snapshot, _route = _build(sc, scene)
    building = scene.obstacles[0]
    xs = [p[0] for p in building]
    ys = [p[1] for p in building]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)

    bad = RoutePlan(
        route_id="bad-v1",
        plan_version="v1",
        snapshot_id=snapshot.snapshot_id,
        algorithm="manual",
        waypoints=[
            task.origin.model_copy(update={"x_m": cx - 200, "y_m": cy}),
            task.origin.model_copy(update={"x_m": cx, "y_m": cy}),
            task.destination,
        ],
        energy_budget_wh=100.0,
    )
    report = validate_route(bad, task, snapshot, scene, profile=TOY, now=T0)
    clearance = _check(report, "clearance")
    assert not clearance.passed
    assert "建筑" in clearance.detail


def test_payload_limit_rejected(scene, suite) -> None:
    task, snapshot, route = _build(suite["S4-01"], scene)
    report = validate_route(route, task, snapshot, scene, profile=TOY, now=T0)
    assert not _check(report, "payload_limit").passed


def test_time_limit_rejected(scene, suite) -> None:
    task, snapshot, route = _build(suite["S4-02"], scene)
    report = validate_route(route, task, snapshot, scene, profile=TOY, now=T0)
    assert not _check(report, "time_limit").passed


def test_no_landing_sites_rejected(scene, suite) -> None:
    task, snapshot, route = _build(suite["S4-03"], scene)
    assert snapshot.landing_sites == []
    report = validate_route(route, task, snapshot, scene, profile=TOY, now=T0)
    assert not _check(report, "diversion_reachability").passed


def test_energy_below_reserve_rejected(scene, suite) -> None:
    task, snapshot, route = _build(suite["S4-05"], scene)
    report = validate_route(route, task, snapshot, scene, profile=TOY, now=T0)
    energy = _check(report, "energy")
    assert not energy.passed
    assert "保留量" in energy.detail


# --------------------------------------------------------------------------- #
# 本该通过的必须通过（否则校验器就是噪声）
# --------------------------------------------------------------------------- #
def test_normal_scenario_passes_all(scene, suite) -> None:
    task, snapshot, route = _build(suite["S1-01"], scene)
    report = validate_route(route, task, snapshot, scene, profile=TOY, now=T0)
    ok, msg = summarize(report)
    assert ok, msg
    # 顺带证明：这份报告能被 M3 的守卫接受（两边的契约真的对得上）
    assert report_failures(report, task, route, snapshot, T0, not_before=T0) == []


# --------------------------------------------------------------------------- #
# 缺参数时必须说"不确定"，而不是猜
# --------------------------------------------------------------------------- #
def test_missing_profile_is_reported_as_unavailable(scene, suite) -> None:
    task, snapshot, route = _build(suite["S1-01"], scene)
    report = validate_route(route, task, snapshot, scene, profile=None, now=T0)
    for name in ("energy", "diversion_reachability"):
        c = _check(report, name)
        assert not c.passed
        assert c.detail.startswith(UNAVAILABLE), c.detail
    # 几何两项不需要机型参数，应该照常判定
    assert _check(report, "clearance").passed
    ok, msg = summarize(report)
    assert not ok and "无法判定" in msg


# --------------------------------------------------------------------------- #
# 绑定与防护
# --------------------------------------------------------------------------- #
def test_digest_changes_when_route_changes(scene, suite) -> None:
    task, snapshot, route = _build(suite["S1-01"], scene)
    before = route_digest(route)
    moved = route.model_copy(deep=True)
    moved.waypoints[1] = moved.waypoints[1].model_copy(update={"x_m": moved.waypoints[1].x_m + 5.0})
    assert route_digest(moved) != before


def test_report_bound_to_digest_rejects_tampered_route(scene, suite) -> None:
    """M3 拿到一份报告后，如果航线被改过，guard 必须拒绝这份报告。"""
    task, snapshot, route = _build(suite["S1-01"], scene)
    report = validate_route(route, task, snapshot, scene, profile=TOY, now=T0)
    assert report_failures(report, task, route, snapshot, T0, not_before=T0) == []

    tampered = route.model_copy(deep=True)
    tampered.waypoints[2] = tampered.waypoints[2].model_copy(
        update={"x_m": tampered.waypoints[2].x_m + 50.0}
    )
    issues = report_failures(report, task, tampered, snapshot, T0, not_before=T0)
    assert any("does not match" in i.detail for i in issues)


def test_cross_snapshot_validation_is_refused(scene, suite) -> None:
    task, _snapshot, route = _build(suite["S1-01"], scene)
    other = build_snapshot(suite["S1-02"], scene, T0)
    with pytest.raises(ValueError, match="不能跨快照校验"):
        validate_route(route, task, other, scene, profile=TOY, now=T0)


def test_waypoint_reference_mismatch_raises(scene, suite) -> None:
    task, snapshot, route = _build(suite["S1-01"], scene)
    broken = route.model_copy(deep=True)
    broken.waypoints = [task.origin.model_copy(update={"frame": "wgs84", "x_m": None, "y_m": None, "lat_deg": 28.0, "lon_deg": 115.0})] + list(route.waypoints[1:])
    with pytest.raises(ValueError, match="ENU"):
        validate_route(broken, task, snapshot, scene, profile=TOY, now=T0)


# --------------------------------------------------------------------------- #
# 备降可达距离的尺子（2026-11-15 修掉的口径错误）
# --------------------------------------------------------------------------- #
def test_escape_distance_never_uses_straight_line_through_wall() -> None:
    """备降距离必须绕开建筑，不能用欧氏直线。

    旧实现拿 min(hypot(采样点, 备降点)) 算退出路径，等于默认可以穿墙飞过去，
    会系统性低估备降能耗、把不安全的航线判成安全。这两条断言锁住修复。
    """
    from core.geometry import rect_polygon
    from validator.escape import EscapeSite, build_escape_field

    wall = rect_polygon(980.0, 0.0, 1020.0, 1400.0)  # 竖墙，缺口在 y > 1400
    site = EscapeSite("L-test", 2000.0, 700.0, 30.0)
    field = build_escape_field([wall], [site])

    dist_m, idx = field.lookup(500.0, 700.0)
    assert idx >= 0, "墙上方有缺口，应该存在绕行的退出路径"
    assert dist_m > 1500.0, f"距离 {dist_m:.0f} m 不应短于穿墙直线 1500 m"

    sealed = build_escape_field([rect_polygon(980.0, 0.0, 1020.0, 3000.0)], [site])
    assert sealed.lookup(500.0, 700.0)[1] == -1, "完全隔断时不得给出可达距离"


def test_grid_constants_are_shared_between_planner_and_validator() -> None:
    """栅格分辨率与净空只能有一份定义，否则两边的尺子又会悄悄分叉。"""
    from core.geometry import GRID_CLEARANCE_M, GRID_RES_M
    from planner.grid import DEFAULT_CLEARANCE_M, DEFAULT_RES_M
    from validator import escape

    assert DEFAULT_RES_M == GRID_RES_M == escape.GRID_RES_M
    assert DEFAULT_CLEARANCE_M == GRID_CLEARANCE_M == escape.GRID_CLEARANCE_M


def test_missing_enu_coordinates_do_not_become_origin(scene, suite) -> None:
    """备降点缺 ENU 坐标时不能当成 (0, 0) 凭空造一条退出路径。"""
    task, snapshot, route = _build(suite["S1-01"], scene)
    broken_snapshot = snapshot.model_copy(deep=True)
    for site in broken_snapshot.landing_sites:
        site.position = site.position.model_copy(
            update={"frame": "wgs84", "x_m": None, "y_m": None, "lat_deg": 28.0, "lon_deg": 115.0}
        )
    report = validate_route(route, task, broken_snapshot, scene, profile=TOY, now=T0)
    diversion = _check(report, "diversion_reachability")
    assert not diversion.passed
    assert "缺少 ENU 坐标" in diversion.detail or "几何可达" in diversion.detail
