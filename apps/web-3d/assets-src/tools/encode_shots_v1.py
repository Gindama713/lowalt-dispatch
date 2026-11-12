#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动态预演合成：_frames/<shot>/f_####.png + 字幕（shots_def.SUBS）+ 角标 → shots/<shot>.mp4（1920×1080, 24 fps, H.264 yuv420p）
用法：python3 assets-src/tools/encode_shots_v1.py [S1_reveal ...]"""
import os, sys, glob, subprocess, shutil, importlib.util, types
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SH = os.path.join(ROOT, "_shots", "stage1", "shots")
sys.modules["skel_lib"] = types.ModuleType("skel_lib")  # shots_def 只在 state() 里用到 skel_lib，这里只取常量
spec = importlib.util.spec_from_file_location("sd", os.path.join(ROOT, "assets-src", "blender", "shots_def.py"))
SD = importlib.util.module_from_spec(spec); spec.loader.exec_module(SD)
F = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
fsub = ImageFont.truetype(F, 46); fsm = ImageFont.truetype(F, 24)
for shot in (sys.argv[1:] or list(SD.SHOTS)):
    src = next((d for d in ("_frames_wb", "_frames") if len(glob.glob(os.path.join(SH, d, shot, "f_*.png"))) >= int(SD.SHOTS[shot]["dur"] * SD.FPS)), "_frames_wb")
    ENG = "Workbench 快速预演 + 遮罩辉光" if src == "_frames_wb" else "Cycles 4 spp"
    frames = sorted(glob.glob(os.path.join(SH, src, shot, "f_*.png")))
    if not frames: print("skip", shot); continue
    tmp = os.path.join(SH, "_tmp_" + shot); shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    for i, fp in enumerate(frames):
        t = i / SD.FPS
        im = Image.open(fp).convert("RGB")
        if im.size != (1920, 1080): im = im.resize((1920, 1080), Image.LANCZOS)
        mp = fp.replace("f_", "m_")
        if os.path.exists(mp):  # 自发光遮罩 → 核心提亮 + 两级高斯辉光（模拟 Bloom）
            mm = np.asarray(Image.open(mp).convert("RGB"), np.float32)
            mm = np.clip(mm - 26.0, 0, None) * (255.0 / 229.0)  # 扣除遮罩帧的世界底色（约 20,20,23）
            m = Image.fromarray(mm.astype(np.uint8)); a = np.asarray(im, np.float32)
            g1 = np.asarray(m.filter(ImageFilter.GaussianBlur(6)), np.float32)
            g2 = np.asarray(m.filter(ImageFilter.GaussianBlur(22)), np.float32)
            core = (mm.max(axis=2, keepdims=True) > 8)
            a = np.where(core, a * 0.35 + mm * 0.8, a) + g1 * 0.55 + g2 * 0.9
            im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(im, "RGBA")
        for a, b, txt in SD.SUBS[shot]:
            if a <= t <= b:
                fade = min(1, (t - a) / 0.25, (b - t) / 0.25); al = int(255 * fade)
                tw = d.textlength(txt, font=fsub); x = (1920 - tw) / 2
                d.rectangle([(x - 28, 928), (x + tw + 28, 1006)], fill=(0, 0, 0, int(150 * fade)))
                d.rectangle([(x - 28, 928), (x - 22, 1006)], fill=(255, 196, 0, al))
                d.text((x, 936), txt, font=fsub, fill=(240, 241, 244, al))
        d.text((40, 32), f"{shot} · {SD.SHOTS[shot]['title']}", font=fsm, fill=(255, 196, 0, 230))
        d.text((40, 64), f"t = {t:5.2f} s / {SD.SHOTS[shot]['dur']} s · 阶段 1 骨架预演（{ENG} 离线渲染，非实时画面、非终稿）", font=fsm, fill=(170, 172, 178, 220))
        im.save(os.path.join(tmp, f"f_{i:04d}.png"))
    out = os.path.join(SH, f"{shot}.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(SD.FPS), "-i", os.path.join(tmp, "f_%04d.png"),
                    "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], check=True)
    shutil.rmtree(tmp)
    print("encoded", out, len(frames), "frames", f"{len(frames)/SD.FPS:.2f}s")
