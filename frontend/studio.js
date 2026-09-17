/* ═══════════════════════════════════════════════════════════════════════
   Studio

   Three phases, one URL: compose -> running -> review. Every result surface
   the engine can produce is reachable here, because a committee that reports
   twenty-five findings and shows you none of them is not explainable, it is
   just quiet.
   ═══════════════════════════════════════════════════════════════════════ */

const API = (() => {
  const o = new URLSearchParams(location.search).get("api");
  if (o) return o.replace(/\/$/, "");
  return `${location.origin}/api/v1`;
})();

const $ = (id) => document.getElementById(id);
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
const HEX = { indigo: "#7FA3D4", hingula: "#E4694C", ochre: "#DFA85C", orpiment: "#F0D165", chalk: "#9C9078" };

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
  plans: {},          // id -> { plan, vastu, cost, interior, analysis, drawing }
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

function phase(p) { S.phase = p; document.body.dataset.phase = p; }

/* ═══ MANDALA ════════════════════════════════════════════════════════ */

function strike(svg) {
  const N = 9, U = 900 / N, out = [];
  for (let r = 0; r < N; r++)
    for (let c = 0; c < N; c++)
      out.push(`<rect class="pada" data-r="${r}" data-c="${c}" x="${c * U}" y="${r * U}" width="${U}" height="${U}" fill="transparent" stroke="#2E2517" stroke-width="1"/>`);
  out.push(`<path d="M0 0L900 900M900 0L0 900" stroke="#2E2517" stroke-width="1" opacity=".45"/>`);
  out.push(`<rect x="${3 * U}" y="${3 * U}" width="${3 * U}" height="${3 * U}" fill="none" stroke="#453724" stroke-width="2"/>`);
  svg.innerHTML = out.join("");
}

/** Project the plan onto the 9x9 field and light each room's padas. */
function lightPadas(svg, plan) {
  if (!svg || !plan?.levels?.length) return { occupied: 0, sectors: [] };
  svg.querySelectorAll(".pada").forEach((p) => {
    p.setAttribute("fill", "transparent"); p.setAttribute("stroke", "#2E2517"); p.removeAttribute("data-lit");
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
    } else { p.setAttribute("stroke", "#9C9078"); }
  }
  return { occupied, sectors };
}

/* ═══ COSMIC STAR-FIELD RENDERER ═════════════════════════════════════ */

function initStarField() {
  if (window.self !== window.top) return { spread: () => {} };
  const canvas = document.getElementById("space-stars");
  if (!canvas) return { spread: () => {} };
  const ctx = canvas.getContext("2d");

  const INTRO_STAR_COUNT = 32;
  const BURST_STAR_COUNT = 200;
  const stars = [];
  let state = "forming"; // "forming" | "splitting" | "ambient"
  let spreadStart = 0;
  let birthTime = performance.now();
  let cx = window.innerWidth / 2;
  let cy = window.innerHeight / 2;
  let dpr = 1;
  let mouse = { x: -1000, y: -1000, active: false };

  function updateCenter() {
    const stage = document.querySelector(".intro-brand-stage");
    if (stage && state === "forming") {
      const rect = stage.getBoundingClientRect();
      cx = rect.left + rect.width / 2;
      cy = rect.top + rect.height / 2;
    } else {
      cx = window.innerWidth / 2;
      cy = window.innerHeight / 2;
    }
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width  = Math.floor(window.innerWidth * dpr);
    canvas.height = Math.floor(window.innerHeight * dpr);
    canvas.style.width  = window.innerWidth + "px";
    canvas.style.height = window.innerHeight + "px";
    updateCenter();
  }

  // Celestial palette
  const COLORS = [
    { rgb: "255, 255, 255", glow: "rgba(255, 255, 255, 0.35)" },
    { rgb: "255, 255, 255", glow: "rgba(255, 255, 255, 0.35)" },
    { rgb: "245, 248, 255", glow: "rgba(200, 225, 255, 0.30)" },
    { rgb: "245, 205, 130", glow: "rgba(229, 169, 88, 0.40)" },
    { rgb: "170, 205, 255", glow: "rgba(127, 163, 212, 0.35)" },
  ];

  // Creates wide-apart initial stars scattered across the deep space perimeter
  function createIntroStar(index) {
    const angle = Math.random() * Math.PI * 2;
    // Spread wide across the screen: minimum 240px away from logo so center is pristine
    const maxRadius = Math.max(window.innerWidth, window.innerHeight) * 0.55;
    const orbitR = Math.random() * (maxRadius - 240) + 240;

    const dir = Math.random() > 0.5 ? 1 : -1;
    const orbitSpeed = (Math.random() * 0.002 + 0.001) * dir;

    const targetX = Math.random() * window.innerWidth;
    const targetY = Math.random() * window.innerHeight;

    const isHero = Math.random() < 0.15;
    const radius = isHero
      ? Math.random() * 0.8 + 1.6
      : Math.random() * 0.9 + 0.6;

    const col = COLORS[Math.floor(Math.random() * COLORS.length)];
    const popDelay = (index / INTRO_STAR_COUNT) * 1400 + Math.random() * 300;

    return {
      x: cx + Math.cos(angle) * orbitR,
      y: cy + Math.sin(angle) * (orbitR * 0.75),
      orbitR, orbitAngle: angle, orbitSpeed,
      targetX, targetY,
      vx: 0, vy: 0,
      r: radius,
      isHero,
      introAlpha: Math.random() * 0.30 + 0.55,
      ambientAlpha: Math.random() * 0.10 + 0.14, // Calm, dull background presence
      color: col,
      phase: Math.random() * Math.PI * 2,
      twinkleSpeed: Math.random() * 0.002 + 0.001,
      driftX: (Math.random() - 0.5) * 0.08,
      driftY: (Math.random() - 0.5) * 0.08,
      popDelay,
      popDuration: 400,
    };
  }

  // Creates additional stars generated during the supernova spread
  function createBurstStar() {
    const angle = Math.random() * Math.PI * 2;
    const startDist = Math.random() * 60 + 10;
    const targetX = Math.random() * window.innerWidth;
    const targetY = Math.random() * window.innerHeight;

    const isHero = Math.random() < 0.08;
    const radius = isHero
      ? Math.random() * 0.8 + 1.5
      : Math.random() * 0.8 + 0.5;

    const col = COLORS[Math.floor(Math.random() * COLORS.length)];
    const speed = Math.random() * 24 + 14;

    return {
      x: cx + Math.cos(angle) * startDist,
      y: cy + Math.sin(angle) * startDist,
      orbitR: 0, orbitAngle: angle, orbitSpeed: 0,
      targetX, targetY,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      r: radius,
      isHero,
      introAlpha: Math.random() * 0.35 + 0.65,
      ambientAlpha: Math.random() * 0.10 + 0.14,
      color: col,
      phase: Math.random() * Math.PI * 2,
      twinkleSpeed: Math.random() * 0.002 + 0.001,
      driftX: (Math.random() - 0.5) * 0.08,
      driftY: (Math.random() - 0.5) * 0.08,
      popDelay: 0,
      popDuration: 0,
    };
  }

  function seed() {
    stars.length = 0;
    updateCenter();
    birthTime = performance.now();
    for (let i = 0; i < INTRO_STAR_COUNT; i++) {
      stars.push(createIntroStar(i));
    }
  }

  function spread(fast = false) {
    if (state === "ambient") return;
    state = "splitting";
    spreadStart = performance.now();
    updateCenter();

    // 1. Give existing wide stars an outward impulse
    for (let i = 0; i < stars.length; i++) {
      const s = stars[i];
      const angle = Math.atan2(s.y - cy, s.x - cx) + (Math.random() - 0.5) * 0.25;
      const speed = fast ? (Math.random() * 20 + 14) : (Math.random() * 15 + 8);
      s.vx = Math.cos(angle) * speed;
      s.vy = Math.sin(angle) * speed;
    }

    // 2. Dynamically generate full cosmos burst stars erupting from center outward
    const burstCount = fast ? Math.floor(BURST_STAR_COUNT * 0.75) : BURST_STAR_COUNT;
    for (let i = 0; i < burstCount; i++) {
      stars.push(createBurstStar());
    }
  }

  function draw(t) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.scale(dpr, dpr);

    if (state === "forming") {
      updateCenter();
    }

    const w = window.innerWidth;
    const h = window.innerHeight;
    const elapsed = t - birthTime;

    for (let i = 0; i < stars.length; i++) {
      const s = stars[i];

      // ─── 1. FORMING: Minimal, wide-spaced stars softly popping in around perimeter ───
      if (state === "forming") {
        if (elapsed < s.popDelay) continue;

        const popAge = elapsed - s.popDelay;
        const popFade = Math.min(popAge / s.popDuration, 1);
        const popEase = 1 - Math.pow(1 - popFade, 3);

        s.orbitAngle += s.orbitSpeed;
        s.x = cx + Math.cos(s.orbitAngle) * s.orbitR;
        s.y = cy + Math.sin(s.orbitAngle) * (s.orbitR * 0.75);

        const alpha = s.introAlpha * popEase;
        const rNow = s.r * (0.4 + 0.6 * popEase);

        if (rNow > 0.7) {
          ctx.beginPath();
          ctx.arc(s.x, s.y, rNow * 2.2, 0, Math.PI * 2);
          ctx.fillStyle = s.color.glow;
          ctx.globalAlpha = popEase * 0.6;
          ctx.fill();
          ctx.globalAlpha = 1;
        }

        ctx.beginPath();
        ctx.arc(s.x, s.y, rNow, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${s.color.rgb}, ${alpha.toFixed(3)})`;
        ctx.fill();
      }

      // ─── 2. SPLITTING: Dynamic star eruption & settling into wide positions ───
      else if (state === "splitting") {
        s.x += s.vx;
        s.y += s.vy;
        s.vx *= 0.91;
        s.vy *= 0.91;

        s.x += (s.targetX - s.x) * 0.055;
        s.y += (s.targetY - s.y) * 0.055;

        const splitAge = performance.now() - spreadStart;
        const fadeProgress = Math.min(splitAge / 1800, 1);
        const alpha = s.introAlpha * (1 - fadeProgress) + s.ambientAlpha * fadeProgress;

        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${s.color.rgb}, ${alpha.toFixed(3)})`;
        ctx.fill();

        if (splitAge > 1850) {
          state = "ambient";
        }
      }

      // ─── 3. AMBIENT: Dull, subtle, wide-apart peaceful starry void ───
      else {
        s.x += s.driftX;
        s.y += s.driftY;

        if (s.x < 0) s.x = w;
        if (s.x > w) s.x = 0;
        if (s.y < 0) s.y = h;
        if (s.y > h) s.y = 0;

        if (mouse.active) {
          const mdx = s.x - mouse.x;
          const mdy = s.y - mouse.y;
          const mdist = Math.hypot(mdx, mdy);
          if (mdist < 100 && mdist > 0) {
            const push = (1 - mdist / 100) * 1.2;
            s.x += (mdx / mdist) * push;
            s.y += (mdy / mdist) * push;
          }
        }

        const twinkle = Math.sin(t * s.twinkleSpeed + s.phase) * 0.05 + 0.95;
        const alpha = s.ambientAlpha * twinkle;

        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${s.color.rgb}, ${alpha.toFixed(3)})`;
        ctx.fill();
      }
    }

    ctx.restore();
    requestAnimationFrame(draw);
  }

  resize();
  seed();
  requestAnimationFrame(draw);

  window.addEventListener("resize", () => {
    resize();
    if (state === "ambient") seed();
  });

  window.addEventListener("mousemove", (e) => {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
    mouse.active = true;
    document.documentElement.style.setProperty("--mouse-x", `${e.clientX}px`);
    document.documentElement.style.setProperty("--mouse-y", `${e.clientY}px`);
  });
  window.addEventListener("mouseleave", () => { mouse.active = false; });

  return { spread };
}

/* ═══ BOOT ═══════════════════════════════════════════════════════════ */

function updatePlotStats() {
  const w = parseFloat($("inp-plot-width")?.value || 12);
  const d = parseFloat($("inp-plot-depth")?.value || 18);
  const areaM2 = (w * d).toFixed(0);
  const areaSqFt = (w * d * 10.7639).toFixed(0);
  const badge = $("plot-area-calc");
  if (badge) {
    badge.textContent = `${areaM2} m² · ${Number(areaSqFt).toLocaleString()} sq ft (Aspect 1:${(d/w).toFixed(2)})`;
  }
}

(async function boot() {
  // Cosmic Star-field Engine
  const starField = initStarField();

  // Intro Drawing Screen Controller
  const curtain = $("intro-curtain");
  const skipBtn = $("intro-skip");
  const inIframe = window.self !== window.top;

  if (curtain) {
    if (inIframe) {
      curtain.style.display = "none";
      document.body.classList.remove("is-loading");
      starField.spread(true);
    } else {
      let isDismissed = false;
      const triggerBlast = () => {
        // Trigger stars explosion from center collision blast
        starField.spread(false);
      };

      const dismissIntro = (fast = false) => {
        if (isDismissed) return;
        isDismissed = true;
        starField.spread(fast);
        document.body.classList.remove("is-loading");
        curtain.classList.add("is-fading");
        setTimeout(() => { curtain.style.display = "none"; }, 850);
      };

      // 1. Trigger Star Blast when silver collapses into gold in center (1.45s)
      const blastTimer = setTimeout(triggerBlast, 1450);

      // 2. Smoothly transition into home studio after intro sequence (3.3s)
      const introTimer = setTimeout(() => dismissIntro(false), 3300);

      skipBtn?.addEventListener("click", (e) => {
        e.stopPropagation();
        clearTimeout(blastTimer);
        clearTimeout(introTimer);
        dismissIntro(true);
      });
      curtain.addEventListener("click", () => {
        clearTimeout(blastTimer);
        clearTimeout(introTimer);
        dismissIntro(true);
      });
    }
  }



  strike($("hero-mandala"));
  strike($("review-mandala"));
  updatePlotStats();

  $("inp-plot-width")?.addEventListener("input", updatePlotStats);
  $("inp-plot-depth")?.addEventListener("input", updatePlotStats);

  $("stance").addEventListener("input", (e) => {
    const [n, , note] = STANCES[+e.target.value];
    $("stance-name").textContent = n; $("stance-note").textContent = note;
  });
  $("brief").addEventListener("submit", onSubmit);
  $("home").addEventListener("click", () => { if (S.phase === "review") phase("compose"); });
  $("restart").addEventListener("click", () => phase("compose"));
  $("see-why").addEventListener("click", openWhy);
  $("why-close").addEventListener("click", () => { $("why").hidden = true; });
  $("why").addEventListener("click", (e) => { if (e.target === $("why")) $("why").hidden = true; });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      $("why").hidden = true;
      if (compareModal) compareModal.hidden = true;
    }
  });
  $("dl-svg").addEventListener("click", downloadSheet);
  $("dl-dxf").addEventListener("click", downloadDxf);
  $("zoom").addEventListener("click", () => {
    const on = $("plate").classList.toggle("is-zoomed");
    $("zoom").textContent = on ? "Fit to frame" : "Actual size";
  });
  document.querySelectorAll(".view-tab").forEach((t) =>
    t.addEventListener("click", () => showView(t.dataset.view)));

  try {
    const [h, c] = await Promise.all([
      fetch(`${API}/health`).then((r) => r.json()),
      fetch(`${API}/capabilities`).then((r) => r.json()),
    ]);
    S.committee = c.committee || [];
    $("ledger-cost").textContent = (h.total_model_cost_usd || 0).toFixed(2);
    $("convene-sub").textContent = `${S.committee.length} critics · 3 schemes · ₹0 to run`;

    const note = $("engine-note");
    if (h.degraded_mode) {
      note.textContent = "Engine ready. No hosted model provider is configured, so the three judgement critics will run in a labelled degraded mode. Every computed result — geometry, daylight, compliance, Vastu, cost — is unaffected.";
    } else {
      note.dataset.tone = "ok";
      note.textContent = `Engine ready · ${h.providers_configured.length} free provider(s) · ${h.corpus.total} corpus passages · $0.00 spent.`;
    }
    seatCritics();
  } catch {
    const note = $("engine-note");
    note.dataset.tone = "bad";
    note.textContent = `Cannot reach the engine at ${API}. Start it with:  uvicorn aip.api.app:app --port 8000`;
  }
})();

function seatCritics() {
  const run = $("run-critics"); run.innerHTML = "";
  const rail = $("critics"); rail.innerHTML = "";
  for (const c of S.committee) {
    const pig = CRITIC_PIG[c.id] || "chalk";

    const li = el("li", "rc"); li.dataset.critic = c.id; li.dataset.pig = pig;
    li.append(el("i", "rc__g"), el("span", "rc__n", c.name), el("span", "rc__s", "—"));
    run.append(li);

    const row = el("li", "cr"); row.dataset.critic = c.id; row.dataset.pig = pig;
    row.title = c.charter || "";
    const bar = el("span", "cr__b"); bar.append(el("i"));
    row.append(el("i", "cr__g"), el("span", "cr__n", c.name),
      el("span", "cr__k", c.analytical ? "computed" : "judged"),
      el("span", "cr__s", "—"), bar);
    rail.append(row);
  }
}

/* ═══ RUN ════════════════════════════════════════════════════════════ */

function readBrief() {
  const d = new FormData($("brief")); const n = (k) => Number(d.get(k) || 0);
  return {
    project_name: "Studio scheme",
    plot_width: n("plot_width"), plot_depth: n("plot_depth"),
    locality: String(d.get("locality") || ""), road_direction: String(d.get("road_direction") || "N"),
    levels: n("levels") || 1, bedrooms: n("bedrooms"), bathrooms: n("bathrooms"),
    styles: [String(d.get("styles") || "contemporary")],
    budget: n("budget"), currency: "INR",
    vastu: STANCES[n("vastu_slider")][1],
    occupant_adults: n("occupant_adults"), occupant_children: n("occupant_children"),
    occupant_elders: n("occupant_elders"),
  };
}

async function onSubmit(e) {
  e.preventDefault();
  if (S.phase === "running") return;

  S.briefSent = readBrief();
  S.plans = {}; S.planIds = []; S.activeId = null;
  phase("running");
  $("run-log").innerHTML = "";
  $("run-fill").style.transform = "scaleX(0)";
  $("run-title").textContent = "The committee is sitting";
  document.querySelectorAll(".rc").forEach((r) => {
    r.classList.remove("is-in"); r.querySelector(".rc__s").textContent = "—";
  });
  document.querySelectorAll(".cr").forEach((r) => {
    r.classList.remove("is-low");
    r.querySelector(".cr__s").textContent = "—";
    r.querySelector(".cr__b i").style.transform = "scaleX(0)";
  });

  try {
    await stream(S.briefSent);
  } catch (err) {
    toast(`The engine could not complete this design: ${err.message}`);
    $("run-title").textContent = "The run failed";
    $("restart").hidden = false;
  }
}

async function stream(simple) {
  const res = await fetch(`${API}/design/stream`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ simple, candidates: 3, include_generative_critics: true }),
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
      if (sawResult || S.phase !== "running") return;
      $("run-title").textContent = "The engine stopped responding";
      $("run-stage").textContent =
        "No update for three minutes. The run may still be finishing on the server; check its log, or start again.";
      $("restart").hidden = false;
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

  if (!sawResult && S.phase === "running") {
    $("run-title").textContent = "The run ended without a scheme";
    $("run-stage").textContent =
      "The engine closed the connection before returning a design. Check the server log, then try again.";
    $("restart").hidden = false;
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
    if (d.status !== "running" || d.stage === "critique") {
      const p = el("p"); p.append(el("b", null, `${d.stage} `), document.createTextNode(d.message));
      $("run-log").append(p); $("run-log").scrollTop = $("run-log").scrollHeight;
    }
    $("run-stage").textContent = d.message;
    $("run-fill").style.transform = `scaleX(${d.percent || 0})`;
    if (d.detail?.scores) markScores(d.detail.scores);
  } else if (name === "result") {
    applyResult(d);
  } else if (name === "error") {
    toast(d.message || "The engine reported an error.");
  }
}

function markScores(scores) {
  for (const [axis, score] of Object.entries(scores)) {
    const c = S.committee.find((x) => x.axis === axis); if (!c) return;
    const rc = document.querySelector(`.rc[data-critic="${c.id}"]`);
    if (rc) { rc.classList.add("is-in"); rc.querySelector(".rc__s").textContent = score.toFixed(2); }
  }
}

/* ═══ RESULT ═════════════════════════════════════════════════════════ */

async function applyResult(d) {
  window.dispatchEvent(new Event("aip:result"));
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

  S.plans[d.winner_plan_id] = { plan: d.plan, vastu: d.vastu, cost: d.cost };
  $("ledger-cost").textContent = (d.model_cost_usd || 0).toFixed(2);
  if (d.degraded) toast(d.degraded_reason || "Some critics ran in degraded mode.");

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
    b.append(document.createTextNode(`Scheme ${String.fromCharCode(65 + i)}`));

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
  $("pick-name").textContent = idx >= 0
    ? `Scheme ${String.fromCharCode(65 + idx)}`
    : "Selected scheme";
  const dq = (S.consensus?.disqualified || []).find((d) => d.candidate_id === activeCandidate());
  $("pick-why").textContent = dq
    ? `Disqualified. ${dq.reasons[0] || "It carries a critical finding."} A statutory or physical breach removes a scheme regardless of how it scores elsewhere.`
    : S.activeId === S.winnerId
      ? "Selected by the committee as the best trade-off across every measured axis."
      : "An alternative on the trade-off frontier. Compare it against the selected scheme.";

  const row = rankingRow();
  const bars = $("axis-bars"); bars.innerHTML = "";
  const axes = Object.entries(row?.axis_scores || {}).sort((a, b) => a[1] - b[1]);
  for (const [axis, v] of axes) {
    const d = el("div", "abar");
    const top = el("div", "abar__top");
    top.append(el("span", null, cap(axis)), el("b", null, v.toFixed(2)));
    const t = el("div", "abar__t"); const i = el("i");
    i.style.background = v < 0.5 ? HEX.hingula : v < 0.75 ? HEX.ochre : HEX.indigo;
    t.append(i); d.append(top, t); bars.append(d);
    requestAnimationFrame(() => { i.style.transform = `scaleX(${v})`; });
  }

  const b = S.briefSent || {};
  const recap = $("brief-recap"); recap.innerHTML = "";
  const rows = [
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
  document.querySelectorAll(".cr").forEach((el2) => {
    const c = S.committee.find((x) => x.id === el2.dataset.critic);
    const v = c ? scores[c.axis] : undefined;
    el2.querySelector(".cr__s").textContent = v == null ? "—" : v.toFixed(2);
    el2.classList.toggle("is-low", v != null && v < 0.55);
    const fill = el2.querySelector(".cr__b i");
    requestAnimationFrame(() => { fill.style.transform = `scaleX(${v ?? 0})`; });
  });
  const ag = S.consensus?.overall_agreement;
  $("agree-chip").textContent = ag == null ? "" : `${Math.round(ag * 100)}% agreed`;
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

function showView(v) {
  S.view = v;
  document.querySelectorAll(".view-tab").forEach((t) => t.classList.toggle("is-on", t.dataset.view === v));
  document.querySelectorAll(".pane").forEach((p) => { p.hidden = p.dataset.view !== v; });

  if (v === "mandala") renderMandala();
  if (v === "vastu") renderVastu();
  if (v === "cost") renderCost();
  if (v === "interior") renderInterior();
  if (v === "model") renderModel();
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

function buildSheetTabs() {
  const { plan } = cur();
  const tabs = $("sheet-tabs"); tabs.innerHTML = "";
  const levels = plan?.levels || [];
  const sheets = [
    ...levels.map((lv) => [`plan_level_${lv.index}`, lv.index === 0 ? "Ground plan" : `Level ${lv.index}`]),
    ["elevation_N", "North"], ["elevation_E", "East"], ["elevation_S", "South"], ["elevation_W", "West"],
    ["section_aa", "Section A–A"], ["section_bb", "Section B–B"], ["roof_plan", "Roof"], ["site_plan", "Site"],
    ...levels.map((lv) => [`airflow_level_${lv.index}`, levels.length > 1 ? `Airflow L${lv.index}` : "Airflow"]),
  ];
  for (const [key, label] of sheets) {
    const b = el("button", null, label); b.type = "button"; b.setAttribute("role", "tab");
    b.dataset.sheet = key;
    b.setAttribute("aria-selected", String(key === S.sheet));
    b.addEventListener("click", () => loadSheet(key));
    tabs.append(b);
  }
}

async function loadSheet(key) {
  S.sheet = key;
  $("sheet-tabs").querySelectorAll("button").forEach((b) =>
    b.setAttribute("aria-selected", String(b.dataset.sheet === key)));
  const plate = $("plate");
  plate.innerHTML = "";
  plate.append(el("p", "empty-note", "Drawing…"));
  try {
    const r = await fetch(`${API}/plans/${S.activeId}/drawings/${key}.svg?dark=true`);
    if (!r.ok) throw new Error(String(r.status));
    plate.innerHTML = await r.text();
    const { plan } = cur();
    $("plate-caption").textContent =
      `${(plan?.total_built_area || 0).toFixed(1)} m² built-up · FAR ${(plan?.achieved_far || 0).toFixed(2)} · ` +
      `${(plan?.levels || []).length} level(s) · ${plan?.style ? cap(plan.style) : ""}`;
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
  const s = scrollPane("model");
  s.append(el("h3", "sec", "Three-dimensional model"));
  s.append(el("p", "lede", "Exported as glTF, which every browser, phone and XR headset reads natively. Open it on a phone to place the scheme in a real room."));

  const links = el("div"); links.style.cssText = "display:flex;gap:8px;flex-wrap:wrap;margin-bottom:24px";
  for (const [label, href] of [
    ["Download model (.glb)", `${API}/plans/${S.activeId}/model.glb`],
    ["Download for CAD (.obj)", `${API}/plans/${S.activeId}/model.obj`],
  ]) {
    const a = el("a", "ghost-btn", label); a.href = href; a.style.textDecoration = "none"; links.append(a);
  }
  s.append(links);

  try {
    const d = await fetch(`${API}/plans/${S.activeId}/walkthrough`).then((r) => r.json());
    const st = d.statistics || {};
    const stats = el("div", "stat-row");
    for (const [pig, k, v2, sub] of [
      ["indigo", "Triangles", (st.triangles || 0).toLocaleString(), `${st.parts || 0} parts`],
      ["chalk", "Height", `${(st.height_m || 0).toFixed(2)} m`, `${st.bounds?.width_m ?? "—"} × ${st.bounds?.depth_m ?? "—"} m`],
      ["orpiment", "Waypoints", `${(d.waypoints || []).length}`, "narrated route"],
    ]) {
      const dl = el("dl", "stat"); dl.dataset.pig = pig;
      dl.append(el("dt", null, k), el("dd", null, v2), el("small", null, sub)); stats.append(dl);
    }
    s.append(stats);

    s.append(el("h3", "sec", "Narrated walkthrough"));
    const play = el("button", "ghost-btn", "Play narration"); play.type = "button";
    play.style.marginBottom = "16px";
    play.addEventListener("click", () => {
      if (!("speechSynthesis" in window)) return toast("This browser has no speech synthesis.");
      speechSynthesis.cancel();
      for (const line of d.narration || []) speechSynthesis.speak(new SpeechSynthesisUtterance(line.text));
    });
    s.append(play);
    for (const line of d.narration || []) {
      const p = el("p", "find__t", line.text);
      p.style.cssText = "padding:10px 0;border-bottom:1px solid var(--rule);margin:0";
      s.append(p);
    }
    if (d.ar?.note) s.append(el("p", "note-card", d.ar.note));
  } catch (err) {
    s.append(el("p", "empty-note", `Walkthrough data unavailable (${err.message}).`));
  }
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
