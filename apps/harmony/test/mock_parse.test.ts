import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { MockDataSource } from './.generated/client/MockDataSource.ts';
import { ApiError, formatDetail } from './.generated/model/errors.ts';
import { polygonContains } from './.generated/model/example_plan.ts';
import { unwrapPayload } from './.generated/model/json_read.ts';
import {
  marginViewFromRoute,
  parseHealth,
  parseMargin,
  parsePlan,
  parseScene,
  parseSeedRoutes,
  parseSeedSnapshots,
  parseTasks,
} from './.generated/model/parse.ts';
import { taskBody } from './.generated/model/serialize.ts';
import type { GeoPolygon, PlanRequest, SceneDocument, Task } from './.generated/model/types.ts';

declare const process: {
  env: { LIVE_HEALTH_JSON?: string; LIVE_SCENE_JSON?: string; LIVE_PLAN_JSON?: string };
  exit(code: number): never;
};

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

function load(name: string): ESObject {
  const root = dirname(fileURLToPath(import.meta.url));
  const text = readFileSync(join(root, '../entry/src/main/resources/rawfile/mock', name), 'utf8');
  return unwrapPayload(text);
}

function zone(scene: SceneDocument, id: string): GeoPolygon {
  for (let i = 0; i < scene.restriction_zones.length; i++) {
    if (scene.restriction_zones[i].id === id) {
      return scene.restriction_zones[i];
    }
  }
  throw new Error('missing zone ' + id);
}

async function main(): Promise<void> {
  const health = parseHealth(load('health.json'));
  assert(health.status === 'ok' || health.status === 'degraded', 'health status');
  assert(health.storage_backend === 'memory' || health.storage_backend === 'sqlite', 'storage');
  assert(health.schema_version === '0.1.0', 'schema');
  assert(health.postgres.connected === false && health.redis.connected === false, 'cloud slots stay disconnected');

  const tasks = parseTasks(load('tasks.json'));
  assert(tasks.length === 2, 'two seed tasks');
  assert(tasks[0].task_id === 'T-20261109-001', 'demo task id');
  assert(tasks[0].origin.frame === 'enu_m' && tasks[0].origin.x_m === 150, 'origin enu');
  assert(tasks[0].origin.lat_deg === null && tasks[0].destination.y_m === 2750, 'no lon on enu');
  const posted = taskBody(tasks[0]);
  const origin = posted['origin'] as ESObject;
  assert(origin['lat_deg'] === undefined && origin['x_m'] === 150, 'phone task body omits longitude');

  const scene = parseScene(load('scene_v0.json'));
  assert(scene.scene_id === 'v0' && scene.is_simulated === true, 'scene v0 simulated');
  assert(scene.counts.obstacles === 20 && scene.obstacles.length === 20, '20 obstacles');
  assert(scene.counts.restriction_zones === 4 && scene.counts.landing_sites === 4, 'zone and site counts');
  assert(scene.crs_note.indexOf('ENU') >= 0, 'crs note');
  const ids: string[] = [];
  for (let i = 0; i < scene.restriction_zones.length; i++) {
    ids.push(scene.restriction_zones[i].id);
  }
  ids.sort();
  assert(ids.join(',') === 'R01,R02,R03,R04', 'zone ids');
  assert(polygonContains(2500, 2500, zone(scene, 'R04').rings), 'R04 contains sample destination');
  assert(!polygonContains(2650, 2750, zone(scene, 'R04').rings), 'default destination is outside R04');

  const snapshots = parseSeedSnapshots(load('snapshots.json'));
  assert(snapshots[0].snapshot.snapshot_id === 'T-20261109-001-snap-1', 'snapshot id');
  assert(snapshots[0].snapshot.events.length === 1, 'one active zone');
  assert(snapshots[0].snapshot.events[0].zone_id === 'R01', 'R01 active');
  assert(snapshots[0].snapshot.events[0].rings.length > 0, 'zone polygon parsed');
  let occupiedL2 = false;
  for (let i = 0; i < snapshots[0].snapshot.landing_sites.length; i++) {
    const site = snapshots[0].snapshot.landing_sites[i];
    if (site.site_id === 'L2') {
      occupiedL2 = site.occupied;
    }
  }
  assert(occupiedL2, 'L2 occupied');
  assert(snapshots[1].snapshot.valid_until !== null && snapshots[1].snapshot.valid_until.indexOf('2020-01-02') >= 0, 'stale stamp');

  const groups = parseSeedRoutes(load('routes.json'));
  const seeded = groups[0].routes[0];
  assert(seeded.found === true && seeded.waypoints.length === 3, 'example polyline');
  assert(seeded.route === null && seeded.margin_profile === null, 'no invented plan or margin');
  let length = 0;
  for (let i = 1; i < seeded.waypoints.length; i++) {
    const prev = seeded.waypoints[i - 1];
    const point = seeded.waypoints[i];
    const dx = (point.x_m ?? 0) - (prev.x_m ?? 0);
    const dy = (point.y_m ?? 0) - (prev.y_m ?? 0);
    length += Math.sqrt(dx * dx + dy * dy);
  }
  assert(seeded.length_m !== null && Math.abs(seeded.length_m - length) < 1e-6, 'length is the polyline');

  const foundPlan = parsePlan(load('plan_found.json'));
  assert(foundPlan.route.found === true && foundPlan.agent.applied === false, 'plan envelope');
  const missed = parsePlan(load('plan_not_found.json'));
  assert(missed.route.found === false && missed.route.length_m === null && missed.route.waypoints.length === 0, 'not found shape');
  assert(missed.route.reason !== null && missed.route.reason.indexOf('终点') >= 0, 'reason mentions destination');

  const margin = parseMargin(load('margin_v1.json'));
  assert(margin.status === 'unavailable', 'margin unavailable');
  assert(margin.profile === null && margin.min_margin_wh === null, 'no fake margin number');
  assert(margin.negative_sample_count === null && margin.is_feasible === null, 'derived fields stay null');
  const derived = marginViewFromRoute(seeded);
  assert(derived.status === margin.status && derived.min_margin_wh === null, 'margin helper matches file');

  const detail = formatDetail(JSON.stringify({
    detail: [{ loc: ['body', 'task_id'], msg: 'Field required' }],
  }));
  assert(detail.indexOf('body.task_id') >= 0 && detail.indexOf('Field required') >= 0, '422 detail');
  assert(formatDetail(JSON.stringify({ detail: '任务已存在' })) === '任务已存在', 'string detail');

  const source = MockDataSource.fromParts(health, tasks, scene, snapshots, groups);
  const listed = await source.listTasks();
  assert(listed.length === 2, 'mock lists seed tasks');
  const again = listed[0];
  let duplicate = false;
  try {
    await source.createTask(again);
  } catch (err) {
    duplicate = err instanceof ApiError && err.status === 409;
  }
  assert(duplicate, 'duplicate task is 409');

  let unknown = false;
  try {
    await source.snapshotFromScene('T-20261109-001', {
      scene_id: 'v0',
      active_zone_ids: ['R99'],
      occupied_site_ids: [],
    });
  } catch (err) {
    unknown = err instanceof ApiError && err.status === 422 && err.detailText.indexOf('R99') >= 0;
  }
  assert(unknown, 'unknown zone is 422');

  const freshTask: Task = {
    task_id: 'T-phone-001',
    origin: { frame: 'enu_m', x_m: 500, y_m: 500, alt_m: 0, alt_ref: 'rel_takeoff', lat_deg: null, lon_deg: null },
    destination: { frame: 'enu_m', x_m: 2500, y_m: 2500, alt_m: 30, alt_ref: 'rel_takeoff', lat_deg: null, lon_deg: null },
    payload_kg: 1,
    vehicle_type: 'placeholder',
    initial_energy_wh: 100,
    reserve_energy_wh: 20,
    time_limit_s: null,
    provenance: {
      source: 'harmony:test',
      version: '0',
      captured_at: '2026-11-13T00:00:00Z',
      valid_from: null,
      valid_until: null,
      is_simulated: true,
      uncertainty_note: '示例',
    },
  };
  await source.createTask(freshTask);
  const bound = await source.snapshotFromScene(freshTask.task_id, {
    scene_id: 'v0',
    active_zone_ids: ['R04'],
    occupied_site_ids: ['L1'],
  });
  assert(bound.snapshot.snapshot_id === 'T-phone-001-snap-1', 'generated snapshot id');
  const blocked = await source.plan(freshTask.task_id, { snapshot_id: null, algorithm: 'astar_diversion' });
  assert(blocked.route.found === false, 'destination inside R04 is not found');
  assert(blocked.route.limitations.join('\n').indexOf('astar_diversion') >= 0, 'requested algorithm is recorded');
  const blockedMargin = await source.getMargin(freshTask.task_id, blocked.route.route_id);
  assert(blockedMargin.status === 'unavailable' && blockedMargin.is_feasible === null, 'blocked route has no margin');

  const openRequest: PlanRequest = { snapshot_id: snapshots[0].snapshot.snapshot_id, algorithm: null };
  const openPlan = await source.plan('T-20261109-001', openRequest);
  assert(openPlan.route.found === true && openPlan.route.route_id === 'v2', 'second version is a sample polyline');
  assert(openPlan.agent.applied === false, 'agent does not apply');

  let stale = false;
  try {
    await source.plan('T-stale-demo', { snapshot_id: null, algorithm: null });
  } catch (err) {
    stale = err instanceof ApiError && err.status === 409 && err.detailText.indexOf('valid_until') >= 0;
  }
  assert(stale, 'expired snapshot is 409');
  const staleRoutes = await source.listRoutes('T-stale-demo');
  assert(staleRoutes.length === 0, '409 does not store a route');

  if (process.env.LIVE_HEALTH_JSON !== undefined) {
    const liveHealth = parseHealth(JSON.parse(readFileSync(process.env.LIVE_HEALTH_JSON, 'utf8')) as ESObject);
    assert(liveHealth.service === 'lowalt-dispatch-api', 'live health service');
  }
  if (process.env.LIVE_SCENE_JSON !== undefined) {
    const liveScene = parseScene(JSON.parse(readFileSync(process.env.LIVE_SCENE_JSON, 'utf8')) as ESObject);
    assert(liveScene.counts.obstacles === 20, 'live scene counts');
  }
  if (process.env.LIVE_PLAN_JSON !== undefined) {
    const livePlan = parsePlan(JSON.parse(readFileSync(process.env.LIVE_PLAN_JSON, 'utf8')) as ESObject);
    assert(typeof livePlan.route.found === 'boolean', 'live plan parses');
    assert(livePlan.agent.applied === false, 'live agent is not applied');
  }

  console.log('mock parse tests passed');
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
