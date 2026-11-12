# -*- coding: utf-8 -*-
"""动态预演（animatic）渲染：blender -b --factory-startup -P render_shots_v1.py -- --shot S1_reveal [--samples 4] [--step 1] [--resume]
每帧状态来自 shots_def.state()，同时写出状态日志供 check_v1.py 回放做穿模检测。"""
import bpy, sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skel_lib as L, shots_def as SD
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SHOT = argv[argv.index("--shot") + 1]
SAMPLES = int(argv[argv.index("--samples") + 1]) if "--samples" in argv else 4
ENGINE = argv[argv.index("--engine") + 1].upper() if "--engine" in argv else "CYCLES"  # CYCLES | WORKBENCH
SKIP = "--resume" in argv  # 断点续渲：已存在的帧跳过
STEP = int(argv[argv.index("--step") + 1]) if "--step" in argv else 1
OUT = os.path.join(L.WEB, "_shots", "stage1", "shots", "_frames" + ("_wb" if ENGINE == "WORKBENCH" else ""), SHOT); os.makedirs(OUT, exist_ok=True)
data = L.load()
L.clear_scene(); L._T = None
objs = L.build(data, inset=0.0, mat_mode="system")
L.setup_render("CYCLES", (1920, 1080), SAMPLES)
sc = bpy.context.scene; sc.render.fps = SD.FPS
sc.cycles.max_bounces = 3
cam = L.camera("cam", (2, 0, 0.3), 50); tgt = L.target_empty()
lights = {n: bpy.data.objects[n] for n in ("key", "fill", "rim")}; base_e = {n: o.data.energy for n, o in lights.items()}
# 眼部/GNSS 独立材质（逐件动画）
pp = L.P(data)
eye_mats = {}
for pid, ob in objs.items():
    if pp[pid]["system"] == "sensing":
        m = ob.data.materials[0].copy(); ob.data.materials[0] = m; eye_mats[pid] = m
gn_mats = {}
for pid in ("gnss_ant_rl", "gnss_ant_rr", "rtk_module"):
    m = L.principled("gn_" + pid, "#0E1A22", 0.3, 0.25, 0.6, 0.03, "#6FE3FF", 0.0); objs[pid].data.materials[0] = m; gn_mats[pid] = m
# 扫光环（金属黄轮廓扫光：一圈极薄发光环带，仅光效，不参与穿模检测）
import bmesh
me = bpy.data.meshes.new("scan_ring"); bm = bmesh.new()
bmesh.ops.create_cone(bm, cap_ends=False, segments=160, radius1=0.6, radius2=0.6, depth=0.008)
bm.to_mesh(me); bm.free()
ring = bpy.data.objects.new("scan_ring", me); sc.collection.objects.link(ring)
sc_mat = L.principled("scan", "#FFC400", 0, 0.3, 0, 0.03, "#FFC400", 30.0); me.materials.append(sc_mat)
sp = bpy.data.lights.new("scan_light", "AREA"); sp.shape = "DISK"; sp.size = 1.3; sp.energy = 0; sp.color = (1.0, 0.77, 0.0)
spo = bpy.data.objects.new("scan_light", sp); sc.collection.objects.link(spo)
ring.hide_render = True

WB = ENGINE == "WORKBENCH"
def _bc(m):
    try: return tuple(m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value)[:3]
    except Exception: return (0.5, 0.5, 0.5)
def _ec(m):
    try: return tuple(m.node_tree.nodes["Principled BSDF"].inputs["Emission Color"].default_value)[:3]
    except Exception: return (0.43, 0.89, 1.0)
if WB:
    # 快速预演：Workbench（Studio 光 + 阴影 + 腔体 + 高光），自发光用物体色提亮 + 合成器 Fog Glow 模拟
    sc.render.engine = "BLENDER_WORKBENCH"
    sh = sc.display.shading
    sh.light = "STUDIO"; sh.color_type = "OBJECT"; sh.show_shadows = True; sh.shadow_intensity = 0.6
    sh.show_cavity = True; sh.cavity_type = "BOTH"; sh.show_specular_highlight = True
    sc.display.render_aa = "8"
    sc.view_settings.view_transform = "Standard"; sc.view_settings.look = "None"
    sc.world.color = (0.006, 0.006, 0.008)
    sc.render.film_transparent = False
    BASE = {}
    for pid, ob in objs.items():
        ob.color = (*_bc(ob.data.materials[0]), 1); BASE[pid] = ob.color[:3]
    EMC = {pid: _ec(m) for pid, m in eye_mats.items()}
    for n in ("floor",):
        if n in bpy.data.objects: bpy.data.objects[n].color = (0.006, 0.006, 0.007, 1)
    ring.color = (1.0, 0.77, 0.0, 1)
    FL = bpy.data.objects.get("floor")
    def render_mask(path, st):
        """自发光遮罩帧（Flat 光照，非发光件全黑）：编码时据此叠加辉光，模拟 Bloom"""
        keep = {o.name: tuple(o.color) for o in list(objs.values()) + [ring] + ([FL] if FL else [])}
        for o in objs.values(): o.color = (0, 0, 0, 1)
        if FL: FL.color = (0, 0, 0, 1)
        for pid in eye_mats:
            k = max(0.0, min(1.0, st["eyes"].get(pid, st["eyes"].get("*", 0.6)) / 1.2)); objs[pid].color = (0.43 * k, 0.89 * k, 1.0 * k, 1)
        g = max(0.0, min(1.0, st.get("gnss_glow", 0.6)))
        for pid in gn_mats: objs[pid].color = (0.43 * g, 0.89 * g, 1.0 * g, 1)
        ring.color = (1.0, 0.77, 0.0, 1)
        sh.light = "FLAT"; sh.show_shadows = False; sh.show_cavity = False; sh.show_specular_highlight = False
        sc.render.filepath = path; bpy.ops.render.render(write_still=True)
        sh.light = "STUDIO"; sh.show_shadows = True; sh.show_cavity = True; sh.show_specular_highlight = True
        for o in list(objs.values()) + [ring] + ([FL] if FL else []): o.color = keep[o.name]
    def _mix(a, b, k): return tuple(a[i] + (b[i] - a[i]) * k for i in range(3))

log = []
N = int(round(SD.SHOTS[SHOT]["dur"] * SD.FPS))
for f in range(0, N, STEP):
    t = f / SD.FPS
    if SKIP and os.path.exists(os.path.join(OUT, f"f_{f:04d}.png")):
        log.append({"f": f, "t": round(t, 4)}); continue
    st = SD.state(SHOT, t, data)
    SD.apply(objs, data, st)
    for pid in objs:
        if pp[pid]["system"] == "payload": objs[pid].hide_render = st["hide_payload"]
    cam.location = st["cam"]["loc"]; cam.data.lens = st["cam"]["lens"]; tgt.location = st["cam"]["target"]
    for n, o in lights.items(): o.data.energy = base_e[n] * st["lights"]
    for pid, m in eye_mats.items():
        v = st["eyes"].get(pid, st["eyes"].get("*", 0.6))
        m.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 5.0 * v
        if WB: objs[pid].color = (*_mix(BASE[pid], (0.75, 0.97, 1.0), max(0.0, min(1.0, v * 1.3))), 1)
    for pid, m in gn_mats.items():
        m.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 3.0 * st.get("gnss_glow", 0.6)
        if WB: objs[pid].color = (*_mix((0.06, 0.12, 0.16), (0.55, 0.93, 1.0), st.get("gnss_glow", 0.6)), 1)
    if st["scan_z"] is not None:
        ring.hide_render = False; ring.location = (0, 0, st["scan_z"]); spo.location = (0, 0, st["scan_z"] + 0.002); sp.energy = 60
    else:
        ring.hide_render = True; sp.energy = 0
    bpy.context.view_layer.update()
    sc.render.filepath = os.path.join(OUT, f"f_{f:04d}.png"); bpy.ops.render.render(write_still=True)
    if WB: render_mask(os.path.join(OUT, f"m_{f:04d}.png"), st)
    log.append({"f": f, "t": round(t, 4)})
    print(f"SHOTFRAME {SHOT} {f+1}/{N}", flush=True)
json.dump({"shot": SHOT, "fps": SD.FPS, "frames": len(log)}, open(os.path.join(OUT, "frames.json"), "w"))
print("SHOT DONE", SHOT)
