import { build, normalizePath } from "vite";
import react from "@vitejs/plugin-react";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

// Self-contained visual review file. Business routes open the unchanged local app.
const entry = "virtual:aeris-home-preview";
const result = await build({
  configFile: false,
  plugins: [
    react(),
    {
      name: "aeris-home-preview",
      resolveId(id) { if (id === entry) return entry; },
      load(id) {
        if (id !== entry) return;
        return `
          import React from "react";
          import { createRoot } from "react-dom/client";
          import Landing from "${normalizePath(resolve("src/portal/LandingPage.tsx"))}";
          import { ThemeProvider } from "${normalizePath(resolve("src/portal/Theme.tsx"))}";
          import "${normalizePath(resolve("src/fonts.css"))}";
          import "${normalizePath(resolve("src/styles.css"))}";
          import "${normalizePath(resolve("src/portal/night.css"))}";
          const go = path => {
            if (path === "/") { window.scrollTo({top: 0, behavior: "smooth"}); return; }
            window.open("http://127.0.0.1:5174" + path, "_blank", "noopener");
          };
          createRoot(document.getElementById("root")).render(
            React.createElement(ThemeProvider, null, React.createElement(Landing, {go, user: null}))
          );
        `;
      },
    },
  ],
  resolve: { dedupe: ["three"] },
  build: {
    write: false,
    cssCodeSplit: false,
    assetsInlineLimit: Number.MAX_SAFE_INTEGER,
    rollupOptions: {
      input: entry,
      output: { format: "iife", inlineDynamicImports: true },
    },
  },
});
const outputs = (Array.isArray(result) ? result : [result]).flatMap(value => value.output);
const js = outputs.filter(value => value.type === "chunk").map(value => value.code).join("\n");
const css = outputs.filter(value => value.type === "asset" && value.fileName.endsWith(".css")).map(value => value.source).join("\n");
const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AERIS · 交互式三维首页</title><style>${css}</style>
<style>.preview-note{padding:8px 20px;text-align:center;background:#142b48;color:#d5e6fc;font:11px system-ui;line-height:1.8}</style></head>
<body><div class="preview-note">首页交互预览 · 模型、场景与字体均已内嵌 · 业务入口连接本机 5174 端口的完整 AERIS 项目</div><div id="root"></div>
<script>${js.replace(/<\/script/gi, "<\\/script")}</script></body></html>`;
await mkdir("dist/home-preview", { recursive: true });
await writeFile("dist/home-preview/AERIS-home.html", html);
console.log("Self-contained HTML exported:", Buffer.byteLength(html), "bytes");
