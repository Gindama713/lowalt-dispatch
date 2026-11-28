import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  Bell,
  Check,
  ChevronDown,
  ChevronUp,
  Compass,
  Expand,
  MapPin,
  Layers,
  Navigation,
  Pause,
  Play,
  Route,
  Settings2,
  ShieldCheck,
  Upload,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { enuToLngLat, type LngLat } from "../geo";
import type { LiveTelemetry, Point, SceneData, TerrainChange } from "../types";
import {
  altitudeLabel,
  guide,
  liveRouteProblem,
  liveSample,
  navigationAlerts,
  parseRoutes,
  routeDistance,
  routeMetrics,
  sampleAlong,
  terrainAhead,
  type NavPoint,
  type NavRoute,
  type NavigationOverlay,
} from "./engine";
import "./navigation.css";
import VoiceInput from "./VoiceInput";
import Preflight from "./Preflight";
import {
  assessPreflight,
  emptyPreflight,
  type PreflightRecord,
} from "./compliance";
import Airspace from "./AirspacePanel";
import {
  airspaceKinds,
  parseAirspaces,
  type AirspaceKind,
  type AirspaceRegion,
  type ConstraintSnapshotData,
} from "./airspace";

type Preferences = {
  deviation: number;
  battery: number;
  focusDistance: number;
  autoFocus: boolean;
  cruise: number;
  speech: "off" | "safety" | "all";
};
const defaults: Preferences = {
  deviation: 80,
  battery: 25,
  focusDistance: 250,
  autoFocus: true,
  cruise: 12,
  speech: "off",
};
function loadPreferences(): Preferences {
  try {
    const p = JSON.parse(
      localStorage.getItem("aeris.navigation.preferences") || "null",
    );
    return {
      deviation: p?.deviation >= 20 && p.deviation <= 500 ? p.deviation : 80,
      battery: p?.battery >= 20 && p.battery <= 50 ? p.battery : 25,
      focusDistance:
        p?.focusDistance >= 50 && p.focusDistance <= 1000
          ? p.focusDistance
          : 250,
      cruise: p?.cruise >= 1 && p.cruise <= 30 ? p.cruise : 12,
      autoFocus: typeof p?.autoFocus === "boolean" ? p.autoFocus : true,
      speech: ["off", "safety", "all"].includes(p?.speech) ? p.speech : "off",
    };
  } catch {
    return defaults;
  }
}
export const distance = (m: number | null | undefined) =>
  m == null
    ? "—"
    : m >= 1000
      ? `${(m / 1000).toFixed(2)} km`
      : `${m.toFixed(0)} m`;
export const duration = (s: number | null) =>
  s == null
    ? "—"
    : s < 60
      ? `${Math.ceil(s)} 秒`
      : `${Math.floor(s / 60)} 分 ${Math.ceil(s % 60)} 秒`;
export function xyRoute(
  id: string,
  title: string,
  points: Point[],
  source: string,
): NavRoute {
  return {
    id,
    title,
    frame: "ENU",
    waypoints: points.map((p, i) => ({
      x: p[0],
      y: p[1],
      altitude: null,
      label: `航点 ${i + 1}`,
    })),
    altitude_ref: null,
    source,
    is_simulated: true,
    task_id: null,
    plan_version: null,
    display_anchor: "demo",
  };
}
const toMap = (p: NavPoint, r: NavRoute): LngLat | null =>
  r.frame === "WGS84"
    ? [p.x, p.y]
    : r.display_anchor === "demo"
      ? enuToLngLat([p.x, p.y])
      : null;

type Input = {
  onRealCandidates: (route: NavRoute) => void;
  regions: AirspaceRegion[];
  setRegions: (regions: AirspaceRegion[]) => void;
  activeSnapshot?: ConstraintSnapshotData | null;
  onSyncAirspace?: (
    regions: AirspaceRegion[],
    mode?: "replace" | "known_empty" | "clear",
  ) => Promise<ConstraintSnapshotData | null>;
  liveMode: boolean;
  liveFrame: LiveTelemetry | null;
  liveStatus: string;
  history: LiveTelemetry[];
  progress: number;
  external: NavRoute[];
  terrain: TerrainChange | null;
  notify: (s: string) => void;
  onEvent: (
    title: string,
    detail: string,
    type?: "info" | "warning" | "success",
  ) => void;
  onActivate: () => void;
  readOnly: boolean;
};
export function useNavigation(input: Input) {
  const [open, setOpen] = useState(
      () =>
        new URLSearchParams(window.location.search).get("navigation") === "1",
    ),
    [tab, setTab] = useState<
      "routes" | "guide" | "preflight" | "settings" | "airspace"
    >("routes");
  const [preflight, setPreflight] = useState<PreflightRecord | null>(null);
  const [preflightDraft, setPreflightDraft] = useState(emptyPreflight);
  const { regions, setRegions } = input;
  const [regionKinds, setRegionKinds] = useState(
    Object.keys(airspaceKinds) as AirspaceKind[],
  );
  const [selectedRegion, setSelectedRegion] = useState("");
  const [regionError, setRegionError] = useState("");
  const visibleRegions = useMemo(
    () => regions.filter((r) => regionKinds.includes(r.kind)),
    [regions, regionKinds],
  );
  function toggleRegionKind(kind: AirspaceKind) {
    setRegionKinds((old) =>
      old.includes(kind) ? old.filter((k) => k !== kind) : [...old, kind],
    );
  }
  async function importAirspace(file: File) {
    setRegionError("");
    try {
      if (file.size > 5_000_000) throw new Error("空域文件不能超过5MB");
      const raw = JSON.parse(await file.text());
      const parsed = parseAirspaces(raw);
      setRegions(parsed);
      setRegionKinds(Object.keys(airspaceKinds) as AirspaceKind[]);
      setSelectedRegion(parsed[0].id);
      if (latest.current.onSyncAirspace) {
        await latest.current.onSyncAirspace(parsed, "replace");
      }
      latest.current.notify(
        `已载入并同步服务端快照（${parsed.length} 个区域）；来源与适用性仍需人工核实`,
      );
      latest.current.onEvent(
        "载入空域约束快照",
        `${parsed.length} 个区域已写入服务端快照；禁飞/内控区参与二维全高度避让，未改变飞控电子围栏。`,
      );
    } catch (e) {
      setRegionError(
        e instanceof Error ? e.message : "空域格式错误，原图层未改变",
      );
    }
  }
  async function clearAirspace(mode: "clear" | "known_empty" = "clear") {
    setRegionError("");
    setRegions([]);
    setSelectedRegion("");
    if (latest.current.onSyncAirspace) {
      await latest.current.onSyncAirspace([], mode);
    }
    latest.current.notify(
      mode === "known_empty"
        ? "已标记当前已知空域快照显式为空（0 区域）；官方空域仍须人工核对"
        : "本次导入图层与工作区活跃快照已移除；未改变真实空域或飞控限制",
    );
  }
  const [clock, setClock] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 30000);
    return () => window.clearInterval(timer);
  }, []);
  const [scene, setScene] = useState<SceneData | null>(null),
    [sceneError, setSceneError] = useState("");
  const [imported, setImported] = useState<NavRoute[]>([]),
    [candidates, setCandidates] = useState<NavRoute[]>([]);
  const [selection, setSelection] = useState("");
  const [comparisonId, setComparisonId] = useState("");
  const [enabled, setEnabled] = useState(false),
    [follow, setFollow] = useState(false);
  const [settings, setSettings] = useState(loadPreferences);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [candidateNote, setCandidateNote] = useState("");
  const [acknowledged, setAcknowledged] = useState<string[]>([]);
  const [speaking, setSpeaking] = useState(false);
  const latest = useRef(input);
  latest.current = input;
  const candidateAbort = useRef<AbortController | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    fetch("/demo-scene.json", { signal: abort.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error();
        const s = (await r.json()) as SceneData;
        if (
          s.metadata?.isSimulated !== true ||
          !Array.isArray(s.route) ||
          s.route.length < 2 ||
          s.route.some(
            (p) =>
              !Array.isArray(p) || p.length !== 2 || !p.every(Number.isFinite),
          )
        )
          throw new Error();
        setScene(s);
      })
      .catch((e) => {
        if (e.name !== "AbortError")
          setSceneError("演练航线加载失败；仍可导入有来源的航线。");
      });
    return () => {
      abort.abort();
      candidateAbort.current?.abort();
    };
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem(
        "aeris.navigation.preferences",
        JSON.stringify(settings),
      );
    } catch {
      /* Current session still works. */
    }
  }, [settings]);
  const base = useMemo(
    () =>
      scene
        ? [
            xyRoute(
              "demo-scene",
              "城区任务 · 演练基线",
              scene.route,
              "demo-scene.json · 构造演示场景",
            ),
          ]
        : [],
    [scene],
  );
  const routes = useMemo(
    () =>
      [
        ...input.external,
        ...imported,
        ...(input.liveMode ? [] : [...candidates, ...base]),
      ].filter((r, i, a) => a.findIndex((v) => v.id === r.id) === i),
    [input.external, imported, candidates, base, input.liveMode],
  );
  const route = routes.find((r) => r.id === selection) ?? routes[0] ?? null;
  const comparison =
    routes.find((r) => r.id === comparisonId && r.id !== route?.id) ?? null;
  // Route changes and source changes require explicit restart; no silent flight-state transfer.
  const routeFingerprint = useMemo(() => JSON.stringify(route), [route]);
  useEffect(() => {
    setEnabled(false);
    setFollow(false);
    setAcknowledged([]);
  }, [routeFingerprint, input.liveMode, input.liveFrame?.source]);
  const sample = useMemo(
    () =>
      input.liveMode
        ? input.liveStatus === "live"
          ? liveSample(input.liveFrame)
          : null
        : route
          ? {
              point: sampleAlong(route, input.progress),
              frame: route.frame,
              altitude_ref: route.altitude_ref,
              speed: settings.cruise,
              heading: null,
              battery: null,
            }
          : null,
    [
      input.liveMode,
      input.liveStatus,
      input.liveFrame,
      route,
      input.progress,
      settings.cruise,
    ],
  );
  const problem = input.liveMode
    ? liveRouteProblem(route, input.liveFrame, input.liveStatus)
    : route
      ? null
      : "选择或导入一条航线";
  const guidance = useMemo(
    () =>
      enabled && route && sample && !problem ? guide(route, sample) : null,
    [enabled, route, sample, problem],
  );
  const alerts = useMemo(() => {
    const result = enabled
      ? navigationAlerts(
          sample ?? {
            battery:
              input.liveMode && input.liveStatus === "live"
                ? (input.liveFrame?.battery ?? null)
                : null,
          },
          guidance,
          settings.deviation,
          settings.battery,
        )
      : [];
    if (
      enabled &&
      !input.liveMode &&
      route &&
      guidance &&
      input.terrain &&
      terrainAhead(route, guidance, input.terrain)
    )
      result.push({
        id: `terrain-${input.terrain.revision}`,
        severity: "warning",
        title: "前方航段涉及地形更新",
        detail: `场景地形 v${input.terrain.revision} 变化范围与前方航段在平面上重叠。来源：${input.terrain.source}；请重新核对垂直净空，此提示不等于碰撞判定。`,
      });
    return result;
  }, [
    enabled,
    sample,
    guidance,
    settings.deviation,
    settings.battery,
    input.terrain,
    input.liveMode,
    input.liveStatus,
    input.liveFrame?.battery,
    route,
  ]);
  const nearAction = Boolean(
    enabled &&
      guidance &&
      !guidance.arrived &&
      settings.autoFocus &&
      guidance.nextDistance <= settings.focusDistance &&
      (Math.abs(guidance.turn) > 25 ||
        Math.abs(guidance.altitudeDelta ?? 0) > 5),
  );
  const phase = !guidance
    ? input.liveMode && sample && !route
      ? "自由观察"
      : "等待定位"
    : guidance.arrived
      ? "接近终点"
      : guidance.along < Math.min(100, guidance.total * 0.1)
        ? "起始航段"
        : guidance.remaining < 300
          ? "终段进近"
          : nearAction
            ? "航点动作"
            : "航路巡航";
  const signature = alerts.map((a) => a.id + ":" + a.severity).join("|");
  const previouslyAlerted = useRef(new Set<string>());
  useEffect(() => {
    const current = new Set(alerts.map((a) => a.id + ":" + a.severity));
    for (const a of alerts)
      if (!previouslyAlerted.current.has(a.id + ":" + a.severity))
        latest.current.onEvent(
          `${latest.current.liveMode ? "导航提示" : "演练导航"} · ${a.title}`,
          a.detail,
          "warning",
        );
    previouslyAlerted.current = current;
  }, [signature]);
  useEffect(() => {
    setAcknowledged((p) => p.filter((id) => alerts.some((a) => a.id === id)));
  }, [signature]);
  const speechSupported =
    typeof window !== "undefined" && "speechSynthesis" in window;
  const lastSpoken = useRef("");
  const spokenText = enabled
    ? alerts[0]
      ? `${alerts[0].title}。${alerts[0].detail}`
      : settings.speech === "all" && nearAction && guidance
        ? `前方${Math.round(guidance.nextDistance)}米接近航点${guidance.nextIndex + 1}，请核对动作。`
        : ""
    : "";
  const speechKey = alerts[0]
    ? signature
    : nearAction
      ? `${route?.id}:${guidance?.nextIndex}`
      : "";
  useEffect(() => {
    if (!speechSupported || settings.speech === "off" || !enabled) {
      if (speechSupported) window.speechSynthesis.cancel();
      setSpeaking(false);
      lastSpoken.current = "";
      return;
    }
    if (!spokenText) {
      lastSpoken.current = "";
      return;
    }
    if (lastSpoken.current === speechKey) return;
    lastSpoken.current = speechKey;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(
      (input.liveMode ? "" : "演练提示。") + spokenText,
    );
    utterance.lang = "zh-CN";
    utterance.rate = 1.05;
    utterance.onstart = () => setSpeaking(true);
    utterance.onend = utterance.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utterance);
  }, [speechKey, settings.speech, enabled, speechSupported]);
  useEffect(
    () => () => {
      if (speechSupported) window.speechSynthesis.cancel();
    },
    [speechSupported],
  );
  const overlay = useMemo<NavigationOverlay>(() => {
    const active =
      route?.waypoints
        .map((p) => toMap(p, route))
        .filter((p): p is LngLat => p !== null) ?? [];
    const old =
      comparison?.waypoints
        .map((p) => toMap(p, comparison))
        .filter((p): p is LngLat => p !== null) ?? [];
    let flown: LngLat[][] = [];
    if (input.liveMode) {
      let segment: LngLat[] = [];
      let previous: LiveTelemetry | null = null;
      for (const f of input.history) {
        if (f.position?.frame !== "WGS84" || !liveSample(f)) {
          previous = null;
          if (segment.length > 1) flown.push(segment);
          segment = [];
          continue;
        }
        if (
          previous &&
          (f.source !== previous.source ||
            f.is_simulated !== previous.is_simulated ||
            f.task_id !== previous.task_id ||
            f.plan_version !== previous.plan_version ||
            Date.parse(f.captured_at) - Date.parse(previous.captured_at) > 5000)
        ) {
          if (segment.length > 1) flown.push(segment);
          segment = [];
        }
        segment.push([f.position.lon_deg, f.position.lat_deg]);
        previous = f;
      }
      if (segment.length > 1) flown.push(segment);
    } else if (route && guidance) {
      const points = route.waypoints
        .slice(0, guidance.nextIndex)
        .map((p) => toMap(p, route))
        .filter((p): p is LngLat => !!p);
      const current = toMap(guidance.projected, route);
      if (current) points.push(current);
      if (points.length > 1) flown = [points];
    }
    return {
      regions: visibleRegions,
      selectedRegion,
      active,
      comparison: old,
      flown,
      aircraft:
        enabled && sample && route && !problem
          ? toMap(sample.point, route)
          : null,
      target:
        guidance && route
          ? toMap(route.waypoints[guidance.nextIndex], route)
          : null,
      heading: sample?.heading ?? guidance?.bearing ?? null,
    };
  }, [
    route,
    comparison,
    input.liveMode,
    input.history,
    guidance,
    enabled,
    sample,
    problem,
    visibleRegions,
    selectedRegion,
  ]);
  async function importFile(file: File) {
    setError("");
    try {
      if (file.size > 1_000_000) throw new Error("航线文件不能超过1MB");
      const data = parseRoutes(JSON.parse(await file.text()));
      setImported((previous) =>
        [
          ...data,
          ...previous.filter((r) => !data.some((v) => v.id === r.id)),
        ].slice(0, 8),
      );
      setSelection(data[0].id);
      setEnabled(false);
      setFollow(false);
      latest.current.onEvent(
        "导入导航参考航线",
        `${data.length} 条；${data.map((r) => r.frame).join(" / ")}；未下发飞控。`,
      );
      latest.current.notify(`已导入 ${data.length} 条参考航线，尚未启用引导`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "航线文件格式错误");
    }
  }
  async function generateCandidates() {
    if (!scene || input.readOnly || busy) return;
    if (route?.frame === "WGS84") {
      latest.current.onRealCandidates(route);
      return;
    }
    candidateAbort.current?.abort();
    const abort = new AbortController();
    candidateAbort.current = abort;
    setBusy(true);
    setError("");
    const timer = window.setTimeout(() => abort.abort(), 30000);
    try {
      const [start, end] = route
        ? [
            [route.waypoints[0].x, route.waypoints[0].y],
            [
              route.waypoints[route.waypoints.length - 1].x,
              route.waypoints[route.waypoints.length - 1].y,
            ],
          ]
        : [scene.route[0], scene.route.at(-1)!];
      const response = await fetch("/api/assistant/navigation/candidates", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Aeris-Request": "1" },
        signal: abort.signal,
        body: JSON.stringify({
          origin: { x: start[0], y: start[1] },
          destination: { x: end[0], y: end[1] },
          frame: "ENU",
        }),
      });
      const data = await response.json();
      if (!response.ok)
        throw new Error(
          typeof data.detail === "string" ? data.detail : "场景方案计算失败",
        );
      const computed: NavRoute[] = data.alternatives
        .filter((a: { available: boolean }) => a.available)
        .flatMap((a: { route: unknown }) => parseRoutes(a.route))
        .map((r: NavRoute) => ({ ...r, display_anchor: "demo" }));
      setCandidates(computed);
      setCandidateNote(
        `${data.limitation} ${data.alternatives
          .filter((a: { available: boolean }) => !a.available)
          .map(
            (a: { title: string; reason: string }) => `${a.title}：${a.reason}`,
          )
          .join(" ")}`,
      );
      if (computed.length) {
        setComparisonId(route?.id ?? "");
        setSelection(computed[0].id);
        setEnabled(false);
        setFollow(false);
        latest.current.notify(
          `已计算 ${computed.length} 条几何方案，请比较后选择`,
        );
      }
    } catch (e) {
      if (candidateAbort.current === abort)
        setError(
          e instanceof Error && e.name !== "AbortError"
            ? e.message
            : "场景计算超时或已取消，请重试",
        );
    } finally {
      window.clearTimeout(timer);
      if (candidateAbort.current === abort) setBusy(false);
    }
  }
  function activate() {
    if (!route && !input.liveMode) return;
    setEnabled(true);
    setTab("guide");
    setOpen(true);
    setFollow(true);
    latest.current.onActivate();
    latest.current.notify(
      input.liveMode
        ? "已启用导航参考，未发送飞控指令"
        : "已开始航线演练，未发送飞控指令",
    );
  }
  return {
    ...input,
    open,
    setOpen,
    tab,
    setTab,
    sceneError,
    routes,
    route,
    comparison,
    setComparisonId,
    setSelection,
    enabled,
    setEnabled,
    follow,
    setFollow,
    settings,
    setSettings,
    error,
    setError,
    busy,
    candidateNote,
    importFile,
    generateCandidates,
    activate,
    sample,
    guidance,
    problem,
    alerts,
    nearAction,
    phase,
    overlay,
    acknowledged,
    setAcknowledged,
    speechSupported,
    speaking,
    preflight,
    setPreflight,
    preflightDraft,
    setPreflightDraft,
    regions,
    setRegions,
    regionKinds,
    toggleRegionKind,
    visibleRegions,
    selectedRegion,
    setSelectedRegion,
    regionError,
    importAirspace,
    clearAirspace,
    activeSnapshot: input.activeSnapshot ?? null,
    preflightAssessment: assessPreflight(
      preflight,
      route,
      input.liveMode,
      Math.max(clock, Date.now()),
    ),
  };
}
export type NavigationController = ReturnType<typeof useNavigation>;

function Profile({ nav }: { nav: NavigationController }) {
  const route = nav.route;
  if (!route) return null;
  const known =
    route.waypoints.every((p) => p.altitude != null) && route.altitude_ref;
  if (!known)
    return (
      <div className="nav-empty">
        <Compass size={23} />
        <div>
          <strong>高度剖面等待数据</strong>
          <p>
            航点需提供高度与统一基准。当前不会把地形高程、离地高度或相对高度混用。
          </p>
        </div>
      </div>
    );
  const metrics = routeMetrics(route),
    xs = [0];
  metrics.legs.forEach((d) => xs.push(xs.at(-1)! + d));
  const levels = route.waypoints.map((p) => p.altitude!);
  const actual =
    nav.sample?.altitude_ref === route.altitude_ref
      ? nav.sample.point.altitude
      : null;
  const min = Math.min(...levels, actual ?? Infinity) - 15,
    max = Math.max(...levels, actual ?? -Infinity) + 15;
  const y = (v: number) => 111 - ((v - min) / (max - min)) * 80;
  return (
    <div className="nav-profile">
      <header>
        <strong>垂直航路剖面</strong>
        <span>{altitudeLabel(route.altitude_ref)} / m · 无实测地形净空</span>
      </header>
      <svg viewBox="0 0 600 145" role="img" aria-label="航线高度剖面">
        <path
          className="nav-profile-grid"
          d="M35 30H580M35 70H580M35 110H580"
        />
        <text x="0" y="33">
          {max.toFixed(0)}
        </text>
        <text x="0" y="113">
          {min.toFixed(0)}
        </text>
        <polyline
          points={levels
            .map((v, i) => `${35 + (xs[i] / metrics.length) * 545},${y(v)}`)
            .join(" ")}
          className="nav-profile-line"
        />
        {nav.guidance && actual != null && (
          <circle
            cx={35 + (nav.guidance.along / metrics.length) * 545}
            cy={y(actual)}
            r="5"
            className="nav-profile-aircraft"
          />
        )}
        <text x="35" y="139">
          起点
        </text>
        <text x="520" y="139">
          {distance(metrics.length)}
        </text>
      </svg>
    </div>
  );
}
export function NavigationHUD({ nav }: { nav: NavigationController }) {
  const g = nav.guidance;
  if (!nav.enabled || !nav.open) return null;
  return (
    <div
      className={`nav-hud ${nav.nearAction ? "action-focus" : ""}`}
      role="region"
      aria-label="航点导航引导"
    >
      <header>
        <span>
          <Navigation size={15} />
          {nav.liveMode ? "导航参考" : "演练导航"} · {nav.phase}
        </span>
        <button aria-label="收起导航引导" onClick={() => nav.setOpen(false)}>
          <ChevronUp size={16} />
        </button>
      </header>
      {g && nav.route ? (
        <>
          <div className="nav-hud-direction">
            <Compass
              size={34}
              style={{ transform: `rotate(${g.headingError ?? 0}deg)` }}
            />
            <div>
              <strong>
                {g.arrived ? "已接近航线终点" : distance(g.nextDistance)}
              </strong>
              <span>
                {g.arrived
                  ? "几何到达提示，任务完成以执行回执为准"
                  : `前往 ${nav.route.waypoints[g.nextIndex].label}`}
              </span>
            </div>
          </div>
          <div className="nav-hud-details">
            <span>航向 {g.bearing.toFixed(0)}°</span>
            <span>剩余 {distance(g.remaining)}</span>
            <span>预计 {duration(g.eta)}</span>
          </div>
          <div
            className="nav-progress"
            role="progressbar"
            aria-label="沿航线几何进度"
            aria-valuenow={Math.round((g.along / g.total) * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <i style={{ width: `${(g.along / g.total) * 100}%` }} />
          </div>
          {nav.nearAction && (
            <p className="nav-action">
              <MapPin size={13} />
              动作聚焦：
              {Math.abs(g.turn) > 25
                ? `${g.turn > 0 ? "右" : "左"}转约 ${Math.abs(g.turn).toFixed(0)}°`
                : "高度变更"}
              {g.altitudeDelta != null
                ? ` · 高度差 ${g.altitudeDelta > 0 ? "+" : ""}${g.altitudeDelta.toFixed(0)} m`
                : " · 目标高度未提供"}
            </p>
          )}
        </>
      ) : (
        <p className="nav-paused">{nav.problem ?? "等待可用位置"}</p>
      )}
      <footer>
        <button
          aria-pressed={nav.follow}
          onClick={() => nav.setFollow((v) => !v)}
        >
          <Navigation size={13} />
          {nav.follow ? "跟随中" : "恢复跟随"}
        </button>
        <span>
          {nav.route?.frame} · {nav.route?.plan_version ?? "无执行版本"}
        </span>
      </footer>
    </div>
  );
}
export function NavigationWorkspace({
  nav,
  onOverview,
  onAreaOverview,
  onAssistant,
  onPlayback,
  playing,
}: {
  nav: NavigationController;
  onOverview: () => void;
  onAreaOverview: (points: LngLat[]) => void;
  onAssistant: () => void;
  onPlayback: (playing: boolean) => void;
  playing: boolean;
}) {
  const file = useRef<HTMLInputElement>(null);
  const [command, setCommand] = useState("");
  const [confirm, setConfirm] = useState(false);
  function download(value: unknown, name: string) {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    nav.notify("文件已生成");
  }
  const example = {
    id: "route-v1",
    title: "示例参考航线",
    frame: "WGS84",
    altitude_ref: "rel_takeoff",
    source: "手工导入示例 · 请替换为实际任务数据",
    is_simulated: true,
    task_id: "example-task",
    plan_version: "v1",
    waypoints: [
      { x: 121.4737, y: 31.2304, altitude: 100, label: "起点" },
      { x: 121.4767, y: 31.2334, altitude: 120, label: "巡检点" },
      { x: 121.4797, y: 31.2314, altitude: 100, label: "终点" },
    ],
  };
  const selected = nav.route;
  const compatibleComparison =
    nav.comparison && selected && nav.comparison.frame === selected.frame;
  const comparisonDelta =
    compatibleComparison && nav.comparison && selected
      ? routeMetrics(nav.comparison).length - routeMetrics(selected).length
      : null;
  const currentAlerts = nav.alerts.filter(
    (a) => !nav.acknowledged.includes(a.id) || a.severity === "critical",
  );
  function executeCommand() {
    const text = command.trim();
    setCommand("");
    if (!text) return;
    if (/^(全览|航线全览|查看全览)$/.test(text)) {
      nav.setFollow(false);
      onOverview();
    } else if (/^(跟随|恢复跟随)$/.test(text)) {
      nav.setFollow(true);
      nav.notify("已恢复跟随视角");
    } else if (/^(静音|关闭播报)$/.test(text)) {
      nav.setSettings((s) => ({ ...s, speech: "off" }));
      nav.notify("播报已静音");
    } else if (/^(暂停演练|继续演练)$/.test(text) && !nav.liveMode) {
      onPlayback(text === "继续演练");
      nav.notify(text);
    } else if (/^(打开助手|询问助手)$/.test(text)) {
      onAssistant();
    } else
      nav.notify(
        "此入口只调整视图和演练。支持：全览、跟随、静音、暂停演练、继续演练、打开助手。",
      );
  }
  return (
    <section
      className={`nav-workspace ${nav.open ? "expanded" : ""}`}
      aria-label="无人机导航工作区"
    >
      <button
        className="nav-launch"
        onClick={() => nav.setOpen((v) => !v)}
        aria-expanded={nav.open}
      >
        <span className="nav-launch-icon">
          <Navigation size={19} />
        </span>
        <span>
          <strong>飞行导航</strong>
          <small>
            {nav.enabled
              ? (nav.problem ??
                `${nav.phase} · ${distance(nav.guidance?.remaining)} 剩余`)
              : nav.liveMode
                ? "任务与版本校验 · 参考引导"
                : "选择航线 → 比较方案 → 演练引导"}
          </small>
        </span>
        <span className="nav-mode-tag">
          {nav.liveMode ? "LIVE 参考" : "DEMO 演练"}
        </span>
        {nav.alerts.length > 0 && (
          <b className="nav-alert-count">{nav.alerts.length} 项提示</b>
        )}
        {nav.open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>
      {nav.enabled &&
        currentAlerts.length > 0 &&
        (!nav.open || nav.tab !== "guide") && (
          <div
            className={`nav-priority-alert ${currentAlerts[0].severity}`}
            role="alert"
          >
            <Bell size={17} />
            <div>
              <strong>{currentAlerts[0].title}</strong>
              <p>{currentAlerts[0].detail}</p>
            </div>
            <button
              className="nav-button"
              onClick={() => {
                nav.setOpen(true);
                nav.setTab("guide");
              }}
            >
              查看处置提示
            </button>
          </div>
        )}
      {nav.open && (
        <div className="nav-body">
          <nav className="nav-tabs" aria-label="导航工作区分页">
            {(
              [
                ["routes", "航线与方案", Route],
                ["guide", "导航与告警", Compass],
                ["airspace", "空域图层", Layers],
                ["preflight", "飞前核对", ShieldCheck],
                ["settings", "导航设置", Settings2],
              ] as const
            ).map(([id, label, Icon]) => (
              <button
                key={id}
                aria-pressed={nav.tab === id}
                onClick={() => nav.setTab(id)}
              >
                <Icon size={14} />
                {label}
              </button>
            ))}
            <span>WGS‑84 / ENU · 视图操作不下发飞控</span>
          </nav>
          {(nav.error || nav.sceneError) && (
            <div className="nav-error" role="alert">
              {nav.error || nav.sceneError}
              <button
                aria-label="关闭导航错误"
                onClick={() => nav.setError("")}
              >
                <X size={14} />
              </button>
            </div>
          )}
          {nav.preflight &&
            nav.preflightAssessment.issues.length > 0 &&
            nav.tab !== "preflight" && (
              <div className="nav-compliance-summary">
                <span>
                  飞前资料有 {nav.preflightAssessment.issues.length} 项待复核 ·
                  不影响遥测观察
                </span>
                <button
                  className="nav-link"
                  onClick={() => nav.setTab("preflight")}
                >
                  查看核对记录
                </button>
              </div>
            )}
          {nav.tab === "preflight" && (
            <Preflight nav={nav} download={download} />
          )}
          {nav.tab === "airspace" && (
            <Airspace
              nav={nav}
              download={download}
              onOverview={onAreaOverview}
            />
          )}
          {nav.tab === "routes" && (
            <>
              <div className="nav-section-heading">
                <div>
                  <h3>先选航线，再开始导航</h3>
                  <p>
                    蓝色为当前参考，紫色虚线为对比方案。真实地点需导入 WGS‑84
                    航线，地图直连线不作为规划结果。地图航线为水平投影，高度以剖面为准。
                  </p>
                </div>
                <div className="nav-inline">
                  <input
                    ref={file}
                    type="file"
                    hidden
                    accept=".json,application/json"
                    onChange={(e) => {
                      if (e.target.files?.[0])
                        void nav.importFile(e.target.files[0]);
                      e.target.value = "";
                    }}
                  />
                  <button
                    className="nav-button"
                    onClick={() => file.current?.click()}
                  >
                    <Upload size={14} />
                    导入航线 JSON
                  </button>
                  <button
                    className="nav-link"
                    onClick={() =>
                      download(example, "navigation-route-example.json")
                    }
                  >
                    下载示例
                  </button>
                </div>
              </div>
              <div className="nav-route-grid">
                {nav.routes.map((r) => {
                  const m = routeMetrics(r);
                  return (
                    <article
                      key={r.id}
                      className={`nav-route-card ${selected?.id === r.id ? "selected" : ""}`}
                    >
                      <header>
                        <span className="nav-frame">
                          {r.frame} · {r.is_simulated ? "仿真" : "真实来源声明"}
                        </span>
                        {selected?.id === r.id && <Check size={17} />}
                      </header>
                      <h4>{r.title}</h4>
                      <div className="nav-route-metrics">
                        <div>
                          <strong>{distance(m.length)}</strong>
                          <small>水平航程</small>
                        </div>
                        <div>
                          <strong>
                            {duration(m.length / nav.settings.cruise)}
                          </strong>
                          <small>按 {nav.settings.cruise} m/s 估算</small>
                        </div>
                        <div>
                          <strong>
                            {m.maxAltitude == null
                              ? "—"
                              : `${m.maxAltitude.toFixed(0)} m`}
                          </strong>
                          <small>
                            最高航点 · {altitudeLabel(r.altitude_ref)}
                          </small>
                        </div>
                      </div>
                      <p title={r.source}>{r.source}</p>
                      <small>
                        {r.plan_version
                          ? `${r.task_id} / ${r.plan_version}`
                          : "未绑定飞行任务版本"}{" "}
                        · 能耗 / 备降待校验
                      </small>
                      <footer>
                        <button
                          className="nav-button"
                          aria-pressed={selected?.id === r.id}
                          onClick={() => {
                            nav.setSelection(r.id);
                            nav.setEnabled(false);
                            nav.setFollow(false);
                            setConfirm(false);
                            nav.notify("参考方案已切换，需重新启用引导");
                          }}
                        >
                          {selected?.id === r.id ? "已选参考" : "选择为参考"}
                        </button>
                        <button
                          className="nav-link"
                          disabled={selected?.id === r.id}
                          aria-pressed={nav.comparison?.id === r.id}
                          onClick={() =>
                            nav.setComparisonId(
                              nav.comparison?.id === r.id ? "" : r.id,
                            )
                          }
                        >
                          {nav.comparison?.id === r.id
                            ? "移除对比"
                            : "叠加对比"}
                        </button>
                      </footer>
                    </article>
                  );
                })}
              </div>
              {!nav.routes.length && (
                <div className="nav-empty">
                  暂无可用航线；可导入带坐标系、来源和版本的 JSON 文件。
                </div>
              )}
              {!nav.liveMode && (
                <div className="nav-candidate-callout">
                  <div>
                    <strong>比较不同净空的场景方案</strong>
                    <p>
                      调用仓库几何 A*，以30 / 60
                      m膨胀参数计算固定场景的两条路线。不会把真实地图选点套入演示坐标。
                    </p>
                  </div>
                  <button
                    className="nav-button"
                    disabled={nav.busy || nav.readOnly}
                    onClick={() => void nav.generateCandidates()}
                  >
                    {nav.busy ? "正在实际计算…" : "计算场景方案"}
                  </button>
                </div>
              )}
              {nav.candidateNote && (
                <p className="nav-note">{nav.candidateNote}</p>
              )}
              {nav.comparison && (
                <div className="nav-comparison">
                  <Route size={18} />
                  <div>
                    <strong>
                      当前：{selected?.title}　/　对比：{nav.comparison.title}
                    </strong>
                    <p>
                      {comparisonDelta == null
                        ? "不同坐标系，仅保留数值查看，不判定路线优劣。"
                        : `对比方案比当前${comparisonDelta >= 0 ? "长" : "短"} ${distance(Math.abs(comparisonDelta))}。`}
                      {selected &&
                      nav.comparison.frame === selected.frame &&
                      routeDistance(
                        selected.waypoints[0],
                        nav.comparison.waypoints[0],
                        selected.frame,
                      ) > 20
                        ? "起点不同，不构成同一任务的优劣比较。"
                        : ""}{" "}
                      对比与选择均不替换已执行任务。
                    </p>
                  </div>
                  <button
                    className="nav-link"
                    onClick={() => nav.setComparisonId("")}
                  >
                    清除
                  </button>
                </div>
              )}
              <div className="nav-start-row">
                <p>
                  <ShieldCheck size={16} />
                  {nav.liveMode
                    ? "实时引导需要坐标系、任务ID、航线版本和仿真标记一致。"
                    : "演练位置沿所选航线插值；速度为估算参数，不代表真实飞控。"}
                </p>
                <button
                  className="nav-button primary"
                  disabled={!selected && !nav.liveMode}
                  onClick={() => {
                    if (nav.enabled) nav.setTab("guide");
                    else setConfirm(true);
                  }}
                >
                  <Navigation size={15} />
                  {nav.enabled
                    ? "查看导航引导"
                    : nav.liveMode
                      ? selected
                        ? "启用参考引导"
                        : "开始自由观察"
                      : "开始航线演练"}
                </button>
              </div>
              {confirm && (
                <div
                  className="nav-review"
                  role="region"
                  aria-label="导航参考确认"
                >
                  <strong>
                    {selected
                      ? `启用「${selected.title}」的导航参考`
                      : "启用无航线自由观察"}
                  </strong>
                  <p>
                    {selected?.frame} · {selected?.waypoints.length}{" "}
                    个航点。此操作只启用显示与提示，不解锁、不起飞、不修改正在执行的航线。
                  </p>
                  <p>
                    真实作业前请在“飞前核对”确认适用资料；地图参考、演练和告警均不授予飞行许可。
                  </p>
                  <div className="nav-inline">
                    <button
                      className="nav-button"
                      onClick={() => setConfirm(false)}
                    >
                      返回比较
                    </button>
                    <button
                      className="nav-button primary"
                      onClick={() => {
                        setConfirm(false);
                        nav.activate();
                      }}
                    >
                      确认启用参考
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
          {nav.tab === "guide" && (
            <>
              <div className="nav-section-heading">
                <div>
                  <h3>{nav.enabled ? nav.phase : "导航尚未启用"}</h3>
                  <p>
                    {nav.enabled
                      ? (nav.problem ??
                        "沿航线几何投影计算，结果仅作为态势参考。")
                      : "先在“航线与方案”中选择并确认参考路线。"}
                  </p>
                </div>
                <div className="nav-inline">
                  <button
                    className="nav-button"
                    onClick={() => {
                      nav.setFollow(false);
                      onOverview();
                    }}
                  >
                    <Expand size={14} />
                    航线全览
                  </button>
                  <button
                    className="nav-button"
                    disabled={!nav.enabled}
                    aria-pressed={nav.follow}
                    onClick={() => nav.setFollow((v) => !v)}
                  >
                    <Navigation size={14} />
                    {nav.follow ? "跟随中" : "恢复跟随"}
                  </button>
                  {!nav.liveMode && (
                    <button
                      className="nav-button"
                      onClick={() => onPlayback(!playing)}
                    >
                      {playing ? <Pause size={14} /> : <Play size={14} />}{" "}
                      {playing ? "暂停演练" : "继续演练"}
                    </button>
                  )}
                </div>
              </div>
              <div className="nav-guide-grid">
                <div className="nav-guide-card">
                  <div>
                    <span>下一航点距离</span>
                    <strong>{distance(nav.guidance?.nextDistance)}</strong>
                    <small>
                      {nav.guidance && selected
                        ? selected.waypoints[nav.guidance.nextIndex].label
                        : "等待可用位置"}
                    </small>
                  </div>
                  <div>
                    <span>沿航路剩余</span>
                    <strong>{distance(nav.guidance?.remaining)}</strong>
                    <small>
                      预计 {duration(nav.guidance?.eta ?? null)} · 停止时不估时
                    </small>
                  </div>
                  <div>
                    <span>水平偏航</span>
                    <strong>{distance(nav.guidance?.crossTrack)}</strong>
                    <small>阈值 {nav.settings.deviation} m</small>
                  </div>
                  <div>
                    <span>目标高度差</span>
                    <strong>
                      {nav.guidance?.altitudeDelta == null
                        ? "—"
                        : `${nav.guidance.altitudeDelta > 0 ? "+" : ""}${nav.guidance.altitudeDelta.toFixed(0)} m`}
                    </strong>
                    <small>
                      {altitudeLabel(selected?.altitude_ref ?? null)}
                    </small>
                  </div>
                </div>
                <Profile nav={nav} />
              </div>
              <div className="nav-alerts" aria-live="polite">
                <header>
                  <Bell size={15} />
                  <strong>主动安全提示</strong>
                  <span>{nav.liveMode ? "基于当前可用遥测" : "演练模式"}</span>
                </header>
                {currentAlerts.length ? (
                  currentAlerts.map((a) => (
                    <div
                      className={`nav-alert ${a.severity}`}
                      role={a.severity === "critical" ? "alert" : "status"}
                      key={a.id}
                    >
                      <span className="nav-severity">
                        {a.severity === "critical" ? "紧急" : "关注"}
                      </span>
                      <div>
                        <strong>{a.title}</strong>
                        <p>{a.detail}</p>
                      </div>
                      {a.severity !== "critical" && (
                        <button
                          className="nav-link"
                          onClick={() =>
                            nav.setAcknowledged((p) => [...p, a.id])
                          }
                        >
                          已知悉
                        </button>
                      )}
                    </div>
                  ))
                ) : (
                  <p className="nav-note">
                    {nav.enabled
                      ? "当前可用指标未触发阈值提示；不等于已通过完整安全评估。"
                      : "启用导航后显示阈值提示。"}
                  </p>
                )}
                <p className="nav-data-gaps">
                  待接数据：障碍物距离、交通目标、有效空域与机型能耗。当前不输出碰撞判定、禁飞区合法性或返航安全半径。
                </p>
              </div>
              <form
                className="nav-command"
                onSubmit={(e) => {
                  e.preventDefault();
                  executeCommand();
                }}
              >
                <label htmlFor="navigation-command">不中断地图的快捷操作</label>
                <div>
                  <input
                    id="navigation-command"
                    value={command}
                    onChange={(e) => setCommand(e.target.value)}
                    placeholder="输入“全览”“跟随”“静音”或“打开助手”"
                    maxLength={100}
                  />
                  <VoiceInput onText={setCommand} notify={nav.notify} />
                  <button type="submit" className="nav-button">
                    执行视图操作
                  </button>
                </div>
                <p className="nav-note">
                  语音由浏览器识别，可能使用其在线服务；仅填入文字，核对后再执行。飞行指令请通过任务审核流程。
                </p>
              </form>
              <div className="nav-start-row">
                <button
                  className="nav-link"
                  onClick={() => nav.setTab("routes")}
                >
                  返回方案选择
                </button>
                <div className="nav-inline">
                  <button
                    className="nav-button"
                    disabled={!nav.enabled}
                    onClick={() =>
                      download(
                        {
                          captured_at: new Date().toISOString(),
                          source: nav.liveMode
                            ? nav.liveFrame?.source
                            : "navigation rehearsal",
                          is_simulated: nav.liveMode
                            ? nav.liveFrame?.is_simulated
                            : true,
                          route: nav.route,
                          guidance: nav.guidance,
                          blocked_reason: nav.problem,
                          alerts: nav.alerts,
                          preflight: nav.preflight,
                          preflight_assessment: nav.preflightAssessment,
                          airspace_regions: nav.regions,
                          visible_airspace_categories: nav.regionKinds,
                          dispatch_enabled: false,
                        },
                        "navigation-reference.json",
                      )
                    }
                  >
                    <ArrowDownToLine size={14} />
                    导出导航记录
                  </button>
                  <button
                    className="nav-link"
                    disabled={!nav.enabled}
                    onClick={() => {
                      nav.setEnabled(false);
                      nav.setFollow(false);
                      nav.notify("导航参考已结束，飞控任务未受影响");
                    }}
                  >
                    结束参考引导
                  </button>
                </div>
              </div>
            </>
          )}
          {nav.tab === "settings" && (
            <>
              <div className="nav-section-heading">
                <div>
                  <h3>按任务调整提醒强度</h3>
                  <p>
                    偏好保存在本机浏览器；阈值用于辅助提示，不是飞行器性能或飞控保护参数。
                  </p>
                </div>
                <button
                  className="nav-link"
                  onClick={() => {
                    nav.setSettings(defaults);
                    nav.notify("已恢复导航默认设置");
                  }}
                >
                  恢复默认
                </button>
              </div>
              <div className="nav-settings-grid">
                <label>
                  偏航提醒阈值
                  <select
                    value={nav.settings.deviation}
                    onChange={(e) =>
                      nav.setSettings((s) => ({
                        ...s,
                        deviation: Number(e.target.value),
                      }))
                    }
                  >
                    {[20, 50, 80, 100, 200, 500].map((v) => (
                      <option key={v} value={v}>
                        {v} m
                      </option>
                    ))}
                  </select>
                  <small>水平距离，过期或版本不一致时暂停计算。</small>
                </label>
                <label>
                  低电量提醒
                  <select
                    value={nav.settings.battery}
                    onChange={(e) =>
                      nav.setSettings((s) => ({
                        ...s,
                        battery: Number(e.target.value),
                      }))
                    }
                  >
                    {[20, 25, 30, 40, 50].map((v) => (
                      <option key={v} value={v}>
                        {v}%
                      </option>
                    ))}
                  </select>
                  <small>≤15%持续紧急提示；无法代替机型返航阈值。</small>
                </label>
                <label>
                  演练巡航速度
                  <select
                    value={nav.settings.cruise}
                    onChange={(e) =>
                      nav.setSettings((s) => ({
                        ...s,
                        cruise: Number(e.target.value),
                      }))
                    }
                  >
                    {[3, 5, 8, 12, 15, 20, 30].map((v) => (
                      <option key={v} value={v}>
                        {v} m/s
                      </option>
                    ))}
                  </select>
                  <small>仅用于估时；实时导航使用遥测地速。</small>
                </label>
                <label>
                  动作聚焦距离
                  <select
                    value={nav.settings.focusDistance}
                    onChange={(e) =>
                      nav.setSettings((s) => ({
                        ...s,
                        focusDistance: Number(e.target.value),
                      }))
                    }
                  >
                    {[50, 100, 250, 500, 1000].map((v) => (
                      <option key={v} value={v}>
                        {v} m
                      </option>
                    ))}
                  </select>
                  <small>接近明显转向或高度变化时显示聚焦提示。</small>
                </label>
                <label>
                  语音播报
                  <select
                    disabled={!nav.speechSupported}
                    value={nav.settings.speech}
                    onChange={(e) =>
                      nav.setSettings((s) => ({
                        ...s,
                        speech: e.target.value as Preferences["speech"],
                      }))
                    }
                  >
                    <option value="off">关闭播报</option>
                    <option value="safety">仅安全提示</option>
                    <option value="all">安全与航点动作</option>
                  </select>
                  <small>
                    {nav.speechSupported
                      ? "使用浏览器语音引擎；系统语音可用性决定播报效果。"
                      : "当前浏览器不支持语音合成，文字提示始终可用。"}
                  </small>
                </label>
                <label className="nav-check">
                  <input
                    type="checkbox"
                    checked={nav.settings.autoFocus}
                    onChange={(e) =>
                      nav.setSettings((s) => ({
                        ...s,
                        autoFocus: e.target.checked,
                      }))
                    }
                  />
                  自动显示航点动作聚焦
                  <small>
                    仅跟随模式调整地图比例尺；手动拖动立即释放跟随。
                  </small>
                </label>
              </div>
              <div className="nav-note nav-inline">
                {nav.settings.speech === "off" ? (
                  <VolumeX size={17} />
                ) : (
                  <Volume2 size={17} />
                )}{" "}
                {nav.speaking ? "正在播报" : "语音播报"} ·
                飞行操作继续通过任务审核和执行回执流程完成。
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
