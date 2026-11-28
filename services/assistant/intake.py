"""Natural-language task intakes: persisted evidence records, not executable Tasks.

An intake is NOT ``core.models.Task``. It never enters the M3 state machine,
never produces a flight command, and is always marked simulated. Its purpose is
to make a spoken request and the evidence behind it visible in the web console.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PlaceQuery(Strict):
    name: str = Field(min_length=1, max_length=120)


class ForecastQuery(Strict):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    scheduled_for: str | None = None


class IntakeCreate(Strict):
    text: str = Field(min_length=1, max_length=3000)
    origin: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    scheduled_for: str | None = None
    schedule_note: str = ""
    schedule_confirmed: bool = False
    origin_point: list[float] | None = None
    destination_point: list[float] | None = None
    places_confirmed: bool = False
    payload_kg: float | None = Field(default=None, ge=0, le=100)
    priority: Literal["P1", "P2"] | None = None

    @field_validator("origin_point", "destination_point")
    @classmethod
    def coordinates(cls, point):
        if point is not None and (
            len(point) != 2 or not -180 <= point[0] <= 180 or not -85.0511 <= point[1] <= 85.0511
        ):
            raise ValueError("地点必须是有效 WGS84 经纬度")
        return point


class IntakeConfirmation(IntakeCreate):
    """Explicit browser action. This contract is never exposed as a model tool."""

    confirmation_id: UUID
    origin_point: list[float] = Field(min_length=2, max_length=2)
    destination_point: list[float] = Field(min_length=2, max_length=2)
    scheduled_for: str
    payload_kg: float = Field(ge=0, le=100)
    priority: Literal["P1", "P2"]

    @field_validator("scheduled_for")
    @classmethod
    def aware_schedule(cls, value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("确认时间必须包含时区")
        return parsed.isoformat()

    def as_input(self, text: str) -> IntakeCreate:
        return IntakeCreate.model_validate(
            {
                **self.model_dump(exclude={"confirmation_id"}),
                "text": text,
                "schedule_confirmed": True,
                "places_confirmed": True,
            }
        )


class PlaceEvidence(Strict):
    name: str
    point: list[float] | None = None
    crs: str = "unresolved"
    source: str
    address: str = ""
    is_simulated: bool = True


class WeatherEvidence(Strict):
    status: Literal["ok", "unavailable"] = "unavailable"
    kind: Literal["forecast"] = "forecast"
    source: str = "Open-Meteo / hourly forecast"
    scheduled_for: str | None = None
    valid_for: str | None = None
    requested_point: list[float] | None = None
    fetched_at: str | None = None
    values: dict[str, float | None] = Field(default_factory=dict)
    reason: str = ""
    note: str = "模式预报值，不是实测；风速未进入能耗或绕路计算。"


class TaskIntake(Strict):
    intake_id: str
    text: str
    origin: PlaceEvidence
    destination: PlaceEvidence
    scheduled_for: str | None
    schedule_note: str
    payload_kg: float | None
    priority: str | None
    weather: WeatherEvidence
    airspace: dict
    route_preview: dict | None
    real_route: dict | None = None
    constraint_snapshot: dict | None = None
    airspace_check: dict | None = None
    route_history: list[dict] = Field(default_factory=list)
    warnings: list[str]
    created_at: str
    request_digest: str | None = None
    is_simulated: Literal[True] = True
    dispatch_enabled: Literal[False] = False

    @classmethod
    def build(
        cls,
        body: IntakeCreate,
        *,
        origin: PlaceEvidence,
        destination: PlaceEvidence,
        weather: WeatherEvidence,
        airspace: dict,
        route_preview: dict | None,
        warnings: list[str],
        real_route: dict | None = None,
        constraint_snapshot: dict | None = None,
        airspace_check: dict | None = None,
        route_history: list[dict] | None = None,
    ):
        return cls(
            intake_id=str(uuid4()),
            text=body.text,
            origin=origin,
            destination=destination,
            scheduled_for=body.scheduled_for,
            schedule_note=body.schedule_note,
            payload_kg=body.payload_kg,
            priority=body.priority,
            weather=weather,
            airspace=airspace,
            route_preview=route_preview,
            real_route=real_route,
            constraint_snapshot=constraint_snapshot,
            airspace_check=airspace_check,
            route_history=route_history or [],
            warnings=warnings,
            created_at=datetime.now(UTC).isoformat(),
        )


def enrich_legacy_intake(record: dict) -> dict:
    """Annotate older building-only intake records that predate ConstraintSnapshot."""
    if not isinstance(record, dict):
        return record
    route = record.get("real_route") or {}
    snap = record.get("constraint_snapshot") or (route.get("planning_result") or {}).get(
        "constraint_snapshot"
    )
    if snap is None and route.get("status") == "ok" and record.get("airspace_check") is None:
        from services.assistant.airspace_snapshot import check_route_against_snapshot

        legacy_check = check_route_against_snapshot(route.get("waypoints") or [], None)
        return {
            **record,
            "constraint_snapshot": None,
            "airspace_check": legacy_check,
            "route_history": list(record.get("route_history") or []),
        }
    return {
        **record,
        "route_history": list(record.get("route_history") or []),
    }


class IntakeStore:
    """JSON-per-intake store under ``AERIS_INTAKE_DIR`` (default logs/intakes)."""

    def __init__(self, root: Path | None = None):
        self.root = root or Path(os.getenv("AERIS_INTAKE_DIR", str(ROOT / "logs/intakes")))
        self._lock = threading.RLock()

    @staticmethod
    def request_id(key: str) -> str:
        return str(uuid5(NAMESPACE_URL, "aeris:intake:" + key))

    def replay(self, key: str, digest: str) -> dict | None:
        with self._lock:
            try:
                saved = self.get(self.request_id(key))
            except KeyError:
                return None
            if saved.get("request_digest") != digest:
                raise ValueError("同一次确认的内容已改变，请重新确认")
            return saved

    def create_once(self, record: TaskIntake, key: str, digest: str) -> tuple[dict, bool]:
        # ponytail: one process-local writer; use a database unique constraint before multiple workers.
        with self._lock:
            saved = self.replay(key, digest)
            if saved is not None:
                return saved, False
            record = record.model_copy(update={"intake_id": self.request_id(key), "request_digest": digest})
            return self.create(record), True

    def _path(self, intake_id: str) -> Path:
        if not intake_id or "/" in intake_id or "\\" in intake_id or ".." in intake_id:
            raise KeyError(intake_id)
        return self.root / f"{intake_id}.json"

    def create(self, record: TaskIntake) -> dict:
        payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self._path(record.intake_id)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
        return record.model_dump(mode="json")

    def get(self, intake_id: str) -> dict:
        path = self._path(intake_id)
        with self._lock:
            if not path.exists():
                raise KeyError(intake_id)
            return enrich_legacy_intake(json.loads(path.read_text(encoding="utf-8")))

    def list(self, limit: int = 100) -> list[dict]:
        with self._lock:
            if not self.root.exists():
                return []
            paths = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
            return [enrich_legacy_intake(json.loads(p.read_text(encoding="utf-8"))) for p in paths]


store = IntakeStore()
