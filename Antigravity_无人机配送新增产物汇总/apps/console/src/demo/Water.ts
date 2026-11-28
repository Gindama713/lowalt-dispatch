import * as THREE from "three";
import { RIVER_CENTER_X, RIVER_HALF_WIDTH, SHORELINE_Z } from "./city-layout";

/**
 * 10x City-Scale Shenzhen Bay ocean & Dasha River analytic water shader.
 * Purely visual; never used as hydrology or real-world terrain data.
 */
export function createWater() {
  const group = new THREE.Group();
  const material = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 } },
    vertexShader: `
      varying vec3 vWorld;
      void main() {
        vec4 world = modelMatrix * vec4(position, 1.0);
        vWorld = world.xyz;
        gl_Position = projectionMatrix * viewMatrix * world;
      }
    `,
    fragmentShader: `
      uniform float uTime;
      varying vec3 vWorld;
      void main() {
        vec2 p = vWorld.xz;
        float t = uTime * 0.34;
        float waveA = sin(p.x * 0.14 + p.y * 0.12 - t);
        float waveB = cos(p.x * 0.38 - p.y * 0.29 + t * 0.8);
        float waveC = sin((p.x + p.y) * 0.72 - t * 1.25);
        vec3 N = normalize(vec3(0.075 * waveA + 0.025 * waveC, 1.0, 0.065 * waveB));
        vec3 V = normalize(cameraPosition - vWorld);
        vec3 L = normalize(vec3(-0.62, 0.88, 0.38));
        float fresnel = pow(1.0 - max(dot(N, V), 0.0), 3.1);
        float highlight = pow(max(dot(N, normalize(L + V)), 0.0), 62.0);
        float shoreDist = max(0.0, p.y - 116.0);
        float shoreGlow = exp(-shoreDist * 0.055);
        float cityBounce = exp(-shoreDist * 0.011) * (0.5 + 0.5 * sin(p.x * 0.09 + waveB * 0.7));
        vec3 deepBay = vec3(0.010, 0.052, 0.092);
        vec3 horizonBay = vec3(0.044, 0.148, 0.198);
        vec3 water = mix(deepBay, horizonBay, fresnel);
        water += vec3(0.35, 0.22, 0.11) * highlight;
        water += vec3(0.058, 0.135, 0.15) * shoreGlow * (0.55 + 0.45 * waveC);
        water += vec3(0.048, 0.072, 0.088) * cityBounce;
        gl_FragColor = vec4(max(water, vec3(0.0)), 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }
    `,
  });

  // Expansive Shenzhen Bay ocean stretching 5,800 x 2,400 units into horizon fog
  const bay = new THREE.Mesh(new THREE.PlaneGeometry(5800, 2400), material);
  bay.rotation.x = -Math.PI / 2;
  bay.position.set(0, -0.35, SHORELINE_Z + 1196);
  group.add(bay);

  // Dasha River extending 790 units north through Nanshan–Futian into Tanglangshan
  const river = new THREE.Mesh(
    new THREE.PlaneGeometry(RIVER_HALF_WIDTH * 2 + 4, 800),
    material,
  );
  river.rotation.x = -Math.PI / 2;
  river.position.set(RIVER_CENTER_X, -0.25, SHORELINE_Z - 395);
  group.add(river);

  return Object.assign(group, { material });
}
