import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CircleHelp,
  Film,
  Maximize,
  Pause,
  Play,
  Radio,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";
import {
  chapters,
  DURATION,
  frameAt,
  studioExplodeAt,
  timeLabel,
  visualViewAt,
  type StudioExplode,
  type VisualChoice,
} from "./playback";
import type { StudioAngle } from "./Studio";
import AlgorithmExplain from "./AlgorithmExplain";
import Scene from "./Scene";
import "./demo.css";
import { readTaskEvidence, type TaskEvidence } from "../assistant/taskEvidence";
import { EvidenceMap, TaskEvidenceCard } from "../assistant/TaskEvidenceCard";

const explanations = [
  {
    title: "从一句话生成配送工单",
    copy: "虚拟物资站、救援点与载荷已纳入同一份演示记录。",
  },
  {
    title: "一座城市，一张任务单",
    copy: "深圳湾艺术场景与 CR30 只作展示。地标不是测绘坐标，也不作为算法避障依据。",
  },
  {
    title: "沿着航线，查看每一步的备降余量",
    copy: "冻结的算法输出与独立校验记录共同驱动场景图和余量曲线；数值仅适用于示例机型。",
  },
  {
    title: "合成执行回放",
    copy: "地图、进度、通信状态与事件由同一个播放时钟驱动。",
  },
  {
    title: "通信状态发生变化",
    copy: "通信退化为情景提示；保持已验证的冻结路线，不展示未经验证的途中备降切换。",
  },
  {
    title: "几何航线回放完成",
    copy: "回放到达冻结航线终点；未下发任务，配送完成情况未验证。",
  },
];
const events = [
  { at: 0, label: "工单已确认" },
  { at: 52, label: "查看冻结算法与校验记录" },
  { at: 95, label: "开始合成回放" },
  { at: 118, label: "通信退化情景" },
  { at: 142, label: "回放结束 · 未下发" },
];

export default function Demo() {
  const [cases, setCases] = useState<{
    main?: TaskEvidence;
    contrast?: TaskEvidence;
  }>({});
  useEffect(() => {
    const abort = new AbortController();
    fetch("/task-evidence.json", { signal: abort.signal })
      .then((r) => {
        if (!r.ok) throw new Error("证据不可用");
        return r.json();
      })
      .then((data) =>
        setCases({
          main: readTaskEvidence(data.cases?.main),
          contrast: readTaskEvidence(data.cases?.contrast),
        }),
      )
      .catch(() => {});
    return () => abort.abort();
  }, []);
  const [confirmed, setConfirmed] = useState(false);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [capture, setCapture] = useState(false);
  const [visualChoice, setVisualChoice] = useState<VisualChoice>("auto");
  const [studioAngle, setStudioAngle] = useState<StudioAngle>("orbit");
  const [studioExplode, setStudioExplode] = useState<StudioExplode>("auto");
  const [evidenceCase, setEvidenceCase] = useState<"main" | "contrast">("main");
  const [algorithmMap, setAlgorithmMap] = useState(false);
  const evidence = cases[evidenceCase];
  const [selectedSample, setSelectedSample] = useState<number | null>(null);
  const frame = frameAt(time, confirmed);
  const visualView = visualViewAt(visualChoice, frame.time);
  const explodeFactor = studioExplodeAt(studioExplode, frame.time);
  const explain = explanations[frame.phase];
  const sampleIndex = evidence
    ? Math.min(
        evidence.samples.length - 1,
        selectedSample ??
          Math.floor(
            Math.max(0, Math.min(1, (time - 52) / 43)) *
              (evidence.samples.length - 1),
          ),
      )
    : 0;
  const mission = {
    id: evidence?.task_id ?? "证据不可用",
    origin: evidence?.origin ?? "—",
    destination: evidence?.destination ?? "—",
    cargo: "应急医疗物资",
    weight: evidence ? `${evidence.payload_kg} kg（示例）` : "—",
    aircraft: "CR30（仅外观展示）",
  };

  useEffect(() => {
    if (!playing || !confirmed) return;
    let raf = 0;
    let previous = performance.now();
    const step = (now: number) => {
      const delta = (now - previous) / 1000;
      previous = now;
      setTime((t) => Math.min(DURATION, t + delta));
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, confirmed]);
  useEffect(() => {
    if (time >= DURATION) setPlaying(false);
  }, [time]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") setCapture(false);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  function reset() {
    setPlaying(false);
    setTime(0);
    setConfirmed(false);
    setVisualChoice("auto");
    setStudioAngle("orbit");
    setEvidenceCase("main");
    setSelectedSample(null);
    setAlgorithmMap(false);
  }

  function seek(seconds: number) {
    setPlaying(false);
    setSelectedSample(null);
    setAlgorithmMap(false);
    setTime(seconds);
  }

  return (
    <main className={`aeris-demo ${capture ? "demo-capture" : ""}`}>
      <header className="demo-header">
        <div className="demo-brand">
          <a href="/" aria-label="返回首页">
            <ArrowLeft size={18} />
          </a>
          <strong>
            AERIS<span>.</span>
          </strong>
          <div className="demo-separator" />
          <span>低空应急配送 / 竞赛演示</span>
        </div>
        <div className="demo-mode">
          <span /> 离线仿真 · 情景回放
        </div>
      </header>
      <section className="demo-headline">
        <div>
          <small>{frame.chapter.label}</small>
          <h1>{explain.title}</h1>
          <p>{explain.copy}</p>
        </div>
        <div className="demo-task-status">
          <small>MISSION / {mission.id}</small>
          <strong>
            {evidenceCase === "contrast"
              ? "对照案例 · 独立校验拒绝，未执行"
              : frame.status}
          </strong>
        </div>
      </section>
      <div className="demo-grid">
        <aside className="demo-card demo-mission">
          <div className="demo-eyebrow">
            <CircleHelp size={16} /> TASK INTAKE
          </div>
          <h2>调度助手</h2>
          <div className="demo-chat">“请把应急医疗物资送到河东救援点。”</div>
          <div className="demo-reply">已整理为虚拟场景配送任务，请审核。</div>
          <dl>
            <dt>起点</dt>
            <dd>{mission.origin}</dd>
            <dt>目的地</dt>
            <dd>{mission.destination}</dd>
            <dt>货物</dt>
            <dd>{mission.cargo}</dd>
            <dt>载荷</dt>
            <dd>{mission.weight}</dd>
            <dt>展示机型</dt>
            <dd>{mission.aircraft}</dd>
          </dl>
          <button
            disabled={confirmed || evidenceCase === "contrast" || !evidence}
            className="demo-primary"
            onClick={() => {
              setConfirmed(true);
              setPlaying(true);
            }}
          >
            {confirmed ? <Check size={17} /> : <ArrowRight size={17} />}
            {confirmed ? "已确认仿真任务" : "确认演示工单"}
          </button>
          <p className="demo-caption">固定工单示例 · 不提交至飞控或业务后端</p>
          <label className="demo-evidence-select">
            算法案例
            <select
              aria-label="算法案例"
              value={evidenceCase}
              onChange={(event) => {
                setEvidenceCase(event.target.value as "main" | "contrast");
                setPlaying(false);
                setConfirmed(false);
                setSelectedSample(null);
                setTime(52);
                setAlgorithmMap(true);
              }}
            >
              <option value="main">S1-02 · 通过例</option>
              <option value="contrast">S1-01 · 拒绝对照</option>
            </select>
          </label>
        </aside>

        <section className="demo-map" data-view={visualView}>
          {evidence && (
            <Scene
              key={evidence.revision}
              frame={frame}
              view={visualView}
              studioAngle={studioAngle}
              studioExplode={studioExplode}
              evidence={evidence}
            />
          )}
          {evidence && (algorithmMap || frame.phase === 2) && (
            <div className="demo-algorithm-map" aria-label="算法证据主地图">
              <header>
                <strong>{evidence.task_id} · 算法场景</strong>
                <button
                  onClick={() => {
                    setAlgorithmMap(false);
                    if (frame.phase === 2) seek(95);
                  }}
                >
                  返回城市镜头
                </button>
              </header>
              <EvidenceMap evidence={evidence} sampleIndex={sampleIndex} />
              <p>{evidence.algorithm} · 栅格 ENU · 冻结仿真输入</p>
            </div>
          )}
          <div className="demo-map-top">
            <span>
              <span className="demo-dot" />{" "}
              {visualView === "studio"
                ? "CR30 / STUDIO"
                : visualView === "detail"
                  ? "CITY / ARCHITECTURE"
                  : frame.time >= 52
                    ? "ALGORITHM / ENU"
                    : "VIRTUAL CITY"}
            </span>
            <div className="demo-view-switch" aria-label="视觉镜头">
              <button
                type="button"
                aria-pressed={visualChoice === "auto"}
                onClick={() => setVisualChoice("auto")}
              >
                自动镜头
              </button>
              <button
                type="button"
                aria-pressed={visualChoice === "city"}
                onClick={() => setVisualChoice("city")}
              >
                城市全景
              </button>
              <button
                type="button"
                aria-pressed={visualChoice === "detail"}
                onClick={() => setVisualChoice("detail")}
              >
                建筑近景
              </button>
              <button
                type="button"
                aria-pressed={visualChoice === "studio"}
                onClick={() => setVisualChoice("studio")}
              >
                CR30 特写
              </button>
            </div>
          </div>
          {visualView === "city" ? (
            <div className="demo-map-bottom">
              <div>
                <i className="demo-key" /> 场景轨迹
              </div>
              <div>
                <i className="demo-key amber" /> 备降标记
              </div>
              <span>
                {frame.time >= 52
                  ? "冻结算法 ENU 场景 · 高度仅作示意"
                  : "深圳湾艺术场景 · 非测绘坐标，不是实飞"}
              </span>
            </div>
          ) : visualView === "detail" ? (
            <div className="demo-map-bottom">
              <span>艺术天际线 · 非测绘坐标</span>
              <span>不作为算法避障依据</span>
            </div>
          ) : (
            <div className="demo-studio-caption">
              <div>
                <small>
                  {explodeFactor > 0.15
                    ? "EXPLODED ASSEMBLY"
                    : "PRODUCT VIEW / CR30"}
                </small>
                <strong>CR30</strong>
                <span>高精度展示模型 · 非性能或实机数据</span>
              </div>
              <div className="demo-studio-angles" aria-label="拆解模式">
                <button
                  type="button"
                  aria-pressed={studioExplode === "auto"}
                  onClick={() => setStudioExplode("auto")}
                >
                  自动拆解
                </button>
                <button
                  type="button"
                  aria-pressed={studioExplode === "assembled"}
                  onClick={() => setStudioExplode("assembled")}
                >
                  整机
                </button>
                <button
                  type="button"
                  aria-pressed={studioExplode === "exploded"}
                  onClick={() => setStudioExplode("exploded")}
                >
                  爆炸拆解
                </button>
              </div>
              <div className="demo-studio-angles" aria-label="展示角度">
                <button
                  type="button"
                  aria-pressed={studioAngle === "orbit"}
                  onClick={() => setStudioAngle("orbit")}
                >
                  斜视
                </button>
                <button
                  type="button"
                  aria-pressed={studioAngle === "side"}
                  onClick={() => setStudioAngle("side")}
                >
                  侧视
                </button>
                <button
                  type="button"
                  aria-pressed={studioAngle === "top"}
                  onClick={() => setStudioAngle("top")}
                >
                  顶视
                </button>
              </div>
            </div>
          )}
          {frame.phase === 4 && visualView === "city" && (
            <div className="demo-alert">
              <Radio size={17} /> 通信退化情景 · 航线保持冻结版本
            </div>
          )}
        </section>

        <aside className="demo-card demo-analysis">
          <div className="demo-eyebrow">
            <ShieldCheck size={16} /> DECISION REVIEW
          </div>
          <h2>决策与证据</h2>
          <div className="demo-indicator">
            <span>链路状态</span>
            <strong className={frame.phase === 4 ? "demo-warning" : ""}>
              {frame.signal}
            </strong>
          </div>
          <div className="demo-indicator">
            <span>回放进度</span>
            <strong>{Math.round(frame.progress * 100)}%</strong>
          </div>
          <div className="demo-meter">
            <i style={{ width: `${frame.progress * 100}%` }} />
          </div>
          <AlgorithmExplain frame={frame} />
          {evidence ? (
            <TaskEvidenceCard
              key={evidence.revision}
              evidence={evidence}
              sampleIndex={sampleIndex}
              onSample={(index) => {
                setSelectedSample(index);
                setPlaying(false);
                setAlgorithmMap(true);
              }}
              onLocate={() => {
                setAlgorithmMap(true);
                setPlaying(false);
              }}
            />
          ) : (
            <p role="alert">冻结算法证据不可用，请重新导出。</p>
          )}
          <h3>事件记录</h3>
          <ol className="demo-events">
            {events.map((event) => (
              <li key={event.at} data-active={confirmed && time >= event.at}>
                <button
                  disabled={!confirmed || time < event.at}
                  onClick={() => seek(event.at)}
                >
                  <time>{timeLabel(event.at)}</time>
                  <span>{event.label}</span>
                </button>
              </li>
            ))}
          </ol>
        </aside>
      </div>
      <footer className="demo-controls">
        <div className="demo-play-actions">
          <button
            aria-label={playing ? "暂停" : "播放"}
            disabled={!confirmed || evidenceCase === "contrast"}
            onClick={() => {
              setSelectedSample(null);
              if (time >= DURATION) setTime(0);
              setPlaying(!playing);
            }}
          >
            {playing ? <Pause size={19} /> : <Play size={19} />}
          </button>
          <button aria-label="重置" onClick={reset}>
            <RotateCcw size={19} />
          </button>
          <time>{timeLabel(time)} / 03:00</time>
          <button
            className="demo-capture-button"
            onClick={() => setCapture(true)}
          >
            <Maximize size={16} /> 录制模式
          </button>
        </div>
        <input
          type="range"
          aria-label="演示时间轴"
          min={0}
          max={DURATION}
          step={0.1}
          value={time}
          disabled={!confirmed}
          onChange={(e) => seek(Number(e.target.value))}
        />
        <nav aria-label="演示章节">
          {chapters.map((chapter) => (
            <button
              key={chapter.time}
              disabled={!confirmed}
              data-current={chapter === frame.chapter}
              onClick={() => seek(chapter.time)}
            >
              {chapter.title}
            </button>
          ))}
        </nav>
      </footer>
      {capture && (
        <button
          className="demo-exit-capture"
          onClick={() => setCapture(false)}
          title="Esc 退出录制模式"
        >
          <Film size={14} /> 返回控制
        </button>
      )}
    </main>
  );
}
