import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";

async function openAssistant(page: Page) {
  // Assistant integration checks exercise the real local service; public tiles
  // are covered separately so external network latency cannot stall this suite.
  await page.route("https://basemaps.cartocdn.com/**", (route) =>
    route.abort(),
  );
  await page.goto("/");
  await expect(page.getByText("构建数字空域…")).toBeHidden();
  await page.getByRole("button", { name: "打开调度助手", exact: true }).click();
  await expect(page.locator(".assistant-panel")).toBeVisible();
}

async function ask(page: Page, text: string) {
  await page.getByRole("textbox", { name: "向调度助手提问" }).fill(text);
  await page.getByRole("button", { name: "发送给调度助手" }).click();
  await expect(page.locator(".assistant-message.assistant").last()).toHaveClass(
    /done/,
  );
}

test("project questions show the exact document evidence and can report no match", async ({
  page,
}) => {
  await openAssistant(page);
  await expect(page.getByText("S1-01 回放 · 演示限制区均未生效")).toBeVisible();
  await ask(page, "ACK 代表飞完了吗？");
  const message = page.locator(".assistant-message.assistant").last();
  await expect(message).toContainText("执行端受理并启动了执行器");
  const source = message
    .locator(".assistant-document")
    .filter({ hasText: "7.3 ACK 语义" });
  await source.locator("summary").click();
  await expect(source).toContainText("docs/接口契约.md");
  await expect(source.locator("blockquote")).toBeVisible();
  await ask(page, "查项目文档，量子纠缠超光速通信");
  await expect(message).toContainText("没有找到能回答这个问题的依据");
  await expect(message.locator(".assistant-document")).toHaveCount(0);
});

test("natural-language tasks support missing fields, actual route preview and explicit draft saving", async ({
  page,
}) => {
  await openAssistant(page);
  await expect(page.locator(".assistant-connection")).toContainText(
    "本地规则模式",
  );
  await ask(page, "创建任务，从医疗物资中转站到北区应急中心");
  await expect(page.getByLabel("助手任务载荷")).toHaveValue("");
  await expect(
    page.locator(".assistant-message.assistant").last(),
  ).toContainText("还需要你补充：载荷");
  await expect(
    page.getByRole("button", { name: "确认保存草稿", exact: true }),
  ).toBeDisabled();
  await ask(page, "补充载荷1公斤，优先级P1");
  await expect(page.getByLabel("助手任务起点")).toHaveValue("医疗物资中转站");
  await expect(page.getByLabel("助手任务终点")).toHaveValue("北区应急中心");
  await expect(page.getByLabel("助手任务载荷")).toHaveValue("1");
  await page.getByRole("button", { name: "预览几何路线", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "路线预览结果" }),
  ).toContainText("已实际计算");
  await page.getByRole("button", { name: "地图展示预览", exact: true }).click();
  await expect(page.locator(".assistant-preview-label")).toContainText(
    "不替换当前任务",
  );
  await expect(
    page.getByRole("button", { name: "确认保存草稿", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "确认保存草稿", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "已保存到任务空间", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "收起调度助手", exact: true }).click();
  await page
    .locator(".rail")
    .getByRole("button", { name: "任务空间", exact: true })
    .click();
  await expect(
    page.locator(".task-card").filter({ hasText: "尚未提交" }),
  ).toContainText("北区应急中心");
  await expect(
    page.locator(".task-card").filter({ hasText: "尚未提交" }),
  ).toContainText("尚未提交");
});

test("editing a draft invalidates the visible route preview", async ({
  page,
}) => {
  await openAssistant(page);
  await ask(page, "从医疗物资中转站到北区应急中心，配送1公斤药品，预览路线");
  await page.getByRole("button", { name: "地图展示预览", exact: true }).click();
  await expect(page.locator(".assistant-preview-label")).toBeVisible();
  await page.getByLabel("助手任务终点").fill("L1");
  await expect(page.locator(".assistant-preview-label")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "路线预览结果" })).toHaveCount(
    0,
  );
});

test("risk analysis computes geometric evidence and links to the changed map region", async ({
  page,
}) => {
  await openAssistant(page);
  await ask(page, "分析地形变化对当前航线的影响");
  await expect(
    page.locator(".assistant-message.assistant").last(),
  ).toContainText("没有可分析的显著地形变化");
  await page
    .getByRole("button", { name: "注入演示地形变化", exact: true })
    .click();
  await expect(page.locator(".assistant-risk-nudge")).toContainText("REV 1");
  await page.locator(".assistant-risk-nudge").getByRole("button").click();
  await expect(
    page.getByRole("region", { name: "风险分析结果" }),
  ).toContainText("平面筛查结果不能代替净空与备降校验");
  await page.getByRole("button", { name: "定位变化区域", exact: true }).click();
  await expect(page.locator(".assistant-map-focus")).toContainText(
    "地形变化区域",
  );
  await expect(page.locator(".assistant-traces").last()).toContainText(
    "检查变化影响",
  );
});

test("status queries, evidence actions and record exports contain source labels", async ({
  page,
}) => {
  await openAssistant(page);
  await ask(page, "查询当前飞行状态和电量");
  await expect(
    page.locator(".assistant-message.assistant").last(),
  ).toContainText("浏览器演示遥测快照");
  await page.getByRole("button", { name: "定位无人机", exact: true }).click();
  await expect(page.locator(".assistant-map-focus")).toContainText("AER-01");
  await ask(page, "总结本次任务记录");
  await expect(
    page.locator(".assistant-message.assistant").last(),
  ).toContainText("不能推断配送完成");
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出助手对话", exact: true }).click();
  const output = await pending;
  const content = JSON.parse(await readFile((await output.path())!, "utf8"));
  expect(content.dispatch_enabled).toBe(false);
  expect(content.is_simulated).toBe(true);
  expect(
    content.messages.some((m: { traces: unknown[] }) => m.traces.length > 0),
  ).toBe(true);
});

test("service failures remain explicit and leave the console usable", async ({
  page,
}) => {
  await page.route("**/api/assistant/health", (route) =>
    route.fulfill({ status: 503, body: "" }),
  );
  await page.route("**/api/assistant/turn", (route) =>
    route.fulfill({ status: 503, body: "" }),
  );
  await openAssistant(page);
  await expect(page.locator(".assistant-connection")).toContainText("未连接");
  await page
    .getByRole("textbox", { name: "向调度助手提问" })
    .fill("查询当前状态");
  await page.getByRole("button", { name: "发送给调度助手" }).click();
  await expect(page.locator(".assistant-message.assistant").last()).toHaveClass(
    /error/,
  );
  await expect(
    page.locator(".assistant-message.assistant").last(),
  ).toContainText("助手服务未连接");
  await page.getByRole("button", { name: "收起调度助手", exact: true }).click();
  await page.getByRole("button", { name: "2D", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "2D", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
});

test("stop, clear confirmation, mobile layout and keyboard shortcuts stay usable", async ({
  page,
}) => {
  await openAssistant(page);
  await page.route("**/api/assistant/turn", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 3000));
    await route.fulfill({ status: 503, body: "" }).catch(() => {});
  });
  await page
    .getByRole("textbox", { name: "向调度助手提问" })
    .fill("查询当前状态");
  await page.getByRole("button", { name: "发送给调度助手" }).click();
  await page
    .getByRole("button", { name: "停止接收助手结果", exact: true })
    .click();
  await expect(
    page.locator(".assistant-message.assistant").last(),
  ).toContainText("已停止接收");
  await page.getByRole("button", { name: "清空助手会话", exact: true }).click();
  await expect(page.locator(".assistant-clear-confirm")).toBeVisible();
  await page
    .locator(".assistant-clear-confirm")
    .getByRole("button", { name: "取消", exact: true })
    .click();
  await expect(page.locator(".assistant-message.user")).toHaveCount(1);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.body.scrollWidth <= innerWidth),
  ).toBe(true);
  await expect(
    page.getByRole("textbox", { name: "向调度助手提问" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".assistant-panel")).toBeHidden();
  await page
    .locator(".rail")
    .getByRole("button", { name: "调度助手 A", exact: true })
    .click();
  await expect(page.locator(".assistant-message.user")).toHaveCount(1);
});
