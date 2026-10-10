/* ═══════════════════════════════════════════════════════════════════════
   Home: describe the house in your own words.

   The first page is a conversation. The client writes what they want the
   way they would say it to an architect; the brief agent reads it, says back
   what it understood, and asks only for what is still missing - plot, road
   side, floors, bedrooms - with one-tap answers. Everything it reads lands in
   the specification sheet at once, so the plot drawing beside the chat
   redraws as they talk. The sheet itself is still there, one click away, for
   anyone who prefers to fill in fields.
   ═══════════════════════════════════════════════════════════════════════ */

const EXAMPLES = [
  "A 30 × 40 ft north-facing plot, 3 bedrooms on G+1, a pooja room and parking",
  "40 × 60 east-facing site in Bengaluru, 4 BHK duplex, courtyard in the middle, strict Vastu",
  "Small 9 × 15 m plot, 2 bedrooms, a balcony off the master bedroom upstairs, earthy colours",
  "Single-storey home for my parents, 2 bedrooms, no stairs, a sit-out at the front",
];
const ANSWER = {   // what a one-tap answer means, written out for the parser
  road_direction: (o) => `road on the ${o.toLowerCase()}`,
  bedrooms: (o) => `${o} bedrooms`,
  levels: (o) => (/ground/i.test(o) ? "single storey" : o),
  plot: (o) => `plot ${o}`,
};

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

export function mountHome({ host, api: API, setField, start, openManual }) {
  const state = { brief: {}, busy: false };
  host.innerHTML = "";
  const head = el("div", "chat__head");
  head.append(el("span", "chat__k", "Design brief"));
  const manual = el("button", "chat__manual", "Fill in the sheet instead"); manual.type = "button";
  manual.addEventListener("click", () => openManual("brief"));
  const upload = el("button", "chat__manual", "I already have a plan"); upload.type = "button";
  upload.addEventListener("click", () => openManual("upload"));
  head.append(upload, manual);

  const log = el("div", "chat__log"); log.setAttribute("aria-live", "polite"); log.setAttribute("role", "log");
  const form = el("form", "chat__form");
  const input = el("textarea", "chat__in"); input.rows = 1; input.maxLength = 4000;
  input.placeholder = "Describe the home you want - plot, road side, floors, rooms, anything you'd love…";
  input.setAttribute("aria-label", "Describe the home you want");
  const send = el("button", "chat__send"); send.type = "submit"; send.setAttribute("aria-label", "Send");
  send.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h14M12 5l7 7-7 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  form.append(input, send);
  host.append(head, log, form);

  const say = (who, text, extra) => {
    const m = el("div", `msg msg--${who}`);
    if (who === "studio") m.append(el("span", "msg__who", "Atri"));
    const body = el("p", "msg__body");
    m.append(body);
    log.append(m);
    if (who === "studio" && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
      // Typed out, quickly: the reply arrives the way a person writes it.
      let i = 0;
      const tick = () => { body.textContent = text.slice(0, i += 3); if (i < text.length) setTimeout(tick, 16); else extra?.(m); log.scrollTop = log.scrollHeight; };
      tick();
    } else { body.textContent = text; extra?.(m); }
    log.scrollTop = log.scrollHeight;
    return m;
  };
  const chips = (m, options, onPick) => {
    const row = el("div", "msg__chips");
    for (const o of options) {
      const c = el("button", "chip", o); c.type = "button";
      c.addEventListener("click", () => { row.remove(); onPick(o); });
      row.append(c);
    }
    m.append(row);
    log.scrollTop = log.scrollHeight;
  };
  const thinking = () => {
    const m = el("div", "msg msg--studio msg--thinking");
    m.append(el("span", "msg__who", "Atri"), el("span", "dots"));
    m.querySelector(".dots").innerHTML = "<i></i><i></i><i></i>";
    log.append(m); log.scrollTop = log.scrollHeight;
    return m;
  };

  // What the agent understood goes straight into the sheet, so the drawing
  // beside the chat redraws while the client is still talking.
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
    for (const a of b.amenities || []) setField(`amenity_${a === "pooja" ? "pooja" : a.split(" ")[0]}`, true);
  };

  const turn = async (text, shown = text) => {
    if (state.busy || !text.trim()) return;
    state.busy = true; send.disabled = true;
    say("you", shown);
    const t = thinking();
    try {
      const r = await fetch(`${API}/design/chat`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, brief: state.brief }) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      t.remove();
      state.brief = d.brief;
      apply(d.brief);
      say("studio", d.reply, (m) => {
        for (const q of d.questions || []) {
          chips(m, q.options, (o) => turn(ANSWER[q.key] ? ANSWER[q.key](o) : o, o));
        }
        if (d.ready) {
          const go = el("div", "msg__go");
          const b = el("button", "btn btn--cream", "Convene the studio"); b.type = "button";
          b.addEventListener("click", () => start(d.request, d.brief));
          const adj = el("button", "chip", "Adjust the details"); adj.type = "button";
          adj.addEventListener("click", () => openManual("brief"));
          go.append(b, adj);
          m.append(go);
          log.scrollTop = log.scrollHeight;
        }
      });
    } catch (err) {
      t.remove();
      say("studio", `I couldn't reach the studio just now (${err.message}). You can still fill in the sheet.`);
    } finally {
      state.busy = false; send.disabled = false; input.focus();
    }
  };

  form.addEventListener("submit", (e) => { e.preventDefault(); const v = input.value; input.value = ""; input.style.height = ""; turn(v); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
  input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = `${Math.min(160, input.scrollHeight)}px`; });

  say("studio", "Tell me about the home you want to build - the plot, which side the road is on, how many floors and bedrooms, and anything you'd love: a courtyard, a balcony off the master bedroom, parking, Vastu, the colours you like. I'll ask about anything you leave out.",
    (m) => chips(m, EXAMPLES, (o) => turn(o)));
  return { focus: () => input.focus() };
}
