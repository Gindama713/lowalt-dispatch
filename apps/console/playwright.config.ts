import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

const telemetryFixture = resolve("test-results/telemetry-feed.ndjson");
if (!process.env.AERIS_TEST_RUNTIME_DIR) {
  process.env.AERIS_TEST_RUNTIME_DIR = resolve(
    "../../logs/browser-tests",
    String(Date.now()),
  );
}
const runtimeRoot = process.env.AERIS_TEST_RUNTIME_DIR;

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  // CI 用 SwiftShader 软件渲染 3D 地图：最慢用例本机 10.2 s、CI 1.9 m，
  // 默认 45 s 会在流程中途耗尽（报 Test timeout 而非断言失败）。
  // 只放宽 CI 上限，本机保持原阈值，真实卡顿在本机仍会暴露。
  timeout: process.env.CI ? 180_000 : 45_000,
  expect: { timeout: process.env.CI ? 30_000 : 15_000 },
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    viewport: { width: 1600, height: 1000 },
    baseURL: "http://127.0.0.1:5174",
    headless: true,
    launchOptions: {
      ...(process.env.CI ? {} : { channel: "chrome" }),
      args: ["--enable-unsafe-swiftshader"],
    },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "npm run assistant",
      url: "http://127.0.0.1:8012/api/assistant/health",
      reuseExistingServer: !process.env.CI,
      env: {
        AERIS_TELEMETRY_FILE: telemetryFixture,
        AERIS_DISPATCH_TRANSPORT: "direct",
        AERIS_DISPATCH_DIR: resolve(runtimeRoot, "dispatch"),
        AERIS_IDENTITY_DIR: resolve(runtimeRoot, "identity"),
        AERIS_AIRSPACE_DIR: resolve(runtimeRoot, "airspace"),
        AERIS_INTAKE_DIR: resolve(runtimeRoot, "intakes"),
        AERIS_OSM_CACHE_DIR: resolve(runtimeRoot, "osm_cache"),
        AERIS_FLYSAFE_LIVE: "0",
        AERIS_RAG: "keyword",
        SQLITE_PATH: resolve(runtimeRoot, "planning.sqlite"),
        AERIS_REGISTRATION: "invite",
      },
    },
    {
      command: "npm run dev -- --port 5174 --strictPort",
      url: "http://127.0.0.1:5174",
      reuseExistingServer: !process.env.CI,
    },
  ],
});
