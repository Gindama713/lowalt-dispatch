/**
 * Deterministic storyboard for the competition recording.
 * All values here are illustrative animation coordinates and captions.
 * This module has no flight, planning, network or dispatch capabilities.
 */
export const DURATION = 180;

export const chapters = [
  { time: 0, title: "任务确认", label: "01 / INTAKE" },
  { time: 32, title: "虚拟城区", label: "02 / DIGITAL TWIN" },
  { time: 52, title: "方案解释", label: "03 / SAFETY CONCEPT" },
  { time: 95, title: "情景回放", label: "04 / SIMULATION" },
  { time: 142, title: "备降复盘", label: "05 / REVIEW" },
] as const;

export function frameAt(seconds: number, confirmed: boolean) {
  const time = Math.max(
    0,
    Math.min(DURATION, Number.isFinite(seconds) ? seconds : 0),
  );
  const chapter =
    [...chapters].reverse().find((item) => time >= item.time) ?? chapters[0];
  const phase =
    time < 32
      ? 0
      : time < 52
        ? 1
        : time < 95
          ? 2
          : time < 118
            ? 3
            : time < 142
              ? 4
              : 5;
  const progress = Math.max(0, Math.min(1, (time - 95) / 47));
  return {
    time,
    chapter,
    phase,
    progress,
    confirmed,
    signal:
      phase === 4 ? "退化（情景）" : phase === 5 ? "回放结束" : "正常（情景）",
    status: !confirmed
      ? "等待确认"
      : phase === 5
        ? "几何航线回放结束 · 未下发"
        : phase === 4
          ? "链路退化示意 · 航线保持冻结版本"
          : phase === 3
            ? "合成回放中"
            : phase === 2
              ? "查看冻结算法证据"
              : "仿真工单已确认",
  };
}

export type DemoFrame = ReturnType<typeof frameAt>;

export type VisualChoice = "auto" | "city" | "detail" | "studio";
export type VisualView = "city" | "detail" | "studio";
export type StudioExplode = "auto" | "assembled" | "exploded";

/**
 * Historical planning snapshot shipped with the Antigravity package.
 * Commit e9674ab, example vehicle, planning layer only. Not a re-run of
 * this branch and not a flight test.
 */
export const frozenEvalBaseline = {
  commit: "e9674ab",
  suite: "v0.yaml（20 场景 × 3 种子 = 120 组）",
  vehicleNote:
    "示例机型 example_not_real · 历史规划评测快照，非本分支重跑，非实飞",
  staticFeasible: 36,
  staticReturned: 57,
  staticUnsafeRoutes: 21,
  staticNegativeRoutes: 12,
  staticP50LengthM: 3018,
  diversionFeasible: 39,
  diversionReturned: 39,
  diversionUnsafeRoutes: 0,
  diversionNegativeRoutes: 0,
  diversionP50LengthM: 2832,
  validatorSummary: "14 通过 / 5 拒绝 / 1 无航线",
  cases: [
    {
      id: "S2-03",
      tag: "主动绕行通过",
      detail: "快照记录：基线侵入限制区判失败；约束绕行后余量为正",
    },
    {
      id: "S1-01",
      tag: "负余量剪枝",
      detail: "快照记录：基线终点余量为负；约束搜索拒绝该风险航线",
    },
    {
      id: "S2-01",
      tag: "时变禁飞剪枝",
      detail: "快照记录：基线侵入已激活的 R01；约束搜索按禁飞与备降剪枝",
    },
  ],
} as const;

/** The studio shot is a purely visual insert within the fictional replay. */
export function visualViewAt(
  choice: VisualChoice,
  seconds: number,
): VisualView {
  if (choice !== "auto") return choice;
  if (seconds >= 34 && seconds < 49) return "studio";
  if (seconds >= 32 && seconds < 52) return "detail";
  return "city";
}

function smoothstep01(x: number): number {
  const t = Math.max(0, Math.min(1, x));
  return t * t * (3 - 2 * t);
}

/** Deterministic CR30 exploded-view factor (0 = assembled, 1 = full explosion). */
export function studioExplodeAt(mode: StudioExplode, seconds: number): number {
  if (mode === "assembled") return 0;
  if (mode === "exploded") return 1;
  if (seconds < 36.5 || seconds >= 48.2) return 0;
  if (seconds < 40.5) return smoothstep01((seconds - 36.5) / 4.0);
  if (seconds < 44.5) return 1;
  return 1 - smoothstep01((seconds - 44.5) / 3.7);
}

export function timeLabel(seconds: number) {
  const whole = Math.floor(seconds);
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}
