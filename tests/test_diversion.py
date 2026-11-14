"""备降余量与搜索剪枝。

这些测试盯住三件事：余量按“绕开障碍的路径能耗”算，而不是直线；
不满足约束的状态会被剪掉，并且无解时不交出那条不安全的路线；
基线 A* 仍然会把那条几何路线交出来，方便对照。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.geometry import point_in_polygon, rect_polygon, sample_polyline
from planner.diversion import (
    UNREACHABLE_MARGIN_WH,
    active_landing_sites,
    build_diversion_field,
    plan_baseline_annotated,
    plan_scenario_with_diversion,
    profile_along_route,
    query_margin,
)
from planner.grid import build_grid
from planner.scene import LandingSite, Scene, load_scene, load_suite, zones_known_at_t0
from sim.energy import VEHICLE_PATH, VehicleProfile, load_vehicle

EXAMPLE = Path(__file__).resolve().parents[1] / "scenarios" / "vehicles" / "example_not_real.yaml"
REPO = Path(__file__).resolve().parents[1]


def _toy() -> VehicleProfile:
    """合成参数，只验证公式。不是示例机型，也不是真实平台。"""
    return VehicleProfile(
        vehicle_key="toy",
        max_payload_kg=2.0,
        cruise_speed_mps=10.0,
        climb_rate_mps=2.0,
        energy_per_meter_wh=0.1,
        energy_per_second_hover_wh=0.0,
        usable_battery_wh=500.0,
        reserve_policy_wh=0.0,
        draft_geometry_vehicle_alias="placeholder",
    )


def _open_query(energy_per_m: float = 0.02):
    grid = build_grid([], x0=0, y0=0, x1=400, y1=400, res_m=10, clearance_m=0)
    site = LandingSite("L", 300.0, 50.0, radius_m=20.0)
    field_ = build_diversion_field(grid, [site])
    vehicle = VehicleProfile(
        vehicle_key="toy",
        max_payload_kg=1.0,
        cruise_speed_mps=10.0,
        climb_rate_mps=2.0,
        energy_per_meter_wh=energy_per_m,
        energy_per_second_hover_wh=0.0,
        usable_battery_wh=100.0,
        reserve_policy_wh=0.0,
    )
    queried = query_margin(
        field_=field_,
        grid=grid,
        x=50.0,
        y=50.0,
        energy_left_wh=100.0,
        reserve_wh=10.0,
        vehicle=vehicle,
    )
    return queried


def test_open_field_margin_matches_path_energy() -> None:
    queried = _open_query()
    assert queried.geometrically_reachable
    assert queried.nearest_site_id == "L"
    # 栅格中心大约在 (55, 55)，降落半径 20 m，水平距离应落在 200 m 量级，而不是 0。
    assert queried.distance_m == pytest.approx(220.0, abs=30.0)
    assert queried.energy_need_wh == pytest.approx(queried.distance_m * 0.02)
    assert queried.margin_wh == pytest.approx(100.0 - 10.0 - queried.energy_need_wh)
    assert queried.satisfies_constraint


def test_wall_makes_diversion_longer_than_straight_line() -> None:
    wall = rect_polygon(140, 0, 180, 200)
    blocked = build_grid([wall], x0=0, y0=0, x1=400, y1=400, res_m=10, clearance_m=0)
    site = LandingSite("L", 300.0, 50.0, radius_m=20.0)
    field_ = build_diversion_field(blocked, [site])
    vehicle = VehicleProfile(
        vehicle_key="toy",
        max_payload_kg=1.0,
        cruise_speed_mps=10.0,
        climb_rate_mps=2.0,
        energy_per_meter_wh=0.02,
        energy_per_second_hover_wh=0.0,
        usable_battery_wh=100.0,
        reserve_policy_wh=0.0,
    )
    queried = query_margin(
        field_=field_,
        grid=blocked,
        x=50.0,
        y=50.0,
        energy_left_wh=100.0,
        reserve_wh=0.0,
        vehicle=vehicle,
    )
    straight = _open_query().energy_need_wh
    assert straight is not None
    assert queried.nearest_site_id == "L"
    assert queried.energy_need_wh is not None
    assert queried.energy_need_wh > straight * 1.15


def test_no_landing_site_is_a_negative_sentinel_not_zero_margin() -> None:
    grid = build_grid([], x0=0, y0=0, x1=200, y1=200, res_m=10, clearance_m=0)
    field_ = build_diversion_field(grid, [])
    vehicle = _toy()
    queried = query_margin(
        field_=field_,
        grid=grid,
        x=40.0,
        y=40.0,
        energy_left_wh=80.0,
        reserve_wh=10.0,
        vehicle=vehicle,
    )
    assert queried.nearest_site_id is None
    assert queried.energy_need_wh is None
    assert queried.margin_wh == UNREACHABLE_MARGIN_WH
    assert not queried.satisfies_constraint


def test_pruning_rejects_route_that_baseline_still_returns() -> None:
    """能量只够单程、不够再飞回唯一备降点时，约束搜索必须无解，基线仍给出几何路线。"""
    scene = Scene(obstacles=[], zones={}, sites={"L": LandingSite("L", 100.0, 100.0, radius_m=30.0, compatible_vehicle_types=("toy",))})
    scenario = {
        "id": "toy-far",
        "origin": {"x_m": 100.0, "y_m": 100.0, "alt_m": 0.0},
        "destination": {"x_m": 100.0, "y_m": 900.0, "alt_m": 0.0},
        "payload_kg": 0.2,
        "events": [],
        "landing_site_changes": [],
        "initial_energy_wh": 100.0,
        "reserve_energy_wh": 0.0,
    }
    vehicle = _toy()
    baseline = plan_baseline_annotated(scenario, scene, vehicle)
    diversion = plan_scenario_with_diversion(scenario, scene, vehicle)

    assert baseline.found
    assert baseline.profile is not None
    assert baseline.profile.min_margin_wh is not None
    assert baseline.profile.min_margin_wh < 0
    assert not diversion.found
    assert diversion.waypoints == []
    assert diversion.reason is not None and "备降" in diversion.reason
    assert diversion.pruned > 0


def test_short_hop_profile_stays_non_negative_and_matches_formula() -> None:
    scene = Scene(
        obstacles=[],
        zones={},
        sites={"L": LandingSite("L", 100.0, 100.0, radius_m=30.0, compatible_vehicle_types=("toy",))},
    )
    scenario = {
        "id": "toy-near",
        "origin": {"x_m": 100.0, "y_m": 100.0, "alt_m": 0.0},
        "destination": {"x_m": 100.0, "y_m": 250.0, "alt_m": 0.0},
        "payload_kg": 0.2,
        "events": [],
        "landing_site_changes": [],
        "initial_energy_wh": 100.0,
        "reserve_energy_wh": 0.0,
    }
    vehicle = _toy()
    diversion = plan_scenario_with_diversion(scenario, scene, vehicle)
    assert diversion.found
    assert diversion.profile is not None
    assert diversion.profile.is_feasible
    start = diversion.profile.samples[0]
    assert start.nearest_site_id == "L"
    assert start.energy_need_wh == pytest.approx(0.0, abs=0.5)
    assert start.margin_wh == pytest.approx(100.0 - (start.energy_need_wh or 0.0), abs=0.5)
    end = diversion.profile.samples[-1]
    assert end.energy_need_wh is not None
    assert end.margin_wh == pytest.approx(100.0 - vehicle.energy_per_meter_wh * end.s_m - end.energy_need_wh, abs=1.0)


def test_profile_samples_cover_the_polyline() -> None:
    grid = build_grid([], x0=0, y0=0, x1=400, y1=200, res_m=10, clearance_m=0)
    site = LandingSite("L", 40.0, 40.0, radius_m=20.0)
    field_ = build_diversion_field(grid, [site])
    vehicle = _toy()
    waypoints = [(40.0, 40.0), (300.0, 40.0)]
    profile = profile_along_route(
        route_id="adhoc",
        waypoints=waypoints,
        grid=grid,
        field_=field_,
        vehicle=vehicle,
        initial_energy_wh=200.0,
        reserve_wh=5.0,
        climb_delta=0.0,
        sample_step_m=50.0,
    )
    assert profile.samples[0].s_m == 0.0
    assert profile.samples[-1].s_m == pytest.approx(260.0, abs=1.0)
    assert all(sample.nearest_site_id == "L" for sample in profile.samples)


def _suite_map() -> dict:
    return {sc["id"]: sc for sc in load_suite()["scenarios"]}


def test_s4_cases_return_explicit_reasons_and_keep_baseline() -> None:
    scene = load_scene()
    suite = _suite_map()
    vehicle = load_vehicle(EXAMPLE)

    closed = plan_scenario_with_diversion(suite["S4-03"], scene, vehicle)
    closed_base = plan_baseline_annotated(suite["S4-03"], scene, vehicle)
    assert closed_base.found
    assert not closed.found and closed.waypoints == []
    assert closed.reason is not None and "备降" in closed.reason
    assert closed_base.profile is not None and not closed_base.profile.is_feasible

    low = plan_scenario_with_diversion(suite["S4-05"], scene, vehicle)
    assert not low.found
    assert low.reason is not None and "保留" in low.reason
    assert plan_baseline_annotated(suite["S4-05"], scene, vehicle).found

    heavy = plan_scenario_with_diversion(suite["S4-01"], scene, vehicle)
    assert not heavy.found
    assert heavy.reason is not None and "载荷" in heavy.reason

    tight = plan_scenario_with_diversion(suite["S4-02"], scene, vehicle)
    assert not tight.found
    assert tight.reason is not None and "时限" in tight.reason

    blocked = plan_scenario_with_diversion(suite["S4-04"], scene, vehicle)
    blocked_base = plan_baseline_annotated(suite["S4-04"], scene, vehicle)
    assert not blocked.found and not blocked_base.found
    assert blocked.reason is not None and "终点" in blocked.reason


def test_example_parameters_make_s1_01_constraint_bind() -> None:
    """示例参数下，S1-01 的最短路线终点余量为负；约束搜索不交出这条线。

    数字来自 example_not_real.yaml。换真实参数后这个对照要重跑，不能沿用。
    """
    scene = load_scene()
    scenario = _suite_map()["S1-01"]
    vehicle = load_vehicle(EXAMPLE)
    baseline = plan_baseline_annotated(scenario, scene, vehicle)
    diversion = plan_scenario_with_diversion(scenario, scene, vehicle)
    assert baseline.found and baseline.profile is not None
    assert baseline.profile.min_margin_wh is not None and baseline.profile.min_margin_wh < 0
    assert not diversion.found
    assert diversion.reason is not None and "备降" in diversion.reason
    assert diversion.waypoints == []


def test_diversion_routes_stay_clear_of_obstacles_and_keep_non_negative_margin() -> None:
    scene = load_scene()
    vehicle = load_vehicle(EXAMPLE)
    found_any = False
    for scenario in load_suite()["scenarios"]:
        result = plan_scenario_with_diversion(scenario, scene, vehicle)
        if not result.found:
            assert result.reason
            assert result.waypoints == []
            continue
        found_any = True
        assert result.profile is not None and result.profile.is_feasible
        assert result.profile.min_margin_wh is not None and result.profile.min_margin_wh >= -1e-6
        blockers = list(scene.obstacles) + [z.polygon for z in zones_known_at_t0(scenario, scene)]
        for _s, (px, py) in sample_polyline(result.waypoints, 2.0):
            for poly in blockers:
                assert not point_in_polygon(px, py, poly), scenario["id"]
    assert found_any


def test_incompatible_vehicle_sees_no_draft_sites() -> None:
    vehicle = _toy()
    vehicle = VehicleProfile(
        vehicle_key="other",
        max_payload_kg=vehicle.max_payload_kg,
        cruise_speed_mps=vehicle.cruise_speed_mps,
        climb_rate_mps=vehicle.climb_rate_mps,
        energy_per_meter_wh=vehicle.energy_per_meter_wh,
        energy_per_second_hover_wh=vehicle.energy_per_second_hover_wh,
        usable_battery_wh=vehicle.usable_battery_wh,
        reserve_policy_wh=vehicle.reserve_policy_wh,
    )
    sites, notes = active_landing_sites(load_scene(), {"landing_site_changes": []}, vehicle)
    assert sites == []
    assert notes


def test_example_vehicle_file_is_labeled_and_does_not_replace_placeholder() -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    assert "示例参数，非真实平台数据" in text
    profile = load_vehicle(EXAMPLE)
    assert profile.is_example
    assert profile.vehicle_key == "example_not_real"
    assert profile.draft_geometry_vehicle_alias == "placeholder"
    assert VEHICLE_PATH.name == "placeholder.yaml"
    placeholder = (REPO / "scenarios" / "vehicles" / "placeholder.yaml").read_text(encoding="utf-8")
    assert "energy_per_meter_wh: null" in placeholder


def test_real_planners_ignore_seed_and_eval_splits_mock(tmp_path: Path) -> None:
    from eval import run
    from eval.planners import get

    scenario = _suite_map()["S1-02"]
    planner = get("astar_diversion", vehicle_path=EXAMPLE)
    first = planner.plan(scenario, seed=1)
    second = planner.plan(scenario, seed=2)
    assert first.task_feasible == second.task_feasible
    assert first.route_length_m == second.route_length_m
    assert first.min_landing_margin == second.min_landing_margin
    assert not planner.is_mock

    out = tmp_path / "compare.csv"
    code = run.main(
        [
            "--suite",
            str(REPO / "eval" / "scenarios" / "v0.yaml"),
            "--seeds",
            "1",
            "--algorithms",
            "astar_static,astar_diversion,astar_dynamic",
            "--vehicle",
            str(EXAMPLE),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert out.is_file()
    mock = tmp_path / "compare_MOCK.csv"
    assert mock.is_file()

    import csv
    import json

    with out.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert {r["run_mode"] for r in rows} == {"real"}
    assert {r["algorithm"] for r in rows} == {"astar_static", "astar_diversion"}
    by_id = {(r["scenario_id"], r["algorithm"]): r for r in rows}
    assert float(by_id[("S1-01", "astar_static")]["route_length_m"]) > 0
    assert by_id[("S1-01", "astar_static")]["task_feasible"] == "False"
    assert float(by_id[("S1-01", "astar_static")]["min_landing_margin"]) < 0
    assert float(by_id[("S1-01", "astar_diversion")]["route_length_m"]) == 0
    assert "备降" in by_id[("S1-01", "astar_diversion")]["infeasible_reason"]
    assert "备降" in by_id[("S4-03", "astar_diversion")]["infeasible_reason"]
    assert by_id[("S4-05", "astar_diversion")]["infeasible_reason"]
    assert "保留" in by_id[("S4-05", "astar_diversion")]["infeasible_reason"]

    meta = json.loads(out.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert meta["run_mode"] == "real"
    assert meta["vehicle_is_example"] is True
    assert meta["is_simulated"] is True
    assert "示例" in meta["warning"]
    assert "非真实平台" in meta["warning"]
    profiles = json.loads(out.with_suffix(".profiles.json").read_text(encoding="utf-8"))
    assert profiles["vehicle_is_example"] is True
    found = [p for p in profiles["profiles"] if p["algorithm"] == "astar_diversion" and p.get("samples")]
    assert found
    assert found[0]["samples"][0]["s_m"] == 0
    assert "margin_wh" in found[0]["samples"][0]

    with mock.open(encoding="utf-8-sig", newline="") as fh:
        mock_rows = list(csv.DictReader(fh))
    assert {r["algorithm"] for r in mock_rows} == {"astar_dynamic"}
    assert {r["run_mode"] for r in mock_rows} == {"mock"}


# --------------------------------------------------------------------------- #
# 飞行中关闭的备降点（2026-11-15 修掉的余量高估）
# --------------------------------------------------------------------------- #
def test_site_closure_during_flight_enters_search_and_profile() -> None:
    """S3-04 的 L2 在 45 s 关闭、飞行 204 s，不能全程把它算作有效退出路径。"""
    from planner.diversion import (
        blockers_at_t0,
        cached_grid,
        climb_delta_m,
        resolve_energy,
        shared_scene,
        site_closure_schedule,
        sites_available_at,
    )
    from planner.scene import load_suite

    vehicle = load_vehicle(EXAMPLE)
    scene = shared_scene()
    sc = next(s for s in load_suite()["scenarios"] if s["id"] == "S3-04")
    schedule = site_closure_schedule(sc)
    assert schedule == ((45.0, "L2"),)

    sites, _ = active_landing_sites(scene, sc, vehicle)
    assert any(s.site_id == "L2" for s in sites_available_at(sites, schedule, 10.0))
    assert all(s.site_id != "L2" for s in sites_available_at(sites, schedule, 60.0))

    base = plan_baseline_annotated(sc, scene, vehicle)
    constrained = plan_scenario_with_diversion(sc, scene, vehicle)
    assert base.profile is not None and constrained.profile is not None
    late = [s for s in constrained.profile.samples if s.t_s > 45.0]
    assert late, "飞行时间应明显超过 45 s"
    assert all(s.nearest_site_id != "L2" for s in late), "L2 关闭后不得再作为最近备降点"

    # 静态口径（全程把 L2 当有效）会高估余量；时变口径必须更保守
    grid = cached_grid(blockers_at_t0(sc, scene))
    static_field = build_diversion_field(grid, sites)
    initial, reserve = resolve_energy(sc, vehicle)
    static_profile = profile_along_route(
        route_id="static",
        waypoints=base.waypoints,
        grid=grid,
        field_=static_field,
        vehicle=vehicle,
        initial_energy_wh=initial,
        reserve_wh=reserve,
        climb_delta=climb_delta_m(sc),
    )
    assert constrained.profile.min_margin_wh < static_profile.min_margin_wh
    assert constrained.profile.is_feasible
    # 基线与约束两条剖面用同一套时变口径，对照才公平
    assert abs(base.profile.min_margin_wh - constrained.profile.min_margin_wh) < 1e-6
