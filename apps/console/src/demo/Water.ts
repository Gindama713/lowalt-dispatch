import * as THREE from "three";

/** Decorative analytic ripples; the surface is not a hydrology simulation. */
export function createWater() {
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
        float t = uTime * 0.28;
        float waveA = sin(p.x * 0.76 + p.y * 0.53 - t);
        float waveB = cos(p.x * 1.81 - p.y * 1.14 + t * 0.7);
        vec3 N = normalize(vec3(0.09 * waveA, 1.0, 0.08 * waveB));
        vec3 V = normalize(cameraPosition - vWorld);
        vec3 L = normalize(vec3(-0.65, 1.0, 0.3));
        float fresnel = pow(1.0 - max(dot(N, V), 0.0), 3.5);
        float highlight = pow(max(dot(N, normalize(L + V)), 0.0), 74.0);
        float edge = smoothstep(7.5, 13.5, abs(p.x));
        float streak = pow(0.5 + 0.5 * sin(p.y * 0.51 + waveB * 0.5), 10.0);
        vec3 water = mix(vec3(0.012, 0.065, 0.099), vec3(0.048, 0.138, 0.177), fresnel);
        water += vec3(0.31, 0.20, 0.11) * highlight;
        water += vec3(0.025, 0.026, 0.019) * edge * streak;
        water += vec3(0.003, 0.011, 0.013) * (waveA + waveB);
        gl_FragColor = vec4(max(water, vec3(0.0)), 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }
    `,
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(27.8, 177.8), material);
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = -0.12;
  return mesh;
}
