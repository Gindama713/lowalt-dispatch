# Encode an image sequence into H264 MP4 via Blender's compositor.
# Run: Blender -b --python asset/blender/encode_seq.py -- <frames_dir> <out_mp4> <fps> [pattern] [width height]
import bpy, os, sys, glob

ARGV = sys.argv[sys.argv.index("--") + 1:]
DIR, OUT, FPS = ARGV[0], ARGV[1], int(ARGV[2])
PATTERN = ARGV[3] if len(ARGV) > 3 else "f_*.jpg"
RW = int(ARGV[4]) if len(ARGV) > 4 else 1280
RH = int(ARGV[5]) if len(ARGV) > 5 else 720

files = sorted(glob.glob(os.path.join(DIR, PATTERN)))
assert files, "no frames found"
print("frames:", len(files))

sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.render.resolution_x, sc.render.resolution_y = RW, RH
sc.render.resolution_percentage = 100
sc.render.fps = FPS
sc.frame_start = 1
sc.frame_end = len(files)
ifs = sc.render.image_settings
mt_prop = ifs.bl_rna.properties.get("media_type")
if mt_prop:
    print("media_type items:", [i.identifier for i in mt_prop.enum_items])
    ifs.media_type = 'VIDEO'
ifs.file_format = 'FFMPEG'
sc.render.ffmpeg.format = 'MPEG4'
sc.render.ffmpeg.codec = 'H264'
sc.render.ffmpeg.constant_rate_factor = 'MEDIUM'
sc.render.ffmpeg.ffmpeg_preset = 'GOOD'
sc.render.filepath = OUT

img = bpy.data.images.load(files[0])
img.source = 'SEQUENCE'

ng = bpy.data.node_groups.new("enc", type='CompositorNodeTree')
sc.compositing_node_group = ng
ng.interface.new_socket("Image", in_out='OUTPUT', socket_type='NodeSocketColor')
inode = ng.nodes.new("CompositorNodeImage")
inode.image = img
inode.frame_duration = len(files)
outn = ng.nodes.new("NodeGroupOutput")
ng.links.new(inode.outputs["Image"], outn.inputs["Image"])

bpy.ops.render.render(animation=True)
print("ENCODE DONE ->", OUT)
