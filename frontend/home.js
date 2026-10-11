/* ═══════════════════════════════════════════════════════════════════════
   Home: describe the house in your own words.

   A conversation with the studio's lead architect, in any language. What
   she understands lands at once in the brief strip above the conversation
   and in the specification sheet, so the plot drawing beside the chat
   redraws while the client talks. When the essentials are known, Start
   designing runs the studio on exactly that brief. The sheet itself stays
   one click away for anyone who prefers fields.
   ═══════════════════════════════════════════════════════════════════════ */

const SUGGEST = [
  ["30 × 40 ft, east facing", "We have a 30x40 ft east-facing plot. Need a G+1 house with 3 bedrooms, a pooja room and car parking."],
  ["A home for my parents", "Single-storey home for my parents, 2 bedrooms with attached baths, no stairs, a sit-out at the front, on a 40x60 north-facing plot."],
  ["Courtyard house", "40 x 60 site in Bengaluru, road on the west. 4 BHK duplex built around a courtyard, strict Vastu, earthy colours."],
];
const ROAD = { N: "north", NE: "north-east", E: "east", SE: "south-east", S: "south", SW: "south-west", W: "west", NW: "north-west" };
const FLOORS = (n) => (n === 1 ? "Ground only" : `G+${n - 1}`);

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

export function mountHome({ host, api: API, setField, start, openManual }) {
  const state = { brief: {}, busy: false, history: [], ready: false, request: null };
  host.innerHTML = "";

  // The brief so far, as it is understood, with the way to start.
  const strip = el("div", "brief-strip");
  const facts = el("div", "brief-strip__facts");
  const actions = el("div", "brief-strip__act");
  const sheet = el("button", "link-btn", "Fill in a form"); sheet.type = "button";
  sheet.addEventListener("click", () => openManual("brief"));
  const upload = el("button", "link-btn", "Review my plan"); upload.type = "button";
  upload.addEventListener("click", () => openManual("upload"));
  const go = el("button", "btn btn--cream btn--start", "Start designing"); go.type = "button"; go.disabled = true;
  go.addEventListener("click", () => state.ready && start(state.request, state.brief));
  actions.append(upload, sheet, go);
  strip.append(facts, actions);

  const log = el("div", "chat__log"); log.setAttribute("role", "log"); log.setAttribute("aria-live", "polite");
  const empty = el("div", "chat__empty");
  empty.append(el("h2", "chat__hello", "What are we building?"),
    el("p", "chat__lede", "Tell me about the plot and the home you have in mind - in any language, as much or as little as you like. I'll ask about whatever matters and leave the rest to sensible defaults."));
  const cards = el("div", "suggest");
  for (const [title, text] of SUGGEST) {
    const c = el("button", "suggest__card"); c.type = "button";
    c.append(el("b", null, title), el("span", null, text));
    c.addEventListener("click", () => send(text));
    cards.append(c);
  }
  empty.append(cards);
  log.append(empty);

  const form = el("form", "composer");
  const input = el("textarea", "composer__in"); input.rows = 1; input.maxLength = 4000;
  input.placeholder = "Message Atri…";
  input.setAttribute("aria-label", "Message Atri");
  const sendBtn = el("button", "composer__send"); sendBtn.type = "submit"; sendBtn.disabled = true;
  sendBtn.setAttribute("aria-label", "Send");
  sendBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  form.append(input, sendBtn);
  const hint = el("p", "composer__hint", "Enter to send · Shift + Enter for a new line");
  host.append(strip, log, form, hint);

  const scroll = () => { log.scrollTop = log.scrollHeight; };

  const renderFacts = () => {
    const b = state.brief;
    const bits = [];
    if (b.plot_width) bits.push(b.plot_unit === "ft"
      ? `${Math.round(b.plot_width / 0.3048)} × ${Math.round(b.plot_depth / 0.3048)} ft`
      : `${(+b.plot_width).toFixed(1)} × ${(+b.plot_depth).toFixed(1)} m`);
    if (b.road_direction) bits.push(`Road ${ROAD[b.road_direction] || b.road_direction}`);
    if (b.levels) bits.push(FLOORS(b.levels));
    if (b.bedrooms) bits.push(`${b.bedrooms} bed`);
    for (const a of b.amenities || []) bits.push(a.replace(/^\w/, (c) => c.toUpperCase()));
    for (const r of b.rooms || []) {
      if (r.level == null && !r.attach_to) continue;
      const name = r.type.replace(/_/g, " ");
      bits.push(`${name[0].toUpperCase()}${name.slice(1)}${r.level != null ? ` · ${r.level ? `L${r.level}` : "ground"}` : ""}`);
    }
    if (b.vastu && b.vastu !== "balanced") bits.push(`Vastu ${b.vastu}`);
    facts.replaceChildren(...(bits.length ? bits.map((t) => el("span", "fact", t)) : [el("span", "fact fact--empty", "Your brief will appear here as we talk")]));
    strip.classList.toggle("is-ready", state.ready);
    go.disabled = !state.ready;
  };
  renderFacts();

  const bubble = (who, text) => {
    empty.remove();
    const m = el("div", `msg msg--${who}`);
    if (who === "atri") m.append(el("span", "msg__av"));
    const body = el("div", "msg__body");
    body.textContent = text;
    m.append(body);
    log.append(m);
    scroll();
    return m;
  };

  // What the agent understood also goes into the sheet, so the drawing
  // beside the chat follows the conversation.
  const apply = (b) => {
    if (b.plot_width) setField("plot_width", (+b.plot_width).toFixed(1));
    if (b.plot_depth) setField("plot_depth", (+b.plot_depth).toFixed(1));
    if (b.road_direction) setField("road_direction", b.road_direction);
    if (b.levels) setField("levels", String(Math.min(4, b.levels)));
    if (b.bedrooms) setField("bedrooms", String(b.bedrooms));
    if (b.bathrooms || b.bedrooms) setField("bathrooms", String(b.bathrooms || b.bedrooms));
    if (b.vastu) setField("vastu", b.vastu);
    if (b.budget) setField("budget", String(Math.round(b.budget)));
    if (b.locality) setField("locality", b.locality);
    for (const a of b.amenities || []) setField(`amenity_${a.split(" ")[0]}`, true);
  };

  async function send(text, shown = text) {
    text = text.trim();
    if (state.busy || !text) return;
    state.busy = true; sendBtn.disabled = true;
    log.querySelectorAll(".quick").forEach((q) => q.remove());
    bubble("you", shown);
    const typing = el("div", "msg msg--atri msg--typing");
    typing.append(el("span", "msg__av"));
    const dots = el("div", "typing"); dots.innerHTML = "<i></i><i></i><i></i>";
    typing.append(dots); log.append(typing); scroll();
    try {
      const r = await fetch(`${API}/design/chat`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, brief: state.brief, history: state.history }) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      typing.remove();
      state.brief = d.brief; state.ready = !!d.ready; state.request = d.request;
      state.history.push({ role: "user", text }, { role: "assistant", text: d.reply });
      apply(d.brief);
      renderFacts();
      const m = bubble("atri", d.reply);
      const opts = (d.questions || []).flatMap((q) => (q.options || []).slice(0, 5));
      if (opts.length) {
        const row = el("div", "quick");
        for (const o of opts) {
          const c = el("button", "quick__opt", o); c.type = "button";
          c.addEventListener("click", () => send(o));
          row.append(c);
        }
        m.append(row);
      }
      if (d.ready) {
        go.classList.remove("is-pulse"); void go.offsetWidth; go.classList.add("is-pulse");
      }
      // "Yes, start": the client confirmed, so the studio starts on its own.
      if (d.ready && d.start && d.request) setTimeout(() => start(d.request, d.brief), 900);
      scroll();
    } catch (err) {
      typing.remove();
      bubble("atri", `I couldn't reach the studio just now (${err.message}). Try again in a moment, or use the form.`);
    } finally {
      state.busy = false; sendBtn.disabled = !input.value.trim(); input.focus();
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const v = input.value; input.value = ""; input.style.height = ""; sendBtn.disabled = true;
    send(v);
  });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
  input.addEventListener("input", () => {
    input.style.height = "auto"; input.style.height = `${Math.min(180, input.scrollHeight)}px`;
    sendBtn.disabled = state.busy || !input.value.trim();
  });
  return { focus: () => input.focus() };
}
