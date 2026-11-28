import type {
  EventItem,
  LiveTelemetry,
  Point,
  Telemetry,
  TerrainChange,
} from "../types";
import type { Presentation } from "./presentation";

export type AssistantDraft = {
  name: string;
  origin: string | null;
  destination: string | null;
  payload_kg: number | null;
  priority: "P1" | "P2";
};
export type AssistantContext = {
  is_simulated: true;
  sampled_at: string;
  task_id: string | null;
  selected_task_id: string | null;
  route_id: string | null;
  selected_intake_id?: string | null;
  airspace_snapshot_id?: string | null;
  active_route?: {
    route_id: string;
    task_id: string | null;
    frame: "WGS84" | "ENU";
    source: string;
    waypoints: Point[];
    constraint_snapshot_id?: string | null;
    constraint_digest?: string | null;
  } | null;
  progress: number;
  telemetry_mode: "demo" | "live" | "planning";
  telemetry: Telemetry | null;
  live_telemetry: LiveTelemetry | null;
  terrain: TerrainChange | null;
  events: EventItem[];
};
export type ToolTrace = {
  id: string;
  name: string;
  status: "running" | "completed" | "error";
  elapsed_ms?: number;
  source?: string;
  arguments?: Record<string, unknown>;
  result?: Record<string, unknown>;
};
export type DocumentExcerpt = {
  path: string;
  heading: string;
  start_line: number;
  end_line: number;
  revision: string;
  text: string;
};
export type PreviewRoute = {
  status: "geometry_only";
  route_id: string;
  draft_digest: string;
  waypoints: Point[];
  length_m: number;
  waypoint_count: number;
  source: string;
  assumptions: string;
  dispatch_enabled: false;
};
export type RiskResult = {
  status:
    | "no_change_data"
    | "review_required"
    | "past_segments_only"
    | "outside_footprint";
  focus_point?: Point;
  remaining_segment_count?: number;
  affected_segments?: { segment: number; distance_m: number[] }[];
  terrain_revision?: number;
  limitation?: string;
  source: string;
  stale?: boolean;
};
export type ClarificationQuestion = {
  field: string;
  question: string;
  current?: string | null;
  map_pin?: MapPin | null;
  options?: { label: string; value: string }[];
};
export type MapPin = {
  candidates?: {
    name: string;
    point: [number, number];
    address?: string;
    source: string;
    capturedAt: string;
  }[];
  field: string;
  name: string;
  point: [number, number] | null;
  crs: string;
  source: string;
  address?: string;
  confirmed: boolean;
  note: string;
};
export type Clarification = {
  status: "needs_clarification";
  source: string;
  questions: ClarificationQuestion[];
  map_pins: MapPin[];
  draft_values?: {
    scheduled_for?: string | null;
    payload_kg?: number | null;
    priority?: string | null;
  };
  weather_feasibility: {
    status: "available_if_date_in_window" | "needs_map_pin";
    latitude?: number;
    longitude?: number;
    note: string;
  };
  summary: string;
  is_simulated: true;
  dispatch_enabled: false;
};
export type IntakeConfirmation = {
  confirmation_id: string;
  text: string;
  origin: string;
  destination: string;
  origin_point: [number, number];
  destination_point: [number, number];
  scheduled_for: string;
  payload_kg: number;
  priority: "P1" | "P2";
};
export type AssistantResult = {
  intake?: { id: string; origin: string; destination: string } | null;
  turn_id: string;
  provider: "local" | "maas";
  text: string;
  traces: ToolTrace[];
  documents?: DocumentExcerpt[];
  draft: AssistantDraft | null;
  draft_digest: string | null;
  route?: PreviewRoute | { status: "blocked"; reason: string } | null;
  risk?: RiskResult | null;
  task_status?: {
    source: string;
    task_id: string;
    scenario_id: string;
    planning_label: string;
    execution_label: string | null;
    ack_accepted: boolean | null;
    plan_version: string | null;
  } | null;
  dispatch_enabled: false;
  is_simulated: true;
  created_at: string;
  clarification?: Clarification | null;
  presentation?: Presentation;
};
export type Capabilities = {
  available: string[];
  pending: string[];
  dispatch_enabled: false;
  is_simulated: true;
};
export type Health = {
  provider: "local" | "maas";
  status: "ok";
  model_configured: boolean;
  dispatch_enabled: false;
  protocol: string;
};
export type Packet =
  | { type: "start"; provider: "local" | "maas" }
  | { type: "tool_start"; id: string; name: string }
  | { type: "tool_result"; trace: ToolTrace }
  | { type: "result"; result: AssistantResult }
  | { type: "error"; message: string }
  | { type: "heartbeat" };

export const toolLabels: Record<string, string> = {
  inspect_mission_plan: "复核工单航线、天气与备降依据",
  get_task_evidence: "读取冻结任务证据",
  search_project_docs: "检索项目文档",
  get_flight_status: "读取遥测快照",
  get_task_status: "查询当前联调任务",
  list_events: "查询页面事件",
  list_places: "查询登记地点",
  update_task_draft: "整理任务参数",
  plan_task_preview: "计算几何路线",
  inspect_terrain_risk: "检查变化影响",
  get_capabilities: "检查接入能力",
  resolve_real_place: "解析地点坐标",
  get_weather_forecast: "读取时段天气预报",
  get_airspace_zones: "读取空域约束快照",
  inspect_airspace_constraints: "核查任务禁飞区与航段冲突",
  create_task_intake: "确认/生成任务工单",
  get_intake_overview: "汇总工单图表数据",
};
