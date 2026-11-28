import { expect, test } from "@playwright/test";

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
    18000,
  );
  await expect(page.locator(".demo-task-status")).toContainText("等待确认");
  await page.getByRole("button", { name: "建筑近景" }).click();
  await expect(scene).toHaveAttribute("data-view", "detail");
  await expect(scene.locator("canvas")).toHaveAttribute(
    "aria-label",
    "深圳湾地标建筑近景",
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
  await page.getByRole("button", { name: "爆炸拆解", exact: true }).click();
  await expect(scene).toHaveAttribute("data-rendered-explode", "1.00");
  await expect(scene).toHaveAttribute("data-explode-parts", "318");
  await page.screenshot({ path: testInfo.outputPath("cr30-exploded.png") });
  await page.getByRole("button", { name: "自动拆解", exact: true }).click();
  await page.getByRole("button", { name: "顶视", exact: true }).click();
  await expect(scene).toHaveAttribute("data-rendered-angle", "top");
  await page.screenshot({ path: testInfo.outputPath("cr30-top.png") });
  await page.getByRole("button", { name: "斜视", exact: true }).click();
  await page.getByRole("button", { name: "自动镜头" }).click();
  await page.getByRole("tab", { name: "冻结实测" }).click();
  await expect(page.locator(".demo-algo")).toContainText("e9674ab");
  await page.getByRole("tab", { name: "余量剖面" }).click();
  await page.getByRole("button", { name: "确认演示工单" }).click();
  await page.getByRole("slider", { name: "演示时间轴" }).fill("40");
  await expect(scene).toHaveAttribute("data-rendered-view", "studio");
  await page.getByRole("slider", { name: "演示时间轴" }).fill("118");
  await expect(scene).toHaveAttribute("data-rendered-view", "city");
  await expect(page.locator(".demo-alert")).toContainText("通信退化情景");
  await page.screenshot({ path: testInfo.outputPath("waterfront-city.png") });
  await page.getByRole("button", { name: "备降复盘", exact: true }).click();
  await expect(page.locator(".demo-task-status")).toContainText("物资待接续");
  await page.getByRole("button", { name: "录制模式" }).click();
  await expect(page.locator(".demo-controls")).toBeHidden();
  await page.keyboard.press("Escape");
  await expect(page.locator(".demo-controls")).toBeVisible();
  await page.getByRole("button", { name: "重置" }).click();
  await expect(page.locator(".demo-task-status")).toContainText("等待确认");
  expect(external).toEqual([]);
  expect(errors).toEqual([]);
});
