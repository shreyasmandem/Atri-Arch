/* ═══════════════════════════════════════════════════════════════════════
   AIP embeddable widget

   Drops into an architecture practice's own website:

     <script src="https://your-aip-host/embed/aip-widget.js"
             data-key="aip_pk_..." data-accent="#c2603a" defer></script>

   Design constraints that shaped this file:

   * **Shadow DOM.** The widget lands on somebody else's stylesheet - often a
     WordPress theme with aggressive global selectors. A shadow root is the only
     reliable isolation, in both directions: their CSS cannot break the widget,
     and the widget cannot break their site.
   * **No dependencies, no build.** A practice's webmaster pastes one tag. A
     bundle that needs npm would never get installed.
   * **Public key only.** This runs in a browser, so it can hold no secret. The
     key is origin-bound and limited to client-facing operations server-side.
   * **The practice's brand, not ours.** Accent, name and copy come from data
     attributes and the firm record. The widget is their tool, not our advert.
   ═══════════════════════════════════════════════════════════════════════ */

(function () {
  "use strict";

  if (window.__AIP_WIDGET_LOADED__) return;
  window.__AIP_WIDGET_LOADED__ = true;

  const script =
    document.currentScript ||
    document.querySelector('script[src*="aip-widget"]');

  const cfg = {
    key: script?.dataset.key || "",
    api: (script?.dataset.api || new URL(script?.src || location.href).origin) + "/api/v1",
    accent: script?.dataset.accent || "#7FA3D4",
    practice: script?.dataset.practice || "",
    mount: script?.dataset.mount || "",
    label: script?.dataset.label || "Design my home",
    currency: script?.dataset.currency || "INR",
  };

  /* ── styles ─────────────────────────────────────────────────────────── */

  const CSS = `
:host {
  all: initial;
  font-family: "Inter", -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
  --bg: #06080D; --bg-2: #0E111A; --input: rgba(5, 6, 9, 0.85);
  --glass: rgba(255, 255, 255, 0.03);
  --rule: rgba(255, 255, 255, 0.08); --rule-2: rgba(255, 255, 255, 0.14);
  --chalk: #FFFFFF; --chalk-2: #E4E7EC; --chalk-3: #8D94A5;
  --indigo: #7FA3D4; --hingula: #F06548; --ok: #3DD68C;
  --num: "JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace;
  --r-sm: 8px; --r: 14px; --r-lg: 20px;
  --ease: cubic-bezier(.16, 1, .3, 1);
}
*, *::before, *::after { box-sizing: border-box; }

/* Form controls do not inherit font-family from the host by default - the user
   agent stylesheet sets its own. Without this the widget renders in Arial while
   everything around it uses the intended stack, which reads as a broken embed. */
button, input, select, textarea { font-family: inherit; }

.launch {
  position: fixed; right: 20px; bottom: 20px; z-index: 2147483000;
  display: inline-flex; align-items: center; gap: 9px;
  background: var(--accent); color: #fff; border: 0; border-radius: 999px;
  padding: 13px 22px; font-size: 14.5px; font-weight: 600; letter-spacing: -.01em; cursor: pointer;
  box-shadow: 0 8px 26px rgba(0,0,0,.35), inset 0 1px 1px rgba(255,255,255,.18);
  transition: transform .18s var(--ease), box-shadow .18s;
}
.launch:hover { transform: translateY(-2px); box-shadow: 0 12px 34px rgba(0,0,0,.45), inset 0 1px 1px rgba(255,255,255,.18); }
.launch svg { flex: 0 0 auto; }
.launch[hidden] { display: none; }

.scrim {
  position: fixed; inset: 0; z-index: 2147483001;
  background: rgba(0,0,0,.72); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
  display: grid; place-items: center; padding: 16px;
  animation: fade .2s ease both;
}
@keyframes fade { from { opacity: 0 } }
.scrim[hidden] { display: none; }

.shell {
  width: min(940px, 100%); max-height: min(880px, 92vh);
  background: rgba(8, 10, 15, 0.92); color: var(--chalk-2);
  border: 1px solid var(--rule-2); border-radius: var(--r-lg);
  display: flex; flex-direction: column; overflow: hidden;
  box-shadow: 0 30px 80px rgba(0,0,0,.7), inset 0 1px 1px rgba(255,255,255,.06);
  animation: rise .28s var(--ease) both;
  -webkit-font-smoothing: antialiased;
}
@keyframes rise { from { transform: translateY(14px); opacity: 0 } }

.bar {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 18px; border-bottom: 1px solid var(--rule); flex: 0 0 auto;
  background: var(--glass);
}
.bar h2 {
  margin: 0; font-size: 12px; font-weight: 650; color: var(--chalk);
  letter-spacing: .14em; text-transform: uppercase;
}
.bar .by { margin-left: auto; font-size: 11px; color: var(--chalk-3); letter-spacing: .04em; }
.x {
  appearance: none; background: rgba(255,255,255,.04); border: 1px solid var(--rule-2); color: var(--chalk-3);
  width: 30px; height: 30px; border-radius: 999px; cursor: pointer; font-size: 14px;
  line-height: 1; display: grid; place-items: center; transition: all .16s var(--ease);
}
.x:hover { color: var(--chalk); border-color: rgba(255,255,255,.3); background: rgba(255,255,255,.1); }

.body { overflow-y: auto; padding: 22px; flex: 1 1 auto; min-height: 0; }

.steps { display: flex; gap: 6px; margin-bottom: 22px; }
.steps i {
  flex: 1; height: 3px; border-radius: 999px; background: var(--rule-2); display: block;
  transition: background .3s;
}
.steps i.on { background: var(--accent); }

h3 { margin: 0 0 6px; font-size: 21px; font-weight: 700; letter-spacing: -.03em; color: var(--chalk); }
.lede { margin: 0 0 20px; color: var(--chalk-3); font-size: 13.5px; line-height: 1.6; max-width: 62ch; }

.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
label { display: block; font-size: 11.5px; font-weight: 600; color: var(--chalk-3); margin-bottom: 6px; letter-spacing: .02em; }
input, select {
  width: 100%; appearance: none; background: var(--input); color: var(--chalk);
  border: 1px solid var(--rule-2); border-radius: var(--r-sm); padding: 10px 12px;
  font: inherit; font-size: 14px; transition: border-color .16s var(--ease), box-shadow .16s var(--ease);
}
input { font-family: var(--num); font-weight: 500; }
input:hover, select:hover { border-color: rgba(255,255,255,.22); }
input:focus, select:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 28%, transparent); }
.f { margin-bottom: 14px; }

.chips { display: flex; flex-wrap: wrap; gap: 7px; }
.chip {
  appearance: none; background: var(--glass); border: 1px solid var(--rule-2); color: var(--chalk-2);
  border-radius: 999px; padding: 8px 14px; font: inherit; font-size: 13px; font-weight: 500; cursor: pointer;
  transition: all .16s var(--ease);
}
.chip:hover { border-color: rgba(255,255,255,.3); color: var(--chalk); background: rgba(255,255,255,.07); }
.chip[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: #fff; }

.actions { display: flex; gap: 9px; padding: 14px 18px; border-top: 1px solid var(--rule); flex: 0 0 auto; background: var(--glass); }
.btn {
  appearance: none; border-radius: 999px; padding: 11px 22px; font: inherit;
  font-size: 14px; font-weight: 600; letter-spacing: -.01em; cursor: pointer; border: 1px solid transparent;
  transition: all .16s var(--ease);
}
.btn--go { background: var(--accent); color: #fff; margin-left: auto; box-shadow: inset 0 1px 1px rgba(255,255,255,.18); }
.btn--go:hover { filter: brightness(1.1); transform: translateY(-1px); }
.btn--go[disabled] { opacity: .5; cursor: progress; transform: none; }
.btn--back { background: rgba(255,255,255,.04); border-color: var(--rule-2); color: var(--chalk-3); }
.btn--back:hover { color: var(--chalk); border-color: rgba(255,255,255,.3); }

.prog { font-family: var(--num); font-size: 12px; color: var(--chalk-3); line-height: 1.9; }
.prog b { color: var(--chalk); font-weight: 600; }
.track { height: 3px; border-radius: 999px; background: var(--rule-2); margin: 14px 0 18px; overflow: hidden; }
.track i { display: block; height: 100%; background: var(--accent); transform: scaleX(0);
           transform-origin: left center; transition: transform .4s var(--ease); }

.result { display: grid; grid-template-columns: 1.35fr 1fr; gap: 20px; }
@media (max-width: 700px) { .result { grid-template-columns: 1fr; } }
.plate {
  background: #000; border: 1px solid var(--rule); border-radius: var(--r); padding: 10px;
  min-height: 240px; display: grid; place-items: center;
}
.plate svg { max-width: 100%; height: auto; }

.stat {
  border: 1px solid var(--rule); border-radius: var(--r); background: var(--glass);
  padding: 12px 14px; margin-bottom: 10px;
}
.stat dt { font-size: 10.5px; font-weight: 600; letter-spacing: .12em; text-transform: uppercase; color: var(--chalk-3); }
.stat dd {
  margin: 4px 0 0; font-family: var(--num); color: var(--chalk);
  font-size: 24px; font-weight: 600; font-variant-numeric: tabular-nums; letter-spacing: -.02em;
}
.stat small { color: var(--chalk-3); font-size: 12px; font-family: var(--num); }

.note {
  font-size: 13px; line-height: 1.65; color: var(--chalk-2);
  border-left: 2px solid var(--accent); padding-left: 12px; margin: 16px 0 0;
}
.err { color: var(--hingula); font-size: 13px; line-height: 1.6; }
.fine { font-size: 11px; color: var(--chalk-3); line-height: 1.6; margin: 14px 0 0; }
`;

  /* ── data ───────────────────────────────────────────────────────────── */

  const STYLES = [
    ["tropical_modern", "Tropical modern"], ["contemporary", "Contemporary"],
    ["kerala_vernacular", "Kerala vernacular"], ["chettinad", "Chettinad"],
    ["modern_minimal", "Minimal"], ["japandi", "Japandi"],
    ["biophilic", "Biophilic"], ["traditional_indian", "Traditional Indian"],
  ];
  const VASTU = [
    ["ignore", "Not important"], ["advisory", "Advisory only"],
    ["balanced", "Balanced"], ["strict", "Strict"], ["orthodox", "Orthodox"],
  ];

  const answers = {
    plot_width: 12, plot_depth: 18, road_direction: "N", locality: "Chennai, Tamil Nadu",
    bedrooms: 3, bathrooms: 2, levels: 1,
    styles: ["tropical_modern"], vastu: "balanced", budget: 6500000,
    occupant_adults: 2, occupant_children: 0, occupant_elders: 0,
    name: "", email: "",
  };

  let step = 0, running = false, result = null;

  /* ── shell ──────────────────────────────────────────────────────────── */

  const host = document.createElement("div");
  host.setAttribute("data-aip-widget", "");
  const root = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = `:host{--accent:${cfg.accent}}` + CSS;
  root.append(style);

  const launch = document.createElement("button");
  launch.className = "launch";
  launch.type = "button";
  launch.innerHTML =
    `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
       <rect x="3" y="3" width="18" height="18"/><path d="M9 3v18M15 3v18M3 9h18M3 15h18"/>
     </svg><span></span>`;
  launch.querySelector("span").textContent = cfg.label;

  const scrim = document.createElement("div");
  scrim.className = "scrim";
  scrim.hidden = true;

  const shell = document.createElement("div");
  shell.className = "shell";
  shell.setAttribute("role", "dialog");
  shell.setAttribute("aria-modal", "true");
  shell.setAttribute("aria-label", "Design your home");
  scrim.append(shell);
  root.append(launch, scrim);

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  /* ── render ─────────────────────────────────────────────────────────── */

  function render() {
    shell.innerHTML = "";

    const bar = el("div", "bar");
    bar.append(el("h2", null, cfg.practice || "Design studio"));
    bar.append(el("span", "by", "Powered by AIP"));
    const close = el("button", "x", "×");
    close.type = "button";
    close.setAttribute("aria-label", "Close");
    close.addEventListener("click", shut);
    bar.append(close);

    const body = el("div", "body");
    const steps = el("div", "steps");
    for (let i = 0; i < 4; i++) {
      const bead = el("i");
      if (i <= step) bead.className = "on";
      steps.append(bead);
    }
    body.append(steps);

    if (step === 0) paintPlot(body);
    else if (step === 1) paintProgramme(body);
    else if (step === 2) paintTaste(body);
    else paintResult(body);

    shell.append(bar, body);

    if (step < 3) {
      const actions = el("div", "actions");
      if (step > 0) {
        const back = el("button", "btn btn--back", "Back");
        back.type = "button";
        back.addEventListener("click", () => { step--; render(); });
        actions.append(back);
      }
      const go = el("button", "btn btn--go", step === 2 ? "Design it" : "Continue");
      go.type = "button";
      go.addEventListener("click", () => {
        if (step === 2) { step = 3; render(); start(); }
        else { step++; render(); }
      });
      actions.append(go);
      shell.append(actions);
    }
  }

  function field(parent, label, key, attrs = {}) {
    const wrap = el("div", "f");
    const id = `f_${key}`;
    const lab = el("label", null, label);
    lab.htmlFor = id;
    const input = el(attrs.tag === "select" ? "select" : "input");
    input.id = id;
    if (attrs.tag === "select") {
      for (const [value, text] of attrs.options) {
        const opt = el("option", null, text);
        opt.value = value;
        if (answers[key] === value) opt.selected = true;
        input.append(opt);
      }
    } else {
      input.type = attrs.type || "text";
      input.value = answers[key];
      if (attrs.min != null) input.min = attrs.min;
      if (attrs.max != null) input.max = attrs.max;
      if (attrs.step != null) input.step = attrs.step;
    }
    input.addEventListener("input", () => {
      answers[key] = attrs.type === "number" ? Number(input.value) : input.value;
    });
    wrap.append(lab, input);
    parent.append(wrap);
    return input;
  }

  function paintPlot(body) {
    body.append(el("h3", null, "Tell us about the plot"));
    body.append(el("p", "lede",
      "Two dimensions and which way the road runs is enough to begin. " +
      "Everything else we will infer and you can correct."));
    const grid = el("div", "grid");
    field(grid, "Width (m)", "plot_width", { type: "number", min: 3, max: 200, step: 0.5 });
    field(grid, "Depth (m)", "plot_depth", { type: "number", min: 3, max: 200, step: 0.5 });
    field(grid, "Road lies to the", "road_direction", {
      tag: "select",
      options: [["N", "North"], ["NE", "North-east"], ["E", "East"], ["SE", "South-east"],
                ["S", "South"], ["SW", "South-west"], ["W", "West"], ["NW", "North-west"]],
    });
    field(grid, "Floors", "levels", { type: "number", min: 1, max: 4 });
    body.append(grid);
    field(body, "Town or city", "locality", {});
  }

  function paintProgramme(body) {
    body.append(el("h3", null, "Who is it for?"));
    body.append(el("p", "lede",
      "Room count and household shape the zoning, the privacy and whether " +
      "step-free access is designed in from the start."));
    const grid = el("div", "grid");
    field(grid, "Bedrooms", "bedrooms", { type: "number", min: 0, max: 10 });
    field(grid, "Bathrooms", "bathrooms", { type: "number", min: 0, max: 10 });
    field(grid, "Adults", "occupant_adults", { type: "number", min: 0, max: 12 });
    field(grid, "Children", "occupant_children", { type: "number", min: 0, max: 12 });
    field(grid, "Elders", "occupant_elders", { type: "number", min: 0, max: 12 });
    body.append(grid);
    field(body, `Budget (${cfg.currency})`, "budget", { type: "number", min: 0, step: 50000 });
  }

  function paintTaste(body) {
    body.append(el("h3", null, "How should it feel?"));
    body.append(el("p", "lede", "Pick the character you are drawn to, and how strictly Vastu should apply."));

    body.append(el("label", null, "Style"));
    const chips = el("div", "chips");
    for (const [value, label] of STYLES) {
      const chip = el("button", "chip", label);
      chip.type = "button";
      chip.setAttribute("aria-pressed", String(answers.styles[0] === value));
      chip.addEventListener("click", () => {
        answers.styles = [value];
        chips.querySelectorAll(".chip").forEach((c) =>
          c.setAttribute("aria-pressed", String(c === chip)));
      });
      chips.append(chip);
    }
    body.append(chips);

    const vastu = el("div", "f");
    vastu.style.marginTop = "18px";
    body.append(vastu);
    field(vastu, "Vastu", "vastu", { tag: "select", options: VASTU });

    const grid = el("div", "grid");
    field(grid, "Your name", "name", {});
    field(grid, "Email", "email", { type: "email" });
    body.append(grid);
    body.append(el("p", "fine",
      "Your details are shared only with " + (cfg.practice || "this practice") +
      " so they can follow up. Nothing is generated at any cost to you."));
  }

  function paintResult(body) {
    body.append(el("h3", null, running ? "Designing your home" : "Your scheme"));
    if (running) {
      body.append(el("p", "lede",
        "A committee of independent reviewers is checking daylight, ventilation, " +
        "privacy, building code, Vastu and cost on three competing layouts."));
      const track = el("div", "track");
      track.append(el("i"));
      body.append(track);
      body.append(el("div", "prog"));
      return;
    }
    if (!result) {
      body.append(el("p", "err", "The design could not be completed. Please try again."));
      return;
    }
    paintScheme(body, result);
  }

  function money(n) {
    if (cfg.currency !== "INR") return `${cfg.currency} ${Math.round(n).toLocaleString()}`;
    return n >= 1e7 ? `₹${(n / 1e7).toFixed(2)} Cr`
         : n >= 1e5 ? `₹${(n / 1e5).toFixed(1)} L`
         : `₹${Math.round(n).toLocaleString("en-IN")}`;
  }

  function paintScheme(body, data) {
    const wrap = el("div", "result");
    const plate = el("div", "plate");
    plate.innerHTML = data.svg || "";
    wrap.append(plate);

    const side = el("div");
    const stats = [
      ["Built area", `${Math.round((data.plan?.total_built_area) || 0)} m²`, `${(data.plan?.levels || []).length} floor(s)`],
      ["Estimated cost", money(data.cost?.total || 0),
        data.cost ? `${money(data.cost.p10)} – ${money(data.cost.p90)}` : ""],
      ["Vastu", data.vastu ? `${Math.round(data.vastu.score)}/100` : "—",
        data.vastu ? `${data.vastu.grade} · ${data.vastu.rules_assessed} rules checked` : ""],
    ];
    for (const [label, value, sub] of stats) {
      const stat = el("dl", "stat");
      stat.append(el("dt", null, label), el("dd", null, value));
      if (sub) stat.append(el("small", null, sub));
      side.append(stat);
    }
    wrap.append(side);
    body.append(wrap);

    if (data.explanation) {
      body.append(el("p", "note", String(data.explanation).split(/\n{2,}/)[0]));
    }
    body.append(el("p", "fine",
      "This is an automated first study, not a construction drawing. " +
      (cfg.practice || "The practice") + " will review it with you before anything is built."));
  }

  /* ── run ────────────────────────────────────────────────────────────── */

  async function start() {
    running = true;
    result = null;
    render();

    const prog = shell.querySelector(".prog");
    const fill = shell.querySelector(".track i");
    const say = (text, pct) => {
      if (!prog) return;
      const line = el("p");
      line.append(el("b", null, "› "), document.createTextNode(text));
      prog.append(line);
      prog.parentElement.scrollTop = prog.parentElement.scrollHeight;
      if (fill && pct != null) fill.style.transform = `scaleX(${pct})`;
    };

    try {
      const res = await fetch(`${cfg.api}/design/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": cfg.key },
        body: JSON.stringify({
          simple: {
            project_name: answers.name ? `${answers.name}'s home` : "Website enquiry",
            plot_width: answers.plot_width, plot_depth: answers.plot_depth,
            road_direction: answers.road_direction, locality: answers.locality,
            levels: answers.levels, bedrooms: answers.bedrooms, bathrooms: answers.bathrooms,
            styles: answers.styles, vastu: answers.vastu,
            budget: answers.budget, currency: cfg.currency,
            occupant_adults: answers.occupant_adults,
            occupant_children: answers.occupant_children,
            occupant_elders: answers.occupant_elders,
          },
          candidates: 3,
          client_name: answers.name,
          client_email: answers.email,
        }),
      });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "", final = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let cut;
        while ((cut = buf.indexOf("\n\n")) !== -1) {
          const frame = buf.slice(0, cut);
          buf = buf.slice(cut + 2);
          let name = "", payload = "";
          for (const line of frame.split("\n")) {
            if (line.startsWith("event:")) name = line.slice(6).trim();
            else if (line.startsWith("data:")) payload += line.slice(5).trim();
          }
          if (!payload) continue;
          let data;
          try { data = JSON.parse(payload); } catch { continue; }
          if (name === "progress" && data.status !== "running") say(data.message, data.percent);
          if (name === "result") final = data;
          if (name === "error") throw new Error(data.message || "engine error");
        }
      }
      if (!final) throw new Error("The engine returned no scheme.");

      // Fetch the ground-floor plan for display.
      try {
        const svg = await fetch(
          `${cfg.api}/plans/${final.winner_plan_id}/drawings/plan_level_0.svg?dark=true&dimensions=false`,
          { headers: { "X-API-Key": cfg.key } },
        );
        if (svg.ok) final.svg = await svg.text();
      } catch { /* the numbers still stand without the drawing */ }

      result = final;
    } catch (err) {
      result = null;
      running = false;
      render();
      const body = shell.querySelector(".body");
      body.append(el("p", "err",
        `We could not complete the design: ${err.message}. ` +
        `Please try again, or contact ${cfg.practice || "the practice"} directly.`));
      return;
    }

    running = false;
    render();
  }

  /* ── open / close ───────────────────────────────────────────────────── */

  let lastFocus = null;

  function open() {
    lastFocus = document.activeElement;
    step = 0;
    scrim.hidden = false;
    launch.hidden = true;
    render();
    shell.querySelector("input, select, button")?.focus();
    document.addEventListener("keydown", onKey);
  }

  function shut() {
    scrim.hidden = true;
    launch.hidden = false;
    document.removeEventListener("keydown", onKey);
    lastFocus?.focus?.();
  }

  function onKey(event) {
    if (event.key === "Escape") shut();
    if (event.key !== "Tab") return;
    // Trap focus inside the dialog: a modal that leaks focus to the host page
    // behind it is unusable with a keyboard or a screen reader.
    const focusable = shell.querySelectorAll(
      'button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])',
    );
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    const active = root.activeElement;
    if (event.shiftKey && active === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && active === last) { event.preventDefault(); first.focus(); }
  }

  launch.addEventListener("click", open);
  scrim.addEventListener("click", (e) => { if (e.target === scrim) shut(); });

  /* ── mount ──────────────────────────────────────────────────────────── */

  function mount() {
    const target = cfg.mount ? document.querySelector(cfg.mount) : document.body;
    (target || document.body).append(host);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }

  window.AIPWidget = { open, close: shut, config: cfg };
})();
