"""低空应急配送项目 —— 跨模块公共数据结构（接口契约的唯一代码来源）。

约定
----
- 距离 m；时间用 UTC 的 `datetime`（带时区）或秒（float）；能量 Wh；速度 m/s。
- 每个来自外部或仿真的数据对象都必须带 `provenance`，其中 `is_simulated`
  决定它在材料、日志和视频里能否被称作"实测"。
- 坐标系没有确认前不允许下发路线：`Position` 会在构造时检查基准字段是否自洽。
- 本文件改动必须同步 `docs/接口契约.md`；两边不一致以本文件为准，并立刻改文档。

当前阶段
--------
v0：字段已定义，**机型/能量/速度的数值一律待定**，由学生 A 在 11/10 前
按实际平台参数填入 `scenarios/vehicles/*.yaml`，不得套用通用数值。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.1.0"


# --------------------------------------------------------------------------- #
# 枚举
# --------------------------------------------------------------------------- #
class Frame(str, Enum):
    """位置所使用的平面坐标基准。"""

    ENU_M = "enu_m"  # 以场景原点为原点的局部 ENU，单位 m（v0 仿真场景默认）
    WGS84 = "wgs84"  # 经纬度，接飞控时必须使用


class AltitudeReference(str, Enum):
    """高度基准。三者不能混算 —— 交付计划 7.2 明确要求区分。"""

    AMSL = "amsl"  # 海拔高度
    AGL = "agl"  # 离地高度
    REL_TAKEOFF = "rel_takeoff"  # 相对起飞点高度


class RouteOutcome(str, Enum):
    """一条任务的终态。绝不把"合理终止"混进"配送完成"。"""

    DELIVERED = "delivered"  # 成功送达
    DIVERTED = "diverted"  # 备降，未完成配送
    RETURNED = "returned"  # 返航
    ABORTED = "aborted"  # 主动终止
    INFEASIBLE = "infeasible"  # 规划阶段即判定不可行，未起飞
    FAILED = "failed"  # 执行中失败（含硬约束违规）


# --------------------------------------------------------------------------- #
# 溯源与位置
# --------------------------------------------------------------------------- #
class DataProvenance(BaseModel):
    """任何空间/状态数据的来源与有效期。缺这个字段的数据不允许进入规划。"""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="数据来源标识，如 'sim:scenario_v0', 'fc:px4_sitl', 'doc:访谈20261110'")
    version: str = Field(description="来源内部版本号，改一次加一")
    captured_at: datetime = Field(description="采集时刻（UTC）")
    valid_from: datetime | None = Field(default=None, description="生效时刻；None 表示不限定")
    valid_until: datetime | None = Field(default=None, description="失效时刻；None 表示不限定")
    is_simulated: bool = Field(description="True=仿真/构造数据，False=实测或真实来源")
    uncertainty_note: str | None = Field(
        default=None,
        description="误差范围的文字说明。v0 不假装有数值误差模型，接真实数据前留空或写定性描述",
    )


class Position(BaseModel):
    """带坐标基准与高度基准的位置。ENU 与 WGS84 两种模式互斥，构造时强制检查。"""

    model_config = ConfigDict(extra="forbid")

    frame: Frame
    alt_m: float = Field(description="高度数值，含义由 alt_ref 决定")
    alt_ref: AltitudeReference

    x_m: float | None = Field(default=None, description="ENU 东向坐标 (m)，frame=enu_m 时必填")
    y_m: float | None = Field(default=None, description="ENU 北向坐标 (m)，frame=enu_m 时必填")
    lat_deg: float | None = Field(default=None, description="纬度，frame=wgs84 时必填")
    lon_deg: float | None = Field(default=None, description="经度，frame=wgs84 时必填")

    @model_validator(mode="after")
    def _check_frame_consistency(self) -> Position:
        if self.frame is Frame.ENU_M:
            if self.x_m is None or self.y_m is None:
                raise ValueError("frame=enu_m 必须同时给出 x_m 与 y_m")
            if self.lat_deg is not None or self.lon_deg is not None:
                raise ValueError("frame=enu_m 不允许填经纬度，避免两套基准并存")
        else:
            if self.lat_deg is None or self.lon_deg is None:
                raise ValueError("frame=wgs84 必须同时给出 lat_deg 与 lon_deg")
            if self.x_m is not None or self.y_m is not None:
                raise ValueError("frame=wgs84 不允许填 ENU 坐标")
        return self


# --------------------------------------------------------------------------- #
# 任务与场景
# --------------------------------------------------------------------------- #
class LandingSite(BaseModel):
    """可备降降落点。可用性必须带时窗与有效期，过期点不算有效退出方案。"""

    model_config = ConfigDict(extra="forbid")

    site_id: str
    position: Position
    radius_m: float = Field(gt=0, description="可用降落半径")
    compatible_vehicle_types: list[str] = Field(description="适用机型，空列表等价于对任何机型都不可用")
    available_from: datetime | None = None
    available_until: datetime | None = None
    occupied: bool = Field(default=False, description="当前被占用则不可作为备降点")
    provenance: DataProvenance


class Task(BaseModel):
    """一张配送任务单。字段不全时必须走确认流程，不允许猜。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    origin: Position
    destination: Position
    payload_kg: float = Field(ge=0)
    vehicle_type: str = Field(description="机型标识，对应 scenarios/vehicles/*.yaml 的 key")
    initial_energy_wh: float = Field(gt=0, description="起飞时可用能量（不是 SOC 百分比换算的猜测值）")
    reserve_energy_wh: float = Field(ge=0, description="策略保留能量 E_reserve，备降约束的基线")
    time_limit_s: float | None = Field(default=None, description="任务时限（秒），None 表示不限")
    provenance: DataProvenance


class RiskEvent(BaseModel):
    """风险事件：限制区、风、链路退化、备降点变化、电量异常。"""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    kind: Literal[
        "restriction_zone",
        "wind",
        "link_degradation",
        "landing_site_change",
        "battery_anomaly",
    ]
    geometry: dict[str, Any] = Field(default_factory=dict, description="GeoJSON geometry，坐标基准随场景")
    alt_min_m: float | None = None
    alt_max_m: float | None = None
    effective_from: datetime = Field(description="生效时刻。早于此时刻进入该区域不算违规")
    effective_until: datetime | None = None
    provenance: DataProvenance

    @model_validator(mode="after")
    def _check_alt_band(self) -> RiskEvent:
        if self.alt_min_m is not None and self.alt_max_m is not None and self.alt_min_m > self.alt_max_m:
            raise ValueError("alt_min_m 不能大于 alt_max_m")
        return self


class RiskSnapshot(BaseModel):
    """某一时刻的规划输入快照。规划器与校验器必须读同一个 snapshot_id。"""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    captured_at: datetime
    valid_until: datetime | None = None
    landing_sites: list[LandingSite] = Field(default_factory=list)
    events: list[RiskEvent] = Field(default_factory=list)
    note: str | None = None

    def is_stale(self, now: datetime) -> bool:
        """快照是否已过期。过期快照不得用于批准新路线。"""
        return self.valid_until is not None and now > self.valid_until


# --------------------------------------------------------------------------- #
# 规划与校验
# --------------------------------------------------------------------------- #
class ConstraintCheck(BaseModel):
    """单条硬约束的检查结果。校验器输出这个列表，而不是一个 valid=true。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="例如 'restriction_zone', 'clearance', 'diversion_reachability', 'energy'")
    passed: bool
    detail: str = Field(description="人可读的判定理由，必须能被材料直接引用")


class DiversionMarginSample(BaseModel):
    """备降余量剖面图上的一个采样点（主视觉的数据契约）。"""

    model_config = ConfigDict(extra="forbid")

    s_m: float = Field(ge=0, description="沿航线累计距离")
    t_s: float = Field(ge=0, description="预计飞行时间")
    margin_wh: float = Field(description="E_left - E_reserve - E_need_to_nearest_valid_landing，单位 Wh")
    nearest_site_id: str | None = Field(
        default=None,
        description="该采样点能量意义上最近的可用备降点；None 表示无有效退出路径",
    )
    energy_need_wh: float | None = Field(
        default=None,
        description=(
            "到 nearest_site_id 的能耗（Wh）。None 且 nearest_site_id 为 None 时，"
            "表示几何上没有可达备降点；此时 margin_wh 只是负的哨兵值，不是物理缺口"
        ),
    )


class DiversionMarginProfile(BaseModel):
    """沿整条路线的备降余量。零线以下即为不可行区。"""

    model_config = ConfigDict(extra="forbid")

    route_id: str
    plan_version: str
    reserve_wh: float
    samples: list[DiversionMarginSample] = Field(default_factory=list)

    @property
    def min_margin_wh(self) -> float | None:
        return min((s.margin_wh for s in self.samples), default=None)

    @property
    def negative_sample_count(self) -> int:
        return sum(1 for s in self.samples if s.margin_wh < 0)

    @property
    def is_feasible(self) -> bool:
        """全程非负、样本非空，且每个采样点都有备降点，才算可行。

        空剖面不可信。nearest_site_id 为 None 表示没有有效退出路径，
        即使 margin_wh 被误填成非负也按不可行处理。
        """
        if not self.samples:
            return False
        if any(sample.nearest_site_id is None for sample in self.samples):
            return False
        return self.negative_sample_count == 0


class RoutePlan(BaseModel):
    """候选航线。由规划器产出，但它自己的结论不算数，必须过独立校验。"""

    model_config = ConfigDict(extra="forbid")

    route_id: str
    plan_version: str = Field(description="同一任务每次改线递增，如 v1/v2")
    snapshot_id: str = Field(description="生成此路线所用的数据快照")
    algorithm: str = Field(description="例如 'astar_static', 'astar_diversion_aware'")
    waypoints: list[Position] = Field(min_length=2)
    energy_budget_wh: float = Field(gt=0)
    diversion_site_id: str | None = Field(
        default=None, description="主备降点；None 表示规划时未找到有效退出方案"
    )
    valid_until: datetime | None = None
    checks: list[ConstraintCheck] = Field(
        default_factory=list,
        description="规划器自报的检查结果，仅供参考；独立校验器必须重新复算",
    )


def route_digest(route: RoutePlan) -> str:
    """把校验报告绑定到航线**内容**，而不只是版本号。

    为什么放在 core：这是 RoutePlan 自身的属性，规划器和校验器必须用**同一份实现**
    算同一个摘要。如果两边各写一份，摘要一旦对不上，报告就永远绑不上；
    更糟的情况是绑上了一条被偷偷改过的航线。

    顺带拒绝嵌套模型里的 NaN/Infinity（allow_nan=False）。
    """
    encoded = json.dumps(
        route.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# 执行与遥测
# --------------------------------------------------------------------------- #
class VehicleState(BaseModel):
    """飞控/仿真回传的状态。`executing_plan_version` 是对账的关键字段。"""

    model_config = ConfigDict(extra="forbid")

    ts: datetime
    position: Position
    groundspeed_mps: float | None = None
    energy_remaining_wh: float | None = Field(
        default=None, description="飞控能给出的估计值；拿不到就留 None，不要拿 SOC 硬换算"
    )
    flight_mode: str = Field(description="飞控原始模式名，如 'AUTO.MISSION', 'AUTO.LOITER'")
    gps_fix: str | None = Field(default=None, description="定位质量，如 '3d_fix', 'rtk_fixed'；未知留 None")
    link_quality_pct: float | None = Field(default=None, ge=0, le=100, description="云边链路质量采样值")
    executing_plan_version: str | None = Field(default=None, description="飞控当前正在执行的计划版本")
    provenance: DataProvenance


class PlanCommand(BaseModel):
    """云端下发给边缘/飞控的执行请求。重试必须靠 command_id 去重。"""

    model_config = ConfigDict(extra="forbid")

    command_id: str
    task_id: str
    plan_version: str
    issued_at: datetime
    expires_at: datetime = Field(description="过期命令边缘端必须拒绝执行")
    payload: dict[str, Any] = Field(default_factory=dict)


class PlanAck(BaseModel):
    """飞控/边缘对执行请求的确认。没有 ACK 就不算执行成功。"""

    model_config = ConfigDict(extra="forbid")

    command_id: str
    task_id: str
    plan_version: str
    received_at: datetime
    accepted: bool
    reject_reason: str | None = None
    fc_mode: str | None = None


__all__ = [
    "SCHEMA_VERSION",
    "AltitudeReference",
    "ConstraintCheck",
    "DataProvenance",
    "DiversionMarginProfile",
    "DiversionMarginSample",
    "Frame",
    "LandingSite",
    "PlanAck",
    "PlanCommand",
    "Position",
    "RiskEvent",
    "RiskSnapshot",
    "RouteOutcome",
    "RoutePlan",
    "Task",
    "VehicleState",
    "route_digest",
]
