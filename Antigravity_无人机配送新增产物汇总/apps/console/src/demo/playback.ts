/**
 * Deterministic storyboard for the competition recording.
 * All animation coordinates and captions here are illustrative.
 * Frozen benchmark figures in `frozenEvalBaseline` come from
 * `results/frozen_example_vehicle_4f70f50.csv` (example vehicle, planning only).
 * This module has no flight, planning, network or dispatch capabilities.
 */
export const DURATION = 180;

export const mission = {
  id: "DEMO-001",
  origin: "南山医疗物资中心",
  destination: "福田中心应急医院",
  aircraft: "CR30",
  cargo: "应急医疗物资",
  weight: "1 kg（示例）",
} as const;

export const chapters = [
  {
    time: 0,
    title: "任务确认",
    label: "01 / INTAKE",
    focus: "自然语言工单解析与人工确认",
  },
  {
    time: 32,
    title: "深圳湾城区",
    label: "02 / SHENZHEN TWIN",
    focus: "深圳湾城市级三维景观与 CR30 318 零件拆解",
  },
  {
    time: 52,
    title: "方案解释",
    label: "03 / SAFETY CONCEPT",
    focus: "备降可达性搜索期硬约束与负余量剪枝",
  },
  {
    time: 95,
    title: "情景回放",
    label: "04 / SIMULATION",
    focus: "单时钟跨区巡航与 118s 通信退化备降切换",
  },
  {
    time: 142,
    title: "备降复盘",
    label: "05 / REVIEW",
    focus: "深圳湾备降坪落盘复盘、证据留痕与物资接续",
  },
] as const;

/** Frozen planning benchmark metrics (git commit e9674ab, example_not_real.yaml). */
export const frozenEvalBaseline = {
  commit: "e9674ab",
  suite: "v0.yaml（20 场景 × 3 种子 = 120 组）",
  vehicleNote: "示例机型 example_not_real · 仅规划层评测，非实飞",
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
      detail: "基线 +90s 闯限飞失败；约束绕行 3115→3296 m，余量 +54.0 Wh",
    },
    {
      id: "S1-01",
      tag: "负余量剪枝",
      detail: "基线终点余量 -6.1 Wh；约束剪枝 408 状态拒绝风险航线",
    },
    {
      id: "S2-01",
      tag: "时变禁飞剪枝",
      detail: "基线 +131s 侵入 R01；约束剪枝 219 备降 + 157 禁飞状态",
    },
  ],
} as const;

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
        ? "仿真备降 · 物资待接续"
        : phase === 4
          ? "备用方案情景回放"
          : phase === 3
            ? "合成回放中"
            : phase === 2
              ? "查看约束示意"
              : "仿真工单已确认",
  };
}

export type DemoFrame = ReturnType<typeof frameAt>;

export type VisualChoice = "auto" | "city" | "detail" | "studio";
export type VisualView = "city" | "detail" | "studio";
export type StudioExplode = "auto" | "assembled" | "exploded";

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

/** Deterministic CR30 exploded-view factor (0 = assembled, 1 = full 318-part explosion). */
export function studioExplodeAt(mode: StudioExplode, seconds: number): number {
  if (mode === "assembled") return 0;
  if (mode === "exploded") return 1;
  if (seconds < 36.5 || seconds >= 48.2) return 0;
  if (seconds < 40.5) return smoothstep01((seconds - 36.5) / 4.0);
  if (seconds < 44.5) return 1;
  return 1 - smoothstep01((seconds - 44.5) / 3.7);
}

const CUT_TIMES = [32, 34, 49, 52, 118, 142] as const;

/** Brief cinema dip opacity around deterministic shot cuts (active only while playing). */
export function transitionVeilOpacity(
  seconds: number,
  playing: boolean = true,
): number {
  if (!playing) return 0;
  let peak = 0;
  for (const cut of CUT_TIMES) {
    const dist = Math.abs(seconds - cut);
    if (dist < 0.45) {
      const value = Math.cos((dist / 0.45) * (Math.PI / 2)) * 0.48;
      if (value > peak) peak = value;
    }
  }
  return peak;
}

/** Deterministic chapter title slate opacity during the opening 3s of chapters 2–5. */
export function chapterIntroOpacity(
  seconds: number,
  confirmed: boolean,
): number {
  if (!confirmed) return 0;
  for (let i = 1; i < chapters.length; i++) {
    const elapsed = seconds - chapters[i].time;
    if (elapsed >= 0 && elapsed < 3.0) {
      if (elapsed < 0.45) return smoothstep01(elapsed / 0.45);
      if (elapsed > 2.2) return 1 - smoothstep01((elapsed - 2.2) / 0.8);
      return 1;
    }
  }
  return 0;
}

export function timeLabel(seconds: number) {
  const whole = Math.floor(seconds);
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}
