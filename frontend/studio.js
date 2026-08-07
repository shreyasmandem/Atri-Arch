/* ═══════════════════════════════════════════════════════════════════════
   Studio — the mandala at work.

   Two things carry the world here rather than in CSS:

   1. The pada grid is struck out in SVG at 9x9, and rooms light the padas
      they actually occupy, in the pigment of their compass quarter. It is a
      diagram of the building on the diagram the building is judged against.

   2. The committee seats itself in order as the pipeline streams. Each
      critic's glyph fills when its verdict lands. Nothing is faked: a critic
      only lights when the server has actually reported its score.
   ═══════════════════════════════════════════════════════════════════════ */

const API = (() => {
  const override = new URLSearchParams(location.search).get("api");
  if (override) return override.replace(/\/$/, "");
  // Served from the API itself in production; localhost during development.
  if (location.port && location.port !== "8000") return "http://127.0.0.1:8000/api/v1";
  return `${location.origin}/api/v1`;
})();

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
};

/* Compass quarter → pigment. The mapping the whole product reasons in. */
const QUARTER_PIGMENT = {
  N: "indigo", NNE: "indigo", NE: "indigo", ENE: "indigo",
  E: "orpiment", ESE: "orpiment",
  SE: "hingula", SSE: "hingula", S: "hingula",
  SSW: "ochre", SW: "ochre", WSW: "ochre", W: "ochre",
  WNW: "orpiment", NW: "orpiment", NNW: "orpiment",
  CENTRE: "chalk",
};

const PIGMENT_HEX = {
  indigo: "#6E93C8", hingula: "#E0664B", ochre: "#D9A45C",
  orpiment: "#EFCE63", chalk: "#A2957C",
};

/* Which pigment a critic belongs to, by what it does. */
const CRITIC_PIGMENT = {
  "critic.compliance": "hingula", "critic.daylight": "indigo",
  "critic.ventilation": "indigo", "critic.privacy": "indigo",
  "critic.circulation": "indigo", "critic.accessibility": "indigo",
  "critic.spatial": "indigo", "critic.structure": "ochre",
  "critic.vastu": "orpiment", "critic.cost": "ochre",
  "critic.coherence": "orpiment", "critic.brief": "orpiment",
  "critic.livability": "orpiment",
};

const STANCES = [
  ["Modern", "ignore", "Vastu is reported but never constrains the design."],
  ["Advisory", "advisory", "Violations are reported; the layout is not bent to satisfy them."],
  ["Balanced", "balanced", "Classical rules and modern building science carry equal weight."],
  ["Strict", "strict", "Vastu constrains the layout wherever it is physically possible."],
  ["Orthodox", "orthodox", "The classical texts win every conflict, at any cost."],
];

const state = {
  planId: null, plan: null, consensus: null, vastu: null, cost: null,
  interior: null, drawings: [], activeDrawing: null, view: "drawings",
  committee: [], projectId: null, sessionId: null, running: false,
};

/* ═══ THE PADA GRID ══════════════════════════════════════════════════ */

function strikeGrid() {
  const svg = $("pada-grid");
  const N = 9, S = 900 / N;
  const parts = [];

  // The 81 padas.
  for (let r = 0; r < N; r++) {
    for (let c = 0; c < N; c++) {
      parts.push(
        `<rect class="pada" data-r="${r}" data-c="${c}" x="${c * S}" y="${r * S}" ` +
        `width="${S}" height="${S}" fill="transparent" stroke="#33291D" stroke-width="1"/>`
      );
    }
  }
  // The Brahmasthan, struck heavier — the centre 3x3.
  parts.push(
    `<rect x="${3 * S}" y="${3 * S}" width="${3 * S}" height="${3 * S}" ` +
    `fill="none" stroke="#4A3B29" stroke-width="2"/>`
  );
  // The two diagonals of the mandala.
  parts.push(
    `<path d="M0 0 L900 900 M900 0 L0 900" stroke="#33291D" stroke-width="1" opacity=".5"/>`
  );
  svg.innerHTML = parts.join("");
}

/** Light the padas each room occupies, in its quarter's pigment. */
function lightPadas(plan) {
  const svg = $("pada-grid");
  svg.querySelectorAll(".pada").forEach((p) => {
    p.setAttribute("fill", "transparent");
    p.removeAttribute("data-lit");
  });
  if (!plan || !plan.levels || !plan.levels.length) return;

  const rooms = plan.levels[0].rooms || [];
  if (!rooms.length) return;

  // Normalise the plan's footprint onto the 9x9 field.
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const room of rooms) {
    for (const [x, y] of room.polygon || []) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
  }
  const w = maxX - minX, h = maxY - minY;
  if (!(w > 0 && h > 0)) return;

  const summary = new Map((plan.room_summary || []).map((r) => [r.id, r.direction]));

  for (const room of rooms) {
    const xs = (room.polygon || []).map((p) => p[0]);
    const ys = (room.polygon || []).map((p) => p[1]);
    if (!xs.length) continue;

    const c0 = Math.floor(((Math.min(...xs) - minX) / w) * 9);
    const c1 = Math.ceil(((Math.max(...xs) - minX) / w) * 9);
    // Plan +Y is north; SVG +Y is down. Flip so north sits at the top.
    const r0 = Math.floor(((maxY - Math.max(...ys)) / h) * 9);
    const r1 = Math.ceil(((maxY - Math.min(...ys)) / h) * 9);

    const pigment = PIGMENT_HEX[QUARTER_PIGMENT[summary.get(room.id)] || "chalk"];

    for (let r = Math.max(0, r0); r < Math.min(9, r1); r++) {
      for (let c = Math.max(0, c0); c < Math.min(9, c1); c++) {
        const pada = svg.querySelector(`.pada[data-r="${r}"][data-c="${c}"]`);
        if (pada) {
          pada.setAttribute("fill", pigment);
          pada.setAttribute("fill-opacity", "0.14");
          pada.setAttribute("data-lit", "1");
        }
      }
    }
  }

  markBrahmasthan(svg);
}

/**
 * The centre 3x3 is the Brahmasthan, which the corpus requires to stay unbuilt.
 *
 * Lighting it in the same wash as every other pada would flatten the diagram
 * into a coloured rectangle and hide the one rule the whole world is built
 * around. So the centre is scored separately: clear padas are struck open in
 * chalk, occupied ones flare in hingula. The violation is the moment the
 * mandala exists to show.
 */
function markBrahmasthan(svg) {
  let occupied = 0;
  for (let r = 3; r < 6; r++) {
    for (let c = 3; c < 6; c++) {
      const pada = svg.querySelector(`.pada[data-r="${r}"][data-c="${c}"]`);
      if (!pada) continue;
      if (pada.getAttribute("data-lit")) {
        occupied += 1;
        pada.setAttribute("fill", PIGMENT_HEX.hingula);
        pada.setAttribute("fill-opacity", "0.3");
        pada.setAttribute("stroke", PIGMENT_HEX.hingula);
      } else {
        pada.setAttribute("fill", "transparent");
        pada.setAttribute("stroke", "#A2957C");
      }
    }
  }

  const note = $("brahmasthan-note");
  if (!note) return;
  if (occupied) {
    note.hidden = false;
    note.dataset.tone = "breach";
    note.textContent =
      `Brahmasthan built over — ${occupied} of 9 central padas are occupied.`;
  } else {
    note.hidden = false;
    note.dataset.tone = "clear";
    note.textContent = "Brahmasthan clear.";
  }
}

/* ═══ COMMITTEE ══════════════════════════════════════════════════════ */

function seatCommittee(charter) {
  const list = $("committee");
  list.innerHTML = "";
  state.committee = charter;

  for (const critic of charter) {
    const li = el("li", "critic");
    li.dataset.critic = critic.id;
    li.dataset.pigment = CRITIC_PIGMENT[critic.id] || "chalk";
    li.title = critic.charter || "";

    li.append(
      el("span", "critic__glyph"),
      el("span", "critic__name", critic.name),
      el("span", "critic__kind", critic.analytical ? "computed" : "judged"),
      el("span", "critic__score", "—"),
    );
    const bar = el("span", "critic__bar");
    bar.append(el("i"));
    li.append(bar);
    list.append(li);
  }
}

function reportScores(scores) {
  for (const [axis, score] of Object.entries(scores || {})) {
    const critic = state.committee.find((c) => c.axis === axis);
    if (!critic) continue;
    const row = document.querySelector(`.critic[data-critic="${critic.id}"]`);
    if (!row) continue;
    row.classList.add("is-seated");
    row.classList.toggle("is-flagged", score < 0.55);
    row.querySelector(".critic__score").textContent = score.toFixed(2);
    row.querySelector(".critic__bar i").style.transform = `scaleX(${score})`;
  }
}

/* ═══ LOG ════════════════════════════════════════════════════════════ */

function logStage(event) {
  const log = $("stage-log");
  const line = el("p");
  const cls = event.status === "skipped" ? "lg-skip" : event.status === "failed" ? "lg-warn" : "";
  if (cls) line.className = cls;
  line.append(el("b", null, `${event.stage} `), document.createTextNode(event.message));
  log.append(line);
  log.scrollTop = log.scrollHeight;
}

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(node._t);
  node._t = setTimeout(() => { node.hidden = true; }, 7000);
}

/* ═══ FORM ═══════════════════════════════════════════════════════════ */

function readBrief() {
  const form = $("brief");
  const data = new FormData(form);
  const num = (k) => Number(data.get(k) || 0);
  return {
    project_name: "Studio scheme",
    plot_width: num("plot_width"),
    plot_depth: num("plot_depth"),
    locality: String(data.get("locality") || ""),
    road_direction: String(data.get("road_direction") || "N"),
    levels: num("levels") || 1,
    bedrooms: num("bedrooms"),
    bathrooms: num("bathrooms"),
    styles: [String(data.get("styles") || "contemporary")],
    budget: num("budget"),
    currency: "INR",
    vastu: STANCES[num("vastu_slider")][1],
    occupant_adults: num("occupant_adults"),
    occupant_children: num("occupant_children"),
    occupant_elders: num("occupant_elders"),
  };
}

$("stance").addEventListener("input", (e) => {
  const [name, , note] = STANCES[Number(e.target.value)];
  $("stance-name").textContent = name;
  $("stance-note").textContent = note;
});

/* ═══ PIPELINE ═══════════════════════════════════════════════════════ */

$("brief").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.running) return;

  state.running = true;
  document.body.dataset.state = "running";
  $("cast").disabled = true;
  $("cast").querySelector(".cast__label").textContent = "The committee is sitting…";
  $("stage-log").innerHTML = "";
  $("rationale").hidden = true;
  document.querySelectorAll(".critic").forEach((c) => {
    c.classList.remove("is-seated", "is-flagged");
    c.querySelector(".critic__score").textContent = "—";
    c.querySelector(".critic__bar i").style.transform = "scaleX(0)";
  });

  try {
    await runPipeline(readBrief());
  } catch (err) {
    toast(`The engine could not complete this design: ${err.message}`);
    logStage({ stage: "error", status: "failed", message: err.message });
  } finally {
    state.running = false;
    document.body.dataset.state = "done";
    $("cast").disabled = false;
    $("cast").querySelector(".cast__label").textContent = "Convene the committee";
  }
});

async function runPipeline(simple) {
  const response = await fetch(`${API}/design/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ simple, candidates: 3, include_generative_critics: true }),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${(await response.text()).slice(0, 180)}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    let split;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      handleFrame(frame);
    }
  }
}

function handleFrame(frame) {
  let name = "message", payload = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) payload += line.slice(5).trim();
  }
  if (!payload) return;

  let data;
  try { data = JSON.parse(payload); } catch { return; }

  if (name === "progress") {
    logStage(data);
    if (data.detail && data.detail.scores) reportScores(data.detail.scores);
  } else if (name === "result") {
    applyResult(data);
  } else if (name === "error") {
    toast(data.message || "The engine reported an error.");
  }
}

function applyResult(data) {
  state.planId = data.winner_plan_id;
  state.plan = data.plan;
  state.consensus = data.consensus;
  state.vastu = data.vastu;
  state.cost = data.cost;
  state.projectId = data.project_id;

  const ranking = (data.consensus && data.consensus.ranking) || [];
  if (ranking.length) reportScores(ranking[0].axis_scores);

  lightPadas(data.plan);
  buildSheetRail();
  renderVerdict();
  renderRationale(data);

  $("ledger-cost").textContent = (data.model_cost_usd || 0).toFixed(2);
  if (data.degraded) toast(data.degraded_reason || "Some critics ran in degraded mode.");

  showView(state.view);
}

/* ═══ DRAWINGS ═══════════════════════════════════════════════════════ */

function buildSheetRail() {
  const rail = $("sheet-rail");
  rail.innerHTML = "";
  const levels = (state.plan && state.plan.levels) || [];

  const sheets = [
    ...levels.map((lv) => ({ key: `plan_level_${lv.index}`, label: lv.index === 0 ? "Ground plan" : `Level ${lv.index}` })),
    { key: "elevation_N", label: "North elev" },
    { key: "elevation_E", label: "East elev" },
    { key: "elevation_S", label: "South elev" },
    { key: "elevation_W", label: "West elev" },
    { key: "section_aa", label: "Section A–A" },
    { key: "section_bb", label: "Section B–B" },
    { key: "roof_plan", label: "Roof" },
    { key: "site_plan", label: "Site" },
  ];
  state.drawings = sheets;

  for (const sheet of sheets) {
    const button = el("button", null, sheet.label);
    button.type = "button";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", "false");
    button.addEventListener("click", () => loadDrawing(sheet));
    rail.append(button);
  }
  rail.hidden = false;
  loadDrawing(sheets[0]);
}

async function loadDrawing(sheet) {
  if (!state.planId) return;
  state.activeDrawing = sheet.key;

  $("sheet-rail").querySelectorAll("button").forEach((b) => {
    b.setAttribute("aria-selected", String(b.textContent === sheet.label));
  });

  const view = $("sheet-view");
  view.innerHTML = "";
  view.append(el("p", "empty-state__body", "Drawing…"));

  try {
    const res = await fetch(`${API}/plans/${state.planId}/drawings/${sheet.key}.svg?dark=true`);
    if (!res.ok) throw new Error(`${res.status}`);
    view.innerHTML = await res.text();

    const plan = state.plan || {};
    $("sheet-title").textContent = sheet.label;
    $("sheet-meta").textContent =
      `${(plan.total_built_area || 0).toFixed(1)} m² built · FAR ${(plan.achieved_far || 0).toFixed(2)} · ` +
      `${(plan.levels || []).length} level(s)`;
  } catch (err) {
    view.innerHTML = "";
    view.append(el("p", "empty-state__body", `That drawing could not be produced (${err.message}).`));
  }
}

/* ═══ VERDICT BAND ═══════════════════════════════════════════════════ */

const inr = (n) =>
  n >= 1e7 ? `₹${(n / 1e7).toFixed(2)} Cr`
  : n >= 1e5 ? `₹${(n / 1e5).toFixed(2)} L`
  : `₹${Math.round(n).toLocaleString("en-IN")}`;

function renderVerdict() {
  const c = state.consensus || {};
  $("v-score").textContent = c.winner_score != null ? c.winner_score.toFixed(2) : "—";
  $("v-agree").textContent = c.overall_agreement != null
    ? `${Math.round(c.overall_agreement * 100)}% committee agreement`
    : "awaiting the committee";

  if (state.vastu) {
    $("v-vastu").textContent = `${Math.round(state.vastu.score)}`;
    $("v-vastu-note").textContent = `${state.vastu.grade} · ${state.vastu.rules_assessed} rules assessed`;
  }
  if (state.cost) {
    $("v-cost").textContent = inr(state.cost.total);
    $("v-cost-note").textContent = `${inr(state.cost.p10)} – ${inr(state.cost.p90)}`;
  }
  if (state.plan) {
    $("v-area").textContent = `${(state.plan.total_built_area || 0).toFixed(0)} m²`;
    $("v-far").textContent = `FAR ${(state.plan.achieved_far || 0).toFixed(2)} of ${(state.plan.site || {}).max_far ?? "—"}`;
  }

  const findings = countFindings();
  $("v-findings").textContent = String(findings.total);
  $("v-findings-note").textContent = findings.critical
    ? `${findings.critical} critical · must be resolved`
    : findings.total ? "none critical" : "nothing outstanding";
}

function countFindings() {
  const hist = ((state.consensus || {}).ranking || [{}])[0]?.finding_counts || {};
  const total = Object.values(hist).reduce((a, b) => a + b, 0);
  return { total, critical: hist.critical || 0 };
}

function renderRationale(data) {
  if (!data.explanation) return;
  const body = $("rationale-body");
  body.innerHTML = "";
  for (const para of String(data.explanation).split(/\n{2,}/)) {
    if (para.trim()) body.append(el("p", null, para.trim()));
  }
  const close = el("button", "rationale__close", "Dismiss");
  close.type = "button";
  close.addEventListener("click", () => { $("rationale").hidden = true; });
  $("rationale").hidden = false;
  $("rationale").append(close);
}

/* ═══ VIEWS ══════════════════════════════════════════════════════════ */

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => showView(tab.dataset.view));
});

function showView(view) {
  state.view = view;
  document.querySelectorAll(".tab").forEach((t) => {
    const on = t.dataset.view === view;
    t.classList.toggle("is-on", on);
    t.setAttribute("aria-pressed", String(on));
  });

  const hasPlan = Boolean(state.planId);
  $("empty-state").hidden = hasPlan;
  $("sheet").hidden = !(hasPlan && view === "drawings");
  $("sheet-rail").hidden = !(hasPlan && view === "drawings");
  for (const key of ["vastu", "cost", "interior", "walkthrough"]) {
    $(`panel-${key}`).hidden = !(hasPlan && view === key);
  }
  if (!hasPlan) return;

  if (view === "vastu") renderVastu();
  if (view === "cost") renderCost();
  if (view === "interior") renderInterior();
  if (view === "walkthrough") renderWalkthrough();
}

/* ─── Vastu ─────────────────────────────────────────────────────────── */

function renderVastu() {
  const panel = $("panel-vastu");
  const v = state.vastu;
  if (!v) { panel.textContent = "No Vastu assessment for this scheme."; return; }

  panel.innerHTML = "";
  panel.append(el("h3", null, `Vastu — ${Math.round(v.score)}/100 · ${v.grade}`));
  panel.append(el("p", "panel__lede", v.summary || ""));

  // The stance control: re-scoring is instant, so the reconciliation is
  // something you watch happen rather than something you are told about.
  const control = el("div", "field-group");
  const label = el("label", "fld fld--wide");
  label.append(el("span", null, `Stance — ${STANCES[Math.round(v.tradition_weight * 4)][0]}`));
  const slider = el("input", "stance");
  Object.assign(slider, { type: "range", min: 0, max: 4, step: 1, value: Math.round(v.tradition_weight * 4) });
  slider.addEventListener("change", () => rescoreVastu(Number(slider.value) / 4));
  label.append(slider);
  control.append(label);
  panel.append(control);

  if (v.reconciliation_note) {
    const note = el("p", "panel__lede", v.reconciliation_note);
    note.style.borderTop = "1px solid var(--rule)";
    note.style.paddingTop = "0.8rem";
    panel.append(note);
  }

  if ((v.top_remedies || []).length) {
    panel.append(el("h3", null, "What fixing each thing is worth"));
    for (const remedy of v.top_remedies) {
      const row = el("div", "bar-row");
      row.append(el("span", "bar-row__label", remedy.title));
      const track = el("span", "bar-row__track");
      const fill = el("i");
      fill.style.transform = `scaleX(${Math.min(1, remedy.points_recoverable / 12.5)})`;
      fill.style.background = remedy.modern_validity >= 0.65 ? "var(--indigo)" : "var(--chalk-3)";
      track.append(fill);
      row.append(track, el("span", "bar-row__value", `+${remedy.points_recoverable.toFixed(1)}`));
      panel.append(row);

      const why = el("p", "finding__fix", remedy.explanation);
      why.style.margin = "0 0 0.7rem";
      panel.append(why);
    }
  }

  const violated = (v.verdicts || []).filter((x) => x.assessable && x.compliance < 0.6);
  if (violated.length) {
    panel.append(el("h3", null, `Rules not satisfied (${violated.length})`));
    for (const verdict of violated) {
      const item = el("div", "finding");
      item.dataset.sev = verdict.verdict === "prohibited" ? "major" : "moderate";
      item.append(el("span", "finding__sev"));
      item.append(el("span", "finding__msg", verdict.title));
      item.append(el("span", "finding__cite", `${verdict.citation} · ${verdict.school}`));
      item.append(el("span", "finding__fix", verdict.remedy));
      panel.append(item);
    }
  }

  const skipped = (v.verdicts || []).filter((x) => !x.assessable);
  if (skipped.length) {
    panel.append(el("h3", null, `Not assessable (${skipped.length})`));
    panel.append(el("p", "panel__lede",
      "These rules were excluded from the score rather than guessed at. " +
      "Scoring a rule the model cannot evaluate is how these systems manufacture false precision."));
    for (const verdict of skipped) {
      const item = el("div", "finding");
      item.dataset.sev = "info";
      item.append(el("span", "finding__sev"));
      item.append(el("span", "finding__msg", verdict.title));
      item.append(el("span", "finding__cite", verdict.reason_not_assessable || verdict.defeated_by));
      panel.append(item);
    }
  }
}

async function rescoreVastu(traditionWeight) {
  try {
    const res = await fetch(`${API}/plans/vastu`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_id: state.planId, tradition_weight: traditionWeight }),
    });
    if (!res.ok) throw new Error(String(res.status));
    state.vastu = await res.json();
    renderVastu();
    renderVerdict();
  } catch (err) {
    toast(`Could not re-score at that stance: ${err.message}`);
  }
}

/* ─── Cost ──────────────────────────────────────────────────────────── */

function renderCost() {
  const panel = $("panel-cost");
  const c = state.cost;
  if (!c) { panel.textContent = "No estimate for this scheme."; return; }

  panel.innerHTML = "";
  panel.append(el("h3", null, `Cost — ${inr(c.total)} at ${inr(c.rate_per_m2)}/m²`));
  panel.append(el("p", "panel__lede", c.summary || ""));

  panel.append(el("h3", null, "By work package"));
  const max = Math.max(...Object.values(c.by_trade || { x: 1 }));
  for (const [trade, amount] of Object.entries(c.by_trade || {}).slice(0, 12)) {
    const row = el("div", "bar-row");
    row.append(el("span", "bar-row__label", trade.replace(/_/g, " ")));
    const track = el("span", "bar-row__track");
    const fill = el("i");
    fill.style.transform = `scaleX(${amount / max})`;
    track.append(fill);
    row.append(track, el("span", "bar-row__value", inr(amount)));
    panel.append(row);
  }

  panel.append(el("h3", null, "Bill of quantities"));
  const table = el("table", "ledger-table");
  table.innerHTML =
    "<thead><tr><th>Code</th><th>Description</th><th>Unit</th>" +
    "<th class='num'>Qty</th><th class='num'>Rate</th><th class='num'>Amount</th></tr></thead>";
  const body = el("tbody");
  for (const item of (c.line_items || []).slice().sort((a, b) => b.amount - a.amount)) {
    const tr = el("tr");
    tr.title = item.basis || "";
    for (const [value, cls] of [
      [item.code], [item.description], [item.unit],
      [item.quantity.toLocaleString("en-IN", { maximumFractionDigits: 1 }), "num"],
      [Math.round(item.rate).toLocaleString("en-IN"), "num"],
      [Math.round(item.amount).toLocaleString("en-IN"), "num"],
    ]) tr.append(el("td", cls, value));
    body.append(tr);
  }
  table.append(body);
  const foot = el("tfoot");
  const ftr = el("tr");
  ftr.append(el("td", null, ""), el("td", null, "Works subtotal"), el("td", null, ""),
    el("td", "num", ""), el("td", "num", ""),
    el("td", "num", Math.round(c.works_subtotal).toLocaleString("en-IN")));
  foot.append(ftr);
  table.append(foot);
  panel.append(table);

  panel.append(el("h3", null, "Risk register"));
  for (const risk of c.risks || []) {
    const item = el("div", "finding");
    item.dataset.sev = risk.likelihood > 0.6 ? "major" : "moderate";
    item.append(el("span", "finding__sev"));
    item.append(el("span", "finding__msg", risk.name));
    item.append(el("span", "finding__cite",
      `${Math.round(risk.likelihood * 100)}% likely · +${risk.cost_impact_percent}% cost · ` +
      `+${risk.schedule_impact_weeks} weeks`));
    item.append(el("span", "finding__fix", risk.mitigation));
    panel.append(item);
  }

  panel.append(el("h3", null, "Assumptions"));
  const ul = el("ul");
  ul.style.cssText = "margin:0;padding-left:1.1rem;color:var(--chalk-3);font-size:var(--step);line-height:1.7";
  for (const line of c.assumptions || []) ul.append(el("li", null, line));
  panel.append(ul);
}

/* ─── Interior ──────────────────────────────────────────────────────── */

async function renderInterior() {
  const panel = $("panel-interior");
  if (state.interior) return paintInterior(panel, state.interior);

  panel.innerHTML = "";
  panel.append(el("p", "panel__lede", "Solving the furniture layout…"));
  try {
    const res = await fetch(`${API}/plans/${state.planId}/interior`, { method: "POST" });
    if (!res.ok) throw new Error(String(res.status));
    state.interior = await res.json();
    paintInterior(panel, state.interior);
  } catch (err) {
    panel.innerHTML = "";
    panel.append(el("p", "panel__lede", `The interior layout could not be produced (${err.message}).`));
  }
}

function paintInterior(panel, scheme) {
  panel.innerHTML = "";
  panel.append(el("h3", null, `Interior — ${scheme.style.replace(/_/g, " ")}`));
  panel.append(el("p", "panel__lede", scheme.summary || ""));

  const swatches = el("div");
  swatches.style.cssText = "display:flex;gap:2px;margin-bottom:1.2rem;flex-wrap:wrap";
  for (const sw of (scheme.palette && scheme.palette.swatches) || []) {
    const chip = el("div");
    chip.style.cssText =
      `flex:1 1 84px;min-width:84px;height:56px;background:${sw.hex};` +
      "display:flex;align-items:flex-end;padding:4px 6px;font-size:.56rem;" +
      "letter-spacing:.08em;text-transform:uppercase;color:#17130E;font-weight:700";
    chip.textContent = sw.role;
    chip.title = `${sw.role} — ${sw.hex}`;
    swatches.append(chip);
  }
  panel.append(swatches);

  for (const room of scheme.rooms || []) {
    panel.append(el("h3", null, `${room.room_name} · ${room.area_m2.toFixed(1)} m² · ${room.direction}`));
    const table = el("table", "ledger-table");
    table.innerHTML = "<thead><tr><th>Item</th><th>Size</th><th>Against</th><th class='num'>Cost</th></tr></thead>";
    const body = el("tbody");
    for (const f of room.furniture || []) {
      const tr = el("tr");
      tr.title = f.notes || "";
      tr.append(
        el("td", null, f.name),
        el("td", null, `${f.width.toFixed(2)} × ${f.depth.toFixed(2)} m`),
        el("td", null, f.against_wall || "—"),
        el("td", "num", Math.round(f.cost).toLocaleString("en-IN")),
      );
      body.append(tr);
    }
    table.append(body);
    panel.append(table);

    for (const missing of room.unplaced || []) {
      const item = el("div", "finding");
      item.dataset.sev = "major";
      item.append(el("span", "finding__sev"));
      item.append(el("span", "finding__msg", `${missing.name} could not be placed`));
      item.append(el("span", "finding__cite", missing.reason));
      panel.append(item);
    }
  }
}

/* ─── Walkthrough ───────────────────────────────────────────────────── */

async function renderWalkthrough() {
  const panel = $("panel-walkthrough");
  panel.innerHTML = "";
  panel.append(el("h3", null, "Walkthrough"));
  panel.append(el("p", "panel__lede",
    "The scheme is exported as glTF, which every browser, phone and headset reads " +
    "natively. Open it in the viewer for VR, or on a phone to place it in your own room."));

  const model = `${API}/plans/${state.planId}/model.glb`;
  const links = el("div");
  links.style.cssText = "display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1.2rem";
  for (const [label, href] of [
    ["Download 3D model (.glb)", model],
    ["Download for CAD (.obj)", `${API}/plans/${state.planId}/model.obj`],
  ]) {
    const a = el("a", null, label);
    a.href = href;
    a.className = "tab";
    a.style.textDecoration = "none";
    links.append(a);
  }
  panel.append(links);

  try {
    const res = await fetch(`${API}/plans/${state.planId}/walkthrough`);
    if (!res.ok) throw new Error(String(res.status));
    const data = await res.json();

    const s = data.statistics || {};
    panel.append(el("p", "panel__lede",
      `${(s.triangles || 0).toLocaleString()} triangles across ${s.parts || 0} parts, ` +
      `${(s.height_m || 0).toFixed(2)} m tall.`));

    panel.append(el("h3", null, "Narrated route"));
    for (const line of data.narration || []) {
      const p = el("p", "finding__msg", line.text);
      p.style.cssText = "padding:.45rem 0;border-bottom:1px solid var(--rule)";
      panel.append(p);
    }

    const speak = el("button", "tab", "Play narration");
    speak.type = "button";
    speak.addEventListener("click", () => {
      if (!("speechSynthesis" in window)) return toast("This browser has no speech synthesis.");
      speechSynthesis.cancel();
      for (const line of data.narration || []) {
        speechSynthesis.speak(new SpeechSynthesisUtterance(line.text));
      }
    });
    panel.append(speak);
  } catch (err) {
    panel.append(el("p", "panel__lede", `Walkthrough data unavailable (${err.message}).`));
  }
}

/* ═══ BOOT ═══════════════════════════════════════════════════════════ */

(async function boot() {
  strikeGrid();
  try {
    const [health, caps] = await Promise.all([
      fetch(`${API}/health`).then((r) => r.json()),
      fetch(`${API}/capabilities`).then((r) => r.json()),
    ]);
    seatCommittee(caps.committee || []);
    $("ledger-cost").textContent = (health.total_model_cost_usd || 0).toFixed(2);

    const note = $("conn-note");
    if (health.degraded_mode) {
      note.dataset.tone = "";
      note.textContent =
        "Engine ready. No hosted model provider is configured, so the three " +
        "judgement critics will run in degraded mode. Every computed result — " +
        "geometry, daylight, compliance, Vastu, cost — is unaffected.";
    } else {
      note.dataset.tone = "ok";
      note.textContent = `Engine ready · ${health.providers_configured.length} free provider(s) · corpus ${health.corpus.total} passages.`;
    }
  } catch (err) {
    const note = $("conn-note");
    note.dataset.tone = "bad";
    note.textContent = `Cannot reach the engine at ${API}. Start it with: uvicorn aip.api.app:app --port 8000`;
  }
})();
