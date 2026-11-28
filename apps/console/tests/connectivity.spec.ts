import { readFile } from "node:fs/promises";
import { expect, test } from "./fixtures";

const route = {
  id: "stored-connectivity",
  title: "保存的路线",
  source: "browser adapter fixture",
  frame: "WGS84",
  is_simulated: false,
  waypoints: [
    { x: 121.46, y: 31.22 },
    { x: 121.47, y: 31.222 },
    { x: 121.48, y: 31.22 },
  ],
};
const intake = {
  intake_id: "connectivity-intake",
  payload_kg: 0.8,
  origin: { name: "保存的起点", point: [121.46, 31.22], crs: "EPSG:4326" },
  destination: { name: "保存的终点", point: [121.48, 31.22], crs: "EPSG:4326" },
  real_route: {
    status: "ok",
    route_id: route.id,
    route,
    waypoints: route.waypoints,
    scene_id: "matching-scene",
    length_m: 1960,
    clearance_m: 20,
    resolution_used_m: 10,
    obstacle_source: route.source,
  },
};

test("imported exclusion reaches the WGS84 planner and invalidates the old route", async ({
  page,
}) => {
  await page.route("https://basemaps.cartocdn.com/**", (r) => r.abort());
  await page.route("**/api/assistant/intakes/connectivity-intake", (r) =>
    r.fulfill({
      json: { ...intake, real_route: { ...intake.real_route, scene_id: null } },
    }),
  );
  await page.goto("/airspace?intake=connectivity-intake&navigation=1");
  await expect(page.getByTestId("real-routing")).toContainText(
    "3 个 WGS84 航点",
  );
  const nav = page.locator(".nav-workspace");
  await nav.getByRole("button", { name: "空域图层", exact: true }).click();
  const region = {
    type: "FeatureCollection",
    coordinate_system: "WGS84",
    features: [
      {
        type: "Feature",
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [121.469, 31.219],
              [121.471, 31.219],
              [121.471, 31.221],
              [121.469, 31.221],
              [121.469, 31.219],
            ],
          ],
        },
        properties: {
          id: "team-exclusion",
          name: "测试管制区",
          kind: "restricted",
          source: "browser fixture",
          source_ref: "test",
          source_kind: "team",
          updated_at: "2026-11-25T00:00:00Z",
          effective_from: null,
          effective_until: null,
          is_simulated: true,
        },
      },
    ],
  };
  await nav.locator('.nav-airspaces input[type="file"]').setInputFiles({
    name: "regions.geojson",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(region)),
  });
  await expect(page.getByTestId("real-routing")).toContainText(
    "旧版本结果已失效",
  );
  let requested: any;
  await page.route("**/api/assistant/navigation/candidates", (r) => {
    requested = r.request().postDataJSON();
    return r.fulfill({ status: 503, json: { detail: "audit end of request" } });
  });
  await page
    .getByTestId("real-routing")
    .getByRole("button", { name: "按当前约束重新规划" })
    .click();
  await expect
    .poll(() => requested?.avoid_regions?.[0]?.id)
    .toBe("team-exclusion");
  expect(requested.frame).toBe("WGS84");
  expect(requested.origin).toEqual({ lng: 121.46, lat: 31.22 });
});

test("saved route, matching scene, assistant context and export stay connected", async ({
  page,
}) => {
  await page.route("https://basemaps.cartocdn.com/**", (r) => r.abort());
  await page.route("**/api/assistant/intakes/connectivity-intake", (r) =>
    r.fulfill({ json: intake }),
  );
  let sceneRequests = 0,
    recomputes = 0;
  page.on("request", (r) => {
    if (r.url().includes("navigation/candidates")) recomputes++;
  });
  await page.route("**/api/assistant/navigation/scenes/matching-scene", (r) => {
    sceneRequests++;
    return r.fulfill({
      json: {
        obstacles: { type: "FeatureCollection", features: [] },
        roads: { type: "FeatureCollection", features: [] },
      },
    });
  });
  await page.goto("/airspace?intake=connectivity-intake");
  const panel = page.getByTestId("real-routing");
  await expect(panel).toContainText("3 个 WGS84 航点");
  expect(sceneRequests).toBe(1);
  expect(recomputes).toBe(0);
  await expect(panel.getByLabel("航线配送载荷")).toHaveValue("0.8");
  await page.getByRole("button", { name: "打开调度助手", exact: true }).click();
  const request = page.waitForRequest(
    (r) => r.url().includes("/api/assistant/turn") && r.method() === "POST",
  );
  await page
    .getByRole("textbox", { name: "向调度助手提问" })
    .fill("查询当前飞行状态和电量");
  await page.getByRole("button", { name: "发送给调度助手" }).click();
  const body = (await request).postDataJSON();
  expect(body.context).toMatchObject({
    task_id: intake.intake_id,
    route_id: route.id,
    telemetry_mode: "planning",
    telemetry: null,
    terrain: null,
    events: [],
  });
  expect(body.context.active_route.waypoints).toEqual(
    route.waypoints.map((p) => [p.x, p.y]),
  );
  await expect(
    page.locator(".assistant-response-block.response-metrics"),
  ).toContainText("当前规划路线");
  await expect(
    page.locator(".assistant-response-block.response-metrics"),
  ).not.toContainText("83.4");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出快照", exact: true }).click();
  const file = await (await download).path();
  const snapshot = JSON.parse(await readFile(file!, "utf8"));
  expect(snapshot.telemetry).toBeNull();
  expect(snapshot.active_route.id).toBe(route.id);
  expect(snapshot.geographic_mission.route_status).toBe("planned");
  expect(snapshot.geographic_mission.scene_id).toBe("matching-scene");
  expect(
    snapshot.geographic_mission.route.waypoints.map(
      (p: { x: number; y: number }) => [p.x, p.y],
    ),
  ).toEqual(body.context.active_route.waypoints);
  await page.goto("/airspace?intake=connectivity-intake&telemetry=live");
  await expect.poll(() => sceneRequests).toBe(2);
  await expect(
    page.getByRole("region", { name: "规划航线状态概览" }),
  ).toHaveCount(0);
  await expect(page.getByTestId("telemetry-battery")).toBeVisible();
});

test("legacy saved route keeps explicit gaps and never needs a second OSM request", async ({
  page,
}) => {
  await page.route("https://basemaps.cartocdn.com/**", (r) => r.abort());
  const old = {
    ...intake,
    real_route: {
      status: "ok",
      waypoints: route.waypoints,
      length_m: 1960,
      obstacle_source: "legacy fixture",
    },
  };
  await page.route("**/api/assistant/intakes/connectivity-intake", (r) =>
    r.fulfill({ json: old }),
  );
  await page.goto("/airspace?intake=connectivity-intake");
  const panel = page.getByTestId("real-routing");
  await expect(panel).toContainText("3 个 WGS84 航点");
  await panel.getByText("数据来源与限制").click();
  await expect(panel).toContainText("历史工单未保存对应建筑快照");
  await expect(panel).toContainText("要求水平净空 ≥ —");
});

test("a missing matching snapshot never publishes a restored route", async ({
  page,
}) => {
  await page.route("https://basemaps.cartocdn.com/**", (r) => r.abort());
  await page.route("**/api/assistant/intakes/connectivity-intake", (r) =>
    r.fulfill({ json: intake }),
  );
  await page.route("**/api/assistant/navigation/scenes/matching-scene", (r) =>
    r.fulfill({ status: 404, json: { detail: "expired" } }),
  );
  await page.goto("/airspace?intake=connectivity-intake");
  await expect(page.getByTestId("real-routing")).toContainText(
    "工单建筑快照不可用或过期",
  );
  await expect(page.getByTestId("real-routing")).toContainText(
    "历史建筑避障结果，空域未核对",
  );
});
