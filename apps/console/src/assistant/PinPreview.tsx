import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import mapWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

import { CARTO_STYLE } from "../GeoMap";
import type { LngLat } from "../geo";
import "./clarification.css";

maplibregl.setWorkerUrl(mapWorkerUrl);

type Props = {
  point: LngLat;
  label: string;
  onOpen: () => void;
};

/** Small read-only map so the intake card shows the actual place, not just text. */
export function PinPreview({ point, label, onOpen }: Props) {
  const holder = useRef<HTMLDivElement>(null);
  const [lng, lat] = point;

  useEffect(() => {
    if (!holder.current) return;
    const instance = new maplibregl.Map({
      container: holder.current,
      style: CARTO_STYLE,
      center: [lng, lat],
      zoom: 14,
      interactive: false,
      attributionControl: false,
    });
    new maplibregl.Marker({ color: "#1f9d55" })
      .setLngLat([lng, lat])
      .addTo(instance);
    return () => instance.remove();
  }, [lng, lat]);

  return (
    <button
      type="button"
      className="intake-pin-map"
      aria-label={`查看或修改 ${label} 的位置`}
      onClick={onOpen}
    >
      <div ref={holder} />
      <span>点击修改位置</span>
    </button>
  );
}
