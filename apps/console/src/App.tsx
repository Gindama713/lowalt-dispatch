import { DispatchPanel } from "./DispatchPanel";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  AudioLines,
  Bell,
  Box,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Cloud,
  CloudRain,
  CloudSun,
  Command,
  Compass,
  Crosshair,
  Download,
  Droplets,
  Expand,
  Eye,
  EyeOff,
  FileText,
  Focus,
  Gauge,
  Globe2,
  Layers3,
  LayoutDashboard,
  Link2,
  Map,
  MapPin,
  Maximize2,
  Minus,
  MoreHorizontal,
  Mountain,
  Navigation,
  Orbit,
  PanelRightClose,
  Pause,
  Play,
  Plus,
  Radar,
  Radio,
  RefreshCw,
  Route,
  Satellite,
  ScanLine,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  SquareTerminal,
  Target,
  Thermometer,
  Timer,
  TriangleAlert,
  Wifi,
  Wind,
  X,
  Zap,
} from "lucide-react";
import MapSurface, { type MapSurfaceHandle } from "./MapSurface";
import LocationPanel from "./LocationPanel";
import {
  Drone,
  LiveLocalTrack,
  LiveTelemetryDetails,
} from "./LiveTelemetryPanel";
import EventFeed, { replayEvents } from "./EventFeed";
import RadarDisplay from "./RadarDisplay";
import Onboarding from "./Onboarding";
import RouteReview, { type ReviewRoute } from "./RouteReview";
import {
  enuToLngLat,
  formatCoordinates,
  loadGeoMission,
  validGeoPlace,
  validLngLat,
  type GeoMission,
  type GeoPlace,
  type LngLat,
} from "./geo";
import "./enhancements.css";
import { Attitude, MarginChart, Sparkline } from "./Charts";
import { demoPatch, TerrainModel } from "./terrain";
import {
  fetchRadarFrames,
  fetchWeather,
  weatherCodeLabel,
  windDirectionLabel,
  type RadarFrame,
  type WeatherSnapshot,
} from "./weather";
import { useFlight, useLiveTelemetry } from "./useFlight";
import Assistant from "./assistant/Assistant";
import type { AssistantDraft, PreviewRoute } from "./assistant/types";
import type {
  Basemap,
  EventItem,
  Layers,
  PanelId,
  TerrainChange,
  TerrainPatch,
  ViewMode,
} from "./types";

const metric = (value: number | null | undefined, digits = 1) =>
  value?.toFixed(digits) ?? "—";

/** 把 Promise.allSettled 的 rejection 归一成可展示的中文提示。 */
const errorText = (reason: unknown, fallback: string) =>
  reason instanceof Error && reason.message ? reason.message : fallback;

const initialEvents: EventItem[] = [
  {
    id: "e3",
    time: "13:44:26",
    type: "success",
    title: "航线校验流程演示",
    detail: "模拟校验回执 · 非安全性结论",
  },
  {
    id: "e2",
    time: "13:44:24",
    type: "info",
    title: "任务数据已载入",
    detail: "T-S1-01 · 几何基线 / 266个航点",
  },
  {
    id: "e1",
    time: "13:44:22",
    type: "info",
    title: "演示遥测流已就绪",
    detail: "合成参数 · 未连接 PX4 / 华为云",
  },
];
const panelNames: Record<PanelId, string> = {
  mission: "任务概览",
  instruments: "飞行仪表",
  analysis: "航线分析",
  events: "事件流",
  perception: "感知与搜索",
};
const defaultPanels: Record<PanelId, boolean> = {
  mission: true,
  instruments: true,
  analysis: true,
  events: true,
  perception: true,
};
type WeatherStatus = "idle" | "loading" | "ok" | "error";
/** 公开气象/雷达在界面内的完整状态（全部免 key、演示参考）。 */
type WeatherState = {
  snapshot: WeatherSnapshot | null;
  status: WeatherStatus;
  error: string;
  radarEnabled: boolean;
  radarFrames: RadarFrame[] | null;
  radarFrame: number;
  radarError: string;
  windEnabled: boolean;
};
const initialWeather: WeatherState = {
  snapshot: null,
  status: "idle",
  error: "",
  radarEnabled: false,
  radarFrames: null,
  radarFrame: 0,
  radarError: "",
  windEnabled: true,
};
type TaskDraft = {
  name: string;
  payload: string;
  origin: string;
  destination: string;
  priority: string;
  geo?: GeoMission;
};
function loadDrafts(): TaskDraft[] {
  try {
    const value = JSON.parse(localStorage.getItem("aeris-drafts-v1") || "[]");
    return Array.isArray(value)
      ? value
          .filter(
            (d) =>
              d &&
              ["name", "payload", "origin", "destination", "priority"].every(
                (k) => typeof d[k] === "string" && d[k].length <= 200,
              ),
          )
          .slice(0, 100)
      : [];
  } catch {
    return [];
  }
}
const time = () =>
  new Date().toLocaleTimeString("zh-CN", {
    hour12: false,
    timeZone: "Asia/Shanghai",
  });
function loadPreferences() {
  try {
    const stored = JSON.parse(localStorage.getItem("aeris-console-v1") || "{}");
    return {
      panels: {
        ...defaultPanels,
        ...Object.fromEntries(
          Object.keys(defaultPanels).map((k) => [
            k,
            typeof stored.panels?.[k] === "boolean" ? stored.panels[k] : true,
          ]),
        ),
      },
      mode: stored.mode === "2d" ? ("2d" as const) : ("3d" as const),
    };
  } catch {
    return { panels: defaultPanels, mode: "3d" as const };
  }
}

function IconButton({
  children,
  label,
  onClick,
  active = false,
  className = "",
  ...rest
}: {
  children: ReactNode;
  label: string;
  onClick?: () => void;
  active?: boolean;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className={`icon-button ${active ? "is-active" : ""} ${className}`}
      aria-label={label}
      title={label}
      onClick={onClick}
      {...rest}
    >
      {children}
    </button>
  );
}
function PanelTitle({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children?: ReactNode;
}) {
  return (
    <div className="panel-title">
      <h2>
        {title}
        {subtitle && <span>{subtitle}</span>}
      </h2>
      {children}
    </div>
  );
}
function Rotor({
  index,
  rpm,
  playing,
}: {
  index: number;
  rpm: number;
  playing: boolean;
}) {
  return (
    <div className="rotor">
      <svg viewBox="0 0 58 58" aria-hidden="true">
        <circle cx="29" cy="29" r="25" fill="none" stroke="#2b333d" />
        <circle
          cx="29"
          cy="29"
          r="22"
          fill="none"
          stroke="#776a9d"
          strokeDasharray="2 7"
          opacity=".5"
        />
        <g
          className={playing ? "rotor-spin" : ""}
          style={{ animationDirection: index % 2 ? "reverse" : "normal" }}
        >
          {[0, 120, 240].map((angle) => (
            <path
              key={angle}
              d="M29 28 C24 22 24 12 28 8 C33 12 34 22 29 28"
              fill="#aeb4c4"
              transform={`rotate(${angle} 29 29)`}
            />
          ))}
        </g>
        <circle cx="29" cy="29" r="3" fill="#c3b0ff" />
      </svg>
      <span>M{index + 1}</span>
      <strong>{rpm.toLocaleString("en-US")}</strong>
    </div>
  );
}

/**
 * 任务区公开气象 HUD。
 * 数据来自 Open-Meteo（当前风/阵风/能见度/云量/降水/温度）与 RainViewer 雷达，
 * 均为免 key 公开数据，卡片仅标注来源与更新时间。
 */
function WeatherHud({
  state,
  open,
  onToggle,
  onRetry,
}: {
  state: WeatherState;
  open: boolean;
  onToggle: () => void;
  onRetry: () => void;
}) {
  const snapshot = state.snapshot;
  const frames = state.radarFrames;
  const frame =
    frames && frames.length
      ? frames[Math.min(state.radarFrame, frames.length - 1)]
      : null;
  const updatedLabel = snapshot
    ? new Date(snapshot.updatedAt).toLocaleTimeString("zh-CN", { hour12: false })
    : null;
  const visibilityKm =
    snapshot?.visibilityM == null
      ? "—"
      : (snapshot.visibilityM / 1000).toFixed(1);
  const windLabel = windDirectionLabel(snapshot?.windDirDeg ?? null);
  const loading = state.status === "loading";
  const radarLabel = frame
    ? `${frame.label} · ${Math.min(state.radarFrame, frames!.length - 1) + 1}/${frames!.length}`
    : state.radarError
      ? "暂不可用"
      : "加载中";
  return (
    <section
      className={`weather-hud glass ${open ? "" : "collapsed"} ${
        state.status === "error" ? "has-error" : ""
      } ${loading ? "is-loading" : ""}`}
      aria-label="任务区公开气象"
    >
      <header className="weather-hud-head">
        <span className="weather-hud-title">
          <CloudSun size={13} /> 任务区气象 <small>公开数据</small>
        </span>
        <div className="weather-hud-actions">
          {loading && (
            <span className="weather-sync" aria-label="正在刷新天气">
              <RefreshCw size={11} />
            </span>
          )}
          <button
            onClick={onToggle}
            aria-label={open ? "折叠天气卡片" : "展开天气卡片"}
            aria-expanded={open}
          >
            <ChevronDown size={13} />
          </button>
        </div>
      </header>
      {!open ? (
        <div className="weather-hud-compact">
          <Wind size={12} />
          {metric(snapshot?.windSpeedMs)} m/s · {windLabel}
          {state.status === "error" && (
            <span className="weather-mini-error">数据不可用</span>
          )}
        </div>
      ) : state.status === "error" && !snapshot ? (
        <div className="weather-empty" role="status">
          <TriangleAlert size={14} />
          <span>天气数据不可用</span>
          <button onClick={onRetry}>重试</button>
        </div>
      ) : (state.status === "loading" || state.status === "idle") &&
        !snapshot ? (
        <div className="weather-empty" role="status">
          <RefreshCw size={14} />
          <span>正在获取任务区气象…</span>
        </div>
      ) : (
        <>
          <div className="weather-hero">
            <span
              className="weather-wind-arrow"
              style={{ transform: `rotate(${snapshot?.windDirDeg ?? 0}deg)` }}
              aria-hidden="true"
            >
              <Wind size={16} />
            </span>
            <div className="weather-hero-main">
              <strong>
                {metric(snapshot?.windSpeedMs)}
                <small>m/s</small>
              </strong>
              <span>
                {windLabel} · 来向 {metric(snapshot?.windDirDeg, 0)}°
              </span>
            </div>
            <div className="weather-temp">
              <strong>
                {metric(snapshot?.temperatureC)}
                <small>°C</small>
              </strong>
              <span>{weatherCodeLabel(snapshot?.code ?? null)}</span>
            </div>
          </div>
          <div className="weather-grid">
            <div>
              <span>
                <Wind size={10} /> 阵风
              </span>
              <strong>
                {metric(snapshot?.gustMs)}
                <small>m/s</small>
              </strong>
            </div>
            <div>
              <span>
                <Eye size={10} /> 能见度
              </span>
              <strong>
                {visibilityKm}
                <small>km</small>
              </strong>
            </div>
            <div>
              <span>
                <Cloud size={10} /> 云量
              </span>
              <strong>
                {metric(snapshot?.cloudPct, 0)}
                <small>%</small>
              </strong>
            </div>
            <div>
              <span>
                <Droplets size={10} /> 降水
              </span>
              <strong>
                {metric(snapshot?.precipMm, 2)}
                <small>mm</small>
              </strong>
            </div>
          </div>
          {state.radarEnabled && (
            <div className="weather-radar-row">
              <span>
                <Radar size={10} /> 雷达回波
              </span>
              <strong>{radarLabel}</strong>
            </div>
          )}
          {state.status === "error" && (
            <div className="weather-stale" role="status">
              天气数据不可用 · 重试
              <button onClick={onRetry} aria-label="重试天气数据">
                <RefreshCw size={11} />
              </button>
            </div>
          )}
          <footer className="weather-hud-foot">
            <span>Open-Meteo 公开气象数据</span>
            {updatedLabel && (
              <time dateTime={snapshot?.updatedAt}>{updatedLabel} 更新</time>
            )}
          </footer>
        </>
      )}
    </section>
  );
}

export default function App() {
  const preferences = useRef(loadPreferences()).current;
  const [panels, setPanels] = useState<Record<PanelId, boolean>>(
    preferences.panels,
  );
  const [mode, setMode] = useState<ViewMode>(preferences.mode);
  const [playing, setPlaying] = useState(true);
  const [focus, setFocus] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [assistantPreview, setAssistantPreview] = useState<PreviewRoute | null>(
    null,
  );
  const [assistantFocus, setAssistantFocus] = useState("");
  const [drawer, setDrawer] = useState<
    | "panels"
    | "tasks"
    | "events"
    | "settings"
    | "help"
    | "new"
    | "routes"
    | "dispatch"
    | null
  >(null);
  const [layers, setLayers] = useState<Layers>({
    buildings: true,
    terrain: true,
    restrictions: true,
    routes: true,
    scan: true,
    hillshade: true,
  });
  const [showLayers, setShowLayers] = useState(false);
  const [compare, setCompare] = useState(true);
  const [reviewRoute, setReviewRoute] = useState<ReviewRoute | null>(null);
  const [mapKind, setMapKind] = useState<"world" | "terrain">("world");
  const [showGeographic, setShowGeographic] = useState(false);
  const [demoVisible, setDemoVisible] = useState(true);
  const [realTerrain, setRealTerrain] = useState(false);
  const [basemap, setBasemap] = useState<Basemap>("dark");
  const [weather, setWeather] = useState<WeatherState>(initialWeather);
  const [weatherOpen, setWeatherOpen] = useState(true);
  const [weatherNonce, setWeatherNonce] = useState(0);
  const [mapStatus, setMapStatus] = useState("连接真实底图");
  const [locationOpen, setLocationOpen] = useState(false);
  const [selectedPlace, setSelectedPlace] = useState<GeoPlace | null>(null);
  const [geoMission, setGeoMission] = useState<GeoMission>(loadGeoMission);
  const [terrainModel] = useState(() => new TerrainModel());
  const [motionReduced, setMotionReduced] = useState(() => {
    try {
      return (
        localStorage.getItem("aeris-motion") === "reduced" ||
        window.matchMedia("(prefers-reduced-motion: reduce)").matches
      );
    } catch {
      return false;
    }
  });
  const [onboarding, setOnboarding] = useState(false);
  const [ready, setReady] = useState(false);
  const [mapError, setMapError] = useState("");
  const [manualEvents, setEvents] = useState(initialEvents);
  const [toast, setToast] = useState("");
  const [terrain, setTerrain] = useState<TerrainChange | null>(null);
  const [terrainAuto, setTerrainAuto] = useState(false);
  const [clock, setClock] = useState(time());
  const [coordinate, setCoordinate] = useState<LngLat>(
    enuToLngLat([1284, 1460]),
  );
  const [drafts, setDrafts] = useState<TaskDraft[]>(loadDrafts);
  const [socketUrl, setSocketUrl] = useState("");
  const [socketState, setSocketState] = useState<
    "offline" | "connecting" | "online"
  >("offline");
  const socket = useRef<WebSocket | null>(null);
  const map = useRef<MapSurfaceHandle>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const dialog = useRef<HTMLElement>(null);
  const revision = useRef(0);
  const [liveMode, setLiveMode] = useState(
    () =>
      new URLSearchParams(window.location.search).get("telemetry") === "live",
  );
  const {
    telemetry: t,
    progress,
    tick,
    setProgress,
  } = useFlight(playing && !liveMode);
  const {
    frame: liveFrame,
    history: liveHistory,
    status: liveStatus,
  } = useLiveTelemetry(liveMode);
  const readings = liveMode ? liveFrame : t;
  const liveSource =
    liveFrame?.source === "sim:px4_sitl" || liveFrame?.source === "fc:px4_sitl"
      ? "PX4 SITL"
      : (liveFrame?.source ?? "M4");
  const liveStatusText = {
    connecting: "正在连接遥测",
    waiting: "等待遥测",
    live: "实时",
    stale: "遥测已过期",
    offline: "遥测连接中断",
  }[liveStatus];
  const position = liveFrame?.position;
  const localTrackAvailable = liveMode && position?.frame !== "WGS84";
  const showLocalTrack =
    localTrackAvailable && !showGeographic && !locationOpen;
  const coordinates =
    liveMode && liveStatus === "live" && position?.frame === "WGS84"
      ? [position.lon_deg, position.lat_deg]
      : null;
  const livePoint = validLngLat(coordinates) ? coordinates : null;
  const altitudeLabel = liveMode
    ? { agl: "离地高度", amsl: "海拔高度", rel_takeoff: "相对起飞点高度" }[
        liveFrame?.altitude_ref ?? "rel_takeoff"
      ]
    : "相对高度";
  const events = useMemo(
    () =>
      [
        ...manualEvents.filter(
          (e) => !initialEvents.some((initial) => initial.id === e.id),
        ),
        ...replayEvents(progress),
        ...manualEvents.filter((e) =>
          initialEvents.some((initial) => initial.id === e.id),
        ),
      ].slice(0, 100),
    [manualEvents, progress],
  );

  // 天气坐标优先取任务起点，否则使用地图当前选点/中心。
  const weatherTarget = useMemo<LngLat>(
    () => geoMission.origin?.point ?? coordinate,
    [geoMission.origin, coordinate],
  );
  useEffect(() => {
    let disposed = false;
    const controller = new AbortController();
    const [lng, lat] = weatherTarget;
    const load = async () => {
      setWeather((w) => ({ ...w, status: "loading", error: "" }));
      const [weatherResult, radarResult] = await Promise.allSettled([
        fetchWeather(lng, lat, controller.signal),
        fetchRadarFrames(controller.signal),
      ]);
      if (disposed) return;
      setWeather((current) => {
        const next = { ...current };
        if (weatherResult.status === "fulfilled") {
          next.snapshot = weatherResult.value;
          next.status = "ok";
          next.error = "";
        } else {
          next.status = "error";
          next.error = errorText(weatherResult.reason, "天气数据不可用");
        }
        if (radarResult.status === "fulfilled") {
          next.radarFrames = radarResult.value.frames;
          next.radarFrame = Math.max(
            0,
            Math.min(current.radarFrame, radarResult.value.frames.length - 1),
          );
          next.radarError = "";
        } else {
          next.radarFrames = null;
          next.radarFrame = 0;
          next.radarError = errorText(radarResult.reason, "雷达回波暂不可用");
        }
        return next;
      });
    };
    void load();
    // 公开气象每 10 分钟刷新一次；坐标变化由依赖重置。
    const timer = window.setInterval(() => void load(), 10 * 60 * 1000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      controller.abort();
    };
  }, [weatherTarget, weatherNonce]);
  // 雷达帧轮播：仅开启雷达且未减少动态效果时播放（帧来自 RainViewer 最近 2–3 帧）。
  useEffect(() => {
    if (!weather.radarEnabled || motionReduced) return;
    const count = weather.radarFrames?.length ?? 0;
    if (count < 2) return;
    const timer = window.setInterval(() => {
      setWeather((w) => {
        const total = w.radarFrames?.length ?? 0;
        return total < 2
          ? w
          : { ...w, radarFrame: (w.radarFrame + 1) % total };
      });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [weather.radarEnabled, weather.radarFrames, motionReduced]);
  const mapWeather = useMemo(() => {
    const frames = weather.radarFrames;
    const index =
      frames && frames.length
        ? Math.min(weather.radarFrame, frames.length - 1)
        : -1;
    const frame = index >= 0 ? frames![index] : null;
    const snapshot = weather.snapshot;
    const wind =
      weather.windEnabled &&
      snapshot &&
      snapshot.windSpeedMs !== null &&
      snapshot.windDirDeg !== null
        ? { speedMs: snapshot.windSpeedMs, dirDeg: snapshot.windDirDeg }
        : null;
    return {
      radarTiles:
        weather.radarEnabled && frame ? [frame.tiles] : (null as string[] | null),
      radarVisible: weather.radarEnabled && Boolean(frame),
      radarOpacity: 0.55,
      wind,
    };
  }, [
    weather.radarEnabled,
    weather.radarFrames,
    weather.radarFrame,
    weather.windEnabled,
    weather.snapshot,
  ]);

  const notify = useCallback((message: string) => setToast(message), []);
  const addEvent = useCallback(
    (title: string, detail: string, type: EventItem["type"] = "info") =>
      setEvents((e) =>
        [
          { id: crypto.randomUUID(), time: time(), title, detail, type },
          ...e,
        ].slice(0, 100),
      ),
    [],
  );
  const togglePanel = useCallback(
    (key: PanelId) => setPanels((p) => ({ ...p, [key]: !p[key] })),
    [],
  );
  const selectPlace = useCallback((place: GeoPlace) => {
    setSelectedPlace(place);
    setCoordinate(place.point);
    setLocationOpen(true);
    setAssistantFocus("");
    map.current?.flyTo(place.point);
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem("aeris-geo-mission-v1", JSON.stringify(geoMission));
    } catch {
      /* Export still available. */
    }
  }, [geoMission]);
  useEffect(() => {
    try {
      localStorage.setItem("aeris-motion", motionReduced ? "reduced" : "full");
    } catch {
      /* Optional preference. */
    }
  }, [motionReduced]);
  const applyTerrain = useCallback(
    (patch: TerrainPatch) => {
      try {
        if (!map.current) throw new Error("地图尚未就绪");
        const result = map.current.applyTerrain(patch);
        revision.current = result.revision;
        setTerrain(result);
        if (result.count)
          addEvent(
            "识别到地形高程变化",
            `${result.count} 个网格超过2 m阈值 · 最大 Δ ${result.maxDelta.toFixed(1)} m · ${result.source}`,
            "warning",
          );
        else
          addEvent("地形增量已更新", `版本 ${result.revision} · 未超过2 m阈值`);
        notify(
          result.count
            ? `已定位 ${result.count} 个变化网格`
            : "地形更新完成，无显著变化",
        );
      } catch (error) {
        notify(error instanceof Error ? error.message : "地形数据处理失败");
      }
    },
    [addEvent, notify],
  );
  const simulateTerrain = useCallback(
    () => applyTerrain(demoPatch(revision.current + 1)),
    [applyTerrain],
  );
  useEffect(() => {
    const timer = setInterval(() => setClock(time()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3600);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    try {
      localStorage.setItem(
        "aeris-console-v1",
        JSON.stringify({ panels, mode }),
      );
    } catch {
      /* Private mode may disable persistence. */
    }
  }, [panels, mode]);
  useEffect(() => {
    try {
      localStorage.setItem("aeris-drafts-v1", JSON.stringify(drafts));
    } catch {
      /* Snapshot export remains available when storage is disabled. */
    }
  }, [drafts]);
  useEffect(() => {
    if (!playing || !terrainAuto || !ready) return;
    const timer = setInterval(simulateTerrain, 8000);
    return () => clearInterval(timer);
  }, [playing, terrainAuto, ready, simulateTerrain]);
  useEffect(() => () => socket.current?.close(), []);
  useEffect(() => {
    if (!drawer) return;
    const previous = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() =>
      dialog.current
        ?.querySelector<HTMLElement>("button,input,select")
        ?.focus(),
    );
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const elements = [
        ...(dialog.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled),input:not(:disabled),select:not(:disabled),a[href]",
        ) || []),
      ].filter((e) => !e.hidden && e.offsetParent !== null);
      const first = elements[0],
        last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", trapFocus);
    const siblings = [
      ...document.querySelectorAll<HTMLElement>(
        ".topbar,.rail,.main,.assistant-panel,.assistant-launcher",
      ),
    ];
    siblings.forEach((element) => {
      element.inert = true;
    });
    return () => {
      cancelAnimationFrame(frame);
      siblings.forEach((element) => {
        element.inert = false;
      });
      document.removeEventListener("keydown", trapFocus);
      previous?.focus();
    };
  }, [drawer]);
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDrawer(null);
        setShowLayers(false);
        setFocus(false);
        setAssistantOpen(false);
      }
      if (
        drawer ||
        (event.target as HTMLElement).closest("input,textarea,select") ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey
      )
        return;
      if (event.key.toLowerCase() === "f") setFocus((v) => !v);
      if (event.key.toLowerCase() === "a") setAssistantOpen((v) => !v);
      if (event.key.toLowerCase() === "l") {
        setMapKind("world");
        setLocationOpen((v) => !v);
      }
      if (event.key === "?") setOnboarding((v) => !v);
      if (event.key.toLowerCase() === "v")
        setMode((v) => (v === "3d" ? "2d" : "3d"));
      if (event.code === "Space") {
        if ((event.target as HTMLElement).closest("button")) return;
        event.preventDefault();
        setPlaying((v) => !v);
      }
      if (["1", "2", "3", "4", "5"].includes(event.key))
        togglePanel(
          (
            [
              "mission",
              "instruments",
              "analysis",
              "events",
              "perception",
            ] as PanelId[]
          )[Number(event.key) - 1],
        );
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [togglePanel, drawer]);

  const exportSnapshot = () => {
    const body = {
      schema_version: "aeris-ui-0.1",
      exported_at: new Date().toISOString(),
      provenance: {
        is_simulated: liveMode ? (liveFrame?.is_simulated ?? null) : true,
        source: liveMode ? (liveFrame?.source ?? null) : "frontend demo",
        captured_at: liveMode ? (liveFrame?.captured_at ?? null) : null,
        telemetry_mode: liveMode ? "live" : "demo",
        telemetry_status: liveMode ? liveStatus : null,
      },
      telemetry: readings,
      terrain,
      events,
      progress: liveMode ? null : progress,
      drafts,
      geographic_mission: {
        crs: "EPSG:4326",
        ...geoMission,
        route_status: "not_planned",
        basemap: mapStatus,
        demo_anchor_is_georeferenced: false,
      },
      comparison: reviewRoute
        ? {
            id: reviewRoute.id,
            source: reviewRoute.source,
            is_simulated: true,
            captured_at: reviewRoute.captured_at,
          }
        : null,
    };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(body, null, 2)], { type: "application/json" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `aeris-${liveMode ? "TELEMETRY" : "DEMO"}-${Date.now()}.json`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    // Give the browser time to start the download before releasing its source.
    window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
    notify(
      liveMode
        ? "已导出遥测快照，含采样时间和来源"
        : "已导出演示快照，含数据来源标识",
    );
  };
  const connectTerrain = () => {
    if (socket.current) {
      socket.current.close();
      socket.current = null;
      setSocketState("offline");
      return;
    }
    try {
      const url = new URL(socketUrl);
      if (
        !["ws:", "wss:"].includes(url.protocol) ||
        (url.protocol === "ws:" &&
          !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)) ||
        url.username ||
        url.password
      )
        throw new Error("远程地形流请使用 wss://，本机可用 ws://");
      setTerrainAuto(false);
      setSocketState("connecting");
      const ws = new WebSocket(url);
      socket.current = ws;
      ws.onopen = () => {
        setSocketState("online");
        addEvent(
          "地形数据流已连接",
          "等待 terrain.patch 数据；飞行仪表仍为演示数据",
        );
      };
      ws.onmessage = (event) => {
        try {
          if (typeof event.data !== "string" || event.data.length > 1000000)
            throw new Error();
          const data = JSON.parse(event.data);
          if (data.type !== "terrain.patch") throw new Error();
          applyTerrain(data.patch);
        } catch {
          notify("已忽略不合法的地形数据消息");
        }
      };
      ws.onerror = () => notify("地形流连接失败，请检查地址和服务状态");
      ws.onclose = () => {
        if (socket.current === ws) {
          socket.current = null;
          setSocketState("offline");
        }
      };
    } catch (error) {
      notify(error instanceof Error ? error.message : "连接失败");
      setSocketState("offline");
    }
  };

  const saveAssistantDraft = (draft: AssistantDraft) => {
    if (!draft.origin || !draft.destination || draft.payload_kg === null)
      return false;
    const value: TaskDraft = {
      name: draft.name,
      payload: String(draft.payload_kg),
      origin: draft.origin,
      destination: draft.destination,
      priority: draft.priority === "P1" ? "P1 · 应急" : "P2 · 常规",
    };
    if (drafts.length >= 100) {
      notify("任务草稿已达100条，请先导出整理");
      return false;
    }
    if (drafts.some((d) => JSON.stringify(d) === JSON.stringify(value))) {
      notify("任务空间已有相同草稿");
      return true;
    }
    setDrafts((previous) => [...previous, value]);
    notify("已确认保存到任务空间，尚未下发");
    return true;
  };

  return (
    <div
      className={`app ${focus ? "focus-mode" : ""} ${playing ? "" : "paused"} ${assistantOpen ? "assistant-open" : ""} ${motionReduced ? "motion-reduced" : ""} ${locationOpen ? "locating" : ""}`}
    >
      <header className="topbar">
        <a className="brand" href="#" aria-label="AERIS 低空智能调度台">
          <span className="brand-mark">
            <Orbit size={25} />
          </span>
          <span>
            AERIS<span className="brand-period">.</span>
            <small>低空智能调度</small>
          </span>
        </a>
        <div className="top-divider" />
        <nav className="top-nav" aria-label="主导航">
          <button className="active" onClick={() => setDrawer(null)}>
            态势总览
          </button>
          <button onClick={() => setDrawer("tasks")}>
            任务空间<span>{String(1 + drafts.length).padStart(2, "0")}</span>
          </button>
          <button onClick={() => setDrawer("events")}>飞行记录</button>
        </nav>
        <div className="top-right">
          <button
            className="environment"
            aria-label="实时遥测"
            aria-pressed={liveMode}
            title={liveMode ? "切换到演示回放" : "切换到 M4 实时遥测"}
            onClick={() => {
              if (!liveMode) setMapKind("world");
              setLiveMode(!liveMode);
            }}
          >
            <span className="status-dot" /> {liveMode ? "LIVE" : "DEMO"}{" "}
            <span className="environment-label">
              {liveMode ? "实时遥测" : "演示数据"}
            </span>
          </button>
          <time className="clock">
            {clock}
            <small>UTC+8</small>
          </time>
          <span className="top-divider" />
          <IconButton label="通知与事件" onClick={() => setDrawer("events")}>
            <Bell size={17} />
            <i className="notification-dot" />
          </IconButton>
          <button
            className="avatar"
            title="flora-0627 · 本地演示工作区"
            onClick={() => setDrawer("settings")}
          >
            F
          </button>
        </div>
      </header>

      <aside className="rail" aria-label="工具栏">
        <div className="rail-top">
          <IconButton
            label="态势总览"
            active
            onClick={() => {
              setDrawer(null);
              setFocus(false);
            }}
          >
            <LayoutDashboard size={20} />
          </IconButton>
          <IconButton
            label="任务空间"
            active={drawer === "tasks"}
            onClick={() => setDrawer("tasks")}
          >
            <Route size={20} />
          </IconButton>
          <IconButton
            label="地形数据设置"
            active={drawer === "settings"}
            onClick={() => setDrawer("settings")}
          >
            <Layers3 size={20} />
          </IconButton>
          <IconButton
            label="飞行事件"
            active={drawer === "events"}
            onClick={() => setDrawer("events")}
          >
            <Activity size={20} />
          </IconButton>
          <span className="rail-line" />
          <span className="assistant-rail-button">
            <IconButton
              label="调度助手 A"
              active={assistantOpen}
              onClick={() => setAssistantOpen((v) => !v)}
            >
              <Sparkles size={20} />
            </IconButton>
          </span>
          <IconButton
            label="组件管理"
            active={drawer === "panels"}
            onClick={() => setDrawer("panels")}
          >
            <SlidersHorizontal size={20} />
          </IconButton>
        </div>
        <div className="rail-bottom">
          <IconButton label="快捷键与说明" onClick={() => setDrawer("help")}>
            <CircleHelp size={19} />
          </IconButton>
          <IconButton label="设置" onClick={() => setDrawer("settings")}>
            <Settings2 size={19} />
          </IconButton>
          <span className="rail-version">V.01</span>
        </div>
      </aside>

      <main className="main">
        <div className="page-heading">
          <div>
            <div className="eyebrow">
              <span /> MISSION CONTROL <ChevronRight size={11} /> WORKSPACE 01
            </div>
            <h1>
              低空任务指挥台 <span>全域感知，从容决策。</span>
            </h1>
          </div>
          <div className="heading-actions">
            <button
              className="button subtle"
              onClick={() => setDrawer("panels")}
            >
              <SlidersHorizontal size={14} /> 组件管理 <kbd>1–5</kbd>
            </button>
            <button
              className="button subtle export-button"
              onClick={exportSnapshot}
            >
              <ArrowDownToLine size={14} /> 导出快照
            </button>
            <button className="button primary" onClick={() => setDrawer("new")}>
              <Plus size={16} /> 新建任务
            </button>
            <button
              className="button subtle"
              onClick={() => setDrawer("dispatch")}
            >
              <Link2 size={15} /> 本地任务联调
            </button>
          </div>
        </div>

        <section className="summary-strip" aria-label="任务状态概览">
          <div className="summary-current">
            <span className="tiny-drone">
              <Drone size={21} />
            </span>
            <div>
              <strong>
                {liveMode ? liveSource : "AER-01"}{" "}
                <span>
                  {liveMode
                    ? liveFrame?.is_simulated
                      ? "仿真遥测"
                      : "遥测"
                    : "四旋翼 · 仿真机"}
                </span>
              </strong>
              <small>
                {(!liveMode || liveStatus === "live") && (
                  <span className="status-dot" />
                )}{" "}
                {liveMode
                  ? liveStatusText
                  : playing
                    ? "演示巡航中"
                    : "演示已暂停"}{" "}
                <span className="muted">
                  /{" "}
                  {liveMode ? (liveFrame?.flight_mode ?? "—") : "AUTO.MISSION"}
                </span>
              </small>
            </div>
            <ChevronDown size={14} />
          </div>
          <div className="summary-item">
            <span>{liveMode ? "电量 / 电压" : "任务编号"}</span>
            <strong>
              {liveMode ? (
                <>
                  {metric(liveFrame?.battery)}
                  <small>%</small>
                  <small> / {metric(liveFrame?.voltage)} V</small>
                </>
              ) : (
                <>
                  T-S1-01 <i>BASELINE</i>
                </>
              )}
            </strong>
          </div>
          <div className="summary-item">
            <span>{liveMode ? "地速" : "航程进度"}</span>
            <strong>
              {liveMode ? (
                <>
                  {metric(liveFrame?.speed)} <small>m/s</small>
                </>
              ) : (
                <>
                  {(progress * 3.67).toFixed(2)} <small>/ 3.67 km</small>
                </>
              )}
            </strong>
          </div>
          <div className="summary-item">
            <span>
              {liveMode ? (
                "俯仰 / 横滚"
              ) : (
                <>
                  剩余航时 <small>示例</small>
                </>
              )}
            </span>
            <strong>
              {liveMode ? (
                <>
                  {metric(liveFrame?.pitch)}° <small>/</small>{" "}
                  {metric(liveFrame?.roll)}°
                </>
              ) : (
                <>
                  08<span className="colon">:</span>42 <small>min</small>
                </>
              )}
            </strong>
          </div>
          <div className="summary-item link-summary">
            <span>{liveMode ? "遥测状态" : "云边链路"}</span>
            <strong>
              <Radio size={14} />{" "}
              {liveMode ? (
                liveStatusText
              ) : (
                <>
                  演示连接 <small>{t.rtt} ms</small>
                </>
              )}
            </strong>
          </div>
          <div className="summary-safe">
            <ShieldCheck size={16} />
            <div>
              备降约束可视化<small>示例数据 · 未作安全判定</small>
            </div>
          </div>
        </section>

        {liveMode && !focus && (
          <div className="telemetry-section-nav">
            <a href="#live-telemetry-details">
              <Activity size={13} /> 遥测明细与趋势 <ArrowDownRight size={12} />
            </a>
          </div>
        )}
        <div
          className={`workspace ${panels.instruments && !focus ? "" : "no-instruments"}`}
        >
          <section className="map-panel panel" aria-label="地图与航线">
            <div className="map-toolbar">
              <div className="map-title">
                <span className="live-dot" />
                <strong>{showLocalTrack ? "局部轨迹" : "空域态势"}</strong>
                <span className="map-breadcrumb">
                  {showLocalTrack
                    ? (position?.frame ?? "局部定位")
                    : mapKind === "world"
                      ? basemap === "satellite"
                        ? "ESRI WORLD IMAGERY / WGS84"
                        : "CARTO DARK MATTER / WGS84"
                      : "地形实验 / ENU · 3 × 3 km"}
                </span>
              </div>
              <div className="map-toolbar-actions">
                <button
                  className={`map-locate-button ${locationOpen ? "selected" : ""}`}
                  aria-label="地点定位 L"
                  onClick={() => {
                    setMapKind("world");
                    setLocationOpen((v) => !v);
                  }}
                  title="地点定位 L"
                >
                  <MapPin size={13} />
                  <span>地点定位</span>
                </button>
                {mapKind === "world" && !showLocalTrack && (
                  <button
                    className={`map-surface-toggle basemap-toggle ${
                      basemap === "satellite" ? "selected" : ""
                    }`}
                    aria-pressed={basemap === "satellite"}
                    aria-label="切换卫星实景底图"
                    title="暗色底图 / 卫星实景（Esri World Imagery，免 key）"
                    onClick={() =>
                      setBasemap((value) =>
                        value === "satellite" ? "dark" : "satellite",
                      )
                    }
                  >
                    {basemap === "satellite" ? (
                      <Satellite size={13} />
                    ) : (
                      <Map size={13} />
                    )}
                    <span>
                      {basemap === "satellite" ? "卫星实景" : "暗色底图"}
                    </span>
                  </button>
                )}
                {localTrackAvailable && !locationOpen && (
                  <button
                    className="map-surface-toggle live-map-toggle"
                    onClick={() => {
                      setShowGeographic((value) => !value);
                      setReady(false);
                      setMapError("");
                    }}
                  >
                    {showLocalTrack ? (
                      <Globe2 size={13} />
                    ) : (
                      <Compass size={13} />
                    )}
                    {showLocalTrack ? "真实底图" : "局部轨迹"}
                  </button>
                )}
                {!liveMode && (
                  <button
                    className="map-surface-toggle"
                    onClick={() => {
                      setMapKind((k) => (k === "world" ? "terrain" : "world"));
                      setLocationOpen(false);
                      setMapError("");
                    }}
                    title="在真实地图与原始地形实验视图间切换"
                  >
                    {mapKind === "world" ? (
                      <>
                        <Mountain size={13} />
                        <span>地形实验</span>
                      </>
                    ) : (
                      <>
                        <Globe2 size={13} />
                        <span>真实地图</span>
                      </>
                    )}
                  </button>
                )}
                <div className="segmented" hidden={showLocalTrack}>
                  <button
                    className={mode === "2d" ? "selected" : ""}
                    aria-pressed={mode === "2d"}
                    onClick={() => setMode("2d")}
                  >
                    2D
                  </button>
                  <button
                    className={mode === "3d" ? "selected" : ""}
                    aria-pressed={mode === "3d"}
                    onClick={() => setMode("3d")}
                  >
                    <Box size={12} /> 3D
                  </button>
                </div>
                {!showLocalTrack && (
                  <IconButton
                    label="地图图层"
                    active={showLayers}
                    onClick={() => setShowLayers((v) => !v)}
                  >
                    <Layers3 size={15} />
                  </IconButton>
                )}
                <IconButton
                  label={focus ? "退出专注视图" : "专注视图 F"}
                  active={focus}
                  onClick={() => setFocus((v) => !v)}
                >
                  <Expand size={15} />
                </IconButton>
              </div>
            </div>
            {showLocalTrack && (
              <LiveLocalTrack
                history={liveHistory}
                active={liveStatus === "live"}
              />
            )}
            <div className="map-stage" hidden={showLocalTrack}>
              {!showLocalTrack && (
                <MapSurface
                  ref={map}
                  mode={mode}
                  basemap={basemap}
                  layers={layers}
                  progress={progress}
                  playing={playing}
                  onReady={() => setReady(true)}
                  onError={setMapError}
                  onPoint={(point) =>
                    selectPlace({
                      name: "地图选点",
                      point,
                      source: "map_click",
                      capturedAt: new Date().toISOString(),
                    })
                  }
                  preview={assistantPreview}
                  comparison={reviewRoute}
                  kind={liveMode ? "world" : mapKind}
                  demoVisible={!liveMode && demoVisible}
                  liveMode={liveMode}
                  livePoint={livePoint}
                  realTerrain={realTerrain}
                  reducedMotion={motionReduced}
                  terrainModel={terrainModel}
                  mission={geoMission}
                  selected={selectedPlace}
                  weather={mapWeather}
                  onStatus={setMapStatus}
                />
              )}
              {mapKind === "world" && (
                <LocationPanel
                  open={locationOpen}
                  onClose={() => setLocationOpen(false)}
                  selected={selectedPlace}
                  mission={geoMission}
                  onSelect={selectPlace}
                  onAssign={(key, place) => {
                    setGeoMission((m) => ({ ...m, [key]: place }));
                    if (place)
                      addEvent(
                        `已设置真实${key === "origin" ? "起点" : "终点"}`,
                        `${place.name} · WGS84 ${formatCoordinates(place.point)} · 未规划`,
                      );
                  }}
                  onTask={() => setDrawer("new")}
                  onError={notify}
                />
              )}
              {onboarding && (
                <Onboarding
                  onClose={() => setOnboarding(false)}
                  onLocate={() => {
                    setMapKind("world");
                    setLocationOpen(true);
                  }}
                />
              )}
              {!ready && !mapError && (
                <div className="map-loading">
                  <Orbit size={25} className="spin-slow" />
                  <span>构建数字空域…</span>
                </div>
              )}
              {mapError && (
                <div className="map-loading" role="alert">
                  <TriangleAlert size={25} />
                  <span>{mapError}</span>
                </div>
              )}
              <div className="map-vignette" />
              {!liveMode &&
                reviewRoute &&
                mapKind === "world" &&
                demoVisible &&
                layers.routes && (
                  <div className="review-map-label">
                    <Route size={11} />
                    历史方案对比 · {reviewRoute.id} · DEMO
                    <button
                      aria-label="关闭历史方案对比"
                      onClick={() => setReviewRoute(null)}
                    >
                      <X size={12} />
                    </button>
                  </div>
                )}
              {!liveMode && assistantPreview && (
                <div className="assistant-preview-label">
                  <Sparkles size={12} /> 助手几何预览 · 不替换当前任务{" "}
                  <button
                    aria-label="关闭助手航线预览"
                    onClick={() => setAssistantPreview(null)}
                  >
                    <X size={12} />
                  </button>
                </div>
              )}
              {!liveMode && assistantFocus && (
                <div className="assistant-map-focus">
                  <MapPin size={11} />
                  {assistantFocus}
                </div>
              )}
              {!liveMode && panels.mission && !focus && !locationOpen && (
                <div className="mission-card glass">
                  <div className="mission-card-top">
                    <span>当前任务</span>
                    <IconButton
                      label="隐藏任务概览 1"
                      onClick={() => togglePanel("mission")}
                    >
                      <Minus size={13} />
                    </IconButton>
                  </div>
                  <h3>应急医疗物资配送</h3>
                  <div className="mission-tags">
                    <span>优先级 P1</span>
                    <span>载荷 1.0 kg</span>
                  </div>
                  <div className="mission-stops">
                    <div>
                      <i className="stop-origin" />
                      <small>起点</small>
                      <strong>医疗物资中转站</strong>
                    </div>
                    <div>
                      <i className="stop-destination" />
                      <small>终点</small>
                      <strong>北区应急中心</strong>
                    </div>
                  </div>
                  <div className="mission-card-footer">
                    <span>几何基线</span>
                    <span>
                      266 航点 <ArrowUpRight size={11} />
                    </span>
                  </div>
                </div>
              )}
              <button
                className={`terrain-status glass ${terrain?.count ? "changed" : ""}`}
                onClick={() => setDrawer("settings")}
              >
                <span className="terrain-status-icon">
                  <ScanLine size={16} />
                </span>
                <span>
                  <strong>
                    地形变更监测 <span className="status-dot" />
                  </strong>
                  <small>
                    {terrain
                      ? `REV ${String(terrain.revision).padStart(3, "0")} · ${terrain.count} 网格变化`
                      : "DEM 增量比对 · 演示源"}
                  </small>
                </span>
                <ChevronRight size={13} />
              </button>
              {!liveMode && panels.perception && !focus && (
                <div className="perception-card glass">
                  <div className="mission-card-top">
                    <span>
                      <Radar size={12} /> 感知与搜索 <small>DEMO</small>
                    </span>
                    <IconButton
                      label="隐藏感知与搜索 5"
                      onClick={() => togglePanel("perception")}
                    >
                      <Minus size={12} />
                    </IconButton>
                  </div>
                  <RadarDisplay
                    heading={t.heading}
                    playing={playing && !motionReduced}
                  />
                  <div className="perception-coverage">
                    <strong>
                      {t.coverage}
                      <small>%</small>
                    </strong>
                    <span>
                      区域覆盖
                      <small>
                        {t.scanned} / {t.totalCells} 网格
                      </small>
                    </span>
                  </div>
                  <div className="coverage-track">
                    <i style={{ width: `${t.coverage}%` }} />
                  </div>
                  <div className="perception-metrics">
                    <div>
                      <span>目标距离</span>
                      <strong>
                        {t.distanceToTarget}
                        <small> m</small>
                      </strong>
                    </div>
                    <div>
                      <span>前方障碍</span>
                      <strong>
                        {t.obstacleDistance}
                        <small> m</small>
                      </strong>
                    </div>
                  </div>
                </div>
              )}
              {mapKind === "world" && !locationOpen && !focus && (
                <WeatherHud
                  state={weather}
                  open={weatherOpen}
                  onToggle={() => setWeatherOpen((v) => !v)}
                  onRetry={() => setWeatherNonce((v) => v + 1)}
                />
              )}
              {showLayers && (
                <div className="layer-menu glass">
                  <strong>地图图层</strong>
                  {(
                    Object.entries({
                      terrain: "地形与等高线",
                      buildings: "建筑体块",
                      routes: "航线与备降点",
                      restrictions: "限制区",
                      scan: "扫描波纹",
                    }) as [keyof Layers, string][]
                  ).map(([key, name]) => (
                    <button
                      key={key}
                      onClick={() =>
                        setLayers((v) => ({ ...v, [key]: !v[key] }))
                      }
                    >
                      <span>{name}</span>
                      <span
                        className={`checkbox ${layers[key] ? "checked" : ""}`}
                      >
                        {layers[key] && <Check size={11} />}
                      </span>
                    </button>
                  ))}
                  <button onClick={() => setDemoVisible((v) => !v)}>
                    <span>演示场景叠加</span>
                    <span
                      className={`checkbox ${demoVisible ? "checked" : ""}`}
                    >
                      {demoVisible && <Check size={11} />}
                    </span>
                  </button>
                  <button onClick={() => setRealTerrain((v) => !v)}>
                    <span>全球三维地形 · 在线DEM</span>
                    <span
                      className={`checkbox ${realTerrain ? "checked" : ""}`}
                    >
                      {realTerrain && <Check size={11} />}
                    </span>
                  </button>
                  <button
                    onClick={() =>
                      setLayers((v) => ({ ...v, hillshade: !v.hillshade }))
                    }
                    title="DEM 晕渲叠加，仅在开启在线三维地形时显示"
                  >
                    <span>地形晕渲 · 公开高程</span>
                    <span
                      className={`checkbox ${layers.hillshade ? "checked" : ""}`}
                    >
                      {layers.hillshade && <Check size={11} />}
                    </span>
                  </button>
                  <button
                    onClick={() => setBasemap("dark")}
                    aria-pressed={basemap === "dark"}
                  >
                    <span>暗色底图 · CARTO</span>
                    <span
                      className={`checkbox ${basemap === "dark" ? "checked" : ""}`}
                    >
                      {basemap === "dark" && <Check size={11} />}
                    </span>
                  </button>
                  <button
                    onClick={() => setBasemap("satellite")}
                    aria-pressed={basemap === "satellite"}
                  >
                    <span>卫星实景 · Esri</span>
                    <span
                      className={`checkbox ${basemap === "satellite" ? "checked" : ""}`}
                    >
                      {basemap === "satellite" && <Check size={11} />}
                    </span>
                  </button>
                  <button
                    onClick={() =>
                      setWeather((v) => ({
                        ...v,
                        radarEnabled: !v.radarEnabled,
                      }))
                    }
                  >
                    <span>天气雷达 · RainViewer</span>
                    <span
                      className={`checkbox ${weather.radarEnabled ? "checked" : ""}`}
                    >
                      {weather.radarEnabled && <Check size={11} />}
                    </span>
                  </button>
                  <button
                    onClick={() =>
                      setWeather((v) => ({
                        ...v,
                        windEnabled: !v.windEnabled,
                      }))
                    }
                  >
                    <span>风场风羽 · 地图中心</span>
                    <span
                      className={`checkbox ${weather.windEnabled ? "checked" : ""}`}
                    >
                      {weather.windEnabled && <Check size={11} />}
                    </span>
                  </button>
                  <p>
                    在线地形为公开高程、非实时测绘；卫星影像来自 Esri World
                    Imagery。天气与雷达为 Open-Meteo / RainViewer 公开数据。
                  </p>
                </div>
              )}
              <div className="map-navigation">
                <IconButton
                  label="新手分步引导"
                  onClick={() => setOnboarding((v) => !v)}
                >
                  <CircleHelp size={16} />
                </IconButton>
                <div className="compass">
                  <span>N</span>
                  <Navigation size={19} />
                </div>
                <div className="map-zoom glass">
                  <IconButton
                    label="放大地图"
                    onClick={() => map.current?.zoom(0.82)}
                  >
                    <Plus size={16} />
                  </IconButton>
                  <IconButton
                    label="缩小地图"
                    onClick={() => map.current?.zoom(1.22)}
                  >
                    <Minus size={16} />
                  </IconButton>
                  <span />
                  <IconButton
                    label="重置视角"
                    onClick={() => map.current?.reset()}
                  >
                    <Focus size={16} />
                  </IconButton>
                </div>
              </div>
              <div className="map-footer">
                <div className="map-legend">
                  <span>
                    <i className="legend-route" />
                    基线航线
                  </span>
                  <span>
                    <i className="legend-planned" />
                    对照示意
                  </span>
                  <span>
                    <i className="legend-zone" />
                    限制区
                  </span>
                  <span>
                    <i className="legend-site" />
                    备降点
                  </span>
                </div>
                <div className="map-coordinates">
                  {coordinate[0].toFixed(5)}° E <span>/</span>
                  {coordinate[1].toFixed(5)}° N
                </div>
              </div>
              <div className="map-bottom-note">
                <span>
                  {mapKind === "world"
                    ? basemap === "satellite"
                      ? "卫星实景 · Esri World Imagery · 航线/限制区/建筑叠加为演示"
                      : "真实底图 · 航线 / 限制区 / 建筑叠加为演示"
                    : "局部 ENU · 虚拟场景 · 地形／建筑高度为演示"}
                </span>
                <span>
                  {mode === "3d"
                    ? "左键平移 · 右键旋转 · 滚轮缩放"
                    : "正射视角 · 拖动平移 · 滚轮缩放"}
                </span>
              </div>
            </div>
            {liveMode ? (
              <div className="playback" aria-live="polite">
                <span className="playback-live">
                  {liveSource} · {liveStatusText}
                  {liveFrame?.is_simulated ? " · 仿真" : ""}
                </span>
                {liveFrame && (
                  <time
                    className="playback-time"
                    dateTime={liveFrame.captured_at}
                  >
                    {new Date(liveFrame.captured_at).toLocaleTimeString()}
                  </time>
                )}
                {position && position.frame !== "WGS84" && (
                  <small>
                    {position.frame} · {metric(position.x_m)} /{" "}
                    {metric(position.y_m)} / {metric(position.z_m)} m
                  </small>
                )}
              </div>
            ) : (
              <div className="playback">
                <IconButton
                  label={playing ? "暂停演示 空格" : "继续演示 空格"}
                  active={!playing}
                  onClick={() => setPlaying((v) => !v)}
                >
                  {playing ? <Pause size={14} /> : <Play size={14} />}
                </IconButton>
                <span className="playback-time">
                  {Math.floor(progress * 8)
                    .toString()
                    .padStart(2, "0")}
                  :
                  {Math.floor((progress * 480) % 60)
                    .toString()
                    .padStart(2, "0")}
                </span>
                <input
                  type="range"
                  min="0"
                  max="0.99"
                  step="0.001"
                  value={progress}
                  aria-label="演示轨迹进度"
                  onChange={(e) => setProgress(Number(e.target.value))}
                  style={
                    {
                      "--range-progress": `${progress * 100}%`,
                    } as React.CSSProperties
                  }
                />
                <span className="playback-duration">08:00</span>
                <span className="playback-live">
                  <span className="status-dot" />
                  {playing ? "演示回放" : "已暂停"}
                </span>
                <button
                  className="playback-speed"
                  onClick={() => {
                    setProgress(0.43);
                    notify("已回到任务演示起点");
                  }}
                >
                  重置
                </button>
              </div>
            )}
          </section>

          {panels.instruments && !focus && (
            <aside className="instruments">
              <section className="panel telemetry-panel">
                <PanelTitle title="飞行遥测" subtitle="TELEMETRY">
                  <span className="panel-indicator">
                    {liveMode ? liveStatusText : "合成数据"}
                  </span>
                  <IconButton
                    label="隐藏飞行仪表 2"
                    onClick={() => togglePanel("instruments")}
                  >
                    <PanelRightClose size={14} />
                  </IconButton>
                </PanelTitle>
                <div className="flight-main-metrics">
                  <div>
                    <span>
                      {altitudeLabel} <small>ALT</small>
                    </span>
                    <strong>
                      {metric(readings?.altitude)}
                      <small>m</small>
                    </strong>
                    <span className="metric-trend">
                      <ArrowUpRight size={11} />
                      {metric(readings?.climb)} m/s
                    </span>
                  </div>
                  <div>
                    <span>
                      地速 <small>GND</small>
                    </span>
                    <strong>
                      {metric(readings?.speed)}
                      <small>m/s</small>
                    </strong>
                    <span className="metric-trend muted">
                      航向 {metric(readings?.heading, 0)}°
                      {liveMode ? "" : " NE"}
                    </span>
                  </div>
                </div>
                <div className="battery-block">
                  <div>
                    <span className="metric-label">
                      <Zap size={12} /> 电源状态
                    </span>
                    <strong>
                      <span data-testid="telemetry-battery">
                        {metric(readings?.battery)}
                      </span>
                      <small>%</small>
                    </strong>
                  </div>
                  <div className="battery-bars">
                    {Array.from({ length: 30 }, (_, i) => (
                      <i
                        key={i}
                        className={
                          i / 30 < (readings?.battery ?? 0) / 100
                            ? "filled"
                            : ""
                        }
                      />
                    ))}
                  </div>
                  <div className="battery-values">
                    <span>
                      电压{" "}
                      <b>
                        {metric(readings?.voltage)}
                        <small> V</small>
                      </b>
                    </span>
                    <span>
                      电流{" "}
                      <b>
                        {metric(readings?.current)}
                        <small> A</small>
                      </b>
                    </span>
                    <span>
                      能量{" "}
                      <b>
                        {metric(readings?.energyWh, 0)}
                        <small> Wh</small>
                      </b>
                    </span>
                  </div>
                </div>
                {liveMode ? (
                  <div className="metric-mode-line">
                    <span>
                      MODE <b>{liveFrame?.flight_mode ?? "—"}</b>
                    </span>
                    <span>
                      飞行{" "}
                      <b>
                        {liveFrame?.in_air == null
                          ? "—"
                          : liveFrame.in_air
                            ? "空中"
                            : "地面"}
                      </b>
                    </span>
                    <span>
                      GPS <b>{liveFrame?.gps_fix ?? "—"}</b>
                    </span>
                    {liveFrame?.task_id && (
                      <span>
                        任务 <b>{liveFrame.task_id}</b>
                      </span>
                    )}
                    {liveFrame?.plan_version && (
                      <span>
                        方案 <b>{liveFrame.plan_version}</b>
                      </span>
                    )}
                  </div>
                ) : (
                  <>
                    <div className="link-row">
                      <div>
                        <Wifi size={13} />
                        <span>
                          {t.rssi} <small>dBm</small>
                        </span>
                        <i className="signal-bars">
                          <b />
                          <b />
                          <b />
                          <b />
                          <b />
                        </i>
                      </div>
                      <span>
                        GNSS <b>{t.satellites}</b>
                        <span className="link-divider" />
                        HDOP <b>{t.hdop}</b>
                      </span>
                    </div>
                    <div className="metric-mode-line">
                      <span>
                        MODE <b>AUTO.MISSION</b>
                      </span>
                      <span>
                        GPS <b>3D FIX</b>
                      </span>
                      <span>
                        延迟 <b>{t.rtt} ms</b>
                      </span>
                      <span>
                        链路{" "}
                        <i className="metric-signal">
                          <i
                            style={{
                              width: `${Math.max(0, Math.min(100, (t.rssi + 100) * 2))}%`,
                            }}
                          />
                        </i>
                      </span>
                    </div>
                  </>
                )}
              </section>
              <section className="panel propulsion-panel">
                <PanelTitle title="姿态与动力" subtitle="FLIGHT SYSTEM">
                  <span className="status-dot" />
                </PanelTitle>
                <div className="flight-instruments">
                  <div className="attitude-group">
                    {readings?.pitch != null && readings.roll != null && (
                      <Attitude pitch={readings.pitch} roll={readings.roll} />
                    )}
                    <div className="attitude-values">
                      <span>
                        P <b>{metric(readings?.pitch)}°</b>
                      </span>
                      <span>
                        R{" "}
                        <b>
                          {(readings?.roll ?? 0) > 0 ? "+" : ""}
                          {metric(readings?.roll)}°
                        </b>
                      </span>
                    </div>
                  </div>
                  {!liveMode && (
                    <div className="rotors">
                      <div className="rotors-header">
                        旋翼转速 <span>RPM</span>
                      </div>
                      <div className="rotor-grid">
                        {t.rotors.map((rpm, i) => (
                          <Rotor
                            key={i}
                            index={i}
                            rpm={rpm}
                            playing={playing}
                          />
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                {!liveMode && (
                  <div className="motor-wave">
                    <div>
                      <span>
                        <AudioLines size={12} /> 电机电流
                      </span>
                      <span>
                        {t.motorTemp}°C <i>温度示例</i>
                      </span>
                    </div>
                    <Sparkline color="#aeb9c9" phase={tick / 8} height={31} />
                  </div>
                )}
              </section>
            </aside>
          )}
        </div>

        {liveMode && !focus && (
          <LiveTelemetryDetails history={liveHistory} status={liveStatusText} />
        )}
        {!focus && (panels.analysis || panels.events) && (
          <div
            className={`bottom-grid ${!panels.analysis ? "events-only" : ""} ${!panels.events ? "analysis-only" : ""}`}
          >
            {panels.analysis && (
              <section className="panel margin-panel">
                <PanelTitle title="备降余量剖面" subtitle="DIVERSION MARGIN">
                  <span className="data-tag">示例曲线</span>
                  <button
                    className="chart-compare"
                    onClick={() => setDrawer("routes")}
                  >
                    <Route size={12} />
                    方案
                  </button>
                  <button
                    className={`chart-compare ${compare ? "selected" : ""}`}
                    aria-pressed={compare}
                    onClick={() => setCompare((v) => !v)}
                  >
                    {compare ? <Eye size={12} /> : <EyeOff size={12} />} 对照
                  </button>
                  <IconButton
                    label="隐藏航线分析 3"
                    onClick={() => togglePanel("analysis")}
                  >
                    <Minus size={13} />
                  </IconButton>
                </PanelTitle>
                <div className="margin-content">
                  <div className="margin-summary">
                    <span>候选方案最小余量</span>
                    <strong>
                      {reviewRoute
                        ? reviewRoute.samples.length
                          ? Math.min(
                              ...reviewRoute.samples.map((p) => p.margin_wh),
                            ).toFixed(2)
                          : "—"
                        : "+34.8"}
                      <small>Wh</small>
                    </strong>
                    <div className="margin-chip">
                      <ShieldCheck size={11} />{" "}
                      {reviewRoute
                        ? `${reviewRoute.version} · 历史演示`
                        : "示例全程非负"}
                    </div>
                    <p>
                      <i /> 候选示例 <span />
                      <i className="gray" /> 对照示例
                    </p>
                  </div>
                  {reviewRoute && !reviewRoute.samples.length ? (
                    <div className="review-no-profile">
                      此历史方案暂无剖面数据
                    </div>
                  ) : (
                    <MarginChart
                      progress={progress}
                      compare={compare && !reviewRoute}
                      review={reviewRoute}
                    />
                  )}
                </div>
              </section>
            )}
            {panels.events && (
              <section className="panel event-panel">
                <PanelTitle title="系统事件" subtitle="EVENT STREAM">
                  <span className="event-count">
                    {events.length.toString().padStart(2, "0")}
                  </span>
                  <IconButton
                    label="查看完整事件"
                    onClick={() => setDrawer("events")}
                  >
                    <ArrowUpRight size={14} />
                  </IconButton>
                  <IconButton
                    label="隐藏事件流 4"
                    onClick={() => togglePanel("events")}
                  >
                    <Minus size={13} />
                  </IconButton>
                </PanelTitle>
                <EventFeed
                  events={events}
                  onInspect={(event) => {
                    if (event.id.startsWith("replay-")) {
                      map.current?.focus([1500, 1500]);
                      setAssistantFocus("演示回放相关区域");
                    } else notify(event.detail);
                  }}
                />
                <div className="event-footer">
                  <span>
                    <span className="status-dot" /> 演示事件流
                  </span>
                  <button onClick={() => setDrawer("events")}>
                    全部事件 <ArrowRight size={11} />
                  </button>
                </div>
              </section>
            )}
          </div>
        )}
        <footer className="statusbar">
          <span>
            <span className="status-dot" />{" "}
            {liveMode ? "M4 TELEMETRY" : "LOCAL DEMO"} <i />{" "}
            {liveMode ? "场景与备降剖面为示例" : "演示仪表不代表真实飞控遥测"}
          </span>
          <div>
            <span>地形阈值 ≥ 2 m</span>
            <span>场景版本 V0.1</span>
            <button onClick={() => setDrawer("help")}>
              <Command size={11} /> 快捷键
            </button>
          </div>
        </footer>
      </main>

      <Assistant
        open={assistantOpen}
        onToggle={() => setAssistantOpen((v) => !v)}
        context={{
          is_simulated: true,
          sampled_at:
            liveMode && liveFrame
              ? liveFrame.captured_at
              : new Date().toISOString(),
          task_id: "T-S1-01",
          route_id: "S1-01-baseline",
          progress: liveMode ? 0 : progress,
          telemetry_mode: liveMode ? "live" : "demo",
          telemetry: liveMode ? null : t,
          live_telemetry: liveMode ? liveFrame : null,
          terrain: liveMode ? null : terrain,
          events,
        }}
        onDraft={saveAssistantDraft}
        onFocus={(point, label) => {
          map.current?.focus(point);
          setCoordinate(enuToLngLat(point));
          setAssistantFocus(label);
        }}
        onRoute={(route) => {
          setAssistantPreview(route);
          if (route) {
            setLayers((l) => ({ ...l, routes: true }));
            map.current?.reset();
            setAssistantFocus("");
          }
        }}
        onPanel={(panel) => {
          setPanels((p) => ({ ...p, [panel]: true }));
          setFocus(false);
          if (panel === "events") setDrawer("events");
        }}
        onInjectTerrain={simulateTerrain}
        onEvent={(title, detail) => addEvent(title, detail)}
      />

      {focus && (
        <button className="focus-exit button" onClick={() => setFocus(false)}>
          <Maximize2 size={14} />
          退出专注视图 <kbd>F</kbd>
        </button>
      )}
      {toast && (
        <div className="toast" role="status">
          <Check size={15} />
          {toast}
          <button aria-label="关闭提示" onClick={() => setToast("")}>
            <X size={13} />
          </button>
        </div>
      )}
      <input
        type="file"
        accept=".json,application/json"
        hidden
        ref={fileInput}
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          try {
            if (file.size > 1000000) throw new Error("地形补丁需小于1MB");
            applyTerrain(JSON.parse(await file.text()));
          } catch (error) {
            notify(error instanceof Error ? error.message : "文件读取失败");
          }
          e.target.value = "";
        }}
      />

      {drawer && (
        <div
          className="drawer-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setDrawer(null);
          }}
        >
          <aside
            ref={dialog}
            className="drawer"
            role="dialog"
            aria-modal="true"
            aria-label={
              {
                panels: "组件管理",
                tasks: "任务空间",
                events: "系统事件",
                settings: "数据与地形设置",
                help: "操作说明",
                new: "新建任务草稿",
                routes: "候选与历史方案",
                dispatch: "本地任务联调",
              }[drawer]
            }
          >
            <div className="drawer-header">
              <div>
                <span className="eyebrow">AERIS / WORKSPACE</span>
                <h2>
                  {
                    {
                      panels: "组件管理",
                      tasks: "任务空间",
                      events: "系统事件",
                      settings: "数据与地形设置",
                      help: "操作说明",
                      new: "新建任务草稿",
                      routes: "候选与历史方案",
                      dispatch: "本地任务联调",
                    }[drawer]
                  }
                </h2>
              </div>
              <IconButton label="关闭面板" onClick={() => setDrawer(null)}>
                <X size={19} />
              </IconButton>
            </div>
            <div className="drawer-body">
              {drawer === "dispatch" && <DispatchPanel />}
              {drawer === "routes" && (
                <RouteReview
                  onSelect={(route) => {
                    setReviewRoute(route);
                    setDrawer(null);
                    setMapKind("world");
                    setDemoVisible(true);
                    setLayers((l) => ({ ...l, routes: true }));
                    map.current?.reset();
                  }}
                />
              )}
              {drawer === "panels" && (
                <>
                  <p className="drawer-intro">
                    让重要信息留在眼前。自由收起面板，获得更大的空域视野。
                  </p>
                  {(Object.entries(panelNames) as [PanelId, string][]).map(
                    ([key, label], i) => (
                      <button
                        className="setting-row"
                        key={key}
                        onClick={() => togglePanel(key)}
                      >
                        <span>
                          {label}
                          <small>快捷键 {i + 1}</small>
                        </span>
                        <span className={`switch ${panels[key] ? "on" : ""}`} />
                      </button>
                    ),
                  )}
                  <button
                    className="button full-width"
                    onClick={() => {
                      setPanels(defaultPanels);
                      setFocus(false);
                      notify("已恢复默认布局");
                    }}
                  >
                    恢复默认布局
                  </button>
                  <div className="info-card">
                    <Focus size={19} />
                    <strong>专注模式</strong>
                    <p>
                      按 F 隐藏辅助仪表与分析面板；按 Esc
                      恢复。布局会保存在本机。
                    </p>
                  </div>
                </>
              )}
              {drawer === "tasks" && (
                <>
                  <div className="drawer-section-label">
                    当前演示 <span>01</span>
                  </div>
                  <div className="task-card">
                    <span className="tag-purple">演示巡航中</span>
                    <h3>应急医疗物资配送</h3>
                    <p>
                      医疗物资中转站 <ArrowRight size={12} /> 北区应急中心
                    </p>
                    <div>
                      <span>T-S1-01</span>
                      <span>1.0 kg · AER-01</span>
                    </div>
                  </div>
                  <div className="drawer-section-label">
                    本地草稿{" "}
                    <span>{drafts.length.toString().padStart(2, "0")}</span>
                  </div>
                  {drafts.length ? (
                    drafts.map((d, i) => (
                      <div className="task-card" key={i}>
                        <span className="data-tag">尚未提交</span>
                        <h3>{d.name}</h3>
                        <p>
                          {d.origin} <ArrowRight size={12} /> {d.destination}
                        </p>
                        <div>
                          <span>载荷 {d.payload} kg</span>
                          <span>{d.priority} · 待规划</span>
                        </div>
                        {(validGeoPlace(d.geo?.origin) ||
                          validGeoPlace(d.geo?.destination)) && (
                          <div className="task-geo-coordinates">
                            <span>WGS84 · 真实选点</span>
                            {validGeoPlace(d.geo?.origin) && (
                              <small>
                                起：{formatCoordinates(d.geo.origin.point)}
                              </small>
                            )}
                            {validGeoPlace(d.geo?.destination) && (
                              <small>
                                终：{formatCoordinates(d.geo.destination.point)}
                              </small>
                            )}
                          </div>
                        )}
                      </div>
                    ))
                  ) : (
                    <div className="empty-state">
                      <FileText size={27} />
                      <p>还没有任务草稿</p>
                      <small>创建草稿后，等待后端规划和确认。</small>
                    </div>
                  )}
                  <button
                    className="button primary full-width"
                    onClick={() => setDrawer("new")}
                  >
                    <Plus size={15} /> 新建任务草稿
                  </button>
                </>
              )}
              {drawer === "new" && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const values = new FormData(e.currentTarget);
                    const name = String(values.get("name")).trim();
                    if (
                      !name ||
                      !String(values.get("origin")).trim() ||
                      !String(values.get("destination")).trim()
                    ) {
                      notify("请填写有效的任务名称和起终点");
                      return;
                    }
                    if (drafts.length >= 100) {
                      notify("本地最多保留100条草稿，请先导出整理");
                      return;
                    }
                    setDrafts((d) => [
                      ...d,
                      {
                        name,
                        payload: String(values.get("payload")),
                        origin: String(values.get("origin")).trim(),
                        destination: String(values.get("destination")).trim(),
                        priority: String(values.get("priority")),
                        geo: {
                          origin:
                            String(values.get("origin")).trim() ===
                            geoMission.origin?.name
                              ? geoMission.origin
                              : null,
                          destination:
                            String(values.get("destination")).trim() ===
                            geoMission.destination?.name
                              ? geoMission.destination
                              : null,
                        },
                      },
                    ]);
                    addEvent("已保存本地任务草稿", `${name} · 尚未规划或下发`);
                    notify("草稿已保存，尚未提交飞控");
                    setDrawer("tasks");
                  }}
                >
                  <p className="drawer-intro">
                    创建待确认的任务。当前为前端原型，保存操作不会控制无人机。
                  </p>
                  <label className="form-field">
                    任务名称
                    <input
                      name="name"
                      placeholder="例如：北区应急药品配送"
                      maxLength={80}
                      required
                    />
                  </label>
                  <label className="form-field">
                    起点
                    <input
                      name="origin"
                      aria-label="起点"
                      placeholder="请输入起点名称"
                      maxLength={120}
                      defaultValue={geoMission.origin?.name ?? ""}
                      required
                    />
                    {geoMission.origin && (
                      <small className="form-geo-coordinate">
                        WGS84 {formatCoordinates(geoMission.origin.point)}
                      </small>
                    )}
                  </label>
                  <label className="form-field">
                    终点
                    <input
                      name="destination"
                      aria-label="终点"
                      placeholder="请输入终点名称"
                      maxLength={120}
                      defaultValue={geoMission.destination?.name ?? ""}
                      required
                    />
                    {geoMission.destination && (
                      <small className="form-geo-coordinate">
                        WGS84 {formatCoordinates(geoMission.destination.point)}
                      </small>
                    )}
                  </label>
                  <div className="form-grid">
                    <label className="form-field">
                      载荷 / kg
                      <input
                        name="payload"
                        type="number"
                        min="0"
                        max="100"
                        step="0.1"
                        defaultValue="1"
                        required
                      />
                    </label>
                    <label className="form-field">
                      任务优先级
                      <select name="priority" aria-label="任务优先级">
                        <option>P1 · 应急</option>
                        <option>P2 · 常规</option>
                      </select>
                    </label>
                  </div>
                  <div className="notice">
                    <TriangleAlert size={16} />
                    <p>
                      地图选择的经纬度会随草稿保存。若更改地点名称，原坐标不再绑定；请回地图重新选点。草稿不会下发飞控。
                    </p>
                  </div>
                  <button className="button primary full-width" type="submit">
                    保存任务草稿 <ArrowRight size={14} />
                  </button>
                </form>
              )}
              {drawer === "events" && (
                <>
                  <p className="drawer-intro">
                    任务状态与地形变化时间线。当前事件均来自前端演示或手动接入的数据。
                  </p>
                  <EventFeed events={events} expanded />
                  <button
                    className="button full-width"
                    onClick={exportSnapshot}
                  >
                    <Download size={14} /> 导出演示记录 JSON
                  </button>
                </>
              )}
              {drawer === "settings" && (
                <>
                  <div className="source-card">
                    <span className="tag-purple">DEMO DATA</span>
                    <h3>透明的数据边界</h3>
                    <p>
                      航线来自仓库几何A*基线；仪表为合成遥测。地形、建筑高度与余量曲线为界面演示。卫星影像、公开DEM、天气与雷达来自第三方公开服务，仅作演示参考，不用于飞行决策。
                    </p>
                  </div>
                  <button
                    className="setting-row"
                    onClick={() => setMotionReduced((v) => !v)}
                  >
                    <span>
                      减少动态效果
                      <small>雷达、入场与运镜使用静态或即时呈现</small>
                    </span>
                    <span className={`switch ${motionReduced ? "on" : ""}`} />
                  </button>
                  <button
                    className="setting-row"
                    onClick={() => setRealTerrain((v) => !v)}
                  >
                    <span>
                      全球在线三维地形
                      <small>公开DEM，非实时测绘，与增量比对独立</small>
                    </span>
                    <span className={`switch ${realTerrain ? "on" : ""}`} />
                  </button>
                  <h3 className="section-subhead">
                    <Mountain size={15} /> 地形变化监测
                  </h3>
                  <p className="drawer-intro">
                    对比相邻高程网格，定位超过 2 m
                    的变化。支持导入DEM增量；不能仅凭地图识别现实地形。
                  </p>
                  <div className="terrain-revision">
                    <span>
                      当前版本{" "}
                      <strong>
                        REV {String(terrain?.revision ?? 0).padStart(3, "0")}
                      </strong>
                    </span>
                    <span>
                      最大高差{" "}
                      <strong>{terrain?.maxDelta.toFixed(1) ?? "0.0"} m</strong>
                    </span>
                  </div>
                  <button
                    className="button full-width"
                    disabled={!ready || socketState !== "offline"}
                    onClick={simulateTerrain}
                  >
                    <ScanLine size={15} /> 注入一次演示地形变化
                  </button>
                  <button
                    className="setting-row"
                    disabled={socketState !== "offline"}
                    onClick={() => setTerrainAuto((v) => !v)}
                  >
                    <span>
                      自动演示地形增量<small>每 8 秒更新 · 明确合成来源</small>
                    </span>
                    <span className={`switch ${terrainAuto ? "on" : ""}`} />
                  </button>
                  <button
                    className="button full-width"
                    disabled={!ready}
                    onClick={() => fileInput.current?.click()}
                  >
                    <ArrowDownToLine size={14} /> 导入地形补丁 JSON
                  </button>
                  <h3 className="section-subhead">
                    <Link2 size={15} /> 连接地形数据流
                  </h3>
                  <label className="form-field">
                    WebSocket 地址
                    <input
                      value={socketUrl}
                      onChange={(e) => setSocketUrl(e.target.value)}
                      placeholder="wss://your-service/terrain"
                      disabled={socketState !== "offline"}
                    />
                  </label>
                  <button
                    className="button full-width"
                    onClick={connectTerrain}
                  >
                    {socketState === "offline" ? (
                      <Radio size={14} />
                    ) : (
                      <X size={14} />
                    )}{" "}
                    {socketState === "offline"
                      ? "连接数据流"
                      : socketState === "connecting"
                        ? "连接中 · 点击取消"
                        : "断开数据流"}
                  </button>
                  <p className="fine-print">
                    仅更新地形，飞行遥测仍为演示。接口格式见前端README。
                  </p>
                  <h3 className="section-subhead">搜救与感知 · 演示</h3>
                  <div className="coverage-summary">
                    <div>
                      <strong>
                        {t.coverage}
                        <small>%</small>
                      </strong>
                      <span>区域覆盖率</span>
                    </div>
                    <div className="coverage-grid">
                      {Array.from({ length: t.totalCells }, (_, i) => (
                        <i key={i} className={i < t.scanned ? "covered" : ""} />
                      ))}
                    </div>
                  </div>
                  <div className="detail-row">
                    <span>扫描网格</span>
                    <strong>
                      {t.scanned} / {t.totalCells}
                    </strong>
                  </div>
                  <div className="detail-row">
                    <span>目标距离</span>
                    <strong>{t.distanceToTarget} m</strong>
                  </div>
                  <div className="detail-row">
                    <span>前方障碍距离</span>
                    <strong>{t.obstacleDistance} m</strong>
                  </div>
                  <div className="detail-row">
                    <span>电机温度</span>
                    <strong>{t.motorTemp} °C</strong>
                  </div>
                </>
              )}
              {drawer === "help" && (
                <>
                  <p className="drawer-intro">
                    为低空航线规划设计的桌面调度工作区。所有飞行操作当前均为演示，未接入真实飞机。
                  </p>
                  <button
                    className="button primary full-width"
                    onClick={() => {
                      setDrawer(null);
                      setOnboarding(true);
                    }}
                  >
                    启动新手分步引导 <ArrowRight size={14} />
                  </button>
                  <h3 className="section-subhead">键盘快捷键</h3>
                  {[
                    ["1—5", "显示或隐藏对应组件"],
                    ["V", "切换二维 / 三维视角"],
                    ["L", "打开地点定位"],
                    ["A", "打开调度助手"],
                    ["?", "新手分步引导"],
                    ["F", "进入或退出专注视图"],
                    ["Space", "暂停或继续演示"],
                    ["Esc", "关闭面板并退出专注视图"],
                  ].map(([key, label]) => (
                    <div className="detail-row" key={key}>
                      <span>{label}</span>
                      <kbd>{key}</kbd>
                    </div>
                  ))}
                  <h3 className="section-subhead">地图操作</h3>
                  <p className="drawer-intro">
                    左键平移、右键旋转、滚轮缩放。真实地图可点击选择WGS84坐标，设为任务起终点。原始地形视图保留在“地形实验”，其中点击不会保存真实目的地。
                  </p>
                  <div className="info-card">
                    <ShieldCheck size={20} />
                    <strong>每一份数据，都有来源。</strong>
                    <p>
                      图层和仪表仅用于演示交互。真实感知、能耗与备降安全结论，需要服务端数据和独立校验。
                    </p>
                  </div>
                </>
              )}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
