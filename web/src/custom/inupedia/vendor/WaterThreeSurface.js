/**
 * 引大济岷首页水面，派生自 WaterThreeJS 的 Gerstner 波谱与细节法线实现。
 * Source: https://github.com/achrefelouafi/WaterThreeJS
 * Copyright (c) 2026 mohamedachrefelouafi, MIT License.
 */
import * as THREE from 'three'

const NOISE = /* glsl */ `
  float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
  }

  vec3 noised(vec2 x) {
    vec2 p = floor(x);
    vec2 f = fract(x);
    vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
    vec2 du = 30.0 * f * f * (f * (f - 2.0) + 1.0);
    float a = hash21(p);
    float b = hash21(p + vec2(1.0, 0.0));
    float c = hash21(p + vec2(0.0, 1.0));
    float d = hash21(p + vec2(1.0));
    float k1 = b - a;
    float k2 = c - a;
    float k3 = a - b - c + d;
    float n = a + k1 * u.x + k2 * u.y + k3 * u.x * u.y;
    vec2 g = du * vec2(k1 + k3 * u.y, k2 + k3 * u.x);
    return vec3(n, g);
  }

  const mat2 FBM_M = mat2(1.6, 1.2, -1.2, 1.6);

  float fbm(vec2 p, int octaves) {
    float amplitude = 0.5;
    float sum = 0.0;
    for (int i = 0; i < 6; i++) {
      if (i >= octaves) break;
      sum += amplitude * noised(p).x;
      p = FBM_M * p;
      amplitude *= 0.5;
    }
    return sum;
  }
`

const GERSTNER_OCEAN = /* glsl */ `
  #define MAX_WAVES 24

  uniform float uTime;
  uniform vec2 uWindDir;
  uniform float uWaveCount;
  uniform float uBaseFreq;
  uniform float uAmplitude;
  uniform float uChoppy;
  uniform float uDirSpread;
  uniform float uFreqMul;
  uniform float uAmpMul;
  uniform float uSpeed;

  struct WaveSample {
    vec3 displacement;
    vec3 normal;
    float fold;
    float height;
  };

  WaveSample sampleOcean(vec2 position) {
    vec3 displacement = vec3(0.0);
    vec3 normal = vec3(0.0, 1.0, 0.0);
    float jxx = 1.0;
    float jzz = 1.0;
    float jxz = 0.0;
    float baseAngle = atan(uWindDir.y, uWindDir.x);
    float frequency = uBaseFreq;
    float amplitude = uAmplitude;
    int count = int(uWaveCount);

    for (int i = 0; i < MAX_WAVES; i++) {
      if (i >= count) break;
      float index = float(i);
      float randomDirection = hash21(vec2(index, 1.7));
      float randomPhase = hash21(vec2(index, 9.1));
      float angle = baseAngle + (randomDirection * 2.0 - 1.0) * uDirSpread;
      vec2 direction = vec2(cos(angle), sin(angle));
      float phaseSpeed = sqrt(9.81 * frequency) * uSpeed;
      float steepness = uChoppy / max(frequency * amplitude * uWaveCount, 0.001);
      float phase = frequency * dot(direction, position) + uTime * phaseSpeed
        + randomPhase * 6.2831853;
      float sine = sin(phase);
      float cosine = cos(phase);
      float waveAmplitude = frequency * amplitude;

      displacement.x += steepness * amplitude * direction.x * cosine;
      displacement.z += steepness * amplitude * direction.y * cosine;
      displacement.y += amplitude * sine;
      normal.x -= direction.x * waveAmplitude * cosine;
      normal.z -= direction.y * waveAmplitude * cosine;
      normal.y -= steepness * waveAmplitude * sine;
      jxx -= steepness * direction.x * direction.x * waveAmplitude * sine;
      jzz -= steepness * direction.y * direction.y * waveAmplitude * sine;
      jxz -= steepness * direction.x * direction.y * waveAmplitude * sine;
      frequency *= uFreqMul;
      amplitude *= uAmpMul;
    }

    WaveSample waveResult;
    waveResult.displacement = displacement;
    waveResult.normal = normalize(normal);
    waveResult.fold = jxx * jzz - jxz * jxz;
    waveResult.height = displacement.y;
    return waveResult;
  }
`

const DETAIL_NORMAL = /* glsl */ `
  vec3 detailNormal(vec2 point, float time, float strength) {
    vec2 gradient = vec2(0.0);
    float amplitude = 1.0;
    mat2 octaveMatrix = mat2(1.7, 1.1, -1.1, 1.7);
    vec2 flow = uWindDir * time * 0.6;

    for (int i = 0; i < 5; i++) {
      vec3 noise = noised(point + flow);
      gradient += amplitude * noise.yz;
      point = octaveMatrix * point;
      flow = -flow * 0.85;
      amplitude *= 0.55;
    }

    return normalize(vec3(-gradient.x, 1.0 / max(strength, 0.001), -gradient.y));
  }
`

const VERTEX_SHADER = /* glsl */ `
  precision highp float;
  ${NOISE}
  ${GERSTNER_OCEAN}

  varying vec3 vWorldPosition;
  varying vec3 vNormal;
  varying float vFold;
  varying float vHeight;

  void main() {
    vec3 worldPosition = (modelMatrix * vec4(position, 1.0)).xyz;
    WaveSample wave = sampleOcean(worldPosition.xz);
    vec3 displaced = worldPosition + wave.displacement;
    vWorldPosition = displaced;
    vNormal = wave.normal;
    vFold = wave.fold;
    vHeight = wave.height;
    gl_Position = projectionMatrix * viewMatrix * vec4(displaced, 1.0);
  }
`

const FRAGMENT_SHADER = /* glsl */ `
  precision highp float;

  uniform float uTime;
  uniform vec2 uWindDir;
  uniform vec3 uSunDirection;
  uniform vec3 uDeepColor;
  uniform vec3 uShallowColor;
  uniform vec3 uFoamColor;
  uniform float uDetailScale;
  uniform float uDetailStrength;
  uniform float uOpacity;

  ${NOISE}
  ${DETAIL_NORMAL}

  varying vec3 vWorldPosition;
  varying vec3 vNormal;
  varying float vFold;
  varying float vHeight;

  float fresnel(float cosine) {
    return 0.02 + 0.98 * pow(clamp(1.0 - cosine, 0.0, 1.0), 5.0);
  }

  void main() {
    vec3 viewDirection = normalize(cameraPosition - vWorldPosition);
    float distanceToCamera = length(cameraPosition - vWorldPosition);
    float detailFade = exp(-distanceToCamera * 0.018);
    vec3 normal = normalize(vNormal);
    vec3 detailA = detailNormal(vWorldPosition.xz * uDetailScale, uTime, 1.0);
    vec3 detailB = detailNormal(
      vWorldPosition.xz * uDetailScale * 4.1 + 17.0,
      uTime * 1.45,
      1.0
    );
    vec2 detail = detailA.xz * uDetailStrength
      + detailB.xz * uDetailStrength * 0.42 * detailFade;
    normal = normalize(vec3(normal.x + detail.x, normal.y, normal.z + detail.y));

    vec3 reflectedDirection = reflect(-viewDirection, normal);
    float skyBlend = pow(clamp(reflectedDirection.y * 0.5 + 0.5, 0.0, 1.0), 0.7);
    vec3 horizon = vec3(0.58, 0.72, 0.77);
    vec3 sky = vec3(0.77, 0.88, 0.91);
    vec3 reflection = mix(horizon, sky, skyBlend);
    float depth = smoothstep(8.0, 125.0, distanceToCamera);
    vec3 water = mix(uShallowColor, uDeepColor, depth);
    float fresnelAmount = fresnel(max(dot(normal, viewDirection), 0.0));
    vec3 color = mix(water, reflection, 0.22 + fresnelAmount * 0.72);

    vec3 halfVector = normalize(viewDirection + normalize(uSunDirection));
    float sunGlint = pow(max(dot(normal, halfVector), 0.0), 150.0);
    color += vec3(0.92, 0.97, 0.96) * sunGlint * 1.8;

    float breakEnergy = 1.0 - smoothstep(0.08, 0.72, vFold);
    float crestEnergy = smoothstep(0.34, 0.74, vHeight);
    vec2 foamFlow = uWindDir * uTime * 0.22;
    float foamNoise = fbm(vWorldPosition.xz * 0.34 - foamFlow, 5);
    float foam = smoothstep(0.52, 0.72, foamNoise)
      * clamp(breakEnergy * 0.72 + crestEnergy * 0.32, 0.0, 1.0);
    color = mix(color, uFoamColor, foam * 0.62);

    float nearOpacity = mix(0.92, 0.66, smoothstep(18.0, 150.0, distanceToCamera));
    gl_FragColor = vec4(color, uOpacity * nearOpacity);
  }
`

/** 创建适合门户首屏的 WaterThreeJS 派生水面。 */
export function createWaterThreeSurface({ lowPower = false } = {}) {
  const uniforms = {
    uTime: { value: 0 },
    uWindDir: { value: new THREE.Vector2(1, 0.34).normalize() },
    uWaveCount: { value: lowPower ? 11 : 16 },
    uBaseFreq: { value: (2 * Math.PI) / 46 },
    uAmplitude: { value: lowPower ? 0.27 : 0.36 },
    uChoppy: { value: 0.4 },
    uDirSpread: { value: 0.82 },
    uFreqMul: { value: 1.21 },
    uAmpMul: { value: 0.76 },
    uSpeed: { value: 0.5 },
    uSunDirection: { value: new THREE.Vector3(-0.25, 0.72, 0.42).normalize() },
    uDeepColor: { value: new THREE.Color('#073b55') },
    uShallowColor: { value: new THREE.Color('#4e969e') },
    uFoamColor: { value: new THREE.Color('#e8f2f0') },
    uDetailScale: { value: 0.34 },
    uDetailStrength: { value: lowPower ? 0.11 : 0.15 },
    uOpacity: { value: 0.9 }
  }
  const segments = lowPower ? [96, 64] : [180, 120]
  const geometry = new THREE.PlaneGeometry(240, 190, segments[0], segments[1])
  geometry.rotateX(-Math.PI / 2)
  const material = new THREE.ShaderMaterial({
    uniforms,
    vertexShader: VERTEX_SHADER,
    fragmentShader: FRAGMENT_SHADER,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide
  })
  const mesh = new THREE.Mesh(geometry, material)
  mesh.position.z = -58
  mesh.frustumCulled = false

  return {
    mesh,
    update(time) {
      uniforms.uTime.value = time
    },
    dispose() {
      geometry.dispose()
      material.dispose()
    }
  }
}
