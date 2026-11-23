import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

export type StudioAngle = "orbit" | "side" | "top";

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

/** An isolated product photography stage for the existing CR30 art asset. */
export function createStudio(environment: THREE.Texture) {
  const scene = new THREE.Scene();
  scene.background = makeBackdrop("#27434e", "#080e16");
  scene.environment = environment;
  scene.environmentIntensity = 1.15;

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
    scene.add(ring);
  }

  const key = new THREE.DirectionalLight(0xffe4c0, 3.5);
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

  const fill = new THREE.DirectionalLight(0xa6dfff, 1.7);
  fill.position.set(7, 4, 4);
  const rim = new THREE.DirectionalLight(0x91dbf6, 4.5);
  rim.position.set(2, 6, -8);
  scene.add(fill, rim, new THREE.HemisphereLight(0xe3f0ff, 0x28343b, 0.6));

  let focusY = 0.8;
  function mount(asset: THREE.Object3D) {
    const bounds = new THREE.Box3().setFromObject(asset);
    const size = bounds.getSize(new THREE.Vector3());
    const center = bounds.getCenter(new THREE.Vector3());
    const scale = 6.6 / Math.max(size.x, size.y, size.z, 0.001);
    asset.scale.setScalar(scale);
    asset.position.set(
      -center.x * scale,
      0.255 - bounds.min.y * scale,
      -center.z * scale,
    );
    focusY = 0.255 + (size.y * scale) / 2;
    asset.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        child.castShadow = true;
        child.receiveShadow = true;
      }
    });
    model.add(asset);
  }

  function updateCamera(time: number, angle: StudioAngle) {
    const ratio = Math.max(1, 1.24 / camera.aspect);
    const turn = THREE.MathUtils.smoothstep(time, 34, 49);
    const theta =
      angle === "side"
        ? Math.PI / 2
        : angle === "top"
          ? 0.12
          : 0.55 + turn * 1.2;
    const radius = (angle === "top" ? 1.2 : 9.8) * ratio;
    const height =
      (angle === "top" ? 11 : angle === "side" ? 2.25 : 4.2) * ratio;
    camera.position.set(
      Math.sin(theta) * radius,
      focusY + height,
      Math.cos(theta) * radius,
    );
    camera.lookAt(0, focusY, 0);
  }

  return { scene, camera, mount, updateCamera, shadow: key.shadow };
}
