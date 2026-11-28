"""Natural language to a confirmed WGS84 task and its actual planning evidence."""

from uuid import uuid4

import pytest

from services.assistant import environment, evidence, tools
from services.assistant.engine import Engine, Settings
from services.assistant.intake import IntakeStore
from services.assistant.models import Context
from services.assistant.tests.test_assistant import make_turn
from services.assistant.tests.test_route_environment import _weather


def test_synthetic_place_is_not_a_priority_or_a_geographic_pin():
    text = "下周从医疗物资中转站送东西到北区应急中心"
    assert "priority" not in evidence.extract_confirmations(text)
    result = Engine(Settings()).run(make_turn(text), lambda _: None)
    card = result["clarification"]
    assert any(q["field"] == "priority" for q in card["questions"])
    assert "150.000000" not in card["summary"]
    assert "150.000000" not in " ".join(q["question"] for q in card["questions"])


@pytest.mark.parametrize(
    "text",
    [
        "从江西农业大学到南昌航空大学，规划一条航线",
        "江西农业大学和南昌航空大学之间规划一条路线",
        "明天15点从江西农业大学到南昌航空大学，配送2公斤药品，优先级P1",
    ],
)
def test_real_places_without_a_date_still_produce_a_confirmation(monkeypatch, text):
    def locate(name, **kwargs):
        return {
            "status": "ok",
            "name": name,
            "point": [120, 30] if name == "江西农业大学" else [120.01, 30],
            "crs": "EPSG:4326",
            "source": "test location",
            "is_simulated": False,
        }

    monkeypatch.setattr(evidence, "resolve_place", locate)
    result = Engine(Settings()).run(make_turn(text), lambda _: None)
    card = result["clarification"]
    assert card and card["status"] == "needs_clarification"
    assert [p["name"] for p in card["map_pins"]] == ["江西农业大学", "南昌航空大学"]
    assert result["draft"]["origin"] == "江西农业大学"
    assert result["draft"]["destination"] == "南昌航空大学"
    assert result["intake"] is None
    assert not any(t["name"] == "plan_task_preview" for t in result["traces"])
    if "明天" not in text:
        assert any(q["field"] == "scheduled_for" for q in card["questions"])


def test_confirmation_receipt_and_comprehensive_inspection_use_one_route(monkeypatch, tmp_path):
    store = IntakeStore(tmp_path / "intakes")
    monkeypatch.setattr(tools, "intake_store", store)
    monkeypatch.setattr(environment, "AUDIT_ROOT", tmp_path / "audit")
    environment.clear_environment_cache()

    def route(origin, destination, when):
        weather = _weather([0, 1, 0])
        for sample in weather["samples"]:
            sample["values"].pop("wind_speed_10m")
            sample["values"].pop("wind_direction_10m")
        return {
            "status": "ok",
            "route_id": "actual-detour",
            "waypoints": [
                {"x": origin[0], "y": origin[1]},
                {"x": 120.005, "y": 30.005},
                {"x": destination[0], "y": destination[1]},
            ],
            "length_m": 1500,
            "planning_result": {"weather": weather},
        }

    monkeypatch.setattr(tools, "real_route_for_intake", route)
    turn = make_turn(
        "确认地点和任务",
        confirmation={
            "confirmation_id": str(uuid4()),
            "text": "确认任务",
            "origin": "起点",
            "destination": "终点",
            "origin_point": [120, 30],
            "destination_point": [120.01, 30],
            "scheduled_for": "2026-11-29T15:00:00+08:00",
            "payload_kg": 2,
            "priority": "P1",
        },
    )
    created = Engine(Settings()).run(turn, lambda _: None)
    assert created["intake"]["origin"] == "起点"
    intake_id = created["intake"]["id"]
    inspect = make_turn("综合检查当前路线的禁飞区、天气、风向和备降点")
    inspect.context = Context.model_validate(
        {
            **inspect.context.model_dump(),
            "telemetry_mode": "planning",
            "telemetry": None,
            "selected_intake_id": intake_id,
            "route_id": "actual-detour",
            "task_id": intake_id,
            "active_route": {
                "route_id": "actual-detour",
                "task_id": intake_id,
                "frame": "WGS84",
                "source": "test actual route",
                "waypoints": [[120, 30], [120.005, 30.005], [120.01, 30]],
            },
        }
    )
    result = Engine(Settings()).run(inspect, lambda _: None)
    plan = result["traces"][0]["result"]
    assert result["traces"][0]["name"] == "inspect_mission_plan"
    assert plan["route_id"] == "actual-detour"
    assert plan["environment"]["geometry_scope"] == "provided_route"
    assert plan["landing"]["status"] == "unavailable"
    assert "缺少建筑足迹连续净空通过证据" in dict(plan["rows"])["建筑避障"]
    assert "保存风场事后评估" in dict(plan["rows"])["风向与侧风"]
    assert any(b["type"] == "env_matrix" for b in result["presentation"]["blocks"])
    assert any(b["title"] == "任务规划与备降依据" for b in result["presentation"]["blocks"])
    assert "风未参与几何寻路" in result["text"]
    inspect.context.active_route.waypoints[1] = (120.006, 30.006)
    mismatch = Engine(Settings()).run(inspect, lambda _: None)
    assert mismatch["traces"][0]["result"]["status"] == "route_mismatch"
    assert not mismatch["presentation"]["blocks"]
