import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import decoderWasm from "three/examples/jsm/libs/draco/gltf/draco_decoder.wasm?url";
import decoderWrapper from "three/examples/jsm/libs/draco/gltf/draco_wasm_wrapper.js?url";
import decoderScript from "three/examples/jsm/libs/draco/gltf/draco_decoder.js?url";
import modelUrl from "../../../references/rea-city-flight/asset/out/cr30_lod1.glb?url";
import { createEnvironment } from "./demo/Studio";
import {
  DRONE_CYCLE_PERIOD,
  SUBSYSTEM_SPOTLIGHTS,
  evaluateDroneCycle,
  smootherstep,
} from "./drone-explode-cycle";
import "./drone-explode-backdrop.css";

const STORAGE_KEY = "aeris-drone-bg-enabled";

type ExplodeRecord = {
  node: THREE.Object3D;
  system: string;
  origin: THREE.Vector3;
  baseScale: THREE.Vector3;
  offset: THREE.Vector3;
  stagger: number;
};

type RotorRecord = {
  node: THREE.Object3D;
  dir: number;
};

type SystemMaterialEntry = {
  material: THREE.MeshStandardMaterial;
  baseEmissive: THREE.Color;
  baseEmissiveIntensity: number;
};

declare global {
  interface Window {
    __aerisDesktopDrone3d?: {
      setTime: (sec: number) => void;
      setPaused: (paused: boolean) => void;
      setEnabled: (enabled: boolean) => void;
      getState: () => {
        enabled: boolean;
        paused: boolean;
        loaded: boolean;
        partCount: number;
        cycleTime: number;
        phase: string;
        activeSubsystem: string | null;
        zoomPercent: number;
      };
    };
  }
}

function readInitialEnabled(): boolean {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "0" || saved === "false") return false;
  } catch {
    // Ignore storage restriction
  }
  return true;
}

function isDarkSurface(): boolean {
  if (typeof document === "undefined") return false;
  return (
    document.documentElement.dataset.theme === "dark" ||
    window.location.pathname === "/demo"
  );
}

export default function DroneExplodeBackdrop() {
  const stageRef = useRef<HTMLDivElement>(null);
  const [enabled, setEnabled] = useState<boolean>(readInitialEnabled);
  const [paused, setPaused] = useState<boolean>(false);
  const [loaded, setLoaded] = useState<boolean>(false);
  const [hud, setHud] = useState<{
    label: string;
    phase: string;
    zoomPercent: number;
    accent: string;
  }>({
    label: "CR30 3D 爆炸视图加载中",
    phase: "assembled",
    zoomPercent: 100,
    accent: "#35d4f5",
  });

  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const isDemoRoute =
    typeof window !== "undefined" && window.location.pathname === "/demo";

  useEffect(() => {
    document.documentElement.dataset.droneBg = enabled ? "on" : "off";
    try {
      window.localStorage.setItem(STORAGE_KEY, enabled ? "1" : "0");
    } catch {
      // Ignore storage restriction
    }
    return () => {
      delete document.documentElement.dataset.droneBg;
    };
  }, [enabled]);

  useEffect(() => {
    if (!enabled) {
      setLoaded(false);
      return;
    }
    const host = stageRef.current;
    if (!host) return;
    let teardown: (() => void) | undefined;
    const boot = () => {
      let renderer: THREE.WebGLRenderer;
      try {
        renderer = new THREE.WebGLRenderer({
          alpha: true,
          antialias: true,
          powerPreference: "high-performance",
        });
      } catch {
        setHud((h) => ({ ...h, label: "WebGL 不可用" }));
        return;
      }

      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
      renderer.setClearColor(0x000000, 0);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.14;
      renderer.domElement.style.pointerEvents = "none";
      renderer.domElement.setAttribute("aria-hidden", "true");
      host.appendChild(renderer.domElement);

      const environment = createEnvironment(renderer);
      const scene = new THREE.Scene();
      scene.environment = environment.texture;
      scene.environmentIntensity = 1.15;

      const camera = new THREE.PerspectiveCamera(37, 1, 0.05, 100);
      camera.position.set(0, 1.55, 4.55);

      const hemi = new THREE.HemisphereLight(0xe5f4ff, 0x26384d, 1.45);
      const keyLight = new THREE.DirectionalLight(0xffffff, 3.35);
      keyLight.position.set(3.8, 7.2, 5.6);
      const rimLight = new THREE.DirectionalLight(0x4bc5ff, 3.1);
      rimLight.position.set(-5.6, 3.4, -4.6);
      const warmFill = new THREE.DirectionalLight(0xffcb74, 1.25);
      warmFill.position.set(2.8, -2.2, -3.4);
      scene.add(hemi, keyLight, rimLight, warmFill);

      const dronePivot = new THREE.Group();
      scene.add(dronePivot);

      // Subtle aerospace calibration floor rings & grid
      const floor = new THREE.Group();
      floor.position.y = -1.48;
      scene.add(floor);

      const ringMat = new THREE.MeshBasicMaterial({
        color: 0x3596d4,
        transparent: true,
        opacity: 0.22,
        side: THREE.DoubleSide,
        depthWrite: false,
      });
      for (const r of [1.85, 2.55, 3.25]) {
        const ring = new THREE.Mesh(
          new THREE.RingGeometry(r, r + 0.015, 96),
          ringMat,
        );
        ring.rotation.x = -Math.PI / 2;
        floor.add(ring);
      }
      const grid = new THREE.GridHelper(7.4, 24, 0x3a8fc4, 0x24557a);
      const gridMats = Array.isArray(grid.material)
        ? grid.material
        : [grid.material];
      for (const gm of gridMats) {
        gm.transparent = true;
        gm.opacity = 0.14;
      }
      floor.add(grid);

      const scanMat = new THREE.MeshBasicMaterial({
        color: 0x38d6e8,
        transparent: true,
        opacity: 0.06,
        side: THREE.DoubleSide,
        depthWrite: false,
      });
      const scanPlane = new THREE.Mesh(
        new THREE.CircleGeometry(2.7, 72),
        scanMat,
      );
      scanPlane.rotation.x = -Math.PI / 2;
      scene.add(scanPlane);

      const particleCount = 72;
      const posArr = new Float32Array(particleCount * 3);
      for (let i = 0; i < particleCount; i++) {
        const angle = i * 2.39996;
        const radius = 1.7 + ((i * 19) % 26) / 10;
        posArr[i * 3] = Math.cos(angle) * radius;
        posArr[i * 3 + 1] = ((i * 13) % 30) / 10 - 1.45;
        posArr[i * 3 + 2] = Math.sin(angle) * radius;
      }
      const particleMat = new THREE.PointsMaterial({
        color: 0x4ca9e6,
        size: 0.026,
        transparent: true,
        opacity: 0.48,
        depthWrite: false,
      });
      const particles = new THREE.Points(
        new THREE.BufferGeometry().setAttribute(
          "position",
          new THREE.BufferAttribute(posArr, 3),
        ),
        particleMat,
      );
      scene.add(particles);

      const syncLightingToTheme = () => {
        const dark = isDarkSurface();
        scene.environmentIntensity = dark ? 1.15 : 1.05;
        hemi.intensity = dark ? 1.45 : 1.75;
        keyLight.intensity = dark ? 3.35 : 3.1;
        rimLight.color.setHex(dark ? 0x52c8ff : 0x2574cc);
        rimLight.intensity = dark ? 3.1 : 2.6;
        ringMat.color.setHex(dark ? 0x6cd4ff : 0x2270c2);
        ringMat.opacity = dark ? 0.24 : 0.2;
        scanMat.color.setHex(dark ? 0x5ef0dc : 0x2584d8);
        scanMat.opacity = dark ? 0.065 : 0.055;
        particleMat.color.setHex(dark ? 0x8be4ff : 0x2b7acc);
        particleMat.opacity = dark ? 0.5 : 0.42;
        for (const gm of gridMats) {
          gm.opacity = dark ? 0.14 : 0.12;
        }
      };
      syncLightingToTheme();

      const themeObserver = new MutationObserver(syncLightingToTheme);
      themeObserver.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-theme"],
      });

      const explodeParts: ExplodeRecord[] = [];
      const propNodes: RotorRecord[] = [];
      const systemMaterials = new Map<string, SystemMaterialEntry[]>();
      let modelLoaded = false;

      const decoderAssets: Record<string, string> = {
        "draco_decoder.wasm": decoderWasm,
        "draco_wasm_wrapper.js": decoderWrapper,
        "draco_decoder.js": decoderScript,
      };
      const manager = new THREE.LoadingManager();
      manager.setURLModifier((url) => decoderAssets[url] ?? url);
      const draco = new DRACOLoader(manager);
      const loader = new GLTFLoader(manager).setDRACOLoader(draco);

      let disposed = false;
      loader.load(
        modelUrl,
        (gltf) => {
          if (disposed) return;
          const root = gltf.scene;
          root.updateWorldMatrix(true, true);
          const box = new THREE.Box3().setFromObject(root);
          const size = box.getSize(new THREE.Vector3());
          const center = box.getCenter(new THREE.Vector3());
          const maxDim = Math.max(size.x, size.y, size.z, 0.001);
          const targetScale = 2.65 / maxDim;
          root.scale.setScalar(targetScale);
          root.position.sub(center.multiplyScalar(targetScale));

          // Track cloned materials per (system + original material uuid) so spotlight emissive stays crisp & lightweight
          const clonedCache = new Map<string, THREE.MeshStandardMaterial>();
          const registerSystemMaterial = (
            sys: string,
            mat: THREE.MeshStandardMaterial,
          ) => {
            const key = `${sys}:${mat.uuid}`;
            const existing = clonedCache.get(key);
            if (existing) return existing;
            const cloned = mat.clone();
            if (cloned.metalness > 0.9 && cloned.emissiveIntensity > 1) {
              cloned.emissiveIntensity = 0.08;
            }
            clonedCache.set(key, cloned);
            const bucket = systemMaterials.get(sys) ?? [];
            bucket.push({
              material: cloned,
              baseEmissive: cloned.emissive.clone(),
              baseEmissiveIntensity: cloned.emissiveIntensity,
            });
            systemMaterials.set(sys, bucket);
            return cloned;
          };

          // Inherit nearest ancestor system tag for child meshes
          const resolveSystem = (obj: THREE.Object3D): string => {
            let cur: THREE.Object3D | null = obj;
            while (cur) {
              const sys = (cur.userData as { system?: unknown } | undefined)
                ?.system;
              if (typeof sys === "string" && sys.length > 0) return sys;
              cur = cur.parent;
            }
            return "STD";
          };

          root.traverse((node) => {
            const sys = resolveSystem(node);
            if (node instanceof THREE.Mesh && node.material) {
              if (Array.isArray(node.material)) {
                node.material = node.material.map((m) =>
                  m instanceof THREE.MeshStandardMaterial
                    ? registerSystemMaterial(sys, m)
                    : m,
                );
              } else if (node.material instanceof THREE.MeshStandardMaterial) {
                node.material = registerSystemMaterial(sys, node.material);
              }
            }

            if (/^PWR_PROP-(FL|FR|RL|RR)$/.test(node.name)) {
              propNodes.push({
                node,
                dir:
                  node.name.endsWith("FL") || node.name.endsWith("RR") ? 1 : -1,
              });
            }

            const ud = node.userData as {
              system?: unknown;
              explodeDir?: unknown;
              explodeDist?: unknown;
              stagger?: unknown;
            };
            if (
              typeof ud.system === "string" &&
              Array.isArray(ud.explodeDir) &&
              ud.explodeDir.length === 3 &&
              typeof ud.explodeDist === "number"
            ) {
              explodeParts.push({
                node,
                system: ud.system,
                origin: node.position.clone(),
                baseScale: node.scale.clone(),
                offset: new THREE.Vector3(
                  Number(ud.explodeDir[0]),
                  Number(ud.explodeDir[1]),
                  Number(ud.explodeDir[2]),
                ).multiplyScalar(ud.explodeDist * 0.56),
                stagger: Number(ud.stagger) || 0,
              });
            }
          });

          dronePivot.add(root);
          modelLoaded = true;
          host.dataset.droneBackdrop = "loaded";
          host.dataset.droneParts = String(explodeParts.length);
          setLoaded(true);
        },
        undefined,
        () => {
          if (!disposed) {
            host.dataset.droneBackdrop = "error";
          }
        },
      );

      const resize = () => {
        const w = Math.max(1, window.innerWidth);
        const h = Math.max(1, window.innerHeight);
        renderer.setSize(w, h, false);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      };
      resize();
      window.addEventListener("resize", resize);

      // Start smoothly near the exploding showcase so visitors immediately witness the dynamic exploded animation
      let elapsed = 4.2;
      let lastNow = performance.now();
      let raf = 0;
      let smoothDist = 4.9;
      const smoothLookAt = new THREE.Vector3(0, -0.05, 0);
      const targetLookAt = new THREE.Vector3(0, -0.05, 0);
      const centroidSum = new THREE.Vector3();
      const worldPos = new THREE.Vector3();
      const accentColor = new THREE.Color();
      let lastHudUpdate = 0;
      let lastState = evaluateDroneCycle(elapsed);

      const reducedMotion =
        typeof window.matchMedia === "function" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;

      const applyFrame = (dt: number, snapCamera: boolean) => {
        const state = evaluateDroneCycle(elapsed);
        lastState = state;

        // Smooth continuous turntable rotation + gentle float
        const rotSpeed = reducedMotion ? 0.08 : 0.24;
        dronePivot.rotation.y = elapsed * rotSpeed + 0.45;
        dronePivot.rotation.x = Math.sin(elapsed * 0.48) * 0.065 + 0.1;
        dronePivot.rotation.z = Math.cos(elapsed * 0.36) * 0.04;
        dronePivot.position.y = Math.sin(elapsed * 0.85) * 0.07;

        floor.rotation.y = -elapsed * 0.07;
        particles.rotation.y = elapsed * 0.035;
        scanPlane.position.y =
          -1.15 + (Math.sin(elapsed * 0.72) + 1) * 0.5 * 2.3;

        if (modelLoaded) {
          const master = state.masterExplode;
          for (let i = 0; i < explodeParts.length; i++) {
            const p = explodeParts[i];
            const delay = Math.min(0.42, p.stagger * 0.38);
            const local = Math.max(
              0,
              Math.min(1, (master - delay) / Math.max(0.18, 1 - delay)),
            );
            const eased =
              smootherstep(local) + state.partExtraExplodeFor(p.system);
            p.node.position.copy(p.origin).addScaledVector(p.offset, eased);

            const scaleFactor = state.partScaleFor(p.system);
            p.node.scale.copy(p.baseScale).multiplyScalar(scaleFactor);
          }

          // Spin propellers smoothly
          const spin = reducedMotion ? 1.2 : 4.2;
          for (let i = 0; i < propNodes.length; i++) {
            propNodes[i].node.rotation.y = elapsed * spin * propNodes[i].dir;
          }

          // Smooth emissive highlight per active subsystem
          const activeColorHex = state.activeSpotlight?.accent ?? "#35d4f5";
          accentColor.set(activeColorHex);
          systemMaterials.forEach((entries, sys) => {
            const w = state.emissiveWeightFor(sys);
            for (let i = 0; i < entries.length; i++) {
              const e = entries[i];
              if (w > 0.002) {
                e.material.emissive
                  .copy(e.baseEmissive)
                  .lerp(accentColor, w * 0.85);
                e.material.emissiveIntensity =
                  e.baseEmissiveIntensity + w * 0.62;
              } else {
                e.material.emissive.copy(e.baseEmissive);
                e.material.emissiveIntensity = e.baseEmissiveIntensity;
              }
            }
          });

          // Compute live rotated world centroid of the currently spotlighted subsystem for silky camera zoom-in
          if (state.activeSpotlight && state.focusWeight > 0.002) {
            dronePivot.updateWorldMatrix(true, true);
            centroidSum.set(0, 0, 0);
            let count = 0;
            const activeSystems = state.activeSpotlight.systems;
            for (let i = 0; i < explodeParts.length; i++) {
              const p = explodeParts[i];
              if (activeSystems.includes(p.system)) {
                p.node.getWorldPosition(worldPos);
                centroidSum.add(worldPos);
                count++;
              }
            }
            if (count > 0) {
              centroidSum.divideScalar(count);
              targetLookAt
                .set(0, -0.05, 0)
                .lerp(centroidSum, state.focusWeight * 0.52);
            } else {
              targetLookAt.set(0, -0.05, 0);
            }
          } else {
            targetLookAt.set(0, -0.05, 0);
          }
        }

        // Exponentially damped silky zoom-in / zoom-out camera glide (zero abrupt cuts)
        const aspect = Math.max(0.5, camera.aspect);
        const viewportBoost = aspect < 0.85 ? 1.38 : aspect < 1.15 ? 1.16 : 1.0;
        const desiredDist = state.targetCameraDist * viewportBoost;
        const damp = snapCamera ? 1 : 1 - Math.exp(-Math.max(0.001, dt) * 4.2);
        smoothDist += (desiredDist - smoothDist) * damp;
        smoothLookAt.lerp(targetLookAt, damp);

        camera.position.set(
          smoothLookAt.x * 0.35 + Math.sin(elapsed * 0.22) * 0.28,
          smoothLookAt.y * 0.45 + smoothDist * 0.31,
          smoothDist,
        );
        camera.lookAt(smoothLookAt);

        renderer.render(scene, camera);

        const nowMs = performance.now();
        if (snapCamera || nowMs - lastHudUpdate > 140) {
          lastHudUpdate = nowMs;
          setHud({
            label: state.statusLabel,
            phase: state.phase,
            zoomPercent: state.zoomPercent,
            accent: state.activeSpotlight?.accent ?? "#35d4f5",
          });
        }
      };

      window.__aerisDesktopDrone3d = {
        setTime(sec: number) {
          if (Number.isFinite(sec)) {
            elapsed =
              ((sec % DRONE_CYCLE_PERIOD) + DRONE_CYCLE_PERIOD) %
              DRONE_CYCLE_PERIOD;
            applyFrame(0.016, true);
          }
        },
        setPaused(flag: boolean) {
          setPaused(Boolean(flag));
        },
        setEnabled(flag: boolean) {
          setEnabled(Boolean(flag));
        },
        getState() {
          return {
            enabled: enabledRef.current,
            paused: pausedRef.current,
            loaded: modelLoaded,
            partCount: explodeParts.length,
            cycleTime: Number(lastState.cycleTime.toFixed(2)),
            phase: lastState.phase,
            activeSubsystem: lastState.activeSpotlight?.id ?? null,
            zoomPercent: lastState.zoomPercent,
          };
        },
      };

      const tick = (now: number) => {
        raf = requestAnimationFrame(tick);
        const dt = Math.min(0.05, Math.max(0, (now - lastNow) / 1000));
        lastNow = now;
        if (document.hidden || pausedRef.current) return;
        elapsed += dt * (reducedMotion ? 0.35 : 1);
        applyFrame(dt, false);
      };
      raf = requestAnimationFrame(tick);

      teardown = () => {
        disposed = true;
        cancelAnimationFrame(raf);
        window.removeEventListener("resize", resize);
        themeObserver.disconnect();
        delete window.__aerisDesktopDrone3d;
        environment.dispose();
        draco.dispose();
        systemMaterials.forEach((entries) => {
          for (const e of entries) e.material.dispose();
        });
        renderer.dispose();
        renderer.domElement.remove();
      };
    };
    const bootRaf = requestAnimationFrame(boot);
    return () => {
      cancelAnimationFrame(bootRaf);
      teardown?.();
    };
  }, [enabled]);

  return (
    <>
      {enabled && (
        <div
          className="drone-bg-layer"
          ref={stageRef}
          aria-hidden="true"
          data-drone-backdrop={loaded ? "loaded" : "loading"}
          data-subsystems={SUBSYSTEM_SPOTLIGHTS.length}
        />
      )}
      <div
        className={`drone-bg-pill ${isDemoRoute ? "is-demo-route" : ""} ${enabled ? "is-on" : "is-off"}`}
        role="region"
        aria-label="CR30 3D 爆炸视图背景控制"
      >
        <span
          className="drone-bg-dot"
          style={{
            background: enabled ? hud.accent : "#7e94a8",
            boxShadow: enabled ? `0 0 10px ${hud.accent}` : "none",
          }}
        />
        <span className="drone-bg-text">
          {enabled
            ? `CR30 爆炸背景 · ${hud.label}${hud.zoomPercent > 102 ? ` ${hud.zoomPercent}%` : ""}`
            : "CR30 3D 背景已关闭"}
        </span>
        {enabled && (
          <button
            type="button"
            className="drone-bg-btn"
            aria-pressed={paused}
            title={paused ? "继续 3D 爆炸循环动画" : "暂停 3D 爆炸循环动画"}
            onClick={() => setPaused((p) => !p)}
          >
            {paused ? "继续背景" : "暂停背景"}
          </button>
        )}
        <button
          type="button"
          className="drone-bg-btn"
          aria-pressed={enabled}
          title={
            enabled ? "隐藏页面后景 3D 爆炸模型" : "开启页面后景 3D 爆炸模型"
          }
          onClick={() => setEnabled((v) => !v)}
        >
          {enabled ? "关闭背景" : "开启 3D 背景"}
        </button>
      </div>
    </>
  );
}
