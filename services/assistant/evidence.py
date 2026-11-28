"""Evidence adapters for natural-language task intakes.

Hard rule: never fabricate a value. When an upstream source cannot be reached,
return an explicit ``unavailable`` / ``unresolved`` result with a reason. The
weather values here are FORECASTS, never observations. The real-route adapter
can request the full hourly series; the frozen v0 energy model stays unchanged.
"""

from __future__ import annotations

import json
import math
import re
import time
from datetime import UTC, datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path

import httpx

from services.assistant import geocode, place_match

ROOT = Path(__file__).resolve().parents[2]
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
LOCAL_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
# Open-Meteo Forecast API hourly valid times, from
# https://open-meteo.com/en/docs "Hourly Parameter Definition":
# Instant, Preceding hour sum, Preceding hour probability, Preceding hour max.
# weather_code is documented as an instant WMO code. A linear mix is not a code,
# so it stays on the previous valid code (the historical reader).
# HOURLY_FIELDS is derived from this table; do not keep a second literal list.
FIELD_SEMANTICS = {
    "temperature_2m": "instant",
    "relative_humidity_2m": "instant",
    "wind_speed_10m": "instant",
    "wind_direction_10m": "instant",
    "wind_gusts_10m": "hourly_max",
    "surface_pressure": "instant",
    "precipitation": "hourly_accumulation",
    "visibility": "instant",
    "weather_code": "code",
    "cloud_cover": "instant",
    "cloud_cover_low": "instant",
    "cloud_cover_mid": "instant",
    "cloud_cover_high": "instant",
    "wind_speed_80m": "instant",
    "wind_direction_80m": "instant",
    "wind_speed_120m": "instant",
    "wind_direction_120m": "instant",
    "wind_speed_180m": "instant",
    "wind_direction_180m": "instant",
    "precipitation_probability": "hourly_probability",
    "dew_point_2m": "instant",
    "cape": "instant",
    "freezing_level_height": "instant",
    "temperature_80m": "instant",
    "temperature_120m": "instant",
    "temperature_180m": "instant",
}
HOURLY_FIELDS = tuple(FIELD_SEMANTICS)
_WIND_PAIRS = (
    ("wind_speed_10m", "wind_direction_10m"),
    ("wind_speed_80m", "wind_direction_80m"),
    ("wind_speed_120m", "wind_direction_120m"),
    ("wind_speed_180m", "wind_direction_180m"),
)
# The public single-point fetch keeps the existing 16-day intake window.
# Route batches must not use that window; see fetch_weather_batch.
PUBLIC_FORECAST_DAYS = 16
ROUTE_FORECAST_DAYS = 2
BATCH_POINT_LIMIT = 20
_OMITTED_FIELD_REASON = "Open-Meteo响应未包含该字段，值为null，未用邻近变量或其它高度代替"
WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def _clock(text: str) -> tuple[int, int] | None:
    number = r"[零一二三四五六七八九十两\d]{1,3}"
    match = re.search(
        rf"(凌晨|早上|上午|中午|下午|晚上)?\s*({number})(?:[:：](\d{{2}})|[点时](?:({number})分?)?(半)?)",
        text,
    )
    if not match:
        return None

    def integer(token):
        if not token:
            return 0
        if token.isdigit():
            return int(token)
        digits = {c: n for n, c in enumerate("零一二三四五六七八九")}
        digits["两"] = 2
        if "十" in token:
            tens, ones = token.split("十", 1)
            return (digits.get(tens, 1) * 10) + digits.get(ones, 0)
        return digits[token]

    hour = integer(match[2])
    minute = 30 if match[5] else integer(match[3] or match[4])
    period = match[1]
    if period:
        if not 0 <= hour <= 12:
            raise ValueError("中文时段的小时应在0到12之间")
        if period in {"下午", "晚上"} and hour < 12:
            hour += 12
        elif period == "中午" and hour < 11:
            hour += 12
        elif period in {"凌晨", "上午", "早上"} and hour == 12:
            hour = 0
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError("时刻无效")
    return hour, minute


def parse_schedule(text: str, now: datetime | None = None) -> tuple[str | None, str]:
    """Resolve a coarse Chinese time expression into an ISO instant + its rule.

    The rule is always returned as text so the UI can show *why* a date was
    picked. Nothing is guessed when the expression is absent.
    """
    now = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ)
    try:
        clock = _clock(text)
    except (ValueError, KeyError):
        return None, "时刻无效，请确认小时和分钟"
    hour, minute = clock if clock is not None else (9, 0)
    base = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    time_note = f"{hour:02d}:{minute:02d} Asia/Shanghai" + ("（默认时间，待确认）" if clock is None else "")

    date = re.search(r"(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", text)
    if date:
        month, day = int(date[2]), int(date[3])
        year = int(date[1]) if date[1] else now.year + (month < now.month)
        try:
            target = base.replace(year=year, month=month, day=day)
        except ValueError:
            return None, f"{year}年{month}月{day}日不是有效日期，未采用"
        return target.isoformat(), f"按 {target.date()} {time_note}（年份取 {year}）"

    match = re.search(r"(?:下周|下个星期|下星期)\s*([一二三四五六日天1-7])?", text)
    if match:
        monday = base - timedelta(days=base.weekday()) + timedelta(days=7)
        token = match.group(1)
        if token:
            offset = WEEKDAYS[token] if token in WEEKDAYS else int(token) - 1
            target = monday + timedelta(days=offset)
            note = (
                f"「{match.group(0)}」按下一个自然周一起算（{monday.date()}），"
                f"取第 {offset + 1} 天 {target.date()}，{time_note}"
            )
        else:
            target = monday
            note = f"「下周」未指定具体日，暂按下周一 {target.date()} {time_note} 计"
        return target.isoformat(), note

    for word, days in (("后天", 2), ("明天", 1)):
        if word in text:
            target = base + timedelta(days=days)
            return target.isoformat(), f"「{word}」按 {target.date()} {time_note} 计"

    return None, "未识别到时间，按未指定处理"


def unavailable_weather(reason: str, scheduled_for: str | None = None) -> dict:
    return {
        "status": "unavailable",
        "kind": "forecast",
        "source": "Open-Meteo / hourly forecast",
        "scheduled_for": scheduled_for,
        "valid_for": None,
        "values": {},
        "reason": reason,
        "note": "模式预报值，不是实测；天气不可用时不填默认风速。",
    }


_WEATHER_CACHE: dict[tuple, tuple[float, dict]] = {}
_WEATHER_TTL_S = 120.0


def _finite_number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def read_hourly_value(hourly: dict, field: str, index: int) -> float | None:
    """Read one returned sample. Missing or invalid stays None; nothing is substituted."""
    if not isinstance(hourly, dict) or field not in hourly:
        return None
    series = hourly[field]
    if not isinstance(series, list):
        raise ValueError("hourly weather fields must be arrays")
    if index >= len(series):
        return None
    value = _finite_number(series[index])
    if value is None:
        return None
    if (field.startswith("wind_speed_") or field == "wind_gusts_10m") and value < 0:
        return None
    if field.startswith("wind_direction_") and not 0 <= value <= 360:
        return None
    return value


def _value_at(field: str, left: int, right: int, ratio: float, read) -> float | None:
    """Dispatch one field by FIELD_SEMANTICS.

    Preceding-hour quantities are labeled at the hour end. An exact hour keeps
    that label. A mid-hour keeps the containing hour's sum, probability, or
    maximum and does not blend it with the adjacent hour.
    """
    kind = FIELD_SEMANTICS[field]
    start = read(field, left)
    end = read(field, right)
    if kind == "code":
        return start
    if kind == "instant":
        if start is None or end is None:
            return None
        return start if left == right else start + ratio * (end - start)
    if left == right or ratio == 0.0:
        return start
    return end


def _apply_wind_vectors(values: dict, left: int, right: int, ratio: float, read) -> None:
    """One vector interpolation for every documented wind-height pair."""
    for speed_field, direction_field in _WIND_PAIRS:
        speeds = [read(speed_field, index) for index in (left, right)]
        directions = [read(direction_field, index) for index in (left, right)]
        if any(item is None for item in speeds + directions):
            continue
        east, north = [], []
        for speed, direction in zip(speeds, directions, strict=True):
            east.append(-speed * math.sin(math.radians(direction)))
            north.append(-speed * math.cos(math.radians(direction)))
        u = east[0] + ratio * (east[1] - east[0])
        v = north[0] + ratio * (north[1] - north[0])
        values[speed_field] = math.hypot(u, v)
        values[direction_field] = math.degrees(math.atan2(-u, -v)) % 360


def forecast_times(forecast: dict) -> list[datetime]:
    """Parse hourly timestamps with the payload offset, never the host timezone."""
    hourly = forecast.get("hourly") or {}
    if not isinstance(hourly, dict):
        raise ValueError("hourly must be an object")
    offset = timezone(timedelta(seconds=float(forecast.get("utc_offset_seconds", 0))))
    raw_times = hourly.get("time")
    if (
        not isinstance(raw_times, list)
        or not raw_times
        or not all(isinstance(item, str) for item in raw_times)
    ):
        raise ValueError("hourly timestamps must be a nonempty list of ISO strings")
    times = []
    for raw in raw_times:
        item = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        times.append(item.replace(tzinfo=offset) if item.tzinfo is None else item)
    if any(later <= earlier for earlier, later in pairwise(times)):
        raise ValueError("forecast timestamps must be strictly increasing")
    return times


def interpolate_forecast(forecast: dict, when: datetime) -> dict[str, float | None]:
    """Resolve an hourly series at one aware instant.

    Instants, including wind, interpolate. Wind direction uses the shared
    vector method across the 0/360 seam. Preceding-hour precipitation,
    probability, and gusts keep that hour's own quantity. Weather codes keep
    the previous valid code. Missing observations stay None. No extrapolation.
    """
    if when.tzinfo is None:
        raise ValueError("interpolation instant must have a timezone")
    hourly = forecast.get("hourly") or {}
    times = forecast_times(forecast)
    if not times[0] <= when <= times[-1]:
        raise ValueError("forecast does not cover instant")
    right = next(index for index, value in enumerate(times) if value >= when)
    left = max(0, right - 1) if times[right] != when else right
    span = (times[right] - times[left]).total_seconds()
    ratio = 0.0 if left == right else (when - times[left]).total_seconds() / span

    def read(field, index):
        return read_hourly_value(hourly, field, index)

    values = {field: _value_at(field, left, right, ratio, read) for field in HOURLY_FIELDS}
    _apply_wind_vectors(values, left, right, ratio, read)
    return values


def values_at(forecast: dict, when: datetime) -> dict[str, float | None]:
    """Semantically resolved values at one instant. Missing stays None."""
    return interpolate_forecast(forecast, when)


def _envelope_indices(times: list[datetime], start: datetime, end: datetime) -> list[int]:
    """Hour labels whose valid interval overlaps ``[start, end]``, plus instant brackets."""
    if not times or end < start:
        return []
    step = times[1] - times[0] if len(times) > 1 else timedelta(hours=1)
    chosen = set()
    for index, stamp in enumerate(times):
        previous = times[index - 1] if index else stamp - step
        if stamp >= start and previous < end:
            chosen.add(index)
        if start <= stamp <= end:
            chosen.add(index)
    not_after = [index for index, stamp in enumerate(times) if stamp <= start]
    not_before = [index for index, stamp in enumerate(times) if stamp >= end]
    if not_after:
        chosen.add(not_after[-1])
    if not_before:
        chosen.add(not_before[0])
    return sorted(chosen)


def raw_values_covering(forecast: dict, start: datetime, end: datetime) -> list[dict]:
    """Raw hourly samples overlapping a leg. Not interpolated and not averaged."""
    try:
        times = forecast_times(forecast)
        hourly = forecast.get("hourly") or {}
        if not isinstance(hourly, dict):
            return []
    except (TypeError, ValueError, OverflowError):
        return []
    rows = []
    for index in _envelope_indices(times, start, end):
        row = {}
        for field in HOURLY_FIELDS:
            try:
                row[field] = read_hourly_value(hourly, field, index)
            except ValueError:
                row[field] = None
        rows.append(row)
    return rows


def _omitted_fields(hourly: dict) -> dict[str, str]:
    if not isinstance(hourly, dict):
        return {}
    return {field: _OMITTED_FIELD_REASON for field in HOURLY_FIELDS if field not in hourly}


def _hourly_arrays_match(hourly: dict) -> bool:
    times = hourly.get("time") if isinstance(hourly, dict) else None
    if not isinstance(times, list) or not times:
        return False
    width = len(times)
    for field in HOURLY_FIELDS:
        if field not in hourly:
            continue
        series = hourly[field]
        if not isinstance(series, list) or len(series) != width:
            return False
    return True


def _aware_target(scheduled_for: str | None) -> datetime:
    target = (
        datetime.fromisoformat(scheduled_for.replace("Z", "+00:00"))
        if scheduled_for
        else datetime.now(LOCAL_TZ)
    )
    target = target.replace(tzinfo=LOCAL_TZ) if target.tzinfo is None else target
    return target


def _valid_point(latitude: float, longitude: float) -> bool:
    return (
        all(math.isfinite(value) for value in (latitude, longitude))
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    )


def _forecast_note() -> str:
    return (
        "Open-Meteo模式预报，非实测。瞬时量按时刻插值，风向用向量；"
        "降水、降水概率和阵风保留所在小时的累计、概率或最大，不把相邻小时线性拆开。"
        "风速 m/s，风向为气象来向°。接口未返回的字段为 null。10 m 风不能代表飞行高度风场。"
    )


def _result_from_payload(
    payload: dict,
    latitude: float,
    longitude: float,
    target: datetime,
    scheduled_for,
    *,
    include_hourly: bool,
    forecast_days: int,
) -> dict:
    hourly = payload.get("hourly") or {}
    if not isinstance(payload, dict) or not isinstance(hourly, dict) or not _hourly_arrays_match(hourly):
        return unavailable_weather("气象服务逐时数组长度不一致或格式无效，整段结果不可用", scheduled_for)
    forecast = {"hourly": hourly, "utc_offset_seconds": payload.get("utc_offset_seconds", 0)}
    try:
        values = values_at(forecast, target)
    except (ValueError, TypeError, OverflowError):
        return unavailable_weather(
            f"预报窗口（最多{forecast_days}天）不覆盖该时刻或逐时数据无效", scheduled_for
        )
    omitted = _omitted_fields(hourly)
    note = _forecast_note()
    if omitted:
        note += "未返回字段：" + "、".join(omitted) + "。值为 null，未用邻近变量或其它高度代替。"
    result = {
        "status": "ok",
        "kind": "forecast",
        "source": "Open-Meteo / hourly forecast",
        "scheduled_for": scheduled_for,
        "valid_for": target.astimezone(UTC).isoformat(),
        "requested_point": [longitude, latitude],
        "fetched_at": datetime.now(UTC).isoformat(),
        "values": values,
        "reason": "",
        "note": note,
    }
    if include_hourly:
        result.update(forecast)
        result["hourly_units"] = payload.get("hourly_units") or {}
        result["model_point"] = [payload.get("longitude"), payload.get("latitude")]
        result["omitted_fields"] = omitted
        result["forecast_days"] = forecast_days
    return result


def _cache_key(*parts):
    return (*parts, HOURLY_FIELDS)


def _fetch_weather_forecast(
    latitude: float,
    longitude: float,
    scheduled_for: str | None = None,
    *,
    client: httpx.Client | None = None,
    include_hourly: bool = False,
    forecast_days: int = PUBLIC_FORECAST_DAYS,
) -> dict:
    """Fetch an hourly forecast resolved at the requested aware instant.

    A naive input is interpreted as Asia/Shanghai for compatibility with intakes.
    The default instant is now, never the API's first sample. Wind speeds are
    requested in m/s. The single-point default remains 16 forecast days.
    """
    try:
        target = _aware_target(scheduled_for)
        if not isinstance(forecast_days, int) or isinstance(forecast_days, bool) or forecast_days < 1:
            raise ValueError("invalid forecast_days")
        if not _valid_point(latitude, longitude):
            raise ValueError("invalid coordinates")
    except (ValueError, TypeError, AttributeError):
        return unavailable_weather("气象查询的坐标、日期或预报天数无效", scheduled_for)
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(HOURLY_FIELDS),
        "forecast_days": forecast_days,
        "timezone": "UTC",
        "wind_speed_unit": "ms",
    }
    try:
        if client is None:
            created, _proxy_used = _meteo_client(8)
            with created:
                response = created.get(OPEN_METEO, params=params)
        else:
            response = client.get(OPEN_METEO, params=params)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return unavailable_weather("气象服务当前不可达，未填任何数值", scheduled_for)
    if isinstance(payload, list):
        if len(payload) != 1 or not isinstance(payload[0], dict):
            return unavailable_weather("气象服务返回的地点数量与请求不一致", scheduled_for)
        payload = payload[0]
    if not isinstance(payload, dict):
        return unavailable_weather("气象服务返回格式无效", scheduled_for)
    return _result_from_payload(
        payload,
        latitude,
        longitude,
        target,
        scheduled_for,
        include_hourly=include_hourly,
        forecast_days=forecast_days,
    )


def fetch_weather_forecast(
    latitude: float,
    longitude: float,
    scheduled_for: str | None = None,
    *,
    client: httpx.Client | None = None,
    include_hourly: bool = False,
    forecast_days: int = PUBLIC_FORECAST_DAYS,
) -> dict:
    """Cached wrapper: an unreachable Open-Meteo must not cost 8 s twice.

    The cache key includes forecast days and the requested hourly fields.
    Failures stay cached for two minutes so a repeated timeout does not burn
    the tool budget. A caller-supplied client bypasses the cache.
    """
    if client is not None:
        return _fetch_weather_forecast(
            latitude,
            longitude,
            scheduled_for,
            client=client,
            include_hourly=include_hourly,
            forecast_days=forecast_days,
        )
    key = _cache_key(round(latitude, 4), round(longitude, 4), scheduled_for, include_hourly, forecast_days)
    now = time.monotonic()
    hit = _WEATHER_CACHE.get(key)
    if hit and now - hit[0] < _WEATHER_TTL_S:
        return hit[1]
    result = _fetch_weather_forecast(
        latitude,
        longitude,
        scheduled_for,
        include_hourly=include_hourly,
        forecast_days=forecast_days,
    )
    _WEATHER_CACHE[key] = (now, result)
    return result


def _chunk_payloads(payload, count: int) -> list[dict] | None:
    if count == 1 and isinstance(payload, dict):
        return [payload]
    if (
        not isinstance(payload, list)
        or len(payload) != count
        or not all(isinstance(item, dict) for item in payload)
    ):
        return None
    return payload


def _forecast_window(target: datetime, forecast_days: int) -> dict:
    """Use forecast_days unless the instant is beyond that horizon.

    A departure on day 3 or later is requested with start_date/end_date for the
    departure day and the next day. This does not reopen a 16-day window.
    """
    if target > datetime.now(UTC) + timedelta(days=forecast_days):
        start = target.astimezone(UTC).date()
        end = start + timedelta(days=1)
        return {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": "UTC",
            "wind_speed_unit": "ms",
        }
    return {"forecast_days": forecast_days, "timezone": "UTC", "wind_speed_unit": "ms"}


def _meteo_client(timeout):
    """Honor AERIS_METEO_PROXY. Empty string forces a direct connection.

    The proxy URL is never returned. Callers only see direct/configured/trust_env.
    """
    import os

    proxy = os.environ.get("AERIS_METEO_PROXY")
    if proxy is None:
        return httpx.Client(timeout=timeout, trust_env=True), "trust_env"
    if proxy == "":
        return httpx.Client(timeout=timeout, trust_env=False), "direct"
    return httpx.Client(timeout=timeout, trust_env=False, proxy=proxy), "configured"


def _read_response(client, params):
    """One request, plus a single 2 s retry when the server returns HTTP 429."""
    started = time.perf_counter()
    response = None
    for attempt in (0, 1):
        response = client.get(OPEN_METEO, params=params)
        if response.status_code == 429 and attempt == 0:
            time.sleep(2)
            continue
        break
    elapsed = time.perf_counter() - started
    body = response.content if response is not None else b""
    return response, elapsed, len(body)


def _fetch_chunk(
    latitudes,
    longitudes,
    scheduled_for,
    target,
    *,
    forecast_days: int,
    client,
    include_hourly: bool,
    batch_index: int,
    timeout_s: float,
):
    params = {
        "latitude": ",".join(str(value) for value in latitudes),
        "longitude": ",".join(str(value) for value in longitudes),
        "hourly": ",".join(HOURLY_FIELDS),
        **_forecast_window(target, forecast_days),
    }
    stats = {
        "batch_index": batch_index,
        "point_count": len(latitudes),
        "elapsed_s": None,
        "response_bytes": None,
        "forecast_days": params.get("forecast_days"),
        "start_date": params.get("start_date"),
        "end_date": params.get("end_date"),
        "cache_hit": False,
    }
    try:
        if client is None:
            created, proxy_used = _meteo_client(timeout_s)
            with created:
                response, elapsed, nbytes = _read_response(created, params)
        else:
            proxy_used = "caller"
            response, elapsed, nbytes = _read_response(client, params)
        stats["proxy_used"] = proxy_used
        stats["elapsed_s"] = elapsed
        stats["response_bytes"] = nbytes
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None, "气象服务当前不可达或超时，该批不可用，未改用其它源", stats
    rows = _chunk_payloads(payload, len(latitudes))
    if rows is None:
        return None, "气象服务返回的地点数量与请求不一致，整批不可用", stats
    if any(not _hourly_arrays_match(row.get("hourly") or {}) for row in rows):
        return None, "气象服务逐时数组长度不一致，整批不可用", stats
    parsed = []
    for row, latitude, longitude in zip(rows, latitudes, longitudes, strict=True):
        item = _result_from_payload(
            row,
            latitude,
            longitude,
            target,
            scheduled_for,
            include_hourly=include_hourly,
            forecast_days=forecast_days,
        )
        item["model"] = row.get("model") if isinstance(row.get("model"), str) else None
        item["request_stats"] = dict(stats)
        parsed.append(item)
    return parsed, "", stats


def fetch_weather_batch(
    latitudes,
    longitudes,
    scheduled_for: str | None = None,
    *,
    forecast_days: int = ROUTE_FORECAST_DAYS,
    client: httpx.Client | None = None,
    include_hourly: bool = True,
    batch_size: int = BATCH_POINT_LIMIT,
    timeout_s: float = 8.0,
) -> list[dict]:
    """Fetch many points, at most 20 per request, defaulting to 2 forecast days.

    A length or count mismatch makes the whole batch unavailable. A requested
    field the API omits stays null with a reason and is never replaced by a
    nearby field. ``model_point`` is the returned grid point. Requests are
    issued one batch at a time, so in-flight requests stay at or below 3.
    """
    latitudes = list(latitudes)
    longitudes = list(longitudes)
    count = max(len(latitudes), len(longitudes))
    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or not 1 <= batch_size <= BATCH_POINT_LIMIT
    ):
        batch_size = BATCH_POINT_LIMIT
    if len(latitudes) != len(longitudes) or count == 0:
        return [
            unavailable_weather("批量坐标数量不一致，未请求气象", scheduled_for) for _ in range(count or 1)
        ]
    try:
        target = _aware_target(scheduled_for)
        if not isinstance(forecast_days, int) or isinstance(forecast_days, bool) or forecast_days < 1:
            raise ValueError("invalid forecast_days")
        if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or timeout_s <= 0:
            raise ValueError("invalid timeout")
        if not all(_valid_point(lat, lon) for lat, lon in zip(latitudes, longitudes, strict=True)):
            raise ValueError("invalid coordinates")
    except (ValueError, TypeError, AttributeError):
        return [unavailable_weather("气象查询的坐标、日期或预报天数无效", scheduled_for) for _ in latitudes]

    window = _forecast_window(target, forecast_days)
    results: list[dict | None] = [None] * count
    batch_index = 0
    for start in range(0, count, batch_size):
        stop = min(count, start + batch_size)
        chunk_lats = latitudes[start:stop]
        chunk_lons = longitudes[start:stop]
        cache_key = None
        if client is None:
            cache_key = _cache_key(
                tuple(round(value, 4) for value in chunk_lats),
                tuple(round(value, 4) for value in chunk_lons),
                scheduled_for,
                include_hourly,
                forecast_days,
                tuple(sorted(window.items())),
                "batch",
            )
            hit = _WEATHER_CACHE.get(cache_key)
            if hit and time.monotonic() - hit[0] < _WEATHER_TTL_S:
                cached = []
                for item in hit[1]:
                    copy = dict(item)
                    stats = dict(copy.get("request_stats") or {})
                    stats["cache_hit"] = True
                    stats["elapsed_s"] = None
                    copy["request_stats"] = stats
                    cached.append(copy)
                results[start:stop] = cached
                batch_index += 1
                continue
        parsed, reason, _stats = _fetch_chunk(
            chunk_lats,
            chunk_lons,
            scheduled_for,
            target,
            forecast_days=forecast_days,
            client=client,
            include_hourly=include_hourly,
            batch_index=batch_index,
            timeout_s=float(timeout_s),
        )
        if parsed is None:
            return [unavailable_weather(reason, scheduled_for) for _ in latitudes]
        if cache_key is not None:
            _WEATHER_CACHE[cache_key] = (time.monotonic(), parsed)
        results[start:stop] = parsed
        batch_index += 1
    return results


def count_independent_cells(samples) -> int:
    """Count distinct API-returned ``model_point`` values. No second identity scheme."""
    seen = []
    for sample in samples or []:
        point = sample.get("model_point") if isinstance(sample, dict) else None
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            key = (float(point[0]), float(point[1]))
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in key) or key in seen:
            continue
        seen.append(key)
    return len(seen)


def list_airspace_zones() -> dict:
    """Read the repository's draft restriction zones; never claim real airspace."""
    try:
        raw = json.loads((ROOT / "scenarios/v0/zones.geojson").read_text(encoding="utf-8"))
        zones = []
        for feature in raw["features"]:
            props = feature.get("properties", {})
            zones.append(
                {
                    "id": props.get("id"),
                    "kind": props.get("kind"),
                    "alt_min_m": props.get("alt_min_m"),
                    "alt_max_m": props.get("alt_max_m"),
                    "status": "draft",
                }
            )
    except (OSError, ValueError, KeyError):
        zones = []
    return {
        "status": "draft",
        "source": "scenarios/v0/zones.geojson",
        "crs": "local ENU / m",
        "is_simulated": True,
        "zones": zones,
        "note": "仿真草稿，非实测空域；未接入 NOTAM / 官方空域数据，不能用于安全判定。",
    }


def extract_confirmations(text: str) -> dict:
    """Pull ONLY values the user stated explicitly; never infer a missing one.

    Models do not reliably map a follow-up sentence into a JSON schema. This
    rule-based fallback keeps the multi-turn clarification loop deterministic.
    """
    result: dict = {}
    try:
        clock = _clock(text)
    except (ValueError, KeyError):
        clock = None
    parsed, note = parse_schedule(text)
    if clock is not None and parsed is not None:
        result.update(scheduled_for=parsed, schedule_note=note, schedule_confirmed=True)
    for field, pattern in (
        ("origin_point", r"起点(?:坐标|位置)?\s*[:：]?\s*(-?\d+\.\d+)\s*[,，]\s*(-?\d+\.\d+)"),
        ("destination_point", r"终点(?:坐标|位置)?\s*[:：]?\s*(-?\d+\.\d+)\s*[,，]\s*(-?\d+\.\d+)"),
    ):
        found = re.search(pattern, text)
        if found:
            lng, lat = float(found.group(1)), float(found.group(2))
            if -180 <= lng <= 180 and -85.0511 <= lat <= 85.0511:
                result[field] = [lng, lat]
    payload = re.search(r"载荷\s*(?:重量|是|为)?\s*(\d+(?:\.\d+)?)\s*(?:公斤|千克|kg)", text, re.I)
    if payload:
        result["payload_kg"] = float(payload.group(1))
    if re.search(r"\bP1\b|应急|紧急", text):
        result["priority"] = "P1"
    elif re.search(r"\bP2\b|常规", text):
        result["priority"] = "P2"
    if result.get("origin_point") and result.get("destination_point"):
        result["places_confirmed"] = True
    return result


def resolve_place(
    name: str,
    *,
    local_places: dict | None = None,
    aliases: dict | None = None,
    client: httpx.Client | None = None,
) -> dict:
    """Resolve a place name to coordinates, refusing to invent any."""
    key = (aliases or {}).get(name.strip(), name.strip())
    point = (local_places or {}).get(key)
    if point is not None:
        return {
            "status": "ok",
            "name": name,
            "point": list(point),
            "crs": "local ENU / m",
            "source": "仓库虚拟S1-01场景地点表",
            "address": "场景登记地点（仿真，非真实地址）",
            "is_simulated": True,
        }
    try:
        rows, provider = geocode.lookup(name, 5)
        if rows:
            decision = place_match.resolve(name, rows)
            if decision["status"] == "ok":
                best = decision["best"]
                return {
                    "status": "ok",
                    "name": best["name"],
                    "point": list(best["point"]),
                    "crs": "EPSG:4326",
                    "source": provider,
                    "address": best.get("address", ""),
                    "is_simulated": False,
                    "match": {
                        "query": name,
                        "score": decision["score"],
                        "confidence": decision["confidence"],
                    },
                    "candidates": decision.get("candidates", []),
                    "alternatives": decision.get("alternatives", []),
                    "note": (
                        "按名称精确匹配选中；如实际起降点在别的校区，请在确认卡里改。"
                        if decision["confidence"] == "high"
                        else "名称不是完全一致，请核对确认卡里的坐标。"
                    ),
                }
            return {
                "status": decision["status"],
                "name": name,
                "point": None,
                "crs": "unresolved",
                "source": provider,
                "address": decision.get("note", ""),
                "is_simulated": False,
                "candidates": decision.get("candidates", []),
            }
    except Exception:
        pass
    return {
        "status": "unresolved",
        "name": name,
        "point": None,
        "crs": "unresolved",
        "source": "未解析；未猜测坐标",
        "address": "",
        "is_simulated": True,
    }
