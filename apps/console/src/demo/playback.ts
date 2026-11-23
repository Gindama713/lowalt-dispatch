/**
 * Deterministic storyboard for the competition recording.
 * All values here are illustrative animation coordinates and captions.
 * This module has no flight, planning, network or dispatch capabilities.
 */
export const DURATION = 180;

export const mission = {
  id: "DEMO-001",
  origin: "中心物资站",
  destination: "河东救援点",
  aircraft: "CR30",
  cargo: "应急医疗物资",
  weight: "1 kg（示例）",
} as const;

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

export function timeLabel(seconds: number) {
  const whole = Math.floor(seconds);
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}
