import * as T from "three";

export type PartScope = {
  id: string;
  label: string;
  count: number;
  local: boolean;
};

const sides: Record<string, string> = {
  FL: "左前",
  FR: "右前",
  RL: "左后",
  RR: "右后",
};
const components: Record<string, string> = {
  MOTOR: "电机",
  PROP: "螺旋桨",
  ESC: "电调",
  LEG: "起落架",
};

export function inspectAssembly(root: T.Object3D) {
  const scopes = new Map<string, PartScope>();
  const bounds = new Map<string, T.Box3>();
  const pickTargets: T.Mesh[] = [];
  const pickScopes = new Map<T.Object3D, string>();
  const parts: {
    node: T.Object3D;
    system: string;
    local: string;
    origin: T.Vector3;
    offset: T.Vector3;
    closeOffset: T.Vector3;
    assembled: T.Box3;
    stagger: number;
    progress: number;
  }[] = [];
  const surfaces: {
    mesh: T.Mesh;
    original: T.Material | T.Material[];
    lit: T.Material | T.Material[];
    system: string;
    local: string;
  }[] = [];
  const accents = new Map<T.Material, T.Material>();
  const ghost = new T.MeshBasicMaterial({
    color: 0x89adc8,
    transparent: true,
    opacity: 0.045,
    depthWrite: false,
  });
  function accent(material: T.Material) {
    let lit = accents.get(material);
    if (!lit) {
      // The model's gold anodized rotor shells carry a display emissive value.
      // Keep the status LEDs luminous while revealing reflection detail on metal.
      if (
        material instanceof T.MeshStandardMaterial &&
        material.metalness > 0.9 &&
        material.emissiveIntensity > 1
      )
        material.emissiveIntensity = 0.07;
      lit = material.clone();
      if (lit instanceof T.MeshStandardMaterial) {
        lit.emissive.lerp(new T.Color(0x51afbb), 0.045);
      }
      accents.set(material, lit);
    }
    return lit;
  }
  root.updateWorldMatrix(true, true);
  root.traverse((node) => {
    const { system, explodeDir, explodeDist, stagger } = node.userData;
    if (
      !system ||
      !Array.isArray(explodeDir) ||
      typeof explodeDist !== "number"
    )
      return;
    const parent = node.parent!;
    const directional =
      /^(?:PWR|LAND)_(MOTOR|PROP|ESC|LEG)-(FL|FR|RL|RR)$/.exec(parent.name);
    const local = directional ? parent.name : system;
    const offset = new T.Vector3()
      .fromArray(explodeDir)
      .multiplyScalar(explodeDist);
    const assembled = new T.Box3().setFromObject(node);
    parts.push({
      node,
      system,
      local,
      origin: node.position.clone(),
      offset,
      closeOffset: offset.clone(),
      assembled,
      stagger: Number(stagger) || 0,
      progress: 0,
    });
    // Multi-material GLTF parts can be groups. Move the authored node once and pick its child meshes.
    node.traverse((child) => {
      if (!(child instanceof T.Mesh)) return;
      const original = child.material as T.Material | T.Material[];
      surfaces.push({
        mesh: child,
        original,
        lit: Array.isArray(original) ? original.map(accent) : accent(original),
        system,
        local,
      });
      pickTargets.push(child);
      pickScopes.set(child, local);
    });
    const displacement = offset
      .clone()
      .applyMatrix3(new T.Matrix3().setFromMatrix4(parent.matrixWorld));
    const envelope = assembled.clone().translate(displacement).union(assembled);
    function register(id: string, label: string, isLocal: boolean) {
      if (!scopes.has(id)) {
        scopes.set(id, { id, label, count: 0, local: isLocal });
        bounds.set(id, new T.Box3());
      }
      scopes.get(id)!.count++;
      bounds.get(id)!.union(envelope);
    }
    register(system, parent.parent?.userData.labelZh || system, false);
    if (directional)
      register(local, sides[directional[2]] + components[directional[1]], true);
  });
  // In a close-up the motor and prop hardware separate along their common shaft.
  // Frame that stack at component scale instead of flying it across the whole aircraft.
  for (const scope of scopes.values()) {
    if (!scope.local) continue;
    const group = parts.filter((part) => part.local === scope.id);
    const box = bounds.get(scope.id)!.makeEmpty();
    group.forEach((part) => box.union(part.assembled));
    const size = box.getSize(new T.Vector3());
    const gap = Math.max(0.065, size.y * 0.52, Math.max(size.x, size.z) * 0.16);
    group.sort(
      (a, b) =>
        a.assembled.min.y +
          a.assembled.max.y -
          b.assembled.min.y -
          b.assembled.max.y || a.stagger - b.stagger,
    );
    group.forEach((part, index) => {
      const basis = new T.Matrix3().setFromMatrix4(
        part.node.parent!.matrixWorld,
      );
      if (scope.id.startsWith("LAND")) part.closeOffset.multiplyScalar(0.45);
      else
        part.closeOffset
          .set(0, (index - (group.length - 1) / 2) * gap, 0)
          .applyMatrix3(basis.clone().invert());
      box.union(
        part.assembled
          .clone()
          .translate(part.closeOffset.clone().applyMatrix3(basis)),
      );
    });
  }
  let selection = "";
  const destination = new T.Vector3();
  const anchors = new Map<string, T.Vector3>();
  for (const id of ["PWR_MOTOR-FL", "BAT"]) {
    const box = new T.Box3();
    for (const part of parts)
      if (part.local === id || part.system === id) box.union(part.assembled);
    if (!box.isEmpty()) anchors.set(id, box.getCenter(new T.Vector3()));
  }
  return {
    scopes: Array.from(scopes.values()),
    count: parts.length,
    bounds,
    anchors,
    pick(ray: T.Raycaster) {
      const hits = ray.intersectObjects(pickTargets, false);
      // See through the faded shell when inspecting an internal system.
      const hit =
        hits.find(({ object }) => (object as T.Mesh).material !== ghost) ??
        hits[0];
      return hit && pickScopes.get(hit.object);
    },
    select(id: string) {
      selection = id;
      for (const { mesh, original, lit, system, local } of surfaces)
        mesh.material = !id
          ? original
          : id === system || id === local
            ? lit
            : ghost;
    },
    update(value: number, blend: number) {
      let active = 0;
      for (const part of parts) {
        const target =
          !selection || selection === part.system || selection === part.local
            ? value
            : 0;
        if (part.progress !== target) {
          part.progress = T.MathUtils.lerp(part.progress, target, blend);
          if (Math.abs(part.progress - target) < 0.0004) part.progress = target;
        }
        if (part.progress || !part.node.position.equals(part.origin)) {
          const amount = T.MathUtils.smoothstep(
            part.progress,
            part.stagger * 0.18,
            0.8 + part.stagger * 0.18,
          );
          destination
            .copy(part.origin)
            .addScaledVector(
              selection === part.local ? part.closeOffset : part.offset,
              amount,
            );
          if (part.node.position.distanceToSquared(destination) < 1e-9)
            part.node.position.copy(destination);
          else part.node.position.lerp(destination, 1 - (1 - blend) ** 3);
        }
        if (
          target > 0 ||
          !selection ||
          selection === part.system ||
          selection === part.local
        )
          active = Math.max(active, part.progress);
      }
      return active;
    },
    dispose() {
      for (const { mesh, original } of surfaces) mesh.material = original;
      accents.forEach((material) => material.dispose());
      ghost.dispose();
    },
  };
}
