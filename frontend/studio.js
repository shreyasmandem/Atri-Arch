/* ═══════════════════════════════════════════════════════════════════════
   Studio

   Three phases, one URL: compose -> running -> review. Every result surface
   the engine can produce is reachable here, because a committee that reports
   twenty-five findings and shows you none of them is not explainable, it is
   just quiet.
   ═══════════════════════════════════════════════════════════════════════ */

import { atelier, person, avatar } from "./atelier.js?v=s3";
import { mountEditor } from "./editor.js?v=e5";
import { icon } from "./icons.js?v=i3";
import { autoSetbacks } from "./setbacks.js";

const API = (() => {
  const local = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
  const o = new URLSearchParams(location.search).get("api") || (local ? "" : window.AIP_API);
  if (o) return o.replace(/\/$/, "");
  if (location.port === "8080" || location.port === "3000" || location.port === "5500") {
    return `http://${location.hostname || "127.0.0.1"}:8010/api/v1`;
  }
  return `${location.origin}/api/v1`;
})();

const $ = (id) => document.getElementById(id);
// Write text to an element that a redesign may have removed. The boot sequence
// runs inside one try/catch whose failure message is "cannot reach the engine",
// so a null-reference on a retired element is reported to the user as a dead
// backend - which is what a removed cost ledger did.
const setText = (id, value) => { const n = $(id); if (n) n.textContent = value; };
const el = (t, c, x) => { const n = document.createElement(t); if (c) n.className = c; if (x != null) n.textContent = x; return n; };
const frag = () => document.createDocumentFragment();

/* Compass quarter -> pigment. The mapping the whole product reasons in. */
const PIG = {
  N: "indigo", NNE: "indigo", NE: "indigo", ENE: "indigo",
  E: "orpiment", ESE: "orpiment",
  SE: "hingula", SSE: "hingula", S: "hingula",
  SSW: "ochre", SW: "ochre", WSW: "ochre", W: "ochre",
  WNW: "orpiment", NW: "orpiment", NNW: "orpiment", CENTRE: "chalk",
};
// Pigments, read in the studio's monochrome: stone, sand and cream, with brick
// red kept for the one thing that must stand out, a breach.
const HEX = { indigo: "#A39C92", hingula: "#C4553F", ochre: "#C9B497", orpiment: "#E8DCC6", chalk: "#6F6A63" };

const CRITIC_PIG = {
  "critic.compliance": "hingula", "critic.daylight": "indigo", "critic.ventilation": "indigo",
  "critic.privacy": "indigo", "critic.circulation": "indigo", "critic.accessibility": "indigo",
  "critic.spatial": "indigo", "critic.structure": "ochre", "critic.vastu": "orpiment",
  "critic.cost": "ochre", "critic.coherence": "orpiment", "critic.brief": "orpiment",
  "critic.livability": "orpiment",
};

const STANCES = [
  ["Modern", "ignore", "Vastu is reported but never constrains the design."],
  ["Advisory", "advisory", "Violations are reported; the layout is not bent to satisfy them."],
  ["Balanced", "balanced", "Classical rules and modern building science carry equal weight."],
  ["Strict", "strict", "Vastu constrains the layout wherever it is physically possible."],
  ["Orthodox", "orthodox", "The classical texts win every conflict, at any cost."],
];

const S = {
  committee: [], phase: "compose", view: "drawings",
  planIds: [], activeId: null, winnerId: null,
  consensus: null, explanation: "", recommendations: [],
  negotiation: null, negotiationOutcome: "", exportUrls: {},
  candidateId: null,   // the scheme the committee voted for, before negotiation changed it
  projectId: null, sessionId: null, briefSent: null,
  imported: null,     // { file, source, rooms_read, rooms_kept, unrecognised, warnings, scale_note } for an uploaded plan
  mode: "brief",      // "brief" | "upload"
  plans: {},          // id -> { plan, vastu, cost, interior, analysis, drawing }
  remarks: {},        // candidate id -> { critic id -> { score, line } }, as spoken during the run
  voices: [],         // what each critic said about the chosen scheme, in full
  abort: null,        // the running stream, so "back to the brief" really stops it
  sheet: "plan_level_0",
};

const inr = (n) => n >= 1e7 ? `₹${(n / 1e7).toFixed(2)} Cr`
  : n >= 1e5 ? `₹${(n / 1e5).toFixed(2)} L`
  : `₹${Math.round(n || 0).toLocaleString("en-IN")}`;

const cap = (s) => String(s).replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());

/* ── plans survive a server restart ───────────────────────────────── */

// The server keeps schemes in memory. When it has restarted (a deploy, a free
// instance waking up) a plan the page still shows answers 404; the plan's own
// JSON is sent back and the request tried once more.
const planJson = new Map();
const rememberPlan = (plan) => { if (plan?.id && plan.levels) planJson.set(plan.id, plan); };
(() => {
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const res = await real(input, init);
    if (res.status !== 404) return res;
    try {
      const url = typeof input === "string" ? input : input?.url || "";
      if (!url.startsWith(API)) return res;
      let id = url.slice(API.length).match(/^\/plans\/(plan_[A-Za-z0-9]+)/)?.[1];
      if (!id && typeof init?.body === "string") {
        try { id = JSON.parse(init.body).plan_id; } catch { /* not json */ }
      }
      const plan = id && planJson.get(id);
      if (!plan) return res;
      const back = await real(`${API}/plans/restore`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plan }),
      });
      return back.ok ? real(input, init) : res;
    } catch { return res; }
  };
})();

function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(t._t); t._t = setTimeout(() => { t.hidden = true; }, 8000);
}

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Phases change through a view transition where the browser has one: the
// page cross-fades, the header holds still, and the drawn sheet on the
// atelier board travels into the review's drawing plate as one object.
function phase(p) {
  S.phase = p;
  // Every studio page can be left: Back in the studio; from the brief, a way
  // back to the designs already made.
  const back = $("back"), resume = $("resume");
  if (back) back.hidden = p !== "review";
  if (resume) resume.hidden = !(p === "compose" && S.activeId && S.plans?.[S.activeId]);
  if (document.body.dataset.phase === p) return;
  const apply = () => { document.body.dataset.phase = p; };
  if (document.startViewTransition && !reducedMotion() && !document.hidden) {
    document.documentElement.dataset.vt = p;
    const t = document.startViewTransition(apply);
    // A page that is not painting (a backgrounded window) never runs the
    // transition's callback; the phase must not wait on it.
    setTimeout(() => { if (document.body.dataset.phase !== S.phase) document.body.dataset.phase = S.phase; }, 1500);
    // A transition the browser skips (a hidden tab, a slow frame) still
    // applies the phase; it only loses the animation, so it is not an error.
    t.ready.catch(() => {});
    t.updateCallbackDone.catch(() => {});
    t.finished.catch(() => {}).finally(() => { delete document.documentElement.dataset.vt; });
  } else {
    apply();
  }
}

function cancelRun() {
  if (S.abort) { S.abort.abort(); S.abort = null; }
}

function backToBrief() {
  cancelRun();
  atelier.stop();
  S.isGenerating = false;
  const btn = $("convene");
  if (btn) {
    btn.classList.remove("is-loading");
    btn.disabled = false;
    const txt = btn.querySelector(".convene__title-text");
    if (txt) txt.textContent = "Convene the studio";
  }
  const up = $("review-btn");
  if (up) { up.classList.remove("is-loading"); up.disabled = false; }
  phase("compose");
}

/* ═══ MANDALA ════════════════════════════════════════════════════════ */


/* ═══ THE BRIEF ══════════════════════════════════════════════════════ */

const ROAD_WORD = { N: "north", NE: "north-east", E: "east", SE: "south-east", S: "south", SW: "south-west", W: "west", NW: "north-west" };
const NUMWORD = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight"];
const fmtM = (n) => (Number.isInteger(n) ? String(n) : n.toFixed(1));
// Plots are quoted in feet as often as metres; the sheet keeps what was typed and the studio works in metres.
const FT = 0.3048;
const plotUnit = (f) => (f?.querySelector('input[name="plot_unit"]:checked')?.value === "m" ? "m" : "ft");
const lakh = (n) => n >= 1e7 ? `${(n / 1e7).toFixed(2).replace(/\.?0+$/, "")} crore` : `${Math.round(n / 1e5)} lakh`;

// The headline and the plot drawing are the brief itself, set large, so the
// first screen already shows the house being asked for.
function renderBrief() {
  const f = $("brief");
  if (!f) return;
  const v = (n) => f.elements[n]?.value;
  const unit = plotUnit(f), k = unit === "ft" ? FT : 1;
  const rw = Math.max(3, +v("plot_width") || 40), rd = Math.max(3, +v("plot_depth") || 60);
  const w = rw * k, d = rd * k;
  const road = f.querySelector('input[name="road_direction"]:checked')?.value || "N";
  const levels = +v("levels") || 2;
  const beds = Math.max(1, +v("bedrooms") || 1);
  const budget = +v("budget") || 0;
  const stance = STANCES[+(f.querySelector('input[name="vastu_slider"]:checked')?.value ?? 2)] || STANCES[2];

  setText("hl-plot", `${fmtM(rw)} × ${fmtM(rd)} ${unit}`);
  setText("hl-road", ROAD_WORD[road]);
  const storeys = levels === 1 ? "one storey" : `${NUMWORD[levels] || levels} storeys`;
  setText("hl-prog", `${NUMWORD[beds] || beds} bedroom${beds > 1 ? "s" : ""}, ${storeys}`);
  setText("budget-words", budget ? lakh(budget) : "no budget set");
  // The lawn asked for, in the plot's own unit.
  const lawn = (+v("lawn_share") || 0) / 100;
  setText("lawn-words", lawn
    ? `${Math.round(lawn * 100)}% of the plot kept as lawn, about ${Math.round(rw * rd * lawn).toLocaleString()} ${unit === "ft" ? "sq ft" : "m²"}`
    : "No lawn asked for: the plot's own setbacks stay open");
  setText("stance-note", stance[2]);
  setText("sum-line", `${unit === "ft" ? `${Math.round(rw * rd)} sq ft` : `${Math.round(w * d)} m²`} plot · ${beds} bed · ${budget ? `₹${lakh(budget)}` : "no set budget"} · Vastu ${stance[0].toLowerCase()}`);
  drawPlot({ w, d, rw, rd, unit, road, levels, lawn,
    ...(() => { const sb = autoSetbacks(w * d, +v("setback_front") || null, +v("setback_rear") || null, +v("setback_side") || null, Math.min(w, d));
      return { front: sb[0], rear: sb[1], side: sb[2] }; })() });
}

// The plot to scale: boundary, setback envelope, the road on its side, the
// floors stacked behind, dimensions and a north point. Geometry is set with
// CSS-transitionable attributes so a change of input redraws smoothly.
function drawPlot({ w, d, rw = w, rd = d, unit = "m", road, levels, front, rear, side, lawn = 0 }) {
  const svg = $("plot-svg");
  if (!svg) return;
  // Width runs along the road: an east or west plot is drawn turned, its
  // width north to south beside the road and its depth across (as the server lays it).
  if (road === "E" || road === "W") [w, d, rw, rd] = [d, w, rd, rw];
  const VW = 420, VH = 340, M = 56;
  const k = Math.min((VW - M * 2) / w, (VH - M * 2) / d);
  const pw = w * k, pd = d * k;
  const x0 = (VW - pw) / 2, y0 = (VH - pd) / 2;
  // Which sides face the road: the letters of the direction.
  const has = (s) => road.includes(s);
  const inset = {
    t: has("N") ? front : has("S") ? rear : side,
    b: has("S") ? front : has("N") ? rear : side,
    l: has("W") ? front : has("E") ? rear : side,
    r: has("E") ? front : has("W") ? rear : side,
  };
  if (road.length === 1 && (road === "N" || road === "S")) { inset.l = side; inset.r = side; }
  if (road.length === 1 && (road === "E" || road === "W")) { inset.t = side; inset.b = side; }

  if (!svg.dataset.built) {
    svg.innerHTML = `
      <g class="pf-floors"></g>
      <rect class="pf-plot" />
      <rect class="pf-lawn" />
      <text class="pf-t pf-t--lawn"></text>
      <rect class="pf-env" />
      <g class="pf-road"></g>
      <g class="pf-dims">
        <line class="pf-dim" data-d="w" /><text class="pf-t" data-d="w"></text>
        <line class="pf-dim" data-d="d" /><text class="pf-t" data-d="d"></text>
      </g>
      <g class="pf-north" transform="translate(${VW - 26} 30)">
        <path d="M0 -14 L5 6 L0 2 L-5 6 Z" /><text y="22">N</text>
      </g>`;
    svg.dataset.built = "1";
  }
  const set = (el, a) => { for (const [n, val] of Object.entries(a)) el.setAttribute(n, typeof val === "number" ? val.toFixed(1) : val); };
  set(svg.querySelector(".pf-plot"), { x: x0, y: y0, width: pw, height: pd });
  set(svg.querySelector(".pf-env"), {
    x: x0 + inset.l * k, y: y0 + inset.t * k,
    width: Math.max(0, pw - (inset.l + inset.r) * k), height: Math.max(0, pd - (inset.t + inset.b) * k),
  });

  // Upper floors, stacked behind like sheets on a table.
  const floors = svg.querySelector(".pf-floors");
  floors.innerHTML = "";
  for (let i = levels - 1; i >= 1; i--) {
    const r = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    set(r, { x: x0 + i * 9, y: y0 - i * 9, width: pw, height: pd, class: "pf-floor" });
    floors.append(r);
  }

  // The road: a band along each road side, with its name.
  const g = svg.querySelector(".pf-road");
  g.innerHTML = "";
  const band = (x, y, bw, bh, label, lx, ly, rot = 0) => {
    const r = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    set(r, { x, y, width: bw, height: bh, class: "pf-band" });
    const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
    set(t, { x: lx, y: ly, class: "pf-t pf-t--road", transform: rot ? `rotate(${rot} ${lx} ${ly})` : "" });
    t.textContent = label;
    g.append(r, t);
  };
  const B = 14, G = 8;
  if (has("N")) band(x0 - 20, y0 - G - B, pw + 40, B, "ROAD", x0 + pw / 2, y0 - G - B / 2 + 3);
  if (has("S")) band(x0 - 20, y0 + pd + G, pw + 40, B, "ROAD", x0 + pw / 2, y0 + pd + G + B / 2 + 3);
  if (has("W")) band(x0 - G - B, y0 - 20, B, pd + 40, "ROAD", x0 - G - B / 2 + 3, y0 + pd / 2, -90);
  if (has("E")) band(x0 + pw + G, y0 - 20, B, pd + 40, "ROAD", x0 + pw + G + B / 2 + 3, y0 + pd / 2, -90);

  // Dimensions on the sides away from the road.
  const dimY = has("S") ? y0 - 22 : y0 + pd + 26;
  const dimX = has("E") ? x0 - 26 : x0 + pw + 26;
  set(svg.querySelector('.pf-dim[data-d="w"]'), { x1: x0, x2: x0 + pw, y1: dimY, y2: dimY });
  set(svg.querySelector('.pf-dim[data-d="d"]'), { x1: dimX, x2: dimX, y1: y0, y2: y0 + pd });
  const tw = svg.querySelector('.pf-t[data-d="w"]');
  set(tw, { x: x0 + pw / 2, y: dimY - 6 });
  tw.textContent = `${fmtM(rw)} ${unit}`;
  const td = svg.querySelector('.pf-t[data-d="d"]');
  set(td, { x: dimX + 6, y: y0 + pd / 2, transform: `rotate(-90 ${(dimX + 6).toFixed(1)} ${(y0 + pd / 2).toFixed(1)})` });
  td.textContent = `${fmtM(rd)} ${unit}`;

  // The lawn asked for, at its true share of the plot: a band across the back,
  // away from the road, the way the studio lays the garden out (ground_cover).
  const lw = svg.querySelector(".pf-lawn"), lt = svg.querySelector(".pf-t--lawn");
  const back = road.includes("N") ? "b" : road.includes("S") ? "t" : road.includes("E") ? "l" : "r";
  const across = back === "t" || back === "b";
  const depth = (across ? pd : pw) * Math.min(1, Math.max(0, lawn));
  const r = {
    t: [x0, y0, pw, depth], b: [x0, y0 + pd - depth, pw, depth],
    l: [x0, y0, depth, pd], r: [x0 + pw - depth, y0, depth, pd],
  }[back];
  set(lw, { x: r[0], y: r[1], width: r[2], height: r[3], opacity: lawn > 0 ? 1 : 0 });
  set(lt, { x: r[0] + r[2] / 2, y: r[1] + r[3] / 2 + 4, opacity: lawn > 0 && Math.min(r[2], r[3]) > 14 ? 1 : 0 });
  lt.textContent = `LAWN ${Math.round(lawn * 100)}%`;
  setText("plot-cap", lawn
    ? `Plot to scale, with ${Math.round(lawn * 100)}% kept as lawn at the back; the house and its paving take the rest.`
    : "Plot, setbacks and road, drawn to scale from the brief.");
}

function initBrief() {
  const f = $("brief");
  if (!f) return;
  f.addEventListener("input", renderBrief);
  f.addEventListener("change", renderBrief);
  // Switching the unit converts what is typed, so the plot stays the same size.
  let unit = plotUnit(f);
  f.querySelectorAll('input[name="plot_unit"]').forEach((r) => r.addEventListener("change", () => {
    const next = plotUnit(f);
    if (next === unit) return;
    const k = next === "m" ? FT : 1 / FT;
    for (const n of ["plot_width", "plot_depth"]) {
      const x = +f.elements[n].value;
      if (x) f.elements[n].value = next === "m" ? (Math.round(x * k * 10) / 10) : Math.round(x * k);
    }
    unit = next;
    renderBrief();
  }));
  // Steppers: the − and + beside a number.
  f.querySelectorAll(".step").forEach((b) => b.addEventListener("click", () => {
    const input = b.parentElement.querySelector("input");
    if (+b.dataset.step > 0) input.stepUp(); else input.stepDown();
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }));
  f.querySelectorAll('.amenity-chip input[type="checkbox"]').forEach((chk) => chk.addEventListener("change", () => {
    chk.closest(".amenity-chip")?.classList.toggle("is-checked", chk.checked);
  }));
  $("upload")?.querySelectorAll('.amenity-chip input[type="checkbox"]').forEach((chk) => chk.addEventListener("change", () => {
    chk.closest(".amenity-chip")?.classList.toggle("is-checked", chk.checked);
  }));
  renderBrief();
}

/* ═══ HOME: the brief as a conversation ═══════════════════════════════ */

// The chat writes into the same sheet the manual mode edits, so the plot
// drawing follows the conversation and the run reads one brief either way.
function setField(name, value) {
  const f = $("brief");
  if (name === "vastu") {
    const idx = Math.max(0, STANCES.findIndex(([, k]) => k === value));
    const r = f.querySelector(`input[name="vastu_slider"][value="${idx}"]`);
    if (r) { r.checked = true; r.dispatchEvent(new Event("change", { bubbles: true })); }
    return;
  }
  const inputs = f.querySelectorAll(`[name="${name}"]`);
  if (!inputs.length) return;
  for (const i of inputs) {
    if (i.type === "radio") { if (i.value === value) { i.checked = true; i.dispatchEvent(new Event("change", { bubbles: true })); } }
    else if (i.type === "checkbox") { i.checked = !!value; i.dispatchEvent(new Event("change", { bubbles: true })); }
    else { i.value = value; i.dispatchEvent(new Event("input", { bubbles: true })); }
  }
}

function openManual(mode) {
  setEntry(mode === "upload" ? "upload" : "form", { focus: true });
}

// The three ways in, all in sight at the top of the brief: the form (first,
// and where the studio opens), the conversation, and a drawing to review.
function setEntry(entry, { focus = false } = {}) {
  const e = ["form", "describe", "upload"].includes(entry) ? entry : "form";
  document.body.dataset.entry = e;
  if (e !== "describe") setMode(e === "upload" ? "upload" : "brief");
  document.querySelectorAll(".way__tab").forEach((t) => {
    const on = t.dataset.entry === e;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
  });
  $("sheet")?.setAttribute("aria-labelledby", e === "upload" ? "tab-upload" : "tab-form");
  if (focus) {
    const first = e === "describe" ? document.querySelector(".composer__in")
      : e === "upload" ? $("inp-file") : $("inp-plot-width");
    setTimeout(() => first?.focus({ preventScroll: true }), 60);
  }
}

function initEntry() {
  const tabs = [...document.querySelectorAll(".way__tab")];
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => setEntry(t.dataset.entry, { focus: true }));
    // Arrow keys move along the tabs, Home and End to either end, as a tablist should.
    t.addEventListener("keydown", (ev) => {
      const k = { ArrowRight: 1, ArrowLeft: -1, Home: -99, End: 99 }[ev.key];
      if (k === undefined) return;
      ev.preventDefault();
      const j = k === -99 ? 0 : k === 99 ? tabs.length - 1 : (i + k + tabs.length) % tabs.length;
      setEntry(tabs[j].dataset.entry);
      tabs[j].focus();
    });
  });
  setEntry("form");
}

async function initHome() {
  const host = $("chat");
  if (!host) return;
  const { mountHome } = await import("./home.js");
  // The live hero, the airflow tile and the committee: the page's own proof.
  import("./home-hero.js?v=h5").then(({ mountHero, mountAirShowcase }) => {
    mountHero($("hero3d"), $("hero-cap"));
    const air = $("show-air");
    if (air) new IntersectionObserver((es, o) => { if (es[0].isIntersecting) { mountAirShowcase(air); o.disconnect(); } }).observe(air);
  });
  import("./steps.js").then(({ mountSteps }) => mountSteps()).catch(() => {});
  const grid = $("board-grid");
  if (grid) {
    const { PEOPLE, glyph } = await import("./atelier.js?v=s3");
    for (const p of Object.values(PEOPLE)) {
      const li = el("li", "member"); li.dataset.pig = p.pig;
      li.append(glyph(p.glyph, "member__gl"), el("b", null, p.name), el("span", null, p.role));
      grid.append(li);
    }
  }
  $("cta-go")?.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
    setEntry(document.body.dataset.entry || "form", { focus: true });
  });
  mountHome({
    host, api: API, setField, openManual,
    // A drawing dropped into the chat goes through the plan-review route.
    uploadFile: (f) => {
      const inp = $("inp-file");
      const dt = new DataTransfer(); dt.items.add(f);
      inp.files = dt.files;
      inp.dispatchEvent(new Event("change", { bubbles: true }));
      setEntry("upload");
      $("upload").requestSubmit();
    },
    start: (request, brief, words = "") => {
      S.chatBrief = brief;
      S.chatWords = words;
      if (brief?.colours) S.palette = { ...(S.palette || {}), text: brief.colours };
      const form = readBrief();
      // Said in the chat: "a pool", "a big lawn". The form's own choice wins.
      if (!form.pool && /\b(swimming )?pool\b/i.test(words)) form.pool = /\blap\b/i.test(words) ? "lap" : /\bplunge|small pool/i.test(words) ? "plunge" : "family";
      if (!form.lawn_share && /\b(lawn|garden|green space|open space)\b/i.test(words)) form.lawn_share = /\b(big|large|huge|lots of|spacious)\b/i.test(words) ? 0.35 : 0.2;
      const amenities = [...new Set([...(form.amenities || []), ...(request?.amenities || [])])];
      onSubmit(null, { ...form, ...request, amenities, must_haves: amenities });
    },
  });
}

/* ═══ BOOT ═══════════════════════════════════════════════════════════ */

(async function boot() {
  atelier.mount($("atelier"));
  initBrief();

  $("brief").addEventListener("submit", onSubmit);
  $("upload")?.addEventListener("submit", onUpload);
  initEntry();
  initDropzone();
  initHome();
  $("home").addEventListener("click", () => { if (S.phase === "review") phase("compose"); });
  $("back")?.addEventListener("click", goBack);
  $("resume")?.addEventListener("click", resumeStudio);
  // Esc steps back too, once no dialog or drawer is open to take it first.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || S.phase !== "review") return;
    if (e.target.closest?.("input, select, textarea")) return;
    const open = !$("why").hidden || ($("editdrawer") && !$("editdrawer").hidden);
    if (!open) goBack();
  }, { capture: true });
  $("see-why")?.addEventListener("click", openWhy);
  $("restart")?.addEventListener("click", () => {
    cancelRun();
    atelier.stop();
    S.isGenerating = false;
    const btn = $("convene");
    if (btn) { btn.classList.remove("is-loading"); btn.disabled = false; }
    phase("compose");
  });
  $("why-close").addEventListener("click", () => { $("why").hidden = true; });
  $("why").addEventListener("click", (e) => { if (e.target === $("why")) $("why").hidden = true; });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      $("why").hidden = true;
    }
  });
  $("dl-svg").addEventListener("click", downloadSheet);
  $("dl-dxf").addEventListener("click", downloadDxf);
  initPlate();
  initEditDrawer();
  document.querySelectorAll(".view-tab").forEach((t) =>
    t.addEventListener("click", () => showView(t.dataset.view)));

  const updateEngineStatus = (tone, text) => {
    const note = $("engine-note");
    const dot = $("engine-dot");
    if (note) {
      note.dataset.tone = tone;
      note.textContent = text;
    }
    if (dot) {
      dot.dataset.tone = tone;
    }
  };

  async function checkEngineHealth(retries = 4) {
    for (let attempt = 1; attempt <= retries; attempt++) {
      try {
        const [h, c] = await Promise.all([
          fetch(`${API}/health`).then((r) => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
          }),
          fetch(`${API}/capabilities`).then((r) => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
          }),
        ]);
        S.committee = c.committee || [];
        setText("ledger-cost", (h.total_model_cost_usd || 0).toFixed(2));
        setText("convene-sub", `${S.committee.length || 13} specialists · 3 schemes · costs nothing to run`);
        const critStat = $("convene-critics-status");
        if (critStat) {
          critStat.textContent = `${S.committee.length} PARALLEL CRITICS ARMED`;
        }

        if (h.degraded_mode) {
          updateEngineStatus("ok", "Engine ready");
        } else {
          updateEngineStatus("ok", "Engine ready");
        }
        seatCritics();
        return;
      } catch (err) {
        console.warn(`Health check attempt ${attempt} failed:`, err);
        if (attempt < retries) {
          updateEngineStatus("bad", "Connecting…");
          await new Promise((res) => setTimeout(res, 1200));
        } else {
          updateEngineStatus("bad", "Engine offline");
          toast(`The engine is not answering at ${API}. Start the backend and reload.`);
        }
      }
    }
  }

  checkEngineHealth();
})();

// The committee sits twice: around the atelier table during the run, and in
// the review's east rail, where each person keeps what they said.
function seatCritics() {
  atelier.seat(S.committee);
  const rail = $("critics"); if (!rail) return;
  rail.innerHTML = "";
  for (const c of S.committee) {
    const p = person(c.id, S.committee);
    const row = el("li", "tm");
    row.dataset.critic = c.id;
    row.dataset.pig = p.pig;
    const head = el("button", "tm__head");
    head.type = "button";
    head.setAttribute("aria-expanded", "false");
    head.append(avatar(p, 26));
    const who = el("span", "tm__who");
    who.append(el("b", null, p.name), el("small", null, p.role));
    head.append(who, el("span", "tm__sc", "—"));
    const line = el("p", "tm__line", "");
    const bar = el("span", "tm__bar"); bar.append(el("i"));
    const more = el("div", "tm__more"); more.hidden = true;
    head.addEventListener("click", () => {
      const open = row.classList.toggle("is-open");
      head.setAttribute("aria-expanded", String(open));
      more.hidden = !open;
    });
    row.append(head, line, bar, more);
    rail.append(row);
  }
}

/* ═══ RUN ════════════════════════════════════════════════════════════ */

function readBrief() {
  const d = new FormData($("brief"));
  const n = (k, def = 0) => {
    const raw = d.get(k);
    if (raw === null || raw === undefined || raw === "") return def;
    const val = Number(raw);
    return isNaN(val) ? def : val;
  };
  const stanceIdx = Math.max(0, Math.min(4, Math.round(n("vastu_slider", 2))));
  const vastu = (STANCES[stanceIdx] && STANCES[stanceIdx][1]) || "balanced";

  const amenities = [];
  if (d.get("amenity_pooja")) amenities.push("pooja");
  if (d.get("amenity_dining")) amenities.push("dining");
  if (d.get("amenity_study")) amenities.push("study");
  if (d.get("amenity_utility")) amenities.push("utility");
  if (d.get("amenity_balcony")) amenities.push("balcony");
  if (d.get("amenity_parking")) amenities.push("parking");

  const setbackSide = n("setback_side", 0);
  const elderlyAccess = Boolean(d.get("elderly_access"));

  return {
    project_name: "Studio scheme",
    plot_width: +(Math.max(3, n("plot_width", 40) || 40) * (plotUnit($("brief")) === "ft" ? FT : 1)).toFixed(2),
    plot_depth: +(Math.max(3, n("plot_depth", 60) || 60) * (plotUnit($("brief")) === "ft" ? FT : 1)).toFixed(2),
    plot_unit: plotUnit($("brief")),
    locality: String(d.get("locality") || "Bengaluru, Karnataka"),
    road_direction: String(d.get("road_direction") || "N"),
    levels: Math.max(1, Math.min(6, n("levels", 2) || 2)),
    bedrooms: Math.max(1, n("bedrooms", 3) || 3),
    bathrooms: Math.max(1, n("bathrooms", 3) || 3),
    styles: [String(d.get("styles") || "modern_indian")],
    // Left blank, there is no budget to be over: the cost axis then judges efficiency, not a number nobody gave.
    budget: n("budget", 0) > 0 ? Math.max(500000, n("budget", 0)) : 0,
    currency: "INR",
    vastu: vastu,
    accessibility: elderlyAccess ? "universal" : "basic",
    occupant_adults: Math.max(1, n("occupant_adults", 2) || 2),
    occupant_children: Math.max(0, n("occupant_children", 1)),
    occupant_elders: Math.max(0, n("occupant_elders", 1)),
    // Left blank, the setbacks follow the plot (the server decides, as the sheet shows).
    ...(d.get("setback_front") ? { setback_front: Math.max(0, n("setback_front", 0)) } : {}),
    ...(d.get("setback_rear") ? { setback_rear: Math.max(0, n("setback_rear", 0)) } : {}),
    ...(d.get("setback_side") ? { setback_left: Math.max(0, setbackSide), setback_right: Math.max(0, setbackSide) } : {}),
    finish_tier: String(d.get("finish_tier") || "premium"),
    kitchen_type: String(d.get("kitchen_type") || "open_modular"),
    amenities: amenities,
    must_haves: amenities,
    // Outdoors: the plan leaves this much lawn, and room for the pool.
    ...(n("lawn_share", 0) > 0 ? { lawn_share: Math.min(0.5, n("lawn_share", 0) / 100) } : {}),
    ...(d.get("pool") ? { pool: String(d.get("pool")) } : {}),
  };
}

async function onSubmit(e, preset = null) {
  e?.preventDefault?.();
  if (S.isGenerating) return;

  S.isGenerating = true;
  const btn = $("convene");
  const dot = $("engine-dot");
  const note = $("engine-note");

  if (btn) {
    btn.classList.add("is-loading");
    btn.disabled = true;
    const txt = btn.querySelector(".convene__title-text");
    if (txt) txt.textContent = "Convening the studio…";
  }
  if (dot) dot.dataset.tone = "running";
  if (note) {
    note.dataset.tone = "running";
    note.textContent = "Designing";
  }

  S.briefSent = preset || readBrief();
  S.plans = {}; S.planIds = []; S.activeId = null; S.imported = null;
  S.remarks = {}; S.voices = [];

  atelier.begin({ brief: S.briefSent, onCancel: backToBrief });
  phase("running");

  try {
    await stream(`${API}/design/stream`, S.briefSent);
  } catch (err) {
    if (err.name === "AbortError") return;
    toast(`The engine could not complete this design: ${err.message}`);
    atelier.fail("The run stopped", `The engine could not complete this design: ${err.message}`, { onBack: backToBrief });
    if (dot) dot.dataset.tone = "bad";
    if (note) {
      note.dataset.tone = "bad";
      note.textContent = "Run stopped";
    }
  } finally {
    S.isGenerating = false;
    if (S.phase !== "review" && btn) {
      btn.classList.remove("is-loading");
      btn.disabled = false;
      const txt = btn.querySelector(".convene__title-text");
      if (txt) txt.textContent = "Convene the studio";
      setText("convene-sub", `${S.committee.length || 13} specialists · 3 schemes · costs nothing to run`);
      if (dot) dot.dataset.tone = "ok";
      if (note) {
        note.dataset.tone = "ok";
        note.textContent = "Engine ready";
      }
    }
  }
}

/* ═══ UPLOAD ═════════════════════════════════════════════════════════ */

function setMode(mode) {
  S.mode = mode === "upload" ? "upload" : "brief";
  $("brief").hidden = S.mode !== "brief";
  $("upload").hidden = S.mode !== "upload";
  document.body.dataset.mode = S.mode;
}

function initDropzone() {
  const zone = $("dropzone"), input = $("inp-file");
  if (!zone || !input) return;
  const show = () => {
    const f = input.files?.[0];
    zone.classList.toggle("has-file", Boolean(f));
    $("drop-file").hidden = !f;
    if (f) {
      $("drop-file").textContent = `${f.name} · ${(f.size / 1024).toFixed(0)} KB`;
      $("drop-title").textContent = "Ready to review";
      $("drop-sub").textContent = describeUpload(f);
    }
    $("import-report").hidden = true;
  };
  input.addEventListener("change", show);
  for (const ev of ["dragenter", "dragover"]) {
    zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("is-over"); });
  }
  for (const ev of ["dragleave", "drop"]) {
    zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove("is-over"); });
  }
  zone.addEventListener("drop", (e) => {
    if (e.dataTransfer?.files?.length) { input.files = e.dataTransfer.files; show(); }
  });
}

function describeUpload(f) {
  const ext = (f.name.split(".").pop() || "").toLowerCase();
  if (ext === "dxf") return "A CAD drawing. Rooms are read from closed outlines and their labels, at the drawing's own scale.";
  if (ext === "svg") return "A vector drawing. Rooms are read from shapes and the text inside them; the plot size sets the scale.";
  if (ext === "json") return "A plan exported from this studio. It is loaded exactly as saved.";
  return "An image. A vision model reads the rooms; it can take a minute, and every room it names is listed for you to check.";
}

function renderImportReport(imp, rooms, error) {
  const box = $("import-report"); box.innerHTML = ""; box.hidden = false;
  box.classList.toggle("is-error", Boolean(error));
  if (error) {
    box.append(el("h4", null, "The plan could not be read"), el("p", "bad", error));
    return;
  }
  const src = { dxf: "DXF", svg: "SVG", image: "image (vision model)", json: "plan JSON" }[imp.source] || imp.source;
  box.append(el("h4", null, `Read ${imp.rooms_kept} room${imp.rooms_kept === 1 ? "" : "s"} from the ${src}`));
  if (imp.rooms_read !== imp.rooms_kept) {
    box.append(el("p", "note", `${imp.rooms_read} outlines were found; ${imp.rooms_read - imp.rooms_kept} were too small to be rooms or could not be placed.`));
  }
  if (imp.scale_note) box.append(el("p", "note", imp.scale_note));
  if (imp.unrecognised?.length) {
    box.append(el("p", "warn", `Labels not recognised as rooms (kept as "other"): ${imp.unrecognised.join(", ")}.`));
  }
  for (const w of imp.warnings || []) box.append(el("p", "warn", w));
  if (rooms?.length) {
    const wrap = el("div", "import-rooms");
    for (const r of rooms) {
      const chip = el("span", "import-room");
      if ((r.confidence ?? 1) < 0.6) chip.dataset.low = "1";
      chip.append(el("b", null, r.name), document.createTextNode(` ${r.area.toFixed(1)} m²`));
      chip.title = (r.confidence ?? 1) < 1 ? `Read with ${Math.round(r.confidence * 100)}% confidence` : cap(r.type);
      wrap.append(chip);
    }
    box.append(wrap);
  }
}

async function onUpload(e) {
  e.preventDefault();
  if (S.isGenerating) return;
  const file = $("inp-file").files?.[0];
  if (!file) { toast("Choose a plan file first."); return; }

  S.isGenerating = true;
  const upBtn = $("review-btn");
  if (upBtn) {
    upBtn.classList.add("is-loading");
    upBtn.disabled = true;
  }
  const dot = $("engine-dot");
  const note = $("engine-note");
  if (dot) dot.dataset.tone = "running";
  if (note) {
    note.dataset.tone = "running";
    note.textContent = "Reading the drawing";
  }

  const f = new FormData($("upload"));
  const num = (k) => { const v = Number(f.get(k)); return Number.isFinite(v) && v > 0 ? v : null; };
  const budget = num("budget") || 0;
  const vastu = String(f.get("vastu") || "balanced");
  const body = new FormData();
  body.append("file", file);
  if (num("plot_width")) body.append("plot_width", String(num("plot_width")));
  if (num("plot_depth")) body.append("plot_depth", String(num("plot_depth")));
  body.append("road_direction", String(f.get("road_direction") || "N"));
  if (f.get("name")) body.append("name", String(f.get("name")));

  S.plans = {}; S.planIds = []; S.activeId = null; S.imported = null;
  S.remarks = {}; S.voices = [];
  atelier.begin({ upload: true, fileName: file.name, onCancel: backToBrief });
  phase("running");

  let up;
  try {
    const res = await fetch(`${API}/plans/import`, { method: "POST", body });
    const text = await res.text();
    let data = {}; try { data = JSON.parse(text); } catch { /* not json */ }
    if (!res.ok) throw new Error(data.detail || `${res.status} ${text.slice(0, 160)}`);
    up = data;
  } catch (err) {
    S.isGenerating = false;
    atelier.stop();
    if (upBtn) { upBtn.classList.remove("is-loading"); upBtn.disabled = false; }
    phase("compose");
    setEntry("upload");
    renderImportReport(null, null, err.message);
    toast("The plan could not be read.");
    return;
  }

  S.imported = { file: file.name, ...up.import };
  renderImportReport(up.import, up.rooms, null);
  const site = up.plan?.site || {};
  // Points serialise as [x, y] pairs.
  const pt = (p) => (Array.isArray(p) ? p : [p.x, p.y]);
  const xs = (site.boundary || []).map((p) => pt(p)[0]), ys = (site.boundary || []).map((p) => pt(p)[1]);
  S.briefSent = {
    project_name: up.plan?.name || file.name,
    plot_width: xs.length ? Math.max(...xs) - Math.min(...xs) : 0,
    plot_depth: ys.length ? Math.max(...ys) - Math.min(...ys) : 0,
    road_direction: site.road_direction || String(f.get("road_direction") || "N"),
    levels: up.plan?.levels?.length || 1,
    bedrooms: up.rooms.filter((r) => /bedroom/.test(r.type)).length,
    bathrooms: up.rooms.filter((r) => /bathroom|toilet/.test(r.type)).length,
    budget, vastu, locality: "—", styles: [],
  };
  atelier.say("d.nikhil",
    `${up.import.rooms_kept} rooms read from your ${String(up.import.source).toUpperCase()}. ${up.import.scale_note || ""}`.trim());

  const q = new URLSearchParams({ vastu, budget: String(budget), include_generative_critics: "true" });
  try {
    await stream(`${API}/plans/${up.plan_id}/review/stream?${q}`, null);
  } catch (err) {
    if (err.name === "AbortError") return;
    toast(`The engine could not review this plan: ${err.message}`);
    atelier.fail("The review stopped", `The engine could not review this plan: ${err.message}`, { onBack: backToBrief });
    if (dot) dot.dataset.tone = "bad";
    if (note) { note.dataset.tone = "bad"; note.textContent = `Review failed: ${err.message}`; }
  } finally {
    S.isGenerating = false;
    if (upBtn && S.phase !== "review") {
      upBtn.classList.remove("is-loading");
      upBtn.disabled = false;
    }
  }
}

async function stream(url, simple) {
  cancelRun();
  S.abort = new AbortController();
  S.streamError = null;
  const res = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: simple ? JSON.stringify({ simple, candidates: 3, include_generative_critics: true }) : undefined,
    signal: S.abort.signal,
  });
  if (!res.ok) throw new Error(`${res.status} ${(await res.text()).slice(0, 160)}`);

  const rd = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
  let sawResult = false;
  const seen = () => { sawResult = true; };
  window.addEventListener("aip:result", seen, { once: true });

  // Watchdog. A stream that goes quiet is stuck, not "still working", and
  // leaving the user on a progress line forever is the worst failure mode
  // this screen has. Surface it instead of waiting out the heat death.
  let idle = null;
  const kick = () => {
    clearTimeout(idle);
    idle = setTimeout(() => {
      if (sawResult || (!S.isGenerating && S.phase !== "running")) return;
      atelier.fail("The engine stopped responding",
        "No update for three minutes. The run may still be finishing on the server; check its log, or start again.",
        { onBack: backToBrief });
    }, 180000);
  };
  kick();

  try {
    while (true) {
      const { done, value } = await rd.read(); if (done) break;
      kick();
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) !== -1) { handle(buf.slice(0, i)); buf = buf.slice(i + 2); }
    }
  } finally {
    clearTimeout(idle);
    window.removeEventListener("aip:result", seen);
  }

  if (!sawResult && (S.isGenerating || S.phase === "running")) {
    const why = S.streamError;
    S.streamError = null;
    atelier.fail(why ? "This brief needs a change" : "The studio lost its connection",
      why || "The connection dropped before the design came back. Nothing was lost - press Start designing again.",
      { onBack: backToBrief });
  }
}

function handle(frame) {
  let name = "", raw = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) raw += line.slice(5).trim();
  }
  if (!raw) return;
  let d; try { d = JSON.parse(raw); } catch { return; }

  if (name === "progress") {
    const note = $("engine-note");
    if (note) { note.dataset.tone = "running"; note.textContent = d.message; }
    const dot = $("engine-dot");
    if (dot) dot.dataset.tone = "running";
    if (d.detail?.plan && d.detail?.remarks) {
      S.remarks[d.detail.plan] = Object.fromEntries(d.detail.remarks.map((r) => [r.critic, r]));
    }
    atelier.progress(d);
  } else if (name === "result") {
    window.dispatchEvent(new Event("aip:result"));
    atelier.result(d, { onOpen: () => applyResult(d) });
  } else if (name === "error") {
    S.streamError = d.message || "The engine reported an error.";
    toast(S.streamError);
  }
}

/* ═══ RESULT ═════════════════════════════════════════════════════════ */

async function applyResult(d) {
  if (S.phase !== "running") return;   // the user went back to the brief meanwhile
  S.isGenerating = false;
  S.abort = null;
  const btn = $("convene");
  if (btn) {
    btn.classList.remove("is-loading");
    btn.disabled = false;
  }
  const upBtn = $("review-btn");
  if (upBtn) {
    upBtn.classList.remove("is-loading");
    upBtn.disabled = false;
  }
  S.planIds = d.plan_ids || [];
  S.winnerId = d.winner_plan_id;
  S.activeId = d.winner_plan_id;
  S.consensus = d.consensus;
  // The committee ranks *candidates*. Refinement and negotiation each mint a new
  // plan with a new id, so the returned plan is usually not in the ranking at
  // all. Keeping the candidate id separate is what stops every consensus lookup
  // silently missing the moment the agents actually improve the design.
  S.candidateId = d.selected_candidate_id || d.consensus?.winner_id || d.winner_plan_id;
  S.negotiation = d.negotiation || null;
  S.negotiationOutcome = d.negotiation_outcome || "";
  // Links the server returns are relative to it; with the UI hosted apart they need its origin.
  const apiOrigin = /^https?:/.test(API) ? new URL(API).origin : "";
  S.exportUrls = Object.fromEntries(Object.entries(d.export_urls || {})
    .map(([k, u]) => [k, typeof u === "string" && u.startsWith("/") ? apiOrigin + u : u]));
  S.explanation = d.explanation || "";
  S.recommendations = d.recommendations || [];
  S.projectId = d.project_id; S.sessionId = d.trace_id;
  S.voices = d.voices || [];

  S.plans[d.winner_plan_id] = { plan: d.plan, vastu: d.vastu, cost: d.cost };
  rememberPlan(d.plan);
  // Every candidate's drawing is held too, so any tab survives a restart.
  for (const id of d.plan_ids || []) {
    if (!planJson.has(id)) fetch(`${API}/plans/${id}`).then((r) => (r.ok ? r.json() : null)).then(rememberPlan).catch(() => {});
  }
  setText("ledger-cost", (d.model_cost_usd || 0).toFixed(2));
  if (d.degraded) toast(d.degraded_reason || "Some critics ran in degraded mode.");

  // The sheet the team just drew goes into the plate as a stand-in, so the
  // view transition carries one drawing across rather than a blank box; the
  // full drawing replaces it the moment it arrives.
  const drawn = atelier.currentSheet();
  if (drawn) {
    const ghost = drawn.cloneNode(true);
    ghost.classList.remove("is-on");
    ghost.classList.add("plate__ghost");
    $("plate").replaceChildren(ghost);
  }
  S.sheet = "plan_level_0";
  atelier.stop();
  phase("review");
  $("restart").hidden = false;
  buildSchemeTabs();
  buildSheetTabs();
  renderAll();
  showView("drawings");
}

// Leaving a studio page: Back (the button, the browser's, the phone's, or
// Esc) steps to the view before; from the first view it returns to the
// brief, where "Back to your designs" brings the studio back as it was.
function goBack() {
  if (S.exitRoom) return S.exitRoom();
  if (history.state?.studio) return history.back();
  phase("compose");
}
function resumeStudio() {
  if (!S.activeId || !S.plans?.[S.activeId]) return;
  phase("review");
  $("restart").hidden = false;
  const v = S.view && S.view !== "compose" ? S.view : "drawings";
  history.pushState({ studio: true, view: v }, "", `#${v}`);
  showView(v, { fromHistory: true });
}
window.addEventListener("popstate", (e) => {
  const st = e.state;
  if (st?.studio && S.activeId && S.plans?.[S.activeId]) {
    if (S.phase !== "review") { phase("review"); $("restart").hidden = false; }
    showView(st.view, { fromHistory: true });
  } else if (S.phase === "review") {
    phase("compose");
  }
});

function buildSchemeTabs() {
  const wrap = $("schemes"); wrap.innerHTML = "";
  const ranked = S.consensus?.ranking || [];
  const dq = new Set((S.consensus?.disqualified || []).map((d) => d.candidate_id));

  S.planIds.forEach((id, i) => {
    const row = ranked.find((r) => r.candidate_id === id);
    const b = el("button", "scheme-tab"); b.type = "button"; b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", String(id === activeCandidate()));
    // "Scheme" drops on a narrower bar; the letter and score stay, and the name stays for screen readers.
    if (S.imported && i === 0) b.append(document.createTextNode("Uploaded plan"));
    else {
      b.append(el("span", "scheme-tab__w", "Scheme "), document.createTextNode(String.fromCharCode(65 + i)));
    }
    if (S.imported && i === 0) b.dataset.imported = "1";

    // A scheme with no score was not merely last - it was disqualified for a
    // critical finding and never entered the ranking. Leaving the score blank
    // reads as a rendering fault; saying so is the honest signal.
    if (row) {
      b.append(el("b", null, row.score.toFixed(2)));
      // The number is the committee's score out of 1: say so where it is read.
      b.title = `Committee score ${row.score.toFixed(2)} out of 1 · `
        + (id === S.candidateId ? "selected by the committee" : "on the trade-off frontier");
    } else if (dq.has(id)) {
      b.dataset.dq = "1";
      b.append(el("b", null, "DQ"));
      const why = (S.consensus.disqualified.find((d) => d.candidate_id === id)?.reasons || [])[0];
      b.title = `Disqualified for a critical finding. ${why || ""}`.trim();
    } else {
      b.append(el("b", null, "—"));
      b.title = "Dominated on every measured axis";
    }
    b.addEventListener("click", () => selectScheme(id));
    wrap.append(b);
  });
}

async function selectScheme(id) {
  if (id === S.activeId) return;
  S.activeId = id;
  document.querySelectorAll(".scheme-tab").forEach((b, i) =>
    b.setAttribute("aria-selected", String(S.planIds[i] === id)));

  if (!S.plans[id]) {
    S.plans[id] = {};
    try {
      const [plan, vastu, cost] = await Promise.all([
        fetch(`${API}/plans/${id}`).then((r) => r.json()),
        fetch(`${API}/plans/vastu`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plan_id: id, tradition_weight: 0.5 }) }).then((r) => r.json()),
        fetch(`${API}/plans/cost`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plan_id: id, budget: S.briefSent?.budget || 0 }) }).then((r) => r.json()),
      ]);
      S.plans[id] = { plan, vastu, cost };
      rememberPlan(plan);
    } catch (err) { toast(`Could not load that scheme: ${err.message}`); }
  }
  renderAll();
  showView(S.view);
}

const cur = () => S.plans[S.activeId] || {};

// Map whatever is on screen back to the candidate the committee scored. The
// winner tab shows a post-negotiation plan; every other tab is a candidate and
// maps to itself.
const activeCandidate = () => (S.activeId === S.winnerId ? S.candidateId : S.activeId);
const rankingRow = () =>
  (S.consensus?.ranking || []).find((r) => r.candidate_id === activeCandidate());

function renderAll() {
  renderRail();
  renderCritics();
  renderVerdict();
  loadSheet(S.sheet);
}

function renderRail() {
  const { plan } = cur();
  const idx = S.planIds.indexOf(activeCandidate());
  $("pick-name").textContent = S.imported
    ? (S.briefSent?.project_name || "Uploaded plan")
    : idx >= 0 ? `Scheme ${String.fromCharCode(65 + idx)}` : "Selected scheme";
  const dq = (S.consensus?.disqualified || []).find((d) => d.candidate_id === activeCandidate());
  $("pick-why").textContent = dq
    ? `Disqualified. ${dq.reasons[0] || "It carries a critical finding."} A statutory or physical breach removes a scheme regardless of how it scores elsewhere.`
    : S.imported
      ? (S.negotiationOutcome && S.negotiationOutcome !== "unchanged"
        ? "Your drawing, reviewed as drawn, then adjusted by the committee where it could satisfy a finding without redrawing the plan."
        : "Your drawing, reviewed as drawn. Every critic, the Vastu graph, the cost takeoff and the airflow solve ran on it unchanged.")
      : S.activeId === S.winnerId
        ? "Selected by the committee as the best trade-off across every measured axis."
        : "An alternative on the trade-off frontier. Compare it against the selected scheme.";

  // A scheme the generator could not make clean says so, in the words of
  // the rule it broke. It is offered only when nothing clean was left.
  const guard = plan?.metadata?.guardrail || [];
  if (guard.length) {
    $("pick-why").textContent += ` Offered with reservations: ${guard.slice(0, 3).join("; ")}.`;
  }

  const b = S.briefSent || {};
  const recap = $("brief-recap"); recap.innerHTML = "";
  // The two ways to change a finished design live in the drawer beside the drawing.
  const slot = $("edit-slot");
  const anchor = document.createElement("span");
  slot.replaceChildren(anchor);
  if (!S.imported) {
    mountEditor(anchor, {
      api: API, getPlanId: () => S.activeId, selected: () => S.editSel, select: (id) => { S.editSel = id; },
      canUndo: () => (S.editHistory || []).length > 0,
      said: () => S.editSaid, setSaid: (t) => { S.editSaid = t; },
      onEdited: adoptEdited, onUndo: undoEdit,
      // The plan on screen: rooms are picked by clicking them on it.
      plate: () => $("plate"),
      sheetLevel: () => { const k = /^plan_level_(\d+)$/.exec(S.sheet || ""); return k ? +k[1] : null; },
      showLevel: (i) => loadSheet(`plan_level_${i}`),
      setSync: (fn) => { S.editSync = fn; },
    });
  }
  reviseBox(anchor);
  const rows = S.imported ? [
    ["Source", `${S.imported.file} (${S.imported.source})`],
    ["Rooms read", `${S.imported.rooms_kept} of ${S.imported.rooms_read} outlines`],
    ["Plot", `${(+b.plot_width).toFixed(1)} × ${(+b.plot_depth).toFixed(1)} m`],
    ["Road", b.road_direction],
    ["Bedrooms", b.bedrooms], ["Bathrooms", b.bathrooms],
    ["Floors", b.levels],
    ["Budget", b.budget ? inr(b.budget) : "not set"], ["Vastu", cap(b.vastu || "")],
    ["Openings", S.imported.openings_added ? "placed by the studio" : "as drawn"],
  ] : [
    ["Plot", `${b.plot_width} × ${b.plot_depth} m`],
    ["Locality", b.locality], ["Road", b.road_direction],
    ["Bedrooms", b.bedrooms], ["Bathrooms", b.bathrooms],
    ["Floors", b.levels], ["Style", cap(b.styles?.[0] || "")],
    ["Budget", b.budget ? inr(b.budget) : "not set"], ["Vastu", cap(b.vastu || "")],
  ];
  for (const [k, v] of rows) {
    const d = el("div"); d.append(el("dt", null, k), el("dd", null, String(v ?? "—"))); recap.append(d);
  }
}

/* ── edits to the drawing ─────────────────────────────────────────── */

// The edited plan takes the place of the one on screen, in its own tab, and is
// re-scored in the background; the numbers beside it say so until they land.
async function adoptEdited(newId) {
  const oldId = S.activeId;
  // Undo puts back everything the edit and its re-score replace, the committee's words included.
  const snap = { planIds: [...S.planIds], winnerId: S.winnerId, candidateId: S.candidateId, activeId: oldId,
    consensus: S.consensus ? structuredClone(S.consensus) : S.consensus, sheet: S.sheet,
    explanation: S.explanation, recommendations: S.recommendations, voices: S.voices };
  const jf = (u, body) => fetch(u, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined)
    .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); });
  let plan, vastu, cost;
  try {
    [plan, vastu, cost] = await Promise.all([
      jf(`${API}/plans/${newId}`),
      jf(`${API}/plans/vastu`, { plan_id: newId, tradition_weight: S.plans[oldId]?.vastu?.tradition_weight ?? 0.5, compare_to: oldId }),
      // Priced at the specification and region the plan before it was, so an edit moves the estimate only by what it changed.
    jf(`${API}/plans/cost`, { plan_id: newId, budget: S.briefSent?.budget || 0, ...pricedAs(S.plans[oldId]?.cost) }),
    ]);
  } catch (err) {
    toast(`The edit was made but could not be loaded (${err.message}). The plan on screen is unchanged.`);
    return;
  }
  if (S.activeId !== oldId) return;                    // the client moved to another scheme meanwhile
  (S.editHistory ||= []).push(snap);
  // The row the edited plan replaces: its rank among the schemes stands until the committee ranks them again.
  S.plans[newId] = { plan, vastu, cost, parent: oldId, parentRow: rankingRow() };
  rememberPlan(plan);
  // Say what the edit did to the Vastu, right away.
  const since = vastu?.since_edit;
  if (since && (since.delta || since.changes?.length)) {
    // Name the change that moved the score the way it went (the Vastu tab lists the rest).
    const top = since.changes?.find((c) => c.better === since.delta >= 0) || since.changes?.[0];
    const more = (since.changes?.length || 0) - 1;
    toast(`Vastu ${Math.round(since.score_before)} → ${Math.round(since.score_after)}${top ? `: ${top.title.toLowerCase()} ${top.better ? "now met" : "no longer met"}` : ""}${more > 0 ? ` (+${more} more on the Vastu tab)` : ""}`);
  }
  // The winner on screen may be a refined copy of a candidate; its tab is the candidate's.
  const slotId = S.planIds.includes(oldId) ? oldId : snap.candidateId;
  const swap = (id) => (id === oldId || id === slotId ? newId : id);
  S.planIds = S.planIds.map(swap);
  if (!S.planIds.includes(newId)) S.planIds.push(newId);
  S.winnerId = swap(S.winnerId);
  S.candidateId = swap(S.candidateId);
  S.activeId = newId;
  if (S.consensus) {
    S.consensus.ranking = (S.consensus.ranking || []).filter((r) => r.candidate_id !== oldId && r.candidate_id !== snap.candidateId);
    if (S.consensus.winner_id === oldId) S.consensus.winner_id = newId;
    S.consensus.disqualified = (S.consensus.disqualified || []).filter((d) => d.candidate_id !== oldId);
  }
  buildSchemeTabs();
  renderAll();
  showView(S.view);
  rescoreEdited(newId);
}

// The specification and region an estimate was priced at, to price an edit the same way.
const pricedAs = (c) => Object.fromEntries([["finish_tier", c?.finish_tier], ["region", c?.region]].filter(([, x]) => x));

async function rescoreEdited(id) {
  const q = new URLSearchParams({ vastu: S.briefSent?.vastu || "balanced", budget: String(S.briefSent?.budget || 0),
    include_generative_critics: "true", keep: "true", ...pricedAs(S.plans[id]?.cost) });
  try {
    const res = await fetch(`${API}/plans/${id}/review/stream?${q}`, { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const rd = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
    while (true) {
      const { done, value } = await rd.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) !== -1) {
        const frame = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!/^event: result/m.test(frame)) continue;
        const d = JSON.parse(frame.split("\n").find((l) => l.startsWith("data:")).slice(5));
        if (S.activeId !== id) return;                       // the client moved on
        const row = (d.consensus?.ranking || []).find((r) => r.candidate_id === d.selected_candidate_id) || d.consensus?.ranking?.[0];
        if (row) {
          // Reviewed alone, a plan tops its own vote; scored that way an edit would look far
          // better than it is. Its parent's standing among the schemes carries over, and the
          // committee's new measure of it moves the score (consensus.BORDA_WEIGHT = 0.42).
          const base = S.plans[id]?.parentRow;
          const fair = base && typeof base.borda === "number" && typeof row.utility === "number"
            ? { borda: base.borda, score: Math.round((0.42 * base.borda + 0.58 * row.utility) * 1e4) / 1e4 } : {};
          S.consensus ||= { ranking: [], disqualified: [] };
          S.consensus.ranking = [{ ...row, ...fair, candidate_id: id }, ...(S.consensus.ranking || []).filter((r) => r.candidate_id !== id)];
          S.consensus.winner_id = S.winnerId === id ? id : S.consensus.winner_id;
        }
        S.plans[id] = { plan: d.plan?.id ? d.plan : S.plans[id].plan, vastu: d.vastu || S.plans[id].vastu, cost: d.cost || S.plans[id].cost };
        S.explanation = d.explanation || S.explanation;
        S.recommendations = d.recommendations || S.recommendations;
        S.voices = d.voices || S.voices;
        S.candidateId = S.winnerId === id ? id : S.candidateId;
        buildSchemeTabs();
        renderAll();
        return;
      }
    }
  } catch (err) {
    toast(`The edited plan could not be re-scored: ${err.message}`);
  }
}

function undoEdit() {
  const snap = (S.editHistory || []).pop();
  if (!snap) return;
  Object.assign(S, { planIds: snap.planIds, winnerId: snap.winnerId, candidateId: snap.candidateId,
    activeId: snap.activeId, consensus: snap.consensus, sheet: snap.sheet,
    explanation: snap.explanation, recommendations: snap.recommendations, voices: snap.voices });
  buildSchemeTabs();
  renderAll();
  showView(S.view);
}

function renderCritics() {
  const row = rankingRow();
  const scores = row?.axis_scores || {};
  const cand = activeCandidate();
  const spoken = S.remarks[cand] || {};
  const full = cand === S.candidateId
    ? Object.fromEntries((S.voices || []).map((v) => [v.critic, v]))
    : {};

  document.querySelectorAll(".tm").forEach((tm) => {
    const id = tm.dataset.critic;
    const c = S.committee.find((x) => x.id === id);
    const v = full[id] || spoken[id];
    const score = v?.score ?? (c ? scores[c.axis] : undefined);
    tm.querySelector(".tm__sc").textContent = score == null ? "—" : score.toFixed(2);
    tm.dataset.low = score != null && score < 0.55 ? "1" : "0";
    tm.querySelector(".tm__line").textContent = v?.line || (score == null ? "Did not review this scheme." : "");
    const fill = tm.querySelector(".tm__bar i");
    requestAnimationFrame(() => { fill.style.transform = `scaleX(${score ?? 0})`; });

    const more = tm.querySelector(".tm__more");
    more.innerHTML = "";
    if (v?.detail && v.detail !== v.line) more.append(el("p", "tm__detail", v.detail));
    if (v?.finding) {
      const f = el("p", "tm__finding");
      const sev = el("span", "sev", v.finding.severity);
      sev.dataset.sev = v.finding.severity;
      f.append(sev, document.createTextNode(` ${v.finding.where ? `${v.finding.where}: ` : ""}${v.finding.message}`));
      more.append(f);
    }
    if (v?.suggestion) more.append(el("p", "tm__fix", v.suggestion));
    if (!more.childElementCount) {
      more.append(el("p", "tm__detail", c?.charter || "No specific concern on this scheme."));
    }
  });
}

function renderVerdict() {
  const { plan, vastu, cost } = cur();
  const row = rankingRow();

  $("v-score").textContent = row ? row.score.toFixed(2) : "—";
  $("v-agree").textContent = S.consensus ? `${Math.round(S.consensus.overall_agreement * 100)}% committee agreement` : "—";
  if (vastu) { $("v-vastu").textContent = Math.round(vastu.score); $("v-vastu-note").textContent = `${vastu.grade}, ${String(vastu.stance_label || "balanced").toLowerCase()}`; }
  if (cost) { $("v-cost").textContent = inr(cost.total); $("v-cost-note").textContent = `${inr(cost.p10)} – ${inr(cost.p90)}`; }
  if (plan) {
    $("v-area").textContent = `${Math.round(plan.total_built_area)} m²`;
    $("v-far").textContent = `FAR ${(plan.achieved_far || 0).toFixed(2)} of ${plan.site?.max_far ?? "—"}`;
  }
  // Finding counts must describe the plan being shown, not the candidate the
  // committee voted on. Negotiation routinely clears a critical breach and
  // returns a new plan; reading the counts off the ranking row would keep
  // telling the client their scheme is blocked after the agents unblocked it.
  paintFindingCounts();
}

function paintFindingCounts() {
  const analysis = cur().analysis;
  if (!analysis) {
    $("v-find").textContent = "…";
    $("v-find-note").textContent = "counting";
    loadAnalysis();
    return;
  }

  let total = 0;
  let critical = 0;
  const tally = (list) => {
    for (const f of list || []) {
      total += 1;
      if (f.severity === "critical") critical += 1;
    }
  };
  for (const report of Object.values(analysis.metrics || {})) tally(report.findings);
  tally(analysis.compliance?.findings);

  $("v-find").textContent = total;
  $("v-find-note").textContent = critical
    ? `${critical} critical · blocks delivery`
    : total ? "none critical" : "nothing outstanding";
}

async function loadAnalysis() {
  const id = S.activeId;
  if (!id || S.plans[id]?.analysisPending) return;
  S.plans[id] = S.plans[id] || {};
  S.plans[id].analysisPending = true;
  try {
    const r = await fetch(`${API}/plans/${id}/analysis`);
    if (!r.ok) throw new Error(String(r.status));
    S.plans[id].analysis = await r.json();
    if (S.activeId === id) paintFindingCounts();
  } catch {
    if (S.activeId === id) {
      $("v-find").textContent = "—";
      $("v-find-note").textContent = "could not load";
    }
  } finally {
    S.plans[id].analysisPending = false;
  }
}

/* ═══ VIEWS ══════════════════════════════════════════════════════════ */

const VIEW_GROUPS = {
  report: [["findings", "Findings"], ["negotiation", "Negotiation"], ["audit", "Audit"]],
};
const groupOf = (v) => Object.keys(VIEW_GROUPS).find((g) => VIEW_GROUPS[g].some(([k]) => k === v)) || v;

function showView(v, { fromHistory = false } = {}) {
  if (v === "mandala") v = "vastu";       // the mandala is part of the Vastu page now
  if (VIEW_GROUPS[v] && !VIEW_GROUPS[v].some(([k]) => k === v)) v = S.lastIn?.[v] || VIEW_GROUPS[v][0][0];
  // Each view is a step the browser's (and the phone's) back button can undo.
  if (!fromHistory && S.phase === "review" && history.state?.view !== v) history.pushState({ studio: true, view: v }, "", `#${v}`);
  S.exitRoom = null;
  if (v !== "model" && S.viewer) { S.viewer.dispose(); S.viewer = null; window.speechSynthesis?.cancel(); }
  if (v !== "exterior" && S.exViewer) { S.exViewer.dispose(); S.exViewer = null; }
  if (v !== "air" && S.air) { S.air.dispose(); S.air = null; }
  if (v !== "drawings" && S.sheetViewer) { S.sheetViewer.dispose(); S.sheetViewer = null; S.sheetViewerPlan = null; }
  S.view = v;
  const g = groupOf(v);
  (S.lastIn ||= {})[g] = v;
  document.querySelectorAll(".view-tab").forEach((t) => t.classList.toggle("is-on", t.dataset.view === g));
  // On a narrow screen the tabs scroll sideways: keep the one you are on in sight.
  const on = document.querySelector(".view-tab.is-on"), strip = on?.parentElement;
  if (on && strip && strip.scrollWidth > strip.clientWidth)
    strip.scrollTo({ left: on.getBoundingClientRect().left - strip.getBoundingClientRect().left + strip.scrollLeft
      - (strip.clientWidth - on.offsetWidth) / 2, behavior: reducedMotion() ? "auto" : "smooth" });
  document.querySelectorAll(".pane").forEach((p) => { p.hidden = p.dataset.view !== v; });
  const sub = $("subnav");
  sub.hidden = !VIEW_GROUPS[g];
  sub.innerHTML = "";
  for (const [k, label] of VIEW_GROUPS[g] || []) {
    const b = el("button", null, label);
    b.type = "button";
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", String(k === v));
    b.addEventListener("click", () => showView(k));
    sub.append(b);
  }

  if (v === "vastu") renderVastu();
  if (v === "cost") renderCost();
  if (v === "interior") renderInterior();
  if (v === "model") renderModel();
  if (v === "exterior") renderExterior();
  if (v === "air") renderAir();
  if (v === "findings") renderFindings();
  if (v === "negotiation") renderNegotiation();
  if (v === "audit") renderAudit();
}

const pane = (v) => document.querySelector(`.pane[data-view="${v}"]`);

function scrollPane(v) {
  const p = pane(v); p.innerHTML = "";
  const s = el("div", "pane__scroll"); p.append(s); return s;
}

/* ── drawings ──────────────────────────────────────────────────────── */

const floorName = (i) => (i === 0 ? "Ground" : `Level ${i}`);

function sheetSets() {
  const levels = cur().plan?.levels || [];
  return [
    ["Plans", levels.map((lv) => [`plan_level_${lv.index}`, floorName(lv.index)])],
    ["Elevations", [["elevation_N", "North"], ["elevation_E", "East"], ["elevation_S", "South"], ["elevation_W", "West"]]],
    ["Sections", [["section_aa", "A–A"], ["section_bb", "B–B"]]],
    ["Roof", [["roof_plan", "Roof"]]],
    ["Site", [["site_plan", "Site"]]],
    ["Airflow", levels.map((lv) => [`airflow_level_${lv.index}`, floorName(lv.index)])],
  ];
}

function buildSheetTabs() {
  const sets = sheetSets();
  const inSet = sets.find(([, items]) => items.some(([k]) => k === S.sheet)) || sets[0];
  const groups = $("sheet-groups"); groups.innerHTML = "";
  for (const [name, items] of sets) {
    if (!items.length) continue;
    const b = el("button", null, name); b.type = "button"; b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", String(name === inSet[0]));
    b.addEventListener("click", () => {
      const keep = items.find(([k]) => k.replace(/^\w+_level_/, "") === S.sheet.replace(/^\w+_level_/, ""));
      loadSheet((keep || items[0])[0]);
    });
    groups.append(b);
  }
  const tabs = $("sheet-tabs"); tabs.innerHTML = "";
  tabs.hidden = inSet[1].length < 2;
  for (const [key, label] of inSet[1]) {
    const b = el("button", null, label); b.type = "button"; b.setAttribute("role", "tab");
    b.dataset.sheet = key;
    b.setAttribute("aria-selected", String(key === S.sheet));
    b.addEventListener("click", () => loadSheet(key));
    tabs.append(b);
  }
}

/* ── drawings: pan and zoom ─────────────────────────────────────────── */

// Scroll to zoom toward the pointer, drag to pan, double-click to step in
// or back to fit. The drawing moves; the plate stays put.
const plateView = { z: 1, x: 0, y: 0, drag: null };

function applyPlate(animate = false) {
  const art = $("plate")?.querySelector("svg, img");
  if (art) {
    art.style.transition = animate ? "transform .45s cubic-bezier(.16,1,.3,1)" : "none";
    art.style.transform = `translate(${plateView.x}px, ${plateView.y}px) scale(${plateView.z})`;
  }
  setText("zoom-val", `${Math.round(plateView.z * 100)}%`);
  // On a phone the drawing only takes the finger once it is zoomed in; at fit,
  // a vertical swipe over it scrolls the page.
  $("plate")?.classList.toggle("is-zoomed", plateView.z > 1.02);
}

function zoomPlate(z, cx = 0, cy = 0, animate = false) {
  const next = Math.max(0.5, Math.min(5, z));
  const f = next / plateView.z;
  plateView.x = cx - (cx - plateView.x) * f;
  plateView.y = cy - (cy - plateView.y) * f;
  plateView.z = next;
  applyPlate(animate);
}

function resetPlate(animate = true) {
  Object.assign(plateView, { z: 1, x: 0, y: 0 });
  applyPlate(animate);
}

function initEditDrawer() {
  const drawer = $("editdrawer"), open = $("edit-open");
  if (!drawer || !open) return;
  // The editor docks beside the plan, which makes room for it, so the room
  // being changed stays in view and can be clicked.
  const set = (on) => {
    drawer.hidden = !on; open.setAttribute("aria-expanded", String(on));
    drawer.closest(".pane")?.classList.toggle("is-editing", on);
    open.textContent = on ? "Done editing" : "Edit design";
    const svg = $("plate")?.querySelector("svg");
    if (on) S.editSync?.(); else svg?.classList.remove("is-editing", "is-swapping");
  };
  open.addEventListener("click", () => set(drawer.hidden));
  $("editdrawer-x")?.addEventListener("click", () => set(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !drawer.hidden) set(false); });
  S.openEditor = () => set(true);
}

function initPlate() {
  const plate = $("plate");
  if (!plate) return;
  const centre = (e) => {
    const r = plate.getBoundingClientRect();
    return [e.clientX - r.left - r.width / 2, e.clientY - r.top - r.height / 2];
  };
  // The 3D sheets handle their own pan and zoom.
  const own = (e) => e.target.closest?.(".plate3d, .plate3d__tools");
  plate.addEventListener("wheel", (e) => {
    if (own(e)) return;
    e.preventDefault();
    zoomPlate(plateView.z * (e.deltaY < 0 ? 1.15 : 1 / 1.15), ...centre(e));
  }, { passive: false });
  // Two fingers pinch; one finger pans.
  const fingers = new Map();
  let pinch = null;
  const spread = () => {
    const [a, b] = [...fingers.values()];
    return { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  };
  plate.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || own(e)) return;
    fingers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    plate.setPointerCapture(e.pointerId);
    if (fingers.size === 2) {
      plateView.drag = null;
      pinch = { ...spread(), z: plateView.z };
      return;
    }
    plateView.drag = { x: e.clientX - plateView.x, y: e.clientY - plateView.y };
    plate.classList.add("is-panning");
  });
  plate.addEventListener("pointermove", (e) => {
    if (fingers.has(e.pointerId)) fingers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch && fingers.size === 2) {
      const now = spread();
      const r = plate.getBoundingClientRect();
      zoomPlate(pinch.z * (now.d / pinch.d), now.x - r.left - r.width / 2, now.y - r.top - r.height / 2);
      return;
    }
    if (!plateView.drag) return;
    plateView.x = e.clientX - plateView.drag.x;
    plateView.y = e.clientY - plateView.drag.y;
    applyPlate();
  });
  const end = (e) => {
    if (e?.pointerId != null) fingers.delete(e.pointerId);
    if (fingers.size < 2) pinch = null;
    plateView.drag = null; plate.classList.remove("is-panning");
  };
  plate.addEventListener("pointerup", end);
  plate.addEventListener("pointercancel", end);
  plate.addEventListener("dblclick", (e) => {
    if (plateView.z > 1.05) resetPlate();
    else zoomPlate(2, ...centre(e), true);
  });
  $("zoom-in")?.addEventListener("click", () => zoomPlate(plateView.z * 1.3, 0, 0, true));
  $("zoom-out")?.addEventListener("click", () => zoomPlate(plateView.z / 1.3, 0, 0, true));
  $("zoom-val")?.addEventListener("click", () => resetPlate());
}

// Elevations, sections, roof and site are drawn from the 3D model in
// orthographic projection, lit by a sun the reader can move.
const ORTHO = { elevation_N: "N", elevation_E: "E", elevation_S: "S", elevation_W: "W",
  section_aa: "sectionA", section_bb: "sectionB", roof_plan: "roof", site_plan: "site" };

function sheetModelUrl(id) {
  const pal = S.palette || {};
  const q = new URLSearchParams(); if (pal.id) q.set("palette", pal.id); if (pal.text) q.set("colours", pal.text); if (pal.design) q.set("design", pal.design);
  return `${API}/plans/${id}/model.glb${q.size ? `?${q}` : ""}`;
}

async function loadOrthoSheet(key) {
  const plate = $("plate");
  const kind = ORTHO[key];
  const id = S.activeId;
  let host = plate.querySelector(".plate3d");
  if (!host || S.sheetViewerPlan !== id) {
    S.sheetViewer?.dispose(); S.sheetViewer = null;
    plate.innerHTML = "";
    host = el("div", "plate3d");
    const tools = el("div", "plate3d__tools");
    const sun = el("label", "plate3d__ctl");
    sun.append(el("span", null, "Sun"));
    const sunIn = el("input"); sunIn.type = "range"; sunIn.min = "6.5"; sunIn.max = "18.5"; sunIn.step = "0.1"; sunIn.value = "15";
    const sunOut = el("b", null, "15:00");
    sun.append(sunIn, sunOut);
    const cut = el("label", "plate3d__ctl plate3d__ctl--cut");
    cut.append(el("span", null, "Cut"));
    const cutIn = el("input"); cutIn.type = "range"; cutIn.min = "0.05"; cutIn.max = "0.95"; cutIn.step = "0.01"; cutIn.value = "0.5";
    cut.append(cutIn);
    tools.append(sun, cut);
    plate.append(host, tools);
    const { Viewer3D } = await import("./viewer3d.js?v=p17");
    if (S.sheet !== key) return;
    S.sheetViewer = new Viewer3D(host);
    S.sheetViewerPlan = id;
    host.append(el("p", "model-cap", "Building the model…"));
    S.sheetViewerUrl = null;
    sunIn.addEventListener("input", () => {
      const h = +sunIn.value; sunOut.textContent = `${String(Math.floor(h)).padStart(2, "0")}:${String(Math.round((h % 1) * 60)).padStart(2, "0")}`;
      S.sheetViewer?.setSun(h);
    });
    cutIn.addEventListener("input", () => S.sheetViewer?.setOrtho(S.sheetViewer.orthoKind, { cut: +cutIn.value }));
  }
  if (S.sheet !== key || !S.sheetViewer) return;
  // The sheet shows the design and colours chosen now, rebuilt in place when
  // they change: a recoloured house redraws its elevations.
  const url = sheetModelUrl(id);
  if (S.sheetViewerUrl !== url) {
    await S.sheetViewer.load(url, { keepView: !!S.sheetViewerUrl });
    S.sheetViewerUrl = url;
    plate.querySelector(".model-cap")?.remove();
    if (S.sheet !== key || !S.sheetViewer) return;
  }
  plate.querySelector(".plate3d__ctl--cut").hidden = !kind.startsWith("section");
  S.sheetViewer.setOrtho(kind, { cut: +(plate.querySelector(".plate3d__ctl--cut input")?.value || 0.5) });
  const [set, items] = sheetSets().find(([, it]) => it.some(([k]) => k === key)) || ["", []];
  const label = items.find(([k]) => k === key)?.[1] || "";
  $("plate-caption").textContent = `${set === label ? set : `${set} · ${label}`}  ·  drag to pan, scroll to zoom${kind.startsWith("section") ? ", slide the cut" : ""}, move the sun`;
}

async function loadSheet(key) {
  S.sheet = key;
  buildSheetTabs();
  if (ORTHO[key]) return loadOrthoSheet(key).catch((err) => {
    $("plate").innerHTML = ""; $("plate").append(el("p", "empty-note", `That view could not be built (${err.message}).`));
  });
  S.sheetViewer?.dispose(); S.sheetViewer = null; S.sheetViewerPlan = null;
  const plate = $("plate");
  const ghost = plate.querySelector(".plate__ghost");
  if (!ghost) {
    plate.innerHTML = "";
    plate.append(el("p", "empty-note", "Drawing…"));
  }
  try {
    const r = await fetch(`${API}/plans/${S.activeId}/drawings/${key}.svg?dark=true`);
    if (!r.ok) throw new Error(String(r.status));
    const text = await r.text();
    if (S.sheet !== key) return;   // another sheet was asked for meanwhile
    plate.innerHTML = text;
    resetPlate(false);
    if (!$("editdrawer")?.hidden) S.editSync?.();     // the room being edited stays marked
    const fresh = plate.querySelector("svg");
    if (fresh && ghost && !reducedMotion()) {
      fresh.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 420, easing: "ease-out" });
    }
    const { plan } = cur();
    const [set, items] = sheetSets().find(([, it]) => it.some(([k]) => k === key)) || ["", []];
    const label = items.find(([k]) => k === key)?.[1] || "";
    $("plate-caption").textContent = [set === label ? set : `${set} · ${label}`, plan?.style ? cap(plan.style) : ""]
      .filter(Boolean).join("  ·  ");
  } catch (err) {
    plate.innerHTML = "";
    plate.append(el("p", "empty-note", `That drawing could not be produced (${err.message}).`));
  }
}

function downloadSheet() {
  const svg = $("plate").querySelector("svg");
  if (!svg) return toast("No drawing to download yet.");
  const blob = new Blob([svg.outerHTML], { type: "image/svg+xml" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = `${S.sheet}.svg`; a.click();
  URL.revokeObjectURL(a.href);
}

function downloadDxf() {
  // The sheet tabs cover elevations and sections too; DXF is emitted per floor
  // plan, so fall back to the ground floor when the current sheet is not one.
  const m = /^plan_level_(\d+)$/.exec(S.sheet);
  const level = m ? m[1] : 0;
  const url = S.exportUrls[`dxf_level_${level}`]
    || `${API}/plans/${S.activeId}/level-${level}.dxf`;
  const a = document.createElement("a");
  a.href = url;
  a.download = `${S.activeId}_level_${level}.dxf`;
  a.click();
  toast(`Level ${level} exported as editable CAD geometry.`);
}

/* ── mandala ───────────────────────────────────────────────────────── */

/* ── vastu ─────────────────────────────────────────────────────────── */

// The nine squares of the Vastu Purusha mandala, as the plan is read.
const VX_ZONES = [
  ["NW", "Vayavya", "air"], ["N", "Uttara", "wealth"], ["NE", "Ishanya", "water"],
  ["W", "Paschima", "gain"], ["C", "Brahmasthan", "space"], ["E", "Purva", "sun"],
  ["SW", "Nairutya", "earth"], ["S", "Dakshina", "rest"], ["SE", "Agneya", "fire"],
];
const VX_CATS = { zone_placement: "Room zones", entrance: "Entrance", brahmasthan: "Centre", water: "Water", fire: "Fire",
  mass_distribution: "Mass and open space", proportion: "Shape", openings: "Openings", slope: "Slope",
  circulation: "Stairs", sleeping: "Sleeping", relations: "Rooms and neighbours" };
// The stance, as five named readings from modern to orthodox.
// The same five stances, at the same weights, as the brief's Vastu question (domain/brief.py).
const VX_STANCES = [[0, "Modern", "ignore"], [0.25, "Advisory", "advisory"], [0.5, "Balanced", "balanced"],
  [0.8, "Strict", "strict"], [1, "Orthodox", "orthodox"]];
const vxStanceAt = (w) => VX_STANCES.reduce((a, s) => (Math.abs(s[0] - w) < Math.abs(a[0] - w) ? s : a));
const VX_WORD = { ideal: "Ideal here", acceptable: "Acceptable here", neutral: "Neutral here", discouraged: "Discouraged here",
  prohibited: "Forbidden here", undetermined: "No reading" };
const vxName = (z) => VX_ZONES.find(([k]) => k === z)?.[1] || z;

// The plan drawn on the Vastu Purusha mandala: north up, the 9 x 9 padas
// over the house, the nine zones named round it, every room marked by what
// the reading says of it where it stands.
function vxMandala(plan, v, level, onRoom) {
  const levels = plan?.levels || [];
  const lv = levels.find((l) => l.index === level) || levels[0];
  const ground = levels.find((l) => l.index === 0) || lv;
  if (!lv) return el("p", "empty-note", "No plan to read.");
  const na = ((plan.site?.north_angle || 0) * Math.PI) / 180;
  // Points come as [x, y] or {x, y}; turned so north is up.
  const rot = (q) => {
    const x = Array.isArray(q) ? q[0] : q.x, y = Array.isArray(q) ? q[1] : q.y;
    return [x * Math.cos(na) + y * Math.sin(na), -x * Math.sin(na) + y * Math.cos(na)];
  };
  // The mandala is laid on the ground floor's footprint, so every floor reads against the same field.
  const field = ground.rooms.flatMap((r) => (r.polygon || []).map(rot));
  const xs = field.map((p) => p[0]), ys = field.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const w = x1 - x0, h = y1 - y0, m = Math.max(w, h) * 0.2, fs = Math.max(w, h) / 30;
  const NS = "http://www.w3.org/2000/svg";
  const n = (tag, attrs = {}, text) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, val] of Object.entries(attrs)) e.setAttribute(k, val);
    if (text != null) e.textContent = text;
    return e;
  };
  const svg = n("svg", { viewBox: `${x0 - m} ${-(y1 + m)} ${w + 2 * m} ${h + 2 * m}`, class: "vxm" });
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${floorName(lv.index)} plan on the Vastu mandala, north at the top`);
  // The padas: hairlines; the nine zones a step brighter; the Brahmasthan dashed.
  const g = n("g", { class: "vxm__grid" });
  for (let i = 0; i <= 9; i++) {
    const cls = i % 3 === 0 ? "vxm__zone" : "vxm__pada";
    g.append(n("line", { x1: x0 + (w * i) / 9, y1: -y0, x2: x0 + (w * i) / 9, y2: -y1, class: cls }));
    g.append(n("line", { x1: x0, y1: -(y0 + (h * i) / 9), x2: x1, y2: -(y0 + (h * i) / 9), class: cls }));
  }
  g.append(n("rect", { x: x0 + w / 3, y: -(y0 + (2 * h) / 3), width: w / 3, height: h / 3, class: "vxm__brahma" }));
  svg.append(g);
  // The rooms, marked by their reading.
  const reads = Object.fromEntries((v.graph_placements || []).map((p) => [p.room_id, p]));
  const rooms = n("g", { class: "vxm__rooms" });
  for (const r of lv.rooms) {
    if (!r.polygon || r.polygon.length < 3) continue;
    const pts = r.polygon.map(rot);
    const p = reads[r.id];
    const poly = n("polygon", { points: pts.map(([x, y]) => `${x},${-y}`).join(" "), class: "vxm__room", "data-v": p?.verdict || "none" });
    const tip = p ? `${p.room}: ${(VX_WORD[p.verdict] || p.verdict).toLowerCase()}, in the ${p.direction} (${p.quarter})`
      + (p.better_directions?.length && !["ideal", "acceptable"].includes(p.verdict) ? `. Better in the ${p.better_directions.map((b) => b.direction).join(", ")}` : "")
      : r.name || r.type;
    poly.append(n("title", {}, tip));
    if (p) {
      poly.setAttribute("tabindex", "0");
      poly.addEventListener("click", () => onRoom?.(r.id));
      poly.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onRoom?.(r.id); } });
    }
    rooms.append(poly);
    // The name sits across the room, turns up a tall narrow one, and is left to the tooltip where neither fits.
    const rx = pts.map((q) => q[0]), ry = pts.map((q) => q[1]);
    const bw = Math.max(...rx) - Math.min(...rx), bh = Math.max(...ry) - Math.min(...ry);
    const cx = (Math.max(...rx) + Math.min(...rx)) / 2, cy = (Math.max(...ry) + Math.min(...ry)) / 2;
    const label = (r.name || r.type || "").replace(/_/g, " ");
    const size = fs * 0.78, long = label.length * size * 0.56;
    if (long < bw * 0.88 && size * 1.6 < bh) rooms.append(n("text", { x: cx, y: -cy, "font-size": size, class: "vxm__name" }, label));
    else if (long < bh * 0.88 && size * 1.6 < bw) rooms.append(n("text", { x: cx, y: -cy, "font-size": size, class: "vxm__name", transform: `rotate(-90 ${cx} ${-cy})` }, label));
  }
  svg.append(rooms);
  // The zones, named round the field: Ishanya at the north-east, Brahmasthan at the heart.
  const at = { NW: [0, 2], N: [1, 2], NE: [2, 2], W: [0, 1], E: [2, 1], SW: [0, 0], S: [1, 0], SE: [2, 0] };
  const lab = n("g", { class: "vxm__labels", "font-size": fs });
  for (const [z, [cx, cy]] of Object.entries(at)) {
    const x = cx === 0 ? x0 - m * 0.5 : cx === 2 ? x1 + m * 0.5 : x0 + w / 2;
    const y = cy === 0 ? y0 - m * 0.42 : cy === 2 ? y1 + m * 0.42 : y0 + h / 2;
    const t = n("text", { x, y: -y, class: "vxm__label" });
    t.append(n("tspan", { x, dy: "-0.2em", class: "vxm__dir" }, z), n("tspan", { x, dy: "1.25em", class: "vxm__zn" }, vxName(z)));
    lab.append(t);
  }
  svg.append(lab);
  return svg;
}

function renderVastu() {
  const s = scrollPane("vastu");
  const v = cur().vastu;
  const plan = cur().plan;
  if (!v) { s.append(el("p", "empty-note", "No Vastu assessment for this scheme.")); return; }
  const reads = v.graph_placements || [];

  // ── the reading: the plan on the mandala, and what it comes to ────
  const top = el("section", "vx2");
  const draw = el("figure", "vx2__draw");
  const levels = plan?.levels || [];
  S.vastuLevel = levels.some((l) => l.index === S.vastuLevel) ? S.vastuLevel : 0;
  const showRoom = (id) => {
    const row = s.querySelector(`#vx-room-${id}`);
    if (!row) return;
    row.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "center" });
    row.classList.remove("is-flash"); void row.offsetWidth; row.classList.add("is-flash");
  };
  const paint = () => {
    draw.replaceChildren();
    if (levels.length > 1) {
      const floors = el("div", "vx2__floors"); floors.setAttribute("role", "radiogroup"); floors.setAttribute("aria-label", "Floor");
      for (const lv of levels) {
        const b = el("button", null, floorName(lv.index)); b.type = "button"; b.setAttribute("role", "radio");
        b.setAttribute("aria-checked", String(lv.index === S.vastuLevel));
        b.addEventListener("click", () => { S.vastuLevel = lv.index; paint(); draw.querySelector('[aria-checked="true"]')?.focus(); });
        floors.append(b);
      }
      draw.append(floors);
    }
    draw.append(vxMandala(plan, v, S.vastuLevel, showRoom));
    const key = el("figcaption", "vx2__key");
    for (const [k, t] of [["fits", "Placed as the texts ask"], ["discouraged", "Discouraged where it stands"], ["prohibited", "Forbidden where it stands"], ["brahma", "Brahmasthan, the centre kept open"]]) {
      const i = el("i"); i.dataset.v = k;
      const item = el("span", "vx2__k"); item.append(i, document.createTextNode(t)); key.append(item);
    }
    draw.append(key);
  };
  paint();

  const read = el("div", "vx2__read");
  const score = el("h2", "vx2__score");
  score.append(el("span", "vx2__word", "Vastu"), el("b", null, String(Math.round(v.score))), el("small", null, "/100"));
  read.append(score, el("p", "vx2__grade", `${v.grade}, read at a ${String(v.stance_label || "balanced").toLowerCase()} stance`));
  read.append(el("p", "vx2__meta", `${v.rules_assessed} of ${v.rules_total} rules could be measured on this plan. `
    + (v.violations ? `${v.violations} ${v.violations === 1 ? "is" : "are"} not met${v.serious_violations ? `, ${v.serious_violations} of them serious` : ""}.` : "Every one of them is met.")));
  // Stance: the plan was laid out for the brief's reading; this re-reads the same plan
  // at another, without changing it, and offers to redesign at that one.
  const stance = el("div", "vx2__stance");
  const sid = "vx-stance-l";
  const [nowW, nowName, nowKey] = vxStanceAt(v.tradition_weight ?? 0.5);
  const briefKey = S.briefSent?.vastu || "balanced";
  const [, briefName] = VX_STANCES.find((x) => x[2] === briefKey) || VX_STANCES[2];
  const lab = el("span", "vx2__label", "What if the texts were read differently?"); lab.id = sid;
  stance.append(lab, el("p", "vx2__hint", S.imported
    ? `Your drawing is read here at a ${briefName.toLowerCase()} stance. Pick another to see how the same plan scores.`
    : `This plan was laid out for a ${briefName.toLowerCase()} reading, as your brief asked. Pick another to see how the same plan would score; the plan itself does not change.`));
  const seg = el("div", "vx2__seg"); seg.setAttribute("role", "radiogroup"); seg.setAttribute("aria-labelledby", sid);
  for (const [wgt, name, key] of VX_STANCES) {
    const b = el("button", null, name); b.type = "button"; b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(key === nowKey));
    if (key === briefKey) {
      b.dataset.brief = "1"; b.title = "The stance your brief asked for";
      b.append(el("span", "sr-only", " (your brief)"));
    }
    b.addEventListener("click", () => {
      if (key === nowKey) return;
      // The pill moves at once; the reading follows when the server answers.
      seg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
      seg.setAttribute("aria-busy", "true");
      rescore(wgt);
    });
    seg.append(b);
  }
  const marks = el("div", "vx2__marks"); marks.setAttribute("aria-hidden", "true");
  for (const [, , key] of VX_STANCES) marks.append(el("span", null, key === briefKey ? "Your brief" : ""));
  stance.append(seg, marks);
  stance.append(el("p", "vx2__hint", "Modern weighs each rule by what it does for light, air and structure; orthodox follows the texts as written."));
  // Read at another stance than the brief's: the layout can be redrawn for it.
  if (nowKey !== briefKey && !S.imported && S.briefSent) {
    const re = el("div", "vx2__redo");
    re.append(el("p", null, `Scored at ${nowName.toLowerCase()}, this is still the plan laid out for ${briefName.toLowerCase()}. Redesigning starts a fresh run from your brief with only the Vastu stance changed, and replaces this design and its edits.`));
    const go = el("button", "btn btn--line", `Redesign for a ${nowName.toLowerCase()} reading`); go.type = "button";
    go.addEventListener("click", () => {
      // The brief form follows, so New brief shows the stance this design was made for.
      const idx = VX_STANCES.findIndex((x) => x[2] === nowKey);
      const r = document.querySelector(`input[name="vastu_slider"][value="${idx}"]`);
      if (r) { r.checked = true; r.dispatchEvent(new Event("change", { bubbles: true })); }
      onSubmit(null, { ...S.briefSent, vastu: nowKey });
    });
    re.append(go);
    stance.append(re);
  }
  read.append(stance);

  // What the last edit did.
  const since = v.since_edit;
  if (since) {
    const box = el("section", "vx2__since");
    box.append(el("h3", "vx2__h", since.delta
      ? `Since your edit: ${Math.round(since.score_before)} to ${Math.round(since.score_after)}`
      : `Since your edit: unchanged at ${Math.round(since.score_after)}`));
    for (const c of (since.changes || []).slice(0, 5)) {
      const row = el("p", `vx2__change ${c.better ? "is-up" : "is-down"}`);
      row.append(el("b", null, c.better ? "Now met" : "No longer met"), document.createTextNode(` ${c.title}`));
      box.append(row);
    }
    if (!since.changes?.length) box.append(el("p", "vx2__hint", "No rule changed its reading."));
    read.append(box);
  }

  // The fixes worth most, in order.
  const fixes = v.top_remedies || [];
  if (fixes.length) {
    read.append(el("h3", "vx2__h", "What to fix first"));
    const ol = el("ol", "vx2__fixes");
    for (const r of fixes.slice(0, 4)) {
      const li = el("li");
      const head = el("div", "vx2__fixhead");
      head.append(el("span", "vx2__fixt", r.title), el("span", "vx2__gain", `+${r.points_recoverable.toFixed(1)}`));
      li.append(head, el("p", "vx2__fixr", r.remedy || r.explanation));
      li.append(el("p", "vx2__fixs", `Score after: ${Math.round(r.score_if_fixed)}${r.modern_validity >= 0.65 ? ". It also helps the building on its own merits." : ""}`));
      ol.append(li);
    }
    read.append(ol);
  }
  top.append(draw, read);
  s.append(top);

  // ── room by room ─────────────────────────────────────────────────
  if (reads.length) {
    s.append(el("h3", "sec", "Room by room"));
    const tbl = el("div", "vx2__rooms"); tbl.setAttribute("role", "table"); tbl.setAttribute("aria-label", "Each room's Vastu reading");
    const hd = el("div", "vx2__row vx2__row--head"); hd.setAttribute("role", "row");
    for (const t of ["Room", "Where it stands", "Reading", "Better in"]) { const c = el("span", null, t); c.setAttribute("role", "columnheader"); hd.append(c); }
    tbl.append(hd);
    const order = { prohibited: 0, discouraged: 1, neutral: 2, undetermined: 3, acceptable: 4, ideal: 5 };
    const floorOf = Object.fromEntries(levels.flatMap((l) => l.rooms.map((r) => [r.id, l.index])));
    for (const p of [...reads].sort((a, b) => (order[a.verdict] ?? 3) - (order[b.verdict] ?? 3) || a.score - b.score)) {
      const row = el("div", "vx2__row"); row.setAttribute("role", "row"); row.id = `vx-room-${p.room_id}`; row.dataset.v = p.verdict;
      const good = ["ideal", "acceptable", "undetermined"].includes(p.verdict);
      for (const t of [p.room, `${p.direction}, ${p.quarter}`, VX_WORD[p.verdict] || p.verdict,
        good ? "" : (p.better_directions || []).map((b) => b.direction).join(", ")]) {
        const c = el("span", null, t); c.setAttribute("role", "cell"); row.append(c);
      }
      // A house of more than one floor has a Corridor on each: say which.
      if (levels.length > 1 && floorOf[p.room_id] != null) row.firstChild.append(el("small", "vx2__floor", floorName(floorOf[p.room_id])));
      tbl.append(row);
    }
    s.append(tbl);
  }

  // ── by category ──────────────────────────────────────────────────
  const cats = (v.category_scores || []).filter((c) => c.rules_assessed > 0 && VX_CATS[c.category]);
  if (cats.length) {
    s.append(el("h3", "sec", "By category"));
    const box = el("div", "vx2__cats");
    for (const c of cats.sort((a, b) => b.weight - a.weight)) {
      const pct = Math.round(c.score > 1 ? c.score : c.score * 100);
      const row = el("div", "vx2__cat");
      const bar = el("span", "vx2__bar"); const fill = el("i"); fill.style.setProperty("--f", (pct / 100).toFixed(3));
      if (pct < 40) fill.dataset.v = "low";
      bar.append(fill);
      row.append(el("span", null, VX_CATS[c.category]), bar, el("b", null, String(pct)));
      box.append(row);
    }
    s.append(box);
  }
  if (v.reconciliation_note) s.append(el("p", "vx2__note", v.reconciliation_note));

  // ── for the builder: decided on the plot ─────────────────────────
  const site = (v.verdicts || []).filter((x) => x.category === "site");
  if (site.length) {
    s.append(el("h3", "sec", "For the builder, on the plot"));
    s.append(el("p", "vx2__note", "Placed during construction, so they are in neither the drawings nor the score."));
    const ul = el("ul", "vx-check");
    for (const x of site) { const li = el("li"); li.append(el("b", null, x.title), el("span", null, x.remedy || "")); ul.append(li); }
    s.append(ul);
  }

  // ── every rule, folded away ──────────────────────────────────────
  const fold = (title, n, fill, open = false) => {
    if (!n) return;
    const d = el("details", "vx-fold"); d.open = open;
    d.append(el("summary", null, `${title} (${n})`));
    fill(d);
    s.append(d);
  };
  const violated = (v.verdicts || []).filter((x) => x.assessable && x.compliance < 0.6);
  const met = (v.verdicts || []).filter((x) => x.assessable && x.compliance >= 0.6);
  const skipped = (v.verdicts || []).filter((x) => !x.assessable && x.category !== "site");
  fold("Rules not met", violated.length, (d) => { for (const x of violated) d.append(vastuRow(x, x.verdict === "prohibited" ? "major" : "moderate")); }, true);
  fold("Rules met", met.length, (d) => { for (const x of met) d.append(vastuRow(x, "info")); });
  fold("Not measured on this plan", skipped.length, (d) => {
    d.append(el("p", "vx2__note", "Left out of the score rather than guessed at."));
    for (const x of skipped) {
      const r = el("div", "find"); r.dataset.sev = "info";
      r.append(el("i", "find__s"), el("span", "find__t", x.title), el("span", "find__c", x.reason_not_assessable || `Superseded by ${x.defeated_by}`));
      d.append(r);
    }
  });
  fold("How each room's reading was derived", reads.length, (d) => {
    if (v.graph_note) d.append(el("p", "vx2__note", v.graph_note));
    for (const p of reads) {
      const box = el("div", "deriv");
      box.dataset.v = p.verdict;
      const h = el("div", "deriv__h");
      h.append(el("b", null, p.room), el("span", "deriv__dir", `${p.direction}, ${p.quarter}`),
        el("span", "deriv__sc", p.verdict === "undetermined" ? "—" : p.score.toFixed(2)),
        el("span", "deriv__tag", p.derived ? "derived" : "cited"));
      box.append(h);
      if (p.derivation) box.append(chainRow("supports", p.derivation));
      if (p.objection) box.append(chainRow("objects", p.objection));
      if (!p.derivation && !p.objection) box.append(el("p", "deriv__x", p.explanation));
      if (p.agrees_with_text === false) {
        box.append(el("p", "deriv__warn", "The derivation disagrees with a cited text. The text governs the score; the disagreement is shown rather than hidden."));
      }
      if (p.better_directions?.length) {
        box.append(el("p", "deriv__alt", "Better: " + p.better_directions.map((b) => `${b.direction} (${b.score.toFixed(2)})`).join(", ")));
      }
      if (p.citations?.length) box.append(el("p", "deriv__cite", p.citations.join("; ")));
      d.append(box);
    }
  });
}

function chainRow(kind, chain) {
  const row = el("div", "chain"); row.dataset.k = kind;
  // Render "A -[edge]-> B" as alternating node / edge tokens so the reasoning
  // reads as a path rather than a string.
  const parts = chain.split(/\s*-\[|\]->\s*/);
  parts.forEach((tok, i) => {
    if (!tok) return;
    row.append(el("span", i % 2 ? "chain__e" : "chain__n", tok));
  });
  return row;
}

function vastuRow(x, sev) {
  const d = el("div", "find"); d.dataset.sev = sev;
  d.append(el("i", "find__s"), el("span", "find__t", x.title));
  d.append(el("span", "find__m",
    `${x.observed_direction ? x.observed_direction + " · " : ""}${x.verdict} · weight ${x.effective_weight.toFixed(2)} · modern validity ${x.modern_validity.toFixed(2)}`));
  if (x.remedy && sev !== "info") d.append(el("span", "find__r", x.remedy));
  d.append(el("span", "find__c", `${x.citation} — ${x.school}`));
  return d;
}

async function rescore(w) {
  const n = (S.vxSeq = (S.vxSeq || 0) + 1), id = S.activeId;
  try {
    const r = await fetch(`${API}/plans/vastu`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_id: id, tradition_weight: w, ...(cur().parent ? { compare_to: cur().parent } : {}) }),
    });
    if (!r.ok) throw new Error(String(r.status));
    const v = await r.json();
    if (n !== S.vxSeq || id !== S.activeId) return;     // a later stance, or another scheme, came first
    S.plans[id].vastu = v;
  } catch (err) {
    if (n !== S.vxSeq) return;
    toast(`Could not re-score at that stance: ${err.message}`);
  }
  // Redrawn where the reader was: the same scroll, the stance still in hand.
  if (S.view === "vastu") {
    const top = pane("vastu")?.querySelector(".pane__scroll")?.scrollTop || 0;
    renderVastu();
    const sc = pane("vastu").querySelector(".pane__scroll");
    if (sc) sc.scrollTop = top;
    pane("vastu").querySelector('.vx2__seg [aria-checked="true"]')?.focus({ preventScroll: true });
  }
  renderVerdict();
}

/* ── cost ──────────────────────────────────────────────────────────── */

function renderCost() {
  const s = scrollPane("cost");
  const c = cur().cost;
  if (!c) { s.append(el("p", "empty-note", "No estimate for this scheme.")); return; }

  const stats = el("div", "stat-row");
  for (const [pig, k, val, sub] of [
    ["ochre", "Estimate", inr(c.total), `${inr(c.rate_per_m2)} per m²`],
    ["indigo", "80% range", `${inr(c.p10)}`, `to ${inr(c.p90)}${c.total ? ` · ±${Math.round((c.p90 - c.p10) / 2 / c.total * 100)}%` : ""}`],
    ["chalk", "Programme", `${c.duration_months} mo`, c.expected_delay_weeks > 0.5 ? `plan for about ${Math.round(c.expected_delay_weeks)} weeks of slip` : "no material slip expected"],
    ["hingula", "Line items", `${c.line_items.length}`, `${c.finish_tier} spec · ${c.region}`],
  ]) {
    const d = el("dl", "stat"); d.dataset.pig = pig;
    d.append(el("dt", null, k), el("dd", null, val), el("small", null, sub)); stats.append(d);
  }
  s.append(stats);
  s.append(el("p", "lede", c.summary || ""));

  s.append(el("h3", "sec", "By work package"));
  const max = Math.max(...Object.values(c.by_trade || { x: 1 }));
  for (const [trade, amt] of Object.entries(c.by_trade || {})) {
    const line = el("div", "bar-line");
    line.append(el("span", "bar-line__l", cap(trade)));
    const t = el("div", "bar-line__t"); const i = el("i"); t.append(i);
    line.append(t, el("span", "bar-line__v", inr(amt)));
    s.append(line);
    requestAnimationFrame(() => { i.style.transform = `scaleX(${amt / max})`; });
  }

  s.append(el("h3", "sec", "Build-up"));
  const bt = el("table", "led");
  const bb = el("tbody");
  for (const [k, v] of [
    ["Works subtotal", c.works_subtotal], ["Overhead and profit", c.overhead_profit],
    ["Contingency", c.contingency], ["Professional fees", c.professional_fees], ["Tax", c.tax],
  ]) {
    const tr = el("tr"); tr.append(el("td", null, k), el("td", "n", inr(v))); bb.append(tr);
  }
  bt.append(bb);
  const tf = el("tfoot"); const tr = el("tr");
  tr.append(el("td", null, "Total"), el("td", "n", inr(c.total))); tf.append(tr); bt.append(tf);
  s.append(bt);

  s.append(el("h3", "sec", `Bill of quantities (${c.line_items.length})`));
  const t = el("table", "led");
  t.innerHTML = "<thead><tr><th>Code</th><th>Description</th><th>Unit</th><th class='n'>Qty</th><th class='n'>Rate</th><th class='n'>Amount</th></tr></thead>";
  const tb = el("tbody");
  for (const it of [...c.line_items].sort((a, b) => b.amount - a.amount)) {
    const r = el("tr"); r.title = it.basis || "";
    r.append(el("td", null, it.code), el("td", null, it.description), el("td", null, it.unit),
      el("td", "n", it.quantity.toLocaleString("en-IN", { maximumFractionDigits: 1 })),
      el("td", "n", Math.round(it.rate).toLocaleString("en-IN")),
      el("td", "n", Math.round(it.amount).toLocaleString("en-IN")));
    tb.append(r);
  }
  t.append(tb); s.append(t);

  s.append(el("h3", "sec", "Cash flow"));
  const cf = el("table", "led");
  cf.innerHTML = "<thead><tr><th>Month</th><th class='n'>Outflow</th><th class='n'>Cumulative</th><th class='n'>Complete</th></tr></thead>";
  const cb = el("tbody");
  for (const p of c.cash_flow || []) {
    const r = el("tr");
    r.append(el("td", null, p.label), el("td", "n", inr(p.outflow)),
      el("td", "n", inr(p.cumulative)), el("td", "n", `${p.percent_complete}%`));
    cb.append(r);
  }
  cf.append(cb); s.append(cf);

  s.append(el("h3", "sec", `Risk register (${(c.risks || []).length})`));
  for (const r of c.risks || []) {
    const d = el("div", "find"); d.dataset.sev = r.likelihood > 0.6 ? "major" : "moderate";
    d.append(el("i", "find__s"), el("span", "find__t", r.name),
      el("span", "find__m", `${Math.round(r.likelihood * 100)}% likely · +${r.cost_impact_percent}% cost · +${r.schedule_impact_weeks} weeks`),
      el("span", "find__r", r.mitigation));
    s.append(d);
  }

  s.append(el("h3", "sec", "Assumptions"));
  const ul = el("ul");
  ul.style.cssText = "margin:0;padding-left:18px;color:var(--chalk-3);font-size:12.5px;line-height:1.85";
  for (const a of c.assumptions || []) ul.append(el("li", null, a));
  s.append(ul);
}

/* ── interior ──────────────────────────────────────────────────────── */

async function renderInterior() {
  const p = pane("interior");
  p.innerHTML = "";
  const id = S.activeId;
  const plan = cur().plan;
  const wrap = el("div", "inx");
  const side = el("aside", "inx__side");
  const stage = el("div", "inx__stage model-stage");
  const info = el("div", "inx__info");
  wrap.append(side, stage);
  p.append(wrap);

  // The interior scheme (furniture, finishes, costs), solved once per plan.
  let sc = cur().interior;
  const scP = sc ? Promise.resolve(sc) : fetch(`${API}/plans/${id}/interior`, { method: "POST" })
    .then((r) => (r.ok ? r.json() : null)).then((x) => { if (x) S.plans[id].interior = x; return x; }).catch(() => null);

  // Rooms, floor by floor.
  const rooms = (plan?.levels || []).flatMap((lv) => lv.rooms
    .filter((r) => !["corridor", "staircase", "shaft", "lobby"].includes(r.type))
    .map((r) => ({ r, lv: lv.index })));
  side.append(el("h3", "inx__h", "Rooms"));
  const list = el("ol", "inx__rooms");
  side.append(list);

  const cap = el("p", "model-cap", "Loading the interiors…");
  stage.append(cap, info);
  const { Viewer3D } = await import("./viewer3d.js?v=p17");
  if (S.view !== "interior" || S.activeId !== id) return;
  S.viewer?.dispose();
  const viewer = (S.viewer = new Viewer3D(stage));
  const pal = (S.palette ||= {});
  // The model without the pieces that have real ones; those, the fans, the
  // cushions and the paintings are stood in afterwards.
  let furn = null, furnP = null;
  const furnish = async () => {
    try {
      furnP = fetch(`${API}/plans/${id}/furnishings`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
      furn = await furnP;
      await viewer.furnish(furn);
    } catch { /* the model still stands without them */ }
  };
  const url = () => {
    const q = new URLSearchParams({ real: "1" });
    if (pal.id) q.set("palette", pal.id);
    if (pal.text) q.set("colours", pal.text);
    if (pal.design) q.set("design", pal.design);
    const rev = S.plans[id]?.interior?.rev;
    if (rev) q.set("v", rev);
    return `${API}/plans/${id}/model.glb${q.size ? `?${q}` : ""}`;
  };
  try { await viewer.load(url()); } catch (e) { cap.textContent = `The model could not be shown (${e.message}).`; return; }
  cap.textContent = "Pick a room to stand in it and change it";
  furnish();
  const vr = await Viewer3D.vrSupported();

  // Interior palettes, cycled in place.
  let schemes = [];
  fetch(`${API}/plans/${id}/palettes`).then((r) => r.json()).then((d) => { schemes = d.schemes || []; drawStyle(); }).catch(() => {});
  const style = el("div", "inx__style");
  side.append(style);
  const drawStyle = () => {
    if (!schemes.length) return;
    const i = Math.max(0, schemes.findIndex((s) => s.id === pal.id));
    const s = schemes[i];
    style.innerHTML = "";
    style.append(el("span", "inx__k", "Interior style"));
    const row = el("div", "inx__style-row");
    const name = el("b", null, s.name);
    const sw = el("span", "inx__sw");
    for (const hex of Object.values(s.interior || {})) { const c = el("i"); c.style.background = hex; sw.append(c); }
    const nav = el("div", "inx__nav");
    for (const [t, step] of [["prev", -1], ["next", 1]]) {
      const b = el("button", "ghost-btn ghost-btn--ico"); b.type = "button"; b.append(icon(t));
      b.setAttribute("aria-label", step < 0 ? "Previous style" : "Next style");
      b.addEventListener("click", async () => {
        pal.id = schemes[(i + step + schemes.length) % schemes.length].id;
        drawStyle();
        await viewer.load(url(), { keepView: true });
        await furnish();
      });
      nav.append(b);
    }
    row.append(name, nav);
    style.append(row, sw, el("p", "inx__story", s.story || ""));
  };

  // ── Rooms: pick one and you stand in it, with a small window to change it ──
  let current = null;
  const boxOf = (item) => {
    const xs = item.r.polygon.map((q) => q.x ?? q[0]), ys = item.r.polygon.map((q) => q.y ?? q[1]);
    return { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
  };
  const roomOf = (item) => (S.plans[id]?.interior)?.rooms?.find((x) => x.room_id === item.r.id);
  const ft = (m) => `${(m / 0.3048).toFixed(1).replace(/\.0$/, "")} ft`;
  const mm = (m) => `${(+m).toFixed(2)} m`;

  // Stand facing the room's main piece - the bed, the sofa, the table - a few steps back from it.
  const stand = (item, box) => {
    const fur = roomOf(item)?.furniture || [];
    const anchor = fur.find((f) => /^bed/.test(f.item_id)) || fur.find((f) => /^(sofa|sectional|diwan)/.test(f.item_id))
      || fur.find((f) => /^(dining|desk|study_desk|counter|mandir)/.test(f.item_id))
      || [...fur].sort((a, b) => b.width * b.depth - a.width * a.depth)[0];
    let pose = {};
    if (anchor) {
      const r = (anchor.rotation * Math.PI) / 180, fx = -Math.sin(r), fy = Math.cos(r);
      const back = Math.min(3.2, Math.max(1.6, ((Math.abs(fy) > 0.5 ? box.y1 - box.y0 : box.x1 - box.x0) - anchor.depth) * 0.85));
      const m = 0.35;
      pose = {
        from: { x: Math.min(box.x1 - m, Math.max(box.x0 + m, anchor.x + fx * (anchor.depth / 2 + back))),
                y: Math.min(box.y1 - m, Math.max(box.y0 + m, anchor.y + fy * (anchor.depth / 2 + back))) },
        look: { x: anchor.x, y: anchor.y },
      };
    }
    viewer.walkInto(box, item.lv, pose);
  };

  // The bar under the view: the room you are in, the rooms either side, and how you see it.
  const walkBar = el("div", "inx__walkbar");
  walkBar.hidden = true;
  stage.append(walkBar);
  let walkIdx = -1, fromAbove = false;
  const drawBar = (item) => {
    walkBar.innerHTML = "";
    const prev = el("button", "ghost-btn ghost-btn--ico"); prev.type = "button"; prev.append(icon("prev"));
    prev.setAttribute("aria-label", "Previous room"); prev.addEventListener("click", () => stepRoom(-1));
    const next = el("button", "ghost-btn ghost-btn--ico"); next.type = "button"; next.append(icon("next"));
    next.setAttribute("aria-label", "Next room"); next.addEventListener("click", () => stepRoom(1));
    const name = el("b", null, item.r.name || item.r.type);
    const view = el("button", "ghost-btn", fromAbove ? "Stand inside" : "See from above"); view.type = "button";
    view.addEventListener("click", () => {
      fromAbove = !fromAbove;
      if (fromAbove) { viewer.leaveWalk(); viewer.focusRoom(current.box, item.lv); cap.textContent = "Drag to turn the room · scroll to zoom"; }
      else { stand(item, current.box); cap.textContent = WALK_HINT; }
      drawBar(item);
    });
    const out = el("button", "ghost-btn", "Whole house"); out.type = "button";
    out.addEventListener("click", () => leave());
    walkBar.append(prev, name, next, view);
    if (wrap.classList.contains("ed-hidden")) {
      const ed = el("button", "ghost-btn", "Edit room"); ed.type = "button";
      ed.addEventListener("click", () => { wrap.classList.remove("ed-hidden"); drawBar(item); });
      walkBar.append(ed);
    }
    if (vr) {
      const vrB = el("button", "ghost-btn", "VR"); vrB.type = "button";
      vrB.title = "In a VR headset: trigger to step where you point, grip for the next room";
      vrB.addEventListener("click", async () => {
        if (fromAbove) { fromAbove = false; stand(item, current.box); drawBar(item); }
        try { await viewer.enterVR({ onNextRoom: () => stepRoom(1) }); } catch (e) { toast(`VR could not start (${e.message}).`); }
      });
      walkBar.append(vrB);
    }
    walkBar.append(out);
    walkBar.hidden = false;
  };
  const WALK_HINT = "Drag to look round · double-click the floor to walk · WASD to move";

  const enter = async (item) => {
    walkIdx = rooms.indexOf(item);
    list.querySelectorAll("li").forEach((x) => x.classList.toggle("is-on", x === lis.get(item)));
    lis.get(item)?.scrollIntoView({ block: "nearest", inline: "nearest" });
    await scP;
    const box = boxOf(item);
    current = { box, lv: item.lv, item };
    fromAbove = false;
    stand(item, box);
    viewer.setRoomLight(roomOf(item)?.finishes?.kelvin);
    drawBar(item);
    cap.textContent = WALK_HINT;
    S.exitRoom = () => leave();
    editor(item);
  };
  const leave = () => {
    S.exitRoom = null;
    current = null;
    wrap.querySelector(".inx__ed")?.remove();
    wrap.classList.remove("has-ed", "ed-hidden");
    viewer.mark(null);
    viewer.interact = null;
    list.querySelectorAll("li").forEach((x) => x.classList.remove("is-on"));
    walkBar.hidden = true;
    viewer.leaveWalk();
    viewer.setMode("exterior");
    cap.textContent = "Pick a room to stand in it and change it";
  };
  const stepRoom = (k) => {
    if (!rooms.length) return;
    enter(rooms[((walkIdx < 0 ? 0 : walkIdx) + k + rooms.length) % rooms.length]);
  };

  // ── The edit window ─────────────────────────────────────────────────
  // One room at a time: its look, its pieces (what each is, its standard size,
  // its colour, where it stands), what to add, its walls and floor, and the
  // room from above. Every change is kept as it is made and the view follows.
  let catCache = new Map();
  const editor = async (item) => {
    wrap.querySelector(".inx__ed")?.remove();
    const rs = roomOf(item);
    if (!rs) return;
    const win = el("section", "inx__ed");
    win.setAttribute("aria-label", `Change the ${item.r.name || item.r.type}`);
    wrap.append(win);
    wrap.classList.add("has-ed");
    wrap.classList.remove("ed-hidden");
    const head = el("header", "inx__ed-head");
    const title = el("div", "inx__ed-title");
    const where = item.lv === 0 ? "ground floor" : `level ${item.lv}`;
    title.append(el("h3", null, item.r.name || item.r.type),
      el("p", null, `${(+item.r.area || 0).toFixed(1)} m², ${where}${rs.direction ? `, ${rs.direction} side` : ""}`));
    const status = el("span", "inx__ed-status", rs.edited ? "Your changes are kept" : "Changes save as you go");
    status.setAttribute("aria-live", "polite");
    const fold = el("button", "inx__ed-fold"); fold.type = "button";
    fold.setAttribute("aria-label", "Close the edit panel");
    fold.addEventListener("click", () => {
      wrap.classList.add("ed-hidden");
      if (current) drawBar(current.item);
    });
    head.append(title, fold);
    win.append(head);
    const loading = el("p", "inx__ed-empty", "Loading what this room can hold…");
    win.append(loading);

    let cat = catCache.get(item.r.type);
    if (!cat) {
      cat = await fetch(`${API}/plans/${id}/interior/catalogue?room_id=${encodeURIComponent(item.r.id)}`)
        .then((r) => (r.ok ? r.json() : null)).catch(() => null);
      if (cat) catCache.set(item.r.type, cat);
    }
    if (!win.isConnected) return;
    loading.remove();
    if (!cat) { win.append(el("p", "inx__ed-empty", "The furniture list could not be loaded. Pick the room again to retry.")); return; }

    const byId = new Map(), groupOf = new Map();
    for (const g of cat.groups) for (const it of g.items) { byId.set(it.id, it); groupOf.set(it.id, g.name); }
    const swatchHex = { wood: "#8a6a4c", fabric: "#b9ab90", metal: "#b08a3e", none: "#d9d6cf" };
    const draft = {
      items: rs.furniture.map((f) => ({ uid: f.uid, item_id: f.item_id, x: f.x, y: f.y, rotation: f.rotation || 0,
        colour: f.colour || null, art: f.art || null, w: f.width, d: f.depth })),
      finishes: { ...(rs.finishes || {}) },
    };
    let sel = draft.items[0]?.uid || null;
    const bx = current.box;
    const snap = (v) => Math.round(v / 0.05) * 0.05;
    const size = (d) => { const it = byId.get(d.item_id) || { width: 0.5, depth: 0.5 }; return [d.w || it.width, d.d || it.depth]; };
    const dims = (d) => { const [w, dd] = size(d); return Math.round(d.rotation / 90) % 2 === 1 ? [dd, w] : [w, dd]; };
    const keepIn = (d) => {
      const [w, h] = dims(d);
      d.x = Math.min(Math.max(d.x, bx.x0 + w / 2), Math.max(bx.x0 + w / 2, bx.x1 - w / 2));
      d.y = Math.min(Math.max(d.y, bx.y0 + h / 2), Math.max(bx.y0 + h / 2, bx.y1 - h / 2));
    };
    const ftin = (m) => { const t = Math.round(m / 0.0254); return `${Math.floor(t / 12)} ft ${t % 12} in`; };
    const sizeName = (d) => {
      const [w, dd] = size(d);
      const z = (byId.get(d.item_id)?.sizes || []).find((x) => Math.abs(x.w - w) < 0.1 && Math.abs(x.d - dd) < 0.1);
      return z ? `${z.name}, ${ft(w)} × ${ft(dd)}` : `${ft(w)} × ${ft(dd)}`;
    };

    // Keep each change as it is made: a short pause, then the room is saved and the view redrawn.
    let timer = null, saving = false, again = false;
    const commit = () => {
      status.textContent = "Saving…";
      clearTimeout(timer);
      timer = setTimeout(push, 650);
    };
    const push = async () => {
      if (saving) { again = true; return; }
      saving = true;
      try {
        const res = await fetch(`${API}/plans/${id}/interior/rooms/${encodeURIComponent(item.r.id)}`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft),
        });
        if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
        const out = await res.json();
        apply(out);
        for (const n of out.notes || []) toast(n);
        status.textContent = "Updating the view…";
        await viewer.load(url(), { keepView: true });
        await furnish();
        if (fromAbove && current) viewer.focusRoom(current.box, item.lv, true);
        markSel();
        viewer.setRoomLight(draft.finishes.kelvin);
        status.textContent = "Saved";
      } catch (e) {
        status.textContent = "Not saved";
        toast(`The room could not be saved (${e.message}). Try the change again.`);
      } finally {
        saving = false;
        if (again) { again = false; push(); }
      }
    };
    const apply = (out) => {
      const sc2 = S.plans[id].interior;
      if (sc2) {
        sc2.rooms = sc2.rooms.map((x) => (x.room_id === out.room.room_id ? out.room : x));
        sc2.rev = out.rev;
      }
    };
    const changed = () => { drawPlan(); drawTab(); markSel?.(); commit(); };

    // Tabs.
    const tabs = el("div", "inx__ed-tabs"); tabs.setAttribute("role", "tablist");
    const body = el("div", "inx__ed-body");
    const TABS = [["looks", "Looks"], ["pieces", "Furniture"], ["add", "Add"], ["room", "Walls & floor"], ["plan", "Layout"]];
    let tab = "looks";
    for (const [k, label] of TABS) {
      const b = el("button", null, label); b.type = "button"; b.setAttribute("role", "tab"); b.dataset.tab = k;
      b.addEventListener("click", () => { tab = k; drawTab(); });
      tabs.append(b);
    }
    win.append(tabs, body);
    const foot = el("footer", "inx__ed-foot");
    const reset = el("button", "link", "Undo all changes"); reset.type = "button";
    reset.title = "Go back to the designer's layout for this room";
    reset.addEventListener("click", async () => {
      if (!confirm("Undo every change to this room and go back to the designer's layout?")) return;
      status.textContent = "Resetting…";
      try {
        const res = await fetch(`${API}/plans/${id}/interior/rooms/${encodeURIComponent(item.r.id)}`, { method: "DELETE" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        apply(await res.json());
        await viewer.load(url(), { keepView: true });
        await furnish();
        editor(item);
      } catch (e) { status.textContent = "Not reset"; toast(`The room could not be reset (${e.message}).`); }
    });
    foot.append(status, reset);
    win.append(foot);

    // Small parts.
    const label = (t) => el("p", "inx__lbl", t);
    const swatches = (list, current, pick, name, { custom = true } = {}) => {
      const row = el("div", "inx__swatches");
      row.setAttribute("role", "radiogroup"); row.setAttribute("aria-label", name);
      for (const c of list) {
        const on = current && (current === c.hex || current === c.id);
        const b = el("button", `inx__swatch${on ? " is-on" : ""}`); b.type = "button";
        b.style.background = c.hex; b.title = c.name; b.setAttribute("aria-label", c.name);
        b.setAttribute("role", "radio"); b.setAttribute("aria-checked", String(!!on));
        b.addEventListener("click", () => { pick(c.hex); changed(); });
        row.append(b);
      }
      if (custom) {
        // Any colour at all, for a client who has a shade in mind.
        const own = el("label", "inx__swatch inx__swatch--own"); own.title = "Any colour";
        const inp = el("input"); inp.type = "color"; inp.value = /^#[0-9a-f]{6}$/i.test(current || "") ? current : "#c8b89a";
        inp.setAttribute("aria-label", `${name}: any colour`);
        inp.addEventListener("change", () => { pick(inp.value); changed(); });
        own.append(inp);
        row.append(own);
      }
      return row;
    };
    const artPicker = (current, pick, allowNone = false) => {
      const grid = el("div", "inx__art");
      for (const a of [...(allowNone ? [{ id: "none", title: "No painting" }] : []), ...(cat.art || [])]) {
        const on = current === a.id;
        const b = el("button", `inx__art-btn${on ? " is-on" : ""}`); b.type = "button";
        b.title = a.artist ? `${a.title}, ${a.artist}` : a.title;
        b.setAttribute("aria-label", b.title); b.setAttribute("aria-pressed", String(on));
        if (a.id === "none") b.append(el("span", null, "None"));
        else { const im = el("img"); im.src = `assets/art/${a.id}.jpg`; im.alt = ""; im.loading = "lazy"; b.append(im); }
        b.addEventListener("click", () => { pick(a.id); changed(); });
        grid.append(b);
      }
      return grid;
    };
    // Where a new piece goes: a wall piece on a wall (a television over its unit),
    // a light over the table, a piece that stands against a wall along the
    // first free one, anything else in the middle of the room.
    const lowSolid = (x) => { const it = byId.get(x.item_id); return it && !it.mount && (it.height || 0) > 0.05; };
    const clash = (c) => {
      const [w, h] = dims(c);
      return draft.items.some((x) => {
        if (!lowSolid(x)) return false;
        const [xw, xh] = dims(x);
        return Math.abs(x.x - c.x) < (w + xw) / 2 - 0.02 && Math.abs(x.y - c.y) < (h + xh) / 2 - 0.02;
      });
    };
    const placeNew = (o) => {
      const cx = (bx.x0 + bx.x1) / 2, cy = (bx.y0 + bx.y1) / 2;
      const c = { uid: newUid(), item_id: o.id, x: cx, y: cy, rotation: 0, colour: null, w: null, d: null, art: null };
      if (o.mount === "ceiling") {
        const t = draft.items.find((x) => /^dining/.test(x.item_id));
        if (t) { c.x = t.x; c.y = t.y; }
        keepIn(c);
        return c;
      }
      const unit = o.id === "tv_wall" && draft.items.find((x) => /^(tv_unit|family_tv)/.test(x.item_id));
      if (unit) {
        const [, ud] = size(unit), r = (unit.rotation * Math.PI) / 180, ly = -ud / 2 + o.depth / 2;
        c.rotation = unit.rotation; c.x = unit.x - ly * Math.sin(r); c.y = unit.y + ly * Math.cos(r);
        return c;
      }
      if (o.mount === "wall" || ["against_wall", "corner", "counter_run"].includes(o.placement)) {
        const d = o.depth, w = o.width;
        const walls = [[0, (t) => [bx.x0 + w / 2 + t * (bx.x1 - bx.x0 - w), bx.y0 + d / 2]],
          [180, (t) => [bx.x0 + w / 2 + t * (bx.x1 - bx.x0 - w), bx.y1 - d / 2]],
          [270, (t) => [bx.x0 + d / 2, bx.y0 + w / 2 + t * (bx.y1 - bx.y0 - w)]],
          [90, (t) => [bx.x1 - d / 2, bx.y0 + w / 2 + t * (bx.y1 - bx.y0 - w)]]];
        const along = o.placement === "corner" ? [0, 1, 0.5] : [0.5, 0.2, 0.8, 0, 1];
        for (const [rot, at] of walls) {
          for (const t of along) {
            [c.x, c.y] = at(t); c.rotation = rot; keepIn(c);
            if (o.mount === "wall" || !clash(c)) return c;
          }
        }
        [c.x, c.y] = walls[0][1](0.5); c.rotation = 0;
        keepIn(c);
        return c;
      }
      // Free-standing: the open spot nearest the middle, on a 25 cm grid.
      keepIn(c);
      if (clash(c) && (byId.get(o.id)?.height || o.height || 0) > 0.05) {
        const spots = [];
        for (let x = bx.x0 + 0.3; x <= bx.x1 - 0.3; x += 0.25) for (let y = bx.y0 + 0.3; y <= bx.y1 - 0.3; y += 0.25) spots.push([x, y]);
        spots.sort((a, b) => Math.hypot(a[0] - cx, a[1] - cy) - Math.hypot(b[0] - cx, b[1] - cy));
        for (const [x, y] of spots) { c.x = x; c.y = y; keepIn(c); if (!clash(c)) return c; }
        c.x = cx; c.y = cy; keepIn(c);
      }
      return c;
    };
    const turn = (d) => { d.rotation = (d.rotation + 90) % 360; keepIn(d); changed(); };
    const remove = (d) => { draft.items = draft.items.filter((x) => x !== d); sel = draft.items[0]?.uid || null; changed(); };
    const nudge = (d, dx, dy) => { d.x = snap(d.x + dx); d.y = snap(d.y + dy); keepIn(d); changed(); };
    // Left, right, away and closer as the view looks, kept to the room's own axes.
    const nudgeView = (d, k) => {
      const { fwd, right } = viewer.viewAxes();
      const v = { away: fwd, closer: [-fwd[0], -fwd[1]], right, left: [-right[0], -right[1]] }[k];
      const [dx, dy] = Math.abs(v[0]) > Math.abs(v[1]) ? [Math.sign(v[0]) * 0.1, 0] : [0, Math.sign(v[1]) * 0.1];
      nudge(d, dx, dy);
    };
    const snapTo = (d, w) => {
      if (w === "C") { d.x = (bx.x0 + bx.x1) / 2; d.y = (bx.y0 + bx.y1) / 2; keepIn(d); changed(); return; }
      d.rotation = { S: 0, N: 180, E: 90, W: 270 }[w];
      const [, dd] = size(d);
      if (w === "S") d.y = bx.y0 + dd / 2;
      if (w === "N") d.y = bx.y1 - dd / 2;
      if (w === "W") d.x = bx.x0 + dd / 2;
      if (w === "E") d.x = bx.x1 - dd / 2;
      keepIn(d); changed();
    };
    const newUid = () => `n${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`;

    // The room from above, for the Layout tab.
    const NS = "http://www.w3.org/2000/svg";
    const pad = 0.25;
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "inx__plan");
    svg.setAttribute("viewBox", `${bx.x0 - pad} ${-bx.y1 - pad} ${bx.x1 - bx.x0 + 2 * pad} ${bx.y1 - bx.y0 + 2 * pad}`);
    svg.setAttribute("role", "application");
    svg.setAttribute("aria-label", "The room from above: drag a piece to move it, R turns it, Delete removes it, arrow keys nudge it");
    svg.tabIndex = 0;
    const ptOf = (ev) => { const m = svg.getScreenCTM().inverse(); const q = new DOMPoint(ev.clientX, ev.clientY).matrixTransform(m); return { x: q.x, y: -q.y }; };
    const drawPlan = () => {
      svg.innerHTML = "";
      const room = document.createElementNS(NS, "polygon");
      room.setAttribute("points", item.r.polygon.map((q) => `${q.x ?? q[0]},${-(q.y ?? q[1])}`).join(" "));
      room.setAttribute("class", "inx__plan-room");
      if (draft.finishes.floor) room.style.fill = (cat.floors.find((f) => f.id === draft.finishes.floor) || {}).hex || "";
      svg.append(room);
      const order = [...draft.items].sort((a, b) => (byId.get(a.item_id)?.height || 0) - (byId.get(b.item_id)?.height || 0));
      const fs = Math.max(0.12, Math.min(0.2, (bx.x1 - bx.x0) / 26));
      for (const d of order) {
        const it = byId.get(d.item_id);
        if (!it) continue;
        const [w, dd] = size(d);
        const g = document.createElementNS(NS, "g");
        g.setAttribute("class", `inx__piece${d.uid === sel ? " is-sel" : ""}`);
        g.setAttribute("transform", `translate(${d.x} ${-d.y}) rotate(${-d.rotation})`);
        const r = document.createElementNS(NS, "rect");
        r.setAttribute("x", -w / 2); r.setAttribute("y", -dd / 2); r.setAttribute("width", w); r.setAttribute("height", dd);
        r.style.fill = d.colour || swatchHex[it.colour_group] || "#8a6a4c";
        if ((it.height || 0) < 0.05) r.style.opacity = "0.55";
        const front = document.createElementNS(NS, "line");
        front.setAttribute("x1", -w / 2); front.setAttribute("x2", w / 2); front.setAttribute("y1", -dd / 2); front.setAttribute("y2", -dd / 2);
        front.setAttribute("class", "inx__front");
        const t = document.createElementNS(NS, "text");
        t.textContent = it.name.length > 18 ? `${it.name.slice(0, 16)}…` : it.name;
        t.setAttribute("font-size", fs); t.setAttribute("transform", `rotate(${d.rotation})`);
        t.setAttribute("text-anchor", "middle"); t.setAttribute("dominant-baseline", "middle");
        const tip = document.createElementNS(NS, "title"); tip.textContent = `${it.name}, ${sizeName(d)}`;
        g.append(r, front, t, tip);
        g.addEventListener("pointerdown", (ev) => {
          ev.preventDefault();
          sel = d.uid; drawPlan();
          const start = ptOf(ev), ox = d.x, oy = d.y;
          let moved = false;
          svg.setPointerCapture(ev.pointerId);
          const move = (e2) => {
            const q = ptOf(e2);
            d.x = snap(ox + q.x - start.x); d.y = snap(oy + q.y - start.y); keepIn(d); moved = true;
            svg.querySelector(".inx__piece.is-sel")?.setAttribute("transform", `translate(${d.x} ${-d.y}) rotate(${-d.rotation})`);
          };
          const up = () => {
            svg.removeEventListener("pointermove", move); svg.removeEventListener("pointerup", up); svg.removeEventListener("pointercancel", up);
            if (moved) changed(); else drawTab();
          };
          svg.addEventListener("pointermove", move); svg.addEventListener("pointerup", up); svg.addEventListener("pointercancel", up);
        });
        svg.append(g);
      }
    };
    svg.addEventListener("keydown", (ev) => {
      const d = draft.items.find((x) => x.uid === sel);
      if (!d) return;
      const st = ev.shiftKey ? 0.25 : 0.05;
      const k = { ArrowLeft: [-st, 0], ArrowRight: [st, 0], ArrowUp: [0, st], ArrowDown: [0, -st] }[ev.key];
      if (k) { ev.preventDefault(); nudge(d, k[0], k[1]); return; }
      if (ev.key === "r" || ev.key === "R") { ev.preventDefault(); turn(d); }
      if (ev.key === "Delete" || ev.key === "Backspace") { ev.preventDefault(); remove(d); }
    });

    // What a piece is: its kind, a standard size, its colour, and where it stands.
    const pieceDetail = (d) => {
      const it = byId.get(d.item_id);
      const box = el("div", "inx__detail");
      const top = el("div", "inx__detail-top");
      const [sw0, sd0] = size(d);
      top.append(el("b", null, it.name), el("span", null, sizeName(d)),
        el("span", "inx__dims", `${sw0.toFixed(2)} m × ${sd0.toFixed(2)} m  /  ${ftin(sw0)} × ${ftin(sd0)}`));
      box.append(top);
      const kinds = cat.groups.find((g) => g.name === groupOf.get(d.item_id))?.items || [];
      if (kinds.length > 1) {
        const lab = el("label", "inx__field"); lab.append(label("Type"));
        const pick = el("select");
        for (const o of kinds) { const op = el("option", null, o.name); op.value = o.id; op.selected = o.id === d.item_id; pick.append(op); }
        pick.addEventListener("change", () => {
          const was = byId.get(d.item_id)?.colour_group;
          d.item_id = pick.value; d.w = d.d = null;
          if (byId.get(d.item_id)?.colour_group !== was) d.colour = null;
          keepIn(d); changed();
        });
        lab.append(pick);
        box.append(lab);
      }
      if (it.sizes?.length) {
        box.append(label("Standard size"));
        const row = el("div", "inx__sizes");
        const [w, dd] = size(d);
        for (const z of it.sizes) {
          const on = Math.abs(z.w - w) < 0.1 && Math.abs(z.d - dd) < 0.1;
          const b = el("button", `inx__size${on ? " is-on" : ""}`); b.type = "button";
          b.setAttribute("aria-pressed", String(on));
          b.append(el("b", null, z.name), el("span", null, z.ft), el("small", null, z.m));
          b.addEventListener("click", () => { d.w = z.w; d.d = z.d; keepIn(d); changed(); });
          row.append(b);
        }
        box.append(row);
      } else {
        box.append(el("p", "inx__note", `${mm(it.width)} wide, ${mm(it.depth)} deep, ${mm(it.height)} high (${ft(it.width)} × ${ft(it.depth)})`));
      }
      if (d.item_id === "wall_art" && cat.art?.length) box.append(label("Painting"), artPicker(d.art, (a) => { d.art = a; }));
      if (cat.colours[it.colour_group]) {
        box.append(label(it.colour_group === "fabric" ? "Fabric colour" : it.colour_group === "metal" ? "Metal finish" : "Wood finish"));
        box.append(swatches(cat.colours[it.colour_group], d.colour, (h) => { d.colour = h; }, "Colour"));
      }
      box.append(label("Put it against"));
      const snaps = el("div", "inx__snaps");
      for (const [t, w] of [["Top wall", "N"], ["Bottom wall", "S"], ["Left wall", "W"], ["Right wall", "E"], ["Centre", "C"]]) {
        const b = el("button", "inx__chip", t); b.type = "button";
        b.title = w === "C" ? "Move it to the middle of the room" : `Back against the ${t.toLowerCase()} as the Layout tab shows it`;
        b.addEventListener("click", () => snapTo(d, w));
        snaps.append(b);
      }
      box.append(snaps);
      box.append(label("Move it 10 cm, as you are looking"));
      const acts = el("div", "inx__acts");
      const pad4 = el("div", "inx__nudge"); pad4.setAttribute("role", "group"); pad4.setAttribute("aria-label", "Move by 10 cm as seen in the view");
      for (const [t, k, a] of [["prev", "left", "Move left"], ["up", "away", "Move away from you"], ["down", "closer", "Move closer to you"], ["next", "right", "Move right"]]) {
        const b = el("button", "ghost-btn ghost-btn--ico"); b.type = "button"; b.append(icon(t)); b.setAttribute("aria-label", `${a} by 10 cm`);
        b.title = a;
        b.addEventListener("click", () => nudgeView(d, k));
        pad4.append(b);
      }
      const tb = el("button", "ghost-btn inx__act"); tb.type = "button"; tb.append(icon("turn"), document.createTextNode("Turn"));
      tb.addEventListener("click", () => turn(d));
      const db = el("button", "ghost-btn inx__act"); db.type = "button"; db.append(icon("copy"), document.createTextNode("Duplicate"));
      db.addEventListener("click", () => { const c = { ...d, uid: newUid(), x: d.x + 0.3, y: d.y - 0.3 }; keepIn(c); draft.items.push(c); sel = c.uid; changed(); });
      const rb = el("button", "ghost-btn inx__act inx__del"); rb.type = "button"; rb.append(icon("trash"), document.createTextNode("Remove"));
      rb.addEventListener("click", () => remove(d));
      acts.append(pad4, tb, db, rb);
      box.append(acts);
      return box;
    };

    let addQuery = "", addGroup = "All";
    const symbol = (w, d, hex) => {
      const NS2 = "http://www.w3.org/2000/svg", k = 30 / Math.max(w, d, 0.3);
      const sw = Math.max(3, w * k), sh = Math.max(3, d * k);
      const svgEl = document.createElementNS(NS2, "svg");
      svgEl.setAttribute("viewBox", "0 0 36 36"); svgEl.setAttribute("class", "inx__sym"); svgEl.setAttribute("aria-hidden", "true");
      const r = document.createElementNS(NS2, "rect");
      r.setAttribute("x", 18 - sw / 2); r.setAttribute("y", 18 - sh / 2); r.setAttribute("width", sw); r.setAttribute("height", sh);
      r.setAttribute("rx", 0.6); r.style.fill = hex;
      const f = document.createElementNS(NS2, "line");
      f.setAttribute("x1", 18 - sw / 2); f.setAttribute("x2", 18 + sw / 2); f.setAttribute("y1", 18 + sh / 2); f.setAttribute("y2", 18 + sh / 2);
      svgEl.append(r, f);
      return svgEl;
    };
    const addButton = (o) => {
      const std = `${ft(o.width)} × ${ft(o.depth)}${o.sizes?.length > 1 ? ` · ${o.sizes.length} sizes` : ""}`;
      const b = el("button", "inx__row"); b.type = "button";
      b.setAttribute("aria-label", `Add ${o.name}, ${std}`);
      const txt = el("span", "inx__row-txt");
      txt.append(el("b", null, o.name), el("small", null, std));
      const add = el("span", "inx__row-add"); add.append(icon("plus"));
      b.append(symbol(o.width, o.depth, swatchHex[o.colour_group] || "#8a6a4c"), txt, add);
      b.addEventListener("click", () => {
        const c = placeNew(o);
        draft.items.push(c); sel = c.uid; tab = "pieces";
        toast(`${o.name} added. Drag it in the view, or use Furniture to place it.`);
        changed();
      });
      return b;
    };
    const drawTab = () => {
      tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
      body.innerHTML = "";
      body.scrollTop = 0;
      if (tab === "looks") {
        body.append(el("p", "inx__note", "One click colours the whole room: walls, accent wall, floor, and the wood and fabric of every piece."));
        const grid = el("div", "inx__looks");
        for (const lk of cat.looks || []) {
          const on = draft.finishes.look === lk.id;
          const b = el("button", `inx__look${on ? " is-on" : ""}`); b.type = "button"; b.setAttribute("aria-pressed", String(on));
          const strip = el("span", "inx__look-strip");
          const floorHex = (cat.floors.find((f) => f.id === lk.floor) || {}).hex || "#999";
          for (const [hex, part] of [[lk.wall, "walls"], [lk.accent, "accent"], [lk.wood, "wood"], [lk.fabric, "fabric"], [floorHex, "floor"]]) {
            const c = el("i"); c.style.background = hex; c.title = part; strip.append(c);
          }
          b.append(strip, el("b", null, lk.name), el("small", null, lk.story));
          b.addEventListener("click", () => {
            draft.finishes = { ...draft.finishes, wall: lk.wall, accent: lk.accent, floor: lk.floor, look: lk.id };
            for (const d of draft.items) {
              const g = byId.get(d.item_id)?.colour_group;
              d.colour = g === "wood" ? lk.wood : g === "fabric" ? lk.fabric : g === "metal" ? lk.metal : null;
            }
            changed();
          });
          grid.append(b);
        }
        body.append(grid);
      } else if (tab === "pieces") {
        const d = draft.items.find((x) => x.uid === sel);
        if (d && byId.get(d.item_id)) body.append(pieceDetail(d));
        else body.append(el("p", "inx__ed-empty", draft.items.length ? "Pick a piece below to change it." : "This room is empty. Add a piece from the Add tab."));
        if (draft.items.length) {
          body.append(label(`In this room (${draft.items.length})`));
          const ul = el("ul", "inx__list");
          for (const x of draft.items) {
            const it = byId.get(x.item_id);
            if (!it) continue;
            const li2 = el("li"); const b = el("button", `inx__row${x.uid === sel ? " is-on" : ""}`); b.type = "button";
            const [xw, xd] = size(x);
            const txt = el("span", "inx__row-txt"); txt.append(el("b", null, it.name), el("small", null, sizeName(x)));
            b.append(symbol(xw, xd, x.colour || swatchHex[it.colour_group] || "#8a6a4c"), txt);
            b.addEventListener("click", () => { sel = x.uid; drawPlan(); drawTab(); });
            li2.append(b); ul.append(li2);
          }
          body.append(ul);
        }
      } else if (tab === "add") {
        const findWrap = el("label", "inx__find"); findWrap.append(icon("search"));
        const find = el("input", "inx__search"); find.type = "search"; find.placeholder = "Search furniture, appliances, decor";
        find.value = addQuery; find.setAttribute("aria-label", "Search what to add");
        findWrap.append(find);
        const chips = el("div", "inx__chips"); chips.setAttribute("role", "group"); chips.setAttribute("aria-label", "Show one kind");
        const total = cat.groups.reduce((n, g) => n + g.items.length, 0);
        for (const name of ["All", ...cat.groups.map((g) => g.name)]) {
          const on = addGroup === name;
          const n = name === "All" ? total : cat.groups.find((g) => g.name === name).items.length;
          const c = el("button", `inx__chip${on ? " is-on" : ""}`); c.type = "button"; c.setAttribute("aria-pressed", String(on));
          c.append(document.createTextNode(name), el("small", null, String(n)));
          c.addEventListener("click", () => { addGroup = name; drawTab(); });
          chips.append(c);
        }
        const results = el("div", "inx__results");
        body.append(findWrap, chips, results);
        const drawResults = () => {
          results.innerHTML = "";
          const q = addQuery.trim().toLowerCase();
          let shown = 0;
          for (const g of cat.groups) {
            if (addGroup !== "All" && g.name !== addGroup) continue;
            const items = g.items.filter((o) => !q || o.name.toLowerCase().includes(q) || g.name.toLowerCase().includes(q));
            if (!items.length) continue;
            const head = el("h4", "inx__grp"); head.append(document.createTextNode(g.name), el("small", null, String(items.length)));
            results.append(head);
            const list2 = el("div", "inx__rows");
            for (const o of items) { shown++; list2.append(addButton(o)); }
            results.append(list2);
          }
          if (!shown) results.append(el("p", "inx__ed-empty", `Nothing called “${addQuery}” fits this room. Try another word, or All.`));
        };
        find.addEventListener("input", () => { addQuery = find.value; drawResults(); });
        drawResults();
      } else if (tab === "room") {
        const fin = draft.finishes;
        const unlook = () => { delete fin.look; };
        body.append(label("Walls"), swatches(cat.paints, fin.wall, (h) => { fin.wall = h; unlook(); }, "Wall paint"));
        body.append(label("Accent wall"), swatches(cat.paints, fin.accent, (h) => { fin.accent = h; unlook(); }, "Accent wall paint"));
        // Each wall on its own: any colour at all, with its code to write down or type in.
        const lvl = (cur().plan?.levels || []).find((l) => l.index === item.lv);
        const pt = (q) => ({ x: q.x ?? q[0], y: q.y ?? q[1] });
        const cx = (bx.x0 + bx.x1) / 2, cy = (bx.y0 + bx.y1) / 2;
        const seen = {};
        const myWalls = (lvl?.walls || []).filter((w) => (w.rooms || []).includes(item.r.id)).map((w) => {
          const a2 = pt(w.start), b2 = pt(w.end), mx = (a2.x + b2.x) / 2 - cx, my = (a2.y + b2.y) / 2 - cy;
          const side = Math.abs(mx) > Math.abs(my) ? (mx > 0 ? "East" : "West") : (my > 0 ? "North" : "South");
          seen[side] = (seen[side] || 0) + 1;
          return { id: w.id, side, n: seen[side], len: Math.hypot(b2.x - a2.x, b2.y - a2.y) };
        });
        if (myWalls.length) {
          body.append(label("Each wall"), el("p", "inx__note", "Pick any colour for a single wall, or type its code (like #C27B5C)."));
          fin.walls ||= {};
          for (const w of myWalls) {
            const row = el("div", `inx__wall${pickedWall === w.id ? " is-on" : ""}`);
            row.dataset.wall = w.id;
            const val = fin.walls[w.id] || "";
            const isTreat = (cat.treatments || []).some((t) => t.id === val);
            const cur2 = isTreat ? "" : (val || fin.wall || "");
            const name = el("span", "inx__wall-name", `${w.side} wall${seen[w.side] > 1 ? ` ${w.n}` : ""}, ${w.len.toFixed(1)} m`);
            const pick = el("input"); pick.type = "color"; pick.value = /^#[0-9a-f]{6}$/i.test(cur2) ? cur2 : "#efe9dc";
            pick.setAttribute("aria-label", `${name.textContent}: colour`);
            const code = el("input", "inx__hex"); code.type = "text"; code.value = (fin.walls[w.id] || "").toUpperCase();
            code.placeholder = cur2 ? cur2.toUpperCase() : "#RRGGBB"; code.maxLength = 7; code.spellcheck = false;
            code.setAttribute("aria-label", `${name.textContent}: colour code`);
            const set = (h) => { fin.walls[w.id] = h.toLowerCase(); unlook(); changed(); };
            pick.addEventListener("change", () => set(pick.value));
            code.addEventListener("change", () => {
              const v = code.value.trim().replace(/^([0-9a-f]{6})$/i, "#$1");
              if (/^#[0-9a-f]{6}$/i.test(v)) set(v); else { code.value = (fin.walls[w.id] || "").toUpperCase(); toast("A colour code is # and six letters or digits, like #C27B5C."); }
            });
            const clear = el("button", "link", "Reset"); clear.type = "button";
            clear.addEventListener("click", () => { delete fin.walls[w.id]; changed(); });
            const kind = el("select", "inx__treat"); kind.setAttribute("aria-label", `${name.textContent}: finish`);
            for (const [v, t] of [["", "Paint"], ...(cat.treatments || []).map((x) => [x.id, x.name])]) {
              const op = el("option", null, t); op.value = v; op.selected = (isTreat ? val : "") === v; kind.append(op);
            }
            kind.addEventListener("change", () => {
              if (kind.value) fin.walls[w.id] = kind.value; else delete fin.walls[w.id];
              unlook(); changed();
            });
            if (isTreat) { pick.disabled = true; code.disabled = true; code.value = ""; code.placeholder = "—"; }
            row.append(name, pick, code, kind, ...(val ? [clear] : []));
            body.append(row);
          }
        }
        body.append(label("Floor"));
        const fl = el("div", "inx__floors");
        for (const f of cat.floors) {
          const on = fin.floor === f.id;
          const b = el("button", `inx__floor${on ? " is-on" : ""}`); b.type = "button"; b.setAttribute("aria-pressed", String(on));
          const chip = el("i"); chip.style.background = f.hex;
          b.append(chip, el("span", null, f.name));
          b.addEventListener("click", () => { fin.floor = f.id; unlook(); changed(); });
          fl.append(b);
        }
        body.append(fl);
        // The ceiling: a false-ceiling tray with a hidden light, and the colour of the light.
        body.append(label("Ceiling and lights"));
        const cove = el("label", "inx__toggle");
        const box2 = el("input"); box2.type = "checkbox"; box2.checked = !!fin.cove;
        box2.addEventListener("change", () => { if (box2.checked) fin.cove = true; else delete fin.cove; changed(); });
        cove.append(box2, el("span", null, "False-ceiling cove with a hidden light strip"));
        body.append(cove);
        const temps = el("div", "inx__chips");
        for (const lt of cat.lights || []) {
          const on = fin.kelvin === lt.k;
          const c = el("button", `inx__chip inx__chip--k${lt.k}${on ? " is-on" : ""}`, lt.name); c.type = "button";
          c.setAttribute("aria-pressed", String(on));
          c.addEventListener("click", () => { if (on) delete fin.kelvin; else fin.kelvin = lt.k; viewer.setRoomLight(fin.kelvin); changed(); });
          temps.append(c);
        }
        body.append(temps);
        if (cat.art?.length) body.append(label("Painting over the bed or sofa"), artPicker(fin.art, (a) => { fin.art = a; }, true));
        const clr = el("button", "ghost-btn", "Use the house colours"); clr.type = "button";
        clr.addEventListener("click", () => { draft.finishes = {}; changed(); });
        body.append(clr);
      } else {
        body.append(el("p", "inx__note", "Drag a piece to move it. Click one, then R turns it, Delete removes it, arrow keys nudge it."));
        body.append(svg);
        drawPlan();
      }
      markSel();
    };
    // In the view: grab a piece to move it, click it to change it, click a wall to paint it.
    let pickedWall = null, grabbed = null, moved = false;
    const LIFT = { tv_wall: 0.95, ac_split: 2.15, wall_clock: 1.95, mirror_round: 1.2, mirror_cabinet: 1.2, chimney: 1.55,
                   purifier: 1.15, geyser: 1.75, wall_art: 1.0, wall_shelf: 1.4, mandir_wall: 0.9, blinds_venetian: 0.9,
                   microwave: 0.9, chandelier: 2.2, pendant_light: 2.1 };
    const markSel = () => {
      const d = draft.items.find((x) => x.uid === sel), it = d && byId.get(d.item_id);
      if (!d || !it) { viewer.mark(null); return; }
      const [w, dd] = size(d);
      viewer.mark({ x: d.x, y: d.y, w, d: dd, h: it.height, rotation: d.rotation, lift: LIFT[d.item_id] || 0 }, item.lv);
    };
    const pieceAt = (p) => {
      const elev = p.h - viewer._floorY(item.lv);
      const hits = draft.items.filter((d) => {
        const it = byId.get(d.item_id), lift = LIFT[d.item_id] || 0;
        if (elev < lift - 0.15 || elev > lift + (it?.height || 0.5) + 0.15) return false;
        const [w, dd] = size(d), r = (-d.rotation * Math.PI) / 180;
        const lx = (p.x - d.x) * Math.cos(r) - (p.y - d.y) * Math.sin(r), ly = (p.x - d.x) * Math.sin(r) + (p.y - d.y) * Math.cos(r);
        return Math.abs(lx) <= w / 2 + 0.05 && Math.abs(ly) <= dd / 2 + 0.05;
      });
      const flat = (d) => (byId.get(d.item_id)?.height || 0) < 0.05;
      hits.sort((a, b) => flat(a) - flat(b) || size(a)[0] * size(a)[1] - size(b)[0] * size(b)[1]);
      return hits[0] || null;
    };
    const inRoom = (p) => p.x > bx.x0 - 0.3 && p.x < bx.x1 + 0.3 && p.y > bx.y0 - 0.3 && p.y < bx.y1 + 0.3;
    let off = [0, 0];
    viewer.enableEditing({
      level: item.lv,
      grab: (hit) => {
        if (!win.isConnected || !inRoom(hit)) return false;
        const d = pieceAt(hit);
        if (!d) return false;
        grabbed = d; moved = false; off = [d.x - hit.x, d.y - hit.y];
        sel = d.uid; markSel();
        return true;
      },
      drag: (p) => {
        if (!grabbed) return;
        grabbed.x = snap(p.x + off[0]); grabbed.y = snap(p.y + off[1]); keepIn(grabbed); moved = true;
        markSel();
      },
      drop: () => {
        if (!grabbed) return;
        grabbed = null;
        tab = "pieces";
        if (moved) changed(); else { drawPlan(); drawTab(); }
      },
      click: (hit) => {
        if (!win.isConnected || !hit || !inRoom(hit)) return;
        if (hit.wall) {
          // The nearest wall of this room to where the click landed.
          const lvl = (cur().plan?.levels || []).find((l) => l.index === item.lv);
          const pt = (q) => ({ x: q.x ?? q[0], y: q.y ?? q[1] });
          let best = null, bd = 0.45;
          for (const w of lvl?.walls || []) {
            if (!(w.rooms || []).includes(item.r.id)) continue;
            const a = pt(w.start), b2 = pt(w.end), vx = b2.x - a.x, vy = b2.y - a.y, L = vx * vx + vy * vy || 1;
            const t = Math.max(0, Math.min(1, ((hit.x - a.x) * vx + (hit.y - a.y) * vy) / L));
            const dist = Math.hypot(hit.x - (a.x + t * vx), hit.y - (a.y + t * vy));
            if (dist < bd) { bd = dist; best = w.id; }
          }
          if (best) {
            pickedWall = best; tab = "room"; drawTab();
            body.querySelector(`[data-wall="${best}"]`)?.scrollIntoView({ block: "center" });
          }
        }
      },
    });
    drawPlan();
    drawTab();
    markSel();
  };

  const lis = new Map();
  for (const item of rooms) {
    const li = el("li");
    lis.set(item, li);
    const b = el("button", "inx__room-btn"); b.type = "button";
    b.append(el("span", null, item.r.name || item.r.type), el("small", null, `${floorName(item.lv)}, ${(+item.r.area || 0).toFixed(1)} m²`));
    b.addEventListener("click", () => enter(item));
    li.append(b);
    list.append(li);
  }
  info.hidden = true;
  const first = rooms.find((x) => x.r.type === "living") || rooms[0];
  if (first) enter(first);
}

/* ── 3D ────────────────────────────────────────────────────────────── */

async function renderModel() {
  S.viewer?.dispose();
  S.viewer = null;
  const p = pane("model"); p.innerHTML = "";
  const bar = el("div", "pane__bar");
  // Exterior, a cut-away interior per floor, and a night view with the lamps on.
  const modes = el("div", "sheet-groups");
  modes.setAttribute("role", "tablist");
  bar.append(modes);
  const tools = el("div", "pane__tools");
  const play = el("button", "ghost-btn", "Play walkthrough"); play.type = "button";
  // Exterior design has a tab of its own; the 3D view shows what was chosen there.
  const exterior = el("button", "ghost-btn", "Exterior design"); exterior.type = "button";
  exterior.addEventListener("click", () => showView("exterior"));
  tools.append(exterior, play);
  for (const [label, href, what] of [["GLB", `${API}/plans/${S.activeId}/model.glb`, "for the web, Blender or SketchUp"],
    ["OBJ", `${API}/plans/${S.activeId}/model.obj`, "for most 3D software"]]) {
    const a = el("a", "ghost-btn dl-btn"); a.href = href; a.download = "";
    a.append(icon("download"), document.createTextNode(label));
    a.title = `Download the 3D model as ${label}, ${what}`; a.setAttribute("aria-label", a.title);
    tools.append(a);
  }
  bar.append(tools);
  const stage = el("div", "model-stage");
  const cap = el("p", "model-cap", "Loading the model…");
  const say = el("p", "model-say"); say.setAttribute("aria-live", "polite");
  stage.append(cap, say);
  p.append(bar, stage);

  const id = S.activeId;
  const pal = (S.palette ||= {});
  const modelUrl = () => {
    const q = new URLSearchParams();
    if (pal.id) q.set("palette", pal.id);
    if (pal.text) q.set("colours", pal.text);
    if (pal.design) q.set("design", pal.design);
    const rev = S.plans[id]?.interior?.rev;
    if (rev) q.set("v", rev);
    return `${API}/plans/${id}/model.glb${q.size ? `?${q}` : ""}`;
  };
  try {
    const { Viewer3D } = await import("./viewer3d.js?v=p17");
    if (S.view !== "model" || S.activeId !== id) return;
    S.viewer = new Viewer3D(stage, { daylight: true });
    const road = { N: [0, 1], NE: [0.7, 0.7], E: [1, 0], SE: [0.7, -0.7], S: [0, -1], SW: [-0.7, -0.7], W: [-1, 0], NW: [-0.7, 0.7] }[(cur().plan?.site?.road_directions || ["N"])[0]];
    const st = await S.viewer.load(modelUrl(), { front: road });
    const levels = cur().plan?.levels?.length || 1;
    const options = [["exterior", 0, "Exterior"], ...Array.from({ length: levels }, (_, i) => ["interior", i, i ? `Level ${i} inside` : "Ground inside"]), ["night", 0, "Night"],
      ...Array.from({ length: levels }, (_, i) => ["vastu", i, i ? `Vastu L${i}` : "Vastu ground"])];
    let vastu = null;
    const pick = async (b, mode, lv) => {
      modes.querySelectorAll("button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
      if (mode !== "vastu") { S.viewer.clearVastu(); S.viewer.pickMode(mode, lv); return; }
      // Vastu: the floor cut open, its grid laid on it and every room pinned.
      S.viewer.setMode("interior", lv);
      try {
        vastu ||= await fetch(`${API}/plans/${id}/vastu3d`).then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); });
        if (S.viewer && b.getAttribute("aria-selected") === "true") {
          S.viewer.setVastu(vastu, lv);
          const here = vastu.rooms.filter((r) => r.level === lv);
          const off = here.filter((r) => r.target).length;
          cap.textContent = `Vastu ${vastu.score.toFixed(0)} / 100  ·  ${here.length} rooms placed on this floor`
            + (off ? `  ·  ${off} could move to a better quarter` : "  ·  every room in a good quarter");
        }
      } catch (e) { toast(`Vastu placements could not be loaded (${e.message}).`); }
    };
    for (const [mode, lv, label] of options) {
      const b = el("button", null, label); b.type = "button"; b.setAttribute("role", "tab");
      b.dataset.mode = mode; b.dataset.level = String(lv);
      b.addEventListener("click", () => pick(b, mode, lv));
      modes.append(b);
    }
    modes.firstChild?.setAttribute("aria-selected", "true");
    // Zooming in walks inside: the tab follows, and the caption says how to get back out.
    const outside = () => cap.textContent;
    let said = "";
    S.viewer.autoInterior((mode, lv) => {
      modes.querySelectorAll("button").forEach((x) => x.setAttribute("aria-selected", String(x.dataset.mode === mode && +x.dataset.level === lv)));
      if (mode === "interior") {
        said ||= outside();
        cap.textContent = `Inside · ${floorName(lv)}  ·  ${lv > 0 ? "zoom in for the floor below, out to go back up" : "zoom out to go back up and outside"}`;
      } else if (said) { cap.textContent = said; said = ""; }
    });
    cap.textContent = `${st.width.toFixed(1)} × ${st.depth.toFixed(1)} m  ·  ${st.height.toFixed(1)} m high  ·  ${st.triangles.toLocaleString()} triangles`;
  } catch (err) {
    cap.textContent = `The model could not be shown here (${err.message}). It can still be downloaded.`;
  }

  fetch(`${API}/plans/${id}/walkthrough`).then((r) => r.json()).then((d) => {
    const lines = (d.narration || []).map((l) => l.text);
    play.disabled = !lines.length;
    play.addEventListener("click", () => {
      if (!("speechSynthesis" in window)) return toast("This browser has no speech synthesis.");
      speechSynthesis.cancel();
      for (const text of lines) {
        const u = new SpeechSynthesisUtterance(text);
        u.onstart = () => { say.textContent = text; };
        speechSynthesis.speak(u);
      }
    });
  }).catch(() => { play.disabled = true; });
}

/* ── Exterior: a tab of its own ───────────────────────────────────── */

// The gallery takes the page, so many designs show at once; beside it the
// chosen design in 3D and all four of its elevations, redrawn as it changes.
async function renderExterior() {
  S.exViewer?.dispose(); S.exViewer = null;
  const p = pane("exterior"); p.innerHTML = "";
  const id = S.activeId;
  if (!id) return;
  const wrap = el("div", "exw");
  const card = el("div", "pal ex ex--page");
  const side = el("aside", "exw__side");
  side.setAttribute("aria-label", "The chosen exterior");
  const stage = el("div", "exw__stage");
  const cap = el("p", "model-cap", "Loading the house…");
  stage.append(cap);
  const elevHead = el("div", "exw__elevhead");
  elevHead.append(el("h3", "ex__h", "Elevations"));
  const open3d = el("button", "ghost-btn", "Open in 3D"); open3d.type = "button";
  open3d.addEventListener("click", () => showView("model"));
  elevHead.append(open3d);
  const elev = el("div", "exw__elev");
  side.append(stage, elevHead, elev);
  wrap.append(card, side);
  p.append(wrap);

  const pal = (S.palette ||= {});
  const modelUrl = () => {
    const q = new URLSearchParams();
    if (pal.id) q.set("palette", pal.id);
    if (pal.text) q.set("colours", pal.text);
    if (pal.design) q.set("design", pal.design);
    return `${API}/plans/${id}/model.glb${q.size ? `?${q}` : ""}`;
  };
  // The four elevations of what the model shows, drawn without the site.
  const { elevations } = await import("./thumbs.js?v=p4");
  let drawn = "";
  const drawElevations = async () => {
    const url = modelUrl();
    if (url === drawn) return;
    drawn = url;
    elev.innerHTML = "";
    const figs = ["North", "East", "South", "West"].map((name) => {
      const f = el("figure", "exw__fig is-loading");
      f.append(el("figcaption", null, name));
      elev.append(f);
      return f;
    });
    const srcs = await elevations(url).catch(() => []);
    if (drawn !== url) return;
    figs.forEach((f, i) => {
      if (!srcs[i]) { f.classList.replace("is-loading", "is-failed"); return; }
      const img = el("img"); img.src = srcs[i]; img.alt = `${f.textContent} elevation`;
      f.prepend(img); f.classList.remove("is-loading");
    });
  };
  try {
    const { Viewer3D } = await import("./viewer3d.js?v=p17");
    if (S.view !== "exterior" || S.activeId !== id) return;
    S.exViewer = new Viewer3D(stage, { daylight: true });
    const road = { N: [0, 1], NE: [0.7, 0.7], E: [1, 0], SE: [0.7, -0.7], S: [0, -1], SW: [-0.7, -0.7], W: [-1, 0], NW: [-0.7, 0.7] }[(cur().plan?.site?.road_directions || ["N"])[0]];
    await S.exViewer.load(modelUrl(), { front: road });
    cap.remove();
  } catch (err) {
    cap.textContent = `The house could not be shown here (${err.message}).`;
  }
  drawElevations();
  paletteCard(card, id, modelUrl, { viewer: () => S.exViewer, page: true, onModel: drawElevations });
}

/* ── 3D: colour schemes, recommended and browsable ─────────────────── */

// Exterior design ids, mirrored from engines/experience/exteriors.py:
// ex:roof.base.upper.screen.windows.planters.accent.feature[~w:hex,c:hex,r:hex,m:hex]
// The paintable parts, in the server's order (from the grammar; see exteriors.PARTS).
let EX_PART_ORDER = [];
const EX_PARTS = ["roof", "base", "upper", "screen", "windows", "planters", "accent", "feature"];
const EX_TINTS = { w: "wall", c: "clad", r: "roof_tint", m: "metal", f: "frame", d: "door" };
const EX_OPTS = { b: "boundary", l: "railing", h: "shade", e: "canopy", g: "gate", v: "paving", t: "garden", s: "solar",
  x: "panel", q: "parapet", k: "deck", i: "lights", y: "yard", a: "garage" };
const EX_NICE = { flat: "Flat parapet", slab: "Cantilever slab", mono: "Mono-pitch", butterfly: "Butterfly", hip: "Hip, tiled", gable: "Gable",
  plaster: "Plaster", stone: "Stone", brick: "Brick", concrete: "Concrete", timber: "Timber", metal: "Metal", none: "None",
  fins: "Fins", louvres: "Louvres", frame: "Box frame", jaali: "Jaali", perforated: "Perforated", punched: "Punched", band: "Glazing band",
  jharokha: "Jharokha", colonnade: "Colonnade", chhatri: "Chhatri", cornice: "Cornice", breeze: "Breeze-block", greenwall: "Green wall", balcony: "Balcony",
  hedge: "Hedge", grille: "Grille", glass: "Glass", solid: "Solid wall", terracotta: "Terracotta tile", acp: "ACP panel",
  slate: "Stacked slate", corten: "Corten steel", vault: "Barrel vault", sawtooth: "Sawtooth", slats: "Timber slats", bamboo: "Bamboo",
  arcade: "Arcade", portico: "Portico", bay: "Bay window", floatbox: "Floating box", featurewall: "Monolith wall",
  thinnai: "Thinnai", bangla: "Bangla pavilion", pergolaframe: "Pergola frame", cornerglass: "Glass corner",
  brickcurtain: "Brick curtain", wavescreen: "Wave screen", moongate: "Moon gate", cantilever: "Cantilever room",
  flutedbands: "Fluted bands", brisesoleil: "Brise-soleil", planterbands: "Planter bands", rooftopframe: "Crown frame" };
// A count too large to read as digits, in words: "120 quintillion".
function bigWords(n) {
  const names = ["", "thousand", "million", "billion", "trillion", "quadrillion", "quintillion", "sextillion", "septillion", "octillion"];
  let i = 0;
  while (n >= 1000 && i < names.length - 1) { n /= 1000; i++; }
  return `${n >= 100 ? Math.round(n) : n.toFixed(n >= 10 ? 0 : 1)} ${names[i]}`.trim();
}
function exParse(id) {
  if (!id || !id.startsWith("ex:")) return null;
  const [core, tail = ""] = id.slice(3).split("~");
  const p = core.split(".");
  if (p.length === 7) p.push("none");
  if (p.length !== 8) return null;
  const d = Object.fromEntries(EX_PARTS.map((k, i) => [k, p[i]]));
  d.planters = d.planters === "p";
  for (const kv of tail.split(",")) {
    const [k, v = ""] = kv.split(":");
    if (k === "z") d.paints = Object.fromEntries(v.split(".").map((x) => x.split(/-(?=[0-9a-f]{6}$)/i))
      .filter(([pk, hx]) => /^[a-z_]+$/.test(pk || "") && /^[0-9a-f]{6}$/i.test(hx || "")).map(([pk, hx]) => [pk, hx.toLowerCase()]));
    else if (EX_TINTS[k] && /^[0-9a-f]{6}$/i.test(v)) d[EX_TINTS[k]] = v.toLowerCase();
    else if (EX_OPTS[k] && /^[a-z]+$/.test(v)) d[EX_OPTS[k]] = v;
  }
  return d;
}
// A design in a colour scheme's tints: only the surfaces the scheme names change.
const EX_TINT_FIELDS = ["wall", "clad", "roof_tint", "metal", "frame", "door"];
function exTint(id, tint) {
  const p = exParse(id);
  if (!p || !tint) return id;
  for (const k of EX_TINT_FIELDS) if (tint[k]) p[k] = tint[k];
  return exId(p);
}
const schemeTint = (sc) => sc && Object.fromEntries([["id", sc.id], ["name", sc.name],
  ...[["wall", "wall"], ["clad", "clad"], ["roof_tint", "roof"], ["metal", "metal"], ["frame", "frame"], ["door", "door"]]
    .map(([k, f]) => [k, String(sc[f] || "").replace("#", "").toLowerCase()])]);
function exId(d) {
  const core = "ex:" + EX_PARTS.map((k) => (k === "planters" ? (d.planters ? "p" : "n") : d[k])).join(".");
  const tail = [...Object.entries(EX_TINTS), ...Object.entries(EX_OPTS)].filter(([, f]) => d[f]).map(([k, f]) => `${k}:${d[f]}`);
  // Parts painted one by one, in the server's order so equal paints give equal ids.
  const pk = Object.keys(d.paints || {}).sort((a, b) => (EX_PART_ORDER.indexOf(a) + 1 || 99) - (EX_PART_ORDER.indexOf(b) + 1 || 99));
  if (pk.length) tail.push(`z:${pk.map((k) => `${k}-${d.paints[k]}`).join(".")}`);
  const t = tail.join(",");
  return t ? `${core}~${t}` : core;
}

// The palette card: the recommended scheme first, the others a click away,
// and a line where the client can say what colours they like in words.
// `viewer` is whichever 3D view shows the house; `page` lays the panel out as
// the Exterior tab itself rather than a card over a model; `onModel` hears
// each rebuild (the Exterior tab redraws its elevations).
async function paletteCard(card, id, modelUrl, { viewer = () => S.viewer, page = false, onModel = null } = {}) {
  const pal = S.palette;
  const [{ thumb }, { swatch: texSwatch }] = await Promise.all([import("./thumbs.js?v=p4"), import("./materials.js?v=m4")]);
  const swatch = (hex, label) => {
    const sw = el("span", "pal__sw"); sw.style.background = hex; sw.title = `${label} ${hex}`; return sw;
  };
  const LABELS = { plaster: "Walls", trim: "Bands", clad: "Cladding", roof: "Roof", frame: "Frames", door: "Main door",
    living: "Living", master: "Master bed", bedroom: "Bedrooms", kitchen: "Kitchen", accent_wall: "Feature wall",
    floor_stone: "Floor", joinery: "Joinery", upholstery: "Fabric" };
  const TINTS = ["wall", "clad", "roof_tint", "metal", "frame", "door"];
  const front = { N: [0, 1], NE: [0.7, 0.7], E: [1, 0], SE: [0.7, -0.7], S: [0, -1], SW: [-0.7, -0.7], W: [-1, 0], NW: [-0.7, 0.7] }[
    (S.plans[id]?.plan?.site?.road_directions || ["N"])[0]] || null;
  const hx = (h) => String(h || "").replace("#", "").toLowerCase();
  let list = [];
  let designs = [];
  let grammar = null;
  // Which pools fit round this house, and where: the Customise sheet offers only those.
  let pools = null, poolNow = null;
  fetch(`${API}/plans/${id}/pools`).then((r) => (r.ok ? r.json() : null))
    .then((x) => { pools = x?.options || null; poolNow = x?.current || null; }).catch(() => {});
  let loading = false, batch = 0, seq = 0, live = 0, timer = 0, lastTab = null, lastGroup = null;
  // What the client said about the look, sent with every batch so each one
  // follows the brief as well as the style; and what the server heard in it.
  const cb = S.chatBrief || {};
  const briefPrefs = [S.chatWords, cb.notes, (cb.styles || []).join(" "), cb.colours, pal.text].filter(Boolean).join(". ").slice(0, 1100);
  let heard = [], planStyle = S.plans[id]?.plan?.style || "";
  const styleName = (k) => (k === "signature" ? "Signature homes" : grammar?.styles?.find((x) => x.id === k)?.name || "");
  // pal.base is the chosen design as drawn; pal.tint the exterior colours laid
  // over it (null: the design's own); pal.design what the model is built from.
  const idx = () => Math.max(0, designs.findIndex((x) => x.id === pal.base));
  const tinted = (did, tint = pal.tint) => exTint(did, tint);
  const thumbUrl = (did) => {
    const q = new URLSearchParams({ design: did, furniture: "false" });
    if (pal.id) q.set("palette", pal.id);
    return `${API}/plans/${id}/model.glb?${q}`;
  };
  // A design's colours: its card's own choice if one was made there (null:
  // the design's own), otherwise whatever the Colours tab set for all.
  const cardTint = (d) => (d && d.tint !== undefined ? d.tint : pal.tint);
  // Whether the house's exterior is its own: claimed after each change lands.
  let uniq = null;
  const uniqBadge = () => {
    if (!uniq || uniq.design !== pal.design) return null;
    const u = el("span", `ex__uniq${uniq.unique ? "" : " is-shared"}`,
      uniq.unique ? "Unique to your house" : "Another house has this exact look: change any detail to make it yours");
    u.setAttribute("role", "status");
    return u;
  };
  const claim = async (designId) => {
    try {
      const r = await fetch(`${API}/plans/${id}/exteriors/claim?design=${encodeURIComponent(designId)}`, { method: "POST" });
      if (!r.ok || designId !== pal.design) return;
      uniq = { design: designId, ...(await r.json()) };
      const head = card.querySelector(".ex__title");
      head?.querySelector(".ex__uniq")?.remove();
      const u = uniqBadge();
      if (head && u) head.append(u);
    } catch { /* uniqueness is a courtesy; the design stands either way */ }
  };
  const rebuild = async () => {
    if (!viewer() || !designs.length) return;
    pal.design = tinted(designs[idx()].id, cardTint(designs[idx()]));
    const asked = pal.design;
    live++; card.classList.add("is-live");
    try { await viewer().load(modelUrl(), { keepView: true }); } catch (e) { toast(`Could not rebuild the exterior (${e.message}).`); }
    if (--live === 0) card.classList.remove("is-live");
    picker?.refresh();
    if (asked === pal.design) { claim(asked); onModel?.(); }
  };
  const choose = (did) => { pal.base = did; pal.notes = []; draw(); rebuild(); };
  const merge = (xs) => {
    const known = new Set(designs.map((d) => d.id));
    const fresh = (xs || []).filter((d) => exParse(d.id) && !known.has(d.id));
    designs.push(...fresh);
    return fresh;
  };
  const loadMore = async (n = 12, style = pal.style || "", extra = "") => {
    if (loading) return [];
    loading = true;
    let fresh = [];
    try {
      const q = new URLSearchParams({ seed: `${Date.now().toString(36)}-${++batch}`, n: String(n) });
      if (style) q.set("style", style);
      // What the catalogue is narrowed to steers the next batch, ahead of the brief.
      const prefs = [extra, briefPrefs].filter(Boolean).join(". ").slice(0, 1150);
      if (prefs) q.set("prefs", prefs);
      for (const d of designs.slice(-40)) q.append("avoid", d.id);
      const r = await fetch(`${API}/plans/${id}/exteriors?${q}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const x = await r.json();
      grammar = x.grammar || grammar;
      if (grammar?.parts) EX_PART_ORDER = grammar.parts.map((q) => q.key);
      setupPicker();
      heard = x.heard || heard;
      planStyle = x.style || planStyle;
      fresh = merge(x.designs.map((d) => ({ ...d, fam: style })));
    } catch (e) { toast(`Could not generate more designs (${e.message}).`); }
    loading = false;
    return fresh;
  };
  const fetchList = async () => {
    const q = new URLSearchParams(); if (pal.text) q.set("colours", pal.text);
    const r = await fetch(`${API}/plans/${id}/palettes${q.size ? `?${q}` : ""}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    list = d.schemes;
    pal.prefs = d.preferences;
  };
  // The designer's set for what the client said, and a fresh batch beside it,
  // so the gallery opens with plenty to choose from.
  const start = async () => {
    const agent = fetch(`${API}/plans/${id}/exteriors${briefPrefs ? `?prefs=${encodeURIComponent(briefPrefs)}` : ""}`)
      .then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const settle = () => {
      if (!designs.length) return draw();
      // A design chosen elsewhere (a drawing sheet) leads the gallery rather than being lost.
      if (pal.base && exParse(pal.base) && !designs.some((d) => d.id === pal.base)) {
        // The house keeps its own name and story when its plan is edited (a pool moved, a room widened).
        designs.unshift(pal.baseCard?.id === pal.base ? { ...pal.baseCard }
          : { id: pal.base, name: "Your current design", story: "The design the drawings show.", fam: "" });
      }
      if (!designs.some((d) => d.id === pal.base)) pal.base = designs[0].id;
      draw();
      if (tinted(designs[idx()].id) !== pal.design) rebuild();
    };
    // The grammar's batch is instant; the designer (a model call) can take a
    // while, so its picks join at the front of the gallery when they arrive.
    await loadMore(24);
    if (designs.length) settle();
    const x = await agent;
    if (x?.designs?.length) {
      grammar = x.grammar || grammar;
      const lead = x.designs.filter((d) => exParse(d.id));
      if (!designs.length) {
        designs = lead;
        return settle();
      }
      // The gallery is already on screen: the designer's picks join at the
      // end, so nothing moves under the client's hand.
      const shownIds = new Set(designs.map((d) => d.id));
      designs.push(...lead.filter((d) => !shownIds.has(d.id)));
      draw();
    } else if (!designs.length) draw();
  };
  // The whole-house scheme: interiors, frames and doors as well as the outside.
  const apply = async (scheme) => {
    if (!viewer()) return;
    pal.id = scheme.id;
    draw();
    live++; card.classList.add("is-live");
    try { await viewer().load(modelUrl(), { keepView: true }); } catch (e) { toast(`Could not recolour the model (${e.message}).`); }
    if (--live === 0) card.classList.remove("is-live");
    onModel?.();
  };

  // Thumbnails render when their tile scrolls into view, latest first.
  const io = new IntersectionObserver((es) => {
    for (const e of es) if (e.isIntersecting) { io.unobserve(e.target); e.target._load?.(); }
  }, { rootMargin: "80px" });
  const tile = ({ selected, url, label, title, strip, onPick }) => {
    const b = el("button", "ex-tile"); b.type = "button";
    b.setAttribute("aria-pressed", String(selected));
    if (title) b.title = title;
    const fig = el("span", "ex-tile__img is-loading");
    const img = el("img"); img.alt = ""; img.decoding = "async";
    img.addEventListener("load", () => fig.classList.remove("is-loading"));
    fig.append(img);
    b._load = () => thumb(url, front).then((src) => { if (src) img.src = src; else fig.classList.replace("is-loading", "is-failed"); });
    io.observe(b);
    const cap = el("span", "ex-tile__cap");
    cap.append(el("span", "ex-tile__name", label));
    if (strip) {
      const st = el("span", "ex-tile__strip"); st.setAttribute("aria-hidden", "true");
      for (const hex of strip) { const i = el("i"); i.style.background = hex; st.append(i); }
      cap.append(st);
    }
    b.append(fig, cap);
    b.addEventListener("click", onPick);
    return b;
  };
  // The schemes a card offers: the design's own colours, then the five that
  // suit its style best (its style's own first).
  const cardSchemes = (d) => {
    const all = grammar?.schemes || [];
    const mine = grammar?.styles?.find((x) => x.id === (d.fam || planStyle))?.schemes || [];
    return [null, ...[...all.filter((x) => mine.includes(x.id)), ...all.filter((x) => !mine.includes(x.id))].slice(0, 5)];
  };
  // ── the catalogue ──────────────────────────────────────────────────
  // A lookbook: each design as an architectural photograph, the surfaces it
  // is built from as a material board (real texture chips, as an architect
  // pins samples beside a facade), its colourways, and a way to keep it.
  const FINISH_OF = { plaster: ["plaster", "#e9e2d4"], stone: ["stone", "#9a8a76"], brick: ["brick", "#9a5238"],
    concrete: ["concrete", "#a9a7a1"], timber: ["timber", "#8a5a34"], metal: ["seam", "#3a3b3d"],
    terracotta: ["tiles", "#b0613f"], acp: ["acpanel", "#8f9296"], slate: ["slate", "#56585b"],
    glass: ["curtain", "#33424c"], corten: ["corten", "#7a3d1f"] };
  const ROOF_FINISH = { flat: ["plaster", "Terrace"], slab: ["concrete", "Concrete slab"], hip: ["tile", "Clay tiles"],
    gable: ["tile", "Clay tiles"], mono: ["seam", "Standing seam"], butterfly: ["seam", "Standing seam"],
    vault: ["seam", "Curved sheet"], sawtooth: ["seam", "Standing seam"] };
  const lower = (t) => String(t || "").toLowerCase();
  // The colours a design wears: its card's colourway, else its own tints, else the scheme's.
  const wears = (d, s) => {
    const p = exParse(d.id) || {}, t = cardTint(d) || {};
    const pick = (k, fall) => (t[k] ? `#${t[k]}` : p[k] ? `#${p[k]}` : fall);
    return { p, wall: pick("wall", s.exterior.plaster), clad: pick("clad", ""), roof: pick("roof_tint", s.exterior.roof),
      accent: grammar?.accents?.[p.accent] || s.exterior.frame };
  };
  // The board: ground floor, upper floors (when they differ), roof, accent.
  const board = (d, s, size = 44) => {
    const w = wears(d, s), p = w.p;
    const one = (S.plans[id]?.plan?.levels?.length || 1) <= 1;
    const skin = (mat) => {
      const [kind, hex] = FINISH_OF[mat] || FINISH_OF.plaster;
      return [kind, mat === "plaster" ? w.wall : (w.clad || hex), EX_NICE[mat] || mat];
    };
    const rows = [["Ground floor", ...skin(p.base)]];
    if (!one && p.upper && p.upper !== p.base) rows.push(["Upper floors", ...skin(p.upper)]);
    else if (p.base !== "plaster") rows.push(["Walls", "plaster", w.wall, "Painted plaster"]);
    const [rk, rn] = ROOF_FINISH[p.roof] || ROOF_FINISH.flat;
    rows.push(["Roof", rk, w.roof, rn]);
    rows.push(["Accent", p.accent === "teak" ? "timber" : "seam", w.accent, `${p.accent?.[0]?.toUpperCase() || ""}${p.accent?.slice(1) || ""}`]);
    const box = el("ul", "lb-board");
    box.setAttribute("aria-label", `${d.name} materials`);
    for (const [where, kind, hex, name] of rows) {
      const li = el("li", "lb-board__chip");
      const c = texSwatch(kind, hex || "#cccccc", size); c.setAttribute("aria-hidden", "true");
      const cap = el("span", "lb-board__name", name);
      cap.append(el("small", null, lower(where)));
      li.append(c, cap);
      li.title = `${where}: ${name}`;
      box.append(li);
    }
    return box;
  };
  // One plain sentence on what the design is.
  const spec = (d) => {
    const p = exParse(d.id) || {};
    const roof = { flat: "A flat roof terrace", slab: "A cantilevered slab roof", mono: "A mono-pitch roof", butterfly: "A butterfly roof",
      hip: "A tiled hip roof", gable: "A gable roof", vault: "A barrel-vault roof", sawtooth: "A sawtooth roof" }[p.roof] || "A roof";
    const mats = [...new Set([p.base, p.upper].filter(Boolean))].map((m) => lower(EX_NICE[m] || m));
    let line = `${roof} over ${mats.join(" and ")}`;
    if (p.screen && p.screen !== "none") line += `, ${lower(EX_NICE[p.screen] || p.screen)} on the street face`;
    if (p.feature && p.feature !== "none") line += `, with a ${lower(EX_NICE[p.feature] || p.feature)}`;
    return `${line}.`;
  };
  // What the catalogue can be narrowed by.
  const moodOf = (hex) => {
    const n = parseInt(String(hex || "#cccccc").slice(1), 16);
    const r = (n >> 16) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2;
    const sat = mx === mn ? 0 : (mx - mn) / (1 - Math.abs(2 * l - 1));
    if (l > 0.82) return "light";
    if (l < 0.38) return "dark";
    if (sat > 0.42) return "colourful";
    return r >= b ? "earthy" : "cool";
  };
  const MOODS = [["light", "Light and airy"], ["earthy", "Warm and earthy"], ["cool", "Cool greys and blues"],
    ["colourful", "Colourful"], ["dark", "Dark and bold"]];
  const facetsOf = (d, s) => {
    const w = wears(d, s), p = w.p;
    return { roof: p.roof, walls: [...new Set([p.base, p.upper])], mood: moodOf(w.wall) };
  };
  pal.facets ||= { roof: [], walls: [], mood: [] };
  pal.saved ||= [];
  const saved = (d) => pal.saved.includes(d.id);
  const toggleSave = (d) => {
    pal.saved = saved(d) ? pal.saved.filter((x) => x !== d.id) : [...pal.saved, d.id];
  };
  const BOOKMARK = "M6 3.5h12v17l-6-4.2-6 4.2z";
  const pathIcon = (path, cls) => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true"); svg.classList.add(cls);
    const pa = document.createElementNS("http://www.w3.org/2000/svg", "path"); pa.setAttribute("d", path);
    svg.append(pa);
    return svg;
  };
  const designCard = (d, s, { lead = false } = {}) => {
    const on = d.id === pal.base;
    const wrap = el("article", `lb-card${lead ? " lb-card--lead" : ""}${on ? " is-on" : ""}`);
    // The photograph chooses the design.
    const photo = el("button", "lb-card__photo is-loading"); photo.type = "button";
    photo.setAttribute("aria-pressed", String(on));
    photo.setAttribute("aria-label", on ? `${d.name}, on your house` : `Put ${d.name} on your house`);
    const img = el("img"); img.alt = ""; img.decoding = "async";
    img.addEventListener("load", () => photo.classList.remove("is-loading"));
    photo.append(img);
    if (on) photo.append(el("span", "lb-card__on", "On your house"));
    else if (lead) photo.append(el("span", "lb-card__on lb-card__on--pick", "The studio's pick for this house"));
    if (d.look) photo.append(el("span", "lb-card__look", "Signature home"));
    photo._load = () => thumb(thumbUrl(tinted(d.id, cardTint(d))), front, lead ? "wide" : "card")
      .then((src) => { if (src) img.src = src; else photo.classList.replace("is-loading", "is-failed"); });
    io.observe(photo);
    photo.addEventListener("click", () => choose(d.id));
    const body = el("div", "lb-card__body");
    const head = el("div", "lb-card__head");
    const name = el("h4", "lb-card__name", d.name);
    const keep = el("button", "lb-card__keep"); keep.type = "button";
    keep.setAttribute("aria-pressed", String(saved(d)));
    keep.setAttribute("aria-label", saved(d) ? `Remove ${d.name} from your shortlist` : `Add ${d.name} to your shortlist`);
    keep.title = saved(d) ? "On your shortlist" : "Add to shortlist";
    keep.append(pathIcon(BOOKMARK, "lb-card__keepicon"));
    keep.addEventListener("click", (e) => {
      toggleSave(d); draw();
      // A keyboard toggle keeps the keyboard on the same bookmark across the redraw.
      if (e.detail === 0) [...card.querySelectorAll(".lb-card__keep")].find((x) => x.getAttribute("aria-label").includes(` ${d.name} `))?.focus({ preventScroll: true });
    });
    head.append(name, keep);
    body.append(head, el("p", "lb-card__spec", spec(d)), board(d, s, lead ? 52 : 40));
    // Colourways: each a two-tone paint chip; choosing one puts the design on in those colours.
    const ways = el("div", "lb-ways"); ways.setAttribute("role", "group"); ways.setAttribute("aria-label", `${d.name} colourways`);
    const now = cardTint(d)?.id ?? null;
    const p = exParse(d.id) || {};
    const own = [p.wall ? `#${p.wall}` : s.exterior.plaster, s.exterior.clad, p.roof_tint ? `#${p.roof_tint}` : s.exterior.roof];
    for (const sc of cardSchemes(d)) {
      const b = el("button", "lb-ways__chip"); b.type = "button";
      const nm = sc ? sc.name : "Its own colours";
      b.title = nm;
      b.setAttribute("aria-label", `${d.name} in ${nm}`);
      b.setAttribute("aria-pressed", String((sc?.id ?? null) === now));
      const [w, c, r] = sc ? [sc.wall, sc.clad, sc.roof] : own;
      b.style.background = `linear-gradient(90deg, ${w} 0 58%, ${c} 58% 82%, ${r} 82%)`;
      b.addEventListener("click", (e) => {
        d.tint = schemeTint(sc);
        choose(d.id);
        if (e.detail === 0) card.querySelector(`[aria-label="${d.name} in ${nm}"]`)?.focus({ preventScroll: true });
      });
      ways.append(b);
    }
    body.append(ways);
    wrap.append(photo, body);
    return wrap;
  };

  // Side by side: the shortlist as an architect lays options out for a client.
  const compare = (s) => {
    const list = designs.filter(saved).slice(0, 4);
    const dlg = el("dialog", "lb-cmp");
    dlg.setAttribute("aria-label", "Compare your shortlist");
    const top = el("div", "lb-cmp__top");
    top.append(el("h3", "lb-cmp__title", `Your shortlist, side by side`));
    const x = el("button", "ghost-btn", "Close"); x.type = "button";
    x.addEventListener("click", () => dlg.close());
    top.append(x);
    dlg.append(top);
    const grid = el("div", "lb-cmp__grid");
    grid.style.setProperty("--n", String(list.length));
    const ROWS = [["Roof", (p) => EX_NICE[p.roof] || p.roof], ["Ground floor", (p) => EX_NICE[p.base] || p.base],
      ["Upper floors", (p) => EX_NICE[p.upper] || p.upper], ["Street screen", (p) => EX_NICE[p.screen || "none"]],
      ["Signature element", (p) => EX_NICE[p.feature || "none"]], ["Windows", (p) => EX_NICE[p.windows] || p.windows],
      ["Boundary", (p) => EX_NICE[p.boundary || "plaster"] || p.boundary], ["Gate", (p) => ({ none: "Open", sliding: "Steel sliding", timber: "Timber" })[p.gate || "none"]],
      ["Garden feature", (p) => ({ tulsi: "Tulsi platform", jhoola: "Jhoola swing", waterwall: "Water wall", koipond: "Koi pond",
        gazebo: "Gazebo", rockgarden: "Rock garden", sitout: "Garden sit-out", fountain: "Fountain", firepit: "Fire pit",
        lounge: "Lounge deck", flowerbeds: "Flower beds" })[p.yard] || "None"]];
    for (const d of list) {
      const col = el("section", "lb-cmp__col");
      const ph = el("div", "lb-cmp__photo is-loading");
      const im = el("img"); im.alt = d.name;
      im.addEventListener("load", () => ph.classList.remove("is-loading"));
      ph.append(im);
      thumb(thumbUrl(tinted(d.id, cardTint(d))), front).then((src) => { if (src) im.src = src; });
      col.append(ph, el("h4", "lb-card__name", d.name), board(d, s, 36));
      const dl = el("dl", "lb-cmp__facts");
      const p = exParse(d.id) || {};
      for (const [k, f] of ROWS) dl.append(el("dt", null, k), el("dd", null, f(p) || "None"));
      col.append(dl);
      const use = el("button", "btn lb-cmp__use", d.id === pal.base ? "On your house" : "Put on my house"); use.type = "button";
      use.disabled = d.id === pal.base;
      use.addEventListener("click", () => { dlg.close(); choose(d.id); });
      const drop = el("button", "pal__clr", "Remove from shortlist"); drop.type = "button";
      drop.addEventListener("click", () => { toggleSave(d); dlg.close(); draw(); if (pal.saved.length) compare(s); });
      col.append(use, drop);
      grid.append(col);
    }
    dlg.append(grid);
    dlg.addEventListener("close", () => dlg.remove());
    document.body.append(dlg);
    dlg.showModal();
  };
  const skeleton = (panel, n = 6) => {
    const grid = el("div", "ex-grid");
    for (let i = 0; i < n; i++) {
      const t = el("span", "ex-tile is-ghost");
      t.append(el("span", "ex-tile__img is-loading"), el("span", "ex-tile__cap"));
      grid.append(t);
    }
    panel.append(el("p", "ex__hint", "Composing exterior designs for this house…"), grid);
  };

  // A row of choices drawn as chips; `paint` may decorate each chip.
  const chips = (title, options, current, pick, { paint, cls = "", disabled = () => false } = {}) => {
    const box = el("div", "ex-group");
    const head = el("span", "pal__rk", title);
    head.id = `ex-g-${title.replace(/\W+/g, "-").toLowerCase()}`;
    const row = el("div", `ex-chips ${cls}`);
    row.setAttribute("role", "group"); row.setAttribute("aria-labelledby", head.id);
    for (const [value, label] of options) {
      const b = el("button", "ex-chip"); b.type = "button";
      b.setAttribute("aria-pressed", String(value === current));
      b.disabled = disabled(value);
      if (paint) paint(b, value);
      b.append(el("span", "ex-chip__t", label));
      // A keyboard choice keeps the keyboard where it was across the redraw.
      b.addEventListener("click", (e) => { lastGroup = e.detail === 0 ? head.id : null; pick(value, b); });
      row.append(b);
    }
    box.append(head, row);
    return box;
  };

  const designsPanel = (panel, s) => {
    // House styles: each pulls its own batch, kept for when the client comes back.
    const own = styleName(planStyle);
    // Signature homes: whole houses after admired ones - a Goan villa, a
    // Chettinad mansion, a Bawa house - each in its colourways.
    const styles = [["", own ? `For this house: ${own}` : "For this house"], ["signature", "Signature homes"],
      ...(grammar?.styles || []).filter((x) => x.id !== planStyle).map((x) => [x.id, x.name])];
    const filt = chips("Style", styles, pal.style || "", async (v) => {
      pal.style = v; draw();
      if (v && !designs.some((d) => d.fam === v)) { await loadMore(v === "signature" ? 40 : 24, v); draw(); }
    }, { cls: "ex-chips--scroll" });
    panel.append(filt);

    const inStyle = designs.filter((d) => !pal.style || d.fam === pal.style);
    if (!inStyle.length) return skeleton(panel);
    const F = pal.facets;
    const active = F.roof.length + F.walls.length + F.mood.length;
    const matches = (d) => {
      const f = facetsOf(d, s);
      return (!F.roof.length || F.roof.includes(f.roof))
        && (!F.walls.length || f.walls.some((w) => F.walls.includes(w)))
        && (!F.mood.length || F.mood.includes(f.mood))
        && (!pal.shortOnly || saved(d));
    };
    const shown = inStyle.filter(matches);

    // The tools: refine, the shortlist, compare, and how big to show the photographs.
    const bar = el("div", "lb-bar");
    const refine = el("button", "lb-tool", active ? `Refine (${active})` : "Refine"); refine.type = "button";
    refine.setAttribute("aria-expanded", String(!!pal.refineOpen)); refine.setAttribute("aria-controls", "lb-refine");
    refine.addEventListener("click", () => { pal.refineOpen = !pal.refineOpen; draw(); card.querySelector(".lb-bar .lb-tool")?.focus(); });
    const short = el("button", "lb-tool", `Shortlist ${pal.saved.length}`); short.type = "button";
    short.prepend(pathIcon(BOOKMARK, "lb-tool__icon"));
    short.setAttribute("aria-pressed", String(!!pal.shortOnly));
    short.title = pal.saved.length ? "Show only your shortlist" : "Bookmark designs to shortlist them";
    short.disabled = !pal.saved.length && !pal.shortOnly;
    short.addEventListener("click", () => { pal.shortOnly = !pal.shortOnly; draw(); });
    const cmp = el("button", "lb-tool", "Compare"); cmp.type = "button";
    cmp.disabled = pal.saved.length < 2;
    cmp.title = pal.saved.length < 2 ? "Shortlist two or more designs to compare them" : "Compare your shortlist side by side";
    cmp.addEventListener("click", () => compare(s));
    const view = el("div", "lb-view"); view.setAttribute("role", "group"); view.setAttribute("aria-label", "Photograph size");
    for (const [v, label] of [[false, "Large"], [true, "Compact"]]) {
      const b = el("button", null, label); b.type = "button";
      b.setAttribute("aria-pressed", String(!!pal.dense === v));
      b.addEventListener("click", () => { pal.dense = v; draw(); });
      view.append(b);
    }
    bar.append(refine, short, cmp, view);
    panel.append(bar);

    if (pal.refineOpen) {
      const box = el("div", "lb-refine"); box.id = "lb-refine";
      const facet = (key, title, opts) => {
        const g = el("div", "lb-facet");
        const h = el("span", "lb-facet__t", title); h.id = `lb-f-${key}`;
        const row = el("div", "lb-facet__row"); row.setAttribute("role", "group"); row.setAttribute("aria-labelledby", h.id);
        const counts = {};
        for (const d of inStyle) { const f = facetsOf(d, s)[key]; for (const v of [].concat(f)) counts[v] = (counts[v] || 0) + 1; }
        for (const [v, label, paint] of opts) {
          if (!counts[v] && !F[key].includes(v)) continue;
          const b = el("button", "lb-facet__opt"); b.type = "button";
          b.setAttribute("aria-pressed", String(F[key].includes(v)));
          if (paint) b.append(paint());
          b.append(el("span", null, label), el("small", null, String(counts[v] || 0)));
          b.addEventListener("click", () => {
            F[key] = F[key].includes(v) ? F[key].filter((x) => x !== v) : [...F[key], v];
            draw();
            card.querySelector(`#lb-f-${key} + .lb-facet__row button:nth-of-type(${[...row.children].indexOf(b) + 1})`)?.focus({ preventScroll: true });
          });
          row.append(b);
        }
        g.append(h, row);
        box.append(g);
      };
      const roofIcon = (v) => () => { const i = pathIcon(ROOF_ICON[v] || "", "lb-facet__icon"); return i; };
      facet("roof", "Roof", ["flat", "slab", "mono", "butterfly", "hip", "gable", "vault", "sawtooth"].map((v) => [v, EX_NICE[v], roofIcon(v)]));
      facet("walls", "Walls", Object.keys(FINISH_OF).map((v) => [v, EX_NICE[v] || v, () => {
        const c = texSwatch(FINISH_OF[v][0], FINISH_OF[v][1], 22); c.className = "lb-facet__sw"; c.setAttribute("aria-hidden", "true"); return c; }]));
      facet("mood", "Colour mood", MOODS.map(([v, label]) => [v, label]));
      if (active) {
        const clr = el("button", "pal__clr", "Clear all"); clr.type = "button";
        clr.addEventListener("click", () => { pal.facets = { roof: [], walls: [], mood: [] }; draw(); });
        box.append(clr);
      }
      panel.append(box);
    }

    const from = pal.style ? styleName(pal.style) : own;
    const said = el("p", "lb-count");
    said.append(`${shown.length === inStyle.length ? shown.length : `${shown.length} of ${inStyle.length}`} ${from ? `${from.toLowerCase()} ` : ""}designs`);
    if (heard.length) said.append(`, following your brief: ${heard.join(", ")}`);
    if (pal.tint) {
      said.append(`. Shown in ${pal.tint.name} colours, `);
      const clr = el("button", "pal__clr", "use each design's own"); clr.type = "button";
      clr.addEventListener("click", () => { pal.tint = null; draw(); rebuild(); });
      said.append(clr);
    }
    panel.append(said);

    // Narrowed to nothing, or to a few: design more that match.
    const words = [...F.roof.map((v) => `${v} roof`), ...F.walls.map((v) => `${v} walls`),
      ...F.mood.map((v) => ({ light: "light colours", earthy: "earthy colours", cool: "grey and blue colours", colourful: "colourful", dark: "dark colours" })[v])].join(", ");
    const moreLike = async (btn) => {
      btn.disabled = true; btn.textContent = "Designing…";
      await loadMore(24, pal.style || "", words);
      draw();
    };
    if (!shown.length) {
      const empty = el("div", "lb-empty");
      empty.append(el("p", null, pal.shortOnly ? "Nothing on your shortlist matches. Clear the filters, or bookmark more designs." : "No designs here match all of that yet."));
      if (!pal.shortOnly && active) {
        const b = el("button", "btn", `Design 24 with ${words}`); b.type = "button";
        b.addEventListener("click", () => moreLike(b));
        empty.append(b);
      }
      panel.append(empty);
      return;
    }

    const grid = el("div", `lb-grid${pal.dense ? " lb-grid--dense" : ""}`);
    // The end of the gallery (or of the phone's sideways strip): reaching it pulls the next batch.
    const sentinel = el("span", "ex-sentinel"); sentinel.setAttribute("aria-hidden", "true");
    grid.append(sentinel);
    // The studio's pick leads, wide, when the whole collection is showing.
    const leadOne = !pal.dense && !active && !pal.shortOnly && !pal.style;
    const add = (xs) => {
      for (const d of xs) grid.insertBefore(designCard(d, s, { lead: leadOne && d === shown[0] }), sentinel);
    };
    add(shown);
    panel.append(grid);
    if (pal.shortOnly) return;
    const more = el("button", "ghost-btn ex-more", active ? `Design 24 more with ${words}` : "Design 24 more"); more.type = "button";
    const go = async () => {
      if (loading) return;
      more.disabled = true; more.textContent = "Designing…"; more.setAttribute("aria-busy", "true");
      const fresh = await loadMore(24, pal.style || "", words);
      if (active) { draw(); return; }
      add(fresh);
      more.disabled = false; more.textContent = "Design 24 more"; more.removeAttribute("aria-busy");
      const tab = card.querySelector("#ex-tab-designs"); if (tab) tab.textContent = `Designs ${designs.length}`;
      const k = card.querySelector(".ex__title .pal__k"); if (k) k.textContent = `Exterior ${idx() + 1} of ${designs.length}`;
    };
    more.addEventListener("click", go);
    panel.append(more);
    // Up to a point on a desktop, where the button keeps going after that; a
    // phone has no room for the button, so its strip just keeps coming.
    const phone = matchMedia("(max-width: 720px)");
    if (!active) new IntersectionObserver(([e]) => { if (e.isIntersecting && (designs.length < 240 || phone.matches)) go(); }).observe(sentinel);
  };

  // Colours, one surface at a time: named paints, and any colour at all.
  const SURFACES = [["wall", "Walls"], ["clad", "Cladding & stone"], ["roof_tint", "Roof"], ["metal", "Accent metal"],
    ["frame", "Window frames"], ["door", "Main door"]];
  const setTint = (f, hex, redraw = true) => {
    const d = designs[idx()];
    const p = exParse(d?.id) || {};
    const base = cardTint(d) || Object.fromEntries(TINTS.map((k) => [k, p[k] || ""]));
    pal.tint = { ...base, id: "custom", name: "Custom", [f]: hx(hex) };
    if (d) delete d.tint;                 // the Colours tab now speaks for this design
    clearTimeout(timer);
    timer = setTimeout(rebuild, redraw ? 30 : 220);
    if (redraw) draw();
  };
  const coloursPanel = (panel, s) => {
    const d = designs[idx()];
    if (!d) return skeleton(panel, 4);
    const p = exParse(d.id) || {};
    const ct = cardTint(d);               // this design's colours, wherever they were chosen
    panel.append(el("p", "lb-count", `${(grammar?.schemes || []).length} colour schemes for ${d.name}. Pick one, then fine-tune any surface below.`));
    const own = [p.wall ? `#${p.wall}` : s.exterior.plaster, s.exterior.clad, p.roof_tint ? `#${p.roof_tint}` : s.exterior.roof,
      grammar?.accents?.[p.accent] || s.exterior.frame];
    // The style's own schemes first, then every other.
    const fam = d.fam || planStyle;
    const mine = grammar?.styles?.find((x) => x.id === fam)?.schemes || [];
    const all = grammar?.schemes || [];
    const groups = [[mine.length ? `Suggested for ${styleName(fam)}` : "Colour schemes", [null, ...all.filter((x) => mine.includes(x.id))]],
      [mine.length ? "More schemes" : "", all.filter((x) => !mine.includes(x.id))]];
    // A scheme: the house photographed in it, its name, and the paint strip it is made of.
    const schemeCard = (sc) => {
      const tint = schemeTint(sc);
      const on = (ct?.id ?? null) === (sc?.id ?? null);
      const name = sc ? sc.name : "The design's own colours";
      const card_ = el("article", `lb-card cs-card${on ? " is-on" : ""}`);
      const photo = el("button", "lb-card__photo is-loading"); photo.type = "button";
      photo.setAttribute("aria-pressed", String(on));
      photo.setAttribute("aria-label", on ? `${name}, on your house` : `Put ${d.name} in ${name}`);
      const img = el("img"); img.alt = ""; img.decoding = "async";
      img.addEventListener("load", () => photo.classList.remove("is-loading"));
      photo.append(img);
      if (on) photo.append(el("span", "lb-card__on", "On your house"));
      photo._load = () => thumb(thumbUrl(tinted(d.id, tint)), front)
        .then((src) => { if (src) img.src = src; else photo.classList.replace("is-loading", "is-failed"); });
      io.observe(photo);
      photo.addEventListener("click", () => { pal.tint = tint; delete d.tint; draw(); rebuild(); });
      const body = el("div", "lb-card__body");
      const strip = el("span", "cs-strip"); strip.setAttribute("aria-hidden", "true");
      const hexes = sc ? [sc.wall, sc.clad, sc.roof, sc.metal] : own;
      for (const [hex, where] of hexes.map((h, i) => [h, ["Walls", "Cladding", "Roof", "Metal"][i]])) {
        const i = el("i"); i.style.background = hex; i.title = `${where} ${hex}`; strip.append(i);
      }
      body.append(el("h4", "lb-card__name", name), strip);
      card_.append(photo, body);
      return card_;
    };
    for (const [heading, schemesIn] of groups) {
      if (!schemesIn.length) continue;
      if (heading) panel.append(el("h4", "sp-group__t cs-head", heading));
      const grid = el("div", "lb-grid lb-grid--dense cs-grid");
      for (const sc of schemesIn) grid.append(schemeCard(sc));
      panel.append(grid);
    }

    // Every surface on its own: a row each, its paint now, opening to the paints for it.
    const fine = el("section", "sp-group cs-surfaces");
    fine.append(el("h4", "sp-group__t", ct?.id === "custom" ? "Every surface, your own mix" : "Every surface"));
    const fallback = { wall: own[0], clad: own[1], roof_tint: own[2], metal: own[3], frame: s.exterior.frame, door: s.exterior.door };
    for (const [f, title] of SURFACES) {
      const now = ct?.[f] || p[f] || "";
      const named = (grammar?.paints?.[f] || []).find((x) => hx(x.hex) === now);
      const nowName = now ? (named?.name || (ct?.[f] === now && ct.id !== "custom" ? ct.name : `#${now}`)) : "As designed";
      const open = pal.colourOpen === f;
      const row = el("div", `sp-row${open ? " is-open" : ""}`);
      const head = el("button", "sp-row__head"); head.type = "button";
      head.id = `cs-${f}`;
      head.setAttribute("aria-expanded", String(open)); head.setAttribute("aria-controls", `cs-${f}-opts`);
      const cur = el("span", "sp-row__now");
      const chip = el("i", "sp-pic cs-chip"); chip.style.background = now ? `#${now}` : (fallback[f] || "#cccccc");
      cur.append(chip, el("span", null, nowName));
      head.append(el("span", "sp-row__name", title), cur, el("span", "sp-row__chev"));
      head.addEventListener("click", () => {
        pal.colourOpen = open ? null : f;
        draw();
        card.querySelector(`#cs-${f}`)?.focus({ preventScroll: true });
      });
      row.append(head);
      if (open) {
        const opts = el("div", "sp-opts cs-paints");
        opts.id = `cs-${f}-opts`;
        opts.setAttribute("role", "radiogroup"); opts.setAttribute("aria-labelledby", head.id);
        const paint = (hex, name, checked, onPick) => {
          const b = el("button", "cs-paint"); b.type = "button";
          b.setAttribute("role", "radio"); b.setAttribute("aria-checked", String(checked));
          const sw = el("i", "cs-paint__sw"); sw.style.background = hex;
          b.append(sw, el("span", "cs-paint__name", name));
          b.addEventListener("click", onPick);
          return b;
        };
        opts.append(paint(fallback[f] || "#cccccc", "As designed", !now, () => {
          if (!now) return;
          const base = { ...(ct || {}) };
          base[f] = "";
          pal.tint = { ...Object.fromEntries(TINTS.map((k) => [k, base[k] || ""])), id: "custom", name: "Custom" };
          delete d.tint; draw(); rebuild();
        }));
        for (const { name, hex } of grammar?.paints?.[f] || []) {
          opts.append(paint(hex, name, hx(hex) === now, (e) => {
            setTint(f, hex);
            if (e.detail === 0) card.querySelector(`#cs-${f}-opts [aria-checked="true"]`)?.focus({ preventScroll: true });
          }));
        }
        // Any colour at all.
        const anyB = el("label", "cs-paint cs-paint--any");
        const inp = el("input"); inp.type = "color"; inp.name = f;
        const curHex = now ? `#${now}` : fallback[f];
        inp.value = /^#[0-9a-f]{6}$/i.test(curHex || "") ? curHex : "#cccccc";
        inp.setAttribute("aria-label", `Any ${title.toLowerCase()} colour`);
        inp.addEventListener("input", () => setTint(f, inp.value, false));
        inp.addEventListener("change", () => setTint(f, inp.value));
        anyB.append(inp, el("span", "cs-paint__name", "Any colour"));
        opts.append(anyB);
        row.append(opts);
      }
      fine.append(row);
    }
    if (ct) {
      const r = el("button", "ghost-btn pal__reset", "Back to the design's own colours"); r.type = "button";
      r.addEventListener("click", () => { pal.tint = null; delete d.tint; draw(); rebuild(); });
      fine.append(r);
    }
    panel.append(fine);
    // The whole-house palette lives here too, folded away: it colours the
    // inside as well, and the exterior colours above sit over it.
    const house = el("details", "ex-house");
    house.open = !!pal.open;
    house.addEventListener("toggle", () => { pal.open = house.open; });
    house.append(el("summary", null, `Whole-house palette, inside and out: ${s.name}`));
    const i = Math.max(0, list.findIndex((x) => x.id === pal.id));
    const nav = el("div", "pal__head");
    const strip = el("span", "pal__strip");
    for (const hex of [s.exterior.plaster, s.exterior.clad, s.exterior.roof, s.interior.living, s.interior.master, s.interior.accent_wall]) {
      const c = el("i"); c.style.background = hex; strip.append(c);
    }
    const lab = el("span", "pal__toggle");
    lab.append(el("span", "pal__k", i === 0 ? "Recommended" : `${i + 1} / ${list.length}`), el("b", "pal__name", s.name), strip);
    const arrows = el("div", "pal__nav");
    for (const [t, step, name] of [["prev", -1, "Previous palette"], ["next", 1, "Next palette"]]) {
      const bt = el("button", "ghost-btn ghost-btn--ico"); bt.type = "button"; bt.setAttribute("aria-label", name); bt.append(icon(t));
      bt.addEventListener("click", () => apply(list[(i + step + list.length) % list.length]));
      arrows.append(bt);
    }
    nav.append(lab, arrows);
    house.append(nav, el("p", "pal__story", s.story));
    for (const [title, group] of [["Exterior", s.exterior], ["Interior", s.interior]]) {
      const row = el("div", "pal__row");
      row.append(el("span", "pal__rk", title));
      const sws = el("div", "pal__sws");
      for (const [k, hex] of Object.entries(group)) sws.append(swatch(hex, LABELS[k] || k));
      row.append(sws);
      house.append(row);
    }
    const form = el("form", "pal__form");
    const input = el("input", "pal__input"); input.type = "text"; input.name = "colours"; input.maxLength = 600;
    input.placeholder = "Colours you like… e.g. sage bedrooms, navy front door, no pink";
    input.value = pal.text || "";
    input.setAttribute("aria-label", "Colours you like, in your own words");
    const goB = el("button", "ghost-btn", "Apply"); goB.type = "submit";
    form.append(input, goB);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      pal.text = input.value.trim();
      try { await fetchList(); await apply(list[0]); } catch (err) { toast(`Could not read those colours (${err.message}).`); }
    });
    house.append(form);
    panel.append(house);
  };

  // A customised design replaces the one it started from (kept for Reset);
  // each change is fitted to the plan by the server, then the model reloads
  // with the camera where it is. Rapid changes collapse into the last one.
  const edit = (di, patch) => {
    const d = designs[di];
    const wanted = exId({ ...(exParse(d.id) || {}), ...patch });
    designs[di] = { ...d, id: wanted, custom: true, orig: d.orig || d };
    pal.base = wanted;
    clearTimeout(timer);
    timer = setTimeout(() => commit(di, wanted, Object.keys(patch)[0]), 60);
  };
  const commit = async (di, wanted, focusKey) => {
    const mine = ++seq;
    try {
      const r = await fetch(`${API}/plans/${id}/exteriors/fit?design=${encodeURIComponent(wanted)}`);
      if (r.ok) {
        const x = await r.json();
        if (mine !== seq) return;
        designs[di] = { ...x.design, custom: true, orig: designs[di].orig };
        pal.base = x.design.id;
        pal.notes = x.notes;
      }
    } catch { /* the model endpoint fits the design itself */ }
    if (mine !== seq) return;
    const scroll = card.querySelector(".ex-panel")?.scrollTop;
    const inSheet = !!card.querySelector(".sp")?.contains(document.activeElement);
    draw();
    if (inSheet && pal.specOpen) card.querySelector(`#sp-${pal.specOpen}-opts [aria-checked="true"]`)?.focus({ preventScroll: true });
    const panel = card.querySelector(".ex-panel"); if (panel && scroll != null) panel.scrollTop = scroll;
    if (lastGroup) card.querySelector(`[aria-labelledby="${lastGroup}"] [aria-pressed="true"]`)?.focus({ preventScroll: true });
    rebuild();
  };
  // Roof silhouettes, drawn small, so the choice reads before the label.
  const ROOF_ICON = { flat: "M5 20V10h14v10M4 10V8h16v2", slab: "M5 20v-9h14v9M2 10.5h20", mono: "M5 20v-8l14-4v12M3 12.6l18-5.2",
    butterfly: "M5 20V9l7 3 7-3v11M3 8.4l9 3.8 9-3.8", hip: "M5 20v-8h14v8M3 12l5-5h8l5 5z", gable: "M5 20v-9h14v9M3 11.5L12 4l9 7.5",
    vault: "M5 20v-8h14v8M3 12c0-6.5 18-6.5 18 0", sawtooth: "M5 20v-8h14v8M3 12l6-4v4l6-4v4l6-4v4" };
  const FINISH = { plaster: ["plaster", "#e9e2d4"], stone: ["stone", "#9a8a76"], brick: ["brick", "#9a5238"], concrete: ["concrete", "#a9a7a1"],
    timber: ["timber", "#8a5a34"], metal: ["seam", "#3a3b3d"], terracotta: ["tiles", "#b0613f"], acp: ["acpanel", "#8f9296"],
    slate: ["slate", "#56585b"], glass: ["curtain", "#33424c"], corten: ["corten", "#7a3d1f"] };
  const PANEL = { none: ["plaster", "#e9e2d4"], stone: FINISH.stone, timber: FINISH.timber, slate: FINISH.slate,
    terracotta: FINISH.terracotta, acp: FINISH.acp, brick: FINISH.brick, corten: FINISH.corten };
  const DRIVE = { stone: ["paving", "#a29a8c"], concrete: ["concrete", "#a9a7a1"], gravel: ["gravel", "#b7aa94"], grass: ["grass", "#6f8a4f"] };
  // Every choice the customise tab offers, grouped the way a client thinks
  // about a house: the top, the walls, the openings, the way in, the plot.
  // An option's first value is the house's own, so the id leaves it out.
  const OPTIONS = {
    roof: ["Roof", null], solar: ["Solar panels", [["off", "None"], ["on", "On the roof"]]],
    feature: ["Signature element", null],
    base: ["Ground floor", null], upper: ["Upper floors", null],
    windows: ["Glazing", null], shade: ["Window shades", [["slim", "Slim chajja"], ["deep", "Deep chajja"], ["box", "Box frames"], ["none", "None"]]],
    screen: ["Sun screen", null],
    canopy: ["Entrance canopy", [["slab", "Concrete"], ["glass", "Glass"], ["pergola", "Pergola"], ["none", "None"]]],
    railing: ["Balcony railings", [["glass", "Glass"], ["metal", "Metal"], ["solid", "Solid wall"]]],
    boundary: ["Boundary wall", [["plaster", "Plaster"], ["stone", "Stone"], ["brick", "Brick"], ["hedge", "Hedge"], ["grille", "Grille"]]],
    gate: ["Gate", [["none", "Open"], ["sliding", "Steel sliding"], ["timber", "Timber"]]],
    garage: ["Garage", [["open", "Open car porch"], ["closed", "Closed, rolling shutter"]]],
    paving: ["Driveway", [["stone", "Stone pavers"], ["concrete", "Concrete"], ["gravel", "Gravel"], ["grass", "Grass pavers"]]],
    garden: ["Garden", [["standard", "Standard"], ["lush", "Lush"], ["minimal", "Minimal"], ["none", "Paved"]]],
    planters: ["Planters", [[false, "None"], [true, "Along the front"]]],
    panel: ["Feature panel", [["none", "None"], ["stone", "Stone"], ["timber", "Wood-look"], ["slate", "Slate"],
      ["terracotta", "Terracotta"], ["acp", "ACP"], ["brick", "Brick"], ["corten", "Corten"]]],
    parapet: ["Parapet", [["plain", "Plain"], ["glass", "Glass strip"], ["grooved", "Grooved"], ["screen", "CNC screen"], ["stepped", "Stepped"]]],
    deck: ["Roof terrace", [["none", "Open"], ["pergola", "Pergola"], ["garden", "Roof garden"]]],
    lights: ["Facade lighting", [["none", "None"], ["washers", "Wall washers"], ["strips", "LED strips"]]],
    yard: ["Garden feature", [["none", "None"], ["tulsi", "Tulsi platform"], ["jhoola", "Jhoola swing"], ["waterwall", "Water wall"],
      ["koipond", "Koi pond"], ["gazebo", "Gazebo"], ["rockgarden", "Rock garden"], ["sitout", "Sit-out"],
      ["fountain", "Fountain"], ["firepit", "Fire pit"], ["lounge", "Lounge deck"], ["flowerbeds", "Flower beds"]]],
    accent: ["Accent", null],
  };
  // The specification: every element of the outside as one row - its name,
  // what it is now, drawn - grouped the way an architect lists a house's
  // finishes. A row opens in place to show its choices; one at a time.
  const GROUPS = [["The roof", ["roof", "parapet", "deck", "solar"]],
    ["Walls", ["base", "upper", "panel", "accent"]],
    ["Windows and the street face", ["windows", "shade", "screen", "feature"]],
    ["The way in", ["canopy", "railing", "lights", "garage"]],
    ["Around the house", ["boundary", "gate", "paving", "garden", "yard", "planters", "pool", "poolPlace"]]];
  const BOUND = { plaster: FINISH.plaster, stone: FINISH.stone, brick: FINISH.brick, hedge: ["lawn", "#56703f"], grille: ["seam", "#3a3b3d"] };
  const GARDEN = { standard: ["lawn", "#6f8a4f"], lush: ["lawn", "#4f6b3a"], minimal: ["gravel", "#b7aa94"], none: ["paving", "#a29a8c"] };
  const POOLS_UI = [["none", "No pool"], ["plunge", "Plunge pool, 3 × 6 m"], ["family", "Family pool, 4 × 8 m"], ["lap", "Lap pool, 2.5 × 14 m"]];
  const POOL_PLACES_UI = [["rear", "Behind the house, centred"], ["side", "Beside the house"], ["northeast", "In the north-east, for Vastu"], ["corner", "In the far corner"]];
  // Move, resize or remove the pool: a change to the plan itself, so the
  // drawings, the Vastu and the model all see the same garden.
  const editPool = async (op, row) => {
    row?.classList.add("is-busy");
    try {
      const r = await fetch(`${API}/plans/${id}/edit`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ops: [{ op: "pool", ...op }] }) });
      const x = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(x.detail || `HTTP ${r.status}`);
      toast(x.applied?.[0] || "Pool changed");
      await adoptEdited(x.plan_id);
    } catch (e) {
      row?.classList.remove("is-busy");
      toast(`The pool could not be changed: ${e.message}`);
    }
  };
  const customiser = (panel, di) => {
    const d = designs[di];
    const now = d && exParse(d.id);
    if (!now || !grammar) return skeleton(panel, 2);
    const plan = S.plans[id]?.plan;
    const one = (plan?.levels?.length || 1) <= 1;
    const flatRoof = now.roof === "flat" || now.roof === "slab";
    const site = plan?.site || {};
    const hasGarage = (plan?.levels || []).some((lv) => (lv.rooms || []).some((r) => r.type === "garage"));
    const ROWS = {
      ...Object.fromEntries(Object.entries(OPTIONS).map(([k, [name, opts]]) => [k, { name, opts }])),
      pool: { name: "Pool", opts: POOLS_UI },
      poolPlace: { name: "Pool position", opts: POOL_PLACES_UI },
    };
    const choices = (key) => ROWS[key].opts
      || (key === "accent" ? Object.keys(grammar.accents || {}).map((k) => [k, k[0].toUpperCase() + k.slice(1)])
        : (grammar[key] || []).map((v) => [v, EX_NICE[v] || v]));
    // An option left out of the id is its first value.
    const value = (key) => {
      // The pool as built: a brief's pool too big for the plot is placed smaller.
      if (key === "pool") return poolNow?.kind || (pools ? "none" : site.pool || "none");
      if (key === "poolPlace") return poolNow?.place || site.pool_place || "rear";
      return now[key] === undefined || now[key] === "" ? choices(key)[0][0] : now[key];
    };
    const label = (key) => (choices(key).find(([v]) => v === value(key)) || [, ""])[1];
    // What each choice looks like, drawn small: a roof's silhouette, a real texture, a colour.
    const roofPic = (v) => {
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true"); svg.classList.add("sp-pic", "sp-pic--line");
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", ROOF_ICON[v] || ""); svg.append(path);
      return svg;
    };
    const texPic = (map, tintOf) => (v, size) => {
      const [kind, hex] = map[v] || Object.values(map)[0];
      const t = tintOf?.(v);
      const c = texSwatch(kind, t ? `#${t}` : hex, size); c.className = "sp-pic"; c.setAttribute("aria-hidden", "true");
      return c;
    };
    const wallTint = (v) => (v === "plaster" ? (pal.tint?.wall || now.wall) : (pal.tint?.clad || now.clad));
    const PIC = {
      roof: roofPic, base: texPic(FINISH, wallTint), upper: texPic(FINISH, wallTint), panel: texPic(PANEL),
      paving: texPic(DRIVE), boundary: texPic(BOUND), garden: texPic(GARDEN),
      accent: (v) => { const i = el("i", "sp-pic sp-pic--dot"); i.style.background = grammar.accents[v]; return i; },
    };
    // Why a choice is not open to this house, said where it is offered.
    const WHY = {
      upper: (v) => one && v !== "plaster" && "This house has one storey.",
      feature: (v) => one && ["jharokha", "balcony", "bay", "floatbox", "cornerglass", "cantilever", "planterbands"].includes(v) && "Needs an upper floor.",
      solar: (v) => v === "on" && !flatRoof && "Needs a flat or slab roof.",
      parapet: (v) => v !== "plain" && now.roof !== "flat" && "Needs a flat roof.",
      deck: (v) => v !== "none" && now.roof !== "flat" && "Needs a flat roof.",
      pool: (v) => v !== "none" && pools && !(pools[v] || []).length && "Too big for the open ground round this house.",
      poolPlace: (v) => pools && value("pool") !== "none" && !(pools[value("pool")] || []).includes(v) && "No room for this pool there.",
    };
    const pick = (key, v, row) => {
      if (key === "pool") return editPool({ kind: v }, row);
      if (key === "poolPlace") return editPool({ place: v }, row);
      if (key === "accent" && pal.tint?.metal) pal.tint = { ...pal.tint, id: "custom", name: "Custom", metal: "" };
      // The house's own value stays out of the id, keeping it short.
      const first = choices(key)[0][0];
      const store = ROWS[key].opts && key !== "planters" && v === first ? "" : v;
      edit(di, { [key]: store });
    };
    const shows = (key) => (key !== "garage" || hasGarage) && (key !== "poolPlace" || value("pool") !== "none");
    const sheet = el("div", "sp");
    for (const [title, keys] of GROUPS) {
      const rows = keys.filter(shows);
      if (!rows.length) continue;
      const grp = el("section", "sp-group");
      grp.append(el("h4", "sp-group__t", title));
      for (const key of rows) {
        const open = pal.specOpen === key;
        const row = el("div", `sp-row${open ? " is-open" : ""}`);
        const head = el("button", "sp-row__head"); head.type = "button";
        head.id = `sp-${key}`;
        head.setAttribute("aria-expanded", String(open)); head.setAttribute("aria-controls", `sp-${key}-opts`);
        const cur = el("span", "sp-row__now");
        if (PIC[key]) cur.append(PIC[key](value(key), 26));
        cur.append(el("span", null, label(key)));
        head.append(el("span", "sp-row__name", ROWS[key].name), cur, el("span", "sp-row__chev"));
        head.addEventListener("click", () => {
          pal.specOpen = open ? null : key;
          draw();
          card.querySelector(`#sp-${key}`)?.focus({ preventScroll: true });
        });
        row.append(head);
        if (open) {
          const visual = !!PIC[key];
          const opts = el("div", `sp-opts${visual ? " sp-opts--tiles" : ""}`);
          opts.id = `sp-${key}-opts`;
          opts.setAttribute("role", "radiogroup"); opts.setAttribute("aria-labelledby", head.id);
          for (const [v, name] of choices(key)) {
            const why = WHY[key]?.(v);
            const b = el("button", visual ? "sp-tile" : "sp-opt"); b.type = "button";
            b.setAttribute("role", "radio"); b.setAttribute("aria-checked", String(v === value(key)));
            b.disabled = !!why;
            if (visual) b.append(PIC[key](v, 64));
            b.append(el("span", "sp-opt__name", name));
            if (why) b.append(el("small", "sp-opt__why", why));
            b.addEventListener("click", () => {
              if (v === value(key)) return;
              pick(key, v, row);
              card.querySelector(`#sp-${key}`)?.focus({ preventScroll: true });
            });
            opts.append(b);
          }
          row.append(opts);
        }
        grp.append(row);
      }
      sheet.append(grp);
    }
    panel.append(sheet);
    const notes = el("p", "pal__why pal__notes", (pal.notes || []).join(" ")); notes.setAttribute("aria-live", "polite");
    panel.append(notes);
    if (d.orig) {
      const r = el("button", "ghost-btn pal__reset", `Reset to ${d.orig.name}`); r.type = "button";
      r.addEventListener("click", () => { designs[di] = d.orig; choose(d.orig.id); });
      panel.append(r);
    }
  };

  // ── parts: point at any part of the house, see its name, paint it ────
  // The model names every mesh by its part (arch3d), the grammar labels the
  // parts (exteriors.PARTS), and a part's colour rides in the design id, so
  // the elevations and the gallery see the same paint as the 3D view.
  const partInfo = (k) => grammar?.parts?.find((x) => x.key === k) || null;
  const paintOf = (k) => (exParse(designs[idx()]?.id) || {}).paints?.[k];
  const paintPart = (k, hex) => {
    const di = idx(), d = designs[di];
    if (!d) return;
    const paints = { ...((exParse(d.id) || {}).paints || {}) };
    if (hex) paints[k] = hex.replace("#", "").toLowerCase(); else delete paints[k];
    edit(di, { paints });
  };
  let picker = null;
  const setupPicker = () => {
    const v = viewer();
    if (!page || !v || picker?.v === v) return;
    const host = v.host, canvas = v.renderer.domElement;
    const tip = el("div", "exw-tip"); tip.hidden = true; tip.setAttribute("role", "status");
    const editor = el("div", "exw-edit"); editor.hidden = true;
    const tags = el("div", "exw-tags"); tags.hidden = true; tags.setAttribute("aria-hidden", "true");
    const bar = el("div", "exw-bar");
    const labelsBtn = el("button", "exw-btn", "Label parts"); labelsBtn.type = "button"; labelsBtn.setAttribute("aria-pressed", "false");
    const listBtn = el("button", "exw-btn", "All parts"); listBtn.type = "button"; listBtn.setAttribute("aria-expanded", "false");
    const list = el("div", "exw-list"); list.hidden = true;
    bar.append(labelsBtn, listBtn);
    const hint = el("p", "exw-hint", "Point at any part to see its name · click it to change its colour");
    host.append(tags, tip, editor, bar, list, hint);
    let editing = null, down = null, raf = 0;
    const light = (k) => v.highlight(k || editing);
    const openEditor = (k) => {
      const info = partInfo(k);
      if (!info) return;
      editing = k; light(k);
      editor.hidden = false; editor.innerHTML = "";
      const head = el("div", "exw-edit__head");
      const name = el("div");
      name.append(el("b", null, info.label), el("span", null, info.group));
      const x = el("button", "exw-edit__x"); x.type = "button"; x.setAttribute("aria-label", "Close"); x.append(icon("close"));
      x.addEventListener("click", closeEditor);
      head.append(name, x);
      const nowHex = paintOf(k) ? `#${paintOf(k)}` : (v.parts().get(k) || "#cccccc");
      const now = el("div", "exw-edit__now");
      const sw = el("i"); sw.style.background = nowHex;
      now.append(sw, el("span", null, paintOf(k) ? `Painted ${nowHex}` : "The design's own colour"));
      const grid = el("div", "exw-edit__grid"); grid.setAttribute("role", "listbox"); grid.setAttribute("aria-label", `Colours for the ${info.label.toLowerCase()}`);
      const seen = new Set();
      const groups = info.group === "Roof" ? ["roof_tint", "wall", "clad"] : info.group === "Windows and doors" ? ["frame", "door", "metal", "wall"]
        : info.group === "Outside" ? ["clad", "wall", "metal", "door"] : info.group === "Trims" ? ["metal", "wall", "clad"] : ["wall", "clad", "metal"];
      for (const g of groups) for (const c of grammar?.paints?.[g] || []) {
        const hx = c.hex.toLowerCase();
        if (seen.has(hx)) continue;
        seen.add(hx);
        const b = el("button", "exw-sw"); b.type = "button"; b.style.background = hx; b.title = c.name;
        b.setAttribute("role", "option"); b.setAttribute("aria-label", c.name);
        b.setAttribute("aria-selected", String(paintOf(k) === hx.slice(1)));
        b.addEventListener("click", () => paintPart(k, hx));
        grid.append(b);
      }
      const any = el("label", "exw-edit__any");
      const input = el("input"); input.type = "color"; input.value = nowHex.length === 7 ? nowHex : "#cccccc";
      input.addEventListener("change", () => paintPart(k, input.value));
      any.append(input, el("span", null, "Any colour"));
      const foot = el("div", "exw-edit__foot");
      foot.append(any);
      if (paintOf(k)) {
        const reset = el("button", "ghost-btn", "Design's own colour"); reset.type = "button";
        reset.addEventListener("click", () => paintPart(k, null));
        foot.append(reset);
      }
      editor.append(head, now, grid, foot);
      // The colours run in one row: bring the part's own into view.
      grid.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest", inline: "center" });
    };
    const closeEditor = () => { editing = null; editor.hidden = true; light(null); };
    // The tags: one per part, at the middle of its largest piece, kept clear of each other.
    const placeTags = () => {
      if (tags.hidden || !v.model) return;
      const r = host.getBoundingClientRect(), placed = [];
      for (const t of tags.children) {
        const p = t._at.clone().project(v.camera);
        const x = (p.x + 1) / 2 * r.width, y = (1 - p.y) / 2 * r.height;
        const w = t.offsetWidth || 80, h = 20;
        const clash = p.z > 1 || x < 0 || y < 0 || x > r.width || y > r.height
          || placed.some(([a, b]) => Math.abs(a - x) < (w + 60) / 2 && Math.abs(b - y) < h);
        t.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
        t.hidden = clash;
        if (!clash) placed.push([x, y]);
      }
    };
    const buildTags = () => {
      tags.innerHTML = "";
      if (tags.hidden || !v.model) return;
      const best = new Map();
      v.model.traverse((o) => {
        if (!o.isMesh || !o.visible) return;
        const k = o.name.split("__").pop();
        if (!partInfo(k)) return;
        const box = new v.THREE.Box3().setFromObject(o);
        const size = box.getSize(new v.THREE.Vector3()).length();
        if (!best.has(k) || best.get(k).size < size) best.set(k, { size, at: box.getCenter(new v.THREE.Vector3()) });
      });
      // Bigger parts first, so the walls and roof always get their tag.
      for (const [k, { at }] of [...best].sort((a, b) => b[1].size - a[1].size)) {
        const t = el("button", "exw-tag", partInfo(k).label); t.type = "button"; t._at = at; t.tabIndex = -1;
        t.addEventListener("click", () => openEditor(k));
        t.addEventListener("pointerenter", () => light(k));
        t.addEventListener("pointerleave", () => light(null));
        tags.append(t);
      }
      requestAnimationFrame(placeTags);
    };
    v.controls.addEventListener("change", () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(placeTags); });
    labelsBtn.addEventListener("click", () => {
      tags.hidden = !tags.hidden;
      labelsBtn.setAttribute("aria-pressed", String(!tags.hidden));
      labelsBtn.textContent = tags.hidden ? "Label parts" : "Hide labels";
      buildTags();
    });
    // Every part in the model, grouped, with the colour it wears.
    const buildList = () => {
      list.innerHTML = "";
      const have = v.parts();
      const byGroup = new Map();
      for (const p of grammar?.parts || []) if (have.has(p.key)) (byGroup.get(p.group) || byGroup.set(p.group, []).get(p.group)).push(p);
      for (const [g, ps] of byGroup) {
        list.append(el("span", "exw-list__g", g));
        for (const p of ps) {
          const row = el("button", "exw-list__row"); row.type = "button";
          const sw = el("i"); sw.style.background = paintOf(p.key) ? `#${paintOf(p.key)}` : have.get(p.key);
          row.append(sw, el("span", null, p.label), el("small", null, paintOf(p.key) ? "painted" : ""));
          row.addEventListener("pointerenter", () => light(p.key));
          row.addEventListener("pointerleave", () => light(null));
          row.addEventListener("click", () => openEditor(p.key));
          list.append(row);
        }
      }
    };
    listBtn.addEventListener("click", () => {
      list.hidden = !list.hidden;
      listBtn.setAttribute("aria-expanded", String(!list.hidden));
      if (!list.hidden) buildList();
    });
    canvas.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
    canvas.addEventListener("pointermove", (e) => {
      if (e.buttons) { tip.hidden = true; return; }
      const hit = v.partAt(e.clientX, e.clientY), info = hit && partInfo(hit.key);
      canvas.style.cursor = info ? "pointer" : "";
      if (!info) { tip.hidden = true; light(null); return; }
      const r = host.getBoundingClientRect();
      tip.hidden = false;
      tip.textContent = `${info.label} · click to change its colour`;
      tip.style.left = `${Math.min(e.clientX - r.left + 14, r.width - 220)}px`;
      tip.style.top = `${e.clientY - r.top + 16}px`;
      light(hit.key);
    });
    canvas.addEventListener("pointerleave", () => { tip.hidden = true; light(null); });
    canvas.addEventListener("click", (e) => {
      if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
      const hit = v.partAt(e.clientX, e.clientY);
      if (hit && partInfo(hit.key)) openEditor(hit.key); else closeEditor();
    });
    picker = {
      v,
      // After each rebuild: the new model's part lit again, the editor and labels current.
      refresh() {
        v._lit = undefined; light(null);
        if (editing) openEditor(editing);
        if (!tags.hidden) buildTags();
        if (!list.hidden) buildList();
      },
    };
  };

  // ── the design chat: say what to change ─────────────────────────────
  const CHAT_IDEAS = ["Paint the boundary wall charcoal", "Make the gate teak", "A hip roof with Mangalore red tiles",
    "Jaali on the upper floor", "Window frames black and the main door walnut", "Put the gate back to its own colour"];
  const chatPanel = (panel, di) => {
    const log = (pal.chat ||= []);
    panel.append(el("p", "ex__hint", "Tell the designer what to change, naming parts as they are labelled in 3D (point at a part, or press Label parts). It uses the same AI as the home-page chat."));
    const box = el("div", "exc-log"); box.setAttribute("role", "log"); box.setAttribute("aria-live", "polite");
    if (!log.length) box.append(el("p", "exc-empty", "For example:"));
    for (const m of log) {
      const b = el("div", `exc-msg exc-msg--${m.role}`);
      b.append(el("p", null, m.text));
      if (m.changed?.length) {
        const ul = el("ul", "exc-changes");
        for (const c of m.changed) ul.append(el("li", null, c));
        b.append(ul);
      }
      if (m.by) b.append(el("small", null, m.by === "rules" ? "answered offline (no AI key reachable)" : `answered by ${m.by}`));
      box.append(b);
    }
    if (pal.chatBusy) box.append(el("div", "exc-msg exc-msg--assistant is-busy", "Changing the design…"));
    panel.append(box);
    if (!log.length || log.length < 2) {
      const ideas = el("div", "ex-chips exc-ideas");
      for (const t of CHAT_IDEAS) {
        const c = el("button", "chip", t); c.type = "button";
        c.addEventListener("click", () => send(t));
        ideas.append(c);
      }
      panel.append(ideas);
    }
    const form = el("form", "exc-form");
    const input = el("input"); input.type = "text"; input.placeholder = "e.g. paint the boundary wall grey stone";
    input.setAttribute("aria-label", "What to change"); input.maxLength = 800; input.value = pal.chatDraft || "";
    input.addEventListener("input", () => { pal.chatDraft = input.value; });
    const go = el("button", "btn", "Send"); go.type = "submit"; go.disabled = !!pal.chatBusy;
    form.append(input, go);
    form.addEventListener("submit", (e) => { e.preventDefault(); if (input.value.trim()) send(input.value.trim()); });
    panel.append(form);
    requestAnimationFrame(() => { box.scrollTop = box.scrollHeight; if (pal.chatFocus) input.focus(); });
    const send = async (text) => {
      if (pal.chatBusy) return;
      const d = designs[di];
      if (!d) return;
      log.push({ role: "user", text });
      pal.chatBusy = true; pal.chatDraft = ""; pal.chatFocus = true;
      draw();
      try {
        const r = await fetch(`${API}/plans/${id}/exteriors/chat`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ design: pal.design || d.id, message: text, history: log.slice(-7, -1).map(({ role, text: t }) => ({ role, text: t })),
            parts: [...(viewer()?.parts().keys() || [])] }),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const x = await r.json();
        log.push({ role: "assistant", text: x.reply, changed: x.changed, by: x.by });
        if (x.changed?.length && x.design?.id) {
          // The chat's design keeps its own colours: the card's scheme is already in it.
          designs[di] = { ...x.design, custom: true, orig: d.orig || d, tint: null, fam: d.fam };
          pal.base = x.design.id; pal.notes = x.notes || [];
          pal.chatBusy = false;
          draw(); rebuild();
          return;
        }
      } catch (e) {
        log.push({ role: "assistant", text: `The designer could not be reached (${e.message}).` });
      }
      pal.chatBusy = false;
      draw();
    };
  };

  const TABS = [["designs", "Designs"], ["colours", "Colours"], ["customise", "Customise"], ["chat", "Ask AI"]];
  const draw = () => {
    const s = list[Math.max(0, list.findIndex((x) => x.id === pal.id))];
    if (!s) return;
    const keep = card.querySelector(".ex-panel")?.scrollTop || 0;
    card.hidden = false; card.innerHTML = "";
    const min = !page && pal.min;
    card.className = `pal ex${page ? " ex--page" : ""}${min ? " is-min" : ""}${live ? " is-live" : ""}`;
    // On the Exterior page the panel folds to a slim rail, giving the house the room.
    if (page) {
      const wrap = card.closest(".exw");
      wrap?.classList.toggle("is-min", !!pal.pageMin);
      if (pal.pageMin) {
        card.classList.add("is-rail");
        const open = el("button", "ex-rail__open"); open.type = "button"; open.append(icon("next"));
        open.setAttribute("aria-label", "Show the design panel"); open.setAttribute("aria-expanded", "false");
        open.title = "Show the design panel";
        open.addEventListener("click", () => { pal.pageMin = false; draw(); card.querySelector(".ex-rail__min")?.focus(); });
        const dd = designs[idx()];
        const name = el("span", "ex-rail__name", dd ? dd.name : "Exterior designs");
        name.addEventListener("click", () => open.click());
        card.append(open, name);
        return;
      }
    }
    pal.tab ||= "designs";
    const di = idx(), d = designs[di];
    if (d && d.id === pal.base) pal.baseCard = { id: d.id, name: d.name, story: d.story, fam: d.fam, custom: d.custom, look: d.look };
    const head = el("div", "ex__head");
    const title = el("div", "ex__title");
    title.append(el("span", "pal__k", d ? `Exterior ${di + 1} of ${designs.length}${d.custom ? " · customised" : ""}` : "Exterior designs"),
      el("b", "pal__name", d ? d.name : "Composing…"));
    if (d?.story) title.title = d.story;
    const badge = d && uniqBadge();
    if (badge) title.append(badge);
    const nav = el("div", "pal__nav");
    for (const [t, step, name] of [["prev", -1, "Previous design"], ["next", 1, "Next design"]]) {
      const bt = el("button", "ghost-btn ghost-btn--ico"); bt.type = "button"; bt.setAttribute("aria-label", name); bt.disabled = !d; bt.append(icon(t));
      bt.addEventListener("click", () => choose(designs[(di + step + designs.length) % designs.length].id));
      nav.append(bt);
    }
    if (page) {
      const mb = el("button", "ghost-btn ghost-btn--ico ex-rail__min"); mb.type = "button"; mb.append(icon("collapse"));
      mb.setAttribute("aria-label", "Minimise the design panel"); mb.setAttribute("aria-expanded", "true");
      mb.title = "Minimise the design panel";
      mb.addEventListener("click", () => { pal.pageMin = true; draw(); card.querySelector(".ex-rail__open")?.focus(); });
      nav.append(mb);
    }
    if (!page) {
      const mb = el("button", "ghost-btn ghost-btn--ico"); mb.type = "button"; mb.append(icon(pal.min ? "plus" : "minus"));
      mb.setAttribute("aria-label", pal.min ? "Show exterior designs" : "Minimise exterior designs");
      mb.setAttribute("aria-expanded", String(!pal.min));
      mb.addEventListener("click", () => { pal.min = !pal.min; draw(); });
      nav.append(mb);
    }
    head.append(title, nav);
    card.append(head);
    if (min) return;
    if (d?.story) card.append(el("p", "pal__story ex__story", d.story));
    const tabs = el("div", "ex__tabs"); tabs.setAttribute("role", "tablist"); tabs.setAttribute("aria-label", "Exterior");
    TABS.forEach(([k, label], n) => {
      const b = el("button", "ex__tab", k === "designs" && designs.length ? `${label} ${designs.length}` : label);
      b.type = "button"; b.id = `ex-tab-${k}`; b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", String(pal.tab === k)); b.setAttribute("aria-controls", "ex-panel");
      b.tabIndex = pal.tab === k ? 0 : -1;
      b.addEventListener("click", (e) => { pal.tab = k; draw(); if (e.detail === 0) card.querySelector(`#ex-tab-${k}`)?.focus(); });
      b.addEventListener("keydown", (e) => {
        const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!step) return;
        e.preventDefault();
        const nk = TABS[(n + step + TABS.length) % TABS.length][0];
        pal.tab = nk; draw(); card.querySelector(`#ex-tab-${nk}`)?.focus();
      });
      tabs.append(b);
    });
    card.append(tabs);
    const panel = el("div", "ex-panel"); panel.id = "ex-panel";
    panel.setAttribute("role", "tabpanel"); panel.setAttribute("aria-labelledby", `ex-tab-${pal.tab}`);
    if (pal.tab === "colours") coloursPanel(panel, s);
    else if (pal.tab === "customise") customiser(panel, di);
    else if (pal.tab === "chat") chatPanel(panel, di);
    else designsPanel(panel, s);
    card.append(panel);
    if (lastTab === pal.tab) panel.scrollTop = keep;
    lastTab = pal.tab;
    const on = panel.querySelector(".ex-chips--scroll [aria-pressed='true']");
    if (on) on.parentElement.scrollLeft = on.offsetLeft - on.parentElement.offsetLeft - 8;
  };
  try {
    await fetchList();
    if (!pal.id || !list.some((x) => x.id === pal.id)) pal.id = list[0]?.id;
    draw();
    start();
  } catch { card.hidden = true; }
}

/* ── air: the breeze through each floor, solved and set moving ─────── */

const WINDS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

async function renderAir() {
  S.air?.dispose();
  S.air = null;
  const p = pane("air"); p.innerHTML = "";
  const id = S.activeId;
  const levels = cur().plan?.levels || [];
  const st = (S.airState ||= { level: 0, wind: null, doors: true, mode: "breeze" });
  if (!levels.some((lv) => lv.index === st.level)) st.level = levels[0]?.index ?? 0;

  // Two readings of the same air: where the breeze goes, and how warm each
  // room gets through the day.
  const modes = el("div", "air-modes"); modes.setAttribute("role", "tablist"); modes.setAttribute("aria-label", "Air");
  for (const [m, name] of [["breeze", "Breeze"], ["heat", "Temperature"]]) {
    const b = el("button", null, name); b.type = "button"; b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", String(st.mode === m));
    b.addEventListener("click", () => { if (st.mode !== m) { st.mode = m; renderAir(); } });
    modes.append(b);
  }
  const floors = el("div", "sheet-groups"); floors.setAttribute("role", "tablist");
  for (const lv of levels) {
    const b = el("button", null, floorName(lv.index)); b.type = "button"; b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", String(lv.index === st.level));
    b.addEventListener("click", () => { st.level = lv.index; renderAir(); });
    floors.append(b);
  }

  if (st.mode === "heat") {
    const bar = el("div", "pane__bar");
    bar.append(modes, floors);
    const body = el("div", "air-heat");
    p.append(bar, body);
    const { ThermalView } = await import("./thermal.js?v=t6");
    if (S.view !== "air" || S.activeId !== id) return;
    const th = (S.airHeat ||= { season: "summer", windows: "open", fans: true, cool_roof: false, chajja: 0.6 });
    S.air = new ThermalView(body, { api: API, planId: id, level: st.level, state: th });
    return;
  }

  const bar = el("div", "pane__bar");
  const rose = el("div", "air-rose"); rose.setAttribute("role", "radiogroup"); rose.setAttribute("aria-label", "Wind from");
  rose.append(el("span", "air-rose__label", "Wind from"));
  const tools = el("div", "pane__tools");
  const doors = el("button", "ghost-btn", st.doors ? "Doors open" : "Doors shut"); doors.type = "button";
  doors.setAttribute("aria-pressed", String(st.doors));
  doors.addEventListener("click", () => { st.doors = !st.doors; renderAir(); });
  const best = el("button", "ghost-btn", "Best wind"); best.type = "button";
  best.title = "Solve the floor for all eight winds and rank them";
  const play = el("button", "ghost-btn", "Pause"); play.type = "button";
  tools.append(doors, best, play);
  bar.append(modes, floors, rose, tools);
  const stage = el("div", "model-stage air-stage");
  const cap = el("p", "model-cap", "Solving the breeze…");
  const rank = el("div", "air-rank"); rank.hidden = true;
  p.append(bar, stage, rank);

  const { AirflowView } = await import("./airflow.js");
  if (S.view !== "air" || S.activeId !== id) return;
  const view = (S.air = new AirflowView(stage));
  stage.append(cap);
  play.addEventListener("click", () => { view.setPlaying(!view.playing); play.textContent = view.playing ? "Pause" : "Play"; });

  const fail = (e) => { cap.textContent = `The airflow could not be solved (${e.message}).`; };
  const load = async (wind, ranking = false) => {
    const q = new URLSearchParams({ doors_open: String(st.doors) });
    if (wind) q.set("wind", wind);
    if (ranking) q.set("rank", "true");
    cap.textContent = ranking ? "Trying all eight winds…" : "Solving the breeze…";
    const r = await fetch(`${API}/plans/${id}/airflow/${st.level}?${q}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    if (S.air !== view) return null;
    view.setData(d);
    st.wind = d.wind.label;
    rose.querySelectorAll("button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.wind === d.wind.label)));
    const s = d.summary;
    cap.textContent = `Wind ${d.wind.speed} m/s from ${d.wind.label}  ·  ${s.cross_ventilated} of ${s.habitable} rooms cross-ventilated`
      + (s.poor.length ? `  ·  stuffy: ${s.poor.join(", ")}` : "  ·  every habitable room gets air")
      + `  ·  solved in ${s.solve_ms} ms`;
    return d;
  };
  for (const w of WINDS) {
    const b = el("button", null, w); b.type = "button"; b.dataset.wind = w; b.setAttribute("role", "radio");
    b.addEventListener("click", () => load(w).catch(fail));
    rose.append(b);
  }
  best.addEventListener("click", async () => {
    best.disabled = true;
    try {
      const d = await load(st.wind, true);
      if (!d) return;
      const top = Math.max(...d.ranking.map((x) => x.score), 1e-6);
      rank.hidden = false; rank.innerHTML = "";
      rank.append(el("span", "air-rank__title", "How well each wind serves this floor"));
      for (const x of [...d.ranking].sort((a, b) => b.score - a.score)) {
        const row = el("button", "air-rank__row"); row.type = "button";
        const barEl = el("span", "air-rank__bar"); barEl.style.setProperty("--f", (x.score / top).toFixed(3));
        row.append(el("span", "air-rank__w", x.wind), barEl, el("span", "air-rank__n", `${Math.round(x.score * 100)}`));
        row.addEventListener("click", () => load(x.wind).catch(fail));
        rank.append(row);
      }
    } catch (e) { fail(e); } finally { best.disabled = false; }
  });
  load(st.wind).catch(fail);
}

/* ── findings ──────────────────────────────────────────────────────── */

async function renderFindings() {
  const s = scrollPane("findings");
  s.append(el("h3", "sec", "Everything the committee found"));
  s.append(el("p", "lede", "Every finding names what is wrong, where it is, the authority for that judgement, and the fix. A finding with no remedy would be noise."));

  let a = cur().analysis;
  if (!a) {
    try {
      a = await fetch(`${API}/plans/${S.activeId}/analysis`).then((r) => r.json());
      S.plans[S.activeId].analysis = a;
    } catch (err) { s.append(el("p", "empty-note", `Could not load findings (${err.message}).`)); return; }
    if (S.view !== "findings") return;
  }

  // How you get to each room. Shown first, because it is the question a
  // client asks of a plan before any number: what do I walk through.
  const lay = a.layout;
  if (lay?.routes?.length) {
    s.append(el("h3", "sec", "How you move through it"));
    const stats = el("div", "stat-row");
    const illegal = lay.routes.filter((r) => !r.legal).length;
    for (const [pig, k, v, sub] of [
      [illegal ? "hingula" : "ochre", "Walkable", `${Math.round(lay.walkable * 100)}%`,
        illegal ? `${illegal} room(s) reached the wrong way` : "every room reached correctly"],
      ["indigo", "Adjacency", `${Math.round(lay.adjacency * 100)}%`, "programme honoured"],
      ["chalk", "Zoning", `${Math.round(lay.zoning * 100)}%`, "front-to-back order"],
    ]) {
      const d = el("dl", "stat"); d.dataset.pig = pig;
      d.append(el("dt", null, k), el("dd", null, v), el("small", null, sub)); stats.append(d);
    }
    s.append(stats);
    const routes = [...lay.routes].sort((x, y) => (x.legal - y.legal) || (x.path.length - y.path.length));
    for (const r of routes) {
      const row = el("div", "route"); row.dataset.ok = r.legal ? "y" : "n";
      row.append(el("b", "route__room", r.room));
      const chain = el("span", "route__path");
      r.path.forEach((step, i) => {
        if (i) chain.append(icon("next", "ico route__arrow"));
        chain.append(el("span", i === r.path.length - 1 ? "route__end" : "route__step", step));
      });
      row.append(chain);
      if (!r.legal) row.append(el("span", "route__why", r.reason));
      s.append(row);
    }
    if (lay.broken?.length) {
      s.append(el("p", "note-card", lay.broken[0]));
    }
  }

  const all = [];
  for (const [axis, rep] of Object.entries(a.metrics || {}))
    for (const f of rep.findings || []) all.push({ ...f, axis });
  for (const f of a.compliance?.findings || []) all.push({ ...f, axis: "compliance" });
  const v = cur().vastu;
  for (const x of (v?.verdicts || []).filter((x) => x.assessable && x.compliance < 0.6))
    all.push({ code: x.rule_id, severity: x.effective_weight > 0.5 ? "moderate" : "minor",
      message: `${x.title} — ${x.subject_label || "element"} ${x.observed_direction || ""} (${x.verdict})`,
      remedy: x.remedy, axis: "vastu", target_label: x.subject_label,
      evidence: [{ source: x.citation, detail: x.school }] });

  const order = { critical: 0, major: 1, moderate: 2, minor: 3, info: 4 };
  all.sort((x, y) => (order[x.severity] ?? 9) - (order[y.severity] ?? 9));

  const counts = all.reduce((m, f) => (m[f.severity] = (m[f.severity] || 0) + 1, m), {});
  const stats = el("div", "stat-row");
  for (const [sev, pig] of [["critical", "hingula"], ["major", "hingula"], ["moderate", "ochre"], ["minor", "chalk"], ["info", "indigo"]]) {
    const d = el("dl", "stat"); d.dataset.pig = pig;
    d.append(el("dt", null, sev), el("dd", null, String(counts[sev] || 0)),
      el("small", null, sev === "critical" ? "blocks delivery" : ""));
    stats.append(d);
  }
  s.append(stats);

  if (!all.length) { s.append(el("p", "empty-note", "No findings. Every measured axis is within tolerance.")); return; }

  for (const f of all) {
    const d = el("div", "find"); d.dataset.sev = f.severity;
    d.append(el("i", "find__s"), el("span", "find__t", f.message));
    const meta = [cap(f.axis), f.code, f.target_label].filter(Boolean).join(" · ");
    d.append(el("span", "find__m", meta +
      (f.actual != null ? ` · actual ${f.actual}${f.expected != null ? ` vs expected ${f.expected}` : ""}` : "")));
    if (f.remedy) d.append(el("span", "find__r", f.remedy));
    const cite = (f.evidence || []).map((e) => e.source).filter(Boolean).join(" · ");
    if (cite) d.append(el("span", "find__c", cite));
    s.append(d);
  }
}

/* ── audit ─────────────────────────────────────────────────────────── */

/* ── negotiation ───────────────────────────────────────────────────── */

const OUTCOME_COPY = {
  satisfied: ["Settled", "Every hard and soft constraint holds."],
  converged: ["Converged", "Further rounds stopped paying for themselves."],
  converged_with_open_constraints: ["Open", "No agent could improve the design further."],
  exhausted: ["Timed out", "The round budget ran out before settling."],
};

function renderNegotiation() {
  const s = scrollPane("negotiation");
  const n = S.negotiation;

  s.append(el("h3", "sec", "The agents negotiating"));
  s.append(el("p", "lede",
    "Everything before this point is one forward pass — generate, critique, vote, repair. " +
    "It produces a scheme that is good on average but can still carry a specific unsatisfied " +
    "constraint, because no stage looks at the design again after changing it. " +
    "Here the manager measures every constraint, hands each failure to the agent that owns it, " +
    "and accepts a proposal only when re-measuring shows the whole design improved."));

  if (!n) { s.append(el("p", "empty-note", "No negotiation record for this scheme.")); return; }

  const [word, sub] = OUTCOME_COPY[n.outcome] || [cap(n.outcome || "—"), ""];
  const stats = el("div", "stat-row");
  const accepted = (n.log || []).reduce(
    (a, r) => a + r.mutations.filter((m) => m.accepted).length, 0);
  const proposed = (n.log || []).reduce((a, r) => a + r.mutations.length, 0);
  for (const [pig, k, v, sm] of [
    ["indigo", "Outcome", word, sub],
    ["chalk", "Rounds", `${n.rounds}`, `${n.seconds}s`],
    ["orpiment", "Proposals", `${accepted}/${proposed}`, "accepted"],
    [n.hard_constraints_open ? "hingula" : "ochre", "Hard open",
      `${n.hard_constraints_open}`, n.hard_constraints_open ? "unresolved" : "all satisfied"],
  ]) {
    const d = el("dl", "stat"); d.dataset.pig = pig;
    d.append(el("dt", null, k), el("dd", null, v), el("small", null, sm)); stats.append(d);
  }
  s.append(stats);

  if (!n.log?.length) {
    s.append(el("p", "note-card",
      "The scheme satisfied every constraint on first measurement, so no negotiation was needed. " +
      "The protocol still ran — a clean measurement is a result, not a skipped step."));
    return;
  }

  for (const r of n.log) {
    const card = el("div", "round");

    const head = el("div", "round__h");
    head.append(el("span", "round__n", `Round ${r.round}`));
    const [from, to] = String(r.score).split(" -> ");
    const delta = (+to) - (+from);
    const chip = el("span", "round__d", `${from} → ${to}`);
    chip.dataset.dir = delta > 0.0001 ? "up" : "flat";
    head.append(chip);
    if (r.hard_open !== "0 -> 0") head.append(el("span", "round__hard", `hard ${r.hard_open}`));
    card.append(head);

    if (r.unsatisfied?.length) {
      const ul = el("ul", "round__open");
      for (const c of r.unsatisfied) {
        const li = el("li");
        li.dataset.sev = c.severity;
        li.append(el("b", null, c.id), el("span", null, c.detail),
          el("em", null, `owner: ${c.owner}`));
        ul.append(li);
      }
      card.append(el("p", "round__lab", `${r.unsatisfied.length} constraint(s) open at the start of this round`));
      card.append(ul);
    }

    if (r.mutations?.length) {
      card.append(el("p", "round__lab", "Proposals"));
      for (const m of r.mutations) {
        const row = el("div", "mut");
        row.dataset.ok = m.accepted ? "y" : "n";
        row.append(el("span", "mut__w", m.worker.replace(/_/g, " ")));
        row.append(el("span", "mut__c", m.change));
        row.append(el("span", "mut__f", `for ${m["for"]}`));
        row.append(el("span", "mut__d", `${m.delta >= 0 ? "+" : ""}${m.delta.toFixed(4)}`));
        row.append(el("span", "mut__v", m.accepted ? "accepted" : "rejected"));
        card.append(row);
      }
    } else if (!r.notes?.length) {
      card.append(el("p", "round__lab", "No agent proposed a change in this round."));
    }

    // An agent that owns a failing constraint and cannot help has to say why.
    // Silence from the responsible agent looks identical to the agent not running.
    for (const note of r.notes || []) {
      card.append(el("p", "round__note", note));
    }
    s.append(card);
  }

  s.append(el("p", "note-card",
    "A proposal is accepted only when re-measuring the whole design shows a net gain, and hard " +
    "constraints are weighted three times a soft one. That is what makes the loop safe to run " +
    "unattended: no accumulation of small comfort gains can ever outrank fixing a statutory breach, " +
    "and the design can never end a round worse than it began."));
}

/* ── audit ─────────────────────────────────────────────────────────── */

function renderAudit() {
  const s = scrollPane("audit");
  const c = S.consensus;
  s.append(el("h3", "sec", "How the decision was reached"));
  s.append(el("p", "lede", c?.explanation || "No consensus record."));

  if (!c) return;

  const stats = el("div", "stat-row");
  for (const [pig, k, v, sub] of [
    ["indigo", "Method", c.method, "Pareto + weighted Borda"],
    ["chalk", "Frontier", `${c.pareto_front.length}`, `${c.dominated.length} dominated`],
    ["hingula", "Disqualified", `${c.disqualified.length}`, "critical findings"],
    ["orpiment", "Agreement", `${Math.round(c.overall_agreement * 100)}%`, c.debate_triggered ? "debate opened" : "no debate needed"],
  ]) {
    const d = el("dl", "stat"); d.dataset.pig = pig;
    d.append(el("dt", null, k), el("dd", null, v), el("small", null, sub)); stats.append(d);
  }
  s.append(stats);

  s.append(el("h3", "sec", "Ranking"));
  const t = el("table", "led");
  t.innerHTML = "<thead><tr><th>Scheme</th><th class='n'>Score</th><th class='n'>Utility</th><th class='n'>Borda</th><th class='n'>Agreement</th></tr></thead>";
  const tb = el("tbody");
  for (const r of c.ranking) {
    const i = S.planIds.indexOf(r.candidate_id);
    const tr = el("tr");
    if (r.candidate_id === S.activeId) tr.style.background = "var(--earth-3)";
    const name = el("td", "audit__scheme", `Scheme ${String.fromCharCode(65 + Math.max(0, i))}`);
    if (r.candidate_id === S.winnerId) { name.append(icon("check", "ico ico--sm")); name.title = "The chosen scheme"; }
    tr.append(name,
      el("td", "n", r.score.toFixed(4)), el("td", "n", r.utility.toFixed(4)),
      el("td", "n", r.borda.toFixed(4)), el("td", "n", `${Math.round(r.agreement * 100)}%`));
    tb.append(tr);
  }
  t.append(tb); s.append(t);

  if (c.axis_agreement?.length) {
    s.append(el("h3", "sec", "Agreement by axis"));
    const at = el("table", "led");
    at.innerHTML = "<thead><tr><th>Axis</th><th class='n'>Mean</th><th class='n'>Dispersion</th><th class='n'>Agreement</th><th>Status</th></tr></thead>";
    const ab = el("tbody");
    for (const a of c.axis_agreement) {
      const tr = el("tr");
      tr.append(el("td", null, cap(a.axis)), el("td", "n", a.mean_score.toFixed(3)),
        el("td", "n", a.dispersion.toFixed(3)), el("td", "n", `${Math.round(a.agreement * 100)}%`),
        el("td", null, a.contested ? "contested" : "settled"));
      if (a.contested) tr.style.color = "var(--hingula)";
      ab.append(tr);
    }
    at.append(ab); s.append(at);
  }

  if (c.disqualified?.length) {
    s.append(el("h3", "sec", "Disqualified schemes"));
    for (const d of c.disqualified) {
      const i = S.planIds.indexOf(d.candidate_id);
      const box = el("div", "find"); box.dataset.sev = "critical";
      box.append(el("i", "find__s"),
        el("span", "find__t", `Scheme ${String.fromCharCode(65 + Math.max(0, i))} — ${d.reasons.length} critical finding(s)`));
      for (const r of d.reasons) box.append(el("span", "find__c", r));
      s.append(box);
    }
  }

  if (S.recommendations.length) {
    s.append(el("h3", "sec", "Recommended actions"));
    const ol = el("ol");
    ol.style.cssText = "margin:0;padding-left:20px;color:var(--chalk-2);font-size:13px;line-height:1.9";
    for (const r of S.recommendations) ol.append(el("li", null, r));
    s.append(ol);
  }

  s.append(el("h3", "sec", "Critic reliability weights"));
  const wt = el("table", "led");
  wt.innerHTML = "<thead><tr><th>Critic</th><th class='n'>Weight</th></tr></thead>";
  const wb = el("tbody");
  for (const [id, w] of Object.entries(c.critic_weights || {})) {
    const tr = el("tr"); tr.append(el("td", null, id), el("td", "n", w.toFixed(4))); wb.append(tr);
  }
  wt.append(wb); s.append(wt);
  s.append(el("p", "note-card", "These weights are learned. When an architect rates a delivered scheme, each critic's prediction is scored against that verdict and its influence moves — so the committee calibrates to this practice over time."));
}

/* ── why ───────────────────────────────────────────────────────────── */

function openWhy() {
  const b = $("why-body"); b.innerHTML = "";
  const text = S.explanation || S.consensus?.explanation || "No rationale was produced.";
  for (const p of String(text).split(/\n{2,}/)) if (p.trim()) b.append(el("p", null, p.trim()));
  $("why").hidden = false;
  $("why-close").focus();
}


/* ── revise a finished design in words ─────────────────────────────── */

// "Make the kitchen bigger", "add a balcony to the master bedroom", "no puja
// room": the brief agent turns the sentence into a changed brief, says what it
// changed, and the studio runs again on it.
function reviseBox(after) {
  if (S.imported) return;
  document.getElementById("revise")?.remove();
  const box = el("form", "revise"); box.id = "revise";
  box.append(el("h3", "revise__k", "Ask for a bigger change"),
    el("p", "revise__note", "Describe it and the studio redraws the house, keeping what you do not mention."));
  const input = el("input", "revise__in"); input.type = "text"; input.maxLength = 2000;
  input.placeholder = "e.g. make the kitchen bigger, add a balcony off the master bedroom";
  input.setAttribute("aria-label", "Describe a change to this design");
  const go = el("button", "ghost-btn", "Revise"); go.type = "submit";
  const said = el("p", "revise__said"); said.setAttribute("aria-live", "polite");
  // Changes this design could take, one tap each: what it lacks, what is
  // usually asked of a house like it. Each is a sentence the studio reads.
  const have = new Set((cur()?.plan?.levels || []).flatMap((l) => l.rooms.map((r) => r.type)));
  const floors = (cur()?.plan?.levels || []).length;
  const ideas = [
    ["Bigger kitchen", "make the kitchen bigger"],
    ["Bigger living room", "make the living room bigger"],
    !have.has("study") && ["Add a study", "add a study"],
    !have.has("puja") && ["Add a puja room", "add a pooja room"],
    !have.has("balcony") && floors > 1 && ["Balcony off the master", "add a balcony off the master bedroom"],
    !have.has("garage") && ["Car parking", "add car parking"],
    ["Kitchen in the south-east", "put the kitchen in the south-east"],
    floors > 1 && ["Bedroom downstairs", "add a bedroom on the ground floor"],
    ["One more bathroom", "add one more bathroom"],
    ["Traditional look", "make it look traditional with a tiled roof"],
  ].filter(Boolean).slice(0, 8);
  const chips = el("div", "revise__ideas");
  chips.append(el("span", "revise__try", "Try:"));
  for (const [label, text] of ideas) {
    const c = el("button", "revise__idea", label); c.type = "button";
    c.addEventListener("click", () => { input.value = text; box.requestSubmit(); });
    chips.append(c);
  }
  box.append(input, go, chips, said);
  after.before(box);
  box.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    go.disabled = true; said.textContent = "Reading that…";
    try {
      const r = await fetch(`${API}/design/revise`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction: text, brief: S.chatBrief || S.briefSent || {} }) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      said.textContent = d.changes.join(" · ");
      if (!d.understood) { go.disabled = false; return; }
      S.chatBrief = d.brief;
      const next = { ...S.briefSent, ...d.request,
        extra_rooms: [...(S.briefSent?.extra_rooms || []), ...(d.request.extra_rooms || [])].filter((x, i, a) => a.findIndex((y) => JSON.stringify(y) === JSON.stringify(x)) === i) };
      setTimeout(() => onSubmit(null, next), 900);
    } catch (err) {
      said.textContent = `Could not read that change (${err.message}).`;
    } finally { go.disabled = false; }
  });
}
