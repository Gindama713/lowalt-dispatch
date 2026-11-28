"""Route environment verdict.

The recovered v3 text requires a factor matrix and a verdict in
{pass, degraded, blocked, unknown}, but it does not include the §9.5 name
list or any sourced numeric threshold. This module therefore:

- evaluates only fields the forecast path already returns, plus gaps named
  in the agent spec (cloud base, NOTAM, terrain, diversion, vertical clearance);
- reads numeric thresholds only from scenarios/standards/thresholds.yaml;
- never treats a null threshold as a pass;
- treats WMO codes 95/96/99 as thunderstorms because that is the Open-Meteo
  weather-code table, not a local millimetre limit.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.assistant.route_weather import _distance, assess_route_weather

ALGO_VERSION = 1
ROOT = Path(__file__).resolve().parents[2]
THRESHOLDS_PATH = ROOT / "scenarios/standards/thresholds.yaml"
AUDIT_ROOT = ROOT / "logs/env_audit"
WMO_THUNDERSTORM = (95, 96, 99)
WMO_SOURCE = "https://open-meteo.com/en/docs"
RANK = {"pass": 0, "degraded": 1, "unknown": 2, "blocked": 3}

# Ordered. Names are either hourly fields already requested or gaps named in
# the agent/acceptance specs. This is not a claim that §9.5's unpublished
# 24-row list was recovered.
FACTOR_CATALOG = (
    ("precipitation_max", "降水最大", "hard", True),
    ("precipitation_probability_max", "降水概率最大", "info", False),
    ("visibility_min", "能见度最小", "hard", True),
    ("wind_gust_10m_max", "10米阵风最大", "hard", False),
    ("wind_speed_10m_max", "10米风速最大", "info", False),
    ("wind_speed_120m_max", "120米风速最大", "info", False),
    ("wind_cross", "侧风", "hard", True),
    ("cloud_cover_max", "总云量最大", "info", False),
    ("weather_code_max", "天气代码", "hard", True),
    ("temperature_2m_min", "2米气温最低", "info", False),
    ("relative_humidity_2m_max", "相对湿度最大", "info", False),
    ("surface_pressure_min", "地面气压最低", "info", False),
    ("dew_point_2m_min", "露点最低", "info", False),
    ("cape_max", "CAPE最大", "info", False),
    ("freezing_level_height_min", "冻结高度最低", "info", False),
    ("cloud_base_height", "云底高", "info", False),
    ("vehicle_wind_limit", "厂家抗风", "hard", False),
    ("payload_limit", "载荷上限", "hard", False),
    ("vertical_clearance", "垂直净空", "hard", False),
    ("diversion_reachability", "备降可达", "hard", False),
    ("known_airspace_snapshot", "已知限制区快照", "hard", False),
    ("airspace_notam", "NOTAM空域", "hard", False),
    ("terrain_clearance", "地形净空", "hard", False),
    ("energy_wh", "能耗", "info", False),
)

_CACHE: dict[tuple, tuple[float, dict]] = {}
_EVIDENCE: dict[str, dict] = {}


class EnvQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    origin: tuple[float, float]
    destination: tuple[float, float]
    scheduled_for: str | None = None
    payload_kg: float | None = Field(default=None, ge=0, le=1000)
    vehicle_key: str | None = None
    altitude_agl_m: float = Field(default=120.0, gt=0, le=500)
    waypoints: list[tuple[float, float]] | None = Field(default=None, min_length=2, max_length=1000)
    airspace_snapshot_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def geographic(self):
        for lng, lat in (self.origin, self.destination, *(self.waypoints or [])):
            if not (-180 <= lng <= 180 and -90 <= lat <= 90):
                raise ValueError("坐标越界")
        if abs(self.origin[0] - self.destination[0]) > 180:
            raise ValueError("跨日期变更线请分段规划")
        distance = _distance(self.origin, self.destination)
        if distance < 10:
            raise ValueError("起终点至少相距10米")
        if distance > 80_000:
            raise ValueError("真实航线限80km局部区域")
        if self.waypoints and (
            _distance(self.waypoints[0], self.origin) > 1
            or _distance(self.waypoints[-1], self.destination) > 1
            or sum(_distance(a, b) for a, b in pairwise(self.waypoints)) > 80_000
        ):
            raise ValueError("环境采样路线须匹配起终点，且累计长度不超过80km")
        return self


def load_thresholds() -> dict:
    if not THRESHOLDS_PATH.is_file():
        return {}
    raw = yaml.safe_load(THRESHOLDS_PATH.read_text(encoding="utf-8")) or {}
    found = {}
    for key, item in (raw.get("thresholds") or {}).items():
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        source = item.get("source_ref")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            value = None
        if not isinstance(source, str) or not source.strip():
            source = None
        if value is not None and source is None:
            value = None
        found[key] = {"value": value, "source_ref": source}
    return found


def thresholds_all_null(thresholds: dict | None = None) -> bool:
    data = load_thresholds() if thresholds is None else thresholds
    return not any(item.get("value") is not None for item in data.values())


def decide_verdict(factors, coverage, *, thresholds_all_null=True, weather_unavailable=False):
    """Return (verdict, reason). pass is only the last branch, and only with a sourced threshold."""
    hard = [factor["id"] for factor in factors if factor.get("hard_failed")]
    if weather_unavailable:
        return "unknown", "气象服务不可达，未做环境判定"
    if hard:
        return "blocked", "硬约束失败: " + ", ".join(hard)
    cells = coverage.get("independent_cells") if isinstance(coverage, dict) else None
    if cells is None:
        return "unknown", "没有可用的 model_point，不能确认空间覆盖"
    if not isinstance(cells, int) or cells < 3:
        return "degraded", f"仅 {cells} 个独立模式格点，不能判通过"
    critical = [
        factor["id"]
        for factor in factors
        if factor.get("critical") and factor.get("status") in {"unavailable", "not_evaluated"}
    ]
    if critical:
        return "degraded", "关键项未判定: " + ", ".join(critical)
    if any(factor.get("status") == "unavailable" for factor in factors):
        return "degraded", "存在不可用因素，不能判通过"
    if thresholds_all_null or any(
        factor.get("threshold") is None and factor.get("effect") == "hard" for factor in factors
    ):
        return "degraded", "没有来源明确的阈值，只能列出风险项，不能判通过"
    return "pass", "已评估因素未触发硬约束，且阈值来自已登记来源"


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _extreme(samples, field, how):
    values = []
    for sample in samples:
        value = (sample.get("values") or {}).get(field)
        if _finite(value):
            values.append(float(value))
    if not values:
        return None
    return how(values)


def _factor(
    factor_id,
    name,
    effect,
    critical,
    *,
    status,
    value=None,
    unit="",
    threshold=None,
    threshold_source=None,
    reason="",
    hard_failed=False,
    segment_index=None,
):
    return {
        "id": factor_id,
        "name": name,
        "status": status,
        "value": value,
        "unit": unit,
        "threshold": threshold,
        "threshold_source": threshold_source,
        "effect": effect,
        "critical": critical,
        "segment_index": segment_index,
        "reason": reason,
        "hard_failed": hard_failed,
    }


def _catalog_limit(vehicle_key, field):
    if not vehicle_key:
        return None
    from services.assistant.vehicles import catalog

    for vehicle in catalog()["vehicles"]:
        if vehicle.get("id") != vehicle_key:
            continue
        value = vehicle.get(field)
        sources = vehicle.get("sources") or []
        index = (vehicle.get("field_sources") or {}).get(
            field if field != "max_payload_kg" else "max_payload_kg"
        )
        if field == "max_wind_mps":
            index = (vehicle.get("field_sources") or {}).get("max_wind_mps")
        if not _finite(value) or value <= 0:
            return None
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(sources):
            return None
        source = sources[index]
        url = source.get("url") if isinstance(source, dict) else None
        if not url:
            return None
        return float(value), url
    return None


def _build_factors(weather, query: EnvQuery, thresholds):
    samples = weather.get("samples") or []
    envelope = weather.get("safety_envelope") or {}
    provenance = weather.get("provenance") or {}
    speed = provenance.get("speed_mps")
    factors = []
    specs = {item[0]: item for item in FACTOR_CATALOG}

    def add(factor_id, **kwargs):
        _id, name, effect, critical = specs[factor_id]
        factors.append(_factor(factor_id, name, effect, critical, **kwargs))

    precip = envelope.get("precip_max")
    if precip is None:
        precip = _extreme(samples, "precipitation", max)
    interior = [(sample.get("values") or {}).get("precipitation") for sample in samples[1:-1]]
    interior_values = [float(value) for value in interior if _finite(value)]
    ends = []
    if len(samples) >= 2:
        for sample in (samples[0], samples[-1]):
            value = (sample.get("values") or {}).get("precipitation")
            if _finite(value):
                ends.append(float(value))
    mid_rain = bool(interior_values) and max(interior_values) > 0 and ends == [0.0, 0.0]
    precip_threshold = (thresholds.get("precipitation_max_mm") or {}).get("value")
    precip_source = (thresholds.get("precipitation_max_mm") or {}).get("source_ref")
    add(
        "precipitation_max",
        status="modeled" if precip is not None else "unavailable",
        value=precip,
        unit="mm",
        threshold=precip_threshold,
        threshold_source=precip_source,
        reason="中段降水高于两端，且没有来源明确的降水阈值"
        if mid_rain
        else ("" if precip is not None else "降水缺测"),
        hard_failed=bool(precip_threshold is not None and precip is not None and precip > precip_threshold),
        segment_index=next(
            (
                sample.get("index")
                for sample in samples[1:-1]
                if _finite((sample.get("values") or {}).get("precipitation"))
                and (sample.get("values") or {}).get("precipitation") == max(interior_values)
            ),
            None,
        )
        if mid_rain
        else None,
    )
    probability = envelope.get("precip_probability_max")
    if probability is None:
        probability = _extreme(samples, "precipitation_probability", max)
    add(
        "precipitation_probability_max",
        status="modeled" if probability is not None else "unavailable",
        value=probability,
        unit="%",
        reason="" if probability is not None else "降水概率缺测",
    )
    visibility = envelope.get("visibility_min")
    if visibility is None:
        visibility = _extreme(samples, "visibility", min)
    vis_threshold = (thresholds.get("visibility_min_m") or {}).get("value")
    vis_source = (thresholds.get("visibility_min_m") or {}).get("source_ref")
    add(
        "visibility_min",
        status="modeled" if visibility is not None else "unavailable",
        value=visibility,
        unit="m",
        threshold=vis_threshold,
        threshold_source=vis_source,
        reason="" if visibility is not None else "能见度缺测",
        hard_failed=bool(vis_threshold is not None and visibility is not None and visibility < vis_threshold),
    )
    gust = envelope.get("gust_max")
    if gust is None:
        gust = _extreme(samples, "wind_gusts_10m", max)
    add(
        "wind_gust_10m_max",
        status="modeled" if gust is not None else "unavailable",
        value=gust,
        unit="m/s",
        threshold=(thresholds.get("wind_gust_10m_max_mps") or {}).get("value"),
        threshold_source=(thresholds.get("wind_gust_10m_max_mps") or {}).get("source_ref"),
        reason="" if gust is not None else "阵风缺测",
    )
    wind10 = envelope.get("wind_speed_10m_max")
    if wind10 is None:
        wind10 = _extreme(samples, "wind_speed_10m", max)
    add(
        "wind_speed_10m_max",
        status="modeled" if wind10 is not None else "unavailable",
        value=wind10,
        unit="m/s",
        reason="" if wind10 is not None else "10米风速缺测",
    )
    wind120 = _extreme(samples, "wind_speed_120m", max)
    add(
        "wind_speed_120m_max",
        status="modeled" if wind120 is not None else "unavailable",
        value=wind120,
        unit="m/s",
        reason="" if wind120 is not None else "120米风速缺测，未用10米风代替该字段",
    )
    cross = envelope.get("crosswind_max")
    cross_failed = False
    cross_reason = "没有可用空速，侧风不能和空速比较"
    if cross is None:
        cross_status = "unavailable"
    elif speed is None:
        cross_status = "unavailable"
    else:
        cross_status = "modeled"
        cross_failed = cross >= float(speed)
        cross_reason = f"侧风 {cross} m/s 与空速 {speed} m/s 比较" if cross_failed else ""
    add(
        "wind_cross",
        status=cross_status,
        value=cross,
        unit="m/s",
        threshold=speed,
        threshold_source=provenance.get("speed_source"),
        reason=cross_reason,
        hard_failed=cross_failed,
    )
    cloud = envelope.get("cloud_cover_max")
    if cloud is None:
        cloud = _extreme(samples, "cloud_cover", max)
    add(
        "cloud_cover_max",
        status="modeled" if cloud is not None else "unavailable",
        value=cloud,
        unit="%",
        reason="" if cloud is not None else "云量缺测",
    )
    codes = []
    for sample in samples:
        code = (sample.get("values") or {}).get("weather_code")
        if _finite(code):
            codes.append(int(code))
    storm = next((code for code in codes if code in WMO_THUNDERSTORM), None)
    add(
        "weather_code_max",
        status="modeled" if codes else "unavailable",
        value=storm if storm is not None else (max(codes) if codes else None),
        unit="WMO",
        threshold_source=WMO_SOURCE if storm is not None else None,
        reason="Open-Meteo 天气代码表将 95/96/99 标为雷暴"
        if storm is not None
        else ("" if codes else "天气代码缺测"),
        hard_failed=storm is not None,
    )
    for factor_id, field, how, unit in (
        ("temperature_2m_min", "temperature_2m", min, "degC"),
        ("relative_humidity_2m_max", "relative_humidity_2m", max, "%"),
        ("surface_pressure_min", "surface_pressure", min, "hPa"),
        ("dew_point_2m_min", "dew_point_2m", min, "degC"),
        ("cape_max", "cape", max, "J/kg"),
        ("freezing_level_height_min", "freezing_level_height", min, "m"),
    ):
        value = _extreme(samples, field, how)
        add(
            factor_id,
            status="modeled" if value is not None else "unavailable",
            value=value,
            unit=unit,
            reason="" if value is not None else "该字段缺测",
        )
    add("cloud_base_height", status="not_evaluated", reason="已请求的 hourly 字段没有云底高，不能用云量代替")
    wind_limit = _catalog_limit(query.vehicle_key, "max_wind_mps")
    if wind_limit and gust is not None:
        limit, url = wind_limit
        add(
            "vehicle_wind_limit",
            status="modeled",
            value=gust,
            unit="m/s",
            threshold=limit,
            threshold_source=url,
            reason="阵风高于厂家公布抗风" if gust > limit else "",
            hard_failed=gust > limit,
        )
    else:
        add("vehicle_wind_limit", status="not_evaluated", reason="没有同时具备的厂家抗风来源和阵风值")
    payload_limit = _catalog_limit(query.vehicle_key, "max_payload_kg")
    if query.payload_kg is not None and payload_limit:
        limit, url = payload_limit
        add(
            "payload_limit",
            status="modeled",
            value=query.payload_kg,
            unit="kg",
            threshold=limit,
            threshold_source=url,
            reason="载荷高于厂家公布上限" if query.payload_kg > limit else "",
            hard_failed=query.payload_kg > limit,
        )
    else:
        add(
            "payload_limit",
            status="not_evaluated",
            reason="未同时提供载荷和有来源的厂家上限，不默认 0 或最大载荷",
        )
    add("vertical_clearance", status="not_evaluated", reason="垂直净空未判定")
    add("diversion_reachability", status="not_evaluated", reason="无备降几何数据，不能据此判不能飞")
    from services.assistant.airspace_snapshot import (
        check_route_against_snapshot,
    )
    from services.assistant.airspace_snapshot import (
        store as airspace_store,
    )

    air_snap = (
        airspace_store.resolve(snapshot_id=query.airspace_snapshot_id, scheduled_for=query.scheduled_for)
        if query.airspace_snapshot_id
        else airspace_store.get_active()
    )
    if air_snap is None or air_snap.source_status in {"not_loaded", "query_failed", "unavailable"}:
        if air_snap is not None and air_snap.source_status == "unavailable":
            air_reason = (
                f"大疆 FlySafe 厂商地理围栏不可用或为空：{air_snap.failure_reason or '未知原因'}。"
                "空域未知，不是放行。这不是 assess_route_environment 的法定空域结论。"
            )
            air_factor = "unavailable"
        elif air_snap is not None and air_snap.source_status == "query_failed":
            air_reason = f"空域快照读取失败：{air_snap.failure_reason or '未知原因'}"
            air_factor = "unavailable"
        else:
            air_reason = "未导入空域约束快照，仅完成建筑避障"
            air_factor = "not_evaluated"
        add(
            "known_airspace_snapshot",
            status=air_factor,
            reason=air_reason,
        )
    else:
        air_check = check_route_against_snapshot(
            query.waypoints or [query.origin, query.destination],
            air_snap,
            scheduled_for=query.scheduled_for,
        )
        conflicts = air_check.get("conflicts") or []
        add(
            "known_airspace_snapshot",
            status="modeled",
            value=len(conflicts),
            unit="处冲突",
            threshold=0.0,
            threshold_source=f"snapshot:{air_snap.snapshot_id} ({air_snap.digest[:19]}…)",
            segment_index=conflicts[0]["segment_index"] if conflicts else None,
            reason=air_check.get("verdict_label") or "",
            hard_failed=bool(conflicts),
        )
    add("airspace_notam", status="not_evaluated", reason="未接入 NOTAM/UOM，需人工核对")
    add("terrain_clearance", status="not_evaluated", reason="地形净空未判定")
    energy = weather.get("energy") or {}
    if _finite(energy.get("energy_wh")):
        add(
            "energy_wh",
            status="modeled",
            value=energy.get("energy_wh"),
            unit="Wh",
            reason=energy.get("status") or "",
        )
    else:
        add("energy_wh", status="unavailable", reason=energy.get("reason") or "没有标定 Wh/m，未计算能耗")
    ordered = []
    by_id = {factor["id"]: factor for factor in factors}
    for factor_id, *_rest in FACTOR_CATALOG:
        ordered.append(by_id[factor_id])
    return ordered, mid_rain


def _gaps(factors):
    gaps = []
    for factor in factors:
        if factor["status"] in {"not_evaluated", "unavailable"} or (
            factor["effect"] == "hard" and factor["threshold"] is None and factor["status"] == "modeled"
        ):
            closable = factor["id"] in {"vehicle_wind_limit", "payload_limit", "energy_wh"}
            gaps.append(
                {
                    "factor": factor["id"],
                    "why": factor["reason"] or factor["status"],
                    "to_close": "补来源或数据" if closable else "需外部数据或人工核对",
                    "closable_in_project": closable,
                }
            )
    return gaps


def _evidence_id(payload) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    return "env-" + hashlib.sha256(raw).hexdigest()[:12]


def _request_key(query: EnvQuery):
    scheduled = query.scheduled_for or ""
    return (
        round(query.origin[0], 5),
        round(query.origin[1], 5),
        round(query.destination[0], 5),
        round(query.destination[1], 5),
        scheduled,
        round(query.payload_kg if query.payload_kg is not None else -1, 2),
        query.vehicle_key or "",
        round(query.altitude_agl_m, 1),
        tuple(query.waypoints or []),
        query.airspace_snapshot_id or "",
        ALGO_VERSION,
    )


def _write_audit(record):
    day = datetime.now(UTC).strftime("%Y%m%d")
    directory = AUDIT_ROOT / day
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{record['evidence_id']}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def assess_route_environment(query: EnvQuery, *, client=None, weather=None, turn_id=None):
    key = _request_key(query)
    cached = _CACHE.get(key)
    if cached is not None and time.monotonic() - cached[0] < 300 and weather is None and client is None:
        return {**cached[1], "_cached": True}
    if weather is None:
        weather = assess_route_weather(
            query.waypoints or [query.origin, query.destination],
            query.scheduled_for,
            vehicle_key=query.vehicle_key,
            client=client,
        )
    thresholds = load_thresholds()
    factors, mid_rain = _build_factors(weather, query, thresholds)
    coverage = weather.get("coverage") or {}
    samples = weather.get("samples") or []
    weather_down = not samples or all(sample.get("status") != "ok" for sample in samples)
    verdict, reason = decide_verdict(
        factors,
        coverage,
        thresholds_all_null=thresholds_all_null(thresholds),
        weather_unavailable=weather_down,
    )
    if mid_rain and verdict == "pass":
        verdict, reason = "degraded", "端点无降水但中段有降水，且没有来源明确的降水阈值"
    if mid_rain and verdict not in {"blocked", "unknown"}:
        verdict, reason = "degraded", reason if "中段" in reason else "端点无降水但中段有降水，不能判通过"
    hard = [factor["id"] for factor in factors if factor.get("hard_failed")]
    if weather_down:
        status = "unavailable"
    elif any(sample.get("status") != "ok" for sample in samples):
        status = "partial"
    else:
        status = "ok"
    gaps = _gaps(factors)
    if mid_rain and not any(gap["factor"] == "precipitation_max" for gap in gaps):
        gaps.append(
            {
                "factor": "precipitation_max",
                "why": "中段降水高于两端，阈值未登记",
                "to_close": "补有来源的降水阈值",
                "closable_in_project": True,
            }
        )
    honesty = {
        "checked": len(factors),
        "modeled": sum(factor["status"] == "modeled" for factor in factors),
        "unavailable": sum(factor["status"] == "unavailable" for factor in factors),
        "not_evaluated": sum(factor["status"] == "not_evaluated" for factor in factors),
        "hard_failed": hard,
    }
    if honesty["checked"] != len(factors) or honesty["checked"] != len(FACTOR_CATALOG):
        raise RuntimeError("honesty.checked 必须等于因素条数")
    digest_body = {
        "algo": ALGO_VERSION,
        "request": query.model_dump(),
        "verdict": verdict,
        "factors": [
            {key: factor[key] for key in ("id", "status", "value", "hard_failed")} for factor in factors
        ],
        "coverage": {
            "sample_count": coverage.get("sample_count"),
            "independent_cells": coverage.get("independent_cells"),
        },
    }
    evidence_id = _evidence_id(digest_body)
    result = {
        "geometry_scope": "provided_route" if query.waypoints else "endpoint_corridor",
        "geometry_note": "按提供的 WGS84 航点折线采样"
        if query.waypoints
        else "仅起终点直线走廊，未绑定实际避障航线",
        "status": status,
        "verdict": verdict,
        "verdict_reason": reason,
        "coverage": coverage,
        "factors": [{key: value for key, value in factor.items() if key != "critical"} for factor in factors],
        "constraints": {"hard_failed": hard, "mid_route_precipitation": mid_rain},
        "gaps": gaps,
        "honesty": honesty,
        "provenance": weather.get("provenance") or {},
        "dispatch_enabled": False,
        "operationally_approved": False,
        "evidence_id": evidence_id,
        "samples": samples,
    }
    _EVIDENCE[evidence_id] = result
    if len(_CACHE) >= 128:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = (time.monotonic(), result)
    _write_audit(
        {
            "evidence_id": evidence_id,
            "turn_id": turn_id,
            "request": query.model_dump(),
            "result_digest": "sha256:"
            + hashlib.sha256(json.dumps(digest_body, default=str, sort_keys=True).encode()).hexdigest(),
            "factor_count": len(factors),
            "honesty": honesty,
            "provenance": result["provenance"],
            "tool_sequence": ["assess_route_environment"],
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    return result


def get_evidence(evidence_id: str):
    return _EVIDENCE.get(evidence_id)


def explain_verdict(evidence_id: str):
    found = get_evidence(evidence_id)
    if found is None:
        return {
            "status": "unavailable",
            "reason": "没有这份 evidence_id，不能重新计算",
            "evidence_id": evidence_id,
        }
    drivers = [
        factor
        for factor in found["factors"]
        if factor.get("hard_failed")
        or factor["id"] == "precipitation_max"
        and found["constraints"].get("mid_route_precipitation")
    ]
    if not drivers:
        drivers = [factor for factor in found["factors"] if factor["status"] != "modeled"][:3]
    not_reason = [
        factor["id"]
        for factor in found["factors"]
        if factor["id"] not in {item["id"] for item in drivers}
        and factor["id"] in {"wind_cross", "visibility_min", "wind_gust_10m_max"}
    ]
    return {
        "status": "ok",
        "evidence_id": evidence_id,
        "verdict": found["verdict"],
        "verdict_reason": found["verdict_reason"],
        "drivers": drivers,
        "not_the_reason": not_reason,
        "gaps": found["gaps"],
        "dispatch_enabled": False,
    }


def list_environment_gaps(evidence_id: str | None = None):
    found = get_evidence(evidence_id) if evidence_id else None
    gaps = (found or {}).get("gaps") or []
    if found is None:
        return {"status": "unavailable", "reason": "没有可解释的环境判定", "gaps": []}
    counts = {"data_missing": 0, "no_model": 0, "manual_required": 0}
    for gap in gaps:
        if gap["factor"] in {
            "airspace_notam",
            "terrain_clearance",
            "vertical_clearance",
            "diversion_reachability",
        }:
            counts["manual_required"] += 1
        elif gap["factor"] in {"cloud_base_height"}:
            counts["no_model"] += 1
        else:
            counts["data_missing"] += 1
    closable = sum(1 for gap in gaps if gap.get("closable_in_project"))
    return {
        "status": "ok",
        "gaps": gaps,
        "count_by_reason": counts,
        "statement": f"共 {len(gaps)} 项未完全判定，其中 {closable} 项可由本项目的资料补齐，{len(gaps) - closable} 项需外部数据或人工核对。",
        "dispatch_enabled": False,
    }


def clear_environment_cache():
    _CACHE.clear()
    _EVIDENCE.clear()
