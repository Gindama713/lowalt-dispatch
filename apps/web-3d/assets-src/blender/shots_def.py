# -*- coding: utf-8 -*-
"""高光镜头表 v0 的机器可读定义（docs/高光镜头表v0.md 与动态预演、穿模回放共用）。
时间单位 s；位置单位 m（机体坐标系，x 前 y 左 z 上）；焦距 mm（全画幅 36 mm 胶片宽）。"""
import math
import skel_lib as L

FPS = 24

def lerp(a, b, k): return [a[i] + (b[i] - a[i]) * k for i in range(len(a))] if isinstance(a, (list, tuple)) else a + (b - a) * k

def orbit(az_deg, r, h): a = math.radians(az_deg); return [r * math.cos(a), r * math.sin(a), h]

SHOTS = {
 "S1_reveal": {"title": "开场环绕亮相", "dur": 8.0},
 "S2_unfold": {"title": "机臂展开", "dur": 6.0},
 "S3_explode": {"title": "部件拆解/复原", "dur": 9.5},
 "S4_lightscan": {"title": "光效扫描（冰蓝眼部 + 金属黄轮廓扫光）", "dur": 6.5},
}
SUBS = {
 "S1_reveal": [(0.8, 3.2, "LOWALT · 低空应急配送"), (4.2, 7.6, "M350 RTK 级工程比例 · 810×670×430 mm · 轴距 895 mm")],
 "S2_unfold": [(0.3, 2.0, "先前臂 · 后后臂（手册顺序）"), (3.2, 5.8, "臂锁到位 · 桨叶离心展开 · 就绪")],
 "S3_explode": [(0.6, 4.0, "69 个部件 · 6 层拆解"), (5.2, 9.2, "严丝合缝复原（同路径倒放）")],
 "S4_lightscan": [(0.6, 3.0, "全向感知 · 六向双目 + 红外"), (3.4, 6.2, "冰蓝之眼 · RTK 厘米级定位")],
}

def state(shot, t, data):
    """返回该时刻的骨架状态 + 机位"""
    st = {"fold_each": None, "blade_stow": 0.0, "lock": 1.0, "explode_each": None, "spin_deg": 0.0,
          "hide_payload": False, "eyes": {}, "scan_z": None, "lights": 1.0}
    E = L.ease
    if shot == "S1_reveal":
        k = E("power3.inOut", t / 8.0)
        st["cam"] = {"loc": orbit(lerp(-150, 60, k), lerp(2.3, 1.55, k), lerp(0.12, 0.42, k)), "lens": lerp(35, 50, k), "target": [0, 0, -0.06]}
        st["spin_deg"] = 360 * 1.2 * t   # 骨架预演：低速转（实时渲染阶段改为运动模糊盘）
        st["eyes"] = {"*": 0.55 + 0.45 * math.sin(2 * math.pi * t / 2.4)}
    elif shot == "S2_unfold":
        tt = t - 0.6
        fold, lock, bl = L.unfold_state(data, max(0.0, tt))
        st.update(fold_each=fold, lock=0.0, blade_stow=bl, hide_payload=True)
        st["lock_each"] = lock
        k = E("sine.inOut", t / 6.0)
        st["cam"] = {"loc": lerp([1.05, -1.0, 0.62], [1.55, -1.35, 0.40], k), "lens": lerp(40, 32, k), "target": [0, 0, -0.08]}
        st["eyes"] = {"*": E("sine.inOut", t / 0.6)}
    elif shot == "S3_explode":
        T = data["explode_total_s"]
        if t < 0.5: ee = L.explode_progress(data, 0.0, True)
        elif t < 0.5 + T: ee = L.explode_progress(data, t - 0.5, True)
        elif t < 5.0: ee = L.explode_progress(data, T + 1, True)
        elif t < 5.0 + T: ee = L.explode_progress(data, t - 5.0, False)
        else: ee = L.explode_progress(data, T + 1, False)
        st["explode_each"] = ee
        k = E("sine.inOut", t / 9.5)
        st["cam"] = {"loc": orbit(lerp(-55, -15, k), 2.15, lerp(0.85, 0.6, k)), "lens": 35, "target": [0, 0, 0.06]}
        st["eyes"] = {"*": 0.8}
    elif shot == "S4_lightscan":
        k = E("power2.out", t / 6.5)
        st["cam"] = {"loc": lerp([2.3, -0.35, 0.10], [1.45, 0.42, 0.06], k), "lens": lerp(40, 55, k), "target": [0.10, 0, -0.02]}
        st["lights"] = 0.25
        st["scan_z"] = lerp(-0.30, 0.16, E("power3.inOut", (t - 0.4) / 2.4)) if 0.4 <= t <= 2.8 else None
        order = [["fpv_cam", "vision_front", "ir_tof_front"], ["vision_left", "vision_right"], ["vision_top", "ir_tof_top", "vision_bottom", "ir_tof_bottom"], ["vision_rear", "ir_tof_rear"]]
        eyes = {}
        for gi, grp in enumerate(order):
            t0 = 3.0 + gi * 0.35
            x = (t - t0) / 0.5
            v = 0.15 if x < 0 else (math.sin(math.pi * min(x, 1)) * 1.6 if x < 1 else 0.7)
            for pid in grp: eyes[pid] = v
        st["eyes"] = eyes
        st["gnss_glow"] = 0.2 if t < 4.6 else E("power2.out", (t - 4.6) / 0.6)
    return st

def apply(objs, data, st):
    fe = st["fold_each"]
    L.apply_state(objs, data, fold=0.0, blade_stow=st["blade_stow"], explode_each=st["explode_each"],
                  lock=1.0, spin_deg=st["spin_deg"], fold_each=fe)
    if "lock_each" in st:
        import math as _m
        pp = L.P(data)
        for c, v in st["lock_each"].items():
            L.set_rot(objs[f"arm_lock_{c}"], pp[f"arm_lock_{c}"]["pivot"]["axis"], 35 * v)
        import bpy; bpy.context.view_layer.update()
