"""Loopback BFF with NDJSON tool events. No cloud resources required."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from services.api.routes import router as dispatch_router
from services.api.routes import runtime as dispatch_runtime
from services.assistant.airspace_snapshot import (
    ConstraintSnapshot,
    build_corridor_simulation_zone,
    check_route_against_snapshot,
    snapshot_from_geojson,
)
from services.assistant.airspace_snapshot import (
    store as airspace_store,
)
from services.assistant.dispatch_bridge import DispatchDraftInput, build_task_draft
from services.assistant.engine import Engine, ModelUnavailable, Settings
from services.assistant.intake import store as intake_store
from services.assistant.models import Turn
from services.assistant.navigation import CandidateInput, candidate_routes
from services.assistant.places import search_places
from services.assistant.telemetry import read_latest, stream_telemetry
from services.assistant.tools import (
    CAPABILITIES,
    _invoke_route_provider,
    apply_route_update_to_intake,
    real_route_for_intake,
)
from services.assistant.vehicles import CustomVehicle, VehicleTestInput
from services.identity.routes import COOKIE
from services.identity.routes import router as identity_router
from services.identity.store import IdentityStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.api.main import create_app
    from services.api.runtime import from_env

    app.state.identity = IdentityStore(Path(os.getenv("AERIS_IDENTITY_DIR", "logs/identity")))
    app.state.planning = create_app()
    dispatch = from_env()
    app.state.dispatch = dispatch
    app.state.dispatch_error = False
    stop = threading.Event()

    def advance():
        while not stop.wait(0.5):
            try:
                dispatch.tick()
            except Exception:
                # Surface a failed pump instead of silently advertising health.
                app.state.dispatch_error = True
                break

    worker = threading.Thread(target=advance, daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=10)
        dispatch.close()
        app.state.planning.state.store.close()
        app.state.identity.close()
        app.state.dispatch = None


app = FastAPI(
    title="AERIS assistant local BFF", docs_url="/api/assistant/docs", redoc_url=None, lifespan=lifespan
)
app.include_router(dispatch_router)
app.include_router(identity_router)


class PlanningGateway:
    async def __call__(self, scope, receive, send):
        await app.state.planning(scope, receive, send)


app.mount("/api/planning", PlanningGateway())
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
settings = Settings.from_env()
engine = Engine(settings)
navigation_slot = threading.BoundedSemaphore(1)


@app.get("/api/assistant/vehicles")
def vehicle_catalog():
    from services.assistant.vehicles import catalog

    return {**catalog(), "dispatch_enabled": False}


@app.post("/api/assistant/vehicles/validate")
def validate_custom_vehicle(body: CustomVehicle):
    return {"vehicle": body.model_dump(), "data_status": "user_supplied_test", "dispatch_enabled": False}


@app.post("/api/assistant/vehicles/evaluate")
def evaluate_vehicle_test(body: VehicleTestInput):
    from services.assistant.vehicles import evaluate_vehicle

    return evaluate_vehicle(
        body, body.distance_km * 1000, wind_speed_mps=body.wind_speed_mps, wind_direction=body.wind_direction
    )


class AirspaceSnapshotUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["replace", "known_empty", "clear"] = "replace"
    geojson: dict | None = None
    zone_buffer_m: float = Field(default=0.0, ge=0.0, le=500.0)
    scheduled_for: str | None = None
    set_active: bool = True


class CorridorSimulationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    origin: list[float] = Field(min_length=2, max_length=2)
    destination: list[float] = Field(min_length=2, max_length=2)
    waypoints: list[list[float]] | None = Field(default=None, max_length=1000)
    append: bool = False
    zone_buffer_m: float = Field(default=0.0, ge=0.0, le=500.0)
    scheduled_for: str | None = None


class FlySafeQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    origin: list[float] = Field(min_length=2, max_length=2)
    destination: list[float] = Field(min_length=2, max_length=2)
    zone_buffer_m: float = Field(default=0.0, ge=0.0, le=500.0)
    scheduled_for: str | None = None
    drone: str | None = Field(default=None, max_length=64)
    preserve_snapshot_id: str | None = Field(default=None, max_length=64)


class RouteAirspaceCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    waypoints: list[list[float]] = Field(min_length=2, max_length=1000)
    snapshot_id: str | None = Field(default=None, max_length=64)
    scheduled_for: str | None = None


class IntakeRouteRefreshInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    snapshot_id: str | None = Field(default=None, max_length=64)
    zone_buffer_m: float | None = Field(default=None, ge=0.0, le=500.0)


@app.get("/api/assistant/airspace/snapshot")
def get_active_airspace_snapshot():
    active = airspace_store.get_active()
    return {
        "status": active.source_status if active else "not_loaded",
        "snapshot": active.model_dump(mode="json") if active else None,
        "dispatch_enabled": False,
    }


@app.get("/api/assistant/airspace/snapshots/{snapshot_id}")
def get_airspace_snapshot_by_id(snapshot_id: str):
    try:
        return airspace_store.get(snapshot_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "找不到指定的空域约束快照") from None


@app.post("/api/assistant/airspace/snapshot")
def upsert_airspace_snapshot(body: AirspaceSnapshotUpsert):
    try:
        if body.mode == "clear":
            snap = airspace_store.clear_active(zone_buffer_m=body.zone_buffer_m)
        elif body.mode == "known_empty":
            snap = ConstraintSnapshot.build(
                zones=[],
                source_status="known_empty",
                zone_buffer_m=body.zone_buffer_m,
                scheduled_for=body.scheduled_for,
            )
            snap = airspace_store.save(snap, set_active=body.set_active)
        else:
            if body.geojson is None:
                raise ValueError("上传空域约束时必须提供 geojson")
            snap = snapshot_from_geojson(
                body.geojson,
                zone_buffer_m=body.zone_buffer_m,
                scheduled_for=body.scheduled_for,
            )
            snap = airspace_store.save(snap, set_active=body.set_active)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    write_audit(
        {
            "type": "airspace_snapshot_upsert",
            "mode": body.mode,
            "snapshot_id": snap.snapshot_id,
            "digest": snap.digest,
            "enforced_zone_count": snap.enforced_zone_count,
            "dispatch_enabled": False,
        }
    )
    return snap.model_dump(mode="json")


@app.post("/api/assistant/airspace/simulate-corridor")
def simulate_corridor_airspace(body: CorridorSimulationInput):
    try:
        existing = airspace_store.get_active() if body.append else None
        prior_zones = list(existing.zones) if existing else []
        zone = build_corridor_simulation_zone(
            body.origin,
            body.destination,
            body.waypoints,
            existing_zones=prior_zones,
        )
        snap = ConstraintSnapshot.build(
            zones=[*prior_zones, zone],
            source_status="simulation_preset",
            zone_buffer_m=body.zone_buffer_m,
            scheduled_for=body.scheduled_for,
        )
        snap = airspace_store.save(snap, set_active=True)
        route_check = (
            check_route_against_snapshot(
                body.waypoints,
                snap,
                scheduled_for=body.scheduled_for,
            )
            if body.waypoints and len(body.waypoints) >= 2
            else None
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    write_audit(
        {
            "type": "airspace_simulate_corridor",
            "snapshot_id": snap.snapshot_id,
            "digest": snap.digest,
            "zone_id": zone.id,
            "dispatch_enabled": False,
        }
    )
    return {
        "snapshot": snap.model_dump(mode="json"),
        "added_zone_id": zone.id,
        "route_check": route_check,
        "dispatch_enabled": False,
    }


@app.post("/api/assistant/airspace/flysafe")
def query_flysafe_zones(body: FlySafeQueryInput):
    """Query DJI FlySafe for the planning bbox and store a manufacturer-reference snapshot.

    Disabled processes (``AERIS_FLYSAFE_LIVE=0``) do not contact the network and
    do not replace the active snapshot. Failures and empty results are
    ``unavailable`` with no invented geometry.
    """
    from services.assistant.flysafe import (
        FLYSAFE_SOURCE,
        flysafe_live_enabled,
        refresh_planning_snapshot,
    )

    if not flysafe_live_enabled():
        return {
            "status": "disabled",
            "snapshot": None,
            "reason": "本进程未开启大疆 FlySafe 实时查询（AERIS_FLYSAFE_LIVE=0），未编造围栏",
            "reference_label": FLYSAFE_SOURCE,
            "dispatch_enabled": False,
            "operationally_approved": False,
        }
    prior = None
    if body.preserve_snapshot_id:
        try:
            prior = airspace_store.get(body.preserve_snapshot_id)
        except KeyError:
            prior = airspace_store.get_active()
    else:
        prior = airspace_store.get_active()
    try:
        snap = refresh_planning_snapshot(
            body.origin,
            body.destination,
            zone_buffer_m=body.zone_buffer_m,
            scheduled_for=body.scheduled_for,
            prior=prior,
            drone=body.drone,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if snap is None:
        raise HTTPException(503, "大疆 FlySafe 查询没有执行，未编造围栏")
    snap = airspace_store.save(snap, set_active=True)
    write_audit(
        {
            "type": "airspace_flysafe_query",
            "snapshot_id": snap.snapshot_id,
            "digest": snap.digest,
            "source_status": snap.source_status,
            "total_zone_count": snap.total_zone_count,
            "enforced_zone_count": snap.enforced_zone_count,
            "failure_reason": snap.failure_reason,
            "reference_label": FLYSAFE_SOURCE,
            "dispatch_enabled": False,
        }
    )
    return {
        "status": snap.source_status,
        "snapshot": snap.model_dump(mode="json"),
        "reference_label": FLYSAFE_SOURCE,
        "reason": snap.failure_reason,
        "dispatch_enabled": False,
        "operationally_approved": False,
    }


class FlySafeNationalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    force: bool = False
    drone: str | None = Field(default=None, max_length=64)


@app.get("/api/assistant/airspace/flysafe/national")
def read_flysafe_national_overlay():
    """Return the cached China-wide display overlay. Does not query DJI or planning."""

    from services.assistant.flysafe_national import read_national_overlay

    return read_national_overlay()


@app.post("/api/assistant/airspace/flysafe/national")
def refresh_flysafe_national_overlay(body: FlySafeNationalInput):
    """Refresh the China-wide display overlay. Never writes the planning snapshot."""

    from services.assistant.flysafe_national import refresh_national_overlay

    result = refresh_national_overlay(force=body.force, drone=body.drone)
    write_audit(
        {
            "type": "airspace_flysafe_national",
            "status": result["status"],
            "zone_count": result["zone_count"],
            "incomplete": result["incomplete"],
            "retained_prior": result["retained_prior"],
            "reference_label": result["reference_label"],
            "dispatch_enabled": False,
        }
    )
    return result


@app.post("/api/assistant/airspace/check")
def check_airspace_route(body: RouteAirspaceCheckInput):
    try:
        snap = (
            airspace_store.get(body.snapshot_id)
            if body.snapshot_id
            else airspace_store.get_active_or_unloaded(scheduled_for=body.scheduled_for)
        )
        return check_route_against_snapshot(
            body.waypoints,
            snap,
            scheduled_for=body.scheduled_for,
        )
    except KeyError:
        raise HTTPException(404, "指定的空域约束快照不存在") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/assistant/navigation/candidates")
def navigation_candidates(body: CandidateInput):
    if not navigation_slot.acquire(blocking=False):
        raise HTTPException(429, "航线计算忙碌，请稍后重试")
    try:
        result = candidate_routes(body)
        if body.frame == "WGS84" and body.intake_id and isinstance(result.get("constraint_snapshot"), dict):
            try:
                existing_intake = intake_store.get(body.intake_id)
            except KeyError:
                existing_intake = None
            if existing_intake is not None:
                route_obj = result.get("route") or {}
                route_record = {
                    "status": result["status"],
                    "frame": "WGS84",
                    "route_id": route_obj.get("id"),
                    "route": route_obj,
                    "scene_id": result.get("scene_id"),
                    "planning_result": result,
                    "waypoints": route_obj.get("waypoints") or [],
                    "length_m": route_obj.get("length_m"),
                    "resolution_requested_m": result.get("resolution_requested_m"),
                    "resolution_used_m": result.get("resolution_used_m"),
                    "clearance_m": result.get("clearance_m"),
                    "zone_buffer_m": result.get("zone_buffer_m"),
                    "continuous_clearance_verified": result.get("continuous_clearance_verified", False),
                    "continuous_zone_verified": result.get("continuous_zone_verified", False),
                    "geometric_generation": result.get("geometric_generation"),
                    "constraint_snapshot": result.get("constraint_snapshot"),
                    "airspace_check": result.get("airspace_check"),
                    "previous_route_check": result.get("previous_route_check"),
                    "route_changed": result.get("route_changed"),
                    "obstacle_source": result.get("obstacle_source"),
                    "reason": (result.get("alternatives") or [{}])[0].get("reason"),
                    "attempts": result.get("plan_attempts", []),
                    "warnings": result.get("warnings", [])[:5],
                    "computed_at": datetime.now(UTC).isoformat(),
                    "note": "几何避障参考；未接真实空域、地形、线缆，不代表获准飞行。",
                }
                updated_intake = apply_route_update_to_intake(
                    existing_intake,
                    route_record,
                    ConstraintSnapshot.model_validate(result["constraint_snapshot"]),
                    store_override=intake_store,
                )
                result["synced_intake_id"] = updated_intake["intake_id"]
                result["route_version"] = updated_intake["real_route"].get("version_label")
                if updated_intake.get("route_history"):
                    result["previous_route_check"] = updated_intake["route_history"][-1].get(
                        "rechecked_airspace_check"
                    )
        write_audit({"type": "navigation_candidates", "input": body.model_dump(), "dispatch_enabled": False})
        return result
    except Exception as exc:
        from services.assistant.osm_obstacles import OSMDataUnavailable

        if isinstance(exc, OSMDataUnavailable):
            raise HTTPException(
                503,
                {
                    "status": "unavailable",
                    "obstacle_source": "OpenStreetMap / Overpass",
                    "reason": str(exc),
                    "dispatch_enabled": False,
                },
            ) from exc
        if isinstance(exc, ValueError):
            raise HTTPException(422, str(exc)) from exc
        raise
    finally:
        navigation_slot.release()


@app.get("/api/assistant/navigation/scenes/{scene_id}")
def navigation_scene(scene_id: str):
    from services.assistant.osm_obstacles import OSMDataUnavailable, load_cached_scene

    try:
        return load_cached_scene(scene_id)
    except (OSMDataUnavailable, ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, "该真实地图快照不存在或已过期，请重新计算航线") from exc


audit_lock = threading.Lock()
slots = threading.BoundedSemaphore(3)


@app.middleware("http")
async def local_requests(request: Request, call_next):
    origin = request.headers.get("origin")
    if origin and origin not in {
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:4174",
        "http://localhost:4174",
        "http://127.0.0.1:8012",
        "http://localhost:8012",
    }:
        return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
    path = request.url.path
    public = {
        "/api/auth/policy",
        "/api/auth/setup",
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/mfa/login",
        "/api/assistant/health",
    }
    if path.startswith("/api/"):
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("x-aeris-request") != "1":
            return JSONResponse({"detail": "缺少同源请求标记，请刷新页面后重试"}, status_code=403)
        if path not in public:
            user = app.state.identity.user(request.cookies.get(COOKIE, ""))
            if not user:
                return JSONResponse({"detail": "请登录后继续"}, status_code=401)
            request.state.actor_id = user["id"]
            permission = None
            if path.startswith(("/api/dispatch", "/api/planning")):
                permission = "task.read" if request.method == "GET" else "task.create"
                if path.endswith(("/confirm", "/abandon")):
                    permission = "task.execute"
            elif path.startswith("/api/assistant/"):
                permission = "map.read" if request.method == "GET" else "task.create"
            elif path.startswith("/api/telemetry/"):
                permission = "telemetry.read"
            elif path.startswith("/api/workspace/"):
                permission = "workspace.read"
            if permission and permission not in user["permissions"]:
                return JSONResponse({"detail": "当前角色没有此操作权限"}, status_code=403)
    response = await call_next(request)
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/api/workspace/summary")
def workspace_summary(request: Request):
    dispatch = dispatch_runtime(request)
    tasks = dispatch.list_tasks()
    return {
        "tasks": tasks,
        "planning_tasks": [
            task.model_dump(mode="json") for task in app.state.planning.state.store.list_tasks()
        ],
        "dispatch": dispatch.health(),
        "services": [
            {"name": "任务 Agent / M3", "status": "ready", "detail": "本地状态机 · 工具审计"},
            {"name": "规划与校验 / M2", "status": "ready", "detail": "本地规划器 · 独立校验"},
            {"name": "边缘执行 / M4", "status": "ready", "detail": "合成执行端 · 不连接 PX4"},
            {
                "name": "飞控遥测",
                "status": "configured" if os.getenv("AERIS_TELEMETRY_FILE") else "pending",
                "detail": "已配置文件源，连接态请在设备页核对"
                if os.getenv("AERIS_TELEMETRY_FILE")
                else "尚未配置遥测文件源",
            },
            {
                "name": "大模型服务",
                "status": "configured" if settings.provider == "maas" else "local",
                "detail": "Maas 已配置，调用结果以助手为准"
                if settings.provider == "maas"
                else "本地规则工具助手",
            },
        ],
    }


@app.get("/api/assistant/health")
def health():
    return {
        "status": "ok",
        "provider": settings.provider,
        "model_configured": settings.provider == "maas",
        "dispatch_enabled": False,
        "data_mode": "ui_demo",
        "protocol": "aeris-assistant-1",
    }


@app.get("/api/assistant/places/search")
def places(q: str):
    return search_places(q)


@app.get("/api/assistant/capabilities")
def capabilities():
    """What this build actually does; rendered by the assistant instead of prompt buttons."""
    return {**CAPABILITIES, "dispatch_enabled": False, "is_simulated": True}


@app.get("/api/assistant/intakes")
def list_intakes():
    """Read-only list of natural-language task intakes. Never an executable task."""
    return {"items": intake_store.list(), "is_simulated": True, "dispatch_enabled": False}


@app.get("/api/assistant/intakes/{intake_id}")
def get_intake(intake_id: str):
    try:
        return intake_store.get(intake_id)
    except KeyError:
        raise HTTPException(404, "找不到该任务工单") from None


@app.post("/api/assistant/intakes/{intake_id}/dispatch-draft")
def dispatch_draft(intake_id: str, body: DispatchDraftInput):
    """Turn an intake into a core.models.Task draft; never executes or plans."""
    try:
        intake = intake_store.get(intake_id)
    except KeyError:
        raise HTTPException(404, "找不到该任务工单") from None
    result = build_task_draft(intake, body)
    write_audit(
        {
            "type": "dispatch_draft",
            "intake_id": intake_id,
            "status": result["status"],
            "blockers": [item["code"] for item in result["blockers"]],
            "dispatch_enabled": False,
        }
    )
    return result


@app.post("/api/assistant/intakes/{intake_id}/route")
def refresh_intake_route(
    intake_id: str,
    body: Annotated[IntakeRouteRefreshInput | None, Body()] = None,
):
    """Compute or recalculate a real-geometry route for an existing intake bound to a ConstraintSnapshot."""
    try:
        intake = intake_store.get(intake_id)
    except KeyError:
        raise HTTPException(404, "找不到该任务工单") from None
    origin = (intake.get("origin") or {}).get("point")
    destination = (intake.get("destination") or {}).get("point")
    if not origin or not destination:
        raise HTTPException(422, "工单起终点没有 WGS84 坐标，无法计算真实航线")
    try:
        target_snapshot = airspace_store.resolve(
            snapshot_id=body.snapshot_id if body else None,
            zone_buffer_m=body.zone_buffer_m if (body and body.zone_buffer_m is not None) else 0.0,
            scheduled_for=intake.get("scheduled_for"),
        )
        from services.assistant.flysafe import refresh_planning_snapshot

        refreshed = refresh_planning_snapshot(
            list(origin),
            list(destination),
            zone_buffer_m=target_snapshot.zone_buffer_m,
            scheduled_for=intake.get("scheduled_for"),
            prior=target_snapshot,
        )
        if refreshed is not None:
            target_snapshot = airspace_store.save(refreshed, set_active=True)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    old_wps = (intake.get("real_route") or {}).get("waypoints") or []
    prev_lonlats = [
        [float(pt.get("lng", pt.get("x"))), float(pt.get("lat", pt.get("y")))]
        for pt in old_wps
        if isinstance(pt, dict) and pt.get("lng", pt.get("x")) is not None
    ]
    route = _invoke_route_provider(
        real_route_for_intake,
        list(origin),
        list(destination),
        intake.get("scheduled_for"),
        snapshot=target_snapshot,
        intake_id=intake_id,
        previous_waypoints=prev_lonlats if len(prev_lonlats) >= 2 else None,
    )
    updated = apply_route_update_to_intake(
        intake,
        route,
        target_snapshot,
        store_override=intake_store,
    )
    write_audit(
        {
            "type": "intake_route_refresh",
            "intake_id": intake_id,
            "snapshot_id": target_snapshot.snapshot_id,
            "digest": target_snapshot.digest,
            "status": route.get("status"),
            "dispatch_enabled": False,
        }
    )
    return updated


@app.get("/api/telemetry/stream")
async def telemetry_stream():
    path = os.environ.get("AERIS_TELEMETRY_FILE")
    if not path:
        raise HTTPException(503, "M4 telemetry feed is not configured")
    return StreamingResponse(
        stream_telemetry(Path(path)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def write_audit(packet):
    root = Path(__file__).resolve().parents[2] / "logs/assistant"
    root.mkdir(parents=True, exist_ok=True)
    path = root / (datetime.now(UTC).strftime("%Y-%m-%d") + "_DEMO.jsonl")
    with audit_lock, path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"at": datetime.now(UTC).isoformat(), **packet}, ensure_ascii=False, allow_nan=False)
            + "\n"
        )


@app.post("/api/assistant/turn")
async def turn(request: Request):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 200_000:
            raise HTTPException(413, "Request too large")
    try:
        value = Turn.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "Assistant request fields are invalid") from None
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "Assistant is busy; retry later")
    packets = queue.Queue()
    stopped = threading.Event()
    try:
        read_dispatch_task = dispatch_runtime(request).get
    except HTTPException:
        read_dispatch_task = None

    def worker():
        try:

            def emit(packet):
                if packet["type"] == "tool_result":
                    write_audit({"turn_id": str(value.request_id), "provider": settings.provider, **packet})
                packets.put(packet)

            write_audit(
                {
                    "turn_id": str(value.request_id),
                    "provider": settings.provider,
                    "type": "turn_start",
                    "is_simulated": True,
                }
            )
            telemetry_path = os.environ.get("AERIS_TELEMETRY_FILE")
            result = engine.run(
                value,
                emit,
                read_dispatch_task=read_dispatch_task,
                actor_id=request.state.actor_id,
                cancelled=stopped.is_set,
                read_live_telemetry=lambda: read_latest(Path(telemetry_path)) if telemetry_path else None,
            )
            write_audit(
                {
                    "turn_id": str(value.request_id),
                    "provider": settings.provider,
                    "type": "turn_complete",
                    "tool_count": len(result["traces"]),
                    "dispatch_enabled": False,
                }
            )
            packets.put({"type": "result", "result": result})
        except ModelUnavailable as error:
            packets.put({"type": "error", "message": str(error)})
        except Exception:
            import traceback

            traceback.print_exc()
            packets.put(
                {"type": "error", "message": "本地工具或审计写入失败，请检查服务状态；本轮没有执行飞行操作。"}
            )
        finally:
            packets.put(None)
            slots.release()

    threading.Thread(target=worker, daemon=True).start()

    async def stream():
        yield (
            json.dumps({"type": "start", "turn_id": str(value.request_id), "provider": settings.provider})
            + "\n"
        )
        try:
            while True:
                try:
                    packet = await asyncio.to_thread(packets.get, True, 1)
                except queue.Empty:
                    yield '{"type":"heartbeat"}\n'
                    continue
                if packet is None:
                    break
                yield json.dumps(packet, ensure_ascii=False, allow_nan=False) + "\n"
        finally:
            stopped.set()

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
