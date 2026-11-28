# Hero confirmation render for the finalized "暗夜战甲" skin.
# Run: Blender -b asset/out/cr30.blend --python asset/blender/render_hero.py -- <out_png>
import bpy, os, sys
from mathutils import Vector

ARGV = sys.argv[sys.argv.index("--") + 1:]
OUT = ARGV[0]

sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.render.resolution_x, sc.render.resolution_y = 1280, 720
sc.render.image_settings.file_format = 'PNG'
sc.render.resolution_percentage = 100

w = sc.world
w.node_tree.nodes["Background"].inputs[0].default_value = (0.012, 0.012, 0.018, 1)
w.node_tree.nodes["Background"].inputs[1].default_value = 0.5

# demo-C lighting as approved: KeySun from the .blend + dark world, no extra lights

cam = bpy.data.objects.get("ReviewCam")
sc.camera = cam
cam.location = (1.05, -1.25, 0.62)
d = Vector((0, 0, -0.02)) - cam.location
cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("HERO DONE")
