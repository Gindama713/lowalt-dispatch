# apps/web · 低空配送调度控制台（单文件原型）

深色桌面控制台原型，以 **地图 / 航线轨迹 / 飞行仪表 / 备降余量剖面 / 事件流** 为中心。
视觉语言参考 HALOFLUX lab（暗色预设 A），布局、代码与动效为本项目原创实现，未复制参考站或其它版本源码。

- 形态：纯静态单文件 `index.html`（内联 CSS + 内联经典脚本），**双击即可打开**，无需构建。
- 数据：`assets/scene.js` 内联仓库 `scenarios/v0/` 草稿几何（局部 ENU 米制）与构造的仿真业务数据。
- 技术：MapLibre GL JS + deck.gl（CDN 固定版本），原生 JS，不使用 React / Vite / Three.js。

三维与视觉前端不在本目录，在 [`apps/web-3d/`](../web-3d/)（Vite + React + TypeScript；展厅用 R3F / Three.js）。阶段 0–1：工程骨架、ENU 换算、M350 RTK 比例骨架。天地图 / Cesium ion token 与后端接线未实现。本目录保持上游的静态调度控制台。

## 其他前端入口

- [AERIS 调度控制台](../console/README.md)提供实时遥测、Agent 调度和动态 ASCII 航图。
- [A / B / C 设计候选](designs/index.html)和 [D1 / D2 / D3 设计候选](designs/3d-index.html)保留在 `designs/`。原静态战术态势台的 3D 沙盘和 ASCII 侧窗可在 [D3](designs/d3-tactical.html) 查看。

## 运行

直接用浏览器打开：

```
apps/web/index.html
```

或访问 `file:///.../apps/web/index.html`。页面不依赖本地服务器。

CDN 依赖（全部锁定版本，UMD/经典脚本）：

- `maplibre-gl@4.7.1`
- `deck.gl@9.1.0`
- `@deck.gl/mapbox@9.1.0`
- `@deck.gl/layers@9.1.0`
- `@deck.gl/geo-layers@9.1.0`

底图使用 CARTO `dark-matter` 暗色瓦片。启动时同时探测**样式**（`style.json`）与**瓦片**（CARTO 瓦片 URL，5 s 超时）：若网络不可用、样式不可达、瓦片被代理/拦截器阻断，或任一探测超时，页面自动降级为程序化暗色网格，三维要素与面板仍可用；舞台左上出现降级提示条，可点「重试底图」。样式已应用后若 Maplibre 报出瓦片资源错误，同样会切到该降级模式（每次会话只触发一次）。

## 界面与快捷键

**工作区分页（数字键 1–6）**：总览 / 任务空间 / 飞行仪表 / 航线分析 / 事件流 / 感知与搜索。切换分页会应用对应的面板显隐预设，并带过渡动画。

**面板与视图**：

| 操作 | 快捷键 |
| --- | --- |
| 分页切换 | `1`–`6` |
| 专注地图（隐藏左右列） | `H` / `F` |
| 任务面板 | `T` |
| 候选路线面板 | `R` |
| 备降余量剖面 | `P` |
| 图例 | `L` |
| 无人机仪表盘 | `I` |
| 地形变化识别 | `G` |
| 图层菜单 | `K` |
| 2D / 3D 视角切换 | `V` |
| 暂停 / 继续演示 | `Space` |
| 组件管理抽屉 | `O`（打开 / 关闭） |
| 帮助 / 快捷键说明 | `?` |
| 关闭抽屉/菜单、恢复默认布局 | `Esc` |

其它交互：任务/候选列表可点选并联动地图高亮与剖面版本；每条候选路线带 `SIM` 徽标与 provenance（`source` / `version` / `captured_at`，优先取 `route.provenance`，缺省回退 `task.provenance`）；KPI「最小备降余量」口径为**取全部剖面（含 v1 历史方案）的最小值**；事件时间线默认「LIVE · 跟随」，新事件生效时自动逐条滚动并入场高亮，手动滚动/悬停会暂停跟随数秒后恢复；舞台底部回放滑块可拖动定位演示时刻；「导出快照」下载 JSON。

**诊断接口**：`window.LOWALT_CONSOLE`（version `1.0.0`），含 `getState()`、`getPanels()`、`setWorkspace()`、`getLayers()`、`setLayer()`、`setAutoFollow()`、`selectTask()`、`selectRoute()`、`setPlaying()`、`setDemoTime()`、`setMode()`、`exportSnapshot()`、`simulateDegradation()`、`symbols`、`lastFrameMs`。

## 降级模式

页面按可用能力分四级，均不白屏：

| 模式 | 触发 | 表现 |
| --- | --- | --- |
| FULL | 底图与三维库均可用 | 暗色底图 + 三维场景 |
| NO_BASEMAP | 底图样式或瓦片探测失败/超时（含瓦片被拦截） | 程序化暗色网格 + 三维要素，提示条 + 重试 |
| DECK_ONLY | MapLibre 不可用 | deck.gl 独立三维视图，面板可读 |
| STATIC | 三维库或场景数据缺失 | 网格占位说明；任务/剖面/遥测/时间线仍可读 |

可用 `LOWALT_CONSOLE.simulateDegradation('basemap' | 'map' | 'cdn')` 演练。

## 数据来源与仿真边界

- 建筑、限制区、备降点来自 `scenarios/v0/` 草稿几何；几何为 **局部 ENU 米制坐标**，页面通过 `scene.js` 的演示近似转换为 WGS84，**非真实地理坐标**。
- 建筑高度为 `height_source = "demo_derived"` 的公式推导值，不是测量结果。
- 任务、候选路线、备降余量剖面、事件、遥测均为构造的 **SITL 软件在环仿真** 演示数据（`is_simulated = true`）。
- 无人机姿态、地形高度变化、扩展仪表（电压/电流/转速/温度/波形）、感知雷达数值均由演示数据推导，界面已逐项标注「演示推导」。
- **这些数据与曲线不能作为算法效果、安全判定或飞行验证证据。**

## 验收记录

静态门禁（负责人复跑，2026-11-11）：

- `pytest tests/test_web_console_static.py` → **43 passed**（文件存在性、无构建痕迹、CDN 版本、C-CRS、C-SCENE-GEO、C-SCENE-DATA、I1–I7、禁用词、锚点等）。
- 内联脚本抽取后 `node --check` → 通过。
- 页面与数据文件的真实性表述扫描（禁用词清单）→ 0 命中。

运行期抽查（证据由实现方无头 Chrome file:// + CDP 自检提供，尚未经独立第三方全量复核）：

| 项 | 观察/证据 |
| --- | --- |
| 启动 | `[DECK_SYMBOLS]` 全 true、`[BOOT] mode=FULL`、console 无未捕获异常；运行时 4 备降点 / 4 限制区 / 20 建筑 / 5 路线 |
| 2D/3D | pitch 0° / 55°，aria-pressed 与文案同步，连点不卡死 |
| 轨迹 | 飞行器沿路线前进；暂停后位置不变；继续无跳变 |
| 备降剖面 | v1（RT-S2-01-A）红填充位于零线下方（y∈[154,176]，零线 154.57）；v2（RT-S2-01-B）全程非负、无红填充 |
| 事件流 | 倒序；事件生效时自动平滑滚动（scrollTop 0→136）并加入场动画 |
| 分页 | 数字键 1–6 切换，aria-selected 与面板显隐一致 |
| 感知雷达 | canvas 绘制非空（约 3885 px）、覆盖率/网格/目标距离/障碍距离/航向有值 |
| 扩展仪表 | 电压/电流/RSSI/卫星/HDOP/延迟/RPM/温度/波形随演示时钟变化 |
| 图层/回放 | `K` 菜单 7 个开关生效；滑块 scrub 时 demoT_s 与 `mm:ss / mm:ss` 联动 |
| 降级 | basemap / map / cdn 三级演练均无白屏，面板仍可读 |
| 布局 | 1920 / 1280 / 900 三档无横向溢出，KPI 不截断，剖面可读 |
| 性能 | `lastFrameMs` ≈ 6.1–6.7 ms，PERF: OK（未进入 LITE） |

## 已知限制

- 坐标为演示近似，不代表真实城区；建筑高度为构造值。
- 姿态、地形变化、扩展仪表与雷达均为演示推导，非测量结果。
- 底图依赖外网 CDN；离线时走 NO_BASEMAP 网格降级。
- 单文件原型优先演示与信息架构，未接入后端 API / WebSocket / 真实遥测。

## 遗留 Vite 工程说明

`apps/web` 原本存在一个 Vite + React 工程。本特性只将入口 `index.html` 覆盖为单文件原型，原入口已备份为：

```
apps/web/index.vite.entry.backup.html
```

`src/`、`node_modules/`、`.vite/` 等若存在，属既有工程基线，**不是本特性新增的运行时文件，也未删除**。如需恢复原 Vite 工程：把 `index.vite.entry.backup.html` 改回 `index.html`，并确保 `src/` 等原工程文件存在（若当前工作区未保留这些目录，则说明本工作区只包含单文件原型）。

## 版权

视觉语言参考 HALOFLUX by Ryder191（PolyForm Noncommercial，仅非商业用途）。本页面为原创实现，未复制其源码或其它版本源码。
