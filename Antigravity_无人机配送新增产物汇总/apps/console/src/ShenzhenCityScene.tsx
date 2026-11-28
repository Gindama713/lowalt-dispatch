import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import decoderWasm from "three/examples/jsm/libs/draco/gltf/draco_decoder.wasm?url";
import decoderWrapper from "three/examples/jsm/libs/draco/gltf/draco_wasm_wrapper.js?url";
import decoderScript from "three/examples/jsm/libs/draco/gltf/draco_decoder.js?url";
import modelUrl from "../../../references/rea-city-flight/asset/out/cr30_lod1.glb?url";
import { createCity } from "./demo/City";
import { createEnvironment, makeBackdrop } from "./demo/Studio";
import { createWater } from "./demo/Water";
import { landmarks } from "./demo/city-layout";
import type { MapHandle } from "./MapScene";
import type {
  Layers,
  Point,
  TerrainChange,
  TerrainPatch,
  ViewMode,
} from "./types";
import "./shenzhen-city.css";

type PresetId = "panorama" | "qianhai" | "houhai" | "futian" | "luohu";

const DISTRICT_PRESETS: Record<
  PresetId,
  {
    label: string;
    pos: [number, number, number];
    target: [number, number, number];
  }
> = {
  panorama: {
    label: "深圳湾全景",
    pos: [20, 390, 740],
    target: [12, 48, -60],
  },
  qianhai: {
    label: "前海·摩天轮",
    pos: [-580, 175, 360],
    target: [-585, 58, 12],
  },
  houhai: {
    label: "后海·春笋",
    pos: [-240, 160, 290],
    target: [-165, 56, -8],
  },
  futian: {
    label: "福田·平安",
    pos: [355, 212, 295],
    target: [185, 72, -88],
  },
  luohu: {
    label: "罗湖·京基100",
    pos: [690, 195, 240],
    target: [590, 76, -65],
  },
};

const ROUTE_POINTS = [
  new THREE.Vector3(landmarks[0].x, 4, landmarks[0].z),
  new THREE.Vector3(-82, 86, 16),
  new THREE.Vector3(42, 92, -20),
  new THREE.Vector3(landmarks[1].x, 4, landmarks[1].z),
];
const DESTINATION = new THREE.Vector3(landmarks[2].x, 4, landmarks[2].z);
const PRIMARY_CURVE = new THREE.CatmullRomCurve3(ROUTE_POINTS.slice(0, 3));
const DIVERSION_CURVE = new THREE.CatmullRomCurve3([
  ROUTE_POINTS[2],
  new THREE.Vector3(74, 64, 22),
  ROUTE_POINTS[3],
]);
const RISK_CORRIDOR = new THREE.CatmullRomCurve3([
  ROUTE_POINTS[2],
  new THREE.Vector3(165, 96, -64),
  DESTINATION,
]);

const LANDMARK_PINS = [
  {
    pos: new THREE.Vector3(-680, 108, 96),
    name: "湾区之光摩天轮",
    kind: "landmark",
  },
  {
    pos: new THREE.Vector3(-540, 152, -38),
    name: "前海双子塔",
    kind: "landmark",
  },
  {
    pos: new THREE.Vector3(-278, 104, -46),
    name: "腾讯滨海大厦",
    kind: "landmark",
  },
  { pos: new THREE.Vector3(-132, 136, 30), name: "华润春笋", kind: "landmark" },
  {
    pos: new THREE.Vector3(185, 204, -78),
    name: "平安金融中心",
    kind: "landmark",
  },
  { pos: new THREE.Vector3(565, 162, -84), name: "京基 100", kind: "landmark" },
  {
    pos: ROUTE_POINTS[0].clone().add(new THREE.Vector3(0, 16, 0)),
    name: "南山物资中心",
    kind: "pad",
  },
  {
    pos: ROUTE_POINTS[3].clone().add(new THREE.Vector3(0, 16, 0)),
    name: "深圳湾备降坪",
    kind: "diversion",
  },
  {
    pos: DESTINATION.clone().add(new THREE.Vector3(0, 16, 0)),
    name: "福田应急医院",
    kind: "pad",
  },
] as const;

export type ShenzhenCitySceneProps = {
  variant?: "workspace" | "hero";
  mode?: ViewMode;
  layers?: Layers;
  progress?: number;
  playing?: boolean;
  onReady?: () => void;
  onError?: (message: string) => void;
  onApplyTerrain?: (patch: TerrainPatch) => TerrainChange;
};

export default forwardRef<MapHandle, ShenzhenCitySceneProps>(
  function ShenzhenCityScene(props, ref) {
    const variant = props.variant ?? "workspace";
    const host = useRef<HTMLDivElement>(null);
    const labelRefs = useRef<(HTMLSpanElement | null)[]>([]);
    const [activePreset, setActivePreset] = useState<PresetId>("panorama");
    const [stats, setStats] = useState({ buildings: 0, details: 0 });
    const [unavailable, setUnavailable] = useState(false);

    const liveProps = useRef(props);
    liveProps.current = props;

    const runtime = useRef<{
      camera: THREE.PerspectiveCamera;
      controls: OrbitControls;
      flyToPreset: (preset: PresetId) => void;
      zoom: (factor: number) => void;
      setMode: (mode: ViewMode) => void;
    } | null>(null);

    useImperativeHandle(ref, () => ({
      reset: () => {
        setActivePreset("panorama");
        runtime.current?.flyToPreset("panorama");
      },
      zoom: (factor: number) => runtime.current?.zoom(factor),
      focus: (_point: Point) => runtime.current?.flyToPreset("futian"),
      applyTerrain: (patch: TerrainPatch) => {
        if (liveProps.current.onApplyTerrain) {
          return liveProps.current.onApplyTerrain(patch);
        }
        throw new Error("深圳三维视图不应用局部地形补丁");
      },
    }));

    useEffect(() => {
      if (props.mode) {
        runtime.current?.setMode(props.mode);
      }
    }, [props.mode]);

    useEffect(() => {
      const node = host.current;
      if (!node) return;
      let teardown: (() => void) | undefined;
      const boot = () => {
        let renderer: THREE.WebGLRenderer;
        try {
          renderer = new THREE.WebGLRenderer({
            antialias: true,
            alpha: false,
            powerPreference: "high-performance",
          });
        } catch {
          setUnavailable(true);
          liveProps.current.onError?.(
            "当前浏览器未启用 WebGL，无法渲染深圳三维城市。",
          );
          return;
        }

        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.6));
        renderer.setClearColor("#07101a");
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 1.1;
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        renderer.shadowMap.autoUpdate = false;
        node.appendChild(renderer.domElement);
        renderer.domElement.setAttribute(
          "aria-label",
          "可交互的 10 倍规模深圳湾城市级三维景观（拖动旋转，滚轮缩放）",
        );
        renderer.domElement.setAttribute("role", "img");

        const environment = createEnvironment(renderer);
        const scene = new THREE.Scene();
        scene.background = makeBackdrop("#2d586e", "#0c1c2c");
        scene.environment = environment.texture;
        scene.environmentIntensity = 0.6;
        scene.fog = new THREE.Fog("#102434", 1200, 3600);

        scene.add(new THREE.HemisphereLight(0xc6e5fa, 0x24343c, 1.35));
        const sun = new THREE.DirectionalLight(0xffd6a5, 3.4);
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
        scene.add(sun, sun.target);

        const rim = new THREE.DirectionalLight(0x7ccbf5, 1.65);
        rim.position.set(520, 260, -440);
        scene.add(rim);

        const camera = new THREE.PerspectiveCamera(42, 1, 2, 5400);
        const initialPreset =
          variant === "hero"
            ? {
                pos: [-30, 320, 620] as [number, number, number],
                target: [20, 56, -50] as [number, number, number],
              }
            : DISTRICT_PRESETS.panorama;
        camera.position.set(
          initialPreset.pos[0],
          initialPreset.pos[1],
          initialPreset.pos[2],
        );

        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.065;
        controls.minDistance = 95;
        controls.maxDistance = 2150;
        controls.maxPolarAngle = Math.PI / 2.08;
        controls.target.set(
          initialPreset.target[0],
          initialPreset.target[1],
          initialPreset.target[2],
        );
        controls.autoRotate = variant === "hero";
        controls.autoRotateSpeed = 0.32;
        controls.update();

        const pauseAutoRotate = () => {
          controls.autoRotate = false;
        };
        controls.addEventListener("start", pauseAutoRotate);

        const city = createCity();
        scene.add(city);
        const water = createWater();
        scene.add(water);
        renderer.shadowMap.needsUpdate = true;

        const buildingCount = Number(city.userData.buildingCount ?? 0);
        const detailCount = Number(city.userData.detailCount ?? 0);
        node.dataset.city = String(city.userData.cityId ?? "shenzhen-bay-10x");
        node.dataset.buildings = String(buildingCount);
        node.dataset.details = String(detailCount);
        setStats({ buildings: buildingCount, details: detailCount });

        // Flight corridors, diversion safety tether & constraint volume
        const overlay = new THREE.Group();
        scene.add(overlay);

        const primaryTube = new THREE.Mesh(
          new THREE.TubeGeometry(PRIMARY_CURVE, 56, 1.55, 8, false),
          new THREE.MeshBasicMaterial({ color: 0x6ee8df, toneMapped: false }),
        );
        overlay.add(primaryTube);

        const diversionTube = new THREE.Mesh(
          new THREE.TubeGeometry(DIVERSION_CURVE, 48, 1.65, 8, false),
          new THREE.MeshBasicMaterial({ color: 0xffc779, toneMapped: false }),
        );
        overlay.add(diversionTube);

        const riskLine = new THREE.Line(
          new THREE.BufferGeometry().setFromPoints(RISK_CORRIDOR.getPoints(48)),
          new THREE.LineDashedMaterial({
            color: 0xff7c8a,
            dashSize: 8,
            gapSize: 5,
          }),
        );
        riskLine.computeLineDistances();
        overlay.add(riskLine);

        // Dynamic safety tether line from flying CR30 to Shenzhen Bay diversion pad
        const tetherGeo = new THREE.BufferGeometry().setFromPoints([
          ROUTE_POINTS[0].clone(),
          ROUTE_POINTS[3].clone(),
        ]);
        const tetherLine = new THREE.Line(
          tetherGeo,
          new THREE.LineDashedMaterial({
            color: 0xffd289,
            dashSize: 6,
            gapSize: 4,
            transparent: true,
            opacity: 0.8,
          }),
        );
        overlay.add(tetherLine);

        // Constraint cylinder over Futian high-density corridor
        const zoneGroup = new THREE.Group();
        const zoneWall = new THREE.Mesh(
          new THREE.CylinderGeometry(34, 34, 126, 48, 1, true),
          new THREE.MeshBasicMaterial({
            color: 0xff5e70,
            transparent: true,
            opacity: 0.14,
            side: THREE.DoubleSide,
            depthWrite: false,
            toneMapped: false,
          }),
        );
        zoneWall.position.y = 63;
        const zoneRing = new THREE.Mesh(
          new THREE.RingGeometry(33, 35.5, 64),
          new THREE.MeshBasicMaterial({
            color: 0xff6b7a,
            transparent: true,
            opacity: 0.72,
            side: THREE.DoubleSide,
            toneMapped: false,
          }),
        );
        zoneRing.rotation.x = -Math.PI / 2;
        zoneRing.position.y = 1.5;
        zoneGroup.add(zoneWall, zoneRing);
        zoneGroup.position.set(162, 0, -64);
        overlay.add(zoneGroup);

        // Pulsing diversion beacon
        const beaconMat = new THREE.MeshBasicMaterial({
          color: 0xffc779,
          transparent: true,
          opacity: 0.65,
          side: THREE.DoubleSide,
          depthWrite: false,
          toneMapped: false,
        });
        const beaconRing = new THREE.Mesh(
          new THREE.RingGeometry(15, 17.5, 48),
          beaconMat,
        );
        beaconRing.rotation.x = -Math.PI / 2;
        beaconRing.position.set(ROUTE_POINTS[3].x, 1.3, ROUTE_POINTS[3].z);
        overlay.add(beaconRing);

        // CR30 Aircraft
        const aircraft = new THREE.Group();
        const fallbackMesh = new THREE.Mesh(
          new THREE.OctahedronGeometry(5),
          new THREE.MeshStandardMaterial({ color: 0xe6f4fb, metalness: 0.7 }),
        );
        aircraft.add(fallbackMesh);
        overlay.add(aircraft);
        const rotors: { node: THREE.Object3D; dir: number }[] = [];

        const decoderAssets: Record<string, string> = {
          "draco_decoder.wasm": decoderWasm,
          "draco_wasm_wrapper.js": decoderWrapper,
          "draco_decoder.js": decoderScript,
        };
        const manager = new THREE.LoadingManager();
        manager.setURLModifier((url) => decoderAssets[url] ?? url);
        const decoder = new DRACOLoader(manager);
        const loader = new GLTFLoader(manager).setDRACOLoader(decoder);

        let disposed = false;
        loader.load(modelUrl, (gltf) => {
          if (disposed) return;
          const box = new THREE.Box3().setFromObject(gltf.scene);
          const size = box.getSize(new THREE.Vector3());
          const center = box.getCenter(new THREE.Vector3());
          const scale = 24 / Math.max(size.x, size.y, size.z, 0.001);
          gltf.scene.scale.setScalar(scale);
          gltf.scene.position.copy(center.multiplyScalar(-scale));
          gltf.scene.traverse((child) => {
            if (/^PWR_PROP-(FL|FR|RL|RR)$/.test(child.name)) {
              rotors.push({
                node: child,
                dir:
                  child.name.endsWith("FL") || child.name.endsWith("RR")
                    ? 1
                    : -1,
              });
            }
          });
          aircraft.remove(fallbackMesh);
          aircraft.add(gltf.scene);
          node.dataset.model = "loaded";
        });

        // Smooth camera preset glide state
        let glide: {
          fromPos: THREE.Vector3;
          toPos: THREE.Vector3;
          fromTarget: THREE.Vector3;
          toTarget: THREE.Vector3;
          t: number;
        } | null = null;

        const flyToPreset = (preset: PresetId) => {
          const spec = DISTRICT_PRESETS[preset];
          controls.autoRotate = false;
          glide = {
            fromPos: camera.position.clone(),
            toPos: new THREE.Vector3(...spec.pos),
            fromTarget: controls.target.clone(),
            toTarget: new THREE.Vector3(...spec.target),
            t: 0,
          };
        };

        runtime.current = {
          camera,
          controls,
          flyToPreset,
          zoom: (factor: number) => {
            camera.position
              .sub(controls.target)
              .multiplyScalar(factor)
              .clampLength(95, 2150)
              .add(controls.target);
            controls.update();
          },
          setMode: (mode: ViewMode) => {
            controls.autoRotate = false;
            glide = {
              fromPos: camera.position.clone(),
              toPos:
                mode === "2d"
                  ? new THREE.Vector3(12, 1520, 40)
                  : new THREE.Vector3(...DISTRICT_PRESETS.panorama.pos),
              fromTarget: controls.target.clone(),
              toTarget: new THREE.Vector3(12, 0, -90),
              t: 0,
            };
          },
        };

        const resize = () => {
          const width = Math.max(1, node.clientWidth);
          const height = Math.max(1, node.clientHeight);
          renderer.setSize(width, height);
          camera.aspect = width / height;
          camera.updateProjectionMatrix();
        };
        const observer = new ResizeObserver(resize);
        observer.observe(node);
        resize();
        liveProps.current.onReady?.();

        let raf = 0;
        let elapsed = 0;
        let prev = performance.now();
        const lookVec = new THREE.Vector3();

        const animate = (now: number) => {
          const dt = Math.min(0.05, Math.max(0, (now - prev) / 1000));
          prev = now;
          elapsed += dt;

          water.material.uniforms.uTime.value = elapsed;

          if (glide) {
            glide.t = Math.min(1, glide.t + dt * 1.35);
            const ease =
              glide.t < 0.5
                ? 4 * glide.t * glide.t * glide.t
                : 1 - Math.pow(-2 * glide.t + 2, 3) / 2;
            camera.position.lerpVectors(glide.fromPos, glide.toPos, ease);
            controls.target.lerpVectors(glide.fromTarget, glide.toTarget, ease);
            if (glide.t >= 1) glide = null;
          }
          controls.update();

          // Sync visibility with workspace layers when provided
          const layers = liveProps.current.layers;
          if (layers) {
            primaryTube.visible = layers.routes;
            diversionTube.visible = layers.routes;
            riskLine.visible = layers.routes;
            zoneGroup.visible = layers.restrictions;
            beaconRing.visible = layers.routes;
            tetherLine.visible = layers.routes;
          }

          // Smooth aircraft flight along primary + diversion loop (synced to workspace progress or gentle loop)
          const externalProgress = liveProps.current.progress;
          const loopP =
            typeof externalProgress === "number" && externalProgress > 0.001
              ? externalProgress
              : (elapsed * 0.045) % 1;
          const isDivert = loopP >= 0.55;
          const legT = isDivert ? (loopP - 0.55) / 0.45 : loopP / 0.55;
          const curve = isDivert ? DIVERSION_CURVE : PRIMARY_CURVE;
          const pos = curve.getPoint(THREE.MathUtils.clamp(legT, 0, 1));
          const tangent = curve.getTangent(THREE.MathUtils.clamp(legT, 0, 1));
          aircraft.position.copy(pos);
          lookVec.copy(pos).add(tangent);
          aircraft.lookAt(lookVec);
          aircraft.rotateX(0.08);
          if (isDivert) {
            aircraft.rotateZ(-Math.sin(legT * Math.PI) * 0.24);
          }
          for (let i = 0; i < rotors.length; i++) {
            rotors[i].node.rotation.y += dt * 18 * rotors[i].dir;
          }

          // Update live safety tether from CR30 to Shenzhen Bay diversion pad
          const tAttr = tetherGeo.getAttribute(
            "position",
          ) as THREE.BufferAttribute;
          tAttr.setXYZ(0, pos.x, pos.y, pos.z);
          tAttr.setXYZ(
            1,
            ROUTE_POINTS[3].x,
            ROUTE_POINTS[3].y + 2,
            ROUTE_POINTS[3].z,
          );
          tAttr.needsUpdate = true;
          tetherLine.computeLineDistances();

          // Pulse diversion landing beacon
          const wave = (elapsed * 0.8) % 1;
          beaconRing.scale.setScalar(1 + wave * 0.9);
          beaconMat.opacity = (1 - wave) * 0.65;

          // Project landmark labels
          const showLabels =
            variant === "workspace" || camera.position.length() < 1200;
          for (let i = 0; i < LANDMARK_PINS.length; i++) {
            const el = labelRefs.current[i];
            if (!el) continue;
            const pin = LANDMARK_PINS[i];
            if (variant === "hero" && pin.kind === "pad") {
              el.style.display = "none";
              continue;
            }
            const proj = pin.pos.clone().project(camera);
            const inFront = proj.z > -1 && proj.z < 1;
            const inBounds = Math.abs(proj.x) < 0.94 && Math.abs(proj.y) < 0.92;
            if (!showLabels || !inFront || !inBounds) {
              el.style.display = "none";
            } else {
              el.style.display = "inline-flex";
              el.style.left = `${(proj.x + 1) * 50}%`;
              el.style.top = `${(1 - proj.y) * 50}%`;
            }
          }

          renderer.render(scene, camera);
          raf = requestAnimationFrame(animate);
        };

        raf = requestAnimationFrame(animate);
        teardown = () => {
          disposed = true;
          cancelAnimationFrame(raf);
          controls.removeEventListener("start", pauseAutoRotate);
          controls.dispose();
          observer.disconnect();
          environment.dispose();
          decoder.dispose();
          sun.shadow.dispose();
          renderer.dispose();
          renderer.domElement.remove();
        };
      };
      const bootRaf = requestAnimationFrame(boot);
      return () => {
        cancelAnimationFrame(bootRaf);
        teardown?.();
      };
    }, [variant]);

    return (
      <div
        className={`sz-city-root sz-city-${variant}`}
        ref={host}
        data-sz-variant={variant}
      >
        {!unavailable &&
          LANDMARK_PINS.map((pin, idx) => (
            <span
              key={pin.name}
              className={`sz-city-pin sz-pin-${pin.kind}`}
              ref={(el) => {
                labelRefs.current[idx] = el;
              }}
            >
              {pin.name}
            </span>
          ))}

        {!unavailable && (
          <div className="sz-city-bar" role="toolbar" aria-label="深圳片区视角">
            {(Object.keys(DISTRICT_PRESETS) as PresetId[]).map((id) => (
              <button
                key={id}
                type="button"
                aria-pressed={activePreset === id}
                onClick={() => {
                  setActivePreset(id);
                  runtime.current?.flyToPreset(id);
                }}
              >
                {DISTRICT_PRESETS[id].label}
              </button>
            ))}
          </div>
        )}

        {!unavailable && (
          <div className="sz-city-badge">
            <span>
              大深圳湾 10× 城市级三维 · {stats.buildings} 栋建筑 ·
              可拖动旋转与滚轮缩放
            </span>
          </div>
        )}

        {unavailable && (
          <div className="sz-city-fallback">深圳湾三维场景 · WebGL 不可用</div>
        )}
      </div>
    );
  },
);
