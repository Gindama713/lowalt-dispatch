import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { MapPin, Search, X } from "lucide-react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import mapWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

import { CARTO_STYLE } from "../GeoMap";
import {
  formatCoordinates,
  parseCoordinates,
  validGeoPlace,
  type GeoPlace,
  type LngLat,
} from "../geo";
import "./clarification.css";

maplibregl.setWorkerUrl(mapWorkerUrl);

type Props = {
  field: "origin" | "destination";
  initial: LngLat | null;
  onClose: () => void;
  onPick: (place: GeoPlace) => void;
};

export function MapPicker({ field, initial, onClose, onPick }: Props) {
  const holder = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const marker = useRef<maplibregl.Marker | null>(null);
  const [point, setPoint] = useState<LngLat | null>(initial);
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GeoPlace[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [manual, setManual] = useState("");
  const [tileError, setTileError] = useState(false);
  const [chosenAddress, setChosenAddress] = useState("");

  useEffect(() => {
    if (!holder.current) return;
    const instance = new maplibregl.Map({
      container: holder.current,
      style: CARTO_STYLE,
      center: initial ?? [121.4737, 31.2304],
      zoom: initial ? 14 : 11,
      attributionControl: false,
    });
    map.current = instance;
    instance.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "top-right",
    );
    instance.on("click", (event) => {
      setPoint([event.lngLat.lng, event.lngLat.lat]);
      setChosenAddress("");
    });
    instance.on("error", () => setTileError(true));
    return () => {
      instance.remove();
      map.current = null;
      marker.current = null;
    };
  }, [initial]);

  useEffect(() => {
    const instance = map.current;
    if (!instance || !point) return;
    if (!marker.current) {
      marker.current = new maplibregl.Marker({ color: "#1f9d55" })
        .setLngLat(point)
        .addTo(instance);
    } else {
      marker.current.setLngLat(point);
    }
    instance.flyTo({
      center: point,
      zoom: Math.max(instance.getZoom(), 14),
      duration: 400,
    });
  }, [point]);

  async function search(event: React.FormEvent) {
    event.preventDefault();
    const value = query.trim();
    if (value.length < 2) return;
    setBusy(true);
    setMessage("");
    setResults([]);
    try {
      const response = await fetch(
        `/api/assistant/places/search?q=${encodeURIComponent(value)}`,
      );
      if (!response.ok)
        throw new Error(
          response.status === 429
            ? "搜索太快，请等一秒再试。"
            : "地点搜索暂不可用，可直接在地图上点选。",
        );
      const body = await response.json();
      const places = (body.places ?? []).filter(validGeoPlace);
      setResults(places);
      if (body.unavailable)
        setMessage(
          "地点搜索服务不可达（外网受限）。可在地图上点选或手动输入经纬度。",
        );
      else if (!places.length)
        setMessage("没有找到匹配地点，可直接在地图上点选");
    } catch (error) {
      setMessage(
        error instanceof TypeError
          ? "连不上助手服务，请确认后端已启动。"
          : error instanceof Error
            ? error.message
            : "搜索失败",
      );
    } finally {
      setBusy(false);
    }
  }

  function choose(place: GeoPlace) {
    setPoint(place.point);
    setName(place.name);
    setQuery(place.name);
    setChosenAddress(place.address ?? "");
    setResults([]);
  }

  function applyManual() {
    try {
      const coordinates = parseCoordinates(manual);
      if (!coordinates) {
        setMessage("请按「经度, 纬度」输入两个数字");
        return;
      }
      setPoint(coordinates);
      setChosenAddress("");
      setMessage("已使用手动输入的经纬度");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "坐标格式不正确");
    }
  }

  function confirm() {
    if (!point) return;
    onPick({
      name:
        name.trim() ||
        (field === "origin" ? "地图选点（起点）" : "地图选点（终点）"),
      point,
      source: "map_click",
      capturedAt: new Date().toISOString(),
      address: chosenAddress || undefined,
    });
  }

  // Portal to <body>: the assistant panel uses transforms, which would clip a
  // position:fixed dialog and break centring.
  return createPortal(
    <div
      className="map-picker-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={field === "origin" ? "地图选点：起点" : "地图选点：终点"}
      data-testid="map-picker"
    >
      <div className="map-picker">
        <header>
          <strong>{field === "origin" ? "选择起点" : "选择终点"}</strong>
          <button type="button" aria-label="关闭地图选点" onClick={onClose}>
            <X size={16} />
          </button>
        </header>
        <form className="map-picker-search" onSubmit={search}>
          <Search size={14} />
          <input
            aria-label="搜索地点"
            placeholder="搜索地名，例如 南昌航空大学"
            value={query}
            maxLength={180}
            onChange={(event) => setQuery(event.target.value)}
          />
          <button disabled={busy || query.trim().length < 2}>
            {busy ? "…" : "搜索"}
          </button>
        </form>
        {!!results.length && (
          <div className="map-picker-results">
            {results.map((place) => (
              <button
                type="button"
                key={place.name + place.point.join(",")}
                onClick={() => choose(place)}
              >
                <MapPin size={12} />
                <span>
                  {place.name}
                  <small>{formatCoordinates(place.point)}</small>
                </span>
              </button>
            ))}
          </div>
        )}
        {message && <p className="map-picker-message">{message}</p>}
        <div className="map-picker-canvas" ref={holder} />
        <p className="map-picker-message">
          {tileError
            ? "底图瓦片未加载（网络受限时常见）。仍可搜索地名或手动输入经纬度。"
            : "底图来自 CARTO 公开瓦片；若长时间空白，可直接搜索地名或输入经纬度。"}
        </p>
        <form
          className="map-picker-manual"
          onSubmit={(event) => {
            event.preventDefault();
            applyManual();
          }}
        >
          <input
            aria-label="手动输入经纬度"
            placeholder="或输入 经度, 纬度（例如 115.858, 28.685）"
            value={manual}
            maxLength={40}
            onChange={(event) => setManual(event.target.value)}
          />
          <button disabled={!manual.trim()}>使用坐标</button>
        </form>
        <footer>
          <small>
            {point ? formatCoordinates(point) : "在地图上点选一个位置"}
          </small>
          <button type="button" disabled={!point} onClick={confirm}>
            确认使用此位置
          </button>
        </footer>
        <p className="map-picker-note">
          地图选点保存 WGS84 经纬度，只用于任务工单；不会自动规划或下发。
        </p>
      </div>
    </div>,
    document.body,
  );
}
