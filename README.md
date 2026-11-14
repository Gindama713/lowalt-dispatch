# lowalt-dispatch

面向**应急配送**的低空航线规划系统。核心机制只有一条：把"备降可达性"做成**规划搜索阶段的硬约束**（每个候选状态都必须还能落到一个当前有效的降落点，否则直接剪枝），而不是选完最短路线之后再弹一次告警。配套的是云端链路退化时，边缘端按已同步、仍有效的快照执行**预校验过的**备用方案。

> **验证边界：软件在环仿真（SITL），无实机飞行。**
> 本仓库目前**没有**真实飞行数据、**没有**真实机型参数、**没有**云部署；已有几何 A\* 基线、搜索期备降硬约束（`planner/diversion.py`，示例机型，不是动态重规划）与 M3 决策内核。
> 能量和备降余量如果来自 `example_not_real.yaml`，那是**示例参数，非真实平台数据**。

## 现在是什么状态

v0.1 —— 骨架 + 一条能跑通的评测管道。

已经有的：

- `core/models.py` —— 五类接口的数据契约（Task / RiskSnapshot / RoutePlan / VehicleState / 执行确认），带单位、高度基准和"是否仿真"的硬校验
- `core/geometry.py` —— 几何原语（只做数学，不做判定）
- `planner/` —— 栅格化 + A\* 基线，能真的在草稿城区里算出一条不穿楼的路线。`planner/diversion.py` 把备降可达性放进搜索：不够就剪枝，无解不交负余量路线。默认示例机型，不是真实平台数据
- `sim/energy.py` —— 能量模型；**机型参数不填就直接报错，不给你一个像样的错数字**
- `validator/` —— **独立校验器**：只读航线航点，按自己的采样重新判净空、限制区（按生效时刻）、载荷、能量、备降可达性
- `agent/` —— M3 决策、审计恢复、M2适配、草稿确认与云服务基础接口；[最新运行与待办](docs/M3_2026-11-10基础接入与下一步.md)。本地可联调，真实MaaS/云资源/飞控仍待接入
- `eval/` —— 评测 harness，一条命令跑 20 场景 × 3 种子 × 3 算法，产出带溯源 meta 的 CSV
- `tests/` + `services/assistant/tests/` —— 公共契约、规划校验、M3/M4与助手集成测试；本机全量 **309 passed / 4 skipped**（2026-11-15 实跑，313 项收集）；定向回归与浏览器测试的历史记录见事实文档
- [`apps/console/`](apps/console/README.md) —— AERIS React/MapLibre 控制台：真实底图与选点、2D/3D、M4/PX4 SITL 实时遥测或演示回放、地形版本变化、事件流、候选方案和调度助手
- [`services/assistant/`](services/assistant/README.md) —— 控制台本地工具服务、MaaS 工具调用适配与地点搜索；默认规则演示，不下发飞控
- [`services/api/`](services/api/README.md) —— 两条本地 HTTP：助手上的合成任务入口（确认 → 真实 M3/M2/独立校验 → M4 FakeExecutor → ACK/状态回传，支持直连及真实本机 MQTT Broker；不控制 PX4），以及独立进程 `python -m services.api` 的任务 / 场景 / 规划接口（默认仍是几何基线）
- [`apps/web-3d/`](apps/web-3d/README.md) —— 三维 / 视觉前端，阶段 0–1（工程骨架、ENU 换算、机体比例骨架）。与 `apps/web/` 静态页、`apps/console/` 控制台分开，token 和后端接线未做

**待完成的**：动态重规划（`astar_dynamic` 仍是 mock）、飞控任务上传与起飞（见 [`ops/sitl/README.md`](ops/sitl/README.md)）、机型参数、真实地理草稿与正式执行的坐标绑定，以及当前状态下备用航线复核/切换。当前优先本地运行，云部署暂不要求。
`apps/web/index.html` 有一张**硬编码静态战术态势台**（3D 倾斜俯视 + ASCII 侧栏），零依赖、不接 API、几何为草稿、数值为占位，仅用于可视化表达，不是上述正式工程。
准确进度只看 [`事实文档.md`](事实文档.md)，别信 README 的乐观描述。

## 文档

- [`启动指南.md`](启动指南.md) — 三层启动（纯本地 / 本地 Docker 替身 / PX4 SITL）。
- [`docs/接口契约.md`](docs/接口契约.md) — 单位、对象字段和目标动作。和代码不一致时以 `core/models.py` 为准。
- [`docs/功能树与实现逻辑.md`](docs/功能树与实现逻辑.md) — 功能树。文首注明了它写于同步之前，现状以事实文档为准。
- [`docs/关键接口文档.md`](docs/关键接口文档.md) — 独立 FastAPI 的路由，以及同步前对上游接口的对照。
- [`apps/web-3d/README.md`](apps/web-3d/README.md) — 三维前端怎么启动。

## 快速开始

> **第一次拿到仓库？先看 [`启动指南.md`](启动指南.md)** —— 分三层（纯本地 / 本地 Docker 替身 / PX4 SITL），
> 每步都有实测预期输出和常见坑。独立控制台入口见下面及 [`apps/console/README.md`](apps/console/README.md)。

控制台本地启动（Node.js 22.12+、Python 3.11+）：

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r services/assistant/requirements.txt
cd apps/console
npm ci
npm run dev:all
```

打开 <http://127.0.0.1:5174/>。Windows PowerShell 如有限制，使用 `npm.cmd`。真实选点可以保存为草稿；地图上的建筑、航线、仪表和历史剖面仍标明为演示。全球 DEM 是已有高程资料，实时变化需外部数据源。

规划与 M3 命令：

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Linux/macOS

# A* 基线：在草稿城区里给 20 个任务各算一条路线
.venv/Scripts/python -m planner.astar

# 基线 vs 带约束 A*。默认示例机型，第一行会标明不是真实平台数据
.venv/Scripts/python -m planner.diversion

# 独立校验器：拿 20 条基线航线跑五项检查
.venv/Scripts/python -m validator

# 评测：真算法对照。必须显式传入示例机型；数字不能写成实测
.venv/Scripts/python -m eval.run --suite eval/scenarios/v0.yaml --seeds 1,2,3 \
    --algorithms astar_static,astar_diversion \
    --vehicle scenarios/vehicles/example_not_real.yaml \
    --out results/example_vehicle_compare.csv

# 仍是 mock 的动态基线。输出文件名自动带 _MOCK
.venv/Scripts/python -m eval.run --suite eval/scenarios/v0.yaml --seeds 1,2,3 \
    --algorithms astar_dynamic --out results/v0.csv

# M3 决策内核（MOCK 联调）
.venv/Scripts/python -m agent.demo --scenario all

# M3基础接入（可选依赖；无需购买云资源）
.venv/Scripts/python -m pip install -r requirements-m3.txt
.venv/Scripts/python -m agent.integration check
.venv/Scripts/python -m agent.integration demo --scenario S1-01

# 本地 Docker 模式：用容器替身 RDS / DCS / MQTT（仍然不是华为云）
docker compose -f ops/docker-compose.yml up -d
cp ops/local.env.example .env
.venv/Scripts/python -m agent.integration --env-file .env check
# 起停、验证、断连演示见 ops/README.md；三个真实服务测试需要 Docker daemon 在跑

# 跑测试
.venv/Scripts/python -m pytest
```

只跑 `astar_dynamic` 时的预期输出：

```
MOCK 运行 —— 这些数字不是结果，只证明管道能跑通
场景 20 × 种子 3 × 算法 1 = 60 行
CSV  → results\v0_MOCK.csv
meta → results\v0_MOCK.meta.json
```

文件名里的 `_MOCK` 是自动加的：只要用的还是占位规划器，输出就别想伪装成真实结果。
带 `--vehicle` 的 `astar_static` / `astar_diversion` 写到你指定的路径，并另有 `.meta.json` 与 `.profiles.json`。那些数字只对示例机型成立。
不带 `--algorithms` 也不带 `--vehicle` 直接跑 `eval.run` 会以 `exit 2` 退出：默认算法里含真算法，而机型参数文件必须显式指定。

## 目录

```
core/            数据契约 + 几何原语（A/B/C 共用，改这里必须同步 docs/接口契约.md）
planner/         栅格化 + A* 基线 + 场景装配 + 备降搜索期硬约束（M2）
sim/             能量模型（M2）—— 机型参数不填就报错
validator/       独立校验器（M2）—— 只读航点，自己重新采样复算
agent/           M3 决策内核 + M2适配/草稿确认/云服务基础接口；默认本地 MOCK，真实云资源待接入
eval/            评测 harness + 场景集
  scenarios/     20 个任务样例（v0.yaml）
scenarios/v0/    草稿几何：建筑 / 限制区 / 备降点 —— 待 B 复核或重画
  vehicles/      placeholder.yaml 仍全是 null；example_not_real.yaml 是示例参数
services/api/    本地合成任务（routes.py）+ 独立任务/场景/规划 FastAPI（main.py）
services/assistant/ 控制台本地助手与地点搜索；正式M3下发仍待对接
edge/            边缘执行端：去重/过期/ACK/遥测/重启恢复（控制流可用；PX4 SITL 遥测已通，任务上传未实现）
apps/web/        原有静态战术页面（保留队友实现）
apps/web-3d/     三维/视觉前端（阶段 0–1）。见 apps/web-3d/README.md
apps/console/    AERIS React + MapLibre/Three.js 独立演示台
ops/             Compose 拓扑（含断连演示用的双网络）
docs/            接口契约、功能树、关键接口、M3/M4 记录
results/         评测产物；真实结果在冻结时提交，mock 永不入库
```

## 三个人从哪进

| 角色 | 第一件事 | 卡点 |
|---|---|---|
| A · 飞控与仿真 | SITL 遥测已通（[`ops/sitl/`](ops/sitl/README.md)）；下一步校准/home → `MavsdkExecutor.upload_mission` | 填 `scenarios/vehicles/placeholder.yaml` 的 `null`——**它卡着所有能量计算** |
| B · 规划与数据 | 复核 `scenarios/v0/` 草稿几何；备降余量已进 A\* 搜索（`planner/diversion.py`，示例机型）。下一步是动态重规划 | 真实机型参数（来自 A） |
| C · 平台与智能体 | ECS 最小部署 + SWR 镜像预检；FastAPI 骨架；把 `validator` 接进 `AgentTools.verify_route` | 云账号与安全组 |

## 表述红线

这些词在本仓库和一切材料里都不许乱用，理由见 [`事实文档.md`](事实文档.md) 第 5 节：

- 仿真 → 不能说成实飞
- 本地备用方案切换 → 不能说成边缘实时重规划
- 固定顺序调用工具 → 不能说成 Agent 自主决策
- mock 数字 → 不能出现在任何效果描述里
- 示例机型参数下的余量 / 可行场景数 → 不能说成实机能耗或已标定的任务完成率
