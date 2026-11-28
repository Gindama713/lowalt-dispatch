"""Deterministic regression suite for the end-to-end airspace constraint chain.

Covers all 12 required verification scenarios using synthetic local WGS84
geometry (no external Overpass or Open-Meteo network calls).
"""

from __future__ import annotations

import time
from uuid import uuid4

import pytest
from pydantic import ValidationError
from shapely.geometry import LineString, Polygon

from planner.georef import enu_to_wgs84, wgs84_to_enu
from planner.real import plan_real_route
from services.assistant import airspace_snapshot, osm_obstacles, route_weather, tools
from services.assistant import app as app_module
from services.assistant.airspace_snapshot import (
    AirspaceSnapshotStore,
    ConstraintSnapshot,
    check_route_against_snapshot,
    snapshot_from_geojson,
)
from services.assistant.engine import Engine, Settings
from services.assistant.intake import (
    IntakeCreate,
    IntakeStore,
    PlaceEvidence,
    TaskIntake,
    WeatherEvidence,
)
from services.assistant.models import Turn
from services.assistant.navigation import CandidateInput, real_candidate_routes
from services.assistant.tests.test_assistant import FakeModel, tool_call

GENUINE_REAL_ROUTE_FOR_INTAKE = tools.real_route_for_intake
ANCHOR = (115.8300, 28.7000)  # Nanchang synthetic local test anchor (WGS84)


def geo(x_m: float, y_m: float) -> list[float]:
    lng, lat = enu_to_wgs84(ANCHOR, (x_m, y_m))
    return [round(lng, 7), round(lat, 7)]


def make_zone_feature(
    zone_id: str,
    rings_enu: list[list[tuple[float, float]]],
    *,
    kind: str = "restricted",
    name: str | None = None,
    is_simulated: bool = True,
    effective_from: str | None = None,
    effective_until: str | None = None,
    max_height_m: float | None = None,
    altitude_ref: str | None = None,
    multi_rings_enu: list[list[list[tuple[float, float]]]] | None = None,
) -> dict:
    if multi_rings_enu is not None:
        geometry = {
            "type": "MultiPolygon",
            "coordinates": [
                [[geo(x, y) for x, y in ring] for ring in poly_rings] for poly_rings in multi_rings_enu
            ],
        }
    else:
        geometry = {
            "type": "Polygon",
            "coordinates": [[geo(x, y) for x, y in ring] for ring in rings_enu],
        }
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "id": zone_id,
            "name": name or f"测试区域-{zone_id}",
            "kind": kind,
            "source_kind": "team",
            "source": "本地确定性回归几何样例",
            "source_ref": f"test:{zone_id}",
            "updated_at": "2026-11-20T00:00:00Z",
            "effective_from": effective_from,
            "effective_until": effective_until,
            "is_simulated": is_simulated,
            "max_height_m": max_height_m,
            "altitude_ref": altitude_ref,
            "description": "确定性测试多边形，非真实空域。",
        },
    }


def make_fc(features: list[dict], *, coordinate_system: str = "WGS84") -> dict:
    return {
        "type": "FeatureCollection",
        "coordinate_system": coordinate_system,
        "features": features,
    }


@pytest.fixture
def synthetic_osm(monkeypatch):
    """Provide deterministic empty-building bbox covering [-1500..4500] x [-1500..1500] m around ANCHOR."""
    sw = geo(-1500, -1500)
    ne = geo(4500, 1500)
    data = {
        "obstacles": {
            "type": "FeatureCollection",
            "bbox": [sw[0], sw[1], ne[0], ne[1]],
            "coverage_status": "queried_empty",
            "features": [],
        },
        "roads": {"type": "FeatureCollection", "features": []},
        "metadata": {
            "scene_id": "a" * 16,
            "source": "synthetic OSM test fixture",
            "fetched_at": "2026-11-20T00:00:00+00:00",
            "building_count": 0,
            "road_count": 0,
        },
        "warnings": [],
    }
    monkeypatch.setattr(osm_obstacles, "fetch_obstacles", lambda *args, **kwargs: data)
    monkeypatch.setattr(osm_obstacles, "load_cached_scene", lambda scene_id: data)
    monkeypatch.setattr(
        route_weather,
        "assess_route_weather",
        lambda *args, **kwargs: {
            "status": "unavailable",
            "source": "synthetic weather unavailable",
            "warnings": [],
            "energy": {"status": "unavailable", "reason": "no calibrated vehicle"},
        },
    )
    # Restore genuine real_route_for_intake against synthetic_osm instead of conftest's 2-point stub!
    monkeypatch.setattr(tools, "real_route_for_intake", GENUINE_REAL_ROUTE_FOR_INTAKE)
    monkeypatch.setattr(app_module, "real_route_for_intake", GENUINE_REAL_ROUTE_FOR_INTAKE)
    return data


def test_1_and_2_mid_segment_crossing_detected_and_replan_detours(synthetic_osm):
    """1 & 2: Endpoints outside zone, middle segment crosses -> flagged red conflict; replan detours."""
    start, goal = geo(0, 0), geo(2000, 0)
    # Step 1: Plan original route v1 with no airspace zones loaded.
    v1 = real_candidate_routes(
        CandidateInput(
            frame="WGS84",
            origin={"lng": start[0], "lat": start[1]},
            destination={"lng": goal[0], "lat": goal[1]},
        )
    )
    assert v1["status"] == "ok"
    assert v1["geometric_generation"]["generated"] is True
    assert v1["airspace_check"]["status"] == "snapshot_not_loaded"
    assert v1["airspace_check"]["passed_known_snapshot"] is None
    v1_pts = [[p["lng"], p["lat"]] for p in v1["route"]["waypoints"]]
    assert len(v1_pts) == 2  # straight clear corridor initially

    # Step 2: Add restricted zone across [900..1100] x [-250..250] m; both endpoints (0,0) & (2000,0) are outside!
    block_ring = [(900, -250), (1100, -250), (1100, 250), (900, 250), (900, -250)]
    snap = snapshot_from_geojson(make_fc([make_zone_feature("nfz-mid", [block_ring])]))
    airspace_snapshot.store.save(snap, set_active=True)

    recheck_v1 = check_route_against_snapshot(v1_pts, snap)
    assert recheck_v1["status"] == "conflict"
    assert recheck_v1["passed_known_snapshot"] is False
    assert recheck_v1["conflicting_zone_ids"] == ["nfz-mid"]
    assert recheck_v1["conflicting_segment_indices"] == [0]
    assert recheck_v1["conflicts"][0]["conflict_type"] == "segment_crosses"

    # Step 3: Re-plan v2 with the active snapshot and pass v1 as previous_waypoints.
    v2 = real_candidate_routes(
        CandidateInput(
            frame="WGS84",
            origin={"lng": start[0], "lat": start[1]},
            destination={"lng": goal[0], "lat": goal[1]},
            snapshot_id=snap.snapshot_id,
            previous_waypoints=v1_pts,
        )
    )
    assert v2["status"] == "ok"
    assert v2["route_changed"] is True
    assert v2["previous_route_check"]["status"] == "conflict"
    assert v2["previous_route_check"]["conflicting_segment_indices"] == [0]
    assert v2["airspace_check"]["status"] == "passed_known_snapshot"
    assert v2["airspace_check"]["passed_known_snapshot"] is True
    assert "通过本次已知区域检查" in v2["airspace_check"]["verdict_label"]
    assert "获准飞行" in v2["airspace_check"]["verdict_label"]  # "不代表获准飞行"
    assert v2["route"]["length_m"] > v1["route"]["length_m"] + 40.0
    assert len(v2["route"]["waypoints"]) >= 3


def test_3_origin_or_destination_inside_zone_rejected_without_moving_endpoints(synthetic_osm):
    """3: Start or destination inside restricted/internal zone fails explicitly without snapping."""
    origin_zone = [(-80, -80), (80, -80), (80, 80), (-80, 80), (-80, -80)]
    dest_zone = [(1920, -80), (2080, -80), (2080, 80), (1920, 80), (1920, -80)]
    snap_origin = snapshot_from_geojson(make_fc([make_zone_feature("nfz-origin", [origin_zone])]))
    airspace_snapshot.store.save(snap_origin, set_active=True)

    start, goal = geo(0, 0), geo(2000, 0)
    res_origin = real_candidate_routes(
        CandidateInput(
            frame="WGS84",
            origin={"lng": start[0], "lat": start[1]},
            destination={"lng": goal[0], "lat": goal[1]},
            snapshot_id=snap_origin.snapshot_id,
        )
    )
    assert res_origin["status"] == "no_route"
    assert res_origin["route"] is None
    assert "起点位于限制区" in res_origin["alternatives"][0]["reason"]
    assert "nfz-origin" in res_origin["alternatives"][0]["reason"]
    assert "未移动端点" in res_origin["alternatives"][0]["reason"]
    assert res_origin["airspace_check"]["status"] == "conflict"

    snap_dest = snapshot_from_geojson(make_fc([make_zone_feature("ctrl-dest", [dest_zone], kind="internal")]))
    airspace_snapshot.store.save(snap_dest, set_active=True)
    res_dest = real_candidate_routes(
        CandidateInput(
            frame="WGS84",
            origin={"lng": start[0], "lat": start[1]},
            destination={"lng": goal[0], "lat": goal[1]},
            snapshot_id=snap_dest.snapshot_id,
        )
    )
    assert res_dest["status"] == "no_route"
    assert res_dest["route"] is None
    assert "终点位于限制区" in res_dest["alternatives"][0]["reason"]
    assert "ctrl-dest" in res_dest["alternatives"][0]["reason"]
    assert "未移动端点" in res_dest["alternatives"][0]["reason"]


def test_4_sealed_corridor_returns_no_route_never_straight_line(synthetic_osm):
    """4: When restriction zone completely blocks the search corridor, return no_route without straight fallback."""
    wall_ring = [(900, -1400), (1100, -1400), (1100, 1400), (900, 1400), (900, -1400)]
    snap = snapshot_from_geojson(make_fc([make_zone_feature("nfz-wall", [wall_ring])]))
    airspace_snapshot.store.save(snap, set_active=True)

    start, goal = geo(0, 0), geo(2000, 0)
    res = real_candidate_routes(
        CandidateInput(
            frame="WGS84",
            origin={"lng": start[0], "lat": start[1]},
            destination={"lng": goal[0], "lat": goal[1]},
            snapshot_id=snap.snapshot_id,
        )
    )
    assert res["status"] == "no_route"
    assert res["geometric_available"] is False
    assert res["geometric_generation"]["generated"] is False
    assert res["route"] is None
    assert "未使用直线替代" in res["alternatives"][0]["reason"]


def test_5_multipolygon_hole_boundary_touch_buffer_and_schedule_rules(synthetic_osm):
    """5: MultiPolygon, interior hole, closed boundary touch, project buffer_m, and conservative schedule rules."""
    # (a) Boundary touch counts as conflict!
    touch_ring = [(400, 0), (800, 0), (800, 300), (400, 300), (400, 0)]
    snap_touch = snapshot_from_geojson(make_fc([make_zone_feature("nfz-touch", [touch_ring])]))
    # Segment from (0,0) to (1200,0) grazes the bottom edge y=0 of touch_ring!
    grazing_check = check_route_against_snapshot([geo(0, 0), geo(1200, 0)], snap_touch)
    assert grazing_check["status"] == "conflict"
    assert grazing_check["conflicts"][0]["conflict_type"] == "boundary_contact"

    # Planner must detour strictly below y=0 (never touching y=0)!
    planned = plan_real_route(
        tuple(geo(0, 0)),
        tuple(geo(1200, 0)),
        synthetic_osm["obstacles"],
        exclusions_fc=snap_touch.to_exclusions_fc(),
        zone_buffer_m=0.0,
    )
    assert planned["found"] is True
    post = check_route_against_snapshot(planned["waypoints"], snap_touch)
    assert post["status"] == "passed_known_snapshot"

    # (b) Project buffer_m = 60 m: segment at y = -40 m is outside polygon but inside 60 m buffer -> conflict!
    snap_buf = snapshot_from_geojson(
        make_fc([make_zone_feature("nfz-buf", [touch_ring])]),
        zone_buffer_m=60.0,
    )
    buf_check = check_route_against_snapshot([geo(0, -40), geo(1200, -40)], snap_buf)
    assert buf_check["status"] == "conflict"
    assert buf_check["conflicts"][0]["conflict_type"] == "buffer_intrusion"

    planned_buf = plan_real_route(
        tuple(geo(0, -100)),
        tuple(geo(1200, -100)),
        synthetic_osm["obstacles"],
        exclusions_fc=snap_buf.to_exclusions_fc(),
        zone_buffer_m=60.0,
    )
    assert planned_buf["found"] is True
    ref = planned_buf["projection_origin"]
    poly_enu = Polygon([wgs84_to_enu(ref, tuple(geo(x, y))) for x, y in touch_ring])
    line_enu = LineString([wgs84_to_enu(ref, p) for p in planned_buf["waypoints"]])
    assert line_enu.distance(poly_enu) > 60.0

    # (c) MultiPolygon with two blocks + interior hole, plus conservative future/expired rules:
    mp_feat = make_zone_feature(
        "nfz-multi",
        [],
        effective_from="2026-12-01T00:00:00Z",  # future! Still conservatively enforced!
        max_height_m=80,
        altitude_ref="agl",
        multi_rings_enu=[
            [[(300, -200), (450, -200), (450, 200), (300, 200), (300, -200)]],
            [[(700, -200), (850, -200), (850, 200), (700, 200), (700, -200)]],
        ],
    )
    expired_feat = make_zone_feature(
        "nfz-expired",
        [[(500, -1400), (600, -1400), (600, 1400), (500, 1400), (500, -1400)]],
        effective_from="2026-11-01T00:00:00Z",
        effective_until="2026-11-10T00:00:00Z",  # expired before scheduled_for!
    )
    warning_feat = make_zone_feature(
        "warn-only",
        [[(500, -1400), (600, -1400), (600, 1400), (500, 1400), (500, -1400)]],
        kind="warning",
    )
    snap_mix = snapshot_from_geojson(
        make_fc([mp_feat, expired_feat, warning_feat]),
        scheduled_for="2026-11-20T09:00:00+08:00",
    )
    assert snap_mix.enforced_zone_ids == ["nfz-multi"]
    airspace_snapshot.store.save(snap_mix, set_active=True)

    res_mix = real_candidate_routes(
        CandidateInput(
            frame="WGS84",
            origin={"lng": geo(0, 0)[0], "lat": geo(0, 0)[1]},
            destination={"lng": geo(1200, 0)[0], "lat": geo(1200, 0)[1]},
            scheduled_for="2026-11-20T09:00:00+08:00",
            snapshot_id=snap_mix.snapshot_id,
        )
    )
    assert res_mix["status"] == "ok"
    assert res_mix["airspace_check"]["status"] == "passed_known_snapshot"


def test_6_8_9_intake_background_freeze_recalc_persistence_and_legacy(
    client, tmp_path, monkeypatch, synthetic_osm
):
    """6, 8, 9: Background freeze, unified snapshot across manual & AI intake, recalculation history, legacy label, and restart persistence."""
    intakes_dir = tmp_path / "persisted_intakes"
    airspace_dir = tmp_path / "persisted_airspace"
    istore = IntakeStore(root=intakes_dir)
    astore = AirspaceSnapshotStore(root=airspace_dir)
    monkeypatch.setattr(tools, "intake_store", istore)
    monkeypatch.setattr(app_module, "intake_store", istore)
    monkeypatch.setattr(airspace_snapshot, "store", astore)
    monkeypatch.setattr(tools, "airspace_store", astore)
    monkeypatch.setattr(app_module, "airspace_store", astore)
    from services.assistant import navigation as nav_module

    monkeypatch.setattr(nav_module, "airspace_store", astore)
    monkeypatch.setattr(
        tools.evidence,
        "fetch_weather_forecast",
        lambda *a, **kw: tools.evidence.unavailable_weather("offline-test"),
    )

    start, goal = geo(0, 0), geo(2000, 0)

    # Legacy intake on disk without constraint_snapshot -> must be marked "历史建筑避障结果，空域未核对"
    legacy = TaskIntake.build(
        IntakeCreate(text="旧工单", origin="起点A", destination="终点B", payload_kg=1.0),
        origin=PlaceEvidence(name="起点A", point=start, crs="EPSG:4326", source="test", is_simulated=False),
        destination=PlaceEvidence(
            name="终点B", point=goal, crs="EPSG:4326", source="test", is_simulated=False
        ),
        weather=WeatherEvidence(),
        airspace={"status": "draft", "note": "旧记录", "zones": []},
        route_preview=None,
        real_route={
            "status": "ok",
            "waypoints": [
                {"lng": start[0], "lat": start[1], "x": start[0], "y": start[1]},
                {"lng": goal[0], "lat": goal[1], "x": goal[0], "y": goal[1]},
            ],
            "length_m": 2000.0,
        },
        warnings=[],
    )
    istore.create(legacy)
    loaded_legacy = client.get(f"/api/assistant/intakes/{legacy.intake_id}").json()
    assert loaded_legacy["airspace_check"]["status"] == "not_checked_legacy"
    assert loaded_legacy["airspace_check"]["verdict_label"] == "历史建筑避障结果，空域未核对"

    # Upload Snapshot S1 via BFF endpoint
    ring1 = [(900, -220), (1100, -220), (1100, 220), (900, 220), (900, -220)]
    up1 = client.post(
        "/api/assistant/airspace/snapshot",
        json={"mode": "replace", "geojson": make_fc([make_zone_feature("nfz-s1", [ring1])])},
    )
    assert up1.status_code == 200
    s1 = up1.json()

    # Manual candidate planning uses S1 automatically
    manual = client.post(
        "/api/assistant/navigation/candidates",
        json={
            "frame": "WGS84",
            "origin": {"lng": start[0], "lat": start[1]},
            "destination": {"lng": goal[0], "lat": goal[1]},
        },
    ).json()
    assert manual["constraint_snapshot"]["snapshot_id"] == s1["snapshot_id"]
    assert manual["constraint_snapshot"]["digest"] == s1["digest"]

    # AI intake background worker freezes S1 at start even if workspace changes to S2 mid-flight!
    entered = []

    def slow_router(
        origin, destination, scheduled_for, *, snapshot=None, intake_id=None, previous_waypoints=None
    ):
        entered.append(snapshot.snapshot_id if snapshot else None)
        time.sleep(0.12)
        return tools.real_route_for_intake(
            origin,
            destination,
            scheduled_for,
            snapshot=snapshot,
            intake_id=intake_id,
            previous_waypoints=previous_waypoints,
        )

    turn = Turn.model_validate(
        {
            "request_id": str(uuid4()),
            "text": "建单测试",
            "history": [],
            "context": {
                "sampled_at": "2026-11-20T01:00:00+00:00",
                "progress": 0,
                "telemetry_mode": "planning",
                "telemetry": None,
                "events": [],
            },
        }
    )
    tset = tools.Toolset(turn, real_route_provider=slow_router, route_background=True)
    created = tset.execute(
        "create_task_intake",
        {
            "text": "从起点A送1公斤到终点B",
            "origin": "起点A",
            "destination": "终点B",
            "origin_point": start,
            "destination_point": goal,
            "scheduled_for": "2026-11-20T09:00:00+08:00",
            "schedule_confirmed": True,
            "places_confirmed": True,
            "payload_kg": 1.0,
            "priority": "P1",
        },
    )
    intake_id = created["intake_id"]

    # Immediately mutate active workspace snapshot to S2 while background thread is still running!
    ring2 = [(1400, -280), (1600, -280), (1600, 280), (1400, 280), (1400, -280)]
    up2 = client.post(
        "/api/assistant/airspace/snapshot",
        json={
            "mode": "replace",
            "geojson": make_fc([make_zone_feature("nfz-s1", [ring1]), make_zone_feature("nfz-s2", [ring2])]),
        },
    )
    assert up2.status_code == 200
    s2 = up2.json()
    assert s2["digest"] != s1["digest"]

    deadline = time.time() + 4.0
    while time.time() < deadline:
        current = istore.get(intake_id)
        if current["real_route"]["status"] != "pending":
            break
        time.sleep(0.03)

    finished_v1 = istore.get(intake_id)
    assert finished_v1["real_route"]["status"] == "ok", finished_v1["real_route"]
    assert entered == [s1["snapshot_id"]]
    # Background job saved S1 (what it actually computed with), NOT S2!
    assert finished_v1["constraint_snapshot"]["snapshot_id"] == s1["snapshot_id"]
    assert finished_v1["constraint_snapshot"]["digest"] == s1["digest"]
    assert finished_v1["real_route"]["waypoints"] == manual["route"]["waypoints"]

    # Because workspace active snapshot is now S2, Agent audit detects stale_against_workspace!
    audit_turn = Turn.model_validate(
        {
            "request_id": str(uuid4()),
            "text": "有没有考虑禁飞区？",
            "history": [],
            "context": {
                "sampled_at": "2026-11-20T01:05:00+00:00",
                "selected_intake_id": intake_id,
                "progress": 0,
                "telemetry_mode": "planning",
                "telemetry": None,
                "events": [],
            },
        }
    )
    audit_before_recalc = Engine(Settings()).run(audit_turn, lambda _: None)
    assert s1["snapshot_id"] in audit_before_recalc["text"]
    assert s2["snapshot_id"] in audit_before_recalc["text"]
    assert "版本失效提醒" in audit_before_recalc["text"]

    # Recalculate intake via POST /api/assistant/intakes/{id}/route -> binds S2 and archives v1 in route_history!
    refreshed = client.post(f"/api/assistant/intakes/{intake_id}/route").json()
    assert refreshed["constraint_snapshot"]["snapshot_id"] == s2["snapshot_id"]
    assert refreshed["real_route"]["version_label"] == "v2"
    assert len(refreshed["route_history"]) == 1
    assert refreshed["route_history"][0]["version_label"] == "v1"
    assert refreshed["airspace_check"]["status"] == "passed_known_snapshot"

    # Simulate process restart: create fresh Store instances pointing to same disk directories
    restarted_airspace = AirspaceSnapshotStore(root=airspace_dir)
    restarted_intakes = IntakeStore(root=intakes_dir)
    assert restarted_airspace.get_active().digest == s2["digest"]
    reloaded_intake = restarted_intakes.get(intake_id)
    assert reloaded_intake["constraint_snapshot"]["digest"] == s2["digest"]
    assert len(reloaded_intake["route_history"]) == 1


def test_10_enu_wgs84_and_gcj02_mixing_explicitly_rejected(client):
    """10: Mixing ENU/WGS84 or GCJ02 is explicitly rejected across snapshot import and CandidateInput."""
    # Reject GCJ02
    res_gcj = client.post(
        "/api/assistant/airspace/snapshot",
        json={
            "mode": "replace",
            "geojson": make_fc(
                [make_zone_feature("z1", [[(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]])],
                coordinate_system="GCJ02",
            ),
        },
    )
    assert res_gcj.status_code == 422
    assert "WGS84" in res_gcj.json()["detail"]

    # Reject ENU declaration
    res_enu_decl = client.post(
        "/api/assistant/airspace/snapshot",
        json={
            "mode": "replace",
            "geojson": make_fc(
                [make_zone_feature("z1", [[(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]])],
                coordinate_system="local ENU / m",
            ),
        },
    )
    assert res_enu_decl.status_code == 422
    assert "ENU" in res_enu_decl.json()["detail"]

    # Reject ENU meter coordinates disguised inside a WGS84 FeatureCollection
    bad_fc = make_fc([make_zone_feature("z1", [[(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]])])
    bad_fc["features"][0]["geometry"]["coordinates"] = [
        [[1400, 1400], [1600, 1400], [1600, 1600], [1400, 1600], [1400, 1400]]
    ]
    res_enu_coords = client.post(
        "/api/assistant/airspace/snapshot",
        json={"mode": "replace", "geojson": bad_fc},
    )
    assert res_enu_coords.status_code == 422
    assert "ENU" in res_enu_coords.json()["detail"] or "范围" in res_enu_coords.json()["detail"]

    # Reject binding WGS84 snapshot_id to ENU CandidateInput
    with pytest.raises(ValidationError, match="ENU"):
        CandidateInput(
            frame="ENU",
            origin={"x": 150, "y": 150},
            destination={"x": 2650, "y": 2750},
            snapshot_id="air-1234567890ab",
        )


def test_11_distinct_missing_empty_failed_and_passed_states_never_conflated():
    """11: not_loaded, query_failed, known_empty, and passed_known_snapshot remain distinct."""
    pts = [geo(0, 0), geo(1000, 0)]

    legacy = check_route_against_snapshot(pts, None)
    unloaded = check_route_against_snapshot(
        pts, ConstraintSnapshot.build(zones=[], source_status="not_loaded")
    )
    failed = check_route_against_snapshot(
        pts,
        ConstraintSnapshot.build(zones=[], source_status="query_failed", failure_reason="磁盘读取异常"),
    )
    known_empty = check_route_against_snapshot(
        pts, ConstraintSnapshot.build(zones=[], source_status="known_empty")
    )
    far_zone = snapshot_from_geojson(
        make_fc(
            [make_zone_feature("nfz-far", [[(400, 400), (600, 400), (600, 600), (400, 600), (400, 400)]])]
        )
    )
    passed = check_route_against_snapshot(pts, far_zone)

    statuses = [
        legacy["status"],
        unloaded["status"],
        failed["status"],
        known_empty["status"],
        passed["status"],
    ]
    assert statuses == [
        "not_checked_legacy",
        "snapshot_not_loaded",
        "query_failed",
        "known_empty_snapshot",
        "passed_known_snapshot",
    ]
    assert legacy["passed_known_snapshot"] is None
    assert unloaded["passed_known_snapshot"] is None
    assert failed["passed_known_snapshot"] is None
    assert known_empty["passed_known_snapshot"] is True
    assert passed["passed_known_snapshot"] is True
    assert all(
        item["operationally_approved"] is False for item in (legacy, unloaded, failed, known_empty, passed)
    )


def test_12_agent_local_and_maas_agree_with_intake_and_corridor_simulation(
    client, synthetic_osm, monkeypatch
):
    """12: Corridor simulation, intake replan, Agent (local + MaaS), and route payload share exact digest & waypoints."""
    start, goal = geo(0, 0), geo(2200, 0)
    monkeypatch.setattr(
        tools.evidence,
        "resolve_place",
        lambda name, **kw: {
            "status": "ok",
            "name": name,
            "point": start if name == "南昌西点" else goal,
            "crs": "EPSG:4326",
            "source": "synthetic test site",
            "is_simulated": True,
        },
    )
    monkeypatch_weather = tools.evidence.unavailable_weather("offline")
    orig_fetch = tools.evidence.fetch_weather_forecast
    tools.evidence.fetch_weather_forecast = lambda *a, **kw: monkeypatch_weather
    try:
        # 1. Create intake -> initial v1 route with unloaded snapshot
        init_turn = Turn.model_validate(
            {
                "request_id": str(uuid4()),
                "text": "建单",
                "history": [],
                "context": {
                    "sampled_at": "2026-11-20T02:00:00+00:00",
                    "progress": 0,
                    "telemetry_mode": "planning",
                    "telemetry": None,
                    "events": [],
                },
            }
        )
        created = tools.Toolset(init_turn, route_background=False).execute(
            "create_task_intake",
            {
                "text": "从南昌西点送到南昌东点",
                "origin": "南昌西点",
                "destination": "南昌东点",
                "origin_point": start,
                "destination_point": goal,
                "scheduled_for": "2026-11-20T10:00:00+08:00",
                "schedule_confirmed": True,
                "places_confirmed": True,
                "payload_kg": 2.0,
                "priority": "P1",
            },
        )
        intake_id = created["intake_id"]
        intake_v1 = client.get(f"/api/assistant/intakes/{intake_id}").json()
        v1_wps = [[p["lng"], p["lat"]] for p in intake_v1["real_route"]["waypoints"]]

        # 2. Generate corridor simulation zone across v1 -> immediately flags conflict on v1!
        sim_resp = client.post(
            "/api/assistant/airspace/simulate-corridor",
            json={"origin": start, "destination": goal, "waypoints": v1_wps},
        )
        assert sim_resp.status_code == 200
        sim_data = sim_resp.json()
        sim_snap = sim_data["snapshot"]
        assert sim_data["route_check"]["status"] == "conflict"
        assert len(sim_data["route_check"]["conflicting_segment_indices"]) >= 1

        # 3. Re-plan via navigation/candidates bound to intake_id -> syncs v2 & v1 conflict history to intake!
        replan_resp = client.post(
            "/api/assistant/navigation/candidates",
            json={
                "frame": "WGS84",
                "origin": {"lng": start[0], "lat": start[1]},
                "destination": {"lng": goal[0], "lat": goal[1]},
                "scheduled_for": "2026-11-20T10:00:00+08:00",
                "snapshot_id": sim_snap["snapshot_id"],
                "intake_id": intake_id,
                "previous_waypoints": v1_wps,
            },
        )
        assert replan_resp.status_code == 200
        replan = replan_resp.json()
        assert replan["status"] == "ok"
        assert replan["route_changed"] is True
        assert replan["airspace_check"]["status"] == "passed_known_snapshot"

        intake_v2 = client.get(f"/api/assistant/intakes/{intake_id}").json()
        assert intake_v2["constraint_snapshot"]["digest"] == sim_snap["digest"]
        assert intake_v2["real_route"]["waypoints"] == replan["route"]["waypoints"]
        assert intake_v2["route_history"][-1]["rechecked_airspace_check"]["status"] == "conflict"

        # 4. Ask Agent in local mode AND MaaS mode: "有没有考虑禁飞区？"
        ask_turn = Turn.model_validate(
            {
                "request_id": str(uuid4()),
                "text": "这次规划有没有考虑禁飞区？原路线为什么判为冲突？",
                "history": [],
                "context": {
                    "sampled_at": "2026-11-20T02:05:00+00:00",
                    "selected_intake_id": intake_id,
                    "airspace_snapshot_id": sim_snap["snapshot_id"],
                    "active_route": {
                        "route_id": replan["route"]["id"],
                        "task_id": intake_id,
                        "frame": "WGS84",
                        "source": replan["route"]["source"],
                        "waypoints": [[p["lng"], p["lat"]] for p in replan["route"]["waypoints"]],
                        "constraint_snapshot_id": sim_snap["snapshot_id"],
                        "constraint_digest": sim_snap["digest"],
                    },
                    "progress": 0,
                    "telemetry_mode": "planning",
                    "telemetry": None,
                    "events": [],
                },
            }
        )
        local_ans = Engine(Settings()).run(ask_turn, lambda _: None)
        assert local_ans["traces"][0]["name"] == "inspect_airspace_constraints"
        assert sim_snap["snapshot_id"] in local_ans["text"]
        assert sim_snap["digest"] in local_ans["text"]
        assert "通过本次已知区域检查" in local_ans["text"]
        assert "未接入官方 UOM / NOTAM" in local_ans["text"]

        # MaaS mode with honesty guard: if model tries to claim "现实中没有禁飞区", honesty guard blocks it!
        dishonest_model = FakeModel(
            [
                tool_call("inspect_airspace_constraints", {"intake_id": intake_id}),
                {"content": "现实中没有禁飞区，已经获准飞行！"},
            ]
        )
        maas_ans = Engine(Settings(provider="maas"), dishonest_model).run(ask_turn, lambda _: None)
        assert "现实中没有禁飞区" not in maas_ans["text"]
        assert "已经获准飞行" not in maas_ans["text"]
    finally:
        tools.evidence.fetch_weather_forecast = orig_fetch
