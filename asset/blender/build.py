# CR-30 city logistics delivery quadcopter — parametric build (Blender 5.2, Z-up meters)
# Hierarchy: CR30_Assembly > SYS_<code> > <SYS>_<COMP> > parts (SYS_COMP_PartName_NN)
# Extras per part: system / explodeDir (glTF Y-up space) / explodeDist / stagger
import bpy, math, os, sys, csv, random
from mathutils import Vector, Matrix

random.seed(30)
ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ROOT = ARGV[0] if ARGV else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEX = os.path.join(ROOT, "textures")
OUT = os.path.join(ROOT, "out")
DOCS = os.path.join(os.path.dirname(ROOT), "docs")
os.makedirs(OUT, exist_ok=True)

# ---------- reset ----------
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.unit_settings.system = 'METRIC'
sc.unit_settings.scale_length = 1.0
sc.render.engine = 'BLENDER_EEVEE'

COL = bpy.context.collection
REG = []          # BOM registry
PARTS = []        # part objects

def b2g(v):
    """Blender Z-up vector -> glTF Y-up vector."""
    return [v[0], v[2], -v[1]]

def g2b(v):
    return Vector((v[0], -v[2], v[1]))

# ---------- materials ----------
def mat_principled(name, color, metallic, roughness, coat=0.0, emission=None, em_str=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bs.inputs["Base Color"].default_value = (*color, 1.0)
    bs.inputs["Metallic"].default_value = metallic
    bs.inputs["Roughness"].default_value = roughness
    if coat:
        bs.inputs["Coat Weight"].default_value = coat
        bs.inputs["Coat Roughness"].default_value = 0.12
    if emission:
        bs.inputs["Emission Color"].default_value = (*emission, 1.0)
        bs.inputs["Emission Strength"].default_value = em_str
    nt.links.new(bs.outputs["BSDF"], out.inputs["Surface"])
    return m

def add_tex(m, path, colorspace, to_input, scale_input=None):
    nt = m.node_tree
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = colorspace
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
    bs = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    if to_input == "Normal":
        nm = nt.nodes.new("ShaderNodeNormalMap")
        if scale_input is not None:
            nm.inputs["Strength"].default_value = scale_input
        nt.links.new(tex.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bs.inputs["Normal"])
    else:
        nt.links.new(tex.outputs["Color"], bs.inputs[to_input])
    return tex

MAT = {}
MAT["carbon"]  = mat_principled("碳纤维 · 2K斜纹清漆", (0.055, 0.058, 0.065), 0.0, 0.28, coat=1.0)
add_tex(MAT["carbon"], os.path.join(TEX, "carbon_2k.png"), "sRGB", "Base Color")
add_tex(MAT["carbon"], os.path.join(TEX, "carbon_2k_normal.png"), "Non-Color", "Normal", 0.9)
MAT["alu_d"]   = mat_principled("阳极氧化铝 · 深空灰", (0.21, 0.22, 0.25), 1.0, 0.35)
MAT["alu"]     = mat_principled("铝合金 · 本色", (0.68, 0.70, 0.73), 1.0, 0.30)
MAT["red"]     = mat_principled("阳极氧化铝 · 能量黄", (0.45, 0.33, 0.02), 1.0, 0.28,
                                emission=(1.0, 0.72, 0.08), em_str=2.2)
MAT["pcb"]     = mat_principled("PCB · 绿阻焊丝印", (0.05, 0.30, 0.12), 0.15, 0.50)
add_tex(MAT["pcb"], os.path.join(TEX, "pcb_1k.png"), "sRGB", "Base Color")
MAT["abs"]     = mat_principled("注塑ABS · 哑黑", (0.022, 0.023, 0.026), 0.0, 0.55)
add_tex(MAT["abs"], os.path.join(TEX, "abs_normal.png"), "Non-Color", "Normal", 0.25)
MAT["abs_w"]   = mat_principled("注塑ABS · 石墨黑", (0.05, 0.05, 0.055), 0.3, 0.50)
add_tex(MAT["abs_w"], os.path.join(TEX, "abs_normal.png"), "Non-Color", "Normal", 0.20)
MAT["abs_panel"] = mat_principled("注塑ABS · 石墨装甲", (0.05, 0.05, 0.055), 0.3, 0.48)
add_tex(MAT["abs_panel"], os.path.join(TEX, "panel_normal_1k.png"), "Non-Color", "Normal", 0.5)
MAT["canopy"]  = mat_principled("整流罩 · 枪黑战甲", (0.055, 0.055, 0.06), 0.9, 0.34, coat=0.6)
add_tex(MAT["canopy"], os.path.join(TEX, "panel_normal_1k.png"), "Non-Color", "Normal", 0.7)
MAT["visor"]   = mat_principled("前视窗 · 熏黑", (0.015, 0.02, 0.03), 0.3, 0.08, coat=1.0,
                                emission=(1.0, 0.72, 0.08), em_str=0.8)
MAT["foam"]    = mat_principled("减震泡棉", (0.045, 0.045, 0.05), 0.0, 0.90)
add_tex(MAT["foam"], os.path.join(TEX, "foam_normal.png"), "Non-Color", "Normal", 0.5)
MAT["rubber"]  = mat_principled("橡胶脚垫", (0.02, 0.02, 0.022), 0.0, 0.85)
MAT["steel"]   = mat_principled("合金钢 · 发黑", (0.17, 0.17, 0.185), 1.0, 0.42)
MAT["nylon"]   = mat_principled("尼龙 · 防松圈", (0.85, 0.85, 0.82), 0.0, 0.60)
MAT["silicone"]= mat_principled("硅胶减震球", (0.72, 0.26, 0.08), 0.0, 0.75)
MAT["gold"]    = mat_principled("镀金触点", (0.83, 0.66, 0.20), 1.0, 0.25)
MAT["glass"]   = mat_principled("镜头玻璃", (0.012, 0.018, 0.03), 0.0, 0.05, coat=1.0)
MAT["led"]     = mat_principled("LED · 状态灯", (0.05, 0.04, 0.01), 0.0, 0.3, emission=(1.0, 0.78, 0.12), em_str=12.0)
MAT["copper"]  = mat_principled("漆包铜线", (0.45, 0.18, 0.06), 1.0, 0.35)

# ---------- geometry helpers ----------
def finish(obj, name, mat, parent, explode_dir_b, stagger, system, sub,
             standard="", qty=1, dist=0.35, bevel=0.0, smooth=False, uv_cube=None):
    obj.name = name
    if mat:
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
    if bevel > 0:
        mod = obj.modifiers.new("Bevel", 'BEVEL')
        mod.width = bevel; mod.segments = 3; mod.limit_method = 'ANGLE'
        activate(obj)
        bpy.ops.object.modifier_apply(modifier=mod.name)
    if smooth:
        for p in obj.data.polygons:
            p.use_smooth = True
    if uv_cube:
        activate(obj)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.cube_project(cube_size=uv_cube)
        bpy.ops.object.mode_set(mode='OBJECT')
    obj.parent = parent
    obj["system"] = system
    obj["explodeDir"] = b2g(Vector(explode_dir_b).normalized())
    obj["explodeDist"] = float(dist)
    obj["stagger"] = float(stagger)
    REG.append(dict(name=name, system=system, sub=sub, qty=qty,
                    material=mat.name if mat else "-", standard=standard))
    PARTS.append(obj)
    return obj

def link_to_col(obj):
    COL.objects.link(obj)
    return obj

def activate(o):
    bpy.ops.object.select_all(action='DESELECT')
    o.select_set(True)
    bpy.context.view_layer.objects.active = o

def box(name, dims, loc, rot, mat, parent, ed, stag, system, sub,
        standard="", dist=0.35, bevel=0.002, uv_cube=None):
    bpy.ops.mesh.primitive_cube_add(location=loc, rotation=rot)
    o = bpy.context.object
    o.scale = (dims[0] / 2, dims[1] / 2, dims[2] / 2)
    activate(o)
    bpy.ops.object.transform_apply(scale=True)
    return finish(o, name, mat, parent, ed, stag, system, sub,
                  standard=standard, dist=dist, bevel=bevel, uv_cube=uv_cube)

def cyl(name, r, h, loc, rot, mat, parent, ed, stag, system, sub,
        standard="", dist=0.35, bevel=0.0, verts=24, uv_cube=None):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=h, location=loc, rotation=rot)
    o = bpy.context.object
    return finish(o, name, mat, parent, ed, stag, system, sub,
                  standard=standard, dist=dist, bevel=bevel, smooth=True, uv_cube=uv_cube)

def sph(name, r, scale, loc, mat, parent, ed, stag, system, sub,
        standard="", dist=0.35, uv_cube=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=40, ring_count=24, radius=r, location=loc)
    o = bpy.context.object
    o.scale = scale
    activate(o)
    bpy.ops.object.transform_apply(scale=True)
    return finish(o, name, mat, parent, ed, stag, system, sub,
                  standard=standard, dist=dist, smooth=True, uv_cube=uv_cube)

def torus(name, R, r, loc, rot, mat, parent, ed, stag, system, sub,
          standard="", dist=0.35):
    bpy.ops.mesh.primitive_torus_add(major_radius=R, minor_radius=r,
        major_segments=28, minor_segments=10, location=loc, rotation=rot)
    o = bpy.context.object
    return finish(o, name, mat, parent, ed, stag, system, sub, standard=standard,
                  dist=dist, smooth=True)

def cyl_between(name, p1, p2, r, mat, parent, ed, stag, system, sub,
                standard="", dist=0.35):
    p1, p2 = Vector(p1), Vector(p2)
    d = p2 - p1
    mid = (p1 + p2) / 2
    bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=r, depth=d.length, location=mid)
    o = bpy.context.object
    o.rotation_mode = 'QUATERNION'
    o.rotation_quaternion = d.to_track_quat('Z', 'Y')
    return finish(o, name, mat, parent, ed, stag, system, sub,
                  standard=standard, dist=dist, smooth=True)

def join(objs, name):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    o = bpy.context.object
    o.name = name
    return o

def raw_cyl(r, h, loc=(0, 0, 0), rot=(0, 0, 0), verts=20):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=h, location=loc, rotation=rot)
    return bpy.context.object

def raw_box(dims, loc=(0, 0, 0), rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(location=loc, rotation=rot)
    o = bpy.context.object
    o.scale = (dims[0] / 2, dims[1] / 2, dims[2] / 2)
    activate(o)
    bpy.ops.object.transform_apply(scale=True)
    return o

# ---------- hierarchy ----------
ROOT_E = bpy.data.objects.new("CR30_Assembly", None); link_to_col(ROOT_E)
SYS_E = {}
def sys_empty(code, zh):
    e = bpy.data.objects.new("SYS_" + code, None)
    link_to_col(e); e.parent = ROOT_E
    e["labelZh"] = zh
    SYS_E[code] = e
    return e
SUB_E = {}
def sub_empty(sys_code, comp):
    key = sys_code + "_" + comp
    if key in SUB_E:
        return SUB_E[key]
    e = bpy.data.objects.new(key, None)
    link_to_col(e); e.parent = SYS_E[sys_code]
    SUB_E[key] = e
    return e

for c, z in [("SHELL", "外壳与整流罩"), ("FRAME", "机架系统"), ("PWR", "动力系统"),
             ("BAT", "能源系统"), ("FC", "飞控与航电"), ("SENS", "感知系统"),
             ("CARGO", "货舱与投放机构"), ("LAND", "起落架"), ("STD", "标准件系统")]:
    sys_empty(c, z)

# ---------- layout constants ----------
R_MOTOR = 0.55
ARMS = {"FR": 45.0, "FL": 135.0, "RL": 225.0, "RR": 315.0}
Z_UP, Z_LO = 0.028, -0.022      # plate centers
PLATE_T = 0.002
def arm_xy(deg, r):
    a = math.radians(deg)
    return Vector((r * math.cos(a), r * math.sin(a), 0))

# ============================================================ FRAME
pe = sub_empty("FRAME", "PLATE")
box("FRAME_PLATE_UpperCarbonPlate_01", (0.34, 0.34, PLATE_T), (0, 0, Z_UP), (0, 0, 0),
    MAT["carbon"], pe, (0, 0, 1), 0.15, "FRAME", "PLATE", dist=0.28, bevel=0.006, uv_cube=0.064)
box("FRAME_PLATE_LowerCarbonPlate_01", (0.34, 0.34, PLATE_T), (0, 0, Z_LO), (0, 0, 0),
    MAT["carbon"], pe, (0, 0, -1), 0.10, "FRAME", "PLATE", dist=0.26, bevel=0.006, uv_cube=0.064)

se = sub_empty("FRAME", "STANDOFF")
for i in range(6):
    a = math.radians(i * 60 + 30)
    x, y = 0.145 * math.cos(a), 0.145 * math.sin(a)
    cyl(f"FRAME_STANDOFF_AlColumn_{i+1:02d}", 0.004, 0.046, (x, y, 0.003), (0, 0, 0),
        MAT["alu"], se, (x, y, 0), 0.20, "FRAME", "STANDOFF", dist=0.22)

for tag, deg in ARMS.items():
    dirv = arm_xy(deg, 1.0)
    ae = sub_empty("FRAME", "ARM")
    p1, p2 = arm_xy(deg, 0.16), arm_xy(deg, 0.545)
    cyl_between(f"FRAME_ARM_CarbonTube_{tag}_01", p1, p2, 0.0125, MAT["carbon"], ae,
                dirv, 0.25, "FRAME", "ARM", dist=0.30, uv_cube=0.064) if False else \
    cyl_between(f"FRAME_ARM_CarbonTube_{tag}_01", p1, p2, 0.0125, MAT["carbon"], ae,
                dirv, 0.25, "FRAME", "ARM", dist=0.30)
    je = sub_empty("FRAME", "JOINT")
    jp = arm_xy(deg, 0.185)
    box(f"FRAME_JOINT_AlArmJoint_{tag}_01", (0.062, 0.048, 0.038), (jp.x, jp.y, 0.003),
        (0, 0, math.radians(deg)), MAT["alu_d"], je, dirv, 0.22, "FRAME", "JOINT",
        dist=0.26, bevel=0.004)
    ce = sub_empty("FRAME", "CLASP")
    cp = arm_xy(deg, 0.195)
    box(f"FRAME_CLASP_FoldingLatch_{tag}_01", (0.030, 0.014, 0.028),
        (cp.x, cp.y, 0.030), (math.radians(18), 0, math.radians(deg)),
        MAT["alu_d"], ce, (dirv.x, dirv.y, 0.6), 0.30, "FRAME", "CLASP", dist=0.30, bevel=0.002)
    for k, sgn in enumerate((-1, 1)):
        off = Vector((-dirv.y, dirv.x, 0)) * 0.012 * sgn
        pp = cp + off
        cyl(f"FRAME_CLASP_LatchPin_{tag}_{k+1:02d}", 0.0025, 0.030,
            (pp.x, pp.y, 0.030), (math.pi / 2, 0, math.radians(deg)),
            MAT["steel"], ce, off, 0.55, "FRAME", "CLASP",
            standard="GB/T 882", dist=0.34)
    sp = arm_xy(deg, 0.175)
    spr = join([torus(f"tmp_s{i}", 0.004, 0.0009, (sp.x, sp.y, 0.024 + i * 0.0035),
                      (0, 0, 0), MAT["steel"], ce, (0, 0, 1), 0.5, "FRAME", "CLASP")
                for i in range(3)], "tmp_spring")
    PARTS.pop(); PARTS.pop(); PARTS.pop()
    REG.pop(); REG.pop(); REG.pop()
    finish(spr, f"FRAME_CLASP_ReturnSpring_{tag}_01", MAT["steel"], ce, (0, 0, 1),
           0.50, "FRAME", "CLASP", standard="GB/T 2089", dist=0.30)
    me = sub_empty("FRAME", "MOTORMNT")
    mp = arm_xy(deg, 0.545)
    cyl(f"FRAME_MOTORMNT_MountPlate_{tag}_01", 0.034, 0.004, (mp.x, mp.y, 0.016), (0, 0, 0),
        MAT["alu_d"], me, dirv, 0.28, "FRAME", "MOTORMNT", dist=0.26)

# ============================================================ PWR
def build_prop(name, loc, rot_z, parent, ed, stag):
    """15-inch 2-blade propeller, one mesh."""
    verts, faces = [], []
    # hub
    bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=0.011, depth=0.008)
    hub = bpy.context.object
    blades = []
    for s in (0, 1):
        r0, r1 = 0.014, 0.190
        w0, w1 = 0.024, 0.011
        t = 0.0014
        pitch = math.radians(12) * (1 if s == 0 else 1)
        ang = math.pi * s
        ca, sa = math.cos(ang), math.sin(ang)
        def rot(p):
            x, y, z = p
            return (x * ca - y * sa, x * sa + y * ca, z)
        v = []
        for (rr, ww, lift) in ((r0, w0, 0.0), (r1, w1, 0.006)):
            dx, dy = math.sin(pitch) * lift, math.cos(pitch) * lift
            v += [rot((rr, -ww / 2, -t / 2 + dy)), rot((rr, ww / 2, -t / 2 + dy)),
                  rot((rr, ww / 2, t / 2 + dy)), rot((rr, -ww / 2, t / 2 + dy))]
        base = len(verts)
        verts += v
        faces += [(base+0, base+1, base+2, base+3), (base+4, base+7, base+6, base+5),
                  (base+0, base+4, base+5, base+1), (base+1, base+5, base+6, base+2),
                  (base+2, base+6, base+7, base+3), (base+3, base+7, base+4, base+0)]
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(verts, [], faces); mesh.update()
    bl = bpy.data.objects.new("tmp_blade", mesh); link_to_col(bl)
    prop = join([hub, bl], name + "_j")
    prop.location = loc; prop.rotation_euler[2] = rot_z
    bevm = prop.modifiers.new("Bevel", 'BEVEL'); bevm.width = 0.0012; bevm.segments = 2
    activate(prop)
    bpy.ops.object.modifier_apply(modifier=bevm.name)
    return finish(prop, name, MAT["carbon"], parent, ed, stag, "PWR", "PROP",
                  dist=0.52, smooth=False)

for tag, deg in ARMS.items():
    a = math.radians(deg)
    mx, my = R_MOTOR * math.cos(a), R_MOTOR * math.sin(a)
    comp = "MOTOR-" + tag
    me = sub_empty("PWR", comp)
    dirv = arm_xy(deg, 1.0)
    cyl(f"PWR_{comp}_StatorBase_01", 0.023, 0.010, (mx, my, 0.024), (0, 0, 0),
        MAT["alu_d"], me, (0, 0, -1), 0.10, "PWR", comp, dist=0.22)
    # copper stator winding hint ring (separate part: stator winding)
    torus(f"PWR_{comp}_StatorWinding_01", 0.018, 0.005, (mx, my, 0.032), (0, 0, 0),
          MAT["copper"], me, (0, 0, -1), 0.14, "PWR", comp, dist=0.24)
    for k, z in enumerate((0.026, 0.038)):
        cyl(f"PWR_{comp}_Bearing_6201_{k+1:02d}", 0.008, 0.005, (mx, my, z), (0, 0, 0),
            MAT["steel"], me, (0, 0, 1), 0.20 + k * 0.05, "PWR", comp,
            standard="GB/T 276 6201", dist=0.30)
    bell = join([raw_cyl(0.0275, 0.014, (mx, my, 0.040)),
                 raw_cyl(0.024, 0.006, (mx, my, 0.048))], "tmp_bell")
    finish(bell, f"PWR_{comp}_RotorBell_01", MAT["red"], me, (0, 0, 1), 0.28,
           "PWR", comp, dist=0.34, smooth=True)
    cyl(f"PWR_{comp}_Shaft_01", 0.003, 0.052, (mx, my, 0.046), (0, 0, 0),
        MAT["steel"], me, (0, 0, 1), 0.32, "PWR", comp, dist=0.36)
    build_prop(f"PWR_PROP-{tag}_Propeller15in_01", (mx, my, 0.066), a,
               sub_empty("PWR", "PROP-" + tag), (0, 0, 1), 0.45)
    cyl(f"PWR_PROP-{tag}_PropClamp_01", 0.010, 0.006, (mx, my, 0.070), (0, 0, 0),
        MAT["alu_d"], sub_empty("PWR", "PROP-" + tag), (0, 0, 1), 0.60, "PWR",
        "PROP-" + tag, dist=0.50)
    cyl(f"PWR_PROP-{tag}_SelfLockNut_01", 0.0055, 0.006, (mx, my, 0.077), (0, 0, 0),
        MAT["steel"], sub_empty("PWR", "PROP-" + tag), (0, 0, 1), 0.95, "PWR",
        "PROP-" + tag, standard="DIN 985 M5", dist=0.56, verts=6)
    ee = sub_empty("PWR", "ESC-" + tag)
    ex, ey = 0.36 * math.cos(a), 0.36 * math.sin(a)
    box(f"PWR_ESC-{tag}_ESC60A_01", (0.046, 0.026, 0.009), (ex, ey, 0.018),
        (0, 0, a), MAT["abs"], ee, dirv, 0.30, "PWR", "ESC-" + tag, dist=0.26, bevel=0.002)
    fins = [raw_box((0.040, 0.002, 0.006), (ex - 0.020 * math.sin(a) * 0 +
            (i - 2.5) * 0.005 * -math.sin(a), ey + (i - 2.5) * 0.005 * math.cos(a), 0.026))
            for i in range(5)]
    hs = join(fins, "tmp_hs")
    finish(hs, f"PWR_ESC-{tag}_Heatsink_01", MAT["alu"], ee, (dirv.x, dirv.y, 0.5),
           0.38, "PWR", "ESC-" + tag, dist=0.28)

# ============================================================ BAT
be = sub_empty("BAT", "PACK")
box("BAT_PACK_SmartBattery10S_01", (0.168, 0.235, 0.108), (0, -0.01, 0.004), (0, 0, 0),
    MAT["abs"], be, (0, -1, 0), 0.20, "BAT", "PACK", dist=0.42, bevel=0.008, uv_cube=0.05)
handle = join([raw_cyl(0.005, 0.090, (-0.045, -0.01, 0.072), (0, math.pi / 2, 0)),
               raw_cyl(0.005, 0.090, (0.045, -0.01, 0.072), (0, math.pi / 2, 0)),
               raw_cyl(0.005, 0.120, (0, -0.01, 0.088), (0, math.pi / 2, 0))], "tmp_handle")
finish(handle, "BAT_PACK_CarryHandle_01", MAT["abs_w"], be, (0, 0, 1), 0.55,
       "BAT", "PACK", dist=0.34, smooth=True)
for k, x in enumerate((-0.030, 0.030)):
    cyl(f"BAT_PACK_PowerContact_{k+1:02d}", 0.006, 0.008, (x, -0.132, 0.028),
        (math.pi / 2, 0, 0), MAT["gold"], be, (0, -1, 0.3), 0.60, "BAT", "PACK",
        standard="XT60", dist=0.40)
for k, sgn in enumerate((-1, 1)):
    box(f"BAT_PACK_AntiMistakeLatch_{k+1:02d}", (0.012, 0.030, 0.024),
        (sgn * 0.092, -0.06, 0.010), (0, 0, 0), MAT["abs_w"], be, (sgn, 0, 0.2),
        0.50, "BAT", "PACK", dist=0.36, bevel=0.002)
re = sub_empty("BAT", "RAIL")
for k, sgn in enumerate((-1, 1)):
    box(f"BAT_RAIL_SlideRail_{k+1:02d}", (0.010, 0.250, 0.014), (sgn * 0.098, -0.01, -0.012),
        (0, 0, 0), MAT["alu"], re, (sgn, 0, 0), 0.15, "BAT", "RAIL", dist=0.24, bevel=0.001)
box("BAT_RAIL_ContactPlate_01", (0.070, 0.008, 0.040), (0, -0.145, 0.028), (0, 0, 0),
    MAT["pcb"], re, (0, -1, 0), 0.18, "BAT", "RAIL", dist=0.26, bevel=0.001)

# ============================================================ FC
fe = sub_empty("FC", "FC")
box("FC_FC_FlightControllerPCB_01", (0.100, 0.100, 0.0016), (0, 0, 0.006), (0, 0, 0),
    MAT["pcb"], fe, (0, 0, 1), 0.15, "FC", "FC", dist=0.24, bevel=0.0005, uv_cube=0.1)
box("FC_FC_ShieldCover_01", (0.062, 0.062, 0.010), (0, 0, 0.014), (0, 0, 0),
    MAT["alu"], fe, (0, 0, 1), 0.35, "FC", "FC", dist=0.28, bevel=0.002)
box("FC_FC_IMUCarrier_01", (0.030, 0.030, 0.002), (0, 0, 0.022), (0, 0, 0),
    MAT["abs"], fe, (0, 0, 1), 0.30, "FC", "FC", dist=0.27)
for k in range(4):
    a = math.radians(45 + k * 90)
    x, y = 0.011 * math.cos(a), 0.011 * math.sin(a)
    sph(f"FC_FC_IMUDampingBall_{k+1:02d}", 0.0055, (1, 1, 1.15), (x, y, 0.020),
        MAT["silicone"], fe, (x, y, 0.8), 0.42, "FC", "FC",
        standard="GB/T 20688", dist=0.30)
sph("FC_FC_BarometerCover_01", 0.009, (1, 1, 0.6), (0.032, 0.032, 0.010),
    MAT["foam"], fe, (0.5, 0.5, 1), 0.40, "FC", "FC", dist=0.26)
cyl("FC_FC_Buzzer_01", 0.0065, 0.004, (-0.034, -0.034, 0.009), (0, 0, 0),
    MAT["abs"], fe, (-0.4, -0.4, 1), 0.40, "FC", "FC", dist=0.26)
box("FC_FC_StatusLEDModule_01", (0.018, 0.006, 0.003), (0, -0.152, 0.010), (0, 0, 0),
    MAT["pcb"], fe, (0, -1, 0.4), 0.45, "FC", "FC", dist=0.28)
box("FC_FC_LEDLens_01", (0.016, 0.004, 0.0025), (0, -0.157, 0.010), (0, 0, 0),
    MAT["led"], fe, (0, -1, 0.6), 0.60, "FC", "FC", dist=0.32)

# ============================================================ SENS
ge = sub_empty("SENS", "GPS")
cyl("SENS_GPS_MastBase_01", 0.020, 0.007, (0, -0.05, 0.096), (0, 0, 0),
    MAT["abs"], ge, (0, 0, 1), 0.20, "SENS", "GPS", dist=0.30)
cyl("SENS_GPS_MastPole_01", 0.004, 0.085, (0, -0.05, 0.140), (0, 0, 0),
    MAT["carbon"], ge, (0, 0, 1), 0.30, "SENS", "GPS", dist=0.38)
sph("SENS_GPS_GNSSCompassModule_01", 0.028, (1, 1, 0.45), (0, -0.05, 0.188),
    MAT["abs_w"], ge, (0, 0, 1), 0.55, "SENS", "GPS", dist=0.46)
ve = sub_empty("SENS", "FVISION")
box("SENS_FVISION_Housing_01", (0.086, 0.030, 0.026), (0, 0.172, 0.004), (0, 0, 0),
    MAT["abs"], ve, (0, 1, 0), 0.20, "SENS", "FVISION", dist=0.30, bevel=0.004)
for k, sgn in enumerate((-1, 1)):
    x = sgn * 0.024
    cyl(f"SENS_FVISION_Lens_{k+1:02d}", 0.0085, 0.006, (x, 0.188, 0.004),
        (math.pi / 2, 0, 0), MAT["glass"], ve, (0, 1, 0), 0.50, "SENS", "FVISION", dist=0.40)
    torus(f"SENS_FVISION_LensBezel_{k+1:02d}", 0.0095, 0.0018, (x, 0.189, 0.004),
          (math.pi / 2, 0, 0), MAT["alu_d"], ve, (0, 1, 0), 0.60, "SENS", "FVISION", dist=0.44)
de = sub_empty("SENS", "DVISION")
box("SENS_DVISION_ToFModule_01", (0.026, 0.022, 0.010), (0.045, 0, -0.040), (0, 0, 0),
    MAT["abs"], de, (0, 0, -1), 0.25, "SENS", "DVISION", dist=0.28, bevel=0.002)
cyl("SENS_DVISION_DownCamera_01", 0.009, 0.012, (-0.045, 0, -0.040), (0, 0, 0),
    MAT["glass"], de, (0, 0, -1), 0.35, "SENS", "DVISION", dist=0.32)
ra = sub_empty("SENS", "RADAR")
box("SENS_RADAR_MmWaveRadar_01", (0.052, 0.036, 0.013), (0, 0.118, -0.038), (0, 0, 0),
    MAT["abs_w"], ra, (0, 0.4, -1), 0.25, "SENS", "RADAR", dist=0.30, bevel=0.003)

# ============================================================ CARGO
ce = sub_empty("CARGO", "BAY")
box("CARGO_BAY_Shell_01", (0.260, 0.215, 0.155), (0, 0, -0.137), (0, 0, 0),
    MAT["abs_panel"], ce, (0, 0, -1), 0.15, "CARGO", "BAY", dist=0.30, bevel=0.010, uv_cube=0.06)
box("CARGO_BAY_ReleaseDoor_01", (0.240, 0.195, 0.007), (0, 0, -0.218), (0, 0, 0),
    MAT["abs"], ce, (0, 0, -1), 0.55, "CARGO", "BAY", dist=0.44, bevel=0.004)
box("CARGO_BAY_ElectromagneticLock_01", (0.036, 0.020, 0.018), (0.115, 0, -0.200),
    (0, 0, 0), MAT["alu_d"], ce, (1, 0, -0.4), 0.40, "CARGO", "BAY", dist=0.34, bevel=0.002)
box("CARGO_BAY_LockTongue_01", (0.010, 0.016, 0.004), (0.095, 0, -0.212), (0, 0, 0),
    MAT["steel"], ce, (1, 0, -0.6), 0.62, "CARGO", "BAY", dist=0.40)
te = sub_empty("CARGO", "DROP")
box("CARGO_DROP_ServoWinch_01", (0.032, 0.020, 0.026), (-0.08, 0, -0.062), (0, 0, 0),
    MAT["alu_d"], te, (0, 0, -1), 0.30, "CARGO", "DROP", dist=0.30, bevel=0.002)
cyl("CARGO_DROP_WinchDrum_01", 0.010, 0.014, (-0.08, 0.016, -0.062), (math.pi / 2, 0, 0),
    MAT["steel"], te, (0, 0.4, -1), 0.45, "CARGO", "DROP", dist=0.34)
for k, sgn in enumerate((-1, 1)):
    cyl_between(f"CARGO_DROP_ReleaseLinkRod_{k+1:02d}", (sgn * 0.06, 0, -0.070),
                (sgn * 0.09, 0, -0.205), 0.0022, MAT["steel"], te, (sgn * 0.4, 0, -1),
                0.55, "CARGO", "DROP", dist=0.38)
for k, sgn in enumerate((-1, 1)):
    box(f"CARGO_DROP_LoadCell_{k+1:02d}", (0.040, 0.010, 0.008), (sgn * 0.09, 0, -0.058),
        (0, 0, 0), MAT["alu"], te, (sgn, 0, -0.5), 0.35, "CARGO", "DROP",
        standard="GB/T 7551", dist=0.30, bevel=0.001)
cyl("CARGO_DROP_PayloadHook_01", 0.006, 0.020, (0, 0, -0.232), (0, 0, 0),
    MAT["steel"], te, (0, 0, -1), 0.65, "CARGO", "DROP", dist=0.48)

# ============================================================ LAND
for k, (tag, deg) in enumerate(ARMS.items()):
    a = math.radians(deg)
    le = sub_empty("LAND", "LEG-" + tag)
    top = Vector((0.30 * math.cos(a), 0.30 * math.sin(a), -0.022))
    bot = Vector((0.40 * math.cos(a), 0.40 * math.sin(a), -0.375))
    box(f"LAND_LEG-{tag}_LegMount_01", (0.034, 0.026, 0.018), tuple(top), (0, 0, a),
        MAT["alu_d"], le, (top.x, top.y, -1), 0.20, "LAND", "LEG-" + tag, dist=0.28, bevel=0.003)
    cyl_between(f"LAND_LEG-{tag}_CarbonLeg_01", top, bot, 0.0085, MAT["carbon"], le,
                (bot.x, bot.y, -1), 0.30, "LAND", "LEG-" + tag, dist=0.36)
    mid = top.lerp(bot, 0.72)
    cyl_between(f"LAND_LEG-{tag}_FoamSleeve_01", top.lerp(bot, 0.55), top.lerp(bot, 0.9),
                0.0135, MAT["foam"], le, (bot.x, bot.y, -1), 0.45, "LAND", "LEG-" + tag, dist=0.40)
    sph(f"LAND_LEG-{tag}_FootPad_01", 0.016, (1, 1, 0.55), tuple(bot + Vector((0, 0, -0.006))),
        MAT["rubber"], le, (bot.x, bot.y, -1), 0.60, "LAND", "LEG-" + tag, dist=0.44)

# ============================================================ SHELL
sh = sub_empty("SHELL", "CANOPY")
sph("SHELL_CANOPY_MainCanopy_01", 0.10, (1.85, 1.62, 0.72), (0, 0, 0.032),
    MAT["canopy"], sh, (0, 0, 1), 0.30, "SHELL", "CANOPY", dist=0.40, uv_cube=0.064)
sph("SHELL_VISOR_FrontVisor_01", 0.05, (1.5, 1.0, 0.62), (0, 0.128, 0.045),
    MAT["visor"], sub_empty("SHELL", "VISOR"), (0, 1, 0.5), 0.45, "SHELL", "VISOR", dist=0.44)
cyl("SHELL_HATCH_GPSHatch_01", 0.034, 0.004, (0, -0.05, 0.0965), (0, 0, 0),
    MAT["canopy"], sub_empty("SHELL", "HATCH"), (0, 0, 1), 0.55, "SHELL", "HATCH", dist=0.42,
    uv_cube=0.05)
torus("SHELL_CANOPY_SealRing_01", 0.148, 0.006, (0, 0, 0.032), (0, 0, 0),
      MAT["rubber"], sh, (0, 0, 1), 0.20, "SHELL", "CANOPY", dist=0.34)
for k, sgn in enumerate((-1, 1)):
    slats = [raw_box((0.003, 0.050, 0.006), (sgn * 0.168, -0.02 + i * 0.016, 0.052))
             for i in range(4)]
    vent = join(slats, "tmp_vent")
    finish(vent, f"SHELL_VENT_CoolingGrill_{k+1:02d}", MAT["abs"], sub_empty("SHELL", "VENT"),
           (sgn, 0, 0.4), 0.50, "SHELL", "VENT", dist=0.38)
for tag, deg in ARMS.items():
    a = math.radians(deg)
    dirv = arm_xy(deg, 1.0)
    cen = arm_xy(deg, 0.35)
    se2 = sub_empty("SHELL", "ARMSHELL")
    box(f"SHELL_ARMSHELL_UpperCover_{tag}_01", (0.330, 0.034, 0.005),
        (cen.x, cen.y, 0.017), (0, 0, a), MAT["canopy"], se2, (0, 0, 1), 0.35,
        "SHELL", "ARMSHELL", dist=0.30, bevel=0.002, uv_cube=0.05)
    box(f"SHELL_ARMSHELL_LowerCover_{tag}_01", (0.330, 0.034, 0.005),
        (cen.x, cen.y, -0.008), (0, 0, a), MAT["abs"], se2, (0, 0, -1), 0.35,
        "SHELL", "ARMSHELL", dist=0.28, bevel=0.002)

# ============================================================ STD (fasteners)
PROTOS = {}

def hex_recess(obj, r, depth, top_z):
    cutter = raw_cyl(r, depth, (0, 0, top_z - depth / 2 + 0.0002), verts=6)
    mod = obj.modifiers.new("Bool", 'BOOLEAN')
    mod.operation = 'DIFFERENCE'; mod.solver = 'EXACT'; mod.object = cutter
    activate(obj)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(cutter)

def proto_socket(name, r_shaft, l_shaft, r_head, h_head, hex_r):
    shaft = raw_cyl(r_shaft, l_shaft, (0, 0, -l_shaft / 2))
    head = raw_cyl(r_head, h_head, (0, 0, h_head / 2))
    o = join([shaft, head], name)
    hex_recess(o, hex_r, h_head * 0.55, h_head)
    bevm = o.modifiers.new("Bevel", 'BEVEL'); bevm.width = 0.0003; bevm.segments = 2
    activate(o)
    bpy.ops.object.modifier_apply(modifier=bevm.name)
    for p in o.data.polygons:
        p.use_smooth = True
    return o

def proto_button(name, r_shaft, l_shaft, r_head, h_head):
    shaft = raw_cyl(r_shaft, l_shaft, (0, 0, -l_shaft / 2))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=12, radius=r_head,
                                         location=(0, 0, h_head * 0.15))
    hd = bpy.context.object
    hd.scale = (1, 1, h_head / r_head)
    activate(hd)
    bpy.ops.object.transform_apply(scale=True)
    o = join([shaft, hd], name)
    for p in o.data.polygons:
        p.use_smooth = True
    return o

def proto_washer(name, r_out, r_in, h):
    o = raw_cyl(r_out, h)
    cutter = raw_cyl(r_in, h * 3)
    mod = o.modifiers.new("Bool", 'BOOLEAN'); mod.operation = 'DIFFERENCE'
    mod.solver = 'EXACT'; mod.object = cutter
    activate(o)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(cutter)
    o.name = name
    return o

def proto_nyloc(name, r_hex, h, r_ring):
    nut = raw_cyl(r_hex, h, verts=6)
    ring = raw_cyl(r_ring, h * 0.35, (0, 0, h / 2 + h * 0.175))
    ring.data.materials.append(MAT["nylon"])
    nut.data.materials.append(MAT["steel"])
    o = join([nut, ring], name)
    return o

def proto_springwasher(name, r, t):
    bpy.ops.mesh.primitive_torus_add(major_radius=r, minor_radius=t,
        major_segments=20, minor_segments=8, location=(0, 0, 0))
    o = bpy.context.object
    o.scale = (1, 1, 1.6)
    activate(o)
    bpy.ops.object.transform_apply(scale=True)
    o.name = name
    return o

def new_proto(key, obj, mat):
    if mat and not obj.data.materials:
        obj.data.materials.append(mat)
    PROTOS[key] = obj
    return obj

new_proto("M2", proto_socket("p_m2", 0.001, 0.006, 0.0019, 0.002, 0.00087), MAT["steel"])
new_proto("M3", proto_socket("p_m3", 0.0015, 0.008, 0.00275, 0.003, 0.00144), MAT["steel"])
new_proto("M4", proto_socket("p_m4", 0.002, 0.010, 0.0035, 0.004, 0.00173), MAT["steel"])
new_proto("M3B", proto_button("p_m3b", 0.0015, 0.006, 0.0028, 0.00165), MAT["steel"])
new_proto("W3", proto_washer("p_w3", 0.0035, 0.0017, 0.0005), MAT["steel"])
new_proto("W4", proto_washer("p_w4", 0.0045, 0.0022, 0.0008), MAT["steel"])
new_proto("SW4", proto_springwasher("p_sw4", 0.003, 0.0007), MAT["steel"])
new_proto("NL3", proto_nyloc("p_nl3", 0.00275, 0.0032, 0.0023), None)

STD_NAMES = {
    "M2": ("SocketScrewM2", "ISO 4762 M2×6"),
    "M3": ("SocketScrewM3", "ISO 4762 M3×8"),
    "M4": ("SocketScrewM4", "ISO 4762 M4×10"),
    "M3B": ("ButtonScrewM3", "ISO 7380 M3×6"),
    "W3": ("FlatWasherM3", "ISO 7089 3"),
    "W4": ("FlatWasherM4", "ISO 7089 4"),
    "SW4": ("SpringWasherM4", "GB/T 93 4"),
    "NL3": ("NylocNutM3", "DIN 985 M3"),
}
fe = sub_empty("STD", "FAST")
_counter = {}

def place(proto, loc, normal, stagger=0.9, dist=0.42):
    base, std = STD_NAMES[proto]
    key = base
    _counter[key] = _counter.get(key, 0) + 1
    name = f"STD_FAST_{base}_{_counter[key]:02d}"
    src = PROTOS[proto]
    o = src.copy()
    link_to_col(o)
    o.location = loc
    o.rotation_mode = 'QUATERNION'
    o.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(Vector(normal).normalized())
    finish(o, name, None, fe, normal, stagger, "STD", "FAST", standard=std, dist=dist)
    return o

UP, DOWN = (0, 0, 1), (0, 0, -1)
# canopy M2 ×4
for x, y in ((0.10, 0.095), (-0.10, 0.095), (0.10, -0.095), (-0.10, -0.095)):
    place("M2", (x, y, 0.068), UP, 0.92, 0.46)
# standoff M3 ×12
for i in range(6):
    a = math.radians(i * 60 + 30)
    x, y = 0.145 * math.cos(a), 0.145 * math.sin(a)
    place("M3", (x, y, Z_UP + 0.003), UP, 0.85, 0.40)
    place("M3", (x, y, Z_LO - 0.003), DOWN, 0.85, 0.40)
# arm joints M4 ×16 + spring washers ×16
for tag, deg in ARMS.items():
    a = math.radians(deg)
    jp = arm_xy(deg, 0.185)
    ca, sa = math.cos(a), math.sin(a)
    for dx, dy in ((0.019, 0.014), (0.019, -0.014), (-0.019, 0.014), (-0.019, -0.014)):
        px = jp.x + dx * ca - dy * sa
        py = jp.y + dx * sa + dy * ca
        place("M4", (px, py, 0.0245), UP, 0.88, 0.44)
        place("SW4", (px, py, 0.0215), UP, 0.80, 0.40)
# motor mounts M3 ×16 + washers ×16
for tag, deg in ARMS.items():
    mp = arm_xy(deg, 0.545)
    mx, my = mp.x, mp.y
    for dx, dy in ((0.012, 0.012), (0.012, -0.012), (-0.012, 0.012), (-0.012, -0.012)):
        place("M3", (mx + dx, my + dy, 0.021), UP, 0.90, 0.44)
        place("W3", (mx + dx, my + dy, 0.0185), UP, 0.82, 0.40)
# ESC M2 ×8
for tag, deg in ARMS.items():
    a = math.radians(deg)
    ex, ey = 0.36 * math.cos(a), 0.36 * math.sin(a)
    for s in (-0.016, 0.016):
        place("M2", (ex + s * math.cos(a), ey + s * math.sin(a), 0.024), UP, 0.90, 0.42)
# battery rails M3 ×4
for sgn in (-1, 1):
    for y in (-0.10, 0.10):
        place("M3", (sgn * 0.098, y, -0.004), UP, 0.86, 0.40)
# FC M2 ×4 + washers ×4 + nyloc ×4
for sx in (-0.042, 0.042):
    for sy in (-0.042, 0.042):
        place("M2", (sx, sy, 0.0085), UP, 0.88, 0.42)
        place("W3", (sx, sy, 0.007), UP, 0.80, 0.38)
        place("NL3", (sx, sy, -0.004), DOWN, 0.95, 0.44)
# GPS base M3B ×3 + washers
for k in range(3):
    a = math.radians(k * 120)
    place("M3B", (0.014 * math.cos(a), -0.05 + 0.014 * math.sin(a), 0.101), UP, 0.90, 0.44)
    place("W3", (0.014 * math.cos(a), -0.05 + 0.014 * math.sin(a), 0.098), UP, 0.82, 0.40)
# front vision M2 ×4 (horizontal axis +Y)
for sx in (-0.036, 0.036):
    for sz in (-0.008, 0.008):
        place("M2", (sx, 0.189, 0.004 + sz), (0, 1, 0), 0.92, 0.44)
# downward modules M2 ×4 (axis -Z)
for sx, sy in ((0.06, 0.02), (0.06, -0.02), (-0.06, 0.02), (-0.06, -0.02)):
    place("M2", (sx, sy, -0.048), DOWN, 0.92, 0.42)
# radar M2 ×4
for sx, sy in ((-0.02, 0.106), (0.02, 0.106), (-0.02, 0.130), (0.02, 0.130)):
    place("M2", (sx, sy, -0.047), DOWN, 0.90, 0.42)
# cargo M3 ×6 + washers + nyloc
for sx in (-0.10, 0, 0.10):
    for sy in (-0.085, 0.085):
        place("M3", (sx, sy, -0.056), UP, 0.88, 0.44)
        place("W3", (sx, sy, -0.0585), UP, 0.80, 0.40)
        place("NL3", (sx, sy, -0.064), DOWN, 0.96, 0.46)
# legs M4 ×8 + washers
for tag, deg in ARMS.items():
    a = math.radians(deg)
    top = Vector((0.30 * math.cos(a), 0.30 * math.sin(a), -0.012))
    ca, sa = math.cos(a), math.sin(a)
    for dx in (-0.008, 0.008):
        px = top.x + dx * ca
        py = top.y + dx * sa
        place("M4", (px, py, -0.012), UP, 0.88, 0.42)
        place("W4", (px, py, -0.015), UP, 0.80, 0.38)
# hatch M3B ×2
for x in (-0.016, 0.016):
    place("M3B", (x, -0.05, 0.0995), UP, 0.90, 0.44)
# zip-tie mounts ×8
for tag, deg in ARMS.items():
    a = math.radians(deg)
    for r in (0.25, 0.45):
        x, y = r * math.cos(a), r * math.sin(a)
        box(f"STD_FAST_ZipTieMount_{tag}_{int(r*100):02d}", (0.012, 0.012, 0.003),
            (x, y, 0.015), (0, 0, a), MAT["abs"], fe, UP, 0.60, "STD", "FAST",
            dist=0.30, bevel=0.001)

# delete prototypes (mesh data survives via instances)
for p in PROTOS.values():
    bpy.data.objects.remove(p)
print("STD fasteners placed:", sum(_counter.values()))

# ============================================================ explode overlap check
def aabb(obj, offset):
    bb = [obj.matrix_world @ Vector(c) + offset for c in obj.bound_box]
    lo = Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
    hi = Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
    return lo, hi

def overlap(a, b):
    return all(a[0][i] < b[1][i] and b[0][i] < a[1][i] for i in range(3))

sys_parts = {}
for o in PARTS:
    sys_parts.setdefault(o["system"], []).append(o)

total_collisions = 0
for rnd in range(4):
    collisions = 0
    for sysc, plist in sys_parts.items():
        data = []
        for o in plist:
            d = g2b(o["explodeDir"]) * o["explodeDist"] * (1.0 + 0.4 * o["stagger"])
            data.append((o, d, aabb(o, d)))
        n = len(data)
        for i in range(n):
            for j in range(i + 1, n):
                if overlap(data[i][2], data[j][2]):
                    collisions += 1
                    victim = data[i] if data[i][0]["stagger"] >= data[j][0]["stagger"] else data[j]
                    victim[0]["explodeDist"] = victim[0]["explodeDist"] * 1.18 + 0.01
    total_collisions = collisions
    if collisions == 0:
        break
print("explode overlap check: residual collisions =", total_collisions)

# part counts on system empties
for sysc, e in SYS_E.items():
    e["partCount"] = len(sys_parts.get(sysc, []))
print("TOTAL PARTS:", len(PARTS))
for sysc in sorted(sys_parts):
    print(" ", sysc, len(sys_parts[sysc]))
tris = sum(len(o.data.loop_triangles) if o.data.loop_triangles else 0 for o in PARTS)
for o in PARTS:
    o.data.calc_loop_triangles()
tris = sum(len(o.data.loop_triangles) for o in PARTS)
print("TOTAL TRIANGLES:", tris)

# ============================================================ renders
def add_camera_light():
    cam_d = bpy.data.cameras.new("ReviewCam")
    cam = bpy.data.objects.new("ReviewCam", cam_d)
    link_to_col(cam)
    cam_d.lens = 52
    sc.camera = cam
    sun_d = bpy.data.lights.new("KeySun", type='SUN')
    sun_d.energy = 4.0; sun_d.angle = 0.25
    sun = bpy.data.objects.new("KeySun", sun_d)
    link_to_col(sun)
    sun.rotation_euler = (0.9, 0.15, 0.6)
    w = bpy.data.worlds.new("W")
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.035, 0.036, 0.04, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 0.6
    sc.world = w
    return cam, sun

def look_at(cam, target):
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

cam, sun = add_camera_light()
sc.render.resolution_x, sc.render.resolution_y = 960, 540
sc.render.image_settings.file_format = 'PNG'

# assembly views (Eevee)
sc.render.engine = 'BLENDER_EEVEE'
for i, ang in enumerate((45, 135, 225, 315)):
    a = math.radians(ang)
    cam.location = (1.35 * math.cos(a), 1.35 * math.sin(a), 0.72)
    look_at(cam, (0, 0, -0.04))
    sc.render.filepath = os.path.join(DOCS, "previews", f"assembly_view{i+1}.png")
    bpy.ops.render.render(write_still=True)

# per-system preview (Eevee) + wireframe (Workbench)
cam.location = (0.95, -0.95, 0.62)
look_at(cam, (0, 0, -0.02))
for sysc in SYS_E:
    plist = sys_parts.get(sysc, [])
    for o in PARTS:
        o.hide_render = o not in plist
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.filepath = os.path.join(DOCS, "previews", f"system_{sysc}.png")
    bpy.ops.render.render(write_still=True)
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.use_freestyle = True
    vl = bpy.context.view_layer
    ls = vl.freestyle_settings.linesets[0]
    ls.select_silhouette = True; ls.select_border = True; ls.select_crease = True
    if not bpy.data.linestyles.get("wire_style"):
        lstyle = bpy.data.linestyles.new("wire_style")
        lstyle.color = (0.12, 0.12, 0.14); lstyle.thickness = 1.1
    ls.linestyle = bpy.data.linestyles["wire_style"]
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.94, 0.94, 0.95, 1)
    sc.world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
    sc.render.filepath = os.path.join(DOCS, "wireframes", f"system_{sysc}_wire.png")
    bpy.ops.render.render(write_still=True)
    sc.render.use_freestyle = False
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.035, 0.036, 0.04, 1)
    sc.world.node_tree.nodes["Background"].inputs[1].default_value = 0.6
for o in PARTS:
    o.hide_render = False

# full-assembly wireframe overview (Eevee + Freestyle line art)
sc.render.engine = 'BLENDER_EEVEE'
sc.render.use_freestyle = True
sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.94, 0.94, 0.95, 1)
sc.world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
sc.render.filepath = os.path.join(DOCS, "wireframes", "assembly_wire.png")
bpy.ops.render.render(write_still=True)
sc.render.use_freestyle = False
sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.035, 0.036, 0.04, 1)
sc.world.node_tree.nodes["Background"].inputs[1].default_value = 0.6

# ============================================================ save + export
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "cr30.blend"))
bpy.data.objects.remove(cam)
bpy.data.objects.remove(sun)

def export_glb(path):
    bpy.ops.export_scene.gltf(
        filepath=path, export_format='GLB', export_yup=True,
        export_apply=True, export_extras=True,
        export_cameras=False, export_lights=False,
        export_image_format='WEBP', export_animations=False,
        export_skins=False, export_morph=False,
        export_draco_mesh_compression_enable=True,
        export_draco_mesh_compression_level=6,
    )

export_glb(os.path.join(OUT, "cr30.glb"))

# LOD1: decimate meshes >400 polygons
for o in PARTS:
    if len(o.data.polygons) > 400:
        m = o.modifiers.new("Deci", 'DECIMATE')
        m.ratio = 0.5
        activate(o)
        bpy.ops.object.modifier_apply(modifier=m.name)
export_glb(os.path.join(OUT, "cr30_lod1.glb"))
tris_lod = 0
for o in PARTS:
    o.data.calc_loop_triangles()
    tris_lod += len(o.data.loop_triangles)
print("LOD1 TRIANGLES:", tris_lod)

# ============================================================ BOM CSV
agg = {}
for r in REG:
    base = r["name"].rsplit("_", 1)[0]
    k = (r["system"], r["sub"], base, r["material"], r["standard"])
    agg[k] = agg.get(k, 0) + 1
with open(os.path.join(OUT, "bom.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["system", "subassembly", "part", "quantity", "material", "standard"])
    for k in sorted(agg):
        w.writerow([*k[:3], agg[k], k[3], k[4]])
print("BOM rows:", len(agg))
print("BUILD DONE")
