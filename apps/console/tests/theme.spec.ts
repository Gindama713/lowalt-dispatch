import { test, expect } from "@playwright/test";
import { authenticate } from "./fixtures";

test("theme persists through login navigation and reload, including mobile", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "切换到夜间模式" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({
    path: "test-results/design-night-home.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.locator(".p-hero-cta").click();
  await expect(page.locator(".p-auth-form")).toBeVisible();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(
    page.getByRole("button", { name: "切换到日间模式" }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/design-night-login.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "切换到日间模式" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});

test("night mode preserves task input and map renderer; system appearance syncs across tabs", async ({
  page,
  context,
}) => {
  await authenticate(context.request);
  await page.goto("/workspace");
  await page.getByRole("button", { name: "切换到夜间模式" }).click();
  await expect(page.locator(".p-service-list")).toContainText("任务 Agent");
  await page.screenshot({
    path: "test-results/design-night-workspace.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.goto("/missions/new");
  await page.getByRole("button", { name: "生成待审任务" }).click();
  await expect(page.locator(".p-stepper .current")).toContainText("核对与审核");
  await page.getByRole("checkbox", { name: /我已核对任务参数/ }).check();
  await page.getByRole("button", { name: "切换到日间模式" }).click();
  await expect(
    page.getByRole("checkbox", { name: /我已核对任务参数/ }),
  ).toBeChecked();
  await page.getByRole("button", { name: "切换到夜间模式" }).click();
  await page.screenshot({
    path: "test-results/design-night-review.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "确认并运行本地任务" }).click();
  await expect(
    page.getByRole("heading", { name: "任务结果已保存" }),
  ).toBeVisible();

  const styles: string[] = [];
  await page.route("https://basemaps.cartocdn.com/**", (route) => {
    const url = route.request().url();
    if (url.endsWith("style.json")) styles.push(url);
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        version: 8,
        sources: {},
        layers: [
          {
            id: "background",
            type: "background",
            paint: {
              "background-color": url.includes("dark-matter")
                ? "#101c2d"
                : "#eef3f7",
            },
          },
        ],
      }),
    });
  });
  await page.goto("/airspace");
  const canvas = page.locator(".geo-map canvas");
  await expect(canvas).toBeVisible();
  await expect
    .poll(() => styles.some((url) => url.includes("positron")))
    .toBeTruthy();
  expect(styles.some((url) => url.includes("dark-matter"))).toBeFalsy();
  await canvas.evaluate((el) => el.setAttribute("data-probe", "same-map"));
  await page.getByRole("button", { name: "切换到日间模式" }).click();
  await page.getByRole("button", { name: "切换到夜间模式" }).click();
  await expect(canvas).toHaveAttribute("data-probe", "same-map");
  expect(styles.some((url) => url.includes("dark-matter"))).toBeFalsy();
  await page.locator(".assistant-launcher").click();
  await expect(page.locator(".assistant-panel")).toBeVisible();
  await page.screenshot({
    path: "test-results/design-night-map.png",
    fullPage: true,
    animations: "disabled",
  });

  // Exercise the disconnected empty state independently of the telemetry fixture.
  await page.route("**/api/telemetry/stream", (route) => route.abort());
  await page.goto("/fleet");
  const emptyTrackIcon = page.locator(".live-track-empty > svg");
  await expect(emptyTrackIcon).toBeVisible();
  const iconSize = await emptyTrackIcon.boundingBox();
  expect(iconSize?.width).toBe(22);
  expect(iconSize?.height).toBe(22);
  await page.screenshot({
    path: "test-results/design-night-fleet.png",
    fullPage: true,
    animations: "disabled",
  });

  await page.goto("/account");
  await page.getByRole("button", { name: "跟随系统", exact: true }).click();
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({
    path: "test-results/design-night-account.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  const other = await context.newPage();
  await other.goto("/");
  await other.getByRole("button", { name: "切换到夜间模式" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(
    page.getByRole("button", { name: "夜间模式", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "test-results/design-night-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await other.close();
});
