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
  }

  async load(url, { keepView = false } = {}) {
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
    const dist = span / (2 * Math.tan((this.camera.fov * Math.PI) / 360)) * 1.35;
    this.camera.position.set(dist * 0.62, dist * 0.55, dist * 0.78);
    this.controls.target.set(0, size.y * 0.3, 0);
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


  // Vastu over the model: the nine-cell grid laid on one floor, a pin over
  // every assessed room coloured by its verdict, and for a room in the wrong
  // quarter a ghost of it in the right one with an arc showing the move.
  setVastu(data, level = 0) {
    this.clearVastu();
    this.vastuData = data; this.vastuLevel = level;
    if (!data || !this.model) return;
    const g = (this.vastu = new THREE.Group());
    g.name = "vastu_overlay";
    const lv = data.levels.find((l) => l.index === level) || data.levels[0];
    const y = (lv?.base ?? 0.45) + 0.03;
    const [x0, y0, x1, y1] = data.envelope;
    const w = x1 - x0, h = y1 - y0;

    // The grid, drawn on a canvas and laid on the floor.
    const px = 1024, py = Math.round(px * h / w);
    const cv = document.createElement("canvas"); cv.width = px; cv.height = py;
    const c = cv.getContext("2d");
    // Opaque: a painted floor, the zone colours washed over warm stone.
    c.fillStyle = "#d9cfbd"; c.fillRect(0, 0, px, py);
    const cell = { NW: [0, 0], N: [1, 0], NE: [2, 0], W: [0, 1], CENTRE: [1, 1], E: [2, 1], SW: [0, 2], S: [1, 2], SE: [2, 2] };
    for (const z of data.zones) {
      const [col, row] = cell[z.dir];
      c.fillStyle = z.colour; c.globalAlpha = z.dir === "CENTRE" ? 0.35 : 0.85;
      c.fillRect(col * px / 3, row * py / 3, px / 3, py / 3);
      c.globalAlpha = 0.95;
      c.fillStyle = "#1c1a17";
      c.font = `800 ${Math.round(px / 14)}px Geist, system-ui, sans-serif`;
      c.textAlign = "center"; c.textBaseline = "middle";
      const cx = (col + 0.5) * px / 3, cy = (row + 0.5) * py / 3;
      c.fillText(z.dir === "CENTRE" ? "BRAHMA" : z.dir, cx, cy - px / 30);
      c.font = `600 ${Math.round(px / 30)}px Geist, system-ui, sans-serif`;
      c.globalAlpha = 0.8;
      c.fillText(z.dir === "CENTRE" ? "keep open" : `${z.name} · ${z.element}`, cx, cy + px / 20);
    }
    c.globalAlpha = 0.85; c.strokeStyle = "#1c1a17"; c.lineWidth = 6; c.setLineDash([26, 16]);
    for (let k = 1; k < 3; k++) {
      c.beginPath(); c.moveTo(k * px / 3, 0); c.lineTo(k * px / 3, py); c.stroke();
      c.beginPath(); c.moveTo(0, k * py / 3); c.lineTo(px, k * py / 3); c.stroke();
    }
    c.setLineDash([]); c.strokeRect(2, 2, px - 4, py - 4);
    const tex = new THREE.CanvasTexture(cv);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = 8;
    const grid = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
      new THREE.MeshBasicMaterial({ map: tex }));
    grid.rotation.x = -Math.PI / 2;
    grid.position.set((x0 + x1) / 2, y, -(y0 + y1) / 2);
    grid.renderOrder = 2;
    g.add(grid);

    // Pins and moves for the rooms on this floor.
    const col = { ideal: 0x8fb27a, acceptable: 0xd9b45a, neutral: 0xd9b45a, prohibited: 0xd2553f };
    this.pins = [];
    for (const r of data.rooms.filter((x) => x.level === lv.index)) {
      const top = y + 3.1;
      const colour = col[r.verdict] ?? 0xd9b45a;
      const pin = new THREE.Group();
      const head = new THREE.Mesh(new THREE.SphereGeometry(0.34, 20, 14), new THREE.MeshStandardMaterial({ color: colour, emissive: colour, emissiveIntensity: 0.35, roughness: 0.4 }));
      const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, top - y, 8), new THREE.MeshBasicMaterial({ color: colour, transparent: true, opacity: 0.6 }));
      stem.position.y = -(top - y) / 2;
      pin.add(head, stem);
      pin.position.set(r.centre[0], top, -r.centre[1]);
      g.add(pin);
      const el = document.createElement("div");
      el.className = `v3-pin v3-pin--${r.verdict}`;
      const move = r.ideal_point ? `<span>belongs in the ${r.ideal_zone}</span>` : "";
      el.innerHTML = `<b>${r.name}</b><span>${r.zone || r.direction} · ${r.verdict === "ideal" ? "ideal" : r.verdict === "prohibited" ? "avoid" : "acceptable"}</span>${move}`;
      el.title = `${r.rule}\n${r.why || ""}${r.remedy ? `\nRemedy: ${r.remedy}` : ""}`;
      this.host.append(el);
      this.pins.push({ el, obj: pin, dy: 0.45 });
      if (r.ideal_point) {
        // The room as it would sit in its ideal quarter, and the move there.
        const side = Math.sqrt(Math.max(r.area, 2));
        const ghost = new THREE.Mesh(new THREE.BoxGeometry(side, 0.06, side),
          new THREE.MeshStandardMaterial({ color: 0x8fb27a, emissive: 0x8fb27a, emissiveIntensity: 0.3, roughness: 0.6 }));
        ghost.position.set(r.ideal_point[0], y + 0.03, -r.ideal_point[1]);
        const edge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(side, 1.2, side)),
          new THREE.LineDashedMaterial({ color: 0xfbf6ec, dashSize: 0.25, gapSize: 0.15, transparent: true, opacity: 0.8 }));
        edge.position.set(r.ideal_point[0], y + 0.6, -r.ideal_point[1]);
        edge.computeLineDistances();
        const a = new THREE.Vector3(r.centre[0], y + 1.6, -r.centre[1]);
        const b = new THREE.Vector3(r.ideal_point[0], y + 1.2, -r.ideal_point[1]);
        const mid = a.clone().lerp(b, 0.5).setY(y + 1.6 + a.distanceTo(b) * 0.35);
        const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
        const arc = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(40)),
          new THREE.LineDashedMaterial({ color: 0xfbf6ec, dashSize: 0.3, gapSize: 0.2 }));
        arc.computeLineDistances();
        const tip = new THREE.Mesh(new THREE.ConeGeometry(0.12, 0.32, 14), new THREE.MeshBasicMaterial({ color: 0xfbf6ec }));
        tip.position.copy(b);
        tip.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), curve.getTangent(1).normalize());
        g.add(ghost, edge, arc, tip);
        this.vastuPulse = (this.vastuPulse || []).concat([ghost.material]);
      }
    }
    this.model.add(g);
    // Look down on the floor so the grid reads: a high, slightly tilted plan view.
    const focus = new THREE.Vector3(); grid.getWorldPosition(focus);
    const span = Math.max(w, h);
    const to = new THREE.Vector3(focus.x + span * 0.1, focus.y + span * 2.5, focus.z + span * 0.85);
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
      this.vastu.traverse((o) => { o.geometry?.dispose(); o.material?.map?.dispose(); o.material?.dispose?.(); });
    }
    this.vastu = null;
    this.vastuPulse = [];
    (this.pins || []).forEach((p) => p.el.remove());
    this.pins = [];
  }

  _pinsTick(now) {
    if (!this.pins?.length) return;
    const w = this.host.clientWidth, h = this.host.clientHeight;
    const v = new THREE.Vector3();
    for (const p of this.pins) {
      p.obj.getWorldPosition(v);
      v.y += p.dy;
      v.project(this.camera);
      const hidden = v.z > 1 || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1;
      p.el.style.opacity = hidden ? "0" : "1";
      p.el.style.transform = `translate(-50%, -100%) translate(${(v.x * 0.5 + 0.5) * w}px, ${(-v.y * 0.5 + 0.5) * h}px)`;
    }
    for (const m of this.vastuPulse || []) m.emissiveIntensity = 0.3 + 0.25 * Math.sin(now / 420);
  }

  _tick(now) {
    this.raf = requestAnimationFrame(this._tick);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this._pinsTick(now || performance.now());
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
