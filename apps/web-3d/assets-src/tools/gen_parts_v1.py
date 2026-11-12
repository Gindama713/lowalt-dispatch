#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
部件清单 v1 生成器（唯一数据源）
输出：assets-src/parts-v1.json（机器可读，代码/浮签/爆炸图/动效共用）
机体坐标系：原点=机身中心（机身壳体包围盒几何中心），x 前、y 左、z 上，单位 mm，右手系。
所有几何均为“静止展开态”（arms unfolded, props in flight orientation）世界坐标。
"""
import json, math, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def v(*a): return [round(float(x), 2) for x in a]
def add(a, b): return [a[i] + b[i] for i in range(3)]
def sub(a, b): return [a[i] - b[i] for i in range(3)]
def mul(a, s): return [x * s for x in a]
def norm(a):
    l = math.sqrt(sum(x * x for x in a)); return [x / l for x in a]
def cross(a, b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def r(a, n=2): return [round(x, n) for x in a]

# ---------------- 官方参数（来源见 SOURCES） ----------------
OFFICIAL = {
    "unfolded_LWH_mm": [810, 670, 430],
    "folded_LWH_mm_with_props": [430, 420, 430],
    "diagonal_wheelbase_mm": 895,
    "mass_no_battery_kg": 3.77, "mass_2xTB65_kg": 6.47, "mtow_kg": 9.2,
    "single_gimbal_max_payload_g": 960,
    "payload_max_dims_mm_C3": [200, 200, 200],
    "max_prop_rpm": 4700, "sound_power_dBA": 97,
    "prop_std": "2110s（直径 53 cm / 螺距 25 cm）", "prop_high_alt": "2112 高原静音桨",
    "ip": "IP55", "op_temp_c": [-20, 50], "gnss": "GPS+GLONASS+BeiDou+Galileo",
    "rtk_accuracy": "1 cm + 1 ppm（水平），1.5 cm + 1 ppm（垂直）",
    "tb65": {"capacity_mAh": 5880, "voltage_V": 44.76, "energy_Wh": 263.2, "mass_kg": 1.35, "type": "Li-ion"},
    "fpv": {"res": "1080p", "fov_deg": 142, "fps": 30},
    "vision_range_m": {"fwd_back_lr": [0.7, 40], "up_down": [0.6, 30]},
    "vision_fov": {"fwd_back_down": "65°(H)×50°(V)", "lr_up": "75°(H)×60°(V)"},
    "ir_range_m": [0.1, 8], "ir_fov": "30°(±15°)",
    "aux_light": "有效照明距离 5 m，60 Hz 常亮",
    "transmission": "DJI O3 Enterprise，4 天线 2T4R，20 km(FCC)/8 km(CE/SRRC/MIC)",
    "max_flight_time_min": 55, "max_speed_ms": 23, "max_wind_ms": 12,
    "gimbal_configs": "单下置 / 单上置 / 双下置 / 单下置+单上置 / 双下置+单上置",
    "h30_ref": {"dims_mm": [170, 145, 165], "mass_g": "915–925", "ip": "IP54"},
}
SRC = {
    "spec": "https://enterprise.dji.com/matrice-350-rtk/specs",
    "manual": "https://dl.djicdn.com/downloads/matrice_350_rtk/Matrice_350_RTK_User_Manual_en.pdf",
    "manual_p36": "用户手册 p.36 Aircraft Overview 部件图（1–27 号部件）",
    "manual_c3": "用户手册 p.123 C3 Certification（最高桨速 4700 RPM、载荷尺寸 ≤0.2 m³ 立方、载荷重心居中）",
    "acc": "https://dl.djicdn.com/downloads/matrice-300/20230518RN/Accessory_Compatibility_List_for_M300_RTK_and_M350_RTK_EN.pdf",
    "prop": "https://ibtservices.nl/verticals/uav-drone-equipment/uav-payloads-accessories/dji-matrice-350-rtk-2110s-propellers/",
    "h30": "https://enterprise.dji.com/zenmuse-h30-series/specs",
    "photo": "https://www-cdn.djiits.com/cms/uploads/3f33b79fc054eaf64bd357bf287069f9@374*374.png（官网正视产品图，用于目测比例）",
}

# ---------------- PBR 材质预设（glTF 2.0 + KHR 扩展口径） ----------------
MATERIALS = {
  "paint_bumblebee": {"name": "大黄蜂金属黄·汽车级金属漆", "baseColor": "#FFC400", "metallic": 0.55, "roughness": 0.32,
      "clearcoat": 1.0, "clearcoatRoughness": 0.03, "flake": {"density": 0.6, "size_mm": 0.04, "normalStrength": 0.25, "color": "#FFE27A"},
      "ior": 1.5, "notes": "三层：底色金属漆 + 金属闪粒法线噪声（微米级各向随机法线）+ 清漆层；KHR_materials_clearcoat；闪粒用 3 层 tile 噪声法线贴图实现，禁止纯色平涂。"},
  "paint_black_gloss": {"name": "钢琴黑饰条漆", "baseColor": "#0B0B0C", "metallic": 0.0, "roughness": 0.18, "clearcoat": 1.0, "clearcoatRoughness": 0.02,
      "notes": "配送箱警示条/机身分色线；与黄漆形成大黄蜂分色。"},
  "carbon_weave": {"name": "黑色碳纤维 2×2 斜纹编织", "baseColor": "#121315", "metallic": 0.0, "roughness": 0.30, "clearcoat": 0.8, "clearcoatRoughness": 0.05,
      "anisotropy": {"strength": 0.6, "rotation": "沿丝束方向，经纬交替 ±45°"}, "weave": {"pattern": "2x2 twill", "tow_mm": 3.0},
      "notes": "法线+各向异性方向贴图做编织反光（KHR_materials_anisotropy），清漆层透出织纹。"},
  "gunmetal_brushed": {"name": "枪灰拉丝金属", "baseColor": "#4A4F55", "metallic": 1.0, "roughness": 0.34,
      "anisotropy": {"strength": 0.75, "rotation": "沿零件主轴（电机沿周向，臂沿轴向）"},
      "notes": "拉丝方向 = 零件主轴；粗糙度贴图加 0.30–0.40 细纹抖动。"},
  "chrome_mirror": {"name": "镜面铬银饰件", "baseColor": "#E9ECEF", "metallic": 1.0, "roughness": 0.04,
      "notes": "锁环、电机顶盖、桨毂、铰链销；依赖 HDR 环境反射才出效果。"},
  "glass_sensor": {"name": "传感器镀膜玻璃（眼睛）", "baseColor": "#05080C", "metallic": 0.0, "roughness": 0.02, "transmission": 0.6, "ior": 1.52,
      "iridescence": {"factor": 0.35, "ior": 1.3, "thickness_nm": [200, 400]},
      "emissive": "#6FE3FF", "emissiveStrength": 3.0,
      "notes": "冰蓝自发光只允许用于 FPV/视觉/红外‘眼睛’；镜头内圈冰蓝虹膜环，外圈铬银。"},
  "ice_blue_accent": {"name": "冰蓝 GNSS/RTK 点缀发光环", "baseColor": "#0E1A22", "metallic": 0.2, "roughness": 0.25,
      "emissive": "#6FE3FF", "emissiveStrength": 2.0, "notes": "仅 GNSS 天线罩底环、RTK 状态窗使用。"},
  "polymer_satin": {"name": "缎面工程塑料（深枪灰）", "baseColor": "#26292D", "metallic": 0.0, "roughness": 0.48,
      "notes": "电池壳、电调舱盖、天线罩、内部模块壳。"},
  "prop_composite": {"name": "碳纤增强桨叶 + 金属黄桨尖", "baseColor": "#16181B", "metallic": 0.0, "roughness": 0.38,
      "tip": {"baseColor": "#FFC400", "metallic": 0.55, "roughness": 0.3, "clearcoat": 1.0, "length_mm": 30},
      "notes": "原厂 2110s 为橙色桨尖，本项目按配色规范改金属黄（见待拍板 Q4）。"},
  "rubber_matte": {"name": "哑光橡胶", "baseColor": "#151515", "metallic": 0.0, "roughness": 0.88, "notes": "脚垫、减震球。"},
  "pcb_internal": {"name": "内部电路板（拆解可见）", "baseColor": "#0F2A1E", "metallic": 0.3, "roughness": 0.5,
      "notes": "仅爆炸图可见；铜箔用 metallic 1.0/roughness 0.3 贴图。"},
  "led_red": {"name": "红色 LED", "baseColor": "#300000", "emissive": "#FF2A1A", "emissiveStrength": 6.0, "metallic": 0, "roughness": 0.2},
  "led_green": {"name": "绿色 LED", "baseColor": "#002A0A", "emissive": "#22FF66", "emissiveStrength": 6.0, "metallic": 0, "roughness": 0.2},
  "led_white": {"name": "白色补光/信标", "baseColor": "#222222", "emissive": "#FFF4E0", "emissiveStrength": 8.0, "metallic": 0, "roughness": 0.2},
}

SYSTEMS = {
  "frame":     {"zh": "机身框架", "required": ["机身", "机臂", "起落架"], "skeleton_color": "#FFC400"},
  "power":     {"zh": "动力", "required": ["电机", "电调", "桨"], "skeleton_color": "#4A4F55"},
  "energy":    {"zh": "能源", "required": ["电池", "电池仓", "电源板"], "skeleton_color": "#E9ECEF"},
  "sensing":   {"zh": "感知", "required": ["FPV", "六向双目", "红外", "下视"], "skeleton_color": "#6FE3FF"},
  "payload":   {"zh": "载荷", "required": ["云台", "相机", "配送箱", "投放机构"], "skeleton_color": "#FF9A00"},
  "avionics":  {"zh": "航电", "required": ["飞控", "RTK", "GNSS", "天线"], "skeleton_color": "#2E6F8A"},
  "indicator": {"zh": "指示", "required": ["LED", "臂锁"], "skeleton_color": "#FF3B30"},
}

# ---------------- 布局（由官方三围+轴距反推） ----------------
# 电机（电机舱）中心 (±A, ±B, z)；若外缘由电机舱决定：2A+D=810, 2B+D=670, 2√(A²+B²)=895 → D≈111, A=349.5, B=279.5
D_POD = 111.0
A = (810 - D_POD) / 2   # 349.5
B = (670 - D_POD) / 2   # 279.5
Z_ARM = 50.0            # 机臂中心线高度
BODY = [280, 190, 180]  # 机身壳体 L×W×H（估算）
HINGE = {"fl": [120, 170, Z_ARM], "fr": [120, -170, Z_ARM], "rl": [-120, 170, Z_ARM], "rr": [-120, -170, Z_ARM]}
MOTOR_XY = {"fl": [A, B], "fr": [A, -B], "rl": [-A, B], "rr": [-A, -B]}
CORNER_ZH = {"fl": "左前", "fr": "右前", "rl": "左后", "rr": "右后"}
# 旋向（俯视）：对角同向；FL/RR 逆时针 CCW，FR/RL 顺时针 CW —— 估算（多旋翼惯例，手册未给）
SPIN = {"fl": "CCW", "rr": "CCW", "fr": "CW", "rl": "CW"}

parts = []
def P(**k):
    k.setdefault("parent", None); k.setdefault("internal", False); k.setdefault("contacts", [])
    k.setdefault("fx", {}); k.setdefault("explode", {"layer": 0, "vector_mm": [0, 0, 0]})
    parts.append(k); return k

def box(center, size, x_axis=None, z_axis=None):
    g = {"type": "box", "center": r(center), "size": r(size)}
    if x_axis: g["x_axis"] = r(x_axis, 4)
    if z_axis: g["z_axis"] = r(z_axis, 4)
    return g
def cyl(center, d, h, axis=(0, 0, 1)):
    return {"type": "cyl", "center": r(center), "d": d, "h": h, "axis": r(list(axis), 4)}

def src(kind, note, ref=None):
    s = {"kind": kind, "note": note}
    if ref: s["ref"] = ref
    return s
EST, OFF, DER = "estimate", "official", "derived"

# ===== 机身框架 =====
P(id="body_shell", name="机身壳体", system="frame", group="body_shell",
  geometry=[box([0, 0, 0], [BODY[0] - 40, BODY[1], BODY[2]]), box([0, 0, 0], [BODY[0], BODY[1] - 40, BODY[2]])]
           + [box([HINGE[c][0], HINGE[c][1] / abs(HINGE[c][1]) * (BODY[1] / 2 + HINGE[c][1] * (1 if HINGE[c][1] > 0 else -1)) / 2, Z_ARM], [30, abs(HINGE[c][1]) - BODY[1] / 2, 24]) for c in ("fl", "fr", "rl", "rr")],
  material="paint_bumblebee", movable=False,
  pivot={"pos": [0, 0, 0], "axis": None, "type": "fixed"},
  tooltip={"title": "机身壳体 · 中心舱", "params": ["IP55 防护（官方）", "工作温度 −20~50 °C（官方）", "空机 3.77 kg / 双 TB65 6.47 kg（官方）", "中心舱 280×190×180 mm，四角切角 + 4 个机臂肩座（估算）"]},
  source=src(EST, "官方未给机身单体尺寸；按手册 p.36 三视图比例（俯视长宽比≈1.25）与官网正视图目测，且需满足桨盘与机身角点间隙≥3 mm、折叠宽 420 mm 约束。", SRC["manual_p36"]))

for c in ["fl", "fr", "rl", "rr"]:
    h = HINGE[c]; m = [MOTOR_XY[c][0], MOTOR_XY[c][1], Z_ARM]
    d = norm(sub(m, h)); L = math.dist(h, m); t = cross([0, 0, 1], d)
    fold_axis = norm(t)          # 水平铰轴 ⊥ 臂向；绕 t 转 +90° 使臂向 d → −z（向下折）
    fold_angle = 90
    a0 = 22.0
    p_arm = P(id=f"arm_{c}", name=f"{CORNER_ZH[c]}机臂", system="frame", group="arm",
      geometry=[cyl(add(h, mul(d, (a0 + L) / 2)), 30, round(L - a0, 1), d)], material="carbon_weave", movable=True,
      pivot={"pos": r(h), "axis": r(fold_axis, 4), "type": "revolute", "range_deg": sorted([0, fold_angle]),
             "note": "水平折叠铰：轴 = z×臂向（水平、垂直于臂），展开 0° → 折叠 +90°（臂竖直向下，电机舱顶天线朝外，桨叶贴臂内侧向上收拢；依据手册 p.11 展开示意图）"},
      tooltip={"title": f"{CORNER_ZH[c]}机臂 · 碳纤维管", "params": [f"臂长（铰点→电机轴）{L:.1f} mm（反推）", "管径 Ø30 mm（估算）", "对角轴距 895 mm（官方）", "臂锁检测：未锁报警（官方功能）"]},
      source=src(DER, f"电机轴位置由官方 810×670 三围与 895 轴距反推；铰点位置与管径为估算；折叠方式依据手册 p.11 示意图（向下折、先前臂后后臂），铰点位置按折叠包络 430×420 反推。", SRC["spec"]),
      fold={"folded_angle_deg": fold_angle, "axis": r(fold_axis, 4)})
    p_arm["_d"] = d; p_arm["_t"] = t; p_arm["_L"] = L

    M = [m[0], m[1], 5.0]
    P(id=f"motor_{c}", name=f"{CORNER_ZH[c]}电机", system="power", group="motor", parent=f"arm_{c}", contacts=[f"arm_{c}"],
      geometry=[cyl(M, D_POD, 60)], material="gunmetal_brushed", movable=True,
      pivot={"pos": r([m[0], m[1], 5.0]), "axis": [0, 0, -1] if SPIN[c] == "CCW" else [0, 0, 1], "type": "continuous",
             "note": f"倒置安装于臂端下方，转子绕 z 轴（俯视 {SPIN[c]}，旋向估算）"},
      tooltip={"title": f"{CORNER_ZH[c]}动力电机", "params": ["最高桨速 4700 RPM（官方 C3 声明）", f"俯视旋向 {SPIN[c]}（估算）", "电机舱外径 Ø111 mm（由三围反推）", "定子规格：未查到"]},
      source=src(DER, "外径由官方三围反推（假设三围外缘由电机舱决定）；官网照片目测电机舱更细（≈60–80 mm），阶段 2 用正交参考图复核。倒置安装依据手册 p.36 及官网正视图（桨位于臂下方）。", SRC["manual_p36"]))
    P(id=f"esc_{c}", name=f"{CORNER_ZH[c]}电调", system="power", group="esc", parent=f"arm_{c}", contacts=[f"arm_{c}", f"motor_{c}"],
      geometry=[cyl([m[0], m[1], 82.0], 64, 34)], material="polymer_satin", movable=False,
      pivot={"pos": r([m[0], m[1], 65.0]), "axis": None, "type": "fixed"},
      tooltip={"title": f"{CORNER_ZH[c]}电调舱", "params": ["FOC 电调（类型估算）", "位置：臂端上方舱（估算）", "输入：12S 电池母线 44.76 V（官方电池电压）"]},
      source=src(EST, "官方未公开电调位置与规格；按臂端上方舱体位置估算。"))
    hub_c = [m[0], m[1], -33.0]
    P(id=f"prop_{c}", name=f"{CORNER_ZH[c]}桨毂", system="power", group="prop_hub", parent=f"motor_{c}", contacts=[f"motor_{c}"],
      geometry=[cyl(hub_c, 40, 16)], material="chrome_mirror", movable=True,
      pivot={"pos": r([m[0], m[1], -25.0]), "axis": [0, 0, -1] if SPIN[c] == "CCW" else [0, 0, 1], "type": "continuous", "note": "随电机转子旋转"},
      tooltip={"title": f"{CORNER_ZH[c]}桨毂 · 2110s", "params": ["2110s 标配桨（官方）", "直径 53 cm / 螺距 25 cm（经销商规格页）", "H2.5 内六角固定、螺纹胶 243（官方）", "可换 2112 高原静音桨（官方）"]},
      source=src(OFF, "桨型号官方；直径/螺距来自经销商页；桨毂尺寸估算。", SRC["prop"]))
    for bi, (bn, sgn, zc) in enumerate([("a", 1, -30.0), ("b", -1, -37.0)]):
        bd = mul(t, sgn); root = add(hub_c[:2] + [zc], mul(bd, 20))
        center = add(root, mul(bd, 122.5))
        s_out = 1 if t[1] * d[1] > 0 else -1; beta = math.radians(10)
        stow = (-math.cos(beta) * d[0] + s_out * math.sin(beta) * t[0], -math.cos(beta) * d[1] + s_out * math.sin(beta) * t[1])   # 收桨：叶尖指向机身方向并外偏 10°（折叠后叶片上端外倾，避让机身侧面）
        ang_now = math.atan2(bd[1], bd[0]); ang_stow = math.atan2(stow[1], stow[0])
        da = (math.degrees(ang_stow - ang_now) + 540) % 360 - 180
        P(id=f"prop_{c}_blade_{bn}", name=f"{CORNER_ZH[c]}桨叶{bn.upper()}", system="power", group="prop_blade", parent=f"prop_{c}", contacts=[f"prop_{c}", f"motor_{c}"],
          geometry=[box([center[0], center[1], zc], [245, 42, 6], x_axis=bd)], material="prop_composite", movable=True,
          pivot={"pos": r([root[0], root[1], zc]), "axis": [0, 0, 1], "type": "revolute", "range_deg": sorted([0, round(da, 1)]),
                 "note": "桨叶根部折叠铰（2110s 为可折叠桨），收桨态两叶指向机身并外偏 10°，上下错层 7 mm"},
          tooltip={"title": f"{CORNER_ZH[c]}桨叶 {bn.upper()}", "params": ["2110s 可折叠桨叶（官方型号）", "半径 265 mm（53 cm 直径/2）", "桨尖金属黄饰（项目涂装）"]},
          source=src(DER, "长度由官方 53 cm 直径推得；弦宽 42 mm、厚 6 mm 为估算。", SRC["prop"]),
          fold={"stowed_angle_deg": round(da, 1)})

    # 航电/指示 on pods
    if c in ("fl", "fr"):
        P(id=f"ant_tx_{c}", name=f"{CORNER_ZH[c]}图传天线", system="avionics", group="ant_tx", parent=f"arm_{c}", contacts=[f"esc_{c}"],
          geometry=[cyl([m[0], m[1], 119.5], 16, 41)], material="polymer_satin", movable=False,
          pivot={"pos": r([m[0], m[1], 99.0]), "axis": None, "type": "fixed"},
          tooltip={"title": f"{CORNER_ZH[c]}图传天线 · O3 Enterprise", "params": ["4 天线 2T4R（官方）", "最远 20 km FCC / 8 km CE（官方）", "Wi-Fi 6 / 2.4·5.1·5.8 GHz（官方）"]},
          source=src(EST, "前臂端竖立天线位置依据手册 p.36 第 10 号部件；尺寸估算。", SRC["manual_p36"]))
    else:
        P(id=f"gnss_ant_{c}", name=f"{CORNER_ZH[c]}GNSS 天线罩", system="avionics", group="gnss_ant", parent=f"arm_{c}", contacts=[f"esc_{c}"],
          geometry=[cyl([m[0], m[1], 115.0], 62, 32)], material="ice_blue_accent", movable=False,
          pivot={"pos": r([m[0], m[1], 99.0]), "axis": None, "type": "fixed"},
          tooltip={"title": f"{CORNER_ZH[c]}GNSS/RTK 天线", "params": ["GPS+GLONASS+BeiDou+Galileo（官方）", "RTK FIX 1 cm+1 ppm 水平 / 1.5 cm+1 ppm 垂直（官方）", "双天线测向（估算）"]},
          source=src(EST, "后臂端蘑菇罩位置依据手册 p.36 第 16 号部件；尺寸估算。", SRC["manual_p36"]),
          fx={"light": {"type": "breath", "color": "#6FE3FF", "period_s": 3.0, "phase_s": 0.0 if c == "rl" else 1.5, "note": "RTK FIX 时冰蓝慢呼吸；未 FIX 时快闪 0.5 s"}})
        out = add([m[0], m[1], 0], mul(d, 44))
        P(id=f"ant_tx_{c}", name=f"{CORNER_ZH[c]}图传天线", system="avionics", group="ant_tx", parent=f"arm_{c}", contacts=[f"motor_{c}"],
          geometry=[cyl([out[0], out[1], 87.5], 14, 105)], material="polymer_satin", movable=False,
          pivot={"pos": r([out[0], out[1], 35.0]), "axis": None, "type": "fixed"},
          tooltip={"title": f"{CORNER_ZH[c]}图传天线 · O3 Enterprise", "params": ["4 天线 2T4R（官方）", "后侧天线位置：未查到（估算）"]},
          source=src(EST, "官方仅说明共 4 根图传天线；后侧两根具体位置未查到，估算置于后臂端外侧。", SRC["spec"]))
    led_c = add([m[0], m[1], 0], mul(d, 45))
    is_front = c in ("fl", "fr")
    P(id=f"led_{c}", name=f"{CORNER_ZH[c]}{'机头灯' if is_front else '状态指示灯'}", system="indicator", group="led_front" if is_front else "led_status",
      parent=f"arm_{c}", contacts=[f"motor_{c}"],
      geometry=[box([led_c[0], led_c[1], 20.0], [14, 24, 12], x_axis=d)], material="led_red" if is_front else "led_green", movable=False,
      pivot={"pos": r([led_c[0], led_c[1], 20.0]), "axis": None, "type": "fixed"},
      tooltip={"title": f"{CORNER_ZH[c]}{'机头 LED' if is_front else '飞行器状态指示灯'}",
               "params": (["上电未起桨：常亮红（官方）", "起桨后：红绿交替闪（官方）"] if is_front else ["指示飞控/RTK/电量状态（官方，详见手册指示灯表）"])},
      source=src(EST, "位置依据手册 p.36 第 9/17 号部件；尺寸估算。", SRC["manual_p36"]),
      fx={"light": {"type": "sequence", "color": "#FF2A1A" if is_front else "#22FF66", "on_arm_lock": True,
                    "note": "展开锁定瞬间点亮：先 120 ms 白闪，再转本色常亮"}})
    sleeve_c = add(h, mul(d, 22))
    P(id=f"arm_lock_{c}", name=f"{CORNER_ZH[c]}臂锁", system="indicator", group="arm_lock", parent=f"arm_{c}", contacts=[f"arm_{c}", "body_shell"],
      geometry=[cyl(sleeve_c, 42, 36, d)], material="chrome_mirror", movable=True,
      pivot={"pos": r(sleeve_c), "axis": r(d, 4), "type": "revolute", "range_deg": [0, 35], "note": "旋套锁：绕臂轴旋 35° 锁紧（角度估算）"},
      tooltip={"title": f"{CORNER_ZH[c]}机臂锁扣", "params": ["臂锁未锁检测与告警（官方功能）", "旋紧角 35°（估算）"]},
      source=src(EST, "臂锁检测为官方功能描述；旋套形式与角度估算（官网正视图可见臂根套筒）。", SRC["manual"]))

for side, sy in (("l", 1), ("r", -1)):
    GT = 80.0; GF = 200.0
    top = [0, GT * sy, -90]; foot = [0, GF * sy, -270]
    dd = norm(sub(foot, top)); Ls = math.dist(top, foot)
    P(id=f"gear_{side}", name=f"{'左' if sy > 0 else '右'}起落架", system="frame", group="gear",
      geometry=[cyl(mul(add(top, foot), 0.5), 22, round(Ls, 1), dd), cyl([0, GF * sy, -279], 22, 180, (1, 0, 0))],
      material="carbon_weave", movable=False, pivot={"pos": top, "axis": None, "type": "fixed", "note": "快拆插接（官方：对齐红标插入后旋锁）"},
      tooltip={"title": f"{'左' if sy > 0 else '右'}起落架", "params": ["快拆式（官方安装说明）", "离地净高：机腹至地面 200 mm（估算）", "滑橇长 180 mm、轮距 400 mm（估算）"]},
      source=src(EST, "形态依据手册 p.36 第 11 号部件与官网正视图；尺寸按总高 430 mm 与云台离地间隙估算。", SRC["manual_p36"]))

# ===== 能源 =====
for side, sy in (("l", 1), ("r", -1)):
    P(id=f"battery_{side}", name=f"{'左' if sy > 0 else '右'} TB65 电池", system="energy", group="battery", parent="body_shell", contacts=["body_shell", "battery_bay"],
      geometry=[box([-60, 50 * sy, 30], [100, 75, 170])], material="polymer_satin", movable=True,
      pivot={"pos": [-60, 50 * sy, -55], "axis": [0, 0, 1], "type": "prismatic", "range_mm": [0, 220], "note": "沿 +z 竖直抽出（插拔轴）"},
      tooltip={"title": "TB65 智能飞行电池", "params": ["5880 mAh / 44.76 V / 263.2 Wh（官方）", "Li-ion，单块约 1.35 kg（官方）", "工作温度 −20~50 °C，低温自加热（官方）", "支持热插拔（官方）", "外形 100×75×170 mm（估算）"]},
      source=src(EST, "电性能与重量官方；外形尺寸未查到（检索到的 430×420×245 mm 为错误转载，不采用），按 12S 锂电体积与机身比例估算。", SRC["spec"]),
      fx={"light": {"type": "level_bar", "color": "#22FF66", "note": "后端电量格 4 灯自下而上依次点亮，每格 80 ms"}})
P(id="battery_bay", name="电池仓", system="energy", group="battery_bay", parent="body_shell", internal=True, contacts=["body_shell", "battery_l", "battery_r"],
  geometry=[box([-65, 0, 15], [130, 190, 140])], material="gunmetal_brushed", movable=False, pivot={"pos": [-65, 0, 15], "axis": None, "type": "fixed"},
  tooltip={"title": "双电池仓 · 电池锁扣", "params": ["双电池并联冗余（官方：TB65 双电池系统）", "后部电池锁扣（官方 p.36 第 25 号）"]},
  source=src(EST, "仓体位置依据手册后视图（电量指示 14/15、锁扣 25 位于后部）；尺寸估算。", SRC["manual_p36"]))
P(id="power_board", name="电源管理板", system="energy", group="power_board", parent="body_shell", internal=True, contacts=["body_shell"],
  geometry=[box([45, 0, -70], [120, 110, 8])], material="pcb_internal", movable=False, pivot={"pos": [45, 0, -70], "axis": None, "type": "fixed"},
  tooltip={"title": "电源分配板 PDB", "params": ["12S 母线分配至 4 路电调（估算）", "为载荷口/E-Port 供电（官方接口存在，功率未查到）"]},
  source=src(EST, "内部结构未公开，按常规多旋翼布局估算。"))

# ===== 感知 =====
P(id="fpv_cam", name="夜视 FPV 相机", system="sensing", group="fpv_cam", parent="body_shell", contacts=["body_shell"],
  geometry=[cyl([149, 0, 20], 34, 18, (1, 0, 0))], material="glass_sensor", movable=False, pivot={"pos": [140, 0, 20], "axis": None, "type": "fixed"},
  tooltip={"title": "星光级 FPV 相机", "params": ["1080p / 30 fps（官方）", "FOV 142°（官方）", "低照度优化（官方）"]},
  source=src(EST, "参数官方；位置依据手册 p.36 第 1 号部件（机头中央）；尺寸估算。", SRC["manual_p36"]),
  fx={"light": {"type": "breath", "color": "#6FE3FF", "period_s": 2.4, "phase_s": 0.0, "note": "主‘眼睛’：唤醒时 0→100% 0.6 s，随后呼吸"}})
faces = {
  "front": ([147, 0, 62], [14, 150, 34], [1, 0, 0], "前"), "rear": ([-147, 0, 62], [14, 150, 34], [-1, 0, 0], "后"),
  "left": ([30, 99, 40], [130, 8, 34], [0, 1, 0], "左"), "right": ([30, -99, 40], [130, 8, 34], [0, -1, 0], "右"),
  "top": ([95, 0, 96], [60, 150, 12], [0, 0, 1], "上"), "bottom": ([40, 0, -96], [34, 150, 12], [0, 0, -1], "下"),
}
eye_phase = {"front": 0.0, "left": 0.2, "right": 0.2, "top": 0.4, "bottom": 0.4, "rear": 0.6}
for k, (cc, sz, n, zh) in faces.items():
    rng = "0.6–30 m" if k in ("top", "bottom") else "0.7–40 m"
    fov = "65°(H)×50°(V)" if k in ("front", "rear", "bottom") else "75°(H)×60°(V)"
    piv = sub(cc, mul(n, sz[[0, 1, 2][[abs(x) for x in n].index(1)]] / 2))
    P(id=f"vision_{k}", name=f"{zh}视双目视觉" + ("（下视）" if k == "bottom" else ""), system="sensing", group="vision", parent="body_shell", contacts=["body_shell"],
      geometry=[box(cc, sz)], material="glass_sensor", movable=False, pivot={"pos": r(piv), "axis": None, "type": "fixed", "normal": n},
      tooltip={"title": f"{zh}视双目视觉" + ("·下视定位/降落保护" if k == "bottom" else ""), "params": [f"测距 {rng}（官方）", f"FOV {fov}（官方）", "工作环境：纹理丰富、照度 >15 lux（官方）"]},
      source=src(EST, "参数官方；安装面依据手册 p.36 第 3 号部件；模块尺寸估算。", SRC["manual_p36"]),
      fx={"light": {"type": "breath", "color": "#6FE3FF", "period_s": 2.4, "phase_s": eye_phase[k], "note": "眼部波次：前→左右→上下→后，相位差 0.2 s"}})
ir = {"front": ([146, 0, -20], [12, 50, 18], [1, 0, 0], "前"), "rear": ([-146, 0, -20], [12, 50, 18], [-1, 0, 0], "后"),
      "top": ([48, 0, 95], [30, 40, 10], [0, 0, 1], "上"), "bottom": ([10, 0, -95], [16, 40, 10], [0, 0, -1], "下")}
for k, (cc, sz, n, zh) in ir.items():
    P(id=f"ir_tof_{k}", name=f"{zh}向红外 ToF", system="sensing", group="ir_tof", parent="body_shell", contacts=["body_shell"],
      geometry=[box(cc, sz)], material="glass_sensor", movable=False, pivot={"pos": r(cc), "axis": None, "type": "fixed", "normal": n},
      tooltip={"title": f"{zh}向红外感知", "params": ["测距 0.1–8 m（官方）", "FOV 30°（±15°）（官方）", "适用：大尺寸漫反射障碍、反射率 >10%（官方）"]},
      source=src(EST, "参数官方；手册 p.36 第 2 号部件见于前/后/上/下四面（左右未见，未建）；尺寸估算。", SRC["manual_p36"]),
      fx={"light": {"type": "scan_pulse", "color": "#6FE3FF", "period_s": 1.2, "note": "细环脉冲，仅光效扫描镜头使用"}})

# ===== 载荷 =====
GX = 120.0; CZ = -222.0
P(id="gimbal_damper", name="云台减震座 DGC2.0", system="payload", group="gimbal_damper", parent="body_shell", contacts=["body_shell"],
  geometry=[box([GX, 0, -105], [80, 80, 30])], material="gunmetal_brushed", movable=False, pivot={"pos": [GX, 0, -90], "axis": None, "type": "fixed"},
  tooltip={"title": "DJI Gimbal Connector v2.0", "params": ["单云台减震最大载荷 960 g（官方）", "一键拆卸按钮（官方 p.36 第 5 号）", "支持单下/单上/双下等 5 种构型（官方）"]},
  source=src(EST, "接口官方；尺寸估算。", SRC["manual_p36"]))
P(id="gimbal_yaw", name="云台航向轴", system="payload", group="gimbal_axis", parent="gimbal_damper", contacts=["gimbal_damper"],
  geometry=[cyl([GX, 0, -130], 50, 20)], material="gunmetal_brushed", movable=True,
  pivot={"pos": [GX, 0, -120], "axis": [0, 0, 1], "type": "revolute", "range_deg": [-320, 320]},
  tooltip={"title": "云台 Yaw 轴", "params": ["可控 ±320°（H30 官方）", "增稳精度 悬停 ±0.002° / 飞行 ±0.004°（H30 官方）"]},
  source=src(EST, "运动范围取蓝本相机 Zenmuse H30 官方值；几何估算。", SRC["h30"]))
P(id="gimbal_roll", name="云台横滚臂", system="payload", group="gimbal_axis", parent="gimbal_yaw", contacts=["gimbal_yaw"],
  geometry=[box([GX - 38.5, 0, -146], [57, 30, 10]), box([GX - 71, 0, -195.5], [6, 120, 89]), box([GX - 31, 56, CZ], [82, 8, 20]), box([GX - 31, -56, CZ], [82, 8, 20])],
  material="gunmetal_brushed", movable=True,
  pivot={"pos": [GX, 0, CZ], "axis": [1, 0, 0], "type": "revolute", "range_deg": [-60, 60], "note": "横滚轴过相机中心"},
  tooltip={"title": "云台 Roll 轴", "params": ["机械范围 ±60°（H30 官方）"]},
  source=src(EST, "范围官方；U 形臂几何估算。", SRC["h30"]))
P(id="camera_payload", name="云台相机（H30T 级）", system="payload", group="camera", parent="gimbal_roll", contacts=["gimbal_roll"],
  geometry=[box([GX, 0, CZ], [96, 96, 80]), cyl([GX + 54, 0, CZ], 56, 12, (1, 0, 0))], material="gunmetal_brushed", movable=True,
  pivot={"pos": [GX, 0, CZ], "axis": [0, 1, 0], "type": "revolute", "range_deg": [-120, 60], "note": "Pitch 轴；正值抬头"},
  tooltip={"title": "五合一云台相机（参考 Zenmuse H30T）", "params": ["整机 170×145×165 mm / 915–925 g（H30 官方）", "40MP 1/1.8″ 变焦 + 48MP 广角（官方）", "1280×1024 红外（H30T 官方）", "激光测距 3–3000 m（官方）", "Pitch −120°~+60°（官方）"]},
  source=src(OFF, "参考载荷为 Zenmuse H30T（M350 兼容列表内）；本骨架相机头 100×100×84 为外形分解估算，整机外包络与官方 170×145×165 量级一致。", SRC["h30"]))
P(id="drop_mech", name="投放机构（电磁挂钩）", system="payload", group="drop_mech", parent="body_shell", contacts=["body_shell", "payload_box"],
  geometry=[box([-100, 0, -107.5], [120, 100, 35])], material="gunmetal_brushed", movable=True,
  pivot={"pos": [-100, 0, -125], "axis": [0, 0, -1], "type": "prismatic", "range_mm": [0, 0], "note": "释放：挂钩舌片绕 y 轴转 30°（子件，阶段 2 细化）；箱体可整体脱钩"},
  tooltip={"title": "投放机构 · 项目自定义载荷", "params": ["电磁挂钩 + 舱门联动（项目设计）", "自重 150 g（设计值）", "挂点位于机体重心正下方（满足 C3 载荷重心居中要求）"]},
  source=src("project_custom", "项目自定义载荷，非 M350 原装；遵循手册 C3 声明：载荷 ≤0.2 m 立方、重心居中。", SRC["manual_c3"]))
P(id="payload_box", name="应急配送箱", system="payload", group="payload_box", parent="drop_mech", contacts=["drop_mech", "payload_box_door"],
  geometry=[box([-100, 0, -179], [200, 160, 108])], material="paint_bumblebee", movable=True,
  pivot={"pos": [-100, 0, -125], "axis": [0, 0, -1], "type": "prismatic", "range_mm": [0, 120], "note": "脱钩下坠方向（演示动画用）"},
  tooltip={"title": "应急配送箱 · 项目自定义载荷", "params": ["外形 200×160×116 mm（含门，≤200 mm 立方，满足 C3 尺寸）", "空箱 300 g + 舱门 60 g（设计值）", "最大货重 450 g（设计值）", "箱+门+货+投放机构 = 960 g ≤ 单挂点 960 g"]},
  source=src("project_custom", "项目自定义载荷；外形选项见待拍板 Q2（推荐 A 圆角胶囊箱，骨架阶段以方盒代替）。", SRC["manual_c3"]))
P(id="payload_box_door", name="配送箱投放舱门", system="payload", group="payload_box_door", parent="payload_box", contacts=["payload_box"],
  geometry=[box([-100, 0, -237], [196, 156, 8])], material="paint_black_gloss", movable=True,
  pivot={"pos": [-2, 0, -237], "axis": [0, 1, 0], "type": "revolute", "range_deg": [0, 100], "note": "底部舱门绕前缘 y 轴向下开 100°（仅空中投放；落地时禁止开启）"},
  tooltip={"title": "投放舱门", "params": ["开启 100°（设计值）", "开启用时 0.6 s（设计值）"]},
  source=src("project_custom", "项目设计值。"))

# ===== 航电（机身内） =====
P(id="fc_core", name="飞控核心（双 IMU）", system="avionics", group="fc", parent="body_shell", internal=True, contacts=["body_shell"],
  geometry=[box([45, 0, 15], [80, 70, 22])], material="pcb_internal", movable=False, pivot={"pos": [45, 0, 15], "axis": None, "type": "fixed"},
  tooltip={"title": "飞控系统", "params": ["悬停精度 RTK ±0.1 m（官方）", "最大俯仰 30°、航向角速度 100°/s（官方）", "最大水平速度 23 m/s、抗风 12 m/s（官方）", "冗余 IMU 数量：未查到"]},
  source=src(EST, "性能官方；内部模块位置与尺寸估算。", SRC["spec"]))
P(id="rtk_module", name="内置 RTK 模块", system="avionics", group="rtk", parent="body_shell", internal=True, contacts=["body_shell"],
  geometry=[box([45, 0, 60], [70, 50, 16])], material="ice_blue_accent", movable=False, pivot={"pos": [45, 0, 60], "axis": None, "type": "fixed"},
  tooltip={"title": "内置 RTK 模块", "params": ["RTK FIX 1 cm+1 ppm（官方）", "抗金属/高压线磁干扰（官方）", "配 D-RTK 2 或网络 RTK（官方）"]},
  source=src(EST, "功能官方（手册 RTK Module Introduction）；位置尺寸估算。", SRC["manual"]))

# ===== 指示（机身） =====
P(id="beacon_top", name="顶部信标", system="indicator", group="beacon", parent="body_shell", contacts=["body_shell"],
  geometry=[cyl([-90, 0, 96], 22, 12)], material="led_white", movable=False, pivot={"pos": [-90, 0, 90], "axis": None, "type": "fixed"},
  tooltip={"title": "上信标", "params": ["夜航识别，Pilot 2 可开关（官方）"]}, source=src(EST, "手册 p.36 第 18 号；尺寸估算。", SRC["manual_p36"]),
  fx={"light": {"type": "strobe", "color": "#FFF4E0", "period_s": 1.0, "on_ms": 60}})
P(id="beacon_bottom", name="底部信标", system="indicator", group="beacon", parent="body_shell", contacts=["body_shell"],
  geometry=[cyl([-80, 70, -96], 22, 12)], material="led_white", movable=False, pivot={"pos": [-80, 70, -90], "axis": None, "type": "fixed"},
  tooltip={"title": "下信标", "params": ["夜航识别，Pilot 2 可开关（官方）"]}, source=src(EST, "手册 p.36 第 24 号；尺寸估算。", SRC["manual_p36"]),
  fx={"light": {"type": "strobe", "color": "#FFF4E0", "period_s": 1.0, "on_ms": 60, "phase_s": 0.5}})
P(id="aux_light_top", name="顶部补光灯", system="indicator", group="aux_light", parent="body_shell", contacts=["body_shell"],
  geometry=[box([20, 0, 95], [24, 24, 10])], material="led_white", movable=False, pivot={"pos": [20, 0, 90], "axis": None, "type": "fixed"},
  tooltip={"title": "上补光灯", "params": ["有效照明 5 m（官方）", "60 Hz 常亮（官方）"]}, source=src(EST, "手册 p.36 第 27 号；尺寸估算。", SRC["manual_p36"]))
P(id="aux_light_bottom", name="底部补光灯（下视辅助）", system="indicator", group="aux_light", parent="body_shell", contacts=["body_shell"],
  geometry=[box([10, 50, -95], [20, 20, 10])], material="led_white", movable=False, pivot={"pos": [10, 50, -90], "axis": None, "type": "fixed"},
  tooltip={"title": "下补光灯", "params": ["有效照明 5 m（官方）", "为下视视觉与降落提供照明（官方）"]}, source=src(EST, "手册 p.36 第 23 号；尺寸估算。", SRC["manual_p36"]))

# ---------------- 动效字段：爆炸分层 / 展开时序 ----------------
IDX = {p["id"]: p for p in parts}
def radial_xy(p_id, amt):
    p = IDX[p_id]; c = p["geometry"][0]["center"]; dd = norm([c[0], c[1], 0.0001]); return [dd[0] * amt, dd[1] * amt, 0]
def ex(pid, layer, vec, order=0):
    IDX[pid]["explode"] = {"layer": layer, "order": order, "vector_mm": r(vec), "space": "parent_relative",
                           "delay_s": round(0.45 * (layer - 1) + 0.04 * order, 2), "duration_s": 0.7, "ease": "expo.out", "return": "time_reversed"}
EXPLODE_LAYERS = {1: "桨叶/桨毂", 2: "载荷（相机三轴、配送箱、投放机构）", 3: "电池抽出 + 机身灯具", 4: "传感器外推 + 臂端天线", 5: "电机/电调/臂锁 + 机臂外推 + 起落架", 6: "内部模块（电池仓/飞控/RTK/电源板）"}
for i, c in enumerate(["fl", "fr", "rl", "rr"]):
    ex(f"prop_{c}", 1, [0, 0, -150], i)
    for bn in "ab":
        ex(f"prop_{c}_blade_{bn}", 1, add(mul(IDX[f"arm_{c}"]["_d"], 60), [0, 0, 30 if bn == "a" else -30]), i)
    ex(f"motor_{c}", 5, [0, 0, -70], i); ex(f"esc_{c}", 5, [0, 0, 70], i)
    ex(f"arm_lock_{c}", 5, mul(IDX[f"arm_{c}"]["_d"], -0.0) if False else [0, 0, 45], i)
    ex(f"arm_{c}", 5, radial_xy(f"arm_{c}", 140), i)
    ex(f"led_{c}", 4, mul(IDX[f"arm_{c}"]["_d"], 45), i)
    ex(f"ant_tx_{c}", 4, [0, 0, 80], i)
    if c in ("rl", "rr"): ex(f"gnss_ant_{c}", 4, [0, 0, 120], i)
ex("camera_payload", 2, [70, 0, -90], 0); ex("gimbal_roll", 2, [-40, 0, -60], 1); ex("gimbal_yaw", 2, [0, 0, -30], 2); ex("gimbal_damper", 2, [30, 0, -30], 3)
ex("payload_box_door", 2, [0, 0, -90], 0); ex("payload_box", 2, [-40, 0, -110], 1); ex("drop_mech", 2, [-30, 0, -25], 2)
ex("battery_l", 3, [0, 0, 220], 0); ex("battery_r", 3, [0, 0, 220], 1)
for pid, vec in [("beacon_top", [0, 0, 400]), ("aux_light_top", [0, 0, 400]), ("beacon_bottom", [0, 0, -40]), ("aux_light_bottom", [0, 0, -40])]:
    ex(pid, 3, vec)
for k, (cc, sz, n, zh) in faces.items(): ex(f"vision_{k}", 4, mul(n, 420 if k == "top" else 70))
for k, (cc, sz, n, zh) in ir.items(): ex(f"ir_tof_{k}", 4, mul(n, 440 if k == "top" else 110))
ex("fpv_cam", 4, [110, 0, 0])
ex("gear_l", 5, [0, 90, -60]); ex("gear_r", 5, [0, -90, -60])
ex("rtk_module", 6, [0, 0, 300], 0); ex("fc_core", 6, [0, 0, 220], 1); ex("battery_bay", 6, [0, 0, 170], 2); ex("power_board", 6, [40, 0, 150], 3)
# 内部模块逐个错峰 0.2 s 出舱（防止互相穿插）
for pid, dl in [("rtk_module", 2.25), ("fc_core", 2.45), ("battery_bay", 2.65), ("power_board", 2.85)]:
    IDX[pid]["explode"]["delay_s"] = dl
EXPLODE_TOTAL = max(p["explode"]["delay_s"] + p["explode"]["duration_s"] for p in parts if p["explode"].get("layer"))

# 展开时序（运输折叠态 → 飞行态），手册：先展前臂再展后臂，锁臂后展桨
UNFOLD = {
  "total_s": 3.4,
  "steps": [
    {"t": 0.00, "dur": 0.60, "target": ["fpv_cam", "vision_*"], "action": "eyes_wake", "ease": "sine.inOut", "note": "冰蓝眼部 0→100%，前→左右→上下→后 相位 0.2 s"},
    {"t": 0.20, "dur": 0.90, "target": ["arm_fl"], "action": "unfold", "ease": "back.out(1.2)", "note": "前臂先展（官方顺序）"},
    {"t": 0.40, "dur": 0.90, "target": ["arm_fr"], "action": "unfold", "ease": "back.out(1.2)", "note": "与 fl 错开 0.2 s，避免中间态对撞"},
    {"t": 1.10, "dur": 0.25, "target": ["arm_lock_fl"], "action": "lock_35deg", "ease": "power2.out", "light": "led_fl 白闪 120 ms→红常亮"},
    {"t": 1.30, "dur": 0.25, "target": ["arm_lock_fr"], "action": "lock_35deg", "ease": "power2.out", "light": "led_fr 白闪 120 ms→红常亮"},
    {"t": 1.20, "dur": 0.90, "target": ["arm_rl"], "action": "unfold", "ease": "back.out(1.2)"},
    {"t": 1.40, "dur": 0.90, "target": ["arm_rr"], "action": "unfold", "ease": "back.out(1.2)"},
    {"t": 2.10, "dur": 0.25, "target": ["arm_lock_rl"], "action": "lock_35deg", "ease": "power2.out", "light": "led_rl 白闪→绿常亮；gnss_ant_rl 冰蓝环点亮"},
    {"t": 2.30, "dur": 0.25, "target": ["arm_lock_rr"], "action": "lock_35deg", "ease": "power2.out", "light": "led_rr 白闪→绿常亮；gnss_ant_rr 冰蓝环点亮"},
    {"t": 2.55, "dur": 0.50, "target": ["prop_*_blade_*"], "action": "blade_unfold", "ease": "expo.out", "note": "8 片桨叶同时离心甩开"},
    {"t": 3.05, "dur": 0.35, "target": ["beacon_top", "beacon_bottom"], "action": "strobe_on", "ease": "none", "light": "信标首闪 = 就绪"},
  ],
}
for st in UNFOLD["steps"]:
    for tgt in st["target"]:
        if tgt in IDX and st["action"] == "unfold":
            IDX[tgt]["fx"]["unfold"] = {"t": st["t"], "dur": st["dur"], "from_deg": IDX[tgt]["fold"]["folded_angle_deg"], "to_deg": 0, "ease": st["ease"]}

for p in parts:
    for k in ("_d", "_t", "_L"): p.pop(k, None)
    lo = [1e9] * 3; hi = [-1e9] * 3
    for g in p["geometry"]:
        c = g["center"]
        if g["type"] == "cyl":
            a = norm(g["axis"]); ext = [abs(a[i]) * g["h"] / 2 + g["d"] / 2 * math.sqrt(max(0, 1 - a[i] ** 2)) for i in range(3)]
        else:
            xa = norm(g.get("x_axis", [1, 0, 0])); za = norm(g.get("z_axis", [0, 0, 1])); ya = cross(za, xa)
            ext = [abs(xa[i]) * g["size"][0] / 2 + abs(ya[i]) * g["size"][1] / 2 + abs(za[i]) * g["size"][2] / 2 for i in range(3)]
        for i in range(3):
            lo[i] = min(lo[i], c[i] - ext[i]); hi[i] = max(hi[i], c[i] + ext[i])
    p["aabb_mm"] = {"min": r(lo, 1), "max": r(hi, 1)}
    # 部件自身尺寸（主几何本征尺寸，不受安装方向影响）
    g0 = p["geometry"][0]
    if len(p["geometry"]) == 1:
        p["dims_mm"] = ({"L": g0["size"][0], "W": g0["size"][1], "H": g0["size"][2]} if g0["type"] == "box" else {"D": g0["d"], "H_or_len": g0["h"]})
    else:
        p["dims_mm"] = {"aabb_LxWxH": r([hi[i] - lo[i] for i in range(3)], 1), "note": "组合件，见 geometry"}

out = {
  "schema": "lowalt.parts/1", "version": "v1", "frozen": True,
  "naming_rule": "id 定稿后禁止改名；新增细分件只能追加新 id（如 *_sub_x），不得重命名既有 id。",
  "blueprint": "DJI Matrice 350 RTK", "units": "mm",
  "frame": {"origin": "机身壳体包围盒几何中心", "x": "前", "y": "左", "z": "上", "handedness": "right"},
  "official": OFFICIAL, "sources": SRC, "systems": SYSTEMS, "materials": MATERIALS,
  "layout_derivation": {"pod_d": D_POD, "motor_A": A, "motor_B": B, "formula": "2A+D=810, 2B+D=670, 2√(A²+B²)=895"},
  "explode_layers": EXPLODE_LAYERS, "explode_total_s": round(EXPLODE_TOTAL, 2), "explode_restore_rule": "复原 = 拆解时间轴严格倒放（k_restore(t) = k_explode(T_total − t)），保证与拆解同路径返回、无新穿模", "unfold_timeline": UNFOLD,
  "envelope_rules": {"unfolded_no_props_exclude_groups": ["prop_hub", "prop_blade"], "folded_exclude_systems": ["payload"],
                     "note": "官方 810×670×430 为展开不含桨；折叠 430×420×430 含桨。折叠运输态按实机惯例先拆云台（DGC2.0 一键拆卸），载荷不计入折叠包络（推断口径）。"},
  "parts": parts,
}
os.makedirs(os.path.join(ROOT), exist_ok=True)
with open(os.path.join(ROOT, "parts-v1.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("parts:", len(parts), "groups:", len({p['group'] for p in parts}))
