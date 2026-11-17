import { useEffect, useRef, useState } from "react";
import {
  Box,
  Expand,
  Layers3,
  LoaderCircle,
  Map,
  Pause,
  Play,
  RotateCcw,
  ScanLine,
} from "lucide-react";
import { useTheme } from "./Theme";
import type { HeroState } from "./heroScene";
import "./hero-experience.css";

export default function HeroExperience() {
  const { theme } = useTheme();
  const [mode, setMode] = useState<"model" | "city">("model");
  const [explode, setExplode] = useState(0);
  const [rotate, setRotate] = useState(
    () => !matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const [scan, setScan] = useState(false);
  const [reset, setReset] = useState(0);
  const [retry, setRetry] = useState(0);
  const [ready, setReady] = useState({ model: false, city: false });
  const [errors, setErrors] = useState({ model: "", city: "" });
  const [fullscreenError, setFullscreenError] = useState("");
  const host = useRef<HTMLDivElement>(null);
  const state = useRef<HeroState>({
    mode,
    explode,
    rotate,
    scan,
    reset,
    theme,
  });
  state.current = { mode, explode, rotate, scan, reset, theme };

  useEffect(() => {
    let disposed = false;
    let cleanup: (() => void) | undefined;
    setErrors({ model: "", city: "" });
    setReady({ model: false, city: false });
    import("./heroScene")
      .then(({ createHeroScene }) => {
        if (disposed || !host.current) return;
        cleanup = createHeroScene(host.current, state, (scene, error) => {
          if (disposed) return;
          setErrors((value) => ({ ...value, [scene]: error || "" }));
          setReady((value) => ({ ...value, [scene]: !error }));
        });
      })
      .catch(() => {
        if (!disposed)
          setErrors({
            model: "三维场景未能载入，请重试。",
            city: "三维场景未能载入，请重试。",
          });
      });
    return () => {
      disposed = true;
      cleanup?.();
    };
  }, [retry]);

  const error = errors[mode];
  const loaded = ready[mode] && !error;
  async function fullscreen() {
    setFullscreenError("");
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (host.current?.parentElement?.requestFullscreen)
        await host.current.parentElement.requestFullscreen();
      else setFullscreenError("当前浏览器不支持全屏展示。");
    } catch {
      setFullscreenError("当前浏览器不支持全屏展示。");
    }
  }
  return (
    <div
      className="hero-experience"
      data-scene={mode}
      data-ready={Boolean(loaded)}
    >
      <div className="hx-topline">
        <span>
          <i /> INTERACTIVE SPATIAL LAB
        </span>
        <span>01 / AERIS</span>
      </div>
      <div className="hx-tabs" role="group" aria-label="三维展示场景">
        <button
          aria-pressed={mode === "model"}
          onClick={() => setMode("model")}
        >
          <Box size={14} />
          机体展示
        </button>
        <button aria-pressed={mode === "city"} onClick={() => setMode("city")}>
          <Map size={14} />
          城市场景
        </button>
      </div>
      <div
        className="hx-canvas"
        ref={host}
        role="img"
        aria-label={
          mode === "model"
            ? "CR30 无人机交互模型，可拖动旋转并分解零件"
            : "REA 城市三维模型，可拖动旋转与缩放"
        }
      />
      <div className="hx-model-label" aria-hidden="true">
        <span>
          {mode === "model"
            ? "ENGINEERED TO EXPLORE"
            : "A CONNECTED PERSPECTIVE"}
        </span>
        <strong>
          {mode === "model" ? "CR30" : "CITY / 3D"}
          <small>{mode === "model" ? "MULTIROTOR" : "SPATIAL SCENE"}</small>
        </strong>
      </div>
      <div className="hx-status" role="status">
        {!loaded && !error && <LoaderCircle size={14} className="hx-loading" />}
        {error ||
          (loaded
            ? mode === "model"
              ? "CR30 · 原始机体模型"
              : "城市布局 · 三维演示"
            : mode === "city"
              ? "正在构建城市场景…"
              : "正在载入 CR30 模型…")}
        {error && (
          <button onClick={() => setRetry((value) => value + 1)}>
            重新载入
          </button>
        )}
      </div>
      <div className="hx-controls">
        {mode === "model" ? (
          <>
            <div className="hx-explode-row">
              <button
                disabled={!loaded}
                onClick={() => setExplode(explode > 0 ? 0 : 100)}
              >
                <Layers3 size={15} />
                {explode > 0 ? "反向复原" : "爆炸分解"}
              </button>
              <span>
                {String(explode).padStart(3, "0")}
                <small> %</small>
              </span>
            </div>
            <input
              aria-label="模型分解程度"
              type="range"
              min="0"
              max="100"
              value={explode}
              disabled={!loaded}
              onChange={(event) => setExplode(Number(event.target.value))}
            />
          </>
        ) : (
          <div className="hx-city-note">
            河道、建筑与能源园区<span>场景模型演示 · 非真实地理数据</span>
          </div>
        )}
        <div className="hx-tool-row">
          <button aria-pressed={rotate} onClick={() => setRotate(!rotate)}>
            {rotate ? <Pause size={14} /> : <Play size={14} />}自动环绕
          </button>
          <button aria-pressed={scan} onClick={() => setScan(!scan)}>
            <ScanLine size={14} />
            扫描光效
          </button>
          <button
            aria-label="重置三维视角"
            onClick={() => {
              setReset((value) => value + 1);
              setExplode(0);
            }}
          >
            <RotateCcw size={14} />
          </button>
          <button aria-label="放大三维展示" onClick={() => void fullscreen()}>
            <Expand size={14} />
          </button>
        </div>
      </div>
      <p className="hx-hint" role={fullscreenError ? "status" : undefined}>
        {fullscreenError || (
          <>
            拖动旋转 <span>·</span> 滚轮缩放 <span>·</span>{" "}
            {mode === "model" ? "滑动探索机体结构" : "探索城市空间"}
          </>
        )}
      </p>
    </div>
  );
}
