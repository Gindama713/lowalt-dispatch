"""低空应急配送的 HTTP 层。

领域对象直接用 core.models。规划只经过 planner_adapter。
M3 只在规划完成后调用 agent_hook，不在这里实现。
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from core.models import SCHEMA_VERSION, RiskSnapshot, Task
from services.api.agent_hook import AgentContext, agent_status, invoke_task_agent
from services.api.assemble import assemble_route, margin_view
from services.api.config import REPO_ROOT, Settings
from services.api.envelopes import (
    Health,
    MarginView,
    PlanRequest,
    PlanResponse,
    RouteRecord,
    SceneBindRequest,
    SceneBindResult,
    SceneDocument,
    SlotStatus,
)
from services.api.errors import ApiError
from services.api.planner_adapter import PlannerIntegrationError, plan_for_task, resolve_entry
from services.api.scene_loader import bind_scene, load_scene_document
from services.api.store import SqliteStore, build_store

SERVICE_NAME = "lowalt-dispatch-api"


class UTF8JSONResponse(JSONResponse):
    """中文说明保持 UTF-8，避免健康检查和错误信息变成 \\u 转义。"""

    def render(self, content: object) -> bytes:
        return json.dumps(content, ensure_ascii=False, allow_nan=False).encode("utf-8")


def git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (subprocess.SubprocessError, OSError):
        return "unknown"
    text = out.strip()
    if not text or any(ch not in "0123456789abcdef" for ch in text):
        return "unknown"
    return text


def _check_id(value: str, name: str) -> str:
    if not value or not value.strip() or any(ch in value for ch in "/\\"):
        raise ApiError(422, f"{name} 不能为空，也不能包含斜杠")
    return value


def _postgres_slot(settings: Settings) -> SlotStatus:
    names = [
        name
        for name, value in (("RDS_DSN", settings.rds_dsn), ("DATABASE_URL", settings.database_url))
        if value
    ]
    if not names:
        note = "未配置。RDS_DSN 和 DATABASE_URL 都是空的，当前不会连接 PostgreSQL。"
    else:
        note = (
            f"{'、'.join(names)} 已填写。本版本不建立连接，任务仍写在本地 SQLite 或内存里。"
            "连接串不会出现在响应中。"
        )
    return SlotStatus(name="postgresql", configured=bool(names), connected=False, note=note)


def _redis_slot(settings: Settings) -> SlotStatus:
    names = [
        name for name, value in (("DCS_HOST", settings.dcs_host), ("REDIS_URL", settings.redis_url)) if value
    ]
    if not names:
        note = "未配置。DCS_HOST 和 REDIS_URL 都是空的，当前不会连接 Redis。"
    else:
        note = (
            f"{'、'.join(names)} 已填写。本版本不建立连接，也不把任务状态放进 Redis。地址不会出现在响应中。"
        )
    return SlotStatus(name="redis", configured=bool(names), connected=False, note=note)


def _storage_note(settings: Settings) -> str:
    if settings.storage_backend == "memory":
        return "当前是进程内 SQLite :memory:，退出即失。不是 PostgreSQL，也不是 Redis。"
    return "当前是本地 SQLite 文件，不是 PostgreSQL。文件路径不回显。"


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings.from_env()
    app = FastAPI(
        title="低空应急配送 API",
        version=SCHEMA_VERSION,
        description=(
            "M5 后端。任务、快照和航线使用 core.models。"
            "场景几何是仿真草稿。备降余量只在规划器真正返回时才有数字。"
        ),
        default_response_class=UTF8JSONResponse,
    )
    app.state.settings = cfg
    app.state.store = build_store(cfg)
    app.state.planner_entry = resolve_entry(cfg.planner_entry)

    @app.exception_handler(ApiError)
    async def _api_error(_, exc: ApiError) -> JSONResponse:
        return UTF8JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(PlannerIntegrationError)
    async def _planner_error(_, exc: PlannerIntegrationError) -> JSONResponse:
        return UTF8JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.get("/health", response_model=Health)
    def health() -> Health:
        store: SqliteStore = app.state.store
        alive = store.ping()
        return Health(
            status="ok" if alive else "degraded",
            schema_version=SCHEMA_VERSION,
            service=SERVICE_NAME,
            git_commit=git_commit(),
            storage_backend=cfg.storage_backend,
            storage_note=_storage_note(cfg),
            planner_entry=app.state.planner_entry.spec,
            postgres=_postgres_slot(cfg),
            redis=_redis_slot(cfg),
            agent=agent_status(cfg.agent_entry),
        )

    @app.post("/tasks", response_model=Task, status_code=201)
    def create_task(task: Task) -> Task:
        _check_id(task.task_id, "task_id")
        if not app.state.store.insert_task(task):
            raise ApiError(409, f"任务 {task.task_id} 已存在")
        return task

    @app.get("/tasks", response_model=list[Task])
    def list_tasks() -> list[Task]:
        return app.state.store.list_tasks()

    @app.get("/tasks/{task_id}", response_model=Task)
    def get_task(task_id: str) -> Task:
        task = app.state.store.get_task(task_id)
        if task is None:
            raise ApiError(404, f"没有任务 {task_id}")
        return task

    @app.get("/scenes/{scene_id}", response_model=SceneDocument)
    def get_scene(scene_id: str) -> SceneDocument:
        return load_scene_document(scene_id)

    @app.post("/tasks/{task_id}/snapshots", response_model=RiskSnapshot, status_code=201)
    def create_snapshot(task_id: str, snapshot: RiskSnapshot) -> RiskSnapshot:
        _require_task(app.state.store, task_id)
        _check_id(snapshot.snapshot_id, "snapshot_id")
        _aware_snapshot(snapshot)
        if not app.state.store.insert_snapshot(task_id, snapshot):
            raise ApiError(409, f"快照 {snapshot.snapshot_id} 已存在")
        return snapshot

    @app.post("/tasks/{task_id}/snapshots/from-scene", response_model=SceneBindResult, status_code=201)
    def snapshot_from_scene(task_id: str, request: SceneBindRequest | None = None) -> SceneBindResult:
        _require_task(app.state.store, task_id)
        body = request or SceneBindRequest()
        snapshot_id = _fresh_snapshot_id(app.state.store, task_id)
        result = bind_scene(task_id, body, snapshot_id=snapshot_id)
        if not app.state.store.insert_snapshot(task_id, result.snapshot):
            raise ApiError(409, f"快照 {snapshot_id} 已存在")
        return result

    @app.get("/tasks/{task_id}/snapshot", response_model=RiskSnapshot)
    def latest_snapshot(task_id: str) -> RiskSnapshot:
        _require_task(app.state.store, task_id)
        snapshot = app.state.store.latest_snapshot(task_id)
        if snapshot is None:
            raise ApiError(404, f"任务 {task_id} 还没有快照")
        return snapshot

    @app.get("/tasks/{task_id}/snapshots/{snapshot_id}", response_model=RiskSnapshot)
    def get_snapshot(task_id: str, snapshot_id: str) -> RiskSnapshot:
        _require_task(app.state.store, task_id)
        return _snapshot_for_task(app.state.store, task_id, snapshot_id)

    @app.post("/tasks/{task_id}/plan", response_model=PlanResponse)
    def plan_task(task_id: str, request: PlanRequest | None = None) -> PlanResponse:
        store: SqliteStore = app.state.store
        task = _require_task(store, task_id)
        body = request or PlanRequest()
        if body.snapshot_id is None:
            snapshot = store.latest_snapshot(task_id)
            if snapshot is None:
                raise ApiError(400, "任务还没有快照。先加载场景或提交 RiskSnapshot，再规划。")
        else:
            _check_id(body.snapshot_id, "snapshot_id")
            snapshot = _snapshot_for_task(store, task_id, body.snapshot_id)

        now = datetime.now(UTC)
        if snapshot.is_stale(now):
            raise ApiError(409, f"快照 {snapshot.snapshot_id} 已过 valid_until，不能用来规划新路线。")

        outcome = plan_for_task(app.state.planner_entry, task, snapshot, now=now)
        plan_version = store.allocate_plan_version(task_id)
        record = assemble_route(
            task,
            route_id=plan_version,
            plan_version=plan_version,
            snapshot_id=snapshot.snapshot_id,
            outcome=outcome,
            requested_algorithm=body.algorithm,
        )
        store.insert_route(record)
        agent = invoke_task_agent(
            AgentContext(
                event="plan_completed",
                task_id=task.task_id,
                snapshot_id=snapshot.snapshot_id,
                route_id=record.route_id,
                found=record.found,
                algorithm=record.algorithm,
            ),
            entry=cfg.agent_entry,
        )
        return PlanResponse(route=record, agent=agent)

    @app.get("/tasks/{task_id}/routes", response_model=list[RouteRecord])
    def list_routes(task_id: str) -> list[RouteRecord]:
        _require_task(app.state.store, task_id)
        return app.state.store.list_routes(task_id)

    @app.get("/tasks/{task_id}/routes/{route_id}", response_model=RouteRecord)
    def get_route(task_id: str, route_id: str) -> RouteRecord:
        _require_task(app.state.store, task_id)
        record = app.state.store.get_route(task_id, route_id)
        if record is None:
            raise ApiError(404, f"任务 {task_id} 没有路线 {route_id}")
        return record

    @app.get("/tasks/{task_id}/routes/{route_id}/margin", response_model=MarginView)
    def get_margin(task_id: str, route_id: str) -> MarginView:
        _require_task(app.state.store, task_id)
        record = app.state.store.get_route(task_id, route_id)
        if record is None:
            raise ApiError(404, f"任务 {task_id} 没有路线 {route_id}")
        return margin_view(record)

    return app


def _require_task(store: SqliteStore, task_id: str) -> Task:
    task = store.get_task(task_id)
    if task is None:
        raise ApiError(404, f"没有任务 {task_id}")
    return task


def _snapshot_for_task(store: SqliteStore, task_id: str, snapshot_id: str) -> RiskSnapshot:
    found = store.get_snapshot(snapshot_id)
    if found is None or found[0] != task_id:
        raise ApiError(404, f"任务 {task_id} 没有快照 {snapshot_id}")
    return found[1]


def _aware_snapshot(snapshot: RiskSnapshot) -> None:
    stamps = [snapshot.captured_at, snapshot.valid_until]
    for event in snapshot.events:
        stamps.extend([event.effective_from, event.effective_until])
    if any(stamp is not None and stamp.tzinfo is None for stamp in stamps):
        raise ApiError(422, "快照时间必须带时区（UTC）。")


def _fresh_snapshot_id(store: SqliteStore, task_id: str) -> str:
    for offset in range(1, 1000):
        candidate = f"{task_id}-snap-{offset}"
        if store.get_snapshot(candidate) is None:
            return candidate
    raise ApiError(500, "快照编号用尽")


# uvicorn services.api.main:app
# 测试请调用 create_app(Settings(...))，不要复用这个懒加载实例。
_APP: FastAPI | None = None


def _lazy_app() -> FastAPI:
    global _APP
    if _APP is None:
        _APP = create_app()
    return _APP


class _AppProxy:
    def __getattr__(self, name: str) -> object:
        return getattr(_lazy_app(), name)

    async def __call__(self, scope, receive, send) -> None:
        await _lazy_app()(scope, receive, send)


app = _AppProxy()
