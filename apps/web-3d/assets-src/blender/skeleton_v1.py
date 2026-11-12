# -*- coding: utf-8 -*-
"""阶段 1 骨架：按 parts-v1.json 摆出全机比例骨架（每部件一个对象，名字 = 部件 id，原点 = 转轴位置）。
输出 skeleton_v1.blend / skeleton_v1.glb，并渲染三视图（带尺寸标注）、透视、折叠态、爆炸态、36 帧转台。
用法：blender -b --factory-startup -P assets-src/blender/skeleton_v1.py -- [--only build|views|states|turntable|hero] [--samples N]"""
import bpy, sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skel_lib as L
from mathutils import Vector, Euler
from bpy_extras.object_utils import world_to_camera_view

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ONLY = argv[argv.index("--only") + 1].split(",") if "--only" in argv else ["build", "views", "states", "turntable", "hero"]
SAMPLES = int(argv[argv.index("--samples") + 1]) if "--samples" in argv else 24
OUT = os.path.join(L.WEB, "_shots", "stage1"); RAW = os.path.join(OUT, "_raw"); os.makedirs(RAW, exist_ok=True)
BL = os.path.join(L.WEB, "assets-src", "blender")
data = L.load()

def fresh(mat_mode="system"):
    L.clear_scene(); L._T = None
    objs = L.build(data, inset=0.0, mat_mode=mat_mode)
    L.setup_render("CYCLES", (1920, 1080), SAMPLES)
    return objs

def render(path):
    bpy.context.scene.render.filepath = path; bpy.ops.render.render(write_still=True)

def proj(cam, pts):
    sc = bpy.context.scene; W, H = sc.render.resolution_x, sc.render.resolution_y
    out = []
    for p in pts:
        c = world_to_camera_view(sc, cam, Vector(p) * L.S); out.append((c.x * W, (1 - c.y) * H))
    return out

ANN = {}
if "build" in ONLY:
    objs = fresh()
    for p in data["parts"]:
        ob = objs[p["id"]]
        ob["tooltip_title"] = p["tooltip"]["title"]; ob["explode_layer"] = p["explode"].get("layer", 0)
        ob["explode_vector_mm"] = p["explode"].get("vector_mm", [0, 0, 0]); ob["movable"] = p["movable"]
        ob["pivot_type"] = p["pivot"]["type"]; ob["pivot_axis"] = p["pivot"].get("axis") or [0, 0, 0]
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(BL, "skeleton_v1.blend"))
    for o in list(bpy.context.scene.objects):
        o.select_set(o.name in objs)
    bpy.ops.export_scene.gltf(filepath=os.path.join(BL, "skeleton_v1.glb"), export_format="GLB", use_selection=True,
                              export_extras=True, export_apply=False, export_yup=True)
    print("BUILD OK")

if "views" in ONLY:
    objs = fresh(); L.apply_state(objs, data)
    bpy.data.objects["floor"].hide_render = True
    bpy.context.scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.035, 0.036, 0.04, 1)  # 工程视图用深灰底提高可读性
    views = {
      "front": dict(loc=(3, 0, -0.075), rot=(90, 0, 90), scale=1.05),
      "side":  dict(loc=(0, 3, -0.075), rot=(90, 0, 180), scale=1.20),
      "top":   dict(loc=(0, 0, 3), rot=(0, 0, 0), scale=1.45),
    }
    for name, v in views.items():
        cam = L.camera("cam_" + name, v["loc"], 50, ortho=v["scale"], track=False)
        cam.rotation_euler = Euler([math.radians(a) for a in v["rot"]])
        bpy.context.view_layer.update()
        render(os.path.join(RAW, f"view_{name}.png"))
        if name == "front":
            ANN[name] = {"W": proj(cam, [(0, 335, -290), (0, -335, -290)]), "H": proj(cam, [(0, -335, -290), (0, -335, 140)]),
                         "labels": [("宽 W", 670), ("高 H", 430)]}
        elif name == "side":
            ANN[name] = {"W": proj(cam, [(405, 0, -290), (-405, 0, -290)]), "H": proj(cam, [(-405, 0, -290), (-405, 0, 140)]),
                         "labels": [("长 L", 810), ("高 H", 430)]}
        else:
            m = {c: objs[f"motor_{c}"].matrix_world.translation * 1000 for c in ("fl", "rr")}
            ANN[name] = {"W": proj(cam, [(405, 335, 0), (-405, 335, 0)]), "H": proj(cam, [(405, -335, 0), (405, 335, 0)]),
                         "diag": proj(cam, [tuple(m["fl"]), tuple(m["rr"])]), "labels": [("长 L", 810), ("宽 W", 670)]}
    json.dump(ANN, open(os.path.join(RAW, "annotations.json"), "w"))
    # 透视
    cam = L.camera("cam_persp", (1.55, -1.25, 0.75), 45); L.target_empty().location = (0, 0, -0.07)
    render(os.path.join(OUT, "view_perspective.png"))
    print("VIEWS OK")

if "states" in ONLY:
    objs = fresh()
    pay = [p["id"] for p in data["parts"] if p["system"] == "payload"]
    L.apply_state(objs, data, fold=1.0, blade_stow=1.0, lock=0.0)
    for i in pay: objs[i].hide_render = True
    cam = L.camera("cam_fold", (1.05, -0.95, 0.45), 45); L.target_empty().location = (0, 0, -0.08)
    render(os.path.join(RAW, "state_folded.png"))
    for i in pay: objs[i].hide_render = False
    L.apply_state(objs, data, explode=1.0)
    # 爆炸位移向量可视化：每个部件 静止原点 → 爆炸原点 画细线（橙色发光）
    import bmesh
    me = bpy.data.meshes.new("explode_vectors"); bm = bmesh.new()
    pp = L.P(data)
    L.apply_state(objs, data); rest = {i: objs[i].matrix_world.translation.copy() for i in objs}
    L.apply_state(objs, data, explode=1.0); ex = {i: objs[i].matrix_world.translation.copy() for i in objs}
    for i in objs:
        if (ex[i] - rest[i]).length > 1e-4:
            a = bm.verts.new(rest[i]); b = bm.verts.new(ex[i]); bm.edges.new((a, b))
    bm.to_mesh(me); bm.free()
    vo = bpy.data.objects.new("explode_vectors", me); bpy.context.scene.collection.objects.link(vo)
    mod = vo.modifiers.new("skin", "SKIN"); 
    for v in vo.data.skin_vertices[0].data: v.radius = (0.0018, 0.0018)
    vo.data.materials.append(L.principled("vec", "#FF9A00", 0, 0.4, 0, 0.03, "#FF9A00", 3.0))
    cam = L.camera("cam_ex", (2.3, -1.9, 1.05), 45); L.target_empty().location = (0, 0, 0.02)
    bpy.data.objects["floor"].location.z = -0.52
    render(os.path.join(OUT, "state_exploded.png"))
    print("STATES OK")

if "turntable" in ONLY:
    objs = fresh(); L.apply_state(objs, data)
    TD = os.path.join(OUT, "turntable"); os.makedirs(TD, exist_ok=True)
    cam = L.camera("cam_tt", (1.6, 0, 0.55), 50); L.target_empty().location = (0, 0, -0.07)
    for f in range(36):
        a = math.radians(f * 10); cam.location = (1.6 * math.cos(a), 1.6 * math.sin(a), 0.55)
        L.apply_state(objs, data, spin_deg=f * 37.0)
        render(os.path.join(TD, f"tt_{f:03d}.png"))
    print("TURNTABLE OK")

if "hero" in ONLY:
    objs = fresh("pbr"); L.apply_state(objs, data, spin_deg=12)
    cam = L.camera("cam_hero", (1.75, -1.45, 0.42), 50); L.target_empty().location = (0, 0, -0.06)
    render(os.path.join(OUT, "hero_pbr_preview.png"))
    print("HERO OK")
