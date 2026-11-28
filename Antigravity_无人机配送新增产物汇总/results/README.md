# results —— 评测产物

## 什么进仓库，什么不进

| 产物 | 进仓库？ | 理由 |
|---|---|---|
| `*_MOCK.csv` / `*_MOCK.meta.json` | ❌ 永不 | 占位数字。每次运行都会因时间戳产生 diff，而且一旦入库就有被截图引用的风险 |
| `*.csv`（`run_mode=real`） | ✅ 冻结版本时提交 | 这是证据，材料里的每个数字都要能追到具体文件 |
| `*.meta.json` | ✅ 与对应 CSV 一起提交 | 记录套件哈希、种子、算法、git commit，是"数字→唯一一次运行"的链条 |

## 命名约定

```
results/
  v0_MOCK.csv              # mock 跑出来的，本地看管道用，不入库
  v0_MOCK.meta.json
  frozen_v0.1.csv          # 冻结进材料的真实结果
  frozen_v0.1.meta.json
```

`example_vehicle_compare.csv` 是早期合并上游之前的历史快照（`git_commit: 088b4f9`，20 m 净空），保留仅作历史对照。

**最新冻结基线（2026-11-23，`git_commit: e9674ab`）**：

- `frozen_example_vehicle_e9674ab.csv` / `.meta.json` / `.profiles.json`
- 套件：`eval/scenarios/v0.yaml`（`suite_sha256: 081e37bec8a654a4…`，20 场景 × 3 种子 × 2 真算法 = 120 行）
- 示例机型：`scenarios/vehicles/example_not_real.yaml`（`vehicle_is_example=true`，非真实平台数据）
- 汇总：`astar_static` feasible **36/60**、returned **57/60**（含 21 条违规航线，其中负余量 **12** 条）、P50 3018 m；`astar_diversion` feasible **39/60**、returned **39/60**（**0 条违规、0 条负余量**）、P50 2832 m。
- 关键案例：`S2-03` 基线在 `t=+90 s` 侵入飞行中限制区判 `failed`，`astar_diversion` 主动安全绕行（3114.6 m → 3296.2 m，最小备降余量 **+54.03 Wh**）判 `delivered`；`S2-01` 基线在 `t=+131 s` 侵入 `R01` 判 `failed`，`astar_diversion` 剪枝 219 备降 + 157 禁飞状态拒发。

冻结时建议把 git commit 写进文件名或 meta，确保能回到当时的代码：

```bash
git rev-parse --short HEAD   # meta 里已经自动记录了
```

## 提醒

`min_landing_margin` 是核心指标。报告它的时候必须同时给出：

- 最小值（最危险的那个采样点）
- 负余量采样点数（进了红区多少次）
- 这些数是哪个套件哈希 + 哪个种子跑出来的

只报平均值没有意义——任务失败的代价不是平均值能表达的。
