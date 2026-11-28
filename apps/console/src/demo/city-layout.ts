/**
 * 10x City-Scale Greater Shenzhen Bay Masterplan:
 * Bao'an & Qianhai (West) ↔ Nanshan Tech Park & Houhai ↔ Dasha River ↔ Futian CBD ↔ Luohu (East)
 * Plus Longhua / Meilin northern districts, Tanglangshan–Wutongshan mountain ridge,
 * expansive Shenzhen Bay, and distant Hong Kong New Territories silhouette.
 *
 * All coordinates are artistic scene units (not real survey / WGS84 coordinates).
 */
export type DistrictId =
  | "qianhai"
  | "techpark"
  | "houhai"
  | "futian"
  | "luohu"
  | "longhua"
  | "coastal";

export type CityLot = {
  x: number;
  z: number;
  width: number;
  depth: number;
  height: number;
  style: "office" | "residential" | "warehouse";
  district: DistrictId;
  tier: "supertall" | "highrise" | "midrise" | "podium";
  detailed: boolean;
};

export type ShenzhenLandmarkSpec = {
  id:
    | "pingan"
    | "chunsun"
    | "tencent"
    | "civic"
    | "cocoon"
    | "kk100"
    | "diwang"
    | "ferris"
    | "qianhai_twins";
  name: string;
  x: number;
  z: number;
  radius: number;
  height: number;
};

/** Three emergency drone vertiports scaled across the Nanshan–Shenzhen Bay–Futian corridor. */
export const landmarks = [
  { x: -230, z: 36 },
  { x: 96, z: 58 },
  { x: 278, z: -98 },
] as const;

/** Signature Greater Shenzhen landmarks spanning ~1,400 units east to west. */
export const shenzhenLandmarks: readonly ShenzhenLandmarkSpec[] = [
  {
    id: "pingan",
    name: "平安金融中心",
    x: 185,
    z: -78,
    radius: 32,
    height: 188,
  },
  {
    id: "chunsun",
    name: "华润大厦·春笋",
    x: -132,
    z: 30,
    radius: 28,
    height: 128,
  },
  {
    id: "tencent",
    name: "腾讯滨海大厦",
    x: -278,
    z: -46,
    radius: 34,
    height: 96,
  },
  {
    id: "civic",
    name: "深圳市民中心",
    x: 185,
    z: -168,
    radius: 42,
    height: 28,
  },
  {
    id: "cocoon",
    name: "深圳湾春茧",
    x: -68,
    z: 80,
    radius: 30,
    height: 20,
  },
  {
    id: "kk100",
    name: "京基 100",
    x: 565,
    z: -84,
    radius: 30,
    height: 154,
  },
  {
    id: "diwang",
    name: "地王大厦",
    x: 642,
    z: -42,
    radius: 28,
    height: 136,
  },
  {
    id: "ferris",
    name: "湾区之光摩天轮",
    x: -680,
    z: 96,
    radius: 44,
    height: 102,
  },
  {
    id: "qianhai_twins",
    name: "前海双子塔",
    x: -540,
    z: -38,
    radius: 38,
    height: 138,
  },
] as const;

/** Southern shoreline of Shenzhen Bay (ocean lies at z > SHORELINE_Z). */
export const SHORELINE_Z = 116;

/** Dasha River channel dividing Nanshan-Houhai (west) and Futian CBD (east). */
export const RIVER_CENTER_X = 12;
export const RIVER_HALF_WIDTH = 22;

/** Major north–south arterial corridors spanning 1,840 units east–west. */
export const xStreets = [
  -850, -750, -645, -540, -430, -325, -220, -110, 68, 168, 274, 382, 492, 604,
  716, 830,
] as const;

/** Major east–west avenues: Nanping (-540), Meilin (-410), Beihuan (-275), Shennan (-42), Binhai (92). */
export const zStreets = [-540, -410, -275, -162, -42, 34, 92] as const;

export function cityNoise(seed: number) {
  const n = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return n - Math.floor(n);
}

function classifyDistrict(x: number, z: number): DistrictId {
  if (z < -290) return "longhua";
  if (z > 48) return "coastal";
  if (x < -420) return "qianhai";
  if (x < -190) return "techpark";
  if (x < RIVER_CENTER_X) return "houhai";
  if (x > 410) return "luohu";
  return "futian";
}

function isClearOfCorridors(x: number, z: number, w: number, d: number) {
  if (z + d / 2 > SHORELINE_Z - 16) return false;
  if (Math.abs(x - RIVER_CENTER_X) - w / 2 < RIVER_HALF_WIDTH + 9) {
    return false;
  }
  if (xStreets.some((sx) => Math.abs(x - sx) < w / 2 + 5.2)) return false;
  if (zStreets.some((sz) => Math.abs(z - sz) < d / 2 + 6.0)) return false;
  if (landmarks.some((p) => Math.hypot(x - p.x, z - p.z) < 28)) return false;
  if (
    shenzhenLandmarks.some(
      (lm) =>
        Math.hypot(x - lm.x, z - lm.z) < lm.radius + Math.max(w, d) * 0.45,
    )
  ) {
    return false;
  }
  return true;
}

export function makeCityLots(): CityLot[] {
  const lots: CityLot[] = [];
  const xEdges = [
    -940, -850, -750, -645, -540, -430, -325, -220, -110, -24, 48, 68, 168, 274,
    382, 492, 604, 716, 830, 940,
  ];
  const zEdges = [-650, -540, -410, -275, -162, -42, 34, 92];

  let id = 0;
  for (let xi = 0; xi < xEdges.length - 1; xi++) {
    const x0 = xEdges[xi];
    const x1 = xEdges[xi + 1];
    // Skip river channel band [-24, 48]
    if (x0 === -24 && x1 === 48) continue;

    for (let zi = 0; zi < zEdges.length - 1; zi++) {
      const z0 = zEdges[zi];
      const z1 = zEdges[zi + 1];
      const ix0 = x0 + 6.5;
      const ix1 = x1 - 6.5;
      const iz0 = z0 + 7.2;
      const iz1 = z1 - 7.2;
      const spanX = ix1 - ix0;
      const spanZ = iz1 - iz0;
      if (spanX < 14 || spanZ < 14) continue;

      // Occasional urban parks & civic plazas (Lianhuashan, Xiangmihu, Zhongshan Park)
      const midX = (ix0 + ix1) / 2;
      const midZ = (iz0 + iz1) / 2;
      if (Math.hypot(midX - 185, midZ + 225) < 55) continue; // Lianhuashan Park north of Civic Center
      if (cityNoise(++id * 3.17) < 0.07) continue;

      const cols = spanX >= 72 ? 3 : spanX >= 36 ? 2 : 1;
      const rows = spanZ >= 85 ? 3 : spanZ >= 42 ? 2 : 1;

      for (let c = 0; c < cols; c++) {
        for (let r = 0; r < rows; r++) {
          const idx = ++id;
          const cellW = spanX / cols;
          const cellZ = spanZ / rows;
          const cx =
            ix0 + (c + 0.5) * cellW + (cityNoise(idx + 17) - 0.5) * 3.0;
          const cz =
            iz0 + (r + 0.5) * cellZ + (cityNoise(idx + 31) - 0.5) * 3.0;

          const district = classifyDistrict(cx, cz);
          const futianCore = Math.hypot(cx - 185, cz + 78) < 155;
          const houhaiCore = Math.hypot(cx + 145, cz - 10) < 135;
          const qianhaiCore = Math.hypot(cx + 540, cz + 30) < 145;
          const luohuCore = Math.hypot(cx - 595, cz + 65) < 150;
          const detailed =
            Math.abs(cx) <= 365 && cz >= -220 && cz <= SHORELINE_Z;

          const maxW = Math.min(20, cellW - 4.2);
          const maxD = Math.min(18, cellZ - 4.2);
          const width = Math.max(
            9.5,
            maxW * (0.68 + cityNoise(idx + 50) * 0.32),
          );
          const depth = Math.max(
            9.0,
            maxD * (0.68 + cityNoise(idx + 80) * 0.32),
          );

          if (!isClearOfCorridors(cx, cz, width, depth)) continue;

          const style: CityLot["style"] =
            (district === "techpark" || district === "longhua") &&
            cityNoise(idx + 11) < 0.28
              ? "warehouse"
              : futianCore ||
                  houhaiCore ||
                  qianhaiCore ||
                  luohuCore ||
                  cityNoise(idx + 23) < 0.52
                ? "office"
                : "residential";

          let height: number;
          let tier: CityLot["tier"];
          if (style === "warehouse") {
            height = 9 + cityNoise(idx) * 9;
            tier = "podium";
          } else if (futianCore) {
            height = 46 + cityNoise(idx + 7) * 76;
            tier = height > 86 ? "supertall" : "highrise";
          } else if (houhaiCore || qianhaiCore || luohuCore) {
            height = 38 + cityNoise(idx + 13) * 66;
            tier = height > 76 ? "supertall" : "highrise";
          } else if (district === "longhua") {
            height = 20 + cityNoise(idx + 37) * 34;
            tier = height > 42 ? "highrise" : "midrise";
          } else if (style === "office") {
            height = 26 + cityNoise(idx + 29) * 42;
            tier = height > 50 ? "highrise" : "midrise";
          } else {
            height = 22 + cityNoise(idx + 41) * 36;
            tier = height > 42 ? "highrise" : "midrise";
          }

          lots.push({
            x: cx,
            z: cz,
            width,
            depth,
            height,
            style,
            district,
            tier,
            detailed,
          });
        }
      }
    }
  }
  return lots;
}
