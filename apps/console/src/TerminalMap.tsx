import { Fragment, useEffect, useMemo, useState } from "react";
import { pointAlong, TERRAIN_SIZE, type TerrainModel } from "./terrain";
import type { Layers, Point, SceneData } from "./types";
import "./terminalMap.css";

const COLUMNS = 64;
const ROWS = 22;
const FRAME = "+" + "-".repeat(COLUMNS) + "+";
const TICKS = [0, 1000, 2000, 3000];

type Ink =
  | "terrain"
  | "building"
  | "zone"
  | "route"
  | "site"
  | "preview"
  | "comparison"
  | "frame"
  | "cursor";
type Glyph = { text: string; ink: Ink; at?: number };

function contains([x, y]: Point, polygon: Point[]) {
  let inside = false;
  for (
    let i = 0, previous = polygon.length - 1;
    i < polygon.length;
    previous = i++
  ) {
    const [x1, y1] = polygon[previous];
    const [x2, y2] = polygon[i];
    if (y1 > y !== y2 > y && x < x1 + ((x2 - x1) * (y - y1)) / (y2 - y1))
      inside = !inside;
  }
  return inside;
}

function cell([x, y]: Point): Point | null {
  if (x < 0 || y < 0 || x > TERRAIN_SIZE || y > TERRAIN_SIZE) return null;
  return [
    Math.min(COLUMNS - 1, Math.floor((x / TERRAIN_SIZE) * COLUMNS)),
    Math.min(ROWS - 1, Math.floor((1 - y / TERRAIN_SIZE) * ROWS)),
  ];
}

function terminalGrid(
  scene: SceneData,
  layers: Layers,
  terrainModel: TerrainModel,
  preview?: Point[],
  comparison?: Point[],
) {
  const width = TERRAIN_SIZE / COLUMNS;
  const height = TERRAIN_SIZE / ROWS;
  const grid = Array.from({ length: ROWS }, (_, y) =>
    Array.from({ length: COLUMNS }, (_, x): Glyph | null => {
      const east = (x + 0.5) * width;
      const north = TERRAIN_SIZE - (y + 0.5) * height;
      const position: Point = [east, north];
      if (
        layers.restrictions &&
        scene.zones.some((zone) => contains(position, zone.polygon))
      ) {
        return { text: "X", ink: "zone" };
      }
      if (
        layers.buildings &&
        scene.buildings.some((building) => contains(position, building.polygon))
      ) {
        return { text: "#", ink: "building" };
      }
      if (!layers.terrain) return null;
      const elevation = terrainModel.heightAt(east, north);
      const band = Math.min(3, Math.floor(Math.max(0, elevation) / 20));
      return band ? { text: ".:="[band - 1], ink: "terrain" } : null;
    }),
  );
  function mark(point: Point | undefined, text: string, ink: Ink) {
    const position = point && cell(point);
    if (position) grid[position[1]][position[0]] = { text, ink };
  }
  function line(points: Point[], text: string, ink: Ink, timeline?: number[]) {
    let last: Point | null = null;
    for (const [index, point] of points.entries()) {
      const next = cell(point);
      if (last && next) {
        const dx = next[0] - last[0];
        const dy = next[1] - last[1];
        const steps = Math.max(Math.abs(dx), Math.abs(dy));
        for (let step = 1; step <= steps; step++) {
          const fraction = step / steps;
          const at =
            timeline &&
            timeline[index - 1] +
              (timeline[index] - timeline[index - 1]) * fraction;
          grid[Math.round(last[1] + dy * fraction)][
            Math.round(last[0] + dx * fraction)
          ] = { text, ink, at };
        }
      } else {
        mark(point, text, ink);
      }
      last = next;
    }
  }
  if (layers.routes) {
    const distance = [0];
    for (let index = 1; index < scene.route.length; index++) {
      const [x, y] = scene.route[index];
      const [lastX, lastY] = scene.route[index - 1];
      distance.push(distance[index - 1] + Math.hypot(x - lastX, y - lastY));
    }
    const total = distance.at(-1) || 1;
    line(
      scene.route,
      "*",
      "route",
      distance.map((meters) => meters / total),
    );
    if (comparison) line(comparison, "=", "comparison");
    if (preview) line(preview, "+", "preview");
    for (const site of scene.sites) mark(site.point, "L", "site");
    mark(scene.route[0], "S", "route");
    mark(scene.route.at(-1), "D", "route");
  }
  return grid;
}

export function TerminalMap({
  layers,
  terrainModel,
  progress,
  playing,
  preview,
  comparison,
}: {
  layers: Layers;
  terrainModel: TerrainModel;
  progress: number;
  playing: boolean;
  preview?: Point[];
  comparison?: Point[];
}) {
  const [scene, setScene] = useState<SceneData | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/demo-scene.json", { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("Scene unavailable");
        return response.json();
      })
      .then((data: SceneData) => setScene(data))
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, []);
  const revision = terrainModel.revision;
  const grid = useMemo(
    () =>
      scene && terminalGrid(scene, layers, terrainModel, preview, comparison),
    [scene, layers, terrainModel, revision, preview, comparison],
  );
  const position = scene?.route.length
    ? pointAlong(scene.route, progress)
    : null;
  const cursor = position && layers.routes ? cell(position) : null;
  const percent = Math.round(progress * 100);
  return (
    <figure className="map-stage terminal-map" aria-label="ASCII 终端地图">
      <div className="terminal-plot">
        {grid ? (
          <div className="terminal-sheet" aria-hidden="true">
            <span className="terminal-north">^ N</span>
            <div className="terminal-ticks terminal-ticks-n">
              {TICKS.map((tick) => (
                <span key={tick}>{TERRAIN_SIZE - tick}</span>
              ))}
            </div>
            <pre className="terminal-grid" data-playing={playing}>
              <span data-ink="frame">{FRAME}</span>
              {"\n"}
              {grid.map((row, y) => {
                const runs: {
                  text: string;
                  ink?: Ink;
                  at?: number;
                  column: number;
                }[] = [];
                row.forEach((glyph, x) => {
                  const pixel: Glyph | null =
                    cursor?.[0] === x && cursor[1] === y
                      ? { text: "@", ink: "cursor" }
                      : glyph;
                  const last = runs.at(-1);
                  const text = pixel?.text ?? " ";
                  if (
                    last &&
                    last.ink === pixel?.ink &&
                    last.at === undefined &&
                    pixel?.at === undefined
                  )
                    last.text += text;
                  else
                    runs.push({
                      text,
                      ink: pixel?.ink,
                      at: pixel?.at,
                      column: x,
                    });
                });
                return (
                  <Fragment key={y}>
                    <span
                      className="terminal-row"
                      style={{ animationDelay: `${y * 14}ms` }}
                    >
                      <span data-ink="frame">|</span>
                      {runs.map(({ text, ink, at, column }) => (
                        <span
                          key={column}
                          data-ink={ink}
                          data-flight={
                            at === undefined
                              ? undefined
                              : at > progress
                                ? "upcoming"
                                : "passed"
                          }
                          data-trail={
                            at !== undefined &&
                            playing &&
                            at <= progress &&
                            progress - at < 0.065
                              ? ""
                              : undefined
                          }
                          style={
                            at === undefined
                              ? undefined
                              : { animationDelay: `${220 + at * 560}ms` }
                          }
                        >
                          {text}
                        </span>
                      ))}
                      <span data-ink="frame">|</span>
                    </span>
                    {"\n"}
                  </Fragment>
                );
              })}
              <span data-ink="frame">{FRAME}</span>
            </pre>
            <div className="terminal-ticks terminal-ticks-e">
              {TICKS.map((tick) => (
                <span key={tick}>{tick}</span>
              ))}
            </div>
            <span className="terminal-east">E &gt;</span>
          </div>
        ) : (
          <p role={failed ? "alert" : "status"}>
            {failed ? "演示场景读取失败，可切回地图后重试。" : "读取演示场景…"}
          </p>
        )}
      </div>
      <figcaption>
        <div className="terminal-meta">
          <span>
            演示场景 · ENU · {TERRAIN_SIZE / 1000} × {TERRAIN_SIZE / 1000} km
          </span>
          {position && (
            <div className="terminal-position" aria-label="回放位置">
              <code data-ink="cursor">@</code>
              <code>E {position[0].toFixed(0)} m</code>
              <code>N {position[1].toFixed(0)} m</code>
              <code title="航图回放进度">{percent}%</code>
            </div>
          )}
        </div>
        {scene && (
          <div className="terminal-legend">
            {layers.buildings && (
              <span>
                <code data-ink="building">#</code> 建筑 {scene.buildings.length}
              </span>
            )}
            {layers.restrictions && (
              <span>
                <code data-ink="zone">X</code> S1-01 限制区 {scene.zones.length}{" "}
                · 均未生效
              </span>
            )}
            {layers.routes && (
              <>
                <span>
                  <code data-ink="route">*</code> 基线航线
                </span>
                <span>
                  <code data-ink="route">S/D</code> 起终点
                </span>
                <span>
                  <code data-ink="site">L</code> 备降点 {scene.sites.length}
                </span>
                {preview && (
                  <span>
                    <code data-ink="preview">+</code> 助手预览
                  </span>
                )}
                {comparison && (
                  <span>
                    <code data-ink="comparison">=</code> 方案对照
                  </span>
                )}
              </>
            )}
            {layers.terrain && (
              <span>
                <code data-ink="terrain">.:=</code> 地形高度
              </span>
            )}
          </div>
        )}
      </figcaption>
    </figure>
  );
}
