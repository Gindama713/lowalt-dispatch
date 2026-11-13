import { forwardRef, lazy, Suspense, useImperativeHandle, useRef } from "react";
import GeoMap, { type GeoMapHandle, type GeoMapProps } from "./GeoMap";
import type { MapHandle } from "./MapScene";
import { type LngLat } from "./geo";
const TerrainScene = lazy(() => import("./MapScene"));
export type MapSurfaceHandle = GeoMapHandle;
export default forwardRef<
  MapSurfaceHandle,
  GeoMapProps & { kind: "world" | "terrain" }
>(function MapSurface(props, ref) {
  const world = useRef<GeoMapHandle>(null),
    terrain = useRef<MapHandle>(null);
  useImperativeHandle(
    ref,
    () => ({
      reset: () =>
        props.kind === "world"
          ? world.current?.reset()
          : terrain.current?.reset(),
      zoom: (factor) =>
        props.kind === "world"
          ? world.current?.zoom(factor)
          : terrain.current?.zoom(factor),
      focus: (point) =>
        props.kind === "world"
          ? world.current?.focus(point)
          : terrain.current?.focus(point),
      flyTo: (point: LngLat) => world.current?.flyTo(point),
      showWindRegion: () => world.current?.showWindRegion(),
      retry: () => world.current?.retry(),
      applyTerrain: (patch) => {
        if (props.kind === "world" && world.current)
          return world.current.applyTerrain(patch);
        if (terrain.current) return terrain.current.applyTerrain(patch);
        return props.terrainModel.apply(patch);
      },
    }),
    [props.kind, props.terrainModel],
  );
  if (props.kind === "terrain")
    return (
      <Suspense fallback={<div className="map-loading">加载地形实验视图…</div>}>
        <TerrainScene
          ref={terrain}
          mode={props.mode}
          layers={props.layers}
          progress={props.progress}
          playing={props.playing && !props.reducedMotion}
          terrainModel={props.terrainModel}
          preview={props.preview}
          onReady={props.onReady}
          onError={props.onError}
          onPoint={() => {
            /* Synthetic ENU clicks must never become real mission coordinates. */
          }}
        />
      </Suspense>
    );
  return <GeoMap ref={world} {...props} />;
});
