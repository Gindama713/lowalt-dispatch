# services/api

这个目录里有两条本地 HTTP，共用包名，不是同一个进程。

1. **本地合成任务**（`runtime.py` + `routes.py`）挂在 `services.assistant.app`，走确认 → M3/M2/独立校验 → M4。控制台「本地任务联调」用的是这一条。
2. **独立 FastAPI**（`python -m services.api`，`main.py`）提供任务、v0 场景和规划查询，默认仍调用几何基线。它不替代上面那条链路。

---

# 本地任务服务

已经实现 `runtime.py` + `routes.py`，挂载在 `services.assistant.app:app`；共用一个8012端口，无需另开API服务或购买云资源。

## 最快运行

在仓库根目录安装 `services/assistant/requirements.txt`，进入 `apps/console` 执行 `npm.cmd run dev:all`，打开 <http://127.0.0.1:5174/>，点击顶部「本地任务联调」。

1. 选择 `S1-01`，点击「生成待审任务」。
2. 检查起终点ENU、高度基准、合成初始/预留能量，勾选确认后运行。
3. 查看真实M3/M2/独立校验代码产生的受理状态、航点数、ACK、版本、启动次数与工具审计。
4. 后台每0.5秒推进FakeExecutor；ACK后仍是 `executing`，结束后才报告 `completed`。
5. 可以明确「结束本次合成测试」，释放本地车辆，随后用 `S2-01` 验证禁飞事件拦截。此操作不会向PX4发指令。

这是一条**本地合成执行链路**。没有调用云模型、没有控制PX4、没有真实飞行安全指标。原调度助手仍只负责问答/草稿/几何预览，地图真实选点尚未直接送入正式执行。

## 两种本地传输

默认 `AERIS_DISPATCH_TRANSPORT=direct`：服务内直接调用 `EdgeService`。SQLite + JSONL是真实持久化；不需要Docker、PostgreSQL或Redis。

需要展示跨进程收发时，从仓库根运行：

```powershell
docker compose -f ops/docker-compose.yml up -d mosquitto
# 第一个终端；Python换成你实际的虚拟环境路径
.venv/Scripts/python.exe -m edge.mqtt
```

另开终端启动网页和API：

```powershell
$env:AERIS_DISPATCH_TRANSPORT = 'mqtt'
cd apps/console
npm.cmd run dev:all
```

MQTT默认车辆 `local-mock-1`，回环地址 `127.0.0.1:1883`，topic前缀 `lowalt/v1/mock/vehicles/local-mock-1/`。命令走 `commands`，回传走 `acks` / `telemetry` / `status` / `heartbeat`，均QoS1、非retained。此Broker匿名配置只用于本机。

MQTT执行端在Broker中断时继续推进已接受的**合成**任务；连接恢复后发送原始ACK和持久状态，绝不重新启动命令。API重启也只恢复订阅/查询，不重发命令。ACK/状态每约5秒重新对账，不能将Broker PUBACK当飞控ACK。

API默认存储 `logs/local-dispatch/`；MQTT执行端存储 `logs/local-edge/`。`AERIS_DISPATCH_DIR` 可改API目录，`edge.mqtt --state-dir` 可改执行端目录；二者不要共用。同一状态目录只允许一个进程写。历史合成产物不进Git。

## 恢复和已知限制

- 单机当前只允许一个活动命令。新命令不会自动替换在飞航线；旧版本或同版本不同ID会拒绝。
- 同一个命令ID的受理/拒绝会保留，重试不能让原先被拒的命令后来突然执行。
- 执行端重启把未完成记录标为 `recovering`，不自动重放。默认直连可在页面明确结束合成测试。MQTT模式需先退出daemon、核对 `logs/local-edge/commands.sqlite3`；纯测试需要全新场景时用新的 `--state-dir` 和API `AERIS_DISPATCH_DIR`，保留原目录用于审计。真实飞控不得按此方法清状态。
- 页面关闭不会取消任务；API服务关闭会停止本地合成推进。服务恢复后必须对账。
- `S2-01` 的拦截是当前基线校验的真实结果。当前A*不能根据反馈真正重规划；不会把重复计算包装成新算法。
- 真实地理草稿还缺ENU原点、机型参数和飞控任务上传；PX4实时读数继续使用独立 `/api/telemetry/stream`，FakeExecutor不会混入。
- 心跳已传输；端到端链路健康判定、当前状态下备用路线独立复核和真实切换仍未打通。
- 如下发后API断电到连审计都来不及记录，任务保留为需恢复，不会自动重新规划/下发；需人工核对执行端原始记录。

## HTTP接口

| 接口 | 用途 |
| --- | --- |
| `GET /api/dispatch/health` | 模式、传输、场景清单、直连活动任务 |
| `POST /api/dispatch/proposals` | `{ "scenario_id": "S1-01" }`，生成待审参数及5分钟有效摘要 |
| `POST /api/dispatch/tasks/{id}/confirm` | `{ "confirmed": true, "review_digest": "..." }`，原任务幂等确认 |
| `GET /api/dispatch/tasks/{id}` | 规划结果、ACK、独立执行状态、合成采样与最近30条M3审计；只读 |
| `POST /api/dispatch/tasks/{id}/abandon` | `{ "confirmed": true }`，仅直连模式明确结束合成任务 |

正式对象继续复用 `core.models`、`ValidationReport`、`ExecutionObservation`，执行状态另用 `agent.execution.ExecutionStatus`，不复制核心模型。

```powershell
.venv/Scripts/python.exe -m pytest tests/test_local_dispatch.py
$env:LOWALT_TEST_MQTT = '1'
.venv/Scripts/python.exe -m pytest tests/test_local_mqtt.py
```

本地API无登录鉴权，仅绑定回环地址，不能直接作为公网服务使用。

---

# services/api —— FastAPI 后端

**负责人：C**　**状态：🟡 本地可跑。未接 PostgreSQL / Redis，未做容器，未部署到华为云。**

验证边界跟仓库其余部分一样：**软件在环仿真（SITL）都还没接，这里更没有实飞。**
场景几何是 `scenarios/v0` 草稿，GeoJSON 自己标着 `is_simulated=true`、`status=draft`。

## 这个进程做什么

接收任务、读场景、调用规划器、把路线存下来。它不控制姿态，不生成电机指令，
也不在规划器没给数据时编造能耗或备降余量。

领域对象只用 `core/models.py` 里的 `Task`、`RiskSnapshot`、`RoutePlan`、
`DiversionMarginProfile`、`LandingSite`、`Position`。
`services/api/envelopes.py` 里的模型是 HTTP 信封（这次有没有拿到 RoutePlan、
余量算出来没有），不是第二套航线契约。

## 启动

```bash
python -m venv .venv
source .venv/bin/activate          # Windows：.venv\Scripts\activate
pip install -r requirements.txt

python -m services.api             # 127.0.0.1:8000
# 或者
uvicorn services.api.main:create_app --factory --host 127.0.0.1 --port 8000
```

默认把任务写到 `data/api.sqlite`（已 gitignore）。关掉进程再开，任务还在。
想要关掉就丢的存储：

```bash
STORAGE_BACKEND=memory python -m services.api
```

`memory` 是进程内的 SQLite `:memory:`，不是 Redis。环境变量样例在仓库根 `.env.example`。
复制成 `.env` 再填；`.env` 不会进仓库。本服务启动时会读它，且不覆盖已经存在的环境变量。

健康检查：

```bash
curl -s http://127.0.0.1:8000/health
```

`postgres.connected` 和 `redis.connected` 在这一版永远是 `false`。
`RDS_DSN`、`DATABASE_URL`、`DCS_HOST`、`REDIS_URL` 只是配置位：填了会显示 `configured=true`，
响应里不回显连接串。

交互式文档在 `/docs`。下面的表是契约，以它为准。

## 接口

| 方法 | 路径 | 请求 | 响应 | 说明 |
|---|---|---|---|---|
| GET | `/health` | — | 信封 | 契约版本、git commit、存储、规划入口、云配置位、M3 是否配置 |
| POST | `/tasks` | `Task` | `Task` | 201。重复 `task_id` 返回 409 |
| GET | `/tasks` | — | `Task[]` | 按创建顺序 |
| GET | `/tasks/{task_id}` | — | `Task` | 没有则 404 |
| GET | `/scenes/{scene_id}` | — | 场景信封 | 目前只有 `v0`。障碍和限制区是 GeoJSON 原文，备降点是 `LandingSite` |
| POST | `/tasks/{task_id}/snapshots` | `RiskSnapshot` | `RiskSnapshot` | 直接存调用方给的快照。时间必须带时区 |
| POST | `/tasks/{task_id}/snapshots/from-scene` | `{scene_id, active_zone_ids, occupied_site_ids}` | `{snapshot, ...}` | 用 v0 草稿生成快照。不点名的限制区不会变成“已经生效” |
| GET | `/tasks/{task_id}/snapshot` | — | `RiskSnapshot` | 最近一张 |
| GET | `/tasks/{task_id}/snapshots/{snapshot_id}` | — | `RiskSnapshot` | |
| POST | `/tasks/{task_id}/plan` | `{snapshot_id?, algorithm?}` | `{route, agent}` | 调规划器。`snapshot_id` 省略则用最近一张 |
| GET | `/tasks/{task_id}/routes` | — | 路线信封[] | |
| GET | `/tasks/{task_id}/routes/{route_id}` | — | 路线信封 | `route_id` 是 `v1`、`v2`… |
| GET | `/tasks/{task_id}/routes/{route_id}/margin` | — | 余量信封 | 有剖面才填数字；否则 `status=unavailable` 且 `profile=null` |

创建一条最小任务（坐标是测试值，不是机型参数）：

```bash
curl -s -X POST http://127.0.0.1:8000/tasks \
  -H 'content-type: application/json' \
  -d '{
    "task_id": "T-20261109-001",
    "origin": {"frame": "enu_m", "x_m": 150, "y_m": 150, "alt_m": 0, "alt_ref": "rel_takeoff"},
    "destination": {"frame": "enu_m", "x_m": 2650, "y_m": 2750, "alt_m": 30, "alt_ref": "rel_takeoff"},
    "payload_kg": 1,
    "vehicle_type": "placeholder",
    "initial_energy_wh": 100,
    "reserve_energy_wh": 20,
    "provenance": {
      "source": "demo",
      "version": "0",
      "captured_at": "2026-11-09T00:00:00+00:00",
      "is_simulated": true
    }
  }'
```

然后：

```bash
curl -s -X POST http://127.0.0.1:8000/tasks/T-20261109-001/snapshots/from-scene \
  -H 'content-type: application/json' \
  -d '{"scene_id":"v0","active_zone_ids":[]}'

curl -s -X POST http://127.0.0.1:8000/tasks/T-20261109-001/plan \
  -H 'content-type: application/json' \
  -d '{}'
```

`initial_energy_wh: 100` 是调用方写在任务单上的数。当前规划器不算能耗，
接口**不会**把它抄进 `energy_budget_wh`。

## 规划结果怎么读

当前默认入口是 `planner.astar:plan_scenario`（`astar_static`）。它只做几何可达：
避开建筑，以及快照里**已经生效**且带了区号的限制区。不判时限，不算能量，不做备降剪枝。

因此现在一次成功的规划是：

- `found=true` 时，`waypoints` 是平面航点，长度与直接调用 `plan_scenario` 一致。
- 端点沿用任务单上的 `Position`。中间点只有 A* 的平面坐标，`alt_m` 复制起点，
  仅为满足 `Position` 必填。`altitude_note` 写了这句话。这不是高度剖面。
- `route` 为 `null`，`route_plan_status=unavailable`。
  原因是组不成合法的 `RoutePlan`：缺 `energy_budget_wh`，而机型参数仍是 null，
  能量模型会拒绝计算。这里不填 0，也不另写一个能耗。
- `margin_status=unavailable`，`margin_detail` 以“未实现”开头，`margin_profile=null`。
  查询余量时 `min_margin_wh`、`negative_sample_count`、`is_feasible` 都是 null。
  空剖面的 `is_feasible` 会是 false，那表示“算过但不行”，所以不能拿来表示“还没算”。
- `is_simulated=true`。场景是草稿仿真。就算任务单把 `is_simulated` 写成 false，路线记录仍标仿真。
- `elapsed_ms` 只是这次搜索函数自己的耗时，不是端到端时延。
- `algorithm` 想写成 `astar_diversion` 也不会换成另一个算法。响应里会说明请求名未生效。

限制区的区号放在 `geometry.zone_id` 或 `geometry.properties.id`。
没有区号的多边形，当前入口不会拿去封控，响应的 `limitations` 会写明。
`effective_from` 还在未来的限制区不会被提前当成障碍；基线也不会做时间轴绕行，同样写在 `limitations`。
快照过了 `valid_until` 会 409，并且不会存一条路线。
经纬度任务直接 422，本服务不做坐标转换。

## 和 M2 怎么接

路由不直接 import `planner.astar`。唯一调用点是 `services/api/planner_adapter.py`。

```bash
PLANNER_ENTRY=模块:函数
```

留空则使用 `planner.astar:plan_scenario`。函数签名里出现这些名字就会被填上：
`task`、`snapshot`、`scenario`、`scene`。其余必填参数对不上时，接口 500，并说明缺什么，不猜。

返回值可以是：

- `PathResult`，或 `(PathResult, 栅格)`：当前基线就是这样。只有平面航点。
- `RoutePlan`：原样放进 `route`，不改航点和 `energy_budget_wh`。
- 带 `route` / `route_plan` 以及 `margin_profile`（或 `margin` / `diversion_margin`）属性的对象。
  剖面原样返回，采样点不改。

`planner/diversion.py` 已经在仓库里。本进程的默认入口仍是 `planner.astar:plan_scenario`，没有把 `PLANNER_ENTRY` 指到备降规划器。
所以现在查余量仍然是“未实现”。以后若把入口改过去，并且那个函数返回 `RoutePlan` 和 `DiversionMarginProfile`，查询路径不用改。
在改入口之前，不要把 HTTP 响应写成已经有剖面。

## 和 M3 怎么接

仓库里的 M3 在 `agent/`，由助手进程上的 `/api/dispatch` 调用（见本文前半）。
**这个独立进程不实现那套状态机**，也不会根据工具结果改路线。

预留的调用点只有一个：`services.api.agent_hook.invoke_task_agent`。
规划函数返回之后（包括“没有可行路线”）会调用它，传入：

```text
event=plan_completed, task_id, snapshot_id, route_id, found, algorithm
```

默认返回 `status=not_implemented`，`applied=false`。
另一组员把函数准备好以后：

```bash
AGENT_ENTRY=他们的模块:函数
```

本服务会调用该函数，然后**丢掉返回值**：不改路线、不改任务、不改快照，也不把文本当成校验结论。
调用失败时规划结果仍然返回，`agent.status=error`。
过期快照、缺快照、坐标系不对这些在进规划器之前就拒绝，不会去叫 M3。

`/health` 只说明入口有没有配置，不回显模块路径。规划响应里的 `agent.entry` 会写出路径，
所以不要把密钥放进 `AGENT_ENTRY`。

## 测试

```bash
python -m pytest
```

API 用例在 `tests/test_api.py`，用 FastAPI `TestClient`，存储用内存库，不读 `.env`。
其中一条会把桩规划器配到 `PLANNER_ENTRY` 上，确认 `RoutePlan` 和余量剖面被原样转发；
桩里的 `12.5` Wh 只存在于测试文件，服务代码里没有这个数。

## 这个独立进程明确没有的

下面这些在仓库其他模块里已经有，但 **不在 `services.api.main` 这条进程里**：

- 独立校验器（`validator/`）。本进程没有 `/verify`，也不会在 `checks` 里写一条 `passed=true`。
- 飞控下发、`PlanCommand` / `PlanAck`、遥测、回放导出（见 `edge/` 与 `/api/dispatch`）。
- 备降余量的真实采样。接口在，默认几何基线不产剖面。
- 由本进程去连 PostgreSQL、Redis、OBS、MQTT 或华为云。配置位只报告是否填写。
- 把 `eval/planners.py` 的 mock 数字接到 HTTP 上。那些数不能出现在效果描述里。
