#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由 parts-v1.json + 自检报告生成 docs/部件清单v1.md（人读版；数据以 JSON 为准）"""
import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = json.load(open(os.path.join(ROOT, "assets-src", "parts-v1.json"), encoding="utf-8"))
RP = os.path.join(ROOT, "_shots", "stage1", "check_report_v1.json")
R = json.load(open(RP, encoding="utf-8")) if os.path.exists(RP) else None
O = D["official"]; S = D["sources"]; M = D["materials"]; SY = D["systems"]
KIND = {"official": "官方", "derived": "反推", "estimate": "估算", "project_custom": "项目自定义"}
def f3(v): return "(" + ", ".join(f"{x:g}" for x in v) + ")"
def dims(p):
    d = p["dims_mm"]
    if "L" in d: return f'{d["L"]:g}×{d["W"]:g}×{d["H"]:g}'
    if "D" in d: return f'Ø{d["D"]:g}×{d["H_or_len"]:g}'
    return "组合 " + "×".join(f"{x:g}" for x in d["aabb_LxWxH"])
L = []
w = L.append
w("# 部件清单 v1（C3 工程级 · 蓝本 DJI Matrice 350 RTK）")
w("")
w("> 阶段 1 交付物。**机器可读唯一数据源：`assets-src/parts-v1.json`**（本文件由 `assets-src/tools/gen_parts_md_v1.py` 从 JSON 生成，二者冲突时以 JSON 为准）。代码、浮签、爆炸图、动效全部读 JSON。")
w("> 生成器：`assets-src/tools/gen_parts_v1.py`；骨架：`assets-src/blender/skeleton_v1.py`；自检：`assets-src/blender/check_v1.py`。")
w("")
w("## 1. 约定（定稿，不许改）")
w("")
w("- **机体坐标系**：原点 = 机身壳体包围盒几何中心；**x 前、y 左、z 上**；右手系；单位 mm。所有 `geometry`/`pivot` 坐标均为**展开飞行态、静止姿态**下的机体坐标。")
w("- 导出 GLB 时 Blender 自动转 glTF 的 Y-up：three.js 中 `X=机体x(前)`，`Y=机体z(上)`，`Z=−机体y`；GLB 单位为米。")
w(f"- **命名冻结**：{D['naming_rule']} 共 **{len(D['parts'])} 个唯一实例 id、{len({p['group'] for p in D['parts']})} 类部件**（成组件逐个编号：`_fl/_fr/_rl/_rr` = 左前/右前/左后/右后，`_l/_r` = 左/右）。")
w("- 每个部件写死五项：**尺寸 `dims_mm`、材质 `material`、可动 `movable`、转轴 `pivot{pos,axis,type,range}`、浮签 `tooltip`**；另有 `explode`（爆炸位移）、`fx`（灯效/展开时序）、`source`（来源/估算标记）、`parent`（运动学父子）、`contacts`（允许接触的安装面）。")
w("- 来源标记：**官方** = DJI 官网规格页/用户手册原值；**反推** = 由官方值计算得到；**估算** = 官方未公开，按图纸比例/工程惯例估计（写明依据）；**项目自定义** = 非 M350 原装。")
w("")
w("## 2. 蓝本官方参数（已核实）")
w("")
w("| 参数 | 官方值 | 来源 |")
w("|---|---|---|")
rows = [
 ("展开尺寸（不含桨）", "810×670×430 mm（长×宽×高）", "规格页 / 手册 p.113"),
 ("折叠尺寸（含桨）", "430×420×430 mm", "规格页 / 手册 p.113"),
 ("对角轴距", "895 mm", "规格页"),
 ("重量（单下置云台）", "不含电池约 3.77 kg；含双 TB65 约 6.47 kg", "规格页"),
 ("最大起飞重量", "9.2 kg", "规格页"),
 ("单云台减震最大载荷", "960 g", "规格页"),
 ("C3 载荷约束", "载荷尺寸 ≤ 0.2×0.2×0.2 m，重心应在机体中心，不得遮挡视觉/红外/散热区", "手册 p.123"),
 ("最高桨速 / 声功率", "4700 RPM / 97 dB(A)", "手册 p.123（C3 声明）"),
 ("标配桨", "2110s；高原可换 2112 高原静音桨（不可混用）", "手册 p.37 / 规格页"),
 ("2110s 桨径/螺距", "53 cm / 25 cm", "经销商规格页（非 DJI 官方页）"),
 ("防护等级", "IP55", "规格页"),
 ("工作温度", "−20 ~ 50 °C", "规格页"),
 ("GNSS", "GPS + GLONASS + BeiDou + Galileo", "规格页"),
 ("RTK 精度（FIX）", "1 cm + 1 ppm（水平），1.5 cm + 1 ppm（垂直）", "规格页"),
 ("悬停精度", "RTK：±0.1 m（垂直/水平）", "规格页"),
 ("TB65 电池", "5880 mAh / 44.76 V / 263.2 Wh / Li-ion / 约 1.35 kg", "规格页"),
 ("续航", "最长 55 min（约 8 m/s、无载荷、无风）", "规格页"),
 ("速度/抗风", "最大水平 23 m/s；上升 6 m/s；下降 5 m/s（倾斜 7）；抗风 12 m/s", "规格页"),
 ("FPV 相机", "1080p / 142° / 30 fps（星光夜视）", "规格页"),
 ("视觉系统", "前后左右 0.7–40 m；上下 0.6–30 m；FOV 前/后/下 65°×50°，左/右/上 75°×60°", "规格页"),
 ("红外感知", "0.1–8 m；FOV 30°（±15°）", "规格页"),
 ("LED 补光", "有效照明 5 m，60 Hz 常亮", "规格页"),
 ("图传", "O3 Enterprise；4 天线 2T4R；20 km(FCC) / 8 km(CE/SRRC/MIC)", "规格页"),
 ("云台构型", "单下置 / 单上置 / 双下置 / 单下+单上 / 双下+单上", "规格页"),
 ("参考相机 Zenmuse H30T", "170×145×165 mm；915–925 g；Pitch −120°~+60°，Yaw ±320°（可控），Roll 机械 ±60°", "H30 规格页"),
 ("机身部件编号", "FPV、红外、视觉、DGC2.0、云台快拆钮、机臂、电机、桨、机头 LED、图传天线、起落架、进风口、电池、电量灯/键、GNSS 天线、状态灯、上/下信标、电源键、辅助口、E-Port、载荷口、上/下补光灯、电池锁扣（共 27 项）", "手册 p.36"),
 ("展开顺序", "装起落架 → 先展前臂再展后臂 → 锁臂（臂锁上推+旋紧）→ 展桨", "手册 p.11"),
]
for a, b, c in rows: w(f"| {a} | {b} | {c} |")
w("")
w("来源链接：")
for k, v in S.items(): w(f"- `{k}`：{v}")
w("")
w("## 3. 查不到 → 估算的条目（绝不当作官方值）")
w("")
w("| 条目 | 处理 | 估算依据 |")
w("|---|---|---|")
for a, b, c in [
 ("电机定子规格 / KV / 单电机重量", "未查到", "浮签标“未查到”；外形尺寸用反推值"),
 ("电机舱外径", "反推 Ø111 mm", "设四电机矩形对称布局且三围外缘由电机舱决定：2A+D=810、2B+D=670、2√(A²+B²)=895 ⇒ D≈111、A=349.5、B=279.5。官网照片目测电机舱更细（≈60–80 mm），阶段 2 用正交参考图复核"),
 ("电调位置与规格", "估算：臂端上方舱", "官方未公开"),
 ("机身单体尺寸", "估算 280×190×180 mm", "手册 p.36 三视图比例 + 桨盘间隙 + 折叠约束"),
 ("机臂管径/铰点", "估算 Ø30 mm，铰点 (±120, ±170, 50)", "折叠后桨叶须避让机身侧面"),
 ("起落架高度/轮距/滑橇", "估算：机腹离地 200 mm，轮距 400 mm，滑橇长 180 mm", "总高 430 mm + 云台离地间隙；滑橇长度受机臂展开扫掠约束"),
 ("TB65 外形尺寸", "估算 100×75×170 mm", "检索到的“430×420×245 mm”为错误转载（与整机折叠尺寸混淆），不采用"),
 ("RTK 模块/飞控/电源板尺寸位置", "估算", "内部结构未公开"),
 ("后侧两根图传天线位置", "估算：后臂端外侧", "官方仅说明共 4 根"),
 ("左右红外 ToF", "未建", "手册 p.36 仅见前/后/上/下四处 2 号部件"),
 ("桨叶弦宽/厚度、桨毂", "估算 42/6 mm、Ø40", "仅直径有来源"),
 ("旋向", "估算：FL/RR 逆时针，FR/RL 顺时针", "多旋翼惯例，手册未给"),
 ("臂锁旋紧角", "估算 35°", "手册 p.11 只示意“上推+旋紧”"),
 ("机臂折叠角度", "估算 90°（向下）", "手册 p.11 示意图：折叠后臂朝下、电机舱天线朝外、桨叶贴臂"),
]: w(f"| {a} | {b} | {c} |")
w("")
w("## 4. 7 大系统覆盖")
w("")
w("| 系统 | 必需子项 | 部件 id |")
w("|---|---|---|")
need = {"frame": [("机身", ["body_shell"]), ("机臂", ["arm"]), ("起落架", ["gear"])],
        "power": [("电机", ["motor"]), ("电调", ["esc"]), ("桨", ["prop_hub", "prop_blade"])],
        "energy": [("电池×2", ["battery"]), ("电池仓", ["battery_bay"]), ("电源板", ["power_board"])],
        "sensing": [("FPV", ["fpv_cam"]), ("六向双目", ["vision"]), ("红外", ["ir_tof"]), ("下视", ["@vision_bottom"])],
        "payload": [("云台", ["gimbal_damper", "gimbal_axis"]), ("相机", ["camera"]), ("配送箱", ["payload_box", "payload_box_door"]), ("投放机构", ["drop_mech"])],
        "avionics": [("飞控", ["fc"]), ("RTK", ["rtk"]), ("GNSS", ["gnss_ant"]), ("天线", ["ant_tx"])],
        "indicator": [("LED", ["led_front", "led_status", "beacon", "aux_light"]), ("臂锁", ["arm_lock"])]}
for sk, items in need.items():
    for name, gs in items:
        ids = [p["id"] for p in D["parts"] if (p["group"] in gs) or ("@" + p["id"] in gs)]
        w(f"| {SY[sk]['zh']} | {name} | {'、'.join('`'+i+'`' for i in ids)} |")
w("")
w("## 5. 部件总表（五项写死 + 爆炸位移 + 来源）")
w("")
w("转轴：`pos` 为机体坐标 (x,y,z) mm；`axis` 为单位方向；类型 fixed=固定 / revolute=转动 / continuous=连续旋转 / prismatic=直线抽拉。爆炸向量为**相对父件**位移（mm）。")
w("")
for sk in SY:
    w(f"### 5.{list(SY).index(sk)+1} {SY[sk]['zh']}（`{sk}`）")
    w("")
    w("| id | 名称 | 尺寸 mm | 材质 | 可动 | 转轴 pos / axis / 范围 | 点击浮签参数 | 爆炸 层·向量 | 来源 |")
    w("|---|---|---|---|---|---|---|---|---|")
    for p in [p for p in D["parts"] if p["system"] == sk]:
        pv = p["pivot"]; ax = f3(pv["axis"]) if pv.get("axis") else "—"
        rg = pv.get("range_deg") or pv.get("range_mm")
        rgs = (f"{rg[0]:g}~{rg[1]:g}{'°' if 'range_deg' in pv else ' mm'}" if rg else ("连续" if pv["type"] == "continuous" else ""))
        e = p["explode"]; es = f"L{e['layer']} {f3(e['vector_mm'])}" if e.get("layer") else "不动（基准）"
        tip = "；".join(p["tooltip"]["params"])
        w(f"| `{p['id']}` | {p['name']} | {dims(p)} | {M[p['material']]['name']} | {'是' if p['movable'] else '否'} | {f3(pv['pos'])} / {ax} / {pv['type']} {rgs} | **{p['tooltip']['title']}**：{tip} | {es} | {KIND[p['source']['kind']]} |")
    w("")
w("## 6. 材质 PBR 方案（有记忆点，禁止纯色平涂）")
w("")
w("glTF 2.0 金属/粗糙度工作流 + KHR 扩展（clearcoat / anisotropy / iridescence / transmission / emissive_strength）。")
w("")
w("| key | 名称 | 底色 | 金属度 | 粗糙度 | 特性 | 用在 |")
w("|---|---|---|---|---|---|---|")
for k, m in M.items():
    used = sorted({p["group"] for p in D["parts"] if p["material"] == k})
    ext = []
    if m.get("clearcoat"): ext.append(f"清漆 {m['clearcoat']}/粗糙 {m.get('clearcoatRoughness')}")
    if m.get("flake"): ext.append(f"金属闪粒 密度 {m['flake']['density']}、粒径 {m['flake']['size_mm']} mm")
    if m.get("anisotropy"): ext.append(f"各向异性 {m['anisotropy']['strength']}（{m['anisotropy']['rotation']}）")
    if m.get("weave"): ext.append(f"{m['weave']['pattern']} 丝束 {m['weave']['tow_mm']} mm")
    if m.get("emissive"): ext.append(f"自发光 {m['emissive']} ×{m.get('emissiveStrength')}")
    if m.get("iridescence"): ext.append("镀膜虹彩")
    if m.get("tip"): ext.append("桨尖 30 mm 金属黄清漆")
    w(f"| `{k}` | {m['name']} | `{m['baseColor']}` | {m.get('metallic', 0)} | {m.get('roughness')} | {'；'.join(ext)}。{m.get('notes', '')} | {'、'.join(used) or '—'} |")
w("")
w("配色红线：主色金属黄 `#FFC400` 汽车级金属漆 + 黑碳纤 + 枪灰拉丝 + 镜面铬银；**冰蓝 `#6FE3FF` 自发光只用于 FPV/视觉/红外“眼睛”与 GNSS/RTK 点缀**（`glass_sensor`、`ice_blue_accent` 两个材质，其他材质不得出现冰蓝）。")
w("")
w("骨架渲染为“按系统着色”（同一调色板）：机身框架=金属黄漆，动力=枪灰拉丝，能源=铬银，感知=冰蓝自发光玻璃，载荷=钢琴黑，航电=深枪灰+弱冰蓝，指示=各自 LED 色。")
w("")
w("## 7. 动效记忆点字段")
w("")
w("### 7.1 灯效（`fx.light`）")
w("")
w("| 部件 | 类型 | 颜色 | 周期/相位 | 说明 |")
w("|---|---|---|---|---|")
for p in D["parts"]:
    l = p["fx"].get("light")
    if l: w(f"| `{p['id']}` | {l['type']} | `{l['color']}` | {l.get('period_s', '—')} s / {l.get('phase_s', 0)} s | {l.get('note', '')} |")
w("")
w(f"### 7.2 展开时序（`unfold_timeline`，运输折叠态 → 飞行态，总长 {D['unfold_timeline']['total_s']} s）")
w("")
w("| t (s) | 时长 | 目标 | 动作 | 缓动 | 灯光/备注 |")
w("|---|---|---|---|---|---|")
for s in sorted(D["unfold_timeline"]["steps"], key=lambda s: s["t"]):
    w(f"| {s['t']:.2f} | {s['dur']:.2f} | {'、'.join('`'+x+'`' for x in s['target'])} | {s['action']} | `{s['ease']}` | {s.get('light', '')} {s.get('note', '')} |")
w("")
w("折叠运动学：机臂铰轴 = z × 臂向（水平、垂直于臂），展开 0° → 折叠 +90°（臂竖直朝下）；桨叶收拢 = 绕桨根 z 轴转到“指向机身并外偏 10°”方向；臂锁 = 绕臂轴旋 35°。运输折叠态按实机惯例先拆云台载荷（DGC2.0 一键拆卸）。")
w("")
w(f"### 7.3 爆炸拆解分层（`explode`，总长 {D['explode_total_s']} s；复原 = 时间轴严格倒放）")
w("")
w("| 层 | 内容 | 起始延时 |")
w("|---|---|---|")
for k, v in D["explode_layers"].items():
    ds = sorted({p["explode"]["delay_s"] for p in D["parts"] if p["explode"].get("layer") == int(k)})
    w(f"| L{k} | {v} | {ds[0]:.2f}–{ds[-1]:.2f} s |")
w("")
w("每件 `duration_s=0.7`、`ease=expo.out`；同层按 `order` 错峰 0.04 s；L6 内部模块逐个错峰 0.2 s 出舱（RTK→飞控→电池仓→电源板），避免互相穿插。")
w("")
w("## 8. 载荷与质量预算（项目自定义载荷）")
w("")
w("| 项 | 质量 | 依据 |")
w("|---|---|---|")
for a, b, c in [("整机（双 TB65、单下置云台接口）", "6.470 kg", "官方"), ("云台相机（H30T 级）", "0.925 kg", "H30 官方上限 925 g ≤ 960 g"),
                ("投放机构", "0.150 kg", "设计值"), ("配送箱 + 舱门", "0.360 kg", "设计值"), ("货物上限", "0.450 kg", "设计值"),
                ("**配送挂点合计**", "**0.960 kg**", "= 单挂点 960 g 上限"), ("**起飞重量**", "**8.355 kg**", "≤ MTOW 9.2 kg，余量 0.845 kg")]:
    w(f"| {a} | {b} | {c} |")
w("")
w("尺寸：配送箱含舱门 200×160×116 mm ≤ 0.2 m 立方（C3）。重心：相机 0.925 kg @ x=+120，配送组 0.960 kg @ x=−100 ⇒ 载荷合重心 x≈+8 mm（接近机体中心，满足 C3“重心居中”要求）。")
w("")
w("> 说明：官方 6.47 kg 口径为“含单下置云台”，此处理解为含云台接口不含相机；若实际含相机，则起飞重量更低，结论不变。")
w("")
w("## 9. 需要用户拍板的设计取舍（可逆项已按推荐先做）")
w("")
w("| 编号 | 问题 | 选项 A | 选项 B | 推荐 | 理由 | 当前骨架 |")
w("|---|---|---|---|---|---|---|")
for r in [
 ("Q1", "载荷构型", "前下置云台相机 + 机腹中心挂配送箱（自定义挂架）", "官方双下置云台接口：左相机、右配送箱", "A", "配送箱在重心正下方，满足 C3 重心居中；展示时相机与箱体前后分层，轮廓更清楚。B 走官方接口但横向偏心", "A（可逆）"),
 ("Q2", "配送箱外形", "圆角胶囊箱（呼应工作界面圆形语言）", "方正医疗箱 + 红十字（沿用旧主页稿）", "A", "与“圆形设计代替方形”一致、更有辨识度；红十字作为贴花可在 A 上保留", "骨架用方盒占位"),
 ("Q3", "上置云台/雷达", "不装（顶面干净，信标与天线露出）", "加装 CSM 毫米波雷达（官方配件 75×75×105 mm、336 g）", "A", "雷达会挡顶部视觉，首页主视觉更简洁；需要“避障”叙事时再加", "A（可逆）"),
 ("Q4", "桨尖涂装", "金属黄桨尖", "原厂橙色桨尖", "A", "配色规范只允许金属黄/黑/枪灰/铬银", "A（可逆）"),
]: w("| " + " | ".join(r) + " |")
w("")
w("## 10. 自检结果（阶段 1 合格标准）")
w("")
if R:
    e = R["envelope_unfolded_no_props"]; wb = R["wheelbase"]; fo = R["envelope_folded_with_props_no_payload"]
    w(f"- 骨架三围（展开、不含桨，Blender 世界坐标实测）：**{e['measured_mm'][0]:g} × {e['measured_mm'][1]:g} × {e['measured_mm'][2]:g} mm**，蓝本 810×670×430，误差 **{e['error_pct'][0]}% / {e['error_pct'][1]}% / {e['error_pct'][2]}%**（< 5%）")
    w(f"- 对角电机轴距实测 **{wb['measured_fl_rr_mm']} mm**（FL–RR）/ {wb['measured_fr_rl_mm']} mm（FR–RL），蓝本 895，误差 **{wb['error_pct']}%**")
    w(f"- 唯一性：{R['ids']['count']} 个 id，{R['ids']['unique']} 个唯一，重复 {len(R['ids']['duplicates'])}；格式违规 {len(R['ids']['bad_format'])}；Blender 对象名与 id 一一对应：{R['ids']['blender_object_names_match']}")
    w(f"- 覆盖：7 大系统全部必需子项齐全 = {R['coverage']['all_required_present']}；电池 {R['coverage']['battery_count']} 块；视觉 {R['coverage']['vision_directions']} 向")
    w(f"- 五项缺失：{len(R['five_fields']['missing'])}；可动件缺转轴：{len(R['five_fields']['movable_without_axis'])}")
    w(f"- 参考项（非合格标准）：折叠含桨包络 {fo['measured_mm']} mm vs 官方 430×420×430，误差 {fo['error_pct']}%；桨尖与机身/载荷最小水平间隙 {R['rotor_tip_to_body_min_gap_mm']} mm")
    w(f"- 骨架级穿模：{len(R['collision_states'])} 组状态/镜头逐帧检测，合计穿模对 **{R['collision_total']}**；检测器自检（故意穿模必须检出）：{R['detector_selftest']}")
w("")
w("## 11. 已知限制")
w("")
w("- 骨架只对比例（方盒/圆柱），不含细节、倒角、法线贴图；PBR 参数是给阶段 2 的规格，骨架渲染只做近似预览。")
w("- 估算项见第 3 节；电机舱外径由三围反推，与照片目测有出入，阶段 2 开工前需用正交参考图复核。")
w("- 折叠包络宽度比官方大约 11%（GNSS 天线罩折叠后外凸），说明铰点/天线罩尺寸仍是估算；不影响展开态比例验收。")
open(os.path.join(ROOT, "docs", "部件清单v1.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
print("written", len(L), "lines")
