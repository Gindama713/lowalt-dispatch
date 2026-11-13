import { MercatorCoordinate } from "maplibre-gl";
import { sampleWind, WIND_REGION, type WindField } from "./weather";

export const WIND_MAX_ZOOM = 10.75;
export const WIND_COLORS = [
  "#354b68",
  "#376783",
  "#35877d",
  "#74a688",
  "#c5a56e",
];
const STOPS = [0, 2, 4, 7, 10];
const SIZE = 512;
const { west, east, south, north } = WIND_REGION;
const top = MercatorCoordinate.fromLngLat([west, north]);
const bottom = MercatorCoordinate.fromLngLat([east, south]);
type Pixel = [x: number, y: number];

function windAtPixel(field: WindField, x: number, y: number) {
  const point = new MercatorCoordinate(
    top.x + ((bottom.x - top.x) * x) / SIZE,
    top.y + ((bottom.y - top.y) * y) / SIZE,
  ).toLngLat();
  return sampleWind(field, [point.lng, point.lat]);
}

export function createWindLayer(field: WindField) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SIZE;
  const ctx = canvas.getContext("2d")!;
  const background = document.createElement("canvas");
  background.width = background.height = 128;
  const colors = WIND_COLORS.map((hex) =>
    [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)),
  );
  const bg = background.getContext("2d")!;
  const img = bg.createImageData(128, 128);
  for (let y = 0; y < 128; y += 1) {
    for (let x = 0; x < 128; x += 1) {
      const wind = windAtPixel(field, (x + 0.5) * 4, (y + 0.5) * 4);
      if (!wind) continue;
      const speed = Math.min(10, Math.hypot(...wind));
      const stop = STOPS.findIndex((v) => v >= speed);
      const low = Math.max(0, stop - 1);
      const t =
        low === stop ? 0 : (speed - STOPS[low]) / (STOPS[stop] - STOPS[low]);
      const i = 4 * (y * 128 + x);
      for (let c = 0; c < 3; c += 1)
        img.data[i + c] =
          colors[low][c] + t * (colors[stop][c] - colors[low][c]);
      img.data[i + 3] =
        162 * Math.min(1, x / 16, y / 16, (127 - x) / 16, (127 - y) / 16);
    }
  }
  bg.putImageData(img, 0, 0);

  // Precompute the same paths for static arrows and motion. The render loop only paints.
  const paths: { points: Pixel[]; speed: number; phase: number }[] = [];
  for (let row = 0; row < 15; row += 1) {
    for (let col = 0; col < 15; col += 1) {
      const phase = ((col * 41 + row * 23) % 97) / 97;
      let x = 13 + col * 33 + phase * 11;
      let y = 13 + row * 33 + (1 - phase) * 11;
      const points: Pixel[] = [[x, y]];
      let speed = 0;
      for (let step = 0; step < 12; step += 1) {
        const wind = windAtPixel(field, x, y);
        if (!wind) break;
        const magnitude = Math.hypot(...wind);
        if (magnitude < 0.25) break;
        if (step === 0) speed = magnitude;
        x += (2.5 * wind[0]) / magnitude;
        y -= (2.5 * wind[1]) / magnitude;
        if (x < 4 || y < 4 || x > SIZE - 4 || y > SIZE - 4) break;
        points.push([x, y]);
      }
      if (points.length >= 5) paths.push({ points, speed, phase });
    }
  }

  const draw = (elapsed?: number) => {
    ctx.clearRect(0, 0, SIZE, SIZE);
    ctx.drawImage(background, 0, 0, SIZE, SIZE);
    ctx.lineWidth = 1.15;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#def8f2";
    ctx.beginPath();
    for (const { points, phase, speed } of paths) {
      if (elapsed === undefined) {
        const [a, , b, c] = points;
        ctx.moveTo(...a);
        ctx.lineTo(...b);
        const angle = Math.atan2(c[1] - b[1], c[0] - b[0]);
        ctx.lineTo(...c);
        ctx.moveTo(
          c[0] - 3 * Math.cos(angle - 0.6),
          c[1] - 3 * Math.sin(angle - 0.6),
        );
        ctx.lineTo(...c);
        ctx.lineTo(
          c[0] - 3 * Math.cos(angle + 0.6),
          c[1] - 3 * Math.sin(angle + 0.6),
        );
      } else {
        const head =
          ((phase + elapsed * (0.22 + Math.min(speed, 12) * 0.05)) % 1) *
          (points.length + 4);
        const last = Math.min(points.length - 1, head);
        const first = Math.max(0, head - 4);
        if (first >= last) continue;
        // Fractional endpoints keep the short trails from stepping between vertices.
        const at = (t: number): Pixel => {
          const a = points[Math.floor(t)],
            b = points[Math.ceil(t)];
          const f = t % 1;
          return [a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])];
        };
        ctx.moveTo(...at(first));
        for (let i = Math.ceil(first); i < last; i += 1)
          ctx.lineTo(...points[i]);
        ctx.lineTo(...at(last));
      }
    }
    ctx.globalAlpha = elapsed === undefined ? 0.45 : 0.7;
    ctx.stroke();
    ctx.globalAlpha = 1;
  };
  draw();
  return { canvas, draw };
}
