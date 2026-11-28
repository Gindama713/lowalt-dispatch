import { test, expect } from "./fixtures";
import { createHash, randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

function routeBbox(
  origin: [number, number],
  destination: [number, number],
  marginM = 1000,
): [number, number, number, number] {
  const dy = marginM / 111_000.0;
  const maxLat = Math.max(Math.abs(origin[1]), Math.abs(destination[1])) + dy;
  const dx = marginM / (111_000.0 * Math.cos((maxLat * Math.PI) / 180));
  const raw: [number, number, number, number] = [
    Math.min(origin[0], destination[0]) - dx,
    Math.min(origin[1], destination[1]) - dy,
    Math.max(origin[0], destination[0]) + dx,
    Math.max(origin[1], destination[1]) + dy,
  ];
  return [
    Math.floor(raw[0] * 1e6) / 1e6,
    Math.floor(raw[1] * 1e6) / 1e6,
    Math.ceil(raw[2] * 1e6) / 1e6,
    Math.ceil(raw[3] * 1e6) / 1e6,
  ];
}

function seedDeterministicOsmScene(
  cacheRoot: string,
  origin: [number, number],
  destination: [number, number],
) {
  const bbox = routeBbox(origin, destination, 1000);
  const sceneId = createHash("sha256")
    .update(JSON.stringify(bbox))
    .digest("hex")
    .slice(0, 16);
  const dir = resolve(cacheRoot, sceneId);
  mkdirSync(dir, { recursive: true });
  const nowIso = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  const expiresIso = new Date(Date.now() + 24 * 3600_000)
    .toISOString()
    .replace(/\.\d{3}Z$/, "Z");

  // One small off-corridor building + one reference road so both GPU layers render cleanly.
  const bldgFeature = {
    type: "Feature",
    properties: {
      id: "way/900001",
      source: "OpenStreetMap / Overpass",
      fetched_at: nowIso,
      height_m: 18,
      height_source: "tag",
      height_estimated: false,
      geometry_status: "osm_polygon",
    },
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [origin[0] + 0.002, origin[1] + 0.003],
          [origin[0] + 0.0026, origin[1] + 0.003],
          [origin[0] + 0.0026, origin[1] + 0.0035],
          [origin[0] + 0.002, origin[1] + 0.0035],
          [origin[0] + 0.002, origin[1] + 0.003],
        ],
      ],
    },
  };
  const roadFeature = {
    type: "Feature",
    properties: {
      id: "way/900002",
      highway: "secondary",
      source: "OpenStreetMap / Overpass",
      fetched_at: nowIso,
    },
    geometry: {
      type: "LineString",
      coordinates: [
        [origin[0], origin[1] - 0.002],
        [destination[0], destination[1] - 0.002],
      ],
    },
  };

  writeFileSync(
    resolve(dir, "obstacles.geojson"),
    JSON.stringify({
      type: "FeatureCollection",
      status: "real",
      crs: "EPSG:4326",
      bbox,
      fetched_at: nowIso,
      coverage_status: "complete",
      pass_allowed: false,
      features: [bldgFeature],
    }),
    "utf8",
  );
  writeFileSync(
    resolve(dir, "roads.geojson"),
    JSON.stringify({
      type: "FeatureCollection",
      status: "real",
      crs: "EPSG:4326",
      bbox,
      fetched_at: nowIso,
      coverage_status: "complete",
      pass_allowed: false,
      features: [roadFeature],
    }),
    "utf8",
  );
  writeFileSync(
    resolve(dir, "metadata.json"),
    JSON.stringify({
      schema_version: 1,
      scene_id: sceneId,
      source: "OpenStreetMap / Overpass (deterministic local test cache)",
      attribution: "© OpenStreetMap contributors; ODbL 1.0",
      bbox,
      fetched_at: nowIso,
      source_fetched_at: nowIso,
      expires_at: expiresIso,
      building_count: 1,
      road_count: 1,
      coverage_status: "complete",
      pass_allowed: false,
      warnings: ["测试缓存场景：仅用于确定性回归验证，不代表获准飞行。"],
    }),
    "utf8",
  );
  return sceneId;
}

test("full mission -> conflict -> hidden-layer replan detour -> agent audit -> export -> reload consistency & legacy badge", async ({
  page,
  context,
}) => {
  const runtimeDir = process.env.AERIS_TEST_RUNTIME_DIR;
  expect(
    runtimeDir,
    "AERIS_TEST_RUNTIME_DIR must be set for E2E cache seeding",
  ).toBeTruthy();

  await page.route("https://basemaps.cartocdn.com/**", (r) =>
    r.fulfill({
      json: {
        version: 8,
        sources: {},
        layers: [
          {
            id: "bg",
            type: "background",
            paint: { "background-color": "#101c2d" },
          },
        ],
      },
    }),
  );
  await page.route("https://api.open-meteo.com/**", (r) =>
    r.abort("blockedbyclient"),
  );

  const origin: [number, number] = [115.83, 28.7];
  const destination: [number, number] = [115.85, 28.7];
  seedDeterministicOsmScene(
    resolve(runtimeDir!, "osm_cache"),
    origin,
    destination,
  );

  // 1. Seed a legacy building-only intake on disk (no constraint_snapshot) and verify honest legacy label!
  const legacyId = "legacy-building-only-001";
  mkdirSync(resolve(runtimeDir!, "intakes"), { recursive: true });
  writeFileSync(
    resolve(runtimeDir!, "intakes", `${legacyId}.json`),
    JSON.stringify({
      intake_id: legacyId,
      text: "历史遗留建筑避障工单",
      origin: {
        name: "南昌测试西站",
        point: origin,
        crs: "EPSG:4326",
        source: "test",
        address: "",
        is_simulated: false,
      },
      destination: {
        name: "南昌测试东站",
        point: destination,
        crs: "EPSG:4326",
        source: "test",
        address: "",
        is_simulated: false,
      },
      scheduled_for: "2026-11-20T09:00:00+08:00",
      schedule_note: "",
      payload_kg: 1.5,
      priority: "P2",
      weather: { status: "unavailable", kind: "forecast", values: {} },
      airspace: { status: "draft", note: "旧记录", zones: [] },
      route_preview: null,
      real_route: {
        status: "ok",
        frame: "WGS84",
        route_id: "real-legacy-v0",
        waypoints: [
          { x: origin[0], y: origin[1], lng: origin[0], lat: origin[1] },
          {
            x: destination[0],
            y: destination[1],
            lng: destination[0],
            lat: destination[1],
          },
        ],
        length_m: 1955.0,
      },
      warnings: [],
      created_at: "2026-11-19T00:00:00Z",
      is_simulated: true,
      dispatch_enabled: false,
    }),
    "utf8",
  );

  await page.goto(`/airspace?intake=${legacyId}`);
  const panel = page.getByTestId("real-routing");
  await expect(panel.getByTestId("legacy-airspace-badge")).toContainText(
    "历史建筑避障结果，空域未核对",
  );

  // 2. Create a brand-new AI intake via the real BFF turn endpoint + compute initial route v1!
  const turnResp = await context.request.post("/api/assistant/turn", {
    headers: { "X-Aeris-Request": "1", "Content-Type": "application/json" },
    data: {
      request_id: randomUUID(),
      text: "确认创建南昌配送任务",
      history: [],
      context: {
        is_simulated: true,
        sampled_at: new Date().toISOString(),
        progress: 0,
        telemetry_mode: "planning",
        telemetry: null,
        events: [],
      },
      confirmation: {
        confirmation_id: randomUUID(),
        text: "从南昌起点配送医疗包到南昌终点",
        origin: "南昌起点",
        destination: "南昌终点",
        origin_point: origin,
        destination_point: destination,
        scheduled_for: "2026-11-20T09:00:00+08:00",
        payload_kg: 2.0,
        priority: "P1",
      },
    },
  });
  expect(turnResp.ok()).toBeTruthy();
  const ndjsonLines = (await turnResp.text())
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line));
  const createdTrace = ndjsonLines.find(
    (p) => p.type === "tool_result" && p.trace?.name === "create_task_intake",
  );
  const intakeId: string = createdTrace.trace.result.intake_id;
  expect(intakeId).toBeTruthy();

  // Wait briefly for background v1 route to finish against cached local OSM scene.
  await expect
    .poll(
      async () => {
        const res = await context.request.get(
          `/api/assistant/intakes/${intakeId}`,
        );
        const body = await res.json();
        return body.real_route?.status;
      },
      { timeout: 15_000 },
    )
    .toBe("ok");

  // 3. Open the newly created intake on /airspace?intake=... -> view original route v1
  await page.goto(`/airspace?intake=${intakeId}`);
  await expect(panel.getByTestId("geometric-status-line")).toContainText(
    "几何生成（v1）：几何 A* · 2 个 WGS84 航点",
  );
  await expect(panel.getByTestId("airspace-check-summary")).toContainText(
    "未导入空域区域",
  );

  // 4. Click 1-click corridor restriction zone generator -> flags v1 conflict in RED!
  await panel.getByTestId("simulate-corridor-zone").click();
  await expect(page.locator(".geo-airspace-label")).toHaveCount(1);
  await expect(page.locator(".geo-airspace-label")).toContainText("演练");
  await expect(panel.getByTestId("airspace-stale-banner")).toContainText(
    "原路线 v1 与最新限制区冲突",
  );
  await expect(panel.getByTestId("conflict-segment-list")).toContainText(
    "红色冲突段 #1",
  );
  await expect(page.locator(".geo-map")).toHaveAttribute(
    "data-real-conflict-segments",
    "1",
  );

  // 5. Hide restriction layer on map -> verify hiding layer only hides visual marker, NEVER cancels avoidance!
  await page.getByRole("button", { name: "地图图层" }).click();
  await page
    .locator(".layer-menu")
    .first()
    .getByRole("button", { name: "限制区" })
    .click();
  await expect(page.locator(".geo-airspace-label")).toBeHidden();
  await page.getByRole("button", { name: "地图图层" }).click();

  // Re-plan while map restriction layer is hidden -> must still detour around the restricted zone!
  await panel.getByRole("button", { name: "按当前约束重新规划" }).click();
  await expect(panel.getByTestId("route-version-comparison")).toContainText(
    "路线版本对比：v1 → v2",
  );
  await expect(panel.getByTestId("airspace-check-summary")).toContainText(
    "通过本次已知区域检查",
  );
  await expect(panel.getByTestId("airspace-check-summary")).toContainText(
    "纳入避让：1 个禁飞/内部管制区",
  );
  // v2 genuinely detoured (> 2 waypoints), and v1's conflicting segment remains highlighted in RED for comparison!
  const v2StatusText = await panel
    .getByTestId("geometric-status-line")
    .textContent();
  const wpMatch = v2StatusText?.match(/(\d+) 个 WGS84 航点/);
  expect(Number(wpMatch?.[1] ?? "0")).toBeGreaterThanOrEqual(4);
  await expect(page.locator(".geo-map")).toHaveAttribute(
    "data-real-conflict-segments",
    "1",
  );

  // Read bound snapshot ID & digest from UI
  const intakeAfterV2 = await (
    await context.request.get(`/api/assistant/intakes/${intakeId}`)
  ).json();
  const expectedSnapshotId: string =
    intakeAfterV2.constraint_snapshot.snapshot_id;
  const expectedDigest: string = intakeAfterV2.constraint_snapshot.digest;
  await expect(panel.getByTestId("bound-snapshot-digest")).toContainText(
    expectedSnapshotId,
  );
  await expect(panel.getByTestId("bound-snapshot-digest")).toContainText(
    expectedDigest.slice(0, 23),
  );

  // 6. Ask Assistant: "有没有考虑禁飞区？" -> must cite exact same snapshot_id & digest!
  await page.getByRole("button", { name: "调度助手 A" }).click();
  const askBox = page.getByLabel("向调度助手提问");
  await askBox.fill("这次规划有没有考虑禁飞区？原路线为什么冲突？");
  await page.getByRole("button", { name: "发送给调度助手" }).click();
  const convo = page.getByLabel("助手对话记录");
  await expect(convo).toContainText(expectedSnapshotId, { timeout: 15_000 });
  await expect(convo).toContainText(expectedDigest);
  await expect(convo).toContainText("通过本次已知区域检查");
  await expect(convo).toContainText("未接入官方 UOM / NOTAM");
  await askBox.fill("综合检查当前工单的禁飞区、天气、风向和备降点");
  await page.getByRole("button", { name: "发送给调度助手" }).click();
  await expect(
    page.getByRole("region", { name: "任务规划与备降依据" }),
  ).toContainText("备降余量");
  await expect(convo).toContainText("风未参与几何寻路");
  await expect(convo).toContainText("未接入官方 UOM/NOTAM");
  await page.getByRole("button", { name: "收起调度助手" }).click();

  // 7. Export JSON from RealRoutingPanel AND Topbar -> verify exact coordinates & snapshot digest match!
  const routeDownloadPromise = page.waitForEvent("download");
  await panel.getByRole("button", { name: "导出航点与来源 JSON" }).click();
  const routeDownload = await routeDownloadPromise;
  const exportedRouteJson = JSON.parse(
    readFileSync((await routeDownload.path())!, "utf8"),
  );
  expect(exportedRouteJson.constraint_snapshot.snapshot_id).toBe(
    expectedSnapshotId,
  );
  expect(exportedRouteJson.constraint_snapshot.digest).toBe(expectedDigest);
  expect(exportedRouteJson.exported_waypoints).toEqual(
    intakeAfterV2.real_route.waypoints.map(
      (p: { lng: number; lat: number }) => [p.lng, p.lat],
    ),
  );

  const snapDownloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出快照" }).click();
  const snapDownload = await snapDownloadPromise;
  const exportedWorkspaceJson = JSON.parse(
    readFileSync((await snapDownload.path())!, "utf8"),
  );
  expect(
    exportedWorkspaceJson.geographic_mission.constraint_snapshot.digest,
  ).toBe(expectedDigest);
  expect(
    exportedWorkspaceJson.geographic_mission.route.waypoints.map(
      (p: { x: number; y: number }) => [p.x, p.y],
    ),
  ).toEqual(exportedRouteJson.exported_waypoints);

  // 8. Reload page -> verify server-persisted snapshot, v2 route, v1->v2 comparison, and digest remain 100% consistent!
  await page.reload();
  await expect(panel.getByTestId("route-version-comparison")).toContainText(
    "路线版本对比：v1 → v2",
  );
  await expect(panel.getByTestId("bound-snapshot-digest")).toContainText(
    expectedSnapshotId,
  );
  await expect(panel.getByTestId("bound-snapshot-digest")).toContainText(
    expectedDigest.slice(0, 23),
  );
  await expect(page.locator(".geo-map")).toHaveAttribute(
    "data-real-conflict-segments",
    "1",
  );
});
