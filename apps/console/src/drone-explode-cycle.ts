export type DroneCyclePhase =
  | "assembled"
  | "exploding"
  | "spotlight"
  | "reassembling";

export type SubsystemSpotlight = {
  id: string;
  systems: readonly string[];
  label: string;
  english: string;
  accent: string;
};

export const SUBSYSTEM_SPOTLIGHTS: readonly SubsystemSpotlight[] = [
  {
    id: "PWR",
    systems: ["PWR"],
    label: "动力推进系统",
    english: "PROPULSION · 44",
    accent: "#35d4f5",
  },
  {
    id: "FC",
    systems: ["FC"],
    label: "飞控与航电核心",
    english: "AVIONICS CORE · 11",
    accent: "#5ce8c6",
  },
  {
    id: "BAT",
    systems: ["BAT"],
    label: "高能量电池模组",
    english: "BATTERY PACK · 9",
    accent: "#ffb95a",
  },
  {
    id: "CARGO",
    systems: ["CARGO"],
    label: "应急医疗载荷舱",
    english: "MEDICAL PAYLOAD · 11",
    accent: "#ff8c6b",
  },
  {
    id: "SENS",
    systems: ["SENS"],
    label: "多维感知传感阵列",
    english: "SENSOR SUITE · 11",
    accent: "#72c4ff",
  },
  {
    id: "FRAME",
    systems: ["FRAME", "SHELL", "LAND"],
    label: "碳纤机身与起落架",
    english: "AIRFRAME & SHELL · 66",
    accent: "#8fa6ff",
  },
] as const;

export const DRONE_CYCLE_PERIOD = 36;
const ASSEMBLED_END = 3.0;
const EXPLODE_END = 7.5;
const SPOTLIGHT_SLOT = 4.0;
const SPOTLIGHT_END =
  EXPLODE_END + SUBSYSTEM_SPOTLIGHTS.length * SPOTLIGHT_SLOT; // 31.5
const REASSEMBLE_END = 35.0;

/** C2-continuous quintic smootherstep with zero 1st & 2nd derivatives at endpoints. */
export function smootherstep(x: number): number {
  const t = Math.max(0, Math.min(1, x));
  return t * t * t * (t * (t * 6 - 15) + 10);
}

/** Silky bell curve in [0, 1] -> [0, 1] peaking smoothly at u = 0.5 with zero slope at 0, 0.5, 1. */
export function smoothBell(u: number): number {
  const t = Math.max(0, Math.min(1, u));
  const s = Math.sin(Math.PI * t);
  return s * s;
}

export type DroneCycleFrame = {
  cycleTime: number;
  phase: DroneCyclePhase;
  masterExplode: number;
  heroBreathScale: number;
  activeSpotlightIndex: number;
  activeSpotlight: SubsystemSpotlight | null;
  focusWeight: number;
  targetCameraDist: number;
  statusLabel: string;
  zoomPercent: number;
  partScaleFor: (system: string) => number;
  partExtraExplodeFor: (system: string) => number;
  emissiveWeightFor: (system: string) => number;
};

export function evaluateDroneCycle(elapsedSec: number): DroneCycleFrame {
  const safe = Number.isFinite(elapsedSec) ? elapsedSec : 0;
  const cycleTime =
    ((safe % DRONE_CYCLE_PERIOD) + DRONE_CYCLE_PERIOD) % DRONE_CYCLE_PERIOD;

  let phase: DroneCyclePhase = "assembled";
  let masterExplode = 0;
  let activeSpotlightIndex = -1;
  let activeSpotlight: SubsystemSpotlight | null = null;
  let focusWeight = 0;
  let targetCameraDist = 5.65;
  let statusLabel = "整机巡航展示";

  // Subtle alive breathing scale even in intact phase
  const heroBreathScale = 1 + 0.045 * smoothBell(cycleTime / ASSEMBLED_END);

  if (cycleTime < ASSEMBLED_END) {
    phase = "assembled";
    masterExplode = 0;
    targetCameraDist = 5.65 - 0.3 * smoothBell(cycleTime / ASSEMBLED_END);
    statusLabel = "整机巡航展示";
  } else if (cycleTime < EXPLODE_END) {
    phase = "exploding";
    const u = (cycleTime - ASSEMBLED_END) / (EXPLODE_END - ASSEMBLED_END);
    masterExplode = smootherstep(u);
    targetCameraDist = 5.65 + 0.9 * masterExplode;
    statusLabel = "318 构件分层爆炸展开";
  } else if (cycleTime < SPOTLIGHT_END) {
    phase = "spotlight";
    masterExplode = 1;
    const local = cycleTime - EXPLODE_END;
    const rawIdx = Math.floor(local / SPOTLIGHT_SLOT);
    activeSpotlightIndex = Math.min(SUBSYSTEM_SPOTLIGHTS.length - 1, rawIdx);
    activeSpotlight = SUBSYSTEM_SPOTLIGHTS[activeSpotlightIndex];
    const slotU =
      (local - activeSpotlightIndex * SPOTLIGHT_SLOT) / SPOTLIGHT_SLOT;
    focusWeight = smoothBell(slotU);
    // Smooth zoom-in toward active component, then silky zoom-out to full exploded vista
    targetCameraDist = 6.55 - 1.9 * focusWeight;
    statusLabel = activeSpotlight.label;
  } else if (cycleTime < REASSEMBLE_END) {
    phase = "reassembling";
    const u = (cycleTime - SPOTLIGHT_END) / (REASSEMBLE_END - SPOTLIGHT_END);
    masterExplode = 1 - smootherstep(u);
    targetCameraDist = 5.65 + 0.9 * masterExplode;
    statusLabel = "构件丝滑聚合回装";
  } else {
    phase = "assembled";
    masterExplode = 0;
    targetCameraDist = 5.65;
    statusLabel = "整机巡航展示";
  }

  const isHighlighted = (system: string) =>
    activeSpotlight !== null && activeSpotlight.systems.includes(system);

  const partScaleFor = (system: string): number => {
    if (phase === "spotlight" && focusWeight > 0.0005) {
      if (isHighlighted(system)) {
        // Silky 1.00x -> 1.38x -> 1.00x magnification on the spotlighted component
        return 1 + 0.38 * focusWeight;
      }
      // Subtle ambient pull-back on non-focused parts to accentuate contrast
      return 1 - 0.09 * focusWeight;
    }
    if (phase === "assembled" && cycleTime < ASSEMBLED_END) {
      return heroBreathScale;
    }
    return 1;
  };

  const partExtraExplodeFor = (system: string): number => {
    if (
      phase === "spotlight" &&
      focusWeight > 0.0005 &&
      isHighlighted(system)
    ) {
      return 0.18 * focusWeight;
    }
    return 0;
  };

  const emissiveWeightFor = (system: string): number => {
    if (
      phase === "spotlight" &&
      focusWeight > 0.0005 &&
      isHighlighted(system)
    ) {
      return focusWeight;
    }
    return 0;
  };

  const zoomPercent = Math.round(
    phase === "spotlight"
      ? (1 + 0.38 * focusWeight) * 100
      : phase === "assembled" && cycleTime < ASSEMBLED_END
        ? heroBreathScale * 100
        : 100,
  );

  return {
    cycleTime,
    phase,
    masterExplode,
    heroBreathScale,
    activeSpotlightIndex,
    activeSpotlight,
    focusWeight,
    targetCameraDist,
    statusLabel,
    zoomPercent,
    partScaleFor,
    partExtraExplodeFor,
    emissiveWeightFor,
  };
}
