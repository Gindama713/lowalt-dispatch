import test from "node:test";
import assert from "node:assert/strict";
import {
  chapterIntroOpacity,
  chapters,
  DURATION,
  frameAt,
  frozenEvalBaseline,
  studioExplodeAt,
  timeLabel,
  transitionVeilOpacity,
  visualViewAt,
} from "../src/demo/playback.ts";

import {
  landmarks,
  makeCityLots,
  RIVER_CENTER_X,
  RIVER_HALF_WIDTH,
  shenzhenLandmarks,
  SHORELINE_Z,
} from "../src/demo/city-layout.ts";

import {
  DRONE_CYCLE_PERIOD,
  SUBSYSTEM_SPOTLIGHTS,
  evaluateDroneCycle,
  smoothBell,
  smootherstep,
} from "../src/drone-explode-cycle.ts";

test("10x Greater Shenzhen Bay layout has deterministic districts, 9 landmarks and unobstructed pads", () => {
  const lots = makeCityLots();
  assert.deepEqual(lots, makeCityLots());
  assert.ok(
    lots.length >= 450,
    `expected >= 450 city lots, got ${lots.length}`,
  );
  assert.equal(shenzhenLandmarks.length, 9);
  assert.deepEqual([...new Set(lots.map((lot) => lot.style))].sort(), [
    "office",
    "residential",
    "warehouse",
  ]);
  for (const lot of lots) {
    assert.ok(lot.width > 0 && lot.depth > 0 && lot.height > 0);
    assert.ok(lot.z + lot.depth / 2 < SHORELINE_Z - 14);
    assert.ok(
      Math.abs(lot.x - RIVER_CENTER_X) - lot.width / 2 > RIVER_HALF_WIDTH + 8,
    );
    for (const point of landmarks) {
      assert.ok(Math.hypot(lot.x - point.x, lot.z - point.z) >= 27);
    }
  }
});

test("confirmation and chapter boundaries are deterministic", () => {
  assert.equal(frameAt(0, false).status, "等待确认");
  assert.equal(frameAt(0, true).confirmed, true);
  for (const chapter of chapters) {
    assert.equal(frameAt(chapter.time, true).chapter.title, chapter.title);
  }
  assert.equal(frameAt(117.9, true).phase, 3);
  assert.equal(frameAt(118, true).phase, 4);
  assert.equal(frameAt(118, true).signal, "退化（情景）");
  assert.equal(frameAt(142, true).phase, 5);
  assert.equal(frameAt(142, true).status, "仿真备降 · 物资待接续");
});

test("replay never loops from its terminal state and seeking is reversible", () => {
  assert.equal(frameAt(-10, true).time, 0);
  assert.equal(frameAt(NaN, true).time, 0);
  assert.equal(frameAt(95, true).progress, 0);
  assert.equal(frameAt(142, true).progress, 1);
  assert.deepEqual(frameAt(DURATION, true), frameAt(DURATION + 500, true));
  assert.deepEqual(frameAt(118, true), frameAt(118, true));
  assert.equal(frameAt(0, false).progress, 0);
  assert.equal(timeLabel(DURATION), "03:00");
});

test("cinematic insert follows replay time and respects manual views", () => {
  assert.equal(visualViewAt("auto", 31.9), "city");
  assert.equal(visualViewAt("auto", 32), "detail");
  assert.equal(visualViewAt("auto", 33.9), "detail");
  assert.equal(visualViewAt("auto", 34), "studio");
  assert.equal(visualViewAt("auto", 48.9), "studio");
  assert.equal(visualViewAt("auto", 49), "detail");
  assert.equal(visualViewAt("auto", 52), "city");
  assert.equal(visualViewAt("city", 40), "city");
  assert.equal(visualViewAt("studio", 0), "studio");
  assert.equal(visualViewAt("detail", 0), "detail");
});

test("CR30 studio explode, cinematic veil, chapter slate and frozen baseline are deterministic", () => {
  assert.equal(studioExplodeAt("assembled", 42), 0);
  assert.equal(studioExplodeAt("exploded", 0), 1);
  assert.equal(studioExplodeAt("auto", 0), 0);
  assert.equal(studioExplodeAt("auto", 42), 1);
  assert.equal(studioExplodeAt("auto", 48.5), 0);
  assert.ok(transitionVeilOpacity(34, true) > 0.4);
  assert.equal(transitionVeilOpacity(34, false), 0);
  assert.equal(transitionVeilOpacity(118, false), 0);
  assert.equal(transitionVeilOpacity(42, true), 0);
  assert.equal(chapterIntroOpacity(33, false), 0);
  assert.ok(chapterIntroOpacity(33, true) > 0.9);
  assert.equal(chapterIntroOpacity(40, true), 0);
  assert.equal(frozenEvalBaseline.commit, "e9674ab");
  assert.equal(frozenEvalBaseline.staticFeasible, 36);
  assert.equal(frozenEvalBaseline.diversionFeasible, 39);
  assert.equal(frozenEvalBaseline.diversionUnsafeRoutes, 0);
  assert.equal(frozenEvalBaseline.diversionNegativeRoutes, 0);
});

test("desktop CR30 3D exploded backdrop cycles smoothly across all 6 subsystems with scale zoom", () => {
  assert.equal(smootherstep(0), 0);
  assert.equal(smootherstep(1), 1);
  assert.equal(smoothBell(0), 0);
  assert.equal(smoothBell(0.5), 1);
  assert.ok(smoothBell(1) < 1e-12);

  // Seamless periodic wrap at cycle boundaries
  const start = evaluateDroneCycle(0);
  const wrapped = evaluateDroneCycle(DRONE_CYCLE_PERIOD);
  assert.equal(start.phase, "assembled");
  assert.equal(start.masterExplode, 0);
  assert.equal(wrapped.phase, start.phase);
  assert.equal(wrapped.masterExplode, start.masterExplode);

  // Mid-explode ramps smoothly
  const midExplode = evaluateDroneCycle(5.25);
  assert.equal(midExplode.phase, "exploding");
  assert.ok(midExplode.masterExplode > 0.45 && midExplode.masterExplode < 0.55);

  // All 6 CR30 subsystems peak with >1.35x scale magnification & close-up camera zoom-in
  SUBSYSTEM_SPOTLIGHTS.forEach((spot, idx) => {
    const peakTime = 7.5 + idx * 4.0 + 2.0;
    const f = evaluateDroneCycle(peakTime);
    assert.equal(f.phase, "spotlight");
    assert.equal(f.activeSpotlight?.id, spot.id);
    assert.ok(f.focusWeight > 0.99);
    assert.ok(f.targetCameraDist < 4.8);
    assert.ok(f.partScaleFor(spot.systems[0]) > 1.35);
    assert.ok(f.partExtraExplodeFor(spot.systems[0]) > 0.15);
    assert.ok(f.emissiveWeightFor(spot.systems[0]) > 0.99);
    // Non-active subsystem gently steps back
    const other =
      SUBSYSTEM_SPOTLIGHTS[(idx + 1) % SUBSYSTEM_SPOTLIGHTS.length].systems[0];
    assert.ok(f.partScaleFor(other) < 0.95);
  });

  // Reassembly smoothly converges back toward 0
  const reasm = evaluateDroneCycle(33.25);
  assert.equal(reasm.phase, "reassembling");
  assert.ok(reasm.masterExplode > 0.4 && reasm.masterExplode < 0.6);
});
