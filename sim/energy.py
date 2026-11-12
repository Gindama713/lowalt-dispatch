"""能量模型（M2 的能量部分）。

**这是全项目最容易被伪造的地方。** 机型、电池、爬升率任一参数是猜的，后面每一条
备降余量曲线、每一个"任务可行"的结论都是假的，而且没人看得出来。所以：

`load_vehicle()` 遇到 `null` 就**直接抛异常**，不做任何默认值填充。
宁可跑不起来，也不要跑出一个看起来合理的错数字。

模型本身是 v0 简化版，由学生 B 负责替换成标定模型：
- 巡航能耗 = 单位距离能耗 × 水平距离
- 爬升能耗 = 悬停单位时间能耗 × 爬升耗时（爬升过程按悬停功耗近似，偏保守）
- 风：暂不建模，见 `wind_note`
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

VEHICLE_PATH = Path(__file__).resolve().parents[1] / "scenarios" / "vehicles" / "placeholder.yaml"

REQUIRED_NUMERIC = (
    "max_payload_kg",
    "cruise_speed_mps",
    "climb_rate_mps",
    "energy_per_meter_wh",
    "energy_per_second_hover_wh",
    "usable_battery_wh",
    "reserve_policy_wh",
)

OPTIONAL_NUMERIC = (
    "descent_rate_mps",
    "max_bank_deg",
    "service_ceiling_m",
    "battery_capacity_wh",
)


class IncompleteVehicleProfile(RuntimeError):
    """机型参数缺失。这条异常是设计出来的，不是意外。"""


@dataclass(frozen=True)
class VehicleProfile:
    vehicle_key: str
    max_payload_kg: float
    cruise_speed_mps: float
    climb_rate_mps: float
    energy_per_meter_wh: float
    energy_per_second_hover_wh: float
    usable_battery_wh: float
    reserve_policy_wh: float
    descent_rate_mps: float | None = None
    max_bank_deg: float | None = None
    service_ceiling_m: float | None = None
    battery_capacity_wh: float | None = None
    source: str | None = None
    uncertainty_note: str | None = None
    is_example: bool = False
    display_name: str | None = None
    draft_geometry_vehicle_alias: str | None = None

    @property
    def wind_note(self) -> str:
        return "v0 未建模风场：能耗按无风计算，实际逆风会低估。B 负责替换。"


def load_vehicle(path: Path | None = None, key: str | None = None) -> VehicleProfile:
    p = path or VEHICLE_PATH
    if not p.is_file():
        raise FileNotFoundError(f"机型参数文件不存在：{p}")

    raw: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8"))
    vehicles: dict[str, Any] = raw.get("vehicles") or {}
    if not vehicles:
        raise IncompleteVehicleProfile(f"{p} 里没有 vehicles 段")

    vehicle_key = key or next(iter(vehicles))
    entry: dict[str, Any] = vehicles[vehicle_key]

    missing = [f for f in REQUIRED_NUMERIC if entry.get(f) is None]
    if missing:
        raise IncompleteVehicleProfile(
            "机型参数不完整，无法建立能量模型，因此不会产出任何能耗或备降余量数字。\n"
            f"  文件：{p}\n"
            f"  机型：{vehicle_key}\n"
            f"  缺失 {len(missing)} 项：{', '.join(missing)}\n"
            "  处理：由学生 A 按实际平台参数补齐（厂商手册值可用，但要在 source 里写明来源，\n"
            "        并在 uncertainty_note 里标'未标定'）。补齐前请继续使用 mock 规划器。"
        )

    alias = entry.get("draft_geometry_vehicle_alias")
    return VehicleProfile(
        vehicle_key=vehicle_key,
        **{f: float(entry[f]) for f in REQUIRED_NUMERIC},
        **{f: (float(entry[f]) if entry.get(f) is not None else None) for f in OPTIONAL_NUMERIC},
        source=entry.get("source"),
        uncertainty_note=entry.get("uncertainty_note"),
        is_example=bool(entry.get("is_example", False) or raw.get("is_example", False)),
        display_name=entry.get("display_name"),
        draft_geometry_vehicle_alias=None if alias is None else str(alias),
    )


# --------------------------------------------------------------------------- #
# 能耗计算
# --------------------------------------------------------------------------- #
def cruise_energy_wh(profile: VehicleProfile, distance_m: float) -> float:
    if distance_m < 0:
        raise ValueError("距离不能为负")
    return profile.energy_per_meter_wh * distance_m


def climb_energy_wh(profile: VehicleProfile, delta_alt_m: float) -> float:
    """上升为正、下降暂按 0 计（下降不耗巡航功率，但也忽略了回收/滑翔收益）。"""
    if delta_alt_m <= 0:
        return 0.0
    return profile.energy_per_second_hover_wh * (delta_alt_m / profile.climb_rate_mps)


def leg_energy_wh(profile: VehicleProfile, distance_m: float, delta_alt_m: float = 0.0) -> float:
    return cruise_energy_wh(profile, distance_m) + climb_energy_wh(profile, delta_alt_m)


def max_range_m(profile: VehicleProfile, available_energy_wh: float) -> float:
    """给定可用能量，无风平飞能走多远。不扣保留量——扣不扣由调用方决定。"""
    if available_energy_wh < 0:
        raise ValueError("可用能量不能为负")
    return available_energy_wh / profile.energy_per_meter_wh


def cruise_time_s(profile: VehicleProfile, distance_m: float) -> float:
    return distance_m / profile.cruise_speed_mps
