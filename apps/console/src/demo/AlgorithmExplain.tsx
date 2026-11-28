import { useState } from "react";
import { frozenEvalBaseline, type DemoFrame } from "./playback";

// Illustrative diversion-margin profile synced to the 180s storyboard.
// Values depict the planning mechanism concept; real benchmark figures live in the frozen tab.
const STATIC_POINTS: readonly [number, number][] = [
  [0.0, 58],
  [0.14, 49],
  [0.28, 36],
  [0.42, 22],
  [0.54, 8],
  [0.66, -4],
  [0.78, -11],
  [0.9, -15],
  [1.0, -8],
];

const DIVERSION_POINTS: readonly [number, number][] = [
  [0.0, 58],
  [0.14, 51],
  [0.28, 43],
  [0.42, 35],
  [0.49, 31],
  [0.62, 34],
  [0.78, 39],
  [0.92, 46],
  [1.0, 54],
];

const CHART_W = 248;
const CHART_H = 104;
const PAD_X = 24;
const PAD_TOP = 10;
const PAD_BOTTOM = 18;
const MIN_Y = -20;
const MAX_Y = 70;
const SWITCH_PROGRESS = (118 - 95) / 47;

function xOf(progress: number): number {
  return PAD_X + progress * (CHART_W - PAD_X - 8);
}

function yOf(margin: number): number {
  const ratio = (margin - MIN_Y) / (MAX_Y - MIN_Y);
  return PAD_TOP + (1 - ratio) * (CHART_H - PAD_TOP - PAD_BOTTOM);
}

function polyline(pts: readonly [number, number][]): string {
  return pts
    .map(([p, y]) => `${xOf(p).toFixed(1)},${yOf(y).toFixed(1)}`)
    .join(" ");
}

function sampleCurve(
  pts: readonly [number, number][],
  progress: number,
): number {
  const p = Math.max(0, Math.min(1, progress));
  for (let i = 1; i < pts.length; i++) {
    const [p0, y0] = pts[i - 1];
    const [p1, y1] = pts[i];
    if (p <= p1) {
      const t = p1 === p0 ? 0 : (p - p0) / (p1 - p0);
      return y0 + (y1 - y0) * t;
    }
  }
  return pts[pts.length - 1][1];
}

export default function AlgorithmExplain({ frame }: { frame: DemoFrame }) {
  const [tab, setTab] = useState<"profile" | "frozen">("profile");

  const cursorProgress =
    frame.phase < 2
      ? 0
      : frame.phase === 2
        ? Math.min(1, (frame.time - 52) / 43)
        : frame.progress;

  const safeMargin = sampleCurve(DIVERSION_POINTS, cursorProgress);
  const staticMargin = sampleCurve(STATIC_POINTS, cursorProgress);
  const zeroY = yOf(0);
  const switchX = xOf(SWITCH_PROGRESS);
  const cursorX = xOf(cursorProgress);
  const cursorSafeY = yOf(safeMargin);
  const isFallback = frame.phase >= 4;

  const stageNote =
    frame.phase < 2
      ? "待进入方案解释：展示备降硬约束机制"
      : frame.phase === 2
        ? "概念示意：余量跌破 0 Wh 的候选会在搜索期被剪掉。这不是当前航线的计算值"
        : frame.phase === 3
          ? "概念示意：约束搜索要求保留可达备降。画面不是飞控执行"
          : frame.phase === 4
            ? "118 秒只是情景标记。这里没有切换到一条新的已校验备降航线"
            : "回放结束且未下发。曲线不是这条冻结航线的实测余量";

  return (
    <div className="demo-algo" data-algo-tab={tab}>
      <div className="demo-algo-head">
        <small>备降硬约束</small>
        <div className="demo-algo-tabs" role="tablist" aria-label="算法视图">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "profile"}
            onClick={() => setTab("profile")}
          >
            余量剖面
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "frozen"}
            onClick={() => setTab("frozen")}
          >
            冻结评测
          </button>
        </div>
      </div>

      {tab === "profile" ? (
        <div className="demo-algo-body">
          <svg
            className="demo-margin-svg"
            viewBox={`0 0 ${CHART_W} ${CHART_H}`}
            role="img"
            aria-label="备降余量剖面示意曲线"
          >
            {/* Red danger zone below 0 Wh */}
            <rect
              x={PAD_X}
              y={zeroY}
              width={CHART_W - PAD_X - 8}
              height={CHART_H - PAD_BOTTOM - zeroY}
              fill="#ff5c6c22"
            />
            {/* Grid lines */}
            <line
              x1={PAD_X}
              y1={yOf(50)}
              x2={CHART_W - 8}
              y2={yOf(50)}
              stroke="#2a4457"
              strokeWidth="0.6"
              strokeDasharray="2 3"
            />
            <line
              x1={PAD_X}
              y1={zeroY}
              x2={CHART_W - 8}
              y2={zeroY}
              stroke="#ff6b7a"
              strokeWidth="1"
              strokeDasharray="3 2"
            />
            {/* 118s diversion switch marker */}
            <line
              x1={switchX}
              y1={PAD_TOP}
              x2={switchX}
              y2={CHART_H - PAD_BOTTOM}
              stroke="#ffc77970"
              strokeWidth="0.9"
              strokeDasharray="2 2"
            />
            {/* Y-axis labels */}
            <text x="2" y={yOf(50) + 3} className="demo-svg-tick">
              +50
            </text>
            <text x="6" y={zeroY + 3} className="demo-svg-tick danger">
              0
            </text>
            <text x="2" y={yOf(-15) + 3} className="demo-svg-tick">
              -15
            </text>
            {/* Static A* baseline (dashed red) */}
            <polyline
              fill="none"
              stroke="#ff7c8a"
              strokeWidth="1.4"
              strokeDasharray="4 3"
              points={polyline(STATIC_POINTS)}
            />
            {/* Diversion-constrained A* (solid cyan -> amber after 118s) */}
            <polyline
              fill="none"
              stroke={isFallback ? "#ffc779" : "#6fe1de"}
              strokeWidth="2"
              strokeLinejoin="round"
              points={polyline(DIVERSION_POINTS)}
            />
            {/* Synchronized playhead */}
            <line
              x1={cursorX}
              y1={PAD_TOP}
              x2={cursorX}
              y2={CHART_H - PAD_BOTTOM}
              stroke="#e7f7ff88"
              strokeWidth="1"
            />
            <circle
              cx={cursorX}
              cy={cursorSafeY}
              r="3.4"
              fill={isFallback ? "#ffc779" : "#6fe1de"}
              stroke="#0a1620"
              strokeWidth="1.2"
            />
            {/* X-axis annotations */}
            <text x={PAD_X} y={CHART_H - 4} className="demo-svg-tick">
              起点
            </text>
            <text
              x={switchX - 10}
              y={CHART_H - 4}
              className="demo-svg-tick amber"
            >
              118s
            </text>
            <text x={CHART_W - 28} y={CHART_H - 4} className="demo-svg-tick">
              终点
            </text>
          </svg>

          <div className="demo-algo-legend">
            <span>
              <i className="swatch safe" /> 备降硬约束{" "}
              <b>+{safeMargin.toFixed(0)} Wh</b>
            </span>
            <span>
              <i className="swatch risk" /> 普通几何{" "}
              <b className={staticMargin < 0 ? "demo-danger" : ""}>
                {staticMargin >= 0 ? "+" : ""}
                {staticMargin.toFixed(0)} Wh
              </b>
            </span>
          </div>
          <p className="demo-algo-note">{stageNote}</p>
          <p className="demo-algo-footnote">
            曲线为机制概念示意，不是当前航线算出的余量。历史快照见「冻结评测」
          </p>
        </div>
      ) : (
        <div className="demo-algo-body demo-frozen-body">
          <div className="demo-frozen-metric">
            <div>
              <span>普通几何 A*（36/60 通过 · 21 条违规）</span>
              <strong className="demo-danger">
                负余量 {frozenEvalBaseline.staticNegativeRoutes} 条
              </strong>
            </div>
            <div className="demo-bar-track">
              <i
                className="demo-bar-fill danger"
                style={{
                  width: `${(frozenEvalBaseline.staticUnsafeRoutes / frozenEvalBaseline.staticReturned) * 100}%`,
                }}
              />
            </div>
          </div>
          <div className="demo-frozen-metric">
            <div>
              <span>备降硬约束 A*（39/60 通过 · 0 违规）</span>
              <strong className="demo-safe">
                负余量 {frozenEvalBaseline.diversionNegativeRoutes} 条
              </strong>
            </div>
            <div className="demo-bar-track">
              <i className="demo-bar-fill safe" style={{ width: "100%" }} />
            </div>
          </div>
          <ul className="demo-frozen-cases">
            {frozenEvalBaseline.cases.map((item) => (
              <li key={item.id}>
                <b>
                  {item.id} · {item.tag}
                </b>
                <span>{item.detail}</span>
              </li>
            ))}
          </ul>
          <p className="demo-algo-footnote">
            历史快照 {frozenEvalBaseline.commit} ·{" "}
            {frozenEvalBaseline.vehicleNote}
          </p>
        </div>
      )}
    </div>
  );
}
