# 电脑端 3D 爆炸视图后景融合与组件循环缩放动画展示

已将 **CR30 318 构件三维爆炸视图**直接嵌入电脑端全站页面后景（`/`、`/console`、`/login`、`/workspace`、`/missions`、`/airspace`、`/fleet`、`/demo`），实现 **6 大核心子系统循环丝滑放大/缩小 + 镜头平滑推拉聚焦**，并通过 `pointer-events: none` 与毛玻璃分层架构保证**完全不影响任何前景视图交互**。

---

## 一、全站融合实景截图（真实 Chrome 1600×900 渲染）

````carousel
![官网首页 /（日间模式）：CR30 318 零件爆炸后景 · 动力推进系统 138% 丝滑放大](/Users/cr/.gemini/antigravity/brain/9d1de8be-647e-4fed-a4d3-041a1ebd68b0/bg-home-pwr-zoom.png)
<!-- slide -->
![官网首页 /（暗夜模式）：应急医疗载荷舱 138% 暖金高亮放大 + 前海摩天轮 3D 同框](/Users/cr/.gemini/antigravity/brain/9d1de8be-647e-4fed-a4d3-041a1ebd68b0/bg-home-dark-cargo.png)
<!-- slide -->
![登录页 /login：318 零件全视场爆炸拆解 · 高能量电池模组 138% 聚焦 + 毛玻璃登录卡片](/Users/cr/.gemini/antigravity/brain/9d1de8be-647e-4fed-a4d3-041a1ebd68b0/bg-login-exploded.png)
<!-- slide -->
![低空任务指挥台 /console：飞控与航电核心 138% 聚焦 · 顶部居中无缝控制胶囊 + 10× 深圳三维](/Users/cr/.gemini/antigravity/brain/9d1de8be-647e-4fed-a4d3-041a1ebd68b0/bg-console-exploded.png)
<!-- slide -->
![竞赛演示页 /demo：多维感知传感阵列 138% 聚焦 · 顶栏居中控制胶囊（录制模式自动隐藏）](/Users/cr/.gemini/antigravity/brain/9d1de8be-647e-4fed-a4d3-041a1ebd68b0/bg-demo-exploded.png)
````

---

## 二、36 秒无缝循环「丝滑放大缩小」动画编排

动画逻辑独立沉淀在 [drone-explode-cycle.ts](file:///Users/cr/Desktop/华为ict/lowalt-dispatch/apps/console/src/drone-explode-cycle.ts)，渲染层在 [DroneExplodeBackdrop.tsx](file:///Users/cr/Desktop/华为ict/lowalt-dispatch/apps/console/src/DroneExplodeBackdrop.tsx) 与 [drone-explode-backdrop.css](file:///Users/cr/Desktop/华为ict/lowalt-dispatch/apps/console/src/drone-explode-backdrop.css)，统一挂载在 [main.tsx](file:///Users/cr/Desktop/华为ict/lowalt-dispatch/apps/console/src/main.tsx)：

1. **整机巡航呼吸（`0.0s – 3.0s`）**：CR30 整机 360° 缓转，旋翼平稳旋转，机身做 `100% → 104.5% → 100%` 轻柔呼吸缩放。
2. **318 构件错峰爆炸展开（`3.0s – 7.5s`）**：使用 $C^2$ 五次平滑曲线 `smootherstep` + 各构件真实 `userData.stagger` 与 `explodeDir` 向量，外壳与桨叶先向外漂浮，飞控、电池与载荷舱依次丝滑展开。
3. **6 大子系统循环放大缩小聚焦（`7.5s – 31.5s`，每组 `4.0s`）**：基于 `sin²(πu)` 零突变钟形曲线依次聚焦 CR30 真实子系统：
   - **动力推进系统**（`PWR`，44 构件）→ **飞控与航电核心**（`FC`，11 构件）→ **高能量电池模组**（`BAT`，9 构件）→ **应急医疗载荷舱**（`CARGO`，11 构件）→ **多维感知传感阵列**（`SENS`，11 构件）→ **碳纤机身与起落架**（`FRAME/SHELL/LAND`，66 构件）。
   - **双重丝滑缩放**：聚焦组件自身平滑放大至 **`138%`** 并沿爆炸轴轻浮弹出、非聚焦组件轻退至 `91%` 增强景深对比，同时对应材质平滑泛起子系统专属高亮自发光；相机以指数阻尼平滑推近（`6.55 → 4.65`）跟踪该组件实时质心，随后平滑拉远切换至下一组件。
4. **构件丝滑回装（`31.5s – 36.0s`）**：逆序聚合回整机形态，无缝衔接下一轮循环。

---

## 三、零干扰交互保障与实测验收（Commit `a83c3d8`）

- **全视场鼠标/滚轮/触控完全穿透**：后景容器与 WebGL `<canvas>` 强制 `position: fixed; inset: 0; z-index: 0; pointer-events: none !important`，且无任何键盘焦点占用；前景页面树位于 `z-index: 1`，按钮、输入、滚动、深圳三维地图拖拽缩放 100% 原生响应。
- **独立轻量控制胶囊**：实时显示当前放大的组件名称与倍率，支持一键「暂停背景 / 继续背景」与「关闭背景 / 开启 3D 背景」（状态持久化至 `localStorage`，关闭后全站瞬间还原原始不透明背景；页面切到后台自动暂停省电；`/demo` 录制模式自动隐藏）。

| 验收项目 | 结果 |
| :--- | :--- |
| Prettier 格式检查 (`npm run format:check`) | 通过 |
| 单元测试 (`npm run test:demo`，含 6 子系统放大/缩小曲线单测) | **6/6 通过** |
| TypeScript + Vite 生产构建 (`npm run build`) | 通过（2.27s，新增懒加载 chunk 仅 5.34 kB gzip，复用本地模型零额外资源体积） |
| `/demo` 真实 Chrome E2E (`tests/demo.spec.ts`) | **通过** |
| 全站 5 视图交互与穿透验证（`/` 日夜双模式、`/login`、`/console`、`/demo`） | **全部通过**（`pointer-events: none`、`318` 构件加载、`138%` 聚焦缩放、前景拖拽/点击/输入/Tab/开关背景全正常、390px 移动端 0 溢出、0 报错、0 外部请求） |
| `git merge-tree` 对比 `upstream/main` (`4f70f50`) | **0 冲突（CLEAN）** |
