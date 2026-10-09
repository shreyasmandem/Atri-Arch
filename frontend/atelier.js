/* ═══════════════════════════════════════════════════════════════════════
   Atelier: the run screen.

   One stage and one column. The stage is a small 3D model of the plot
   where a team of three works for the whole run (stage3d.js). The column
   holds the scores, filled in as each specialist reports. Underneath, one
   status line and a progress bar that never stands still: it eases toward
   the end of the current stage and only passes it when the engine says the
   stage is done. Every line shown is a message the engine emitted.
   ═══════════════════════════════════════════════════════════════════════ */

const NS = "http://www.w3.org/2000/svg";
const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ═══ THE PEOPLE (by role) ════════════════════════════════════════════ */

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

const ORDER = [
  "critic.compliance", "critic.structure", "critic.cost",
  "critic.daylight", "critic.ventilation", "critic.privacy", "critic.circulation",
  "critic.accessibility", "critic.spatial",
  "critic.vastu", "critic.coherence", "critic.brief", "critic.livability",
];

export function person(id, charter = []) {
  if (PEOPLE[id]) return { id, ...PEOPLE[id] };
  if (id === PRINCIPAL.id) return PRINCIPAL;
  const c = charter.find((x) => x.id === id);
  const short = c?.axis ? c.axis.replace(/_/g, " ") : "Specialist";
  return { id, name: c?.name || id, short, role: "Specialist", pig: "chalk", glyph: "frame" };
}

export const shortName = (p) => p.short || p.name;

const GLYPHS = {
  code: "M2 3.5h4.2A1.8 1.8 0 0 1 8 5.3V13a1.6 1.6 0 0 0-1.6-1.4H2zM14 3.5H9.8A1.8 1.8 0 0 0 8 5.3V13a1.6 1.6 0 0 1 1.6-1.4H14z",
  sun: "M8 5.2a2.8 2.8 0 1 0 0 5.6 2.8 2.8 0 0 0 0-5.6zM8 1.6v1.6M8 12.8v1.6M1.6 8h1.6M12.8 8h1.6M3.5 3.5l1.1 1.1M11.4 11.4l1.1 1.1M3.5 12.5l1.1-1.1M11.4 4.6l1.1-1.1",
  wind: "M2 6h7.4A2 2 0 1 0 7.5 3.6M2 10.5h9.6a2 2 0 1 1-1.9 2.4M2 8.2h5",
  eye: "M1.6 8S4 3.6 8 3.6 14.4 8 14.4 8 12 12.4 8 12.4 1.6 8 1.6 8zM8 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4z",
  path: "M3.5 13.5c0-3 1.9-4.2 4.5-4.2s4.5-1.2 4.5-4.4M3.5 15a1.5 1.5 0 1 0 0-3M12.5 6.4a1.5 1.5 0 1 0 0-3",
  access: "M7.2 3.4a1.2 1.2 0 1 0 0-.01M7.2 5v4.2h3.6l1.6 3.6M5.4 7.4a3.4 3.4 0 1 0 4.6 4.6",
  frame: "M2.2 5.4V2.2h3.2M10.6 2.2h3.2v3.2M13.8 10.6v3.2h-3.2M5.4 13.8H2.2v-3.2M5.6 5.6h4.8v4.8H5.6z",
  column: "M2.2 2.6h11.6M2.2 13.4h11.6M5.2 2.6v10.8M10.8 2.6v10.8",
  rupee: "M4.4 3h7.2M4.4 6h7.2M6.4 3c3.4 0 3.4 6 0 6H4.4l5.8 4.2",
  mandala: "M2.4 2.4h11.2v11.2H2.4zM6.1 2.4v11.2M9.9 2.4v11.2M2.4 6.1h11.2M2.4 9.9h11.2",
  compass: "M8 1.8v1.4M8 3.2a1.2 1.2 0 1 0 0 2.4 1.2 1.2 0 0 0 0-2.4zM7.4 5.4 3.8 14M8.6 5.4l3.6 8.6M5.2 10.6h5.6",
  brief: "M5.6 2.4h4.8v2H5.6zM4.4 3.4H3v10.4h10V3.4h-1.4M5.4 8h5.2M5.4 10.6h3.4",
  home: "M2.4 7.6 8 3l5.6 4.6V13.4H2.4zM6.6 13.4V9.6h2.8v3.8",
  seal: "M8 1.8 11.6 6 8 13.4 4.4 6zM8 6.6v3.2",
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
export function avatar(p, size = 28) {
  const a = document.createElement("span");
  a.className = "av";
  a.dataset.pig = p.pig || "chalk";
  a.style.setProperty("--av", `${size}px`);
  a.append(glyph(p.glyph, "gl av__gl"));
  a.setAttribute("aria-hidden", "true");
  return a;
}

/* ═══ STAGES ══════════════════════════════════════════════════════════ */

// Where each stage ends on the bar. The engine's own percents take over
// whenever it sends them.
const STAGES = [
  ["interpret", "Reading the brief", 0.08],
  ["retrieve", "Research", 0.16],
  ["generate", "Drafting", 0.36],
  ["critique", "Review", 0.58],
  ["consensus", "Vote", 0.63],
  ["debate", "Debate", 0.70],
  ["refine", "Refinement", 0.84],
  ["negotiate", "Negotiation", 0.88],
  ["explain", "Rationale", 1.0],
];
const STAGE = Object.fromEntries(STAGES.map(([k, label, end], i) =>
  [k, { i, label, end, start: i ? STAGES[i - 1][2] : 0 }]));

const ROAD = { N: "north", NE: "north-east", E: "east", SE: "south-east", S: "south", SW: "south-west", W: "west", NW: "north-west" };

/* ═══ THE ATELIER ═════════════════════════════════════════════════════ */

class Atelier {
  constructor() {
    this.root = null;
    this.charter = [];
    this.run = 0;
    this.stage3d = null;
    this.bar = null;
    this._barTick = this._barTick.bind(this);
  }

  $(id) { return this.root.querySelector(`#${id}`); }

  mount(host) {
    this.root = host;
    host.innerHTML = `
      <div class="at-main" data-done="0">
        <div class="at-stage" id="at-stage">
          <div class="at-top">
            <div class="at-cap">
              <h2 id="at-title">The studio is at work</h2>
              <p class="at-sub" id="at-sub"></p>
            </div>
            <div class="at-ctl">
              <span class="at-clock" id="at-clock">0:00</span>
              <button type="button" class="btn btn--cream" id="at-open" hidden>Open the review</button>
              <button type="button" class="btn btn--line" id="at-cancel">Cancel</button>
            </div>
          </div>
          <div class="at-chapter">
            <p class="at-index" id="at-index">Stage 1 of 9</p>
            <p class="at-step"><span id="at-step">Starting</span></p>
            <p class="at-msg" id="at-msg" aria-live="polite"></p>
          </div>
          <p class="at-note" id="at-note" hidden></p>
          <div class="at-fail" id="at-fail" hidden role="alert"></div>
        </div>
        <aside class="at-side" aria-label="Scores">
          <div class="at-side__h">
            <h3>Scores</h3>
            <div class="at-pills" id="at-pills" role="tablist" aria-label="Schemes"></div>
          </div>
          <p class="at-overall"><span>Overall</span><b id="at-overall">—</b></p>
          <p class="at-voice" id="at-voice" aria-live="polite"></p>
          <ol class="at-scores" id="at-scores"></ol>
        </aside>
      </div>
      <div class="at-track" aria-hidden="true"><i id="at-bar"></i></div>`;
  }

  seat(charter) {
    this.charter = charter || [];
    const list = this.$("at-scores");
    list.innerHTML = "";
    const known = ORDER.filter((id) => !this.charter.length || this.charter.some((c) => c.id === id));
    const extra = this.charter.map((c) => c.id).filter((id) => !ORDER.includes(id));
    for (const id of [...known, ...extra]) {
      const p = person(id, this.charter);
      const li = document.createElement("li");
      li.className = "sc";
      li.dataset.critic = id;
      li.dataset.state = "idle";
      li.title = `${p.name} · ${p.role}`;
      const n = document.createElement("span");
      n.className = "sc__n";
      n.textContent = shortName(p);
      const v = document.createElement("span");
      v.className = "sc__v";
      v.textContent = "—";
      const b = document.createElement("i");
      b.className = "sc__b";
      b.append(document.createElement("b"));
      li.append(avatar(p, 22), n, v, b);
      list.append(li);
    }
  }

  /* ── a run ────────────────────────────────────────────────────────── */

  async begin({ brief, upload = false, fileName = "", onCancel }) {
    const run = ++this.run;
    this.brief = brief || {};
    this.upload = upload;
    this.sketches = [];
    this.letter = {};
    this.remarks = {};
    this.speech = [];
    this.speaking = false;
    this.finished = false;
    this.settled = false;
    this.failed = false;
    this.focused = null;
    this.winner = null;
    this.shot = null;
    this.started = performance.now();
    this.bar = { shown: 0, floor: 0, ceil: STAGES[0][2] };

    this.$("at-title").textContent = upload ? "Reviewing your drawing" : "The studio is at work";
    this.$("at-sub").textContent = upload ? fileName : this._briefLine(brief);
    this.$("at-pills").innerHTML = "";
    this.$("at-overall").textContent = "—";
    this.$("at-voice").textContent = "";
    this.$("at-fail").hidden = true;
    this.$("at-open").hidden = true;
    const cancel = this.$("at-cancel");
    cancel.hidden = false;
    cancel.onclick = () => onCancel && onCancel();
    this.$("at-step").textContent = "Starting";
    this.$("at-index").textContent = upload ? "Reading the drawing" : "Setting out";
    this.$("at-msg").textContent = upload ? "Reading the drawing." : "Setting out the plot.";
    this.$("at-clock").textContent = "0:00";
    this.root.querySelectorAll(".sc").forEach((li) => {
      li.dataset.state = "idle";
      li.classList.remove("is-speaking");
      li.querySelector(".sc__v").textContent = "—";
      li.querySelector(".sc__b b").style.transform = "scaleX(0)";
    });
    this.root.querySelector(".at-main").dataset.done = "0";

    cancelAnimationFrame(this.barRaf);
    this.barLast = performance.now();
    this.barRaf = requestAnimationFrame(this._barTick);

    await this._ensureStage();
    if (run !== this.run || !this.stage3d) return;
    if (!upload && brief?.plot_width && brief?.plot_depth) {
      this.stage3d.setPlot({
        w: +brief.plot_width, d: +brief.plot_depth, levels: +brief.levels || 1,
        road: brief.road_direction || "N",
        setbacks: {
          front: +brief.setback_front || 0, rear: +brief.setback_rear || 0,
          left: +brief.setback_left || 0, right: +brief.setback_right || 0,
        },
      });
      this.stage3d.plan(brief);
    }
  }

  async _ensureStage() {
    if (this.stage3d) { this.stage3d.resume(); return; }
    const note = this.$("at-note");
    try {
      const mod = await import("./stage3d.js");
      if (!mod.webglAvailable()) throw new Error("this device has no WebGL");
      const box = document.createElement("div");
      box.className = "at-3d";
      this.$("at-stage").prepend(box);
      this.stage3d = new mod.Stage3D(box);
      note.hidden = true;
    } catch (err) {
      note.textContent = `The live model could not start (${err.message}). The run continues; scores appear on the right.`;
      note.hidden = false;
    }
  }

  _briefLine(b) {
    if (!b) return "";
    const floors = +b.levels > 1 ? `${b.levels} floors` : "1 floor";
    return `${b.plot_width} × ${b.plot_depth} m  ·  road ${ROAD[b.road_direction] || b.road_direction}  ·  ${b.bedrooms} bed  ·  ${floors}`;
  }

  /* ── the bar never stands still ──────────────────────────────────── */

  _barTick(now) {
    this.barRaf = requestAnimationFrame(this._barTick);
    const dt = Math.min(0.1, (now - this.barLast) / 1000);
    this.barLast = now;
    const b = this.bar;
    if (!b) return;
    // Ease toward just short of the current stage's end: always moving,
    // slower the nearer it gets, never claiming a stage still in progress.
    const target = this.settled ? 1 : this.finished ? 0.97 : Math.max(b.floor, b.ceil - 0.012);
    const rate = this.settled ? 6 : this.finished ? 2 : 0.35;
    b.shown += (target - b.shown) * (1 - Math.exp(-dt * rate));
    this.$("at-bar").style.transform = `scaleX(${b.shown.toFixed(4)})`;
    if (!this.finished && !this.failed) {
      const s = Math.floor((now - this.started) / 1000);
      const t = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
      const c = this.$("at-clock");
      if (c.textContent !== t) c.textContent = t;
    }
  }

  _advance(stage, status, percent) {
    const st = STAGE[stage];
    if (!st || !this.bar) return;
    const b = this.bar;
    if (percent != null && percent > 1) percent /= 100;
    if (status === "running") {
      b.floor = Math.max(b.floor, percent ?? st.start);
      b.ceil = Math.max(b.ceil, st.end);
    } else {
      // Done or skipped: the bar heads into the next stage's span.
      b.floor = Math.max(b.floor, st.end);
      b.ceil = Math.max(b.ceil, STAGES[st.i + 1]?.[2] ?? 1);
    }
    if (b.shown < b.floor - 0.1) b.shown = b.floor - 0.1;
    this.stage3d?.pace(b.ceil);
    this.$("at-index").textContent = `Stage ${st.i + 1} of ${STAGES.length}`;
    this._chapter(st.label);
  }

  _chapter(word) {
    const w = this.$("at-step");
    if (w.textContent === word) return;
    w.textContent = word;
    if (!reduced()) w.animate([{ transform: "translateY(105%)" }, { transform: "none" }], { duration: 620, easing: "cubic-bezier(.16,1,.3,1)" });
  }

  _say(text) {
    const m = this.$("at-msg");
    if (!text || m.textContent === text) return;
    m.textContent = text;
    if (!reduced()) m.animate([{ opacity: 0, transform: "translateY(3px)" }, { opacity: 1, transform: "none" }],
      { duration: 280, easing: "cubic-bezier(.16,1,.3,1)" });
  }

  /** The studio speaking outside the stream (an upload's read-back). */
  say(_who, text) { this._say(this._tidy(text)); }

  _tidy(s) {
    let t = String(s || "").replace(/\.\.\./g, "…").replace(/\bm2\b/g, "m²");
    for (const [id, l] of Object.entries(this.letter)) t = t.split(id).join(`Scheme ${l}`);
    return t.replace(/plan_[0-9a-f]{6,}/g, "the scheme").replace(/\(s\)/g, "s");
  }

  /** One engine progress event. */
  progress(e) {
    if (this.finished || this.failed) return;
    const { stage, status, detail = {} } = e;
    this._advance(stage, status, e.percent);

    if (stage === "generate" && detail.sketches?.length) this._sketches(detail.sketches);
    if (stage === "critique" && detail.plan && detail.remarks) this._remarks(detail.plan, detail.remarks);
    else if (stage === "critique" && status === "running") {
      this.root.querySelectorAll('.sc[data-state="idle"]').forEach((li) => { li.dataset.state = "reading"; });
    }
    if (stage === "consensus" && status === "done" && detail.winner) this._chosen(detail.winner);
    if (stage === "negotiate" && detail.round != null && detail.proposed != null) {
      this._say(`Negotiation round ${detail.round}: ${detail.accepted} of ${detail.proposed} proposals accepted.`);
      return;
    }
    this._say(this._tidy(e.message));
  }

  /* ── schemes ──────────────────────────────────────────────────────── */

  _sketches(list) {
    this.sketches = list;
    list.forEach((s, i) => { this.letter[s.id] = String.fromCharCode(65 + i); });
    const pills = this.$("at-pills");
    pills.innerHTML = "";
    if (list.length > 1) {
      for (const s of list) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "pill";
        b.dataset.plan = s.id;
        b.dataset.state = "drafting";
        b.setAttribute("role", "tab");
        b.setAttribute("aria-label", `Scheme ${this.letter[s.id]}`);
        b.innerHTML = "<span></span><b></b>";
        b.querySelector("span").textContent = this.letter[s.id];
        b.addEventListener("click", () => this._focus(s.id));
        pills.append(b);
      }
    }
    const st = this.stage3d;
    if (st && this.upload) {
      const s = list[0];
      st.setPlot({ w: s.bbox[2] - s.bbox[0], d: s.bbox[3] - s.bbox[1], levels: s.levels.length || 1, road: (s.road || "N")[0] });
    }
    if (st) list.forEach((s) => st.addScheme(s));
    this._focus(list[0].id);
  }

  _focus(id) {
    if (!this.letter[id]) return;
    this.focused = id;
    this.root.querySelectorAll(".pill").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.plan === id)));
    this._paintScores(id);
    this.stage3d?.draw(id, { fast: this.finished });
  }

  _pill(id, state, value) {
    const b = this.root.querySelector(`.pill[data-plan="${id}"]`);
    if (!b) return;
    if (state && b.dataset.state !== "chosen") b.dataset.state = state;
    if (value != null) b.querySelector("b").textContent = value.toFixed(2);
  }

  _remarks(planId, remarks) {
    this.remarks[planId] = Object.fromEntries(remarks.map((r) => [r.critic, r]));
    const mean = remarks.reduce((a, r) => a + r.score, 0) / Math.max(1, remarks.length);
    this._pill(planId, "reviewed", mean);
    // The specialists report in turn on the scheme on the board; the
    // others' scores land quietly on their pills.
    if (planId === this.focused) {
      for (const r of remarks) this.speech.push(r);
      if (!this.speaking) this._speak();
    }
  }

  async _speak() {
    this.speaking = true;
    const run = this.run;
    while (this.speech.length && run === this.run && !this.failed) {
      const r = this.speech.shift();
      const li = this.root.querySelector(`.sc[data-critic="${r.critic}"]`);
      this.root.querySelectorAll(".sc.is-speaking").forEach((x) => x.classList.remove("is-speaking"));
      if (li) {
        li.classList.add("is-speaking");
        this._score(li, r.score);
      }
      const p = person(r.critic, this.charter);
      const v = this.$("at-voice");
      v.replaceChildren();
      const who = document.createElement("b");
      who.textContent = p.name;
      v.append(who, document.createTextNode(this._tidy(r.line)));
      if (!reduced()) v.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 240 });
      this.stage3d?.critique({ critic: r.critic, short: shortName(p), pig: p.pig, line: this._tidy(r.line), score: r.score });
      if (this.finished) break;
      await sleep(this.speech.length > 14 ? 260 : this.speech.length > 5 ? 520 : 950);
    }
    this.root.querySelectorAll(".sc.is-speaking").forEach((x) => x.classList.remove("is-speaking"));
    this.speaking = false;
  }

  _score(li, score) {
    li.dataset.state = score < 0.55 ? "low" : "done";
    const v = li.querySelector(".sc__v");
    li.querySelector(".sc__b b").style.transform = `scaleX(${Math.max(0, Math.min(1, score))})`;
    const from = parseFloat(v.textContent);
    if (reduced()) { v.textContent = score.toFixed(2); return; }
    const start = Number.isNaN(from) ? 0 : from;
    const t0 = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - t0) / 420);
      v.textContent = (start + (score - start) * (1 - Math.pow(1 - k, 3))).toFixed(2);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  _paintScores(planId) {
    const rem = this.remarks[planId];
    if (!rem) return;
    this.root.querySelectorAll(".sc").forEach((li) => {
      const r = rem[li.dataset.critic];
      if (r) this._score(li, r.score);
    });
  }

  _chosen(planId) {
    this.winner = planId;
    const b = this.root.querySelector(`.pill[data-plan="${planId}"]`);
    if (b) b.dataset.state = "chosen";
    if (this.focused !== planId) this._focus(planId);
  }

  /* ── the end ──────────────────────────────────────────────────────── */

  async result(d, { onOpen } = {}) {
    if (this.failed) return;
    const run = this.run;
    this.finished = true;
    this.speech = [];
    const cand = d.selected_candidate_id || d.consensus?.winner_id;
    if (cand && this.letter[cand] && this.winner !== cand) this._chosen(cand);
    for (const row of d.consensus?.ranking || []) this._pill(row.candidate_id, null, row.score);

    const row = (d.consensus?.ranking || []).find((r) => r.candidate_id === cand);
    const score = row?.score ?? d.consensus?.winner_score;
    if (score != null) this.$("at-overall").textContent = score.toFixed(2);
    this._paintScores(cand);

    const agree = d.consensus?.overall_agreement;
    this.$("at-index").textContent = "Decided";
    this._chapter(this.upload ? "Reviewed" : `Scheme ${this.letter[cand] || "A"}`);
    this.$("at-clock").textContent += " total";
    this._say(agree != null
      ? `${Math.round(agree * 100)}% of the committee agreed.`
      : "The committee has reported.");
    this.root.querySelector(".at-main").dataset.done = "1";

    if (this.stage3d) await Promise.race([this.stage3d.settle(), sleep(19000)]);
    if (run !== this.run) return;
    this.settled = true;
    this.shot = this.stage3d?.snapshot() || null;

    const open = this.$("at-open");
    this.$("at-cancel").hidden = true;
    open.hidden = false;
    let clicked;
    const click = new Promise((r) => { clicked = r; });
    open.onclick = () => clicked();
    await Promise.race([click, sleep(reduced() ? 300 : 1100)]);
    open.hidden = true;
    if (run === this.run && onOpen) onOpen();
  }

  fail(title, message, { onBack } = {}) {
    this.failed = true;
    const box = this.$("at-fail");
    box.innerHTML = '<h3></h3><p></p><button type="button" class="btn btn--cream">Back to the brief</button>';
    box.querySelector("h3").textContent = title;
    box.querySelector("p").textContent = message;
    box.querySelector("button").onclick = () => onBack && onBack();
    box.hidden = false;
    this._chapter("Stopped");
    this.$("at-cancel").hidden = true;
    this._say(message);
  }

  /** Leave the run screen: stop the clocks and the model. */
  stop() {
    this.run++;
    this.speech = [];
    cancelAnimationFrame(this.barRaf);
    this.stage3d?.pause();
  }

  /** The settled board, as an image to carry into the review. */
  currentSheet() {
    if (!this.shot) return null;
    const img = document.createElement("img");
    img.src = this.shot;
    img.alt = "";
    return img;
  }
}

export const atelier = new Atelier();
