import { pointAlong } from "../src/terrain";
import { expect, test } from "@playwright/test";

test("algorithm evidence shares a task, cursor and verdict across map and review", async ({
  page,
}, testInfo) => {
  await page.goto("/demo");
  const card = page.locator(".demo-analysis .task-evidence");
  await expect(card).toHaveAttribute("data-task-id", "T-S1-02");
  await expect(page.locator(".demo-task-status")).toContainText("T-S1-02");
  await expect(page.locator(".demo-mission")).toContainText("0.8 kg");
  await page.getByRole("button", { name: "确认演示工单" }).click();
  await page.getByRole("slider", { name: "演示时间轴" }).fill("70");
  const map = page.getByLabel("算法证据主地图");
  await expect(map).toBeVisible();
  const before = await map.locator("svg").getAttribute("data-sample");
  await card.getByRole("slider", { name: "证据采样点" }).fill("10");
  await expect(map.locator("svg")).toHaveAttribute("data-sample", "10");
  expect(before).not.toBe("10");
  await page.screenshot({ path: testInfo.outputPath("task-evidence.png") });
  await page
    .getByRole("combobox", { name: "算法案例" })
    .selectOption("contrast");
  await expect(card).toHaveAttribute("data-task-id", "T-S1-01");
  await expect(card).toContainText("独立校验拒绝");
  await expect(card).toContainText("未标定");
  await expect(
    page.getByRole("button", { name: "确认演示工单" }),
  ).toBeDisabled();
  await expect(map.locator(".evidence-route")).toHaveAttribute(
    "data-verdict",
    "rejected",
  );
  await page.getByRole("button", { name: "重置", exact: true }).click();
  await expect(card).toHaveAttribute("data-task-id", "T-S1-02");
  await expect(page.locator(".demo-task-status")).toContainText("等待确认");
  await expect(map).toBeHidden();
});

test("competition replay loads the local model and preserves the simulated mission", async ({
  page,
}, testInfo) => {
  const external: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      /WebGLProgram|shader error|WebGL: INVALID/.test(message.text())
    ) {
      errors.push(message.text());
    }
  });
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.protocol === "http:" || url.protocol === "https:") {
      if (!["127.0.0.1", "localhost"].includes(url.hostname))
        external.push(url.href);
    }
  });
  await page.goto("/demo");
  await expect(page.locator(".demo-scene")).toHaveAttribute(
    "data-model",
    "loaded",
    {
      timeout: 30_000,
    },
  );
  await expect(page.locator(".demo-scene")).toHaveAttribute(
    "data-city",
    "shenzhen-bay-10x",
  );
  const scene = page.locator(".demo-scene");
  expect(Number(await scene.getAttribute("data-buildings"))).toBeGreaterThan(
    450,
  );
  expect(Number(await scene.getAttribute("data-details"))).toBeGreaterThan(
    8000,
  );
  await expect(page.locator(".demo-task-status")).toContainText("等待确认");
  await page.getByRole("button", { name: "建筑近景" }).click();
  await expect(scene).toHaveAttribute("data-view", "detail");
  await expect(scene.locator("canvas")).toHaveAttribute(
    "aria-label",
    "虚拟城市建筑近景",
  );
  await page.screenshot({ path: testInfo.outputPath("architecture.png") });
  await page.getByRole("button", { name: "CR30 特写" }).click();
  await expect(scene).toHaveAttribute("data-hero-model", "loaded", {
    timeout: 45_000,
  });
  await expect(scene).toHaveAttribute("data-view", "studio");
  await expect(scene.locator("canvas")).toHaveAttribute(
    "aria-label",
    "CR30 高精度模型特写",
  );
  await expect(page.locator(".demo-map-label")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("cr30-studio.png") });
  await page.getByRole("button", { name: "顶视", exact: true }).click();
  await expect(scene).toHaveAttribute("data-rendered-angle", "top");
  await page.screenshot({ path: testInfo.outputPath("cr30-top.png") });
  await page.getByRole("button", { name: "斜视", exact: true }).click();
  await page.getByRole("button", { name: "自动镜头" }).click();
  await page.getByRole("button", { name: "确认演示工单" }).click();
  await page.getByRole("slider", { name: "演示时间轴" }).fill("40");
  await expect(scene).toHaveAttribute("data-rendered-view", "studio");
  await page.getByRole("slider", { name: "演示时间轴" }).fill("118");
  await expect(scene).toHaveAttribute("data-rendered-view", "city");
  await expect(scene).toHaveAttribute("data-active-scene", "S1-02");
  await expect(scene).toHaveAttribute("data-route-id", /T-S1-02/);
  const source = await (await page.request.get("/task-evidence.json")).json();
  const progress = Number(await scene.getAttribute("data-route-progress"));
  const point = JSON.parse((await scene.getAttribute("data-plane-enu"))!);
  const sample = pointAlong(source.cases.main.waypoints, progress);
  expect(Math.hypot(point[0] - sample[0], point[1] - sample[1])).toBeLessThan(
    1e-6,
  );
  await expect(page.locator(".demo-alert")).toContainText("通信退化情景");
  await page.screenshot({ path: testInfo.outputPath("waterfront-city.png") });
  await page.getByRole("button", { name: "备降复盘", exact: true }).click();
  await expect(page.locator(".demo-task-status")).toContainText("未下发");
  await page.getByRole("button", { name: "录制模式" }).click();
  await expect(page.locator(".demo-controls")).toBeHidden();
  await page.keyboard.press("Escape");
  await expect(page.locator(".demo-controls")).toBeVisible();
  await page.getByRole("button", { name: "重置" }).click();
  await expect(page.locator(".demo-task-status")).toContainText("等待确认");
  expect(external).toEqual([]);
  expect(errors).toEqual([]);
});
