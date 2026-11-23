import * as THREE from "three";
import {
  cityNoise,
  landmarks,
  makeCityLots,
  xStreets,
  zStreets,
  type CityLot,
} from "./city-layout";

type BoxPart = [number, number, number, number, number, number, string];
type Surface = "stone" | "glass" | "ground" | "light" | "trim" | "tower";
type PartLists = Record<Surface, BoxPart[]>;

/**
 * A miniature fictional waterfront. Geometry is decorative only and never
 * feeds dispatch, planning, clearance checks, or real-world coordinates.
 */
export function createCity() {
  const root = new THREE.Group();
  root.name = "AERIS fictional waterfront";
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

  // A layered scale-model base and two distinct waterfront districts.
  box("ground", 0, -3.4, 0, 230, 5, 180, "#14252f");
  box("ground", 0, -6.4, 0, 228, 1, 178, "#0c1824");
  box("ground", -64.5, -0.5, 0, 101, 0.8, 178, "#34464a");
  box("ground", 64.5, -0.5, 0, 101, 0.8, 178, "#394a4d");
  box("ground", 0, -0.28, 0, 28, 0.18, 178, "#155569");

  // Road surfaces, sidewalks, lane paint and zebra crossings.
  for (const x of xStreets) {
    box("ground", x, 0.02, 0, 7.8, 0.12, 176, "#1c272d");
    for (const side of [-1, 1]) {
      box("ground", x + side * 4.3, 0.11, 0, 0.8, 0.18, 176, "#65706d");
    }
    for (let z = -83; z <= 83; z += 5.5) {
      if (zStreets.some((v) => Math.abs(v - z) < 5)) continue;
      box("ground", x, 0.1, z, 0.15, 0.025, 1.85, "#bac4bd");
    }
  }
  for (const z of zStreets) {
    for (const side of [-1, 1]) {
      const x = side * 68;
      box("ground", x, 0.04, z, 94, 0.14, 7.5, "#1c272d");
      box("ground", x, 0.12, z + 4.2, 94, 0.16, 0.8, "#65706d");
      box("ground", x, 0.12, z - 4.2, 94, 0.16, 0.8, "#65706d");
      for (let dx = 23; dx < 112; dx += 5.4) {
        const px = side * dx;
        if (xStreets.some((v) => Math.abs(v - px) < 5)) continue;
        box("ground", px, 0.13, z, 1.8, 0.025, 0.14, "#bac4bd");
      }
    }
  }
  for (const x of xStreets) {
    for (const z of zStreets) {
      for (let i = 0; i < 5; i++) {
        box(
          "ground",
          x - 2.5 + i * 1.25,
          0.16,
          z + 3.1,
          0.6,
          0.03,
          1.2,
          "#c1cdca",
        );
      }
    }
  }

  // Quays, pedestrian walks, two scenic bridges and their railings.
  for (const side of [-1, 1]) {
    box("stone", side * 14.7, 0.03, 0, 1.8, 0.65, 178, "#72868a");
    box("ground", side * 17.5, 0.08, 0, 3.4, 0.24, 178, "#73817e");
    box("ground", side * 20.5, 0.03, 0, 2.3, 0.2, 178, "#3b5c50");
    for (let z = -81; z <= 81; z += 9) {
      box("stone", side * 16.1, 1.75, z, 0.22, 3.2, 0.22, "#798889");
      box("light", side * 16.1, 3.45, z, 0.45, 0.18, 0.45, "#c6b58a");
    }
  }
  for (const z of [-57, 63]) {
    box("stone", 0, 0.6, z, 47, 1.2, 7.6, "#687d83");
    box("ground", 0, 1.26, z, 46, 0.12, 5.6, "#25363f");
    for (const side of [-1, 1]) {
      box("stone", 0, 1.85, z + side * 3.55, 47, 0.35, 0.18, "#8a9da1");
      for (let x = -21; x <= 21; x += 3.5) {
        box("stone", x, 1.55, z + side * 3.55, 0.16, 0.9, 0.16, "#607984");
      }
    }
  }

  function building(lot: CityLot, index: number) {
    const { x, z, width: w, depth: d, height: h, style } = lot;
    const office = style === "office";
    const warehouse = style === "warehouse";
    const palette = office
      ? ["#466a78", "#365865", "#537787"]
      : warehouse
        ? ["#536268", "#616e72", "#788280"]
        : ["#7a8988", "#a29c8c", "#8c9b9c"];
    const color = palette[index % palette.length];
    const podium = 0.6;
    box("ground", x, 0.08, z, w + 2, 0.18, d + 2, "#737c77");
    box("stone", x, podium / 2, z, w + 0.5, podium, d + 0.5, "#45585d");
    box(office ? "tower" : "stone", x, podium + h / 2, z, w, h, d, color);
    box(
      office ? "tower" : "stone",
      x,
      podium + h + 0.16,
      z,
      w + 0.3,
      0.32,
      d + 0.3,
      "#9aabac",
    );

    // Foundation courses and recessed lobby glass add visible depth.
    for (const side of [-1, 1]) {
      box("trim", x, 0.85, z + side * (d / 2 + 0.06), w, 0.18, 0.14, "#849798");
      box("trim", x + side * (w / 2 + 0.06), 0.85, z, 0.14, 0.18, d, "#849798");
      box(
        "glass",
        x,
        1.22,
        z + side * (d / 2 + 0.08),
        w * 0.53,
        0.78,
        0.14,
        "#203f50",
      );
      box(
        "trim",
        x,
        1.72,
        z + side * (d / 2 + 0.24),
        w * 0.59,
        0.14,
        0.69,
        "#a0adb0",
      );
    }

    // The roof parapet casts a thin silhouette rather than a flat box outline.
    for (const side of [-1, 1]) {
      box(
        "stone",
        x,
        h + 1.03,
        z + side * (d / 2 - 0.1),
        w,
        0.25,
        0.2,
        "#88979a",
      );
      box(
        "stone",
        x + side * (w / 2 - 0.1),
        h + 1.03,
        z,
        0.2,
        0.25,
        d,
        "#88979a",
      );
    }

    // Roof installations and equipment distinguish different building types.
    if (warehouse) {
      for (let i = -1; i <= 1; i++) {
        box(
          "trim",
          x + i * w * 0.24,
          h + 0.92,
          z,
          w * 0.21,
          0.15,
          d * 0.69,
          "#a1a9a8",
        );
        box(
          "glass",
          x + i * w * 0.24,
          h + 0.98,
          z,
          w * 0.2,
          0.16,
          d * 0.66,
          "#263e50",
        );
        for (let bar = -2; bar <= 2; bar++) {
          box(
            "trim",
            x + i * w * 0.24,
            h + 1.07,
            z + bar * d * 0.12,
            w * 0.19,
            0.025,
            0.045,
            "#627a88",
          );
        }
      }
      for (const side of [-1, 1]) {
        box(
          "trim",
          x,
          1.52,
          z + side * (d / 2 + 0.1),
          w * 0.45,
          2.0,
          0.15,
          "#344550",
        );
        box(
          "stone",
          x,
          2.6,
          z + side * (d / 2 + 0.35),
          w * 0.53,
          0.16,
          0.8,
          "#879797",
        );
      }
    } else {
      box("stone", x, h + 1.15, z, w * 0.3, 1, d * 0.36, "#728488");
      box(
        "stone",
        x + w * 0.27,
        h + 0.95,
        z - d * 0.22,
        1.3,
        0.6,
        1.5,
        "#4c6166",
      );
      for (const side of [-1, 1]) {
        box(
          "trim",
          x + side * w * 0.23,
          h + 1.16,
          z,
          0.85,
          0.43,
          1.15,
          "#576c74",
        );
        for (let grille = -2; grille <= 2; grille++) {
          box(
            "trim",
            x + side * w * 0.23,
            h + 1.39,
            z + grille * 0.2,
            0.72,
            0.04,
            0.045,
            "#263d48",
          );
        }
      }
      if (office && h > 23) {
        box("glass", x, h + 2.15, z, w * 0.57, 2.4, d * 0.56, "#6f8791");
        box("stone", x, h + 3.45, z, w * 0.61, 0.2, d * 0.6, "#a3b1b2");
        box("stone", x, h + 4.6, z, 0.18, 2.1, 0.18, "#b8c3c4");
        box("light", x, h + 5.7, z, 0.28, 0.2, 0.28, "#e6a66a");
      }
    }

    // Vertical metal ribs create continuous reflections along taller facades.
    if (!warehouse) {
      const columns = office ? 5 : 4;
      for (const side of [-1, 1]) {
        for (let column = 0; column <= columns; column++) {
          const nx = x + (column / columns - 0.5) * w * (office ? 0.82 : 0.92);
          const nz = z + (column / columns - 0.5) * d * (office ? 0.82 : 0.92);
          box(
            "trim",
            nx,
            podium + h / 2,
            z + side * (d / 2 + 0.06),
            0.095,
            h,
            0.15,
            "#91a3a9",
          );
          box(
            "trim",
            x + side * (w / 2 + 0.06),
            podium + h / 2,
            nz,
            0.15,
            h,
            0.095,
            "#91a3a9",
          );
        }
      }
    }

    // Windows have restrained warm accents; roofs and streets stay quiet.
    const floors = Math.max(1, Math.floor(h / 2.6));
    for (let floor = 0; floor < floors; floor++) {
      const y = podium + 1.1 + floor * 2.6;
      if (y > h + podium - 0.65) break;
      for (const side of [-1, 1]) {
        if (!warehouse) {
          const band = office ? "#607e89" : "#929e99";
          box(
            "trim",
            x,
            y - 0.57,
            z + side * (d / 2 + 0.07),
            w,
            0.13,
            0.14,
            band,
          );
          box(
            "trim",
            x + side * (w / 2 + 0.07),
            y - 0.57,
            z,
            0.14,
            0.13,
            d,
            band,
          );
          if (!office && (floor + index) % 2 === 0) {
            const balconyZ = z + side * (d / 2 + 0.36);
            box(
              "stone",
              x,
              y - 0.54,
              balconyZ,
              w * 0.58,
              0.13,
              0.76,
              "#a8aaa0",
            );
            box(
              "trim",
              x,
              y - 0.21,
              z + side * (d / 2 + 0.72),
              w * 0.54,
              0.53,
              0.09,
              "#6f8c92",
            );
          }
        }
        const count = office ? 5 : warehouse ? 2 : 4;
        for (let column = 0; column < count; column++) {
          const px = x + ((column + 0.5) / count - 0.5) * w * 0.86;
          const pz = z + ((column + 0.5) / count - 0.5) * d * 0.86;
          const lit =
            cityNoise(index * 137 + floor * 29 + column * 7 + side) < 0.18;
          const surface = lit ? "light" : "glass";
          const windowColor = lit ? "#c3a676" : office ? "#284a61" : "#3d5864";
          box(
            surface,
            px,
            y,
            z + side * (d / 2 + 0.035),
            (w / count) * 0.68,
            office ? 1.12 : 0.86,
            0.08,
            windowColor,
          );
          box(
            surface,
            x + side * (w / 2 + 0.035),
            y,
            pz,
            0.08,
            office ? 1.12 : 0.86,
            (d / count) * 0.68,
            windowColor,
          );
        }
      }
    }
  }

  const lots = makeCityLots();
  lots.forEach(building);

  // Open civic spaces, ornamental trees, and presentation-only landing discs.
  const treePositions: [number, number][] = [];
  for (const side of [-1, 1]) {
    for (let z = -79; z < 83; z += 8) {
      if (zStreets.some((s) => Math.abs(s - z) < 5)) continue;
      treePositions.push([side * 20.4, z]);
    }
  }
  for (const x of [-100, -73.5, -41, 38.5, 69, 98]) {
    for (const z of [-72, -42, -12, 18, 48, 75]) {
      const occupied = lots.some(
        (lot) => Math.abs(lot.x - x) < 13 && Math.abs(lot.z - z) < 16,
      );
      const reserved = landmarks.some((p) => Math.hypot(p.x - x, p.z - z) < 17);
      if (occupied || reserved) continue;
      box("ground", x, 0.04, z, 15, 0.2, 19, "#456459");
      box("ground", x, 0.16, z, 1.25, 0.05, 19, "#8a9690");
      box("ground", x, 0.16, z, 15, 0.05, 1.25, "#8a9690");
      for (const dx of [-5, 5]) {
        for (const dz of [-6, 6]) treePositions.push([x + dx, z + dz]);
      }
    }
  }
  for (const [index, p] of landmarks.entries()) {
    box("ground", p.x, 0.13, p.z, 14, 0.2, 14, "#516c68");
    box("ground", p.x, 0.25, p.z, 10.8, 0.11, 10.8, "#273c42");
    for (const side of [-1, 1]) {
      box("ground", p.x + side * 5.4, 0.33, p.z, 0.14, 0.03, 10.9, "#a3c3bf");
      box("ground", p.x, 0.33, p.z + side * 5.4, 10.9, 0.03, 0.14, "#a3c3bf");
      treePositions.push([p.x + side * 8, p.z + (index % 2 ? 6 : -6)]);
    }
  }
  for (const [x, z] of treePositions) {
    box("stone", x, 1, z, 0.23, 1.8, 0.23, "#6a6251");
  }

  const transform = new THREE.Object3D();
  const color = new THREE.Color();
  const cube = new THREE.BoxGeometry(1, 1, 1);
  // Chamfered corner towers share one extruded mesh, with real edge normals.
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
      roughness: 0.74,
    }),
    glass: new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.24,
      metalness: 0.33,
    }),
    ground: new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.94,
    }),
    light: new THREE.MeshBasicMaterial({ color: 0xffffff }),
    trim: new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.48,
      metalness: 0.26,
    }),
    tower: new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.34,
      metalness: 0.27,
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
    new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.94 }),
    treePositions.length,
  );
  treePositions.forEach(([x, z], i) => {
    const size = 1 + cityNoise(i + 400) * 0.42;
    transform.position.set(x, 2.55, z);
    transform.scale.set(size, size * 1.25, size);
    transform.updateMatrix();
    trees.setMatrixAt(i, transform.matrix);
    trees.setColorAt(i, color.set(i % 3 === 0 ? "#507662" : "#365c4f"));
  });
  trees.instanceMatrix.needsUpdate = true;
  if (trees.instanceColor) trees.instanceColor.needsUpdate = true;
  trees.computeBoundingSphere();
  trees.castShadow = true;
  trees.receiveShadow = true;
  root.add(trees);
  root.userData = {
    buildingCount: lots.length,
    detailCount:
      Object.values(parts).reduce((sum, list) => sum + list.length, 0) +
      treePositions.length,
    fictional: true,
  };
  return root;
}
