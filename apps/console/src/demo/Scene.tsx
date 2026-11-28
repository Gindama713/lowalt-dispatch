import { RoutePolyline, routeSegments } from "../routeGeometry";
import type { TaskEvidence } from "../assistant/taskEvidence";
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import decoderWasm from "three/examples/jsm/libs/draco/gltf/draco_decoder.wasm?url";
import decoderWrapper from "three/examples/jsm/libs/draco/gltf/draco_wasm_wrapper.js?url";
import decoderScript from "three/examples/jsm/libs/draco/gltf/draco_decoder.js?url";
import modelUrl from "../../../../references/rea-city-flight/asset/out/cr30_lod1.glb?url";
import heroModelUrl from "../../../../references/rea-city-flight/asset/out/cr30.glb?url";
import {
  studioExplodeAt,
  type DemoFrame,
  type StudioExplode,
  type VisualView,
} from "./playback";
import { createCity } from "./City";
import {
  createEnvironment,
  createStudio,
  makeBackdrop,
  type StudioAngle,
} from "./Studio";
import { createWater } from "./Water";

// A fixed display transform of the evidence's ENU XY. Heights are visual only.
const worldPoint = ([x, y]: [number, number], height = 24) =>
  new THREE.Vector3((x - 1500) * 0.07, height, (1500 - y) * 0.07);

export default function Scene({
  frame,
  view,
  studioAngle,
  evidence,
  studioExplode = "auto",
}: {
  frame: DemoFrame;
  evidence: TaskEvidence;
  view: VisualView;
  studioAngle: StudioAngle;
  studioExplode?: StudioExplode;
}) {
  const host = useRef<HTMLDivElement>(null);
  const points = evidence.waypoints.map((p) => worldPoint(p));
  const opening = new RoutePolyline(points);
  const labels = [
    { point: points[0], caption: evidence.origin },
    { point: points[points.length - 1], caption: evidence.destination },
  ];
  const current = useRef({ frame, view, studioAngle, studioExplode });
  const [unavailable, setUnavailable] = useState(false);
  const [modelState, setModelState] = useState<
    "loading" | "loaded" | "fallback"
  >("loading");
  const [heroState, setHeroState] = useState<"loading" | "loaded" | "fallback">(
    "loading",
  );
  const labelElements = useRef<(HTMLSpanElement | null)[]>([]);
  current.current = { frame, view, studioAngle, studioExplode };

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
    scene.background = makeBackdrop("#2d586e", "#0c1c2c");
    scene.environment = environment.texture;
    scene.environmentIntensity = 0.6;
    scene.fog = new THREE.Fog("#102434", 1200, 3600);
    scene.add(new THREE.HemisphereLight(0xc2e2f7, 0x26353d, 1.35));
    const sun = new THREE.DirectionalLight(0xffd5a3, 3.4);
    sun.position.set(-480, 420, 380);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.left = -820;
    sun.shadow.camera.right = 820;
    sun.shadow.camera.top = 640;
    sun.shadow.camera.bottom = -640;
    sun.shadow.camera.near = 20;
    sun.shadow.camera.far = 2100;
    sun.shadow.normalBias = 0.4;
    sun.shadow.bias = -0.0002;
    sun.shadow.camera.updateProjectionMatrix();
    scene.add(sun);
    scene.add(sun.target);
    const rim = new THREE.DirectionalLight(0x7ccbf5, 1.65);
    rim.position.set(520, 260, -440);
    scene.add(rim);
    const camera = new THREE.PerspectiveCamera(42, 1, 2, 5400);
    const city = createCity();
    scene.add(city);
    node.dataset.city = String(city.userData.cityId ?? "shenzhen-bay-10x");
    node.dataset.buildings = String(city.userData.buildingCount);
    node.dataset.details = String(city.userData.detailCount);
    const water = createWater();
    scene.add(water);
    const algorithmCity = new THREE.Group();
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(210, 210),
      new THREE.MeshStandardMaterial({ color: 0x142531, roughness: 1 }),
    );
    floor.rotation.x = -Math.PI / 2;
    algorithmCity.add(floor);
    for (const polygon of evidence.buildings) {
      const shape = new THREE.Shape(
        polygon.map(
          (p) => new THREE.Vector2((p[0] - 1500) * 0.07, (p[1] - 1500) * 0.07),
        ),
      );
      const mesh = new THREE.Mesh(
        new THREE.ExtrudeGeometry(shape, { depth: 4, bevelEnabled: false }),
        new THREE.MeshStandardMaterial({
          color: 0x4d687c,
          metalness: 0.2,
          roughness: 0.7,
        }),
      );
      mesh.rotation.x = -Math.PI / 2;
      algorithmCity.add(mesh);
    }
    const grid = new THREE.GridHelper(210, 20, 0x36515f, 0x213744);
    grid.position.y = 0.1;
    algorithmCity.add(grid);
    scene.add(algorithmCity);
    renderer.shadowMap.needsUpdate = true;
    // These overlays belong to the city review shot, not the beauty shot.
    const reviewOverlay = new THREE.Group();
    scene.add(reviewOverlay);
    const line = routeSegments(
      points,
      0.52,
      new THREE.MeshBasicMaterial({ color: 0x6ee8df, toneMapped: false }),
    );
    reviewOverlay.add(line);
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
    marker(points[points.length - 1], 0x87a4ba);
    for (const site of evidence.sites)
      marker(worldPoint(site.point, 0), 0xffc779);
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
        node.dataset.explodeParts = String(studio.getPartCount());
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
    const artShots = [
      { time: 0, angle: -0.14, height: 390, distance: 760 },
      { time: 32, angle: 0.06, height: 350, distance: 710 },
      { time: 52, angle: 0.2, height: 330, distance: 690 },
      { time: 95, angle: 0.08, height: 325, distance: 680 },
      { time: 118, angle: -0.04, height: 345, distance: 700 },
      { time: 142, angle: -0.18, height: 375, distance: 740 },
      { time: 180, angle: -0.18, height: 375, distance: 740 },
    ];
    const evidenceShots = [
      { time: 0, angle: 0.26, height: 154, distance: 200 },
      { time: 32, angle: 0.5, height: 127, distance: 185 },
      { time: 52, angle: 0.72, height: 113, distance: 195 },
      { time: 95, angle: 0.48, height: 122, distance: 190 },
      { time: 118, angle: 0.18, height: 137, distance: 190 },
      { time: 142, angle: -0.22, height: 153, distance: 200 },
      { time: 180, angle: -0.22, height: 153, distance: 200 },
    ];
    let renderedView: VisualView | null = null;
    let renderedAlgorithm: boolean | null = null;
    let renderedAngle: StudioAngle | null = null;
    let renderedExplode: StudioExplode | null = null;
    let renderedTime = -1;
    const animate = () => {
      const {
        frame: state,
        view: activeView,
        studioAngle,
        studioExplode,
      } = current.current;
      const time = Math.floor(state.time * 30) / 30;
      // A paused shot is a static photograph. Avoid continually drawing the
      // high-detail mesh or the city when none of their inputs have changed.
      if (
        !redraw &&
        renderedTime === time &&
        renderedView === activeView &&
        renderedAngle === studioAngle &&
        renderedExplode === studioExplode
      ) {
        raf = requestAnimationFrame(animate);
        return;
      }
      redraw = false;
      renderedTime = time;
      renderedView = activeView;
      renderedAngle = studioAngle;
      renderedExplode = studioExplode;
      if (activeView === "studio") {
        const explodeAmount = studioExplodeAt(studioExplode, time);
        const assemblyMoved = studio.updateAssembly(time, explodeAmount);
        if (studioNeedsShadow || assemblyMoved) {
          renderer.shadowMap.needsUpdate = true;
          studioNeedsShadow = false;
        }
        studio.updateCamera(time, studioAngle, explodeAmount);
        renderer.render(studio.scene, studio.camera);
        renderer.domElement.setAttribute("aria-label", "CR30 高精度模型特写");
        node.dataset.renderedView = "studio";
        node.dataset.renderedAngle = studioAngle;
        node.dataset.renderedExplode = explodeAmount.toFixed(2);
        raf = requestAnimationFrame(animate);
        return;
      }
      if (cityNeedsShadow) {
        renderer.shadowMap.needsUpdate = true;
        cityNeedsShadow = false;
      }
      water.material.uniforms.uTime.value = time;
      const algorithmView = activeView === "city" && state.time >= 52;
      if (renderedAlgorithm !== algorithmView) {
        renderer.shadowMap.needsUpdate = true;
        renderedAlgorithm = algorithmView;
      }
      node.dataset.activeScene = algorithmView
        ? evidence.scenario_id
        : "shenzhen-art";
      node.dataset.activeBuildings = String(
        algorithmView ? evidence.buildings.length : city.userData.buildingCount,
      );
      city.visible = !algorithmView;
      water.visible = !algorithmView;
      algorithmCity.visible = algorithmView;
      reviewOverlay.visible = algorithmView;
      node.dataset.routeId = evidence.route_id;
      node.dataset.routeRevision = evidence.revision;
      aircraft.position.copy(
        opening.getPointAt(
          state.confirmed && evidence.verdict === "passed" ? state.progress : 0,
        ),
      );
      const tangent = opening.getTangentAt(state.progress);
      aircraft.rotation.y = Math.atan2(tangent.x, tangent.z);
      node.dataset.routeProgress = String(state.progress);
      node.dataset.planeEnu = JSON.stringify([
        aircraft.position.x / 0.07 + 1500,
        1500 - aircraft.position.z / 0.07,
      ]);
      const shots = algorithmView ? evidenceShots : artShots;
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
        // Art-directed skyline. Landmark names are scenic, not surveyed coordinates.
        const nudge = THREE.MathUtils.smoothstep(state.time, 32, 52);
        camera.position.set(
          (345 - 48 * nudge) * fit,
          172 * fit,
          (188 - 28 * nudge) * fit,
        );
        camera.lookAt(175, 88, -96);
      } else if (algorithmView) {
        camera.position.set(
          distance * Math.sin(angle),
          THREE.MathUtils.lerp(before.height, after.height, mix) * fit,
          distance * Math.cos(angle),
        );
        camera.lookAt(0, 5, 0);
      } else {
        camera.position.set(
          10 + distance * Math.sin(angle),
          THREE.MathUtils.lerp(before.height, after.height, mix) * fit,
          28 + distance * Math.cos(angle),
        );
        camera.lookAt(12, 48, -60);
      }
      camera.updateMatrixWorld();

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
    camera.position.set(20, 390, 740);
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
