import { describe, expect, it } from "vitest";
import {
  ANCHOR,
  SCENE,
  WGS84,
  WGS84_B,
  ecefDistance,
  ecefToLla,
  enuToLla,
  enuToScene,
  llaDistance,
  llaToEcef,
  llaToEnu,
  sceneToEnu,
  type Enu,
  type Lla,
} from "./enu.ts";

/**
 * 兴隆湖周边 3 个已知地标（水平坐标来源见各条 comment / docs/锚点决议.md）。
 * 高程统一使用锚点的暂定 h0=474 m：本测试检验的是往返闭合误差，而非正高精度。
 */
const LANDMARKS: { name: string; source: string; lla: Lla }[] = [
  {
    name: "成都地铁兴隆湖站（蜀州路与湖畔路北段交叉口北侧）",
    source: "https://zh.wikipedia.org/wiki/兴隆湖站 （30°24′15.5″N 104°4′18.5″E）",
    lla: { lat: 30.404306, lon: 104.071806, h: ANCHOR.h },
  },
  {
    name: "成都地铁科学城站（天府大道南二段与古福四街、青蓉南三街交叉口）",
    source:
      "https://zh.wikipedia.org/wiki/科学城站_(成都市) （30°23′36.2″N 104°4′13.8″E）",
    lla: { lat: 30.393389, lon: 104.0705, h: ANCHOR.h },
  },
  {
    name: "中国西部国际博览城",
    source:
      "OpenStreetMap relation/9681280，Nominatim 代表点 https://www.openstreetmap.org/relation/9681280",
    lla: { lat: 30.4240594, lon: 104.0809524, h: ANCHOR.h },
  },
];

/** 场景内若干已知 ENU 点（相对湖心，米），用于 ENU → LLA → ENU 往返。 */
const KNOWN_ENU: { name: string; enu: Enu }[] = [
  { name: "锚点本身", enu: { e: 0, n: 0, u: 0 } },
  { name: "场景西南角 (0,0)", enu: { e: -1500, n: -1500, u: 0 } },
  { name: "场景东北角 (3000,3000)", enu: { e: 1500, n: 1500, u: 80 } },
  { name: "限制区 R01 西南角", enu: { e: -500, n: -300, u: 20 } },
  { name: "限制区 R01 东北角", enu: { e: -100, n: 200, u: 20 } },
  { name: "东偏 2 km、北偏 1 km、高度 +60 m", enu: { e: 2000, n: 1000, u: 60 } },
];

describe("椭球闭式公式（与平面近似无关）", () => {
  it("赤道本初子午线地面点的 ECEF 为 (a, 0, 0)", () => {
    const p = llaToEcef({ lat: 0, lon: 0, h: 0 });
    expect(p.x).toBeCloseTo(WGS84.a, 9);
    expect(p.y).toBeCloseTo(0, 12);
    expect(p.z).toBeCloseTo(0, 12);
  });

  it("北极地面点的 ECEF 为 (0, 0, b)", () => {
    const p = llaToEcef({ lat: 90, lon: 0, h: 0 });
    expect(p.x).toBeCloseTo(0, 8);
    expect(p.y).toBeCloseTo(0, 8);
    expect(p.z).toBeCloseTo(WGS84_B, 8);
  });

  it("锚点 LLA→ECEF→LLA 闭合到亚毫米", () => {
    const back = ecefToLla(llaToEcef(ANCHOR));
    expect(llaDistance(ANCHOR, back)).toBeLessThan(1e-6);
  });
});

describe("llaToEnu / enuToLla 地标往返", () => {
  it("锚点自身的 ENU 为零", () => {
    const enu = llaToEnu(ANCHOR);
    expect(Math.hypot(enu.e, enu.n, enu.u)).toBeLessThan(1e-9);
  });

  it("3 个兴隆湖周边地标 LLA→ENU→LLA 三维误差均 < 1 m，并报告最大误差", () => {
    const rows = LANDMARKS.map((lm) => {
      const enu = llaToEnu(lm.lla);
      const back = enuToLla(enu);
      const err = llaDistance(lm.lla, back);
      return { name: lm.name, source: lm.source, enu, err };
    });

    const maxErr = Math.max(...rows.map((r) => r.err));
    // 给汇报用的可读摘要（出现在 vitest 标准输出里）
    console.log("\n===== 地标 LLA→ENU→LLA 往返误差 =====");
    for (const r of rows) {
      console.log(
        `${r.name}\n  来源: ${r.source}\n  ENU (m): e=${r.enu.e.toFixed(3)} n=${r.enu.n.toFixed(3)} u=${r.enu.u.toFixed(3)}\n  三维闭合误差: ${r.err.toExponential(3)} m`,
      );
    }
    console.log(`最大三维误差: ${maxErr.toExponential(3)} m（合格标准 < 1 m）\n`);

    for (const r of rows) {
      expect(r.err, r.name).toBeLessThan(1);
    }
    expect(maxErr).toBeLessThan(1);
    // 严格公式下应远小于 1 m；若达到厘米级说明实现有误
    expect(maxErr).toBeLessThan(1e-4);
  });
});

describe("enuToLla / llaToEnu 已知 ENU 点往返", () => {
  it("若干已知 ENU 点 ENU→LLA→ENU 三维误差均 < 1 m，并报告最大误差", () => {
    const rows = KNOWN_ENU.map((pt) => {
      const lla = enuToLla(pt.enu);
      const back = llaToEnu(lla);
      const err = Math.hypot(
        back.e - pt.enu.e,
        back.n - pt.enu.n,
        back.u - pt.enu.u,
      );
      return { name: pt.name, lla, err };
    });

    const maxErr = Math.max(...rows.map((r) => r.err));
    console.log("\n===== 已知 ENU→LLA→ENU 往返误差 =====");
    for (const r of rows) {
      console.log(
        `${r.name}\n  反算 LLA: ${r.lla.lat.toFixed(8)}°N, ${r.lla.lon.toFixed(8)}°E, h=${r.lla.h.toFixed(4)} m\n  三维闭合误差: ${r.err.toExponential(3)} m`,
      );
    }
    console.log(`最大三维误差: ${maxErr.toExponential(3)} m（合格标准 < 1 m）\n`);

    for (const r of rows) {
      expect(r.err, r.name).toBeLessThan(1);
    }
    expect(maxErr).toBeLessThan(1e-4);
  });

  it("ECEF 往返与 ENU 往返给出同一量级的几何误差", () => {
    const sample: Lla = { lat: 30.404306, lon: 104.071806, h: ANCHOR.h };
    const err = ecefDistance(llaToEcef(sample), llaToEcef(enuToLla(llaToEnu(sample))));
    expect(err).toBeLessThan(1e-4);
  });
});

describe("sceneToEnu / enuToScene（中心 1500,1500 对准湖心）", () => {
  it("场景中心对准 ENU 原点", () => {
    expect(sceneToEnu(1500, 1500)).toEqual({ e: 0, n: 0, u: 0 });
    expect(enuToScene({ e: 0, n: 0, u: 0 })).toEqual({ x: 1500, y: 1500, z: 0 });
  });

  it("场景四角与 R01 角点按 (x-1500, y-1500) 平移", () => {
    expect(sceneToEnu(0, 0)).toEqual({ e: -1500, n: -1500, u: 0 });
    expect(sceneToEnu(3000, 3000, 60)).toEqual({ e: 1500, n: 1500, u: 60 });
    expect(sceneToEnu(SCENE.r01.x0, SCENE.r01.y0)).toEqual({
      e: -500,
      n: -300,
      u: 0,
    });
    expect(sceneToEnu(SCENE.r01.x1, SCENE.r01.y1, 20)).toEqual({
      e: -100,
      n: 200,
      u: 20,
    });
  });

  it("scene → enu → scene 往返精确可逆", () => {
    const samples = [
      { x: 0, y: 0, z: 0 },
      { x: 1500, y: 1500, z: 0 },
      { x: 1000, y: 1200, z: 20 },
      { x: 1400, y: 1700, z: 20 },
      { x: 3000, y: 3000, z: 80 },
    ];
    for (const s of samples) {
      const back = enuToScene(sceneToEnu(s.x, s.y, s.z));
      expect(back.x).toBeCloseTo(s.x, 12);
      expect(back.y).toBeCloseTo(s.y, 12);
      expect(back.z).toBeCloseTo(s.z, 12);
    }
  });

  it("场景中心经纬度即锚点", () => {
    const lla = enuToLla(sceneToEnu(SCENE.center, SCENE.center));
    expect(llaDistance(lla, ANCHOR)).toBeLessThan(1e-6);
  });
});
