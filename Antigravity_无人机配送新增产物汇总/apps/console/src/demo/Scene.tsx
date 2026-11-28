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
  transitionVeilOpacity,
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

// 10x City-scale Greater Shenzhen Bay artistic scene coordinates only. No real-world navigation.
const points = [
  new THREE.Vector3(-230, 4, 36),
  new THREE.Vector3(-82, 86, 16),
  new THREE.Vector3(42, 92, -20),
  new THREE.Vector3(96, 4, 58),
];
const destination = new THREE.Vector3(278, 4, -98);
const opening = new THREE.CatmullRomCurve3(points.slice(0, 3));
const ending = new THREE.CatmullRomCurve3([
  points[2],
  new THREE.Vector3(74, 64, 22),
  points[3],
]);
const illustratedPlan = new THREE.CatmullRomCurve3([
  points[2],
  new THREE.Vector3(165, 96, -64),
  destination,
]);
const labels = [
  { point: points[0], caption: "南山物资中心" },
  { point: points[3], caption: "深圳湾备降坪" },
  { point: destination, caption: "福田应急医院" },
];

export default function Scene({
  frame,
  view,
  studioAngle,
  studioExplode = "auto",
  playing = false,
}: {
  frame: DemoFrame;
  view: VisualView;
  studioAngle: StudioAngle;
  studioExplode?: StudioExplode;
  playing?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const current = useRef({ frame, view, studioAngle, studioExplode });
  const [unavailable, setUnavailable] = useState(false);
  const [modelState, setModelState] = useState<
    "loading" | "loaded" | "fallback"
  >("loading");
  const [heroState, setHeroState] = useState<"loading" | "loaded" | "fallback">(
    "loading",
  );
  const [heroParts, setHeroParts] = useState(0);
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
    renderer.shadowMap.needsUpdate = true;
    // These overlays belong to the city review shot, not the beauty shot.
    const reviewOverlay = new THREE.Group();
    scene.add(reviewOverlay);
    const line = new THREE.Mesh(
      new THREE.TubeGeometry(opening, 56, 1.6, 8, false),
      new THREE.MeshBasicMaterial({ color: 0x6ee8df, toneMapped: false }),
    );
    reviewOverlay.add(line);
    const alternate = new THREE.Mesh(
      new THREE.TubeGeometry(ending, 48, 1.7, 8, false),
      new THREE.MeshBasicMaterial({ color: 0xffc779, toneMapped: false }),
    );
    alternate.visible = false;
    reviewOverlay.add(alternate);
    const planned = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(illustratedPlan.getPoints(48)),
      new THREE.LineDashedMaterial({
        color: 0x94b2c7,
        dashSize: 8.5,
        gapSize: 5.5,
      }),
    );
    planned.computeLineDistances();
    reviewOverlay.add(planned);

    // Illustrative restriction / negative-margin risk zone along the unguarded Futian corridor
    const constraintZone = new THREE.Group();
    const zoneWall = new THREE.Mesh(
      new THREE.CylinderGeometry(35, 35, 128, 48, 1, true),
      new THREE.MeshBasicMaterial({
        color: 0xff5e70,
        transparent: true,
        opacity: 0.17,
        side: THREE.DoubleSide,
        depthWrite: false,
        toneMapped: false,
      }),
    );
    zoneWall.position.y = 64;
    const zoneRing = new THREE.Mesh(
      new THREE.RingGeometry(34, 36.5, 64),
      new THREE.MeshBasicMaterial({
        color: 0xff6b7a,
        transparent: true,
        opacity: 0.78,
        side: THREE.DoubleSide,
        toneMapped: false,
      }),
    );
    zoneRing.rotation.x = -Math.PI / 2;
    zoneRing.position.y = 1.6;
    constraintZone.add(zoneWall, zoneRing);
    constraintZone.position.set(162, 0, -64);
    constraintZone.visible = false;
    reviewOverlay.add(constraintZone);

    // Pulsing diversion beacon ring active during phase >= 4
    const diversionPulseMat = new THREE.MeshBasicMaterial({
      color: 0xffc779,
      transparent: true,
      opacity: 0.58,
      side: THREE.DoubleSide,
      depthWrite: false,
      toneMapped: false,
    });
    const diversionPulse = new THREE.Mesh(
      new THREE.RingGeometry(15, 17.5, 48),
      diversionPulseMat,
    );
    diversionPulse.rotation.x = -Math.PI / 2;
    diversionPulse.position.set(points[3].x, 1.3, points[3].z);
    diversionPulse.visible = false;
    reviewOverlay.add(diversionPulse);

    const marker = (p: THREE.Vector3, color: number) => {
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(12.5, 15.2, 48),
        new THREE.MeshBasicMaterial({
          color,
          side: THREE.DoubleSide,
          toneMapped: false,
        }),
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.set(p.x, 1.0, p.z);
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
    const cityRotors: { node: THREE.Object3D; dir: number }[] = [];
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
        const scale = 24 / Math.max(size.x, size.y, size.z, 0.001);
        gltf.scene.scale.setScalar(scale);
        gltf.scene.position.copy(center.multiplyScalar(-scale));
        gltf.scene.traverse((child) => {
          if (/^PWR_PROP-(FL|FR|RL|RR)$/.test(child.name)) {
            cityRotors.push({
              node: child,
              dir:
                child.name.endsWith("FL") || child.name.endsWith("RR") ? 1 : -1,
            });
          }
        });
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
        setHeroParts(studio.getPartCount());
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
    // 10x Greater Shenzhen Bay aerial shots (Qianhai ↔ Houhai ↔ Futian ↔ Luohu horizon).
    const shots = [
      { time: 0, angle: -0.14, height: 390, distance: 760 },
      { time: 32, angle: 0.06, height: 350, distance: 710 },
      { time: 52, angle: 0.2, height: 330, distance: 690 },
      { time: 95, angle: 0.08, height: 325, distance: 680 },
      { time: 118, angle: -0.04, height: 345, distance: 700 },
      { time: 142, angle: -0.18, height: 375, distance: 740 },
      { time: 180, angle: -0.18, height: 375, distance: 740 },
    ];
    let renderedView: VisualView | null = null;
    let renderedAngle: StudioAngle | null = null;
    let renderedExplode: StudioExplode | null = null;
    let renderedTime = -1;
    const lookTarget = new THREE.Vector3();
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
      reviewOverlay.visible = activeView === "city";

      const isFallbackLeg = state.time >= 118;
      const legCurve = isFallbackLeg ? ending : opening;
      const legT = isFallbackLeg
        ? THREE.MathUtils.clamp((state.time - 118) / 24, 0, 1)
        : THREE.MathUtils.clamp((state.time - 95) / 23, 0, 1);
      const pos = legCurve.getPoint(legT);
      const tangent = legCurve.getTangent(legT);
      aircraft.position.copy(pos);
      if (state.phase === 3 || state.phase === 4) {
        lookTarget.copy(pos).add(tangent);
        aircraft.lookAt(lookTarget);
        // Subtle aerodynamic pitch and diversion turn bank
        aircraft.rotateX(0.08);
        if (isFallbackLeg) {
          const bank = Math.sin(legT * Math.PI) * 0.22;
          aircraft.rotateZ(-bank);
        }
        for (let i = 0; i < cityRotors.length; i++) {
          cityRotors[i].node.rotation.y = time * 18 * cityRotors[i].dir;
        }
      } else {
        aircraft.rotation.set(0, Math.PI * 0.25, 0);
      }

      // Show illustrative risk/constraint zone during Safety Concept & Fallback phases
      constraintZone.visible = state.phase === 2 || state.phase >= 4;
      if (constraintZone.visible) {
        const pulse = 1 + Math.sin(time * 2.4) * 0.03;
        zoneRing.scale.setScalar(pulse);
      }

      // Show pulsing amber landing beacon when diversion is active
      diversionPulse.visible = state.phase >= 4;
      if (diversionPulse.visible) {
        const wave = (time * 0.85) % 1;
        diversionPulse.scale.setScalar(1 + wave * 0.95);
        diversionPulseMat.opacity = (1 - wave) * 0.65;
      }

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
        // Dramatic architectural shot framing full Ping An Finance Centre + Civic Center + Futian & Luohu skyline.
        const nudge = THREE.MathUtils.smoothstep(state.time, 32, 52);
        camera.position.set(
          (345 - 48 * nudge) * fit,
          172 * fit,
          (188 - 28 * nudge) * fit,
        );
        camera.lookAt(175, 88, -96);
      } else {
        camera.position.set(
          10 + distance * Math.sin(angle),
          THREE.MathUtils.lerp(before.height, after.height, mix) * fit,
          28 + distance * Math.cos(angle),
        );
        camera.lookAt(12, 56, -54);
      }
      camera.updateMatrixWorld();
      alternate.visible = state.phase >= 4;
      labels.forEach(({ point }, idx) => {
        const element = labelElements.current[idx];
        if (!element) return;
        const projected = point
          .clone()
          .add(new THREE.Vector3(0, 12, 0))
          .project(camera);
        element.style.left = `${(projected.x + 1) * 50}%`;
        element.style.top = `${(1 - projected.y) * 50}%`;
      });
      renderer.render(scene, camera);
      renderer.domElement.setAttribute(
        "aria-label",
        activeView === "detail" ? "深圳湾地标建筑近景" : "深圳湾城市级三维景观",
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

  const veilOpacity = transitionVeilOpacity(frame.time, playing);

  return (
    <div
      className="demo-scene"
      ref={host}
      data-model={modelState}
      data-hero-model={heroState}
      data-explode-parts={heroParts}
      data-view={view}
      data-studio-angle={studioAngle}
      data-studio-explode={studioExplode}
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
      {veilOpacity > 0.01 && (
        <div
          className="demo-transition-veil"
          style={{ opacity: veilOpacity }}
          aria-hidden="true"
        />
      )}
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
