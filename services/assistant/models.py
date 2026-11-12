"""UI assistant contracts, not replacements for core flight contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.assistant.telemetry import LiveTelemetry


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Bounds(Contract):
    minX: float = Field(ge=0, le=3000)
    minY: float = Field(ge=0, le=3000)
    maxX: float = Field(ge=0, le=3000)
    maxY: float = Field(ge=0, le=3000)

    @model_validator(mode="after")
    def ordered(self):
        if self.maxX < self.minX or self.maxY < self.minY:
            raise ValueError("Bounds must be ordered")
        return self


class Terrain(Contract):
    revision: int = Field(ge=1)
    count: int = Field(ge=0, le=8281)
    maxDelta: float = Field(ge=0, le=20000)
    source: str = Field(min_length=1, max_length=200)
    capturedAt: datetime
    bounds: Bounds | None = None

    @field_validator("capturedAt")
    @classmethod
    def timezone(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timezone required")
        return value


class Telemetry(Contract):
    battery: float = Field(ge=0, le=100)
    voltage: float = Field(ge=0, le=1000)
    current: float = Field(ge=-1000, le=1000)
    energyWh: float | None = Field(default=None, ge=0)
    altitude: float = Field(ge=-500, le=10000)
    speed: float = Field(ge=0, le=500)
    climb: float
    heading: float = Field(ge=0, le=360)
    pitch: float = Field(ge=-180, le=180)
    roll: float = Field(ge=-180, le=180)
    rssi: float = Field(ge=-200, le=0)
    satellites: int = Field(ge=0, le=200)
    hdop: float = Field(ge=0, le=100)
    rtt: float = Field(ge=0, le=100000)
    rotors: list[float] = Field(min_length=4, max_length=4)
    motorTemp: float
    coverage: float = Field(ge=0, le=100)
    scanned: int = Field(ge=0)
    totalCells: int = Field(ge=1, le=100000)
    distanceToTarget: float = Field(ge=0)
    obstacleDistance: float = Field(ge=0)


class Event(Contract):
    id: str = Field(max_length=100)
    time: str = Field(max_length=40)
    type: Literal["info", "success", "warning"]
    title: str = Field(max_length=200)
    detail: str = Field(max_length=1000)


class Context(Contract):
    is_simulated: Literal[True] = True
    sampled_at: datetime
    task_id: Literal["T-S1-01"] = "T-S1-01"
    selected_task_id: UUID | None = None
    route_id: Literal["S1-01-baseline"] = "S1-01-baseline"
    progress: float = Field(ge=0, le=1)
    telemetry_mode: Literal["demo", "live"] = "demo"
    telemetry: Telemetry | None
    live_telemetry: LiveTelemetry | None = None
    terrain: Terrain | None = None
    events: list[Event] = Field(default_factory=list, max_length=100)

    @field_validator("sampled_at")
    @classmethod
    def timezone(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timezone required")
        return value

    @model_validator(mode="after")
    def telemetry_matches_mode(self):
        if self.telemetry_mode == "demo":
            if self.telemetry is None or self.live_telemetry is not None:
                raise ValueError("Demo context requires demo telemetry")
        elif self.telemetry is not None:
            raise ValueError("Live context cannot contain demo telemetry")
        return self


class Draft(Contract):
    name: str = Field(default="配送任务草稿", min_length=1, max_length=80)
    origin: str | None = Field(default=None, max_length=120)
    destination: str | None = Field(default=None, max_length=120)
    payload_kg: float | None = Field(default=None, ge=0, le=100)
    priority: Literal["P1", "P2"] = "P2"


class History(Contract):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6000)


class Turn(Contract):
    request_id: UUID
    text: str = Field(min_length=1, max_length=3000)
    history: list[History] = Field(default_factory=list, max_length=16)
    draft: Draft | None = None
    context: Context

    @field_validator("text")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Text cannot be blank")
        return value.strip()


class DraftUpdate(Contract):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    origin: str | None = Field(default=None, max_length=120)
    destination: str | None = Field(default=None, max_length=120)
    payload_kg: float | None = Field(default=None, ge=0, le=100)
    priority: Literal["P1", "P2"] | None = None


class NoArgs(Contract):
    pass


class DocumentQuery(Contract):
    query: str = Field(min_length=1, max_length=3000, pattern=r"\S")
