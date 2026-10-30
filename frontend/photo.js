/* ═══════════════════════════════════════════════════════════════════════
   Photo: the view in front of you, rendered like an architect's visual.

   A path tracer follows the light as it really travels: in through the
   glass from the sky and the sun, down from the ceiling lights, off the
   floor onto the walls and the ceiling. Corners darken softly, colours
   bleed from a rug onto a wall, shadows blur with distance and the view
   outside shows through real glass. The picture builds over a few seconds,
   sharpening as it goes, and can be saved.

   Nothing in the live model changes. What the render needs (surface
   normals, texture co-ordinates for the floors and walls, glass you can see
   through, lamps that give light) is lent for the render and handed back.
   ═══════════════════════════════════════════════════════════════════════ */

import * as THREE from "three";
import { WebGLPathTracer } from "three-gpu-pathtracer";
import { finishOf } from "./materials.js?v=m6";
import { Denoiser } from "./denoise.js?v=d2";

// The light of each mood: the sky, the sun, the lamps and the exposure.
const MOODS = {
  // Late morning: a clear sky, the sun slanting in, the ceiling lights on low.
  day: { zenith: [0.30, 0.50, 0.95], horizon: [1.3, 1.22, 1.08], ground: [0.32, 0.29, 0.24],
         sky: 1.0, sun: 3.2, lamp: 5, window: 1.6, fill: 0.35, fillColour: [1.0, 0.96, 0.9], exposure: 1.15 },
  // Dusk: a deep blue sky, a warm glow at the horizon, every lamp on.
  evening: { zenith: [0.05, 0.08, 0.22], horizon: [0.75, 0.45, 0.32], ground: [0.05, 0.05, 0.06],
             sky: 0.55, sun: 0, lamp: 16, window: 0.25, fill: 0.1, fillColour: [1.0, 0.82, 0.62], exposure: 1.3 },
};

// The most pixels traced per pass: more is slower to clear of grain.
const MAX_PX = 0.6e6;

// A sky all round, as the path tracer wants it: an equirectangular float
// image, bright at the horizon, blue overhead, the ground dim below.
function skyMap(mood) {
  const W = 256, H = 128, data = new Float32Array(W * H * 4);
  const { zenith, horizon, ground } = MOODS[mood];
  for (let y = 0; y < H; y++) {
    const e = ((y + 0.5) / H - 0.5) * Math.PI;           // elevation: row 0 is straight down
    let c;
    if (e >= 0) {
      const t = Math.pow(1 - e / (Math.PI / 2), 3);
      c = zenith.map((z, i) => z + (horizon[i] - z) * t);
    } else {
      const t = Math.min(1, -e * 5);
      c = horizon.map((h, i) => h * 0.55 + (ground[i] - h * 0.55) * t);
    }
    for (let x = 0; x < W; x++) data.set([c[0], c[1], c[2], 1], (y * W + x) * 4);
  }
  const t = new THREE.DataTexture(data, W, H, THREE.RGBAFormat, THREE.FloatType);
  t.mapping = THREE.EquirectangularReflectionMapping;
  t.magFilter = t.minFilter = THREE.LinearFilter;
  t.needsUpdate = true;
  return t;
}

// A finish (oak boards, kota slabs, plaster) as an ordinary texture: the
// grey pattern the live shader lays on, scaled into 0..1 so it can multiply
// a colour, and the gain that brings the colour back to its own brightness.
const finishMaps = new Map();
function finishMap(f) {
  if (finishMaps.has(f.kind)) return finishMaps.get(f.kind);
  const N = 512, c = document.createElement("canvas");
  c.width = c.height = N;
  const g = c.getContext("2d", { willReadFrequently: true });
  // Softened a touch: the tracer reads a texture at full detail however far off the
  // surface is, and a fine plaster speckle would come out as grain on every wall.
  g.filter = "blur(1.5px)";
  // Drawn with a margin of itself all round, so the blur wraps and the tile still repeats seamlessly.
  for (const dx of [-N, 0, N]) for (const dy of [-N, 0, N]) g.drawImage(f.image, dx, dy, N, N);
  g.filter = "none";
  const img = g.getImageData(0, 0, N, N);
  let max = 0, sum = 0;
  const val = new Float32Array(N * N);
  for (let i = 0; i < N * N; i++) {
    const d = img.data[i * 4] / 255;
    const v = 1 + (0.3 + 1.4 * d - 1) * f.k;
    val[i] = v; sum += v; if (v > max) max = v;
  }
  for (let i = 0; i < N * N; i++) {
    const v = Math.round((val[i] / max) * 255);
    img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = v;
    img.data[i * 4 + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.NoColorSpace;
  // The pattern was divided by its brightest value: the colour, multiplied by
  // that value, comes back to the surface's own average brightness.
  const out = { map: t, gain: max };
  finishMaps.set(f.kind, out);
  return out;
}

// Flat-shaded faces with texture co-ordinates laid on from the three axes,
// in metres of the world, as the live shader lays the finishes on.
function lendGeometry(mesh, scale) {
  const src = mesh.geometry;
  let g = src.index ? src.toNonIndexed() : src.clone();
  // The model draws a surface seen from both sides as two triangles in the same
  // place, wound opposite ways. A ray meets both at once and may take the one
  // facing away and slip through the wall: keep one of each pair (the render
  // treats every face as two-sided).
  if (!src.attributes.normal) g = dedupe(g);
  if (!src.attributes.normal) g.computeVertexNormals();
  if (!g.attributes.uv) {
    const pos = g.attributes.position, n = pos.count;
    const uv = new Float32Array(n * 2);
    const m = mesh.matrixWorld, a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
    const e1 = new THREE.Vector3(), e2 = new THREE.Vector3(), nn = new THREE.Vector3(), p = new THREE.Vector3();
    for (let i = 0; i + 2 < n; i += 3) {
      a.fromBufferAttribute(pos, i).applyMatrix4(m);
      b.fromBufferAttribute(pos, i + 1).applyMatrix4(m);
      c.fromBufferAttribute(pos, i + 2).applyMatrix4(m);
      nn.crossVectors(e1.subVectors(b, a), e2.subVectors(c, a));
      const ax = Math.abs(nn.x), ay = Math.abs(nn.y), az = Math.abs(nn.z);
      for (let k = 0; k < 3; k++) {
        p.copy(k === 0 ? a : k === 1 ? b : c).multiplyScalar(scale);
        let u, v;
        if (ay >= ax && ay >= az) { u = p.x; v = p.z; }
        else if (ax >= az) { u = p.z; v = -p.y; }
        else { u = p.x; v = -p.y; }
        uv[(i + k) * 2] = u; uv[(i + k) * 2 + 1] = v;
      }
    }
    g.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
  }
  return g;
}

function dedupe(g) {
  const pos = g.attributes.position, n = Math.floor(pos.count / 3);
  const seen = new Set(), keep = [];
  const k = (i) => `${Math.round(pos.getX(i) * 2000)},${Math.round(pos.getY(i) * 2000)},${Math.round(pos.getZ(i) * 2000)}`;
  for (let t = 0; t < n; t++) {
    const key = [k(t * 3), k(t * 3 + 1), k(t * 3 + 2)].sort().join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    keep.push(t);
  }
  if (keep.length === n) return g;
  const out = new Float32Array(keep.length * 9);
  keep.forEach((t, j) => { for (let q = 0; q < 9; q++) out[j * 9 + q] = pos.array[t * 9 + q]; });
  const h = new THREE.BufferGeometry();
  h.setAttribute("position", new THREE.BufferAttribute(out, 3));
  g.dispose();
  return h;
}

// The window panes in the glass meshes: each pane is a thin box of its own,
// found as a group of triangles sharing corners, measured in the world.
function panes(meshes) {
  const out = [];
  for (const mesh of meshes) {
    const pos = mesh.geometry.attributes.position, idx = mesh.geometry.index;
    const n = idx ? idx.count : pos.count;
    const at = (i) => (idx ? idx.getX(i) : i);
    const v = new THREE.Vector3();
    const key = (i) => { v.fromBufferAttribute(pos, at(i)); return `${Math.round(v.x * 500)},${Math.round(v.y * 500)},${Math.round(v.z * 500)}`; };
    const parent = new Map();
    const find = (a) => { while (parent.get(a) !== a) { parent.set(a, parent.get(parent.get(a))); a = parent.get(a); } return a; };
    const join = (a, b) => { a = find(a); b = find(b); if (a !== b) parent.set(a, b); };
    for (let i = 0; i < n; i++) { const k = key(i); if (!parent.has(k)) parent.set(k, k); }
    for (let t = 0; t + 2 < n; t += 3) { join(key(t), key(t + 1)); join(key(t), key(t + 2)); }
    const boxes = new Map();
    for (let i = 0; i < n; i++) {
      const r = find(key(i));
      if (!boxes.has(r)) boxes.set(r, new THREE.Box3());
      v.fromBufferAttribute(pos, at(i)).applyMatrix4(mesh.matrixWorld);
      boxes.get(r).expandByPoint(v);
    }
    out.push(...boxes.values());
  }
  return out;
}

// Where each ceiling light is: the lights mesh is every room's fitting merged
// into one, so its vertices are gathered into the separate fittings.
function fittings(mesh) {
  const pos = mesh.geometry.attributes.position, v = new THREE.Vector3(), out = [];
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i).applyMatrix4(mesh.matrixWorld);
    let hit = out.find((f) => Math.hypot(f.x / f.n - v.x, f.z / f.n - v.z) < 0.6 && Math.abs(f.y / f.n - v.y) < 0.4);
    if (!hit) out.push((hit = { x: 0, y: 0, z: 0, n: 0, low: Infinity }));
    hit.x += v.x; hit.y += v.y; hit.z += v.z; hit.n++; hit.low = Math.min(hit.low, v.y);
  }
  return out.map((f) => new THREE.Vector3(f.x / f.n, f.low, f.z / f.n));
}

// Standing in a room, only what the room can see is traced: its own floor,
// the slab above as its ceiling, and the furniture in and near it. A whole
// house of furniture would slow every pass for pieces behind walls.
function cull(v, hide) {
  const w = v.walking, model = v.model;
  if (!w || !model) return;
  const lv = w.level;
  const b = w.box;
  const lo = model.localToWorld(new THREE.Vector3(b.x0, 0, -b.y1)), hi = model.localToWorld(new THREE.Vector3(b.x1, 0, -b.y0));
  const near = new THREE.Box3(new THREE.Vector3(Math.min(lo.x, hi.x), -1e9, Math.min(lo.z, hi.z)),
    new THREE.Vector3(Math.max(lo.x, hi.x), 1e9, Math.max(lo.z, hi.z))).expandByVector(new THREE.Vector3(2.5, 0, 2.5));
  for (const o of model.children) {
    const m = /^level_(\d+)$/.exec(o.name);
    if (m) {
      const i = +m[1];
      if (i === lv) continue;
      if (i === lv + 1) {
        for (const c of o.children) if (!/__structure__/.test(c.name)) hide(c);
      } else hide(o);
    } else if (o.name === "roof" && model.getObjectByName(`level_${lv + 1}`)) hide(o);
  }
  const c = new THREE.Vector3();
  for (const g of v.furnished || []) {
    new THREE.Box3().setFromObject(g).getCenter(c);
    if (!near.containsPoint(c)) hide(g);
  }
}

export class Photo {
  constructor(viewer, { mood = "day", samples = 128, onProgress = null, textures = true } = {}) {
    this.textures = textures;
    this.v = viewer;
    this.mood = MOODS[mood] ? mood : "day";
    this.target = samples;
    this.onProgress = onProgress;
    this.state = "idle";
    this.lent = [];
    this.added = [];
    this.saved = {};
  }

  /** Lend the scene what the render needs and start tracing. */
  start() {
    const v = this.v, scene = v.scene, r = v.renderer, M = MOODS[this.mood];
    // What changes for the render, kept to hand back.
    this.saved = {
      env: scene.environment, bg: scene.background, envI: scene.environmentIntensity, bgI: scene.backgroundIntensity,
      tone: r.toneMapping, exp: r.toneMappingExposure,
      sun: v.sun.intensity, sunOn: v.sun.visible,
      hidden: [],
    };
    // Fill lights that only stand in for bounced light: the path tracer bounces it for real.
    const hide = (o) => { if (o && o.visible) { o.visible = false; this.saved.hidden.push(o); } };
    for (const o of [v.roomLamp, v._mark, ...scene.children.filter((c) => c.isDirectionalLight && c !== v.sun)]) hide(o);
    cull(v, hide);
    // Window glass left out: the tracer would treat each pane as something the sun
    // and sky must get past by chance, and the room would fill with grain. Clear
    // glass in a photograph reads as open anyway.
    const glass = [];
    scene.traverse((o) => {
      if (o.isMesh && !Array.isArray(o.material) && o.material?.transparent && /glass/.test(o.material.name || "")) {
        if (o.visible) glass.push(o);
        hide(o);
      }
    });
    this.sky = skyMap(this.mood);
    scene.environment = this.sky;
    scene.environmentIntensity = M.sky;
    if (v.mode === "walk") { scene.background = this.sky; scene.backgroundIntensity = M.sky; }
    v.sun.intensity = M.sun;
    v.sun.visible = M.sun > 0;
    // A photographic curve: warm whites roll off softly, shadows keep some depth.
    r.toneMapping = THREE.ACESFilmicToneMapping;
    r.toneMappingExposure = M.exposure;

    // Every visible surface: normals, texture co-ordinates and a render-ready material.
    const mats = new Map(), lightMeshes = [];
    const lamps = new Set(v.lamps || []);
    scene.updateMatrixWorld(true);
    scene.traverseVisible((o) => {
      if (!o.isMesh || o.isInstancedMesh) return;
      if (/__lights__/.test(o.name)) lightMeshes.push(o);
      const src = o.material;
      if (Array.isArray(src)) return;
      const f = this.textures ? finishOf(src) : null;
      const rec = { mesh: o, geometry: o.geometry, material: src };
      if (!o.geometry.attributes.normal || (!o.geometry.attributes.uv && f)) o.geometry = lendGeometry(o, f ? 1 / f.size : 1);
      if (!mats.has(src)) mats.set(src, this._material(src, f, lamps.has(src), M));
      o.material = mats.get(src);
      this.lent.push(rec);
    });
    this.mats = [...mats.entries()].filter(([a, b]) => a !== b).map(([, b]) => b);

    // A soft panel of light under each ceiling fitting: downlights. Standing in a
    // room, only its own: a lamp behind a wall adds nothing but grain.
    const room = v.walking ? this._roomBox() : null;
    if (M.lamp > 0) {
      for (const mesh of lightMeshes) {
        const col = mesh.material.emissive ? mesh.material.emissive.clone() : new THREE.Color(0xffd9a8);
        for (const p of fittings(mesh)) {
          if (room && !room.containsPoint(p.clone().setY(0))) continue;
          const l = new THREE.RectAreaLight(col, M.lamp, 0.45, 0.45);
          l.position.set(p.x, p.y - 0.02, p.z);
          l.rotation.x = -Math.PI / 2;               // facing straight down
          scene.add(l);
          this.added.push(l);
        }
      }
    }

    // Standing in a room, the daylight is gathered where it comes in. A panel of
    // sky light in each of the room's windows (unseen by the camera, which still
    // sees the view) means every pass finds the window, not one in a hundred;
    // and a soft panel under the ceiling gives the light that ceiling would
    // bounce down, as a photographer's fill does.
    if (room) {
      const skyCol = new THREE.Color(...MOODS[this.mood].horizon).lerp(new THREE.Color(...MOODS[this.mood].zenith), 0.35);
      const lum = skyCol.r * 0.2126 + skyCol.g * 0.7152 + skyCol.b * 0.0722;
      skyCol.multiplyScalar(1 / Math.max(lum, 1e-3));
      const centre = room.getCenter(new THREE.Vector3());
      for (const pane of panes(glass)) {
        const c = pane.getCenter(new THREE.Vector3()), sz = pane.getSize(new THREE.Vector3());
        if (!room.containsPoint(c.clone().setY(0))) continue;
        const alongX = sz.x >= sz.z;                // the pane runs along x: it faces z
        const w = alongX ? sz.x : sz.z, h = sz.y;
        if (w < 0.25 || h < 0.25) continue;
        const inward = alongX ? new THREE.Vector3(0, 0, Math.sign(centre.z - c.z) || 1)
          : new THREE.Vector3(Math.sign(centre.x - c.x) || 1, 0, 0);
        const l = new THREE.RectAreaLight(skyCol, M.window, w, h);
        l.position.copy(c).addScaledVector(inward, 0.04);
        l.lookAt(l.position.clone().add(inward));
        scene.add(l);
        this.added.push(l);
      }
      const ceil = this._ceiling();
      if (ceil != null && M.fill > 0) {
        const sz = room.getSize(new THREE.Vector3());
        const l = new THREE.RectAreaLight(new THREE.Color(...M.fillColour), M.fill, Math.max(0.5, sz.x - 1.2), Math.max(0.5, sz.z - 1.2));
        l.position.set(centre.x, ceil - 0.03, centre.z);
        l.rotation.x = -Math.PI / 2;
        scene.add(l);
        this.added.push(l);
      }
      // The sky still shows through the window and lights what the panels miss, at less strength.
      scene.environmentIntensity = M.sky * 0.45;
    }

    // One path tracer per viewer: building its shader takes a while, so it is kept.
    const pt = (v._pt ||= new WebGLPathTracer(r));
    // Small tiles keep each draw short: a long one can make the GPU give up the page.
    pt.tiles.set(3, 3);
    pt.bounces = 4;
    pt.transmissiveBounces = 3;
    pt.filterGlossyFactor = 1.0;
    pt.multipleImportanceSampling = true;
    pt.minSamples = 1;
    pt.fadeDuration = 0;
    pt.renderDelay = 0;
    pt.rasterizeScene = false;
    pt.dynamicLowRes = false;
    pt.pausePathTracing = false;
    pt.textureSize.set(512, 512);
    const size = r.getDrawingBufferSize(new THREE.Vector2());
    pt.renderScale = Math.min(1, Math.sqrt(MAX_PX / (size.x * size.y)));
    // The grain smoothed away across each surface, its edges and patterns kept.
    const camera = v.walking ? v.camera : (v.orthoKind ? v.ortho : v.camera);
    this.dn = new Denoiser();
    this.albedos = new Map();
    pt.renderToCanvasCallback = (target, renderer) => {
      const w = target.width, h = target.height;
      if (!this.dn.ready || this.dn.size.x !== w || this.dn.size.y !== h) {
        this.dn.guides(renderer, scene, camera, w, h, (o) => this._albedo(o));
      }
      this.dn.render(renderer, target.texture, pt.samples);
    };
    pt.setScene(scene, camera);
    this.camera = camera;
    this.pose = camera.matrixWorld.clone();
    this.pt = pt;
    this.state = "running";
    this.t0 = performance.now();
  }

  // The room stood in, on the ground plane of the world, with a little margin.
  _roomBox() {
    const v = this.v, b = v.walking.box;
    const a = v.model.localToWorld(new THREE.Vector3(b.x0, 0, -b.y1)), c = v.model.localToWorld(new THREE.Vector3(b.x1, 0, -b.y0));
    return new THREE.Box3(new THREE.Vector3(Math.min(a.x, c.x), -0.1, Math.min(a.z, c.z)),
      new THREE.Vector3(Math.max(a.x, c.x), 0.1, Math.max(a.z, c.z))).expandByVector(new THREE.Vector3(0.4, 0, 0.4));
  }

  // The ceiling over where the camera stands: the first thing straight above it.
  _ceiling() {
    const v = this.v, o = v.camera.getWorldPosition(new THREE.Vector3());
    const meshes = [];
    v.model.traverseVisible((m) => { if (m.isMesh) meshes.push(m); });
    const hit = new THREE.Raycaster(o, new THREE.Vector3(0, 1, 0), 0.05, 6).intersectObjects(meshes, false)[0];
    return hit ? hit.point.y : null;
  }

  // A surface's own colour and pattern, unlit, for the denoiser's guide.
  _albedo(o) {
    const m = Array.isArray(o.material) ? o.material[0] : o.material;
    if (!this.albedos.has(m)) {
      this.albedos.set(m, new THREE.MeshBasicMaterial({
        color: m?.color ? m.color.clone() : new THREE.Color(0xffffff), map: m?.map || null,
        side: THREE.DoubleSide, toneMapped: false,
      }));
    }
    return this.albedos.get(m);
  }

  _material(src, f, isLamp, M) {
    if (!src || !src.isMaterial) return src;
    const m = src.clone();
    m.side = THREE.DoubleSide;
    // No mirror-sharp floors in the photo: a near-mirror catches the sun in rare
    // bright specks that take thousands of passes to settle.
    if ((m.metalness ?? 0) < 0.5 && m.roughness != null) m.roughness = Math.max(m.roughness, 0.4);
    if (isLamp || /^light$|^lamp/.test(src.name)) {
      m.emissiveIntensity = M.lamp > 0 ? 2.5 + M.lamp * 0.25 : 1.5;
    }
    if (f) {
      const { map, gain } = finishMap(f);
      m.map = map;
      const hi = Math.max(m.color.r, m.color.g, m.color.b, 1e-3);
      m.color = m.color.clone().multiplyScalar(Math.min(gain, 0.92 / hi));
    }
    return m;
  }

  /** One frame: another pass of light, shown with the grain smoothed. */
  tick() {
    if (this.state !== "running" && this.state !== "done") return;
    const pt = this.pt;
    // Still gliding into place (a view picked a moment ago): start again from where it is.
    this.camera.updateMatrixWorld();
    if (!this.camera.matrixWorld.equals(this.pose)) {
      this.pose.copy(this.camera.matrixWorld);
      pt.updateCamera();
      this.dn.ready = false;
      this.state = "running";
    }
    pt.pausePathTracing = pt.samples >= this.target;
    pt.renderSample();
    if (this.state === "running" && pt.samples >= this.target) this.state = "done";
    this.onProgress?.({
      samples: Math.floor(pt.samples), target: this.target, compiling: pt.isCompiling,
      done: this.state === "done", seconds: (performance.now() - this.t0) / 1000,
    });
  }

  /** The picture as it stands, as a PNG data URL. */
  capture() {
    this.pt.pausePathTracing = true;
    this.pt.renderSample();
    const url = this.v.renderer.domElement.toDataURL("image/png");
    this.pt.pausePathTracing = this.pt.samples >= this.target;
    return url;
  }

  /** Hand everything back as it was. */
  stop() {
    if (this.state === "stopped") return;
    this.state = "stopped";
    const v = this.v, scene = v.scene, r = v.renderer, s = this.saved;
    for (const rec of this.lent) {
      if (rec.mesh.geometry !== rec.geometry) { rec.mesh.geometry.dispose(); rec.mesh.geometry = rec.geometry; }
      rec.mesh.material = rec.material;
    }
    for (const m of this.mats || []) m.dispose();
    for (const m of this.albedos?.values() || []) m.dispose();
    this.dn?.dispose();
    for (const l of this.added) { scene.remove(l); l.dispose?.(); }
    for (const o of s.hidden) o.visible = true;
    scene.environment = s.env; scene.background = s.bg;
    scene.environmentIntensity = s.envI; scene.backgroundIntensity = s.bgI ?? 1;
    r.toneMapping = s.tone; r.toneMappingExposure = s.exp;
    v.sun.intensity = s.sun; v.sun.visible = s.sunOn;
    this.sky?.dispose();
    // Free the traced scene's buffers; the tracer itself (and its compiled shader) stays.
    this.pt?.setScene(new THREE.Scene(), v.camera);
    this.lent = []; this.added = [];
  }
}
