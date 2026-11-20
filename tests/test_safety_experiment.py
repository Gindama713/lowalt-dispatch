from __future__ import annotations

from pathlib import Path

from core.geometry import rect_polygon
from eval.safety_experiment import build_suite
from planner.diversion import _accept_state, build_diversion_field, plan_scenario_with_diversion
from planner.grid import build_grid
from planner.scene import LandingSite, load_scene
from sim.energy import VehicleProfile, load_vehicle

ROOT = Path(__file__).resolve().parents[1]


def test_generated_suite_has_100_unique_paired_task_event_inputs() -> None:
    suite = build_suite()
    assert suite["is_simulated"] is True
    assert len(suite["scenarios"]) == 100
    assert len({s["template_id"] for s in suite["scenarios"]}) == 20
    assert len({s["experiment_variant"] for s in suite["scenarios"]}) == 5
    assert len({s["id"] for s in suite["scenarios"]}) == 100


def test_disabling_diversion_constraint_only_changes_search_policy() -> None:
    vehicle = load_vehicle(ROOT / "scenarios/vehicles/example_not_real.yaml")
    scenario = {
        "id": "ablation-low-energy",
        "origin": {"x_m": 150, "y_m": 150, "alt_m": 0},
        "destination": {"x_m": 2650, "y_m": 2750, "alt_m": 30},
        "payload_kg": 1.0,
        "time_limit_s": 900,
        "initial_energy_wh": 100.0,
        "reserve_energy_wh": 40.0,
        "events": [],
        "landing_site_changes": [],
    }
    scene = load_scene()
    full = plan_scenario_with_diversion(scenario, scene, vehicle)
    ablated = plan_scenario_with_diversion(scenario, scene, vehicle, enforce_diversion=False)
    assert full.found is False
    assert ablated.found is True
    assert ablated.profile is not None and not ablated.profile.is_feasible


def test_future_nfz_ablation_disables_only_future_zone_pruning() -> None:
    grid = build_grid([], x0=0, y0=0, x1=400, y1=400, res_m=10, clearance_m=0)
    site = LandingSite("L", 300, 300, radius_m=30)
    field = build_diversion_field(grid, [site])
    vehicle = VehicleProfile(
        vehicle_key="ablation-test",
        max_payload_kg=2,
        cruise_speed_mps=10,
        climb_rate_mps=2,
        energy_per_meter_wh=0.01,
        energy_per_second_hover_wh=0,
        usable_battery_wh=500,
        reserve_policy_wh=0,
    )
    kwargs = {
        "initial_energy_wh": 500,
        "reserve_wh": 0,
        "climb_wh": 0,
        "climb_time_s": 0,
        "time_limit_s": None,
        "nfz_windows": ((rect_polygon(100, 100, 200, 200), 5.0, None),),
    }
    node = (15, 15)
    full = _accept_state(grid, field, vehicle, **kwargs)
    ablated = _accept_state(grid, field, vehicle, **kwargs, enforce_future_nfz=False)
    assert full(node, 100.0) == "nfz_time"
    assert ablated(node, 100.0) is None
