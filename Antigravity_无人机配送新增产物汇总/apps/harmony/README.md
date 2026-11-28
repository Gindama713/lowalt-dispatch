# HarmonyOS 手机端（第一期）

原生 HarmonyOS 应用，ArkTS + ArkUI 声明式，Stage 模型（UIAbility），Hvigor 工程，三方库走 ohpm。不使用 Flutter、React Native 或 ArkUI-X，也不使用 Map Kit。

这一期只对接仓库里的 FastAPI（默认端口 8000）。手机端可以看健康状态、任务、场景和航线，也可以提交任务单、从场景生成快照、请求规划。**不下发飞控或执行指令。**

界面是简体中文。坐标按局部 ENU 米绘制，不是经纬度。

## 工程结构

```text
apps/harmony/
  AppScope/                         应用名、包名、图标
  entry/src/main/ets/
    entryability/EntryAbility.ets   UIAbility 入口
    model/                          与 core/models.py、envelopes.py 对齐的类型和解析
    client/                         DataSource、MockDataSource、HttpDataSource、偏好设置、本地告警
    pages/                          七个页面
    view/                           顶部 MOCK/真实 角标、「仿真数据」提示、CR30 3D 旋转/拆解背景组件
  entry/src/main/resources/
    base/profile/network_config.json  明文 HTTP（局域网调试）
    rawfile/mock/*.json               示例数据，文件内 example_note 写明「示例」
    rawfile/drone3d/                  离线 CR30 3D 模型（cr30_lod1.glb，318 零件）与本地 Three.js/Draco 场景
  hvigor/hvigor-config.json5
  build-profile.json5               SDK 与空的 signingConfigs
  test/                             Node 类型检查、mock 行为测试、和真实接口的字段对照
```

数据层目录叫 `client`，不是 `data`。仓库根 `.gitignore` 会忽略任意名为 `data/` 的目录（那里是本地 SQLite）。

页面：

| 页面 | 做什么 |
|---|---|
| 首页 | `GET /health`，前台每 10 秒轮询，下拉刷新；入口到其他页 |
| 任务列表 | `GET /tasks`，下拉刷新，进入详情或新建 |
| 新建任务 | 任务单 `POST /tasks` → 场景 v0 `POST .../snapshots/from-scene` → `POST .../plan` |
| 任务详情 | 任务单、最新快照、航线版本、备降余量；「重新规划」「在地图看」 |
| 地图 | ArkUI Canvas，按 ENU 米画障碍、限制区、备降点和所选航线，可缩放、平移 |
| 告警 | 没有后端告警接口。规划 `found=false`、409 快照过期、请求失败或超时、`/health` 为 degraded，记在本机列表 |
| 设置 | Mock / 真实接口、API 地址、测试连接（直接打 `/health`）。用 Preferences 记住 |

顶部始终有数据源角标（`MOCK` 或 `真实接口`）、「仿真数据」提示以及 `3D背景：开/关` 快捷切换。场景和航线在服务端也会标成仿真。

## 3D 无人机背景（CR30 旋转与零件循环拆解）

- 资产来源：上游 `Gindama713/lowalt-dispatch` 的 `references/rea-city-flight/web/public/models/cr30_lod1.glb`（约 844 KB，内置 318 个带 `explodeDir` / `explodeDist` / `stagger` 元数据的零件）。
- 离线渲染：`view/Drone3DBackground.ets` 通过 `@kit.ArkWeb` 的 `onInterceptRequest` 将虚拟域 `https://local.aeris.app/drone3d/` 映射到 `rawfile/drone3d/`（含离线 Three.js 0.182 + GLTFLoader + DRACOLoader + Draco WASM），无需外网 CDN 即可运行。
- 动效与交互隔离：背景持续 360° 平稳旋转并按 12 秒周期循环执行「合拢 → 错峰零件爆炸拆解 → 悬停展示 → 复原」；底层 `Web` 设置 `HitTestMode.None` 与 `focusable(false)`，配合暗色遮罩与前景半透明卡片，确保点击、滚动、下拉刷新与地图手势完全不受影响。顶部栏和「设置」页均可随时开关 3D 背景。

## SDK 写法

以 DevEco Studio / HarmonyOS SDK **26.0.0 Release** 为准，不用 26.0.1 Beta。

`build-profile.json5`：

- `compileSdkVersion` / `targetSdkVersion`：`"26.0.0"`
- `compatibleSdkVersion`：`"5.0.2(14)"`
- `runtimeOS`：`"HarmonyOS"`
- `signingConfigs`：`[]`，产品上**不写** `signingConfig`

依据（2026-10 之后的官方说明）：

- 工程级 `build-profile.json5`：从 API 26.0.0 起，这三个 SDK 字段用字符串，例如 `"26.0.0"`。更早的 HarmonyOS 版本仍是 `"5.0.2(14)"` 这种写法。`runtimeOS` 为 HarmonyOS 时用字符串，而不是 OpenHarmony 的数字 API。
- 升级到 26.0.0 时，官方步骤是把已写明的 `compileSdkVersion` / `targetSdkVersion` 改成 `"26.0.0"`，`compatibleSdkVersion` 通常保持原来的最低安装版本。这里按第一期要求保持 `"5.0.2(14)"`，让包仍可能装到 HarmonyOS 5.0.2。官方示例里升级前的兼容版本是 `"5.0.0(12)"`，字段形态相同。
- `hvigor/hvigor-config.json5` 和工程级 `oh-package.json5` 的 `modelVersion` 都是 `"26.0.0"`，两边必须一致。官方对 DevEco Studio 26.0.0 的说明就是这个版本号。
- `signingConfig` 不填时，官方说明该产品不签名。因此没有证书、没有密码。

`network_config.json` 放在官方固定路径 `entry/src/main/resources/base/profile/network_config.json`，不挂到 `module.json5` 的 metadata。明文开关：

- `base-config.cleartextTrafficPermitted`：API 18 起
- `component-config` 里的 `"Network Kit": true`：API 20 起

Network Kit 从 API 18 起默认允许明文；目标 SDK 26 可以用组件级配置关掉它。这里显式打开，是为了局域网里的 `http://` 调试。公网应改成 `https`。兼容版本 5.0.2(14) 早于这些字段，旧系统不读这份组件配置。

权限：`ohos.permission.INTERNET`、`ohos.permission.GET_NETWORK_INFO`。后者只用来在首页显示当前是 Wi-Fi、蜂窝还是没有默认网络。

本机没有装上命令行工具，**没有用 hvigor 实际编过这个配置**。DevEco Studio 26.0.0 Release 打开后如果改写 `modelVersion` 或提示兼容版本字符串不合法，以 IDE 的修正为准，不要升到 26.0.1 Beta。

## 用 DevEco Studio 打开

1. 安装 **DevEco Studio 26.0.0 Release**（不要用 26.0.1 Beta）。
2. 打开目录 `apps/harmony`（不是仓库根目录）。
3. 等 ohpm / hvigor Sync 结束。IDE 可能会补上 `hvigor/hvigor-wrapper.js`，那是工具链文件，可以留在本机。
4. 签名：`File` → `Project Structure` → `Signing Configs`，勾选自动签名。证书、`.p12`、`.cer`、`.p7b` 和密码不要提交。
5. 连真机或模拟器后 Run。未签名的 HAP 不能当正式包安装；自动签名只留在你的电脑上。

命令行在装好 Command Line Tools 且设置 `DEVECO_HOME` 之后：

```bash
cd apps/harmony
ohpm install
codelinter
hvigorw --mode module -p product=default -p module=entry@default assembleHap
```

工程自带的 `hvigorw` 会优先调用 `hvigor/hvigor-wrapper.js`，否则转给 `$DEVECO_HOME/tools/hvigor/bin/hvigorw`。

## Mock 和真实接口

第一次启动默认是 **Mock**。种子在 `entry/src/main/resources/rawfile/mock/`，外层有 `example: true` 和带「示例」的 `example_note`，真正的接口字段在 `payload` 里。重新生成：

```bash
python apps/harmony/test/build_mock.py
```

设置页可以改成「真实接口」。API 地址默认是占位 `http://192.168.1.10:8000`，请改成手机实际能访问的主机。手机和后端是同 Wi-Fi 还是公网还没定，所以地址必须可改，并写在 Preferences（文件名 `lowalt_settings`）里。

- 模拟器访问本机服务时，常常要写电脑的局域网地址，而不是手机自己的 `127.0.0.1`。
- 「测试连接」总是请求输入框里的地址的 `GET /health`，即使当前数据源仍是 Mock。
- 真实进程：在仓库根目录执行 `STORAGE_BACKEND=memory python -m services.api`（默认 `127.0.0.1:8000`）。无鉴权。

Mock 的规划**不是** A*。终点落在已生效限制区多边形里时返回 `found=false`，原因文字与几何基线无解时一致；其他情况给一条三点示意折线。绕开障碍的航线只在真实接口里出现。`margin_status=unavailable` 时，`min_margin_wh`、`negative_sample_count`、`is_feasible` 保持 null，不用 0 代替。

## 已验证

在这台 Linux 环境里做了下面这些，都通过了。

数据层类型检查和 Mock 行为（TypeScript 5.6.3，`strict`，再由 Node 22 跑同一份解析代码）：

```bash
cd apps/harmony
node test/check.mjs
```

结果：`mock parse tests passed`。覆盖健康检查、任务、v0 场景（20 个障碍、R01–R04、L1–L4）、快照、示意航线长度、`found=false`、余量 null、422 的 `detail` 数组、重复任务 409、未知限制区 422、R04 内终点无路、过期快照 409 且不留下航线。

对照正在运行的 API：

```bash
STORAGE_BACKEND=memory API_HOST=127.0.0.1 API_PORT=8000 python -m services.api
python apps/harmony/test/compare_shapes.py http://127.0.0.1:8000
```

结果：`shape compare passed`。mock 的 health、task、scene、snapshot、route、agent、margin 字段集合与真实响应一致；`POST /tasks` 重复为 409 且 `detail` 是字符串；多余字段为 422 且 `detail` 是数组；手机端那种不带经纬度的任务体返回 201；过期快照可以入库，再规划返回 409；`from-scene` 点名 R01 / L2 后占用状态和区号正确；默认规划 `found=true`，余量 `unavailable` 且三个派生值为 null，`agent.applied` 为 false。

另外用 curl 取了真实响应，再用页面同一套解析函数读入：

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/scenes/v0
curl -sS -H 'content-type: application/json' -d '{}' \
  http://127.0.0.1:8000/tasks/T-20261109-001/plan
```

`/health` 与这次规划都是 HTTP 200。当时的规划结果是 `found=true`、`length_m=3764.406922210657`、283 个航点、`margin_status=unavailable`、`agent.applied=false`。解析测试通过。这个长度是规划器算出来的，不是 mock 折线。

## 没能验证

Command Line Tools 没有装上。官方下载页 `https://developer.huawei.com/consumer/cn/download/command-line` 在这台机器上返回 **403**，下载需要华为开发者账号，页面也要求登录后才能取 Linux 包（文件名类似 `commandline-tools-linux-x64-26.0.0.851.zip`）。因此下面几项**没有运行**：

- `ohpm install`
- `codelinter`
- `hvigorw assembleHap`
- 没有生成 `.hap`，也没有在模拟器或真机上打开界面

ArkTS 语法和 ArkUI 组件（Canvas 手势、Preferences、`@kit.NetworkKit`）没有经过华为编译器。Node 检查只覆盖 `model/` 和 `MockDataSource`，不覆盖页面和 HTTP 实现。HTTP 客户端没有在手机上打过局域网。

## 已知限制

- 地图是 Canvas 上的 ENU 米制草图，不是 Map Kit，也不能换成经纬度底图。
- Mock 不跑 `planner.astar`，不绕障碍。
- 真实接口里请求体的 `algorithm` 不会切换规划器；Mock 同样不切换，只把名字写进 `limitations`。
- 默认规划没有 `RoutePlan.energy_budget_wh`，也没有备降剖面。详情页按 `unavailable` 原样显示。
- 告警只存在手机里，最多 50 条，没有服务端列表。
- 快照历史没有列表接口。详情页只显示最新一张；更早的编号要自己记住。
- 明文 HTTP 是为了调试。不要把带 `cleartextTrafficPermitted: true` 的包当成可以上架的配置。
