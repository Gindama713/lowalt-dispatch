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
  chapterIntroOpacity,
  chapters,
  DURATION,
  frameAt,
  mission,
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

const explanations = [
  {
    title: "从一句话生成深圳跨区配送工单",
    copy: "南山物资中心、福田应急医院与载荷已纳入同一份演示记录。",
  },
  {
    title: "城市级深圳湾，一张任务单",
    copy: "后海春笋、腾讯双塔、平安金融中心、市民中心与深圳湾大桥构成城市级三维场景（意象示意）。",
  },
  {
    title: "为什么要把备降做成硬约束？",
    copy: "高密度摩天楼群间将备降可达性做成规划期硬约束；冻结实测与余量剖面并列对照。",
  },
  {
    title: "合成执行回放",
    copy: "跨大沙河三维航迹、飞行姿态、余量剖面与通信状态由同一个播放时钟驱动。",
  },
  {
    title: "通信退化，边缘自主切入深圳湾备降坪",
    copy: "情景展示云端链路退化后，边缘端按预校验方案平稳切往滨海开阔备降坪。",
  },
  {
    title: "仿真备降完成",
    copy: "本情景终点为深圳湾备降坪，应急物资仍待后续接续。",
  },
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
  const [studioExplode, setStudioExplode] = useState<StudioExplode>("auto");
  const frame = frameAt(time, confirmed);
  const visualView = visualViewAt(visualChoice, frame.time);
  const explain = explanations[frame.phase];
  const explodeFactor = studioExplodeAt(studioExplode, frame.time);
  const chapterSlateOpacity = chapterIntroOpacity(frame.time, confirmed);

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
    setStudioExplode("auto");
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
          <div className="demo-chat">
            “请把应急医疗物资从南山送到福田中心应急医院。”
          </div>
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
          <Scene
            frame={frame}
            view={visualView}
            studioAngle={studioAngle}
            studioExplode={studioExplode}
            playing={playing}
          />
          <div className="demo-map-top">
            <span>
              <span className="demo-dot" />{" "}
              {visualView === "studio"
                ? explodeFactor > 0.15
                  ? "CR30 / EXPLODED STUDIO"
                  : "CR30 / STUDIO"
                : visualView === "detail"
                  ? "SHENZHEN / LANDMARK SKYLINE"
                  : "SHENZHEN BAY METROPOLIS"}
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
          {chapterSlateOpacity > 0.02 && (
            <div
              className="demo-chapter-slate"
              style={{ opacity: chapterSlateOpacity }}
              aria-hidden="true"
            >
              <small>{frame.chapter.label}</small>
              <strong>{frame.chapter.title}</strong>
              <span>{frame.chapter.focus}</span>
            </div>
          )}
          {frame.phase === 2 && visualView === "city" && (
            <div className="demo-concept-hud">
              <small>HARD CONSTRAINT · SEARCH PRUNING</small>
              <strong>红区候选已在搜索期剪枝 · 青线全程保留可达备降点</strong>
              <span>
                冻结基线 e9674ab（示例机型）：通过 36→39/60，违规航线 21→0 条
              </span>
            </div>
          )}
          {visualView === "city" ? (
            <div className="demo-map-bottom">
              <div>
                <i className="demo-key" /> 场景轨迹
              </div>
              <div>
                <i className="demo-key amber" /> 备降标记
              </div>
              {(frame.phase === 2 || frame.phase >= 4) && (
                <div>
                  <i className="demo-key crimson" /> 风险/约束区
                </div>
              )}
              <span>深圳湾意象城市三维场景 · 非真实测绘坐标</span>
            </div>
          ) : visualView === "detail" ? (
            <div className="demo-map-bottom">
              <span>平安金融中心 · 市民中心 · 华润春笋 · 深圳湾大桥</span>
              <span>城市级意象天际线展示</span>
            </div>
          ) : (
            <div className="demo-studio-caption">
              <div>
                <small>
                  {explodeFactor > 0.15
                    ? "EXPLODED ASSEMBLY / 318 PARTS"
                    : "PRODUCT VIEW / CR30"}
                </small>
                <strong>CR30</strong>
                <span>
                  {explodeFactor > 0.15
                    ? `318 零件错峰爆炸拆解（${Math.round(explodeFactor * 100)}%）· 高精度展示模型`
                    : "高精度展示模型 · 非性能或实机数据"}
                </span>
              </div>
              <div className="demo-studio-toolbar">
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
          <AlgorithmExplain frame={frame} />
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
