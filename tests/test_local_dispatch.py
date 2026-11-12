from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from edge.service import EdgeService
from edge.store import CommandStore
from services.api.runtime import LocalDispatch
from tests.test_edge_guard import _command


def test_formal_chain_acceptance_completion_and_idempotency(tmp_path):
    now = [datetime.now(UTC)]
    dispatch = LocalDispatch(tmp_path, clock=lambda: now[0])
    try:
        proposal = dispatch.propose("S1-01")
        result = dispatch.confirm(proposal["task_id"], proposal["review_digest"])
        assert result["planning_status"] == "acknowledged"
        assert result["execution"]["state"] == "executing"  # ACK != completion
        assert result["execution"]["execution_count"] == 1
        again = dispatch.confirm(proposal["task_id"], proposal["review_digest"])
        assert again["result"] == result["result"]
        now[0] += timedelta(hours=1)
        dispatch.tick()
        completed = dispatch.get(proposal["task_id"])
        assert completed["execution"]["state"] == "completed"
        assert completed["planning_status"] == "acknowledged"
        assert completed["observation"]["state"]["provenance"]["source"] == "sim:edge.fake_executor"
        assert (
            completed["observation"]["state"]["position"]["alt_ref"]
            == result["result"]["route"]["waypoints"][0]["alt_ref"]
        )
    finally:
        dispatch.close()
    reopened = LocalDispatch(tmp_path, clock=lambda: now[0])
    try:
        assert (
            reopened.confirm(proposal["task_id"], proposal["review_digest"])["execution"]["execution_count"]
            == 1
        )
        assert reopened.store.count() == 1
    finally:
        reopened.close()


def test_rejected_route_never_reaches_executor_and_report_tamper_is_rejected(tmp_path):
    from edge.guard import check_command

    dispatch = LocalDispatch(tmp_path)
    try:
        blocked = dispatch.propose("S2-01")
        result = dispatch.confirm(blocked["task_id"], blocked["review_digest"])
        assert result["planning_status"] == "blocked"
        assert "侵入限制区 R01" in result["reason"]
        assert "自 +40s 生效" in result["reason"]
        assert result["execution"] is None
        assert dispatch.store.count() == 0
        proposal = dispatch.propose("S1-01")
        result = dispatch.confirm(proposal["task_id"], proposal["review_digest"])
        command = dispatch.store.all()[0].command.model_copy(deep=True)
        command.payload["route"]["waypoints"][0]["x_m"] += 1
        assert not check_command(command, dispatch.clock()).accepted
        command = dispatch.store.all()[0].command.model_copy(deep=True)
        command.payload["validation"]["task_id"] = "other-task"
        assert not check_command(command, dispatch.clock()).accepted
    finally:
        dispatch.close()


def test_vehicle_lock_survives_restart_and_older_versions_are_denied(tmp_path):
    now = datetime.now(UTC)

    def make_service(store, index):
        return EdgeService(
            store,
            audit_path=tmp_path / f"audit{index}.jsonl",
            telemetry_path=tmp_path / f"state{index}.jsonl",
            clock=lambda: now,
        )

    base = _command().model_copy(update={"issued_at": now, "expires_at": now + timedelta(seconds=30)})
    with CommandStore(tmp_path / "edge.db") as store:
        with make_service(store, 1) as service:
            assert service.submit(base).accepted
            other = base.model_copy(update={"command_id": "other", "task_id": "other-task"})
            assert not service.submit(other).accepted
    with CommandStore(tmp_path / "edge.db") as store:
        with make_service(store, 2) as service:
            service.recover()
            assert not service.submit(other).accepted
            assert store.get(base.command_id).state == "recovering"
            assert store.get(base.command_id).execution_count == 1
            store.finish(base.command_id, "completed", now)
            assert not service.submit(base.model_copy(update={"command_id": "old-version"})).accepted
            assert service.submit(
                base.model_copy(update={"command_id": "new-version", "plan_version": "v2"})
            ).accepted


def test_single_vehicle_claim_is_atomic_across_database_connections(tmp_path):
    now = datetime.now(UTC)
    with CommandStore(tmp_path / "edge.db") as one, CommandStore(tmp_path / "edge.db") as two:
        base = _command()

        def claim(index):
            command = base.model_copy(update={"command_id": f"cmd{index}", "task_id": f"task{index}"})
            return (one if index % 2 else two).claim(command, now, "mock", enforce_single_vehicle=True)[0]

        with ThreadPoolExecutor(max_workers=8) as pool:
            verdicts = list(pool.map(claim, range(8)))
        assert sum(v.accepted for v in verdicts) == 1
        assert sum(record.execution_count for record in one.all()) == 0
        assert len(one.pending()) == 1


def test_restart_marks_unfinished_task_for_reconciliation_without_replay(tmp_path):
    dispatch = LocalDispatch(tmp_path)
    proposal = dispatch.propose("S1-01")
    dispatch.confirm(proposal["task_id"], proposal["review_digest"])
    dispatch.close()
    dispatch = LocalDispatch(tmp_path)
    try:
        result = dispatch.confirm(proposal["task_id"], proposal["review_digest"])
        assert result["execution"]["state"] == "recovering"
        assert result["execution"]["execution_count"] == 1
        assert dispatch.edge.tick() == []
        dispatch.abandon(proposal["task_id"])
        assert dispatch.get(proposal["task_id"])["execution"]["state"] == "failed"
        assert dispatch.store.pending() == []
    finally:
        dispatch.close()


def test_local_api_requires_review_and_preserves_real_telemetry_boundary(tmp_path, monkeypatch):
    monkeypatch.setenv("AERIS_DISPATCH_DIR", str(tmp_path))
    monkeypatch.setenv("AERIS_DISPATCH_TRANSPORT", "direct")
    from services.assistant.app import app

    with TestClient(app) as client:
        assert client.get("/api/dispatch/health").json()["controls_px4"] is False
        assert client.get("/api/assistant/health").json()["dispatch_enabled"] is False
        assert (
            client.post(
                "/api/dispatch/proposals",
                json={"scenario_id": "S1-01"},
                headers={"origin": "https://evil.invalid"},
            ).status_code
            == 403
        )
        proposal = client.post("/api/dispatch/proposals", json={"scenario_id": "S1-01"}).json()
        url = f"/api/dispatch/tasks/{proposal['task_id']}/confirm"
        assert (
            client.post(
                url, json={"confirmed": False, "review_digest": proposal["review_digest"]}
            ).status_code
            == 422
        )
        assert client.post(url, json={"confirmed": True, "review_digest": "0" * 64}).status_code == 409
        assert (
            client.get(f"/api/dispatch/tasks/{proposal['task_id']}").json()["planning_status"]
            == "awaiting_confirmation"
        )
        result = client.post(url, json={"confirmed": True, "review_digest": proposal["review_digest"]})
        assert result.status_code == 200
        assert result.json()["execution"]["execution_count"] == 1
        assert (
            client.post(url, json={"confirmed": True, "review_digest": proposal["review_digest"]}).json()[
                "result"
            ]
            == result.json()["result"]
        )
        app.state.dispatch_error = True
        assert client.get("/api/dispatch/health").status_code == 503


def test_expired_proposal_and_real_executor_default_fail_closed(tmp_path):
    now = [datetime.now(UTC)]
    dispatch = LocalDispatch(tmp_path, clock=lambda: now[0])
    try:
        proposal = dispatch.propose("S1-01")
        now[0] += timedelta(minutes=6)
        with pytest.raises(ValueError, match="expired"):
            dispatch.confirm(proposal["task_id"], proposal["review_digest"])
        assert dispatch.store.count() == 0
        with pytest.raises(ValueError, match="integration"):
            EdgeService(
                dispatch.store,
                audit_path=tmp_path / "a",
                telemetry_path=tmp_path / "t",
                run_mode="integration",
            )
    finally:
        dispatch.close()


def test_busy_rejection_is_durable_and_cannot_execute_on_redelivery(tmp_path):
    now = datetime.now(UTC)
    with CommandStore(tmp_path / "edge.db") as store:
        with EdgeService(
            store, audit_path=tmp_path / "a.jsonl", telemetry_path=tmp_path / "t.jsonl", clock=lambda: now
        ) as service:
            first = _command(issued_at=now, expires_at=now + timedelta(seconds=30))
            second = first.model_copy(update={"command_id": "second", "task_id": "second-task"})
            assert service.submit(first).accepted
            rejected = service.submit(second)
            assert not rejected.accepted
            service.abandon_mock(first.command_id, "测试完成")
            assert service.submit(second) == rejected
            assert store.get(second.command_id).execution_count == 0
            assert store.pending() == []


def test_uncertain_start_failure_keeps_vehicle_locked(tmp_path):
    class UncertainExecutor:
        name = "driver"

        def start(self, command, now):
            raise RuntimeError("connection lost after write")

    now = datetime.now(UTC)
    with CommandStore(tmp_path / "edge.db") as store:
        with EdgeService(
            store,
            audit_path=tmp_path / "a.jsonl",
            telemetry_path=tmp_path / "t.jsonl",
            clock=lambda: now,
            executor_factory=lambda points: UncertainExecutor(),
        ) as service:
            first = _command(issued_at=now, expires_at=now + timedelta(seconds=30))
            assert not service.submit(first).accepted
            assert store.get(first.command_id).state == "recovering"
            second = first.model_copy(update={"command_id": "second", "task_id": "second-task"})
            assert not service.submit(second).accepted
