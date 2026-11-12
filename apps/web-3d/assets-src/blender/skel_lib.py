# -*- coding: utf-8 -*-
"""骨架公共库：按 parts-v1.json 建骨架、材质、运动学（折叠/收桨/爆炸/云台/舱门）与缓动。
Blender 4.2 LTS。场景单位：米（json mm × 0.001），glTF 导出天然为米。"""
import bpy, bmesh, json, math, os
from mathutils import Vector, Matrix, Quaternion

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.abspath(os.path.join(HERE, "..", ".."))
JSON_PATH = os.path.join(WEB, "assets-src", "parts-v1.json")
S = 0.001

def load():
    with open(JSON_PATH, encoding="utf-8") as f:
        return json.load(f)

def hex2rgb(h):
    h = h.lstrip("#"); c = [int(h[i:i+2], 16) / 255 for i in (0, 2, 4)]
    return [((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c]  # sRGB→linear

def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)

# ---------------- 几何 ----------------
def _axes_box(g):
    xa = Vector(g.get("x_axis", [1, 0, 0])).normalized(); za = Vector(g.get("z_axis", [0, 0, 1])).normalized()
    za = (za - xa * xa.dot(za)).normalized(); ya = za.cross(xa)
    return xa, ya, za

def add_prim(bm, g, inset=0.0, segs=48):
    c = Vector(g["center"]) * S
    if g["type"] == "box":
        xa, ya, za = _axes_box(g)
        sx, sy, sz = [(v - 2 * inset) * S / 2 for v in g["size"]]
        m = Matrix((xa * sx, ya * sy, za * sz)).transposed()
        mat = Matrix.Translation(c) @ m.to_4x4()
        bmesh.ops.create_cube(bm, size=2.0, matrix=mat)
    else:
        a = Vector(g["axis"]).normalized()
        q = Vector((0, 0, 1)).rotation_difference(a)
        mat = Matrix.Translation(c) @ q.to_matrix().to_4x4()
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segs,
                              radius1=(g["d"] / 2 - inset) * S, radius2=(g["d"] / 2 - inset) * S,
                              depth=(g["h"] - 2 * inset) * S, matrix=mat)

def build(data, inset=0.0, mat_mode="system", collection_name="M350_skeleton"):
    col = bpy.data.collections.new(collection_name); bpy.context.scene.collection.children.link(col)
    mats = make_materials(data, mat_mode)
    objs = {}
    for p in data["parts"]:
        me = bpy.data.meshes.new(p["id"]); bm = bmesh.new()
        for g in p["geometry"]:
            add_prim(bm, g, inset)
        piv = Vector(p["pivot"]["pos"]) * S
        bmesh.ops.translate(bm, vec=-piv, verts=bm.verts)
        bm.to_mesh(me); bm.free()
        ob = bpy.data.objects.new(p["id"], me); ob.location = piv
        ob.rotation_mode = "QUATERNION"
        key = p["material"] if mat_mode == "pbr" else ("sys_" + p["system"] if p["system"] not in ("indicator",) else p["material"])
        if mat_mode == "system" and p["system"] == "sensing": key = "sys_sensing"
        me.materials.append(mats[key])
        if p["group"] == "prop_blade" and mat_mode == "pbr": pass
        col.objects.link(ob); objs[p["id"]] = ob
        ob["system"] = p["system"]; ob["group"] = p["group"]; ob["name_zh"] = p["name"]
    bpy.context.view_layer.update()
    for p in data["parts"]:
        par = p["parent"] or (None if p["id"] == "body_shell" else "body_shell")
        if par:
            ob = objs[p["id"]]; ob.parent = objs[par]
            ob.matrix_parent_inverse = objs[par].matrix_world.inverted()
    bpy.context.view_layer.update()
    for ob in objs.values():
        ob["rest_loc"] = list(ob.location)
    return objs

# ---------------- 材质 ----------------
def principled(name, base, metallic=0.0, rough=0.5, coat=0.0, coat_rough=0.03, emit=None, emit_s=0.0, aniso=0.0, transmission=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*hex2rgb(base), 1)
    b.inputs["Metallic"].default_value = metallic; b.inputs["Roughness"].default_value = rough
    b.inputs["Coat Weight"].default_value = coat; b.inputs["Coat Roughness"].default_value = coat_rough
    b.inputs["Anisotropic"].default_value = aniso
    b.inputs["Transmission Weight"].default_value = transmission
    if emit:
        b.inputs["Emission Color"].default_value = (*hex2rgb(emit), 1); b.inputs["Emission Strength"].default_value = emit_s
    return m

def make_materials(data, mode):
    mats = {}
    for k, v in data["materials"].items():
        mats[k] = principled(k, v["baseColor"], v.get("metallic", 0), v.get("roughness", 0.5), v.get("clearcoat", 0),
                             v.get("clearcoatRoughness", 0.03), v.get("emissive"), v.get("emissiveStrength", 0) * 0.6,
                             (v.get("anisotropy") or {}).get("strength", 0), v.get("transmission", 0) * 0.0)
    # 骨架按系统主色区分（同调色板）
    M = data["materials"]
    mats["sys_frame"] = mats["paint_bumblebee"]
    mats["sys_power"] = mats["gunmetal_brushed"]
    mats["sys_energy"] = mats["chrome_mirror"]
    mats["sys_sensing"] = principled("sys_sensing", "#05080C", 0, 0.05, 1.0, 0.02, "#6FE3FF", 2.5)
    mats["sys_payload"] = principled("sys_payload", "#121315", 0.0, 0.22, 1.0, 0.03)  # 钢琴黑/碳
    mats["sys_avionics"] = principled("sys_avionics", "#1B2A33", 0.6, 0.3, 0.5, 0.05, "#6FE3FF", 0.6)
    return mats

# ---------------- 缓动 ----------------
def clamp01(x): return max(0.0, min(1.0, x))
def ease(name, x):
    x = clamp01(x)
    if name.startswith("back.out"):
        s = 1.2 * 1.70158; x -= 1; return x * x * ((s + 1) * x + s) + 1
    if name == "expo.out": return 1 if x >= 1 else 1 - 2 ** (-10 * x)
    if name == "power2.out": return 1 - (1 - x) ** 2
    if name in ("power3.inOut", "cubic.inOut"): return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2
    if name == "sine.inOut": return -(math.cos(math.pi * x) - 1) / 2
    return x

# ---------------- 运动学 ----------------
def P(data): return {p["id"]: p for p in data["parts"]}

def set_rot(ob, axis, deg):
    ob.rotation_quaternion = Quaternion(Vector(axis).normalized(), math.radians(deg))

def apply_state(objs, data, fold=0.0, blade_stow=0.0, explode=None, lock=1.0, gimbal=(0, 0, 0), door=0.0, spin_deg=0.0,
                fold_each=None, explode_each=None):
    """fold: 0 展开 → 1 折叠；blade_stow: 0 展桨 → 1 收桨；explode: 0..1 统一进度（按层延时），或 explode_each[id]=0..1"""
    pp = P(data)
    for pid, ob in objs.items():
        p = pp[pid]; ob.location = Vector(ob["rest_loc"]); ob.rotation_quaternion = Quaternion()
    for c in ("fl", "fr", "rl", "rr"):
        a = pp[f"arm_{c}"]; f = fold_each[c] if fold_each else fold
        set_rot(objs[f"arm_{c}"], a["pivot"]["axis"], a["fold"]["folded_angle_deg"] * f)
        lk = pp[f"arm_lock_{c}"]; set_rot(objs[f"arm_lock_{c}"], lk["pivot"]["axis"], 35 * lock)
        for bn in "ab":
            b = pp[f"prop_{c}_blade_{bn}"]; set_rot(objs[b["id"]], [0, 0, 1], b["fold"]["stowed_angle_deg"] * blade_stow)
        if spin_deg:
            mp = pp[f"prop_{c}"]; set_rot(objs[f"prop_{c}"], mp["pivot"]["axis"], spin_deg)
    set_rot(objs["gimbal_yaw"], [0, 0, 1], gimbal[0]); set_rot(objs["gimbal_roll"], [1, 0, 0], gimbal[1]); set_rot(objs["camera_payload"], [0, 1, 0], -gimbal[2])
    set_rot(objs["payload_box_door"], [0, 1, 0], -door * 100)  # 绕前缘向下开
    if explode is not None or explode_each:
        for pid, ob in objs.items():
            e = pp[pid]["explode"]
            if not e.get("layer"): continue
            if explode_each is not None: k = explode_each.get(pid, 0.0)
            else:
                t = explode * data["explode_total_s"]; k = ease(e.get("ease", "expo.out"), (t - e["delay_s"]) / e["duration_s"])
            ob.location = Vector(ob["rest_loc"]) + Vector(e["vector_mm"]) * S * k
    bpy.context.view_layer.update()

def explode_progress(data, t_s, forward=True):
    """t_s 秒时各部件爆炸进度；复原 = 时间轴严格倒放"""
    T = data["explode_total_s"]
    if not forward: t_s = T - t_s
    out = {}
    for p in data["parts"]:
        e = p["explode"]
        if not e.get("layer"): continue
        out[p["id"]] = ease(e["ease"], (t_s - e["delay_s"]) / e["duration_s"])
    return out

def unfold_state(data, t_s):
    """按 unfold_timeline 计算 t_s 时：每臂折叠度、臂锁、桨叶收拢度"""
    steps = data["unfold_timeline"]["steps"]
    fold = {}; lock = {}; blades = 1.0
    for c in ("fl", "fr", "rl", "rr"):
        st = [s for s in steps if s["target"] == [f"arm_{c}"]][0]
        fold[c] = 1 - ease(st["ease"], (t_s - st["t"]) / st["dur"])
        ls = [s for s in steps if s["target"] == [f"arm_lock_{c}"]][0]
        lock[c] = ease(ls["ease"], (t_s - ls["t"]) / ls["dur"])
    bs = [s for s in steps if s["action"] == "blade_unfold"][0]
    blades = 1 - ease(bs["ease"], (t_s - bs["t"]) / bs["dur"])
    return fold, lock, blades

# ---------------- 场景：黑背景 + 三点布光 ----------------
def setup_render(engine="CYCLES", res=(1920, 1080), samples=24):
    sc = bpy.context.scene
    sc.render.engine = engine
    sc.render.resolution_x, sc.render.resolution_y = res; sc.render.resolution_percentage = 100
    if engine == "CYCLES":
        sc.cycles.device = "CPU"; sc.cycles.samples = samples; sc.cycles.use_denoising = True
        try: sc.cycles.denoiser = "OPENIMAGEDENOISE"
        except Exception: pass
        sc.cycles.max_bounces = 4
    sc.view_settings.view_transform = "AgX"; sc.view_settings.look = "AgX - Punchy"
    w = bpy.data.worlds.new("black"); w.use_nodes = True
    bg = w.node_tree.nodes["Background"]; bg.inputs[0].default_value = (0.004, 0.004, 0.005, 1); bg.inputs[1].default_value = 1.0
    sc.world = w
    def area(name, loc, energy, size, color=(1, 1, 1)):
        ld = bpy.data.lights.new(name, "AREA"); ld.energy = energy; ld.size = size; ld.color = color
        lo = bpy.data.objects.new(name, ld); lo.location = loc; sc.collection.objects.link(lo)
        tc = lo.constraints.new("TRACK_TO"); tc.target = target_empty(); tc.track_axis = "TRACK_NEGATIVE_Z"; tc.up_axis = "UP_Y"
        return lo
    area("key", (1.6, -1.2, 1.4), 420, 1.2, (1.0, 0.96, 0.9))
    area("fill", (-1.2, -1.6, 0.6), 120, 1.6, (0.85, 0.9, 1.0))
    area("rim", (-1.4, 1.4, 1.6), 380, 0.8, (1.0, 1.0, 1.0))
    # 地面（黑色微反射）
    me = bpy.data.meshes.new("floor"); bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=6); bm.to_mesh(me); bm.free()
    fl = bpy.data.objects.new("floor", me); fl.location = (0, 0, -0.2905); sc.collection.objects.link(fl)
    me.materials.append(principled("floor", "#050506", 0.0, 0.18, 0.0))

_T = None
def target_empty():
    global _T
    if _T is None or _T.name not in bpy.data.objects:
        _T = bpy.data.objects.new("target", None); _T.location = (0, 0, -0.06); bpy.context.scene.collection.objects.link(_T)
    return _T

def camera(name="cam", loc=(1.5, -1.5, 0.8), lens=50, ortho=None, track=True):
    cd = bpy.data.cameras.new(name); cd.lens = lens; cd.clip_start = 0.01; cd.clip_end = 50
    if ortho: cd.type = "ORTHO"; cd.ortho_scale = ortho
    co = bpy.data.objects.new(name, cd); co.location = loc; bpy.context.scene.collection.objects.link(co)
    if track:
        tc = co.constraints.new("TRACK_TO"); tc.target = target_empty(); tc.track_axis = "TRACK_NEGATIVE_Z"; tc.up_axis = "UP_Y"
    bpy.context.scene.camera = co
    return co
