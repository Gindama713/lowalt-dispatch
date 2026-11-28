"""National FlySafe overlay stays off the planning snapshot."""

from services.assistant.flysafe import FLYSAFE_SOURCE, MAX_ZONES
from services.assistant.flysafe_national import (
    CHINA_DISPLAY_ENVELOPE,
    NATIONAL_RED,
    china_display_tiles,
    refresh_national_overlay,
)


def _feature(area: int, lng: float, lat: float, category: str = "warning") -> dict:
    return {
        "type": "Feature",
        "id": f"{area}-1",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [lng, lat],
                    [lng + 0.01, lat],
                    [lng + 0.01, lat + 0.01],
                    [lng, lat + 0.01],
                    [lng, lat],
                ]
            ],
        },
        "properties": {
            "area_id": area,
            "part_index": 1,
            "category": category,
            "name": f"zone-{area}",
        },
    }


def _collection(*features: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


def test_china_envelope_does_not_cross_the_antimeridian():
    west, south, east, north = CHINA_DISPLAY_ENVELOPE
    assert -180 < west < east < 180
    assert -90 < south < north < 90
    tiles = china_display_tiles()
    assert tiles
    assert tiles[0][0] == west and tiles[0][1] == south
    assert tiles[-1][2] == east and tiles[-1][3] == north


def test_national_overlay_keeps_more_than_planning_limit_and_one_red(tmp_path):
    tiles = china_display_tiles()

    def fetcher(bbox, *, drone):
        assert drone == "dji-mini-3"
        index = tiles.index(tuple(bbox))
        if index == 0:
            features = [
                _feature(i, 121.4 + i * 0.02, 31.2, category)
                for i, category in enumerate(
                    ["restricted", "warning", "enhanced_warning", "altitude"],
                    start=1,
                )
            ]
            features.extend(_feature(n, 100 + n * 0.01, 30) for n in range(5, MAX_ZONES + 8))
            features.append(features[0])
            return _collection(*features)
        return _collection()

    result = refresh_national_overlay(fetcher=fetcher, cache_path=tmp_path / "china.json", force=True)
    assert result["zone_count"] > MAX_ZONES
    assert result["status"] == "ready"
    assert result["incomplete"] is False
    assert result["dispatch_enabled"] is False
    assert result["operationally_approved"] is False
    assert "snapshot" not in result
    colors = {feature["properties"]["display_color"] for feature in result["features"]["features"]}
    categories = {feature["properties"]["category"] for feature in result["features"]["features"]}
    assert colors == {NATIONAL_RED}
    assert {"warning", "enhanced_warning", "altitude", "restricted"} <= categories
    assert result["reference_label"] == FLYSAFE_SOURCE
    assert "不是法定空域" in result["note"]
    assert "不是飞行批准" in result["note"]


def test_partial_tile_is_incomplete_and_does_not_invent_geometry(tmp_path):
    tiles = china_display_tiles()
    failed = tiles[1]

    def fetcher(bbox, *, drone):
        if tuple(bbox) == failed:
            raise RuntimeError("tile down")
        if tuple(bbox) == tiles[0]:
            return _collection(_feature(9, 120.1, 30.2, "warning"))
        return _collection()

    result = refresh_national_overlay(fetcher=fetcher, cache_path=tmp_path / "china.json", force=True)
    assert result["status"] == "incomplete"
    assert result["incomplete"] is True
    assert result["zone_count"] == 1
    assert result["failed_tile_count"] == 1
    assert "不完整" in result["note"]
    assert result["features"]["features"][0]["id"] == "9-1"
    saved = (tmp_path / "china.json").read_text(encoding="utf-8")
    assert "120.1" in saved
    assert "tile down" in saved


def test_total_failure_keeps_the_previous_overlay(tmp_path):
    path = tmp_path / "china.json"
    tiles = china_display_tiles()

    def ok(bbox, *, drone):
        if tuple(bbox) == tiles[0]:
            return _collection(_feature(3, 116.4, 39.9, "restricted"))
        return _collection()

    first = refresh_national_overlay(fetcher=ok, cache_path=path, force=True)
    assert first["zone_count"] == 1

    def boom(bbox, *, drone):
        raise TimeoutError("upstream")

    second = refresh_national_overlay(fetcher=boom, cache_path=path, force=True)
    assert second["retained_prior"] is True
    assert second["zone_count"] == 1
    assert second["features"]["features"][0]["id"] == "3-1"
    assert "仍显示上次" in second["note"]
    assert "未编造" in (second["failure_reason"] or "")


def test_live_disabled_does_not_call_the_network(monkeypatch, tmp_path):
    from services.assistant import flysafe, flysafe_national

    monkeypatch.setattr(flysafe, "flysafe_live_enabled", lambda: False)

    def explode(*args, **kwargs):
        raise AssertionError("live national fetch must not run")

    monkeypatch.setattr(flysafe_national, "live_fetch_national_tiles", explode)
    result = refresh_national_overlay(cache_path=tmp_path / "china.json")
    assert result["status"] == "disabled"
    assert result["zone_count"] == 0
    assert result["features"]["features"] == []
    assert "未编造" in (result["failure_reason"] or "")
