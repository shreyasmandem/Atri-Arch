/* ═══════════════════════════════════════════════════════════════════════
   Viewer3D: the scheme's glTF model, in the page.

   The same .glb the studio exports, loaded as is and lit like a massing
   model on a dark table. Drag to orbit, scroll to zoom. It opens at a
   three-quarter view from the road side and turns slowly until touched.
   ═══════════════════════════════════════════════════════════════════════ */

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

// A neutral "photo studio" environment, generated in code so nothing extra
// has to be downloaded: a warm ceiling glow, a cool sky side, a dark floor.
function studioEnvironment(renderer) {
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

export class Viewer3D {
  constructor(host) {
    this.host = host;
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
    this.raf = requestAnimationFrame(this._tick);
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
    const gltf = await new GLTFLoader().loadAsync(url);
    keepView = keepView && !!this.model;
    this.lamps = [];
    this.panes = [];
    if (this.model) this.scene.remove(this.model);
    const m = (this.model = gltf.scene);
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

    const ground = new THREE.Mesh(new THREE.CircleGeometry(span * 1.6, 64),
      new THREE.MeshStandardMaterial({ color: 0x141312, roughness: 1 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.002;
    ground.receiveShadow = true;
    if (this.ground) this.scene.remove(this.ground);
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
    const dist = span / (2 * Math.tan((this.camera.fov * Math.PI) / 360)) * 1.35 * zoom;
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
  setMode(mode, level = 0) {
    if (!this.model) return;
    const levels = [];
    this.model.traverse((o) => { const m = /^level_(\d+)$/.exec(o.name); if (m) levels.push([+m[1], o]); });
    const top = levels.length ? Math.max(...levels.map(([i]) => i)) : 0;
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
    const COLS = { ideal: 0x6f9a55, fair: 0xc9a13e, avoid: 0xc4553f };
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
      const mark = r.verdict === "ideal" ? "✓" : r.verdict === "avoid" ? "✕" : "~";
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
    this.raf = requestAnimationFrame(this._tick);
    this.controls.update();
    this.renderer.render(this.scene, this.orthoKind ? this.ortho : this.camera);
    this._pinsTick(now || performance.now());
    this._datumTick();
  }

  dispose() {
    this.clearVastu();
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
