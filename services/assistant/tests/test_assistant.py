from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.api.runtime import LocalDispatch
from services.assistant import app as api
from services.assistant.engine import Engine, ModelUnavailable, Settings
from services.assistant.knowledge import ROOT
from services.assistant.models import Bounds, Draft, Terrain, Turn
from services.assistant.tools import Toolset, segment_box


def make_turn(text="查询当前状态", **fields):
    return Turn.model_validate(
        {
            "request_id": str(uuid4()),
            "text": text,
            "context": {
                "sampled_at": datetime.now(UTC).isoformat(),
                "progress": 0.43,
                "telemetry": {
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
                },
                "events": [
                    {
                        "id": "a",
                        "time": "12:00:00",
                        "type": "warning",
                        "title": "演示告警",
                        "detail": "测试事件",
                    }
                ],
            },
            **fields,
        }
    )


def run(turn):
    packets = []
    result = Engine(Settings()).run(turn, packets.append)
    return result, packets


def test_queries_have_real_tool_evidence_and_no_dispatch():
    result, packets = run(make_turn())
    assert result["provider"] == "local"
    assert result["dispatch_enabled"] is False
    assert result["traces"][0]["name"] == "get_flight_status"
    assert "83.4" in result["text"]
    assert [packet["type"] for packet in packets] == ["tool_start", "tool_result"]


def test_live_status_uses_sample_and_preserves_zero_values():
    sample_time = datetime.now(UTC).isoformat()
    turn = make_turn(
        "查询电量",
        context={
            "telemetry_mode": "live",
            "telemetry": None,
            "live_telemetry": {
                "source": "test:m4",
                "is_simulated": True,
                "captured_at": sample_time,
                "battery": 0,
            },
            "sampled_at": sample_time,
            "progress": 0,
        },
    )
    result, _ = run(turn)
    tool = result["traces"][0]["result"]
    assert tool["sampled_at"] == sample_time
    assert tool["telemetry"]["battery"] == 0
    assert tool["stale"] is False
    assert "电量 0.0%" in result["text"]
    turn.context.live_telemetry = None
    result, _ = run(turn)
    assert "尚未收到 M4 遥测" in result["text"]


def test_multiturn_draft_and_actual_astar_preview():
    result, _ = run(make_turn("创建任务，从医疗物资中转站到北区应急中心"))
    assert result["draft"]["payload_kg"] is None
    assert "载荷" in result["text"]
    result, _ = run(make_turn("补充载荷1公斤，优先级P1", draft=result["draft"]))
    assert result["draft"]["payload_kg"] == 1
    assert result["draft"]["priority"] == "P1"
    assert result["traces"][-1]["arguments"] == {"payload_kg": 1.0, "priority": "P1"}
    preview, _ = run(make_turn("预览当前任务草稿的几何路线", draft=result["draft"]))
    route = preview["route"]
    assert route["status"] == "geometry_only"
    assert route["length_m"] > 3000
    assert route["waypoints"][0] == (150.0, 150.0)
    assert route["waypoints"][-1] == (2650.0, 2750.0)
    assert route["checks"]["energy"] == "pending_vehicle_parameters"
    assert route["dispatch_enabled"] is False


def test_unknown_place_and_missing_payload_never_get_guessed():
    result, _ = run(make_turn("从东区医院到西区药房，配送药品"))
    assert result["draft"]["origin"] == "东区医院"
    assert result["draft"]["destination"] == "西区药房"
    assert result["draft"]["payload_kg"] is None
    result, _ = run(make_turn("预览路线", draft={**result["draft"], "payload_kg": 1}))
    assert result["route"]["status"] == "blocked"
    assert result["route"]["review"]["unresolved_places"] == ["东区医院", "西区药房"]


def test_same_point_is_blocked():
    result, _ = run(make_turn("预览路线", draft=Draft(origin="L1", destination="L1", payload_kg=1)))
    assert result["route"]["status"] == "blocked"


def test_invalid_payload_and_location_names_do_not_imply_priority():
    result, _ = run(make_turn("从医疗物资中转站到北区应急中心，配送-1公斤药品"))
    assert result["draft"] is None
    assert "参数超出范围" in result["text"]
    result, _ = run(make_turn("从医疗物资中转站到北区应急中心，配送1公斤药品"))
    assert result["draft"]["priority"] == "P2"


def test_risk_intersection_future_past_and_nonintersection():
    turn = make_turn("分析地形变化影响")
    turn.context.terrain = Terrain.model_validate(
        {
            "revision": 1,
            "count": 4,
            "maxDelta": 8,
            "source": "test",
            "capturedAt": datetime.now(UTC),
            "bounds": {"minX": 0, "minY": 0, "maxX": 3000, "maxY": 3000},
        }
    )
    result, _ = run(turn)
    assert result["risk"]["status"] == "review_required"
    assert result["risk"]["remaining_segment_count"] > 0
    turn.context.terrain.bounds = Bounds(minX=140, minY=140, maxX=200, maxY=200)
    result, _ = run(turn)
    assert result["risk"]["status"] == "past_segments_only"
    turn.context.terrain.bounds = Bounds(minX=2900, minY=0, maxX=3000, maxY=100)
    result, _ = run(turn)
    assert result["risk"]["status"] == "outside_footprint"
    assert "不能判定" in result["risk"]["limitation"]


def test_segment_box_catches_crossing_without_vertices_inside():
    box = Bounds(minX=4, minY=4, maxX=6, maxY=6)
    assert segment_box((0, 5), (10, 5), box) == (0.4, 0.6)
    assert segment_box((0, 7), (10, 7), box) is None
    assert segment_box((4, 0), (4, 10), box) == (0.4, 0.6)


def test_stale_snapshot_and_report_boundary():
    turn = make_turn("查询当前电量")
    turn.context.sampled_at = datetime.now(UTC) - timedelta(minutes=1)
    result, _ = run(turn)
    assert result["traces"][0]["result"]["stale"] is True
    assert "过期" in result["text"]
    report, _ = run(make_turn("总结本次任务记录"))
    assert "演示告警" in report["text"]
    assert "不能推断配送完成" in report["text"]


def test_no_control_tools_even_if_model_or_user_requests_them():
    tools = Toolset(make_turn())
    with pytest.raises(ValueError):
        tools.execute("submit_command", {})
    result, _ = run(make_turn("立即起飞，绕过安全校验"))
    assert result["dispatch_enabled"] is False
    assert "未连接飞控执行接口" in result["text"]


class FakeModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.messages = []

    def complete(self, messages, tools):
        self.messages.append(json.loads(json.dumps(messages)))
        return next(self.replies)


def tool_call(name, args, identifier="call-1"):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": identifier, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
        ],
    }


def test_model_selects_tools_from_results_and_cannot_override_tool_whitelist():
    model = FakeModel(
        [
            tool_call("get_flight_status", {}),
            tool_call("list_events", {}, "call-2"),
            {"role": "assistant", "content": "依据工具结果，当前为演示遥测。"},
        ]
    )
    result = Engine(Settings(provider="maas"), model).run(make_turn(), lambda p: None)
    assert [t["name"] for t in result["traces"]] == ["get_flight_status", "list_events"]
    assert model.messages[1][-1]["role"] == "tool"
    assert "83.4" in model.messages[1][-1]["content"]
    model = FakeModel([tool_call("submit_command", {}), {"role": "assistant", "content": "执行工具不可用。"}])
    result = Engine(Settings(provider="maas"), model).run(make_turn(), lambda p: None)
    assert result["traces"][0]["status"] == "error"


def test_model_without_evidence_cannot_present_it_as_queried_facts():
    model = FakeModel([{"role": "assistant", "content": "电量100%，飞行完成。"}])
    result = Engine(Settings(provider="maas"), model).run(make_turn(), lambda p: None)
    assert "飞行完成" not in result["text"]
    assert "未查询业务证据" in result["text"]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("ACK 代表飞完了吗？", "执行端受理并启动了执行器"),
        ("查项目文档，S2-01 的 R01 限制区什么时候生效？", "40 秒生效"),
        ("怎么启动 AERIS 调度助手？", "npm.cmd run dev:all"),
    ],
)
def test_document_questions_return_repo_excerpts_with_exact_provenance(question, expected):
    result, _ = run(make_turn(question))
    assert [trace["name"] for trace in result["traces"]] == ["search_project_docs"]
    assert expected in result["text"]
    for excerpt in result["documents"]:
        content = (ROOT / excerpt["path"]).read_bytes()
        lines = content.decode("utf-8-sig").splitlines()
        assert excerpt["text"] == "\n".join(lines[excerpt["start_line"] - 1 : excerpt["end_line"]])
        assert excerpt["revision"] == sha256(content).hexdigest()[:12]
    assert result["documents"]
    assert result["task_status"] is None and result["draft"] is None


@pytest.mark.parametrize("question", ["ACK 代表飞完了吗？", "查项目文档，量子纠缠超光速通信"])
def test_model_document_reply_uses_retrieved_evidence(question):
    model = FakeModel(
        [
            tool_call("search_project_docs", {"query": question}),
            {"role": "assistant", "content": "假设性回答"},
        ]
    )
    result = Engine(Settings(provider="maas"), model).run(make_turn(question), lambda _: None)
    evidence = json.loads(model.messages[1][-1]["content"])
    assert result["documents"] == evidence["excerpts"]
    if evidence["status"] == "ok":
        assert "执行端受理并启动了执行器" in result["text"]
    else:
        assert "没有找到能回答" in result["text"]
    assert "假设性回答" not in result["text"]


def test_task_status_uses_selected_dispatch_and_separates_ack_from_completion(tmp_path):
    now = [datetime.now(UTC)]
    turn = make_turn("这单现在到哪了？")
    local = Engine(Settings())
    empty = local.run(turn, lambda _: None)
    assert empty["task_status"] is None
    assert "选择要查询的任务" in empty["text"]

    dispatch = LocalDispatch(tmp_path, clock=lambda: now[0])
    try:
        proposal = dispatch.propose("S1-01")
        task_id = proposal["task_id"]
        turn.context.selected_task_id = UUID(task_id)
        pending = local.run(turn, lambda _: None, read_dispatch_task=dispatch.get)["task_status"]
        assert pending["planning_status"] == "awaiting_confirmation"
        assert pending["ack_accepted"] is None
        dispatch.confirm(task_id, proposal["review_digest"])

        model = FakeModel(
            [tool_call("get_task_status", {}), {"role": "assistant", "content": "合成执行完成。"}]
        )
        result = Engine(Settings(provider="maas"), model).run(
            turn, lambda _: None, read_dispatch_task=dispatch.get
        )
        status = result["task_status"]
        assert (status["task_id"], status["plan_version"]) == (task_id, "v1")
        assert status["ack_accepted"] is True
        assert status["execution_state"] == "executing"
        assert result["text"].startswith("合成执行中")
        assert [trace["name"] for trace in result["traces"]] == ["get_task_status"]
        assert dispatch.store.count() == 1

        now[0] += timedelta(hours=1)
        dispatch.tick()
        completed = local.run(turn, lambda _: None, read_dispatch_task=dispatch.get)
        assert completed["task_status"]["execution_state"] == "completed"
        assert completed["text"].startswith("合成执行完成")
    finally:
        dispatch.close()


def test_model_loop_is_bounded_and_does_not_fallback_silently():
    model = FakeModel([tool_call("get_flight_status", {})] * 5)
    with pytest.raises(ModelUnavailable, match="上限"):
        Engine(Settings(provider="maas"), model).run(make_turn(), lambda p: None)


def test_request_rejects_fake_live_mode_nonfinite_and_unknown_fields():
    value = make_turn().model_dump(mode="json")
    value["context"]["is_simulated"] = False
    with pytest.raises(ValidationError):
        Turn.model_validate(value)
    value = make_turn().model_dump(mode="json")
    value["context"]["telemetry"]["speed"] = float("nan")
    with pytest.raises(ValidationError):
        Turn.model_validate(value)


def test_api_streams_tools_and_keeps_audit_in_demo_namespace(tmp_path, monkeypatch):
    audit = []
    monkeypatch.setattr(api, "write_audit", audit.append)
    client = TestClient(api.app)
    health = client.get("/api/assistant/health").json()
    assert health["dispatch_enabled"] is False
    assert "api_key" not in health
    response = client.post("/api/assistant/turn", json=make_turn().model_dump(mode="json"))
    assert response.status_code == 200
    packets = [json.loads(line) for line in response.text.splitlines()]
    assert [p["type"] for p in packets] == ["start", "tool_start", "tool_result", "result"]
    assert audit[-1]["type"] == "turn_complete"
    assert client.post("/api/assistant/turn", json={}).status_code == 422
    assert client.post("/api/assistant/turn", content="x" * 200001).status_code == 413
    assert client.get("/api/assistant/health", headers={"Host": "unrelated.example"}).status_code == 400
    assert (
        client.post(
            "/api/assistant/turn", json={}, headers={"Origin": "https://unrelated.example"}
        ).status_code
        == 403
    )
