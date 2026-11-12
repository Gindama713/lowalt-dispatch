#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三视图尺寸标注：读取 _raw/view_*.png + annotations.json（Blender 投影坐标），画尺寸线并标实测/蓝本值"""
import json, os
from PIL import Image, ImageDraw, ImageFont
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "_shots", "stage1"); RAW = os.path.join(OUT, "_raw")
A = json.load(open(os.path.join(RAW, "annotations.json")))
R = json.load(open(os.path.join(OUT, "check_report_v1.json"), encoding="utf-8"))
F = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
fb = ImageFont.truetype(F, 34); fs = ImageFont.truetype(F, 24)
Y = (255, 196, 0); IB = (111, 227, 255); WH = (235, 236, 239)
meas = R["envelope_unfolded_no_props"]["measured_mm"]; err = R["envelope_unfolded_no_props"]["error_pct"]
wb = R["wheelbase"]
TITLE = {"front": "前视（沿 −x 看）", "side": "左视（沿 −y 看）", "top": "俯视（沿 −z 看，机头朝右）"}
def dim(d, p0, p1, off, label, horiz):
    (x0, y0), (x1, y1) = p0, p1
    if horiz:
        yy = max(y0, y1) + off
        d.line([(x0, y0), (x0, yy + 10)], fill=WH, width=1); d.line([(x1, y1), (x1, yy + 10)], fill=WH, width=1)
        d.line([(x0, yy), (x1, yy)], fill=Y, width=3)
        for x, s in ((x0, 1), (x1, -1)): d.polygon([(x, yy), (x + 16 * s, yy - 7), (x + 16 * s, yy + 7)], fill=Y)
        tw = d.textlength(label, font=fs); d.rectangle([((x0 + x1) / 2 - tw / 2 - 8, yy - 40), ((x0 + x1) / 2 + tw / 2 + 8, yy - 8)], fill=(0, 0, 0))
        d.text(((x0 + x1) / 2 - tw / 2, yy - 38), label, font=fs, fill=Y)
    else:
        xx = min(x0, x1) - off
        d.line([(x0, y0), (xx - 10, y0)], fill=WH, width=1); d.line([(x1, y1), (xx - 10, y1)], fill=WH, width=1)
        d.line([(xx, y0), (xx, y1)], fill=Y, width=3)
        for y, s in ((y0, -1), (y1, 1)): d.polygon([(xx, y), (xx - 7, y - 16 * s), (xx + 7, y - 16 * s)], fill=Y)
        tw = d.textlength(label, font=fs); lx = xx - tw - 16
        if lx < 12: lx = xx + 18  # 左侧放不下则放到尺寸线右侧
        d.rectangle([(lx - 8, (y0 + y1) / 2 - 18), (lx + tw + 8, (y0 + y1) / 2 + 18)], fill=(0, 0, 0))
        d.text((lx, (y0 + y1) / 2 - 16), label, font=fs, fill=Y)
idx = {"长 L": 0, "宽 W": 1, "高 H": 2}
for v, a in A.items():
    im = Image.open(os.path.join(RAW, f"view_{v}.png")).convert("RGB"); d = ImageDraw.Draw(im)
    (n1, r1), (n2, r2) = a["labels"]
    i1, i2 = idx[n1], idx[n2]
    dim(d, a["W"][0], a["W"][1], 60, f"{n1} 实测 {meas[i1]:g} mm ｜ 蓝本 {r1} ｜ 误差 {err[i1]}%", True)
    dim(d, a["H"][0], a["H"][1], 60, f"{n2} {meas[i2]:g} mm ｜ 蓝本 {r2} ｜ {err[i2]}%", False)
    if "diag" in a:
        (x0, y0), (x1, y1) = a["diag"]; d.line([(x0, y0), (x1, y1)], fill=IB, width=3)
        lab = f"对角轴距 实测 {wb['measured_fl_rr_mm']} mm ｜ 蓝本 895 ｜ 误差 {wb['error_pct']}%"
        tw = d.textlength(lab, font=fs); cx, cy = (x0 + x1) / 2 + 40, (y0 + y1) / 2 - 60
        d.rectangle([(cx - 8, cy - 4), (cx + tw + 8, cy + 32)], fill=(0, 0, 0)); d.text((cx, cy), lab, font=fs, fill=IB)
    d.text((40, 30), f"M350 RTK 级骨架 v1 · {TITLE[v]}", font=fb, fill=WH)
    d.text((40, 76), "阶段 1 比例骨架（仅对比例，不含细节）｜ 单位 mm ｜ 实测值由 Blender 世界坐标读取（展开、不含桨）", font=fs, fill=(170, 172, 178))
    leg = [("机身框架", (255, 196, 0)), ("动力", (74, 79, 85)), ("能源", (233, 236, 239)), ("感知", IB), ("载荷", (30, 30, 32)), ("航电", (46, 111, 138)), ("指示", (255, 59, 48))]
    x = 40
    for name, c in leg:
        d.rectangle([(x, 1030), (x + 22, 1052)], fill=c, outline=WH); d.text((x + 30, 1024), name, font=fs, fill=WH); x += 150
    im.save(os.path.join(OUT, f"view_{v}_dim.png"))
print("annotated", list(A))
