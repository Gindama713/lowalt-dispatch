import { test, expect } from "@playwright/test";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

test("exported HTML renders both assets from file without network", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const external: string[] = [];
  await page.route(/^https?:/, (route) => {
    external.push(route.request().url());
    return route.abort();
  });
  await page.goto(
    pathToFileURL(resolve("dist/home-preview/AERIS-home.html")).href,
  );
  const stage = page.locator(".hero-experience");
  await expect(stage).toHaveAttribute("data-ready", "true");
  await page.getByRole("button", { name: "爆炸分解", exact: true }).click();
  await expect(stage.locator("canvas")).toHaveAttribute(
    "data-explode",
    "1.000",
  );
  await page.getByRole("button", { name: "城市场景", exact: true }).click();
  await expect(stage).toHaveAttribute("data-ready", "true");
  expect(
    Number(await stage.locator("canvas").getAttribute("data-buildings")),
  ).toBeGreaterThan(50);
  expect(external).toEqual([]);
  expect(errors).toEqual([]);
});
