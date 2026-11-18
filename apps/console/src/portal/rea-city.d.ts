declare module "*city-world.js" {
  export function buildCity(scene: import("three").Scene): {
    world: import("three").Group;
    stats: { buildings: number; widthMeters: number; depthMeters: number };
    update(dt: number): void;
  };
}
