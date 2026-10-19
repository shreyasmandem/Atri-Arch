/* ═══════════════════════════════════════════════════════════════════════
   Studio

   Three phases, one URL: compose -> running -> review. Every result surface
   the engine can produce is reachable here, because a committee that reports
   twenty-five findings and shows you none of them is not explainable, it is
   just quiet.
   ═══════════════════════════════════════════════════════════════════════ */

import { atelier, person, avatar } from "./atelier.js";
import { mountEditor } from "./editor.js";
import { autoSetbacks } from "./setbacks.js";

const API = (() => {
  const local = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
  const o = new URLSearchParams(location.search).get("api") || (local ? "" : window.AIP_API);
  if (o) return o.replace(/\/$/, "");
  if (location.port === "8080" || location.port === "3000" || location.port === "5500") {
    return `http://${location.hostname || "127.0.0.1"}:8000/api/v1`;
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

function strike(svg) {
  if (!svg) return;
  const N = 9, U = 900 / N, out = [];
  for (let r = 0; r < N; r++)
    for (let c = 0; c < N; c++)
      out.push(`<rect class="pada" data-r="${r}" data-c="${c}" x="${c * U}" y="${r * U}" width="${U}" height="${U}" fill="transparent" stroke="#2A2724" stroke-width="1"/>`);
  out.push(`<path d="M0 0L900 900M900 0L0 900" stroke="#2A2724" stroke-width="1" opacity=".45"/>`);
  out.push(`<rect x="${3 * U}" y="${3 * U}" width="${3 * U}" height="${3 * U}" fill="none" stroke="#57524B" stroke-width="2"/>`);
  svg.innerHTML = out.join("");
}

/** Project the plan onto the 9x9 field and light each room's padas. */
function lightPadas(svg, plan) {
  if (!svg || !plan?.levels?.length) return { occupied: 0, sectors: [] };
  svg.querySelectorAll(".pada").forEach((p) => {
    p.setAttribute("fill", "transparent"); p.setAttribute("stroke", "#2A2724"); p.removeAttribute("data-lit");
  });

  const rooms = plan.levels[0].rooms || [];
  if (!rooms.length) return { occupied: 0, sectors: [] };

  let mnX = Infinity, mnY = Infinity, mxX = -Infinity, mxY = -Infinity;
  for (const rm of rooms) for (const [x, y] of rm.polygon || []) {
    mnX = Math.min(mnX, x); mxX = Math.max(mxX, x); mnY = Math.min(mnY, y); mxY = Math.max(mxY, y);
  }
  const w = mxX - mnX, h = mxY - mnY;
  if (!(w > 0 && h > 0)) return { occupied: 0, sectors: [] };

  const dirOf = new Map((plan.room_summary || []).map((r) => [r.id, r.direction]));
  const sectors = [];

  for (const rm of rooms) {
    const xs = (rm.polygon || []).map((p) => p[0]);
    const ys = (rm.polygon || []).map((p) => p[1]);
    if (!xs.length) continue;
    const dir = dirOf.get(rm.id) || "CENTRE";
    const pig = PIG[dir] || "chalk";
    sectors.push({ name: rm.name || cap(rm.type), dir, pig, area: rm.area });

    const c0 = Math.floor(((Math.min(...xs) - mnX) / w) * 9);
    const c1 = Math.ceil(((Math.max(...xs) - mnX) / w) * 9);
    const r0 = Math.floor(((mxY - Math.max(...ys)) / h) * 9);   // +Y is north; SVG +Y is down
    const r1 = Math.ceil(((mxY - Math.min(...ys)) / h) * 9);

    for (let r = Math.max(0, r0); r < Math.min(9, r1); r++)
      for (let c = Math.max(0, c0); c < Math.min(9, c1); c++) {
        const p = svg.querySelector(`.pada[data-r="${r}"][data-c="${c}"]`);
        if (p) { p.setAttribute("fill", HEX[pig]); p.setAttribute("fill-opacity", ".16"); p.setAttribute("data-lit", "1"); }
      }
  }

  // The Brahmasthan is scored separately - a uniform wash over the centre
  // would hide the one rule the whole diagram exists to enforce.
  let occupied = 0;
  for (let r = 3; r < 6; r++) for (let c = 3; c < 6; c++) {
    const p = svg.querySelector(`.pada[data-r="${r}"][data-c="${c}"]`);
    if (!p) continue;
    if (p.getAttribute("data-lit")) {
      occupied++;
      p.setAttribute("fill", HEX.hingula); p.setAttribute("fill-opacity", ".34"); p.setAttribute("stroke", HEX.hingula);
    } else { p.setAttribute("stroke", "#8A847B"); }
  }
  return { occupied, sectors };
}

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
  drawPlot({ w, d, rw, rd, unit, road, levels,
    ...(() => { const sb = autoSetbacks(w * d, +v("setback_front") || null, +v("setback_rear") || null, +v("setback_side") || null, Math.min(w, d));
      return { front: sb[0], rear: sb[1], side: sb[2] }; })() });
}

// The plot to scale: boundary, setback envelope, the road on its side, the
// floors stacked behind, dimensions and a north point. Geometry is set with
// CSS-transitionable attributes so a change of input redraws smoothly.
function drawPlot({ w, d, rw = w, rd = d, unit = "m", road, levels, front, rear, side }) {
  const svg = $("plot-svg");
  if (!svg) return;
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
  setMode(mode);
  document.body.dataset.manual = "1";
  $("sheet-close")?.focus();
}

async function initHome() {
  const host = $("chat");
  if (!host) return;
  $("sheet-close")?.addEventListener("click", () => { delete document.body.dataset.manual; });
  const { mountHome } = await import("./home.js");
  // The live hero, the airflow tile and the committee: the page's own proof.
  import("./home-hero.js").then(({ mountHero, mountAirShowcase }) => {
    mountHero($("hero3d"), $("hero-cap"));
    const air = $("show-air");
    if (air) new IntersectionObserver((es, o) => { if (es[0].isIntersecting) { mountAirShowcase(air); o.disconnect(); } }).observe(air);
  });
  import("./steps.js").then(({ mountSteps }) => mountSteps()).catch(() => {});
  const grid = $("board-grid");
  if (grid) {
    const { PEOPLE, glyph } = await import("./atelier.js");
    for (const p of Object.values(PEOPLE)) {
      const li = el("li", "member"); li.dataset.pig = p.pig;
      li.append(glyph(p.glyph, "member__gl"), el("b", null, p.name), el("span", null, p.role));
      grid.append(li);
    }
  }
  $("cta-go")?.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
    setTimeout(() => document.querySelector(".composer__in")?.focus(), 500);
  });
  mountHome({
    host, api: API, setField, openManual,
    // A drawing dropped into the chat goes through the plan-review route.
    uploadFile: (f) => {
      const inp = $("inp-file");
      const dt = new DataTransfer(); dt.items.add(f);
      inp.files = dt.files;
      inp.dispatchEvent(new Event("change", { bubbles: true }));
      setMode("upload");
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
  strike($("review-mandala"));
  initBrief();

  $("brief").addEventListener("submit", onSubmit);
  $("upload")?.addEventListener("submit", onUpload);
  document.querySelectorAll(".mode-tab").forEach((t) =>
    t.addEventListener("click", () => setMode(t.dataset.mode)));
  initDropzone();
  initHome();
  $("home").addEventListener("click", () => { if (S.phase === "review") phase("compose"); });
  $("back")?.addEventListener("click", goBack);
  $("resume")?.addEventListener("click", resumeStudio);
  // Esc steps back too, once no dialog or drawer is open to take it first.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || S.phase !== "review") return;
    if (e.target.closest?.("input, select, textarea")) return;
    const open = !$("why").hidden || document.body.dataset.manual || ($("editdrawer") && !$("editdrawer").hidden);
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
    styles: [String(d.get("styles") || "tropical_modern")],
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
  document.querySelectorAll(".mode-tab").forEach((t) =>
    t.setAttribute("aria-selected", String(t.dataset.mode === S.mode)));
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
    setMode("upload");
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
    b.append(document.createTextNode(S.imported && i === 0 ? "Uploaded plan" : `Scheme ${String.fromCharCode(65 + i)}`));
    if (S.imported && i === 0) b.dataset.imported = "1";

    // A scheme with no score was not merely last - it was disqualified for a
    // critical finding and never entered the ranking. Leaving the score blank
    // reads as a rendering fault; saying so is the honest signal.
    if (row) {
      b.append(el("b", null, row.score.toFixed(2)));
      b.title = id === S.candidateId ? "Selected by the committee" : "On the trade-off frontier";
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
  const snap = { planIds: [...S.planIds], winnerId: S.winnerId, candidateId: S.candidateId, activeId: oldId,
    consensus: S.consensus ? structuredClone(S.consensus) : S.consensus, sheet: S.sheet };
  (S.editHistory ||= []).push(snap);
  S.plans[newId] = {};
  const jf = (u, body) => fetch(u, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined)
    .then((r) => r.json());
  const [plan, vastu, cost] = await Promise.all([
    jf(`${API}/plans/${newId}`),
    jf(`${API}/plans/vastu`, { plan_id: newId, tradition_weight: S.plans[oldId]?.vastu?.tradition_weight ?? 0.5, compare_to: oldId }),
    jf(`${API}/plans/cost`, { plan_id: newId, budget: S.briefSent?.budget || 0 }),
  ]);
  S.plans[newId] = { plan, vastu, cost, parent: oldId };
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

async function rescoreEdited(id) {
  const q = new URLSearchParams({ vastu: S.briefSent?.vastu || "balanced", budget: String(S.briefSent?.budget || 0),
    include_generative_critics: "true", keep: "true" });
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
          S.consensus ||= { ranking: [], disqualified: [] };
          S.consensus.ranking = [{ ...row, candidate_id: id }, ...(S.consensus.ranking || []).filter((r) => r.candidate_id !== id)];
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
    activeId: snap.activeId, consensus: snap.consensus });
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
  if (vastu) { $("v-vastu").textContent = Math.round(vastu.score); $("v-vastu-note").textContent = `${vastu.grade} · ${vastu.rules_assessed} rules assessed`; }
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
  vastu: [["vastu", "Score"], ["mandala", "Mandala"]],
  report: [["findings", "Findings"], ["negotiation", "Negotiation"], ["audit", "Audit"]],
};
const groupOf = (v) => Object.keys(VIEW_GROUPS).find((g) => VIEW_GROUPS[g].some(([k]) => k === v)) || v;

function showView(v, { fromHistory = false } = {}) {
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

  if (v === "mandala") renderMandala();
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
  const set = (on) => { drawer.hidden = !on; open.setAttribute("aria-expanded", String(on)); };
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
    const { Viewer3D } = await import("./viewer3d.js");
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

function renderMandala() {
  const { plan } = cur();
  const { occupied, sectors } = lightPadas($("review-mandala"), plan);

  const note = $("brahma-note");
  if (occupied) {
    note.dataset.tone = "breach";
    note.textContent = `Brahmasthan built over — ${occupied} of 9 central padas are occupied. The corpus treats the centre as the seat of Brahma and requires it unbuilt; an open centre is also what drives stack ventilation and daylights a deep plan.`;
  } else {
    note.dataset.tone = "clear";
    note.textContent = "Brahmasthan clear. The central nine padas are unbuilt, satisfying the strongest rule in the corpus and leaving the plan's core available for a courtyard or void.";
  }

  const legend = $("quarter-legend"); legend.innerHTML = "";
  for (const [pig, label] of [
    ["indigo", "Ishanya · north-east · analysis"],
    ["orpiment", "Vayavya · north-west · judgement"],
    ["hingula", "Agneya · south-east · breach"],
    ["ochre", "Nairutya · south-west · mass and cost"],
  ]) {
    const d = el("div"); const i = el("i"); i.style.background = HEX[pig];
    d.append(i, el("span", null, label)); legend.append(d);
  }

  const list = $("room-sectors"); list.innerHTML = "";
  list.append(el("h3", "sec", `Rooms by sector (${sectors.length})`));
  const tbl = el("table", "led");
  tbl.innerHTML = "<thead><tr><th>Room</th><th>Sector</th><th class='n'>Area</th></tr></thead>";
  const tb = el("tbody");
  for (const s of sectors.sort((a, b) => b.area - a.area)) {
    const tr = el("tr");
    const td = el("td", null, s.name);
    const dot = el("i"); dot.style.cssText = `display:inline-block;width:8px;height:8px;transform:rotate(45deg);background:${HEX[s.pig]};margin-right:8px`;
    td.prepend(dot);
    tr.append(td, el("td", null, s.dir), el("td", "n", `${s.area.toFixed(1)} m²`));
    tb.append(tr);
  }
  tbl.append(tb); list.append(tbl);
}

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
// Sixteen compass points to the eight squares (and the centre).
const vxZone = (d) => {
  const k = String(d || "").toUpperCase();
  if (!k || k === "C" || k === "CENTRE") return "C";
  return { NNE: "N", ENE: "E", ESE: "E", SSE: "S", SSW: "S", WSW: "W", WNW: "W", NNW: "N" }[k] || k;
};
const vxTone = (verdict) => ({ ideal: "good", acceptable: "good", neutral: "mid", discouraged: "bad", prohibited: "bad" }[verdict] || "none");

function vxRing(score) {
  const r = 34, c = 2 * Math.PI * r, f = Math.max(0, Math.min(1, score / 100));
  const svg = `<svg viewBox="0 0 84 84" aria-hidden="true"><circle cx="42" cy="42" r="${r}" class="vx-ring__bg"/>`
    + `<circle cx="42" cy="42" r="${r}" class="vx-ring__fg" stroke-dasharray="${(c * f).toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 42 42)"/></svg>`;
  const box = el("div", "vx-ring");
  box.innerHTML = svg;
  box.append(el("b", null, String(Math.round(score))));
  return box;
}

function renderVastu() {
  const s = scrollPane("vastu");
  const v = cur().vastu;
  if (!v) { s.append(el("p", "empty-note", "No Vastu assessment for this scheme.")); return; }

  // ── the reading at a glance ──────────────────────────────────────
  const head = el("section", "vx-head");
  const txt = el("div", "vx-head__t");
  txt.append(el("span", "vx-k", "Vastu"), el("h2", "vx-grade", `${Math.round(v.score)} / 100 · ${v.grade}`),
    el("p", "vx-sum", v.summary || ""),
    el("p", "vx-meta", `${v.rules_assessed} of ${v.rules_total} rules measured on this plan · ${v.violations} not met`
      + (v.serious_violations ? ` (${v.serious_violations} serious)` : "")));
  head.append(vxRing(v.score), txt);
  s.append(head);

  // Stance: how much the client weighs tradition against function.
  const lab = el("label", "vx-stance");
  lab.append(el("span", null, `Your stance: ${cap(v.stance_label)}`));
  const sl = el("input"); Object.assign(sl, { type: "range", min: 0, max: 4, step: 1, value: Math.round(v.tradition_weight * 4) });
  sl.className = "stance";
  sl.setAttribute("aria-label", "How strictly to read Vastu, from modern to traditional");
  sl.addEventListener("change", () => rescore(+sl.value / 4));
  const ends = el("span", "vx-stance__ends"); ends.append(el("i", null, "Modern"), el("i", null, "Traditional"));
  lab.append(sl, ends);
  s.append(lab);

  // ── what the last edit did ───────────────────────────────────────
  const since = v.since_edit;
  if (since) {
    const card = el("section", `vx-since${since.delta < 0 ? " is-down" : since.delta > 0 ? " is-up" : ""}`);
    card.append(el("h3", "sec", "Since your edit"),
      el("p", "vx-since__score", since.delta
        ? `${Math.round(since.score_before)} → ${Math.round(since.score_after)} (${since.delta > 0 ? "+" : ""}${since.delta})`
        : `Unchanged at ${Math.round(since.score_after)}`));
    const word = (x) => (x === null || x === undefined ? "not measured" : x >= 0.95 ? "met" : x >= 0.6 ? "acceptable" : x >= 0.3 ? "weak" : "not met");
    for (const c of (since.changes || []).slice(0, 6)) {
      const row = el("div", `vx-change ${c.better ? "is-up" : "is-down"}`);
      row.append(el("i", "vx-change__a", c.better ? "▲" : "▼"), el("span", "vx-change__t", c.title),
        el("span", "vx-change__w", `${word(c.before)} → ${word(c.after)}`));
      if (c.note) row.append(el("span", "vx-change__n", c.note));
      card.append(row);
    }
    if (!since.changes?.length) card.append(el("p", "vx-meta", "No rule changed its reading."));
    s.append(card);
  }

  // ── the mandala: every room in its square ────────────────────────
  const gp = v.graph_placements || [];
  if (gp.length) {
    s.append(el("h3", "sec", "Rooms on the Vastu mandala"));
    const grid = el("div", "vx-grid");
    grid.setAttribute("role", "img");
    grid.setAttribute("aria-label", "The plan read as the nine squares of the Vastu mandala, each room in its square");
    for (const [z, name, element] of VX_ZONES) {
      const cell = el("div", "vx-cell"); cell.dataset.z = z;
      cell.append(el("span", "vx-cell__h", `${z === "C" ? "Centre" : z} · ${name}`), el("span", "vx-cell__e", element));
      const chips = el("div", "vx-cell__rooms");
      for (const p of gp.filter((x) => vxZone(x.direction) === z)) {
        const chip = el("span", "vx-chip", p.room); chip.dataset.v = vxTone(p.verdict);
        chip.title = `${p.room}: ${p.verdict}${p.better_directions?.length ? ` · better ${p.better_directions.map((b) => b.direction).join(", ")}` : ""}`;
        chips.append(chip);
      }
      cell.append(chips);
      grid.append(cell);
    }
    s.append(grid);
    const key = el("p", "vx-key");
    for (const [t, l] of [["good", "ideal or acceptable"], ["mid", "neutral"], ["bad", "discouraged"], ["none", "no reading"]]) {
      const i = el("i", "vx-chip vx-chip--key"); i.dataset.v = t; key.append(i, el("span", null, l));
    }
    s.append(key);
  }

  // ── by category ──────────────────────────────────────────────────
  const cats = (v.category_scores || []).filter((c) => c.rules_assessed > 0 && VX_CATS[c.category]);
  if (cats.length) {
    s.append(el("h3", "sec", "By category"));
    const box = el("div", "vx-cats");
    for (const c of cats.sort((a, b) => b.weight - a.weight)) {
      const row = el("div", "vx-cat");
      const pct = Math.round(c.score > 1 ? c.score : c.score * 100);
      const bar = el("span", "vx-cat__bar"); const fill = el("i"); fill.style.width = `${pct}%`; fill.dataset.v = pct >= 75 ? "good" : pct >= 50 ? "mid" : "bad";
      bar.append(fill);
      row.append(el("span", "vx-cat__l", VX_CATS[c.category]), bar, el("span", "vx-cat__v", `${pct}`));
      box.append(row);
    }
    s.append(box);
  }

  // ── the fixes worth most ─────────────────────────────────────────
  if (v.top_remedies?.length) {
    s.append(el("h3", "sec", "What fixing each thing is worth"));
    for (const r of v.top_remedies) {
      const line = el("div", "bar-line");
      line.append(el("span", "bar-line__l", r.title));
      const t = el("div", "bar-line__t"); const i = el("i");
      i.style.background = r.modern_validity >= 0.65 ? HEX.indigo : HEX.chalk;
      t.append(i); line.append(t, el("span", "bar-line__v", `+${r.points_recoverable.toFixed(1)} pts`));
      s.append(line);
      requestAnimationFrame(() => { i.style.transform = `scaleX(${Math.min(1, r.points_recoverable / 10)})`; });
      const p = el("p", "find__r", r.explanation); p.style.cssText = "margin:2px 0 14px;padding-left:2px";
      s.append(p);
    }
  }
  if (v.reconciliation_note) s.append(el("p", "note-card", v.reconciliation_note));

  // ── for the builder: decided on the plot ─────────────────────────
  const site = (v.verdicts || []).filter((x) => x.category === "site");
  if (site.length) {
    s.append(el("h3", "sec", "Site checklist for the builder"));
    s.append(el("p", "lede", "Placed on the plot during construction, so they are not in the drawings or the score."));
    const ul = el("ul", "vx-check");
    for (const x of site) {
      const li = el("li");
      li.append(el("b", null, x.title), el("span", null, x.remedy || ""));
      ul.append(li);
    }
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
  fold("Rules not satisfied", violated.length, (d) => { for (const x of violated) d.append(vastuRow(x, x.verdict === "prohibited" ? "major" : "moderate")); }, true);
  fold("Rules satisfied", met.length, (d) => { for (const x of met) d.append(vastuRow(x, "info")); });
  fold("Not measured on this plan", skipped.length, (d) => {
    d.append(el("p", "lede", "Left out of the score rather than guessed at."));
    for (const x of skipped) {
      const r = el("div", "find"); r.dataset.sev = "info";
      r.append(el("i", "find__s"), el("span", "find__t", x.title), el("span", "find__c", x.reason_not_assessable || `Superseded by ${x.defeated_by}`));
      d.append(r);
    }
  });
  fold("How each room's reading was derived", gp.length, (d) => {
    if (v.graph_note) d.append(el("p", "note-card", v.graph_note));
    for (const p of gp) {
      const box = el("div", "deriv");
      box.dataset.v = p.verdict;
      const h = el("div", "deriv__h");
      h.append(el("b", null, p.room), el("span", "deriv__dir", `${p.direction} · ${p.quarter}`),
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
      if (p.citations?.length) box.append(el("p", "deriv__cite", p.citations.join(" · ")));
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
  try {
    const r = await fetch(`${API}/plans/vastu`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_id: S.activeId, tradition_weight: w, ...(cur().parent ? { compare_to: cur().parent } : {}) }),
    });
    if (!r.ok) throw new Error(String(r.status));
    S.plans[S.activeId].vastu = await r.json();
    renderVastu(); renderVerdict();
  } catch (err) { toast(`Could not re-score at that stance: ${err.message}`); }
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
  const { Viewer3D } = await import("./viewer3d.js");
  if (S.view !== "interior" || S.activeId !== id) return;
  S.viewer?.dispose();
  const viewer = (S.viewer = new Viewer3D(stage));
  const pal = (S.palette ||= {});
  const url = () => {
    const q = new URLSearchParams();
    if (pal.id) q.set("palette", pal.id);
    if (pal.text) q.set("colours", pal.text);
    if (pal.design) q.set("design", pal.design);
    return `${API}/plans/${id}/model.glb${q.size ? `?${q}` : ""}`;
  };
  try { await viewer.load(url()); } catch (e) { cap.textContent = `The model could not be shown (${e.message}).`; return; }
  cap.textContent = "Pick a room to walk into it · drag to look around";

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
    for (const [t, step] of [["‹", -1], ["›", 1]]) {
      const b = el("button", "ghost-btn", t); b.type = "button";
      b.setAttribute("aria-label", step < 0 ? "Previous style" : "Next style");
      b.addEventListener("click", async () => {
        pal.id = schemes[(i + step + schemes.length) % schemes.length].id;
        drawStyle();
        await viewer.load(url(), { keepView: true });
        if (current) viewer.focusRoom(current.box, current.lv, true);
      });
      nav.append(b);
    }
    row.append(name, nav);
    style.append(row, sw, el("p", "inx__story", s.story || ""));
  };

  // Walk into a room: the floors above lift away, the camera stands in a
  // corner at eye height, and the furniture and its cost come up beside it.
  let current = null;
  const open = async (item, li) => {
    list.querySelectorAll("li").forEach((x) => x.classList.toggle("is-on", x === li));
    const xs = item.r.polygon.map((q) => q.x ?? q[0]), ys = item.r.polygon.map((q) => q.y ?? q[1]);
    const box = { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
    current = { box, lv: item.lv };
    viewer.focusRoom(box, item.lv);
    // Back (or Esc) leaves the room first, then the view.
    S.exitRoom = () => {
      S.exitRoom = null;
      current = null;
      list.querySelectorAll("li").forEach((x) => x.classList.remove("is-on"));
      info.hidden = true;
      cap.textContent = "Pick a room to walk into it · drag to look around";
      viewer.load(url()).then(() => viewer.setMode("exterior")).catch(() => {});
    };
    const s = await scP;
    const rs = s?.rooms?.find((x) => x.room_id === item.r.id);
    info.innerHTML = "";
    const out = el("button", "ghost-btn inx__out", "Whole house"); out.type = "button";
    out.setAttribute("aria-label", "Leave the room and see the whole house");
    out.addEventListener("click", () => S.exitRoom?.());
    info.append(out);
    info.append(el("b", "inx__room", item.r.name || item.r.type));
    info.append(el("span", "inx__meta", `${(item.r.area ?? 0).toFixed?.(1) ?? ""} m² · ${floorName(item.lv)}${rs?.direction ? ` · ${rs.direction}` : ""}`));
    if (rs?.furniture?.length) {
      const ul = el("ul", "inx__items");
      let total = 0;
      for (const f of rs.furniture) {
        total += f.cost || 0;
        const li2 = el("li");
        li2.append(el("span", null, f.name), el("span", "n", inr(f.cost || 0)));
        ul.append(li2);
      }
      info.append(ul, el("p", "inx__total", `Furniture ${inr(total)}`));
    } else {
      info.append(el("p", "inx__meta", "No loose furniture - finishes only."));
    }
    if (rs?.lighting) info.append(el("p", "inx__meta", `${rs.lighting.target_lux} lux · ${rs.lighting.colour_temperature_k} K · ${rs.lighting.downlight_count} downlights`));
    info.hidden = false;
  };
  const lis = new Map();
  for (const item of rooms) {
    const li = el("li");
    lis.set(item, li);
    const b = el("button", "inx__room-btn"); b.type = "button";
    b.append(el("span", null, item.r.name || item.r.type), el("small", null, `${floorName(item.lv)} · ${(+item.r.area || 0).toFixed(1)} m²`));
    b.addEventListener("click", () => open(item, li));
    li.append(b);
    list.append(li);
  }
  info.hidden = true;
  const first = rooms.find((x) => x.r.type === "living") || rooms[0];
  if (first) open(first, lis.get(first));
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
  for (const [label, href] of [[".glb", `${API}/plans/${S.activeId}/model.glb`], [".obj", `${API}/plans/${S.activeId}/model.obj`]]) {
    const a = el("a", "ghost-btn", label); a.href = href; a.download = ""; a.title = `Download the model as ${label}`;
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
    return `${API}/plans/${id}/model.glb${q.size ? `?${q}` : ""}`;
  };
  try {
    const { Viewer3D } = await import("./viewer3d.js");
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
      if (mode !== "vastu") { S.viewer.clearVastu(); S.viewer.setMode(mode, lv); return; }
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
      b.addEventListener("click", () => pick(b, mode, lv));
      modes.append(b);
    }
    modes.firstChild?.setAttribute("aria-selected", "true");
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
  const { elevations } = await import("./thumbs.js");
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
    const { Viewer3D } = await import("./viewer3d.js");
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
const EX_PARTS = ["roof", "base", "upper", "screen", "windows", "planters", "accent", "feature"];
const EX_TINTS = { w: "wall", c: "clad", r: "roof_tint", m: "metal", f: "frame", d: "door" };
const EX_OPTS = { b: "boundary", l: "railing", h: "shade", e: "canopy", g: "gate", v: "paving", t: "garden", s: "solar",
  x: "panel", q: "parapet", k: "deck", i: "lights" };
const EX_NICE = { flat: "Flat parapet", slab: "Cantilever slab", mono: "Mono-pitch", butterfly: "Butterfly", hip: "Hip, tiled", gable: "Gable",
  plaster: "Plaster", stone: "Stone", brick: "Brick", concrete: "Concrete", timber: "Timber", metal: "Metal", none: "None",
  fins: "Fins", louvres: "Louvres", frame: "Box frame", jaali: "Jaali", perforated: "Perforated", punched: "Punched", band: "Glazing band",
  jharokha: "Jharokha", colonnade: "Colonnade", chhatri: "Chhatri", cornice: "Cornice", breeze: "Breeze-block", greenwall: "Green wall", balcony: "Balcony",
  hedge: "Hedge", grille: "Grille", glass: "Glass", solid: "Solid wall", terracotta: "Terracotta tile", acp: "ACP panel",
  slate: "Stacked slate", vault: "Barrel vault", sawtooth: "Sawtooth", slats: "Timber slats", bamboo: "Bamboo",
  arcade: "Arcade", portico: "Portico", bay: "Bay window", floatbox: "Floating box", featurewall: "Monolith wall",
  thinnai: "Thinnai", bangla: "Bangla pavilion", pergolaframe: "Pergola frame", cornerglass: "Glass corner" };
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
    if (EX_TINTS[k] && /^[0-9a-f]{6}$/i.test(v)) d[EX_TINTS[k]] = v.toLowerCase();
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
  const t = [...Object.entries(EX_TINTS), ...Object.entries(EX_OPTS)].filter(([, f]) => d[f]).map(([k, f]) => `${k}:${d[f]}`).join(",");
  return t ? `${core}~${t}` : core;
}

// The palette card: the recommended scheme first, the others a click away,
// and a line where the client can say what colours they like in words.
// `viewer` is whichever 3D view shows the house; `page` lays the panel out as
// the Exterior tab itself rather than a card over a model; `onModel` hears
// each rebuild (the Exterior tab redraws its elevations).
async function paletteCard(card, id, modelUrl, { viewer = () => S.viewer, page = false, onModel = null } = {}) {
  const pal = S.palette;
  const [{ thumb }, { swatch: texSwatch }] = await Promise.all([import("./thumbs.js"), import("./materials.js")]);
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
  let loading = false, batch = 0, seq = 0, live = 0, timer = 0, lastTab = null, lastGroup = null;
  // What the client said about the look, sent with every batch so each one
  // follows the brief as well as the style; and what the server heard in it.
  const cb = S.chatBrief || {};
  const briefPrefs = [S.chatWords, cb.notes, (cb.styles || []).join(" "), cb.colours, pal.text].filter(Boolean).join(". ").slice(0, 1100);
  let heard = [], planStyle = S.plans[id]?.plan?.style || "";
  const styleName = (k) => grammar?.styles?.find((x) => x.id === k)?.name || "";
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
    if (asked === pal.design) { claim(asked); onModel?.(); }
  };
  const choose = (did) => { pal.base = did; pal.notes = []; draw(); rebuild(); };
  const merge = (xs) => {
    const known = new Set(designs.map((d) => d.id));
    const fresh = (xs || []).filter((d) => exParse(d.id) && !known.has(d.id));
    designs.push(...fresh);
    return fresh;
  };
  const loadMore = async (n = 12, style = pal.style || "") => {
    if (loading) return [];
    loading = true;
    let fresh = [];
    try {
      const q = new URLSearchParams({ seed: `${Date.now().toString(36)}-${++batch}`, n: String(n) });
      if (style) q.set("style", style);
      if (briefPrefs) q.set("prefs", briefPrefs);
      for (const d of designs.slice(-40)) q.append("avoid", d.id);
      const r = await fetch(`${API}/plans/${id}/exteriors?${q}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const x = await r.json();
      grammar = x.grammar || grammar;
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
        designs.unshift({ id: pal.base, name: "Your current design", story: "The design the drawings show.", fam: "" });
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
  // A gallery card: the picture chooses the design; the dots under it
  // recolour this card, and choose the design in those colours.
  const designCard = (d, s) => {
    const p = exParse(d.id) || {};
    const wrap = el("div", "ex-card");
    wrap.classList.toggle("is-on", d.id === pal.base);
    const pick = tile({ selected: d.id === pal.base, url: thumbUrl(tinted(d.id, cardTint(d))), label: d.name, title: d.story,
      onPick: () => choose(d.id) });
    const dots = el("div", "ex-card__dots");
    dots.setAttribute("role", "group"); dots.setAttribute("aria-label", `${d.name} colours`);
    const now = cardTint(d)?.id ?? null;
    const own = [p.wall ? `#${p.wall}` : s.exterior.plaster, s.exterior.clad, p.roof_tint ? `#${p.roof_tint}` : s.exterior.roof,
      grammar?.accents?.[p.accent] || s.exterior.frame];
    for (const sc of cardSchemes(d)) {
      const b = el("button", "ex-card__dot"); b.type = "button";
      const name = sc ? sc.name : "Its own colours";
      b.title = name;
      b.setAttribute("aria-label", `${d.name} in ${name}`);
      b.setAttribute("aria-pressed", String((sc?.id ?? null) === now));
      const [w, c, r, m] = sc ? [sc.wall, sc.clad, sc.roof, sc.metal] : own;
      b.style.background = `conic-gradient(${w} 0 50%, ${c} 0 70%, ${r} 0 88%, ${m} 0)`;
      b.addEventListener("click", (e) => {
        d.tint = schemeTint(sc);
        choose(d.id);
        if (e.detail === 0) card.querySelector(`[aria-label="${d.name} in ${name}"]`)?.focus({ preventScroll: true });
      });
      dots.append(b);
    }
    wrap.append(pick, dots);
    return wrap;
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
    const styles = [["", own ? `For this house · ${own}` : "For this house"],
      ...(grammar?.styles || []).filter((x) => x.id !== planStyle).map((x) => [x.id, x.name])];
    const filt = chips("Style", styles, pal.style || "", async (v) => {
      pal.style = v; draw();
      if (v && !designs.some((d) => d.fam === v)) { await loadMore(24, v); draw(); }
    }, { cls: "ex-chips--scroll" });
    panel.append(filt);
    // Say what the designs are drawn from: the style, and the brief's own words.
    const from = pal.style ? styleName(pal.style) : own;
    if (from || heard.length) {
      panel.append(el("p", "ex__hint ex__from", [from && `${from} designs`, heard.length && `following your brief: ${heard.join(", ")}`]
        .filter(Boolean).join(" · ")));
    }
    if (grammar?.combinations) {
      panel.append(el("p", "ex__hint", `${bigWords(grammar.combinations)} possible exteriors. The one you settle on is kept for your house alone.`));
    }
    const shown = designs.filter((d) => !pal.style || d.fam === pal.style);
    if (!shown.length) return skeleton(panel);
    if (pal.tint) {
      const note = el("p", "ex__hint");
      const clr = el("button", "pal__clr", "use each design's own colours"); clr.type = "button";
      clr.addEventListener("click", () => { pal.tint = null; draw(); rebuild(); });
      note.append(`Shown in ${pal.tint.name} colours · `, clr);
      panel.append(note);
    }
    const grid = el("div", "ex-grid");
    // The end of the gallery (or of the phone's sideways strip): reaching it
    // pulls the next batch.
    const sentinel = el("span", "ex-sentinel"); sentinel.setAttribute("aria-hidden", "true");
    grid.append(sentinel);
    const add = (xs) => {
      for (const d of xs) {
        grid.insertBefore(designCard(d, s), sentinel);
      }
    };
    add(shown);
    panel.append(grid);
    const more = el("button", "ghost-btn ex-more", "Generate 24 more designs"); more.type = "button";
    const go = async () => {
      if (loading) return;
      more.disabled = true; more.textContent = "Designing…"; more.setAttribute("aria-busy", "true");
      const fresh = await loadMore(24);
      add(fresh);
      more.disabled = false; more.textContent = "Generate 24 more designs"; more.removeAttribute("aria-busy");
      const tab = card.querySelector("#ex-tab-designs"); if (tab) tab.textContent = `Designs ${designs.length}`;
      const k = card.querySelector(".ex__title .pal__k"); if (k) k.textContent = `Exterior ${idx() + 1} of ${designs.length}`;
    };
    more.addEventListener("click", go);
    panel.append(more);
    // Up to a point on a desktop, where the button keeps going after that; a
    // phone has no room for the button, so its strip just keeps coming.
    const phone = matchMedia("(max-width: 720px)");
    new IntersectionObserver(([e]) => { if (e.isIntersecting && (designs.length < 240 || phone.matches)) go(); }).observe(sentinel);
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
    panel.append(el("p", "ex__hint", `${(grammar?.schemes || []).length} colour schemes for ${d.name}, then every surface on its own below.`));
    const own = [p.wall ? `#${p.wall}` : s.exterior.plaster, s.exterior.clad, p.roof_tint ? `#${p.roof_tint}` : s.exterior.roof,
      grammar?.accents?.[p.accent] || s.exterior.frame];
    // The style's own schemes first, then every other.
    const fam = d.fam || planStyle;
    const mine = grammar?.styles?.find((x) => x.id === fam)?.schemes || [];
    const all = grammar?.schemes || [];
    const groups = [[mine.length ? `Suggested for ${styleName(fam)}` : "", [null, ...all.filter((x) => mine.includes(x.id))]],
      [mine.length ? "More schemes" : "", all.filter((x) => !mine.includes(x.id))]];
    for (const [heading, schemesIn] of groups) {
      if (heading) panel.append(el("h3", "ex__h", heading));
      const grid = el("div", "ex-grid");
      for (const sc of schemesIn) {
        const tint = schemeTint(sc);
        grid.append(tile({
          selected: (ct?.id ?? null) === (sc?.id ?? null), url: thumbUrl(tinted(d.id, tint)),
          label: sc ? sc.name : "Design's own", strip: sc ? [sc.wall, sc.clad, sc.roof, sc.metal] : own,
          onPick: () => { pal.tint = tint; delete d.tint; draw(); rebuild(); },
        }));
      }
      panel.append(grid);
    }
    const fine = el("div", "ex-custom");
    fine.append(el("h3", "ex__h", ct?.id === "custom" ? "Every surface · your own mix" : "Every surface"));
    const fallback = { wall: own[0], clad: own[1], roof_tint: own[2], metal: own[3], frame: s.exterior.frame, door: s.exterior.door };
    for (const [f, title] of SURFACES) {
      const now = ct?.[f] || p[f] || "";
      const row = el("div", "ex-paint");
      const head = el("div", "ex-paint__head");
      const named = (grammar?.paints?.[f] || []).find((x) => hx(x.hex) === now);
      head.append(el("span", "pal__rk", title),
        el("span", "ex-paint__now", now ? (named?.name || (ct?.[f] === now && ct.id !== "custom" ? ct.name : `#${now}`)) : "as designed"));
      const sws = el("div", "ex-paint__sws");
      sws.setAttribute("role", "group"); sws.setAttribute("aria-label", `${title} colours`);
      for (const { name, hex } of grammar?.paints?.[f] || []) {
        const b = el("button", "ex-dot"); b.type = "button";
        b.style.background = hex; b.title = name; b.setAttribute("aria-label", `${title}: ${name}`);
        b.setAttribute("aria-pressed", String(hx(hex) === now));
        b.addEventListener("click", (e) => {
          setTint(f, hex);
          if (e.detail === 0) card.querySelector(`[aria-label="${title}: ${name}"]`)?.focus({ preventScroll: true });
        });
        sws.append(b);
      }
      const pick = el("label", "ex-dot ex-dot--any"); pick.title = `Any ${title.toLowerCase()} colour`;
      const inp = el("input"); inp.type = "color"; inp.name = f;
      const cur = now ? `#${now}` : fallback[f];
      inp.value = /^#[0-9a-f]{6}$/i.test(cur || "") ? cur : "#cccccc";
      inp.setAttribute("aria-label", `Any ${title.toLowerCase()} colour`);
      inp.addEventListener("input", () => setTint(f, inp.value, false));
      inp.addEventListener("change", () => setTint(f, inp.value));
      pick.append(inp);
      sws.append(pick);
      row.append(head, sws);
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
    house.append(el("summary", null, `Whole-house palette · ${s.name}`));
    const i = Math.max(0, list.findIndex((x) => x.id === pal.id));
    const nav = el("div", "pal__head");
    const strip = el("span", "pal__strip");
    for (const hex of [s.exterior.plaster, s.exterior.clad, s.exterior.roof, s.interior.living, s.interior.master, s.interior.accent_wall]) {
      const c = el("i"); c.style.background = hex; strip.append(c);
    }
    const lab = el("span", "pal__toggle");
    lab.append(el("span", "pal__k", i === 0 ? "Recommended" : `${i + 1} / ${list.length}`), el("b", "pal__name", s.name), strip);
    const arrows = el("div", "pal__nav");
    for (const [t, step, name] of [["‹", -1, "Previous palette"], ["›", 1, "Next palette"]]) {
      const bt = el("button", "ghost-btn", t); bt.type = "button"; bt.setAttribute("aria-label", name);
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
    draw();
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
    slate: ["slate", "#56585b"] };
  const PANEL = { none: ["plaster", "#e9e2d4"], stone: FINISH.stone, timber: FINISH.timber, slate: FINISH.slate,
    terracotta: FINISH.terracotta, acp: FINISH.acp, brick: FINISH.brick };
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
    paving: ["Driveway", [["stone", "Stone pavers"], ["concrete", "Concrete"], ["gravel", "Gravel"], ["grass", "Grass pavers"]]],
    garden: ["Garden", [["standard", "Standard"], ["lush", "Lush"], ["minimal", "Minimal"], ["none", "Paved"]]],
    planters: ["Planters", [[false, "None"], [true, "Along the front"]]],
    panel: ["Feature panel", [["none", "None"], ["stone", "Stone"], ["timber", "Wood-look"], ["slate", "Slate"],
      ["terracotta", "Terracotta"], ["acp", "ACP"], ["brick", "Brick"]]],
    parapet: ["Parapet", [["plain", "Plain"], ["glass", "Glass strip"], ["grooved", "Grooved"], ["screen", "CNC screen"], ["stepped", "Stepped"]]],
    deck: ["Roof terrace", [["none", "Open"], ["pergola", "Pergola"], ["garden", "Roof garden"]]],
    lights: ["Facade lighting", [["none", "None"], ["washers", "Wall washers"], ["strips", "LED strips"]]],
    accent: ["Accent", null],
  };
  const SECTIONS = [["form", "Roof & form", ["roof", "parapet", "deck", "solar", "feature"]], ["walls", "Walls", ["base", "upper", "panel"]],
    ["openings", "Windows & shade", ["windows", "shade", "screen"]], ["entry", "Entrance, balconies & lights", ["canopy", "railing", "lights"]],
    ["site", "Gate, drive & garden", ["boundary", "gate", "paving", "garden", "planters"]], ["accent", "Accent finish", ["accent"]]];
  const customiser = (panel, di) => {
    const d = designs[di];
    const now = d && exParse(d.id);
    if (!now || !grammar) return skeleton(panel, 2);
    const one = (S.plans[id]?.plan?.levels?.length || 1) <= 1;
    const flatRoof = now.roof === "flat" || now.roof === "slab";
    const choices = (key) => OPTIONS[key][1]
      || (key === "accent" ? Object.keys(grammar.accents || {}).map((k) => [k, k[0].toUpperCase() + k.slice(1)])
        : (grammar[key] || []).map((v) => [v, EX_NICE[v] || v]));
    // An option left out of the id is its first value.
    const value = (key) => (now[key] === undefined || now[key] === "" ? choices(key)[0][0] : now[key]);
    const label = (key) => (choices(key).find(([v]) => v === value(key)) || [, ""])[1];
    const icon = (b, v) => {
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true"); svg.classList.add("ex-chip__icon");
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", ROOF_ICON[v] || ""); svg.append(path); b.append(svg);
    };
    const tex = (map, tintOf) => (b, v) => {
      const [kind, hex] = map[v] || Object.values(map)[0];
      const t = tintOf?.(v);
      const c = texSwatch(kind, t ? `#${t}` : hex, 44); c.className = "ex-chip__sw"; c.setAttribute("aria-hidden", "true");
      b.append(c);
    };
    const wallTint = (v) => (v === "plaster" ? (pal.tint?.wall || now.wall) : (pal.tint?.clad || now.clad));
    const DECOR = {
      roof: { paint: icon, cls: "ex-chips--icons" },
      base: { paint: tex(FINISH, wallTint), cls: "ex-chips--sw" },
      upper: { paint: tex(FINISH, wallTint), cls: "ex-chips--sw", disabled: (v) => one && v !== "plaster" },
      paving: { paint: tex(DRIVE), cls: "ex-chips--sw ex-chips--4" },
      feature: { disabled: (v) => one && ["jharokha", "balcony", "bay", "floatbox", "cornerglass"].includes(v) },
      solar: { disabled: (v) => v === "on" && !flatRoof },
      panel: { paint: tex(PANEL), cls: "ex-chips--sw ex-chips--4" },
      parapet: { disabled: (v) => v !== "plain" && now.roof !== "flat" },
      deck: { disabled: (v) => v !== "none" && now.roof !== "flat" },
      accent: { cls: "ex-chips--dots", paint: (b, v) => { const i = el("i", "ex-chip__dot"); i.style.background = grammar.accents[v]; b.prepend(i); } },
    };
    const pick = (key) => (v) => {
      if (key === "accent" && pal.tint?.metal) pal.tint = { ...pal.tint, id: "custom", name: "Custom", metal: "" };
      // The house's own value stays out of the id, keeping it short.
      const first = choices(key)[0][0];
      const store = OPTIONS[key][1] && key !== "planters" && v === first ? "" : v;
      edit(di, { [key]: store });
    };
    pal.sec ||= { form: true };
    for (const [sid, title, keys] of SECTIONS) {
      const sec = el("details", "ex-sec");
      sec.open = !!pal.sec[sid];
      sec.addEventListener("toggle", () => { pal.sec[sid] = sec.open; });
      const sum = el("summary", "ex-sec__sum");
      // The summary names what is there: an absent solar array or signature says nothing.
      const said = keys.map((k) => {
        const v = value(k);
        if (k === "gate") return v === "none" ? "Open gate" : label(k);
        if (k === "planters") return v ? "Planters" : "";
        if (k === "solar") return v === "on" ? "Solar panels" : "";
        if (k === "boundary") return `${label(k)} boundary`;
        if (k === "canopy") return v === "none" ? "" : `${label(k)} canopy`;
        if (k === "railing") return `${label(k)} railings`;
        if (k === "panel") return v === "none" ? "" : `${label(k)} panel`;
        if (k === "parapet") return v === "plain" ? "" : `${label(k)} parapet`;
        return v === "none" || v === "off" ? "" : label(k);
      }).filter(Boolean);
      sum.append(el("span", "ex-sec__t", title), el("span", "ex-sec__now", said.join(" · ") || "Plain"));
      const body = el("div", "ex-sec__body");
      for (const key of keys) {
        const g = chips(OPTIONS[key][0], choices(key), value(key), pick(key), DECOR[key] || {});
        if (key === "solar" && !flatRoof) g.append(el("p", "ex__hint", "Solar panels need a flat or slab roof."));
        if ((key === "parapet" || key === "deck") && now.roof !== "flat") g.append(el("p", "ex__hint", "Needs a flat parapet roof."));
        body.append(g);
      }
      sec.append(sum, body);
      panel.append(sec);
    }
    const notes = el("p", "pal__why pal__notes", (pal.notes || []).join(" ")); notes.setAttribute("aria-live", "polite");
    panel.append(notes);
    if (d.orig) {
      const r = el("button", "ghost-btn pal__reset", `Reset to ${d.orig.name}`); r.type = "button";
      r.addEventListener("click", () => { designs[di] = d.orig; choose(d.orig.id); });
      panel.append(r);
    }
  };

  const TABS = [["designs", "Designs"], ["colours", "Colours"], ["customise", "Customise"]];
  const draw = () => {
    const s = list[Math.max(0, list.findIndex((x) => x.id === pal.id))];
    if (!s) return;
    const keep = card.querySelector(".ex-panel")?.scrollTop || 0;
    card.hidden = false; card.innerHTML = "";
    const min = !page && pal.min;
    card.className = `pal ex${page ? " ex--page" : ""}${min ? " is-min" : ""}${live ? " is-live" : ""}`;
    pal.tab ||= "designs";
    const di = idx(), d = designs[di];
    const head = el("div", "ex__head");
    const title = el("div", "ex__title");
    title.append(el("span", "pal__k", d ? `Exterior ${di + 1} of ${designs.length}${d.custom ? " · customised" : ""}` : "Exterior designs"),
      el("b", "pal__name", d ? d.name : "Composing…"));
    if (d?.story) title.title = d.story;
    const badge = d && uniqBadge();
    if (badge) title.append(badge);
    const nav = el("div", "pal__nav");
    for (const [t, step, name] of [["‹", -1, "Previous design"], ["›", 1, "Next design"]]) {
      const bt = el("button", "ghost-btn", t); bt.type = "button"; bt.setAttribute("aria-label", name); bt.disabled = !d;
      bt.addEventListener("click", () => choose(designs[(di + step + designs.length) % designs.length].id));
      nav.append(bt);
    }
    if (!page) {
      const mb = el("button", "ghost-btn", pal.min ? "+" : "–"); mb.type = "button";
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
  const st = (S.airState ||= { level: 0, wind: null, doors: true });
  if (!levels.some((lv) => lv.index === st.level)) st.level = levels[0]?.index ?? 0;

  const bar = el("div", "pane__bar");
  const floors = el("div", "sheet-groups"); floors.setAttribute("role", "tablist");
  for (const lv of levels) {
    const b = el("button", null, floorName(lv.index)); b.type = "button"; b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", String(lv.index === st.level));
    b.addEventListener("click", () => { st.level = lv.index; renderAir(); });
    floors.append(b);
  }
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
  bar.append(floors, rose, tools);
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
        if (i) chain.append(el("i", "route__arrow", "›"));
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
    tr.append(el("td", null, `Scheme ${String.fromCharCode(65 + Math.max(0, i))}${r.candidate_id === S.winnerId ? " ✓" : ""}`),
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
  box.append(el("span", "revise__k", "Change something"));
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
