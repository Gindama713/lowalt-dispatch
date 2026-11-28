import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { readTaskEvidence } from "../src/assistant/taskEvidence.ts";
import { readPresentation } from "../src/assistant/presentation.ts";
import { RoutePolyline } from "../src/routeGeometry.ts";
import { Vector3 } from "three";
import { sampleWind, windRegionFor } from "../src/weather.ts";
import {
  chapters,
  DURATION,
  frameAt,
  timeLabel,
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
import { frozenEvalBaseline, studioExplodeAt } from "../src/demo/playback.ts";

test("environment UI v2 accepts evidence and rejects malformed nested blocks", () => {
  const base = { title: "environment", source: "test", as_of: null, note: "" };
  const factor = {
    id: "wind",
    name: "wind",
    status: "unavailable",
    value: null,
    unit: "m/s",
    threshold: null,
    threshold_source: null,
    effect: "hard",
    segment_index: null,
    reason: "no data",
  };
  const block = {
    ...base,
    type: "env_matrix",
    verdict: "unknown",
    verdict_reason: "missing data",
    factors: [factor],
    coverage_statement: "not continuous",
    evidence_id: "env-123456789abc",
  };
  assert.equal(
    readPresentation({ version: 2, blocks: [block] }).blocks[0].type,
    "env_matrix",
  );
  assert.equal(
    readPresentation({ version: 2, blocks: [{ ...block, factors: [null] }] }),
    undefined,
  );
  assert.equal(
    readPresentation({
      version: 2,
      blocks: [{ ...base, type: "gaps", total: 1, items: [null] }],
    }),
    undefined,
  );
  assert.equal(
    readPresentation({
      version: 2,
      blocks: [
        { ...base, type: "time_window", caveat: "test", options: [null, null] },
      ],
    }),
    undefined,
  );
});

test("frozen task contracts accept both cases and reject contradictory or malformed data", () => {
  const bundle = JSON.parse(
    readFileSync(
      new URL("../public/task-evidence.json", import.meta.url),
      "utf8",
    ),
  );
  assert.equal(readTaskEvidence(bundle.cases.main).task_id, "T-S1-02");
  assert.equal(readTaskEvidence(bundle.cases.contrast).verdict, "rejected");
  assert.equal(
    readTaskEvidence({ ...bundle.cases.contrast, verdict: "passed" }),
    undefined,
  );
  assert.equal(
    readTaskEvidence({ ...bundle.cases.main, samples: [] }),
    undefined,
  );
  assert.equal(readTaskEvidence({ ...bundle.cases.main, gaps: [] }), undefined);
  assert.equal(
    readTaskEvidence({ ...bundle.cases.main, payload_kg: NaN }),
    undefined,
  );
});

test("shenzhen art city layout is deterministic and keeps pads clear", () => {
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
  assert.equal(frameAt(142, true).status, "几何航线回放结束 · 未下发");
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

test("rendered route preserves corners and uses the same horizontal progress as maps", () => {
  const curve = new RoutePolyline([
    new Vector3(0, 0, 0),
    new Vector3(10, 99, 0),
    new Vector3(10, 100, 10),
  ]);
  assert.deepEqual(curve.getPointAt(0.25).toArray(), [5, 49.5, 0]);
  assert.deepEqual(curve.getPointAt(0.5).toArray(), [10, 99, 0]);
  assert.deepEqual(curve.getPointAt(0.75).toArray(), [10, 99.5, 5]);
  for (const p of curve.getPoints(100))
    assert.ok(Math.abs(p.z) < 1e-9 || Math.abs(p.x - 10) < 1e-9);
});

test("wind fields cover the selected city and never reuse another region's grid", () => {
  const point = [115.83, 28.76];
  const region = windRegionFor(point);
  const field = {
    region,
    validAt: "2026-11-25T00:00:00Z",
    vectors: Array.from({ length: 121 }, () => [3, -1]),
  };
  assert.deepEqual(sampleWind(field, point), [3, -1]);
  assert.equal(sampleWind(field, [121.47, 31.23]), null);
  assert.ok(region.west <= point[0] && region.east >= point[0]);
});

test("studio explode factor and historical frozen snapshot stay labeled", () => {
  assert.equal(studioExplodeAt("assembled", 42), 0);
  assert.equal(studioExplodeAt("exploded", 0), 1);
  assert.equal(studioExplodeAt("auto", 42), 1);
  assert.equal(frozenEvalBaseline.commit, "e9674ab");
  assert.match(frozenEvalBaseline.vehicleNote, /非实飞/);
  assert.equal(frozenEvalBaseline.diversionUnsafeRoutes, 0);
});

test("backdrop cycle visits each subsystem without claiming a flight", () => {
  assert.equal(smootherstep(0), 0);
  assert.equal(smootherstep(1), 1);
  assert.equal(evaluateDroneCycle(0).phase, "assembled");
  assert.equal(
    evaluateDroneCycle(DRONE_CYCLE_PERIOD).phase,
    evaluateDroneCycle(0).phase,
  );
  assert.equal(smoothBell(0.5), 1);
  for (const spot of SUBSYSTEM_SPOTLIGHTS) {
    assert.ok(spot.id);
    assert.ok(spot.systems.length > 0);
  }
});
