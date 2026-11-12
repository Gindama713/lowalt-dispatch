"""M5 HTTP 接口。

这些测试检查三件事：任务和场景能按 core.models 进出；
规划结果来自现有规划入口，而不是 eval 里的 mock；
规划器没给的能量和备降余量必须标成不可用，不能出现一个像样的假数字。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.models import SCHEMA_VERSION, LandingSite
from planner.astar import plan_scenario
from planner.scene import load_scene
from services.api.config import Settings
from services.api.main import create_app
from services.api.planner_adapter import PlannerIntegrationError
from tests import fakes

REPO_ROOT = Path(__file__).resolve().parents[1]

PROVENANCE = {
    "source": "test:api",
    "version": "0",
    "captured_at": "2026-11-09T00:00:00+00:00",
    "is_simulated": True,
    "uncertainty_note": "接口测试构造的数据，不是运营数据",
}


def _settings(**kwargs) -> Settings:
    data = {"storage_backend": "memory", "planner_entry": "", "agent_entry": ""}
    data.update(kwargs)
    return Settings(**data)


@pytest.fixture
def client():
    app = create_app(_settings())
    with TestClient(app) as test_client:
        yield test_client


def _position(x: float, y: float, alt: float = 0.0) -> dict:
    return {"frame": "enu_m", "x_m": x, "y_m": y, "alt_m": alt, "alt_ref": "rel_takeoff"}


def _task(task_id: str = "T-20261109-001", origin: dict | None = None, destination: dict | None = None) -> dict:
    return {
        "task_id": task_id,
        "origin": origin or _position(150, 150, 0),
        "destination": destination or _position(2650, 2750, 30),
        "payload_kg": 1.0,
        "vehicle_type": "placeholder",
        "initial_energy_wh": 100.0,
        "reserve_energy_wh": 20.0,
        "time_limit_s": 600,
        "provenance": dict(PROVENANCE),
    }


def _create(client: TestClient, body: dict | None = None) -> dict:
    response = client.post("/tasks", json=body or _task())
    assert response.status_code == 201, response.text
    return response.json()


def _bind(client: TestClient, task_id: str, payload: dict | None = None) -> dict:
    response = client.post(f"/tasks/{task_id}/snapshots/from-scene", json=payload or {"scene_id": "v0"})
    assert response.status_code == 201, response.text
    return response.json()


def _plan(client: TestClient, task_id: str, payload: dict | None = None):
    return client.post(f"/tasks/{task_id}/plan", json={} if payload is None else payload)


# --------------------------------------------------------------------------- #
# 健康检查与存储
# --------------------------------------------------------------------------- #
def test_health_reports_contract_version_and_unconnected_cloud_slots(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["service"] == "lowalt-dispatch-api"
    assert re.fullmatch(r"[0-9a-f]{7,40}|unknown", body["git_commit"])
    assert body["storage_backend"] == "memory"
    assert "PostgreSQL" in body["storage_note"]
    assert body["planner_entry"] == "planner.astar:plan_scenario"
    assert body["postgres"] == {
        "name": "postgresql",
        "configured": False,
        "connected": False,
        "note": body["postgres"]["note"],
    }
    assert body["postgres"]["connected"] is False
    assert body["redis"]["configured"] is False
    assert body["redis"]["connected"] is False
    assert body["agent"]["status"] == "not_implemented"
    assert body["agent"]["entry_configured"] is False
    assert "M3" in body["agent"]["detail"]


def test_health_hides_database_secrets() -> None:
    app = create_app(
        _settings(
            rds_dsn="postgresql://user:supersecret@db.internal/lowalt",
            database_url="postgresql://user:dbpassword@other/db",
            dcs_host="redis.internal",
            redis_url="redis://:redispassword@redis.internal:6379/0",
            agent_entry="tests.fakes:agent_tries_to_rewrite",
        )
    )
    with TestClient(app) as test_client:
        response = test_client.get("/health")
    assert response.status_code == 200
    text = response.text
    assert "supersecret" not in text
    assert "dbpassword" not in text
    assert "redispassword" not in text
    assert "redis.internal" not in text
    assert "db.internal" not in text
    body = response.json()
    assert body["postgres"]["configured"] is True
    assert body["postgres"]["connected"] is False
    assert body["redis"]["configured"] is True
    assert body["redis"]["connected"] is False
    assert body["agent"]["entry_configured"] is True
    assert "tests.fakes" not in text


def test_sqlite_file_survives_a_new_process(tmp_path: Path) -> None:
    settings = _settings(storage_backend="sqlite", sqlite_path=str(tmp_path / "api.sqlite"))
    with TestClient(create_app(settings)) as first:
        _create(first)
    with TestClient(create_app(settings)) as second:
        response = second.get("/tasks/T-20261109-001")
    assert response.status_code == 200
    assert response.json()["task_id"] == "T-20261109-001"


def test_memory_stores_do_not_share_tasks() -> None:
    with TestClient(create_app(_settings())) as first, TestClient(create_app(_settings())) as second:
        _create(first)
        assert second.get("/tasks/T-20261109-001").status_code == 404


def test_bad_planner_entry_fails_at_startup() -> None:
    with pytest.raises(PlannerIntegrationError):
        create_app(_settings(planner_entry="no.such.module:func"))


# --------------------------------------------------------------------------- #
# 任务
# --------------------------------------------------------------------------- #
def test_create_and_get_task_keeps_simulated_flag(client: TestClient) -> None:
    created = _create(client)
    assert created["provenance"]["is_simulated"] is True
    listed = client.get("/tasks")
    assert listed.status_code == 200
    assert [item["task_id"] for item in listed.json()] == ["T-20261109-001"]
    fetched = client.get("/tasks/T-20261109-001")
    assert fetched.status_code == 200
    assert fetched.json() == created


def test_create_task_rejects_bad_contract(client: TestClient) -> None:
    mixed = _task()
    mixed["origin"]["lat_deg"] = 30.0
    assert client.post("/tasks", json=mixed).status_code == 422

    extra = _task()
    extra["made_up_field"] = 1
    assert client.post("/tasks", json=extra).status_code == 422

    blank = _task(task_id=" ")
    assert client.post("/tasks", json=blank).status_code == 422

    assert client.get("/tasks/missing").status_code == 404


def test_duplicate_task_conflicts(client: TestClient) -> None:
    _create(client)
    again = client.post("/tasks", json=_task())
    assert again.status_code == 409


# --------------------------------------------------------------------------- #
# 场景
# --------------------------------------------------------------------------- #
def test_scene_v0_is_marked_draft_simulation(client: TestClient) -> None:
    response = client.get("/scenes/v0")
    assert response.status_code == 200
    body = response.json()
    assert body["scene_id"] == "v0"
    assert body["is_simulated"] is True
    assert body["geometry_status"] == "draft"
    assert "不是经纬度" in body["crs_note"]
    assert body["counts"] == {"obstacles": 20, "restriction_zones": 4, "landing_sites": 4}
    assert "margin_wh" not in response.text
    assert "energy_budget_wh" not in response.text

    for feature in body["obstacles"] + body["restriction_zones"]:
        assert feature["properties"]["is_simulated"] is True
        assert feature["properties"]["status"] == "draft"

    sites = [LandingSite.model_validate(item) for item in body["landing_sites"]]
    assert [site.site_id for site in sites] == ["L1", "L2", "L3", "L4"]
    assert all(site.provenance.is_simulated for site in sites)
    assert all(site.position.frame.value == "enu_m" for site in sites)
    assert {site.position.alt_ref.value for site in sites} == {"agl"}

    assert client.get("/scenes/real-city").status_code == 404


def test_bind_scene_names_active_zones_and_occupied_sites(client: TestClient) -> None:
    _create(client)
    unknown = client.post(
        "/tasks/T-20261109-001/snapshots/from-scene",
        json={"scene_id": "v0", "active_zone_ids": ["R99"]},
    )
    assert unknown.status_code == 422

    bound = _bind(
        client,
        "T-20261109-001",
        {"scene_id": "v0", "active_zone_ids": ["R04"], "occupied_site_ids": ["L2"]},
    )
    assert bound["is_simulated"] is True
    snapshot = bound["snapshot"]
    assert snapshot["events"][0]["kind"] == "restriction_zone"
    assert snapshot["events"][0]["geometry"]["zone_id"] == "R04"
    occupied = {site["site_id"]: site["occupied"] for site in snapshot["landing_sites"]}
    assert occupied["L2"] is True
    assert occupied["L1"] is False
    assert "障碍物不在 RiskSnapshot" in snapshot["note"]

    latest = client.get("/tasks/T-20261109-001/snapshot")
    assert latest.status_code == 200
    assert latest.json()["snapshot_id"] == snapshot["snapshot_id"]


# --------------------------------------------------------------------------- #
# 规划：真实 A*，缺的数据保持不可用
# --------------------------------------------------------------------------- #
def test_plan_matches_astar_baseline_and_does_not_invent_energy_or_margin(client: TestClient) -> None:
    _create(client)
    _bind(client, "T-20261109-001")
    response = _plan(client, "T-20261109-001")
    assert response.status_code == 200, response.text
    body = response.json()
    route = body["route"]

    scene = load_scene()
    scenario = {
        "id": "T-20261109-001",
        "origin": {"x_m": 150.0, "y_m": 150.0},
        "destination": {"x_m": 2650.0, "y_m": 2750.0},
        "events": [],
    }
    expected, _grid = plan_scenario(scenario, scene)
    assert expected.found

    assert route["found"] is True
    assert route["algorithm"] == "astar_static"
    assert route["planner_entry"] == "planner.astar:plan_scenario"
    assert route["length_m"] == pytest.approx(expected.length_m)
    assert len(route["waypoints"]) == len(expected.waypoints)
    assert route["waypoints"][0]["x_m"] == 150
    assert route["waypoints"][0]["alt_m"] == 0
    assert route["waypoints"][-1]["x_m"] == 2650
    assert route["waypoints"][-1]["alt_m"] == 30
    assert route["waypoints"][1]["alt_m"] == 0
    assert "不是规划器" in route["altitude_note"]
    assert route["route"] is None
    assert route["route_plan_status"] == "unavailable"
    assert "energy_budget_wh" in route["route_plan_detail"]
    assert "initial_energy_wh" in route["route_plan_detail"]
    assert route["margin_status"] == "unavailable"
    assert "未实现" in route["margin_detail"]
    assert route["margin_profile"] is None
    assert "margin_wh" not in response.text
    assert route["is_simulated"] is True
    assert "仿真" in route["simulation_note"]
    assert any("不算能量" in item and "备降" in item for item in route["limitations"])
    assert "端到端" in route["timing_note"]
    assert body["agent"]["status"] == "not_implemented"
    assert body["agent"]["applied"] is False

    fetched = client.get("/tasks/T-20261109-001/routes/v1")
    assert fetched.status_code == 200
    assert fetched.json()["length_m"] == pytest.approx(expected.length_m)

    margin = client.get("/tasks/T-20261109-001/routes/v1/margin")
    assert margin.status_code == 200
    margin_body = margin.json()
    assert margin_body["status"] == "unavailable"
    assert "未实现" in margin_body["detail"]
    assert margin_body["profile"] is None
    assert margin_body["min_margin_wh"] is None
    assert margin_body["negative_sample_count"] is None
    assert margin_body["is_feasible"] is None


def test_requested_algorithm_name_does_not_switch_planner(client: TestClient) -> None:
    _create(client)
    _bind(client, "T-20261109-001")
    response = _plan(client, "T-20261109-001", {"algorithm": "astar_diversion"})
    assert response.status_code == 200, response.text
    route = response.json()["route"]
    assert route["algorithm"] == "astar_static"
    assert any("astar_diversion" in item for item in route["limitations"])
    assert route["margin_profile"] is None


def test_active_restriction_zone_changes_feasibility(client: TestClient) -> None:
    body = _task(
        task_id="T-S4-04",
        origin=_position(500, 500, 0),
        destination=_position(2500, 2500, 30),
    )
    _create(client, body)
    _bind(client, "T-S4-04", {"scene_id": "v0", "active_zone_ids": []})
    open_plan = _plan(client, "T-S4-04")
    assert open_plan.status_code == 200, open_plan.text
    assert open_plan.json()["route"]["found"] is True

    closed = client.post(
        "/tasks/T-S4-04/snapshots",
        json={
            "snapshot_id": "snap-r04",
            "captured_at": "2026-11-09T00:00:00+00:00",
            "landing_sites": [],
            "events": [
                {
                    "event_id": "E-R04",
                    "kind": "restriction_zone",
                    "geometry": {"type": "Polygon", "coordinates": [], "zone_id": "R04"},
                    "effective_from": "2020-01-01T00:00:00+00:00",
                    "provenance": PROVENANCE,
                }
            ],
        },
    )
    assert closed.status_code == 201, closed.text
    blocked = _plan(client, "T-S4-04", {"snapshot_id": "snap-r04"})
    assert blocked.status_code == 200, blocked.text
    route = blocked.json()["route"]
    assert route["found"] is False
    assert route["reason"] is not None and "终点" in route["reason"]
    assert route["waypoints"] == []
    assert route["route"] is None
    assert route["length_m"] is None

    routes = client.get("/tasks/T-S4-04/routes")
    assert routes.status_code == 200
    assert [item["route_id"] for item in routes.json()] == ["v1", "v2"]


def test_future_restriction_is_not_treated_as_active(client: TestClient) -> None:
    _create(client, _task(task_id="T-future", origin=_position(500, 500), destination=_position(2500, 2500, 30)))
    created = client.post(
        "/tasks/T-future/snapshots",
        json={
            "snapshot_id": "snap-future",
            "captured_at": "2026-11-09T00:00:00+00:00",
            "landing_sites": [],
            "events": [
                {
                    "event_id": "E-later",
                    "kind": "restriction_zone",
                    "geometry": {"zone_id": "R04"},
                    "effective_from": "2099-01-01T00:00:00+00:00",
                    "provenance": PROVENANCE,
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    response = _plan(client, "T-future")
    assert response.status_code == 200, response.text
    route = response.json()["route"]
    assert route["found"] is True
    assert any("尚未" in item for item in route["limitations"])


def test_stale_snapshot_is_rejected_without_storing_a_route(client: TestClient) -> None:
    _create(client, _task(task_id="T-stale"))
    created = client.post(
        "/tasks/T-stale/snapshots",
        json={
            "snapshot_id": "snap-old",
            "captured_at": "2020-01-01T00:00:00+00:00",
            "valid_until": "2020-01-02T00:00:00+00:00",
            "landing_sites": [],
            "events": [],
        },
    )
    assert created.status_code == 201, created.text
    response = _plan(client, "T-stale")
    assert response.status_code == 409
    assert "过" in response.json()["detail"]
    assert client.get("/tasks/T-stale/routes").json() == []


def test_plan_requires_snapshot_and_enu(client: TestClient) -> None:
    _create(client, _task(task_id="T-empty"))
    missing = _plan(client, "T-empty")
    assert missing.status_code == 400

    wgs = _task(task_id="T-wgs")
    wgs["origin"] = {
        "frame": "wgs84",
        "lat_deg": 30.0,
        "lon_deg": 120.0,
        "alt_m": 0,
        "alt_ref": "rel_takeoff",
    }
    wgs["destination"] = {
        "frame": "wgs84",
        "lat_deg": 30.1,
        "lon_deg": 120.1,
        "alt_m": 30,
        "alt_ref": "rel_takeoff",
    }
    _create(client, wgs)
    _bind(client, "T-wgs")
    rejected = _plan(client, "T-wgs")
    assert rejected.status_code == 422
    assert "ENU" in rejected.json()["detail"]


def test_naive_snapshot_time_is_rejected(client: TestClient) -> None:
    _create(client, _task(task_id="T-naive"))
    response = client.post(
        "/tasks/T-naive/snapshots",
        json={
            "snapshot_id": "snap-naive",
            "captured_at": "2026-11-09T00:00:00",
            "landing_sites": [],
            "events": [],
        },
    )
    assert response.status_code == 422
    assert "时区" in response.json()["detail"]


def test_route_stays_simulated_when_task_claims_otherwise(client: TestClient) -> None:
    body = _task(task_id="T-claim")
    body["provenance"]["is_simulated"] = False
    _create(client, body)
    _bind(client, "T-claim")
    response = _plan(client, "T-claim")
    assert response.status_code == 200, response.text
    assert client.get("/tasks/T-claim").json()["provenance"]["is_simulated"] is False
    route = response.json()["route"]
    assert route["is_simulated"] is True
    assert "不能写成实测" in route["simulation_note"]


# --------------------------------------------------------------------------- #
# M2 返回值原样转发；M3 返回值不执行
# --------------------------------------------------------------------------- #
def test_adapter_passes_through_route_plan_and_margin() -> None:
    app = create_app(_settings(planner_entry="tests.fakes:diversion_plan"))
    with TestClient(app) as test_client:
        _create(test_client, _task(task_id="T-pass"))
        _bind(test_client, "T-pass")
        response = _plan(test_client, "T-pass")
        assert response.status_code == 200, response.text
        route = response.json()["route"]
        assert route["algorithm"] == "astar_diversion"
        assert route["route_plan_status"] == "available"
        assert route["route"]["route_id"] == "from-planner"
        assert route["route"]["energy_budget_wh"] == 12.5
        assert route["route"]["diversion_site_id"] == "L2"
        assert route["route_id"] == "v1"
        assert not any("不算能量" in item for item in route["limitations"])
        margin = test_client.get("/tasks/T-pass/routes/v1/margin")
        assert margin.status_code == 200
        body = margin.json()
        assert body["status"] == "available"
        assert body["min_margin_wh"] == 5.0
        assert body["negative_sample_count"] == 0
        assert body["is_feasible"] is True
        assert [sample["margin_wh"] for sample in body["profile"]["samples"]] == [10.0, 5.0]
        assert body["profile"]["samples"][0]["nearest_site_id"] == "L1"


def test_agent_return_value_does_not_rewrite_the_route() -> None:
    fakes.CALLS.clear()
    app = create_app(_settings(agent_entry="tests.fakes:agent_tries_to_rewrite"))
    with TestClient(app) as test_client:
        _create(test_client)
        _bind(test_client, "T-20261109-001")
        response = _plan(test_client, "T-20261109-001")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agent"]["status"] == "invoked"
    assert body["agent"]["applied"] is False
    assert len(body["route"]["waypoints"]) > 2
    assert body["route"]["waypoints"][0]["x_m"] == 150
    assert fakes.CALLS[-1].task_id == "T-20261109-001"
    assert fakes.CALLS[-1].event == "plan_completed"


def test_agent_error_keeps_the_route() -> None:
    app = create_app(_settings(agent_entry="tests.fakes:agent_raises"))
    with TestClient(app) as test_client:
        _create(test_client, _task(task_id="T-agent-err"))
        _bind(test_client, "T-agent-err")
        response = _plan(test_client, "T-agent-err")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["route"]["found"] is True
    assert body["agent"]["status"] == "error"
    assert body["agent"]["applied"] is False
    assert "拒绝改写路线" in body["agent"]["detail"]


def test_standalone_api_does_not_implement_m3_or_use_mock_planners() -> None:
    """独立进程不实现 M3，也不把 mock 规划器接到 HTTP。

    `agent/` 来自上游，由 `runtime.py` 的本地调度链路使用。这个测试不要求删掉它。
    """
    assert (REPO_ROOT / "agent").is_dir()
    assert not (REPO_ROOT / "m3").exists()
    standalone = (
        "__main__.py",
        "agent_hook.py",
        "assemble.py",
        "config.py",
        "entrypoints.py",
        "envelopes.py",
        "errors.py",
        "main.py",
        "planner_adapter.py",
        "scene_loader.py",
        "store.py",
    )
    for name in standalone:
        text = (REPO_ROOT / "services" / "api" / name).read_text(encoding="utf-8")
        assert "eval.planners" not in text
        assert "MockPlanner" not in text
        assert "import agent" not in text
        assert "from agent" not in text
