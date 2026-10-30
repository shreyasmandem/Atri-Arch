/* ═══════════════════════════════════════════════════════════════════════
   Denoise: clean grain out of a young path-traced picture, keep its edges.

   The scene is drawn once more, plainly, at the trace's size, to learn
   what each pixel shows: which way the surface faces, how far off it is,
   and its own colour. The traced light is divided by that colour (so the
   weave of a rug or the grain of a floor is not blurred away), smoothed
   in widening steps across pixels that face the same way at the same
   depth, then the colour is laid back on. A wall's grain melts into an
   even wash; the line where it meets the ceiling stays sharp.
   ═══════════════════════════════════════════════════════════════════════ */

import * as THREE from "three";
import { FullScreenQuad } from "three/addons/postprocessing/Pass.js";

const VERT = /* glsl */`
varying vec2 vUv;
void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

const LUM = /* glsl */`
float lum(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }`;

// Which way each surface faces (towards the camera) and how far it is.
const guideMaterial = () => new THREE.ShaderMaterial({
  side: THREE.DoubleSide,
  vertexShader: /* glsl */`
    varying vec3 vW;
    varying float vZ;
    void main() {
      vec4 w = modelMatrix * vec4(position, 1.0);
      vW = w.xyz;
      vec4 mv = viewMatrix * w;
      vZ = -mv.z;
      gl_Position = projectionMatrix * mv;
    }`,
  fragmentShader: /* glsl */`
    varying vec3 vW;
    varying float vZ;
    void main() {
      vec3 n = normalize(cross(dFdx(vW), dFdy(vW)));
      if (dot(n, cameraPosition - vW) < 0.0) n = -n;
      gl_FragColor = vec4(n, vZ);
    }`,
});

// Light alone: the traced colour over the surface's own, with lone bright
// specks (a ray that struck a lamp by luck) brought down to their neighbours.
const splitMaterial = () => new THREE.ShaderMaterial({
  uniforms: { tColor: { value: null }, tAlb: { value: null }, res: { value: new THREE.Vector2() } },
  vertexShader: VERT,
  fragmentShader: /* glsl */`
    uniform sampler2D tColor, tAlb;
    uniform vec2 res;
    varying vec2 vUv;
    ${LUM}
    vec3 light(vec2 uv) { return texture2D(tColor, uv).rgb / max(texture2D(tAlb, uv).rgb, vec3(0.04)); }
    void main() {
      vec3 c = light(vUv);
      float top = 0.0;
      for (int j = -1; j <= 1; j++) for (int i = -1; i <= 1; i++) {
        if (i == 0 && j == 0) continue;
        top = max(top, lum(light(vUv + vec2(i, j) / res)));
      }
      float l = lum(c), cap = top * 1.25 + 1e-4;
      if (l > cap) c *= cap / l;
      gl_FragColor = vec4(c, 1.0);
    }`,
});

// One widening step of the smoothing (an "a-trous" pass): a 5x5 spread of
// pixels `stepSize` apart, each weighted by how alike its surface is.
const atrousMaterial = () => new THREE.ShaderMaterial({
  uniforms: {
    tIrr: { value: null }, tND: { value: null }, res: { value: new THREE.Vector2() },
    stepSize: { value: 1 }, sigmaL: { value: 1 }, sigmaZ: { value: 0.02 }, sigmaN: { value: 64 },
  },
  vertexShader: VERT,
  fragmentShader: /* glsl */`
    uniform sampler2D tIrr, tND;
    uniform vec2 res;
    uniform float stepSize, sigmaL, sigmaZ, sigmaN;
    varying vec2 vUv;
    ${LUM}
    float k(int i) { return i == 0 ? 0.375 : (i == 1 ? 0.25 : 0.0625); }
    void main() {
      vec4 nd = texture2D(tND, vUv);
      vec3 c0 = texture2D(tIrr, vUv).rgb;
      if (nd.w <= 0.0) { gl_FragColor = vec4(c0, 1.0); return; }
      float l0 = lum(c0);
      vec3 sum = vec3(0.0);
      float wsum = 0.0;
      for (int j = -2; j <= 2; j++) for (int i = -2; i <= 2; i++) {
        vec2 uv = vUv + vec2(i, j) * stepSize / res;
        vec4 q = texture2D(tND, uv);
        if (q.w <= 0.0) continue;
        vec3 cq = texture2D(tIrr, uv).rgb;
        float w = k(i < 0 ? -i : i) * k(j < 0 ? -j : j)
          * pow(max(0.0, dot(nd.xyz, q.xyz)), sigmaN)
          * exp(-abs(nd.w - q.w) / (sigmaZ * nd.w * stepSize + 1e-4))
          * exp(-abs(l0 - lum(cq)) / (sigmaL * (l0 + 0.05)));
        sum += cq * w;
        wsum += w;
      }
      gl_FragColor = vec4(sum / max(wsum, 1e-6), 1.0);
    }`,
});

// The smoothed light with the surfaces' colours laid back on, to the screen.
const joinMaterial = () => new THREE.ShaderMaterial({
  uniforms: { tIrr: { value: null }, tAlb: { value: null }, tColor: { value: null }, tND: { value: null } },
  vertexShader: VERT,
  fragmentShader: /* glsl */`
    uniform sampler2D tIrr, tAlb, tColor, tND;
    varying vec2 vUv;
    void main() {
      vec3 c = texture2D(tND, vUv).w <= 0.0
        ? texture2D(tColor, vUv).rgb
        : texture2D(tIrr, vUv).rgb * max(texture2D(tAlb, vUv).rgb, vec3(0.04));
      gl_FragColor = vec4(c, 1.0);
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
    }`,
});

const target = (w, h, filter = THREE.LinearFilter) => new THREE.WebGLRenderTarget(w, h, {
  type: THREE.HalfFloatType, format: THREE.RGBAFormat, magFilter: filter, minFilter: filter, depthBuffer: true,
});

export class Denoiser {
  constructor() {
    this.split = new FullScreenQuad(splitMaterial());
    this.atrous = new FullScreenQuad(atrousMaterial());
    this.join = new FullScreenQuad(joinMaterial());
    this.guideMat = guideMaterial();
    this.size = new THREE.Vector2();
    this.ready = false;
  }

  /** Draw the guides for this view at the trace's size. `albedo(mesh)` gives the
   * plain colour material to draw each surface with. */
  guides(renderer, scene, camera, w, h, albedo) {
    if (!this.nd || this.size.x !== w || this.size.y !== h) {
      for (const t of [this.nd, this.alb, this.a, this.b]) t?.dispose();
      this.nd = target(w, h, THREE.NearestFilter);
      this.alb = target(w, h);
      this.a = target(w, h);
      this.b = target(w, h);
      this.size.set(w, h);
    }
    const bg = scene.background, ov = scene.overrideMaterial, rt = renderer.getRenderTarget();
    const cc = renderer.getClearColor(new THREE.Color()), ca = renderer.getClearAlpha();
    scene.background = null;
    // Facing and depth: nothing drawn (the sky) keeps depth 0.
    scene.overrideMaterial = this.guideMat;
    renderer.setRenderTarget(this.nd);
    renderer.setClearColor(0x000000, 0);
    renderer.clear();
    renderer.render(scene, camera);
    // Bare colour: every surface in its own colour and pattern, unlit.
    scene.overrideMaterial = null;
    const swapped = [];
    scene.traverseVisible((o) => {
      if (!o.isMesh) return;
      swapped.push([o, o.material]);
      o.material = albedo(o);
    });
    renderer.setRenderTarget(this.alb);
    renderer.setClearColor(0xffffff, 1);
    renderer.clear();
    renderer.render(scene, camera);
    for (const [o, m] of swapped) o.material = m;
    scene.background = bg;
    scene.overrideMaterial = ov;
    renderer.setRenderTarget(rt);
    renderer.setClearColor(cc, ca);
    this.ready = true;
  }

  /** Smooth the traced picture `color` (after `samples` passes) onto the screen. */
  render(renderer, color, samples) {
    if (!this.ready) return false;
    const { x: w, y: h } = this.size;
    const rt = renderer.getRenderTarget(), ac = renderer.autoClear;
    renderer.autoClear = false;
    const s = this.split.material.uniforms;
    s.tColor.value = color; s.tAlb.value = this.alb.texture; s.res.value.set(w, h);
    renderer.setRenderTarget(this.a);
    this.split.render(renderer);
    // Five widening steps. The first two follow the surfaces alone (a wall's grain is
    // as bright one pixel to the next as a shadow's edge, so brightness cannot yet
    // tell them apart); the wider ones also hold back across a change of brightness,
    // so a shadow under a sofa keeps its shape. That holds tighter as passes add up.
    const u = this.atrous.material.uniforms;
    u.res.value.set(w, h);
    u.tND.value = this.nd.texture;
    const sigmaL = Math.max(0.35, 6.0 / Math.sqrt(Math.max(1, samples)));
    let src = this.a, dst = this.b;
    for (let i = 0; i < 5; i++) {
      u.tIrr.value = src.texture;
      u.sigmaL.value = i < 2 ? 1e4 : sigmaL;
      u.stepSize.value = 2 ** i;
      renderer.setRenderTarget(dst);
      this.atrous.render(renderer);
      [src, dst] = [dst, src];
    }
    const j = this.join.material.uniforms;
    j.tIrr.value = src.texture; j.tAlb.value = this.alb.texture; j.tColor.value = color; j.tND.value = this.nd.texture;
    renderer.setRenderTarget(null);
    this.join.render(renderer);
    renderer.setRenderTarget(rt);
    renderer.autoClear = ac;
    return true;
  }

  dispose() {
    for (const t of [this.nd, this.alb, this.a, this.b]) t?.dispose();
    for (const q of [this.split, this.atrous, this.join]) { q.material.dispose(); q.dispose(); }
    this.guideMat.dispose();
  }
}
