"""接口契约的最低防线。

这些测试不验证算法对不对，只保证"数据一旦不合约定就立刻炸"——
因为这类错误不会在运行时报错，只会在答辩现场变成没法解释的数字。
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from core.models import (
    AltitudeReference,
    DataProvenance,
    DiversionMarginProfile,
    DiversionMarginSample,
    Frame,
    Position,
    RiskEvent,
    RoutePlan,
)
from eval import planners, run

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE = REPO_ROOT / "eval" / "scenarios" / "v0.yaml"


def _prov() -> DataProvenance:
    return DataProvenance(
        source="test",
        version="0",
        captured_at="2026-11-08T00:00:00+00:00",
        is_simulated=True,
    )


# --------------------------------------------------------------------------- #
# Position：坐标系与高度基准
# --------------------------------------------------------------------------- #
def test_enu_position_ok() -> None:
    p = Position(frame=Frame.ENU_M, x_m=10.0, y_m=20.0, alt_m=30.0, alt_ref=AltitudeReference.REL_TAKEOFF)
    assert p.x_m == 10.0


def test_enu_position_rejects_latlon_mix() -> None:
    with pytest.raises(ValidationError):
        Position(
            frame=Frame.ENU_M,
            x_m=10.0,
            y_m=20.0,
            lat_deg=28.6,
            alt_m=30.0,
            alt_ref=AltitudeReference.REL_TAKEOFF,
        )


def test_enu_position_requires_xy() -> None:
    with pytest.raises(ValidationError):
        Position(frame=Frame.ENU_M, alt_m=30.0, alt_ref=AltitudeReference.AGL)


# --------------------------------------------------------------------------- #
# 备降余量剖面：可行性的唯一判据
# --------------------------------------------------------------------------- #
def test_margin_profile_all_positive_is_feasible() -> None:
    prof = DiversionMarginProfile(
        route_id="R1",
        plan_version="v1",
        reserve_wh=50.0,
        samples=[
            DiversionMarginSample(s_m=0, t_s=0, margin_wh=120.0, nearest_site_id="L1"),
            DiversionMarginSample(s_m=500, t_s=60, margin_wh=0.0, nearest_site_id="L2"),
        ],
    )
    assert prof.is_feasible
    assert prof.min_margin_wh == 0.0
    assert prof.negative_sample_count == 0


def test_margin_profile_negative_blocks_feasibility() -> None:
    prof = DiversionMarginProfile(
        route_id="R1",
        plan_version="v1",
        reserve_wh=50.0,
        samples=[
            DiversionMarginSample(s_m=0, t_s=0, margin_wh=120.0, nearest_site_id="L1"),
            DiversionMarginSample(s_m=500, t_s=60, margin_wh=-1.0, nearest_site_id=None),
        ],
    )
    assert not prof.is_feasible
    assert prof.negative_sample_count == 1


def test_empty_margin_profile_is_not_feasible() -> None:
    """空剖面不能被当成"没问题"，必须按不可行处理。"""
    prof = DiversionMarginProfile(route_id="R1", plan_version="v1", reserve_wh=50.0)
    assert not prof.is_feasible
    assert prof.min_margin_wh is None


# --------------------------------------------------------------------------- #
# 其他硬约束
# --------------------------------------------------------------------------- #
def test_route_plan_needs_two_waypoints() -> None:
    wp = Position(frame=Frame.ENU_M, x_m=0, y_m=0, alt_m=0, alt_ref=AltitudeReference.REL_TAKEOFF)
    with pytest.raises(ValidationError):
        RoutePlan(
            route_id="R",
            plan_version="v1",
            snapshot_id="S1",
            algorithm="astar_static",
            waypoints=[wp],
            energy_budget_wh=100,
        )


def test_risk_event_alt_band_ordered() -> None:
    with pytest.raises(ValidationError):
        RiskEvent(
            event_id="E1",
            kind="restriction_zone",
            effective_from="2026-11-08T00:00:00+00:00",
            alt_min_m=100,
            alt_max_m=50,
            provenance=_prov(),
        )


# --------------------------------------------------------------------------- #
# harness：可复现 + 产物格式
# --------------------------------------------------------------------------- #
def test_margin_profile_without_site_is_not_feasible_even_if_margin_non_negative() -> None:
    """没有备降点就不是 0 余量。正的 margin 也不能把这种采样点算成可行。"""
    prof = DiversionMarginProfile(
        route_id="R1",
        plan_version="v1",
        reserve_wh=50.0,
        samples=[
            DiversionMarginSample(s_m=0, t_s=0, margin_wh=10.0, nearest_site_id=None),
        ],
    )
    assert not prof.is_feasible


def test_mock_planner_is_deterministic() -> None:
    scenario = {"id": "S1-01", "origin": {"x_m": 0, "y_m": 0}, "destination": {"x_m": 1000, "y_m": 1000}}
    planner = planners.get("astar_dynamic")
    assert planner.is_mock
    a = planner.plan(scenario, seed=7)
    b = planner.plan(scenario, seed=7)
    assert a == b


def test_mock_planner_varies_by_seed() -> None:
    scenario = {"id": "S1-01", "origin": {"x_m": 0, "y_m": 0}, "destination": {"x_m": 1000, "y_m": 1000}}
    planner = planners.get("astar_dynamic")
    assert planner.plan(scenario, seed=1) != planner.plan(scenario, seed=2)


def test_harness_end_to_end_marks_mock(tmp_path: Path) -> None:
    out = tmp_path / "v0.csv"
    code = run.main(
        ["--suite", str(SUITE), "--seeds", "1,2", "--algorithms", "astar_dynamic", "--out", str(out)]
    )
    assert code == 0

    mock_csv = tmp_path / "v0_MOCK.csv"
    assert mock_csv.is_file(), "mock 运行必须自动加 _MOCK 后缀"
    assert not out.exists(), "纯 mock 不应产出未标记的 CSV"

    with mock_csv.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    scenario_count = len(yaml.safe_load(SUITE.read_text(encoding="utf-8"))["scenarios"])
    assert len(rows) == scenario_count * 2
    assert {r["run_mode"] for r in rows} == {"mock"}
    assert {r["algorithm"] for r in rows} == {"astar_dynamic"}

    meta = mock_csv.with_suffix(".meta.json")
    assert meta.is_file()
    assert '"run_mode": "mock"' in meta.read_text(encoding="utf-8")


def test_real_algorithms_require_an_explicit_vehicle(tmp_path: Path) -> None:
    out = tmp_path / "v0.csv"
    code = run.main(
        ["--suite", str(SUITE), "--seeds", "1", "--algorithms", "astar_static", "--out", str(out)]
    )
    assert code == 2
    assert not out.exists()
