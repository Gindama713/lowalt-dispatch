import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "demo.spec.ts",
  workers: 1,
  // The replay test waits on a WebGL frame after several model loads.
  // On a busy runner that sequence can pass 120s before the frame lands.
  timeout: 180_000,
  expect: { timeout: 30_000 },
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    viewport: { width: 1600, height: 900 },
    baseURL: "http://127.0.0.1:4175",
    headless: true,
    launchOptions: { args: ["--enable-unsafe-swiftshader"] },
    ...(process.platform === "win32" ? { channel: "chrome" } : {}),
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run preview -- --port 4175 --strictPort",
    url: "http://127.0.0.1:4175/demo",
    reuseExistingServer: false,
  },
});
