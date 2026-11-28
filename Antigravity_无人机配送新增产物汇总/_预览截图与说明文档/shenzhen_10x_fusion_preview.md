# 10 倍大深圳湾三维都市融合效果展示（AERIS 主工程实景截图）

已将深圳三维城市底图扩展至约 **10 倍面积**（东西跨越 `1,880 m` 都市走廊、外围天际线延伸至 `±1,420 m`，共 **859 栋核心建筑 + 外围城市延展群 + 9 座雕塑级深圳地标 + 22,433 个建筑构件实例**），并**直接嵌入当前主项目**（不再局限于独立的 `/demo` 回放页），全部通过本地真实 Google Chrome 渲染与交互验收（0 运行报错、0 外部网络请求、移动端 390px 0 横向溢出）。

> [!NOTE]
> 所有三维城市与航线均保留清晰边界标注：**大深圳湾 10× 意象城市三维 · 非真实测绘坐标 · 不下发飞控**。原有「地形实验」「真实地图」「终端地图」及所有既有测试断言均完整保留，可随时一键切换。

---

## 一、主工程融合效果（真实 Chrome 1600×900 渲染截图）

````carousel
![官网首页 / Hero 主视觉已直接融合可交互 10× 深圳湾三维](/Users/cr/.gemini/antigravity/brain/9d1de8be-647e-4fed-a4d3-041a1ebd68b0/fused-home.png)
<!-- slide -->
![真实低空任务指挥台 /console — 大深圳湾 10× 全景（深圳三维按钮高亮激活）](/Users/cr/.gemini/antigravity/brain/9d1de8be-647e-4fed-a4d3-041a1ebd68b0/fused-console-panorama.png)
<!-- slide -->
![/console 一键切换：前海·湾区之光摩天轮与前海双子塔片区](/Users/cr/.gemini/antigravity/brain/9d1de8be-647e-4fed-a4d3-041a1ebd68b0/fused-console-qianhai.png)
<!-- slide -->
![/console 一键切换：福田 CBD·平安金融中心、应急约束区与备降航线](/Users/cr/.gemini/antigravity/brain/9d1de8be-647e-4fed-a4d3-041a1ebd68b0/fused-console-futian.png)
<!-- slide -->
![/console 一键切换：罗湖 CBD·京基 100 与地王大厦双塔片区](/Users/cr/.gemini/antigravity/brain/9d1de8be-647e-4fed-a4d3-041a1ebd68b0/fused-console-luohu.png)
````

---

## 二、10 倍城市扩展与主工程融合改动清单

| 融合位置 | 访问入口 / 组件 | 核心能力 |
| :--- | :--- | :--- |
| **官网首页主视觉** | `/`（[LandingPage.tsx](file:///Users/cr/Desktop/华为ict/lowalt-dispatch/apps/console/src/portal/LandingPage.tsx)） | 替换原静态占位画布 `#hero-model-slot` 为可 360° 拖动旋转、滚轮缩放的实时 10× 大深圳湾三维场景；新增「进入深圳三维调度台」直达入口 |
| **低空任务指挥台** | `/console` 及 `/airspace`、`/fleet`（[App.tsx](file:///Users/cr/Desktop/华为ict/lowalt-dispatch/apps/console/src/App.tsx)、[MapSurface.tsx](file:///Users/cr/Desktop/华为ict/lowalt-dispatch/apps/console/src/MapSurface.tsx)） | 在空域态势工具栏新增「深圳三维」切换按钮（支持与「真实地图」「地形实验」「终端地图」无损切换），与遥测、感知雷达、任务卡片、时间轴、图层开关同步融合 |
| **独立交互三维组件** | [ShenzhenCityScene.tsx](file:///Users/cr/Desktop/华为ict/lowalt-dispatch/apps/console/src/ShenzhenCityScene.tsx) | 集成 `OrbitControls`（缩放范围 `95..2150`）、5 个深圳片区一键平滑飞行视角（深圳湾全景 / 前海·摩天轮 / 后海·春笋 / 福田·平安 / 罗湖·京基100）、实飞 CR30 四旋翼模型与动态备降系留线 |
| **10× 大深圳城市引擎** | [city-layout.ts](file:///Users/cr/Desktop/华为ict/lowalt-dispatch/apps/console/src/demo/city-layout.ts)、[City.ts](file:///Users/cr/Desktop/华为ict/lowalt-dispatch/apps/console/src/demo/City.ts)、[Water.ts](file:///Users/cr/Desktop/华为ict/lowalt-dispatch/apps/console/src/demo/Water.ts) | **859 栋核心建筑**（分两级 `InstancedMesh` LOD）+ **9 座定制深圳地标**（平安金融中心、华润春笋、腾讯滨海大厦、市民中心、深圳湾春茧、京基 100、地王大厦、湾区之光摩天轮、前海双子塔）+ 深圳湾跨海大桥 + 大沙河 + 分层塘朗山/梧桐山柔化山脉与远景香港新界山脊 + 5800×2400 深圳湾海域 |
| **竞赛回放页同步升级** | `/demo`（[Scene.tsx](file:///Users/cr/Desktop/华为ict/lowalt-dispatch/apps/console/src/demo/Scene.tsx)） | 复用同一套 10× 深圳都市底图与雾效/山脊升级，3 分钟竞赛回放同样享受 10 倍深圳天际线 |

---

## 三、实测验收结果（Commit `7762491`）

| 验收项目 | 结果 |
| :--- | :--- |
| Prettier 代码规范 (`npm run format:check`) | 通过 |
| 单元与布局测试 (`npm run test:demo`) | **5/5 通过** |
| TypeScript + Vite 生产构建 (`npm run build`) | 通过（2.29s） |
| `/demo` 真实 Chrome E2E (`tests/demo.spec.ts`) | **通过**（`data-city="shenzhen-bay-10x"`，`buildings=859`，`details=22433`） |
| `/` 与 `/console` 真实 Chrome 交互与多片区切换校验 | **通过**（5 片区点击切换、地形实验↔深圳三维互切、390px 移动端 0 溢出、0 JS/WebGL 报错、0 外部网络请求） |
| `git merge-tree` 对比 `upstream/main` (`4f70f50`) | **0 冲突（CLEAN）** |
