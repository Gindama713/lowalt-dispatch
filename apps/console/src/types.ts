export type ViewMode = "2d" | "3d";
export type PanelId =
  | "mission"
  | "instruments"
  | "analysis"
  | "events"
  | "perception";
export type Point = [number, number];
export type EventItem = {
  id: string;
  time: string;
  type: "info" | "success" | "warning";
  title: string;
  detail: string;
};
export type Telemetry = {
  battery: number;
  voltage: number;
  current: number;
  energyWh: number | null;
  altitude: number;
  speed: number;
  climb: number;
  heading: number;
  pitch: number;
  roll: number;
  rssi: number;
  satellites: number;
  hdop: number;
  rtt: number;
  rotors: [number, number, number, number];
  motorTemp: number;
  coverage: number;
  scanned: number;
  totalCells: number;
  distanceToTarget: number;
  obstacleDistance: number;
};
export type LiveTelemetry = {
  source: string;
  is_simulated: boolean;
  captured_at: string;
  task_id: string | null;
  plan_version: string | null;
  position:
    | { frame: "WGS84"; lon_deg: number; lat_deg: number }
    | { frame: "NED" | "ENU"; x_m: number; y_m: number; z_m: number }
    | null;
  battery: number | null;
  voltage: number | null;
  current: number | null;
  energyWh: number | null;
  altitude: number | null;
  altitude_ref: "rel_takeoff" | "amsl" | "agl" | null;
  speed: number | null;
  climb: number | null;
  heading: number | null;
  pitch: number | null;
  roll: number | null;
  in_air: boolean | null;
  flight_mode: string | null;
  gps_fix: string | null;
};
export type TerrainPatch = {
  revision: number;
  source: string;
  capturedAt: string;
  mode?: "baseline" | "delta";
  cells: { x: number; y: number; height: number }[];
};
export type TerrainChange = {
  revision: number;
  count: number;
  maxDelta: number;
  source: string;
  capturedAt: string;
  bounds: { minX: number; minY: number; maxX: number; maxY: number } | null;
};
export type Layers = {
  buildings: boolean;
  terrain: boolean;
  restrictions: boolean;
  routes: boolean;
  scan: boolean;
};
export type SceneData = {
  metadata: { source: string; isSimulated: true; note: string };
  route: Point[];
  buildings: { id: string; polygon: Point[]; height: number }[];
  zones: { id: string; polygon: Point[] }[];
  sites: { id: string; point: Point }[];
};
