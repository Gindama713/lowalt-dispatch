"""规划器接口。

`astar_static` 与 `astar_diversion` 是真算法（is_mock=False）。
`astar_dynamic` 仍是占位：动态限制区、风和链路都还没进搜索。
mock 行的数字没有物理含义，harness 会把含 mock 的那一份输出标成 `_MOCK`。

真算法必须显式拿到机型文件。默认的 placeholder.yaml 全是 null，会直接报错。
跑通用 `scenarios/vehicles/example_not_real.yaml`，那个文件是示例参数，不是真实平台数据。
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.models import DiversionMarginProfile, RouteOutcome
from planner.diversion import (
    ScenarioPlan,
    hard_constraint_report,
    plan_baseline_annotated,
    plan_scenario_with_diversion,
    shared_scene,
)
from sim.energy import IncompleteVehicleProfile, VehicleProfile, load_vehicle

# 合成常数：仅用于让 mock 的能耗量级看起来合理，不是任何机型的真实参数。
_SYNTHETIC_WH_PER_M = 0.02

ALGORITHM_NAMES = ("astar_static", "astar_dynamic", "astar_diversion")
# 兼容旧测试：dict 的键就是算法名。值不再是实例，避免在 import 时绑死机型。
ALGORITHMS = {name: name for name in ALGORITHM_NAMES}


def is_mock_name(name: str) -> bool:
    return name == "astar_dynamic"


@dataclass(frozen=True)
class PlanResult:
    """一次规划在评测层面的结果。profile 不进 CSV，由 harness 另写成剖面 JSON。"""

    task_feasible: bool
    task_result: RouteOutcome
    hard_violations: int
    min_landing_margin: float | None
    route_length_m: float
    energy_used_wh: float
    replan_latency_ms: float
    negative_margin_samples: int = 0
    infeasible_reason: str = ""
    profile: DiversionMarginProfile | None = None

    def as_row(self) -> dict[str, Any]:
        margin = self.min_landing_margin
        if margin is None or (isinstance(margin, float) and not math.isfinite(margin)):
            margin_out: float | str = ""
        else:
            margin_out = round(margin, 4)
        return {
            "task_feasible": self.task_feasible,
            "task_result": self.task_result.value,
            "hard_violations": self.hard_violations,
            "negative_margin_samples": self.negative_margin_samples,
            "min_landing_margin": margin_out,
            "route_length_m": round(self.route_length_m, 1),
            "energy_used_wh": round(self.energy_used_wh, 2),
            "replan_latency_ms": round(self.replan_latency_ms, 1),
            "infeasible_reason": self.infeasible_reason,
        }


class MockPlanner:
    """确定性伪随机占位。同一 (scenario_id, seed, algorithm) 得到相同结果。"""

    is_mock = True

    def __init__(self, name: str) -> None:
        self.name = name

    def _rng(self, scenario_id: str, seed: int) -> random.Random:
        digest = hashlib.sha256(f"{scenario_id}|{seed}|{self.name}".encode()).hexdigest()
        return random.Random(int(digest[:16], 16))

    def plan(self, scenario: dict[str, Any], seed: int) -> PlanResult:
        scenario_id = scenario["id"]
        rng = self._rng(scenario_id, seed)
        origin, dest = scenario["origin"], scenario["destination"]
        straight_m = ((dest["x_m"] - origin["x_m"]) ** 2 + (dest["y_m"] - origin["y_m"]) ** 2) ** 0.5
        route_length_m = straight_m * rng.uniform(1.05, 1.45)
        margin = rng.uniform(-60.0, 220.0)
        feasible = margin >= 0
        violations = 0 if feasible else rng.randint(1, 2)
        return PlanResult(
            task_feasible=feasible,
            task_result=RouteOutcome.DELIVERED if feasible else RouteOutcome.INFEASIBLE,
            hard_violations=violations,
            min_landing_margin=round(margin, 2),
            route_length_m=round(route_length_m, 1),
            energy_used_wh=round(route_length_m * _SYNTHETIC_WH_PER_M, 2),
            replan_latency_ms=round(rng.uniform(40.0, 3000.0), 1),
            negative_margin_samples=0 if feasible else violations,
            infeasible_reason="" if feasible else "mock",
        )


class _RealPlanner:
    is_mock = False

    def __init__(
        self,
        name: str,
        vehicle_path: Path | None = None,
        vehicle: VehicleProfile | None = None,
    ) -> None:
        self.name = name
        self.vehicle_path = None if vehicle_path is None else Path(vehicle_path)
        self._vehicle = vehicle

    def vehicle(self) -> VehicleProfile:
        if self._vehicle is None:
            if self.vehicle_path is None:
                raise IncompleteVehicleProfile(
                    "真实规划器需要机型参数文件（--vehicle）。\n"
                    "  跑通请显式传入 scenarios/vehicles/example_not_real.yaml\n"
                    "  （示例参数，非真实平台数据）。\n"
                    "  不要把示例数字写进 placeholder.yaml 冒充真实平台参数。"
                )
            self._vehicle = load_vehicle(self.vehicle_path)
        return self._vehicle

    def _finish(self, scenario: dict[str, Any], plan_out: ScenarioPlan, *, drop_unsafe: bool) -> PlanResult:
        vehicle = self.vehicle()
        report = hard_constraint_report(plan_out, scenario, vehicle)
        found = plan_out.found
        profile = plan_out.profile
        length = plan_out.length_m
        energy = plan_out.energy_used_wh
        reason = report.reason
        if found and drop_unsafe and not report.feasible:
            found = False
            profile = None
            length = 0.0
            energy = 0.0
            reason = "复算未通过硬约束，按无解处理，不返回该航线：" + report.reason
        if found and report.feasible:
            outcome = RouteOutcome.DELIVERED
            feasible = True
        elif found:
            outcome = RouteOutcome.FAILED
            feasible = False
        else:
            outcome = RouteOutcome.INFEASIBLE
            feasible = False
        margin = None if profile is None else profile.min_margin_wh
        return PlanResult(
            task_feasible=feasible,
            task_result=outcome,
            hard_violations=report.hard_violations if found or plan_out.rejection_kind != "geometry" else 0,
            min_landing_margin=margin,
            route_length_m=length,
            energy_used_wh=energy,
            replan_latency_ms=plan_out.elapsed_ms,
            negative_margin_samples=report.negative_margin_samples if found else 0,
            infeasible_reason="" if feasible else reason,
            profile=profile,
        )


class StaticAStarPlanner(_RealPlanner):
    """几何基线。会返回一条可能余量为负的路线，评测里 task_feasible 按复算结果填。"""

    def __init__(self, vehicle_path: Path | None = None, vehicle: VehicleProfile | None = None) -> None:
        super().__init__("astar_static", vehicle_path, vehicle)

    def plan(self, scenario: dict[str, Any], seed: int) -> PlanResult:
        del seed  # 确定性算法，种子不改变航线
        plan_out = plan_baseline_annotated(scenario, shared_scene(), self.vehicle())
        return self._finish(scenario, plan_out, drop_unsafe=False)


class DiversionAStarPlanner(_RealPlanner):
    """扩展节点时检查备降可达。不满足则剪枝；无解不返回不安全航线。"""

    def __init__(self, vehicle_path: Path | None = None, vehicle: VehicleProfile | None = None) -> None:
        super().__init__("astar_diversion", vehicle_path, vehicle)

    def plan(self, scenario: dict[str, Any], seed: int) -> PlanResult:
        del seed
        plan_out = plan_scenario_with_diversion(scenario, shared_scene(), self.vehicle())
        return self._finish(scenario, plan_out, drop_unsafe=True)


def get(
    name: str,
    *,
    vehicle_path: Path | str | None = None,
    vehicle: VehicleProfile | None = None,
) -> MockPlanner | _RealPlanner:
    if name not in ALGORITHMS:
        raise KeyError(f"未知算法 {name!r}，可选：{', '.join(ALGORITHMS)}")
    if name == "astar_dynamic":
        return MockPlanner(name)
    if name == "astar_static":
        return StaticAStarPlanner(vehicle_path, vehicle)
    return DiversionAStarPlanner(vehicle_path, vehicle)
