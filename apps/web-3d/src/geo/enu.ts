/**
 * WGS84 椭球上的经纬高 (LLA) ↔ ECEF ↔ 当地 ENU 严格转换。
 * 不使用平面近似（墨卡托 / 等距柱面 / 局部切平面线性化都不采用）。
 *
 * 公式来源：
 * - 椭球参数：NIMA TR8350.2（WGS84 长半轴 a、扁率 f）
 * - LLA → ECEF：闭式公式
 * - ECEF → LLA：Bowring (1985) 初值后再按标准关系迭代至收敛
 * - ECEF ↔ ENU：原点处东-北-天正交旋转
 *
 * 场景 v0 坐标通过 sceneToEnu / enuToScene 与 ENU 互转。
 * 锚点含义与精度见 docs/锚点决议.md。
 */

/** WGS84 参考椭球。CGCS2000 与之在工程精度上可视为一致。 */
export const WGS84 = {
  /** 长半轴，米 */
  a: 6_378_137.0,
  /** 扁率 */
  f: 1 / 298.257223563,
} as const;

/** 短半轴，米 */
export const WGS84_B = WGS84.a * (1 - WGS84.f);

/** 第一偏心率平方 e² = f(2 − f) */
export const WGS84_E2 = WGS84.f * (2 - WGS84.f);

/**
 * 工程锚点：成都天府新区兴隆湖湖心。
 * 水平坐标取 6 位小数（约 0.1 m）；原始 OSM 值见决议文档。
 */
export const ANCHOR = {
  /** 纬度，度，北纬，WGS84 / CGCS2000 */
  lat: 30.399075,
  /** 经度，度，东经 */
  lon: 104.085889,
  /**
   * 暂用湖区平均正高 474 m（topographic-map.com），现阶段当作椭球高 h0。
   * 正式椭球高待 RTK 测定后替换；本值不作为对图依据。
   */
  h: 474,
} as const;

export type Lla = {
  /** 纬度，度，北正 */
  lat: number;
  /** 经度，度，东正 */
  lon: number;
  /** 椭球高，米 */
  h: number;
};

export type Ecef = { x: number; y: number; z: number };

/** 当地东北天，单位米。约定：e 为东（场景 x 方向），n 为北（场景 y 方向）。 */
export type Enu = { e: number; n: number; u: number };

/** 场景 v0 坐标，单位米。x 向东增大，y 向北增大，z 与 ENU 的 u 一致（相对锚点椭球高）。 */
export type SceneCoord = { x: number; y: number; z: number };

/**
 * 场景 v0（fork 口径）。
 * 用户已确认：3000×3000 m 区域中心 (1500, 1500) 对准兴隆湖湖心
 * （ENU 原点 = 湖心），因此 scene (x, y) 对应 ENU (x − 1500, y − 1500)。
 * 限制区 R01 = (1000,1200)–(1400,1700)，规划净空 20 m。
 */
export const SCENE = {
  sizeMeters: 3000,
  center: 1500,
  r01: { x0: 1000, y0: 1200, x1: 1400, y1: 1700 },
  clearanceMeters: 20,
} as const;

const DEG = Math.PI / 180;
const RAD = 180 / Math.PI;

function primeVerticalRadius(latRad: number): number {
  const s = Math.sin(latRad);
  return WGS84.a / Math.sqrt(1 - WGS84_E2 * s * s);
}

/** 经纬高 → 地心地固直角坐标（米）。 */
export function llaToEcef(lla: Lla): Ecef {
  const lat = lla.lat * DEG;
  const lon = lla.lon * DEG;
  const slat = Math.sin(lat);
  const clat = Math.cos(lat);
  const slon = Math.sin(lon);
  const clon = Math.cos(lon);
  const n = primeVerticalRadius(lat);
  return {
    x: (n + lla.h) * clat * clon,
    y: (n + lla.h) * clat * slon,
    z: (n * (1 - WGS84_E2) + lla.h) * slat,
  };
}

/**
 * 地心地固直角坐标 → 经纬高。
 * Bowring (1985) 给出初值，再按
 * φ = atan2(Z, p · (1 − e² N / (N+h))) 迭代，通常 1–2 步即达 1e-15 rad。
 */
export function ecefToLla(ecef: Ecef): Lla {
  const { x, y, z } = ecef;
  const a = WGS84.a;
  const e2 = WGS84_E2;
  const p = Math.hypot(x, y);
  const lon = Math.atan2(y, x);

  if (p < 1e-12) {
    const sign = z >= 0 ? 1 : -1;
    return { lat: sign * 90, lon: lon * RAD, h: Math.abs(z) - WGS84_B };
  }

  const ePrime2 = e2 / (1 - e2);
  const theta = Math.atan2(z * a, p * WGS84_B);
  const st = Math.sin(theta);
  const ct = Math.cos(theta);
  let lat = Math.atan2(
    z + ePrime2 * WGS84_B * st * st * st,
    p - e2 * a * ct * ct * ct,
  );

  let h = 0;
  for (let i = 0; i < 10; i++) {
    const n = primeVerticalRadius(lat);
    h = p / Math.cos(lat) - n;
    const latNext = Math.atan2(z, p * (1 - (e2 * n) / (n + h)));
    if (Math.abs(latNext - lat) < 1e-16) {
      lat = latNext;
      break;
    }
    lat = latNext;
  }

  return { lat: lat * RAD, lon: lon * RAD, h };
}

function enuRotation(origin: Lla) {
  const lat = origin.lat * DEG;
  const lon = origin.lon * DEG;
  return {
    slat: Math.sin(lat),
    clat: Math.cos(lat),
    slon: Math.sin(lon),
    clon: Math.cos(lon),
  };
}

export function ecefToEnu(ecef: Ecef, origin: Lla = ANCHOR): Enu {
  const o = llaToEcef(origin);
  const dx = ecef.x - o.x;
  const dy = ecef.y - o.y;
  const dz = ecef.z - o.z;
  const { slat, clat, slon, clon } = enuRotation(origin);
  return {
    e: -slon * dx + clon * dy,
    n: -slat * clon * dx - slat * slon * dy + clat * dz,
    u: clat * clon * dx + clat * slon * dy + slat * dz,
  };
}

export function enuToEcef(enu: Enu, origin: Lla = ANCHOR): Ecef {
  const o = llaToEcef(origin);
  const { slat, clat, slon, clon } = enuRotation(origin);
  const { e, n, u } = enu;
  return {
    x: o.x - slon * e - slat * clon * n + clat * clon * u,
    y: o.y + clon * e - slat * slon * n + clat * slon * u,
    z: o.z + clat * n + slat * u,
  };
}

/** 经纬高 → 以 origin（默认兴隆湖湖心）为原点的当地 ENU，米。 */
export function llaToEnu(lla: Lla, origin: Lla = ANCHOR): Enu {
  return ecefToEnu(llaToEcef(lla), origin);
}

/** 当地 ENU（米）→ 经纬高。 */
export function enuToLla(enu: Enu, origin: Lla = ANCHOR): Lla {
  return ecefToLla(enuToEcef(enu, origin));
}

/**
 * 场景 v0 坐标 → ENU。
 * 默认中心 offset=1500：scene (1500,1500) → ENU (0,0,z)。
 */
export function sceneToEnu(
  x: number,
  y: number,
  z = 0,
  center: number = SCENE.center,
): Enu {
  return { e: x - center, n: y - center, u: z };
}

/** ENU → 场景 v0 坐标。 */
export function enuToScene(enu: Enu, center: number = SCENE.center): SceneCoord {
  return { x: enu.e + center, y: enu.n + center, z: enu.u };
}

/** 两点 ECEF 欧氏距离，米。用于往返误差评估。 */
export function ecefDistance(a: Ecef, b: Ecef): number {
  return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
}

export function llaDistance(a: Lla, b: Lla): number {
  return ecefDistance(llaToEcef(a), llaToEcef(b));
}
