/* ═══════════════════════════════════════════════════════════════════════
   Studio

   Three phases, one URL: compose -> running -> review. Every result surface
   the engine can produce is reachable here, because a committee that reports
   twenty-five findings and shows you none of them is not explainable, it is
   just quiet.
   ═══════════════════════════════════════════════════════════════════════ */

import { atelier, person, avatar } from "./atelier.js";

const API = (() => {
  const o = new URLSearchParams(location.search).get("api");
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
  if (document.body.dataset.phase === p) return;
  const apply = () => { document.body.dataset.phase = p; };
  if (document.startViewTransition && !reducedMotion() && !document.hidden) {
    document.documentElement.dataset.vt = p;
    const t = document.startViewTransition(apply);
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
const lakh = (n) => n >= 1e7 ? `${(n / 1e7).toFixed(2).replace(/\.?0+$/, "")} crore` : `${Math.round(n / 1e5)} lakh`;

// The headline and the plot drawing are the brief itself, set large, so the
// first screen already shows the house being asked for.
function renderBrief() {
  const f = $("brief");
  if (!f) return;
  const v = (n) => f.elements[n]?.value;
  const w = Math.max(3, +v("plot_width") || 12), d = Math.max(3, +v("plot_depth") || 18);
  const road = f.querySelector('input[name="road_direction"]:checked')?.value || "N";
  const levels = +v("levels") || 2;
  const beds = Math.max(1, +v("bedrooms") || 1);
  const budget = +v("budget") || 0;
  const stance = STANCES[+(f.querySelector('input[name="vastu_slider"]:checked')?.value ?? 2)] || STANCES[2];

  setText("hl-plot", `${fmtM(w)} × ${fmtM(d)} m`);
  setText("hl-road", ROAD_WORD[road]);
  const storeys = levels === 1 ? "one storey" : `${NUMWORD[levels] || levels} storeys`;
  setText("hl-prog", `${NUMWORD[beds] || beds} bedroom${beds > 1 ? "s" : ""}, ${storeys}`);
  setText("budget-words", budget ? lakh(budget) : "");
  setText("stance-note", stance[2]);
  setText("sum-line", `${Math.round(w * d)} m² plot · ${beds} bed · ₹${lakh(budget)} · Vastu ${stance[0].toLowerCase()}`);
  drawPlot({ w, d, road, levels,
    front: +v("setback_front") || 0, rear: +v("setback_rear") || 0, side: +v("setback_side") || 0 });
}

// The plot to scale: boundary, setback envelope, the road on its side, the
// floors stacked behind, dimensions and a north point. Geometry is set with
// CSS-transitionable attributes so a change of input redraws smoothly.
function drawPlot({ w, d, road, levels, front, rear, side }) {
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
  tw.textContent = `${fmtM(w)} m`;
  const td = svg.querySelector('.pf-t[data-d="d"]');
  set(td, { x: dimX + 6, y: y0 + pd / 2, transform: `rotate(-90 ${(dimX + 6).toFixed(1)} ${(y0 + pd / 2).toFixed(1)})` });
  td.textContent = `${fmtM(d)} m`;
}

function initBrief() {
  const f = $("brief");
  if (!f) return;
  f.addEventListener("input", renderBrief);
  f.addEventListener("change", renderBrief);
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
  $("home").addEventListener("click", () => { if (S.phase === "review") phase("compose"); });
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

  const setbackSide = n("setback_side", 1.2);
  const elderlyAccess = Boolean(d.get("elderly_access"));

  return {
    project_name: "Studio scheme",
    plot_width: Math.max(3, n("plot_width", 12) || 12),
    plot_depth: Math.max(3, n("plot_depth", 18) || 18),
    locality: String(d.get("locality") || "Bengaluru, Karnataka"),
    road_direction: String(d.get("road_direction") || "N"),
    levels: Math.max(1, Math.min(6, n("levels", 2) || 2)),
    bedrooms: Math.max(1, n("bedrooms", 3) || 3),
    bathrooms: Math.max(1, n("bathrooms", 3) || 3),
    styles: [String(d.get("styles") || "tropical_modern")],
    budget: Math.max(500000, n("budget", 6500000) || 6500000),
    currency: "INR",
    vastu: vastu,
    accessibility: elderlyAccess ? "universal" : "basic",
    occupant_adults: Math.max(1, n("occupant_adults", 2) || 2),
    occupant_children: Math.max(0, n("occupant_children", 1)),
    occupant_elders: Math.max(0, n("occupant_elders", 1)),
    setback_front: Math.max(0.5, n("setback_front", 2.5)),
    setback_rear: Math.max(0.5, n("setback_rear", 1.5)),
    setback_left: Math.max(0.5, setbackSide),
    setback_right: Math.max(0.5, setbackSide),
    finish_tier: String(d.get("finish_tier") || "premium"),
    kitchen_type: String(d.get("kitchen_type") || "open_modular"),
    amenities: amenities,
    must_haves: amenities,
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
    atelier.fail("The run ended without a scheme",
      "The engine closed the connection before returning a design. Check the server log, then try again.",
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
    toast(d.message || "The engine reported an error.");
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
  S.exportUrls = d.export_urls || {};
  S.explanation = d.explanation || "";
  S.recommendations = d.recommendations || [];
  S.projectId = d.project_id; S.sessionId = d.trace_id;
  S.voices = d.voices || [];

  S.plans[d.winner_plan_id] = { plan: d.plan, vastu: d.vastu, cost: d.cost };
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
  reviseBox(recap);
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
    ["Budget", inr(b.budget)], ["Vastu", cap(b.vastu || "")],
  ];
  for (const [k, v] of rows) {
    const d = el("div"); d.append(el("dt", null, k), el("dd", null, String(v ?? "—"))); recap.append(d);
  }
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

function showView(v) {
  if (VIEW_GROUPS[v] && !VIEW_GROUPS[v].some(([k]) => k === v)) v = S.lastIn?.[v] || VIEW_GROUPS[v][0][0];
  if (v !== "model" && S.viewer) { S.viewer.dispose(); S.viewer = null; window.speechSynthesis?.cancel(); }
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
  plate.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || own(e)) return;
    plateView.drag = { x: e.clientX - plateView.x, y: e.clientY - plateView.y };
    plate.setPointerCapture(e.pointerId);
    plate.classList.add("is-panning");
  });
  plate.addEventListener("pointermove", (e) => {
    if (!plateView.drag) return;
    plateView.x = e.clientX - plateView.drag.x;
    plateView.y = e.clientY - plateView.drag.y;
    applyPlate();
  });
  const end = () => { plateView.drag = null; plate.classList.remove("is-panning"); };
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
    const pal = S.palette || {};
    const q = new URLSearchParams(); if (pal.id) q.set("palette", pal.id); if (pal.text) q.set("colours", pal.text); if (pal.design) q.set("design", pal.design);
    await S.sheetViewer.load(`${API}/plans/${id}/model.glb${q.size ? `?${q}` : ""}`);
    host.querySelector(".model-cap")?.remove();
    sunIn.addEventListener("input", () => {
      const h = +sunIn.value; sunOut.textContent = `${String(Math.floor(h)).padStart(2, "0")}:${String(Math.round((h % 1) * 60)).padStart(2, "0")}`;
      S.sheetViewer?.setSun(h);
    });
    cutIn.addEventListener("input", () => S.sheetViewer?.setOrtho(S.sheetViewer.orthoKind, { cut: +cutIn.value }));
  }
  if (S.sheet !== key || !S.sheetViewer) return;
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

function renderVastu() {
  const s = scrollPane("vastu");
  const v = cur().vastu;
  if (!v) { s.append(el("p", "empty-note", "No Vastu assessment for this scheme.")); return; }

  const stats = el("div", "stat-row");
  for (const [pig, k, val, sub] of [
    ["orpiment", "Score", `${Math.round(v.score)}/100`, v.grade],
    ["indigo", "Assessed", `${v.rules_assessed}`, `of ${v.rules_total} rules`],
    ["chalk", "Excluded", `${v.rules_not_assessable}`, "not guessed at"],
    ["hingula", "Violations", `${v.violations}`, `${v.serious_violations} serious`],
  ]) {
    const d = el("dl", "stat"); d.dataset.pig = pig;
    d.append(el("dt", null, k), el("dd", null, val), el("small", null, sub)); stats.append(d);
  }
  s.append(stats);
  s.append(el("p", "lede", v.summary || ""));

  // Stance control — re-scoring is instant, so the reconciliation is something
  // you watch happen rather than something you are told about.
  s.append(el("h3", "sec", "Stance"));
  const lab = el("label", "fld fld--full");
  lab.append(el("span", null, `Tradition weight — ${cap(v.stance_label)}`));
  const sl = el("input"); Object.assign(sl, { type: "range", min: 0, max: 4, step: 1, value: Math.round(v.tradition_weight * 4) });
  sl.className = "stance";
  sl.addEventListener("change", () => rescore(+sl.value / 4));
  lab.append(sl); s.append(lab);
  if (v.reconciliation_note) s.append(el("p", "note-card", v.reconciliation_note));

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

  const violated = (v.verdicts || []).filter((x) => x.assessable && x.compliance < 0.6);
  if (violated.length) {
    s.append(el("h3", "sec", `Rules not satisfied (${violated.length})`));
    for (const x of violated) s.append(vastuRow(x, x.verdict === "prohibited" ? "major" : "moderate"));
  }
  const met = (v.verdicts || []).filter((x) => x.assessable && x.compliance >= 0.6);
  if (met.length) {
    s.append(el("h3", "sec", `Rules satisfied (${met.length})`));
    for (const x of met) s.append(vastuRow(x, "info"));
  }
  const skipped = (v.verdicts || []).filter((x) => !x.assessable);
  if (skipped.length) {
    s.append(el("h3", "sec", `Not assessable (${skipped.length})`));
    s.append(el("p", "lede", "Excluded from the score rather than guessed at. Scoring a rule the model cannot evaluate is how these systems manufacture false precision."));
    for (const x of skipped) {
      const d = el("div", "find"); d.dataset.sev = "info";
      d.append(el("i", "find__s"), el("span", "find__t", x.title),
        el("span", "find__c", x.reason_not_assessable || `Superseded by ${x.defeated_by}`));
      s.append(d);
    }
  }

  // ── knowledge graph ──────────────────────────────────────────────
  // The rule corpus can only speak where a text speaks. The graph derives a
  // verdict for every room by reasoning through what it is used for, and shows
  // the chain that produced it — which is the part a client can actually argue
  // with.
  const gp = v.graph_placements || [];
  if (gp.length) {
    s.append(el("h3", "sec", "Knowledge graph — every room, derived"));

    const gstats = el("div", "stat-row");
    const derived = gp.filter((p) => p.derived).length;
    const undet = gp.filter((p) => p.verdict === "undetermined").length;
    const cov = v.graph_coverage || {};
    for (const [pig, k, val, sub] of [
      ["indigo", "Graph score", `${Math.round(v.graph_score)}/100`, "area-weighted"],
      ["ochre", "Rooms derived", `${derived}`, "no rule enumerates these"],
      ["chalk", "Coverage", `${cov.coverage_gain || "—"}×`,
        `${cov.placements_derivable_by_graph || 0} vs ${cov.placements_asserted_by_text || 0} placements`],
      [undet ? "hingula" : "orpiment", "Undetermined", `${undet}`, "excluded from score"],
    ]) {
      const d = el("dl", "stat"); d.dataset.pig = pig;
      d.append(el("dt", null, k), el("dd", null, val), el("small", null, sub)); gstats.append(d);
    }
    s.append(gstats);
    if (v.graph_note) s.append(el("p", "note-card", v.graph_note));

    for (const p of gp) {
      const box = el("div", "deriv");
      box.dataset.v = p.verdict;

      const h = el("div", "deriv__h");
      h.append(el("b", null, p.room));
      h.append(el("span", "deriv__dir", `${p.direction} · ${p.quarter}`));
      h.append(el("span", "deriv__sc", p.verdict === "undetermined" ? "—" : p.score.toFixed(2)));
      h.append(el("span", "deriv__tag", p.derived ? "derived" : "cited"));
      box.append(h);

      if (p.derivation) box.append(chainRow("supports", p.derivation));
      if (p.objection) box.append(chainRow("objects", p.objection));
      if (!p.derivation && !p.objection) {
        box.append(el("p", "deriv__x", p.explanation));
      }

      if (p.agrees_with_text === false) {
        box.append(el("p", "deriv__warn",
          "The derivation disagrees with a cited text. The text governs the score; the disagreement is shown rather than hidden."));
      }
      if (p.better_directions?.length) {
        box.append(el("p", "deriv__alt",
          "Better: " + p.better_directions
            .map((b) => `${b.direction} (${b.score.toFixed(2)})`).join(", ")));
      }
      if (p.citations?.length) box.append(el("p", "deriv__cite", p.citations.join(" · ")));
      s.append(box);
    }
  }
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
      body: JSON.stringify({ plan_id: S.activeId, tradition_weight: w }),
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
    ["indigo", "80% range", `${inr(c.p10)}`, `to ${inr(c.p90)} · ±${c.uncertainty_band_percent ?? "—"}%`],
    ["chalk", "Programme", `${c.duration_months} mo`, `${Math.round(c.delay_probability * 100)}% chance of delay`],
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
  const s = scrollPane("interior");
  let sc = cur().interior;
  if (!sc) {
    s.append(el("p", "empty-note", "Solving the furniture layout…"));
    try {
      const r = await fetch(`${API}/plans/${S.activeId}/interior`, { method: "POST" });
      if (!r.ok) throw new Error(String(r.status));
      sc = await r.json(); S.plans[S.activeId].interior = sc;
    } catch (err) {
      s.innerHTML = ""; s.append(el("p", "empty-note", `The interior layout could not be produced (${err.message}).`)); return;
    }
    if (S.view !== "interior") return;
  }
  s.innerHTML = "";

  const stats = el("div", "stat-row");
  for (const [pig, k, val, sub] of [
    ["ochre", "Furniture", inr(sc.total_furniture_cost), "supply and fit"],
    ["indigo", "Finishes", inr(sc.total_finishes_cost), "floors, walls, ceilings"],
    ["chalk", "Total", inr(sc.total_cost), sc.currency],
    ["orpiment", "Rooms", `${sc.rooms.length}`, cap(sc.style)],
  ]) {
    const d = el("dl", "stat"); d.dataset.pig = pig;
    d.append(el("dt", null, k), el("dd", null, val), el("small", null, sub)); stats.append(d);
  }
  s.append(stats);
  s.append(el("p", "lede", sc.summary || ""));

  s.append(el("h3", "sec", "Palette"));
  const chips = el("div", "chips");
  for (const sw of sc.palette?.swatches || []) {
    const c = el("div", "chip-sw", sw.role); c.style.background = sw.hex; c.title = `${sw.role} — ${sw.hex}`;
    chips.append(c);
  }
  s.append(chips);
  if (sc.palette?.character) s.append(el("p", "note-card", sc.palette.character));

  for (const room of sc.rooms) {
    s.append(el("h3", "sec", `${room.room_name} · ${room.area_m2.toFixed(1)} m² · ${room.direction} · layout ${room.layout_score.toFixed(2)}`));
    if (room.furniture.length) {
      const t = el("table", "led");
      t.innerHTML = "<thead><tr><th>Item</th><th>Size</th><th>Against</th><th class='n'>Cost</th></tr></thead>";
      const tb = el("tbody");
      for (const f of room.furniture) {
        const r = el("tr"); r.title = f.notes || "";
        r.append(el("td", null, f.name), el("td", null, `${f.width.toFixed(2)} × ${f.depth.toFixed(2)} m`),
          el("td", null, f.against_wall || "—"), el("td", "n", Math.round(f.cost).toLocaleString("en-IN")));
        tb.append(r);
      }
      t.append(tb); s.append(t);
    }
    for (const u of room.unplaced || []) {
      const d = el("div", "find"); d.dataset.sev = "major";
      d.append(el("i", "find__s"), el("span", "find__t", `${u.name} could not be placed`),
        el("span", "find__c", u.reason));
      s.append(d);
    }
    if (room.lighting) {
      const l = room.lighting;
      s.append(el("p", "find__m", `Lighting — ${l.target_lux} lux target · ${l.downlight_count} downlights · ${l.colour_temperature_k}K · ~${l.estimated_load_w}W`));
    }
  }
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
  tools.append(play);
  for (const [label, href] of [[".glb", `${API}/plans/${S.activeId}/model.glb`], [".obj", `${API}/plans/${S.activeId}/model.obj`]]) {
    const a = el("a", "ghost-btn", label); a.href = href; a.download = ""; a.title = `Download the model as ${label}`;
    tools.append(a);
  }
  bar.append(tools);
  const stage = el("div", "model-stage");
  const cap = el("p", "model-cap", "Loading the model…");
  const say = el("p", "model-say"); say.setAttribute("aria-live", "polite");
  const card = el("div", "pal"); card.hidden = true;
  stage.append(cap, say, card);
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
    S.viewer = new Viewer3D(stage);
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
    paletteCard(card, id, modelUrl);
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

/* ── 3D: colour schemes, recommended and browsable ─────────────────── */

// The palette card: the recommended scheme first, the others a click away,
// and a line where the client can say what colours they like in words.
async function paletteCard(card, id, modelUrl) {
  const pal = S.palette;
  const swatch = (hex, label) => {
    const sw = el("span", "pal__sw"); sw.style.background = hex; sw.title = `${label} ${hex}`; return sw;
  };
  const LABELS = { plaster: "Walls", trim: "Bands", clad: "Cladding", roof: "Roof", frame: "Frames", door: "Main door",
    living: "Living", master: "Master bed", bedroom: "Bedrooms", kitchen: "Kitchen", accent_wall: "Feature wall",
    floor_stone: "Floor", joinery: "Joinery", upholstery: "Fabric" };
  let list = [];
  let designs = [];
  let busy = false;
  const fetchList = async () => {
    const q = new URLSearchParams(); if (pal.text) q.set("colours", pal.text);
    const r = await fetch(`${API}/plans/${id}/palettes${q.size ? `?${q}` : ""}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    list = d.schemes;
    designs = d.designs || [];
    pal.prefs = d.preferences;
  };
  const apply = async (scheme) => {
    if (busy || !S.viewer) return;
    busy = true; card.classList.add("is-busy");
    pal.id = scheme.id;
    try { await S.viewer.load(modelUrl(), { keepView: true }); } catch (e) { toast(`Could not recolour the model (${e.message}).`); }
    busy = false; card.classList.remove("is-busy");
    draw();
  };
  const draw = () => {
    const i = Math.max(0, list.findIndex((x) => x.id === pal.id));
    const s = list[i];
    if (!s) return;
    card.hidden = false; card.innerHTML = "";
    card.classList.toggle("is-min", !pal.open);
    // Minimised: the name, one strip of colour and the arrows. Open: the
    // story, both swatch rows, the reasons and the colours field.
    const head = el("div", "pal__head");
    const toggle = el("button", "pal__toggle"); toggle.type = "button";
    toggle.setAttribute("aria-expanded", String(!!pal.open));
    toggle.title = pal.open ? "Minimise" : "Show palette details";
    toggle.append(el("span", "pal__k", i === 0 ? "Recommended" : `${i + 1} / ${list.length}`), el("b", "pal__name", s.name));
    const strip = el("span", "pal__strip");
    for (const hex of [s.exterior.plaster, s.exterior.clad, s.exterior.roof, s.interior.living, s.interior.master, s.interior.accent_wall]) {
      const c = el("i"); c.style.background = hex; strip.append(c);
    }
    toggle.append(strip);
    toggle.addEventListener("click", () => { pal.open = !pal.open; draw(); });
    const nav = el("div", "pal__nav");
    const prev = el("button", "ghost-btn", "‹"); prev.type = "button"; prev.title = "Previous palette"; prev.setAttribute("aria-label", "Previous palette");
    const next = el("button", "ghost-btn", "›"); next.type = "button"; next.title = "Next palette"; next.setAttribute("aria-label", "Next palette");
    prev.addEventListener("click", () => apply(list[(i - 1 + list.length) % list.length]));
    next.addEventListener("click", () => apply(list[(i + 1) % list.length]));
    nav.append(prev, next);
    head.append(toggle, nav);
    card.append(head);
    // The facade language, cycled the same way.
    if (designs.length) {
      const di = Math.max(0, designs.findIndex((x) => x.id === pal.design));
      const row = el("div", "pal__head pal__design");
      const lab = el("span", "pal__toggle");
      lab.append(el("span", "pal__k", "Facade"), el("b", "pal__name", designs[di].name));
      lab.title = designs[di].story;
      const dn = el("div", "pal__nav");
      for (const [t, step] of [["‹", -1], ["›", 1]]) {
        const bt = el("button", "ghost-btn", t); bt.type = "button"; bt.setAttribute("aria-label", step < 0 ? "Previous facade" : "Next facade");
        bt.addEventListener("click", async () => {
          if (busy || !S.viewer) return;
          pal.design = designs[(di + step + designs.length) % designs.length].id;
          busy = true; card.classList.add("is-busy");
          try { await S.viewer.load(modelUrl(), { keepView: true }); } catch (e) { toast(`Could not rebuild the facade (${e.message}).`); }
          busy = false; card.classList.remove("is-busy"); draw();
        });
        dn.append(bt);
      }
      row.append(lab, dn);
      card.append(row);
    }
    if (!pal.open) return;
    card.append(el("p", "pal__story", s.story));
    for (const [title, group] of [["Exterior", s.exterior], ["Interior", s.interior]]) {
      const row = el("div", "pal__row");
      row.append(el("span", "pal__rk", title));
      const sws = el("div", "pal__sws");
      for (const [k, hex] of Object.entries(group)) sws.append(swatch(hex, LABELS[k] || k));
      row.append(sws);
      card.append(row);
    }
    if (s.reasons?.length) card.append(el("p", "pal__why", s.reasons.join(" · ")));
    const form = el("form", "pal__form");
    const input = el("input", "pal__input"); input.type = "text"; input.name = "colours"; input.maxLength = 600;
    input.placeholder = "Colours you like… e.g. sage bedrooms, navy front door, no pink";
    input.value = pal.text || "";
    input.setAttribute("aria-label", "Colours you like, in your own words");
    const go = el("button", "ghost-btn", "Apply"); go.type = "submit";
    form.append(input, go);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      pal.text = input.value.trim();
      pal.id = null;
      try { await fetchList(); pal.id = list[0]?.id; await apply(list[0]); } catch (err) { toast(`Could not read those colours (${err.message}).`); }
    });
    card.append(form);
    const pr = pal.prefs;
    if (pr && (pr.likes?.length || pr.avoids?.length || pr.mentions?.length)) {
      const bits = [];
      if (pr.mentions?.length) bits.push(pr.mentions.join(", "));
      if (pr.likes?.length) bits.push(`likes ${pr.likes.join(", ")}`);
      if (pr.avoids?.length) bits.push(`avoids ${pr.avoids.join(", ")}`);
      card.append(el("p", "pal__heard", `Heard: ${bits.join(" · ")}`));
    }
  };
  try {
    await fetchList();
    if (!pal.id || !list.some((x) => x.id === pal.id)) pal.id = list[0]?.id;
    draw();
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
  box.append(input, go, said);
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
