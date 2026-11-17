# Style demo renders for CR-30: mecha / metallic-yellow / Transformers-flavored variants.
# Run: Blender -b asset/out/cr30.blend --python asset/blender/style_demos.py -- <out_dir>
import bpy, os, sys, math
from mathutils import Vector

ARGV = sys.argv[sys.argv.index("--") + 1:]
OUT = ARGV[0]
os.makedirs(OUT, exist_ok=True)

sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.render.resolution_x, sc.render.resolution_y = 1280, 720
sc.render.image_settings.file_format = 'PNG'

def principled(mat_name):
    m = bpy.data.materials.get(mat_name)
    if not m:
        print("missing material:", mat_name)
        return None
    return next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')

def set_mat(mat_name, color=None, metallic=None, rough=None, coat=None,
            emission=None, em_str=None):
    bs = principled(mat_name)
    if not bs:
        return
    if color is not None:
        bs.inputs["Base Color"].default_value = (*color, 1.0)
    if metallic is not None:
        bs.inputs["Metallic"].default_value = metallic
    if rough is not None:
        bs.inputs["Roughness"].default_value = rough
    if coat is not None:
        bs.inputs["Coat Weight"].default_value = coat
    if emission is not None:
        bs.inputs["Emission Color"].default_value = (*emission, 1.0)
    if emission is not None or em_str is not None:
        bs.inputs["Emission Strength"].default_value = em_str if em_str is not None else bs.inputs["Emission Strength"].default_value

def set_world(color, strength):
    w = sc.world
    w.node_tree.nodes["Background"].inputs[0].default_value = (*color, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = strength

YEL = (0.83, 0.60, 0.06)      # 金属黄
YEL_BRIGHT = (0.98, 0.72, 0.04)  # 亮黄
GUN = (0.055, 0.055, 0.06)    # 枪黑
GRAY = (0.16, 0.16, 0.17)     # 深灰

STYLES = {
    # A 工业重机：金属黄机身 + 炮铜框架，工程机械质感
    "A_工业重机": dict(bg=(0.05, 0.05, 0.055, 0.9), mats=[
        ("整流罩 · 珠光白", dict(color=YEL, metallic=0.85, rough=0.30, coat=0.5)),
        ("注塑ABS · 瓷白", dict(color=(0.72, 0.52, 0.08), metallic=0.2, rough=0.5)),
        ("阳极氧化铝 · 深空灰", dict(color=GUN, metallic=1.0, rough=0.42)),
        ("阳极氧化铝 · 动力红", dict(color=(0.55, 0.30, 0.02), metallic=1.0, rough=0.35)),
        ("LED · 状态灯", dict(emission=(1.0, 0.75, 0.1), em_str=8.0)),
    ]),
    # B 大黄蜂双拼：亮黄高光整流罩 + 黑化机身/货舱，蓝色能量灯
    "B_大黄蜂": dict(bg=(0.04, 0.045, 0.055, 0.9), mats=[
        ("整流罩 · 珠光白", dict(color=YEL_BRIGHT, metallic=0.55, rough=0.18, coat=1.0)),
        ("注塑ABS · 瓷白", dict(color=(0.018, 0.018, 0.02), metallic=0.1, rough=0.35)),
        ("阳极氧化铝 · 动力红", dict(color=YEL, metallic=1.0, rough=0.30)),
        ("阳极氧化铝 · 深空灰", dict(color=(0.012, 0.012, 0.014), metallic=1.0, rough=0.30)),
        ("前视窗 · 熏黑", dict(color=(0.004, 0.006, 0.012), metallic=0.4, rough=0.05)),
        ("LED · 状态灯", dict(emission=(0.15, 0.55, 1.0), em_str=10.0)),
    ]),
    # C 暗夜战甲：枪黑主体 + 能量黄发光动力单元，潜行机甲
    "C_暗夜战甲": dict(bg=(0.015, 0.015, 0.02, 0.55), mats=[
        ("整流罩 · 珠光白", dict(color=GUN, metallic=0.9, rough=0.34, coat=0.6)),
        ("注塑ABS · 瓷白", dict(color=(0.05, 0.05, 0.055), metallic=0.3, rough=0.5)),
        ("阳极氧化铝 · 动力红", dict(color=(0.45, 0.33, 0.02), metallic=1.0, rough=0.28,
                                     emission=(1.0, 0.72, 0.08), em_str=2.2)),
        ("LED · 状态灯", dict(emission=(1.0, 0.78, 0.12), em_str=12.0)),
        ("前视窗 · 熏黑", dict(emission=(1.0, 0.72, 0.08), em_str=1.6)),
    ]),
    # D 赛博工程：哑光黄 + 水泥灰 + 橙色细节，粗粝工具感
    "D_赛博工程": dict(bg=(0.03, 0.035, 0.045, 0.8), mats=[
        ("整流罩 · 珠光白", dict(color=(0.78, 0.58, 0.09), metallic=0.3, rough=0.55)),
        ("注塑ABS · 瓷白", dict(color=(0.30, 0.30, 0.31), metallic=0.1, rough=0.7)),
        ("阳极氧化铝 · 深空灰", dict(color=(0.33, 0.34, 0.36), metallic=0.6, rough=0.6)),
        ("阳极氧化铝 · 动力红", dict(color=(0.88, 0.32, 0.03), metallic=0.8, rough=0.4)),
        ("LED · 状态灯", dict(emission=(0.2, 0.9, 1.0), em_str=10.0)),
        ("前视窗 · 熏黑", dict(emission=(0.2, 0.9, 1.0), em_str=1.2)),
    ]),
}

cam = bpy.data.objects.get("ReviewCam")
if cam:
    sc.camera = cam
    cam.location = (1.15, -1.15, 0.68)
    d = Vector((0, 0, -0.03)) - cam.location
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

for name, cfg in STYLES.items():
    for mat_name, kw in cfg["mats"]:
        set_mat(mat_name, **kw)
    set_world(cfg["bg"][:3], cfg["bg"][3])
    sc.render.filepath = os.path.join(OUT, f"style_{name}.png")
    bpy.ops.render.render(write_still=True)
    print("rendered", name)
print("STYLES DONE")
