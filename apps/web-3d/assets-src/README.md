# assets-src · 阶段 1 骨架资产流水线

单一真源：`parts-v1.json`（由 `tools/gen_parts_v1.py` 生成；部件 id 定稿后冻结）。

| 步骤 | 命令（在 /workspace/lowalt-web 下执行） | 产出 |
|---|---|---|
| 1 生成部件表 | `python3 assets-src/tools/gen_parts_v1.py` | `assets-src/parts-v1.json` |
| 2 建骨架 + 渲染 | `$B -b --factory-startup -P assets-src/blender/skeleton_v1.py -- --only build,views,states,turntable,hero --samples 16` | `skeleton_v1.blend/.glb`、`_shots/stage1/*` |
| 3 自检 | `$B -b --factory-startup -P assets-src/blender/check_v1.py` | `_shots/stage1/check_report_v1.json` |
| 4 文档 | `python3 assets-src/tools/gen_parts_md_v1.py` | `docs/部件清单v1.md` |
| 5 三视图标注 | `python3 assets-src/tools/annotate_views_v1.py` | `_shots/stage1/view_*_dim.png` |
| 6 镜头预演 | `$B -b --factory-startup -P assets-src/blender/render_shots_v1.py -- --shot S1_reveal --samples 4`，然后执行 `python3 assets-src/tools/encode_shots_v1.py` | `_shots/stage1/shots/S*.mp4` |

`$B` = Blender 4.2.3 LTS，路径 `/opt/blender-dl/blender-4.2.3-linux-x64/blender`。
坐标约定：机体系，x 前、y 左、z 上；JSON 单位 mm；Blender 场景单位 m；导出 glTF 时转为 Y-up。
每个部件对应一个对象，对象名 = 部件 id，原点在铰点（pivot）。glTF 节点的 extras 里带 system、group、explode、pivot 等字段，供阶段 3 的 R3F 直接读取。
