/* ═══════════════════════════════════════════════════════════════════════
   ThermalView: how hot each room gets through the day, and why.

   The backend runs every room hour by hour through a design day of the
   nearest city's climate (thermal.py): the sun on each wall and the roof,
   the glass, the breeze the wind solve found, people and cooking, and the
   brick and concrete that store the day's heat into the evening. This draws:

   - the floor as a heat map at the chosen hour, scrubbed or played through
     the day, with the sun's bearing and the outdoor temperature beside it;
   - each room's 24 hours against the outdoor air and India's adaptive
     comfort band (IMAC), as air temperature or as it feels with the breeze
     and fans;
   - what heats the chosen room at its hottest hour, the AC it would need,
     and the fixes the model measured (a cool roof, deeper chajjas, opening
     the windows at night instead), each applied with a click.
   ═══════════════════════════════════════════════════════════════════════ */

const SVGNS = "http://www.w3.org/2000/svg";
const h = (t, c, x) => { const n = document.createElement(t); if (c) n.className = c; if (x != null) n.textContent = x; return n; };
const s = (t, a = {}) => { const n = document.createElementNS(SVGNS, t); for (const k in a) n.setAttribute(k, a[k]); return n; };
const hr = (x) => `${String(x).padStart(2, "0")}:00`;
const ampm = (x) => (x === 0 ? "12 am" : x < 12 ? `${x} am` : x === 12 ? "12 pm" : `${x - 12} pm`);

// Cool to hot: monsoon blue through comfortable sage and sand to brick.
const STOPS = [[18, [74, 112, 150]], [24, [96, 146, 138]], [28, [150, 168, 120]], [31, [214, 190, 120]],
  [34, [222, 142, 74]], [37, [196, 85, 63]], [41, [140, 42, 38]]];
export function heat(t) {
  if (t <= STOPS[0][0]) return `rgb(${STOPS[0][1]})`;
  for (let k = 1; k < STOPS.length; k++) {
    const [t1, c1] = STOPS[k];
    if (t <= t1) {
      const [t0, c0] = STOPS[k - 1];
      const f = (t - t0) / (t1 - t0);
      return `rgb(${c0.map((c, i) => Math.round(c + f * (c1[i] - c)))})`;
    }
  }
  return `rgb(${STOPS[STOPS.length - 1][1]})`;
}

const PARTS = [["roof", "Roof slab"], ["walls", "Outside walls"], ["windows", "Sun through glass"], ["people", "People, lights, cooking"], ["air", "Outdoor air in"]];
const SEASONS = [["summer", "Hottest month"], ["monsoon", "Wettest month"], ["winter", "Coolest month"]];
const LOOKS = [["camera", "Thermal camera"], ["rooms", "Room colours"]];

// A thermal camera's "ironbow": cold black-violet through magenta and orange to white-hot.
const IRON = [[0, [6, 4, 24]], [0.16, [40, 8, 104]], [0.34, [128, 16, 140]], [0.52, [208, 52, 72]],
  [0.68, [244, 116, 24]], [0.84, [252, 196, 40]], [1, [255, 252, 228]]];
function iron(f) {
  f = Math.max(0, Math.min(1, f));
  for (let k = 1; k < IRON.length; k++) {
    const [t1, c1] = IRON[k];
    if (f <= t1) {
      const [t0, c0] = IRON[k - 1];
      const g = (f - t0) / (t1 - t0);
      return [c0[0] + g * (c1[0] - c0[0]), c0[1] + g * (c1[1] - c0[1]), c0[2] + g * (c1[2] - c0[2])];
    }
  }
  return IRON[IRON.length - 1][1];
}
const segDist = (px, py, a, b) => {
  const dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy || 1e-9;
  const t = Math.max(0, Math.min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / L2));
  return Math.hypot(px - a[0] - t * dx, py - a[1] - t * dy);
};
const inPoly = (x, y, poly) => {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
};
const WINDOWS = [["open", "Open all day"], ["night", "Open at night"], ["shut", "Shut"]];
const CHAJJA = [[0.3, "Slim"], [0.6, "Standard"], [0.9, "Deep"]];

export class ThermalView {
  /** host: the pane body; opts: { api, planId, level, levels, floorName, state, onLevel } */
  constructor(host, opts) {
    this.host = host; this.o = opts;
    this.st = opts.state;
    this.st.hour ??= 15; this.st.feel ??= false; this.st.look ??= "camera";
    this.st.years ||= {};
    this.data = null; this.timer = 0; this.req = 0;
    this.root = h("div", "th");
    host.append(this.root);
    this.build();
    this.load();
  }

  dispose() { clearInterval(this.timer); this.timer = 0; this.root.remove(); }

  chips(label, items, value, on) {
    const g = h("div", "th-seg"); g.setAttribute("role", "radiogroup"); g.setAttribute("aria-label", label);
    g.append(h("span", "th-seg__label", label));
    for (const [v, name] of items) {
      const b = h("button", null, name); b.type = "button"; b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(v === value));
      b.addEventListener("click", () => { on(v); g.querySelectorAll("button").forEach((x, i) => x.setAttribute("aria-checked", String(items[i][0] === v))); });
      g.append(b);
    }
    return g;
  }

  toggle(label, key) {
    const b = h("button", "th-tog", label); b.type = "button";
    b.setAttribute("aria-pressed", String(!!this.st[key]));
    b.addEventListener("click", () => { this.st[key] = !this.st[key]; b.setAttribute("aria-pressed", String(this.st[key])); this.load(); });
    return b;
  }

  build() {
    const st = this.st;
    const ctl = h("div", "th-ctl");
    ctl.append(
      this.seasonChips = this.chips("Season", SEASONS, st.month ? null : st.season, (v) => { st.season = v; st.month = null; this.load(); }),
      this.chips("Windows", WINDOWS, st.windows, (v) => { st.windows = v; this.load(); }),
      this.chips("Sunshades", CHAJJA, st.chajja, (v) => { st.chajja = v; this.load(); }),
    );
    const togs = h("div", "th-togs");
    togs.append(this.toggle("Ceiling fans", "fans"), this.toggle("Cool roof", "cool_roof"));
    ctl.append(togs);

    // The city's year: each month's average range, with how hot the house gets.
    this.yearBox = h("div", "th-year");
    this.head = h("div", "th-head");
    const grid = h("div", "th-grid");
    const left = h("div", "th-left");
    this.planBox = h("div", "th-plan");
    this.planBox.setAttribute("role", "img");
    // The day: a scrubber and a play button.
    const day = h("div", "th-day");
    this.playBtn = h("button", "th-play", "Play the day"); this.playBtn.type = "button";
    this.playBtn.addEventListener("click", () => this.play());
    this.slider = h("input", "th-slider"); this.slider.type = "range"; this.slider.min = "0"; this.slider.max = "23"; this.slider.step = "1";
    this.slider.value = String(st.hour); this.slider.setAttribute("aria-label", "Hour of the day");
    this.slider.addEventListener("input", () => { st.hour = +this.slider.value; this.stop(); this.paintHour(); });
    this.clock = h("output", "th-clock");
    day.append(this.playBtn, this.slider, this.clock);
    const key = h("div", "th-key");
    this.keyLo = h("span", null, "Cooler"); this.keyHi = h("span", null, "Hotter");
    this.keyRamp = h("i", "th-key__ramp");
    key.append(this.chips("View", LOOKS, st.look, (v) => { st.look = v; this.paintPlan(); this.paintHour(); }), this.keyLo, this.keyRamp, this.keyHi);
    const feel = h("button", "th-tog th-tog--feel", "Show as it feels"); feel.type = "button";
    feel.setAttribute("aria-pressed", String(st.feel));
    feel.title = "Air temperature, or how it feels with the breeze and fans";
    feel.addEventListener("click", () => { st.feel = !st.feel; feel.setAttribute("aria-pressed", String(st.feel)); this.paintHour(); this.paintRoom(); });
    key.append(feel);
    left.append(this.planBox, day, key);

    const right = h("div", "th-right");
    this.chartBox = h("div", "th-card th-chart");
    this.roomBox = h("div", "th-card th-room");
    this.fixBox = h("div", "th-card th-fixes");
    right.append(this.chartBox, this.roomBox, this.fixBox);
    grid.append(left, right);
    this.table = h("div", "th-card th-table");
    this.note = h("p", "th-note");
    this.root.append(ctl, this.yearBox, this.head, grid, this.table, this.note);
  }

  async load() {
    const st = this.st;
    const setup = { windows: st.windows, fans: String(st.fans), cool_roof: String(st.cool_roof), chajja: String(st.chajja) };
    const q = new URLSearchParams({ season: st.season, ...setup });
    if (st.month) q.set("month", String(st.month));
    this.setupKey = new URLSearchParams(setup).toString();
    const my = ++this.req;
    this.root.classList.add("is-busy");
    this.head.textContent = "Working out the temperatures…";
    try {
      const r = await fetch(`${this.o.api}/plans/${this.o.planId}/thermal?${q}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      if (my !== this.req) return;
      this.data = d;
      const here = d.rooms.filter((x) => x.level === this.o.level);
      if (!here.some((x) => x.id === st.room)) st.room = (here.find((x) => x.habitable && x.name === d.summary.hottest?.name) || here.find((x) => x.habitable) || here[0])?.id;
      this.render();
      this.loadYear();
    } catch (e) {
      if (my === this.req) this.head.textContent = `The temperatures could not be worked out (${e.message}).`;
    } finally {
      if (my === this.req) this.root.classList.remove("is-busy");
    }
  }

  // The year under the same set-up: fetched once per set-up, after the day.
  async loadYear() {
    const key = this.setupKey, years = this.st.years;
    if (!years[key]) {
      try {
        const r = await fetch(`${this.o.api}/plans/${this.o.planId}/thermal/year?${key}`);
        if (r.ok) years[key] = await r.json();
      } catch { /* the strip shows the city's averages alone */ }
    }
    if (key === this.setupKey) this.paintYear();
  }

  paintYear() {
    const d = this.data, box = this.yearBox;
    if (!d) return;
    const year = this.st.years[this.setupKey]?.months;
    box.innerHTML = "";
    const head = h("div", "th-year__head");
    head.append(h("span", "th-card__k", `${d.city} through the year`),
      h("span", "th-year__hint", year ? "Bars: the month's average outdoor low to high · tick: the hottest room inside · tap a month" : "The month's average outdoor low to high · tap a month"));
    box.append(head);
    const all = d.normals.flatMap((m) => [m.min, m.max]).concat(year ? year.map((m) => m.indoor_peak) : []);
    const lo = Math.floor(Math.min(...all)) - 1, hi = Math.ceil(Math.max(...all)) + 1;
    const pos = (v) => ((v - lo) / (hi - lo)) * 100;
    const row = h("div", "th-year__row"); row.setAttribute("role", "radiogroup"); row.setAttribute("aria-label", "Month");
    for (const m of d.normals) {
      const y = year?.[m.month - 1];
      const b = h("button", "th-mo"); b.type = "button"; b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(m.month === d.month));
      b.title = `${m.name}: ${m.min}–${m.max}°C outdoors, ${m.humidity}% humidity` + (y ? ` · hottest room ${y.indoor_peak}°C · comfortable ${y.comfort_hours} h a day` : "");
      const col = h("span", "th-mo__col");
      const bar = h("i", "th-mo__bar");
      bar.style.bottom = `${pos(m.min)}%`; bar.style.height = `${pos(m.max) - pos(m.min)}%`;
      bar.style.background = `linear-gradient(0deg, ${heat(m.min)}, ${heat(m.max)})`;
      col.append(bar);
      if (y) { const t = h("i", "th-mo__in"); t.style.bottom = `${pos(y.indoor_peak)}%`; col.append(t); }
      b.append(h("span", "th-mo__t", `${Math.round(m.max)}°`), col, h("span", "th-mo__n", m.name),
        h("span", "th-mo__c", y ? `${y.comfort_hours} h` : ""));
      b.addEventListener("click", () => { this.st.month = m.month; this.seasonChips?.querySelectorAll("button").forEach((x) => x.setAttribute("aria-checked", "false")); this.load(); });
      row.append(b);
    }
    box.append(row);
  }

  rooms() { return (this.data?.rooms || []).filter((x) => x.level === this.o.level); }
  val(r, hour) { return (this.st.feel ? r.feels : r.temps)[hour]; }

  render() {
    const d = this.data, sm = d.summary;
    this.head.innerHTML = "";
    const stat = (k, v, sub) => { const b = h("div", "th-stat"); b.append(h("span", "th-stat__k", k), h("b", null, v)); if (sub) b.append(h("span", "th-stat__s", sub)); return b; };
    this.head.append(
      stat(`${d.city} · ${d.month_name} averages`, `${d.climate.min}–${d.climate.max}°C`, `outdoors · ${d.climate.humidity}% humidity · wind from ${d.climate.wind}`),
      stat("Hottest room", sm.hottest ? `${sm.hottest.peak}°C` : "—", sm.hottest ? `${sm.hottest.name} at ${ampm(sm.hottest.hour)} · ${sm.indoor_over_outdoor >= 0 ? "+" : ""}${sm.indoor_over_outdoor}° on the outdoor high` : ""),
      stat("Coolest room", sm.coolest ? `${sm.coolest.peak}°C` : "—", sm.coolest ? `${sm.coolest.name}, at its hottest` : ""),
      stat("Comfortable", `${sm.comfort_hours} h`, `a day, average living room or bedroom · comfort ${d.comfort.low}–${d.comfort.high}°C`),
      stat("Air-conditioning", sm.ac_tons ? `${sm.ac_tons} TR` : "—", "to hold 26°C, all rooms with AC"),
    );
    this.paintYear();
    this.paintPlan();
    this.paintHour();
    this.paintRoom();
    this.paintFixes();
    this.paintTable();
    this.note.textContent = `${d.comfort.model}. Climate: ${d.city}'s monthly averages (IMD climatological normals, rounded); sun from the NOAA algorithm; air changes from the breeze solve. A concept-stage model: it ranks the rooms and sizes each fix, but it is not a full simulation.`;
  }

  // ── the floor as a heat map ─────────────────────────────────────────
  paintPlan() {
    const rooms = this.rooms();
    this.planBox.innerHTML = "";
    if (!rooms.length) { this.planBox.append(h("p", "th-empty", "No indoor rooms on this floor.")); return; }
    const pts = rooms.flatMap((r) => r.polygon);
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const pad = 2.2;
    const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
    const svg = s("svg", { viewBox: `${x0} ${-y1} ${x1 - x0} ${y1 - y0}`, class: "th-svg", preserveAspectRatio: "xMidYMid meet" });
    this.svgBox = { x0, x1, y0, y1 };
    this.polys = new Map();
    const cam = this.st.look === "camera";
    this.planBox.classList.toggle("is-camera", cam);
    if (cam) {
      this.camImg = s("image", { x: x0, y: -y1, width: x1 - x0, height: y1 - y0, preserveAspectRatio: "none", class: "th-cam" });
      svg.append(this.camImg);
      this.prepCamera();
    } else this.cam = null;
    const fs = Math.max(0.32, Math.min(0.55, (x1 - x0) / 26));
    for (const r of rooms) {
      const g = s("g", { class: "th-rm", tabindex: "0", role: "button", "aria-label": r.name });
      const poly = s("polygon", { points: r.polygon.map((p) => `${p[0]},${-p[1]}`).join(" ") });
      const name = s("text", { x: r.centre[0], y: -r.centre[1] - fs * 0.55, "font-size": fs * 0.62, class: "th-rm__n" });
      name.textContent = r.name.toUpperCase();
      const t = s("text", { x: r.centre[0], y: -r.centre[1] + fs * 0.75, "font-size": fs * 1.35, class: "th-rm__t" });
      g.append(poly, name, t);
      const pick = () => { this.st.room = r.id; this.paintHour(); this.paintRoom(); };
      g.addEventListener("click", pick);
      g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
      svg.append(g);
      this.polys.set(r.id, { g, poly, t, r });
    }
    // The sun: an arrow from its bearing toward the house, when it is up.
    this.sunG = s("g", { class: "th-sun" });
    svg.append(this.sunG);
    // North.
    const nx = x1 - 1.1, ny = -y1 + 1.2;
    const north = s("g", { class: "th-north" });
    north.append(s("path", { d: `M ${nx} ${ny - 0.6} L ${nx + 0.32} ${ny + 0.35} L ${nx} ${ny + 0.15} L ${nx - 0.32} ${ny + 0.35} Z` }));
    const nt = s("text", { x: nx, y: ny + 1.05, "font-size": 0.42 }); nt.textContent = "N";
    north.append(nt);
    svg.append(north);
    this.planBox.append(svg);
    // A probe: point anywhere for the temperature there.
    this.probe = h("div", "th-probe"); this.probe.hidden = true;
    this.planBox.append(this.probe);
    svg.addEventListener("pointermove", (e) => {
      if (!this.cam?.field) { this.probe.hidden = true; return; }
      const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
      const m = pt.matrixTransform(svg.getScreenCTM().inverse());
      const c = this.cam, i = Math.floor((m.x - c.x0) / c.cell), jj = c.H - 1 - Math.floor((-m.y - c.y0) / c.cell);
      if (i < 0 || i >= c.W || jj < 0 || jj >= c.H) { this.probe.hidden = true; return; }
      const v = c.field[jj * c.W + i];
      const b = this.planBox.getBoundingClientRect();
      this.probe.hidden = false;
      this.probe.textContent = `${v.toFixed(1)}°C`;
      this.probe.style.left = `${e.clientX - b.left + 12}px`; this.probe.style.top = `${e.clientY - b.top - 28}px`;
    });
    svg.addEventListener("pointerleave", () => { this.probe.hidden = true; });
  }

  // ── the thermal camera ──────────────────────────────────────────────
  // The floor seen as an infrared camera would: each room's air, warmed or
  // cooled toward its walls by their inside surface temperature, glowing at
  // the windows the sun comes through, lifted by a hot roof slab overhead;
  // the walls themselves at their surface temperature; and the open ground
  // round the house. Weights are worked out once per floor, then each hour
  // is a weighted sum.
  prepCamera() {
    const rooms = this.rooms(), { x0, x1, y0, y1 } = this.svgBox;
    const cell = Math.max(0.06, Math.min(0.12, (x1 - x0) / 220));
    const W = Math.ceil((x1 - x0) / cell), H = Math.ceil((y1 - y0) / cell);
    const owner = new Int16Array(W * H).fill(-1);
    rooms.forEach((r, ri) => {
      const xs = r.polygon.map((p) => p[0]), ys = r.polygon.map((p) => p[1]);
      const i0 = Math.max(0, Math.floor((Math.min(...xs) - x0) / cell)), i1 = Math.min(W - 1, Math.ceil((Math.max(...xs) - x0) / cell));
      const j0 = Math.max(0, Math.floor((Math.min(...ys) - y0) / cell)), j1 = Math.min(H - 1, Math.ceil((Math.max(...ys) - y0) / cell));
      for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
        if (inPoly(x0 + (i + 0.5) * cell, y0 + (j + 0.5) * cell, r.polygon)) owner[j * W + i] = ri;
      }
    });
    // Every outside wall face and window on the floor.
    const faces = [];
    rooms.forEach((r, ri) => (r.faces || []).forEach((f) => faces.push({ ri, f })));
    // Per pixel: [kind, face index, weight] - kind 0 inside surface, 1 glass, 2 outside skin.
    const terms = new Array(W * H);
    for (let j = 0; j < H; j++) for (let i = 0; i < W; i++) {
      const k = j * W + i, px = x0 + (i + 0.5) * cell, py = y0 + (j + 0.5) * cell, own = owner[k];
      const list = [];
      faces.forEach(({ ri, f }, fi) => {
        const d = segDist(px, py, f.a, f.b);
        if (own >= 0) {
          if (ri !== own || d > 2.2) return;
          list.push([0, fi, d < 0.14 ? 1.2 : Math.exp(-d / 0.45) * 0.55]);
          if (f.glass) for (const w of f.windows) {
            const dw = segDist(px, py, w.a, w.b);
            if (dw < 2.6) list.push([1, fi, Math.exp(-dw / 0.7) * 0.8]);
          }
        } else if (d < 1.6) list.push([2, fi, d < 0.16 ? 1.2 : Math.exp(-d / 0.35) * 0.6]);
      });
      terms[k] = list;
    }
    this.cam = { x0, y0, cell, W, H, owner, terms, faces, rooms };
    // The image covers exactly the sampled grid.
    for (const [k, v] of Object.entries({ x: x0, y: -(y0 + H * cell), width: W * cell, height: H * cell })) this.camImg.setAttribute(k, v);
    // One scale for the whole day, so scrubbing the hours compares like with
    // like; exposed, as a camera aimed at a home would be, for the inside -
    // the rooms, their walls, glass and ceilings - so a sunbaked yard or
    // wall skin simply reads white-hot.
    const vals = [];
    for (const r of rooms) {
      vals.push(...r.temps);
      if (r.ceiling) vals.push(...r.ceiling.map((t, h) => r.temps[h] + 0.2 * (t - r.temps[h])));
      for (const f of r.faces || []) { vals.push(...f.inside); if (f.glass) vals.push(...f.glass); }
    }
    this.cam.lo = Math.floor(Math.min(...vals) - 1.5);
    this.cam.hi = Math.ceil(Math.max(...vals) + 1.5);
    const c1 = document.createElement("canvas"); c1.width = W; c1.height = H;
    const c2 = document.createElement("canvas"); c2.width = W * 3; c2.height = H * 3;
    this.cam.small = c1; this.cam.big = c2;
  }

  drawCamera(hour) {
    const c = this.cam, d = this.data;
    const { W, H, owner, terms, faces, rooms, lo, hi } = c;
    const field = c.field || (c.field = new Float32Array(W * H));
    const ground = d.ground[hour];
    const ctx = c.small.getContext("2d");
    const img = ctx.createImageData(W, H);
    for (let j = 0; j < H; j++) for (let i = 0; i < W; i++) {
      const k = j * W + i, own = owner[k];
      let base;
      if (own >= 0) {
        const r = rooms[own], ta = r.temps[hour];
        base = r.ceiling ? ta + 0.2 * (r.ceiling[hour] - ta) : ta;
      } else base = ground;
      let acc = 0, sw = 0;
      for (const [kind, fi, w] of terms[k]) {
        const f = faces[fi].f;
        const t = kind === 0 ? f.inside[hour] : kind === 1 ? f.glass[hour] : f.outside[hour];
        acc += w * (t - base); sw += w;
      }
      const v = base + (sw > 1 ? acc / sw : acc);
      // Canvas rows run top-down; plan y runs up.
      const kk = (H - 1 - j) * W + i;
      field[kk] = v;
      const [r, g, b] = iron((v - lo) / (hi - lo));
      img.data[kk * 4] = r; img.data[kk * 4 + 1] = g; img.data[kk * 4 + 2] = b; img.data[kk * 4 + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    // Smooth it as a camera's optics would.
    const big = c.big.getContext("2d");
    big.filter = "blur(2.5px)";
    big.imageSmoothingEnabled = true;
    big.drawImage(c.small, 0, 0, c.big.width, c.big.height);
    big.filter = "none";
    this.camImg.setAttribute("href", c.big.toDataURL("image/png"));
  }

  paintHour() {
    if (!this.data) return;
    const hour = this.st.hour, d = this.data;
    this.slider.value = String(hour);
    const sun = d.sun[hour];
    this.clock.textContent = `${ampm(hour)} · outdoors ${d.outdoor[hour]}°C${sun.altitude > 0 ? ` · sun ${Math.round(sun.altitude)}° up in the ${compass(sun.azimuth)}` : " · night"}`;
    const cam = this.st.look === "camera" && this.cam;
    if (cam) this.drawCamera(hour);
    this.keyRamp.classList.toggle("is-iron", !!cam);
    this.keyLo.textContent = cam ? `${this.cam.lo}°` : "Cooler";
    this.keyHi.textContent = cam ? `${this.cam.hi}°` : "Hotter";
    for (const { poly, t, r, g } of this.polys?.values() || []) {
      const v = this.val(r, hour);
      poly.setAttribute("fill", cam ? "transparent" : heat(v));
      t.textContent = `${v.toFixed(1)}°`;
      g.classList.toggle("is-on", r.id === this.st.room);
    }
    this.planBox.setAttribute("aria-label", `Room temperatures at ${ampm(hour)}`);
    // Sun arrow: plan +Y is the site's north; bearings come in true degrees.
    this.sunG.innerHTML = "";
    if (sun.altitude > 0 && this.svgBox) {
      const { x0, x1, y0, y1 } = this.svgBox;
      const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
      const a = (sun.azimuth - (d.north_angle || 0)) * Math.PI / 180;
      const R = Math.min(x1 - x0, y1 - y0) / 2 - 0.5;
      const sx = cx + Math.sin(a) * R, sy = cy + Math.cos(a) * R;
      const disc = s("circle", { cx: sx, cy: -sy, r: 0.45 });
      const ray = s("line", { x1: sx, y1: -sy, x2: sx - Math.sin(a) * 1.4, y2: -(sy - Math.cos(a) * 1.4) });
      this.sunG.append(ray, disc);
    }
    this.paintChartCursor();
  }

  // ── one room: its day, its heat, its AC ─────────────────────────────
  paintRoom() {
    const d = this.data; if (!d) return;
    const r = this.rooms().find((x) => x.id === this.st.room) || this.rooms()[0];
    this.chartBox.innerHTML = ""; this.roomBox.innerHTML = "";
    if (!r) return;
    // The chart: outdoor, comfort band, every room faint, this one bold.
    const W = 360, H = 170, L = 30, B = 22, T = 10;
    const all = this.rooms().flatMap((x) => (this.st.feel ? x.feels : x.temps)).concat(d.outdoor, [d.comfort.low, d.comfort.high]);
    const lo = Math.floor(Math.min(...all) - 1), hi = Math.ceil(Math.max(...all) + 1);
    const X = (i) => L + (i / 23) * (W - L - 8), Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "th-chart__svg", role: "img", "aria-label": `${r.name} through the day` });
    svg.append(s("rect", { x: L, y: Y(d.comfort.high), width: W - L - 8, height: Y(d.comfort.low) - Y(d.comfort.high), class: "th-band" }));
    for (let v = Math.ceil(lo / 2) * 2; v <= hi; v += 2) {
      svg.append(s("line", { x1: L, x2: W - 8, y1: Y(v), y2: Y(v), class: "th-gridl" }));
      const tx = s("text", { x: L - 5, y: Y(v) + 3, class: "th-axis", "text-anchor": "end" }); tx.textContent = `${v}°`; svg.append(tx);
    }
    for (const i of [0, 6, 12, 18, 23]) { const tx = s("text", { x: X(i), y: H - 6, class: "th-axis", "text-anchor": "middle" }); tx.textContent = hr(i).slice(0, 2); svg.append(tx); }
    const line = (vals, cls) => s("polyline", { points: vals.map((v, i) => `${X(i)},${Y(v)}`).join(" "), class: cls });
    for (const x of this.rooms()) if (x.id !== r.id) svg.append(line(this.st.feel ? x.feels : x.temps, "th-l th-l--other"));
    svg.append(line(d.outdoor, "th-l th-l--out"));
    svg.append(line(this.st.feel ? r.feels : r.temps, "th-l th-l--me"));
    this.cursor = s("line", { y1: T, y2: H - B, class: "th-cursor" });
    this.dot = s("circle", { r: 3.5, class: "th-dot" });
    svg.append(this.cursor, this.dot);
    this.chartX = X; this.chartY = Y; this.chartRoom = r;
    // Scrub the day on the chart too.
    svg.addEventListener("pointermove", (e) => {
      if (!(e.buttons & 1)) return;
      const b = svg.getBoundingClientRect();
      const i = Math.round(((e.clientX - b.left) / b.width * W - L) / (W - L - 8) * 23);
      this.st.hour = Math.max(0, Math.min(23, i)); this.stop(); this.paintHour();
    });
    const legend = h("div", "th-legend");
    legend.append(h("span", "th-lg th-lg--me", r.name), h("span", "th-lg th-lg--out", "Outdoors"), h("span", "th-lg th-lg--band", "Comfortable"));
    this.chartBox.append(h("span", "th-card__k", this.st.feel ? "Through the day, as it feels" : "Through the day"), svg, legend);
    this.paintChartCursor();

    // What heats it at its hottest hour.
    const parts = PARTS.map(([k, name]) => [name, r.at_peak[k] || 0]);
    const top = Math.max(1, ...parts.map(([, v]) => Math.abs(v)));
    const card = this.roomBox;
    const t = h("div", "th-room__head");
    t.append(h("b", null, r.name), h("span", null, `${r.peak}°C at ${ampm(r.peak_hour)} · ${r.low}°C at its coolest · comfortable ${r.comfort_hours} h`));
    card.append(t);
    card.append(h("span", "th-card__k", `What heats it at ${ampm(r.peak_hour)}`));
    for (const [name, v] of parts) {
      const row = h("div", `th-bar${v < 0 ? " is-cool" : ""}`);
      const bar = h("i"); bar.style.setProperty("--f", (Math.abs(v) / top).toFixed(3));
      row.append(h("span", null, name), bar, h("span", "th-bar__n", `${v > 0 ? "+" : ""}${(v / 1000).toFixed(2)} kW`));
      card.append(row);
    }
    const facts = h("ul", "th-facts");
    const vent = { cross: "cross-ventilated", single: "air from one side only", borrowed: "air only through other rooms", sealed: "no through-air" }[r.ventilation] || r.ventilation;
    facts.append(
      h("li", null, `Air: ${r.ach} changes an hour with windows open, ${vent}${r.breeze ? `, breeze ${r.breeze} m/s` : ""}`),
      h("li", null, r.roof_exposed ? "Under the roof slab: takes the sun all day" : "A floor above shields it from the roof"),
      h("li", null, r.facing.length ? `Windows face ${r.facing.join(", ")}` : "No outside windows"),
    );
    if (r.ac_tons) facts.append(h("li", "th-facts__ac", `AC to hold 26°C: ${r.ac_tons} TR (${(r.cooling_w / 1000).toFixed(1)} kW peak)`));
    card.append(facts);
  }

  paintChartCursor() {
    if (!this.cursor || !this.chartRoom) return;
    const i = this.st.hour, x = this.chartX(i);
    this.cursor.setAttribute("x1", x); this.cursor.setAttribute("x2", x);
    this.dot.setAttribute("cx", x); this.dot.setAttribute("cy", this.chartY(this.val(this.chartRoom, i)));
  }

  paintFixes() {
    const d = this.data, box = this.fixBox;
    box.innerHTML = "";
    box.append(h("span", "th-card__k", "What would help"));
    if (!d.fixes.length) { box.append(h("p", "th-empty", "Nothing the model tried improves on this set-up.")); return; }
    for (const f of d.fixes) {
      const b = h("button", "th-fix"); b.type = "button";
      const n = [f.peak_drop > 0 && `${f.peak_drop}°C cooler at the peak`, f.comfort_gain > 0 && `+${f.comfort_gain} h comfortable`].filter(Boolean).join(" · ");
      b.append(h("span", null, f.label), h("b", null, n));
      b.title = "Apply it";
      b.addEventListener("click", () => {
        // Apply it: the controls redraw to show the change, and the day reloads.
        Object.assign(this.st, f.change);
        this.stop(); this.root.innerHTML = ""; this.build(); this.load();
      });
      box.append(b);
    }
  }

  paintTable() {
    const d = this.data, box = this.table;
    box.innerHTML = "";
    box.append(h("span", "th-card__k", "Every room on this floor"));
    const t = h("table", "th-tbl");
    const head = h("tr");
    for (const c of ["Room", "Hottest", "When", "Coolest", "Comfortable", "Air changes", "AC"]) head.append(h("th", null, c));
    t.append(head);
    for (const r of [...this.rooms()].sort((a, b) => b.peak - a.peak)) {
      const tr = h("tr", r.id === this.st.room ? "is-on" : null);
      const sw = h("i", "th-sw"); sw.style.background = heat(r.peak);
      const name = h("td"); name.append(sw, document.createTextNode(r.name));
      tr.append(name, h("td", null, `${r.peak}°`), h("td", null, ampm(r.peak_hour)), h("td", null, `${r.low}°`),
        h("td", null, `${r.comfort_hours} h`), h("td", null, `${r.ach}/h`), h("td", null, r.ac_tons ? `${r.ac_tons} TR` : "—"));
      tr.addEventListener("click", () => { this.st.room = r.id; this.paintHour(); this.paintRoom(); this.paintTable(); });
      t.append(tr);
    }
    box.append(t);
  }

  play() {
    if (this.timer) { this.stop(); return; }
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) { this.st.hour = (this.st.hour + 1) % 24; this.paintHour(); return; }
    this.playBtn.textContent = "Pause";
    this.timer = setInterval(() => { this.st.hour = (this.st.hour + 1) % 24; this.paintHour(); }, 650);
  }

  stop() { clearInterval(this.timer); this.timer = 0; this.playBtn.textContent = "Play the day"; }
}

function compass(b) { return ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][Math.round(((b % 360) + 360) % 360 / 45) % 8]; }
