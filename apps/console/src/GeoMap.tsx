import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import * as maplibregl from "maplibre-gl";
import {
  type CanvasSource,
  type GeoJSONSource,
  type RasterTileSource,
  type StyleSpecification,
  type Map as LibreMap,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import mapWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import { GRID, GRID_STEP, pointAlong, TerrainModel } from "./terrain";
import { RADAR_TILE_ZOOM, WIND_REGION, type WindField } from "./weather";
import { createWindLayer, WIND_MAX_ZOOM } from "./WindLayer";
import type { NavigationOverlay } from "./navigation/engine";
import type { RealScene } from "./RealRouting";
import { airspaceKinds } from "./navigation/airspace";
import {
  enuToLngLat,
  type GeoMission,
  type GeoPlace,
  type LngLat,
} from "./geo";
import type {
  Basemap,
  Layers,
  Point,
  SceneData,
  TerrainChange,
  TerrainPatch,
  ViewMode,
} from "./types";

export const CARTO_STYLE =
  "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
export const CARTO_NIGHT_STYLE =
  "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
/** Esri World Imagery：免 key 公开卫星影像，注意 URL 是 {z}/{y}/{x} 顺序。 */
const SATELLITE_TILES = [
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
];
const SATELLITE_ATTRIBUTION = "Esri, Maxar, Earthstar Geographics";
/** AWS Terrarium 公开高程（Mapzen 编码），离线/失败时由 error 分支降级。 */
const DEM_TILES = [
  "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
];
const TERRAIN_EXAGGERATION = 1.35;
maplibregl.setWorkerUrl(mapWorkerUrl);
const offline = (dark: boolean): StyleSpecification => ({
  version: 8,
  sources: {},
  layers: [
    {
      id: "background",
      type: "background",
      paint: { "background-color": dark ? "#101c2d" : "#eef3f7" },
    },
  ],
});
type FeatureProps = Record<string, string | number | boolean>;
const feature = (
  geometry: Geometry,
  properties: FeatureProps = {},
): Feature => ({ type: "Feature", geometry, properties });
const collection = (features: Feature[]): FeatureCollection => ({
  type: "FeatureCollection",
  features,
});
const line = (points: LngLat[]) =>
  feature({ type: "LineString", coordinates: points });
const polygon = (points: LngLat[], properties: FeatureProps = {}) =>
  feature(
    { type: "Polygon", coordinates: [[...points, points[0]]] },
    properties,
  );
export type GeoMapHandle = {
  navigate: (
    center: LngLat,
    zoom: number,
    bearing: number,
    pitch: number,
  ) => void;
  overview: (points: LngLat[]) => void;
  reset: () => void;
  zoom: (factor: number) => void;
  focus: (point: Point) => void;
  flyTo: (point: LngLat) => void;
  showWindRegion: () => void;
  retry: () => void;
  applyTerrain: (patch: TerrainPatch) => TerrainChange;
};
export type WeatherOverlay = {
  radarTiles: string | null;
  wind: WindField | null;
  windRegion?: typeof WIND_REGION;
};
export type GeoMapProps = {
  onAirspaceSelect?: (id: string) => void;
  navigation?: NavigationOverlay | null;
  nationalFlysafe?: FeatureCollection | null;
  nationalFlysafeKey?: string;
  onManualMove?: () => void;
  mode: ViewMode;
  basemap: Basemap;
  layers: Layers;
  progress: number;
  playing: boolean;
  demoVisible: boolean;
  liveMode: boolean;
  livePoint: LngLat | null;
  realTerrain: boolean;
  reducedMotion: boolean;
  terrainModel: TerrainModel;
  mission: GeoMission;
  realRoute?: LngLat[];
  realPreviousRoute?: LngLat[];
  realConflictSegments?: [LngLat, LngLat][];
  realScene?: RealScene | null;
  selected: GeoPlace | null;
  preview?: { route_id: string; waypoints: Point[] } | null;
  comparison?: { id: string; waypoints: Point[] } | null;
  weather?: WeatherOverlay;
  onWindView: (visible: boolean) => void;
  onWindMove: (moving: boolean) => void;
  onReady: () => void;
  onError: (message: string) => void;
  onPoint: (point: LngLat) => void;
  onStatus: (status: string) => void;
};

export default forwardRef<GeoMapHandle, GeoMapProps>(
  function GeoMap(props, ref) {
    const root = useRef<HTMLDivElement>(null);
    const runtime = useRef<{
      map: LibreMap;
      update: () => void;
      reload: (force?: boolean) => void;
      scene: SceneData | null;
    } | null>(null);
    const dynamic = useRef(props);
    dynamic.current = props;
    const [status, setStatus] = useState("正在连接真实底图");
    const fly = (point: LngLat, zoom = 15) => {
      const current = runtime.current;
      if (current)
        current.map.flyTo({
          center: point,
          zoom,
          duration: dynamic.current.reducedMotion ? 0 : 1400,
          essential: false,
        });
    };
    useImperativeHandle(ref, () => ({
      navigate: (center, zoom, bearing, pitch) =>
        runtime.current?.map.easeTo({
          center,
          zoom,
          bearing,
          pitch,
          duration: dynamic.current.reducedMotion ? 0 : 550,
          essential: false,
        }),
      overview: (points) => {
        if (!points.length) return;
        const map = runtime.current?.map;
        if (!map) return;
        let attempts = 0;
        const fit = () => {
          const current = runtime.current?.map;
          if (!current) return;
          // `load` fires once per style. A later overview can see
          // isStyleLoaded() false while that event will never fire again,
          // which left zone labels at the previous camera and under the sidebar.
          if (!current.isStyleLoaded()) {
            if (attempts++ < 12) current.once("idle", fit);
            return;
          }
          // The real-route panel can change the workspace width in this same
          // React commit. Fit against its current layout rather than a stale
          // viewport, and render the matching GPU frame below.
          current.resize();
          const bounds = new maplibregl.LngLatBounds(points[0], points[0]);
          points.slice(1).forEach((p) => bounds.extend(p));
          current.fitBounds(bounds, {
            padding: { top: 80, bottom: 65, left: 45, right: 45 },
            maxZoom: 16,
            pitch: 0,
            bearing: 0,
            duration: dynamic.current.reducedMotion ? 0 : 800,
          });
          current.redraw();
        };
        fit();
      },
      reset: () =>
        runtime.current?.map.flyTo({
          center: enuToLngLat([1500, 1500]),
          zoom: 14.1,
          pitch: dynamic.current.mode === "3d" ? 55 : 0,
          bearing: dynamic.current.mode === "3d" ? -24 : 0,
          duration: dynamic.current.reducedMotion ? 0 : 1100,
        }),
      flyTo: fly,
      showWindRegion: () => {
        const r = dynamic.current.weather?.windRegion ?? WIND_REGION;
        runtime.current?.map.fitBounds(
          [
            [r.west + 1.7, r.south + 1.7],
            [r.east - 1.7, r.north - 1.7],
          ],
          {
            padding: 32,
            pitch: 0,
            bearing: 0,
            maxZoom: WIND_MAX_ZOOM - 0.5,
            duration: dynamic.current.reducedMotion ? 0 : 900,
          },
        );
      },
      focus: (point) => fly(enuToLngLat(point), 15.3),
      zoom: (factor) => {
        const m = runtime.current?.map;
        if (m)
          m.easeTo({
            zoom: m.getZoom() - Math.log2(factor),
            duration: dynamic.current.reducedMotion ? 0 : 350,
          });
      },
      retry: () => runtime.current?.reload(),
      applyTerrain: (patch) => {
        const result = dynamic.current.terrainModel.apply(patch);
        runtime.current?.update();
        return result;
      },
    }));

    useEffect(() => {
      let disposed = false,
        map: LibreMap;
      let scene: SceneData | null = null;
      let mapReady = false,
        readySent = false,
        online = false,
        loadingStyle = false;
      let styleAbort: AbortController | null = null;
      let styleGeneration = 0;
      let tileTimeout: number | undefined;
      let basemapSourceIds = new Set<string>();
      let basemapHasTiles = false;
      let terrainFailed = false;
      let satelliteFailed = false;
      let lastBasemap = dynamic.current.basemap;
      let radarTileKey = "";
      let windData: WindField | null = null;
      let windLayer: ReturnType<typeof createWindLayer> | null = null;
      let windTimer = 0;
      let windView = false;
      let glowOpacityCache = -1;
      const visibilityCache = new Map<string, string>();
      let draw: (() => void) | undefined;
      let realSceneError = "";
      let inspectRealSceneNextFrame = true;
      function realSceneStatus(
        value: "loading" | "ready" | "error",
        buildings = 0,
        roads = 0,
      ) {
        const container = root.current;
        if (!container || disposed) return;
        container.dataset.realSceneStatus = value;
        container.dataset.realBuildingsRendered = String(buildings);
        container.dataset.realRoadsRendered = String(roads);
        container.dataset.realSceneError = realSceneError;
      }
      realSceneStatus("loading");
      const labels: { marker: maplibregl.Marker; group: string }[] = [];
      const pins: maplibregl.Marker[] = [];
      const state = (text: string) => {
        if (!disposed) {
          setStatus(text);
          dynamic.current.onStatus(text);
        }
      };
      try {
        map = new maplibregl.Map({
          container: root.current!,
          style: offline(false),
          center: enuToLngLat([1500, 1500]),
          zoom: 14.1,
          pitch: dynamic.current.mode === "3d" ? 55 : 0,
          bearing: -24,
          maxPitch: 70,
          maxZoom: 19,
          minZoom: 2,
          attributionControl: false,
          canvasContextAttributes: { antialias: true },
        });
      } catch {
        dynamic.current.onError(
          "地图引擎无法启动，请启用浏览器硬件加速后刷新。",
        );
        return;
      }
      const canvas = map.getCanvas();
      canvas.setAttribute(
        "aria-label",
        "真实地理地图，点击选点，拖动平移，右键旋转",
      );
      map.addControl(
        new maplibregl.AttributionControl({
          compact: false,
        }),
        "bottom-right",
      );
      map.addControl(
        new maplibregl.ScaleControl({ maxWidth: 80, unit: "metric" }),
        "bottom-left",
      );
      map.on("click", (e) => {
        const hit = map.getLayer("airspace-regions-fill")
          ? map.queryRenderedFeatures(e.point, {
              layers: ["airspace-regions-fill"],
            })[0]
          : null;
        if (hit?.properties?.region_id)
          dynamic.current.onAirspaceSelect?.(String(hit.properties.region_id));
        else dynamic.current.onPoint([e.lngLat.wrap().lng, e.lngLat.lat]);
      });
      const updateWindView = () => {
        const bounds = map.getBounds();
        const center = map.getCenter();
        const offset = center.lng - center.wrap().lng;
        const region = dynamic.current.weather?.windRegion ?? WIND_REGION;
        const next =
          map.getZoom() < WIND_MAX_ZOOM &&
          bounds.getEast() - offset >= region.west &&
          bounds.getWest() - offset <= region.east &&
          bounds.getNorth() >= region.south &&
          bounds.getSouth() <= region.north;
        if (windView !== next) {
          windView = next;
          dynamic.current.onWindView(next);
        }
      };
      map.on("movestart", (event) => {
        if (event.originalEvent) dynamic.current.onManualMove?.();
        dynamic.current.onWindMove(true);
        syncWindAnimation(false);
      });
      map.on("moveend", () => {
        dynamic.current.onWindMove(false);
        updateWindView();
        syncWindAnimation(true);
      });
      map.on("resize", updateWindView);
      const updateWindMotion = () => syncWindAnimation(true);
      const motionPreference = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      );
      motionPreference.addEventListener("change", updateWindMotion);
      document.addEventListener("visibilitychange", updateWindMotion);
      const sendReady = () => {
        if (mapReady && scene && !readySent) {
          readySent = true;
          dynamic.current.onReady();
        }
      };
      const source = (id: string, data: FeatureCollection) => {
        const current = map.getSource(id) as GeoJSONSource | undefined;
        if (current) current.setData(data);
        else map.addSource(id, { type: "geojson", data });
      };
      const marker = (
        point: LngLat,
        text: string,
        kind: string,
        group: string,
      ) => {
        const element = document.createElement("div");
        element.className = `geo-label ${kind}`;
        element.textContent = text;
        labels.push({
          marker: new maplibregl.Marker({ element })
            .setLngLat(point)
            .addTo(map),
          group,
        });
      };
      /** 新叠加层统一放在演示图层之下、底图之上。 */
      function addBelowDemo(id: string) {
        if (!map.getLayer(id)) return;
        if (map.getLayer("demo-grid-lines"))
          map.moveLayer(id, "demo-grid-lines");
        else map.moveLayer(id);
      }
      /** 只在可见性真正变化时写入样式，避免每 150ms 触发无意义的样式更新。 */
      function setLayerVisibility(id: string, visible: boolean) {
        if (!map.getLayer(id)) return;
        const value = visible ? "visible" : "none";
        if (visibilityCache.get(id) === value) return;
        map.setLayoutProperty(id, "visibility", value);
        visibilityCache.set(id, value);
      }
      function syncBasemap() {
        if (disposed || !mapReady) return;
        if (!map.getSource("satellite")) {
          map.addSource("satellite", {
            type: "raster",
            tiles: SATELLITE_TILES,
            tileSize: 256,
            maxzoom: 19,
            attribution: SATELLITE_ATTRIBUTION,
          });
        }
        if (!map.getLayer("satellite-layer")) {
          map.addLayer({
            id: "satellite-layer",
            type: "raster",
            source: "satellite",
            paint: {
              "raster-opacity": 1,
              "raster-fade-duration": 220,
              "raster-saturation": -0.12,
            },
          });
          addBelowDemo("satellite-layer");
        }
        setLayerVisibility(
          "satellite-layer",
          dynamic.current.basemap === "satellite",
        );
        // 卫星影像偏亮，演示航线提高发光强度保持可读性。
        if (map.getLayer("demo-route-glow")) {
          const glow = dynamic.current.basemap === "satellite" ? 0.78 : 0.55;
          if (glow !== glowOpacityCache) {
            glowOpacityCache = glow;
            map.setPaintProperty("demo-route-glow", "line-opacity", glow);
          }
        }
      }
      /**
       * 在线 DEM：raster-dem + 地形晕渲。关闭或失败时按“移除图层 → 关闭地形
       * → 移除数据源”的顺序清理，避免 MapLibre 报“source 正被图层引用”。
       */
      function syncTerrain() {
        if (disposed || !mapReady) return;
        const p = dynamic.current;
        if (p.realTerrain && !terrainFailed) {
          if (!map.getSource("global-dem")) {
            map.addSource("global-dem", {
              type: "raster-dem",
              tiles: DEM_TILES,
              tileSize: 256,
              maxzoom: 14,
              encoding: "terrarium",
              attribution: "Terrain © Mapzen / AWS Open Data",
            });
          }
          if (!lastTerrain)
            map.setTerrain({
              source: "global-dem",
              exaggeration: TERRAIN_EXAGGERATION,
            });
          if (!map.getLayer("dem-hillshade")) {
            map.addLayer({
              id: "dem-hillshade",
              type: "hillshade",
              source: "global-dem",
              paint: {
                "hillshade-exaggeration": 0.32,
                "hillshade-shadow-color": "#05090e",
                "hillshade-highlight-color": "#c2cfdf",
                "hillshade-accent-color": "#263544",
              },
            });
            addBelowDemo("dem-hillshade");
          }
          setLayerVisibility("dem-hillshade", p.layers.hillshade);
          lastTerrain = true;
          return;
        }
        if (terrainFailed && !p.realTerrain) terrainFailed = false;
        if (
          lastTerrain ||
          map.getLayer("dem-hillshade") ||
          map.getSource("global-dem")
        ) {
          map.setTerrain(null);
          if (map.getLayer("dem-hillshade")) map.removeLayer("dem-hillshade");
          if (map.getSource("global-dem")) map.removeSource("global-dem");
          visibilityCache.delete("dem-hillshade");
          lastTerrain = false;
          if (!p.realTerrain)
            state(online ? "真实底图 · CARTO" : "底图离线 · 坐标可用");
        }
      }
      /** RainViewer 雷达拼图：固定 source，帧切换时只更新瓦片模板。 */
      function syncRadar() {
        if (disposed || !mapReady) return;
        const tiles = dynamic.current.weather?.radarTiles;
        if (tiles) {
          const current = map.getSource("weather-radar") as
            | RasterTileSource
            | undefined;
          if (!current) {
            map.addSource("weather-radar", {
              type: "raster",
              tiles: [tiles],
              tileSize: 256,
              maxzoom: RADAR_TILE_ZOOM,
              attribution: "RainViewer · 公开雷达拼图",
            });
            radarTileKey = tiles;
          } else if (tiles !== radarTileKey && !map.isMoving()) {
            current.setTiles([tiles]);
            radarTileKey = tiles;
          }
          if (!map.getLayer("weather-radar-layer")) {
            map.addLayer({
              id: "weather-radar-layer",
              type: "raster",
              source: "weather-radar",
              paint: {
                "raster-opacity": 0.46,
                "raster-fade-duration": 240,
              },
            });
            addBelowDemo("weather-radar-layer");
          }
          return;
        }
        if (map.getLayer("weather-radar-layer"))
          map.removeLayer("weather-radar-layer");
        if (map.getSource("weather-radar")) map.removeSource("weather-radar");
        radarTileKey = "";
      }
      function syncWindAnimation(allow: boolean) {
        const p = dynamic.current;
        const canAnimate =
          allow &&
          Boolean(p.weather?.wind && windLayer && windView) &&
          p.mode === "2d" &&
          p.basemap === "dark" &&
          !p.realTerrain &&
          !p.reducedMotion &&
          !motionPreference.matches &&
          !document.hidden &&
          !map.isMoving();
        if (Boolean(windTimer) === canAnimate) return;
        const paint = (elapsed?: number) => {
          const source = map.getSource("weather-wind") as
            | CanvasSource
            | undefined;
          if (!source || !windLayer) return;
          windLayer.draw(elapsed);
          // Update the texture once and leave the MapLibre render loop idle between frames.
          source.play();
          source.pause();
        };
        if (canAnimate) {
          const start = performance.now();
          windTimer = window.setInterval(
            () => paint((performance.now() - start) / 1000),
            1000 / 24,
          );
        } else {
          window.clearInterval(windTimer);
          windTimer = 0;
          paint();
        }
      }
      function syncWind() {
        const field = dynamic.current.weather?.wind ?? null;
        if (field && field !== windData && map.isMoving()) return;
        const installed = map.getSource("weather-wind");
        if (field !== windData || Boolean(installed) !== Boolean(field)) {
          syncWindAnimation(false);
          if (map.getLayer("weather-wind-layer"))
            map.removeLayer("weather-wind-layer");
          if (installed) map.removeSource("weather-wind");
          if (field !== windData) {
            windLayer = field ? createWindLayer(field) : null;
            windData = field;
          }
          if (windLayer) {
            const { west, east, south, north } = field?.region ?? WIND_REGION;
            map.addSource("weather-wind", {
              type: "canvas",
              canvas: windLayer.canvas,
              animate: false,
              coordinates: [
                [west, north],
                [east, north],
                [east, south],
                [west, south],
              ],
            });
            map.addLayer({
              id: "weather-wind-layer",
              type: "raster",
              source: "weather-wind",
              maxzoom: WIND_MAX_ZOOM,
              paint: { "raster-fade-duration": 0 },
            });
            addBelowDemo("weather-wind-layer");
          }
        }
        syncWindAnimation(true);
      }
      function syncOverlays() {
        if (disposed || !mapReady) return;
        syncBasemap();
        syncTerrain();
        syncRadar();
        syncWind();
      }
      function updateTerrain() {
        if (!mapReady || !map.getSource("demo-route")) return;
        const terrain = dynamic.current.terrainModel;
        const cells: Feature[] = [];
        for (const index of terrain.changedIndices) {
          const x = (index % (GRID + 1)) * GRID_STEP,
            y = Math.floor(index / (GRID + 1)) * GRID_STEP;
          const d = GRID_STEP / 2;
          cells.push(
            polygon(
              [
                [x - d, y - d],
                [x + d, y - d],
                [x + d, y + d],
                [x - d, y + d],
              ].map((p) => enuToLngLat(p as Point)),
              { height: Math.max(2, terrain.heights[index]) },
            ),
          );
        }
        source("demo-changes", collection(cells));
      }
      function install() {
        if (disposed || !scene || !mapReady) return;
        mapReady = true;
        const grid: Feature[] = [];
        for (let n = 0; n <= 3000; n += 250) {
          grid.push(
            line([enuToLngLat([n, 0]), enuToLngLat([n, 3000])]),
            line([enuToLngLat([0, n]), enuToLngLat([3000, n])]),
          );
        }
        source("demo-grid", collection(grid));
        source(
          "demo-buildings",
          collection(
            scene.buildings.map((b) =>
              polygon(b.polygon.map(enuToLngLat), { height: b.height }),
            ),
          ),
        );
        source(
          "demo-zones",
          collection(
            scene.zones.map((z) =>
              polygon(z.polygon.map(enuToLngLat), {
                active: z.active !== false,
              }),
            ),
          ),
        );
        source("demo-route", collection([line(scene.route.map(enuToLngLat))]));
        source(
          "demo-reference",
          collection([
            line([
              enuToLngLat(scene.route[0]),
              enuToLngLat(scene.route.at(-1)!),
            ]),
          ]),
        );
        source("demo-progress", collection([]));
        source("demo-preview", collection([]));
        source("demo-comparison", collection([]));
        source("demo-changes", collection([]));
        source("geo-distance", collection([]));
        const add = (layer: Parameters<LibreMap["addLayer"]>[0]) => {
          if (!map.getLayer(layer.id)) map.addLayer(layer);
        };
        add({
          id: "demo-grid-lines",
          type: "line",
          source: "demo-grid",
          paint: {
            "line-color": "#536370",
            "line-opacity": 0.17,
            "line-width": 0.6,
          },
        });
        add({
          id: "demo-buildings-3d",
          type: "fill-extrusion",
          source: "demo-buildings",
          paint: {
            "fill-extrusion-color": "#4b5868",
            "fill-extrusion-height": ["get", "height"],
            "fill-extrusion-opacity": 0.65,
          },
        });
        add({
          id: "demo-zones-fill",
          type: "fill-extrusion",
          source: "demo-zones",
          paint: {
            "fill-extrusion-color": [
              "case",
              ["get", "active"],
              "#dd8db4",
              "#728393",
            ],
            "fill-extrusion-height": ["case", ["get", "active"], 100, 0],
            "fill-extrusion-opacity": 0.12,
          },
        });
        add({
          id: "demo-zones-line",
          type: "line",
          source: "demo-zones",
          paint: {
            "line-color": ["case", ["get", "active"], "#e8a3c7", "#728393"],
            "line-width": 1.1,
            "line-dasharray": [4, 3],
          },
        });
        add({
          id: "demo-route-glow",
          type: "line",
          source: "demo-route",
          paint: {
            "line-color": "#98e0cf",
            "line-width": 9,
            "line-blur": 7,
            "line-opacity": 0.55,
          },
        });
        add({
          id: "demo-route-line",
          type: "line",
          source: "demo-route",
          paint: {
            "line-color": "#98e0cf",
            "line-width": 2.3,
            "line-opacity": 0.85,
          },
        });
        add({
          id: "demo-reference-line",
          type: "line",
          source: "demo-reference",
          paint: {
            "line-color": "#7b8998",
            "line-width": 1,
            "line-dasharray": [3, 4],
            "line-opacity": 0.6,
          },
        });
        add({
          id: "demo-progress-line",
          type: "line",
          source: "demo-progress",
          paint: { "line-color": "#e3fff7", "line-width": 3.2 },
        });
        add({
          id: "demo-preview-line",
          type: "line",
          source: "demo-preview",
          paint: {
            "line-color": "#c7adff",
            "line-width": 3,
            "line-dasharray": [3, 2],
          },
        });
        add({
          id: "demo-comparison-line",
          type: "line",
          source: "demo-comparison",
          paint: {
            "line-color": "#f0a6c6",
            "line-width": 3,
            "line-dasharray": [3, 2],
          },
        });
        add({
          id: "demo-changes-3d",
          type: "fill-extrusion",
          source: "demo-changes",
          paint: {
            "fill-extrusion-color": "#f0a6c6",
            "fill-extrusion-height": ["get", "height"],
            "fill-extrusion-opacity": 0.66,
          },
        });
        add({
          id: "demo-changes-outline",
          type: "line",
          source: "demo-changes",
          paint: { "line-color": "#ffb6d8", "line-width": 1.6 },
        });
        add({
          id: "geo-distance-line",
          type: "line",
          source: "geo-distance",
          paint: {
            "line-color": "#c5b0f7",
            "line-width": 1.5,
            "line-dasharray": [2, 4],
          },
        });
        if (!labels.length) {
          for (const site of scene.sites)
            marker(
              enuToLngLat(site.point),
              `${site.id} 备降点 · 演示`,
              "site",
              "routes",
            );
          scene.zones.forEach((zone) =>
            marker(
              enuToLngLat(zone.polygon[0]),
              `${zone.id} ${zone.active === false ? "区域草稿 · 本任务未生效" : "限制区"} · 演示`,
              "zone",
              "restrictions",
            ),
          );
        }
        updateTerrain();
        draw?.();
        sendReady();
      }
      async function reload(force = false) {
        if (disposed || (loadingStyle && !force)) return;
        const generation = ++styleGeneration;
        loadingStyle = true;
        online = false;
        clearTimeout(tileTimeout);
        styleAbort?.abort();
        const abort = new AbortController();
        styleAbort = abort;
        const timeout = window.setTimeout(() => abort.abort(), 12000);
        state("正在连接真实底图");
        try {
          const response = await fetch(CARTO_STYLE, { signal: abort.signal });
          if (!response.ok) throw new Error();
          const style = (await response.json()) as StyleSpecification;
          if (
            style.version !== 8 ||
            !style.sources ||
            !Array.isArray(style.layers)
          )
            throw new Error();
          if (disposed || generation !== styleGeneration) return;
          basemapSourceIds = new Set(Object.keys(style.sources));
          basemapHasTiles = false;
          mapReady = false;
          // A retry must rebuild even an identical style, so cached failures and
          // our overlays receive a fresh style.load lifecycle.
          state("底图加载中");
          tileTimeout = window.setTimeout(() => {
            if (!online) state("底图资源响应较慢 · 坐标可用");
          }, 18000);
          map.setStyle(style, { diff: false });
        } catch {
          if (!disposed && generation === styleGeneration) {
            state("底图离线 · 坐标可用");
          }
        } finally {
          clearTimeout(timeout);
          if (generation === styleGeneration) loadingStyle = false;
        }
      }
      const droneEl = document.createElement("div");
      droneEl.className = "geo-drone";
      droneEl.innerHTML =
        '<span class="geo-drone-ring"></span><span class="geo-drone-body">✥</span><b>无人机 <small></small></b>';
      const droneLabel = droneEl.querySelector("small")!;
      droneEl.hidden = true;
      const drone = new maplibregl.Marker({ element: droneEl })
        .setLngLat(enuToLngLat([150, 150]))
        .addTo(map);
      let lastProgress = -1,
        lastPreview = "",
        lastComparison = "",
        lastPins = "",
        lastTerrain = false,
        focusedLive = false;
      let lastNavigation = "";
      let lastRealScene: RealScene | null | undefined;
      let lastRealRoute = "";
      let lastRealConflictKey = "";
      let lastAirspaces = "";
      let lastNational = "";
      let airspaceLabels: maplibregl.Marker[] = [];
      const nationalRed = "#d64545";
      function syncNationalFlysafe() {
        if (!mapReady) return;
        const overlay = dynamic.current.nationalFlysafe;
        const key = dynamic.current.nationalFlysafeKey ?? "";
        const features = overlay?.features ?? [];
        if (key !== lastNational || !map.getSource("flysafe-national")) {
          lastNational = key;
          source(
            "flysafe-national",
            features.length
              ? overlay!
              : { type: "FeatureCollection", features: [] },
          );
          if (!map.getLayer("flysafe-national-fill"))
            map.addLayer({
              id: "flysafe-national-fill",
              type: "fill",
              source: "flysafe-national",
              paint: {
                "fill-color": nationalRed,
                "fill-opacity": 0.46,
              },
            });
          if (!map.getLayer("flysafe-national-outline"))
            map.addLayer({
              id: "flysafe-national-outline",
              type: "line",
              source: "flysafe-national",
              paint: {
                "line-color": nationalRed,
                "line-width": 1.8,
              },
            });
          addBelowDemo("flysafe-national-fill");
          addBelowDemo("flysafe-national-outline");
        }
        const visible =
          dynamic.current.layers.restrictions && features.length > 0;
        setLayerVisibility("flysafe-national-fill", visible);
        setLayerVisibility("flysafe-national-outline", visible);
      }
      function syncNavigation() {
        if (!mapReady) return;
        const nav = dynamic.current.navigation;
        const regionKey = JSON.stringify([nav?.regions, nav?.selectedRegion]);
        if (regionKey !== lastAirspaces || !map.getSource("airspace-regions")) {
          lastAirspaces = regionKey;
          source(
            "airspace-regions",
            collection(
              (nav?.regions ?? []).map((r) =>
                feature(r.geometry, {
                  region_id: r.id,
                  kind: r.kind,
                  color: airspaceKinds[r.kind].color,
                  selected: r.id === nav?.selectedRegion ? 1 : 0,
                }),
              ),
            ),
          );
          if (!map.getLayer("airspace-regions-fill"))
            map.addLayer({
              id: "airspace-regions-fill",
              type: "fill",
              source: "airspace-regions",
              paint: {
                "fill-color": ["get", "color"],
                "fill-opacity": [
                  "case",
                  [
                    "all",
                    ["==", ["get", "kind"], "restricted"],
                    ["==", ["get", "selected"], 1],
                  ],
                  0.52,
                  ["==", ["get", "kind"], "restricted"],
                  0.42,
                  ["==", ["get", "selected"], 1],
                  0.42,
                  0.32,
                ],
              },
            });
          if (!map.getLayer("airspace-regions-outline"))
            map.addLayer({
              id: "airspace-regions-outline",
              type: "line",
              source: "airspace-regions",
              paint: {
                "line-color": ["get", "color"],
                "line-width": [
                  "case",
                  [
                    "all",
                    ["==", ["get", "kind"], "restricted"],
                    ["==", ["get", "selected"], 1],
                  ],
                  3,
                  ["==", ["get", "kind"], "restricted"],
                  2.4,
                  1.8,
                ],
              },
            });
          airspaceLabels.forEach((m) => m.remove());
          airspaceLabels = (nav?.regions ?? []).map((r) => {
            const el = document.createElement("button");
            el.className = "geo-airspace-label";
            el.style.borderColor = airspaceKinds[r.kind].color;
            el.textContent = `${
              r.is_simulated
                ? "演练 · "
                : r.source_kind === "manufacturer"
                  ? "FlySafe · "
                  : "参考 · "
            }${r.name}`;
            el.title = `${airspaceKinds[r.kind].title} · ${r.source}`;
            el.addEventListener("click", (e) => {
              e.stopPropagation();
              dynamic.current.onAirspaceSelect?.(r.id);
            });
            const ring =
              r.geometry.type === "Polygon"
                ? r.geometry.coordinates[0]
                : r.geometry.coordinates[0][0];
            return new maplibregl.Marker({ element: el, anchor: "bottom-left" })
              .setLngLat([ring[0][0], ring[0][1]])
              .addTo(map);
          });
        }
        const restrictionsVisible = dynamic.current.layers.restrictions;
        setLayerVisibility("airspace-regions-fill", restrictionsVisible);
        setLayerVisibility("airspace-regions-outline", restrictionsVisible);
        airspaceLabels.forEach((m) => {
          m.getElement().hidden = !restrictionsVisible;
        });
        const key = JSON.stringify(nav);
        if (key === lastNavigation && map.getSource("navigation-active"))
          return;
        lastNavigation = key;
        for (const [id, points] of [
          ["navigation-active", nav?.active ?? []],
          ["navigation-comparison", nav?.comparison ?? []],
        ] as const) {
          source(id, collection(points.length > 1 ? [line([...points])] : []));
        }
        source(
          "navigation-track",
          collection((nav?.flown ?? []).filter((v) => v.length > 1).map(line)),
        );
        source(
          "navigation-waypoints",
          collection(
            (nav?.active ?? []).map((p, i) =>
              feature({ type: "Point", coordinates: p }, { index: i + 1 }),
            ),
          ),
        );
        source(
          "navigation-target",
          collection(
            nav?.target
              ? [feature({ type: "Point", coordinates: nav.target })]
              : [],
          ),
        );
        for (const [id, color, dash] of [
          ["navigation-active", "#3698eb", false],
          ["navigation-comparison", "#b18be8", true],
          ["navigation-track", "#63d8b0", false],
        ] as const) {
          if (!map.getLayer(id + "-line"))
            map.addLayer({
              id: id + "-line",
              type: "line",
              source: id,
              paint: {
                "line-color": color,
                "line-width": id === "navigation-active" ? 4 : 3,
                ...(dash ? { "line-dasharray": [3, 3] } : {}),
              },
            });
        }
        if (!map.getLayer("navigation-waypoints-circle"))
          map.addLayer({
            id: "navigation-waypoints-circle",
            type: "circle",
            source: "navigation-waypoints",
            paint: {
              "circle-radius": 4,
              "circle-color": "#d4edff",
              "circle-stroke-color": "#328add",
              "circle-stroke-width": 2,
            },
          });
        if (!map.getLayer("navigation-target-circle"))
          map.addLayer({
            id: "navigation-target-circle",
            type: "circle",
            source: "navigation-target",
            paint: {
              "circle-radius": 10,
              "circle-color": "#3295e7",
              "circle-opacity": 0.25,
              "circle-stroke-color": "#b6ddff",
              "circle-stroke-width": 3,
            },
          });
      }
      function syncRealData() {
        if (!mapReady) return;
        const p = dynamic.current;
        if (lastRealScene !== p.realScene || !map.getSource("real-buildings")) {
          lastRealScene = p.realScene;
          realSceneError = "";
          inspectRealSceneNextFrame = true;
          realSceneStatus("loading");
          source("real-buildings", p.realScene?.obstacles ?? collection([]));
          source("real-roads", p.realScene?.roads ?? collection([]));
          map.triggerRepaint();
        }
        const routeKey = JSON.stringify(p.realRoute);
        if (lastRealRoute !== routeKey || !map.getSource("real-route")) {
          lastRealRoute = routeKey;
          source(
            "real-route",
            collection(
              (p.realRoute?.length ?? 0) > 1 ? [line(p.realRoute!)] : [],
            ),
          );
        }
        const conflictKey = JSON.stringify([
          p.realPreviousRoute,
          p.realConflictSegments,
        ]);
        if (
          lastRealConflictKey !== conflictKey ||
          !map.getSource("real-conflict-segments")
        ) {
          lastRealConflictKey = conflictKey;
          source(
            "real-previous-route",
            collection(
              (p.realPreviousRoute?.length ?? 0) > 1
                ? [line(p.realPreviousRoute!)]
                : [],
            ),
          );
          source(
            "real-conflict-segments",
            collection(
              (p.realConflictSegments ?? [])
                .filter((seg) => seg.length === 2)
                .map((seg) => line([seg[0], seg[1]])),
            ),
          );
          if (root.current) {
            root.current.dataset.realConflictSegments = String(
              p.realConflictSegments?.length ?? 0,
            );
            root.current.dataset.realPreviousRoutePoints = String(
              p.realPreviousRoute?.length ?? 0,
            );
          }
        }
        if (!map.getLayer("real-roads-line"))
          map.addLayer({
            id: "real-roads-line",
            type: "line",
            source: "real-roads",
            paint: {
              "line-color": "#66a8b2",
              "line-width": 1.5,
              "line-opacity": 0.65,
            },
          });
        if (!map.getLayer("real-buildings-fill"))
          map.addLayer({
            id: "real-buildings-fill",
            type: "fill",
            source: "real-buildings",
            paint: {
              "fill-color": [
                "case",
                ["==", ["get", "height_source"], "tag"],
                "#d49b6d",
                "#ba8bce",
              ],
              "fill-opacity": 0.4,
            },
          });
        if (!map.getLayer("real-buildings-outline"))
          map.addLayer({
            id: "real-buildings-outline",
            type: "line",
            source: "real-buildings",
            paint: { "line-color": "#c985a4", "line-width": 1 },
          });
        if (!map.getLayer("real-previous-route-line"))
          map.addLayer({
            id: "real-previous-route-line",
            type: "line",
            source: "real-previous-route",
            paint: {
              "line-color": "#94a3b8",
              "line-width": 2.6,
              "line-dasharray": [3, 3],
              "line-opacity": 0.72,
            },
          });
        if (!map.getLayer("real-route-line"))
          map.addLayer({
            id: "real-route-line",
            type: "line",
            source: "real-route",
            paint: { "line-color": "#36dcb5", "line-width": 4 },
          });
        if (!map.getLayer("real-conflict-segments-glow"))
          map.addLayer({
            id: "real-conflict-segments-glow",
            type: "line",
            source: "real-conflict-segments",
            paint: {
              "line-color": "#ff4d5e",
              "line-width": 11,
              "line-blur": 4,
              "line-opacity": 0.34,
            },
          });
        if (!map.getLayer("real-conflict-segments-line"))
          map.addLayer({
            id: "real-conflict-segments-line",
            type: "line",
            source: "real-conflict-segments",
            paint: {
              "line-color": "#ef4444",
              "line-width": 5.5,
            },
          });
        for (const id of ["real-buildings-fill", "real-buildings-outline"])
          map.setLayoutProperty(
            id,
            "visibility",
            p.layers.buildings ? "visible" : "none",
          );
        for (const id of [
          "real-previous-route-line",
          "real-route-line",
          "real-conflict-segments-glow",
          "real-conflict-segments-line",
        ])
          map.setLayoutProperty(
            id,
            "visibility",
            p.layers.routes ? "visible" : "none",
          );
        if (map.getLayer("geo-distance-line"))
          map.setLayoutProperty(
            "geo-distance-line",
            "visibility",
            p.realRoute?.length ? "none" : "visible",
          );
      }
      function inspectRealScene() {
        if (
          disposed ||
          !inspectRealSceneNextFrame ||
          !dynamic.current.realScene ||
          lastRealScene !== dynamic.current.realScene
        )
          return;
        if (realSceneError) {
          realSceneStatus("error");
          return;
        }
        if (
          !map.getLayer("real-buildings-fill") ||
          !map.getLayer("real-roads-line") ||
          !map.isSourceLoaded("real-buildings") ||
          !map.isSourceLoaded("real-roads")
        ) {
          realSceneStatus("loading");
          return;
        }
        // A completed HTTP body or worker index does not mean the map has
        // painted its tiles. Only inspect after MapLibre's render event, and
        // require actual visible features from both genuine scene layers.
        const buildings = map.queryRenderedFeatures({
          layers: ["real-buildings-fill"],
        }).length;
        const roads = map.queryRenderedFeatures({
          layers: ["real-roads-line"],
        }).length;
        const ready = buildings > 0 && roads > 0;
        realSceneStatus(ready ? "ready" : "loading", buildings, roads);
        if (ready) inspectRealSceneNextFrame = false;
      }
      map.on("render", inspectRealScene);
      map.on("moveend", () => {
        inspectRealSceneNextFrame = true;
        map.triggerRepaint();
      });
      map.on("click", "real-buildings-fill", (event) => {
        const props = event.features?.[0]?.properties;
        if (!props) return;
        const node = document.createElement("div");
        node.textContent = `${props.id} · 高度 ${props.height_m == null ? "未知" : `${props.height_m} m`} · 高度来源 ${props.height_source} · 几何 ${props.geometry_status === "derived_conservative" ? "真实节点派生的保守估算包络" : "OSM 建筑轮廓"} · ${props.source} · 抓取 ${props.fetched_at}`;
        new maplibregl.Popup()
          .setLngLat(event.lngLat)
          .setDOMContent(node)
          .addTo(map);
      });
      draw = () => {
        const p = dynamic.current;
        syncRealData();
        droneLabel.textContent = p.liveMode ? "实时遥测" : "演示航迹";
        droneEl.hidden = p.liveMode
          ? !p.livePoint || !mapReady
          : !p.demoVisible || !p.layers.routes;
        if (p.liveMode) {
          lastProgress = -1;
          if (p.livePoint && mapReady) {
            drone.setLngLat(p.livePoint);
            if (!focusedLive) {
              map.jumpTo({ center: p.livePoint, zoom: 15.3 });
              focusedLive = true;
            }
          }
        } else {
          focusedLive = false;
        }
        droneEl.classList.toggle(
          "no-scan",
          p.liveMode || !p.layers.scan || !p.playing || p.reducedMotion,
        );
        syncOverlays();
        syncNationalFlysafe();
        syncNavigation();
        if (p.navigation?.aircraft) {
          droneEl.hidden = !mapReady;
          drone.setLngLat(p.navigation.aircraft);
          droneLabel.textContent = p.liveMode
            ? "导航参考 · 遥测"
            : "导航参考 · 演练";
        }
        (
          droneEl.querySelector(".geo-drone-body") as HTMLElement
        ).style.transform = `rotate(${p.navigation?.heading ?? 0}deg)`;
        if (p.basemap !== lastBasemap) {
          lastBasemap = p.basemap;
          state(
            p.basemap === "satellite"
              ? satelliteFailed
                ? "卫星底图暂不可用 · 主题底图可用"
                : "卫星实景 · Esri World Imagery"
              : online
                ? "真实底图 · CARTO Positron"
                : "底图离线 · 坐标可用",
          );
        }
        if (disposed || !mapReady || !scene || !map.getSource("demo-route"))
          return;
        if (
          !p.liveMode &&
          !p.navigation?.aircraft &&
          p.progress !== lastProgress
        ) {
          lastProgress = p.progress;
          const point = pointAlong(scene.route, p.progress);
          drone.setLngLat(enuToLngLat(point));
          source(
            "demo-progress",
            collection([
              line(
                [
                  ...scene.route.slice(
                    0,
                    Math.max(
                      1,
                      Math.floor(p.progress * (scene.route.length - 1)),
                    ),
                  ),
                  point,
                ].map(enuToLngLat),
              ),
            ]),
          );
        }
        if (JSON.stringify(p.preview) !== lastPreview) {
          lastPreview = JSON.stringify(p.preview);
          source(
            "demo-preview",
            collection(
              p.preview ? [line(p.preview.waypoints.map(enuToLngLat))] : [],
            ),
          );
        }
        if ((p.comparison?.id ?? "") !== lastComparison) {
          lastComparison = p.comparison?.id ?? "";
          source(
            "demo-comparison",
            collection(
              p.comparison
                ? [line(p.comparison.waypoints.map(enuToLngLat))]
                : [],
            ),
          );
        }
        for (const [group, ids] of Object.entries({
          buildings: ["demo-buildings-3d"],
          restrictions: ["demo-zones-fill", "demo-zones-line"],
          routes: [
            "demo-route-glow",
            "demo-route-line",
            "demo-progress-line",
            "demo-reference-line",
            "demo-preview-line",
            "demo-comparison-line",
          ],
          terrain: [
            "demo-changes-3d",
            "demo-changes-outline",
            "demo-grid-lines",
          ],
        })) {
          const visible = p.demoVisible && p.layers[group as keyof Layers];
          ids.forEach((id) => {
            if (map.getLayer(id))
              map.setLayoutProperty(
                id,
                "visibility",
                visible ? "visible" : "none",
              );
          });
        }
        labels.forEach(({ marker, group }) => {
          marker.getElement().hidden =
            !p.demoVisible || !p.layers[group as keyof Layers];
        });
        const pinKey = JSON.stringify([
          p.mission,
          p.selected,
          Boolean(p.realRoute?.length),
        ]);
        if (lastPins !== pinKey) {
          lastPins = pinKey;
          pins.splice(0).forEach((pin) => pin.remove());
          for (const [key, place] of Object.entries({
            ...p.mission,
            selected: p.selected,
          })) {
            if (!place) continue;
            const el = document.createElement("div");
            el.className = `geo-pin ${key}`;
            const icon = document.createElement("span");
            icon.textContent =
              key === "origin" ? "起" : key === "destination" ? "终" : "+";
            const label = document.createElement("b");
            label.textContent = place.name;
            el.append(icon, label);
            pins.push(
              new maplibregl.Marker({ element: el, anchor: "bottom" })
                .setLngLat(place.point)
                .addTo(map),
            );
          }
          source(
            "geo-distance",
            collection(
              p.mission.origin && p.mission.destination && !p.realRoute?.length
                ? [line([p.mission.origin.point, p.mission.destination.point])]
                : [],
            ),
          );
        }
      };
      runtime.current = { map, update: updateTerrain, reload, scene };
      map.on("load", () => {
        mapReady = true;
        install();
        updateWindView();
      });
      map.on("style.load", () => {
        mapReady = true;
        lastProgress = -1;
        lastPins = "";
        lastPreview = "__reset";
        lastComparison = "__reset";
        lastTerrain = false;
        terrainFailed = false;
        satelliteFailed = false;
        radarTileKey = "";
        glowOpacityCache = -1;
        visibilityCache.clear();
        inspectRealSceneNextFrame = true;
        realSceneStatus("loading");
        install();
      });
      map.on("sourcedata", (event) => {
        const sourceId = event.sourceId;
        if (sourceId === "real-buildings" || sourceId === "real-roads") {
          inspectRealSceneNextFrame = true;
          // GeoJSON's heavy worker/tiling completion happens independently
          // from the route response and its DOM panel. Render its new tiles
          // before publishing scene-ready diagnostics.
          map.triggerRepaint();
          return;
        }
        if (sourceId === "satellite") {
          // 卫星瓦片成功即恢复状态；失败只更新状态条，不影响主题底图。
          if (event.tile && event.isSourceLoaded && satelliteFailed) {
            satelliteFailed = false;
            if (dynamic.current.basemap === "satellite")
              state("卫星实景 · Esri World Imagery");
          }
          return;
        }
        if (sourceId?.startsWith("weather-")) return;
        if (sourceId && basemapSourceIds.has(sourceId) && event.tile)
          basemapHasTiles = true;
        if (
          sourceId &&
          basemapSourceIds.has(sourceId) &&
          event.isSourceLoaded &&
          // MapLibre can signal source completion in a later idle event without a tile.
          basemapHasTiles
        ) {
          if (!online) {
            online = true;
            clearTimeout(tileTimeout);
            state(
              dynamic.current.basemap === "satellite"
                ? "卫星实景 · Esri World Imagery"
                : "真实底图 · CARTO",
            );
          }
        }
      });
      map.on("error", (event) => {
        if (disposed) return;
        const sourceId = (event as { sourceId?: string }).sourceId;
        if (sourceId?.startsWith("real-")) {
          realSceneError = event.error?.message ?? "真实地图图层加载失败";
          realSceneStatus("error");
          return;
        }
        if (sourceId === "satellite") {
          // 卫星影像失败：只更新状态条并保留 CARTO 主题底图，绝不阻塞地图。
          if (!satelliteFailed) {
            satelliteFailed = true;
            if (dynamic.current.basemap === "satellite")
              state("卫星底图暂不可用 · 主题底图可用");
          }
          return;
        }
        if (sourceId?.startsWith("weather-")) return;
        if (sourceId === "global-dem") {
          terrainFailed = true;
          map.setTerrain(null);
          state("真实地形暂不可用 · 底图可用");
          return;
        }
        if (
          sourceId &&
          (sourceId.startsWith("demo-") || sourceId.startsWith("geo-"))
        )
          return;
        online = false;
        state("底图资源不可用 · 可重试");
      });
      const sceneAbort = new AbortController();
      fetch("/demo-scene.json", { signal: sceneAbort.signal })
        .then((r) => {
          if (!r.ok) throw new Error();
          return r.json();
        })
        .then((data: SceneData) => {
          if (disposed) return;
          if (
            !Array.isArray(data.route) ||
            data.route.length < 2 ||
            !Array.isArray(data.buildings) ||
            !Array.isArray(data.zones) ||
            !Array.isArray(data.sites)
          )
            throw new Error();
          scene = data;
          if (runtime.current) runtime.current.scene = data;
          install();
          sendReady();
        })
        .catch(() => {
          if (!disposed)
            dynamic.current.onError(
              "虚拟场景加载失败，请刷新重试；真实地图仍可操作。",
            );
        });
      let resizeFrame: number | undefined;
      const observer = new ResizeObserver(() => {
        if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(() => {
          resizeFrame = undefined;
          if (disposed) return;
          // MapLibre 6 resize() updates its canvas, camera, and DOM markers,
          // but does not render. Keep the GPU layer projection in the same
          // frame as the markers after workspace/sidebar layout changes.
          map.resize();
          map.redraw();
        });
      });
      observer.observe(root.current!);
      const timer = window.setInterval(() => draw?.(), 150);
      void reload();
      return () => {
        disposed = true;
        clearInterval(timer);
        clearTimeout(tileTimeout);
        styleAbort?.abort();
        sceneAbort.abort();
        observer.disconnect();
        if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame);
        pins.forEach((p) => p.remove());
        labels.forEach((p) => p.marker.remove());
        airspaceLabels.forEach((m) => m.remove());
        drone.remove();
        window.clearInterval(windTimer);
        dynamic.current.onWindMove(false);
        if (windView) dynamic.current.onWindView(false);
        motionPreference.removeEventListener("change", updateWindMotion);
        document.removeEventListener("visibilitychange", updateWindMotion);
        map.remove();
        runtime.current = null;
      };
    }, []);
    useEffect(() => {
      const map = runtime.current?.map;
      if (map)
        map.easeTo({
          pitch: props.mode === "3d" ? 55 : 0,
          bearing: props.mode === "3d" ? -24 : 0,
          duration: props.reducedMotion ? 0 : 950,
        });
    }, [props.mode, props.reducedMotion]);
    return (
      <>
        <div ref={root} className="map-render geo-map" />
        <div
          className={`basemap-state ${status.includes("离线") || status.includes("不可用") ? "offline" : ""}`}
        >
          <i />
          {status}
          <button
            onClick={() => runtime.current?.reload()}
            aria-label="重试真实底图"
          >
            ↻
          </button>
        </div>
      </>
    );
  },
);
