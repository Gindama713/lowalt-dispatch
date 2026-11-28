"""Regressions found during the Agent review, including adversarial model replies."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest

from services.assistant import evidence, knowledge, rag, tools
from services.assistant.engine import Engine, ModelUnavailable, Settings, allowed_tools
from services.assistant.intake import IntakeStore
from services.assistant.telemetry import LiveTelemetry
from services.assistant.tests.test_assistant import FakeModel, make_turn, tool_call


def test_model_cannot_invent_user_confirmation(tmp_path, monkeypatch):
    store = IntakeStore(tmp_path)
    monkeypatch.setattr(tools, "intake_store", store)
    monkeypatch.setattr(
        evidence,
        "resolve_place",
        lambda name, **_: {
            "status": "ok",
            "name": name,
            "point": [115.8, 28.7],
            "crs": "EPSG:4326",
            "source": "test",
            "is_simulated": False,
        },
    )
    args = {
        "text": "确认建单：",
        "origin": "A",
        "destination": "B",
        "scheduled_for": "2028-01-20T15:00:00+08:00",
        "schedule_confirmed": True,
        "places_confirmed": True,
        "payload_kg": 3,
        "priority": "P1",
    }
    model = FakeModel([tool_call("create_task_intake", args)])
    result = Engine(Settings(provider="maas"), model).run(
        make_turn("创建任务，先让我确认地点，暂时不要建单"), lambda _: None
    )
    assert result["clarification"] is not None
    assert store.list() == []


def test_hidden_tool_is_rejected_at_execution(monkeypatch):
    lookup = Mock()
    monkeypatch.setattr(evidence, "resolve_place", lookup)
    model = FakeModel(
        [tool_call("resolve_real_place", {"name": "A"}), {"role": "assistant", "content": "该工具不可用。"}]
    )
    result = Engine(Settings(provider="maas"), model).run(make_turn("ACK 是什么意思"), lambda _: None)
    lookup.assert_not_called()
    assert result["traces"][0]["status"] == "error"


def test_mutation_and_preview_cache_follow_draft_version():
    ts = tools.Toolset(make_turn())
    for weight in (1, 2, 1):
        result = ts.execute("update_task_draft", {"payload_kg": weight})
        assert result["draft"]["payload_kg"] == ts.draft.payload_kg == weight


def test_cached_preview_remains_the_current_result_after_reverting_draft(monkeypatch):
    ts = tools.Toolset(make_turn())
    monkeypatch.setattr(ts, "plan_task_preview", lambda _: {"draft_digest": tools.draft_digest(ts.draft)})
    ts.execute("update_task_draft", {"payload_kg": 1})
    first = ts.execute("plan_task_preview", {})
    ts.execute("update_task_draft", {"payload_kg": 2})
    ts.execute("update_task_draft", {"payload_kg": 1})
    result = ts.execute("plan_task_preview", {})
    assert result["draft_digest"] == first["draft_digest"]
    assert ts.results["plan_task_preview"]["draft_digest"] == first["draft_digest"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("明天下午3点", "2026-11-20T15:00:00+08:00"),
        ("2028年1月20日14:30", "2028-01-20T14:30:00+08:00"),
        ("11月20日上午10点40分", "2026-11-20T10:40:00+08:00"),
        ("明天00:00", "2026-11-20T00:00:00+08:00"),
    ],
)
def test_explicit_time_is_preserved(text, expected):
    now = datetime(2026, 11, 19, 14, tzinfo=evidence.LOCAL_TZ)
    assert evidence.parse_schedule(text, now=now)[0] == expected


def test_tool_budget_returns_collected_evidence():
    reply = tool_call("get_flight_status", {})
    reply["tool_calls"] = [reply["tool_calls"][0] | {"id": str(i)} for i in range(3)]
    result = Engine(Settings(provider="maas"), FakeModel([reply] * 3)).run(make_turn(), lambda _: None)
    assert result["traces"]
    assert "83.4" in result["text"]
    assert len(result["traces"]) <= 8


def test_keyword_hits_do_not_require_vector_service(monkeypatch):
    monkeypatch.setenv("AERIS_RAG", "auto")
    vector = Mock(side_effect=RuntimeError("offline"))
    monkeypatch.setattr(rag, "search", vector)
    assert knowledge.search("ACK accepted true 执行完成")
    vector.assert_not_called()


def test_keyword_index_tracks_edits_and_new_documents(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "ROOT", tmp_path)
    monkeypatch.setattr(knowledge, "DOCUMENTS", ("guide.md",))
    monkeypatch.setattr(knowledge, "KNOWLEDGE_DIR", tmp_path / "knowledge")
    monkeypatch.setenv("AERIS_RAG", "keyword")
    guide = tmp_path / "guide.md"
    guide.write_text("# ACK\nACK accepted true old evidence", encoding="utf-8")
    old = knowledge.search("ACK accepted true")[0]
    guide.write_text("# ACK\n\nACK accepted true current evidence", encoding="utf-8")
    current = knowledge.search("ACK accepted true")[0]
    assert current["revision"] != old["revision"]
    assert current["start_line"] == 3
    assert "current evidence" in current["text"]
    knowledge.KNOWLEDGE_DIR.mkdir()
    (knowledge.KNOWLEDGE_DIR / "new.md").write_text("# 新文档\n备用场点核实台账", encoding="utf-8")
    assert knowledge.search("备用场点核实台账")[0]["path"] == "knowledge/new.md"


def test_long_code_chunks_keep_exact_source_lines():
    text = "# 示例\n```python\n" + "value = 12345\n" * 200 + "```\n"
    chunks = list(knowledge._split("example.md", text.encode()))
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= knowledge.EXCERPT_LIMIT
        assert chunk.text == "\n".join(text.splitlines()[chunk.start_line - 1 : chunk.end_line])


def test_vector_handle_refreshes_when_corpus_changes(monkeypatch):
    monkeypatch.setattr(rag, "_collection", None)
    monkeypatch.setattr(rag, "_collection_fingerprint", None)
    fingerprint = ["original"]
    monkeypatch.setattr(rag, "_fingerprint", lambda: fingerprint[0])
    build = Mock(side_effect=[object(), object()])
    monkeypatch.setattr(rag, "_build", build)
    first = rag._ensure()
    assert rag._ensure() is first
    fingerprint[0] = "edited"
    assert rag._ensure() is not first
    assert build.call_count == 2


def confirmed_turn():
    return make_turn(
        "确认创建任务工单",
        confirmation={
            "confirmation_id": str(uuid4()),
            "text": "确认创建任务工单",
            "origin": "A",
            "destination": "B",
            "origin_point": [121.3, 31.2],
            "destination_point": [121.5, 31.3],
            "scheduled_for": "2028-01-20T15:00:00+08:00",
            "payload_kg": 0,
            "priority": "P1",
        },
    )


def test_confirmed_operation_is_idempotent_even_with_concurrent_retries(tmp_path, monkeypatch):
    store = IntakeStore(tmp_path)
    monkeypatch.setattr(tools, "intake_store", store)
    monkeypatch.setattr(
        evidence, "fetch_weather_forecast", lambda *a, **k: evidence.unavailable_weather("test")
    )
    model = Mock(side_effect=AssertionError("Explicit confirmation must not ask a model to rewrite fields"))
    engine = Engine(Settings(provider="maas"), model)
    turn = confirmed_turn()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: engine.run(turn, lambda _: None, actor_id="user-1"), range(3)))
    ids = {r["traces"][0]["result"]["intake_id"] for r in results}
    assert len(ids) == len(store.list()) == 1
    saved = store.list()[0]
    assert saved["payload_kg"] == 0
    assert saved["scheduled_for"] == "2028-01-20T15:00:00+08:00"
    model.complete.assert_not_called()
    changed = turn.model_copy(update={"confirmation": turn.confirmation.model_copy(update={"payload_kg": 8})})
    result = engine.run(changed, lambda _: None, actor_id="user-1")
    assert result["traces"][0]["status"] == "error"
    assert store.list()[0]["payload_kg"] == 0


def test_weather_from_another_task_is_not_reused(tmp_path, monkeypatch):
    store = IntakeStore(tmp_path)
    monkeypatch.setattr(tools, "intake_store", store)
    fetch = Mock(return_value=evidence.unavailable_weather("test"))
    monkeypatch.setattr(evidence, "fetch_weather_forecast", fetch)
    turn = confirmed_turn()
    ts = tools.Toolset(turn)
    ts.results["get_weather_forecast"] = {
        "status": "ok",
        "requested_point": [0, 0],
        "valid_for": "2028-01-19T15:00:00+08:00",
        "values": {"wind_speed_10m": 77},
    }
    ts.execute("create_task_intake", turn.confirmation.as_input(turn.text).model_dump())
    fetch.assert_called_once_with(31.2, 121.3, "2028-01-20T15:00:00+08:00")
    assert store.list()[0]["weather"]["status"] == "unavailable"


def test_cancellation_during_weather_lookup_prevents_late_intake_write(tmp_path, monkeypatch):
    store = IntakeStore(tmp_path)
    monkeypatch.setattr(tools, "intake_store", store)
    cancelled = False

    def weather(*args):
        nonlocal cancelled
        cancelled = True
        return evidence.unavailable_weather("test")

    monkeypatch.setattr(evidence, "fetch_weather_forecast", weather)
    Engine(Settings()).run(confirmed_turn(), lambda _: None, cancelled=lambda: cancelled)
    assert store.list() == []


def test_live_status_prefers_server_telemetry_to_browser_values():
    frame = LiveTelemetry(
        source="test:m4", is_simulated=True, captured_at=datetime.now(evidence.UTC), battery=21
    )
    turn = make_turn(
        "当前电量",
        context={
            "sampled_at": frame.captured_at.isoformat(),
            "progress": 0,
            "telemetry_mode": "live",
            "telemetry": None,
            "live_telemetry": frame.model_copy(update={"battery": 99}).model_dump(mode="json"),
        },
    )
    result = Engine(Settings()).run(turn, lambda _: None, read_live_telemetry=lambda: frame)
    assert result["traces"][0]["result"]["telemetry"]["battery"] == 21
    assert result["traces"][0]["result"]["evidence_origin"] == "server_file"


def test_short_followup_keeps_task_tools_and_document_question_removes_them():
    history = [{"role": "user", "content": "创建任务，从A配送到B"}]
    assert "create_task_intake" in allowed_tools(make_turn("P1", history=history))
    assert "create_task_intake" not in allowed_tools(make_turn("ACK 是什么意思", history=history))


def test_chart_values_come_from_the_tool_not_model_text(monkeypatch):
    monkeypatch.setattr(
        tools.Toolset,
        "get_intake_overview",
        lambda *_: {
            "count": 3,
            "status_counts": [{"label": "已生成", "value": 3}],
        },
    )
    model = FakeModel(
        [
            tool_call("get_intake_overview", {}),
            {
                "role": "assistant",
                "content": '```chart\n{"type":"pie","data":[{"label":"已生成","value":999}]}\n```',
            },
        ]
    )
    result = Engine(Settings(provider="maas"), model).run(make_turn("工单状态画成饼图"), lambda _: None)
    spec = json.loads(result["text"].split("```chart\n")[1].split("\n```")[0])
    assert spec["data"] == [{"label": "已生成", "value": 3}]


def test_confirmed_intake_roundtrip_through_authenticated_stream(client, tmp_path, monkeypatch):
    from services.assistant import app as api

    store = IntakeStore(tmp_path / "intakes")
    monkeypatch.setattr(tools, "intake_store", store)
    monkeypatch.setattr(api, "intake_store", store)
    monkeypatch.setattr(
        evidence, "fetch_weather_forecast", lambda *a, **k: evidence.unavailable_weather("test")
    )
    body = confirmed_turn().model_dump(mode="json")

    def submit():
        response = client.post("/api/assistant/turn", json=body)
        assert response.status_code == 200
        packets = [json.loads(line) for line in response.text.splitlines()]
        return next(p["result"] for p in packets if p["type"] == "result")

    first, replay = submit(), submit()
    assert first["traces"][0]["result"]["intake_id"] == replay["traces"][0]["result"]["intake_id"]
    items = client.get("/api/assistant/intakes").json()["items"]
    assert len(items) == 1
    assert items[0]["origin"]["point"] == [121.3, 31.2]


def test_model_outage_after_tool_preserves_evidence():
    client = Mock()
    client.complete.side_effect = [tool_call("get_flight_status", {}), ModelUnavailable("offline")]
    result = Engine(Settings(provider="maas"), client).run(make_turn(), lambda _: None)
    assert "83.4" in result["text"]
    assert "模型服务中断" in result["text"]
