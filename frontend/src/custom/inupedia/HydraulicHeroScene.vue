<template>
  <div ref="sceneHost" class="hydraulic-scene" aria-hidden="true">
    <div class="scene-background"></div>
    <canvas v-show="!fallback" ref="canvasElement" class="water-canvas"></canvas>
    <div v-if="fallback" class="scene-fallback"></div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as THREE from 'three'

import { createWaterThreeSurface } from './vendor/WaterThreeSurface'

const sceneHost = ref(null)
const canvasElement = ref(null)
const fallback = ref(false)
const pointer = new THREE.Vector2()
const targetPointer = new THREE.Vector2()
const lookTarget = new THREE.Vector3()

let renderer = null
let scene = null
let camera = null
let waterSurface = null
let resizeObserver = null
let animationFrame = null
let reducedMotion = false
let disposed = false

/** 按视口调整透视镜头，让动态水面从近景自然延伸至工程远景。 */
function configureCamera(width, height) {
  if (!camera) return
  const compact = width < 768
  camera.aspect = width / height
  camera.fov = compact ? 48 : 42
  camera.position.set(compact ? 1.8 : 0, compact ? 7.2 : 9.4, compact ? 22 : 25)
  lookTarget.set(compact ? 1.2 : 0, compact ? 8.6 : 11.6, compact ? -38 : -46)
  camera.lookAt(lookTarget)
  camera.updateProjectionMatrix()
}

function resizeScene() {
  if (!renderer || !camera || !sceneHost.value) return
  const width = Math.max(sceneHost.value.clientWidth, 1)
  const height = Math.max(sceneHost.value.clientHeight, 1)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, width < 768 ? 1.1 : 1.45))
  renderer.setSize(width, height, false)
  configureCamera(width, height)
  renderer.render(scene, camera)
}

function handlePointerMove(event) {
  if (reducedMotion) return
  targetPointer.set(
    (event.clientX / window.innerWidth - 0.5) * 2,
    (event.clientY / window.innerHeight - 0.5) * 2
  )
}

function renderFrame(time) {
  if (!renderer || !scene || !camera || disposed) return
  pointer.lerp(targetPointer, 0.025)
  const compact = sceneHost.value?.clientWidth < 768
  camera.position.x = (compact ? 1.8 : 0) + pointer.x * (compact ? 0.18 : 0.45)
  camera.position.y = (compact ? 7.2 : 9.4) - pointer.y * 0.12
  camera.lookAt(lookTarget)
  waterSurface?.update(time / 1000)
  renderer.render(scene, camera)
  animationFrame = window.requestAnimationFrame(renderFrame)
}

function handleVisibilityChange() {
  if (reducedMotion || disposed) return
  if (document.hidden) {
    if (animationFrame) window.cancelAnimationFrame(animationFrame)
    animationFrame = null
    return
  }
  if (!animationFrame) animationFrame = window.requestAnimationFrame(renderFrame)
}

/** 初始化 WaterThreeJS 派生水面，并在 WebGL 不可用时保留项目静态场景。 */
function initializeScene() {
  disposed = false
  reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  try {
    renderer = new THREE.WebGLRenderer({
      canvas: canvasElement.value,
      alpha: true,
      antialias: window.innerWidth >= 768,
      powerPreference: 'high-performance'
    })
  } catch (error) {
    console.warn('WaterThreeJS 水面初始化失败，已保留静态工程场景。', error)
    fallback.value = true
    return
  }

  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.setClearColor(0x000000, 0)
  scene = new THREE.Scene()
  camera = new THREE.PerspectiveCamera(42, 1, 0.1, 400)
  const lowPower = window.innerWidth < 768 || (navigator.hardwareConcurrency || 8) <= 4
  waterSurface = createWaterThreeSurface({ lowPower })
  scene.add(waterSurface.mesh)

  resizeObserver = new ResizeObserver(resizeScene)
  resizeObserver.observe(sceneHost.value)
  resizeScene()

  if (reducedMotion) {
    waterSurface.update(5.5)
    renderer.render(scene, camera)
    return
  }

  window.addEventListener('pointermove', handlePointerMove, { passive: true })
  document.addEventListener('visibilitychange', handleVisibilityChange)
  animationFrame = window.requestAnimationFrame(renderFrame)
}

function disposeScene() {
  disposed = true
  if (animationFrame) window.cancelAnimationFrame(animationFrame)
  window.removeEventListener('pointermove', handlePointerMove)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  resizeObserver?.disconnect()
  waterSurface?.dispose()
  renderer?.dispose()
  renderer?.forceContextLoss()
  renderer = null
  scene = null
  camera = null
  waterSurface = null
}

onMounted(initializeScene)
onBeforeUnmount(disposeScene)
</script>

<style lang="less" scoped>
.hydraulic-scene {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
  background: #dce8e9;
}

.scene-background,
.scene-fallback,
.water-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.scene-background {
  z-index: 0;
  background-image: url('/ydjm-luding-intake.jpg');
  background-position: center 48%;
  background-size: cover;
  filter: saturate(0.78) contrast(1.03) brightness(0.92);
  transform: scale(1.015);
}

.water-canvas {
  z-index: 1;
  display: block;
  clip-path: polygon(
    0 62%,
    18% 65%,
    36% 69%,
    54% 75%,
    70% 83%,
    84% 91%,
    100% 98%,
    100% 100%,
    0 100%
  );
}

.hydraulic-scene::before,
.hydraulic-scene::after {
  position: absolute;
  inset: 0;
  z-index: 2;
  content: '';
  pointer-events: none;
}

.hydraulic-scene::before {
  background: linear-gradient(
    90deg,
    rgba(245, 249, 249, 0.97) 0%,
    rgba(245, 249, 249, 0.9) 21%,
    rgba(245, 249, 249, 0.48) 40%,
    rgba(245, 249, 249, 0.07) 63%,
    transparent 80%
  );
}

.hydraulic-scene::after {
  background:
    linear-gradient(180deg, rgba(230, 242, 245, 0.34), transparent 26%),
    linear-gradient(0deg, rgba(229, 239, 240, 0.56), transparent 22%);
}

.scene-fallback {
  z-index: 1;
  background: linear-gradient(
    180deg,
    transparent 48%,
    rgba(29, 89, 105, 0.5) 63%,
    rgba(9, 52, 75, 0.78) 100%
  );
}

@media (max-width: 1023px) {
  .scene-background {
    background-position: 62% center;
  }

  .hydraulic-scene::before {
    background: linear-gradient(
      180deg,
      rgba(245, 249, 249, 0.9) 0%,
      rgba(245, 249, 249, 0.52) 31%,
      rgba(245, 249, 249, 0.08) 62%,
      transparent 80%
    );
  }

  .water-canvas {
    clip-path: polygon(0 64%, 22% 67%, 45% 72%, 66% 78%, 84% 86%, 100% 93%, 100% 100%, 0 100%);
  }
}

@media (max-width: 767px) {
  .water-canvas {
    clip-path: polygon(0 69%, 24% 71%, 48% 75%, 72% 80%, 100% 87%, 100% 100%, 0 100%);
  }
}

@media (prefers-reduced-motion: reduce) {
  .scene-background {
    transform: none;
  }
}
</style>
