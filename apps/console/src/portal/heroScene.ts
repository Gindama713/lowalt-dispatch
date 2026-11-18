import * as T from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/examples/jsm/loaders/DRACOLoader.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import cr30Url from "../../../../references/rea-city-flight/asset/out/cr30.glb?url";
import dracoWrapper from "three/examples/jsm/libs/draco/gltf/draco_wasm_wrapper.js?url";
import dracoWasm from "three/examples/jsm/libs/draco/gltf/draco_decoder.wasm?url";
import type { buildCity } from "../../../../references/rea-city-flight/map-nav/map/city-world.js";
import { inspectAssembly, type PartScope } from "./heroAssembly";

export type HeroState = {
  mode: "model" | "city";
  scope: string;
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
  onScopes: (scopes: PartScope[]) => void,
  onPick: (scope: string) => void,
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
  const hemisphere = new T.HemisphereLight(0xddeeff, 0x7588ad, 1.8);
  scene.add(hemisphere);
  const key = new T.DirectionalLight(0xffffff, 4);
  key.position.set(3, 7, 5);
  scene.add(key);
  const rim = new T.DirectionalLight(0x6cbbff, 3);
  rim.position.set(-5, 3, -4);
  scene.add(rim);
  const model = new T.Group();
  scene.add(model);
  const axis = new T.LineSegments(
    new T.BufferGeometry(),
    new T.LineDashedMaterial({
      color: 0x9debd8,
      transparent: true,
      opacity: 0.55,
      dashSize: 0.024,
      gapSize: 0.02,
      depthWrite: false,
    }),
  );
  axis.visible = false;
  model.add(axis);
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

  let assembly: ReturnType<typeof inspectAssembly> | undefined;
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
  let lastScope = "";
  let lastTime = 0;
  let elapsed = 0;
  let lastMode = state.current.mode;
  let lastReset = state.current.reset;
  let lastAppearance = "";
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
      model.add(gltf.scene);
      assembly = inspectAssembly(gltf.scene);
      onScopes(assembly.scopes);
      renderer.domElement.dataset.parts = String(assembly.count);
      lastScope = "";
      notify("model");
    },
    undefined,
    () => {
      if (!disposed) notify("model", "CR30 模型加载失败，请重新载入。");
    },
  );

  const orbit = new T.Spherical();
  const arm = new T.Vector3();
  let flight:
    | {
        from: T.Spherical;
        to: T.Spherical;
        start: T.Vector3;
        end: T.Vector3;
        time: number;
      }
    | undefined;
  let wheelRadius: number | undefined;
  function frameSelection(immediate = false) {
    const isCity = state.current.mode === "city";
    const box = !isCity && assembly?.bounds.get(state.current.scope);
    const end = new T.Vector3(0, isCity ? -0.8 : -0.05, 0);
    const position = isCity
      ? new T.Vector3(5.2, 4.8, 6.2)
      : new T.Vector3(2.45, 3.15, 6.75).multiplyScalar(
          Math.max(1, 1.52 / camera.aspect),
        );
    controls.minDistance = isCity ? 4 : 0.65;
    if (box) {
      box.getCenter(end);
      const direction = new T.Vector3(end.x, 0, end.z);
      if (direction.lengthSq() < 0.12) direction.set(-0.65, 0, 1);
      direction.normalize().y = state.current.scope.startsWith("PWR_")
        ? 0.17
        : end.y < -0.15
          ? 0.22
          : 0.64;
      direction.normalize();
      const right = new T.Vector3()
        .crossVectors(camera.up, direction)
        .normalize();
      const up = new T.Vector3().crossVectors(direction, right);
      const tan = Math.tan(T.MathUtils.degToRad(camera.fov / 2));
      let distance = 0;
      for (const x of [box.min.x, box.max.x])
        for (const y of [box.min.y, box.max.y])
          for (const z of [box.min.z, box.max.z]) {
            arm.set(x, y, z).sub(end);
            const extent = Math.max(
              Math.abs(arm.dot(right)) / camera.aspect,
              Math.abs(arm.dot(up)),
            );
            distance = Math.max(
              distance,
              arm.dot(direction) + (1.14 * extent) / tan,
            );
          }
      position
        .copy(end)
        .addScaledVector(
          direction,
          T.MathUtils.clamp(
            distance,
            controls.minDistance,
            controls.maxDistance,
          ),
        );
    }
    wheelRadius = undefined;
    if (immediate || reduced.matches) {
      flight = undefined;
      camera.position.copy(position);
      controls.target.copy(end);
      controls.update();
      return;
    }
    const from = new T.Spherical().setFromVector3(
      arm.subVectors(camera.position, controls.target),
    );
    const to = new T.Spherical().setFromVector3(position.sub(end));
    const angle = to.theta - from.theta;
    to.theta = from.theta + Math.atan2(Math.sin(angle), Math.cos(angle));
    flight = { from, to, start: controls.target.clone(), end, time: 0 };
  }
  function interrupt() {
    flight = undefined;
    wheelRadius = undefined;
  }
  controls.addEventListener("start", interrupt);
  const canvas = renderer.domElement;
  function wheel(event: WheelEvent) {
    if (state.current.mode !== "model") return;
    event.preventDefault();
    event.stopImmediatePropagation();
    flight = undefined;
    const units =
      event.deltaMode === 1
        ? 16
        : event.deltaMode === 2
          ? canvas.clientHeight
          : 1;
    const delta = T.MathUtils.clamp(event.deltaY * units, -240, 240);
    wheelRadius = T.MathUtils.clamp(
      (wheelRadius ?? controls.getDistance()) * Math.exp(delta * 0.0016),
      controls.minDistance,
      controls.maxDistance,
    );
  }
  canvas.addEventListener("wheel", wheel, { capture: true, passive: false });
  const ray = new T.Raycaster();
  const pointer = new T.Vector2();
  let tap: { id: number; x: number; y: number } | undefined;
  function pointerDown(event: PointerEvent) {
    tap =
      event.isPrimary && event.button === 0 && state.current.mode === "model"
        ? { id: event.pointerId, x: event.clientX, y: event.clientY }
        : undefined;
  }
  function pointerMove(event: PointerEvent) {
    if (
      tap &&
      tap.id === event.pointerId &&
      Math.hypot(event.clientX - tap.x, event.clientY - tap.y) > 5
    )
      tap = undefined;
  }
  function clearTap() {
    tap = undefined;
  }
  function pointerUp(event: PointerEvent) {
    pointerMove(event);
    if (tap?.id !== event.pointerId) return;
    clearTap();
    if (state.current.mode !== "model" || !assembly) return;
    const rect = canvas.getBoundingClientRect();
    pointer.set(
      (2 * (event.clientX - rect.left)) / rect.width - 1,
      1 - (2 * (event.clientY - rect.top)) / rect.height,
    );
    ray.setFromCamera(pointer, camera);
    const id = assembly.pick(ray);
    if (id) onPick(id);
  }
  canvas.addEventListener("pointerdown", pointerDown);
  canvas.addEventListener("pointermove", pointerMove);
  canvas.addEventListener("pointerup", pointerUp);
  canvas.addEventListener("pointercancel", clearTap);
  function resize() {
    const { width, height } = host.getBoundingClientRect();
    if (!width || !height) return;
    const oldAspect = camera.aspect;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
    if (oldAspect !== camera.aspect) frameSelection(true);
  }
  frameSelection(true);
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(host);
  resize();
  const labels = host.getElementsByClassName(
    "hx-hotspot",
  ) as HTMLCollectionOf<HTMLButtonElement>;
  const projected = new T.Vector3();

  function render(time: number) {
    const dt = Math.min((time - lastTime) / 1000 || 0.016, 0.05);
    lastTime = time;
    elapsed += dt;
    const current = state.current;
    if (
      current.mode !== lastMode ||
      current.reset !== lastReset ||
      (assembly && current.scope !== lastScope)
    ) {
      assembly?.select(current.scope);
      const box = assembly?.bounds.get(current.scope);
      if (box && current.scope.startsWith("PWR_")) {
        const center = box.getCenter(new T.Vector3());
        axis.geometry.dispose();
        axis.geometry = new T.BufferGeometry().setFromPoints([
          new T.Vector3(center.x, box.min.y, center.z),
          new T.Vector3(center.x, box.max.y, center.z),
        ]);
        axis.computeLineDistances();
      }
      frameSelection(current.mode !== lastMode);
      lastMode = current.mode;
      lastReset = current.reset;
      lastScope = current.scope;
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
    const appearance = current.mode + "-" + current.theme;
    if (lastAppearance !== appearance) {
      const isCity = current.mode === "city";
      renderer.toneMappingExposure = isCity ? 0.9 : 1.05;
      scene.environmentIntensity = isCity ? 0.2 : 1.05;
      hemisphere.intensity = isCity ? 1.1 : 1.4;
      key.intensity = isCity ? 1.5 : 2.45;
      rim.intensity = isCity ? 0.45 : 2.8;
      ringMaterial.opacity = current.theme === "dark" ? 0.35 : 0.25;
      lastAppearance = appearance;
    }
    const blend = reduced.matches ? 1 : 1 - Math.exp(-5 * dt);
    const progress = assembly?.update(current.explode / 100, blend) ?? 0;
    axis.visible =
      current.mode === "model" &&
      current.scope.startsWith("PWR_") &&
      progress > 0.04;
    axis.material.opacity = progress * 0.55;
    renderer.domElement.dataset.explode = progress.toFixed(3);
    model.scale.setScalar(
      T.MathUtils.lerp(
        model.scale.x,
        current.scope ? 1 : 1 - progress * 0.18,
        blend,
      ),
    );
    model.visible = current.mode === "model";
    if (city) {
      city.world.visible = current.mode === "city";
      if (!reduced.matches && city.world.visible) city.update(dt);
    }
    floor.visible = current.mode === "model" && !current.scope;
    scan.visible = current.scan;
    scan.position.y = reduced.matches ? 0.25 : Math.sin(elapsed * 0.75) * 1.7;
    particles.visible = current.scan;
    if (!reduced.matches) particles.rotation.y = elapsed * 0.035;
    canvas.style.touchAction = current.mode === "model" ? "none" : "pan-y";
    if (flight) {
      flight.time += dt;
      const t = reduced.matches
        ? 1
        : T.MathUtils.smootherstep(flight.time, 0, 0.85);
      const { from, to } = flight;
      controls.target.lerpVectors(flight.start, flight.end, t);
      orbit.set(
        T.MathUtils.lerp(from.radius, to.radius, t),
        T.MathUtils.lerp(from.phi, to.phi, t),
        T.MathUtils.lerp(from.theta, to.theta, t),
      );
      camera.position.copy(controls.target).add(arm.setFromSpherical(orbit));
      if (t === 1) flight = undefined;
    } else if (wheelRadius !== undefined) {
      const distance = reduced.matches
        ? wheelRadius
        : T.MathUtils.damp(controls.getDistance(), wheelRadius, 14, dt);
      arm.subVectors(camera.position, controls.target).setLength(distance);
      camera.position.copy(controls.target).add(arm);
      if (Math.abs(distance - wheelRadius) < 0.001) wheelRadius = undefined;
    }
    controls.autoRotate = current.rotate && !reduced.matches && !flight;
    controls.update(dt);
    renderer.render(scene, camera);
    const motorAnchor = labels.length && assembly?.anchors.get("PWR_MOTOR-FL");
    const motorOnLeft = motorAnchor
      ? projected
          .copy(motorAnchor)
          .applyMatrix4(model.matrixWorld)
          .project(camera).x < 0
      : false;
    for (const label of labels) {
      const point = assembly?.anchors.get(label.dataset.anchor!);
      if (!point) continue;
      projected.copy(point).applyMatrix4(model.matrixWorld).project(camera);
      const x = ((projected.x + 1) / 2) * canvas.clientWidth;
      const y = ((1 - projected.y) / 2) * canvas.clientHeight;
      const leadLeft =
        label.dataset.anchor === "BAT" ? !motorOnLeft : motorOnLeft;
      label.dataset.side =
        x < 98
          ? "right"
          : x > canvas.clientWidth - 98
            ? "left"
            : leadLeft
              ? "left"
              : "right";
      label.style.visibility =
        Math.abs(projected.x) < 0.93 &&
        Math.abs(projected.y) < 0.85 &&
        Math.abs(projected.z) < 1
          ? "visible"
          : "hidden";
      label.style.transform = `translate3d(${x}px,${y}px,0)`;
    }
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
    canvas.removeEventListener("wheel", wheel, true);
    canvas.removeEventListener("pointerdown", pointerDown);
    canvas.removeEventListener("pointermove", pointerMove);
    canvas.removeEventListener("pointerup", pointerUp);
    canvas.removeEventListener("pointercancel", clearTap);
    controls.removeEventListener("start", interrupt);
    assembly?.dispose();
    controls.dispose();
    draco.dispose();
    release(scene);
    environment.dispose();
    renderer.dispose();
    renderer.domElement.remove();
  };
}
