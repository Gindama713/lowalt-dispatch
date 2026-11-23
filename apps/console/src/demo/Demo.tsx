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
  mission,
  timeLabel,
  visualViewAt,
  type VisualChoice,
} from "./playback";
import type { StudioAngle } from "./Studio";
import Scene from "./Scene";
import "./demo.css";

const explanations = [
  {
    title: "从一句话生成配送工单",
    copy: "虚拟物资站、救援点与载荷已纳入同一份演示记录。",
  },
  {
    title: "一座城市，一张任务单",
    copy: "虚构城区与 CR30 模型共同呈现任务环境。所有地标为场景示意。",
  },
  {
    title: "为什么要考虑备降？",
    copy: "备降可达性是规划阶段的约束。图中展示接受与拒绝的概念，具体算法结果以实验记录为准。",
  },
  {
    title: "合成执行回放",
    copy: "地图、进度、通信状态与事件由同一个播放时钟驱动。",
  },
  {
    title: "通信状态发生变化",
    copy: "情景展示边缘端选择已准备的备用方案。播放内容为脚本演示。",
  },
  { title: "仿真备降完成", copy: "本情景终点为备降点，应急物资仍待后续接续。" },
];
const events = [
  { at: 0, label: "工单已确认" },
  { at: 52, label: "备降约束概念展示" },
  { at: 95, label: "开始合成回放" },
  { at: 118, label: "通信退化情景" },
  { at: 142, label: "仿真备降 · 物资待接续" },
];

export default function Demo() {
  const [confirmed, setConfirmed] = useState(false);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [capture, setCapture] = useState(false);
  const [visualChoice, setVisualChoice] = useState<VisualChoice>("auto");
  const [studioAngle, setStudioAngle] = useState<StudioAngle>("orbit");
  const frame = frameAt(time, confirmed);
  const visualView = visualViewAt(visualChoice, frame.time);
  const explain = explanations[frame.phase];

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
  }

  function seek(seconds: number) {
    setPlaying(false);
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
          <strong>{frame.status}</strong>
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
            disabled={confirmed}
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
        </aside>

        <section className="demo-map" data-view={visualView}>
          <Scene frame={frame} view={visualView} studioAngle={studioAngle} />
          <div className="demo-map-top">
            <span>
              <span className="demo-dot" />{" "}
              {visualView === "studio"
                ? "CR30 / STUDIO"
                : visualView === "detail"
                  ? "CITY / ARCHITECTURE"
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
              <span>虚拟滨水城区 · 非真实地理坐标</span>
            </div>
          ) : visualView === "detail" ? (
            <div className="demo-map-bottom">
              <span>玻璃幕墙 · 建筑立柱 · 屋顶细节</span>
              <span>虚构滨水城区展示</span>
            </div>
          ) : (
            <div className="demo-studio-caption">
              <div>
                <small>PRODUCT VIEW / CR30</small>
                <strong>CR30</strong>
                <span>高精度展示模型 · 非性能或实机数据</span>
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
              <Radio size={17} /> 通信退化情景 · 备用方案回放
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
          <div className="demo-concept">
            <small>规划机制 · 概念示意</small>
            <div>
              <span>候选方案</span>
              <b>约束检查</b>
            </div>
            <div>
              <span>普通几何规划</span>
              <span className="demo-warning">可能余量不足</span>
            </div>
            <div>
              <span>备降约束规划</span>
              <span>筛除不满足条件的候选</span>
            </div>
          </div>
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
            disabled={!confirmed}
            onClick={() => {
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
