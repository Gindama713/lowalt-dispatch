/** 字段名与 core/models.py、services/api/envelopes.py 的 JSON 一致。 */

export interface SlotStatus {
  name: string;
  configured: boolean;
  connected: boolean;
  note: string;
}

export interface AgentStatus {
  status: string;
  entry_configured: boolean;
  detail: string;
}

export interface Health {
  status: string;
  schema_version: string;
  service: string;
  git_commit: string;
  storage_backend: string;
  storage_note: string;
  planner_entry: string;
  postgres: SlotStatus;
  redis: SlotStatus;
  agent: AgentStatus;
}

export interface Position {
  frame: string;
  alt_m: number;
  alt_ref: string;
  x_m: number | null;
  y_m: number | null;
  lat_deg: number | null;
  lon_deg: number | null;
}

export interface DataProvenance {
  source: string;
  version: string;
  captured_at: string;
  valid_from: string | null;
  valid_until: string | null;
  is_simulated: boolean;
  uncertainty_note: string | null;
}

export interface LandingSite {
  site_id: string;
  position: Position;
  radius_m: number;
  compatible_vehicle_types: string[];
  available_from: string | null;
  available_until: string | null;
  occupied: boolean;
  provenance: DataProvenance;
}

export interface Task {
  task_id: string;
  origin: Position;
  destination: Position;
  payload_kg: number;
  vehicle_type: string;
  initial_energy_wh: number;
  reserve_energy_wh: number;
  time_limit_s: number | null;
  provenance: DataProvenance;
}

export interface RiskEvent {
  event_id: string;
  kind: string;
  zone_id: string | null;
  rings: number[][][];
  alt_min_m: number | null;
  alt_max_m: number | null;
  effective_from: string;
  effective_until: string | null;
  provenance: DataProvenance;
}

export interface RiskSnapshot {
  snapshot_id: string;
  captured_at: string;
  valid_until: string | null;
  landing_sites: LandingSite[];
  events: RiskEvent[];
  note: string | null;
}

export interface GeoPolygon {
  id: string;
  kind: string;
  rings: number[][][];
  alt_min_m: number | null;
  alt_max_m: number | null;
}

export interface SceneCounts {
  obstacles: number;
  restriction_zones: number;
  landing_sites: number;
}

export interface SceneDocument {
  scene_id: string;
  is_simulated: boolean;
  geometry_status: string;
  crs_note: string;
  note: string;
  obstacles: GeoPolygon[];
  restriction_zones: GeoPolygon[];
  landing_sites: LandingSite[];
  counts: SceneCounts;
}

export interface SceneBindRequest {
  scene_id: string;
  active_zone_ids: string[];
  occupied_site_ids: string[];
}

export interface SceneBindResult {
  snapshot: RiskSnapshot;
  scene_id: string;
  is_simulated: boolean;
  note: string;
}

export interface ConstraintCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface RoutePlan {
  route_id: string;
  plan_version: string;
  snapshot_id: string;
  algorithm: string;
  waypoints: Position[];
  energy_budget_wh: number;
  diversion_site_id: string | null;
  valid_until: string | null;
  checks: ConstraintCheck[];
}

export interface DiversionMarginSample {
  s_m: number;
  t_s: number;
  margin_wh: number;
  nearest_site_id: string | null;
  energy_need_wh: number | null;
}

export interface DiversionMarginProfile {
  route_id: string;
  plan_version: string;
  reserve_wh: number;
  samples: DiversionMarginSample[];
}

export interface RouteRecord {
  task_id: string;
  route_id: string;
  plan_version: string;
  snapshot_id: string;
  algorithm: string;
  planner_entry: string;
  found: boolean;
  reason: string | null;
  length_m: number | null;
  elapsed_ms: number | null;
  nodes_expanded: number | null;
  timing_note: string;
  waypoints: Position[];
  altitude_note: string;
  route: RoutePlan | null;
  route_plan_status: string;
  route_plan_detail: string;
  margin_status: string;
  margin_detail: string;
  margin_profile: DiversionMarginProfile | null;
  limitations: string[];
  is_simulated: boolean;
  simulation_note: string;
}

export interface AgentHookResult {
  status: string;
  detail: string;
  entry: string | null;
  applied: boolean;
}

export interface PlanRequest {
  snapshot_id: string | null;
  algorithm: string | null;
}

export interface PlanResponse {
  route: RouteRecord;
  agent: AgentHookResult;
}

export interface MarginView {
  task_id: string;
  route_id: string;
  status: string;
  detail: string;
  profile: DiversionMarginProfile | null;
  min_margin_wh: number | null;
  negative_sample_count: number | null;
  is_feasible: boolean | null;
}

export interface SeedSnapshot {
  task_id: string;
  snapshot: RiskSnapshot;
}

export interface SeedRoutes {
  task_id: string;
  routes: RouteRecord[];
}

export interface LocalAlert {
  id: string;
  at: string;
  kind: string;
  title: string;
  detail: string;
  scope: string;
}
