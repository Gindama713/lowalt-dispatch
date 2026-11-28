import { ApiError } from './errors';
import type {
  AgentHookResult,
  GeoPolygon,
  PlanRequest,
  PlanResponse,
  Position,
  RiskEvent,
  RiskSnapshot,
  RouteRecord,
  SceneDocument,
  Task
} from './types';

const EXAMPLE_ENTRY = 'mock:example_polyline';
const TIMING_NOTE = '示例：Mock 没有运行搜索。elapsed_ms 保持 null。真实接口里该字段只表示规划函数内部耗时，不是端到端时延。';
const ALTITUDE_NOTE = '示例：中间点的 alt_m 与 alt_ref 复制起点，只为凑齐 Position。不是高度剖面，也不是规划器输出。';
const NO_ALTITUDE_NOTE = '示例：没有航点。';
const ROUTE_PLAN_DETAIL = '示例：没有 energy_budget_wh，不能构成 RoutePlan。不用任务单上的 initial_energy_wh 填这个字段。';
const MARGIN_DETAIL = '示例：没有备降余量剖面。status=unavailable，剖面和派生数字都是 null，不用 0 代替。';
const SIMULATION_NOTE = '示例。航点是示意折线，坐标系与 scenarios/v0 草稿相同（仿真，不是实测）。Mock 不调用 planner.astar。';

/** 射线法。只用于示例规划，判断终点是否落在已生效限制区的平面多边形里。 */
export function ringContains(x: number, y: number, ring: number[][]): boolean {
  let inside = false;
  let previous = ring.length - 1;
  for (let current = 0; current < ring.length; current++) {
    const xi = ring[current][0];
    const yi = ring[current][1];
    const xj = ring[previous][0];
    const yj = ring[previous][1];
    const crosses = (yi > y) !== (yj > y);
    if (crosses) {
      const xCross = ((xj - xi) * (y - yi)) / (yj - yi) + xi;
      if (x < xCross) {
        inside = !inside;
      }
    }
    previous = current;
  }
  return inside;
}

export function polygonContains(x: number, y: number, rings: number[][][]): boolean {
  if (rings.length === 0) {
    return false;
  }
  return ringContains(x, y, rings[0]);
}

function requireEnu(task: Task): void {
  if (task.origin.frame !== task.destination.frame || task.origin.alt_ref !== task.destination.alt_ref) {
    throw new ApiError(422, '起点和终点的坐标系或高度基准不一致，拒绝规划。');
  }
  if (task.origin.frame !== 'enu_m') {
    throw new ApiError(422, '当前规划入口只接受局部 ENU 米制。未做经纬度转换，拒绝把 WGS84 送进栅格。');
  }
  if (task.origin.x_m === null || task.origin.y_m === null || task.destination.x_m === null || task.destination.y_m === null) {
    throw new ApiError(422, 'ENU 任务缺少平面坐标。');
  }
}

function parseStamp(value: string | null, label: string): number | null {
  if (value === null) {
    return null;
  }
  if (!/[zZ]$/.test(value) && !/[+-]\d\d:\d\d$/.test(value)) {
    throw new ApiError(422, '快照时间必须带时区（UTC）。');
  }
  const stamp = Date.parse(value);
  if (!Number.isFinite(stamp)) {
    throw new ApiError(422, label + ' 不是合法时间。');
  }
  return stamp;
}

function activeZoneBlocks(task: Task, snapshot: RiskSnapshot, scene: SceneDocument): boolean {
  const destX = task.destination.x_m;
  const destY = task.destination.y_m;
  if (destX === null || destY === null) {
    return false;
  }
  const now = Date.now();
  for (let i = 0; i < snapshot.events.length; i++) {
    const event: RiskEvent = snapshot.events[i];
    if (event.kind !== 'restriction_zone' || event.zone_id === null) {
      continue;
    }
    const starts = parseStamp(event.effective_from, 'effective_from');
    if (starts !== null && starts > now) {
      continue;
    }
    const ends = parseStamp(event.effective_until, 'effective_until');
    if (ends !== null && ends <= now) {
      continue;
    }
    let rings = event.rings;
    if (rings.length === 0) {
      rings = ringsForZone(scene, event.zone_id);
    }
    if (polygonContains(destX, destY, rings)) {
      return true;
    }
  }
  return false;
}

function ringsForZone(scene: SceneDocument, zoneId: string): number[][][] {
  for (let i = 0; i < scene.restriction_zones.length; i++) {
    const zone: GeoPolygon = scene.restriction_zones[i];
    if (zone.id === zoneId) {
      return zone.rings;
    }
  }
  return [];
}

function distance(ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax;
  const dy = by - ay;
  return Math.sqrt(dx * dx + dy * dy);
}

function copyPoint(position: Position): Position {
  return {
    frame: position.frame,
    alt_m: position.alt_m,
    alt_ref: position.alt_ref,
    x_m: position.x_m,
    y_m: position.y_m,
    lat_deg: null,
    lon_deg: null
  };
}

function middlePoint(task: Task): Position {
  const ox = task.origin.x_m === null ? 0 : task.origin.x_m;
  const oy = task.origin.y_m === null ? 0 : task.origin.y_m;
  const dx = task.destination.x_m === null ? 0 : task.destination.x_m;
  const dy = task.destination.y_m === null ? 0 : task.destination.y_m;
  return {
    frame: task.origin.frame,
    alt_m: task.origin.alt_m,
    alt_ref: task.origin.alt_ref,
    x_m: (ox + dx) / 2 + 120,
    y_m: (oy + dy) / 2 - 80,
    lat_deg: null,
    lon_deg: null
  };
}

function agentResult(): AgentHookResult {
  return {
    status: 'not_implemented',
    detail: '示例：手机端不调用 M3，也不下发飞控指令。applied 保持 false。',
    entry: null,
    applied: false
  };
}

/**
 * 示例规划，不是 A*。
 * 终点落在「当前已生效」限制区多边形内时 found=false，reason 与几何基线无解时的措辞一致。
 * 其余情况返回一条三点示意折线。
 */
export function examplePlan(
  task: Task,
  snapshot: RiskSnapshot,
  scene: SceneDocument,
  request: PlanRequest,
  planVersion: string
): PlanResponse {
  requireEnu(task);
  parseStamp(snapshot.captured_at, 'captured_at');
  const until = parseStamp(snapshot.valid_until, 'valid_until');
  if (until !== null && until <= Date.now()) {
    throw new ApiError(409, '快照 ' + snapshot.snapshot_id + ' 已过 valid_until，不能用来规划新路线。');
  }
  const blocked = activeZoneBlocks(task, snapshot, scene);
  const limitations: string[] = [];
  limitations.push('示例：MockDataSource 不运行 planner.astar，也不读取障碍物做搜索。');
  limitations.push('示例：只在终点落入已生效限制区多边形时返回 found=false；绕障航线请看真实接口。');
  if (request.algorithm !== null && request.algorithm.length > 0) {
    limitations.push('请求里的算法名是 ' + request.algorithm + '。示例规划不会按这个名字切换算法。');
  }
  const originX = task.origin.x_m === null ? 0 : task.origin.x_m;
  const originY = task.origin.y_m === null ? 0 : task.origin.y_m;
  const destX = task.destination.x_m === null ? 0 : task.destination.x_m;
  const destY = task.destination.y_m === null ? 0 : task.destination.y_m;
  let found = true;
  let reason: string | null = null;
  let lengthM: number | null = null;
  const waypoints: Position[] = [];
  let altitudeNote = ALTITUDE_NOTE;
  if (blocked) {
    found = false;
    reason = '终点周围没有可用单元（目的地可能在限制区内）';
    altitudeNote = NO_ALTITUDE_NOTE;
  } else {
    const mid = middlePoint(task);
    const midX = mid.x_m === null ? 0 : mid.x_m;
    const midY = mid.y_m === null ? 0 : mid.y_m;
    waypoints.push(copyPoint(task.origin));
    waypoints.push(mid);
    waypoints.push(copyPoint(task.destination));
    lengthM = distance(originX, originY, midX, midY) + distance(midX, midY, destX, destY);
  }
  const route: RouteRecord = {
    task_id: task.task_id,
    route_id: planVersion,
    plan_version: planVersion,
    snapshot_id: snapshot.snapshot_id,
    algorithm: found ? 'example_polyline' : 'example_blocked',
    planner_entry: EXAMPLE_ENTRY,
    found: found,
    reason: reason,
    length_m: lengthM,
    elapsed_ms: null,
    nodes_expanded: null,
    timing_note: TIMING_NOTE,
    waypoints: waypoints,
    altitude_note: altitudeNote,
    route: null,
    route_plan_status: 'unavailable',
    route_plan_detail: ROUTE_PLAN_DETAIL,
    margin_status: 'unavailable',
    margin_detail: MARGIN_DETAIL,
    margin_profile: null,
    limitations: limitations,
    is_simulated: true,
    simulation_note: SIMULATION_NOTE
  };
  return {
    route: route,
    agent: agentResult()
  };
}
