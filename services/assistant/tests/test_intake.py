"""Natural-language intake: time parsing, honest degradation and persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from services.assistant import evidence, tools
from services.assistant.engine import Engine, Settings
from services.assistant.intake import (
    IntakeCreate,
    IntakeStore,
    PlaceEvidence,
    TaskIntake,
    WeatherEvidence,
)
from services.assistant.models import Turn

TELEMETRY = {
    "battery": 83.4,
    "voltage": 24.4,
    "current": 8.6,
    "energyWh": 212.8,
    "altitude": 123.6,
    "speed": 12.4,
    "climb": 0.3,
    "heading": 42,
    "pitch": -2.4,
    "roll": 0.7,
    "rssi": -68,
    "satellites": 17,
    "hdop": 0.8,
    "rtt": 42,
    "rotors": [6800, 6500, 6600, 6600],
    "motorTemp": 61,
    "coverage": 65,
    "scanned": 19,
    "totalCells": 29,
    "distanceToTarget": 1240,
    "obstacleDistance": 32.8,
}


def make_turn(text="查询当前状态"):
    return Turn.model_validate(
        {
            "request_id": str(uuid4()),
            "text": text,
            "history": [],
            "context": {
                "sampled_at": "2026-11-15T12:00:00+00:00",
                "progress": 0.43,
                "telemetry": TELEMETRY,
                "events": [],
            },
        }
    )


def test_parse_schedule_next_wednesday():
    now = datetime.fromisoformat("2026-11-15T10:00:00+08:00")
    value, note = evidence.parse_schedule("下周三我想送东西", now)
    assert value.startswith("2026-11-18T09:00:00+08:00")
    assert "下一个自然周一" in note


def test_parse_schedule_without_time():
    value, note = evidence.parse_schedule("帮我规划路线", datetime.fromisoformat("2026-11-15T10:00:00+08:00"))
    assert value is None
    assert "未识别" in note


def test_weather_is_unavailable_when_upstream_fails(monkeypatch):
    class Broken:
        def __enter__(self):
            raise OSError("network blocked")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(evidence.httpx, "Client", lambda **kwargs: Broken())
    result = evidence.fetch_weather_forecast(31.2, 121.4, "2026-11-25T09:00:00+08:00")
    assert result["status"] == "unavailable"
    assert result["values"] == {}
    assert result["kind"] == "forecast"
    assert result["reason"]


def test_extract_confirmations_only_explicit_values():
    text = (
        "确认一下：时间是下周三 11月18日 09:00，起点就是上海虹桥机场，终点是浦东机场，"
        "我在地图上点过了，起点坐标 121.33,31.19，终点 121.80,31.14，载荷 2 公斤，优先级 P1。"
    )
    result = evidence.extract_confirmations(text)
    assert result["scheduled_for"].startswith("2026-11-18T09:00")
    assert result["origin_point"] == [121.33, 31.19]
    assert result["destination_point"] == [121.8, 31.14]
    assert result["payload_kg"] == 2.0
    assert result["priority"] == "P1"
    assert result["schedule_confirmed"] is True
    assert result["places_confirmed"] is True


def test_extract_confirmations_does_not_guess():
    assert evidence.extract_confirmations("下周送东西，可以吗") == {}


def test_airspace_zones_are_explicitly_draft():
    result = evidence.list_airspace_zones()
    assert result["status"] == "draft"
    assert result["is_simulated"] is True
    assert "非实测空域" in result["note"]
    assert len(result["zones"]) == 4


def test_unresolved_place_never_invents_coordinates(monkeypatch):
    class Broken:
        def __enter__(self):
            raise OSError("network blocked")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(evidence.httpx, "Client", lambda **kwargs: Broken())
    result = evidence.resolve_place("某地", local_places={}, aliases={})
    assert result["status"] == "unresolved"
    assert result["point"] is None


def test_store_roundtrip(tmp_path):
    store = IntakeStore(root=tmp_path / "intakes")
    body = IntakeCreate(text="下周送东西", origin="A", destination="B")
    record = TaskIntake.build(
        body,
        origin=PlaceEvidence(name="A", source="test"),
        destination=PlaceEvidence(name="B", source="test"),
        weather=WeatherEvidence(),
        airspace=evidence.list_airspace_zones(),
        route_preview=None,
        warnings=["测试"],
    )
    store.create(record)
    assert store.get(record.intake_id)["intake_id"] == record.intake_id
    assert [item["intake_id"] for item in store.list()] == [record.intake_id]
    with pytest.raises(KeyError):
        store.get("../escape")


def test_create_task_intake_tool_records_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "intake_store", IntakeStore(root=tmp_path / "intakes"))
    monkeypatch.setattr(
        tools.evidence,
        "resolve_place",
        lambda name, **kwargs: {
            "status": "ok",
            "name": name,
            "point": [121.3, 31.2],
            "crs": "EPSG:4326",
            "source": "test-stub",
            "is_simulated": False,
        },
    )
    monkeypatch.setattr(
        tools.evidence,
        "fetch_weather_forecast",
        lambda *args, **kwargs: {
            "status": "ok",
            "kind": "forecast",
            "source": "test-stub",
            "scheduled_for": "2026-11-25T09:00:00+08:00",
            "valid_for": "2026-11-25T09:00",
            "values": {"temperature_2m": 18.2},
            "reason": "",
            "note": "测试桩，非实测",
        },
    )
    toolset = tools.Toolset(make_turn())
    toolset.execute("resolve_real_place", {"name": "上海虹桥机场"})
    toolset.execute("resolve_real_place", {"name": "浦东机场"})
    toolset.execute("get_airspace_zones", {})
    toolset.execute(
        "get_weather_forecast",
        {"latitude": 31.2, "longitude": 121.3, "scheduled_for": "2026-11-25T09:00:00+08:00"},
    )
    result = toolset.execute(
        "create_task_intake",
        {
            "text": "下周三从上海虹桥机场送东西到浦东机场",
            "origin": "上海虹桥机场",
            "destination": "浦东机场",
            "scheduled_for": "2026-11-25T09:00:00+08:00",
            "schedule_confirmed": True,
            "places_confirmed": True,
            "origin_point": [121.3, 31.2],
            "destination_point": [121.8, 31.15],
            "payload_kg": 1.0,
            "priority": "P1",
        },
    )
    assert result["status"] == "created"
    assert result["dispatch_enabled"] is False
    stored = tools.intake_store.get(result["intake_id"])
    assert stored["is_simulated"] is True
    assert stored["airspace"]["status"] == "draft"
    assert stored["weather"]["status"] == "ok"
    assert stored["weather"]["kind"] == "forecast"
    assert stored["route_preview"] is None
    assert stored["real_route"]["status"] == "ok"
    assert len(stored["real_route"]["waypoints"]) == 2
    assert any("物理净空" in warning for warning in stored["warnings"])


def test_engine_asks_full_clarification_before_creating(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "intake_store", IntakeStore(root=tmp_path / "intakes"))
    monkeypatch.setattr(
        tools.evidence,
        "resolve_place",
        lambda name, **kwargs: {
            "status": "unresolved",
            "name": name,
            "point": None,
            "crs": "unresolved",
            "source": "未解析；未猜测坐标",
            "is_simulated": True,
        },
    )
    packets = []
    result = Engine(Settings()).run(
        make_turn("下周我想从上海虹桥机场送东西到浦东机场，你能给我规划路线吗？"), packets.append
    )
    names = [packet["name"] for packet in packets if packet["type"] == "tool_start"]
    assert "resolve_real_place" in names
    assert "get_airspace_zones" in names
    assert "create_task_intake" in names
    assert "地点还没完全解析" in result["text"]
    assert "时间：" in result["text"]
    assert "还差：载荷、优先级" in result["text"]
    assert tools.intake_store.list() == []

    tracer = next(
        packet["trace"]["result"]
        for packet in packets
        if packet["type"] == "tool_result" and packet["trace"]["name"] == "create_task_intake"
    )
    assert tracer["status"] == "needs_clarification"
    assert {item["field"] for item in tracer["questions"]} >= {
        "scheduled_for",
        "origin",
        "destination",
        "payload_kg",
    }
    assert len(tracer["map_pins"]) == 2
    assert all(pin["point"] is None for pin in tracer["map_pins"])
    assert tracer["weather_feasibility"]["status"] == "needs_map_pin"


def test_clarification_then_confirmation_creates_intake(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "intake_store", IntakeStore(root=tmp_path / "intakes"))
    monkeypatch.setattr(
        tools.evidence,
        "fetch_weather_forecast",
        lambda *args, **kwargs: evidence.unavailable_weather("test-stub"),
    )
    monkeypatch.setattr(
        tools.evidence,
        "resolve_place",
        lambda name, **kwargs: {
            "status": "unresolved",
            "name": name,
            "point": None,
            "crs": "unresolved",
            "source": "未解析；未猜测坐标",
            "is_simulated": True,
        },
    )
    toolset = tools.Toolset(make_turn())
    first = toolset.execute(
        "create_task_intake",
        {"text": "下周三送东西", "origin": "A", "destination": "B"},
    )
    assert first["status"] == "needs_clarification"
    assert tools.intake_store.list() == []
    second = toolset.execute(
        "create_task_intake",
        {
            "text": "下周三送东西",
            "origin": "A",
            "destination": "B",
            "scheduled_for": "2026-11-18T09:00:00+08:00",
            "schedule_confirmed": True,
            "places_confirmed": True,
            "origin_point": [121.3, 31.2],
            "destination_point": [121.8, 31.15],
            "payload_kg": 1.0,
            "priority": "P1",
        },
    )
    assert second["status"] == "created"
    assert len(tools.intake_store.list()) == 1


def test_intake_records_route_failure_instead_of_guessing(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "intake_store", IntakeStore(root=tmp_path / "intakes"))
    monkeypatch.setattr(
        tools.evidence,
        "resolve_place",
        lambda name, **kwargs: {
            "status": "ok",
            "name": name,
            "point": [121.3, 31.2],
            "crs": "EPSG:4326",
            "source": "test-stub",
            "is_simulated": False,
        },
    )

    def boom(*args, **kwargs):
        raise RuntimeError("overpass unavailable")

    toolset = tools.Toolset(make_turn(), real_route_provider=boom)
    result = toolset.execute(
        "create_task_intake",
        {
            "text": "从 A 送 1 公斤到 B",
            "origin": "A",
            "destination": "B",
            "origin_point": [121.3, 31.2],
            "destination_point": [121.8, 31.15],
            "scheduled_for": "2026-11-20T09:00:00+08:00",
            "payload_kg": 1.0,
            "priority": "P2",
            "places_confirmed": True,
            "schedule_confirmed": True,
        },
    )
    assert result["status"] == "created"
    stored = tools.intake_store.get(result["intake_id"])
    assert stored["real_route"]["status"] == "unavailable"
    assert "overpass unavailable" in stored["real_route"]["reason"]
    assert stored["real_route"]["waypoints"] == []
    assert any("真实航线未生成" in warning for warning in stored["warnings"])
    assert any("未用直线代替" in warning for warning in stored["warnings"])
    assert stored["dispatch_enabled"] is False


def test_yearless_schedule_is_normalized_before_routing(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "intake_store", IntakeStore(root=tmp_path / "intakes"))
    monkeypatch.setattr(
        tools.evidence,
        "resolve_place",
        lambda name, **kwargs: {
            "status": "ok",
            "name": name,
            "point": [115.83, 28.76] if "农业" in name else [115.82, 28.65],
            "crs": "EPSG:4326",
            "source": "test-stub",
            "is_simulated": False,
        },
    )
    seen = {}

    def provider(origin, destination, scheduled_for):
        seen["scheduled_for"] = scheduled_for
        return {"status": "ok", "waypoints": [], "length_m": 1.0, "reason": None}

    toolset = tools.Toolset(make_turn(), real_route_provider=provider)
    result = toolset.execute(
        "create_task_intake",
        {
            "text": "从江西农业大学送3公斤到南昌航空大学",
            "origin": "江西农业大学",
            "destination": "南昌航空大学",
            "scheduled_for": "11-17T10:40",
            "schedule_confirmed": True,
            "places_confirmed": True,
            "payload_kg": 3.0,
            "priority": "P2",
        },
    )
    assert result["status"] == "created"
    stored = tools.intake_store.get(result["intake_id"])
    assert stored["scheduled_for"].startswith("2026-11-17T10:40")
    assert "年份" in stored["schedule_note"]
    # The router must receive a parseable instant, never the yearless string.
    assert seen["scheduled_for"].startswith("2026-11-17T10:40")


def test_conflicting_map_pin_blocks_intake_and_offers_options(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "intake_store", IntakeStore(root=tmp_path / "intakes"))
    monkeypatch.setattr(
        tools.evidence,
        "resolve_place",
        lambda name, **kwargs: {
            "status": "ok",
            "name": name,
            "point": [115.83, 28.76],
            "crs": "EPSG:4326",
            "source": "test-stub",
            "is_simulated": False,
        },
    )
    toolset = tools.Toolset(make_turn())
    result = toolset.execute(
        "create_task_intake",
        {
            "text": "从江西农业大学送3公斤到南昌航空大学",
            "origin": "江西农业大学",
            "destination": "南昌航空大学",
            # Stale Shanghai click from an earlier session.
            "origin_point": [121.335, 31.198],
            "schedule_confirmed": True,
            "places_confirmed": True,
            "payload_kg": 3.0,
            "priority": "P2",
        },
    )
    assert result["status"] == "needs_clarification"
    question = next(item for item in result["questions"] if item["field"] == "origin")
    assert len(question["options"]) == 2
    assert question["options"][0]["label"].startswith("A")
    assert tools.intake_store.list() == []


def test_unparseable_schedule_blocks_instead_of_creating(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "intake_store", IntakeStore(root=tmp_path / "intakes"))
    monkeypatch.setattr(
        tools.evidence,
        "resolve_place",
        lambda name, **kwargs: {
            "status": "ok",
            "name": name,
            "point": [115.83, 28.76],
            "crs": "EPSG:4326",
            "source": "test-stub",
            "is_simulated": False,
        },
    )
    toolset = tools.Toolset(make_turn())
    result = toolset.execute(
        "create_task_intake",
        {
            "text": "从江西农业大学送3公斤到南昌航空大学",
            "origin": "江西农业大学",
            "destination": "南昌航空大学",
            "scheduled_for": "某个时候",
            "schedule_confirmed": True,
            "places_confirmed": True,
            "payload_kg": 3.0,
            "priority": "P2",
        },
    )
    assert result["status"] == "needs_clarification"
    assert any(item["field"] == "scheduled_for" for item in result["questions"])
    assert tools.intake_store.list() == []


def test_background_route_fills_the_intake_after_creation(tmp_path, monkeypatch):
    import time

    monkeypatch.setattr(tools, "intake_store", IntakeStore(root=tmp_path / "intakes"))
    monkeypatch.setattr(
        tools.evidence,
        "resolve_place",
        lambda name, **kwargs: {
            "status": "ok",
            "name": name,
            "point": [115.83, 28.76] if "农业" in name else [115.82, 28.65],
            "crs": "EPSG:4326",
            "source": "test-stub",
            "is_simulated": False,
        },
    )

    def slow_provider(origin, destination, scheduled_for):
        time.sleep(0.05)
        return {"status": "ok", "waypoints": [], "length_m": 12345.0, "reason": None}

    toolset = tools.Toolset(make_turn(), real_route_provider=slow_provider, route_background=True)
    result = toolset.execute(
        "create_task_intake",
        {
            "text": "从江西农业大学送3公斤到南昌航空大学",
            "origin": "江西农业大学",
            "destination": "南昌航空大学",
            "scheduled_for": "2026-11-20T09:00:00+08:00",
            "schedule_confirmed": True,
            "places_confirmed": True,
            "payload_kg": 3.0,
            "priority": "P2",
        },
    )
    assert result["status"] == "created"
    assert result["intake"]["real_route"]["status"] == "pending"
    deadline = time.time() + 2.0
    while time.time() < deadline:
        stored = tools.intake_store.get(result["intake_id"])
        if stored["real_route"]["status"] != "pending":
            break
        time.sleep(0.02)
    stored = tools.intake_store.get(result["intake_id"])
    assert stored["real_route"]["status"] == "ok"
    assert stored["real_route"]["length_m"] == 12345.0
    assert not any("后台计算中" in warning for warning in stored["warnings"])


def test_maas_mode_requires_the_confirmation_card_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "intake_store", IntakeStore(root=tmp_path / "intakes"))
    monkeypatch.setattr(
        tools.evidence,
        "resolve_place",
        lambda name, **kwargs: {
            "status": "ok",
            "name": name,
            "point": [115.83, 28.76] if "农业" in name else [115.82, 28.65],
            "crs": "EPSG:4326",
            "source": "test-stub",
            "is_simulated": False,
        },
    )
    args = {
        "text": "从江西农业大学送3公斤到南昌航空大学",
        "origin": "江西农业大学",
        "destination": "南昌航空大学",
        "scheduled_for": "2026-11-20T09:00:00+08:00",
        "schedule_confirmed": True,
        "places_confirmed": True,
        "payload_kg": 3.0,
        "priority": "P2",
    }
    toolset = tools.Toolset(make_turn(), require_confirmation=True)
    first = toolset.execute("create_task_intake", args)
    assert first["status"] == "needs_clarification"
    assert tools.intake_store.list() == []
    pins = {pin["field"]: pin["point"] for pin in first["map_pins"]}
    assert pins["origin"] == [115.83, 28.76]
    assert first["draft_values"]["payload_kg"] == 3.0

    from services.assistant.intake import IntakeConfirmation

    toolset.turn.confirmation = IntakeConfirmation.model_validate(
        args
        | {
            "confirmation_id": str(uuid4()),
            "origin_point": [115.83, 28.76],
            "destination_point": [115.82, 28.65],
        }
    )
    confirmed = toolset.execute(
        "create_task_intake",
        args | {"text": "确认建单：起点 江西农业大学，终点 南昌航空大学，按这些建任务"},
    )
    assert confirmed["status"] == "created"
    assert len(tools.intake_store.list()) == 1


def test_intake_overview_returns_real_chart_series(tmp_path, monkeypatch):
    from services.assistant.intake import IntakeCreate, PlaceEvidence, TaskIntake, WeatherEvidence

    store = IntakeStore(root=tmp_path / "intakes")
    monkeypatch.setattr(tools, "intake_store", store)
    waypoints = [
        {"lng": 115.8319 + index * 0.001, "lat": 28.7649 - index * 0.001, "x": 0, "y": 0}
        for index in range(20)
    ]
    done = TaskIntake.build(
        IntakeCreate(text="A→B", origin="A", destination="B", payload_kg=3.0),
        origin=PlaceEvidence(
            name="江西农业大学", point=[115.8319, 28.7649], crs="EPSG:4326", source="t", is_simulated=False
        ),
        destination=PlaceEvidence(
            name="南昌航空大学", point=[115.8225, 28.6543], crs="EPSG:4326", source="t", is_simulated=False
        ),
        weather=WeatherEvidence(),
        airspace={"status": "draft"},
        route_preview=None,
        real_route={"status": "ok", "waypoints": waypoints, "length_m": 12345.0},
        warnings=[],
    )
    pending = TaskIntake.build(
        IntakeCreate(text="C→D", origin="C", destination="D", payload_kg=1.5),
        origin=PlaceEvidence(name="C", point=[115.8, 28.7], crs="EPSG:4326", source="t", is_simulated=False),
        destination=PlaceEvidence(
            name="D", point=[115.81, 28.69], crs="EPSG:4326", source="t", is_simulated=False
        ),
        weather=WeatherEvidence(),
        airspace={"status": "draft"},
        route_preview=None,
        real_route={"status": "pending", "waypoints": [], "reason": None},
        warnings=[],
    )
    store.create(done)
    store.create(pending)
    data = tools.Toolset(make_turn()).execute("get_intake_overview", {})
    counts = {item["label"]: item["value"] for item in data["status_counts"]}
    assert counts["航线已生成"] == 1
    assert counts["后台计算中"] == 1
    assert data["latest_route"]["waypoint_count"] == 20
    assert 2 <= len(data["latest_route"]["profile"]) <= 12
    assert data["latest_route"]["profile"][0]["value"] == 0
    assert data["latest_route"]["profile"][-1]["value"] > 0
    assert {item["value"] for item in data["payloads"]} == {3.0, 1.5}
