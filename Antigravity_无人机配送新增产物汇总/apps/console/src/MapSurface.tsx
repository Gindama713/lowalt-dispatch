import { forwardRef, lazy, Suspense, useImperativeHandle, useRef } from "react";
import GeoMap, { type GeoMapHandle, type GeoMapProps } from "./GeoMap";
import type { MapHandle } from "./MapScene";
import { type LngLat } from "./geo";
const TerrainScene = lazy(() => import("./MapScene"));
const ShenzhenScene = lazy(() => import("./ShenzhenCityScene"));
export type MapSurfaceHandle = GeoMapHandle;
export type MapSurfaceKind = "world" | "shenzhen" | "terrain";
export default forwardRef<
  MapSurfaceHandle,
  GeoMapProps & { kind: MapSurfaceKind }
>(function MapSurface(props, ref) {
  const world = useRef<GeoMapHandle>(null),
    shenzhen = useRef<MapHandle>(null),
    terrain = useRef<MapHandle>(null);
  const active3d = () =>
    props.kind === "shenzhen" ? shenzhen.current : terrain.current;
  useImperativeHandle(
    ref,
    () => ({
      navigate: (center, zoom, bearing, pitch) => {
        if (props.kind === "world")
          world.current?.navigate(center, zoom, bearing, pitch);
      },
      overview: (points) => {
        if (props.kind === "world") world.current?.overview(points);
        else active3d()?.reset();
      },
      reset: () =>
        props.kind === "world" ? world.current?.reset() : active3d()?.reset(),
      zoom: (factor) =>
        props.kind === "world"
          ? world.current?.zoom(factor)
          : active3d()?.zoom(factor),
      focus: (point) =>
        props.kind === "world"
          ? world.current?.focus(point)
          : active3d()?.focus(point),
      flyTo: (point: LngLat) => world.current?.flyTo(point),
      showWindRegion: () => world.current?.showWindRegion(),
      retry: () => world.current?.retry(),
      applyTerrain: (patch) => {
        if (props.kind === "world" && world.current)
          return world.current.applyTerrain(patch);
        const target = active3d();
        if (target) return target.applyTerrain(patch);
        return props.terrainModel.apply(patch);
      },
    }),
    [props.kind, props.terrainModel],
  );
  if (props.kind === "shenzhen")
    return (
      <Suspense
        fallback={
          <div className="map-loading">加载深圳 10× 城市级三维景观…</div>
        }
      >
        <ShenzhenScene
          ref={shenzhen}
          variant="workspace"
          mode={props.mode}
          layers={props.layers}
          progress={props.progress}
          playing={props.playing && !props.reducedMotion}
          onReady={props.onReady}
          onError={props.onError}
          onApplyTerrain={(patch) => props.terrainModel.apply(patch)}
        />
      </Suspense>
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
