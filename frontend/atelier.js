/* ═══════════════════════════════════════════════════════════════════════
   Atelier

   The run, shown as the working session it is. Two architects and a site
   engineer walk onto the board and draw the real candidate schemes room by
   room while thirteen specialists read each sheet and say what they found;
   the lead architect chairs the vote. Nothing here is invented for effect:
   every plan drawn is the geometry the engine produced, and every line a
   specialist says is a message the engine emitted, attributed to the critic
   or stage that produced it.
   ═══════════════════════════════════════════════════════════════════════ */

const NS = "http://www.w3.org/2000/svg";
const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const easeOut = (t) => 1 - Math.pow(1 - t, 4);

/* ═══ THE PEOPLE ══════════════════════════════════════════════════════ */

export const PEOPLE = {
  "critic.compliance":    { name: "Building code officer", short: "Building code", role: "NBC 2016 & bye-laws", pig: "hingula",  glyph: "code" },
  "critic.daylight":      { name: "Daylight analyst",      short: "Daylight",      role: "Light & glare",       pig: "indigo",   glyph: "sun" },
  "critic.ventilation":   { name: "Ventilation analyst",   short: "Ventilation",   role: "Airflow",             pig: "indigo",   glyph: "wind" },
  "critic.privacy":       { name: "Privacy analyst",       short: "Privacy",       role: "Sightlines",          pig: "indigo",   glyph: "eye" },
  "critic.circulation":   { name: "Circulation analyst",   short: "Circulation",   role: "Movement",            pig: "indigo",   glyph: "path" },
  "critic.accessibility": { name: "Accessibility analyst", short: "Access",        role: "Universal access",    pig: "indigo",   glyph: "access" },
  "critic.spatial":       { name: "Spatial analyst",       short: "Spatial",       role: "Proportion & fit",    pig: "indigo",   glyph: "frame" },
  "critic.structure":     { name: "Structural engineer",   short: "Structure",     role: "Spans & grid",        pig: "ochre",    glyph: "column" },
  "critic.cost":          { name: "Quantity surveyor",     short: "Cost",          role: "Takeoff & budget",    pig: "ochre",    glyph: "rupee" },
  "critic.vastu":         { name: "Vastu consultant",      short: "Vastu",         role: "Placement & stance",  pig: "orpiment", glyph: "mandala" },
  "critic.coherence":     { name: "Design critic",         short: "Coherence",     role: "One clear idea",      pig: "orpiment", glyph: "compass" },
  "critic.brief":         { name: "Client advocate",       short: "Brief",         role: "What you asked for",  pig: "orpiment", glyph: "brief" },
  "critic.livability":    { name: "Livability reviewer",   short: "Livability",    role: "Daily life",          pig: "orpiment", glyph: "home" },
};

export const PRINCIPAL = { id: "principal", name: "Lead architect", short: "Lead", role: "Chairs the review", pig: "gold", glyph: "seal" };

export const DRAFTERS = [
  { id: "d.arch1",    name: "Architect",     short: "Architect", role: "Living rooms",    pig: "gold", glyph: "pen", zone: "public",  figure: "a1" },
  { id: "d.engineer", name: "Site engineer", short: "Engineer",  role: "Services & core", pig: "gold", glyph: "pen", zone: "service", figure: "b" },
  { id: "d.arch2",    name: "Architect",     short: "Architect", role: "Bedrooms",        pig: "gold", glyph: "pen", zone: "private", figure: "a2" },
];

export const GROUPS = [
  { title: "Code, structure & cost", ids: ["critic.compliance", "critic.structure", "critic.cost"] },
  { title: "Environment & use", ids: ["critic.daylight", "critic.ventilation", "critic.privacy",
    "critic.circulation", "critic.accessibility", "critic.spatial"] },
  { title: "Vastu & judgement", ids: ["critic.vastu", "critic.coherence", "critic.brief", "critic.livability"] },
];

const BY_ID = Object.fromEntries([
  ...Object.entries(PEOPLE).map(([id, p]) => [id, { id, ...p }]),
  [PRINCIPAL.id, PRINCIPAL],
  ...DRAFTERS.map((d) => [d.id, d]),
]);

/** A person by id, falling back to the committee charter for a critic this file does not know. */
export function person(id, charter = []) {
  if (BY_ID[id]) return BY_ID[id];
  const c = charter.find((x) => x.id === id);
  const short = c?.axis ? c.axis.replace(/_/g, " ") : "Specialist";
  return { id, name: c?.name || id, short, role: "Specialist", pig: "chalk", glyph: "frame" };
}

export const shortName = (p) => p.short || p.name;

/* Discipline glyphs, authored on one 16-unit grid at one stroke weight. */
const GLYPHS = {
  code: "M2 3.5h4.2A1.8 1.8 0 0 1 8 5.3V13a1.6 1.6 0 0 0-1.6-1.4H2zM14 3.5H9.8A1.8 1.8 0 0 0 8 5.3V13a1.6 1.6 0 0 1 1.6-1.4H14z",
  sun: "M8 5.2a2.8 2.8 0 1 0 0 5.6 2.8 2.8 0 0 0 0-5.6zM8 1.6v1.6M8 12.8v1.6M1.6 8h1.6M12.8 8h1.6M3.5 3.5l1.1 1.1M11.4 11.4l1.1 1.1M3.5 12.5l1.1-1.1M11.4 4.6l1.1-1.1",
  wind: "M2 6h7.4A2 2 0 1 0 7.5 3.6M2 10.5h9.6a2 2 0 1 1-1.9 2.4M2 8.2h5",
  eye: "M1.6 8S4 3.6 8 3.6 14.4 8 14.4 8 12 12.4 8 12.4 1.6 8 1.6 8zM8 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4z",
  path: "M3.5 13.5c0-3 1.9-4.2 4.5-4.2s4.5-1.2 4.5-4.4M3.5 13.5h.01M12.5 4.9h.01M3.5 15a1.5 1.5 0 1 0 0-3M12.5 6.4a1.5 1.5 0 1 0 0-3",
  access: "M7.2 3.4a1.2 1.2 0 1 0 0-.01M7.2 5v4.2h3.6l1.6 3.6M5.4 7.4a3.4 3.4 0 1 0 4.6 4.6",
  frame: "M2.2 5.4V2.2h3.2M10.6 2.2h3.2v3.2M13.8 10.6v3.2h-3.2M5.4 13.8H2.2v-3.2M5.6 5.6h4.8v4.8H5.6z",
  column: "M2.2 2.6h11.6M2.2 13.4h11.6M5.2 2.6v10.8M10.8 2.6v10.8",
  rupee: "M4.4 3h7.2M4.4 6h7.2M6.4 3c3.4 0 3.4 6 0 6H4.4l5.8 4.2",
  mandala: "M2.4 2.4h11.2v11.2H2.4zM6.1 2.4v11.2M9.9 2.4v11.2M2.4 6.1h11.2M2.4 9.9h11.2",
  compass: "M8 1.8v1.4M8 3.2a1.2 1.2 0 1 0 0 2.4 1.2 1.2 0 0 0 0-2.4zM7.4 5.4 3.8 14M8.6 5.4l3.6 8.6M5.2 10.6h5.6",
  brief: "M5.6 2.4h4.8v2H5.6zM4.4 3.4H3v10.4h10V3.4h-1.4M5.4 8h5.2M5.4 10.6h3.4",
  home: "M2.4 7.6 8 3l5.6 4.6V13.4H2.4zM6.6 13.4V9.6h2.8v3.8",
  seal: "M8 1.8 11.6 6 8 13.4 4.4 6zM8 6.6v3.2M8 6.6a.6.6 0 1 0 0-.01",
  pen: "M3 13l.9-3.4 7-7 2.5 2.5-7 7zM9.6 4l2.4 2.4",
};

export function glyph(name, cls = "gl") {
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("viewBox", "0 0 16 16");
  s.setAttribute("class", cls);
  s.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(NS, "path");
  p.setAttribute("d", GLYPHS[name] || GLYPHS.frame);
  s.append(p);
  return s;
}

/** A specialist's mark: their discipline's glyph in its pigment. */
export function avatar(p, size = 32) {
  const a = document.createElement("span");
  a.className = "av";
  a.dataset.pig = p.pig || "chalk";
  a.style.setProperty("--av", `${size}px`);
  a.append(glyph(p.glyph, "gl av__gl"));
  a.setAttribute("aria-hidden", "true");
  return a;
}

/* ═══ THE FIGURES ═════════════════════════════════════════════════════ */

// Drawn on a 44 x 64 grid; the pencil tip is where the line is being drawn.
const FIG = { w: 48, h: 70, tip: [40.6, 46.6] };
const TIP = [FIG.tip[0] * FIG.w / 44, FIG.tip[1] * FIG.h / 64];
const WALK = 0.3;   // px per ms

const LOOKS = {
  a1: { coat: "#E4E8EF", accent: "#E5A958", legs: "#3B4252", skin: "#B98463", hair: "bob" },
  a2: { coat: "#7FA3D4", accent: "#F3D063", legs: "#2E3442", skin: "#8D5A3B", hair: "short", glasses: true },
  b:  { coat: "#E8792F", accent: "#F5E9C9", legs: "#4A4E5C", skin: "#C99A75", hat: true },
};

function figureMarkup(kind) {
  const f = LOOKS[kind] || LOOKS.a1;
  const top = f.hat
    ? `<path d="M13.4 12.8Q13.8 6.2 20 6.2T26.6 12.8H28.6V14.4H11.4V12.8Z" fill="#F2B33D"/><path d="M19.6 6.4V10" stroke="#C98A1C" stroke-width="1"/>`
    : f.hair === "bob"
      ? `<path d="M13.6 15.8Q13.2 7 20 7T26.4 15.8L26.2 18.4Q25 12.8 20 12.6T13.8 18.4Z" fill="#1B1511"/>`
      : `<path d="M14 13.2Q14 7.4 20 7.4T26 13.2Q24 10.8 20 10.8T14 13.2Z" fill="#14100D"/>`;
  const eyes = f.glasses ? `<path d="M15.9 14.8h3M21.1 14.8h3M18.9 14.8h2.2" stroke="#0B0C10" stroke-width=".95"/>` : "";
  const front = f.hat
    ? `<path d="M13.4 30.2H26.6M13.4 34.4H26.6" stroke="${f.accent}" stroke-width="1.3"/>`
    : `<path d="M16.8 21.4L20 26.2L23.2 21.4" fill="none" stroke="${f.accent}" stroke-width="1.7"/>`;
  const held = f.hat
    ? `<rect x="7.4" y="29.6" width="5.8" height="7.6" rx=".9" fill="#ECE6D6" stroke="#0B0C10" stroke-width=".7" transform="rotate(-12 10.3 33.4)"/>`
    : `<rect x="8.4" y="30.6" width="3.4" height="10.4" rx="1.7" fill="#EDE6D3" stroke="#0B0C10" stroke-width=".7" transform="rotate(16 10.1 35.8)"/>`;
  return `<svg viewBox="0 0 44 64" class="fg__svg" aria-hidden="true">
    <ellipse class="fg-shadow" cx="20" cy="61.4" rx="9.5" ry="2"/>
    <g class="fg-body">
      <g class="fg-leg fg-leg-l"><path d="M18 39.4L16.4 59.4H13.2" stroke="${f.legs}"/></g>
      <g class="fg-leg fg-leg-r"><path d="M22 39.4L23.6 59.4H26.8" stroke="${f.legs}"/></g>
      <g class="fg-arm-b"><path d="M14.4 24.6L11.2 34" stroke="${f.coat}"/>${held}</g>
      <path class="fg-torso" d="M13.2 24.4Q13.2 21 16.6 21H23.4Q26.8 21 26.8 24.4V40.4H13.2Z" fill="${f.coat}"/>
      ${front}
      <circle class="fg-head" cx="20" cy="14.6" r="6" fill="${f.skin}"/>
      ${top}${eyes}
      <g class="fg-arm">
        <path d="M25.4 24.8L32.8 34.6L38.4 43" stroke="${f.coat}"/>
        <circle cx="38.6" cy="43.4" r="1.9" fill="${f.skin}"/>
        <path class="fg-pencil" d="M37.2 41L40.6 46.6"/>
      </g>
    </g>
  </svg>`;
}

/* ═══ STAGES ══════════════════════════════════════════════════════════ */

const STAGES = [
  ["interpret", "Brief"], ["retrieve", "Research"], ["generate", "Drafting"],
  ["critique", "Review"], ["consensus", "Vote"], ["debate", "Debate"],
  ["refine", "Refine"], ["negotiate", "Negotiate"], ["explain", "Rationale"],
];

const OWNER = {
  floorplan_architect: "d.arch1",
  vastu_compliance: "critic.vastu",
  cost_estimator: "critic.cost",
};

const CONSTRAINT = {
  "code.no_critical": "Code",
  "circulation.reachable": "Circulation",
  "daylight.statutory": "Daylight",
  "ventilation.adequate": "Ventilation",
  "vastu.compliant": "Vastu",
  "cost.within_budget": "Budget",
  "access.usable": "Access",
};

/* ═══ ROOM ZONES ══════════════════════════════════════════════════════ */

const PUBLIC = new Set(["foyer", "living", "dining", "puja", "verandah", "garage", "drawing", "family", "lobby", "home_office"]);
const PRIVATE = new Set(["master_bedroom", "bedroom", "guest_bedroom", "children_bedroom", "study", "balcony", "terrace", "wardrobe", "servant"]);
const WET = new Set(["bathroom", "toilet", "powder", "utility", "laundry"]);
const zoneOf = (t) => (PUBLIC.has(t) ? "public" : PRIVATE.has(t) ? "private" : "service");
const tintOf = (t) => (PUBLIC.has(t) ? "public" : PRIVATE.has(t) ? "private" : WET.has(t) ? "wet" : "service");

/* ═══ SHEET GEOMETRY ═══════════════════════════════════════════════════ */

const U = 24;          // svg units per metre
const GAP = 3.6;       // metres between floor plans on one sheet
const PAD = 2.4;       // metres of margin around the drawing

function sheetLayout(bbox, levels) {
  const [x0, y0, x1, y1] = bbox;
  const w = x1 - x0, d = y1 - y0;
  const n = Math.max(1, levels);
  const width = (n * w + (n - 1) * GAP + 2 * PAD) * U;
  const height = (d + 2 * PAD + 1.4) * U;
  const P = (level, x, y) => [
    (PAD + level * (w + GAP) + (x - x0)) * U,
    (PAD + (y1 - y)) * U,
  ];
  return { x0, y0, x1, y1, w, d, n, width, height, P };
}

const svgEl = (tag, attrs = {}, parent) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.append(e);
  return e;
};

const pathFrom = (pts) => `M${pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("L")}Z`;

function centroid(pts) {
  let x = 0, y = 0;
  for (const p of pts) { x += p[0]; y += p[1]; }
  return [x / pts.length, y / pts.length];
}

const LEVEL_NAME = (i, n) => (n === 1 ? "Ground floor plan" : i === 0 ? "Ground floor" : i === 1 ? "First floor" : i === 2 ? "Second floor" : `Level ${i}`);

/* ═══ THE ATELIER ═════════════════════════════════════════════════════ */

class Atelier {
  constructor() {
    this.root = null;
    this.charter = [];
    this.reset();
    this._tick = this._tick.bind(this);
    this._onResize = () => { this.ctm = null; };
    window.addEventListener("resize", this._onResize, { passive: true });
  }

  _fit(entry) {
    const wrap = this.root?.querySelector("#at-sheetwrap");
    if (!wrap || !entry) return;
    const r = wrap.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const scale = Math.min(r.width / entry.geom.width, r.height / entry.geom.height);
    entry.svg.style.setProperty("--k", (1 / scale).toFixed(3));
    this.ctm = null;
  }

  _current() {
    return Object.values(this.sheets).find((e) => e.svg.classList.contains("is-on")) || null;
  }

  reset() {
    this.run = (this.run || 0) + 1;
    this.sketches = [];          // in candidate order
    this.letter = {};            // plan id -> "A" | "B" | ...
    this.remarks = {};           // plan id -> { critic id -> remark }
    this.sheets = {};            // plan id -> { svg, geom, drawn }
    this.focus = null;
    this.reviewing = null;
    this.winner = null;
    this.speech = [];
    this.speaking = false;
    this.figs = {};              // the team on the board, by drafter id
    this.speed = 1;
    this.drafted = null;         // resolves when the focused sheet is fully drawn
    this.finished = false;
    this.failed = false;
    this.ctm = null;
    clearInterval(this.clockTimer);
    cancelAnimationFrame(this.raf);
    this.raf = 0;
  }

  /* ── construction ─────────────────────────────────────────────────── */

  mount(host) {
    this.root = host;
    host.innerHTML = "";
    host.innerHTML = `
      <div class="at-head">
        <div class="at-title">
          <h2 id="at-title">Your studio is at work</h2>
          <p id="at-sub"></p>
        </div>
        <ol class="at-stages" id="at-stages" aria-label="Stages"></ol>
        <div class="at-clock" aria-label="Elapsed time"><span id="at-clock">0.0</span>s</div>
      </div>
      <div class="at-body">
        <div class="at-work">
          <div class="at-rack" id="at-rack" role="list" aria-label="Schemes on the table"></div>
          <div class="at-board" id="at-board">
            <div class="at-sheetwrap" id="at-sheetwrap"></div>
            <div class="at-pens" id="at-pens" aria-hidden="true"></div>
            <div class="at-tblock" id="at-tblock" aria-hidden="true"></div>
            <ul class="at-legend" aria-label="Key">
              <li><i class="t-public"></i>Living rooms</li>
              <li><i class="t-service"></i>Kitchen &amp; circulation</li>
              <li><i class="t-wet"></i>Bath &amp; utility</li>
              <li><i class="t-private"></i>Bedrooms</li>
            </ul>
            <div class="at-stamp" id="at-stamp" hidden aria-hidden="true"></div>
            <div class="at-fail" id="at-fail" hidden role="alert"></div>
          </div>
          <div class="at-talk">
            <div class="at-talk__h"><span>Studio conversation</span><span class="at-live" id="at-live">Live</span></div>
            <ol class="at-feed" id="at-feed"></ol>
          </div>
        </div>
        <aside class="at-table" aria-label="Around the table">
          <div class="at-table__h">
            <h3>Around the table</h3>
            <span id="at-count"></span>
          </div>
          <div class="at-spot" id="at-spot"></div>
          <div class="at-people" id="at-people"></div>
          <div class="at-actions">
            <button type="button" class="at-btn" id="at-open" hidden>Open the review</button>
            <button type="button" class="at-btn at-btn--quiet" id="at-cancel">Back to the brief</button>
          </div>
        </aside>
      </div>
      <p class="sr-only" id="at-status" aria-live="polite"></p>`;

    // The board can be measured only once the running phase is on screen;
    // refit whenever its size changes, including the moment it appears.
    new ResizeObserver(() => this._fit(this._current())).observe(host.querySelector("#at-sheetwrap"));

    const stages = host.querySelector("#at-stages");
    for (const [key, label] of STAGES) {
      const li = document.createElement("li");
      li.dataset.stage = key;
      li.dataset.state = "pending";
      li.innerHTML = `<i></i><span>${label}</span>`;
      stages.append(li);
    }
  }

  seat(charter) {
    this.charter = charter || [];
    const box = this.root.querySelector("#at-people");
    box.innerHTML = "";
    const known = new Set(this.charter.map((c) => c.id));
    for (const g of GROUPS) {
      const ids = g.ids.filter((id) => !known.size || known.has(id));
      if (!ids.length) continue;
      const sec = document.createElement("section");
      sec.className = "at-group";
      const h = document.createElement("h4");
      h.textContent = g.title;
      sec.append(h);
      const grid = document.createElement("div");
      grid.className = "at-grid";
      for (const id of ids) grid.append(this._tile(id));
      sec.append(grid);
      box.append(sec);
    }
    // Anyone on the committee this file has no group for still gets a seat.
    const placed = new Set(GROUPS.flatMap((g) => g.ids));
    const extra = this.charter.filter((c) => !placed.has(c.id));
    if (extra.length) {
      const grid = document.createElement("div");
      grid.className = "at-grid";
      extra.forEach((c) => grid.append(this._tile(c.id)));
      box.append(grid);
    }
    this.root.querySelector("#at-count").textContent = `${this.charter.length || 13} specialists`;
  }

  _tile(id) {
    const p = person(id, this.charter);
    const t = document.createElement("div");
    t.className = "at-tile";
    t.dataset.critic = id;
    t.dataset.state = "idle";
    t.setAttribute("role", "listitem");
    t.title = `${p.name} · ${p.role}`;
    t.append(avatar(p, 30));
    const tx = document.createElement("span");
    tx.className = "at-tile__tx";
    tx.innerHTML = `<b></b><small></small>`;
    tx.querySelector("b").textContent = shortName(p);
    tx.querySelector("small").textContent = p.role;
    const sc = document.createElement("span");
    sc.className = "at-tile__sc";
    sc.textContent = "";
    t.append(tx, sc);
    return t;
  }

  /* ── a run begins ─────────────────────────────────────────────────── */

  begin({ brief, upload = false, fileName = "", onCancel }) {
    this.reset();
    this.started = performance.now();
    this.brief = brief || {};
    this.upload = upload;
    const r = this.root;
    r.querySelector("#at-title").textContent = upload ? "Your drawing is on the table" : "Your studio is at work";
    r.querySelector("#at-sub").textContent = upload ? `Reading ${fileName}` : this._briefLine(brief);
    r.querySelectorAll("#at-stages li").forEach((li) => { li.dataset.state = "pending"; });
    r.querySelector("#at-rack").innerHTML = "";
    r.querySelector("#at-sheetwrap").innerHTML = "";
    r.querySelector("#at-pens").innerHTML = "";
    r.querySelector("#at-feed").innerHTML = "";
    r.querySelector("#at-stamp").hidden = true;
    r.querySelector("#at-fail").hidden = true;
    r.querySelector("#at-open").hidden = true;
    r.querySelector("#at-live").textContent = "Live";
    r.querySelector("#at-live").dataset.on = "1";
    r.querySelectorAll(".at-tile").forEach((t) => {
      t.dataset.state = "idle";
      t.querySelector(".at-tile__sc").textContent = "";
      t.classList.remove("is-speaking");
    });
    this._spotlight(PRINCIPAL, upload ? "Let's see what you've brought us." : "Let's read the brief together.", null, { quiet: true });
    this._titleBlock();

    const cancel = r.querySelector("#at-cancel");
    cancel.onclick = () => { if (onCancel) onCancel(); };

    this.clockTimer = setInterval(() => {
      const s = (performance.now() - this.started) / 1000;
      r.querySelector("#at-clock").textContent = s.toFixed(1);
    }, 100);

    // The plot is known before any scheme is: set it out while the team
    // walks on and gathers at it.
    this._spawn();
    if (!upload && brief?.plot_width && brief?.plot_depth) {
      const sk = this._siteSketch(brief);
      this._sheet(sk, { setOut: true });
      this._gather();
    } else {
      this._boardNote(upload ? "Reading your drawing…" : "Setting out the plot…");
    }
  }

  _briefLine(b) {
    if (!b) return "";
    const road = { N: "north", NE: "north-east", E: "east", SE: "south-east", S: "south", SW: "south-west", W: "west", NW: "north-west" }[b.road_direction] || b.road_direction;
    const floors = b.levels > 1 ? `${b.levels} floors` : "one floor";
    return `${b.plot_width} × ${b.plot_depth} m plot · road to the ${road} · ${b.bedrooms} bedroom${b.bedrooms === 1 ? "" : "s"} · ${floors}`;
  }

  _siteSketch(b) {
    const w = +b.plot_width, d = +b.plot_depth;
    return {
      id: "__site__", name: "Site", site: [[0, 0], [w, 0], [w, d], [0, d]],
      bbox: [0, 0, w, d], road: [b.road_direction || "N"], north: 0,
      levels: Array.from({ length: Math.max(1, +b.levels || 1) }, (_, i) => ({ index: i, rooms: [], walls: [] })),
    };
  }

  /* ── progress from the engine ─────────────────────────────────────── */

  progress(e) {
    if (this.finished || this.failed) return;
    const { stage, status, detail = {} } = e;
    const msg = this._tidy(e.message || "");
    this._stage(stage, status);
    this.root.querySelector("#at-status").textContent = msg;

    switch (stage) {
      case "interpret":
        if (status === "done") this.say("critic.brief", msg);
        break;
      case "retrieve":
        if (status !== "running") this.say("critic.coherence", msg, { quiet: status === "skipped" });
        break;
      case "generate":
        if (status === "running") this.say("d.arch1", "We're drafting the candidate schemes now.");
        if (detail.sketches?.length) {
          this.sketchesIn(detail.sketches);
          this.say(status === "skipped" ? PRINCIPAL.id : "d.engineer", msg);
        }
        break;
      case "critique":
        if (detail.critics && !detail.plan) {
          this.say(PRINCIPAL.id, msg);
          this.root.querySelectorAll(".at-tile").forEach((t) => { t.dataset.state = "reading"; });
          if (this.sketches[0]) this._reviewing(this.sketches[0].id);
        }
        if (detail.plan && detail.remarks) this.remarksIn(detail.plan, detail.remarks);
        if (status === "done") this.say(PRINCIPAL.id, msg);
        break;
      case "consensus":
        if (status === "done") {
          if (detail.winner) this.chosen(detail.winner);
          this.say(PRINCIPAL.id, msg);
        }
        break;
      case "debate":
        if (status !== "running" || e.detail?.contested) this.say(PRINCIPAL.id, msg, { quiet: status === "skipped" });
        break;
      case "refine":
        this.say("d.arch1", msg, { quiet: status === "skipped" });
        break;
      case "negotiate":
        if (detail.open_constraints) {
          this.say(PRINCIPAL.id, msg);
          for (const c of detail.open_constraints.slice(0, 4)) {
            const who = OWNER[c.owner] || PRINCIPAL.id;
            const label = CONSTRAINT[c.id] || c.id;
            this.say(who, `${label}: ${this._tidy(c.detail || "")}`);
          }
        } else if (detail.round != null) {
          this.say(PRINCIPAL.id, `Round ${detail.round}: ${detail.accepted} of ${detail.proposed} proposal${detail.proposed === 1 ? "" : "s"} accepted.`, { quiet: true });
        } else if (status !== "running") {
          this.say(PRINCIPAL.id, msg, { quiet: status === "skipped" });
        }
        break;
      case "explain":
        if (status === "running") this.say(PRINCIPAL.id, "Writing up the rationale for you.");
        else this.say(PRINCIPAL.id, msg);
        break;
      default:
        if (msg) this.say(PRINCIPAL.id, msg, { quiet: true });
    }
  }

  _tidy(s) {
    let t = String(s).replace(/\.\.\./g, "…").replace(/\bm2\b/g, "m²");
    for (const [id, l] of Object.entries(this.letter)) t = t.split(id).join(`Scheme ${l}`);
    t = t.replace(/plan_[0-9a-f]{6,}/g, "the scheme");
    t = t.replace(/\(s\)/g, "s").replace(/\b1 schemes\b/, "1 scheme").replace(/\b1 verdicts\b/, "1 verdict");
    return t;
  }

  _stage(stage, status) {
    const items = [...this.root.querySelectorAll("#at-stages li")];
    const idx = items.findIndex((li) => li.dataset.stage === stage);
    if (idx < 0) return;
    items.forEach((li, i) => {
      if (i < idx && li.dataset.state !== "skipped") li.dataset.state = "done";
    });
    const li = items[idx];
    li.dataset.state = status === "running" ? "active" : status === "skipped" ? "skipped" : status === "failed" ? "failed" : "done";
  }

  /* ── schemes arrive ───────────────────────────────────────────────── */

  sketchesIn(list) {
    this.sketches = list;
    list.forEach((s, i) => { this.letter[s.id] = String.fromCharCode(65 + i); });
    const rack = this.root.querySelector("#at-rack");
    rack.innerHTML = "";
    list.forEach((s, i) => rack.append(this._rackItem(s, i)));
    // Draw the first scheme on the board with pens; the rest draw in miniature.
    this.setFocus(list[0].id, { pens: true });
  }

  _rackItem(s, i) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "at-scheme";
    b.dataset.plan = s.id;
    b.dataset.state = "drafting";
    b.setAttribute("role", "listitem");
    const thumb = document.createElement("span");
    thumb.className = "at-scheme__thumb";
    thumb.append(this._miniPlan(s, i));
    const tx = document.createElement("span");
    tx.className = "at-scheme__tx";
    tx.innerHTML = `<b></b><small></small>`;
    tx.querySelector("b").textContent = this.upload ? "Your plan" : `Scheme ${String.fromCharCode(65 + i)}`;
    tx.querySelector("small").textContent = `${Math.round(s.area)} m² · drafting`;
    const sc = document.createElement("span");
    sc.className = "at-scheme__sc";
    b.append(thumb, tx, sc);
    b.addEventListener("click", () => this.setFocus(s.id, { pens: false }));
    return b;
  }

  _miniPlan(s, i) {
    const lv = s.levels[0];
    const [x0, y0, x1, y1] = s.bbox;
    const sc = 4;
    const svg = svgEl("svg", { viewBox: `${-1} ${-1} ${(x1 - x0) * sc + 2} ${(y1 - y0) * sc + 2}`, class: "mini" });
    const P = (p) => [(p[0] - x0) * sc, (y1 - p[1]) * sc];
    svgEl("path", { d: pathFrom(s.site.map(P)), class: "mini__site" }, svg);
    const rm = reduced();
    lv.rooms.forEach((room, k) => {
      const path = svgEl("path", { d: pathFrom(room.poly.map(P)), class: `mini__room t-${tintOf(room.type)}` }, svg);
      if (!rm) {
        const len = room.poly.reduce((a, p, j) => {
          const q = room.poly[(j + 1) % room.poly.length];
          return a + Math.hypot(q[0] - p[0], q[1] - p[1]) * sc;
        }, 0);
        path.style.strokeDasharray = `${len}`;
        path.style.strokeDashoffset = `${len}`;
        path.animate([{ strokeDashoffset: len, fillOpacity: 0 }, { strokeDashoffset: 0, fillOpacity: 1 }],
          { duration: 700, delay: 350 + i * 260 + k * 140, easing: "cubic-bezier(.45,0,.2,1)", fill: "forwards" });
      }
    });
    return svg;
  }

  _schemeState(id, state, label) {
    const b = this.root.querySelector(`.at-scheme[data-plan="${id}"]`);
    if (!b) return;
    b.dataset.state = state;
    if (label) b.querySelector("small").textContent = label;
  }

  setFocus(id, { pens = true } = {}) {
    const sk = this.sketches.find((s) => s.id === id);
    if (!sk) return;
    this.focus = id;
    this.root.querySelectorAll(".at-scheme").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.plan === id)));
    const sheet = this._sheet(sk, { pens });
    this._titleBlock();
    return sheet;
  }

  _reviewing(id) {
    this.reviewing = id;
    this.root.querySelectorAll(".at-scheme").forEach((b) => {
      if (b.dataset.plan === id && b.dataset.state !== "chosen") {
        b.dataset.state = "review";
        b.querySelector("small").textContent = "In review";
      }
    });
  }

  remarksIn(planId, remarks) {
    this.remarks[planId] = Object.fromEntries(remarks.map((r) => [r.critic, r]));
    const l = this.letter[planId] || "";
    const n = remarks.length;
    const mean = remarks.reduce((a, r) => a + r.score, 0) / Math.max(1, n);
    this._schemeState(planId, "reviewed", `${n} verdicts`);
    const sc = this.root.querySelector(`.at-scheme[data-plan="${planId}"] .at-scheme__sc`);
    if (sc) sc.textContent = mean.toFixed(2);
    // The next scheme on the table is the one now being read.
    const idx = this.sketches.findIndex((s) => s.id === planId);
    const next = this.sketches[idx + 1];
    if (next) this._reviewing(next.id);

    // Everyone speaks to the scheme, measured voices first; the sharpest
    // concerns also go into the conversation so they are not lost.
    const ordered = [...remarks].sort((a, b) => (a.analytical === b.analytical ? 0 : a.analytical ? -1 : 1));
    for (const r of ordered) this._queue(r.critic, r.line, r.score, l);
    const concerns = [...remarks].filter((r) => r.score < 0.7).sort((a, b) => a.score - b.score).slice(0, 2);
    for (const r of concerns) this.say(r.critic, `${l ? `On Scheme ${l}: ` : ""}${r.line}`, { score: r.score });
  }

  chosen(planId) {
    this.winner = planId;
    this.root.querySelectorAll(".at-scheme").forEach((b) => {
      const won = b.dataset.plan === planId;
      b.dataset.state = won ? "chosen" : "reviewed";
      if (won) b.querySelector("small").textContent = "Selected";
    });
    if (this.focus !== planId) this.setFocus(planId, { pens: true });
  }

  /* ── speech ───────────────────────────────────────────────────────── */

  say(id, text, { quiet = false, score = null } = {}) {
    if (!text) return;
    const p = person(id, this.charter);
    const feed = this.root.querySelector("#at-feed");
    const li = document.createElement("li");
    li.className = "at-line";
    if (quiet) li.dataset.quiet = "1";
    li.append(avatar(p, 24));
    const body = document.createElement("div");
    body.className = "at-line__b";
    const who = document.createElement("b");
    who.textContent = p.name;
    const role = document.createElement("small");
    role.textContent = p.role;
    const tx = document.createElement("p");
    tx.textContent = text;
    body.append(who, role, tx);
    li.append(body);
    if (score != null) {
      const s = document.createElement("span");
      s.className = "at-line__sc";
      s.dataset.low = score < 0.55 ? "1" : "0";
      s.textContent = score.toFixed(2);
      li.append(s);
    }
    this._push(feed, li);
  }

  // Insert with FLIP so earlier lines glide up rather than jump.
  _push(feed, li) {
    const kids = [...feed.children];
    const before = new Map(kids.map((k) => [k, k.getBoundingClientRect().top]));
    feed.append(li);
    while (feed.children.length > 14) feed.firstElementChild.remove();
    if (reduced()) return;
    for (const k of kids) {
      if (!k.isConnected) continue;
      const dy = before.get(k) - k.getBoundingClientRect().top;
      if (Math.abs(dy) < 0.5) continue;
      k.animate([{ transform: `translateY(${dy}px)` }, { transform: "translateY(0)" }],
        { duration: 420, easing: "cubic-bezier(.16,1,.3,1)" });
    }
    li.animate([{ opacity: 0, transform: "translateY(10px)" }, { opacity: 1, transform: "translateY(0)" }],
      { duration: 420, easing: "cubic-bezier(.16,1,.3,1)" });
  }

  _queue(id, line, score, letter) {
    this.speech.push({ id, line, score, letter });
    if (!this.speaking) this._speakNext();
  }

  async _speakNext() {
    this.speaking = true;
    const run = this.run;
    while (this.speech.length && run === this.run) {
      const item = this.speech.shift();
      const p = person(item.id, this.charter);
      this._spotlight(p, item.line, item.score, { letter: item.letter });
      const tile = this.root.querySelector(`.at-tile[data-critic="${item.id}"]`);
      if (tile) {
        this.root.querySelectorAll(".at-tile.is-speaking").forEach((t) => t.classList.remove("is-speaking"));
        tile.classList.add("is-speaking");
        tile.dataset.state = item.score < 0.55 ? "low" : "spoke";
        tile.querySelector(".at-tile__sc").textContent = item.score.toFixed(2);
      }
      // A long queue speeds the room up rather than holding the run back.
      const wait = this.finished ? 0 : this.speech.length > 18 ? 260 : this.speech.length > 8 ? 520 : 980;
      if (wait) await sleep(wait);
      if (this.finished || run !== this.run) break;
    }
    this.root.querySelectorAll(".at-tile.is-speaking").forEach((t) => t.classList.remove("is-speaking"));
    this.speaking = false;
  }

  _spotlight(p, line, score, { letter = "", quiet = false } = {}) {
    const spot = this.root.querySelector("#at-spot");
    const card = document.createElement("div");
    card.className = "at-spot__card";
    card.append(avatar(p, 44));
    const tx = document.createElement("div");
    tx.className = "at-spot__tx";
    const who = document.createElement("div");
    who.className = "at-spot__who";
    who.innerHTML = `<b></b><small></small>`;
    who.querySelector("b").textContent = p.name;
    who.querySelector("small").textContent = p.role;
    const q = document.createElement("p");
    q.textContent = line;
    tx.append(who, q);
    card.append(tx);
    if (score != null) {
      const s = document.createElement("span");
      s.className = "at-spot__sc";
      s.dataset.low = score < 0.55 ? "1" : "0";
      s.innerHTML = `<small></small><b></b>`;
      s.querySelector("small").textContent = letter ? `Scheme ${letter}` : "Score";
      s.querySelector("b").textContent = score.toFixed(2);
      card.append(s);
    }
    const old = spot.firstElementChild;
    spot.append(card);
    if (reduced() || quiet) { if (old) old.remove(); return; }
    card.animate([{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "translateY(0)" }],
      { duration: 380, easing: "cubic-bezier(.16,1,.3,1)" });
    if (old) {
      old.classList.add("is-leaving");
      old.animate([{ opacity: 1 }, { opacity: 0, transform: "translateY(-6px)" }],
        { duration: 220, easing: "ease-in", fill: "forwards" }).finished.then(() => old.remove());
    }
  }

  /* ── the board ────────────────────────────────────────────────────── */

  _boardNote(text) {
    const wrap = this.root.querySelector("#at-sheetwrap");
    wrap.innerHTML = "";
    const p = document.createElement("p");
    p.className = "at-boardnote";
    p.textContent = text;
    wrap.append(p);
  }

  _titleBlock() {
    const tb = this.root.querySelector("#at-tblock");
    const b = this.brief || {};
    const l = this.focus ? this.letter[this.focus] : "";
    const sheetNo = l ? `A-10${"ABCDEFGH".indexOf(l) + 1}` : "A-100";
    tb.innerHTML = `
      <div class="tb-row tb-brand"><b>Atri Arch</b><span>Studio</span></div>
      <div class="tb-row"><span>Project</span><b></b></div>
      <div class="tb-row"><span>Sheet</span><b>${sheetNo}</b><span>Scale</span><b>1:100</b></div>
      <div class="tb-row"><span>Drawn</span><b>Studio team</b><span>Chk</span><b>Lead</b></div>`;
    const name = this.upload ? "Uploaded plan" : l ? `Scheme ${l}` : "Site set-out";
    tb.querySelectorAll(".tb-row")[1].querySelector("b").textContent =
      `${name}${b.plot_width ? ` · ${b.plot_width}×${b.plot_depth} m` : ""}`;
  }

  _sheet(sk, { setOut = false, pens = true } = {}) {
    const wrap = this.root.querySelector("#at-sheetwrap");
    const levels = sk.levels.length;
    let entry = this.sheets[sk.id];

    // The first scheme inherits the set-out sheet when the plot matches, so
    // the drawing grows on the lines already on the board instead of
    // replacing them.
    const site = this.sheets.__site__;
    if (!entry && site && sk.id !== "__site__" && site.geom.n === levels &&
        Math.abs(site.geom.w - (sk.bbox[2] - sk.bbox[0])) < 0.01 &&
        Math.abs(site.geom.d - (sk.bbox[3] - sk.bbox[1])) < 0.01 && !site.claimed) {
      site.claimed = true;
      entry = { svg: site.svg, geom: site.geom, drawn: false, rooms: null };
      this.sheets[sk.id] = entry;
    }

    if (!entry) {
      const geom = sheetLayout(sk.bbox, levels);
      const svg = svgEl("svg", { viewBox: `0 0 ${geom.width.toFixed(0)} ${geom.height.toFixed(0)}`, class: "sheet", preserveAspectRatio: "xMidYMid meet" });
      wrap.append(svg);
      entry = { svg, geom, drawn: false, rooms: null };
      this.sheets[sk.id] = entry;
      this._frame(entry, sk, { animate: setOut });
    }

    // Show it.
    const shown = wrap.querySelector("svg.sheet.is-on");
    if (shown !== entry.svg) {
      wrap.querySelector(".at-boardnote")?.remove();
      entry.svg.classList.add("is-on");
      if (shown) {
        shown.classList.remove("is-on");
        if (!reduced()) {
          entry.svg.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 360, easing: "ease-out" });
        }
      }
    }
    this._fit(entry);

    if (sk.id !== "__site__" && !entry.rooms) this._draft(entry, sk, { pens });
    return entry;
  }

  // Plot, setbacks, road, north point and dimension strings.
  _frame(entry, sk, { animate }) {
    const { svg, geom } = entry;
    const { P, w, d, x0, y0, x1, y1 } = geom;
    const defs = svgEl("defs", {}, svg);
    const pat = svgEl("pattern", { id: `grid-${sk.id}`, width: U, height: U, patternUnits: "userSpaceOnUse" }, defs);
    svgEl("path", { d: `M ${U} 0 L 0 0 0 ${U}`, class: "sh-grid" }, pat);
    svgEl("rect", { x: 0, y: 0, width: geom.width, height: geom.height, fill: `url(#grid-${sk.id})`, class: "sh-gridfill" }, svg);

    const g = svgEl("g", { class: "sh-frame" }, svg);
    const lines = [];
    const b = this.brief || {};
    for (let i = 0; i < geom.n; i++) {
      // Plot boundary on every floor, as a hairline; the building sits inside it.
      const site = sk.site.map((p) => P(i, p[0], p[1]));
      lines.push(svgEl("path", { d: pathFrom(site), class: i === 0 ? "sh-plot" : "sh-plot sh-plot--upper" }, g));
      if (i === 0 && b.setback_front != null && !this.upload) {
        const road = (sk.road && sk.road[0]) || "N";
        const sf = +b.setback_front || 0, sr = +b.setback_rear || 0, sl = +b.setback_left || 0, srt = +b.setback_right || 0;
        // Front is the road side; left/right are as seen from the road.
        let inset;
        if (road === "N") inset = { top: sf, bottom: sr, left: sl, right: srt };
        else if (road === "S") inset = { top: sr, bottom: sf, left: srt, right: sl };
        else if (road === "E") inset = { top: sl, bottom: srt, left: sr, right: sf };
        else inset = { top: srt, bottom: sl, left: sf, right: sr };
        const sb = [[x0 + inset.left, y0 + inset.bottom], [x1 - inset.right, y0 + inset.bottom],
          [x1 - inset.right, y1 - inset.top], [x0 + inset.left, y1 - inset.top]].map((p) => P(0, p[0], p[1]));
        lines.push(svgEl("path", { d: pathFrom(sb), class: "sh-setback" }, g));
      }
      // Level title under each plan.
      const [tx, ty] = P(i, x0, y0);
      const t = svgEl("text", { x: tx, y: ty + U * 1.55, class: "sh-ltitle" }, g);
      t.textContent = LEVEL_NAME(i, geom.n).toUpperCase();
    }

    // Road along the frontage of the ground floor plan.
    const road = (sk.road && sk.road[0]) || "N";
    const [ax, ay] = P(0, x0, y1);
    const [bx, by] = P(0, x1, y0);
    const rw = U * 1.6;
    let rd, lx, ly, rot = 0;
    if (road.startsWith("N")) { rd = `M${ax},${ay - U * .5}H${bx}`; lx = (ax + bx) / 2; ly = ay - U * .5 - rw / 2; }
    else if (road.startsWith("S")) { rd = `M${ax},${by + U * .5}H${bx}`; lx = (ax + bx) / 2; ly = by + U * .5 + rw / 2 + U * .9; }
    else if (road.startsWith("E")) { rd = `M${bx + U * .5},${ay}V${by}`; lx = bx + U * .5 + rw / 2; ly = (ay + by) / 2; rot = 90; }
    else { rd = `M${ax - U * .5},${ay}V${by}`; lx = ax - U * .5 - rw / 2; ly = (ay + by) / 2; rot = -90; }
    lines.push(svgEl("path", { d: rd, class: "sh-road" }, g));
    const rt = svgEl("text", { x: lx, y: ly, class: "sh-roadlabel", transform: rot ? `rotate(${rot} ${lx} ${ly})` : "" }, g);
    rt.textContent = "ROAD";

    // Dimension strings: width under the ground plan, depth to its left.
    const dimY = by + U * (road.startsWith("S") ? 2.9 : 0.95);
    const dimX = ax - U * (road.startsWith("W") ? 2.9 : 0.95);
    lines.push(svgEl("path", { d: `M${ax},${dimY}H${bx}M${ax},${dimY - 5}V${dimY + 5}M${bx},${dimY - 5}V${dimY + 5}`, class: "sh-dim" }, g));
    lines.push(svgEl("path", { d: `M${dimX},${ay}V${by}M${dimX - 5},${ay}H${dimX + 5}M${dimX - 5},${by}H${dimX + 5}`, class: "sh-dim" }, g));
    const wt = svgEl("text", { x: (ax + bx) / 2, y: dimY - 6, class: "sh-dimtext" }, g);
    wt.textContent = w.toFixed(2);
    const dt = svgEl("text", { x: dimX - 7, y: (ay + by) / 2, class: "sh-dimtext", transform: `rotate(-90 ${dimX - 7} ${(ay + by) / 2})` }, g);
    dt.textContent = d.toFixed(2);

    // North point at the top right of the sheet.
    const nx = geom.width - U * 1.6, ny = U * 1.7;
    const north = svgEl("g", { class: "sh-north", transform: `translate(${nx} ${ny}) rotate(${sk.north || 0})` }, g);
    svgEl("path", { d: `M0,-${U * .8}L${U * .32},${U * .45}L0,${U * .22}L-${U * .32},${U * .45}Z` }, north);
    const nt = svgEl("text", { x: 0, y: -U * 1.0 }, north);
    nt.textContent = "N";

    entry.rooms = null;
    if (!animate || reduced()) return;
    lines.forEach((el, i) => {
      const dashed = /sh-setback|sh-road|sh-plot--upper/.test(el.getAttribute("class"));
      const len = el.getTotalLength ? el.getTotalLength() : 0;
      if (dashed || !len) {
        el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 700, delay: 300 + i * 110, fill: "backwards" });
        return;
      }
      el.style.strokeDasharray = `${len}`;
      el.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }],
        { duration: 900, delay: 120 + i * 110, easing: "cubic-bezier(.45,0,.2,1)", fill: "backwards" });
    });
    svg.querySelectorAll("text").forEach((t, i) => {
      t.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 500, delay: 600 + i * 60, fill: "backwards" });
    });
  }

  // The scheme itself: rooms outlined by the drafter who owns their zone,
  // then filled and named, then the walls inked and the openings cut.
  _draft(entry, sk, { pens }) {
    if (this.entry && this.entry !== entry && !this.entry.drawn) {
      for (const it of this.entry.rooms || []) this._complete(it);
      const f = this._finishDraft;
      this._finishDraft = null;
      if (f) f();
    }
    const { svg, geom } = entry;
    const layer = svgEl("g", { class: "sh-plan" }, svg);
    const fills = svgEl("g", { class: "sh-fills" }, layer);
    const outlines = svgEl("g", { class: "sh-outlines" }, layer);
    const walls = svgEl("g", { class: "sh-walls" }, layer);
    const labels = svgEl("g", { class: "sh-labels" }, layer);
    entry.rooms = [];

    const queues = { public: [], service: [], private: [] };
    sk.levels.forEach((lv, li) => {
      // Front to back, so the hands move across the plan the way it is read.
      const rooms = [...lv.rooms].sort((a, b) => centroid(b.poly)[1] - centroid(a.poly)[1]);
      for (const room of rooms) {
        const pts = room.poly.map((p) => geom.P(li, p[0], p[1]));
        const d = pathFrom(pts);
        const fill = svgEl("path", { d, class: `sh-fill t-${tintOf(room.type)}` }, fills);
        const line = svgEl("path", { d, class: "sh-line" }, outlines);
        const [cx, cy] = centroid(pts);
        const minSide = Math.min(...[0, 1].map((ax) => Math.max(...pts.map((p) => p[ax])) - Math.min(...pts.map((p) => p[ax]))));
        const at = svgEl("g", { class: "sh-label", transform: `translate(${cx.toFixed(1)} ${cy.toFixed(1)})` }, labels);
        const lab = svgEl("g", { class: "sh-label__in" }, at);
        const small = minSide < U * 2.2;
        const nm = svgEl("text", { y: small ? 2 : -2, class: small ? "sh-name sh-name--sm" : "sh-name" }, lab);
        nm.textContent = room.name.toUpperCase();
        if (!small) {
          const ar = svgEl("text", { y: 11, class: "sh-area" }, lab);
          ar.textContent = `${room.area.toFixed(1)} m²`;
        }
        const len = line.getTotalLength();
        const item = { room, line, fill, lab, len, done: false };
        entry.rooms.push(item);
        queues[zoneOf(room.type)].push(item);
      }
      // Walls and openings for this floor, inked after the rooms.
      for (const w of lv.walls) {
        const a = geom.P(li, w.a[0], w.a[1]), b = geom.P(li, w.b[0], w.b[1]);
        const wl = svgEl("path", { d: `M${a[0].toFixed(1)},${a[1].toFixed(1)}L${b[0].toFixed(1)},${b[1].toFixed(1)}`,
          class: w.ext ? "sh-wall sh-wall--ext" : "sh-wall", "stroke-width": Math.max(1.4, w.t * U).toFixed(1) }, walls);
        const L = Math.hypot(b[0] - a[0], b[1] - a[1]);
        const ux = (b[0] - a[0]) / (L || 1), uy = (b[1] - a[1]) / (L || 1);
        for (const o of w.open) {
          const c = o.p * L, half = (o.w * U) / 2;
          const s0 = [a[0] + ux * (c - half), a[1] + uy * (c - half)];
          const s1 = [a[0] + ux * (c + half), a[1] + uy * (c + half)];
          svgEl("path", { d: `M${s0[0].toFixed(1)},${s0[1].toFixed(1)}L${s1[0].toFixed(1)},${s1[1].toFixed(1)}`,
            class: "sh-cut", "stroke-width": (Math.max(1.4, w.t * U) + 1.6).toFixed(1) }, walls);
          if (o.k.includes("door")) {
            // Leaf and swing, hinged at the cut's start, opening inward.
            const nx = -uy, ny = ux, r = half * 2;
            const tip = [s0[0] + nx * r, s0[1] + ny * r];
            svgEl("path", { d: `M${s0[0].toFixed(1)},${s0[1].toFixed(1)}L${tip[0].toFixed(1)},${tip[1].toFixed(1)}`, class: "sh-door" }, walls);
            svgEl("path", { d: `M${tip[0].toFixed(1)},${tip[1].toFixed(1)}A${r.toFixed(1)},${r.toFixed(1)} 0 0 1 ${s1[0].toFixed(1)},${s1[1].toFixed(1)}`, class: "sh-swing" }, walls);
          } else {
            const nx = -uy * 2, ny = ux * 2;
            svgEl("path", { d: `M${(s0[0] + nx).toFixed(1)},${(s0[1] + ny).toFixed(1)}L${(s1[0] + nx).toFixed(1)},${(s1[1] + ny).toFixed(1)}M${(s0[0] - nx).toFixed(1)},${(s0[1] - ny).toFixed(1)}L${(s1[0] - nx).toFixed(1)},${(s1[1] - ny).toFixed(1)}`, class: "sh-glaze" }, walls);
          }
        }
      }
    });
    walls.style.opacity = "0";

    for (const it of entry.rooms) {
      it.line.style.strokeDasharray = `${it.len}`;
      it.line.style.strokeDashoffset = `${it.len}`;
      it.fill.style.opacity = "0";
      it.lab.style.opacity = "0";
    }

    let resolveDrafted;
    this.drafted = new Promise((r) => { resolveDrafted = r; });
    const finish = () => {
      if (entry.drawn) return;
      entry.drawn = true;
      this._ink(entry);
      this._schemeDrawn(sk.id);
      resolveDrafted();
    };

    if (reduced() || !pens) {
      // Without pens (a click on another scheme, or reduced motion) the plan
      // arrives whole, with one quiet fade.
      for (const it of entry.rooms) this._complete(it, { fade: !reduced() });
      finish();
      return;
    }

    // Each of the team takes their zone; an idle hand helps the busiest.
    const hands = DRAFTERS.map((d) => ({ d, q: queues[d.zone] }));
    for (const h of hands) {
      if (!h.q.length) {
        const busiest = hands.reduce((a, b) => (b.q.length > a.q.length ? b : a));
        if (busiest.q.length > 1) h.q.push(...busiest.q.splice(Math.ceil(busiest.q.length / 2)));
      }
    }
    if (!Object.keys(this.figs).length) this._spawn();
    for (const h of hands) {
      const f = this.figs[h.d.id];
      if (!f) continue;
      f.q = h.q;
      f.cur = null;
      if (f.x == null) this._offstage(f, hands.indexOf(h));
    }
    this.entry = entry;
    this._finishDraft = finish;
    this._loop();
  }

  _spawn() {
    const layer = this.root.querySelector("#at-pens");
    layer.innerHTML = "";
    this.figs = {};
    if (reduced()) return;
    DRAFTERS.forEach((d) => {
      const el = document.createElement("div");
      el.className = "fg";
      el.dataset.state = "idle";
      el.innerHTML = `${figureMarkup(d.figure)}<span class="fg__tag"></span>`;
      el.style.setProperty("--tx", `${TIP[0].toFixed(1)}px`);
      el.style.setProperty("--ty", `${TIP[1].toFixed(1)}px`);
      layer.append(el);
      this.figs[d.id] = { d, el, x: null, y: null, q: [], cur: null, travel: null, left: false };
    });
  }

  _offstage(f, i) {
    const box = this.root.querySelector("#at-board").getBoundingClientRect();
    f.x = -40 - i * 36;
    f.y = (box.height || 400) - 70 + (i % 2) * 8;
    this._place(f);
  }

  _toBoard(entry, p) {
    const m = entry.svg.getScreenCTM();
    if (!m) return null;
    const box = this.root.querySelector("#at-board").getBoundingClientRect();
    if (!box.width) return null;
    return [m.a * p[0] + m.c * p[1] + m.e - box.left, m.b * p[0] + m.d * p[1] + m.f - box.top];
  }

  // Walk the team on from the left and gather them along the plot's front.
  _gather(tries = 0) {
    const entry = this._current();
    const g = entry?.geom;
    const a = g && this._toBoard(entry, g.P(0, g.x0, g.y0));
    const b = g && this._toBoard(entry, g.P(0, g.x1, g.y0));
    if (!a || !b) {
      if (tries < 90) requestAnimationFrame(() => this._gather(tries + 1));
      return;
    }
    // They gather on the plot itself, near its back edge, facing the middle.
    const figs = Object.values(this.figs);
    figs.forEach((f, i) => {
      this._offstage(f, i);
      const x = a[0] + (b[0] - a[0]) * (0.22 + i * 0.28);
      const mid = (a[0] + b[0]) / 2;
      this._walk(f, [x, a[1] - 34 - (i % 2) * 8], i * 320, x > mid ? "left" : "right");
    });
    this._loop();
  }

  // When the sheet is drawn, the team steps back below it.
  // Clear of the drawing, beside the plans, looking at the work.
  _standBack(entry) {
    const g = entry.geom;
    const spots = [
      [g.P(0, g.x0, g.y1 - g.d * 0.5), -40, "right"],
      [g.P(0, g.x0, g.y1 - g.d * 0.82), -40, "right"],
      [g.P(g.n - 1, g.x1, g.y1 - g.d * 0.66), 40, "left"],
    ];
    Object.values(this.figs).forEach((f, i) => {
      const [pt, dx, face] = spots[i % spots.length];
      const p = this._toBoard(entry, pt);
      if (p) this._walk(f, [p[0] + dx, p[1]], i * 140, face);
    });
    this._loop();
  }

  _walk(f, to, delay = 0, face = null) {
    if (f.x == null) { f.x = to[0]; f.y = to[1]; this._place(f); return; }
    const dist = Math.hypot(to[0] - f.x, to[1] - f.y);
    if (dist < 2) { if (face) f.left = face === "left"; return; }
    f.travel = { from: [f.x, f.y], to, t: -delay, dur: clamp(dist / WALK, 320, 2600), face };
  }

  _place(f) {
    f.el.style.transform = `translate3d(${(f.x - TIP[0]).toFixed(1)}px, ${(f.y - TIP[1]).toFixed(1)}px, 0)`;
  }

  _state(f, state) {
    if (f.el.dataset.state !== state) f.el.dataset.state = state;
  }

  _loop() {
    if (this.raf) return;
    this.lastT = performance.now();
    this.raf = requestAnimationFrame(this._tick);
  }

  _complete(it, { fade = false } = {}) {
    if (it.done) return;
    it.done = true;
    it.line.style.strokeDashoffset = "0";
    if (fade && !reduced()) {
      it.fill.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 420, fill: "forwards", easing: "ease-out" });
      it.lab.animate([{ opacity: 0, transform: "translateY(3px)" }, { opacity: 1, transform: "translateY(0)" }],
        { duration: 380, delay: 80, fill: "forwards", easing: "cubic-bezier(.16,1,.3,1)" });
      it.fill.style.opacity = "1";
      it.lab.style.opacity = "1";
    } else {
      it.fill.style.opacity = "1";
      it.lab.style.opacity = "1";
    }
  }

  _ink(entry) {
    const walls = entry.svg.querySelector(".sh-walls");
    if (!walls) return;
    if (reduced()) { walls.style.opacity = "1"; return; }
    walls.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 650, easing: "ease-out", fill: "forwards" });
    walls.style.opacity = "1";
  }

  _schemeDrawn(id) {
    const b = this.root.querySelector(`.at-scheme[data-plan="${id}"]`);
    if (b && b.dataset.state === "drafting") {
      b.dataset.state = "drawn";
      b.querySelector("small").textContent = "Drawn";
    }
    const entry = this.sheets[id];
    if (entry && Object.keys(this.figs).length) this._standBack(entry);
  }

  _point(path, len) {
    const p = path.getPointAtLength(len);
    if (!this.ctm) {
      const svg = path.ownerSVGElement;
      const box = this.root.querySelector("#at-board").getBoundingClientRect();
      const m = svg.getScreenCTM();
      if (!m) return null;
      this.ctm = { m, ox: box.left, oy: box.top };
    }
    const { m, ox, oy } = this.ctm;
    return [m.a * p.x + m.c * p.y + m.e - ox, m.b * p.x + m.d * p.y + m.f - oy];
  }

  _tick(now) {
    const dt = Math.min(64, now - this.lastT);
    this.lastT = now;
    const step = dt * this.speed;
    let busy = false;

    for (const f of Object.values(this.figs)) {
      // Between rooms: walk to where the next outline starts.
      if (!f.travel && !f.cur && f.q.length) {
        const it = f.q.shift();
        if (it.done) continue;
        f.cur = { it, t: 0, dur: clamp(it.len / 0.4, 560, 1800) };
        f.el.querySelector(".fg__tag").textContent = it.room.name;
        const start = this._point(it.line, 0);
        if (start) {
          if (f.x == null) { f.x = start[0]; f.y = start[1]; }
          else this._walk(f, start);
        }
      }

      if (f.travel) {
        busy = true;
        const tr = f.travel;
        tr.t += step;
        if (tr.t > 0) {
          const k = easeInOut(clamp(tr.t / tr.dur, 0, 1));
          f.x = tr.from[0] + (tr.to[0] - tr.from[0]) * k;
          f.y = tr.from[1] + (tr.to[1] - tr.from[1]) * k;
          const dx = tr.to[0] - tr.from[0];
          if (Math.abs(dx) > 6) f.left = dx < 0;
          this._state(f, "walking");
          if (tr.t >= tr.dur) {
            if (tr.face) f.left = tr.face === "left";
            f.travel = null;
          }
        }
      } else if (f.cur) {
        busy = true;
        const c = f.cur;
        if (c.it.done) { f.cur = null; continue; }
        c.t += step;
        const k = easeInOut(clamp(c.t / c.dur, 0, 1));
        const at = c.it.len * k;
        c.it.line.style.strokeDashoffset = `${(c.it.len - at).toFixed(1)}`;
        const pt = this._point(c.it.line, at);
        if (pt) { f.x = pt[0]; f.y = pt[1]; }
        this._state(f, "drawing");
        if (c.t >= c.dur) {
          this._complete(c.it, { fade: true });
          f.cur = null;
        }
      } else {
        this._state(f, "idle");
      }
      f.el.classList.toggle("is-left", f.left);
      if (f.x != null) this._place(f);
    }

    // The sheet is finished when every room on it is, whoever drew it.
    if (this._finishDraft && this.entry?.rooms?.every((it) => it.done)) {
      const fin = this._finishDraft;
      this._finishDraft = null;
      fin();
      busy = true;
    }

    if (busy) {
      this.raf = requestAnimationFrame(this._tick);
    } else {
      this.raf = 0;
      Object.values(this.figs).forEach((f) => this._state(f, "idle"));
    }
  }

  /* ── the end of the run ───────────────────────────────────────────── */

  async result(d, { onOpen } = {}) {
    if (this.failed) return;
    const run = this.run;
    this.finished = true;
    this.root.querySelectorAll("#at-stages li").forEach((li) => {
      if (li.dataset.state === "pending" || li.dataset.state === "active") li.dataset.state = "done";
    });
    const live = this.root.querySelector("#at-live");
    live.textContent = "Done";
    live.dataset.on = "0";
    clearInterval(this.clockTimer);

    const cand = d.selected_candidate_id || d.consensus?.winner_id;
    if (cand && this.sketches.some((s) => s.id === cand) && this.winner !== cand) this.chosen(cand);

    // Hurry the pens; never hold the review hostage to the drawing.
    this.speed = 7;
    if (this.drafted) await Promise.race([this.drafted, sleep(1400)]);
    if (this.entry && !this.entry.drawn) {
      for (const it of this.entry.rooms || []) this._complete(it);
      for (const f of Object.values(this.figs)) { f.q = []; f.cur = null; }
      const fin = this._finishDraft;
      this._finishDraft = null;
      if (fin) fin();
    }

    const row = (d.consensus?.ranking || []).find((r) => r.candidate_id === cand);
    const score = row?.score ?? d.consensus?.winner_score;
    const agree = d.consensus?.overall_agreement;
    for (const r of d.consensus?.ranking || []) {
      const sc = this.root.querySelector(`.at-scheme[data-plan="${r.candidate_id}"] .at-scheme__sc`);
      if (sc) sc.textContent = r.score.toFixed(2);
    }
    const l = this.letter[cand] || "A";
    this._stamp(this.upload ? "Reviewed" : `Scheme ${l} selected`, score, agree);
    const line = this.upload
      ? `Review complete${score != null ? `: ${score.toFixed(2)}` : ""}. Taking you to the drawings.`
      : `Scheme ${l} it is${score != null ? `, ${score.toFixed(2)}` : ""}${agree != null ? ` with ${Math.round(agree * 100)}% of the committee agreeing` : ""}. Taking it to review.`;
    this.say(PRINCIPAL.id, line);
    this._spotlight(PRINCIPAL, line, null);

    const open = this.root.querySelector("#at-open");
    open.hidden = false;
    let clicked;
    const click = new Promise((r) => { clicked = r; });
    open.onclick = () => clicked();
    await Promise.race([click, sleep(reduced() ? 500 : 1700)]);
    open.hidden = true;
    if (run === this.run && onOpen) onOpen();
  }

  _stamp(label, score, agree) {
    const s = this.root.querySelector("#at-stamp");
    s.innerHTML = `<small></small><b></b><span></span>`;
    s.querySelector("small").textContent = label;
    s.querySelector("b").textContent = score != null ? score.toFixed(2) : "";
    s.querySelector("span").textContent = agree != null ? `${Math.round(agree * 100)}% agreement` : "";
    s.hidden = false;
    if (!reduced()) {
      s.animate([{ opacity: 0, transform: "rotate(-8deg) scale(1.18)" }, { opacity: 1, transform: "rotate(-4deg) scale(1)" }],
        { duration: 420, easing: "cubic-bezier(.2,.9,.25,1)" });
    }
  }

  fail(title, message, { onBack } = {}) {
    this.failed = true;
    clearInterval(this.clockTimer);
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    const live = this.root.querySelector("#at-live");
    live.textContent = "Stopped";
    live.dataset.on = "0";
    this.root.querySelectorAll("#at-stages li[data-state=active]").forEach((li) => { li.dataset.state = "failed"; });
    const box = this.root.querySelector("#at-fail");
    box.innerHTML = `<h3></h3><p></p><button type="button" class="at-btn">Back to the brief</button>`;
    box.querySelector("h3").textContent = title;
    box.querySelector("p").textContent = message;
    box.querySelector("button").onclick = () => onBack && onBack();
    box.hidden = false;
    this.say(PRINCIPAL.id, `${title}. ${message}`);
  }

  stop() {
    clearInterval(this.clockTimer);
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.speech = [];
  }

  /** The drawn sheet, for the hand-off into the review. */
  currentSheet() {
    return this.root.querySelector("#at-sheetwrap svg.sheet.is-on");
  }

  remarksFor(planId) { return this.remarks[planId] || null; }
}

export const atelier = new Atelier();
