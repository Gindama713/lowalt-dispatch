import * as T from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/examples/jsm/loaders/DRACOLoader.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import cr30Url from "../../../../references/rea-city-flight/asset/out/cr30.glb?url";
import dracoWrapper from "three/examples/jsm/libs/draco/gltf/draco_wasm_wrapper.js?url";
import dracoWasm from "three/examples/jsm/libs/draco/gltf/draco_decoder.wasm?url";
import type { buildCity } from "../../../../references/rea-city-flight/map-nav/map/city-world.js";

export type HeroState = {
  mode: "model" | "city";
  explode: number;
  rotate: boolean;
  scan: boolean;
  reset: number;
  theme: "light" | "dark";
};

// Display the supplied assets without invoking any flight or planning code.
export function createHeroScene(
  host: HTMLDivElement,
  state: { current: HeroState },
  notify: (mode: HeroState["mode"], error?: string) => void,
) {
  let renderer: T.WebGLRenderer;
  try {
    renderer = new T.WebGLRenderer({ alpha: true, antialias: true });
  } catch {
    const error = "当前浏览器无法启用 WebGL，请更换浏览器后重试。";
    notify("model", error);
    notify("city", error);
    return () => {};
  }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  renderer.toneMapping = T.ACESFilmicToneMapping;
  host.appendChild(renderer.domElement);
  const scene = new T.Scene();
  const camera = new T.PerspectiveCamera(36, 1, 0.05, 120);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enablePan = false;
  controls.enableDamping = true;
  controls.minDistance = 4;
  controls.maxDistance = 17;
  controls.minPolarAngle = 0.25;
  controls.maxPolarAngle = Math.PI / 2.03;
  controls.autoRotateSpeed = 0.5;
  renderer.domElement.style.touchAction = "pan-y";
  const pmrem = new T.PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  const environment = pmrem.fromScene(room, 0.04);
  room.dispose();
  pmrem.dispose();
  scene.environment = environment.texture;
  scene.add(new T.HemisphereLight(0xddeeff, 0x7588ad, 2.4));
  const key = new T.DirectionalLight(0xffffff, 4);
  key.position.set(3, 7, 5);
  scene.add(key);
  const rim = new T.DirectionalLight(0x6cbbff, 3);
  rim.position.set(-5, 3, -4);
  scene.add(rim);
  const model = new T.Group();
  scene.add(model);
  const floor = new T.Group();
  floor.position.y = -1.65;
  scene.add(floor);
  const ringMaterial = new T.MeshBasicMaterial({
    color: 0x87c9f5,
    transparent: true,
    opacity: 0.28,
    side: T.DoubleSide,
  });
  for (const radius of [2.15, 2.8, 3.4]) {
    const ring = new T.Mesh(
      new T.RingGeometry(radius, radius + 0.012, 128),
      ringMaterial,
    );
    ring.rotation.x = -Math.PI / 2;
    floor.add(ring);
  }
  const grid = new T.GridHelper(7, 28, 0x8eb8d9, 0x8eb8d9);
  grid.material.transparent = true;
  grid.material.opacity = 0.12;
  floor.add(grid);
  const scan = new T.Mesh(
    new T.PlaneGeometry(6.5, 6.5),
    new T.MeshBasicMaterial({
      color: 0x71f8db,
      transparent: true,
      opacity: 0.065,
      side: T.DoubleSide,
      depthWrite: false,
    }),
  );
  scan.rotation.x = -Math.PI / 2;
  scene.add(scan);
  const points = new Float32Array(80 * 3);
  for (let i = 0; i < 80; i++) {
    const angle = i * 2.39996;
    const radius = 2 + ((i * 17) % 23) / 10;
    points.set(
      [
        Math.cos(angle) * radius,
        ((i * 13) % 31) / 10 - 1.5,
        Math.sin(angle) * radius,
      ],
      i * 3,
    );
  }
  const particles = new T.Points(
    new T.BufferGeometry().setAttribute(
      "position",
      new T.BufferAttribute(points, 3),
    ),
    new T.PointsMaterial({
      color: 0x9fe8ff,
      size: 0.025,
      transparent: true,
      opacity: 0.6,
      depthWrite: false,
    }),
  );
  scene.add(particles);

  const parts: {
    mesh: T.Mesh;
    origin: T.Vector3;
    offset: T.Vector3;
    stagger: number;
  }[] = [];
  const manager = new T.LoadingManager();
  manager.setURLModifier((url) =>
    url === "draco_wasm_wrapper.js"
      ? dracoWrapper
      : url === "draco_decoder.wasm"
        ? dracoWasm
        : url,
  );
  const draco = new DRACOLoader(manager)
    .setDecoderConfig({ type: "wasm" })
    .setWorkerLimit(2);
  const loader = new GLTFLoader().setDRACOLoader(draco);
  let disposed = false;
  let visible = true;
  let city: ReturnType<typeof buildCity> | undefined;
  let cityRequested = false;
  let progress = 0;
  let lastTime = 0;
  let elapsed = 0;
  let lastMode = state.current.mode;
  let lastReset = state.current.reset;
  let lastTheme = "";
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");

  function release(root: T.Object3D) {
    const geometries = new Set<T.BufferGeometry>();
    const materials = new Set<T.Material>();
    const textures = new Set<T.Texture>();
    root.traverse((object) => {
      if (
        !(
          object instanceof T.Mesh ||
          object instanceof T.Points ||
          object instanceof T.LineSegments
        )
      )
        return;
      geometries.add(object.geometry);
      for (const material of Array.isArray(object.material)
        ? object.material
        : [object.material]) {
        materials.add(material);
        for (const value of Object.values(material))
          if (value instanceof T.Texture) textures.add(value);
      }
    });
    geometries.forEach((geometry) => geometry.dispose());
    materials.forEach((material) => material.dispose());
    textures.forEach((texture) => texture.dispose());
  }
  loader.load(
    cr30Url,
    (gltf) => {
      if (disposed) {
        release(gltf.scene);
        return;
      }
      const bounds = new T.Box3().setFromObject(gltf.scene);
      const size = bounds.getSize(new T.Vector3());
      const scale = 4.7 / Math.max(size.x, size.y, size.z);
      gltf.scene.position
        .copy(bounds.getCenter(new T.Vector3()))
        .multiplyScalar(-scale);
      gltf.scene.scale.setScalar(scale);
      gltf.scene.traverse((object) => {
        if (!(object instanceof T.Mesh)) return;
        const { explodeDir, explodeDist, stagger } = object.userData;
        if (Array.isArray(explodeDir) && typeof explodeDist === "number")
          parts.push({
            mesh: object,
            origin: object.position.clone(),
            offset: new T.Vector3()
              .fromArray(explodeDir)
              .multiplyScalar(explodeDist),
            stagger: Number(stagger) || 0,
          });
      });
      model.add(gltf.scene);
      renderer.domElement.dataset.parts = String(parts.length);
      notify("model");
    },
    undefined,
    () => {
      if (!disposed) notify("model", "CR30 模型加载失败，请重新载入。");
    },
  );

  function resetCamera() {
    if (state.current.mode === "city") camera.position.set(6.3, 5.5, 7.7);
    else camera.position.set(5.7, 3.2, 6.3);
    controls.target.set(0, -0.05, 0);
    controls.update();
  }
  function resize() {
    const { width, height } = host.getBoundingClientRect();
    if (!width || !height) return;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  }
  resetCamera();
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(host);
  resize();

  function render(time: number) {
    const dt = Math.min((time - lastTime) / 1000 || 0.016, 0.05);
    lastTime = time;
    elapsed += dt;
    const current = state.current;
    if (current.mode !== lastMode || current.reset !== lastReset) {
      resetCamera();
      lastMode = current.mode;
      lastReset = current.reset;
    }
    if (current.mode === "city" && !cityRequested) {
      cityRequested = true;
      import("../../../../references/rea-city-flight/map-nav/map/city-world.js")
        .then(({ buildCity }) => {
          if (disposed) return;
          city = buildCity(scene);
          city.world.scale.setScalar(0.0063);
          city.world.position.y = -1.25;
          renderer.domElement.dataset.buildings = String(city.stats.buildings);
          notify("city");
        })
        .catch(() => {
          if (!disposed) notify("city", "城市场景加载失败，请重新载入。");
        });
    }
    if (lastTheme !== current.theme) {
      renderer.toneMappingExposure = current.theme === "dark" ? 1.65 : 1.45;
      ringMaterial.opacity = current.theme === "dark" ? 0.35 : 0.25;
      lastTheme = current.theme;
    }
    const target = current.explode / 100;
    progress = reduced.matches
      ? target
      : T.MathUtils.damp(progress, target, 5, dt);
    for (const { mesh, origin, offset, stagger } of parts) {
      const amount = T.MathUtils.smoothstep(
        progress,
        stagger * 0.18,
        0.8 + stagger * 0.18,
      );
      mesh.position.copy(origin).addScaledVector(offset, amount);
    }
    renderer.domElement.dataset.explode = progress.toFixed(3);
    model.scale.setScalar(1 - progress * 0.18);
    model.visible = current.mode === "model";
    if (city) {
      city.world.visible = current.mode === "city";
      if (!reduced.matches && city.world.visible) city.update(dt);
    }
    floor.visible = current.mode === "model";
    scan.visible = current.scan;
    scan.position.y = reduced.matches ? 0.25 : Math.sin(elapsed * 0.75) * 1.7;
    particles.visible = current.scan;
    if (!reduced.matches) particles.rotation.y = elapsed * 0.035;
    controls.autoRotate = current.rotate && !reduced.matches;
    controls.update(dt);
    renderer.render(scene, camera);
  }
  function visibility() {
    renderer.setAnimationLoop(visible && !document.hidden ? render : null);
    lastTime = 0;
  }
  const intersection = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    visibility();
  });
  intersection.observe(host);
  document.addEventListener("visibilitychange", visibility);
  function contextLost(event: Event) {
    event.preventDefault();
    renderer.setAnimationLoop(null);
    const error = "三维渲染已中断，请重新载入。";
    notify("model", error);
    notify("city", error);
  }
  renderer.domElement.addEventListener("webglcontextlost", contextLost);
  visibility();
  return () => {
    disposed = true;
    renderer.setAnimationLoop(null);
    intersection.disconnect();
    resizeObserver.disconnect();
    document.removeEventListener("visibilitychange", visibility);
    renderer.domElement.removeEventListener("webglcontextlost", contextLost);
    controls.dispose();
    draco.dispose();
    release(scene);
    environment.dispose();
    renderer.dispose();
    renderer.domElement.remove();
  };
}
