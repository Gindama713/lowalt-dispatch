"""One local MOCK vehicle: reviewed scenario → real M3/M2/validator → M4.

SQLite/files are authoritative. The browser cannot supply an arbitrary command,
mark a flight complete, or silently convert real coordinates into demo ENU.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from agent.contracts import AgentStatus
from agent.execution import ExecutionStatus
from agent.messaging import MqttCommandChannel
from agent.planning import M2Tools
from agent.repository import RunRepository
from agent.service import TaskService
from agent.storage import FileLease, atomic_json
from core.models import RiskSnapshot, Task
from edge.service import EdgeService
from edge.store import CommandStore
from planner.assemble import build_snapshot, build_task
from planner.scene import load_scene, load_suite
from validator.__main__ import SYNTHETIC_INITIAL_WH, SYNTHETIC_PROFILE, SYNTHETIC_RESERVE_WH

WARNING = (
    "本地合成联调：真实规划与独立校验代码，合成机型参数及执行轨迹；不会连接或控制PX4，不代表真实安全性能。"
)


def digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


class LocalDispatch:
    def __init__(self, root: Path, *, transport: str = "direct", mqtt_port: int = 1883, clock=None):
        if transport not in {"direct", "mqtt"}:
            raise ValueError("Local dispatch transport must be direct or mqtt")
        self.root, self.transport = root.resolve(), transport
        self.clock = clock or (lambda: datetime.now(UTC))
        self.lock = RLock()
        self.lease = FileLease(self.root / "process.lock")
        self.channel = self.edge = self.store = self.repository = None
        try:
            self.scene = load_scene()
            self.scenarios = {s["id"]: s for s in load_suite()["scenarios"]}
            self.profile = replace(SYNTHETIC_PROFILE, vehicle_key="placeholder")
            self.repository = RunRepository("sqlite:///" + (self.root / "tasks.sqlite3").as_posix())
            self.repository.initialize()
            if transport == "direct":
                self.store = CommandStore(self.root / "commands.sqlite3")
                self.edge = EdgeService(
                    self.store,
                    audit_path=self.root / "edge_MOCK.jsonl",
                    telemetry_path=self.root / "telemetry_MOCK.jsonl",
                    clock=self.clock,
                )
                self.edge.recover()
            else:
                import paho.mqtt.client as mqtt

                self.channel = MqttCommandChannel(
                    mqtt.Client(mqtt.CallbackAPIVersion.VERSION2),
                    "local-mock-1",
                    run_mode="mock",
                    clock=self.clock,
                )
                for path in self.root.glob("proposals/*.json"):
                    record = self.repository.get(path.stem, "mock")
                    if record and record.result and record.result.command:
                        self.channel.watch_command(record.result.command)
                self.channel.start("127.0.0.1", mqtt_port)
        except Exception:
            self.close()
            raise

    def _path(self, task_id: str, folder="proposals") -> Path:
        if str(UUID(task_id)) != task_id:
            raise ValueError("Invalid local task ID")
        return self.root / folder / (task_id + ".json")

    def _proposal(self, task_id: str) -> dict:
        path = self._path(task_id)
        if not path.is_file():
            raise KeyError("Unknown local task")
        return json.loads(path.read_text(encoding="utf-8"))

    def health(self):
        return {
            "status": "ok",
            "run_mode": "mock",
            "is_simulated": True,
            "transport": self.transport,
            "vehicle_id": "local-mock-1",
            "controls_px4": False,
            "active_task_id": self.store.pending()[0].task_id
            if self.store and self.store.pending()
            else None,
            "warning": WARNING,
            "scenarios": [
                {"id": key, "name": value.get("name", key)} for key, value in self.scenarios.items()
            ],
        }

    def propose(self, scenario_id: str):
        with self.lock:
            if scenario_id not in self.scenarios:
                raise ValueError("Unknown scenario")
            if sum(1 for _ in self.root.glob("proposals/*.json")) >= 1000:
                raise ValueError("Local proposal capacity reached; archive the state directory")
            scenario, now = self.scenarios[scenario_id], self.clock()
            task = build_task(
                scenario,
                now,
                vehicle_type=self.profile.vehicle_key,
                initial_energy_wh=float(scenario.get("initial_energy_wh", SYNTHETIC_INITIAL_WH)),
                reserve_energy_wh=SYNTHETIC_RESERVE_WH,
            )
            task = task.model_copy(update={"task_id": str(uuid4())})
            proposal = {
                "task_id": task.task_id,
                "scenario_id": scenario_id,
                "run_mode": "mock",
                "warning": WARNING,
                "task": task.model_dump(mode="json"),
                "snapshot": build_snapshot(scenario, self.scene, now).model_dump(mode="json"),
                "profile": {"source": "validator.SYNTHETIC_PROFILE", "synthetic": True},
                "expires_at": (now + timedelta(minutes=5)).isoformat(),
            }
            atomic_json(self._path(task.task_id), proposal)
            return {**proposal, "review_digest": digest(proposal)}

    def confirm(self, task_id: str, review_digest: str):
        with self.lock:
            proposal = self._proposal(task_id)
            if review_digest != digest(proposal):
                raise ValueError("Review digest changed; review the original proposal again")
            existing = self.repository.get(task_id, "mock")
            # Repeated confirmation retrieves the original reservation, even
            # after expiry. It never creates a new task, command or route.
            if existing is not None:
                return self.get(task_id)
            if datetime.fromisoformat(proposal["expires_at"]) <= self.clock():
                raise ValueError("Proposal expired; create and review a new proposal")
            task = Task.model_validate(proposal["task"])
            snapshot = RiskSnapshot.model_validate(proposal["snapshot"])
            tools = M2Tools(
                self.scene,
                lambda _task: snapshot,
                self.edge.submit if self.edge else self.channel.submit_command,
                profile=self.profile,
                is_mock=True,
                clock=self.clock,
            )
            service = TaskService(tools, self.repository, self.root / "runs", clock=self.clock)
            service.run(task)
            return self.get(task_id)

    def tick(self):
        with self.lock:
            if self.edge:
                for observation in self.edge.tick():
                    atomic_json(
                        self._path(observation.task_id, "observations"), observation.model_dump(mode="json")
                    )
            else:
                for kind, _received_at, body in self.channel.drain_events():
                    if kind == "heartbeat":
                        continue
                    record = self.repository.get(body.task_id, "mock")
                    if record is None or record.result is None or record.result.command is None:
                        continue
                    command = record.result.command
                    identity = body.accepted_command_id if kind == "telemetry" else body.command_id
                    if identity != command.command_id:
                        continue
                    if kind == "ack" and record.result.ack is None:
                        tools = M2Tools(
                            self.scene,
                            lambda _task: None,
                            self.channel.submit_command,
                            profile=self.profile,
                            is_mock=True,
                            clock=self.clock,
                        )
                        TaskService(tools, self.repository, self.root / "runs", clock=self.clock).recover(
                            body.task_id, body
                        )
                    elif kind in {"status", "telemetry"}:
                        path = self._path(body.task_id, "statuses" if kind == "status" else "observations")
                        if path.exists():
                            previous = json.loads(path.read_text(encoding="utf-8"))
                            if kind == "status" and (
                                datetime.fromisoformat(previous["updated_at"].replace("Z", "+00:00"))
                                > body.updated_at
                                or (
                                    previous["state"] in {"completed", "failed", "rejected"}
                                    and previous["state"] != body.state
                                )
                            ):
                                continue
                            if (
                                kind == "telemetry"
                                and datetime.fromisoformat(previous["state"]["ts"].replace("Z", "+00:00"))
                                > body.state.ts
                            ):
                                continue
                        atomic_json(path, body.model_dump(mode="json"))

    def get(self, task_id: str):
        with self.lock:
            proposal = self._proposal(task_id)
            record = self.repository.get(task_id, "mock")
            result = record.result if record else None
            execution = None
            if result and result.command and self.store:
                edge_record = self.store.get(result.command.command_id)
                if edge_record:
                    execution = ExecutionStatus(
                        command_id=edge_record.command_id,
                        task_id=task_id,
                        plan_version=edge_record.plan_version,
                        state=edge_record.state,
                        updated_at=edge_record.updated_at,
                        execution_count=edge_record.execution_count,
                        reason=edge_record.last_reason,
                    ).model_dump(mode="json")
            elif self.channel:
                status_path = self._path(task_id, "statuses")
                if status_path.exists():
                    execution = json.loads(status_path.read_text(encoding="utf-8"))
            observation_path = self._path(task_id, "observations")
            observation = (
                json.loads(observation_path.read_text(encoding="utf-8"))
                if observation_path.exists()
                else None
            )
            events = []
            if record and Path(record.audit_path).exists():
                # Bounded view, raw authoritative audit stays on disk.
                from collections import deque

                with Path(record.audit_path).open(encoding="utf-8") as stream:
                    events = [json.loads(line) for line in deque(stream, maxlen=30)]
            reason = result.reason if result else "等待确认或审计恢复，不会自动重放"
            if result and result.status == AgentStatus.BLOCKED:
                rejected = next(
                    (
                        event
                        for event in reversed(events)
                        if event.get("event") == "candidate_rejected"
                        and event.get("task_id") == task_id
                        and event.get("run_id") == result.run_id
                    ),
                    None,
                )
                if rejected:
                    details = [check["detail"] for check in rejected["feedback"]]
                    if details:
                        reason = "\n".join(
                            [f"候选航线 {rejected['plan_version']} 校验记录", *details, reason]
                        )
            return {
                "task_id": task_id,
                "scenario_id": proposal["scenario_id"],
                "run_mode": "mock",
                "is_simulated": True,
                "warning": WARNING,
                "transport": self.transport,
                "planning_status": result.status
                if result
                else ("reconcile_required" if record else "awaiting_confirmation"),
                "reason": reason,
                "result": result.model_dump(mode="json") if result else None,
                "execution": execution,
                "observation": observation,
                "events": events,
            }

    def abandon(self, task_id: str):
        with self.lock:
            if self.edge is None:
                raise ValueError("MQTT模式请在执行端人工核对；此入口只结束进程内合成测试")
            self._proposal(task_id)
            record = self.repository.get(task_id, "mock")
            if record and record.result and record.result.command:
                self.edge.abandon_mock(record.result.command.command_id, "操作者从本地联调面板确认结束")
            return self.get(task_id)

    def close(self):
        for resource in (self.channel, self.edge, self.store, self.repository, self.lease):
            if resource is not None:
                resource.close()


def from_env():
    return LocalDispatch(
        Path(os.getenv("AERIS_DISPATCH_DIR", "logs/local-dispatch")),
        transport=os.getenv("AERIS_DISPATCH_TRANSPORT", "direct"),
        mqtt_port=int(os.getenv("AERIS_MQTT_PORT", "1883")),
    )
