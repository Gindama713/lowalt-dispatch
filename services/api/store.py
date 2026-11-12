"""任务、快照、路线的存储。

memory：单个进程内的 SQLite `:memory:`，退出即失。
sqlite：一个本地文件。
两者都不是 PostgreSQL。审计数据不要只放 Redis；本进程目前也不连 Redis。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from core.models import RiskSnapshot, Task
from services.api.config import Settings
from services.api.envelopes import RouteRecord

T = TypeVar("T", bound=BaseModel)


def _dump(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False)


def _load(model_type: type[T], body: str) -> T:
    return model_type.model_validate_json(body)


class SqliteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._pending_route_seq: dict[str, int] = {}
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    seq INTEGER NOT NULL,
                    body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS routes (
                    task_id TEXT NOT NULL,
                    route_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    body TEXT NOT NULL,
                    PRIMARY KEY (task_id, route_id)
                );
                """
            )
            self._conn.commit()

    def ping(self) -> bool:
        with self._lock:
            try:
                self._conn.execute("SELECT 1").fetchone()
            except sqlite3.Error:
                return False
            return True

    def insert_task(self, task: Task) -> bool:
        with self._lock:
            exists = self._conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task.task_id,)).fetchone()
            if exists is not None:
                return False
            seq = self._conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM tasks").fetchone()["n"]
            self._conn.execute(
                "INSERT INTO tasks (task_id, seq, body) VALUES (?, ?, ?)",
                (task.task_id, seq, _dump(task)),
            )
            self._conn.commit()
            return True

    def get_task(self, task_id: str) -> Task | None:
        with self._lock:
            row = self._conn.execute("SELECT body FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return _load(Task, row["body"])

    def list_tasks(self) -> list[Task]:
        with self._lock:
            rows = self._conn.execute("SELECT body FROM tasks ORDER BY seq").fetchall()
        return [_load(Task, row["body"]) for row in rows]

    def insert_snapshot(self, task_id: str, snapshot: RiskSnapshot) -> bool:
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM snapshots WHERE snapshot_id = ?",
                (snapshot.snapshot_id,),
            ).fetchone()
            if exists is not None:
                return False
            seq = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM snapshots WHERE task_id = ?",
                (task_id,),
            ).fetchone()["n"]
            self._conn.execute(
                "INSERT INTO snapshots (snapshot_id, task_id, seq, body) VALUES (?, ?, ?, ?)",
                (snapshot.snapshot_id, task_id, seq, _dump(snapshot)),
            )
            self._conn.commit()
            return True

    def get_snapshot(self, snapshot_id: str) -> tuple[str, RiskSnapshot] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT task_id, body FROM snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            return None
        return row["task_id"], _load(RiskSnapshot, row["body"])

    def latest_snapshot(self, task_id: str) -> RiskSnapshot | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT body FROM snapshots WHERE task_id = ? ORDER BY seq DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return _load(RiskSnapshot, row["body"])

    def allocate_plan_version(self, task_id: str) -> str:
        """占一个版本号。规划可能较慢，先占号避免两次请求写成同一个 v1。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS n FROM routes WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            current = max(int(row["n"]), self._pending_route_seq.get(task_id, 0))
            nxt = current + 1
            self._pending_route_seq[task_id] = nxt
            return f"v{nxt}"

    def insert_route(self, record: RouteRecord) -> None:
        with self._lock:
            if not record.plan_version.startswith("v") or not record.plan_version[1:].isdigit():
                raise RuntimeError(f"非法 plan_version {record.plan_version}")
            seq = int(record.plan_version[1:])
            self._conn.execute(
                "INSERT INTO routes (task_id, route_id, seq, body) VALUES (?, ?, ?, ?)",
                (record.task_id, record.route_id, seq, _dump(record)),
            )
            self._conn.commit()

    def get_route(self, task_id: str, route_id: str) -> RouteRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT body FROM routes WHERE task_id = ? AND route_id = ?",
                (task_id, route_id),
            ).fetchone()
        if row is None:
            return None
        return _load(RouteRecord, row["body"])

    def list_routes(self, task_id: str) -> list[RouteRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT body FROM routes WHERE task_id = ? ORDER BY seq",
                (task_id,),
            ).fetchall()
        return [_load(RouteRecord, row["body"]) for row in rows]


def build_store(settings: Settings) -> SqliteStore:
    if settings.storage_backend == "memory":
        return SqliteStore(":memory:")
    path = settings.sqlite_file()
    if path is None:
        raise RuntimeError("sqlite 后端缺少文件路径")
    return SqliteStore(path)
