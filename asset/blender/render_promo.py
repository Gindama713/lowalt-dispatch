# CR-30 "暗夜战甲" promo: orbit + full-explode + collapse, 300 frames @30fps -> JPG sequence.
# Run: Blender -b asset/out/cr30.blend --python asset/blender/render_promo.py -- <out_dir> <frame_start>
import bpy, os, sys, math
from mathutils import Vector

ARGV = sys.argv[sys.argv.index("--") + 1:]
OUT = ARGV[0]
F0 = int(ARGV[1]) if len(ARGV) > 1 else 61   # leave room for title card frames
os.makedirs(OUT, exist_ok=True)

sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
sc.render.resolution_percentage = 100
sc.render.image_settings.file_format = 'JPEG'
sc.render.image_settings.quality = 92
sc.render.fps = 30

# approved dark mood
w = sc.world
w.node_tree.nodes["Background"].inputs[0].default_value = (0.012, 0.012, 0.018, 1)
w.node_tree.nodes["Background"].inputs[1].default_value = 0.5

N = 300
sc.frame_start = F0
sc.frame_end = F0 + N - 1

def g2b(v):
    return Vector((v[0], -v[2], v[1]))

def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)

# collect parts + base locations
parts = []
for o in bpy.data.objects:
    d = o.get("explodeDir")
    if d is None:
        continue
    parts.append((o, o.location.copy(), g2b(Vector(d)).normalized(),
                  float(o.get("explodeDist", 0.3)), float(o.get("stagger", 0.0))))
print("explodable parts:", len(parts))

# global explode envelope over 300 local frames
def explode_env(f):
    if f < 40: return 0.0
    if f < 115: return smooth((f - 40) / 75)
    if f < 185: return 1.0
    if f < 250: return 1.0 - smooth((f - 185) / 65)
    return 0.0

cam = bpy.data.objects.get("ReviewCam")
sc.camera = cam
TARGET = Vector((0, 0, -0.03))

def drive(scene):
    f = scene.frame_current - F0
    g = explode_env(f)
    # parts with per-part stagger
    for o, base, dvec, dist, stag in parts:
        pt = smooth((g - stag * 0.22) / 0.78)
        o.location = base + dvec * dist * (1.0 + 0.4 * stag) * pt
    # camera: full 360 orbit, dolly well out while exploded
    az = math.radians(205 + 330 * f / (N - 1))
    r = 1.55 + 2.35 * g
    h = 0.55 + 0.70 * g
    cam.location = (r * math.cos(az), r * math.sin(az), h)
    d = TARGET - cam.location
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

bpy.app.handlers.frame_change_post.clear()
bpy.app.handlers.frame_change_post.append(drive)

sc.render.filepath = os.path.join(OUT, "p_")
test_frame = int(os.environ.get("PROMO_TEST_FRAME", "0"))
if test_frame:
    sc.frame_start = sc.frame_end = F0 + test_frame
bpy.ops.render.render(animation=True)
print("PROMO RENDER DONE")
