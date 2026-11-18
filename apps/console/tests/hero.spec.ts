import { test, expect } from "@playwright/test";
import * as T from "three";
import { inspectAssembly } from "../src/portal/heroAssembly";

test("a local exploded view moves the authored part node and restores its material", () => {
  const root = new T.Group();
  const system = new T.Group();
  system.userData.labelZh = "动力系统";
  root.add(system);
  const original = new T.MeshStandardMaterial();
  const geometry = new T.BoxGeometry(0.1, 0.1, 0.1);
  function motor(name: string) {
    const group = new T.Group();
    group.name = name;
    system.add(group);
    return [0, 0.12].map((height) => {
      const part = new T.Group();
      part.position.y = height;
      part.userData = {
        system: "PWR",
        explodeDir: [0, 1, 0],
        explodeDist: 0.5,
      };
      part.add(new T.Mesh(geometry, original));
      group.add(part);
      return part;
    });
  }
  const left = motor("PWR_MOTOR-FL"),
    right = motor("PWR_MOTOR-FR");
  const assembly = inspectAssembly(root);
  assembly.select("PWR_MOTOR-FL");
  assembly.update(1, 1);
  expect(left[1].position.y - left[0].position.y).toBeGreaterThan(0.12);
  expect(right.map((part) => part.position.y)).toEqual([0, 0.12]);
  expect(left[0].children[0].position.lengthSq()).toBe(0);
  assembly.select("PWR_MOTOR-FR");
  assembly.update(1, 1);
  expect(left.map((part) => part.position.y)).toEqual([0, 0.12]);
  assembly.select("");
  assembly.update(0, 1);
  expect(right.map((part) => part.position.y)).toEqual([0, 0.12]);
  expect((right[0].children[0] as T.Mesh).material).toBe(original);
  assembly.dispose();
  original.dispose();
  geometry.dispose();
});

test("inspect a motor by label, select a system, and distinguish mesh clicks from drags", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const stage = page.locator(".hero-experience");
  const select = stage.getByRole("combobox", { name: "选择分解部位" });
  const motor = stage.getByRole("button", { name: "分解左前电机" });
  await expect(stage).toHaveAttribute("data-ready", "true");
  await expect(stage.getByRole("status")).toHaveText("9 个系统 · 318 个零件");
  await motor.click();
  await expect(select).toHaveValue("PWR_MOTOR-FL");
  await expect(stage.getByRole("status")).toHaveText("左前电机 · 6 个零件");
  await expect(stage.locator("canvas")).toHaveAttribute(
    "data-explode",
    "1.000",
  );
  await stage.screenshot({ path: "test-results/hero-motor.jpg", quality: 80 });
  await select.selectOption("FC");
  await expect(stage.getByRole("status")).toHaveText("飞控与航电 · 11 个零件");
  await page.getByRole("button", { name: "重置三维视角" }).click();
  await expect(motor).toBeVisible();
  // Aim at the actual mesh under the annotation, bypassing only the DOM label.
  await page.addStyleTag({
    content: ".hx-hotspot, .hx-hotspot * { pointer-events:none !important }",
  });
  const box = (await motor.boundingBox())!;
  const x = box.x + box.width / 2,
    y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 45, y + 18, { steps: 6 });
  await page.mouse.up();
  await expect(select).toHaveValue("");
  await page.getByRole("button", { name: "重置三维视角" }).click();
  await expect(stage.locator("canvas")).toHaveAttribute(
    "data-explode",
    "0.000",
  );
  const target = (await motor.boundingBox())!;
  await page.mouse.click(
    target.x + target.width / 2,
    target.y + target.height / 2,
  );
  await expect(select).not.toHaveValue("");
});

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
