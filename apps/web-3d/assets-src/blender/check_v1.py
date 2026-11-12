# -*- coding: utf-8 -*-
"""阶段 1 自检：三围/轴距误差、id 唯一性、7 大系统覆盖、骨架级穿模检测（静止态+全部动画关键帧）。
用法：blender -b -P assets-src/blender/check_v1.py"""
import bpy, sys, os, json, math, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skel_lib as L
from mathutils import Vector
from mathutils.bvhtree import BVHTree

data = L.load(); PP = L.P(data); OFF = data["official"]
report = {"generated_by": "assets-src/blender/check_v1.py", "blender": bpy.app.version_string}

def world_bbox(objs, ids):
    lo = Vector((1e9,) * 3); hi = Vector((-1e9,) * 3)
    for i in ids:
        ob = objs[i]
        for v in ob.data.vertices:
            w = ob.matrix_world @ v.co
            lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
    return lo, hi

# ---------- 1) 三围与轴距（inset=0 实体网格，读 Blender 世界坐标） ----------
L.clear_scene(); objs = L.build(data, inset=0.0)
L.apply_state(objs, data)
noprop = [p["id"] for p in data["parts"] if p["group"] not in data["envelope_rules"]["unfolded_no_props_exclude_groups"]]
lo, hi = world_bbox(objs, noprop); dims = [(hi[i] - lo[i]) * 1000 for i in range(3)]
ref = OFF["unfolded_LWH_mm"]
mfl = objs["motor_fl"].matrix_world.translation; mrr = objs["motor_rr"].matrix_world.translation
mfr = objs["motor_fr"].matrix_world.translation; mrl = objs["motor_rl"].matrix_world.translation
wb1 = (mfl - mrr).length * 1000; wb2 = (mfr - mrl).length * 1000
report["envelope_unfolded_no_props"] = {
  "measured_mm": [round(x, 2) for x in dims], "official_mm": ref,
  "error_pct": [round(abs(dims[i] - ref[i]) / ref[i] * 100, 3) for i in range(3)],
  "bbox_min_mm": [round(x * 1000, 1) for x in lo], "bbox_max_mm": [round(x * 1000, 1) for x in hi]}
report["wheelbase"] = {"measured_fl_rr_mm": round(wb1, 2), "measured_fr_rl_mm": round(wb2, 2), "official_mm": OFF["diagonal_wheelbase_mm"],
  "error_pct": round(max(abs(wb1 - 895), abs(wb2 - 895)) / 895 * 100, 3)}
allids = [p["id"] for p in data["parts"]]
lo2, hi2 = world_bbox(objs, allids)
report["envelope_with_props"] = [round((hi2[i] - lo2[i]) * 1000, 1) for i in range(3)]
# 折叠态（含桨、不含载荷）
L.apply_state(objs, data, fold=1.0, blade_stow=1.0)
fold_ids = [p["id"] for p in data["parts"] if p["system"] not in data["envelope_rules"]["folded_exclude_systems"]]
lo3, hi3 = world_bbox(objs, fold_ids); fd = [(hi3[i] - lo3[i]) * 1000 for i in range(3)]
fr = OFF["folded_LWH_mm_with_props"]
ext = sorted(((objs[i].matrix_world @ v.co).x * 1000, i) for i in fold_ids for v in objs[i].data.vertices)
print("FOLD x extremes", ext[0], ext[-1])
exty = sorted(((objs[i].matrix_world @ v.co).y * 1000, i) for i in fold_ids for v in objs[i].data.vertices); print("FOLD y", exty[0], exty[-1])
report["envelope_folded_with_props_no_payload"] = {"measured_mm": [round(x, 1) for x in fd], "official_mm": fr,
  "error_pct": [round(abs(fd[i] - fr[i]) / fr[i] * 100, 2) for i in range(3)], "note": "折叠运动学为估算，此项仅作参考，不属阶段 1 合格标准"}

# ---------- 2) id 唯一性 + 覆盖 ----------
ids = [p["id"] for p in data["parts"]]
dup = sorted({i for i in ids if ids.count(i) > 1})
import re
bad = [i for i in ids if not re.fullmatch(r"[a-z][a-z0-9_]*", i)]
report["ids"] = {"count": len(ids), "unique": len(set(ids)), "duplicates": dup, "bad_format": bad,
                 "blender_object_names_match": all(objs[i].name == i for i in ids), "groups": len({p['group'] for p in data['parts']})}
need = {
 "frame": {"机身": ["body_shell"], "机臂": ["arm"], "起落架": ["gear"]},
 "power": {"电机": ["motor"], "电调": ["esc"], "桨": ["prop_hub", "prop_blade"]},
 "energy": {"电池": ["battery"], "电池仓": ["battery_bay"], "电源板": ["power_board"]},
 "sensing": {"FPV": ["fpv_cam"], "六向双目": ["vision"], "红外": ["ir_tof"], "下视": ["vision_bottom"]},
 "payload": {"云台": ["gimbal_damper", "gimbal_axis"], "相机": ["camera"], "配送箱": ["payload_box"], "投放机构": ["drop_mech"]},
 "avionics": {"飞控": ["fc"], "RTK": ["rtk"], "GNSS": ["gnss_ant"], "天线": ["ant_tx"]},
 "indicator": {"LED": ["led_front", "led_status"], "臂锁": ["arm_lock"]},
}
cov = {}; ok_all = True
for sysk, items in need.items():
    cov[sysk] = {}
    for item, keys in items.items():
        hit = [p["id"] for p in data["parts"] if p["system"] == sysk and (p["group"] in keys or p["id"] in keys)]
        cov[sysk][item] = hit; ok_all &= bool(hit)
cnt = {k: sum(1 for p in data["parts"] if p["group"] == k) for k in ["battery", "vision", "arm", "motor", "esc", "prop_hub", "prop_blade", "arm_lock"]}
report["coverage"] = {"all_required_present": ok_all, "battery_count": cnt["battery"], "vision_directions": cnt["vision"], "group_counts": cnt, "detail": cov}
five = ["dims_mm", "material", "movable", "pivot", "tooltip"]
missing5 = [(p["id"], k) for p in data["parts"] for k in five if p.get(k) in (None, "", {})]
pivot_bad = [p["id"] for p in data["parts"] if p["movable"] and not p["pivot"].get("axis")]
report["five_fields"] = {"missing": missing5, "movable_without_axis": pivot_bad,
                         "has_explode": sum(1 for p in data["parts"] if p["explode"].get("layer")), "has_source": sum(1 for p in data["parts"] if p.get("source"))}

# ---------- 3) 穿模检测（inset 0.5 mm，BVH 三角求交 + 包含判定） ----------
INSET = 0.5
L.clear_scene(); objs = L.build(data, inset=INSET)
allowed = set()
for p in data["parts"]:
    par = p["parent"] or ("body_shell" if p["id"] != "body_shell" else None)
    if par: allowed.add(frozenset((p["id"], par)))
    for c in p["contacts"]: allowed.add(frozenset((p["id"], c)))
    if p["internal"]: allowed.add(frozenset((p["id"], "body_shell")))

def trees(active):
    out = {}
    for i in active:
        ob = objs[i]; mw = ob.matrix_world
        verts = [mw @ v.co for v in ob.data.vertices]
        polys = [list(pl.vertices) for pl in ob.data.polygons]
        lo = Vector(map(min, *verts)) if len(verts) > 1 else verts[0]; hi = Vector(map(max, *verts))
        out[i] = (BVHTree.FromPolygons(verts, polys, epsilon=0.0), lo, hi, verts[0])
    return out

def inside(tree, pt):
    # 射线奇偶判定（3 个非对称方向多数表决，规避射线擦过棱边/重叠体的误判）
    votes = 0
    for d in (Vector((0.6123, 0.3187, 0.7236)), Vector((-0.2871, 0.8412, -0.4583)), Vector((0.1379, -0.5523, 0.8221))):
        n = 0; o = pt.copy()
        for _ in range(64):
            loc, nor, idx, dist = tree.ray_cast(o, d)
            if loc is None: break
            n += 1; o = loc + d * 1e-6
        votes += n % 2
    return votes >= 2

def collide(active):
    T = trees(active); hits = []
    for a, b in itertools.combinations(sorted(active), 2):
        if frozenset((a, b)) in allowed: continue
        ta, la, ha, va = T[a]; tb, lb, hb, vb = T[b]
        if any(ha[k] < lb[k] or hb[k] < la[k] for k in range(3)): continue
        if ta.overlap(tb) or inside(tb, va) or inside(ta, vb):
            hits.append((a, b))
    return hits

states = []
def run(name, frames, fn, active_filter=lambda p: True):
    act = [p["id"] for p in data["parts"] if active_filter(p)]
    bad = {}
    for f in frames:
        fn(f); h = collide(act)
        for pr in h: bad.setdefault("↔".join(pr), []).append(f if isinstance(f, tuple) else round(f, 3))
    states.append({"state": name, "samples": len(frames), "collisions": {k: [v[0], v[-1], len(v)] for k, v in bad.items()}})

FPS = 24
run("静止展开态（全机含载荷）", [0], lambda f: L.apply_state(objs, data))
spin = lambda f: L.apply_state(objs, data, spin_deg=f)
run("旋翼旋转 0–180°（每 15°）", list(range(0, 181, 15)), spin)
def gim(f):
    y, rr, pz = f; L.apply_state(objs, data, gimbal=(y, rr, pz))
gframes = [(y, r, p) for y in range(-320, 321, 40) for r in (-60, -30, 0, 30, 60) for p in (-120, -90, -60, -30, 0, 30, 60)]
report_gimbal = run("云台三轴扫掠（yaw −320~320 步 40° × roll ±60 × pitch −120~60，595 组）", gframes, gim)
run("配送箱舱门开合 0–100°（空中）", [i / 10 for i in range(11)], lambda f: L.apply_state(objs, data, door=f))
def unfold(t):
    fold, lock, bl = L.unfold_state(data, t)
    L.apply_state(objs, data, fold_each=fold, blade_stow=bl, lock=1.0)
T_UN = data["unfold_timeline"]["total_s"]
run("机臂展开时序 0–3.4 s（120 Hz 细采样，不含载荷：运输态已拆云台）", [i / 120 for i in range(int(T_UN * 120) + 1)], unfold, lambda p: p["system"] != "payload")
run("机臂折叠态（静止）", [0], lambda f: L.apply_state(objs, data, fold=1.0, blade_stow=1.0), lambda p: p["system"] != "payload")
TE = data["explode_total_s"]
run(f"爆炸拆解 0–{TE} s（24 fps）", [i / FPS for i in range(int(TE * FPS) + 2)], lambda t: L.apply_state(objs, data, explode_each=L.explode_progress(data, t, True)))
run(f"爆炸复原 0–{TE} s（24 fps）", [i / FPS for i in range(int(TE * FPS) + 2)], lambda t: L.apply_state(objs, data, explode_each=L.explode_progress(data, t, False)))
# 高光镜头逐帧回放（与 render_shots_v1.py 使用同一 shots_def.state()，24 fps 每帧）
import shots_def as SD
for shot, meta in SD.SHOTS.items():
    N = int(round(meta["dur"] * SD.FPS))
    def fn(f, shot=shot):
        st = SD.state(shot, f / SD.FPS, data); SD.apply(objs, data, st)
    hide = SD.state(shot, 0, data)["hide_payload"]
    run(f"镜头 {shot}「{meta['title']}」逐帧 {N} 帧" + ("（载荷已拆）" if hide else ""), list(range(N)), fn,
        (lambda p: p["system"] != "payload") if hide else (lambda p: True))
# 复原精度：复原末帧与初始位置偏差
L.apply_state(objs, data, explode_each=L.explode_progress(data, TE + 0.5, False))
dev = max((objs[i].matrix_world.translation - Vector(objs[i]["rest_loc"]) if objs[i].parent is None else objs[i].location - Vector(objs[i]["rest_loc"])).length for i in ids) * 1000
report["explode_restore_max_dev_mm"] = round(dev, 6)
# 桨盘扫掠：各桨盘（Ø533）与非本臂部件
disc_hits = []
L.apply_state(objs, data)
for c in ("fl", "fr", "rl", "rr"):
    hub = objs[f"prop_{c}"].matrix_world.translation
    for p in data["parts"]:
        if p["id"].startswith(("prop_", "motor_" + c, "arm_" + c, "esc_" + c, "led_" + c, "ant_tx_" + c, "gnss_ant_" + c, "arm_lock_" + c)): continue
        ob = objs[p["id"]]
        for v in ob.data.vertices:
            w = ob.matrix_world @ v.co
            if abs(w.z - hub.z) < 0.010 and math.hypot(w.x - hub.x, w.y - hub.y) < 0.2665:
                disc_hits.append(p["id"]); break
report["rotor_disc_clearance"] = {"hits": sorted(set(disc_hits)), "note": "桨盘平面 ±10 mm 层内、半径 266.5 mm 内是否有其他部件顶点"}
# 桨盘—机身/载荷/传感器最小水平间隙（只计与桨盘平面高度相交的几何体）
gap = []
def prim_vranges(pid):
    out = []; k = 0
    for g in PP[pid]["geometry"]:
        n = 8 if g["type"] == "box" else 96
        out.append((k, k + n)); k += n
    return out
for c in ("fl", "fr", "rl", "rr"):
    hub = objs[f"prop_{c}"].matrix_world.translation
    best = 1e9
    for i in ["body_shell", "camera_payload", "gimbal_roll", "vision_front", "vision_rear", "vision_left", "vision_right", "fpv_cam", "ir_tof_front", "ir_tof_rear", "battery_l", "battery_r", "gear_l", "gear_r", "payload_box"]:
        ob = objs[i]; vs = ob.data.vertices
        for a0, a1 in prim_vranges(i):
            ws = [ob.matrix_world @ vs[j].co for j in range(a0, a1)]
            if min(w.z for w in ws) - 0.004 <= hub.z <= max(w.z for w in ws) + 0.004:
                best = min(best, min(math.hypot(w.x - hub.x, w.y - hub.y) for w in ws))
    gap.append(round(best * 1000 - 266.5, 1))
report["rotor_tip_to_body_min_gap_mm"] = gap
# 检测器自检：故意制造两种穿模，必须被检出（防“检测器永远报 0”）
L.apply_state(objs, data)
cam = objs["camera_payload"]; cam.location = cam.location + Vector((-0.200, 0, 0.030)); bpy.context.view_layer.update()
st1 = ("camera_payload", "payload_box") in collide([p["id"] for p in data["parts"]]) or ("camera_payload", "payload_box_door") in collide([p["id"] for p in data["parts"]])
L.apply_state(objs, data)
irt = objs["ir_tof_top"]; bl = objs["battery_l"]
irt.location = irt.location + (bl.matrix_world.translation + Vector((0, 0, 0.085)) - irt.matrix_world.translation); bpy.context.view_layer.update()
hits2 = collide([p["id"] for p in data["parts"]]); st2 = ("battery_l", "ir_tof_top") in hits2
report["detector_selftest"] = {"intersect_case_detected": bool(st1), "containment_case_detected": bool(st2)}
L.apply_state(objs, data)
report["collision_states"] = states
report["collision_total"] = sum(len(s["collisions"]) for s in states)
report["inset_mm"] = INSET
out = os.path.join(L.WEB, "_shots", "stage1", "check_report_v1.json")
with open(out, "w", encoding="utf-8") as f: json.dump(report, f, ensure_ascii=False, indent=1)
print("REPORT", out); print(json.dumps({k: report[k] for k in ["envelope_unfolded_no_props", "wheelbase", "envelope_folded_with_props_no_payload", "collision_total", "rotor_tip_to_body_min_gap_mm", "explode_restore_max_dev_mm"]}, ensure_ascii=False))
for s in states: print(s["state"], s["collisions"])
print("SELFTEST", report["detector_selftest"], "IDS", report["ids"], "COVER", report["coverage"]["all_required_present"], "FIVE", report["five_fields"])
