"""Coverage and landing-ledger contracts. Payloads are synthetic, not observations."""

import json
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from planner.real import plan_real_route
from services.assistant.landing_sites import EXAMPLE_LEDGER_ID, assess_landing
from services.assistant.osm_obstacles import (
    OSMDataUnavailable,
    fetch_obstacles,
    load_replay_snapshot,
)
from services.assistant.tests.test_osm_obstacles import sample_payload
from services.assistant.tools import ENV_TOOL_NAMES, LandingQuery, Toolset

pytestmark = pytest.mark.fast


def test_complete_fetch_records_evidence_and_does_not_allow_pass(tmp_path):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=sample_payload()))
    ) as client:
        result = fetch_obstacles((121, 31), (121.002, 31), client=client, cache_dir=tmp_path)
    metadata = result["metadata"]
    assert metadata["coverage_status"] == "complete"
    assert metadata["evidence_id"].startswith("obs-")
    assert metadata["crs"] == "EPSG:4326"
    assert metadata["pass_allowed"] is False
    assert metadata["expires_at"]
    assert metadata["stage_timings_s"]["overpass_request_s"] >= 0
    assert metadata["failed_chunks"] == []
    assert result["obstacles"]["coverage_status"] == "complete"
    again = fetch_obstacles((121, 31), (121.002, 31), client=client, cache_dir=tmp_path)
    assert again["metadata"]["cache_hit"] is True
    assert "穷尽" in again["metadata"]["coverage_note"]
    assert again["metadata"]["pass_allowed"] is False


def test_queried_empty_is_not_a_pass(tmp_path):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"elements": []}))
    ) as client:
        result = fetch_obstacles(
            (121, 31), (121.002, 31), client=client, cache_dir=tmp_path, allow_primary_api=False
        )
    assert result["metadata"]["coverage_status"] == "queried_empty"
    assert result["metadata"]["building_count"] == 0
    assert result["metadata"]["pass_allowed"] is False


def test_partial_primary_tiles_do_not_publish_an_empty_success(tmp_path):
    xml = b"""<osm version="0.6"><node id="1" lon="121" lat="31"/><node id="2" lon="121.001" lat="31"/>
      <node id="3" lon="121.001" lat="31.001"/><way id="5"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="1"/>
      <tag k="building" v="yes"/></way></osm>"""
    gets = {"n": 0}

    def upstream(request):
        if request.method == "POST":
            return httpx.Response(503)
        gets["n"] += 1
        if gets["n"] == 1:
            return httpx.Response(200, content=xml)
        return httpx.Response(504)

    with httpx.Client(transport=httpx.MockTransport(upstream)) as client:
        with pytest.raises(OSMDataUnavailable, match="部分覆盖") as caught:
            fetch_obstacles((121.0, 31.0), (121.08, 31.0), client=client, cache_dir=tmp_path, margin_m=100)
    assert caught.value.evidence["coverage_status"] == "partial"
    assert caught.value.evidence["failed_chunks"]
    failure = json.loads(next(tmp_path.rglob("failure.json")).read_text(encoding="utf-8"))
    assert failure["pass_allowed"] is False
    assert failure["coverage_status"] == "partial"
    assert not list(tmp_path.rglob("metadata.json"))


def test_expired_cache_stays_unavailable(tmp_path):
    from services.assistant.osm_obstacles import load_cached_scene

    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=sample_payload()))
    ) as client:
        result = fetch_obstacles((121, 31), (121.002, 31), client=client, cache_dir=tmp_path)
    scene_id = result["metadata"]["scene_id"]
    manifest = tmp_path / scene_id / "metadata.json"
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    metadata["fetched_at"] = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    metadata["source_fetched_at"] = metadata["fetched_at"]
    manifest.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(OSMDataUnavailable, match="过期") as caught:
        load_cached_scene(scene_id, tmp_path)
    assert caught.value.evidence["coverage_status"] == "expired"
    assert (tmp_path / scene_id / "obstacles.geojson").exists()


def test_deadline_does_not_turn_a_timeout_into_coverage(tmp_path):
    def slow(_request):
        time.sleep(0.2)
        return httpx.Response(504)

    with httpx.Client(transport=httpx.MockTransport(slow)) as client:
        with pytest.raises(OSMDataUnavailable, match="未回退到仿真") as caught:
            fetch_obstacles(
                (121, 31),
                (121.002, 31),
                client=client,
                cache_dir=tmp_path,
                budget_s=0.05,
                allow_primary_api=False,
            )
    assert caught.value.evidence["coverage_status"] == "timeout"
    assert caught.value.evidence["pass_allowed"] is False


def test_planner_refuses_partial_empty_collection():
    collection = {
        "type": "FeatureCollection",
        "features": [],
        "bbox": [121.0, 31.0, 121.2, 31.2],
        "coverage_status": "partial",
    }
    result = plan_real_route((121.05, 31.05), (121.08, 31.05), collection, budget_s=1)
    assert result["found"] is False
    assert "空列表" in result["reason"]


def test_replay_snapshot_rejects_a_pass_flag(tmp_path):
    path = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "fixtures"
        / "obstacle_replay_example_offline.json"
    )
    replay = load_replay_snapshot(path)
    assert replay["grade"] == "example_offline"
    assert replay["coverage_status"] == "partial"
    forged = dict(replay)
    forged["pass_allowed"] = True
    target = tmp_path / "forged.json"
    target.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(OSMDataUnavailable, match="不能当作覆盖通过"):
        load_replay_snapshot(target)


def test_landing_without_ledger_is_unverified():
    result = assess_landing((121.3, 31.2), (121.31, 31.2))
    assert result["status"] == "unavailable"
    assert result["verdict"] is None
    assert result["operationally_approved"] is False
    assert result["dispatch_enabled"] is False
    assert "responsible_party" in result["required_fields"]
    assert "不能据此判断不能飞" in result["reason"]


def test_example_ledger_never_becomes_operational():
    result = assess_landing((0.0, 0.0), (0.02, 0.0), EXAMPLE_LEDGER_ID)
    assert result["grade"] == "example_offline"
    assert "offline" in result["labels"] and "example" in result["labels"]
    assert result["verdict"] is None
    assert result["operationally_approved"] is False
    assert result["pass_allowed"] is False
    incomplete = next(site for site in result["sites"] if site["site_id"] == "example-desk-b")
    assert "authorization_evidence" in incomplete["missing"]
    assert incomplete["conflicts"]
    assert incomplete["accepted"] is False
    assert result["clues"][0]["kind"] == "osm_highway"
    tool = Toolset.check_landing_sites(
        None, LandingQuery(origin=(0.0, 0.0), destination=(0.02, 0.0), ledger_id=EXAMPLE_LEDGER_ID)
    )
    assert tool["operationally_approved"] is False


def test_environment_tools_remain_registered():
    assert ENV_TOOL_NAMES == {
        "assess_route_environment",
        "explain_verdict",
        "list_environment_gaps",
        "compare_departure_times",
        "check_landing_sites",
        "audit_route_provenance",
        "inspect_mission_plan",
    }
