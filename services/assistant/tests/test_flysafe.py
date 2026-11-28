"""DJI FlySafe adapter tests. The live client is never called."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from planner.georef import enu_to_wgs84
from services.assistant import flysafe, osm_obstacles, route_weather
from services.assistant.airspace_snapshot import (
    ConstraintSnapshot,
    check_route_against_snapshot,
)
from services.assistant.navigation import CandidateInput, real_candidate_routes
from services.assistant.tests.test_airspace_constraints import ANCHOR, geo

STAMP = "2026-11-27T06:00:00+00:00"


def _ring(enu_ring: list[tuple[float, float]]) -> list[list[float]]:
    coords = [geo(x, y) for x, y in enu_ring]
    if coords[0] != coords[-1]:
        coords.append(list(coords[0]))
    return coords


def flysafe_feature(
    area_id: int,
    ring: list[list[float]],
    *,
    category: str = "restricted",
    name: str = "厂商围栏样例",
    part_index: int = 1,
    circle: bool = False,
    radius_m: float | None = None,
) -> dict:
    properties = {
        "name": name,
        "area_id": area_id,
        "part_index": part_index,
        "category": category,
        "level": 2,
        "color": "#DE4329",
        "height_m": 0,
        "effective_from": None,
        "effective_until": None,
        "area_type": 0,
        "country": "CN",
        "crs_verified": False,
    }
    if circle:
        properties["circle_polygon_approximation"] = True
        properties["radius_m"] = radius_m
        properties["center"] = ring[0]
    return {
        "type": "Feature",
        "id": f"{area_id}-{part_index}",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": properties,
    }


def flysafe_collection(*features: dict) -> dict:
    return {
        "type": "FeatureCollection",
        "dji_source": {
            "drone": "dji-mini-3",
            "queried_at_utc": STAMP,
            "requested_bbox": [115.8, 28.68, 115.9, 28.74],
            "assumed_crs": "WGS-84",
            "crs_verified": False,
            "tiles_queried": 1,
            "usage": "DJI GEO device geofence reference",
        },
        "features": list(features),
    }


@pytest.fixture
def synthetic_osm(monkeypatch):
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
            "fetched_at": STAMP,
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
    return data


def test_mocked_zones_convert_to_manufacturer_snapshot():
    block = _ring([(900, -250), (1100, -250), (1100, 250), (900, 250), (900, -250)])
    circle = _ring([(400, 400), (460, 400), (460, 460), (400, 460), (400, 400)])
    warning = _ring([(3000, 3000), (3100, 3000), (3100, 3100), (3000, 3100), (3000, 3000)])
    snap = flysafe.snapshot_from_flysafe_collection(
        flysafe_collection(
            flysafe_feature(11, block, name="中段禁飞"),
            flysafe_feature(12, circle, name="圆形禁飞", circle=True, radius_m=80),
            flysafe_feature(13, warning, category="warning", name="警示"),
        ),
        drone="dji-mini-3",
    )
    assert snap.source_status == "manufacturer_reference"
    assert snap.crs == "EPSG:4326"
    assert snap.coordinate_system == "WGS84"
    assert snap.is_simulated is False
    assert snap.total_zone_count == 3
    assert snap.enforced_zone_ids == ["flysafe-11-1", "flysafe-12-1"]
    assert all(zone.source == flysafe.FLYSAFE_SOURCE for zone in snap.zones)
    assert all(zone.source_kind == "manufacturer" for zone in snap.zones)
    assert all(zone.is_simulated is False for zone in snap.zones)
    assert "法定空域" in snap.zones[0].description
    assert snap.zones[1].geometry["type"] == "Polygon"
    assert "圆形围栏" in snap.zones[1].description
    assert snap.zones[2].kind == "warning"
    assert snap.zones[2].participates_in_avoidance is False
    assert snap.zones[0].max_height_m is None


def test_route_crossing_flysafe_zone_is_conflict_and_not_clearance():
    block = _ring([(900, -250), (1100, -250), (1100, 250), (900, 250), (900, -250)])
    snap = flysafe.snapshot_from_flysafe_collection(
        flysafe_collection(flysafe_feature(21, block)),
        drone="dji-mini-3",
    )
    check = check_route_against_snapshot([geo(0, 0), geo(2000, 0)], snap)
    assert check["status"] == "conflict"
    assert check["passed_known_snapshot"] is False
    assert check["operationally_approved"] is False
    assert check["conflicting_zone_ids"] == ["flysafe-21-1"]
    assert check["conflicts"][0]["conflict_type"] == "segment_crosses"
    assert "大疆 FlySafe 厂商地理围栏参考" in check["gaps"][0]
    assert "获准飞行" not in check["verdict_label"] or "不代表" in check["verdict_label"]


def test_replan_detours_around_mocked_flysafe_zone(synthetic_osm, monkeypatch):
    block = _ring([(900, -250), (1100, -250), (1100, 250), (900, 250), (900, -250)])
    collection = flysafe_collection(flysafe_feature(31, block, name="航路中段"))

    def fetcher(bbox, *, drone):
        assert drone == "dji-mini-3"
        assert bbox[0] < bbox[2] and bbox[1] < bbox[3]
        return collection

    monkeypatch.setattr(flysafe, "flysafe_live_enabled", lambda: True)
    monkeypatch.setattr(flysafe, "live_fetch_feature_collection", fetcher)
    start, goal = geo(0, 0), geo(2000, 0)
    straight = real_candidate_routes(
        CandidateInput(
            frame="WGS84",
            origin={"lng": start[0], "lat": start[1]},
            destination={"lng": goal[0], "lat": goal[1]},
            include_flysafe=False,
        )
    )
    assert straight["airspace_check"]["status"] == "snapshot_not_loaded"
    detoured = real_candidate_routes(
        CandidateInput(
            frame="WGS84",
            origin={"lng": start[0], "lat": start[1]},
            destination={"lng": goal[0], "lat": goal[1]},
            include_flysafe=True,
            previous_waypoints=[[p["lng"], p["lat"]] for p in straight["route"]["waypoints"]],
        )
    )
    assert detoured["status"] == "ok"
    assert detoured["constraint_snapshot"]["source_status"] == "manufacturer_reference"
    assert detoured["airspace_check"]["status"] == "passed_known_snapshot"
    assert detoured["airspace_check"]["passed_known_snapshot"] is True
    assert "通过本次已知区域检查" in detoured["airspace_check"]["verdict_label"]
    assert "大疆 FlySafe 厂商地理围栏参考" in detoured["airspace_check"]["verdict_label"]
    assert "获准飞行" in detoured["airspace_check"]["verdict_label"]
    assert detoured["operationally_approved"] is False
    assert detoured["dispatch_enabled"] is False
    assert detoured["route"]["length_m"] > straight["route"]["length_m"] + 40
    assert len(detoured["route"]["waypoints"]) >= 3
    assert detoured["airspace"]["reference_label"] == flysafe.FLYSAFE_SOURCE
    # Planning uses the snapshot, not a map-layer visibility list.
    assert detoured["constraint_snapshot"]["enforced_zone_ids"] == ["flysafe-31-1"]
    assert synthetic_osm["metadata"]["scene_id"]


def test_start_inside_flysafe_zone_is_rejected_without_moving(synthetic_osm, monkeypatch):
    cover = _ring([(-80, -80), (80, -80), (80, 80), (-80, 80), (-80, -80)])
    monkeypatch.setattr(flysafe, "flysafe_live_enabled", lambda: True)
    monkeypatch.setattr(
        flysafe,
        "live_fetch_feature_collection",
        lambda bbox, *, drone: flysafe_collection(flysafe_feature(41, cover, name="起点围栏")),
    )
    start, goal = geo(0, 0), geo(2000, 0)
    result = real_candidate_routes(
        CandidateInput(
            frame="WGS84",
            origin={"lng": start[0], "lat": start[1]},
            destination={"lng": goal[0], "lat": goal[1]},
            include_flysafe=True,
        )
    )
    assert result["status"] == "no_route"
    assert result["route"] is None
    assert "起点位于限制区" in result["alternatives"][0]["reason"]
    assert "未移动端点" in result["alternatives"][0]["reason"]
    assert result["airspace_check"]["status"] == "conflict"
    assert result["airspace_check"]["passed_known_snapshot"] is False
    assert synthetic_osm["obstacles"]["features"] == []


def test_fetch_failure_and_empty_result_are_unavailable_without_geometry():
    def fail(bbox, *, drone):
        raise TimeoutError("upstream down")

    failed = flysafe.refresh_planning_snapshot(geo(0, 0), geo(2000, 0), fetcher=fail)
    assert failed is not None
    assert failed.source_status == "unavailable"
    assert failed.zones == []
    assert failed.total_zone_count == 0
    assert "未编造围栏" in failed.failure_reason
    failed_check = check_route_against_snapshot([geo(0, 0), geo(2000, 0)], failed)
    assert failed_check["status"] == "unavailable"
    assert failed_check["passed_known_snapshot"] is None
    assert failed_check["operationally_approved"] is False
    assert "通过本次已知区域检查" not in failed_check["verdict_label"]
    assert "不是放行" in failed_check["verdict_label"]

    empty = flysafe.snapshot_from_flysafe_collection(
        flysafe_collection(),
        drone="dji-mini-3",
    )
    assert empty.source_status == "unavailable"
    assert empty.zones == []
    assert empty.source_status != "known_empty"
    empty_check = check_route_against_snapshot([geo(0, 0), geo(2000, 0)], empty)
    assert empty_check["passed_known_snapshot"] is None
    assert "0 个区域" in empty.failure_reason


def test_failed_refresh_keeps_prior_flysafe_zones():
    block = _ring([(900, -250), (1100, -250), (1100, 250), (900, 250), (900, -250)])
    loaded = flysafe.snapshot_from_flysafe_collection(
        flysafe_collection(flysafe_feature(11, block, name="南昌市藤王阁景区", category="enhanced_warning")),
        drone="dji-mini-3",
    )
    manual = loaded.zones[0].model_copy(
        update={
            "id": "manual-keep",
            "name": "手工附加",
            "kind": "restricted",
            "source": "手工导入对照",
            "source_kind": "team",
            "source_ref": "user:manual-keep",
        }
    )
    prior = ConstraintSnapshot.build(
        zones=[*loaded.zones, manual],
        source_status="manufacturer_reference",
        fetched_at=loaded.fetched_at,
    )

    def fail(bbox, *, drone):
        raise TimeoutError("upstream down")

    kept = flysafe.refresh_planning_snapshot(geo(0, 0), geo(2000, 0), prior=prior, fetcher=fail)
    assert kept is not None
    assert kept.source_status == "manufacturer_reference"
    assert kept.fetched_at == prior.fetched_at
    assert [zone.id for zone in kept.zones] == ["flysafe-11-1", "manual-keep"]
    assert kept.zones[0].geometry == prior.zones[0].geometry
    assert kept.zones[0].source == flysafe.FLYSAFE_SOURCE
    assert "本次刷新失败" in kept.failure_reason
    assert "TimeoutError" in kept.failure_reason
    assert "upstream down" in kept.failure_reason
    assert kept.total_zone_count == 2


def test_live_query_stays_off_in_unit_tests(monkeypatch):
    calls = {"n": 0}

    def explode(bbox, *, drone):
        calls["n"] += 1
        raise AssertionError("unit tests must not call the live FlySafe client")

    monkeypatch.setattr(flysafe, "live_fetch_feature_collection", explode)
    assert flysafe.refresh_planning_snapshot(geo(0, 0), geo(500, 0)) is None
    assert calls["n"] == 0


def test_dji_geo_circle_export_converts_without_network():
    dji_geo = pytest.importorskip("dji_geo")
    center = enu_to_wgs84(ANCHOR, (0, 0))
    zone = dji_geo.GeoZone(
        area_id=7,
        part_index=1,
        name="包装圆形",
        country="CN",
        area_type=0,
        data_source=0,
        category=dji_geo.ZoneCategory.RESTRICTED,
        level=2,
        color="#DE4329",
        height_m=30,
        geometry=dji_geo.CircleGeometry(center=(center[0], center[1]), radius_m=90),
    )
    result = dji_geo.AirspaceQueryResult(
        drone="dji-mini-3",
        request_bbox=dji_geo.BBox(
            west=center[0] - 0.02,
            south=center[1] - 0.02,
            east=center[0] + 0.02,
            north=center[1] + 0.02,
        ),
        queried_at=datetime(2026, 11, 27, tzinfo=UTC),
        zones=(zone,),
        raw_areas=(),
    )
    snap = flysafe.snapshot_from_flysafe_collection(
        result.to_geojson(circle_segments=12),
        drone="dji-mini-3",
    )
    assert snap.source_status == "manufacturer_reference"
    assert snap.zones[0].id == "flysafe-7-1"
    assert snap.zones[0].kind == "restricted"
    assert snap.zones[0].geometry["type"] == "Polygon"
    assert len(snap.zones[0].geometry["coordinates"][0]) >= 12
    assert snap.zones[0].max_height_m is None
    assert snap.enforced_zone_count == 1
