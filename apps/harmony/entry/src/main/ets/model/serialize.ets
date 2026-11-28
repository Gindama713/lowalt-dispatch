import type { PlanRequest, Position, SceneBindRequest, Task } from './types';

function positionBody(position: Position): ESObject {
  const body: ESObject = {
    frame: position.frame,
    alt_m: position.alt_m,
    alt_ref: position.alt_ref
  };
  if (position.frame === 'enu_m') {
    body['x_m'] = position.x_m;
    body['y_m'] = position.y_m;
  } else {
    body['lat_deg'] = position.lat_deg;
    body['lon_deg'] = position.lon_deg;
  }
  return body;
}

/** POST /tasks 的请求体。ENU 不带经纬度，避免两套坐标一起出现。 */
export function taskBody(task: Task): ESObject {
  const provenance: ESObject = {
    source: task.provenance.source,
    version: task.provenance.version,
    captured_at: task.provenance.captured_at,
    is_simulated: task.provenance.is_simulated
  };
  if (task.provenance.valid_from !== null) {
    provenance['valid_from'] = task.provenance.valid_from;
  }
  if (task.provenance.valid_until !== null) {
    provenance['valid_until'] = task.provenance.valid_until;
  }
  if (task.provenance.uncertainty_note !== null) {
    provenance['uncertainty_note'] = task.provenance.uncertainty_note;
  }
  return {
    task_id: task.task_id,
    origin: positionBody(task.origin),
    destination: positionBody(task.destination),
    payload_kg: task.payload_kg,
    vehicle_type: task.vehicle_type,
    initial_energy_wh: task.initial_energy_wh,
    reserve_energy_wh: task.reserve_energy_wh,
    time_limit_s: task.time_limit_s,
    provenance: provenance
  };
}

export function taskToJson(task: Task): string {
  return JSON.stringify(taskBody(task));
}

export function bindBody(request: SceneBindRequest): ESObject {
  return {
    scene_id: request.scene_id,
    active_zone_ids: request.active_zone_ids,
    occupied_site_ids: request.occupied_site_ids
  };
}

export function bindToJson(request: SceneBindRequest): string {
  return JSON.stringify(bindBody(request));
}

export function planBody(request: PlanRequest): ESObject {
  const body: ESObject = {};
  if (request.snapshot_id !== null && request.snapshot_id.length > 0) {
    body['snapshot_id'] = request.snapshot_id;
  }
  if (request.algorithm !== null && request.algorithm.length > 0) {
    body['algorithm'] = request.algorithm;
  }
  return body;
}

export function planToJson(request: PlanRequest): string {
  return JSON.stringify(planBody(request));
}
