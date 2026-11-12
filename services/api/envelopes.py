"""HTTP 信封。

任务、快照、航线、备降剖面的字段以 core.models 为准。
这里只补充 HTTP 才有的状态：这次有没有拿到 RoutePlan、余量剖面是否已实现、
M3 入口有没有被调用。不要在这些模型里重定义坐标或能量。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.models import DiversionMarginProfile, LandingSite, Position, RiskSnapshot, RoutePlan


class SlotStatus(BaseModel):
    """云服务配置位。connected 在本版本恒为 false。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    configured: bool
    connected: bool
    note: str


class AgentHookResult(BaseModel):
    """M3 调用入口的回执。applied 必须保持 false：本服务不执行 Agent 的动作。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["not_implemented", "invoked", "error"]
    detail: str
    entry: str | None = None
    applied: bool = False

    @model_validator(mode="after")
    def _do_not_apply(self) -> AgentHookResult:
        if self.applied:
            raise ValueError("API 不执行 M3 返回的动作")
        return self


class AgentStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["not_implemented", "entry_configured"]
    entry_configured: bool
    detail: str


class Health(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    schema_version: str
    service: str
    git_commit: str
    storage_backend: Literal["memory", "sqlite"]
    storage_note: str
    planner_entry: str
    postgres: SlotStatus
    redis: SlotStatus
    agent: AgentStatus


class SceneDocument(BaseModel):
    """场景包。备降点用 LandingSite；障碍和限制区保持 GeoJSON 原文。"""

    model_config = ConfigDict(extra="forbid")

    scene_id: str
    is_simulated: bool
    geometry_status: str
    crs_note: str
    note: str
    obstacles: list[dict[str, Any]]
    restriction_zones: list[dict[str, Any]]
    landing_sites: list[LandingSite]
    counts: dict[str, int]


class SceneBindRequest(BaseModel):
    """把场景收成一张 RiskSnapshot。这是调用参数，不是另一套场景模型。"""

    model_config = ConfigDict(extra="forbid")

    scene_id: str = "v0"
    active_zone_ids: list[str] = Field(default_factory=list)
    occupied_site_ids: list[str] = Field(default_factory=list)


class SceneBindResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: RiskSnapshot
    scene_id: str
    is_simulated: bool
    note: str


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str | None = None
    algorithm: str | None = Field(default=None, max_length=80)


class RouteRecord(BaseModel):
    """一次规划调用的留存。

    `route` 只有在规划器自己返回了合法 RoutePlan 时才非空。
    几何基线给不出 energy_budget_wh，这里留空，不补一个看起来合理的能耗。
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    route_id: str
    plan_version: str
    snapshot_id: str
    algorithm: str
    planner_entry: str
    found: bool
    reason: str | None = None
    length_m: float | None = None
    elapsed_ms: float | None = None
    nodes_expanded: int | None = None
    timing_note: str
    waypoints: list[Position] = Field(default_factory=list)
    altitude_note: str
    route: RoutePlan | None = None
    route_plan_status: Literal["available", "unavailable"]
    route_plan_detail: str
    margin_status: Literal["available", "unavailable"]
    margin_detail: str
    margin_profile: DiversionMarginProfile | None = None
    limitations: list[str] = Field(default_factory=list)
    is_simulated: bool
    simulation_note: str


class PlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: RouteRecord
    agent: AgentHookResult


class MarginView(BaseModel):
    """余量查询。

    status=unavailable 时，三个派生数字必须是 null。
    空剖面的 is_feasible 会是 false，那是另一种结论，不能拿来表示“还没算”。
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    route_id: str
    status: Literal["available", "unavailable"]
    detail: str
    profile: DiversionMarginProfile | None = None
    min_margin_wh: float | None = None
    negative_sample_count: int | None = None
    is_feasible: bool | None = None
