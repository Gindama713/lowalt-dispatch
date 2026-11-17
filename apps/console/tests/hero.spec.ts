import { test, expect } from "@playwright/test";

test("original CR30 renders, separates and restores; city uses REA geometry", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const stage = page.locator(".hero-experience");
  const canvas = stage.locator("canvas");
  await expect(stage).toHaveAttribute("data-ready", "true");
  expect(Number(await canvas.getAttribute("data-parts"))).toBeGreaterThan(300);
  await stage.scrollIntoViewIfNeeded();
  const assembled = await canvas.screenshot();
  await page.getByRole("button", { name: "爆炸分解", exact: true }).click();
  await expect(page.getByRole("slider", { name: "模型分解程度" })).toHaveValue(
    "100",
  );
  await expect(canvas).toHaveAttribute("data-explode", "1.000");
  expect((await canvas.screenshot()).equals(assembled)).toBe(false);
  await page.screenshot({
    path: "test-results/hero-exploded.jpg",
    animations: "disabled",
    quality: 65,
  });
  await page.getByRole("button", { name: "反向复原", exact: true }).click();
  await expect(canvas).toHaveAttribute("data-explode", "0.000");
  await page.getByRole("slider", { name: "模型分解程度" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("slider", { name: "模型分解程度" })).toHaveValue(
    "1",
  );
  await page.getByRole("button", { name: "重置三维视角" }).click();
  await expect(canvas).toHaveAttribute("data-explode", "0.000");
  await page.getByRole("button", { name: "扫描光效" }).click();
  await expect(page.getByRole("button", { name: "扫描光效" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.screenshot({
    path: "test-results/hero-assembled.jpg",
    animations: "disabled",
    quality: 65,
  });
  await page.getByRole("button", { name: "城市场景", exact: true }).click();
  await expect(stage).toHaveAttribute("data-ready", "true");
  expect(Number(await canvas.getAttribute("data-buildings"))).toBeGreaterThan(
    50,
  );
  await expect(stage).toContainText("非真实地理数据");
  await page.screenshot({
    path: "test-results/hero-city.jpg",
    animations: "disabled",
    quality: 65,
  });
  await page.getByRole("button", { name: "机体展示", exact: true }).click();
  await expect(stage).toHaveAttribute("data-ready", "true");
  await expect(canvas).toHaveCount(1);
  await page.getByRole("button", { name: "切换到夜间模式" }).click();
  await page.screenshot({
    path: "test-results/hero-dark.jpg",
    animations: "disabled",
    quality: 65,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await stage.scrollIntoViewIfNeeded();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/hero-mobile.jpg",
    animations: "disabled",
    quality: 65,
  });
  expect(errors).toEqual([]);
});

test("failed asset can retry while existing task navigation stays usable", async ({
  page,
}) => {
  await page.route(/cr30.*\.glb(?:\?.*)?$/, (route) => route.abort());
  await page.goto("/");
  const retry = page.getByRole("button", { name: "重新载入", exact: true });
  await expect(retry).toBeVisible();
  await page.unroute(/cr30.*\.glb(?:\?.*)?$/);
  await retry.click();
  await expect(page.locator(".hero-experience")).toHaveAttribute(
    "data-ready",
    "true",
  );
  await page
    .getByRole("button", { name: "创建第一个任务", exact: true })
    .click();
  await expect(page).toHaveURL(/\/login\?next=/);
});
