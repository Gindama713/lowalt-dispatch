"""Real, attributed OSM footprints and roads; never substitutes the ENU demo.

OSM is a volunteered map, not an obstacle survey. Missing heights stay unknown;
the planner must avoid the entire footprint rather than infer overflight safety.
Roads are context, not approved flight corridors. Cache manifests are written
last, so an interrupted download cannot become an apparently complete scene.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from shapely.geometry import MultiPoint, mapping, shape

from services.assistant.geocode import USER_AGENT

SOURCE = "OpenStreetMap / Overpass"
MAP_SOURCE = "OpenStreetMap / API 0.6 map"
MAP_API = "https://api.openstreetmap.org/api/0.6"
ATTRIBUTION = "© OpenStreetMap contributors; ODbL 1.0 https://www.openstreetmap.org/copyright"
ENDPOINTS = (
    # Measured 2026-11-17 from this network: the three canonical instances
    # returned 502 / read timeouts while the French mirror answered. Order is
    # operational, not a statement about which instance is "official".
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    # Regional extract (Switzerland): returns empty results outside its area.
    # Kept last so it can never mask "no data" for other regions.
    "https://overpass.osm.ch/api/interpreter",
)
CACHE_DIR = Path(__file__).resolve().parents[2] / "scenarios" / "real"
CACHE_TTL_HOURS = 24.0
WARNINGS = [
    "OSM 是志愿者地图，建筑/道路可能漏绘或过时，不等于实测障碍物全覆盖。",
    "所有建筑轮廓均保守避让；height_source=levels/estimate 不是实测高度，未知高度不补默认值。",
    "道路仅作地理参照，不表示允许沿路飞行；未接入地形、线缆、动态障碍物或官方空域。",
]


class OSMDataUnavailable(RuntimeError):
    """No complete, current real scene is available. Never use demo rectangles."""

    def __init__(self, message: str, *, evidence: dict | None = None):
        super().__init__(message)
        self.evidence = evidence


def route_bbox(origin: tuple[float, float], destination: tuple[float, float], margin_m: float) -> list[float]:
    for lng, lat in (origin, destination):
        if not (math.isfinite(lng) and math.isfinite(lat) and -180 <= lng <= 180 and abs(lat) < 85):
            raise ValueError("OSM 查询需要有效 WGS84 经纬度（纬度绝对值 <85°）")
    if not math.isfinite(margin_m) or not 100 <= margin_m <= 10_000:
        raise ValueError("查询外扩距离必须在100–10000米之间")
    if abs(origin[0] - destination[0]) > 180:
        raise ValueError("暂不支持跨日期变更线的场景")
    dy = margin_m / 111_000.0
    max_lat = max(abs(origin[1]), abs(destination[1])) + dy
    dx = margin_m / (111_000.0 * math.cos(math.radians(max_lat)))
    bounds = [
        min(origin[0], destination[0]) - dx,
        min(origin[1], destination[1]) - dy,
        max(origin[0], destination[0]) + dx,
        max(origin[1], destination[1]) + dy,
    ]
    if bounds[0] < -180 or bounds[2] > 180 or bounds[1] < -85 or bounds[3] > 85:
        raise ValueError("查询边界越过支持的 WGS84 区域")
    # Round outwards, never truncate requested coverage.
    return [math.floor(v * 1e6) / 1e6 if i < 2 else math.ceil(v * 1e6) / 1e6 for i, v in enumerate(bounds)]


def _height(tags: dict) -> dict:
    """OSM height units: metres by default; explicit ft/feet/prime converted."""
    raw = str(tags.get("height", "")).strip().lower()
    match = re.fullmatch(r"([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(m|metres?|meters?|ft|feet|foot|')?", raw)
    if match:
        value = float(match.group(1)) * (0.3048 if match.group(2) in {"ft", "feet", "foot", "'"} else 1)
        if math.isfinite(value) and value > 0:
            return {
                "height_m": value,
                "height_source": "tag",
                "height_estimated": False,
                "height_method": "OSM height 标签（非独立测量）",
            }
    levels = str(tags.get("building:levels", "")).strip()
    if re.fullmatch(r"[+]?(?:\d+(?:\.\d*)?|\.\d+)", levels) and 0 < float(levels) < 1000:
        return {
            "height_m": float(levels) * 3.0,
            "height_source": "levels",
            "height_estimated": True,
            "height_method": "OSM building:levels × 3 m/层；层高为明确估算，非实测",
        }
    return {
        "height_m": None,
        "height_source": "estimate",
        "height_estimated": True,
        "height_method": "高度未知；无可靠 height/levels，未填任何默认高度",
    }


def _coordinates(geometry: Any) -> list[list[float]]:
    if not isinstance(geometry, list):
        return []
    out = []
    for point in geometry:
        if not isinstance(point, dict) or "lon" not in point or "lat" not in point:
            return []
        lng, lat = float(point["lon"]), float(point["lat"])
        if not (math.isfinite(lng) and math.isfinite(lat) and -180 <= lng <= 180 and -90 <= lat <= 90):
            return []
        if not out or out[-1] != [lng, lat]:
            out.append([lng, lat])
    return out


def _closed(ring: list) -> bool:
    return len(ring) >= 4 and ring[0] == ring[-1] and len({tuple(p) for p in ring[:-1]}) >= 3


def _join_rings(parts: list[list]) -> list[list]:
    pending = [list(p) for p in parts]
    rings = []
    while pending:
        ring = pending.pop()
        while not _closed(ring):
            for index, part in enumerate(pending):
                if ring[-1] == part[0]:
                    ring += part[1:]
                elif ring[-1] == part[-1]:
                    ring += list(reversed(part))[1:]
                elif ring[0] == part[-1]:
                    ring = part[:-1] + ring
                elif ring[0] == part[0]:
                    ring = list(reversed(part))[:-1] + ring
                else:
                    continue
                pending.pop(index)
                break
            else:
                raise OSMDataUnavailable("OSM 建筑关系缺失闭合成员，拒绝把不完整轮廓用于避障")
        rings.append(ring)
    return rings


def _inside(point: list, ring: list) -> bool:
    x, y = point
    inside = False
    for a, b in zip(ring, ring[1:], strict=False):
        if (a[1] > y) != (b[1] > y) and x < a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
            inside = not inside
    return inside


def _building_geometry(element: dict) -> dict:
    if element["type"] == "way":
        ring = _coordinates(element.get("geometry"))
        if not _closed(ring):
            raise OSMDataUnavailable(f"OSM way/{element['id']} 建筑轮廓不完整，拒绝漏掉该障碍")
        return {"type": "Polygon", "coordinates": [ring]}
    members = element.get("members") or []
    outer_parts, inner_parts = [], []
    for member in members:
        if member.get("type") != "way":
            continue
        role = member.get("role", "")
        if role not in {"", "outer", "inner"}:
            continue
        part = _coordinates(member.get("geometry"))
        if len(part) < 2:
            raise OSMDataUnavailable(f"OSM relation/{element['id']} 缺少建筑几何成员")
        (inner_parts if role == "inner" else outer_parts).append(part)
    outers, inners = _join_rings(outer_parts), _join_rings(inner_parts)
    if not outers:
        raise OSMDataUnavailable(f"OSM relation/{element['id']} 没有建筑外环")
    polygons = [[ring] for ring in outers]
    for inner in inners:
        owners = [i for i, ring in enumerate(outers) if _inside(inner[0], ring)]
        if len(owners) != 1:
            raise OSMDataUnavailable(f"OSM relation/{element['id']} 内环归属不明确")
        polygons[owners[0]].append(inner)
    return (
        {"type": "Polygon", "coordinates": polygons[0]}
        if len(polygons) == 1
        else {"type": "MultiPolygon", "coordinates": polygons}
    )


def _conservative_geometry(element: dict, reason: str) -> tuple[dict, dict]:
    """Opaque hull from complete genuine coordinates, never fill missing data.

    Malformed OSM topology can describe only fragments of a building. Its hull
    is a derived avoidance envelope, not a measured/reconstructed footprint.
    Unknown omissions remain a warning even though all mapped nodes are kept.
    """
    original = {"osm_type": element["type"]}
    if element["type"] == "way":
        coords = _coordinates(element.get("geometry"))
        if len(coords) < 3:
            raise OSMDataUnavailable("建筑缺失坐标，不能用包络修补数据缺失")
        original["geometry"] = element["geometry"]
    else:
        members = element.get("members") or []
        coords = []
        original["members"] = members
        for member in members:
            part = _coordinates(member.get("geometry"))
            if member.get("type") != "way" or len(part) < 2:
                raise OSMDataUnavailable("建筑关系缺失坐标/成员，不能用包络修补数据缺失")
            coords.extend(part)
    hull = MultiPoint(coords).convex_hull
    if hull.geom_type != "Polygon" or hull.is_empty or not hull.is_valid:
        raise OSMDataUnavailable("真实节点不足以构成有效建筑避让包络")
    return json.loads(json.dumps(mapping(hull))), {
        "geometry_status": "derived_conservative",
        "geometry_method": "convex_hull_of_osm_member_nodes",
        "geometry_repair_reason": reason,
        "original_geometry": original,
        "geometry_note": "原始OSM拓扑无效；全部已获取真实成员节点的凸包作为不透明避让包络。不是实测建筑轮廓，未知漏绘仍需核查。",
    }


def _parse(payload: dict, bbox: list, fetched_at: str, endpoint: str) -> dict:
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("elements"), list)
        or payload.get("remark")
    ):
        raise OSMDataUnavailable("Overpass 响应缺失 elements 或带错误 remark，拒绝使用部分结果")
    buildings, roads = [], []
    seen = set()
    for element in payload["elements"]:
        typ, osm_id = element.get("type"), element.get("id")
        if typ not in {"way", "relation"} or not isinstance(osm_id, int):
            continue
        if (typ, osm_id) in seen:
            continue
        seen.add((typ, osm_id))
        tags = element.get("tags") or {}
        props = {
            "id": f"osm-{typ}-{osm_id}",
            "osm_type": typ,
            "osm_id": osm_id,
            "osm_url": f"https://www.openstreetmap.org/{typ}/{osm_id}",
            "tags": tags,
            "source": SOURCE,
            "fetched_at": fetched_at,
            "status": "real",
            "osm_timestamp": element.get("timestamp"),
            "name": tags.get("name"),
        }
        if tags.get("building") not in (None, "no") or tags.get("building:part") not in (None, "no"):
            status = {"geometry_status": "mapped", "geometry_method": "osm_mapped_outline"}
            try:
                geometry = _building_geometry(element)
                if not shape(geometry).is_valid:
                    geometry, status = _conservative_geometry(element, "OSM 原始轮廓存在自交/无效拓扑")
            except OSMDataUnavailable as exc:
                geometry, status = _conservative_geometry(element, str(exc))
            buildings.append(
                {
                    "type": "Feature",
                    "id": props["id"],
                    "properties": props | _height(tags) | status,
                    "geometry": geometry,
                }
            )
        if typ == "way" and tags.get("highway"):
            coords = _coordinates(element.get("geometry"))
            if len(coords) < 2:
                raise OSMDataUnavailable(f"OSM way/{osm_id} 道路几何不完整")
            roads.append(
                {
                    "type": "Feature",
                    "id": props["id"],
                    "properties": props
                    | {
                        "highway": tags["highway"],
                        "bridge": tags.get("bridge"),
                        "tunnel": tags.get("tunnel"),
                        "layer": tags.get("layer"),
                    },
                    "geometry": {"type": "LineString", "coordinates": coords},
                }
            )
    common = {
        "type": "FeatureCollection",
        "bbox": bbox,
        "crs_note": "WGS84 / EPSG:4326 longitude, latitude",
        "source": SOURCE,
        "attribution": ATTRIBUTION,
        "fetched_at": fetched_at,
        "status": "real",
    }
    counts = {
        key: sum(f["properties"]["height_source"] == key for f in buildings)
        for key in ("tag", "levels", "estimate")
    }
    derived = sum(f["properties"]["geometry_status"] == "derived_conservative" for f in buildings)
    warnings = list(WARNINGS)
    if derived:
        warnings.append(
            f"{derived}个OSM建筑原始拓扑无效，已用全部真实成员节点凸包作保守避让包络；geometry_status=derived_conservative，可追溯原始角色和坐标。"
        )
    return {
        "obstacles": common | {"features": buildings},
        "roads": common | {"features": roads},
        "metadata": {
            "source": SOURCE,
            "attribution": ATTRIBUTION,
            "bbox": bbox,
            "fetched_at": fetched_at,
            "osm_base_timestamp": (payload.get("osm3s") or {}).get("timestamp_osm_base"),
            "endpoint": endpoint,
            "building_count": len(buildings),
            "road_count": len(roads),
            "height_sources": counts,
            "coverage": "OSM mapped features only; completeness not guaranteed",
            "derived_geometry_count": derived,
            "source_fetches": payload.get("source_fetches", []),
            "source_fetched_at": payload.get("source_fetched_at", fetched_at),
            "status": "real",
            "schema_version": 1,
        },
        "warnings": warnings,
    }


def _atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _map_elements(documents: list[bytes]) -> dict[tuple[str, int], dict]:
    """Decode primary OSM XML without guessing missing node/member coordinates."""
    elements = {}
    for document in documents:
        stream = ET.iterparse(io.BytesIO(document), events=("start", "end"))
        _, root = next(stream)
        if root.tag != "osm":
            raise OSMDataUnavailable("OSM 主站未返回 map XML")
        for event, entry in stream:
            if event != "end" or entry.tag not in {"node", "way", "relation"}:
                continue
            key = (entry.tag, int(entry.attrib["id"]))
            data = {"type": entry.tag, "id": key[1]}
            if entry.tag == "node":
                data.update({"lon": float(entry.attrib["lon"]), "lat": float(entry.attrib["lat"])})
            else:
                data.update(
                    {
                        "timestamp": entry.get("timestamp"),
                        "tags": {t.attrib["k"]: t.attrib["v"] for t in entry.findall("tag")},
                    }
                )
                if entry.tag == "way":
                    data["nodes"] = [int(n.attrib["ref"]) for n in entry.findall("nd")]
                else:
                    data["members"] = [
                        {"type": m.attrib["type"], "ref": int(m.attrib["ref"]), "role": m.get("role", "")}
                        for m in entry.findall("member")
                    ]
            elements[key] = data
            entry.clear()
            root.clear()
    return elements


def _is_building(element: dict) -> bool:
    tags = element.get("tags") or {}
    return tags.get("building") not in (None, "no") or tags.get("building:part") not in (None, "no")


def _primary_map_payload(
    active: httpx.Client,
    bbox: list[float],
    cache_dir: Path | None = None,
    *,
    deadline_at: float | None = None,
    max_workers: int = 2,
) -> tuple[dict, list[list[float]]]:
    """Small primary API map requests are a real-source fallback, not fixtures.

    Two concurrent requests, bounded tiles and a 50-second overall deadline.
    Building relations receive /full only when a map tile omitted a member.
    """
    west, south, east, north = bbox
    nx, ny = max(1, math.ceil((east - west) / 0.05)), max(1, math.ceil((north - south) / 0.04))
    if nx * ny > 32:
        raise OSMDataUnavailable("主站备用下载超过32个小块，需使用可达的 Overpass 或离线实测数据")
    tiles = [
        [
            west + (east - west) * ix / nx,
            south + (north - south) * iy / ny,
            west + (east - west) * (ix + 1) / nx,
            south + (north - south) * (iy + 1) / ny,
        ]
        for ix in range(nx)
        for iy in range(ny)
    ]
    if not isinstance(max_workers, int) or isinstance(max_workers, bool) or not 1 <= max_workers <= 2:
        raise ValueError("OSM 主站并发只能是 1 或 2")
    deadline = time.monotonic() + 50 if deadline_at is None else deadline_at
    tiles_cache = (cache_dir or CACHE_DIR) / ".tiles"
    normalized_id = hashlib.sha256(json.dumps(bbox, separators=(",", ":")).encode()).hexdigest()[:16]
    normalized_path = tiles_cache / f"normalized-{normalized_id}.json"
    try:
        saved = json.loads(normalized_path.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(saved["payload"]["source_fetched_at"].replace("Z", "+00:00"))
        if saved.get("bbox") == bbox and timedelta() <= datetime.now(UTC) - fetched <= timedelta(hours=6):
            return saved["payload"], saved["tiles"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    request_lock = threading.Lock()
    request_count = 0
    source_fetches = []

    def get_primary(path, params=None):
        nonlocal request_count
        key = hashlib.sha256(json.dumps([path, params], sort_keys=True).encode()).hexdigest()[:24]
        raw_path, meta_path = tiles_cache / f"{key}.osm", tiles_cache / f"{key}.json"
        try:
            saved = json.loads(meta_path.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(saved["fetched_at"].replace("Z", "+00:00"))
            if timedelta() <= datetime.now(UTC) - fetched <= timedelta(hours=6):
                raw = raw_path.read_bytes()
                if hashlib.sha256(raw).hexdigest() == saved["sha256"]:
                    with request_lock:
                        source_fetches.append(saved | {"cache_hit": True})
                    return raw
        except (OSError, ValueError, KeyError, TypeError):
            pass
        last_error = None
        for host in (MAP_API, "https://www.openstreetmap.org/api/0.6"):
            if time.monotonic() >= deadline:
                raise OSMDataUnavailable("OSM 主站备用下载超过总时限")
            try:
                with request_lock:
                    if request_count >= 32:
                        raise OSMDataUnavailable("OSM 主站达到32次实际 HTTP 请求上限，尚未完成覆盖")
                    request_count += 1
                response = active.get(
                    f"{host}/{path}",
                    params=params,
                    timeout=httpx.Timeout(min(12, max(1, deadline - time.monotonic())), connect=5),
                )
                response.raise_for_status()
                if (
                    len(response.content) > 30_000_000
                    or b"<osm" not in response.content[:1000]
                    or not response.content.rstrip().endswith(b"</osm>")
                ):
                    raise OSMDataUnavailable("OSM 主站返回的 XML 无效或过大")
                tiles_cache.mkdir(parents=True, exist_ok=True)
                temporary = raw_path.with_suffix(f".{uuid4().hex}.tmp")
                try:
                    temporary.write_bytes(response.content)
                    temporary.replace(raw_path)
                finally:
                    temporary.unlink(missing_ok=True)
                record = {
                    "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "url": str(response.request.url),
                    "path": path,
                    "params": params,
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                }
                _atomic_json(meta_path, record)
                with request_lock:
                    source_fetches.append(record | {"cache_hit": False})
                return response.content
            except httpx.TransportError as exc:
                last_error = exc
        raise OSMDataUnavailable(f"OSM 主站两条连接均失败：{type(last_error).__name__}") from last_error

    def download(tile):
        started = time.perf_counter()
        rounded = [round(value, 7) for value in tile]
        try:
            if time.monotonic() >= deadline:
                raise OSMDataUnavailable("OSM 主站备用下载超过总时限")
            content = get_primary("map", params={"bbox": ",".join(f"{v:.7f}" for v in tile)})
        except (OSMDataUnavailable, httpx.HTTPError) as exc:
            return {
                "bbox": rounded,
                "status": "failed",
                "elapsed_s": round(time.perf_counter() - started, 3),
                "error": f"{type(exc).__name__}: {exc}"[:160],
                "content": None,
            }
        return {
            "bbox": rounded,
            "status": "ok",
            "elapsed_s": round(time.perf_counter() - started, 3),
            "error": None,
            "content": content,
        }

    download_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        tile_records = list(pool.map(download, tiles))
    chunk_download_s = round(time.perf_counter() - download_started, 3)
    public_tiles = [
        {key: value for key, value in record.items() if key != "content"} for record in tile_records
    ]
    failed = [record for record in public_tiles if record["status"] != "ok"]
    if failed:
        deadline_hit = time.monotonic() >= deadline
        if any(record["status"] == "ok" for record in public_tiles):
            coverage_status = "partial"
        elif deadline_hit:
            coverage_status = "timeout"
        else:
            coverage_status = "unavailable"
        raise OSMDataUnavailable(
            "OSM 主站分块未全部成功，拒绝用部分覆盖或空列表规划",
            evidence={
                "coverage_status": coverage_status,
                "coverage_tiles": public_tiles,
                "failed_chunks": failed,
                "stage_timings_s": {"chunk_download_s": chunk_download_s},
            },
        )
    documents = [record["content"] for record in tile_records]
    parse_started = time.perf_counter()
    elements = _map_elements(documents)
    map_parse_s = round(time.perf_counter() - parse_started, 3)
    # Parsing is local CPU work, not network waiting. Give relation completion
    # its own small bounded window after the transfer stage.
    deadline = time.monotonic() + 20
    # map returns complete ways, but only immediate relations. Fetch missing
    # members of actual building relations to preserve footprints and holes.
    relations = [
        e
        for e in elements.values()
        if e["type"] == "relation" and _is_building(e) and e["tags"].get("type") == "multipolygon"
    ]
    full_requests = 0
    for relation in relations:
        if any((m["type"], m["ref"]) not in elements for m in relation["members"] if m["type"] == "way"):
            full_requests += 1
            if len(tiles) + full_requests > 32:
                raise OSMDataUnavailable("主站备用下载达到32次请求上限，建筑关系未完整，拒绝规划")
            if time.monotonic() >= deadline:
                raise OSMDataUnavailable("建筑关系补全超过总时限")
            document = get_primary(f"relation/{relation['id']}/full")
            elements.update(_map_elements([document]))
    output = []
    for element in elements.values():
        if element["type"] == "way" and (_is_building(element) or element["tags"].get("highway")):
            coords = [elements.get(("node", nid)) for nid in element["nodes"]]
            if any(c is None for c in coords):
                raise OSMDataUnavailable(f"OSM 主站 way/{element['id']} 缺少坐标，拒绝漏掉真实地物")
            output.append(element | {"geometry": [{"lon": c["lon"], "lat": c["lat"]} for c in coords]})
        elif (
            element["type"] == "relation"
            and _is_building(element)
            and element["tags"].get("type") == "multipolygon"
        ):
            members = []
            for member in element["members"]:
                if member["type"] != "way":
                    raise OSMDataUnavailable(f"OSM 建筑关系 {element['id']} 含嵌套关系，需人工补全障碍物")
                way = elements.get(("way", member["ref"]))
                coords = [elements.get(("node", nid)) for nid in way["nodes"]] if way else []
                if not coords or any(c is None for c in coords):
                    raise OSMDataUnavailable(f"OSM 建筑关系 {element['id']} 缺少成员坐标")
                members.append(member | {"geometry": [{"lon": c["lon"], "lat": c["lat"]} for c in coords]})
            output.append(element | {"members": members})
    earliest = min((r["fetched_at"] for r in source_fetches), default=datetime.now(UTC).isoformat())
    payload = {
        "elements": output,
        "source_fetches": source_fetches,
        "source_fetched_at": earliest,
        "stage_timings_s": {"chunk_download_s": chunk_download_s, "map_parse_s": map_parse_s},
        "coverage_tiles": public_tiles,
    }
    _atomic_json(normalized_path, {"bbox": bbox, "payload": payload, "tiles": tiles})
    return payload, tiles


def _expires_at(fetched_at: str, max_age_hours: float) -> str:
    fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    return (fetched + timedelta(hours=max_age_hours)).isoformat().replace("+00:00", "Z")


def _evidence_id(scene_id: str, fetched_at: str, coverage_status: str) -> str:
    digest = hashlib.sha256(f"{scene_id}|{fetched_at}|{coverage_status}".encode()).hexdigest()
    return f"obs-{digest[:12]}"


def _write_failure(directory: Path, evidence: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _atomic_json(directory / "failure.json", evidence)


def _persist(result: dict, directory: Path, scene_id: str, query: str, max_age_hours: float) -> dict:
    if not result["obstacles"]["features"]:
        result["warnings"].append("该范围 OSM 未返回建筑；这是地图缺失可能性，不能据此认定没有真实障碍物。")
    fetched_at = result["metadata"]["fetched_at"]
    coverage_status = result["metadata"].get("coverage_status") or (
        "queried_empty" if not result["obstacles"]["features"] else "complete"
    )
    result["metadata"].update(
        {
            "scene_id": scene_id,
            "query": query,
            "cache_hit": False,
            "cache_ttl_hours": max_age_hours,
            "warnings": result["warnings"],
            "coverage_status": coverage_status,
            "query_bbox": result["metadata"].get("bbox"),
            "expires_at": _expires_at(fetched_at, max_age_hours),
            "evidence_id": _evidence_id(scene_id, fetched_at, coverage_status),
            "crs": "EPSG:4326",
            "height_datum": "OSM height 标签按米；ft 已换算。缺失高度保持 null，不用默认高度。",
            "local_frame": "规划时以航线中点做局部等距圆柱投影到米；缓存坐标保持 WGS84。",
            "pass_allowed": False,
            "coverage_note": "覆盖状态只说明本次查询到的 OSM 登记要素，不代表现场障碍已被穷尽。",
            "failed_chunks": result["metadata"].get("failed_chunks") or [],
            "coverage_tiles": result["metadata"].get("coverage_tiles") or [],
        }
    )
    for collection in (result["obstacles"], result["roads"]):
        collection["coverage_status"] = coverage_status
        collection["pass_allowed"] = False
        collection["crs"] = "EPSG:4326"
    directory.mkdir(parents=True, exist_ok=True)
    _atomic_json(directory / "obstacles.geojson", result["obstacles"])
    _atomic_json(directory / "roads.geojson", result["roads"])
    _atomic_json(directory / "metadata.json", result["metadata"])
    return result


def _effective_cache_dir(cache_dir: Path | None) -> Path:
    if cache_dir is not None:
        return cache_dir
    override = __import__("os").environ.get("AERIS_OSM_CACHE_DIR")
    return Path(override) if override else CACHE_DIR


def load_cached_scene(
    scene_id: str, cache_dir: Path | None = None, *, max_age_hours: float = CACHE_TTL_HOURS
) -> dict:
    """Load only a current, fully written real scene; reject traversal and stale files."""
    if not re.fullmatch(r"[0-9a-f]{16}", scene_id):
        raise OSMDataUnavailable("真实场景标识无效")
    directory = _effective_cache_dir(cache_dir) / scene_id
    try:
        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(
            metadata.get("source_fetched_at", metadata["fetched_at"]).replace("Z", "+00:00")
        )
        age = datetime.now(UTC) - fetched
        if not timedelta(minutes=-5) <= age <= timedelta(hours=max_age_hours):
            raise OSMDataUnavailable(
                "OSM 缓存已过期，必须重新联网获取；未使用旧数据代替",
                evidence={
                    "coverage_status": "expired",
                    "scene_id": scene_id,
                    "fetched_at": metadata.get("source_fetched_at", metadata.get("fetched_at")),
                    "expires_at": metadata.get("expires_at"),
                    "pass_allowed": False,
                },
            )
        if metadata.get("scene_id") != scene_id or metadata.get("schema_version") != 1:
            raise OSMDataUnavailable("OSM 缓存版本或标识不一致")
        obstacles = json.loads((directory / "obstacles.geojson").read_text(encoding="utf-8"))
        roads = json.loads((directory / "roads.geojson").read_text(encoding="utf-8"))
        for fc, count in ((obstacles, metadata["building_count"]), (roads, metadata["road_count"])):
            if (
                fc.get("status") != "real"
                or fc.get("bbox") != metadata["bbox"]
                or fc.get("fetched_at") != metadata["fetched_at"]
                or len(fc["features"]) != count
            ):
                raise OSMDataUnavailable("OSM 缓存不完整或不同步")
        warnings = metadata.get("warnings", list(WARNINGS))
        return {
            "obstacles": obstacles,
            "roads": roads,
            "metadata": metadata
            | {
                "cache_hit": True,
                "pass_allowed": False,
                "coverage_note": "缓存命中只说明已有这份数据，不代表现场障碍已被穷尽。",
            },
            "warnings": warnings,
        }
    except OSMDataUnavailable:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise OSMDataUnavailable("真实 OSM 场景缓存不存在或损坏") from exc


def fetch_obstacles(
    origin: tuple[float, float],
    destination: tuple[float, float],
    *,
    margin_m: float = 1000.0,
    client: httpx.Client | None = None,
    cache_dir: Path | None = None,
    max_age_hours: float = CACHE_TTL_HOURS,
    force_refresh: bool = False,
    allow_primary_api: bool = True,
    budget_s: float | None = None,
    max_workers: int = 2,
) -> dict:
    """Download buildings/parts, multipolygons and roads for one complete bbox.

    A 24-hour cache is explicitly timestamped. Expired data is never returned on
    network failure. Public mirrors have bounded calls. If unavailable, the OSM
    primary map API is an explicitly attributed real-source alternative.
    """
    bbox = route_bbox(origin, destination, margin_m)
    scene_id = hashlib.sha256(json.dumps(bbox, separators=(",", ":")).encode()).hexdigest()[:16]
    directory = _effective_cache_dir(cache_dir) / scene_id
    if not force_refresh:
        try:
            return load_cached_scene(scene_id, cache_dir, max_age_hours=max_age_hours)
        except OSMDataUnavailable:
            pass
    west, south, east, north = bbox
    area = (east - west) * (north - south) * math.cos(math.radians((north + south) / 2)) * 111.32**2
    if area > 3000:
        raise ValueError("查询范围超过3000平方公里；请拆分航线")
    bounds = f"({south},{west},{north},{east})"
    query = (
        f"[out:json][timeout:15][maxsize:134217728];("
        f'way["building"]["building"!="no"]{bounds};'
        f'way["building:part"]["building:part"!="no"]{bounds};'
        f'relation["type"="multipolygon"]["building"]["building"!="no"]{bounds};'
        f'relation["type"="multipolygon"]["building:part"]["building:part"!="no"]{bounds};'
        f'way["highway"]{bounds};);out meta geom;'
    )
    if budget_s is not None and (
        isinstance(budget_s, bool) or not isinstance(budget_s, (int, float)) or budget_s <= 0
    ):
        raise ValueError("障碍查询总截止时间必须为正数秒")
    errors = []
    empty_result = None
    deadline_hit = False
    primary_evidence = None
    overpass_request_s = 0.0
    parse_s = 0.0
    started = time.perf_counter()
    own_client = client is None
    proxy = __import__("os").environ.get("AERIS_OSM_PROXY")
    proxy_used = "caller"
    if client is None:
        if proxy is None or proxy == "":
            active = httpx.Client(
                timeout=httpx.Timeout(18, connect=5), trust_env=False, headers={"User-Agent": USER_AGENT}
            )
            proxy_used = "direct"
        else:
            active = httpx.Client(
                timeout=httpx.Timeout(18, connect=5),
                trust_env=False,
                proxy=proxy,
                headers={"User-Agent": USER_AGENT},
            )
            proxy_used = "configured"
    else:
        active = client
    active.aeris_proxy_used = proxy_used

    def remaining():
        if budget_s is None:
            return None
        return budget_s - (time.perf_counter() - started)

    def stamp_attempt(result, *, status, tiles):
        result["metadata"]["coverage_status"] = status
        result["metadata"]["coverage_tiles"] = tiles
        result["metadata"]["failed_chunks"] = []
        result["metadata"]["proxy_used"] = proxy_used
        result["metadata"]["stage_timings_s"] = {
            "overpass_request_s": round(overpass_request_s, 3),
            "parse_s": round(parse_s, 3),
        }

    try:
        for endpoint in ENDPOINTS:
            left = remaining()
            if left is not None and left <= 0:
                deadline_hit = True
                errors.append(f"{endpoint}: 超过总截止时间，未再请求")
                break
            request_timeout = 18 if left is None else max(0.2, min(18, left))
            try:
                request_started = time.perf_counter()
                response = active.post(
                    endpoint,
                    data={"data": query},
                    timeout=httpx.Timeout(request_timeout, connect=min(5, request_timeout)),
                )
                overpass_request_s += time.perf_counter() - request_started
                response.raise_for_status()
                fetched_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                parse_started = time.perf_counter()
                result = _parse(response.json(), bbox, fetched_at, endpoint)
                parse_s += time.perf_counter() - parse_started
                tile = {
                    "bbox": bbox,
                    "status": "ok",
                    "endpoint": endpoint,
                    "elapsed_s": round(overpass_request_s, 3),
                    "error": None,
                }
                if not result["obstacles"]["features"] and not result["roads"]["features"]:
                    # A regional mirror (e.g. overpass.osm.ch) answers 200 but
                    # knows nothing outside its own extract. Try other endpoints
                    # first; accept an empty area only if every source agrees.
                    empty_result = result
                    errors.append(f"{endpoint}: 空结果，先尝试其他端点")
                    continue
                stamp_attempt(result, status="complete", tiles=[tile])
                return _persist(result, directory, scene_id, query, max_age_hours)
            except (httpx.HTTPError, ValueError, OSMDataUnavailable) as exc:
                errors.append(f"{endpoint}: {type(exc).__name__}: {str(exc)[:160]}")
        if allow_primary_api and not deadline_hit:
            left = remaining()
            if left is not None and left <= 0:
                deadline_hit = True
            else:
                try:
                    payload, tiles = _primary_map_payload(
                        active,
                        bbox,
                        cache_dir,
                        deadline_at=None if left is None else time.monotonic() + left,
                        max_workers=max_workers,
                    )
                    fetched_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                    parse_started = time.perf_counter()
                    result = _parse(payload, bbox, fetched_at, MAP_API)
                    parse_s += time.perf_counter() - parse_started
                    for fc in (result["obstacles"], result["roads"]):
                        fc["source"] = MAP_SOURCE
                        for feature in fc["features"]:
                            feature["properties"]["source"] = MAP_SOURCE
                    status = (
                        "queried_empty"
                        if not result["obstacles"]["features"] and not result["roads"]["features"]
                        else "complete"
                    )
                    result["metadata"].update(
                        {
                            "source": MAP_SOURCE,
                            "tiles": tiles,
                            "overpass_errors": errors,
                            "coverage_status": status,
                            "coverage_tiles": payload.get("coverage_tiles")
                            or [{"bbox": tile, "status": "ok", "error": None} for tile in tiles],
                            "failed_chunks": [],
                            "proxy_used": proxy_used,
                            "stage_timings_s": {
                                "overpass_request_s": round(overpass_request_s, 3),
                                "parse_s": round(parse_s, 3),
                                **(payload.get("stage_timings_s") or {}),
                            },
                        }
                    )
                    result["warnings"].append(
                        "Overpass 不可达；已改用 OSM 主站真实 map 数据，未使用仿真替代。"
                    )
                    return _persist(
                        result,
                        directory,
                        scene_id,
                        "OSM API 0.6 map tiles + complete building relations",
                        max_age_hours,
                    )
                except (httpx.HTTPError, ValueError, ET.ParseError, OSMDataUnavailable) as exc:
                    errors.append(f"{MAP_API}: {type(exc).__name__}: {str(exc)[:160]}")
                    primary_evidence = getattr(exc, "evidence", None)
    finally:
        if own_client:
            active.close()
    primary_partial = (
        isinstance(primary_evidence, dict) and primary_evidence.get("coverage_status") == "partial"
    )
    if empty_result is not None and not deadline_hit and not primary_partial:
        empty_result["warnings"].append(
            "所有数据源在该范围均未返回建筑/道路记录；不代表现实中没有建筑，规划结果必须按“覆盖未知”读。"
        )
        stamp_attempt(
            empty_result,
            status="queried_empty",
            tiles=[{"bbox": bbox, "status": "ok", "endpoint": "all-overpass-empty", "error": None}],
        )
        return _persist(
            empty_result,
            directory,
            scene_id,
            "all Overpass endpoints returned empty for this bbox",
            max_age_hours,
        )
    coverage_status = "timeout" if deadline_hit else "unavailable"
    failed_chunks = []
    coverage_tiles = []
    if isinstance(primary_evidence, dict):
        coverage_status = primary_evidence.get("coverage_status") or coverage_status
        failed_chunks = primary_evidence.get("failed_chunks") or []
        coverage_tiles = primary_evidence.get("coverage_tiles") or []
    evidence = {
        "coverage_status": coverage_status,
        "scene_id": scene_id,
        "query_bbox": bbox,
        "crs": "EPSG:4326",
        "errors": errors,
        "failed_chunks": failed_chunks,
        "coverage_tiles": coverage_tiles,
        "stage_timings_s": {
            "overpass_request_s": round(overpass_request_s, 3),
            "parse_s": round(parse_s, 3),
            **((primary_evidence or {}).get("stage_timings_s") or {}),
        },
        "proxy_used": proxy_used,
        "pass_allowed": False,
        "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": SOURCE,
        "statement": "查询未形成完整覆盖。空障碍列表不能当作通过。",
    }
    _write_failure(directory, evidence)
    raise OSMDataUnavailable(
        "真实建筑/道路获取失败；未回退到仿真数据。" + " | ".join(errors), evidence=evidence
    )


def load_replay_snapshot(path: Path) -> dict:
    """Read a saved coverage record. A partial or failed record is not a pass."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    allowed = {"complete", "queried_empty", "partial", "timeout", "expired", "not_queried", "unavailable"}
    if data.get("pass_allowed") is not False or data.get("coverage_status") not in allowed:
        raise OSMDataUnavailable("重放快照不能当作覆盖通过")
    if data.get("coverage_status") != "complete" and not data.get("statement"):
        raise OSMDataUnavailable("非完整覆盖的重放快照必须写明不能通过的原因")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="获取真实 OSM 建筑和道路，落盘独立于冻结的 scenarios/v0")
    parser.add_argument("--origin", type=float, nargs=2, required=True, metavar=("LNG", "LAT"))
    parser.add_argument("--destination", type=float, nargs=2, required=True, metavar=("LNG", "LAT"))
    parser.add_argument("--margin-m", type=float, default=1000)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    result = fetch_obstacles(
        tuple(args.origin), tuple(args.destination), margin_m=args.margin_m, force_refresh=args.refresh
    )
    print(json.dumps(result["metadata"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
