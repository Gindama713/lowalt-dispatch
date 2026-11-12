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

`example_vehicle_compare.csv` 是 **示例机型** `scenarios/vehicles/example_not_real.yaml` 下的规划对照，不是冻结的参赛结果，也不是实飞。meta 里 `vehicle_is_example=true`，`git_commit` 为 `088b4f9`。`min_landing_margin=-1000000` 表示该采样点没有几何可达备降点，不是能量缺口。`astar_dynamic` 的 mock 仍然不入库。

这份 CSV 测于合并上游之前（栅格净空 20 m，且当时 S4-05 的任务单能量与现在的 `initial_energy_wh: 50` 不同）。合并后不要把表里的航程或余量当成当前代码的重跑结果。

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
