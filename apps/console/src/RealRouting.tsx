import {
  type AirspaceCheckData,
  type AirspaceRegion,
  type ConstraintSnapshotData,
} from "./navigation/airspace";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FeatureCollection } from "geojson";
import {
  distanceMeters,
  validLngLat,
  type GeoMission,
  type LngLat,
} from "./geo";
import { parseRoutes, type NavRoute } from "./navigation/engine";
import "./real-routing.css";
import { useAircraft, type Assessment } from "./aircraft";
import { VehicleAssessment, VehicleSelect } from "./AircraftLibrary";

export type RealScene = {
  obstacles: FeatureCollection;
  roads: FeatureCollection;
};

export type GeometricGeneration = {
  generated: boolean;
  route_id: string | null;
  waypoint_count: number;
  length_m: number | null;
  resolution_requested_m?: number | null;
  resolution_used_m?: number | null;
  continuous_building_clearance_verified?: boolean;
  continuous_zone_clearance_verified?: boolean;
  reason: string | null;
};

export type RoutingResult = {
  status: string;
  route: unknown;
  route_version?: string | null;
  route_changed?: boolean | null;
  synced_intake_id?: string | null;
  scene_id: string | null;
  clearance_m: number | null;
  zone_buffer_m?: number | null;
  grid_clearance_m: number | null;
  resolution_m: number | null;
  elapsed_ms: number | null;
  obstacle_source: string;
  weather_source: string;
  warnings: string[];
  limitation: string;
  alternatives: { reason: string | null }[];
  vehicle_assessment?: Assessment;
  geometric_generation?: GeometricGeneration;
  constraint_snapshot?: ConstraintSnapshotData | null;
  airspace_check?: AirspaceCheckData | null;
  previous_route_check?: AirspaceCheckData | null;
  airspace?: {
    status: string;
    check_status?: string;
    verdict_label?: string;
    snapshot_id?: string;
    snapshot_digest?: string;
    source?: string;
    enforced_ids?: string[];
    zone_buffer_m?: number;
    buffer_source?: string;
    note?: string;
  };
  avoid_regions?: unknown[];
  data: {
    building_count?: number;
    road_count?: number;
    fetched_at?: string;
    attribution?: string;
  };
  weather: {
    status: string;
    scheduled_for?: string;
    energy?: {
      status: string;
      reason?: string;
      duration_s?: number;
      energy_wh?: number;
      remaining_after_reserve_wh?: number;
    };
    warnings?: string[];
    samples?: {
      at: string;
      valid_for?: string;
      status: string;
      values: Record<string, number | null>;
    }[];
  };
};

export type ArchivedRouteVersion = {
  version_index?: number;
  version_label: string;
  route_id?: string | null;
  waypoints?: { x?: number; y?: number; lng?: number; lat?: number }[];
  length_m?: number | null;
  original_snapshot_id?: string | null;
  original_snapshot_digest?: string | null;
  rechecked_against_snapshot_id?: string | null;
  rechecked_against_snapshot_digest?: string | null;
  rechecked_airspace_check?: AirspaceCheckData | null;
};

export type StoredRealRoute = {
  status?: string;
  version_index?: number;
  version_label?: string;
  route_id?: string;
  route?: unknown;
  route_changed?: boolean | null;
  planning_result?: RoutingResult;
  constraint_snapshot?: ConstraintSnapshotData | null;
  airspace_check?: AirspaceCheckData | null;
  previous_route_check?: AirspaceCheckData | null;
  scene_id?: string | null;
  waypoints?: { x?: number; y?: number; lng?: number; lat?: number }[];
  length_m?: number | null;
  clearance_m?: number | null;
  zone_buffer_m?: number | null;
  resolution_used_m?: number | null;
  obstacle_source?: string | null;
  warnings?: string[];
  note?: string | null;
};

export type PreviousRouteComparison = {
  versionLabel: string;
  routeId: string | null;
  waypoints: LngLat[];
  lengthM: number | null;
  recheck: AirspaceCheckData | null;
};

export function extractConflictSegments(
  waypoints: LngLat[],
  check: AirspaceCheckData | null | undefined,
): [LngLat, LngLat][] {
  if (!check || !Array.isArray(check.conflicting_segment_indices)) return [];
  const pairs: [LngLat, LngLat][] = [];
  for (const idx of check.conflicting_segment_indices) {
    if (idx >= 0 && idx + 1 < waypoints.length) {
      pairs.push([waypoints[idx], waypoints[idx + 1]]);
    }
  }
  if (!pairs.length && Array.isArray(check.conflicts)) {
    for (const item of check.conflicts) {
      if (item.segment_start && item.segment_end) {
        pairs.push([item.segment_start, item.segment_end]);
      }
    }
  }
  return pairs;
}

export function restoredRoute(stored: StoredRealRoute): NavRoute {
  return parseRoutes(
    stored.route ?? {
      id: stored.route_id || "restored-intake-route",
      title: "工单保存的真实几何路线",
      source: stored.obstacle_source || "历史工单；建筑来源待核对",
      frame: "WGS84",
      is_simulated: false,
      waypoints: stored.waypoints?.map((p) => ({
        x: p.x ?? p.lng,
        y: p.y ?? p.lat,
      })),
    },
  )[0];
}

export function useRealRouting(
  mission: GeoMission,
  onReady: (route: NavRoute) => void,
  regions: AirspaceRegion[],
  activeSnapshot: ConstraintSnapshotData | null = null,
  selectedIntakeId: string | null = null,
) {
  const aircraft = useAircraft();
  const regionRef = useRef(regions);
  regionRef.current = regions;
  const snapshotRef = useRef(activeSnapshot);
  snapshotRef.current = activeSnapshot;
  const intakeRef = useRef(selectedIntakeId);
  intakeRef.current = selectedIntakeId;

  const [payloadKg, setPayloadKg] = useState("");
  const [zoneBufferM, setZoneBufferM] = useState("0");
  const bufferRef = useRef(zoneBufferM);
  bufferRef.current = zoneBufferM;

  const selectionRef = useRef(aircraft.selection);
  selectionRef.current = aircraft.selection;
  const payloadRef = useRef(payloadKg);
  payloadRef.current = payloadKg;
  const [queriedVehicle, setQueriedVehicle] = useState("");
  const selectionKey = JSON.stringify([aircraft.selection, payloadKg]);

  const [result, setResult] = useState<RoutingResult | null>(null);
  const [route, setRoute] = useState<NavRoute | null>(null);
  const [routeVersion, setRouteVersion] = useState<string>("v1");
  const [previousComparison, setPreviousComparison] =
    useState<PreviousRouteComparison | null>(null);
  const [showComparison, setShowComparison] = useState(true);
  const [liveRecheck, setLiveRecheck] = useState<AirspaceCheckData | null>(
    null,
  );
  const [scene, setScene] = useState<RealScene | null>(null);
  const [queriedSchedule, setQueriedSchedule] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const abort = useRef<AbortController | null>(null);
  const skipClear = useRef<string | null>(null);

  const routeRef = useRef(route);
  routeRef.current = route;
  const resultRef = useRef(result);
  resultRef.current = result;
  const versionRef = useRef(routeVersion);
  versionRef.current = routeVersion;
  const liveRecheckRef = useRef(liveRecheck);
  liveRecheckRef.current = liveRecheck;

  // Clear route ONLY when mission endpoints actually change — NEVER wipe an existing
  // route when restriction zones change, so conflicts can be inspected and compared!
  const endpointKey = JSON.stringify([
    mission.origin?.point,
    mission.destination?.point,
  ]);
  useEffect(() => {
    if (skipClear.current === endpointKey) {
      skipClear.current = null;
      return;
    }
    skipClear.current = null;
    abort.current?.abort();
    abort.current = null;
    setResult(null);
    setRoute(null);
    setRouteVersion("v1");
    setPreviousComparison(null);
    setLiveRecheck(null);
    setScene(null);
    setQueriedSchedule(null);
    setBusy(false);
    setError("");
  }, [endpointKey]);

  useEffect(
    () => () => {
      abort.current?.abort();
    },
    [],
  );

  const boundSnapshot = result?.constraint_snapshot ?? null;
  const isLegacyUnchecked = Boolean(
    result &&
      !boundSnapshot &&
      result.airspace_check?.status === "not_checked_legacy",
  );
  const activeDigest = activeSnapshot?.digest ?? null;
  const boundDigest = boundSnapshot?.digest ?? null;
  const workspaceHasRegions =
    Boolean(activeSnapshot && activeSnapshot.source_status !== "not_loaded") ||
    regions.length > 0;
  const bufferNumeric = Number.isFinite(Number(zoneBufferM))
    ? Math.max(0, Math.min(500, Number(zoneBufferM)))
    : 0;
  const bufferChanged =
    boundSnapshot != null &&
    Math.abs((boundSnapshot.zone_buffer_m ?? 0) - bufferNumeric) > 1e-6;

  const snapshotStale = Boolean(
    route &&
      ((boundDigest && activeDigest && boundDigest !== activeDigest) ||
        (boundDigest &&
          !activeDigest &&
          boundSnapshot?.source_status !== "not_loaded") ||
        (!boundDigest && workspaceHasRegions) ||
        bufferChanged),
  );

  // Whenever the workspace constraint snapshot changes while a route is displayed,
  // run the server-side continuous polyline check immediately without wiping the route.
  useEffect(() => {
    if (!route || !snapshotStale) {
      setLiveRecheck(null);
      return;
    }
    const pts = route.waypoints.map((p) => [p.x, p.y]);
    if (pts.length < 2) return;
    const controller = new AbortController();
    fetch("/api/assistant/airspace/check", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Aeris-Request": "1",
      },
      signal: controller.signal,
      body: JSON.stringify({
        waypoints: pts,
        snapshot_id: activeSnapshot?.snapshot_id ?? null,
        scheduled_for: queriedSchedule,
      }),
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: AirspaceCheckData | null) => {
        if (!controller.signal.aborted && data) {
          setLiveRecheck(data);
        }
      })
      .catch(() => {
        /* Mocked adapter tests without /airspace/check still mark snapshotStale. */
      });
    return () => controller.abort();
  }, [
    route,
    snapshotStale,
    activeSnapshot?.snapshot_id,
    activeSnapshot?.digest,
    queriedSchedule,
  ]);

  const compute = useCallback(
    async (
      points: GeoMission,
      scheduledFor: string | null = null,
      intakePayload?: number | null,
    ) => {
      if (!points.origin || !points.destination) return;
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      const timer = window.setTimeout(() => controller.abort(), 180_000);

      const priorRoute = routeRef.current;
      const priorResult = resultRef.current;
      const priorWaypoints: LngLat[] | null =
        priorRoute && priorRoute.waypoints.length >= 2
          ? priorRoute.waypoints.map((p) => [p.x, p.y])
          : null;
      const priorLength =
        (priorResult?.route as { length_m?: number } | null)?.length_m ?? null;
      const priorLabel = versionRef.current || "v1";
      const priorLiveCheck = liveRecheckRef.current;

      setBusy(true);
      setError("");
      const selection = selectionRef.current;
      const payloadText =
        intakePayload == null ? payloadRef.current : String(intakePayload);
      if (intakePayload != null) setPayloadKg(payloadText);
      const parsedBuf = Number(bufferRef.current);
      const safeBuffer =
        Number.isFinite(parsedBuf) && parsedBuf >= 0 && parsedBuf <= 500
          ? parsedBuf
          : 0;
      const vehicleKey = JSON.stringify([selection, payloadText]);
      try {
        const [lng, lat] = points.origin.point;
        const [endLng, endLat] = points.destination.point;
        const response = await fetch("/api/assistant/navigation/candidates", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Aeris-Request": "1",
          },
          signal: controller.signal,
          body: JSON.stringify({
            frame: "WGS84",
            origin: { lng, lat },
            destination: { lng: endLng, lat: endLat },
            scheduled_for: scheduledFor,
            snapshot_id: snapshotRef.current?.snapshot_id ?? null,
            include_flysafe: true,
            zone_buffer_m: safeBuffer,
            intake_id: intakeRef.current ?? null,
            previous_waypoints: priorWaypoints,
            avoid_regions: regionRef.current
              .filter((r) => r.kind === "restricted" || r.kind === "internal")
              .map((r) => ({
                id: r.id,
                name: r.name,
                kind: r.kind,
                geometry: r.geometry,
                source: r.source,
                source_ref: r.source_ref,
                source_kind: r.source_kind,
                is_simulated: r.is_simulated,
                updated_at: r.updated_at,
                fetched_at: r.fetched_at ?? r.updated_at,
                effective_from: r.effective_from,
                effective_until: r.effective_until,
                altitude_ref: r.altitude_ref,
                max_height_m: r.max_height_m,
                description: r.description,
              })),
            ...selection,
            payload_kg: payloadText.trim() ? Number(payloadText) : null,
          }),
        });
        const payload: RoutingResult = await response.json();
        if (!response.ok) {
          const detail = (
            payload as unknown as { detail?: { reason?: string } | string }
          ).detail;
          throw new Error(
            (typeof detail === "object" && detail?.reason) ||
              (typeof detail === "string" ? detail : "真实航线计算失败"),
          );
        }
        if (controller.signal.aborted) return;
        setQueriedSchedule(scheduledFor);
        setQueriedVehicle(vehicleKey);
        setLiveRecheck(null);

        const nextVerNum =
          priorWaypoints != null
            ? Number(priorLabel.replace(/^v/i, "") || "1") + 1
            : 1;
        const nextVersionLabel =
          payload.route_version || (priorWaypoints ? `v${nextVerNum}` : "v1");
        setRouteVersion(nextVersionLabel);

        if (priorWaypoints && priorRoute) {
          setPreviousComparison({
            versionLabel: priorLabel,
            routeId: priorRoute.id,
            waypoints: priorWaypoints,
            lengthM: priorLength,
            recheck: payload.previous_route_check ?? priorLiveCheck ?? null,
          });
          setShowComparison(true);
        }

        setResult(payload);
        if (!payload.route) {
          setRoute(null);
        } else {
          const parsed = parseRoutes(payload.route)[0];
          if (
            parsed.frame !== "WGS84" ||
            !parsed.waypoints.every((p) => validLngLat([p.x, p.y]))
          )
            throw new Error("服务返回的真实航线坐标无效");
          if (!payload.scene_id) {
            setRoute(parsed);
            onReady(parsed);
          }
        }
        if (payload.scene_id) {
          const data = await fetch(
            `/api/assistant/navigation/scenes/${encodeURIComponent(payload.scene_id)}`,
            { signal: controller.signal },
          );
          if (!data.ok)
            throw new Error(
              "航线已计算，但同一批建筑和道路快照加载失败，请重试",
            );
          const snapshot = await data.json();
          if (!controller.signal.aborted) {
            setScene(snapshot);
            if (payload.route) {
              const parsed = parseRoutes(payload.route)[0];
              setRoute(parsed);
              onReady(parsed);
            }
          }
        }
      } catch (e) {
        if (abort.current === controller) {
          setResult(null);
          setRoute(null);
          setScene(null);
          setError(
            e instanceof Error && e.name !== "AbortError"
              ? e.message
              : "真实数据获取或规划已取消／超时，请重试",
          );
        }
      } finally {
        window.clearTimeout(timer);
        if (abort.current === controller) setBusy(false);
      }
    },
    [onReady],
  );

  /**
   * Paint a route that was already computed and stored with the intake,
   * preserving its bound ConstraintSnapshot, legacy status, and prior conflict history.
   */
  const hydrate = useCallback(
    (
      stored: StoredRealRoute,
      scheduledFor: string | null = null,
      intakePayload?: number | null,
      expected?: GeoMission,
      intakeConstraintSnapshot?: ConstraintSnapshotData | null,
      intakeAirspaceCheck?: AirspaceCheckData | null,
      routeHistory?: ArchivedRouteVersion[],
    ) => {
      if (
        stored.status !== "ok" ||
        (!stored.waypoints?.length && !stored.route)
      )
        return false;
      let parsed: NavRoute;
      try {
        parsed = restoredRoute(stored);
      } catch (e) {
        setError(e instanceof Error ? e.message : "工单航线格式无效");
        return false;
      }
      if (parsed.frame !== "WGS84") return false;
      const first: LngLat = [parsed.waypoints[0].x, parsed.waypoints[0].y];
      const last: LngLat = [
        parsed.waypoints[parsed.waypoints.length - 1].x,
        parsed.waypoints[parsed.waypoints.length - 1].y,
      ];
      if (
        expected?.origin &&
        expected.destination &&
        (distanceMeters(first, expected.origin.point) > 1 ||
          distanceMeters(last, expected.destination.point) > 1)
      ) {
        setError("工单航线与起终点不一致，请重新计算");
        return false;
      }
      abort.current?.abort();
      abort.current = null;
      skipClear.current = JSON.stringify([
        expected?.origin?.point ?? first,
        expected?.destination?.point ?? last,
      ]);
      const controller = new AbortController();
      abort.current = controller;
      setScene(null);
      setRoute(null);
      setResult(null);
      setLiveRecheck(null);
      setError("");
      setQueriedSchedule(scheduledFor);

      const resolvedSnapshot =
        intakeConstraintSnapshot ??
        stored.constraint_snapshot ??
        stored.planning_result?.constraint_snapshot ??
        null;
      if (resolvedSnapshot?.zone_buffer_m != null) {
        setZoneBufferM(String(resolvedSnapshot.zone_buffer_m));
      }
      const resolvedCheck: AirspaceCheckData =
        intakeAirspaceCheck ??
        stored.airspace_check ??
        stored.planning_result?.airspace_check ??
        (resolvedSnapshot
          ? {
              status:
                resolvedSnapshot.source_status === "not_loaded"
                  ? "snapshot_not_loaded"
                  : "passed_known_snapshot",
              passed_known_snapshot:
                resolvedSnapshot.source_status === "not_loaded" ? null : true,
              operationally_approved: false,
              verdict_label:
                resolvedSnapshot.source_status === "not_loaded"
                  ? "未导入空域区域（空域未核对，非通过）"
                  : "通过本次已知区域检查（非官方空域许可）",
              snapshot_id: resolvedSnapshot.snapshot_id,
              snapshot_digest: resolvedSnapshot.digest,
              crs: "EPSG:4326",
              enforced_zone_count: resolvedSnapshot.enforced_zone_count,
              total_zone_count: resolvedSnapshot.total_zone_count,
              enforced_zone_ids: resolvedSnapshot.enforced_zone_ids,
              zone_buffer_m: resolvedSnapshot.zone_buffer_m,
              conflicts: [],
              conflicting_zone_ids: [],
              conflicting_segment_indices: [],
              gaps: ["未接入官方 UOM / NOTAM 实时管制数据"],
            }
          : {
              status: "not_checked_legacy",
              passed_known_snapshot: null,
              operationally_approved: false,
              verdict_label: "历史建筑避障结果，空域未核对",
              snapshot_id: null,
              snapshot_digest: null,
              crs: "EPSG:4326",
              enforced_zone_count: 0,
              total_zone_count: 0,
              enforced_zone_ids: [],
              zone_buffer_m: null,
              conflicts: [],
              conflicting_zone_ids: [],
              conflicting_segment_indices: [],
              gaps: [
                "历史工单未保存空域约束快照，仅包含建筑避障结果，须重新计算核对",
                "未接入官方 UOM / NOTAM 实时管制数据",
              ],
            });

      setRouteVersion(
        stored.version_label ||
          (routeHistory && routeHistory.length
            ? `v${routeHistory.length + 1}`
            : "v1"),
      );
      const lastArchived =
        routeHistory && routeHistory.length
          ? routeHistory[routeHistory.length - 1]
          : null;
      if (lastArchived && lastArchived.waypoints?.length) {
        const prevPts: LngLat[] = lastArchived.waypoints
          .map((p) => [p.lng ?? p.x ?? 0, p.lat ?? p.y ?? 0] as LngLat)
          .filter((p) => validLngLat(p));
        if (prevPts.length >= 2) {
          setPreviousComparison({
            versionLabel: lastArchived.version_label || "v1",
            routeId: lastArchived.route_id ?? null,
            waypoints: prevPts,
            lengthM: lastArchived.length_m ?? null,
            recheck:
              lastArchived.rechecked_airspace_check ??
              stored.previous_route_check ??
              null,
          });
          setShowComparison(true);
        } else {
          setPreviousComparison(null);
        }
      } else {
        setPreviousComparison(null);
      }

      const sceneId = stored.scene_id ?? stored.planning_result?.scene_id;
      const legacyScene = !sceneId;
      if (intakePayload != null) setPayloadKg(String(intakePayload));
      setQueriedVehicle("");

      const basePayload: RoutingResult = stored.planning_result
        ? {
            ...stored.planning_result,
            route_changed:
              stored.route_changed ?? stored.planning_result.route_changed,
            constraint_snapshot: resolvedSnapshot,
            airspace_check: resolvedCheck,
            previous_route_check:
              lastArchived?.rechecked_airspace_check ??
              stored.previous_route_check ??
              stored.planning_result.previous_route_check ??
              null,
          }
        : {
            status: "ok",
            route: parsed,
            route_changed: stored.route_changed ?? null,
            scene_id: sceneId ?? null,
            clearance_m: stored.clearance_m ?? null,
            zone_buffer_m: resolvedSnapshot?.zone_buffer_m ?? null,
            grid_clearance_m: null,
            resolution_m: stored.resolution_used_m ?? null,
            elapsed_ms: null,
            obstacle_source: stored.obstacle_source ?? "历史来源待核对",
            weather_source: "",
            constraint_snapshot: resolvedSnapshot,
            airspace_check: resolvedCheck,
            previous_route_check:
              lastArchived?.rechecked_airspace_check ??
              stored.previous_route_check ??
              null,
            warnings: [
              ...(stored.warnings ?? []),
              ...(legacyScene
                ? [
                    "历史工单未保存对应建筑快照；仅恢复航点，请重新计算以核对环境。",
                  ]
                : []),
              ...(!resolvedSnapshot
                ? [
                    "历史建筑避障结果，空域未核对；请点击重新计算绑定当前空域快照。",
                  ]
                : []),
            ],
            limitation: stored.note ?? "",
            alternatives: [],
            data: {},
            weather: { status: "unavailable" },
          };

      const publish = (snapshot: RealScene | null) => {
        if (controller.signal.aborted) return;
        setScene(snapshot);
        setResult(basePayload);
        setRoute(parsed);
        setBusy(false);
        onReady(parsed);
      };
      if (!sceneId) {
        setBusy(false);
        publish(null);
      } else {
        setBusy(true);
        const timer = window.setTimeout(() => controller.abort(), 30_000);
        fetch(
          `/api/assistant/navigation/scenes/${encodeURIComponent(sceneId)}`,
          { signal: controller.signal },
        )
          .then(async (response) => {
            if (!response.ok)
              throw new Error("工单建筑快照不可用或过期，请重新计算航线");
            return response.json();
          })
          .then(publish)
          .catch((err) => {
            if (abort.current === controller) {
              // Still restore the route & constraint check even if the 24h OSM scene cache expired.
              setScene(null);
              setResult(basePayload);
              setRoute(parsed);
              setError(
                err instanceof Error ? err.message : "工单建筑快照恢复失败",
              );
              setBusy(false);
              onReady(parsed);
            }
          })
          .finally(() => window.clearTimeout(timer));
      }
      return true;
    },
    [onReady],
  );

  const mapConflictSegments = useMemo<[LngLat, LngLat][]>(() => {
    if (snapshotStale && route && liveRecheck?.status === "conflict") {
      const pts: LngLat[] = route.waypoints.map((p) => [p.x, p.y]);
      return extractConflictSegments(pts, liveRecheck);
    }
    if (
      !snapshotStale &&
      showComparison &&
      previousComparison?.recheck?.status === "conflict"
    ) {
      return extractConflictSegments(
        previousComparison.waypoints,
        previousComparison.recheck,
      );
    }
    return [];
  }, [snapshotStale, route, liveRecheck, showComparison, previousComparison]);

  const mapPreviousRoute = useMemo<LngLat[]>(() => {
    if (
      !snapshotStale &&
      showComparison &&
      previousComparison &&
      (previousComparison.recheck?.status === "conflict" ||
        result?.route_changed === true)
    ) {
      return previousComparison.waypoints;
    }
    return [];
  }, [
    snapshotStale,
    showComparison,
    previousComparison,
    result?.route_changed,
  ]);

  return {
    result,
    route,
    routeVersion,
    previousComparison,
    showComparison,
    setShowComparison,
    liveRecheck,
    snapshotStale,
    isLegacyUnchecked,
    mapConflictSegments,
    mapPreviousRoute,
    scene,
    busy,
    error,
    compute,
    hydrate,
    queriedSchedule,
    aircraft,
    payloadKg,
    setPayloadKg,
    zoneBufferM,
    setZoneBufferM,
    clear: () => {
      abort.current?.abort();
      setRoute(null);
      setResult(null);
      setRouteVersion("v1");
      setPreviousComparison(null);
      setLiveRecheck(null);
      setScene(null);
      setBusy(false);
      setError("");
    },
    vehicleChanged: !!queriedVehicle && queriedVehicle !== selectionKey,
    vehicleUnknown: !!route && !queriedVehicle,
  };
}

export function RealRoutingPanel({
  routing,
  mission,
  scheduledFor,
  onSchedule,
  activeSnapshot,
  onAddCorridorZone,
  corridorBusy = false,
  onOpenAirspacePanel,
}: {
  routing: ReturnType<typeof useRealRouting>;
  mission: GeoMission;
  scheduledFor: string | null;
  onSchedule: (value: string | null) => void;
  activeSnapshot?: ConstraintSnapshotData | null;
  onAddCorridorZone?: () => void;
  corridorBusy?: boolean;
  onOpenAirspacePanel?: () => void;
}) {
  const { result, route, error, busy } = routing;
  if (!mission.origin || !mission.destination) return null;
  const points: LngLat[] = route?.waypoints.map((p) => [p.x, p.y]) ?? [];
  const scheduleChanged =
    routing.queriedSchedule === null || scheduledFor === null
      ? routing.queriedSchedule !== scheduledFor
      : Math.abs(
          Date.parse(routing.queriedSchedule) - Date.parse(scheduledFor),
        ) > 1000;

  const boundSnap = result?.constraint_snapshot ?? null;
  const effectiveCheck = routing.snapshotStale
    ? routing.liveRecheck
    : (result?.airspace_check ?? null);
  const enforcedCount =
    boundSnap?.enforced_zone_count ??
    result?.airspace?.enforced_ids?.length ??
    0;
  const snapshotSources = boundSnap?.zones?.length
    ? Array.from(new Set(boundSnap.zones.map((z) => z.source))).join("；")
    : (result?.airspace?.source ?? "未导入区域（官方空域未接入）");

  return (
    <section
      className="real-routing glass"
      aria-label="真实数据航线规划"
      data-testid="real-routing"
    >
      <strong>真实建筑与空域约束规划</strong>
      <p data-testid="flysafe-source-label">
        主数据源：大疆 FlySafe 厂商地理围栏参考。不是法定空域，不是 UOM /
        国家地图官网 /
        天地图，也不是飞行批准。查询失败或空结果表示未知，不是放行。通过检查只表示通过本次已知区域检查。手动导入和演练走廊是附加对照，不是主数据源；隐藏图层不会取消避让。
      </p>
      {activeSnapshot?.failure_reason ? (
        <p role="status" data-testid="flysafe-refresh-note">
          {activeSnapshot.failure_reason}
        </p>
      ) : null}
      <p>
        地点坐标只作定位参考；请在开阔处确认实际起降点。起终点位于建筑或限制区内时会明确拒绝，不会自动移点。
      </p>
      <p>
        {mission.origin.name} → {mission.destination.name}
      </p>
      <VehicleSelect aircraft={routing.aircraft} />
      <a href="/aircraft">查看官方规格 / 管理自定义机型 →</a>
      <label>
        配送载荷 (kg)
        <input
          aria-label="航线配送载荷"
          type="number"
          min="0"
          max="1000"
          step="any"
          placeholder="未填则不判定载荷"
          value={routing.payloadKg}
          onChange={(e) => routing.setPayloadKg(e.target.value)}
        />
      </label>
      <label>
        限制区项目边界缓冲 (m，非民航法定间隔)
        <input
          aria-label="限制区项目边界缓冲"
          type="number"
          min="0"
          max="500"
          step="5"
          value={routing.zoneBufferM}
          onChange={(e) => routing.setZoneBufferM(e.target.value)}
        />
      </label>
      <label>
        起飞时刻（留空查询当前预报）
        <input
          aria-label="真实航线起飞时刻"
          type="datetime-local"
          value={scheduledFor ? localTime(scheduledFor) : ""}
          onChange={(e) =>
            onSchedule(
              e.target.value ? new Date(e.target.value).toISOString() : null,
            )
          }
        />
      </label>
      <button
        disabled={busy}
        onClick={() => void routing.compute(mission, scheduledFor)}
      >
        {busy
          ? "正在获取真实地图并规划…"
          : routing.snapshotStale || routing.isLegacyUnchecked
            ? "按当前约束重新规划"
            : "计算真实避障航线"}
      </button>
      {onAddCorridorZone && (
        <div className="real-routing-inline-actions">
          <button
            type="button"
            disabled={busy || corridorBusy}
            onClick={onAddCorridorZone}
            data-testid="simulate-corridor-zone"
          >
            {corridorBusy
              ? "正在生成演练禁飞区…"
              : "附加演练走廊（不是主数据源）"}
          </button>
          {onOpenAirspacePanel && (
            <button type="button" onClick={onOpenAirspacePanel}>
              管理空域快照
              {activeSnapshot && activeSnapshot.source_status !== "not_loaded"
                ? `（${activeSnapshot.enforced_zone_count}/${activeSnapshot.total_zone_count}）`
                : ""}
            </button>
          )}
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      {result && (
        <>
          {routing.isLegacyUnchecked && !routing.snapshotStale && (
            <div
              className="routing-banner legacy"
              role="status"
              data-testid="legacy-airspace-badge"
            >
              <strong>历史建筑避障结果，空域未核对</strong>
              <p>
                该历史路线缺少服务端空域约束快照，不能默认视为已检查。请点击「按当前约束重新规划」完成核对。
              </p>
            </div>
          )}
          {routing.snapshotStale && (
            <div
              className={`routing-banner ${routing.liveRecheck?.status === "conflict" ? "conflict" : "stale"}`}
              role="alert"
              data-testid="airspace-stale-banner"
            >
              <strong>
                {routing.liveRecheck?.status === "conflict"
                  ? `原路线 ${routing.routeVersion} 与最新限制区冲突（旧结果已失效）`
                  : `空域约束快照已更新（原路线 ${routing.routeVersion} 对应旧版本，需重新规划）`}
              </strong>
              <p>
                当前工作区快照：
                <code>{activeSnapshot?.snapshot_id ?? "未载入"}</code>
                {activeSnapshot?.digest
                  ? `（${activeSnapshot.digest.slice(0, 19)}…）`
                  : ""}
              </p>
              {routing.liveRecheck?.conflicts?.length ? (
                <ul data-testid="conflict-segment-list">
                  {routing.liveRecheck.conflicts.slice(0, 4).map((c, idx) => (
                    <li key={`${c.zone_id}-${c.segment_index}-${idx}`}>
                      红色冲突段 #{c.segment_number}：{c.reason}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>
                  区域新增、删除或修改后，旧结果不再显示为当前已核对结果。请点击上方「按当前约束重新规划」。
                </p>
              )}
            </div>
          )}
          {!routing.snapshotStale && routing.previousComparison && (
            <div
              className="routing-banner comparison"
              role="status"
              data-testid="route-version-comparison"
            >
              <strong>
                路线版本对比：{routing.previousComparison.versionLabel} →{" "}
                {routing.routeVersion}
              </strong>
              <p>
                {routing.previousComparison.recheck?.status === "conflict"
                  ? `原路线 ${routing.previousComparison.versionLabel} 在当前快照下判为冲突（红色标出第 ${routing.previousComparison.recheck.conflicting_segment_indices.map((i) => i + 1).join("、")} 航段，涉及 ${routing.previousComparison.recheck.conflicting_zone_ids.join("、")}）。`
                  : `原路线 ${routing.previousComparison.versionLabel} 已归档为历史版本。`}
              </p>
              <p>
                {route
                  ? result.route_changed === false
                    ? "本次重算后路线几何未发生绕行变化（原走廊未受新限制区阻断）。"
                    : `新路线 ${routing.routeVersion}（主色）已按最新约束重新生成${routing.previousComparison.lengthM != null && (result.route as { length_m?: number } | null)?.length_m != null ? `：${(routing.previousComparison.lengthM / 1000).toFixed(2)} km → ${(((result.route as { length_m: number }).length_m ?? 0) / 1000).toFixed(2)} km` : ""}。`
                  : "当前约束下未找到可行绕行路线，未使用直线替代。"}
              </p>
              {(routing.previousComparison.recheck?.status === "conflict" ||
                result.route_changed === true) && (
                <button
                  type="button"
                  onClick={() =>
                    routing.setShowComparison(!routing.showComparison)
                  }
                >
                  {routing.showComparison
                    ? "隐藏地图原冲突路线对比"
                    : "在地图显示原冲突路线（红段）对比"}
                </button>
              )}
            </div>
          )}
          {result.weather.scheduled_for && (
            <p>
              本次预报时刻：
              {new Date(result.weather.scheduled_for).toLocaleString("zh-CN")}
              （本地时间）
            </p>
          )}
          {scheduleChanged && (
            <p role="alert">
              起飞时刻已更改，请重新计算；下方结果仍对应上次查询时刻。
            </p>
          )}
          {routing.vehicleUnknown && (
            <p role="status">
              历史工单未绑定当前选择的机型参数；请核对后重新计算。
            </p>
          )}
          {routing.vehicleChanged && (
            <p role="alert">
              机型或载荷已更改，请重新计算；下方为上次参数的结果。
            </p>
          )}
          <p data-testid="geometric-status-line">
            {route
              ? `几何生成（${routing.routeVersion}）：几何 A* · ${points.length} 个 WGS84 航点`
              : `几何生成：未找到航线：${result.alternatives[0]?.reason ?? "未知原因"}`}
          </p>
          <p>
            要求水平净空 ≥ {result.clearance_m ?? "—"} m · 网格{" "}
            {result.resolution_m ?? "—"} m · 搜索{" "}
            {result.elapsed_ms == null
              ? "—"
              : (result.elapsed_ms / 1000).toFixed(2)}{" "}
            s
          </p>
          <div
            className="routing-airspace-evidence"
            data-testid="airspace-check-summary"
          >
            <p>
              <strong>空域约束检查：</strong>
              {routing.snapshotStale
                ? "旧版本结果已失效，待按新快照重算"
                : (effectiveCheck?.verdict_label ??
                  (enforcedCount > 0
                    ? "通过本次已知区域检查（非官方空域许可）"
                    : "未导入已知限制区（官方空域未核对，非通过）"))}
            </p>
            <p>
              纳入避让：{enforcedCount}{" "}
              个禁飞/内部管制区（二维全高度保守避让，缓冲{" "}
              {boundSnap?.zone_buffer_m ?? result.zone_buffer_m ?? 0} m ·
              边界接触判冲突）
            </p>
            <p>区域来源：{snapshotSources}</p>
            {boundSnap && (
              <p data-testid="bound-snapshot-digest">
                绑定快照：<code>{boundSnap.snapshot_id}</code> ·{" "}
                <code>{boundSnap.digest.slice(0, 23)}…</code>
              </p>
            )}
            {!routing.snapshotStale &&
              effectiveCheck?.conflicts &&
              effectiveCheck.conflicts.length > 0 && (
                <ul>
                  {effectiveCheck.conflicts.map((c, idx) => (
                    <li key={`${c.zone_id}-${idx}`}>{c.reason}</li>
                  ))}
                </ul>
              )}
          </div>
          {result.airspace?.note && <p>{result.airspace.note}</p>}
          <p>建筑高度：OSM 标签／楼层推算／未知；点击建筑查看来源。</p>
          {result.data.building_count != null && (
            <p>
              本次数据：{result.data.building_count} 栋建筑 ·{" "}
              {result.data.road_count ?? "未知"} 条道路
            </p>
          )}
          <p>
            天气：
            {result.weather.status === "ok"
              ? "已获取模式预报"
              : "预报或性能评估不完整"}{" "}
            · 能耗：
            {result.weather.energy?.status === "user_test"
              ? "用户参数与真实预报的条件测试"
              : result.weather.energy?.status === "conditional"
                ? "已计算机型条件估算，未判定飞行可行"
                : result.weather.energy?.status === "infeasible"
                  ? "风场下无法保持航迹，条件不满足"
                  : "缺少有效数据，未计算"}
          </p>
          {result.vehicle_assessment && (
            <VehicleAssessment value={result.vehicle_assessment} />
          )}
          {result.weather.energy?.energy_wh != null && (
            <p>
              预报风场下条件测试：
              {(result.weather.energy.duration_s! / 60).toFixed(1)} 分钟 ·{" "}
              {result.weather.energy.energy_wh.toFixed(1)} Wh
              {result.weather.energy.remaining_after_reserve_wh != null
                ? ` · 扣除保留量后 ${result.weather.energy.remaining_after_reserve_wh.toFixed(1)} Wh`
                : ""}
              。未含起降、返航与备降。
            </p>
          )}
          {result.weather.samples?.length ? (
            <details>
              <summary>航路天气预报数值</summary>
              <table>
                <thead>
                  <tr>
                    <th>位置</th>
                    <th>风速 m/s</th>
                    <th>温度 °C</th>
                    <th>湿度 %</th>
                  </tr>
                </thead>
                <tbody>
                  {result.weather.samples.map((sample) => (
                    <tr key={sample.at}>
                      <td>
                        {(
                          {
                            origin: "起点",
                            midpoint: "中点",
                            destination: "终点",
                          } as Record<string, string>
                        )[sample.at] ?? sample.at}
                      </td>
                      {[
                        "wind_speed_10m",
                        "temperature_2m",
                        "relative_humidity_2m",
                      ].map((field) => (
                        <td key={field}>
                          {sample.values[field] == null
                            ? "不可用"
                            : sample.values[field]!.toFixed(1)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <small>
                10 m 模式风与 2 m 温湿度，非航高实测。缺失值不补零。
              </small>
            </details>
          ) : null}
          <details>
            <summary>数据来源与限制</summary>
            <p>
              {result.obstacle_source} · {result.weather_source}
            </p>
            <p>{result.limitation}</p>
            {result.data.fetched_at && (
              <p>地图抓取：{result.data.fetched_at}</p>
            )}
            <p>
              ©{" "}
              <a
                href="https://www.openstreetmap.org/copyright"
                target="_blank"
                rel="noreferrer"
              >
                OpenStreetMap contributors · ODbL
              </a>
            </p>
            {effectiveCheck?.gaps?.length ? (
              <ul>
                {effectiveCheck.gaps.map((gap) => (
                  <li key={gap}>空域未判定项：{gap}</li>
                ))}
              </ul>
            ) : null}
            <ul>
              {result.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </details>
          {route && (
            <button
              onClick={() => {
                const exportPayload = {
                  ...result,
                  route_version: routing.routeVersion,
                  exported_waypoints: points,
                  constraint_snapshot: boundSnap,
                  airspace_check: effectiveCheck,
                  snapshot_stale: routing.snapshotStale,
                  previous_version: routing.previousComparison,
                };
                const url = URL.createObjectURL(
                  new Blob([JSON.stringify(exportPayload, null, 2)], {
                    type: "application/json",
                  }),
                );
                const link = document.createElement("a");
                link.href = url;
                link.download = `${route.id}.json`;
                link.click();
                URL.revokeObjectURL(url);
              }}
            >
              导出航点与来源 JSON
            </button>
          )}
        </>
      )}
      <small>
        已知区域几何避让 ≠ 官方 UOM/NOTAM 核验 ≠ 真实飞控执行。未生成飞控指令。
      </small>
    </section>
  );
}

function localTime(value: string) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);
}
