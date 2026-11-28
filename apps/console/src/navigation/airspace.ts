import type { MultiPolygon, Polygon } from "geojson";
import { validLngLat } from "../geo";
import type { AltitudeRef } from "./engine";

export const airspaceKinds = {
  suitable: {
    title: "适飞空域参考",
    color: "#159d82",
    help: "资料所示适飞范围参考；仍需核对机型、运行方式、时效及临时管制。",
  },
  internal: {
    title: "内部管制区域参考",
    color: "#8159bd",
    help: "团队或场地内部管控范围；不能等同法定管制空域。",
  },
  restricted: {
    title: "禁飞区",
    color: "#d94e61",
    help: "按所提供来源标识的禁止飞行参考区；核对发布主体、范围与例外条件。",
  },
  altitude: {
    title: "限高区",
    color: "#737f98",
    help: "需结合区域高度上限及其基准核对，不能把海拔直接当离地高度。",
  },
  authorization: {
    title: "授权区",
    color: "#4388d5",
    help: "厂商授权或解禁流程参考；不代表已经取得行政许可。",
  },
  enhanced_warning: {
    title: "加强警示区",
    color: "#e38b3f",
    help: "加强提醒类区域，核对原始资料的具体要求及现场风险。",
  },
  warning: {
    title: "警示区",
    color: "#c3a12d",
    help: "警示类参考信息；不表示区域外一定安全或允许飞行。",
  },
} as const;
export type AirspaceKind = keyof typeof airspaceKinds;
export type AirspaceRegion = {
  id: string;
  name: string;
  kind: AirspaceKind;
  geometry: Polygon | MultiPolygon;
  source: string;
  source_ref: string;
  source_kind: "official" | "manufacturer" | "team";
  updated_at: string;
  fetched_at?: string;
  effective_from: string | null;
  effective_until: string | null;
  is_simulated: boolean;
  altitude_ref: AltitudeRef | null;
  max_height_m: number | null;
  description: string;
  participates_in_avoidance?: boolean;
  buffer_m?: number;
  avoidance_rule?: string;
};

export type ConstraintSnapshotData = {
  snapshot_id: string;
  version: string;
  digest: string;
  crs: "EPSG:4326";
  coordinate_system: "WGS84";
  source_status:
    | "not_loaded"
    | "known_empty"
    | "user_imported"
    | "simulation_preset"
    | "query_failed"
    | "manufacturer_reference"
    | "unavailable";
  is_simulated: boolean;
  fetched_at: string;
  zone_buffer_m: number;
  buffer_source: string;
  boundary_rule: string;
  boundary_rule_note?: string;
  conservative_rule?: string;
  failure_reason?: string;
  total_zone_count: number;
  enforced_zone_count: number;
  enforced_zone_ids: string[];
  zones: AirspaceRegion[];
};

export type AirspaceConflictItem = {
  zone_id: string;
  zone_name: string;
  zone_kind: AirspaceKind;
  is_simulated: boolean;
  segment_index: number;
  segment_number: number;
  segment_start: [number, number];
  segment_end: [number, number];
  conflict_type: string;
  distance_m: number;
  buffer_m: number;
  reason: string;
};

export type AirspaceCheckData = {
  status:
    | "passed_known_snapshot"
    | "conflict"
    | "known_empty_snapshot"
    | "no_enforced_zones_in_snapshot"
    | "snapshot_not_loaded"
    | "query_failed"
    | "unavailable"
    | "not_checked_legacy";
  passed_known_snapshot: boolean | null;
  operationally_approved: boolean;
  verdict_label: string;
  snapshot_id: string | null;
  snapshot_version?: string | null;
  snapshot_digest: string | null;
  crs: string;
  source_status?: string;
  enforced_zone_count: number;
  total_zone_count: number;
  enforced_zone_ids: string[];
  zone_buffer_m: number | null;
  buffer_source?: string;
  boundary_rule?: string;
  conflicts: AirspaceConflictItem[];
  conflicting_zone_ids: string[];
  conflicting_segment_indices: number[];
  checked_segment_count?: number;
  gaps: string[];
  checked_at?: string;
};

export const ACTIVE_SNAPSHOT_STORAGE_KEY = "aeris-airspace-snapshot-id";

export function regionsFromSnapshot(
  snapshot: ConstraintSnapshotData | null | undefined,
): AirspaceRegion[] {
  if (!snapshot || !Array.isArray(snapshot.zones)) return [];
  return snapshot.zones.map((z) => ({
    id: z.id,
    name: z.name,
    kind: z.kind,
    geometry: structuredClone(z.geometry),
    source: z.source,
    source_ref: z.source_ref ?? "",
    source_kind: z.source_kind ?? "team",
    updated_at: z.updated_at || z.fetched_at || new Date().toISOString(),
    fetched_at: z.fetched_at,
    effective_from: z.effective_from ?? null,
    effective_until: z.effective_until ?? null,
    is_simulated: Boolean(z.is_simulated),
    altitude_ref: z.altitude_ref ?? null,
    max_height_m: z.max_height_m ?? null,
    description: z.description ?? "",
    participates_in_avoidance: z.participates_in_avoidance,
    buffer_m: z.buffer_m,
    avoidance_rule: z.avoidance_rule,
  }));
}

export function geojsonFromRegions(regions: AirspaceRegion[]) {
  return {
    type: "FeatureCollection" as const,
    coordinate_system: "WGS84" as const,
    features: regions.map(({ geometry, ...properties }) => ({
      type: "Feature" as const,
      geometry,
      properties,
    })),
  };
}
const time = (v: unknown): v is string =>
  typeof v === "string" &&
  /(?:Z|[+-]\d\d:\d\d)$/.test(v) &&
  Number.isFinite(Date.parse(v));
export function airspaceTiming(r: AirspaceRegion, now = Date.now()) {
  if (!r.effective_from || !r.effective_until) return "时效待核实";
  if (Date.parse(r.effective_from) > now) return "所填生效时间未到";
  return Date.parse(r.effective_until) <= now
    ? "所填有效期已过"
    : "所填有效时段内";
}
export const regionPoints = (r: AirspaceRegion): [number, number][] =>
  (r.geometry.type === "Polygon"
    ? r.geometry.coordinates
    : r.geometry.coordinates.flat()
  )
    .flat()
    .map((p) => [p[0], p[1]]);

/** Endpoints plus zone vertices inside the route box expanded by padDeg. */
export function flysafeOverviewPoints(
  origin: [number, number] | null | undefined,
  destination: [number, number] | null | undefined,
  regions: AirspaceRegion[],
  padDeg = 0.3,
): [number, number][] {
  const anchors = [origin, destination].filter(
    (point): point is [number, number] =>
      !!point &&
      point.length === 2 &&
      Number.isFinite(point[0]) &&
      Number.isFinite(point[1]),
  );
  if (!anchors.length) return [];
  const west = Math.min(...anchors.map((point) => point[0])) - padDeg;
  const east = Math.max(...anchors.map((point) => point[0])) + padDeg;
  const south = Math.min(...anchors.map((point) => point[1])) - padDeg;
  const north = Math.max(...anchors.map((point) => point[1])) + padDeg;
  const points = anchors.map(
    (point) => [point[0], point[1]] as [number, number],
  );
  for (const region of regions) {
    for (const vertex of regionPoints(region)) {
      if (
        vertex[0] >= west &&
        vertex[0] <= east &&
        vertex[1] >= south &&
        vertex[1] <= north
      ) {
        points.push(vertex);
      }
    }
  }
  return points;
}

/** Only displays explicitly attributed WGS84 geometry; this is no source/approval verification. */
export function parseAirspaces(value: unknown): AirspaceRegion[] {
  if (!value || typeof value !== "object")
    throw new Error("空域文件需为 GeoJSON FeatureCollection");
  const input = value as Record<string, unknown>;
  if (
    input.type !== "FeatureCollection" ||
    input.coordinate_system !== "WGS84" ||
    input.crs != null ||
    !Array.isArray(input.features) ||
    input.features.length < 1 ||
    input.features.length > 100
  )
    throw new Error(
      "需声明 coordinate_system: WGS84，包含1–100个区域；不接受含糊的 crs 或 GCJ02",
    );
  const ids = new Set<string>();
  let vertices = 0;
  const text = (v: unknown, max: number, required = true): string => {
    if (v == null && !required) return "";
    if (typeof v !== "string" || v.length > max || (required && !v.trim()))
      throw new Error("区域名称、来源或说明缺失 / 过长");
    return v.trim();
  };
  return input.features.map((item): AirspaceRegion => {
    if (!item || typeof item !== "object")
      throw new Error("区域需为 GeoJSON Feature");
    const f = item as Record<string, unknown>,
      p = f.properties as Record<string, unknown>,
      g = f.geometry as Record<string, unknown>;
    if (
      f.type !== "Feature" ||
      !p ||
      typeof p !== "object" ||
      !g ||
      !["Polygon", "MultiPolygon"].includes(String(g.type))
    )
      throw new Error("区域仅接受 Polygon / MultiPolygon");
    const id = text(p.id, 100);
    if (ids.has(id)) throw new Error("区域 id 不能重复");
    ids.add(id);
    if (
      !Object.hasOwn(airspaceKinds, String(p.kind)) ||
      !["official", "manufacturer", "team"].includes(String(p.source_kind)) ||
      typeof p.is_simulated !== "boolean" ||
      !time(p.updated_at)
    )
      throw new Error("区域需声明分类、来源类型、更新时间及仿真标记");
    const dates = [p.effective_from, p.effective_until];
    if (
      dates.some((d) => d != null && !time(d)) ||
      (dates[0] != null &&
        dates[1] != null &&
        Date.parse(String(dates[1])) <= Date.parse(String(dates[0])))
    )
      throw new Error("区域有效时刻需带时区，结束须晚于开始");
    if (
      p.altitude_ref != null &&
      !["agl", "amsl", "rel_takeoff"].includes(String(p.altitude_ref))
    )
      throw new Error("区域高度基准无效");
    if (
      p.max_height_m != null &&
      (typeof p.max_height_m !== "number" ||
        !Number.isFinite(p.max_height_m) ||
        Math.abs(p.max_height_m) > 10000 ||
        !p.altitude_ref)
    )
      throw new Error("高度上限必须是有限米数并声明 altitude_ref");
    const polygons = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
    if (!Array.isArray(polygons) || !polygons.length || polygons.length > 100)
      throw new Error("多边形集合为空或过大");
    for (const polygon of polygons) {
      if (!Array.isArray(polygon) || !polygon.length || polygon.length > 30)
        throw new Error("多边形轮廓不完整");
      for (const ring of polygon) {
        if (!Array.isArray(ring) || ring.length < 4 || ring.length > 1000)
          throw new Error("轮廓需4–1000个点并闭合");
        vertices += ring.length;
        if (vertices > 20000) throw new Error("区域总顶点数不能超过20000");
        for (const point of ring)
          if (
            !Array.isArray(point) ||
            point.length !== 2 ||
            !point.every((n) => typeof n === "number" && Number.isFinite(n)) ||
            !validLngLat(point as [number, number])
          )
            throw new Error("区域坐标需为有效WGS84经纬度，不含高度");
        if (ring[0][0] !== ring.at(-1)[0] || ring[0][1] !== ring.at(-1)[1])
          throw new Error("多边形轮廓必须闭合");
        if (
          ring.some(
            (point, i) => i && Math.abs(point[0] - ring[i - 1][0]) > 180,
          )
        )
          throw new Error("跨180°经线的区域请拆分");
        const area = ring
          .slice(1)
          .reduce(
            (sum, point, i) =>
              sum + ring[i][0] * point[1] - point[0] * ring[i][1],
            0,
          );
        if (Math.abs(area) < 1e-12) throw new Error("多边形面积为零");
      }
    }
    return {
      id,
      name: text(p.name, 150),
      kind: p.kind as AirspaceKind,
      geometry: structuredClone(g) as unknown as Polygon | MultiPolygon,
      source: text(p.source, 300),
      source_ref: text(p.source_ref, 500),
      source_kind: p.source_kind as AirspaceRegion["source_kind"],
      updated_at: p.updated_at as string,
      effective_from: (p.effective_from as string) ?? null,
      effective_until: (p.effective_until as string) ?? null,
      is_simulated: p.is_simulated as boolean,
      altitude_ref: (p.altitude_ref as AltitudeRef) ?? null,
      max_height_m: (p.max_height_m as number) ?? null,
      description: text(p.description, 1500, false),
    };
  });
}
export const airspaceExample = {
  type: "FeatureCollection",
  coordinate_system: "WGS84",
  features: [
    {
      type: "Feature",
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [121.47, 31.23],
            [121.48, 31.23],
            [121.48, 31.24],
            [121.47, 31.24],
            [121.47, 31.23],
          ],
        ],
      },
      properties: {
        id: "example-only",
        name: "构造示例区域 · 非真实禁限飞数据",
        kind: "warning",
        source_kind: "team",
        source: "手工构造教学示例",
        source_ref: "示例，不是公告",
        updated_at: "2026-11-16T00:00:00Z",
        effective_from: null,
        effective_until: null,
        is_simulated: true,
        max_height_m: null,
        altitude_ref: null,
        description: "仅用于验证图层与导入流程，不能用于实际作业。",
      },
    },
  ],
};
