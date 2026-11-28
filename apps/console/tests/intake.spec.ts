import { expect, test } from "./fixtures";

test("future delivery asks full clarification and never treats ENU as WGS84", async ({
  page,
}) => {
  await page.goto("/airspace");
  await page.getByRole("button", { name: "打开调度助手", exact: true }).click();
  await page
    .getByRole("textbox", { name: "向调度助手提问" })
    .fill("下周我想从医疗物资中转站送东西到北区应急中心，你能给我规划路线吗？");
  await page.getByRole("button", { name: "发送给调度助手" }).click();

  const card = page.getByTestId("intake-clarification");
  await expect(card).toBeVisible();
  await expect(card).toContainText("地点还没完全解析");
  await expect(card).toContainText("时间：");
  await expect(
    card.getByRole("button", { name: "A · 就用这个时间" }),
  ).toBeVisible();
  await expect(card).toContainText("载荷重量");
  await expect(card).toContainText("优先级");

  const pins = page.getByTestId("intake-map-pins");
  await expect(pins).toContainText("医疗物资中转站");
  await expect(pins).toContainText("场景坐标不是经纬度，请搜索或地图选点");
  await expect(pins).toContainText("坐标未解析，助手不会猜");
  await expect(page.getByTestId("intake-confirm")).toBeDisabled();
});
