# lowalt-dispatch 缺陷修复与分支收口任务清单

## 一、代码 Bug 逐项修复
- [x] **Task 1 · 修复 `/demo` 暂停与跳帧转场暗幕 Bug**（分支 `feat/demo-cinematic-algorithm-explain`，提交 `a592e38`）
  - 转场遮罩 `transitionVeilOpacity` 仅在播放中（`playing === true`）生效，暂停/跳到 `32/34/49/52/118/142s` 关键帧时画面保持 100% 通透明亮
  - 补测 + `format:check` + `test:demo` + `build` + 真实 Chrome Playwright E2E + 截图像素复核（全部通过）
- [x] **Task 2 · 修复鸿蒙 App ArkTS 编译类型与开关联动 Bug**（分支 `cursor/feat-harmony-app-phase1-9cae`，提交 `f69209d`）
  - `Drone3DBackground.ets`：`setResponseData` 改传 `ArrayBuffer`（修复 `Uint8Array` 严格编译报错），关闭再开时复位 `pageReady`，二进制响应不传空编码串
  - `SettingsPage.ets`：`bg3dEnabled` 改为 `@StorageLink('bg3dEnabled')`，与 `TopBar` 快捷按钮双向同步
  - 跑通 `node test/check.mjs` + 静态语法检查（全部通过）
- [x] **Task 3 · 修复评测口径 Bug（`hard_constraint_report` 漏检 `at_s > 0` 时变禁飞区）并更新冻结基线**（分支 `fix/freeze-eval-20261123`，提交 `e9674ab` + `6cb4054`）
  - 在 `planner/diversion.py` 的 `hard_constraint_report` 中补齐与搜索/校验器一致的时变限制区复算，让 `S2-01`、`S2-03` 违规基线如实判为 `failed`
  - 新增回归测试，全量 `pytest`（500 passed / 6 skipped）+ `ruff check` + `ruff format --check` 全部通过
  - 重跑并冻结 `results/frozen_example_vehicle_e9674ab.{csv,meta.json,profiles.json}`（`astar_static` 36/60 vs `astar_diversion` 39/60、0 违规），同步更新 `results/README.md` / `docs/demo-integration-status.md` / `事实文档.md`

## 二、分支冲突与跨分支一致性收口
- [x] **Task 4 · 同步 `/demo` 冻结数据并验证全部 6 条分支零冲突**
  - 已将最新冻结基线 `e9674ab` 同步到 `feat/demo-cinematic-algorithm-explain`（`8ff028e`），通过 `format:check` + `test:demo`（5/5）+ `build` + 真实 Chrome Playwright E2E
  - 调整 `fix/freeze-eval-20261123`（`edbcbb7`）中 `事实文档.md` 段落位置，消除与 PR #7/#8 的交叉文档冲突
  - 全部 6 条分支 vs `upstream/main`（`4f70f50`）为 **6/6 零冲突**，两两交叉矩阵为 **15/15 零冲突**

## 三、用户手动操作收尾指南
- [x] **Task 5 · 输出清晰的手工操作清单**（GitHub 推送、清理旧 Fork PR、合并上游 PR 顺序、DevEco Studio 打包 `.hap`）
