import { ParseError } from './errors';
import {
  asObject,
  nullBool,
  nullNumber,
  nullString,
  objectList,
  reqBool,
  reqNumber,
  reqString,
  stringField,
  stringList
} from './json_read';
import type {
  AgentHookResult,
  AgentStatus,
  ConstraintCheck,
  DataProvenance,
  DiversionMarginProfile,
  DiversionMarginSample,
  GeoPolygon,
  Health,
  LandingSite,
  LocalAlert,
  MarginView,
  PlanResponse,
  Position,
  RiskEvent,
  RiskSnapshot,
  RoutePlan,
  RouteRecord,
  SceneBindResult,
  SceneCounts,
  SceneDocument,
  SeedRoutes,
  SeedSnapshot,
  SlotStatus,
  Task
} from './types';

const HEALTH_STATUS: string[] = ['ok', 'degraded'];
const STORAGE_BACKEND: string[] = ['memory', 'sqlite'];
const ZONE_KINDS: string[] = [
  'restriction_zone',
  'wind',
  'link_degradation',
  'landing_site_change',
  'battery_anomaly'
];

function oneOf(value: string, allowed: string[], label: string): string {
  for (let i = 0; i < allowed.length; i++) {
    if (allowed[i] === value) {
      return value;
    }
  }
  throw new ParseError(label + ' 不在允许取值内：' + value);
}

export function parsePosition(raw: ESObject, label: string): Position {
  const obj = asObject(raw, label);
  const frame = reqString(obj, 'frame', label);
  const position: Position = {
    frame: frame,
    alt_m: reqNumber(obj, 'alt_m', label),
    alt_ref: reqString(obj, 'alt_ref', label),
    x_m: nullNumber(obj, 'x_m', label),
    y_m: nullNumber(obj, 'y_m', label),
    lat_deg: nullNumber(obj, 'lat_deg', label),
    lon_deg: nullNumber(obj, 'lon_deg', label)
  };
  if (frame === 'enu_m') {
    if (position.x_m === null || position.y_m === null) {
      throw new ParseError(label + ' frame=enu_m 必须同时给出 x_m 与 y_m');
    }
    if (position.lat_deg !== null || position.lon_deg !== null) {
      throw new ParseError(label + ' frame=enu_m 不允许填经纬度');
    }
  } else if (frame === 'wgs84') {
    if (position.lat_deg === null || position.lon_deg === null) {
      throw new ParseError(label + ' frame=wgs84 必须同时给出 lat_deg 与 lon_deg');
    }
    if (position.x_m !== null || position.y_m !== null) {
      throw new ParseError(label + ' frame=wgs84 不允许填 ENU 坐标');
    }
  } else {
    throw new ParseError(label + ' frame 只能是 enu_m 或 wgs84');
  }
  return position;
}

export function parseProvenance(raw: ESObject, label: string): DataProvenance {
  const obj = asObject(raw, label);
  return {
    source: reqString(obj, 'source', label),
    version: reqString(obj, 'version', label),
    captured_at: reqString(obj, 'captured_at', label),
    valid_from: nullString(obj, 'valid_from', label),
    valid_until: nullString(obj, 'valid_until', label),
    is_simulated: reqBool(obj, 'is_simulated', label),
    uncertainty_note: nullString(obj, 'uncertainty_note', label)
  };
}

export function parseLandingSite(raw: ESObject, label: string): LandingSite {
  const obj = asObject(raw, label);
  const radius = reqNumber(obj, 'radius_m', label);
  if (radius <= 0) {
    throw new ParseError(label + '.radius_m 必须大于 0');
  }
  return {
    site_id: reqString(obj, 'site_id', label),
    position: parsePosition(obj['position'] as ESObject, label + '.position'),
    radius_m: radius,
    compatible_vehicle_types: stringList(obj, 'compatible_vehicle_types', label),
    available_from: nullString(obj, 'available_from', label),
    available_until: nullString(obj, 'available_until', label),
    occupied: reqBool(obj, 'occupied', label),
    provenance: parseProvenance(obj['provenance'] as ESObject, label + '.provenance')
  };
}

export function parseTask(raw: ESObject): Task {
  const obj = asObject(raw, 'task');
  const payload = reqNumber(obj, 'payload_kg', 'task');
  const initial = reqNumber(obj, 'initial_energy_wh', 'task');
  const reserve = reqNumber(obj, 'reserve_energy_wh', 'task');
  if (payload < 0) {
    throw new ParseError('task.payload_kg 不能为负');
  }
  if (initial <= 0) {
    throw new ParseError('task.initial_energy_wh 必须大于 0');
  }
  if (reserve < 0) {
    throw new ParseError('task.reserve_energy_wh 不能为负');
  }
  const timeLimit = nullNumber(obj, 'time_limit_s', 'task');
  if (timeLimit !== null && timeLimit < 0) {
    throw new ParseError('task.time_limit_s 不能为负');
  }
  const taskId = reqString(obj, 'task_id', 'task');
  if (taskId.indexOf('/') >= 0 || taskId.indexOf('\\') >= 0) {
    throw new ParseError('task_id 不能包含斜杠');
  }
  return {
    task_id: taskId,
    origin: parsePosition(obj['origin'] as ESObject, 'task.origin'),
    destination: parsePosition(obj['destination'] as ESObject, 'task.destination'),
    payload_kg: payload,
    vehicle_type: reqString(obj, 'vehicle_type', 'task'),
    initial_energy_wh: initial,
    reserve_energy_wh: reserve,
    time_limit_s: timeLimit,
    provenance: parseProvenance(obj['provenance'] as ESObject, 'task.provenance')
  };
}

export function parseTasks(raw: ESObject): Task[] {
  const rows = objectList(raw, 'tasks');
  const tasks: Task[] = [];
  for (let i = 0; i < rows.length; i++) {
    tasks.push(parseTask(rows[i]));
  }
  return tasks;
}

function parsePair(raw: ESObject, label: string): number[] {
  if (!Array.isArray(raw) || raw.length < 2) {
    throw new ParseError(label + ' 点坐标不完整');
  }
  const x = raw[0] as ESObject;
  const y = raw[1] as ESObject;
  if (typeof x !== 'number' || typeof y !== 'number' || !Number.isFinite(x) || !Number.isFinite(y)) {
    throw new ParseError(label + ' 点坐标不是有限数字');
  }
  const pair: number[] = [];
  pair.push(x);
  pair.push(y);
  return pair;
}

function parseRings(raw: ESObject, label: string): number[][][] {
  if (!Array.isArray(raw) || raw.length === 0) {
    throw new ParseError(label + ' 缺少多边形环');
  }
  const rings: number[][][] = [];
  for (let i = 0; i < raw.length; i++) {
    const ringRaw = raw[i] as ESObject;
    if (!Array.isArray(ringRaw) || ringRaw.length < 4) {
      throw new ParseError(label + ' 环至少要有 4 个点');
    }
    const ring: number[][] = [];
    for (let j = 0; j < ringRaw.length; j++) {
      ring.push(parsePair(ringRaw[j] as ESObject, label));
    }
    rings.push(ring);
  }
  return rings;
}

function parsePolygonFeature(raw: ESObject, label: string): GeoPolygon {
  const obj = asObject(raw, label);
  if (stringField(obj, 'type', label) !== 'Feature') {
    throw new ParseError(label + '.type 不是 Feature');
  }
  const geometry = asObject(obj['geometry'] as ESObject, label + '.geometry');
  if (stringField(geometry, 'type', label + '.geometry') !== 'Polygon') {
    throw new ParseError(label + ' 目前只解析 Polygon');
  }
  const props = asObject(obj['properties'] as ESObject, label + '.properties');
  const altMin = nullNumber(props, 'alt_min_m', label + '.properties');
  const altMax = nullNumber(props, 'alt_max_m', label + '.properties');
  if (altMin !== null && altMax !== null && altMin > altMax) {
    throw new ParseError(label + ' alt_min_m 不能大于 alt_max_m');
  }
  return {
    id: reqString(props, 'id', label + '.properties'),
    kind: reqString(props, 'kind', label + '.properties'),
    rings: parseRings(geometry['coordinates'] as ESObject, label + '.coordinates'),
    alt_min_m: altMin,
    alt_max_m: altMax
  };
}

export function parseScene(raw: ESObject): SceneDocument {
  const obj = asObject(raw, 'scene');
  const obstaclesRaw = objectList(obj['obstacles'] as ESObject, 'scene.obstacles');
  const zonesRaw = objectList(obj['restriction_zones'] as ESObject, 'scene.restriction_zones');
  const sitesRaw = objectList(obj['landing_sites'] as ESObject, 'scene.landing_sites');
  const obstacles: GeoPolygon[] = [];
  const zones: GeoPolygon[] = [];
  const sites: LandingSite[] = [];
  for (let i = 0; i < obstaclesRaw.length; i++) {
    obstacles.push(parsePolygonFeature(obstaclesRaw[i], 'scene.obstacles[' + String(i) + ']'));
  }
  for (let i = 0; i < zonesRaw.length; i++) {
    const zone = parsePolygonFeature(zonesRaw[i], 'scene.restriction_zones[' + String(i) + ']');
    if (zone.kind !== 'restriction_zone') {
      throw new ParseError('限制区 kind 应为 restriction_zone');
    }
    zones.push(zone);
  }
  for (let i = 0; i < sitesRaw.length; i++) {
    sites.push(parseLandingSite(sitesRaw[i], 'scene.landing_sites[' + String(i) + ']'));
  }
  const countsRaw = asObject(obj['counts'] as ESObject, 'scene.counts');
  const counts: SceneCounts = {
    obstacles: reqNumber(countsRaw, 'obstacles', 'scene.counts'),
    restriction_zones: reqNumber(countsRaw, 'restriction_zones', 'scene.counts'),
    landing_sites: reqNumber(countsRaw, 'landing_sites', 'scene.counts')
  };
  if (counts.obstacles !== obstacles.length || counts.restriction_zones !== zones.length ||
    counts.landing_sites !== sites.length) {
    throw new ParseError('scene.counts 与数组长度不一致');
  }
  return {
    scene_id: reqString(obj, 'scene_id', 'scene'),
    is_simulated: reqBool(obj, 'is_simulated', 'scene'),
    geometry_status: stringField(obj, 'geometry_status', 'scene'),
    crs_note: stringField(obj, 'crs_note', 'scene'),
    note: stringField(obj, 'note', 'scene'),
    obstacles: obstacles,
    restriction_zones: zones,
    landing_sites: sites,
    counts: counts
  };
}

function eventRings(raw: ESObject, label: string): number[][][] {
  const nested = raw['geometry'] as ESObject;
  if (nested !== undefined && nested !== null && typeof nested === 'object' && !Array.isArray(nested)) {
    if (nested['type'] === 'Polygon') {
      return parseRings(nested['coordinates'] as ESObject, label + '.geometry');
    }
  }
  if (raw['type'] === 'Polygon') {
    return parseRings(raw['coordinates'] as ESObject, label);
  }
  return [];
}

function eventZoneId(raw: ESObject): string | null {
  const direct = raw['zone_id'];
  if (typeof direct === 'string' && direct.length > 0) {
    return direct;
  }
  const props = raw['properties'] as ESObject;
  if (props !== undefined && props !== null && typeof props === 'object' && !Array.isArray(props)) {
    const id = props['id'];
    if (typeof id === 'string' && id.length > 0) {
      return id;
    }
  }
  return null;
}

export function parseRiskEvent(raw: ESObject, label: string): RiskEvent {
  const obj = asObject(raw, label);
  const kind = oneOf(reqString(obj, 'kind', label), ZONE_KINDS, label + '.kind');
  const geometry = asObject(obj['geometry'] as ESObject, label + '.geometry');
  const altMin = nullNumber(obj, 'alt_min_m', label);
  const altMax = nullNumber(obj, 'alt_max_m', label);
  if (altMin !== null && altMax !== null && altMin > altMax) {
    throw new ParseError(label + ' alt_min_m 不能大于 alt_max_m');
  }
  return {
    event_id: reqString(obj, 'event_id', label),
    kind: kind,
    zone_id: eventZoneId(geometry),
    rings: eventRings(geometry, label + '.geometry'),
    alt_min_m: altMin,
    alt_max_m: altMax,
    effective_from: reqString(obj, 'effective_from', label),
    effective_until: nullString(obj, 'effective_until', label),
    provenance: parseProvenance(obj['provenance'] as ESObject, label + '.provenance')
  };
}

export function parseSnapshot(raw: ESObject): RiskSnapshot {
  const obj = asObject(raw, 'snapshot');
  const sitesRaw = objectList(obj['landing_sites'] as ESObject, 'snapshot.landing_sites');
  const eventsRaw = objectList(obj['events'] as ESObject, 'snapshot.events');
  const sites: LandingSite[] = [];
  const events: RiskEvent[] = [];
  for (let i = 0; i < sitesRaw.length; i++) {
    sites.push(parseLandingSite(sitesRaw[i], 'snapshot.landing_sites[' + String(i) + ']'));
  }
  for (let i = 0; i < eventsRaw.length; i++) {
    events.push(parseRiskEvent(eventsRaw[i], 'snapshot.events[' + String(i) + ']'));
  }
  return {
    snapshot_id: reqString(obj, 'snapshot_id', 'snapshot'),
    captured_at: reqString(obj, 'captured_at', 'snapshot'),
    valid_until: nullString(obj, 'valid_until', 'snapshot'),
    landing_sites: sites,
    events: events,
    note: nullString(obj, 'note', 'snapshot')
  };
}

export function parseSeedSnapshots(raw: ESObject): SeedSnapshot[] {
  const rows = objectList(raw, 'snapshots');
  const out: SeedSnapshot[] = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const item: SeedSnapshot = {
      task_id: reqString(row, 'task_id', 'snapshots[' + String(i) + ']'),
      snapshot: parseSnapshot(row['snapshot'] as ESObject)
    };
    out.push(item);
  }
  return out;
}

function parseChecks(raw: ESObject, label: string): ConstraintCheck[] {
  const rows = objectList(raw, label);
  const checks: ConstraintCheck[] = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const item: ConstraintCheck = {
      name: reqString(row, 'name', label),
      passed: reqBool(row, 'passed', label),
      detail: stringField(row, 'detail', label)
    };
    checks.push(item);
  }
  return checks;
}

function parseWaypoints(raw: ESObject, label: string): Position[] {
  const rows = objectList(raw, label);
  const points: Position[] = [];
  for (let i = 0; i < rows.length; i++) {
    points.push(parsePosition(rows[i], label + '[' + String(i) + ']'));
  }
  return points;
}

export function parseRoutePlan(raw: ESObject, label: string): RoutePlan {
  const obj = asObject(raw, label);
  const budget = reqNumber(obj, 'energy_budget_wh', label);
  if (budget <= 0) {
    throw new ParseError(label + '.energy_budget_wh 必须大于 0');
  }
  const waypoints = parseWaypoints(obj['waypoints'] as ESObject, label + '.waypoints');
  if (waypoints.length < 2) {
    throw new ParseError(label + '.waypoints 至少 2 个点');
  }
  return {
    route_id: reqString(obj, 'route_id', label),
    plan_version: reqString(obj, 'plan_version', label),
    snapshot_id: reqString(obj, 'snapshot_id', label),
    algorithm: reqString(obj, 'algorithm', label),
    waypoints: waypoints,
    energy_budget_wh: budget,
    diversion_site_id: nullString(obj, 'diversion_site_id', label),
    valid_until: nullString(obj, 'valid_until', label),
    checks: parseChecks(obj['checks'] as ESObject, label + '.checks')
  };
}

function parseSamples(raw: ESObject, label: string): DiversionMarginSample[] {
  const rows = objectList(raw, label);
  const samples: DiversionMarginSample[] = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const itemLabel = label + '[' + String(i) + ']';
    const s = reqNumber(row, 's_m', itemLabel);
    const t = reqNumber(row, 't_s', itemLabel);
    if (s < 0 || t < 0) {
      throw new ParseError(itemLabel + ' 的 s_m / t_s 不能为负');
    }
    const sample: DiversionMarginSample = {
      s_m: s,
      t_s: t,
      margin_wh: reqNumber(row, 'margin_wh', itemLabel),
      nearest_site_id: nullString(row, 'nearest_site_id', itemLabel),
      energy_need_wh: nullNumber(row, 'energy_need_wh', itemLabel)
    };
    samples.push(sample);
  }
  return samples;
}

export function parseMarginProfile(raw: ESObject, label: string): DiversionMarginProfile {
  const obj = asObject(raw, label);
  return {
    route_id: reqString(obj, 'route_id', label),
    plan_version: reqString(obj, 'plan_version', label),
    reserve_wh: reqNumber(obj, 'reserve_wh', label),
    samples: parseSamples(obj['samples'] as ESObject, label + '.samples')
  };
}

function parseNullablePlan(raw: ESObject, label: string): RoutePlan | null {
  if (raw === undefined || raw === null) {
    return null;
  }
  return parseRoutePlan(raw, label);
}

function parseNullableProfile(raw: ESObject, label: string): DiversionMarginProfile | null {
  if (raw === undefined || raw === null) {
    return null;
  }
  return parseMarginProfile(raw, label);
}

export function parseRoute(raw: ESObject): RouteRecord {
  const obj = asObject(raw, 'route');
  const found = reqBool(obj, 'found', 'route');
  const waypoints = parseWaypoints(obj['waypoints'] as ESObject, 'route.waypoints');
  const lengthM = nullNumber(obj, 'length_m', 'route');
  if (found) {
    if (waypoints.length < 2 || lengthM === null) {
      throw new ParseError('found=true 时必须有 length_m 和至少两个航点');
    }
  } else if (waypoints.length !== 0 || lengthM !== null) {
    throw new ParseError('found=false 时 waypoints 应为空且 length_m 为 null');
  }
  const routePlanStatus = oneOf(reqString(obj, 'route_plan_status', 'route'), ['available', 'unavailable'], 'route.route_plan_status');
  const marginStatus = oneOf(reqString(obj, 'margin_status', 'route'), ['available', 'unavailable'], 'route.margin_status');
  const routePlan = parseNullablePlan(obj['route'] as ESObject, 'route.route');
  const profile = parseNullableProfile(obj['margin_profile'] as ESObject, 'route.margin_profile');
  if (routePlanStatus === 'unavailable' && routePlan !== null) {
    throw new ParseError('route_plan_status=unavailable 时 route 必须为 null');
  }
  if (routePlanStatus === 'available' && routePlan === null) {
    throw new ParseError('route_plan_status=available 时 route 不能为 null');
  }
  if (marginStatus === 'unavailable' && profile !== null) {
    throw new ParseError('margin_status=unavailable 时 margin_profile 必须为 null');
  }
  if (marginStatus === 'available' && profile === null) {
    throw new ParseError('margin_status=available 时 margin_profile 不能为 null');
  }
  const elapsed = nullNumber(obj, 'elapsed_ms', 'route');
  const nodes = nullNumber(obj, 'nodes_expanded', 'route');
  if (nodes !== null && (!Number.isInteger(nodes) || nodes < 0)) {
    throw new ParseError('route.nodes_expanded 必须是非负整数或 null');
  }
  return {
    task_id: reqString(obj, 'task_id', 'route'),
    route_id: reqString(obj, 'route_id', 'route'),
    plan_version: reqString(obj, 'plan_version', 'route'),
    snapshot_id: reqString(obj, 'snapshot_id', 'route'),
    algorithm: reqString(obj, 'algorithm', 'route'),
    planner_entry: reqString(obj, 'planner_entry', 'route'),
    found: found,
    reason: nullString(obj, 'reason', 'route'),
    length_m: lengthM,
    elapsed_ms: elapsed,
    nodes_expanded: nodes,
    timing_note: stringField(obj, 'timing_note', 'route'),
    waypoints: waypoints,
    altitude_note: stringField(obj, 'altitude_note', 'route'),
    route: routePlan,
    route_plan_status: routePlanStatus,
    route_plan_detail: stringField(obj, 'route_plan_detail', 'route'),
    margin_status: marginStatus,
    margin_detail: stringField(obj, 'margin_detail', 'route'),
    margin_profile: profile,
    limitations: stringList(obj, 'limitations', 'route'),
    is_simulated: reqBool(obj, 'is_simulated', 'route'),
    simulation_note: stringField(obj, 'simulation_note', 'route')
  };
}

export function parseRoutes(raw: ESObject): RouteRecord[] {
  const rows = objectList(raw, 'routes');
  const routes: RouteRecord[] = [];
  for (let i = 0; i < rows.length; i++) {
    routes.push(parseRoute(rows[i]));
  }
  return routes;
}

export function parseSeedRoutes(raw: ESObject): SeedRoutes[] {
  const rows = objectList(raw, 'route_groups');
  const out: SeedRoutes[] = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const item: SeedRoutes = {
      task_id: reqString(row, 'task_id', 'route_groups'),
      routes: parseRoutes(row['routes'] as ESObject)
    };
    out.push(item);
  }
  return out;
}

function parseSlot(raw: ESObject, label: string): SlotStatus {
  const obj = asObject(raw, label);
  return {
    name: reqString(obj, 'name', label),
    configured: reqBool(obj, 'configured', label),
    connected: reqBool(obj, 'connected', label),
    note: stringField(obj, 'note', label)
  };
}

function parseAgentStatus(raw: ESObject): AgentStatus {
  const obj = asObject(raw, 'health.agent');
  const status = oneOf(reqString(obj, 'status', 'health.agent'), ['not_implemented', 'entry_configured'], 'health.agent.status');
  return {
    status: status,
    entry_configured: reqBool(obj, 'entry_configured', 'health.agent'),
    detail: stringField(obj, 'detail', 'health.agent')
  };
}

export function parseHealth(raw: ESObject): Health {
  const obj = asObject(raw, 'health');
  return {
    status: oneOf(reqString(obj, 'status', 'health'), HEALTH_STATUS, 'health.status'),
    schema_version: reqString(obj, 'schema_version', 'health'),
    service: reqString(obj, 'service', 'health'),
    git_commit: reqString(obj, 'git_commit', 'health'),
    storage_backend: oneOf(reqString(obj, 'storage_backend', 'health'), STORAGE_BACKEND, 'health.storage_backend'),
    storage_note: stringField(obj, 'storage_note', 'health'),
    planner_entry: reqString(obj, 'planner_entry', 'health'),
    postgres: parseSlot(obj['postgres'] as ESObject, 'health.postgres'),
    redis: parseSlot(obj['redis'] as ESObject, 'health.redis'),
    agent: parseAgentStatus(obj['agent'] as ESObject)
  };
}

export function parseAgentHook(raw: ESObject): AgentHookResult {
  const obj = asObject(raw, 'agent');
  const applied = reqBool(obj, 'applied', 'agent');
  if (applied) {
    throw new ParseError('agent.applied 必须为 false：本服务不执行动作');
  }
  return {
    status: oneOf(reqString(obj, 'status', 'agent'), ['not_implemented', 'invoked', 'error'], 'agent.status'),
    detail: stringField(obj, 'detail', 'agent'),
    entry: nullString(obj, 'entry', 'agent'),
    applied: applied
  };
}

export function parsePlan(raw: ESObject): PlanResponse {
  const obj = asObject(raw, 'plan');
  return {
    route: parseRoute(obj['route'] as ESObject),
    agent: parseAgentHook(obj['agent'] as ESObject)
  };
}

export function parseMargin(raw: ESObject): MarginView {
  const obj = asObject(raw, 'margin');
  const status = oneOf(reqString(obj, 'status', 'margin'), ['available', 'unavailable'], 'margin.status');
  const profile = parseNullableProfile(obj['profile'] as ESObject, 'margin.profile');
  const minMargin = nullNumber(obj, 'min_margin_wh', 'margin');
  const negative = nullNumber(obj, 'negative_sample_count', 'margin');
  const feasible = nullBool(obj, 'is_feasible', 'margin');
  if (negative !== null && (!Number.isInteger(negative) || negative < 0)) {
    throw new ParseError('margin.negative_sample_count 必须是非负整数或 null');
  }
  if (status === 'unavailable') {
    if (profile !== null || minMargin !== null || negative !== null || feasible !== null) {
      throw new ParseError('margin status=unavailable 时剖面和派生数字必须为 null');
    }
  } else if (profile === null) {
    throw new ParseError('margin status=available 时 profile 不能为 null');
  }
  return {
    task_id: reqString(obj, 'task_id', 'margin'),
    route_id: reqString(obj, 'route_id', 'margin'),
    status: status,
    detail: stringField(obj, 'detail', 'margin'),
    profile: profile,
    min_margin_wh: minMargin,
    negative_sample_count: negative,
    is_feasible: feasible
  };
}

export function parseBind(raw: ESObject): SceneBindResult {
  const obj = asObject(raw, 'bind');
  return {
    snapshot: parseSnapshot(obj['snapshot'] as ESObject),
    scene_id: reqString(obj, 'scene_id', 'bind'),
    is_simulated: reqBool(obj, 'is_simulated', 'bind'),
    note: stringField(obj, 'note', 'bind')
  };
}

export function parseAlerts(raw: ESObject): LocalAlert[] {
  const rows = objectList(raw, 'alerts');
  const alerts: LocalAlert[] = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const item: LocalAlert = {
      id: reqString(row, 'id', 'alert'),
      at: reqString(row, 'at', 'alert'),
      kind: reqString(row, 'kind', 'alert'),
      title: reqString(row, 'title', 'alert'),
      detail: stringField(row, 'detail', 'alert'),
      scope: stringField(row, 'scope', 'alert')
    };
    alerts.push(item);
  }
  return alerts;
}

/** 与 services/api/assemble.py 的 margin_view 同一规则：不可用时三个派生值为 null。 */
export function marginViewFromRoute(route: RouteRecord): MarginView {
  const profile = route.margin_profile;
  if (route.margin_status !== 'available' || profile === null) {
    return {
      task_id: route.task_id,
      route_id: route.route_id,
      status: 'unavailable',
      detail: route.margin_detail,
      profile: null,
      min_margin_wh: null,
      negative_sample_count: null,
      is_feasible: null
    };
  }
  let minMargin: number | null = null;
  let negative = 0;
  let missingSite = false;
  for (let i = 0; i < profile.samples.length; i++) {
    const sample = profile.samples[i];
    if (minMargin === null || sample.margin_wh < minMargin) {
      minMargin = sample.margin_wh;
    }
    if (sample.margin_wh < 0) {
      negative++;
    }
    if (sample.nearest_site_id === null) {
      missingSite = true;
    }
  }
  const feasible = profile.samples.length > 0 && !missingSite && negative === 0;
  return {
    task_id: route.task_id,
    route_id: route.route_id,
    status: 'available',
    detail: route.margin_detail,
    profile: profile,
    min_margin_wh: minMargin,
    negative_sample_count: negative,
    is_feasible: feasible
  };
}
