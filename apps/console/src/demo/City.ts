import * as THREE from "three";
import {
  cityNoise,
  landmarks,
  makeCityLots,
  RIVER_CENTER_X,
  RIVER_HALF_WIDTH,
  shenzhenLandmarks,
  SHORELINE_Z,
  xStreets,
  zStreets,
  type CityLot,
} from "./city-layout";

type BoxPart = [number, number, number, number, number, number, string];
type Surface = "stone" | "glass" | "ground" | "light" | "trim" | "tower";
type PartLists = Record<Surface, BoxPart[]>;

/**
 * 10x City-Scale Greater Shenzhen Bay 3D Metropolis:
 * Bao'an & Qianhai ↔ Nanshan Tech Park & Houhai ↔ Dasha River ↔ Futian CBD ↔ Luohu
 * + Longhua northern urban belt + Tanglangshan/Wutongshan range + distant Hong Kong hills.
 *
 * Purely decorative visual environment; never feeds real navigation, clearance checks,
 * real-world coordinate transforms, or flight dispatch.
 */
export function createCity() {
  const root = new THREE.Group();
  root.name = "AERIS Greater Shenzhen 10x Metropolis";
  const parts: PartLists = {
    stone: [],
    glass: [],
    ground: [],
    light: [],
    trim: [],
    tower: [],
  };

  function box(
    surface: Surface,
    x: number,
    y: number,
    z: number,
    width: number,
    height: number,
    depth: number,
    color: string,
  ) {
    parts[surface].push([x, y, z, width, height, depth, color]);
  }

  // ---------------------------------------------------------------------------
  // 1. Seamless Continental Terrain (5,600 x 3,200 horizon — zero diorama edge)
  // ---------------------------------------------------------------------------
  // Deep seabed & continental base extending seamlessly into atmospheric fog
  box("ground", 0, -6.5, 160, 5600, 9, 3400, "#09141d");
  // West Greater Shenzhen mainland (Bao'an / Qianhai / Nanshan / Houhai)
  box("ground", -1155, -0.7, -380, 2286, 1.4, 992, "#1f2e36");
  // East Greater Shenzhen mainland (Futian / Luohu / Yantian / Longhua)
  box("ground", 1185, -0.7, -380, 2302, 1.4, 992, "#223139");
  // Dasha River concrete riverbed
  box("ground", RIVER_CENTER_X, -0.5, -280, 48, 0.4, 800, "#103a49");

  // Shenzhen Bay Coastal Park & Talent Park Promenade spanning 2,200 units east–west
  for (const [cx, span] of [
    [-555, 1086],
    [585, 1102],
  ] as const) {
    box("stone", cx, 0.16, SHORELINE_Z - 1.2, span, 1.3, 2.8, "#5d747b");
    box("ground", cx, 0.2, SHORELINE_Z - 5.0, span, 0.36, 4.8, "#586b6c");
    box("ground", cx, 0.1, SHORELINE_Z - 15.5, span, 0.28, 16.5, "#2b4f45");
    // Glowing cyan coastal waterfront ribbon
    box("light", cx, 0.72, SHORELINE_Z - 0.5, span, 0.18, 0.3, "#68dde6");
  }

  // Coastal promenade streetlamps (dense in core bayfront, sparser toward far ends)
  for (let x = -920; x <= 940; x += 28) {
    if (Math.abs(x - RIVER_CENTER_X) < RIVER_HALF_WIDTH + 8) continue;
    box("stone", x, 2.4, SHORELINE_Z - 3.6, 0.3, 4.4, 0.3, "#73888e");
    box("light", x, 4.7, SHORELINE_Z - 3.6, 0.65, 0.26, 0.65, "#ecc688");
  }

  // Dasha River ecological banks
  for (const side of [-1, 1]) {
    const rx = RIVER_CENTER_X + side * (RIVER_HALF_WIDTH + 1.8);
    box("stone", rx, 0.12, -280, 2.8, 1.0, 790, "#5e747a");
    box("ground", rx + side * 4.8, 0.14, -280, 6.8, 0.28, 790, "#2f5248");
    for (let z = -640; z <= 96; z += 36) {
      box("stone", rx + side * 2.0, 2.2, z, 0.28, 3.8, 0.28, "#72878c");
      box("light", rx + side * 2.0, 4.2, z, 0.55, 0.22, 0.55, "#92e4eb");
    }
  }

  // Lianhuashan Park green hill plaza north of Civic Center
  box("ground", 185, 0.25, -225, 118, 0.45, 96, "#2c5447");

  // ---------------------------------------------------------------------------
  // 2. Metropolitan Expressway & Avenue Grid (Shennan, Binhai, Beihuan, Nanping)
  // ---------------------------------------------------------------------------
  for (const z of zStreets) {
    const isExpressway = z === -42 || z === 92 || z === -275;
    const roadW = isExpressway ? 12.8 : 9.0;
    for (const [cx, span] of [
      [-545, 1066],
      [575, 1082],
    ] as const) {
      box("ground", cx, 0.08, z, span, 0.16, roadW, "#152028");
      box("ground", cx, 0.18, z + roadW / 2 + 0.6, span, 0.2, 1.2, "#4a5c62");
      box("ground", cx, 0.18, z - roadW / 2 - 0.6, span, 0.2, 1.2, "#4a5c62");
      if (isExpressway) {
        box("ground", cx, 0.24, z, span, 0.24, 1.8, "#31574b");
      }
    }
    // Lane markings & twilight traffic glow along Shennan / Binhai / Beihuan
    const step = isExpressway ? 15 : 22;
    for (let x = -940; x <= 960; x += step) {
      if (Math.abs(x - RIVER_CENTER_X) < RIVER_HALF_WIDTH + 6) continue;
      if (xStreets.some((sx) => Math.abs(sx - x) < 7)) continue;
      box(
        "ground",
        x,
        0.18,
        z + (isExpressway ? 3.2 : 0),
        3.2,
        0.04,
        0.22,
        "#899da5",
      );
      if (isExpressway) {
        box("ground", x, 0.18, z - 3.2, 3.2, 0.04, 0.22, "#899da5");
        const traffic = cityNoise(x * 13.7 + z * 7.3);
        if (traffic < 0.26) {
          box("light", x, 0.42, z + 3.6, 2.2, 0.3, 0.85, "#ffe4ad");
        } else if (traffic > 0.76) {
          box("light", x, 0.42, z - 3.6, 2.2, 0.3, 0.85, "#ff7878");
        }
      }
    }
    // Cross-river bridges spanning Dasha River
    box("stone", RIVER_CENTER_X, 1.1, z, 68, 1.7, roadW + 1.6, "#586e76");
    box("ground", RIVER_CENTER_X, 2.02, z, 66, 0.16, roadW - 1.0, "#1a2832");
    for (const side of [-1, 1]) {
      box(
        "light",
        RIVER_CENTER_X,
        2.6,
        z + side * (roadW / 2 + 0.3),
        62,
        0.22,
        0.26,
        isExpressway ? "#72e5ee" : "#e5c48d",
      );
    }
  }

  for (const x of xStreets) {
    box("ground", x, 0.06, -280, 9.0, 0.14, 770, "#162129");
    for (const side of [-1, 1]) {
      box("ground", x + side * 5.0, 0.16, -280, 1.0, 0.2, 770, "#4b5c62");
    }
    for (let z = -640; z <= 84; z += 22) {
      if (zStreets.some((sz) => Math.abs(sz - z) < 8)) continue;
      box("ground", x, 0.15, z, 0.2, 0.04, 3.2, "#899da5");
    }
  }

  // ---------------------------------------------------------------------------
  // 3. Nine Signature Greater Shenzhen Landmarks
  // ---------------------------------------------------------------------------
  const landmarkGroup = new THREE.Group();
  landmarkGroup.name = "Greater Shenzhen Signature Landmarks";
  root.add(landmarkGroup);

  const glassMetalMat = new THREE.MeshStandardMaterial({
    color: 0x3b6c84,
    roughness: 0.18,
    metalness: 0.68,
  });
  const silverSteelMat = new THREE.MeshStandardMaterial({
    color: 0xc2d4dc,
    roughness: 0.24,
    metalness: 0.78,
  });
  const chunsunGlassMat = new THREE.MeshStandardMaterial({
    color: 0x2c5e75,
    roughness: 0.16,
    metalness: 0.72,
  });
  const warmGlowMat = new THREE.MeshBasicMaterial({
    color: 0xffe2a8,
    toneMapped: false,
  });
  const cyanGlowMat = new THREE.MeshBasicMaterial({
    color: 0x73ecf0,
    toneMapped: false,
  });
  const redBeaconMat = new THREE.MeshBasicMaterial({
    color: 0xff5a66,
    toneMapped: false,
  });

  const lmById = Object.fromEntries(
    shenzhenLandmarks.map((lm) => [lm.id, lm]),
  ) as Record<
    (typeof shenzhenLandmarks)[number]["id"],
    (typeof shenzhenLandmarks)[number]
  >;

  // 3A. Ping An Finance Centre (平安金融中心, x=185, z=-78, h=188)
  {
    const lm = lmById.pingan;
    const g = new THREE.Group();
    g.position.set(lm.x, 0, lm.z);

    box("ground", lm.x, 0.18, lm.z, 48, 0.36, 48, "#4b5e65");
    box("stone", lm.x, 7.0, lm.z, 35, 14, 35, "#364f5c");
    box("glass", lm.x, 7.0, lm.z, 35.8, 10.5, 35.8, "#284d62");

    const tiers = [
      { y0: 14, h: 30, r: 14.2 },
      { y0: 44, h: 28, r: 13.1 },
      { y0: 72, h: 26, r: 11.9 },
      { y0: 98, h: 24, r: 10.7 },
      { y0: 122, h: 20, r: 9.4 },
      { y0: 142, h: 18, r: 8.0 },
    ];
    for (const tier of tiers) {
      const seg = new THREE.Mesh(
        new THREE.CylinderGeometry(tier.r * 0.94, tier.r, tier.h, 8),
        glassMetalMat,
      );
      seg.position.y = tier.y0 + tier.h / 2;
      seg.rotation.y = Math.PI / 8;
      seg.castShadow = true;
      seg.receiveShadow = true;
      g.add(seg);

      const band = new THREE.Mesh(
        new THREE.CylinderGeometry(tier.r * 0.955, tier.r * 0.955, 0.85, 8),
        cyanGlowMat,
      );
      band.position.y = tier.y0 + tier.h - 0.35;
      band.rotation.y = Math.PI / 8;
      g.add(band);
    }

    for (let i = 0; i < 8; i++) {
      const a = (i / 8) * Math.PI * 2 + Math.PI / 8;
      const p0 = new THREE.Vector3(Math.cos(a) * 14.3, 14, Math.sin(a) * 14.3);
      const p1 = new THREE.Vector3(Math.cos(a) * 7.2, 160, Math.sin(a) * 7.2);
      const len = p0.distanceTo(p1);
      const col = new THREE.Mesh(
        new THREE.BoxGeometry(1.15, len, 1.15),
        silverSteelMat,
      );
      col.position.copy(p0).lerp(p1, 0.5);
      col.quaternion.setFromUnitVectors(
        new THREE.Vector3(0, 1, 0),
        p1.clone().sub(p0).normalize(),
      );
      col.castShadow = true;
      g.add(col);
    }

    const crown = new THREE.Mesh(
      new THREE.ConeGeometry(7.7, 28, 8),
      silverSteelMat,
    );
    crown.position.y = 160 + 14;
    crown.rotation.y = Math.PI / 8;
    crown.castShadow = true;
    g.add(crown);

    const spire = new THREE.Mesh(
      new THREE.CylinderGeometry(0.22, 0.65, 13, 8),
      silverSteelMat,
    );
    spire.position.y = 188 + 5;
    g.add(spire);

    const beacon = new THREE.Mesh(
      new THREE.SphereGeometry(0.85, 10, 10),
      redBeaconMat,
    );
    beacon.position.y = 200;
    g.add(beacon);

    landmarkGroup.add(g);
  }

  // 3B. China Resources Tower "Spring Bamboo" (华润大厦·春笋, x=-132, z=30, h=128)
  {
    const lm = lmById.chunsun;
    const g = new THREE.Group();
    g.position.set(lm.x, 0, lm.z);

    box("ground", lm.x, 0.18, lm.z, 40, 0.36, 40, "#4b5f65");
    const profile: THREE.Vector2[] = [];
    const totalH = lm.height;
    for (let i = 0; i <= 24; i++) {
      const t = i / 24;
      const y = t * totalH;
      const r =
        t < 0.22
          ? 11.4 + Math.sin((t / 0.22) * (Math.PI / 2)) * 1.6
          : Math.max(0.55, 13.0 * Math.pow(1 - (t - 0.22) / 0.78, 0.62));
      profile.push(new THREE.Vector2(r, y));
    }
    const shell = new THREE.Mesh(
      new THREE.LatheGeometry(profile, 36),
      chunsunGlassMat,
    );
    shell.castShadow = true;
    shell.receiveShadow = true;
    g.add(shell);

    const ribCurvePoints = profile.map(
      (v) => new THREE.Vector3(v.x + 0.22, v.y, 0),
    );
    const ribCurve = new THREE.CatmullRomCurve3(ribCurvePoints);
    const ribGeo = new THREE.TubeGeometry(ribCurve, 28, 0.2, 5, false);
    for (let i = 0; i < 20; i++) {
      const rib = new THREE.Mesh(ribGeo, silverSteelMat);
      rib.rotation.y = (i / 20) * Math.PI * 2;
      g.add(rib);
    }

    for (const frac of [0.68, 0.8, 0.9]) {
      const idx = Math.min(profile.length - 1, Math.round(frac * 24));
      const pt = profile[idx];
      const halo = new THREE.Mesh(
        new THREE.TorusGeometry(pt.x + 0.2, 0.22, 6, 36),
        cyanGlowMat,
      );
      halo.rotation.x = Math.PI / 2;
      halo.position.y = pt.y;
      g.add(halo);
    }

    const tip = new THREE.Mesh(
      new THREE.SphereGeometry(0.7, 10, 10),
      warmGlowMat,
    );
    tip.position.y = totalH + 0.8;
    g.add(tip);

    landmarkGroup.add(g);
  }

  // 3C. Tencent Seafront Towers (腾讯滨海大厦, x=-278, z=-46, h=96)
  {
    const lm = lmById.tencent;
    const tx = lm.x;
    const tz = lm.z;
    box("ground", tx, 0.18, tz, 52, 0.36, 46, "#4b5e64");
    box("tower", tx - 12, 48, tz - 6, 16, 96, 16, "#3c677b");
    box("tower", tx + 12, 39, tz + 7, 15, 78, 15, "#457084");
    for (let y = 10; y < 94; y += 7.5) {
      box("trim", tx - 12, y, tz - 6, 16.5, 0.55, 16.5, "#8fb0bc");
      if (y < 76) {
        box("trim", tx + 12, y, tz + 7, 15.5, 0.55, 15.5, "#8fb0bc");
      }
    }
    for (const [by, bh, glow] of [
      [18, 5.0, "#75e8ef"],
      [42, 5.6, "#ffe09e"],
      [64, 5.0, "#75e8ef"],
    ] as const) {
      const bridge = new THREE.Mesh(
        new THREE.BoxGeometry(27, bh, 7.6),
        glassMetalMat,
      );
      bridge.position.set(tx, by, tz + 0.5);
      bridge.rotation.y = -0.46;
      bridge.castShadow = true;
      landmarkGroup.add(bridge);

      const trim = new THREE.Mesh(
        new THREE.BoxGeometry(27.5, 0.55, 8.0),
        glow === "#75e8ef" ? cyanGlowMat : warmGlowMat,
      );
      trim.position.set(tx, by + bh / 2 + 0.2, tz + 0.5);
      trim.rotation.y = -0.46;
      landmarkGroup.add(trim);
    }
    box("light", tx - 12, 96.8, tz - 6, 1.1, 1.1, 1.1, "#73ecf0");
    box("light", tx + 12, 78.8, tz + 7, 1.1, 1.1, 1.1, "#73ecf0");
  }

  // 3D. Shenzhen Civic Center "Roc Spreading Wings" (深圳市民中心, x=185, z=-168)
  {
    const lm = lmById.civic;
    const g = new THREE.Group();
    g.position.set(lm.x, 0, lm.z);

    box("ground", lm.x, 0.16, lm.z + 24, 82, 0.32, 62, "#3a5c53");
    box("ground", lm.x, 0.26, lm.z, 74, 0.36, 30, "#5c6f73");

    const wingShape = new THREE.Shape();
    wingShape.moveTo(-40, 16);
    wingShape.quadraticCurveTo(-18, 21, 0, 14.5);
    wingShape.quadraticCurveTo(18, 21, 40, 16);
    wingShape.lineTo(40, 20);
    wingShape.quadraticCurveTo(18, 26.5, 0, 18.8);
    wingShape.quadraticCurveTo(-18, 26.5, -40, 20);
    wingShape.closePath();

    const wingRoof = new THREE.Mesh(
      new THREE.ExtrudeGeometry(wingShape, { depth: 22, bevelEnabled: false }),
      new THREE.MeshStandardMaterial({
        color: 0xd9a85b,
        roughness: 0.28,
        metalness: 0.54,
      }),
    );
    wingRoof.position.set(0, 0, -11);
    wingRoof.castShadow = true;
    wingRoof.receiveShadow = true;
    g.add(wingRoof);

    box("glass", lm.x - 20, 8.5, lm.z, 22, 15, 16, "#2b5266");
    box("glass", lm.x + 20, 8.5, lm.z, 22, 15, 16, "#2b5266");
    const centralHall = new THREE.Mesh(
      new THREE.CylinderGeometry(7.0, 7.0, 15, 24),
      new THREE.MeshStandardMaterial({
        color: 0xb04e4a,
        roughness: 0.42,
        metalness: 0.25,
      }),
    );
    centralHall.position.set(0, 7.5, 0);
    centralHall.castShadow = true;
    g.add(centralHall);

    box("light", lm.x, 20.2, lm.z + 11.4, 78, 0.42, 0.42, "#ffd98c");
    landmarkGroup.add(g);
  }

  // 3E. Shenzhen Bay Sports Center "Spring Cocoon" (深圳湾春茧, x=-68, z=80)
  {
    const lm = lmById.cocoon;
    const g = new THREE.Group();
    g.position.set(lm.x, 0, lm.z);

    box("ground", lm.x, 0.18, lm.z, 56, 0.34, 36, "#445c5d");
    const shell = new THREE.Mesh(
      new THREE.SphereGeometry(1, 32, 16, 0, Math.PI * 2, 0, Math.PI * 0.54),
      new THREE.MeshStandardMaterial({
        color: 0xc2d4db,
        roughness: 0.34,
        metalness: 0.52,
      }),
    );
    shell.scale.set(25, 13.5, 14.2);
    shell.position.y = 0.25;
    shell.castShadow = true;
    shell.receiveShadow = true;
    g.add(shell);

    const stadiumHalo = new THREE.Mesh(
      new THREE.TorusGeometry(1, 0.035, 6, 48),
      warmGlowMat,
    );
    stadiumHalo.rotation.x = Math.PI / 2;
    stadiumHalo.scale.set(24.5, 13.8, 1);
    stadiumHalo.position.y = 2.0;
    g.add(stadiumHalo);
    landmarkGroup.add(g);
  }

  // 3F. KK100 (京基 100, Luohu CBD, x=565, z=-84, h=154)
  {
    const lm = lmById.kk100;
    const g = new THREE.Group();
    g.position.set(lm.x, 0, lm.z);
    box("ground", lm.x, 0.18, lm.z, 40, 0.36, 40, "#4b5e65");
    // Sculpted arched-top rectangular skyscraper silhouette
    const kkShape = new THREE.Shape();
    kkShape.moveTo(-11, 0);
    kkShape.lineTo(11, 0);
    kkShape.lineTo(10, 126);
    kkShape.quadraticCurveTo(9, 152, 0, 154);
    kkShape.quadraticCurveTo(-9, 152, -10, 126);
    kkShape.closePath();
    const kkMesh = new THREE.Mesh(
      new THREE.ExtrudeGeometry(kkShape, { depth: 18, bevelEnabled: false }),
      glassMetalMat,
    );
    kkMesh.position.z = -9;
    kkMesh.castShadow = true;
    g.add(kkMesh);
    for (const y of [45, 88, 128]) {
      const band = new THREE.Mesh(
        new THREE.BoxGeometry(20.6, 0.85, 18.6),
        cyanGlowMat,
      );
      band.position.y = y;
      g.add(band);
    }
    const kkBeacon = new THREE.Mesh(
      new THREE.SphereGeometry(0.8, 8, 8),
      redBeaconMat,
    );
    kkBeacon.position.y = 155;
    g.add(kkBeacon);
    landmarkGroup.add(g);
  }

  // 3G. Shun Hing Square / Diwang Tower (地王大厦, Luohu, x=642, z=-42, h=136)
  {
    const lm = lmById.diwang;
    const g = new THREE.Group();
    g.position.set(lm.x, 0, lm.z);
    box("tower", lm.x, 58, lm.z, 22, 116, 14, "#3b6b7d");
    box("light", lm.x, 116.5, lm.z, 22.4, 0.7, 14.4, "#ffe2a8");
    // Iconic twin spires
    for (const dx of [-6.5, 6.5]) {
      const spire = new THREE.Mesh(
        new THREE.CylinderGeometry(0.25, 0.85, 22, 8),
        silverSteelMat,
      );
      spire.position.set(dx, 127, 0);
      g.add(spire);
      const b = new THREE.Mesh(
        new THREE.SphereGeometry(0.65, 8, 8),
        redBeaconMat,
      );
      b.position.set(dx, 139, 0);
      g.add(b);
    }
    landmarkGroup.add(g);
  }

  // 3H. Bay Glory Ferris Wheel (湾区之光摩天轮, Bao'an coastal west, x=-680, z=96)
  {
    const lm = lmById.ferris;
    const g = new THREE.Group();
    g.position.set(lm.x, 0, lm.z);
    const radius = 44;
    const centerY = 54;
    const rim = new THREE.Mesh(
      new THREE.TorusGeometry(radius, 1.35, 10, 64),
      silverSteelMat,
    );
    rim.position.y = centerY;
    g.add(rim);
    const glowRim = new THREE.Mesh(
      new THREE.TorusGeometry(radius - 1.6, 0.45, 6, 64),
      cyanGlowMat,
    );
    glowRim.position.y = centerY;
    g.add(glowRim);
    // Support A-frame legs
    for (const dx of [-24, 24]) {
      for (const dz of [-12, 12]) {
        const p0 = new THREE.Vector3(dx, 0, dz);
        const p1 = new THREE.Vector3(0, centerY, dz * 0.2);
        const leg = new THREE.Mesh(
          new THREE.CylinderGeometry(0.85, 1.4, p0.distanceTo(p1), 8),
          silverSteelMat,
        );
        leg.position.copy(p0).lerp(p1, 0.5);
        leg.quaternion.setFromUnitVectors(
          new THREE.Vector3(0, 1, 0),
          p1.clone().sub(p0).normalize(),
        );
        g.add(leg);
      }
    }
    // 16 radial spokes & glowing passenger capsules
    const spokePts: THREE.Vector3[] = [];
    for (let i = 0; i < 16; i++) {
      const a = (i / 16) * Math.PI * 2;
      const sx = Math.cos(a) * radius;
      const sy = centerY + Math.sin(a) * radius;
      spokePts.push(
        new THREE.Vector3(0, centerY, 0),
        new THREE.Vector3(sx, sy, 0),
      );
      const pod = new THREE.Mesh(
        new THREE.SphereGeometry(1.4, 8, 8),
        warmGlowMat,
      );
      pod.position.set(sx, sy, 0);
      g.add(pod);
    }
    g.add(
      new THREE.LineSegments(
        new THREE.BufferGeometry().setFromPoints(spokePts),
        new THREE.LineBasicMaterial({ color: 0xb9d8e2 }),
      ),
    );
    g.rotation.y = 0.25;
    landmarkGroup.add(g);
  }

  // 3I. Qianhai Twin Financial Towers (前海双子塔, x=-540, z=-38, h=138)
  {
    const lm = lmById.qianhai_twins;
    box("ground", lm.x, 0.18, lm.z, 56, 0.36, 44, "#4b5e65");
    box("tower", lm.x - 14, 69, lm.z, 18, 138, 18, "#346278");
    box("tower", lm.x + 14, 62, lm.z + 4, 17, 124, 17, "#3e6f86");
    box("light", lm.x - 14, 138.6, lm.z, 18.4, 0.8, 18.4, "#73ecf0");
    box("light", lm.x + 14, 124.6, lm.z + 4, 17.4, 0.8, 17.4, "#ffe2a8");
    box("stone", lm.x - 14, 146, lm.z, 0.5, 14, 0.5, "#c2d4dc");
    box("light", lm.x - 14, 153.5, lm.z, 0.9, 0.9, 0.9, "#ff5a66");
  }

  // 3J. Grand Shenzhen Bay Cable-Stayed Bridge (深圳湾跨海大桥)
  {
    const bridge = new THREE.Group();
    const start = new THREE.Vector3(-192, 5.5, SHORELINE_Z - 8);
    const end = new THREE.Vector3(-118, 7.5, SHORELINE_Z + 520);
    const dir = end.clone().sub(start);
    const length = dir.length();
    const mid = start.clone().lerp(end, 0.5);
    const yaw = Math.atan2(dir.x, dir.z);

    const deck = new THREE.Mesh(
      new THREE.BoxGeometry(14.0, 1.8, length),
      new THREE.MeshStandardMaterial({
        color: 0x5c717a,
        roughness: 0.58,
        metalness: 0.24,
      }),
    );
    deck.position.copy(mid);
    deck.rotation.y = yaw;
    deck.castShadow = true;
    deck.receiveShadow = true;
    bridge.add(deck);

    for (const side of [-1, 1]) {
      const rail = new THREE.Mesh(
        new THREE.BoxGeometry(0.38, 0.38, length),
        warmGlowMat,
      );
      rail.position
        .copy(mid)
        .add(
          new THREE.Vector3(
            Math.cos(yaw) * side * 6.7,
            1.2,
            -Math.sin(yaw) * side * 6.7,
          ),
        );
      rail.rotation.y = yaw;
      bridge.add(rail);
    }

    for (let k = 1; k <= 12; k++) {
      const pt = start.clone().lerp(end, k / 13);
      const pier = new THREE.Mesh(
        new THREE.BoxGeometry(4.2, 8.2, 2.8),
        silverSteelMat,
      );
      pier.position.set(pt.x, 2.4, pt.z);
      pier.rotation.y = yaw;
      bridge.add(pier);
    }

    const pylonBase = start.clone().lerp(end, 0.34);
    const pylonTop = pylonBase.clone().add(new THREE.Vector3(-6, 76, -8));
    for (const side of [-1, 1]) {
      const legStart = pylonBase
        .clone()
        .add(
          new THREE.Vector3(
            Math.cos(yaw) * side * 8.6,
            -2,
            -Math.sin(yaw) * side * 8.6,
          ),
        );
      const legLen = legStart.distanceTo(pylonTop);
      const leg = new THREE.Mesh(
        new THREE.BoxGeometry(2.2, legLen, 2.2),
        silverSteelMat,
      );
      leg.position.copy(legStart).lerp(pylonTop, 0.5);
      leg.quaternion.setFromUnitVectors(
        new THREE.Vector3(0, 1, 0),
        pylonTop.clone().sub(legStart).normalize(),
      );
      leg.castShadow = true;
      bridge.add(leg);
    }

    const pylonBeacon = new THREE.Mesh(
      new THREE.SphereGeometry(0.85, 8, 8),
      redBeaconMat,
    );
    pylonBeacon.position.copy(pylonTop).add(new THREE.Vector3(0, 1.5, 0));
    bridge.add(pylonBeacon);

    const cableMat = new THREE.LineBasicMaterial({
      color: 0xa6d2df,
      transparent: true,
      opacity: 0.72,
    });
    const cablePts: THREE.Vector3[] = [];
    for (let i = 0; i < 14; i++) {
      const frac = 0.14 + i * 0.032;
      if (Math.abs(frac - 0.34) < 0.02) continue;
      const anchor = start.clone().lerp(end, frac);
      for (const side of [-1, 1]) {
        const edge = anchor
          .clone()
          .add(
            new THREE.Vector3(
              Math.cos(yaw) * side * 6.6,
              0.9,
              -Math.sin(yaw) * side * 6.6,
            ),
          );
        const topAttach = pylonBase
          .clone()
          .lerp(pylonTop, 0.56 + (1 - Math.abs(frac - 0.34) * 2.1) * 0.4);
        cablePts.push(edge, topAttach);
      }
    }
    bridge.add(
      new THREE.LineSegments(
        new THREE.BufferGeometry().setFromPoints(cablePts),
        cableMat,
      ),
    );
    landmarkGroup.add(bridge);
  }

  // 3K. Northern Mountain Chain (Yangtaishan / Tanglangshan / Wutongshan) & Far Hong Kong Ridge
  {
    const foothillMat = new THREE.MeshStandardMaterial({
      color: 0x1a3843,
      roughness: 0.94,
      metalness: 0.04,
    });
    const ridgeMat = new THREE.MeshStandardMaterial({
      color: 0x132b38,
      roughness: 0.96,
      metalness: 0.02,
    });
    const farRidgeMat = new THREE.MeshStandardMaterial({
      color: 0x0f2230,
      roughness: 0.98,
      metalness: 0.01,
    });
    const ridgeGeo = new THREE.SphereGeometry(1, 22, 14);
    const ridges: [number, number, number, number, number, number][] = [
      // Foreground smooth coastal foothills (Yangtaishan / Meilin / Yinhu / Wutong foothills)
      [-1480, -860, 440, 86, 260, 0],
      [-1040, -890, 470, 108, 280, 0],
      [-620, -870, 420, 96, 250, 0],
      [-210, -885, 430, 104, 265, 0],
      [210, -875, 460, 114, 270, 0],
      [660, -890, 490, 128, 290, 0],
      [1120, -870, 520, 148, 310, 0],
      [1560, -840, 460, 118, 270, 0],
      // Secondary higher misty northern ridgeline (Tanglangshan / Wutongshan main spine)
      [-1260, -1120, 560, 138, 340, 1],
      [-760, -1150, 580, 152, 360, 1],
      [-240, -1160, 540, 146, 340, 1],
      [320, -1150, 600, 168, 360, 1],
      [880, -1160, 640, 198, 390, 1],
      [1420, -1120, 560, 165, 350, 1],
      // Distant Hong Kong New Territories hills across Shenzhen Bay
      [-920, 1260, 540, 96, 280, 2],
      [-320, 1300, 580, 114, 300, 2],
      [340, 1280, 560, 104, 290, 2],
      [980, 1240, 520, 92, 270, 2],
    ];
    for (const [mx, mz, rx, h, rz, tier] of ridges) {
      const mat =
        tier === 0 ? foothillMat : tier === 1 ? ridgeMat : farRidgeMat;
      const hill = new THREE.Mesh(ridgeGeo, mat);
      hill.scale.set(rx, h, rz);
      hill.position.set(mx, -h * 0.12, mz);
      hill.rotation.y = (mx * 0.004) % Math.PI;
      landmarkGroup.add(hill);
    }
  }

  // ---------------------------------------------------------------------------
  // 4. Two-Tier City-Scale Building Clusters (1,000+ Shenzhen Buildings)
  // ---------------------------------------------------------------------------
  function building(lot: CityLot, index: number) {
    const { x, z, width: w, depth: d, height: h, style, tier, detailed } = lot;
    const office = style === "office";
    const warehouse = style === "warehouse";
    const palette = office
      ? ["#335668", "#2d4c5d", "#426a7d", "#3c6274"]
      : warehouse
        ? ["#495a61", "#57686f", "#647479"]
        : ["#64787d", "#7b847d", "#5c7076"];
    const color = palette[index % palette.length];
    const podium = tier === "supertall" ? 3.8 : office ? 2.2 : 1.0;

    // Podium & main tower body
    box("stone", x, podium / 2, z, w + 1.2, podium, d + 1.2, "#384b53");
    box(office ? "tower" : "stone", x, podium + h / 2, z, w, h, d, color);

    // Crowns & aviation lights on supertalls / highrises
    if (tier === "supertall") {
      const crownH = h * 0.16;
      box(
        "tower",
        x,
        podium + h + crownH / 2,
        z,
        w * 0.72,
        crownH,
        d * 0.72,
        "#4f7d91",
      );
      box(
        "light",
        x,
        podium + h + crownH + 0.35,
        z,
        w * 0.74,
        0.38,
        d * 0.74,
        index % 2 === 0 ? "#72e6ee" : "#ffe0a3",
      );
      box("stone", x, podium + h + crownH + 4.2, z, 0.35, 8.0, 0.35, "#b5c6cb");
      box(
        "light",
        x,
        podium + h + crownH + 8.5,
        z,
        0.58,
        0.58,
        0.58,
        "#ff5f6d",
      );
    } else if (office && h > 34) {
      box("glass", x, podium + h + 1.8, z, w * 0.62, 3.4, d * 0.62, "#487185");
      box(
        "light",
        x,
        podium + h + 3.65,
        z,
        w * 0.64,
        0.28,
        d * 0.64,
        "#82dce6",
      );
    } else {
      box(
        "stone",
        x,
        podium + h + 0.28,
        z,
        w + 0.36,
        0.52,
        d + 0.36,
        "#7d9299",
      );
    }

    // Tier C (Outer Metropolitan Ring): lightweight architectural light bands for 60fps at 10x scale
    if (!detailed) {
      if (!warehouse) {
        const bands = Math.min(5, Math.max(2, Math.floor(h / 16)));
        for (let b = 0; b < bands; b++) {
          const y = podium + ((b + 0.6) / bands) * (h - 2);
          const litRoll = cityNoise(index * 47 + b * 19);
          box(
            litRoll < 0.45 ? "light" : "glass",
            x,
            y,
            z,
            w + 0.16,
            office ? 1.5 : 1.0,
            d + 0.16,
            litRoll < 0.18 ? "#92e4ec" : litRoll < 0.45 ? "#dfc086" : "#25495e",
          );
        }
      }
      return;
    }

    // Tier B (Foreground Houhai & Futian Core): high-detail mullions, spandrels & lit windows
    if (!warehouse) {
      const cols = tier === "supertall" ? 4 : 3;
      for (const side of [-1, 1]) {
        for (let c = 0; c <= cols; c++) {
          const nx = x + (c / cols - 0.5) * w * 0.84;
          const nz = z + (c / cols - 0.5) * d * 0.84;
          box(
            "trim",
            nx,
            podium + h / 2,
            z + side * (d / 2 + 0.1),
            0.18,
            h,
            0.22,
            office ? "#7ea1ae" : "#809294",
          );
          box(
            "trim",
            x + side * (w / 2 + 0.1),
            podium + h / 2,
            nz,
            0.22,
            h,
            0.18,
            office ? "#7ea1ae" : "#809294",
          );
        }
      }
    }

    const floorStep = tier === "supertall" ? 6.2 : office ? 5.2 : 4.6;
    const floors = Math.min(14, Math.max(1, Math.floor(h / floorStep)));
    const wCols = office ? 3 : 2;
    for (let floor = 0; floor < floors; floor++) {
      const y = podium + 2.4 + floor * floorStep;
      if (y > podium + h - 1.6) break;
      for (const side of [-1, 1]) {
        for (let col = 0; col < wCols; col++) {
          const px = x + ((col + 0.5) / wCols - 0.5) * w * 0.82;
          const pz = z + ((col + 0.5) / wCols - 0.5) * d * 0.82;
          const litRoll = cityNoise(index * 137 + floor * 29 + col * 7 + side);
          const lit = litRoll < (tier === "supertall" ? 0.28 : 0.2);
          const surface: Surface = lit ? "light" : "glass";
          const winColor = lit
            ? litRoll < 0.08
              ? "#98e5ec"
              : "#e0be83"
            : office
              ? "#22465c"
              : "#324d5a";
          box(
            surface,
            px,
            y,
            z + side * (d / 2 + 0.06),
            (w / wCols) * 0.72,
            office ? 2.0 : 1.4,
            0.14,
            winColor,
          );
          box(
            surface,
            x + side * (w / 2 + 0.06),
            y,
            pz,
            0.14,
            office ? 2.0 : 1.4,
            (d / wCols) * 0.72,
            winColor,
          );
        }
      }
    }
  }

  const lots = makeCityLots();
  lots.forEach(building);

  // Far-horizon outer metropolitan sprawl extending to x=±1420, z=-760
  let outerIdx = 19000;
  for (let gx = -1420; gx <= 1440; gx += 62) {
    for (let gz = -740; gz <= 70; gz += 58) {
      if (gx > -945 && gx < 945 && gz > -655) continue;
      if (Math.abs(gx - RIVER_CENTER_X) < 42) continue;
      const n = cityNoise(++outerIdx * 1.9);
      if (n < 0.25) continue;
      const oh = 16 + n * 44;
      const ow = 18 + cityNoise(outerIdx + 33) * 14;
      const od = 16 + cityNoise(outerIdx + 61) * 12;
      box("stone", gx, oh / 2, gz, ow, oh, od, n > 0.6 ? "#2a414e" : "#223440");
      if (n > 0.7) {
        box("light", gx, oh + 0.3, gz, ow * 0.65, 0.35, od * 0.65, "#6ec8d4");
      }
    }
  }

  // ---------------------------------------------------------------------------
  // 5. Coastal Park Trees & Three Emergency Drone Vertiports
  // ---------------------------------------------------------------------------
  const treePositions: [number, number][] = [];
  for (let x = -910; x <= 930; x += 22) {
    if (Math.abs(x - RIVER_CENTER_X) < RIVER_HALF_WIDTH + 8) continue;
    for (const tz of [SHORELINE_Z - 10, SHORELINE_Z - 20]) {
      if (landmarks.some((p) => Math.hypot(x - p.x, tz - p.z) < 26)) continue;
      treePositions.push([x + (cityNoise(x + tz) - 0.5) * 4, tz]);
    }
  }
  for (let x = -860; x <= 880; x += 30) {
    if (Math.abs(x - RIVER_CENTER_X) < RIVER_HALF_WIDTH + 10) continue;
    if (xStreets.some((sx) => Math.abs(sx - x) < 9)) continue;
    treePositions.push([x, -42]);
  }
  for (const side of [-1, 1]) {
    for (let z = -620; z <= 82; z += 26) {
      if (zStreets.some((sz) => Math.abs(sz - z) < 10)) continue;
      treePositions.push([RIVER_CENTER_X + side * (RIVER_HALF_WIDTH + 6.5), z]);
    }
  }

  // 3 Emergency Drone Vertiports (Nanshan Hub / Shenzhen Bay Diversion / Futian Hospital)
  for (const [index, p] of landmarks.entries()) {
    box("ground", p.x, 0.2, p.z, 30, 0.4, 30, "#3d5c5a");
    box("ground", p.x, 0.42, p.z, 22.5, 0.24, 22.5, "#1e333c");
    const padGlow = index === 1 ? "#ffc779" : "#6fe8df";
    for (const side of [-1, 1]) {
      box("light", p.x + side * 11.2, 0.6, p.z, 0.35, 0.12, 22.8, padGlow);
      box("light", p.x, 0.6, p.z + side * 11.2, 22.8, 0.12, 0.35, padGlow);
    }
    box("light", p.x - 3.4, 0.62, p.z, 0.75, 0.08, 8.6, "#dff8fa");
    box("light", p.x + 3.4, 0.62, p.z, 0.75, 0.08, 8.6, "#dff8fa");
    box("light", p.x, 0.62, p.z, 7.2, 0.08, 0.75, "#dff8fa");
  }

  for (const [x, z] of treePositions) {
    box("stone", x, 1.8, z, 0.45, 3.2, 0.45, "#5d5648");
  }

  // ---------------------------------------------------------------------------
  // 6. Batched InstancedMesh Assembly (High FPS at 10x Metropolis Scale)
  // ---------------------------------------------------------------------------
  const transform = new THREE.Object3D();
  const color = new THREE.Color();
  const cube = new THREE.BoxGeometry(1, 1, 1);

  const towerShape = new THREE.Shape();
  towerShape.moveTo(-0.44, -0.5);
  towerShape.lineTo(0.44, -0.5);
  towerShape.lineTo(0.5, -0.44);
  towerShape.lineTo(0.5, 0.44);
  towerShape.lineTo(0.44, 0.5);
  towerShape.lineTo(-0.44, 0.5);
  towerShape.lineTo(-0.5, 0.44);
  towerShape.lineTo(-0.5, -0.44);
  towerShape.closePath();
  const tower = new THREE.ExtrudeGeometry(towerShape, {
    depth: 1,
    bevelEnabled: false,
  });
  tower.rotateX(-Math.PI / 2);
  tower.translate(0, -0.5, 0);

  const surfaces = {
    stone: new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.72,
    }),
    glass: new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.2,
      metalness: 0.45,
    }),
    ground: new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.92,
    }),
    light: new THREE.MeshBasicMaterial({
      color: 0xffffff,
      toneMapped: false,
    }),
    trim: new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.4,
      metalness: 0.38,
    }),
    tower: new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.28,
      metalness: 0.42,
    }),
  };

  for (const surface of Object.keys(parts) as Surface[]) {
    const list = parts[surface];
    if (!list.length) continue;
    const mesh = new THREE.InstancedMesh(
      surface === "tower" ? tower : cube,
      surfaces[surface],
      list.length,
    );
    list.forEach(([x, y, z, w, h, d, tint], i) => {
      transform.position.set(x, y, z);
      transform.scale.set(w, h, d);
      transform.updateMatrix();
      mesh.setMatrixAt(i, transform.matrix);
      mesh.setColorAt(i, color.set(tint));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.computeBoundingSphere();
    mesh.castShadow =
      surface === "stone" || surface === "glass" || surface === "tower";
    mesh.receiveShadow = surface !== "light";
    root.add(mesh);
  }

  const trees = new THREE.InstancedMesh(
    new THREE.IcosahedronGeometry(1, 1),
    new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.92 }),
    treePositions.length,
  );
  treePositions.forEach(([x, z], i) => {
    const size = 2.0 + cityNoise(i + 400) * 0.9;
    transform.position.set(x, 4.4, z);
    transform.scale.set(size, size * 1.15, size);
    transform.updateMatrix();
    trees.setMatrixAt(i, transform.matrix);
    trees.setColorAt(i, color.set(i % 3 === 0 ? "#46705d" : "#2e5448"));
  });
  trees.instanceMatrix.needsUpdate = true;
  if (trees.instanceColor) trees.instanceColor.needsUpdate = true;
  trees.computeBoundingSphere();
  trees.castShadow = true;
  trees.receiveShadow = true;
  root.add(trees);

  root.userData = {
    cityId: "shenzhen-bay-10x",
    buildingCount: lots.length + shenzhenLandmarks.length,
    detailCount:
      Object.values(parts).reduce((sum, list) => sum + list.length, 0) +
      treePositions.length,
    landmarkCount: shenzhenLandmarks.length,
    fictional: true,
  };
  return root;
}
