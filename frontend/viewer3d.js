/* ═══════════════════════════════════════════════════════════════════════
   Viewer3D: the scheme's glTF model, in the page.

   The same .glb the studio exports, loaded as is and lit like a massing
   model on a dark table. Drag to orbit, scroll to zoom. It opens at a
   three-quarter view from the road side and turns slowly until touched.
   ═══════════════════════════════════════════════════════════════════════ */

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { dress, skyTexture } from "./materials.js?v=m5";
import { iconHTML } from "./icons.js?v=i4";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

// A neutral "photo studio" environment, generated in code so nothing extra
// has to be downloaded: a warm ceiling glow, a cool sky side, a dark floor.
export function studioEnvironment(renderer) {
  const env = new THREE.Scene();
  const room = new THREE.Mesh(new THREE.BoxGeometry(20, 12, 20),
    new THREE.MeshBasicMaterial({ color: 0x8a8580, side: THREE.BackSide }));
  env.add(room);
  const panel = (color, intensity, w, h, pos, rot) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(color).multiplyScalar(intensity), side: THREE.DoubleSide }));
    m.position.set(...pos);
    m.rotation.set(...rot);
    env.add(m);
  };
  panel(0xfff1dc, 4.0, 12, 8, [0, 5.9, 0], [Math.PI / 2, 0, 0]);
  panel(0xbcd0ff, 1.6, 10, 6, [-9.9, 2, 0], [0, Math.PI / 2, 0]);
  panel(0xfff6ea, 2.2, 8, 5, [9.9, 2.5, 3], [0, -Math.PI / 2, 0]);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(20, 20), new THREE.MeshBasicMaterial({ color: 0x1a1816 }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -5.9;
  env.add(floor);
  const pmrem = new THREE.PMREMGenerator(renderer);
  const tex = pmrem.fromScene(env, 0.04).texture;
  pmrem.dispose();
  return tex;
}

// Free a replaced model's GPU buffers: a customised facade reloads often.
function disposeTree(root) {
  root.traverse((o) => {
    o.geometry?.dispose();
    for (const m of [].concat(o.material || [])) m.dispose?.();
  });
}

// The ground beyond the plot, fading to the horizon instead of ending in an edge.
function fadeMap() {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d");
  const r = g.createRadialGradient(64, 64, 20, 64, 64, 64);
  r.addColorStop(0, "#fff"); r.addColorStop(0.7, "#bbb"); r.addColorStop(1, "#000");
  g.fillStyle = r; g.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

export class Viewer3D {
  // `daylight`: the exterior under a sky on open ground, as a house is seen;
  // without it, the dark studio table the drawings and hero use.
  constructor(host, { daylight = false } = {}) {
    this.host = host;
    this.THREE = THREE;          // for callers that measure the model (part labels)
    this.daylight = daylight;
    const r = (this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false }));
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    r.outputColorSpace = THREE.SRGBColorSpace;
    r.toneMapping = THREE.ACESFilmicToneMapping;
    r.shadowMap.enabled = true;
    r.shadowMap.type = THREE.PCFSoftShadowMap;
    r.setClearColor(0x0b0a09, 1);
    r.domElement.className = "v3-canvas";
    host.append(r.domElement);

    const scene = (this.scene = new THREE.Scene());
    // A soft studio environment for reflections: glass, metal and polished
    // stone need something to reflect, or they read as flat colour.
    scene.environment = studioEnvironment(r);
    this.sky = daylight ? skyTexture() : null;
    scene.background = this.sky;
    r.toneMappingExposure = 1.0;
    this.hemi = new THREE.HemisphereLight(0xf4ead8, 0x221c16, 0.7);
    scene.add(this.hemi);
    const sun = (this.sun = new THREE.DirectionalLight(0xfff1dc, 2.1));
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.bias = -0.0005;
    scene.add(sun, sun.target);
    const fill = new THREE.DirectionalLight(0xbcd0ff, 0.45);
    fill.position.set(-1, 0.6, -0.8);
    scene.add(fill);

    this.camera = new THREE.PerspectiveCamera(32, 1, 0.1, 500);
    const c = (this.controls = new OrbitControls(this.camera, r.domElement));
    c.enableDamping = true;
    c.dampingFactor = 0.08;
    c.maxPolarAngle = Math.PI * 0.49;
    c.autoRotate = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    c.autoRotateSpeed = 0.5;
    c.addEventListener("start", () => { c.autoRotate = false; });

    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this.resize();
    this._tick = this._tick.bind(this);
    // The renderer's own loop, so a VR headset can drive it as well as the page.
    r.xr.enabled = true;
    r.setAnimationLoop(this._tick);
  }

  resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    if (this.orthoKind) this.setOrtho(this.orthoKind, { cut: this.cut });
  }

  async load(url, { keepView = false, front = null, zoom = 1, lift = 0.3 } = {}) {
    // Live edits fire loads back to back: only the latest may land, or a slow
    // earlier model could replace a newer one.
    const seq = (this.loadSeq = (this.loadSeq || 0) + 1);
    const gltf = await new GLTFLoader().loadAsync(url);
    if (seq !== this.loadSeq) return null;
    keepView = keepView && !!this.model;
    this.lamps = [];
    this.panes = [];
    if (this.model) { this.scene.remove(this.model); disposeTree(this.model); }
    const m = (this.model = gltf.scene);
    this._house = 0;
    let tris = 0;
    m.traverse((o) => {
      if (!o.isMesh) return;
      o.castShadow = true;
      o.receiveShadow = true;
      const g = o.geometry;
      tris += (g.index ? g.index.count : g.attributes.position.count) / 3;
      for (const mat of [].concat(o.material)) {
        if (mat && mat.transparent) {
          o.castShadow = false; mat.depthWrite = false;
          if (mat.name === "glass") this.panes.push(mat);
        }
        if (mat && mat.emissive && mat.emissive.getHex() !== 0) { o.castShadow = false; mat.emissiveIntensity = 0; this.lamps.push(mat); }
        dress(mat);
      }
    });
    this.scene.add(m);

    // Frame it: centre on the footprint, sit it on the table, and light it
    // from over the viewer's shoulder so the faces you see first read.
    const box = new THREE.Box3().setFromObject(m);
    const size = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3());
    m.position.sub(new THREE.Vector3(centre.x, box.min.y, centre.z));
    const span = Math.max(size.x, size.z, size.y * 1.5);
    this.span = span;

    const ground = new THREE.Mesh(new THREE.CircleGeometry(span * (this.daylight ? 3 : 1.6), 64),
      this.daylight
        ? new THREE.MeshStandardMaterial({ color: 0x8f8877, roughness: 1, transparent: true, alphaMap: (this.fade ||= fadeMap()) })
        : new THREE.MeshStandardMaterial({ color: 0x141312, roughness: 1 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.002;
    ground.receiveShadow = true;
    if (this.ground) { this.scene.remove(this.ground); disposeTree(this.ground); }
    this.ground = ground;
    this.scene.add(ground);

    const sc = this.sun.shadow.camera;
    sc.left = -span; sc.right = span; sc.top = span; sc.bottom = -span; sc.far = span * 6;
    sc.updateProjectionMatrix();
    this.sun.position.set(span * 0.35, span * 1.7, span * 1.25);

    if (keepView) {
      if (this.mode) this.setMode(this.mode, this.modeLevel || 0);
      if (this.vastuData) this.setVastu(this.vastuData, this.vastuLevel);
      return { triangles: Math.round(tris), width: size.x, depth: size.z, height: size.y };
    }
    // A tall, narrow view (a side column, a phone) stands further back, or
    // the house's width would be cut off at the sides.
    const narrow = Math.max(1, 1 / (this.camera.aspect || 1)) ** 0.85;
    const dist = span / (2 * Math.tan((this.camera.fov * Math.PI) / 360)) * 1.35 * zoom * narrow;
    // Open on the street side, three-quarters on: the face the house shows.
    if (front) {
      const a = Math.atan2(-front[1], front[0]) + 0.6;
      this.camera.position.set(Math.cos(a) * dist, dist * 0.55, Math.sin(a) * dist);
    } else this.camera.position.set(dist * 0.62, dist * 0.55, dist * 0.78);
    this.controls.target.set(0, size.y * lift, 0);
    this.controls.minDistance = span * 0.4;
    this.controls.maxDistance = span * 4;
    this.controls.update();
    return { triangles: Math.round(tris), width: size.x, depth: size.z, height: size.y };
  }

  // Exterior: the whole house. Interior: the roof and every floor above the
  // one in view lifted away, ceiling lights hidden so the rooms read from
  // above. Night: dusk light, the lamps on and glowing through the glass.
  // ── zoom in to go inside ────────────────────────────────────────────
  // Close in on the house and its roof and upper floors lift away, showing
  // the floor at the camera's height; draw back and it closes up again. Only
  // an outside view steps in on its own, and only a step it took itself
  // steps back out, so a floor picked from the tabs stays put.
  autoInterior(onChange) {
    this.onAutoMode = onChange;
    if (this._autoBound) return;
    this._autoBound = true;
    this.controls.minDistance = 1.5;
    this.controls.addEventListener("change", () => this._autoStep());
  }

  _autoStep() {
    if (!this.model || !this.span || this.orthoKind || this._gliding) return;
    const d = this.camera.position.distanceTo(this.controls.target);
    // The house itself, not the plot round it, and the view's shape: a tall
    // phone view stands further back to show the same house.
    if (!this._house) {
      const box = new THREE.Box3();
      this.model.traverse((o) => { if (o.isMesh && /^level_\d+__/.test(o.name)) box.expandByObject(o); });
      const sz = box.isEmpty() ? new THREE.Vector3(this.span, 0, this.span) : box.getSize(new THREE.Vector3());
      this._house = Math.max(sz.x, sz.z, sz.y * 1.2);
    }
    const reach = this._house * Math.max(1, 1 / (this.camera.aspect || 1)) ** 0.85;
    // In once the house fills the view; out only well beyond, so it never flickers.
    if ((this.mode || "exterior") === "exterior" && d < reach * 1.6) {
      // Inside from the top: the roof lifts first, then each floor in turn.
      const top = this._topLevel();
      this._auto = true;
      this.setMode("interior", top);
      this.onAutoMode?.("interior", top);
      this._entryD = this._glideInto(top, d) || d;
    } else if (this._auto && this.mode === "interior") {
      if (d > reach * 2.4) {
        this._auto = false;
        this.setMode("exterior");
        this.onAutoMode?.("exterior", 0);
        return;
      }
      // Peel the house: every further 28% closer lifts the floor in view
      // away to show the one below; drawing back puts them back in order.
      const top = this._topLevel();
      const depth = Math.max(0, Math.floor(Math.log((this._entryD || d) / d) / Math.log(1 / 0.72)));
      const level = Math.max(0, top - depth);
      if (level !== this.modeLevel) {
        this.setMode("interior", level);
        this.onAutoMode?.("interior", level);
        this._shiftTo(level);
      }
    }
  }

  _topLevel() {
    let top = 0;
    this.model.traverse((o) => { const m = /^level_(\d+)$/.exec(o.name); if (m) top = Math.max(top, +m[1]); });
    return top;
  }

  // The floor's box: its rooms, walls and furniture.
  _levelBox(level) {
    const box = new THREE.Box3();
    this.model.traverse((o) => { if (o.isMesh && o.name.startsWith(`level_${level}__`)) box.expandByObject(o); });
    return box;
  }

  // Down (or up) to another floor: the view drops by a storey, keeping its
  // angle and distance, so the zoom carries on without a jump.
  _shiftTo(level) {
    const box = this._levelBox(level);
    if (box.isEmpty()) return;
    const dy = box.min.y + 1.0 - this.controls.target.y;
    const fromC = this.camera.position.clone(), fromT = this.controls.target.clone();
    const t0 = performance.now(), ms = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 450;
    this._gliding = true;
    const step = (now) => {
      const k = ms ? Math.min(1, (now - t0) / ms) : 1, e = 1 - (1 - k) ** 3;
      this.camera.position.set(fromC.x, fromC.y + dy * e, fromC.z);
      this.controls.target.set(fromT.x, fromT.y + dy * e, fromT.z);
      this.controls.update();
      if (k < 1) requestAnimationFrame(step); else this._gliding = false;
    };
    requestAnimationFrame(step);
  }

  // Into the floor as a dollhouse: from the side the client was looking,
  // high enough to see down into every room, the floor filling the view.
  // Returns the distance it settles at.
  _glideInto(level, d) {
    const box = this._levelBox(level);
    if (box.isEmpty()) return 0;
    const centre = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const floorY = box.min.y + 1.0;
    const target = new THREE.Vector3(centre.x, floorY, centre.z);
    const dir = this.camera.position.clone().sub(this.controls.target).setY(0);
    if (dir.lengthSq() < 1e-6) dir.set(1, 0, 1);
    dir.normalize();
    // As far off as the client zoomed, tipped to look down at about 50 degrees.
    const dist = Math.max(d, Math.max(size.x, size.z) * 0.9);
    const to = target.clone().add(dir.multiplyScalar(dist * 0.77)).setY(floorY + dist * 0.64);
    const from = this.camera.position.clone(), fromT = this.controls.target.clone();
    const t0 = performance.now(), ms = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 650;
    this._gliding = true;
    const step = (now) => {
      const k = ms ? Math.min(1, (now - t0) / ms) : 1, e = 1 - (1 - k) ** 3;
      this.camera.position.lerpVectors(from, to, e);
      this.controls.target.lerpVectors(fromT, target, e);
      this.controls.update();
      if (k < 1) requestAnimationFrame(step); else this._gliding = false;
    };
    requestAnimationFrame(step);
    return dist;
  }

  // A mode picked by hand: the zoom no longer owns it.
  pickMode(mode, level = 0) {
    this._auto = false;
    return this.setMode(mode, level);
  }

  // ── parts: what a click lands on, and lighting a part up ────────────
  // Each mesh is named node__material__key (arch3d); the key names the part.
  partAt(clientX, clientY) {
    if (!this.model) return null;
    const r = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    const ray = (this._ray ||= new THREE.Raycaster());
    ray.setFromCamera(ndc, this.camera);
    const meshes = [];
    this.model.traverse((o) => { if (o.isMesh && o.visible) meshes.push(o); });
    for (const hit of ray.intersectObjects(meshes, false)) {
      let o = hit.object, ok = true;
      for (let q = o; q; q = q.parent) if (!q.visible) { ok = false; break; }
      if (!ok) continue;
      const key = o.name.split("__").pop();
      return { key, mesh: o, point: hit.point };
    }
    return null;
  }

  // Every part key in the model, with the colour it wears now.
  parts() {
    const out = new Map();
    this.model?.traverse((o) => {
      if (!o.isMesh) return;
      const key = o.name.split("__").pop();
      const m = [].concat(o.material)[0];
      if (!out.has(key) && m?.color) out.set(key, `#${m.color.getHexString()}`);
    });
    return out;
  }

  // Light a part up (null: none), so the client sees what they are about to change.
  highlight(key) {
    if (this._lit === key) return;
    this._lit = key;
    this.model?.traverse((o) => {
      if (!o.isMesh) return;
      const on = key && o.name.split("__").pop() === key;
      for (const m of [].concat(o.material)) {
        if (!m?.emissive || this.lamps?.includes(m)) continue;
        m.userData.glow ??= { c: m.emissive.getHex(), i: m.emissiveIntensity };
        if (on) { m.emissive.setHex(0x6a8cff); m.emissiveIntensity = 0.45; }
        else { m.emissive.setHex(m.userData.glow.c); m.emissiveIntensity = m.userData.glow.i; }
      }
    });
  }

  setMode(mode, level = 0) {
    if (!this.model) return;
    const levels = [];
    this.model.traverse((o) => { const m = /^level_(\d+)$/.exec(o.name); if (m) levels.push([+m[1], o]); });
    const top = levels.length ? Math.max(...levels.map(([i]) => i)) : 0;
    if (mode !== "walk" && this.walking) this.leaveWalk();
    const show = mode === "interior" ? Math.min(level, top) : top;
    for (const [i, o] of levels) o.visible = i <= show;
    const roof = this.model.getObjectByName("roof");
    if (roof) roof.visible = mode !== "interior";
    this.model.traverse((o) => { if (o.isMesh && /__lights__/.test(o.name)) o.visible = mode !== "interior"; });
    const night = mode === "night";
    this.hemi.intensity = night ? 0.05 : 0.7;
    this.sun.intensity = night ? 0.08 : 2.1;
    this.renderer.toneMappingExposure = night ? 0.85 : 1.0;
    this.scene.environmentIntensity = night ? 0.06 : 1.0;
    for (const m of this.lamps) m.emissiveIntensity = night ? 2.4 : 0;
    // Lit rooms seen from outside: the glass carries the warm interior glow.
    for (const m of this.panes) {
      m.emissive.setHex(night ? 0xffc27a : 0x000000);
      m.emissiveIntensity = night ? 0.9 : 0;
      m.opacity = night ? 0.85 : 0.32;
    }
    this.renderer.setClearColor(night ? 0x07080c : 0x0b0a09, 1);
    // Daylight outside: the sky, open ground and a sky-tinted fill. Inside,
    // at night and for Vastu the studio dark reads the rooms better.
    const day = this.daylight && mode === "exterior";
    // Walking inside: a sky through the windows, and the rooms lit as by day.
    if (mode === "walk") this.sky ||= skyTexture();
    this.scene.background = day || mode === "walk" ? this.sky : null;
    if (this.ground) this.ground.material.opacity = day || !this.daylight ? 1 : 0;
    this.hemi.color.setHex(day ? 0xdde6ee : 0xf4ead8);
    this.hemi.groundColor.setHex(day ? 0x6b5f4f : 0x221c16);
    if (day) this.hemi.intensity = 0.95;
    if (mode === "walk") {
      this.hemi.intensity = 1.6;
      this.hemi.groundColor.setHex(0xcdbfa8);     // daylight off a pale floor lights the ceiling
      this.scene.environmentIntensity = 1.3;
      this.renderer.toneMappingExposure = 1.1;
    }
    this.mode = mode;
    this.modeLevel = level;
    return { levels: top + 1 };
  }


  // Vastu over the model, read as a plan: the floor washed in the nine zone
  // tints, each key room ringed in its verdict colour, the quarters named
  // around the house (labels that stay legible at any size), and a dashed arc
  // for every move or swap that would help.
  setVastu(data, level = 0) {
    this.clearVastu();
    this.vastuData = data; this.vastuLevel = level;
    if (!data || !this.model) return;
    const g = (this.vastu = new THREE.Group());
    const lv = data.levels.find((l) => l.index === level) || data.levels[0];
    const y = (lv?.base ?? 0.45) + 0.03;
    const V = (x, py, h = y) => new THREE.Vector3(x, h, -py);
    this.pins = [];
    const tag = (cls, html, obj, dy = 0) => {
      const el = document.createElement("div");
      el.className = cls; el.innerHTML = html;
      this.host.append(el);
      this.pins.push({ el, obj, dy });
      return el;
    };

    // Zone tints: one flat shape per cell, opaque, on the floor.
    for (const z of data.zones) {
      const shape = new THREE.Shape(z.polygon.map(([x, py]) => new THREE.Vector2(x, py)));
      const geo = new THREE.ShapeGeometry(shape);
      geo.rotateX(-Math.PI / 2);
      const base = new THREE.Color(0xe2d8c6).lerp(new THREE.Color(z.colour), z.dir === "CENTRE" ? 0.25 : 0.55);
      const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: base }));
      m.position.y = y;
      g.add(m);
      const edge = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(z.polygon.map(([x, py]) => V(x, py, y + 0.01))),
        new THREE.LineBasicMaterial({ color: 0x1c1a17, transparent: true, opacity: 0.45 }));
      g.add(edge);
    }
    // The quarters named outside the house, and the centre kept open.
    const [x0, y0, x1, y1] = data.envelope;
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, pad = 1.4;
    for (const z of data.zones) {
      const [px, py] = z.point;
      const out = z.dir === "CENTRE" ? V(px, py, y + 0.2)
        : V(cx + (px - cx) * (1 + pad / Math.max(1e-3, Math.abs(px - cx) + Math.abs(py - cy)) * 1.6), cy + (py - cy) * (1 + pad / Math.max(1e-3, Math.abs(px - cx) + Math.abs(py - cy)) * 1.6), y + 0.2);
      const o = new THREE.Object3D(); o.position.copy(out); g.add(o);
      tag(`v3-zone${z.dir === "CENTRE" ? " v3-zone--c" : ""}`,
        z.dir === "CENTRE" ? "<b>Brahmasthan</b><span>keep open</span>" : `<b>${z.dir}</b><span>${z.element}</span>`, o);
    }

    // Key rooms on this floor: a ring in the verdict colour, a chip, a move.
    // The 2D mandala's language: cream where a room fits, sand where it is out of place, brick only where it is forbidden.
    const COLS = { ideal: 0xede6dc, fair: 0xc9b497, avoid: 0xc4553f };
    for (const r of data.rooms.filter((x) => x.level === lv.index)) {
      const pts = r.polygon.map(([x, py]) => new THREE.Vector2(x, py));
      const outer = new THREE.Shape(pts);
      // Inset hole: a band about 25 cm wide just inside the walls.
      const c = pts.reduce((a, p) => a.add(p), new THREE.Vector2()).multiplyScalar(1 / pts.length);
      const hole = new THREE.Path(pts.map((p) => {
        const d = p.clone().sub(c); const L = d.length() || 1;
        return c.clone().add(d.multiplyScalar(Math.max(0.2, (L - 0.42) / L)));
      }));
      outer.holes.push(hole);
      const geo = new THREE.ShapeGeometry(outer);
      geo.rotateX(-Math.PI / 2);
      const ring = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: COLS[r.verdict] }));
      ring.position.y = y + 0.02;
      g.add(ring);
      const anchor = new THREE.Object3D(); anchor.position.copy(V(r.centre[0], r.centre[1], y + 0.1)); g.add(anchor);
      const mark = iconHTML(r.verdict === "ideal" ? "check" : r.verdict === "avoid" ? "close" : "dash", "ico ico--sm");
      const move = r.target ? (r.swap ? `swap with ${r.swap}` : `better in the ${r.target}`) : "";
      const el = tag(`v3-chip v3-chip--${r.verdict}`, `<b>${mark} ${r.name}</b><span>${r.zone}${move ? ` · ${move}` : ""}</span>`, anchor);
      el.title = `${r.rule}\nIdeal: ${r.ideal.join(", ")}${r.avoid.length ? `\nAvoid: ${r.avoid.join(", ")}` : ""}\n${r.why || ""}${r.remedy ? `\nIf it stays: ${r.remedy}` : ""}`;
      if (r.target_point) {
        const a = V(r.centre[0], r.centre[1], y + 0.4), b = V(r.target_point[0], r.target_point[1], y + 0.4);
        const mid = a.clone().lerp(b, 0.5); mid.y += Math.max(1.2, a.distanceTo(b) * 0.4);
        const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
        const arc = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(40)),
          new THREE.LineDashedMaterial({ color: COLS[r.verdict], dashSize: 0.3, gapSize: 0.18 }));
        arc.computeLineDistances();
        const tip = new THREE.Mesh(new THREE.ConeGeometry(0.16, 0.42, 14), new THREE.MeshBasicMaterial({ color: COLS[r.verdict] }));
        tip.position.copy(b);
        tip.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), curve.getTangent(1).normalize());
        g.add(arc, tip);
      }
    }
    this.model.add(g);
    // Look down on the floor so it reads as a plan.
    const focus = this.model.localToWorld(V(cx, cy));
    const span = Math.max(x1 - x0, y1 - y0) + pad * 4;
    const to = new THREE.Vector3(focus.x + span * 0.05, focus.y + span * 2.1, focus.z + span * 0.7);
    const from = this.camera.position.clone(), t0 = this.controls.target.clone();
    this.controls.autoRotate = false;
    const start = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - start) / 900), e = 1 - Math.pow(1 - k, 3);
      this.camera.position.lerpVectors(from, to, e);
      this.controls.target.lerpVectors(t0, focus, e);
      if (k < 1 && this.vastu === g) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  clearVastu() {
    if (this.vastu) {
      this.vastu.removeFromParent();
      this.vastu.traverse((o) => { o.geometry?.dispose(); o.material?.dispose?.(); });
    }
    this.vastu = null;
    (this.pins || []).forEach((p) => p.el.remove());
    this.pins = [];
  }

  _pinsTick() {
    if (!this.pins?.length) return;
    const w = this.host.clientWidth, h = this.host.clientHeight;
    const v = new THREE.Vector3();
    for (const p of this.pins) {
      p.obj.getWorldPosition(v);
      v.y += p.dy;
      v.project(this.orthoKind ? this.ortho : this.camera);
      const hidden = v.z > 1 || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1;
      p.el.style.opacity = hidden ? "0" : "1";
      p.el.style.transform = `translate(-50%, -50%) translate(${(v.x * 0.5 + 0.5) * w}px, ${(-v.y * 0.5 + 0.5) * h}px)`;
    }
  }

  // Drawings from the model itself: an elevation is the house seen square-on
  // from one side, a section is the house cut through and seen from the cut,
  // the roof and site plans are seen from directly above. All orthographic,
  // all lit by a sun you can move, so the shadows read the depth of every
  // projection - the way a rendered presentation elevation does.
  setOrtho(kind, { cut = 0.5 } = {}) {
    if (!this.model) return;
    this.cut = cut;
    this.orthoKind = kind;
    this.controls.autoRotate = false;
    const box = new THREE.Box3().setFromObject(this.model);
    const size = box.getSize(new THREE.Vector3()), mid = box.getCenter(new THREE.Vector3());
    const W = this.host.clientWidth || 1, H = this.host.clientHeight || 1, aspect = W / H;
    const top = kind === "roof" || kind === "site";
    // What the frame must hold: width x height of the projection.
    const span = top ? [size.x, size.z] : kind === "E" || kind === "W" || kind === "sectionB" ? [size.z, size.y] : [size.x, size.y];
    const fit = kind === "site" ? 1.15 : 1.25;
    let hw = (span[0] / 2) * fit, hh = (span[1] / 2) * fit;
    if (hw / hh > aspect) hh = hw / aspect; else hw = hh * aspect;
    const cam = (this.ortho ||= new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 1000));
    cam.left = -hw; cam.right = hw; cam.top = hh; cam.bottom = -hh;
    const far = Math.max(size.x, size.y, size.z) * 4;
    cam.up.set(0, 1, 0);
    const look = mid.clone();
    if (top) { cam.position.set(mid.x, mid.y + far, mid.z + 0.001); cam.up.set(0, 0, -1); look.copy(mid); }
    else if (kind === "S" || kind === "sectionA") cam.position.set(mid.x, mid.y, mid.z + far);
    else if (kind === "N") cam.position.set(mid.x, mid.y, mid.z - far);
    else if (kind === "E" || kind === "sectionB") cam.position.set(mid.x + far, mid.y, mid.z);
    else cam.position.set(mid.x - far, mid.y, mid.z);
    cam.far = far * 3;
    cam.lookAt(look);
    cam.updateProjectionMatrix();
    this.controls.object = cam;
    this.controls.target.copy(look);
    this.controls.enableRotate = false;
    this.controls.screenSpacePanning = true;
    this.controls.update();
    // A section: everything nearer than the cut is clipped away.
    this.renderer.localClippingEnabled = true;
    const plane = kind === "sectionA" ? new THREE.Plane(new THREE.Vector3(0, 0, -1), box.min.z + size.z * cut)
      : kind === "sectionB" ? new THREE.Plane(new THREE.Vector3(-1, 0, 0), box.min.x + size.x * cut) : null;
    this.renderer.clippingPlanes = plane ? [plane] : [];
    // Roof plan: the whole house. Site plan: the same, wider. Elevations and
    // sections show every floor.
    this.model.traverse((o) => { if (/^level_\d+$/.test(o.name) || o.name === "roof") o.visible = true; });
    this.ground.visible = kind === "site";
    // The compound wall and planting would hide the ground floor in an
    // elevation; drawings show the building alone, the site plan shows all.
    const site = this.model.getObjectByName("site");
    if (site) site.visible = kind === "site" || kind === "roof";
    this._datums(kind, box);
    this.setSun(this.sunHour ?? 15);
  }

  // Level datums down the side of an elevation or section: FFL heights.
  _datums(kind, box) {
    (this.datums || []).forEach((d) => d.el.remove());
    this.datums = [];
    if (kind === "roof" || kind === "site") return;
    const levels = [];
    this.model.traverse((o) => {
      const m = /^level_(\d+)$/.exec(o.name);
      if (m) { const b = new THREE.Box3().setFromObject(o); if (!b.isEmpty()) levels.push([+m[1], b.min.y]); }
    });
    levels.sort((a, b) => a[0] - b[0]);
    const roof = this.model.getObjectByName("roof");
    if (roof) { const b = new THREE.Box3().setFromObject(roof); if (!b.isEmpty()) levels.push(["Top", b.max.y]); }
    const ground = box.min.y + 0.12;
    for (const [i, yv] of levels) {
      const el = document.createElement("div");
      el.className = "v3-datum";
      el.innerHTML = `<b>${i === "Top" ? "TOP" : i === 0 ? "GROUND FFL" : `LEVEL ${i} FFL`}</b><span>+${(yv - ground).toFixed(2)} m</span>`;
      this.host.append(el);
      this.datums.push({ el, y: yv });
    }
  }

  // The sun's position for an hour of a summer day, as an arc east to west.
  setSun(hour) {
    this.sunHour = hour;
    const t = (hour - 6) / 12, a = Math.PI * Math.min(1, Math.max(0, t));
    const box = new THREE.Box3().setFromObject(this.model);
    const span = box.getSize(new THREE.Vector3()).length();
    this.sun.position.set(Math.cos(a) * span * 1.2, Math.sin(a) * span * 1.1 + span * 0.15, span * 0.55);
    this.sun.intensity = 0.4 + 1.9 * Math.sin(a);
    const low = Math.sin(a) < 0.35;
    this.sun.color.setHex(low ? 0xffc690 : 0xfff1dc);
  }

  exitOrtho() {
    this.orthoKind = null;
    this.renderer.clippingPlanes = [];
    this.controls.object = this.camera;
    this.controls.enableRotate = true;
    (this.datums || []).forEach((d) => d.el.remove());
    this.datums = [];
    if (this.ground) this.ground.visible = true;
    const site = this.model?.getObjectByName("site");
    if (site) site.visible = true;
  }

  _datumTick() {
    if (!this.datums?.length || !this.ortho) return;
    const h = this.host.clientHeight;
    const v = new THREE.Vector3();
    for (const d of this.datums) {
      v.set(this.controls.target.x, d.y, this.controls.target.z).project(this.ortho);
      d.el.style.transform = `translate(0, -50%) translate(16px, ${(-v.y * 0.5 + 0.5) * h}px)`;
    }
  }


  // Stand in a room: cut the house open at its floor, put the camera in a
  // corner at eye height and look across to the far side.
  focusRoom(box, level = 0, instant = false) {
    if (!this.model) return;
    this.setMode("interior", level);
    let base = 0;
    const g = this.model.getObjectByName(`level_${level}`);
    if (g) {
      const bb = new THREE.Box3().setFromObject(g);
      if (!bb.isEmpty()) base = bb.min.y;
    }
    const local = (x, y, h) => this.model.localToWorld(new THREE.Vector3(x, h, -y));
    const cx = (box.x0 + box.x1) / 2, cy = (box.y0 + box.y1) / 2;
    const w = box.x1 - box.x0, d = box.y1 - box.y0;
    const floorY = base - this.model.position.y;
    // From above and outside the room's corner, looking down into it: a doll's-house view.
    // Far enough that the whole room, and a little around it, fits the frame.
    const fov = (this.camera.fov * Math.PI) / 180;
    const fit = (Math.max(w, d) + 2) / (2 * Math.tan(fov / 2)) / Math.min(1, this.camera.aspect || 1);
    const eye = local(cx - 0.3 * fit, cy - 0.5 * fit, floorY + 0.8 * fit);
    const at = local(cx, cy, floorY + 0.4);
    this.controls.autoRotate = false;
    if (instant) {
      this.camera.position.copy(eye); this.controls.target.copy(at); this.controls.update();
      return;
    }
    const from = this.camera.position.clone(), t0 = this.controls.target.clone();
    const start = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - start) / 1000), e = 1 - Math.pow(1 - k, 3);
      this.camera.position.lerpVectors(from, eye, e);
      this.controls.target.lerpVectors(t0, at, e);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  _tick(now) {
    if (this.walking) this._walkTick(now || performance.now());
    if (this.hung?.length) {
      // Fans and pendants hang from a ceiling the doll's-house view has lifted
      // away: seen from above they would float, so they show only from inside.
      const cy = this.renderer.xr.isPresenting ? 0 : this.camera.getWorldPosition(this._v ||= new THREE.Vector3()).y;
      for (const o of this.hung) o.visible = this.walking || this.renderer.xr.isPresenting || cy < o.userData.top;
    }
    if (this.renderer.xr.isPresenting) { this.renderer.render(this.scene, this.camera); return; }
    this.controls.update();
    this.renderer.render(this.scene, this.orthoKind ? this.ortho : this.camera);
    this._pinsTick(now || performance.now());
    this._datumTick();
  }

  // ── furnishing: real pieces and paintings ───────────────────────────
  // The model leaves out what has a photographed model; each one is loaded
  // once, fitted to the size the plan gave it and stood in its place on its
  // floor, so it lifts away with that floor like everything else.
  async furnish(data, base = "") {
    if (!this.model || !data) return;
    const model = this.model;
    for (const g of this.furnished || []) { g.parent?.remove(g); disposeTree(g); }
    this.furnished = [];
    this.hung = [];
    const loader = (this._gl ||= new GLTFLoader());
    const cache = (this._assets ||= new Map());
    const asset = (name) => {
      if (!cache.has(name)) {
        cache.set(name, loader.loadAsync(`${base}${data.assets}${name}/${name}_1k.gltf`).then((g) => {
          const box = new THREE.Box3().setFromObject(g.scene);
          return { scene: g.scene, size: box.getSize(new THREE.Vector3()), centre: box.getCenter(new THREE.Vector3()), minY: box.min.y };
        }).catch(() => null));
      }
      return cache.get(name);
    };
    const levelNode = (i) => model.getObjectByName(`level_${i}`) || model;
    // Each piece's fitted top, so what stands on it (a vase, a tea set) rests on it.
    const tops = new Array(data.models.length);
    const jobs = [];
    data.models.forEach((m, i) => { tops[i] = jobs[i] = (async () => {
      const a = await asset(m.asset);
      if (!a || this.model !== model) return null;
      const s = m.fit === "height" ? m.h / Math.max(a.size.y, 1e-3)
        : Math.min(m.w / Math.max(a.size.x, 1e-3), m.d / Math.max(a.size.z, 1e-3), m.h / Math.max(a.size.y, 1e-3));
      let y = m.y;
      if (m.on != null) { const top = await tops[m.on]; if (top != null) y = top; }
      const inner = a.scene.clone(true);
      inner.position.set(-a.centre.x * s, -a.minY * s, -a.centre.z * s);
      inner.scale.setScalar(s);
      const g = new THREE.Group();
      g.add(inner);
      g.position.set(m.x, y, m.z);
      g.rotation.y = m.yaw;
      g.name = `furnish__${m.asset}`;
      inner.traverse((o) => {
        if (!o.isMesh) return;
        o.castShadow = o.receiveShadow = true;
        if (m.colour) {
          o.material = o.material.clone();
          o.material.color = new THREE.Color(m.colour).lerp(new THREE.Color(0xffffff), 0.3);
        }
      });
      levelNode(m.level).add(g);
      this.furnished.push(g);
      if (/ceiling_fan|ceiling_lamp|diya_lantern|Chandelier/.test(m.asset)) {
        g.updateWorldMatrix(true, false);
        g.userData.top = g.getWorldPosition(new THREE.Vector3()).y + m.h + 0.3;
        this.hung.push(g);
      }
      return y + a.size.y * s;
    })(); });
    const texLoader = (this._tl ||= new THREE.TextureLoader());
    const frameMat = (this._frameMat ||= new THREE.MeshStandardMaterial({ color: 0x3a2618, roughness: 0.55 }));
    for (const p of data.paintings) {
      const t = texLoader.load(`${base}${data.art}${p.art}.jpg`);
      t.colorSpace = THREE.SRGBColorSpace;
      t.anisotropy = 8;
      const g = new THREE.Group();
      const frame = new THREE.Mesh(new THREE.BoxGeometry(p.w + 0.07, p.h + 0.07, 0.035), frameMat);
      // The painting as painted: its own colours, not re-graded by the room's exposure.
      const canvas = new THREE.Mesh(new THREE.PlaneGeometry(p.w, p.h),
        new THREE.MeshBasicMaterial({ map: t, color: 0xe8e4dc, toneMapped: false }));
      canvas.position.z = 0.019;
      frame.castShadow = true;
      g.add(frame, canvas);
      g.position.set(p.x, p.y, p.z);
      g.rotation.y = p.yaw;
      g.name = `painting__${p.art}`;
      g.userData.title = `${p.title} · ${p.artist}`;
      levelNode(p.level).add(g);
      this.furnished.push(g);
    }
    await Promise.all(jobs);
  }

  // ── walking: standing in the house at eye height ─────────────────────
  // Drag to look round, double-click the floor to walk to that spot, or use
  // the arrow keys / WASD. Walls stop you; doors let you through.
  walkInto(box, level = 0, { from = null, look = null } = {}) {
    if (!this.model) return;
    this.setMode("walk", level);
    const floorY = this._floorY(level);
    const cx = (box.x0 + box.x1) / 2, cy = (box.y0 + box.y1) / 2;
    // Stand back in a corner of the room and look across it, as you would from its door.
    const sx = from ? from.x : cx - (box.x1 - box.x0) * 0.3, sy = from ? from.y : cy - (box.y1 - box.y0) * 0.3;
    const eye = this.model.localToWorld(new THREE.Vector3(sx, floorY + 1.6, -sy));
    const at = look
      ? this.model.localToWorld(new THREE.Vector3(look.x, floorY + 1.0, -look.y))
      : this.model.localToWorld(new THREE.Vector3(cx + (cx - sx) * 0.5, floorY + 1.35, -(cy + (cy - sy) * 0.5)));
    this.walking = { level, floorY, keys: new Set(), last: performance.now() };
    const c = this.controls;
    this._orbit ||= { min: c.minDistance, max: c.maxDistance, pol: c.maxPolarAngle, zoom: c.enableZoom, pan: c.enablePan, speed: c.rotateSpeed };
    c.autoRotate = false;
    c.enableZoom = false; c.enablePan = false;
    c.minDistance = 0.01; c.maxDistance = 0.2;
    c.minPolarAngle = Math.PI * 0.12; c.maxPolarAngle = Math.PI * 0.88;
    c.rotateSpeed = -0.5;
    this.camera.fov = 62; this.camera.near = 0.05; this.camera.updateProjectionMatrix();
    this.camera.position.copy(eye);
    c.target.copy(eye.clone().add(at.clone().sub(eye).normalize().multiplyScalar(0.1)));
    c.update();
    this._bindWalk();
    if (this.renderer.xr.isPresenting) this._placeRig(eye, at);
  }

  leaveWalk() {
    if (!this.walking) return;
    this.walking = null;
    const c = this.controls, o = this._orbit;
    if (o) {
      c.minDistance = o.min; c.maxDistance = o.max; c.maxPolarAngle = o.pol; c.minPolarAngle = 0;
      c.enableZoom = o.zoom; c.enablePan = o.pan; c.rotateSpeed = o.speed;
    }
    this.camera.fov = 32; this.camera.near = 0.1; this.camera.updateProjectionMatrix();
  }

  _floorY(level) {
    let base = 0;
    const g = this.model.getObjectByName(`level_${level}`);
    if (g) {
      // The floor finishes, not the stair or a sunken courtyard, set the level.
      const bb = new THREE.Box3();
      g.traverse((o) => { if (o.isMesh && /__floors__/.test(o.name)) bb.expandByObject(o); });
      if (bb.isEmpty()) bb.setFromObject(g);
      if (!bb.isEmpty()) base = bb.max.y;
    }
    return base - this.model.position.y;
  }

  _bindWalk() {
    if (this._walkBound) return;
    this._walkBound = true;
    const el = this.renderer.domElement;
    el.tabIndex = 0;
    el.addEventListener("keydown", (e) => {
      if (!this.walking) return;
      const k = e.key.toLowerCase();
      if (["arrowup", "arrowdown", "arrowleft", "arrowright", "w", "a", "s", "d"].includes(k)) { e.preventDefault(); this.walking.keys.add(k); }
    });
    el.addEventListener("keyup", (e) => this.walking?.keys.delete(e.key.toLowerCase()));
    el.addEventListener("blur", () => this.walking?.keys.clear());
    el.addEventListener("dblclick", (e) => {
      if (!this.walking) return;
      const hit = this._pick(e.clientX, e.clientY);
      if (!hit) return;
      const n = hit.face ? hit.face.normal.clone().transformDirection(hit.object.matrixWorld) : new THREE.Vector3(0, 1, 0);
      if (n.y < 0.6) return;                        // walk to a floor, not into a wall
      const to = hit.point.clone().setY(this.camera.position.y);
      this._glideWalk(to);
    });
    el.addEventListener("pointerdown", () => el.focus({ preventScroll: true }));
  }

  _pick(clientX, clientY) {
    const r = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    const ray = (this._ray ||= new THREE.Raycaster());
    ray.setFromCamera(ndc, this.camera);
    return this._visibleMeshes().length ? ray.intersectObjects(this._visibleMeshes(), false)[0] : null;
  }

  _visibleMeshes() {
    const out = [];
    this.model.traverse((o) => {
      if (!o.isMesh) return;
      let v = true;
      for (let p = o; p; p = p.parent) if (!p.visible) { v = false; break; }
      if (v && !(o.material && o.material.transparent)) out.push(o);
    });
    return out;
  }

  // Would a step from `from` along `dir` (unit, horizontal) of `len` run into something?
  _blocked(from, dir, len) {
    const ray = (this._wray ||= new THREE.Raycaster());
    ray.far = len + 0.3;
    for (const h of [-0.75, -0.25]) {     // knee and chest, below the eye
      ray.set(from.clone().add(new THREE.Vector3(0, h, 0)), dir);
      if (ray.intersectObjects(this._wallMeshes ||= this._visibleMeshes(), false).length) return true;
    }
    return false;
  }

  _glideWalk(to) {
    const from = this.camera.position.clone();
    const look = this.controls.target.clone().sub(from);
    const t0 = performance.now(), ms = Math.min(1600, from.distanceTo(to) * 450);
    const step = (now) => {
      const k = Math.min(1, (now - t0) / ms), e = 1 - (1 - k) ** 3;
      this.camera.position.lerpVectors(from, to, e);
      this.controls.target.copy(this.camera.position).add(look);
      if (k < 1 && this.walking) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  _walkTick(now) {
    const w = this.walking;
    const dt = Math.min(0.05, (now - w.last) / 1000);
    w.last = now;
    if (!w.keys.size || this.renderer.xr.isPresenting) { this._wallMeshes = null; return; }
    const fwd = this.controls.target.clone().sub(this.camera.position).setY(0).normalize();
    const right = new THREE.Vector3(-fwd.z, 0, fwd.x);
    const mv = new THREE.Vector3();
    if (w.keys.has("w") || w.keys.has("arrowup")) mv.add(fwd);
    if (w.keys.has("s") || w.keys.has("arrowdown")) mv.sub(fwd);
    if (w.keys.has("d") || w.keys.has("arrowright")) mv.add(right);
    if (w.keys.has("a") || w.keys.has("arrowleft")) mv.sub(right);
    if (!mv.lengthSq()) return;
    mv.normalize();
    const len = 1.4 * dt;
    if (this._blocked(this.camera.position, mv, len)) return;
    mv.multiplyScalar(len);
    this.camera.position.add(mv);
    this.controls.target.add(mv);
  }

  // ── editing in the view: pick, drag, see what is selected ───────────
  // The page says what a click or a drag means (`interact`); the viewer turns
  // pointer positions into plan coordinates on the floor being edited.
  enableEditing(interact) {
    this.interact = interact;
    if (this._editBound) return;
    this._editBound = true;
    const host = this.host;
    let down = null;
    host.addEventListener("pointerdown", (e) => {
      if (!this.interact || e.button !== 0 || e.target !== this.renderer.domElement) return;
      const hit = this.pickPlan(e.clientX, e.clientY);
      down = { x: e.clientX, y: e.clientY, t: performance.now(), hit, drag: false };
      if (hit && this.interact.grab?.(hit)) {
        // Dragging a piece: the view holds still while it moves.
        down.drag = true;
        this.controls.enabled = false;
        this.renderer.domElement.setPointerCapture(e.pointerId);
      }
    }, { capture: true });
    host.addEventListener("pointermove", (e) => {
      if (!down?.drag) return;
      const p = this.floorPoint(e.clientX, e.clientY, this.interact.level ?? 0);
      if (p) this.interact.drag?.(p);
    });
    const up = (e) => {
      if (!down) return;
      const d = down; down = null;
      if (d.drag) { this.controls.enabled = true; this.interact?.drop?.(); return; }
      if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < 5 && performance.now() - d.t < 450) this.interact?.click?.(d.hit);
    };
    host.addEventListener("pointerup", up);
    host.addEventListener("pointercancel", up);
  }

  // Where a pointer lands, in plan coordinates: x, y (plan north up), the
  // height above the model's origin, and whether the face is a floor or a wall.
  pickPlan(clientX, clientY) {
    if (!this.model) return null;
    const hit = this._pick(clientX, clientY);
    if (!hit) return null;
    const p = this.model.worldToLocal(hit.point.clone());
    const n = hit.face ? hit.face.normal.clone().transformDirection(hit.object.matrixWorld) : new THREE.Vector3(0, 1, 0);
    return { x: p.x, y: -p.z, h: p.y, up: n.y > 0.6, wall: Math.abs(n.y) < 0.3 };
  }

  // Where a pointer meets the floor of a level, in plan coordinates.
  floorPoint(clientX, clientY, level) {
    const r = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    const ray = (this._ray ||= new THREE.Raycaster());
    ray.setFromCamera(ndc, this.camera);
    const fy = this.model.localToWorld(new THREE.Vector3(0, this._floorY(level), 0)).y;
    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -fy);
    const out = new THREE.Vector3();
    if (!ray.ray.intersectPlane(plane, out)) return null;
    const p = this.model.worldToLocal(out);
    return { x: p.x, y: -p.z };
  }

  // A cream outline round the selected piece, at its true size and turn.
  mark(piece, level) {
    if (!this.model) return;
    if (this._mark) { this._mark.parent?.remove(this._mark); this._mark.geometry.dispose(); this._mark = null; }
    if (!piece) return;
    const h = Math.max(0.05, piece.h || 0.6);
    const g = new THREE.EdgesGeometry(new THREE.BoxGeometry(piece.w + 0.04, h + 0.02, piece.d + 0.04));
    const m = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0xf2e6cf, depthTest: false, transparent: true, opacity: 0.95 }));
    m.renderOrder = 10;
    m.position.set(piece.x, this._floorY(level) + (piece.lift || 0) + h / 2, -piece.y);
    m.rotation.y = (piece.rotation * Math.PI) / 180;
    this.model.add(m);
    this._mark = m;
  }

  // The way the view looks, as a plan direction: for moving things "away" and "to the right".
  viewAxes() {
    const d = new THREE.Vector3();
    this.camera.getWorldDirection(d);
    const inv = new THREE.Quaternion();
    this.model?.getWorldQuaternion(inv);
    d.applyQuaternion(inv.invert());
    const fx = d.x, fy = -d.z, len = Math.hypot(fx, fy) || 1;
    return { fwd: [fx / len, fy / len], right: [fy / len, -fx / len] };
  }

  // The colour of a room's lights while standing in it: warm, natural or task white.
  setRoomLight(kelvin) {
    if (this.mode !== "walk") return;
    this.hemi.color.setHex({ 2700: 0xffd9b0, 4000: 0xfff2e2, 5500: 0xf3f6ff }[kelvin] || 0xf4ead8);
    for (const m of this.lamps) m.emissiveIntensity = kelvin ? 1.4 : 0;
  }

  // ── VR: the same walk, in a headset ──────────────────────────────────
  // The headset gives the eye height and where you look; the trigger
  // teleports to the spot on the floor you point at, the grip button goes
  // on to the next room.
  static async vrSupported() {
    try { return !!(navigator.xr && await navigator.xr.isSessionSupported("immersive-vr")); } catch { return false; }
  }

  async enterVR({ onNextRoom } = {}) {
    if (!navigator.xr) throw new Error("This browser has no WebXR");
    this.onNextRoom = onNextRoom;
    const session = await navigator.xr.requestSession("immersive-vr", { optionalFeatures: ["local-floor", "bounded-floor"] });
    const xr = this.renderer.xr;
    xr.setReferenceSpaceType("local-floor");
    await xr.setSession(session);
    this.controls.enabled = false;
    const rig = (this.rig ||= new THREE.Group());
    this.scene.add(rig);
    rig.add(this.camera);
    const eye = this.camera.position.clone(), at = this.controls.target.clone();
    this._placeRig(eye, at);
    this._bindControllers(rig);
    session.addEventListener("end", () => {
      this.controls.enabled = true;
      const p = this.camera.getWorldPosition(new THREE.Vector3());
      this.scene.add(this.camera);
      this.camera.position.copy(p);
      this.camera.updateProjectionMatrix();
    });
  }

  _placeRig(eye, at) {
    const rig = this.rig;
    if (!rig) return;
    // The rig stands on the floor; the headset adds the eye height itself.
    rig.position.set(eye.x, eye.y - 1.6, eye.z);
    const d = at.clone().sub(eye);
    rig.rotation.set(0, Math.atan2(-d.x, -d.z), 0);
    this.camera.position.set(0, 0, 0);
    this.camera.rotation.set(0, 0, 0);
  }

  _bindControllers(rig) {
    if (this._controllers) return;
    this._controllers = [0, 1].map((i) => {
      const c = this.renderer.xr.getController(i);
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, 0, -4)]),
        new THREE.LineBasicMaterial({ color: 0xf2e6cf }));
      c.add(line);
      rig.add(c);
      c.addEventListener("selectstart", () => {
        const m = new THREE.Matrix4().extractRotation(c.matrixWorld);
        const ray = (this._xray ||= new THREE.Raycaster());
        ray.ray.origin.setFromMatrixPosition(c.matrixWorld);
        ray.ray.direction.set(0, 0, -1).applyMatrix4(m);
        const hit = ray.intersectObjects(this._visibleMeshes(), false)[0];
        if (!hit) return;
        const n = hit.face ? hit.face.normal.clone().transformDirection(hit.object.matrixWorld) : new THREE.Vector3(0, 1, 0);
        if (n.y < 0.6) return;                      // only onto a floor, not up a wall
        rig.position.set(hit.point.x, hit.point.y, hit.point.z);
      });
      c.addEventListener("squeezestart", () => this.onNextRoom?.());
      return c;
    });
  }

  dispose() {
    this.clearVastu();
    this.renderer.setAnimationLoop(null);
    this.renderer.xr.getSession?.()?.end().catch(() => {});
    this.ro.disconnect();
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
