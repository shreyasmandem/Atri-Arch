/* ═══════════════════════════════════════════════════════════════════════
   AirflowView: the solved wind field, alive.

   The backend solves the breeze through a whole floor (windflow.py) and
   sends the velocity on a grid. This draws it three ways at once:

   - the field: air speed as light, still air sinking into the dark of the
     sheet, the breeze rising through umber and sand to cream;
   - the particles: a few thousand motes carried by the solved velocity, with
     trails, so a jet through a window, a room swept end to end and a corner
     the air never reaches are all visible without reading a number;
   - the plan: walls, rooms with their air changes, and every opening marked
     as an inlet or an outlet by the sign of the flow through it.

   Nothing is animated for effect: a particle moves exactly as fast as the
   solve says the air does. With reduced motion, static streamlines are drawn
   from the same field instead.
   ═══════════════════════════════════════════════════════════════════════ */

const RAMP = [
  [0.00, [16, 14, 12]],
  [0.12, [44, 36, 30]],
  [0.30, [96, 76, 58]],
  [0.52, [158, 132, 102]],
  [0.76, [214, 198, 172]],
  [1.00, [250, 245, 236]],
];
const DEAD = [196, 85, 63];

function ramp(t) {
  t = Math.max(0, Math.min(1, t));
  for (let k = 1; k < RAMP.length; k++) {
    const [t1, c1] = RAMP[k];
    if (t <= t1) {
      const [t0, c0] = RAMP[k - 1];
      const f = (t - t0) / (t1 - t0 || 1);
      return [0, 1, 2].map((i) => Math.round(c0[i] + f * (c1[i] - c0[i])));
    }
  }
  return RAMP[RAMP.length - 1][1];
}

function b64bytes(s) {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// IEEE half floats, little-endian, as the backend's numpy "<f2".
function decodeHalf(s) {
  const b = b64bytes(s);
  const n = b.length >> 1;
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const h = b[2 * i] | (b[2 * i + 1] << 8);
    const sign = h & 0x8000 ? -1 : 1;
    const e = (h >> 10) & 0x1f;
    const m = h & 0x3ff;
    out[i] = e === 0 ? sign * m * 2 ** -24 : e === 31 ? (m ? NaN : sign * Infinity) : sign * (1 + m / 1024) * 2 ** (e - 15);
  }
  return out;
}

const VERDICT = { good: "Breezy", fair: "Some air", poor: "Stuffy", open: "Open air" };

export class AirflowView {
  constructor(host, { onHover } = {}) {
    this.host = host;
    this.onHover = onHover;
    this.reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const mk = (cls) => { const c = document.createElement("canvas"); c.className = `air-canvas ${cls}`; host.append(c); return c; };
    this.base = mk("air-canvas--base");
    this.trail = mk("air-canvas--trail");
    this.over = mk("air-canvas--over");
    this.tip = document.createElement("div");
    this.tip.className = "air-tip";
    this.tip.hidden = true;
    host.append(this.tip);
    this.timeScale = 1.6;
    this.playing = !this.reduced;
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this._tick = this._tick.bind(this);
    this._move = this._move.bind(this);
    this.over.addEventListener("pointermove", this._move);
    this.over.addEventListener("pointerleave", () => { this.tip.hidden = true; this.hot = null; this.drawOverlay(); });
    this.last = performance.now();
    this.raf = requestAnimationFrame(this._tick);
  }

  setData(d) {
    this.d = d;
    const { nx, ny } = d.grid;
    this.u = decodeHalf(d.u);
    this.v = decodeHalf(d.v);
    this.mask = b64bytes(d.mask);
    // Speed field and the cells particles may be born in. Cells inside the
    // building are weighted up: that is where the reader is looking.
    const speed = new Float32Array(nx * ny);
    let top = 0;
    for (let i = 0; i < speed.length; i++) { speed[i] = Math.hypot(this.u[i], this.v[i]); }
    this.speed = speed;
    const inside = new Uint8Array(nx * ny);
    const cx = (x) => (x - d.grid.x0) / d.grid.cell, cy = (y) => (y - d.grid.y0) / d.grid.cell;
    const oc = document.createElement("canvas"); oc.width = nx; oc.height = ny;
    const g = oc.getContext("2d");
    g.fillStyle = "#fff";
    for (const r of d.rooms) {
      g.beginPath();
      r.polygon.forEach(([x, y], k) => (k ? g.lineTo(cx(x), cy(y)) : g.moveTo(cx(x), cy(y))));
      g.closePath(); g.fill();
    }
    const px = g.getImageData(0, 0, nx, ny).data;
    for (let i = 0; i < nx * ny; i++) inside[i] = px[i * 4] > 127 ? 1 : 0;
    this.inside = inside;
    // Indoor air is a fraction of the wind outside, so the two are lit on
    // their own scales: the rooms are what the reader came to see.
    const pct = (arr) => { const a = arr.filter((s) => s > 0).sort((x, y) => x - y); return a[Math.floor(a.length * 0.97)] || 0; };
    const sIn = [], sOut = [];
    for (let i = 0; i < nx * ny; i++) if (this.mask[i] === 1) (inside[i] ? sIn : sOut).push(speed[i]);
    this.topIn = Math.max(pct(sIn), 0.05 * d.wind.speed);
    this.topOut = Math.max(pct(sOut), 1e-6);
    this.top = this.topIn;
    const live = [], liveIn = [];
    for (let i = 0; i < nx * ny; i++) if (this.mask[i] === 1) (inside[i] ? liveIn : live).push(i);
    this.liveOut = Uint32Array.from(live);
    this.liveIn = Uint32Array.from(liveIn);
    this.fieldImage();
    this.resize();
    this.seed();
  }

  // The speed field as a small image, smoothed up to screen size when drawn.
  fieldImage() {
    const { nx, ny } = this.d.grid;
    const c = document.createElement("canvas"); c.width = nx; c.height = ny;
    const g = c.getContext("2d");
    const img = g.createImageData(nx, ny);
    for (let i = 0; i < nx; i++) {
      for (let j = 0; j < ny; j++) {
        const k = j * nx + i;
        const o = ((ny - 1 - j) * nx + i) * 4;       // plan y up, image y down
        const m = this.mask[k];
        let rgb;
        if (m === 0) rgb = [10, 9, 8];
        else if (m === 2) rgb = DEAD.map((c) => Math.round(c * 0.32));
        else rgb = this.inside[k] ? ramp(Math.pow(this.speed[k] / this.topIn, 0.6)) : ramp(0.05 + 0.13 * Math.pow(this.speed[k] / this.topOut, 0.8));
        img.data[o] = rgb[0]; img.data[o + 1] = rgb[1]; img.data[o + 2] = rgb[2]; img.data[o + 3] = 255;
      }
    }
    g.putImageData(img, 0, 0);
    this.field = c;
  }

  resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    for (const c of [this.base, this.trail, this.over]) {
      c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
      c.style.width = `${w}px`; c.style.height = `${h}px`;
    }
    this.dpr = dpr;
    this.W = w; this.H = h;
    if (!this.d) return;
    const { nx, ny, cell } = this.d.grid;
    const pad = 28;
    this.k = Math.min((w - pad * 2) / (nx * cell), (h - pad * 2) / (ny * cell));
    this.ox = (w - nx * cell * this.k) / 2;
    this.oy = (h - ny * cell * this.k) / 2;
    this.drawBase();
    this.drawOverlay();
    this.trail.getContext("2d").clearRect(0, 0, this.trail.width, this.trail.height);
    if (this.reduced) this.drawStreamlines();
  }

  // Model metres to CSS pixels.
  sx(x) { return this.ox + (x - this.d.grid.x0) * this.k; }
  sy(y) { return this.H - this.oy - (y - this.d.grid.y0) * this.k; }

  drawBase() {
    const g = this.base.getContext("2d");
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    g.fillStyle = "#0b0a09"; g.fillRect(0, 0, this.W, this.H);
    const { nx, ny, cell } = this.d.grid;
    g.imageSmoothingEnabled = true;
    g.imageSmoothingQuality = "high";
    g.drawImage(this.field, this.ox, this.oy, nx * cell * this.k, ny * cell * this.k);
  }

  drawOverlay() {
    if (!this.d) return;
    const g = this.over.getContext("2d");
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    g.clearRect(0, 0, this.W, this.H);
    const path = (pts) => { g.beginPath(); pts.forEach(([x, y], k) => (k ? g.lineTo(this.sx(x), this.sy(y)) : g.moveTo(this.sx(x), this.sy(y)))); g.closePath(); };

    // Rooms that stay stuffy get a hatched brick wash; the hovered room lifts.
    for (const r of this.d.rooms) {
      path(r.polygon);
      if (r.verdict === "poor") {
        g.fillStyle = "rgba(196,85,63,0.16)"; g.fill();
      }
      if (this.hot === r) {
        g.fillStyle = "rgba(237,230,220,0.07)"; g.fill();
        g.strokeStyle = "rgba(237,230,220,0.6)"; g.lineWidth = 1.5; g.stroke();
      }
    }
    // Walls.
    g.fillStyle = "#ede6dc";
    for (const w of this.d.walls) { path(w); g.fill(); }
    // Openings: inlets and outlets by the sign of the solved flow.
    for (const o of this.d.openings) {
      if (!o.open || !o.exterior || !o.normal || Math.abs(o.flow) < 0.01) continue;
      const room = this.d.rooms.find((r) => o.rooms.includes(r.id));
      if (!room) continue;
      // The normal is arbitrary; orient it into the room.
      let [nx, ny] = o.normal;
      if ((room.centre[0] - o.x) * nx + (room.centre[1] - o.y) * ny < 0) { nx = -nx; ny = -ny; }
      const into = (o.flow * (o.normal[0] * nx + o.normal[1] * ny)) > 0;
      const x = this.sx(o.x), y = this.sy(o.y);
      const dx = nx * (into ? 1 : -1), dy = -ny * (into ? 1 : -1);
      const s = Math.max(6, Math.min(14, this.k * 0.45));
      g.save();
      g.translate(x - dx * s * 1.6, y - dy * s * 1.6);
      g.rotate(Math.atan2(dy, dx));
      g.beginPath(); g.moveTo(s * 0.9, 0); g.lineTo(-s * 0.5, -s * 0.6); g.lineTo(-s * 0.2, 0); g.lineTo(-s * 0.5, s * 0.6); g.closePath();
      g.fillStyle = into ? "#ede6dc" : "#c9b497";
      g.globalAlpha = 0.9; g.fill();
      g.restore();
    }
    // Labels: name, air changes and the verdict.
    g.textAlign = "center"; g.textBaseline = "middle";
    for (const r of this.d.rooms) {
      if (r.area < 2.5) continue;
      const xs = r.polygon.map((q) => q[0]);
      const roomPx = (Math.max(...xs) - Math.min(...xs)) * this.k;
      const fs = Math.max(8, Math.min(12, this.k * 0.4, roomPx / 9));
      const x = this.sx(r.centre[0]), y = this.sy(r.centre[1]);
      g.font = `600 ${fs}px Geist, system-ui, sans-serif`;
      const t1 = r.name.toUpperCase();
      const t2 = r.verdict === "open" ? "open air" : roomPx < 90 ? `${Math.round(r.ach)} ach` : `${Math.round(r.ach)} ach · ${r.mean_speed.toFixed(2)} m/s`;
      const w = Math.min(roomPx - 6, Math.max(g.measureText(t1).width, g.measureText(t2).width * 0.92) + 14);
      g.fillStyle = "rgba(11,10,9,0.72)";
      g.fillRect(x - w / 2, y - fs * 1.35, w, fs * 2.7);
      g.fillStyle = r.verdict === "poor" ? "#e2836f" : "#ede6dc";
      g.fillText(t1, x, y - fs * 0.55);
      g.font = `500 ${fs * 0.86}px Geist, system-ui, sans-serif`;
      g.fillStyle = "rgba(237,230,220,0.66)";
      g.fillText(t2, x, y + fs * 0.65);
    }
    // Wind arrow in the corner, pointing the way the air travels.
    const [wx, wy] = this.d.wind.vector;
    const cx = this.W - 54, cy = 54;
    g.strokeStyle = "rgba(237,230,220,0.3)"; g.lineWidth = 1;
    g.beginPath(); g.arc(cx, cy, 30, 0, Math.PI * 2); g.stroke();
    g.save(); g.translate(cx, cy); g.rotate(Math.atan2(-wy, wx));
    g.strokeStyle = "#ede6dc"; g.lineWidth = 2;
    g.beginPath(); g.moveTo(-22, 0); g.lineTo(18, 0); g.stroke();
    g.beginPath(); g.moveTo(22, 0); g.lineTo(12, -6); g.lineTo(12, 6); g.closePath(); g.fillStyle = "#ede6dc"; g.fill();
    g.restore();
    g.font = "600 10px Geist, system-ui, sans-serif"; g.fillStyle = "rgba(237,230,220,0.6)";
    g.fillText(`FROM ${this.d.wind.label}`, cx, cy + 44);
    g.fillText("N", cx, cy - 38);
  }

  // Bilinear velocity at a model-space point, metres per second.
  vel(x, y) {
    const { x0, y0, cell, nx, ny } = this.d.grid;
    const fx = (x - x0) / cell - 0.5, fy = (y - y0) / cell - 0.5;
    const i = Math.floor(fx), j = Math.floor(fy);
    if (i < 0 || j < 0 || i >= nx - 1 || j >= ny - 1) return null;
    const a = fx - i, b = fy - j;
    const k = j * nx + i;
    if (this.mask[k] !== 1 && this.mask[k + 1] !== 1 && this.mask[k + nx] !== 1 && this.mask[k + nx + 1] !== 1) return null;
    const lerp = (f) => (f[k] * (1 - a) + f[k + 1] * a) * (1 - b) + (f[k + nx] * (1 - a) + f[k + nx + 1] * a) * b;
    return [lerp(this.u), lerp(this.v)];
  }

  spawn(p) {
    const { x0, y0, cell, nx } = this.d.grid;
    const pool = Math.random() < 0.5 && this.liveIn.length ? this.liveIn : this.liveOut;
    const k = pool[(Math.random() * pool.length) | 0];
    p.x = x0 + ((k % nx) + Math.random()) * cell;
    p.y = y0 + (Math.floor(k / nx) + Math.random()) * cell;
    p.age = 0;
    p.life = 2.5 + Math.random() * 4;
  }

  seed() {
    const area = this.W * this.H;
    const n = Math.round(Math.min(5200, Math.max(1400, area / 220)));
    this.parts = Array.from({ length: n }, () => { const p = {}; this.spawn(p); p.age = Math.random() * p.life; return p; });
  }

  step(dt) {
    const g = this.trail.getContext("2d");
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    // Fade the trails rather than clearing them: a particle leaves a short
    // comet whose length is its speed.
    g.globalCompositeOperation = "destination-out";
    g.fillStyle = `rgba(0,0,0,${Math.min(0.5, dt * 5.5)})`;
    g.fillRect(0, 0, this.W, this.H);
    g.globalCompositeOperation = "lighter";
    g.lineCap = "round";
    const sdt = dt * this.timeScale;
    const buckets = [[], [], [], []];
    for (const p of this.parts) {
      p.age += dt;
      const v1 = this.vel(p.x, p.y);
      if (!v1 || p.age > p.life) { this.spawn(p); continue; }
      const mx = p.x + v1[0] * sdt * 0.5, my = p.y + v1[1] * sdt * 0.5;
      const v2 = this.vel(mx, my) || v1;
      const nx = p.x + v2[0] * sdt, ny = p.y + v2[1] * sdt;
      const { x0, y0, cell, nx: gx } = this.d.grid;
      const inRoom = this.inside[Math.floor((p.y - y0) / cell) * gx + Math.floor((p.x - x0) / cell)];
      // Outdoors the motes stay faint so the eye goes to the rooms.
      const s = Math.hypot(v2[0], v2[1]) / (inRoom ? this.topIn : this.topOut * 3.5);
      if (s < 0.004) { p.age += dt * 3; }
      const b = s > 0.55 ? 3 : s > 0.25 ? 2 : s > 0.08 ? 1 : 0;
      const ax = this.sx(p.x), ay = this.sy(p.y), bx = this.sx(nx), by = this.sy(ny);
      // A mote that is barely moving is not drawn: still air should read as
      // empty, not as glitter.
      if (Math.abs(bx - ax) + Math.abs(by - ay) > 0.12) buckets[b].push(ax, ay, bx, by);
      p.x = nx; p.y = ny;
    }
    const styles = ["rgba(160,132,102,0.30)", "rgba(214,198,172,0.42)", "rgba(240,232,218,0.55)", "rgba(255,250,242,0.75)"];
    const widths = [0.9, 1.1, 1.3, 1.5];
    buckets.forEach((seg, b) => {
      if (!seg.length) return;
      g.strokeStyle = styles[b]; g.lineWidth = widths[b];
      g.beginPath();
      for (let i = 0; i < seg.length; i += 4) { g.moveTo(seg[i], seg[i + 1]); g.lineTo(seg[i + 2], seg[i + 3]); }
      g.stroke();
    });
    g.globalCompositeOperation = "source-over";
  }

  // Reduced motion: the same field as still streamlines.
  drawStreamlines() {
    if (!this.d) return;
    const g = this.trail.getContext("2d");
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    g.clearRect(0, 0, this.W, this.H);
    g.strokeStyle = "rgba(237,230,220,0.5)"; g.lineWidth = 1;
    const { x0, y0, cell, nx } = this.d.grid;
    const pool = [...this.liveIn.filter((_, i) => i % 40 === 0), ...this.liveOut.filter((_, i) => i % 160 === 0)];
    for (const k of pool) {
      let x = x0 + ((k % nx) + 0.5) * cell, y = y0 + (Math.floor(k / nx) + 0.5) * cell;
      g.beginPath(); g.moveTo(this.sx(x), this.sy(y));
      for (let s = 0; s < 60; s++) {
        const v = this.vel(x, y); if (!v) break;
        const m = Math.hypot(v[0], v[1]); if (m < 1e-4) break;
        x += (v[0] / m) * cell; y += (v[1] / m) * cell;
        g.lineTo(this.sx(x), this.sy(y));
      }
      g.stroke();
    }
  }

  _tick(now) {
    this.raf = requestAnimationFrame(this._tick);
    const dt = Math.min(0.05, (now - this.last) / 1000);
    this.last = now;
    if (this.d && this.playing && !this.reduced && this.parts) this.step(dt);
  }

  _move(e) {
    if (!this.d) return;
    const r = this.over.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    const x = this.d.grid.x0 + (px - this.ox) / this.k;
    const y = this.d.grid.y0 + (this.H - this.oy - py) / this.k;
    const hit = this.d.rooms.find((rm) => {
      let inside = false; const P = rm.polygon;
      for (let i = 0, j = P.length - 1; i < P.length; j = i++) {
        const [xi, yi] = P[i], [xj, yj] = P[j];
        if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
      }
      return inside;
    }) || null;
    const v = this.vel(x, y);
    if (hit !== this.hot) { this.hot = hit; this.drawOverlay(); }
    if (!hit && !v) { this.tip.hidden = true; return; }
    this.tip.hidden = false;
    this.tip.style.left = `${Math.min(px + 14, this.W - 220)}px`;
    this.tip.style.top = `${Math.min(py + 14, this.H - 120)}px`;
    const here = v ? `${Math.hypot(v[0], v[1]).toFixed(2)} m/s here` : "inside the wall";
    this.tip.innerHTML = hit
      ? `<b>${hit.name}</b><span>${VERDICT[hit.verdict] || ""}${hit.mode === "cross" ? " · cross-ventilated" : hit.mode === "single" ? " · single-sided" : hit.mode === "sealed" ? " · sealed" : " · borrowed air"}</span>`
        + `<span>${hit.ach} air changes / hour · ${hit.flow_m3h} m³/h</span><span>mean ${hit.mean_speed} m/s · ${Math.round(hit.still_share * 100)}% still</span><span class="air-tip__here">${here}</span>`
      : `<span class="air-tip__here">${here}</span>`;
    this.onHover?.(hit);
  }

  setPlaying(on) { this.playing = on; }

  dispose() {
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    this.host.innerHTML = "";
  }
}
