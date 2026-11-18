"""Generate PBR textures for the CR-30 drone (deterministic, seeded).
Outputs PNGs into asset/textures/.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import os

OUT = os.path.join(os.path.dirname(__file__), "..", "textures")
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(30)


def save(arr, name):
    Image.fromarray(arr).save(os.path.join(OUT, name))
    print("wrote", name, arr.shape)


def box_blur(a, k=9):
    """Fast separable box blur (wrap)."""
    def blur1d(x, axis):
        c = np.cumsum(x, axis=axis)
        pad = [(0, 0)] * x.ndim
        pad[axis] = (1, 0)
        c = np.pad(c, pad, mode="constant")
        idx_hi = [slice(None)] * x.ndim
        idx_lo = [slice(None)] * x.ndim
        idx_hi[axis] = slice(k, None)
        idx_lo[axis] = slice(None, -k)
        return (c[tuple(idx_hi)] - c[tuple(idx_lo)]) / k
    for _ in range(2):
        a = blur1d(blur1d(a, 0), 1)
    return a


def height_to_normal(h, strength=1.0):
    gy, gx = np.gradient(h)
    nz = np.ones_like(h) / max(strength, 1e-6)
    l = np.sqrt(gx**2 + gy**2 + nz**2)
    n = np.stack([-gx / l, -gy / l, nz / l], axis=-1)
    return ((n * 0.5 + 0.5) * 255).astype(np.uint8)


# ---------- 2x2 twill carbon weave 2K ----------
S = 2048
tow = 64
u = np.arange(S)[None, :].astype(np.float64)
v = np.arange(S)[:, None].astype(np.float64)
ci = (u // tow).astype(np.int64)
cj = (v // tow).astype(np.int64)
fx = (u % tow) / tow
fy = (v % tow) / tow
horizontal = ((ci + cj) % 2 == 0)
h = np.where(horizontal, np.sin(np.pi * fy), np.sin(np.pi * fx))
gap = np.where(horizontal, np.abs(fx - 0.5), np.abs(fy - 0.5))
h -= np.where(gap > 0.46, 0.35, 0.0)
h += rng.normal(0, 0.015, h.shape)

tow_var = rng.normal(0, 5, (S // tow + 2, S // tow + 2))
shade = h * 26.0
base = 20.0 + shade + tow_var[cj, ci]
rgb = np.stack([base, base + 1.5, base + 4.0], axis=-1)
save(np.clip(rgb, 0, 255).astype(np.uint8), "carbon_2k.png")
save(height_to_normal(h, strength=1.4), "carbon_2k_normal.png")

# ---------- ABS orange-peel normal 1K ----------
S2 = 1024
noise = box_blur(rng.normal(0, 1, (S2, S2)), 9)
noise /= np.abs(noise).max()
save(height_to_normal(noise, strength=3.0), "abs_normal.png")

# ---------- PCB green solder mask + silkscreen 1K ----------
P = 1024
img = Image.new("RGB", (P, P), (11, 74, 30))  # solder-mask green
d = ImageDraw.Draw(img)
# copper-ish darker traces (they read through the mask)
for _ in range(140):
    x0, y0 = rng.integers(0, P, 2)
    length = rng.integers(60, 420)
    ang = rng.choice([0, 45, 90, 135]) * np.pi / 180
    x1 = int(x0 + length * np.cos(ang)); y1 = int(y0 + length * np.sin(ang))
    d.line([(x0, y0), (x1, y1)], fill=(16, 92, 38), width=3)
# pads / vias (gold)
for _ in range(90):
    x, y = rng.integers(20, P - 20, 2)
    r = int(rng.integers(3, 8))
    d.ellipse([x - r, y - r, x + r, y + r], fill=(176, 141, 60))
    d.ellipse([x - r // 2, y - r // 2, x + r // 2, y + r // 2], fill=(60, 48, 20))
# silkscreen white outlines + text
for _ in range(26):
    x, y = rng.integers(30, P - 120, 2)
    w, hh = rng.integers(40, 120), rng.integers(24, 60)
    d.rectangle([x, y, x + w, y + hh], outline=(225, 228, 230), width=2)
try:
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 34)
except Exception:
    font = ImageFont.load_default()
d.text((60, 60), "CR30-FC V2.1", fill=(235, 238, 240), font=font)
d.text((60, 940), "SN 2611-0030", fill=(235, 238, 240), font=font)
save(np.asarray(img), "pcb_1k.png")

# ---------- rubber foam subtle normal 512 ----------
S3 = 512
fine = box_blur(rng.normal(0, 1, (S3, S3)), 5)
fine /= np.abs(fine).max()
save(height_to_normal(fine, strength=4.0), "foam_normal.png")

# ---------- mecha panel-line normal 1K (tileable) ----------
# One tile ≈ 64mm (matches uv_cube=0.06~0.064 on shell parts).
P4 = 1024
h_panel = np.zeros((P4, P4))
# per-plate slight height jitter (2x2 main plates per tile, wrap-safe)
pj = rng.normal(0, 0.05, (2, 2))
yy, xx = np.mgrid[0:P4, 0:P4]
h_panel += pj[(yy // 512) % 2, (xx // 512) % 2]

def wrap_line(pos, axis, width=4, depth=-1.0):
    """Groove line, wrap-safe. axis=0 -> vertical line at x=pos."""
    for q in (pos - P4, pos, pos + P4):
        if axis == 0:
            lo, hi = max(0, q - width // 2), min(P4, q + width // 2 + 1)
            if hi > lo:
                h_panel[:, lo:hi] = np.minimum(h_panel[:, lo:hi], depth)
        else:
            lo, hi = max(0, q - width // 2), min(P4, q + width // 2 + 1)
            if hi > lo:
                h_panel[lo:hi, :] = np.minimum(h_panel[lo:hi, :], depth)

# main seams at 0/512 (wrap) + deterministic sub-seams inside each plate
for s in (0, 512):
    wrap_line(s, 0); wrap_line(s, 1)
sub_rng = np.random.default_rng(77)
for py in range(2):
    for px in range(2):
        if sub_rng.random() < 0.75:
            if sub_rng.random() < 0.5:
                wrap_line(px * 512 + int(sub_rng.integers(140, 372)), 0, width=3, depth=-0.8)
            else:
                wrap_line(py * 512 + int(sub_rng.integers(140, 372)), 1, width=3, depth=-0.8)
# rivet dimples near plate corners (wrap-safe)
def rivet(cx, cy, r=5, depth=-0.7):
    for qx in (cx - P4, cx, cx + P4):
        for qy in (cy - P4, cy, cy + P4):
            x0, x1 = max(0, qx - r), min(P4, qx + r + 1)
            y0, y1 = max(0, qy - r), min(P4, qy + r + 1)
            if x1 <= x0 or y1 <= y0:
                continue
            lx, ly = np.meshgrid(np.arange(x0, x1) - qx, np.arange(y0, y1) - qy)
            m = (lx**2 + ly**2) <= r * r
            patch = h_panel[y0:y1, x0:x1]
            patch[m] = np.minimum(patch[m], depth)
for gy in range(2):
    for gx in range(2):
        for dx, dy in ((26, 26), (512 - 26, 26), (26, 512 - 26), (512 - 26, 512 - 26)):
            rivet(gx * 512 + dx, gy * 512 + dy)
# soften groove walls, add micro surface noise
h_panel = box_blur(h_panel, 3)
h_panel += rng.normal(0, 0.02, h_panel.shape)
save(height_to_normal(h_panel, strength=1.8), "panel_normal_1k.png")

print("all textures done")
