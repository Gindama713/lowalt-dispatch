/**
 * 免密钥公开气象数据适配层。
 *
 * 数据源：
 * - Open-Meteo 当前天气（公开、免 key，仅作演示参考，不是航空气象报文）
 * - RainViewer 公开雷达拼图（公开、免 key，雷达回波为演示叠加）
 *
 * 所有请求都带超时与中文错误信息，调用方只需 try/catch；本模块不会产生
 * 未处理的 Promise rejection。
 */

import type { LngLat } from "./geo";

const WEATHER_ENDPOINT = "https://api.open-meteo.com/v1/forecast";
const RADAR_ENDPOINT = "https://api.rainviewer.com/public/weather-maps.json";
const REQUEST_TIMEOUT_MS = 9000;
const FALLBACK_RADAR_HOST = "https://tilecache.rainviewer.com";
export const WEATHER_REFRESH_MS = 15 * 60 * 1000;
export const RADAR_TILE_ZOOM = 7;
// Shanghai and the surrounding Yangtze River Delta. CMA GRAPES has a 0.125° model grid.
export const WIND_REGION = {
  west: 117.5,
  east: 125.5,
  south: 28.25,
  north: 34.25,
};
const WIND_GRID_SIZE = 11;

export type WeatherSnapshot = {
  temperatureC: number | null;
  windSpeedMs: number | null;
  windDirDeg: number | null;
  gustMs: number | null;
  cloudPct: number | null;
  precipMm: number | null;
  visibilityM: number | null;
  code: number | null;
  validAt: string;
};

export type RadarFrame = {
  time: number;
  tiles: string;
  host: string;
};

export type WindField = {
  validAt: string;
  vectors: [east: number, north: number][];
};

type OpenMeteoCore = {
  time?: string;
  temperature_2m?: number;
  wind_speed_10m?: number;
  wind_direction_10m?: number;
  wind_gusts_10m?: number;
  cloud_cover?: number;
  precipitation?: number;
  weather_code?: number;
  visibility?: number;
};

type OpenMeteoResponse = {
  location_id?: number;
  current?: OpenMeteoCore;
  current_units?: Record<string, string | undefined>;
  hourly?: { time?: string[]; visibility?: (number | null)[] };
  hourly_units?: Record<string, string | undefined>;
};

type RainViewerResponse = {
  host?: string;
  radar?: { past?: { time?: number; path?: string }[] };
};

const finiteOrNull = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const round = (value: number | null, digits = 1): number | null =>
  value === null ? null : Number(value.toFixed(digits));

/**
 * 统一请求包装：超时、HTTP 状态和网络异常都转成中文 Error。
 * @param label 用于拼接“XX暂不可用”的人类可读名称
 */
async function requestJson<T>(
  url: string,
  label: string,
  signal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const forwardAbort = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", forwardAbort, { once: true });
  }
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`${label}返回 HTTP ${response.status}`);
    return (await response.json()) as T;
  } catch (error) {
    if (signal?.aborted) throw new Error(`${label}请求已取消`);
    if (error instanceof Error && error.name === "AbortError")
      throw new Error(`${label}响应超时，请稍后重试`);
    if (error instanceof Error && error.message.startsWith(label)) throw error;
    throw new Error(`${label}暂不可用，请检查网络后重试`);
  } finally {
    window.clearTimeout(timer);
    signal?.removeEventListener("abort", forwardAbort);
  }
}

const speedToMs = (value: number | null, unit: string | undefined) => {
  if (value === null) return null;
  if (unit === "km/h") return value / 3.6;
  if (unit === "mph") return value * 0.44704;
  if (unit === "kn") return value * 0.514444;
  return value;
};

const visibilityToM = (value: number | null, unit: string | undefined) => {
  if (value === null) return null;
  if (unit === "km") return value * 1000;
  return value;
};

/**
 * 当前小时能见度：Open-Meteo 的 visibility 只存在于 hourly，
 * 因此按 current.time 在 hourly.time 中定位同一小时。
 */
function pickVisibility(response: OpenMeteoResponse): number | null {
  const unit = response.hourly_units?.visibility;
  const direct = finiteOrNull(response.current?.visibility);
  if (direct !== null) return visibilityToM(direct, unit);
  const times = response.hourly?.time;
  const values = response.hourly?.visibility;
  if (!Array.isArray(times) || !Array.isArray(values)) return null;
  const currentTime = response.current?.time;
  if (!currentTime) {
    const last = values.at(-1);
    return visibilityToM(finiteOrNull(last), unit);
  }
  // hourly.time 与 current.time 都是“本地时间、整点”，字符串比较即可。
  const currentHour = currentTime.slice(0, 13);
  let index = times.findIndex((t) => t.slice(0, 13) === currentHour);
  if (index < 0) {
    // target ES2022 不含 findLastIndex，手动回退到最近整点。
    for (let i = times.length - 1; i >= 0; i -= 1) {
      if (times[i].slice(0, 13) <= currentHour) {
        index = i;
        break;
      }
    }
  }
  if (index < 0) return null;
  return visibilityToM(finiteOrNull(values[index]), unit);
}

/**
 * 获取指定经纬度的当前气象（风、阵风、能见度、云量、降水、温度）。
 * 网络/解析失败时抛出中文 Error，不产生未捕获异常。
 */
export async function fetchWeather(
  lng: number,
  lat: number,
  signal?: AbortSignal,
): Promise<WeatherSnapshot> {
  if (!Number.isFinite(lng) || !Number.isFinite(lat))
    throw new Error("气象坐标不合法");
  const params = new URLSearchParams({
    latitude: lat.toFixed(5),
    longitude: lng.toFixed(5),
    current:
      "temperature_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,cloud_cover,precipitation,weather_code",
    hourly: "visibility",
    timezone: "GMT",
    forecast_days: "1",
  });
  const data = await requestJson<OpenMeteoResponse>(
    `${WEATHER_ENDPOINT}?${params.toString()}`,
    "气象服务",
    signal,
  );
  const current = data.current;
  const validTime = Date.parse(`${current?.time}Z`);
  if (!current || !Number.isFinite(validTime))
    throw new Error("气象服务返回数据不完整");
  const windUnit = data.current_units?.wind_speed_10m;
  const gustUnit = data.current_units?.wind_gusts_10m;
  return {
    temperatureC: round(finiteOrNull(current.temperature_2m)),
    windSpeedMs: round(
      speedToMs(finiteOrNull(current.wind_speed_10m), windUnit),
    ),
    windDirDeg: round(finiteOrNull(current.wind_direction_10m), 0),
    gustMs: round(speedToMs(finiteOrNull(current.wind_gusts_10m), gustUnit)),
    cloudPct: round(finiteOrNull(current.cloud_cover), 0),
    precipMm: round(finiteOrNull(current.precipitation), 2),
    visibilityM: round(pickVisibility(data), 0),
    code: round(finiteOrNull(current.weather_code), 0),
    validAt: new Date(validTime).toISOString(),
  };
}

export async function fetchWindField(signal: AbortSignal): Promise<WindField> {
  const { west, east, south, north } = WIND_REGION;
  const points = Array.from({ length: WIND_GRID_SIZE ** 2 }, (_, i) => [
    west + ((i % WIND_GRID_SIZE) * (east - west)) / (WIND_GRID_SIZE - 1),
    south +
      (Math.floor(i / WIND_GRID_SIZE) * (north - south)) / (WIND_GRID_SIZE - 1),
  ]);
  const params = new URLSearchParams({
    latitude: points.map((p) => p[1]).join(","),
    longitude: points.map((p) => p[0]).join(","),
    models: "cma_grapes_global",
    current: "wind_speed_10m,wind_direction_10m",
    wind_speed_unit: "ms",
    timezone: "GMT",
    cell_selection: "nearest",
  });
  const data = await requestJson<OpenMeteoResponse[]>(
    `${WEATHER_ENDPOINT}?${params}`,
    "区域风场",
    signal,
  );
  if (!Array.isArray(data) || data.length !== points.length)
    throw new Error("区域风场返回网格不完整");
  const time = data[0]?.current?.time;
  const validTime = Date.parse(`${time}Z`);
  if (!Number.isFinite(validTime)) throw new Error("区域风场缺少有效时间");
  const vectors: WindField["vectors"] = new Array(points.length);
  data.forEach((sample, i) => {
    const id = sample?.location_id ?? i;
    const speed = finiteOrNull(sample?.current?.wind_speed_10m);
    const direction = finiteOrNull(sample?.current?.wind_direction_10m);
    if (
      !Number.isInteger(id) ||
      id < 0 ||
      id >= points.length ||
      vectors[id] ||
      sample?.current?.time !== time ||
      speed === null ||
      speed < 0 ||
      direction === null
    )
      throw new Error("区域风场返回网格不完整");
    // Meteorological direction is where the wind comes from. Draw where it goes.
    const radians = (direction * Math.PI) / 180;
    vectors[id] = [-speed * Math.sin(radians), -speed * Math.cos(radians)];
  });
  return { validAt: new Date(validTime).toISOString(), vectors };
}

export function sampleWind(
  field: WindField,
  [lng, lat]: LngLat,
): [number, number] | null {
  const { west, east, south, north } = WIND_REGION;
  if (lng < west || lng > east || lat < south || lat > north) return null;
  const x = ((lng - west) / (east - west)) * (WIND_GRID_SIZE - 1);
  const y = ((lat - south) / (north - south)) * (WIND_GRID_SIZE - 1);
  const col = Math.min(Math.floor(x), WIND_GRID_SIZE - 2);
  const row = Math.min(Math.floor(y), WIND_GRID_SIZE - 2);
  const i = row * WIND_GRID_SIZE + col;
  const v = field.vectors;
  const mix = (a: number, b: number, t: number) => a + (b - a) * t;
  const component = (k: 0 | 1) =>
    mix(
      mix(v[i][k], v[i + 1][k], x - col),
      mix(v[i + WIND_GRID_SIZE][k], v[i + WIND_GRID_SIZE + 1][k], x - col),
      y - row,
    );
  return [component(0), component(1)];
}

export async function fetchRadarFrame(
  signal?: AbortSignal,
): Promise<RadarFrame> {
  const data = await requestJson<RainViewerResponse>(
    RADAR_ENDPOINT,
    "雷达服务",
    signal,
  );
  const past = Array.isArray(data.radar?.past) ? data.radar.past : [];
  const usable = past.filter(
    (frame): frame is { time: number; path: string } =>
      typeof frame.time === "number" &&
      Number.isFinite(frame.time) &&
      typeof frame.path === "string" &&
      frame.path.startsWith("/"),
  );
  const latest = usable.reduce<(typeof usable)[number] | undefined>(
    (best, frame) => (!best || frame.time > best.time ? frame : best),
    undefined,
  );
  if (!latest) throw new Error("雷达服务暂无可用帧");
  const host =
    typeof data.host === "string" && data.host.startsWith("http")
      ? data.host.replace(/\/+$/, "")
      : FALLBACK_RADAR_HOST;
  return {
    host,
    time: latest.time,
    tiles: `${host}${latest.path}/256/{z}/{x}/{y}/2/1_1.png`,
  };
}

export async function hasRadarCoverage(
  host: string,
  [lng, lat]: LngLat,
  signal: AbortSignal,
) {
  const size = 2 ** RADAR_TILE_ZOOM;
  const x = (((lng + 180) / 360) * size + size) % size;
  const radians = (Math.max(-85, Math.min(85, lat)) * Math.PI) / 180;
  const y = ((1 - Math.asinh(Math.tan(radians)) / Math.PI) / 2) * size;
  const response = await fetch(
    `${host}/v2/coverage/0/256/${RADAR_TILE_ZOOM}/${Math.floor(x)}/${Math.floor(y)}/0/0_0.png`,
    {
      signal: AbortSignal.any([
        signal,
        AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      ]),
    },
  );
  if (!response.ok) throw new Error("无法确认雷达覆盖");
  const bitmap = await createImageBitmap(await response.blob());
  try {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(
      bitmap,
      Math.floor((x % 1) * bitmap.width),
      Math.floor((y % 1) * bitmap.height),
      1,
      1,
      0,
      0,
      1,
      1,
    );
    return ctx.getImageData(0, 0, 1, 1).data[3] < 128;
  } finally {
    bitmap.close();
  }
}

const WIND_DIRECTIONS = [
  "北",
  "东北",
  "东",
  "东南",
  "南",
  "西南",
  "西",
  "西北",
] as const;

/** 把气象风向（来向）转成中文方位，如 45° → “东北风”。 */
export function windDirectionLabel(deg: number | null): string {
  if (deg === null || !Number.isFinite(deg)) return "风向未知";
  const normalized = ((deg % 360) + 360) % 360;
  const index = Math.round(normalized / 45) % 8;
  return `${WIND_DIRECTIONS[index]}风`;
}

/** WMO 天气代码 → 简短中文描述（仅用于 HUD 提示）。 */
export function weatherCodeLabel(code: number | null): string {
  if (code === null) return "未知";
  if (code === 0) return "晴";
  if (code <= 2) return "少云";
  if (code === 3) return "阴";
  if (code <= 48) return "雾霾";
  if (code <= 57) return "毛毛雨";
  if (code <= 67) return "降雨";
  if (code <= 77) return "降雪";
  if (code <= 82) return "阵雨";
  if (code <= 86) return "阵雪";
  if (code <= 99) return "雷暴";
  return "未知";
}
