import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

export type StudioAngle = "orbit" | "side" | "top";

type ExplodePart = {
  node: THREE.Object3D;
  origin: THREE.Vector3;
  offset: THREE.Vector3;
  stagger: number;
};

type RotorNode = {
  node: THREE.Object3D;
  dir: number;
};

/** A local light rig; no remote HDRI or texture dependencies. */
export function createEnvironment(renderer: THREE.WebGLRenderer) {
  const room = new RoomEnvironment();
  const generator = new THREE.PMREMGenerator(renderer);
  const target = generator.fromScene(room, 0.06);
  room.dispose();
  generator.dispose();
  return target;
}

export function makeBackdrop(inner: string, outer: string) {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 512;
  const context = canvas.getContext("2d");
  if (!context) return new THREE.Color(outer);
  const gradient = context.createRadialGradient(260, 190, 18, 260, 235, 360);
  gradient.addColorStop(0, inner);
  gradient.addColorStop(1, outer);
  context.fillStyle = gradient;
  context.fillRect(0, 0, 512, 512);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function easeInOutCubic(x: number): number {
  const t = Math.max(0, Math.min(1, x));
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

/** An isolated product photography stage for the existing CR30 art asset. */
export function createStudio(environment: THREE.Texture) {
  const scene = new THREE.Scene();
  scene.background = makeBackdrop("#27434e", "#080e16");
  scene.environment = environment;
  scene.environmentIntensity = 1.18;

  const camera = new THREE.PerspectiveCamera(35, 1, 0.05, 100);
  const model = new THREE.Group();
  scene.add(model);

  const floor = new THREE.Mesh(
    new THREE.CircleGeometry(28, 96),
    new THREE.MeshStandardMaterial({
      color: 0x101820,
      roughness: 0.68,
      metalness: 0.12,
    }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -0.24;
  floor.receiveShadow = true;
  scene.add(floor);

  const platform = new THREE.Mesh(
    new THREE.CylinderGeometry(4.85, 4.95, 0.37, 96),
    new THREE.MeshStandardMaterial({
      color: 0x202d36,
      roughness: 0.38,
      metalness: 0.45,
    }),
  );
  platform.position.y = -0.03;
  platform.receiveShadow = true;
  scene.add(platform);

  const ringGroup = new THREE.Group();
  scene.add(ringGroup);

  const ringMaterial = new THREE.MeshBasicMaterial({
    color: 0x6ed4dc,
    transparent: true,
    opacity: 0.72,
    toneMapped: false,
  });
  for (let index = 0; index < 4; index++) {
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(
        4.57,
        4.6,
        64,
        1,
        index * Math.PI * 0.5 + 0.1,
        Math.PI * 0.5 - 0.29,
      ),
      ringMaterial,
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.162;
    ringGroup.add(ring);
  }

  // Outer precision telemetry ring
  const outerRing = new THREE.Mesh(
    new THREE.RingGeometry(5.3, 5.33, 128),
    new THREE.MeshBasicMaterial({
      color: 0x5bc2dc,
      transparent: true,
      opacity: 0.28,
      side: THREE.DoubleSide,
      toneMapped: false,
    }),
  );
  outerRing.rotation.x = -Math.PI / 2;
  outerRing.position.y = -0.21;
  ringGroup.add(outerRing);

  // Subtle holographic laser scan plane shown during part explosion
  const scanMat = new THREE.MeshBasicMaterial({
    color: 0x6ef2dd,
    transparent: true,
    opacity: 0,
    side: THREE.DoubleSide,
    depthWrite: false,
    toneMapped: false,
  });
  const scanPlane = new THREE.Mesh(new THREE.CircleGeometry(4.45, 72), scanMat);
  scanPlane.rotation.x = -Math.PI / 2;
  scanPlane.position.y = 0.8;
  scene.add(scanPlane);

  const key = new THREE.DirectionalLight(0xffe4c0, 3.6);
  key.position.set(-5, 9, 7);
  key.castShadow = true;
  key.shadow.mapSize.set(1536, 1536);
  key.shadow.camera.left = -8;
  key.shadow.camera.right = 8;
  key.shadow.camera.top = 8;
  key.shadow.camera.bottom = -8;
  key.shadow.camera.near = 0.1;
  key.shadow.camera.far = 30;
  key.shadow.normalBias = 0.025;
  key.shadow.bias = -0.0001;
  key.shadow.camera.updateProjectionMatrix();
  scene.add(key, key.target);

  const fill = new THREE.DirectionalLight(0xa6dfff, 1.75);
  fill.position.set(7, 4, 4);
  const rim = new THREE.DirectionalLight(0x91dbf6, 4.6);
  rim.position.set(2, 6, -8);
  scene.add(fill, rim, new THREE.HemisphereLight(0xe3f0ff, 0x28343b, 0.65));

  let focusY = 0.8;
  let baseModelY = 0.255;
  let mountedAsset: THREE.Object3D | null = null;
  const explodeParts: ExplodePart[] = [];
  const rotors: RotorNode[] = [];
  let appliedExplode = -1;

  function mount(asset: THREE.Object3D) {
    const bounds = new THREE.Box3().setFromObject(asset);
    const size = bounds.getSize(new THREE.Vector3());
    const center = bounds.getCenter(new THREE.Vector3());
    const scale = 6.6 / Math.max(size.x, size.y, size.z, 0.001);
    asset.scale.setScalar(scale);
    baseModelY = 0.255 - bounds.min.y * scale;
    asset.position.set(-center.x * scale, baseModelY, -center.z * scale);
    focusY = 0.255 + (size.y * scale) / 2;

    const tunedMaterials = new Set<THREE.Material>();
    explodeParts.length = 0;
    rotors.length = 0;

    asset.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        child.castShadow = true;
        child.receiveShadow = true;
        const mats = Array.isArray(child.material)
          ? child.material
          : [child.material];
        for (const mat of mats) {
          if (
            mat instanceof THREE.MeshStandardMaterial &&
            !tunedMaterials.has(mat)
          ) {
            tunedMaterials.add(mat);
            if (mat.metalness > 0.9 && mat.emissiveIntensity > 1) {
              mat.emissiveIntensity = 0.08;
            }
          }
        }
      }
      if (/^PWR_PROP-(FL|FR|RL|RR)$/.test(child.name)) {
        rotors.push({
          node: child,
          dir: child.name.endsWith("FL") || child.name.endsWith("RR") ? 1 : -1,
        });
      }
      const ud = child.userData as {
        system?: unknown;
        explodeDir?: unknown;
        explodeDist?: unknown;
        stagger?: unknown;
      };
      if (
        ud.system &&
        Array.isArray(ud.explodeDir) &&
        ud.explodeDir.length === 3 &&
        typeof ud.explodeDist === "number"
      ) {
        explodeParts.push({
          node: child,
          origin: child.position.clone(),
          // 0.56 factor keeps all 318 exploded parts cleanly framed inside the studio stage
          offset: new THREE.Vector3(
            Number(ud.explodeDir[0]),
            Number(ud.explodeDir[1]),
            Number(ud.explodeDir[2]),
          ).multiplyScalar(ud.explodeDist * 0.56),
          stagger: Number(ud.stagger) || 0,
        });
      }
    });

    mountedAsset = asset;
    appliedExplode = -1;
    model.add(asset);
  }

  /** Apply deterministic 318-part explosion + rotor angle; returns true if shadows need refresh. */
  function updateAssembly(time: number, explodeAmount: number): boolean {
    const clamped = Math.max(0, Math.min(1, explodeAmount));
    ringGroup.rotation.y = time * 0.12;

    // Gentle hover lift during explosion so bottom payload modules stay clear of pedestal
    if (mountedAsset) {
      mountedAsset.position.y = baseModelY + easeInOutCubic(clamped) * 0.52;
    }

    // Subtle scan sweep when exploded
    if (clamped > 0.02) {
      scanMat.opacity = 0.09 * Math.sin(clamped * Math.PI * 0.5 + 0.3);
      scanPlane.position.y =
        focusY + 0.35 + Math.sin(time * 1.45) * (0.9 + clamped * 0.7);
    } else {
      scanMat.opacity = 0;
    }

    // Deterministic rotor spin tied to playback time
    for (let i = 0; i < rotors.length; i++) {
      rotors[i].node.rotation.y = time * 2.2 * rotors[i].dir;
    }

    const changed = Math.abs(clamped - appliedExplode) > 0.002;
    if (changed) {
      appliedExplode = clamped;
      for (let i = 0; i < explodeParts.length; i++) {
        const part = explodeParts[i];
        const delay = Math.min(0.45, part.stagger * 0.42);
        const local = Math.max(
          0,
          Math.min(1, (clamped - delay) / Math.max(0.15, 1 - delay)),
        );
        const eased = easeInOutCubic(local);
        part.node.position
          .copy(part.origin)
          .addScaledVector(part.offset, eased);
      }
    }
    return changed;
  }

  function updateCamera(
    time: number,
    angle: StudioAngle,
    explodeAmount: number = 0,
  ) {
    const ratio = Math.max(1, 1.24 / camera.aspect);
    const turn = THREE.MathUtils.smoothstep(time, 34, 49);
    const explodePull = easeInOutCubic(explodeAmount) * 2.9;
    const theta =
      angle === "side"
        ? Math.PI / 2
        : angle === "top"
          ? 0.12
          : 0.55 + turn * 1.45;
    const radius = ((angle === "top" ? 1.3 : 9.8) + explodePull) * ratio;
    const height =
      ((angle === "top" ? 11.2 : angle === "side" ? 2.4 : 4.2) +
        explodePull * 0.65) *
      ratio;
    const targetY = focusY + easeInOutCubic(explodeAmount) * 0.35;
    camera.position.set(
      Math.sin(theta) * radius,
      targetY + height,
      Math.cos(theta) * radius,
    );
    camera.lookAt(0, targetY, 0);
  }

  function getPartCount(): number {
    return explodeParts.length;
  }

  return {
    scene,
    camera,
    mount,
    updateAssembly,
    updateCamera,
    getPartCount,
    shadow: key.shadow,
  };
}
