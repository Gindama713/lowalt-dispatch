import { expect, test } from "@playwright/test";

test("toolbar opens the regional wind field and weather follows existing mission points", async ({
  page,
}) => {
  let fieldRequests = 0;
  let radarRequests = 0;
  await page.route("https://basemaps.cartocdn.com/**", (r) => r.abort());
  await page.route("https://api.open-meteo.com/**", (r) => {
    const latitudes = new URL(r.request().url()).searchParams
      .get("latitude")!
      .split(",");
    const current = {
      time: "2026-11-14T08:00",
      wind_speed_10m: 4,
      wind_direction_10m: 270,
    };
    if (latitudes.length === 1)
      return r.fulfill({
        json: { current: { ...current, temperature_2m: 18 } },
      });
    fieldRequests += 1;
    return r.fulfill({
      json: latitudes.map((_, location_id) => ({
        location_id,
        current: { ...current, wind_speed_10m: 2 + location_id / 10 },
      })),
    });
  });
  await page.route("https://api.rainviewer.com/**", (r) => {
    radarRequests += 1;
    return r.fulfill({
      json: {
        radar: {
          past: [
            { time: 1794614400, path: "/v2/radar/latest" },
            { time: 1794613800, path: "/v2/radar/older" },
          ],
        },
      },
    });
  });
  const tiles = new Set<string>();
  const transparent = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNgYAAAAAMAASsJTYQAAAAASUVORK5CYII=",
    "base64",
  );
  await page.route("https://tilecache.rainviewer.com/**", (r) => {
    const path = new URL(r.request().url()).pathname;
    if (path.startsWith("/v2/radar/")) tiles.add(path);
    return r.fulfill({ contentType: "image/png", body: transparent });
  });
  await page.goto("/");
  const weather = page.getByRole("region", { name: "任务区公开气象" });
  const layers = page.getByRole("button", { name: "地图图层" });
  const wind = page.getByRole("button", { name: "风场", exact: true });
  await expect(weather).toContainText("4.0 m/s · 西风");
  await expect(page.locator(".geo-wind")).toHaveCount(0);
  expect([fieldRequests, radarRequests]).toEqual([0, 0]);

  await weather.getByRole("button", { name: "展开天气卡片" }).click();
  await expect(weather).toContainText("18.0");
  await expect(weather).toContainText("演示城区 · 上海");
  await page.getByRole("button", { name: "地点定位 L" }).click();
  await page
    .getByRole("textbox", { name: "搜索地点或经纬度" })
    .fill("121.495,31.241");
  await page.getByRole("button", { name: "搜索地点", exact: true }).click();
  await page.getByLabel("选中地点名称").fill("测试起点");
  await page.getByRole("button", { name: "设为起点", exact: true }).click();
  await page.getByRole("button", { name: "3D", exact: true }).click();
  await page
    .getByRole("button", { name: "专注视图 F", exact: true })
    .first()
    .click();

  for (let i = 0; i < 2; i += 1) {
    await wind.click();
    await expect(wind).toHaveAttribute("aria-pressed", "true");
    await expect(
      page.getByRole("button", { name: "2D", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(weather).toContainText("CMA GRAPES");
    await expect(weather).toContainText("起点 · 测试起点");
    await expect(weather).toContainText("31.2410°, 121.4950°");
    await expect(weather.locator(".weather-wind-scale")).toBeVisible();
    await wind.click();
    await expect(wind).toHaveAttribute("aria-pressed", "false");
    await expect(weather.locator(".weather-wind-scale")).toHaveCount(0);
  }
  expect(fieldRequests).toBe(1);

  await layers.click();
  await page.getByRole("button", { name: "降雨雷达 · RainViewer" }).click();
  await expect(weather).toContainText("查询点有覆盖");
  await expect.poll(() => tiles.size).toBeGreaterThan(0);
  expect(
    [...tiles].every((path) => /^\/v2\/radar\/latest\/256\/[0-7]\//.test(path)),
  ).toBe(true);
  expect(radarRequests).toBe(1);
  expect(fieldRequests).toBe(1);
});
