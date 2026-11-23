import test from "node:test";
import assert from "node:assert/strict";
import {
  chapters,
  DURATION,
  frameAt,
  timeLabel,
  visualViewAt,
} from "../src/demo/playback.ts";

import { landmarks, makeCityLots } from "../src/demo/city-layout.ts";

test("fictional city has stable districts and unobstructed visual landmark labels", () => {
  const lots = makeCityLots();
  assert.deepEqual(lots, makeCityLots());
  assert.equal(lots.length, 51);
  assert.deepEqual([...new Set(lots.map((lot) => lot.style))].sort(), [
    "office",
    "residential",
    "warehouse",
  ]);
  for (const lot of lots) {
    assert.ok(lot.width > 0 && lot.depth > 0 && lot.height > 0);
    assert.ok(Math.abs(lot.x) - lot.width / 2 > 14);
    for (const point of landmarks) {
      assert.ok(Math.hypot(lot.x - point.x, lot.z - point.z) >= 15);
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
