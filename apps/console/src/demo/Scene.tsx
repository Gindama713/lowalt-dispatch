import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import decoderWasm from "three/examples/jsm/libs/draco/gltf/draco_decoder.wasm?url";
import decoderWrapper from "three/examples/jsm/libs/draco/gltf/draco_wasm_wrapper.js?url";
import decoderScript from "three/examples/jsm/libs/draco/gltf/draco_decoder.js?url";
import modelUrl from "../../../../references/rea-city-flight/asset/out/cr30_lod1.glb?url";
import heroModelUrl from "../../../../references/rea-city-flight/asset/out/cr30.glb?url";
import type { DemoFrame, VisualView } from "./playback";
import { createCity } from "./City";
import {
  createEnvironment,
  createStudio,
  makeBackdrop,
  type StudioAngle,
} from "./Studio";
import { createWater } from "./Water";

// Artistic scene coordinates only. No map projection or real-world navigation.
const points = [
  new THREE.Vector3(-70, 2, 40),
  new THREE.Vector3(-35, 24, 24),
  new THREE.Vector3(5, 24, 4),
  new THREE.Vector3(37, 2, -25),
];
const destination = new THREE.Vector3(76, 2, -52);
const opening = new THREE.CatmullRomCurve3(points.slice(0, 3));
const ending = new THREE.CatmullRomCurve3([
  points[2],
  new THREE.Vector3(26, 18, -12),
  points[3],
]);
const illustratedPlan = new THREE.CatmullRomCurve3([
  points[2],
  new THREE.Vector3(44, 26, -30),
  destination,
]);
const labels = [
  { point: points[0], caption: "中心物资站" },
  { point: points[3], caption: "备降点" },
  { point: destination, caption: "河东救援点" },
];

export default function Scene({
  frame,
  view,
  studioAngle,
}: {
  frame: DemoFrame;
  view: VisualView;
  studioAngle: StudioAngle;
}) {
  const host = useRef<HTMLDivElement>(null);
  const current = useRef({ frame, view, studioAngle });
  const [unavailable, setUnavailable] = useState(false);
  const [modelState, setModelState] = useState<
    "loading" | "loaded" | "fallback"
  >("loading");
  const [heroState, setHeroState] = useState<"loading" | "loaded" | "fallback">(
    "loading",
  );
  const labelElements = useRef<(HTMLSpanElement | null)[]>([]);
  current.current = { frame, view, studioAngle };

  useEffect(() => {
    const node = host.current;
    if (!node) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setUnavailable(true);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.6));
    renderer.setClearColor("#0b1420");
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.08;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.shadowMap.autoUpdate = false;
    node.appendChild(renderer.domElement);
    renderer.domElement.setAttribute("aria-label", "虚构三维城市动画");
    renderer.domElement.setAttribute("role", "img");
    const environment = createEnvironment(renderer);
    const studio = createStudio(environment.texture);
    const scene = new THREE.Scene();
    scene.background = makeBackdrop("#24414d", "#080e17");
    scene.environment = environment.texture;
    scene.environmentIntensity = 0.44;
    scene.fog = new THREE.Fog("#0c1924", 244, 500);
    scene.add(new THREE.HemisphereLight(0xbadbf0, 0x303a3d, 1.2));
    const sun = new THREE.DirectionalLight(0xffd5a8, 3.2);
    sun.position.set(-118, 92, 65);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.left = -160;
    sun.shadow.camera.right = 160;
    sun.shadow.camera.top = 140;
    sun.shadow.camera.bottom = -140;
    sun.shadow.camera.near = 1;
    sun.shadow.camera.far = 420;
    sun.shadow.normalBias = 0.15;
    sun.shadow.bias = -0.0002;
    sun.shadow.camera.updateProjectionMatrix();
    scene.add(sun);
    scene.add(sun.target);
    const rim = new THREE.DirectionalLight(0x80c9f2, 1.35);
    rim.position.set(110, 65, -95);
    scene.add(rim);
    const camera = new THREE.PerspectiveCamera(43, 1, 0.5, 900);
    const city = createCity();
    scene.add(city);
    node.dataset.city = "waterfront";
    node.dataset.buildings = String(city.userData.buildingCount);
    node.dataset.details = String(city.userData.detailCount);
    const water = createWater();
    scene.add(water);
    renderer.shadowMap.needsUpdate = true;
    // These overlays belong to the city review shot, not the beauty shot.
    const reviewOverlay = new THREE.Group();
    scene.add(reviewOverlay);
    const line = new THREE.Mesh(
      new THREE.TubeGeometry(opening, 40, 0.52, 6, false),
      new THREE.MeshBasicMaterial({ color: 0x6ee8df, toneMapped: false }),
    );
    reviewOverlay.add(line);
    const alternate = new THREE.Mesh(
      new THREE.TubeGeometry(ending, 40, 0.52, 6, false),
      new THREE.MeshBasicMaterial({ color: 0xffc779, toneMapped: false }),
    );
    alternate.visible = false;
    reviewOverlay.add(alternate);
    const planned = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(illustratedPlan.getPoints(40)),
      new THREE.LineDashedMaterial({
        color: 0x87a4ba,
        dashSize: 3,
        gapSize: 2,
      }),
    );
    planned.computeLineDistances();
    reviewOverlay.add(planned);
    const marker = (p: THREE.Vector3, color: number) => {
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(5, 6.3, 48),
        new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide }),
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.set(p.x, 0.4, p.z);
      reviewOverlay.add(ring);
    };
    marker(points[0], 0x56e0dd);
    marker(points[3], 0xffc779);
    marker(destination, 0x87a4ba);
    const aircraft = new THREE.Group();
    const fallback = new THREE.Mesh(
      new THREE.OctahedronGeometry(3.3),
      new THREE.MeshStandardMaterial({ color: 0xe1eef7, metalness: 0.65 }),
    );
    aircraft.add(fallback);
    reviewOverlay.add(aircraft);
    let disposed = false;
    const freeObject = (object: THREE.Object3D) => {
      const geometries = new Set<THREE.BufferGeometry>();
      const materials = new Set<THREE.Material>();
      object.traverse((child) => {
        if (!(child instanceof THREE.Mesh || child instanceof THREE.Line))
          return;
        if (child instanceof THREE.InstancedMesh) child.dispose();
        geometries.add(child.geometry);
        for (const m of Array.isArray(child.material)
          ? child.material
          : [child.material])
          materials.add(m);
      });
      geometries.forEach((g) => g.dispose());
      materials.forEach((m) => {
        for (const value of Object.values(m))
          if (value instanceof THREE.Texture) value.dispose();
        m.dispose();
      });
    };
    const decoderAssets: Record<string, string> = {
      "draco_decoder.wasm": decoderWasm,
      "draco_wasm_wrapper.js": decoderWrapper,
      "draco_decoder.js": decoderScript,
    };
    const manager = new THREE.LoadingManager();
    manager.setURLModifier((url) => decoderAssets[url] ?? url);
    const decoder = new DRACOLoader(manager);
    const loader = new GLTFLoader(manager).setDRACOLoader(decoder);
    let studioNeedsShadow = true;
    let cityNeedsShadow = true;
    let redraw = true;
    loader.load(
      modelUrl,
      (gltf) => {
        if (disposed) {
          freeObject(gltf.scene);
          return;
        }
        const box = new THREE.Box3().setFromObject(gltf.scene);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const scale = 9 / Math.max(size.x, size.y, size.z, 0.001);
        gltf.scene.scale.setScalar(scale);
        gltf.scene.position.copy(center.multiplyScalar(-scale));
        aircraft.remove(fallback);
        freeObject(fallback);
        aircraft.add(gltf.scene);
        redraw = true;
        setModelState("loaded");
      },
      undefined,
      () => {
        if (!disposed) setModelState("fallback");
      },
    );

    loader.load(
      heroModelUrl,
      (gltf) => {
        if (disposed) {
          freeObject(gltf.scene);
          return;
        }
        studio.mount(gltf.scene);
        studioNeedsShadow = true;
        redraw = true;
        setHeroState("loaded");
      },
      undefined,
      () => {
        if (!disposed) setHeroState("fallback");
      },
    );

    const resize = () => {
      const width = Math.max(1, node.clientWidth),
        height = Math.max(1, node.clientHeight);
      renderer.setSize(width, height);
      redraw = true;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      studio.camera.aspect = width / height;
      studio.camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(node);
    resize();
    let raf = 0;
    // Camera presets are driven only by playback time, so paused and
    // repeated captures settle into the same visual composition.
    const shots = [
      { time: 0, angle: 0.26, height: 154, distance: 200 },
      { time: 32, angle: 0.5, height: 127, distance: 185 },
      { time: 52, angle: 0.72, height: 113, distance: 195 },
      { time: 95, angle: 0.48, height: 122, distance: 190 },
      { time: 118, angle: 0.18, height: 137, distance: 190 },
      { time: 142, angle: -0.22, height: 153, distance: 200 },
      { time: 180, angle: -0.22, height: 153, distance: 200 },
    ];
    let renderedView: VisualView | null = null;
    let renderedAngle: StudioAngle | null = null;
    let renderedTime = -1;
    const animate = () => {
      const { frame: state, view: activeView, studioAngle } = current.current;
      const time = Math.floor(state.time * 30) / 30;
      // A paused shot is a static photograph. Avoid continually drawing the
      // high-detail mesh or the city when none of their inputs have changed.
      if (
        !redraw &&
        renderedTime === time &&
        renderedView === activeView &&
        renderedAngle === studioAngle
      ) {
        raf = requestAnimationFrame(animate);
        return;
      }
      redraw = false;
      renderedTime = time;
      renderedView = activeView;
      renderedAngle = studioAngle;
      if (activeView === "studio") {
        if (studioNeedsShadow) {
          renderer.shadowMap.needsUpdate = true;
          studioNeedsShadow = false;
        }
        studio.updateCamera(time, studioAngle);
        renderer.render(studio.scene, studio.camera);
        renderer.domElement.setAttribute("aria-label", "CR30 高精度模型特写");
        node.dataset.renderedView = "studio";
        node.dataset.renderedAngle = studioAngle;
        raf = requestAnimationFrame(animate);
        return;
      }
      if (cityNeedsShadow) {
        renderer.shadowMap.needsUpdate = true;
        cityNeedsShadow = false;
      }
      water.material.uniforms.uTime.value = time;
      reviewOverlay.visible = activeView === "city";
      aircraft.position.copy(
        state.time < 118
          ? opening.getPoint(
              THREE.MathUtils.clamp((state.time - 95) / 23, 0, 1),
            )
          : ending.getPoint(
              THREE.MathUtils.clamp((state.time - 118) / 24, 0, 1),
            ),
      );
      const next = shots.findIndex((shot) => state.time < shot.time);
      const index = next === -1 ? shots.length - 1 : Math.max(1, next);
      const before = shots[index - 1];
      const after = shots[index];
      const mix = THREE.MathUtils.smoothstep(
        state.time,
        before.time,
        after.time,
      );
      const angle = THREE.MathUtils.lerp(before.angle, after.angle, mix);
      const fit = Math.max(1, 1.24 / camera.aspect);
      const distance =
        THREE.MathUtils.lerp(before.distance, after.distance, mix) * fit;
      if (activeView === "detail") {
        // Fixed art-directed composition of the fictional office district.
        const nudge = THREE.MathUtils.smoothstep(state.time, 32, 52);
        camera.position.set(
          52 + (52 - 11 * nudge) * fit,
          10 + 46 * fit,
          -35 + 69 * fit,
        );
        camera.lookAt(52, 10, -35);
      } else {
        camera.position.set(
          distance * Math.sin(angle),
          THREE.MathUtils.lerp(before.height, after.height, mix) * fit,
          distance * Math.cos(angle),
        );
        camera.lookAt(0, 5, 0);
      }
      camera.updateMatrixWorld();
      alternate.visible = state.phase >= 4;
      labels.forEach(({ point }, index) => {
        const element = labelElements.current[index];
        if (!element) return;
        const projected = point
          .clone()
          .add(new THREE.Vector3(0, 5, 0))
          .project(camera);
        element.style.left = `${(projected.x + 1) * 50}%`;
        element.style.top = `${(1 - projected.y) * 50}%`;
      });
      renderer.render(scene, camera);
      renderer.domElement.setAttribute(
        "aria-label",
        activeView === "detail" ? "虚拟城市建筑近景" : "虚构三维城市动画",
      );
      node.dataset.renderedView = activeView;
      raf = requestAnimationFrame(animate);
    };
    camera.position.set(95, 132, 160);
    animate();
    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      observer.disconnect();
      freeObject(scene);
      freeObject(studio.scene);
      if (scene.background instanceof THREE.Texture) scene.background.dispose();
      if (studio.scene.background instanceof THREE.Texture)
        studio.scene.background.dispose();
      environment.dispose();
      decoder.dispose();
      sun.shadow.dispose();
      studio.shadow.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return (
    <div
      className="demo-scene"
      ref={host}
      data-model={modelState}
      data-hero-model={heroState}
      data-view={view}
      data-studio-angle={studioAngle}
    >
      {!unavailable &&
        view === "city" &&
        labels.map(({ caption }, index) => (
          <span
            key={caption}
            className="demo-map-label"
            ref={(element) => {
              labelElements.current[index] = element;
            }}
          >
            {caption}
          </span>
        ))}
      {unavailable && (
        <div className="demo-scene-fallback">虚拟城区 · 3D 渲染不可用</div>
      )}
      {view === "city" && modelState === "fallback" && !unavailable && (
        <span className="demo-model-fallback">模型加载失败 · 使用示意标记</span>
      )}
      {view === "studio" && heroState !== "loaded" && !unavailable && (
        <span className="demo-model-fallback">
          {heroState === "loading"
            ? "正在加载高精度模型…"
            : "高精度模型加载失败"}
        </span>
      )}
    </div>
  );
}
