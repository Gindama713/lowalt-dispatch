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
const offline: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [
    {
      id: "background",
      type: "background",
      paint: { "background-color": "#08090b" },
    },
  ],
};
type FeatureProps = Record<string, string | number>;
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
};
export type GeoMapProps = {
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
      reload: () => void;
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
        // Frame the Yangtze Delta inside the wider data extent, with room to pan.
        runtime.current?.map.fitBounds(
          [
            [119.2, 29.95],
            [123.8, 32.55],
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
      let tileTimeout: number | undefined;
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
          style: offline,
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
      map.on("click", (e) =>
        dynamic.current.onPoint([e.lngLat.wrap().lng, e.lngLat.lat]),
      );
      const updateWindView = () => {
        const bounds = map.getBounds();
        const center = map.getCenter();
        const offset = center.lng - center.wrap().lng;
        const next =
          map.getZoom() < WIND_MAX_ZOOM &&
          bounds.getEast() - offset >= WIND_REGION.west &&
          bounds.getWest() - offset <= WIND_REGION.east &&
          bounds.getNorth() >= WIND_REGION.south &&
          bounds.getSouth() <= WIND_REGION.north;
        if (windView !== next) {
          windView = next;
          dynamic.current.onWindView(next);
        }
      };
      map.on("movestart", () => {
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
            const { west, east, south, north } = WIND_REGION;
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
            scene.zones.map((z) => polygon(z.polygon.map(enuToLngLat))),
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
            "fill-extrusion-color": "#dd8db4",
            "fill-extrusion-height": 100,
            "fill-extrusion-opacity": 0.12,
          },
        });
        add({
          id: "demo-zones-line",
          type: "line",
          source: "demo-zones",
          paint: {
            "line-color": "#e8a3c7",
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
              `${zone.id} 限制区 · 演示`,
              "zone",
              "restrictions",
            ),
          );
        }
        updateTerrain();
        draw?.();
        sendReady();
      }
      async function reload() {
        if (disposed || loadingStyle) return;
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
          if (disposed) return;
          mapReady = false;
          // A retry must rebuild even an identical style, so cached failures and
          // our overlays receive a fresh style.load lifecycle.
          map.setStyle(style, { diff: false }); // Same CARTO style as CodeArts.
          state("底图加载中");
          tileTimeout = window.setTimeout(() => {
            if (!online) state("底图资源响应较慢 · 坐标可用");
          }, 18000);
        } catch {
          if (!disposed) state("底图离线 · 坐标可用");
        } finally {
          clearTimeout(timeout);
          loadingStyle = false;
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
      draw = () => {
        const p = dynamic.current;
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
        if (p.basemap !== lastBasemap) {
          lastBasemap = p.basemap;
          state(
            p.basemap === "satellite"
              ? satelliteFailed
                ? "卫星底图暂不可用 · 暗色底图可用"
                : "卫星实景 · Esri World Imagery"
              : online
                ? "真实底图 · CARTO"
                : "底图离线 · 坐标可用",
          );
        }
        if (disposed || !mapReady || !scene || !map.getSource("demo-route"))
          return;
        if (!p.liveMode && p.progress !== lastProgress) {
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
        if ((p.preview?.route_id ?? "") !== lastPreview) {
          lastPreview = p.preview?.route_id ?? "";
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
        const pinKey = JSON.stringify([p.mission, p.selected]);
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
              p.mission.origin && p.mission.destination
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
        install();
      });
      map.on("sourcedata", (event) => {
        const sourceId = event.sourceId;
        if (sourceId === "satellite") {
          // 卫星瓦片成功即恢复状态；失败只更新状态条，不影响暗色底图。
          if (event.tile && event.isSourceLoaded && satelliteFailed) {
            satelliteFailed = false;
            if (dynamic.current.basemap === "satellite")
              state("卫星实景 · Esri World Imagery");
          }
          return;
        }
        if (sourceId?.startsWith("weather-")) return;
        if (
          sourceId &&
          !sourceId.startsWith("demo-") &&
          !sourceId.startsWith("geo-") &&
          sourceId !== "global-dem" &&
          event.isSourceLoaded &&
          event.tile
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
        if (sourceId === "satellite") {
          // 卫星影像失败：只更新状态条并保留 CARTO 暗色底图，绝不阻塞地图。
          if (!satelliteFailed) {
            satelliteFailed = true;
            if (dynamic.current.basemap === "satellite")
              state("卫星底图暂不可用 · 暗色底图可用");
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
      const observer = new ResizeObserver(() => map.resize());
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
        pins.forEach((p) => p.remove());
        labels.forEach((p) => p.marker.remove());
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
