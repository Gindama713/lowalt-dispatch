# lowalt-web

「低空航线安全规划与动态避险智能体」的三维 / 视觉前端，目录是仓库里的 `apps/web-3d/`。调度任务台仍在 `apps/web/`（只有 README，未开工）。

**阶段 0：** 工程骨架、冻结 demo 存档、ENU↔WGS84 坐标换算、锚点决议。天地图与 Cesium ion 的 token **未接入，待验证**。

**阶段 1：** M350 RTK 比例骨架（69 个部件）和四段高光镜头预演脚本（`docs/部件清单v1.md`、`docs/高光镜头表v0.md`）。尚无真实材质。浏览器里的 60 fps 展厅属于阶段 3，未实现。与后端的接线未实现。首页仍是阶段 0 占位。

## 技术栈（已按需求文档第 5 节登记，不重新选型）

- Vite + React 19 + TypeScript
- 首页展厅：Three.js + React Three Fiber / drei（依赖已装，功能未实现）
- 地图态势：CesiumJS（依赖已装，功能未实现）
- 任务台 2D 规划图：MapLibre GL JS（依赖已装，功能未实现）
- 底图：天地图；增强：Cesium ion Community（需用户提供 token）

## 命令

```bash
npm ci           # 按 package-lock.json 安装
npm run dev      # 开发服务器
npm run build    # 类型检查 + 生产构建
npm test         # ENU / 场景坐标往返测试
```

开发服务器启动后：

- 占位首页：<http://127.0.0.1:5173/>
- 冻结的原版 demo 存档：<http://127.0.0.1:5173/legacy/demo-baseline.html>

## 环境变量

复制 `.env.example` 为 `.env` 后填写。`.env` 已加入 `.gitignore`，**不要提交真实 token**。

| 变量 | 含义 | 默认 |
| --- | --- | --- |
| `VITE_TIANDITU_TOKEN` | 天地图浏览器端 token | 空（待用户申请） |
| `VITE_CESIUM_ION_TOKEN` | Cesium ion Community token | 空（待用户申请；社区授权仅限非商业/评估） |
| `VITE_API_BASE` | 后端 API 根地址 | `http://127.0.0.1:8000` |
| `VITE_ANCHOR_LAT` / `VITE_ANCHOR_LON` / `VITE_ANCHOR_H` | 兴隆湖湖心锚点 | 见 `.env.example` 与 `docs/锚点决议.md` |

## Demo 冻结存档

`public/legacy/demo-baseline.html` 由交接目录中的最终版单文件 demo（文档所称 `index.html`）原样复制，字节一致。

- SHA-256：`a91eb12deb3671d1141d5b01c4c4885ed336cc7a0113e813a42a7d0729bf77be`
- 字节数：72486
- 校验文件：`public/legacy/SHA256SUMS.txt`

## 坐标

- 决议：`docs/锚点决议.md`
- 转换与场景平移：`src/geo/enu.ts`（`enuToLla` / `llaToEnu` / `sceneToEnu` / `enuToScene`）
- 约定：场景中心 `(1500, 1500)` 对准兴隆湖湖心，`scene (x, y)` → ENU `(x-1500, y-1500)`

## 尚未完成

- 两个 token 调通（天地图瓦片出图、ion 地形可加载）需要用户自行注册并提供 token，本目录不代为注册、不付费。
- 与后端 API 的接线未实现（页面只展示 `VITE_API_BASE`，不发请求）。
- 真实材质，以及阶段 3 的 60 fps 首页展厅。
