/* ═══════════════════════════════════════════════════════════════════════
   Edit the drawing - exact changes to a finished plan.

   Pick a room, then widen it, deepen it, swap it with another, rename it,
   use it as something else, or set its ceiling. Each change is made to the
   drawn plan itself (the server slides one wall, or exchanges two rooms) and
   everything not touched stays as drawn. Undo walks back.
   ═══════════════════════════════════════════════════════════════════════ */

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

const USE_AS = [
  ["bedroom", "Bedroom"], ["master_bedroom", "Master bedroom"], ["study", "Study"], ["home_office", "Home office"],
  ["home_theatre", "Media / gaming room"], ["gym", "Gym / yoga"], ["library", "Library"], ["family", "Family lounge"],
  ["dining", "Dining"], ["living", "Living"], ["store", "Store"], ["utility", "Utility"], ["puja", "Puja"],
  ["guest_bedroom", "Guest bedroom"], ["children_bedroom", "Kids' bedroom"], ["laundry", "Laundry"],
];
const STEPS = [0.3, 0.5, 1.0];
const CEILINGS = [2.7, 3.0, 3.3, 3.6, 4.2];

/**
 * Builds the edit panel before `after`.
 * ctx: { api, getPlanId(), onEdited(newPlanId, applied), onUndo(), canUndo(), toast }
 */
export function mountEditor(after, ctx) {
  document.getElementById("edit")?.remove();
  const planId = ctx.getPlanId();
  if (!planId) return;
  const box = el("section", "edit"); box.id = "edit";
  box.setAttribute("aria-label", "Edit the drawing");

  const head = el("div", "edit__head");
  head.append(el("span", "edit__k", "Edit the drawing"));
  const undo = el("button", "ghost-btn edit__undo", "Undo last change"); undo.type = "button";
  undo.hidden = !ctx.canUndo();
  undo.addEventListener("click", () => ctx.onUndo());
  head.append(undo);
  const hint = el("p", "edit__hint", "Pick a room, then change it. Only that room and the wall it shares move; the rest of the plan stays as drawn.");
  const body = el("div", "edit__body");
  const said = el("p", "edit__said"); said.setAttribute("aria-live", "polite");
  said.textContent = ctx.said?.() || "";
  box.append(head, hint, body, said);
  after.before(box);

  body.append(el("p", "edit__loading", "Loading the rooms…"));
  fetch(`${ctx.api}/plans/${planId}/rooms`)
    .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then((d) => build(d.rooms || []))
    .catch((err) => { body.replaceChildren(el("p", "edit__loading", `The rooms could not be listed (${err.message}).`)); });

  function build(rooms) {
    body.replaceChildren();
    const movable = rooms.filter((r) => !r.fixed);
    if (!movable.length) { body.append(el("p", "edit__loading", "There are no rooms to edit.")); return; }
    let sel = movable.find((r) => r.id === ctx.selected?.())?.id || movable[0].id;
    let step = 0.3;
    const label = (r) => `${r.name} · ${r.level === 0 ? "Ground" : `Floor ${r.level}`} · ${r.width.toFixed(1)} × ${r.depth.toFixed(1)} m`;

    const pick = el("select", "edit__sel"); pick.setAttribute("aria-label", "Room to change");
    for (const r of movable) { const o = el("option", null, label(r)); o.value = r.id; pick.append(o); }
    pick.value = sel;
    pick.addEventListener("change", () => { sel = pick.value; ctx.select?.(sel); sync(); });

    const send = async (ops, doing) => {
      said.textContent = doing || "Making that change…";
      box.classList.add("is-busy");
      try {
        const r = await fetch(`${ctx.api}/plans/${planId}/edit`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ops }),
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
        const msg = j.applied.join(" · ") + (j.refused?.length ? `  (not done: ${j.refused.join(" ")})` : "");
        said.textContent = msg;
        ctx.setSaid?.(msg);
        ctx.select?.(sel);
        await ctx.onEdited(j.plan_id, j.applied);
      } catch (err) {
        said.textContent = err.message;
        ctx.setSaid?.(err.message);
      } finally { box.classList.remove("is-busy"); }
    };

    // Size: four buttons, one step size.
    const size = el("div", "edit__row");
    size.append(el("span", "edit__lab", "Size"));
    const mk = (text, ops, title) => {
      const b = el("button", "edit__btn", text); b.type = "button"; b.title = title;
      b.addEventListener("click", () => send([{ op: "resize", room: sel, ...ops() }], `${title}…`));
      return b;
    };
    size.append(
      mk("Wider", () => ({ width: step }), "Make it wider"),
      mk("Narrower", () => ({ width: -step }), "Make it narrower"),
      mk("Deeper", () => ({ depth: step }), "Make it deeper"),
      mk("Shallower", () => ({ depth: -step }), "Make it shallower"),
    );
    const steps = el("span", "edit__steps");
    for (const s of STEPS) {
      const c = el("button", "edit__chip" + (s === step ? " is-on" : ""), `${s} m`); c.type = "button";
      c.addEventListener("click", () => { step = s; steps.querySelectorAll(".edit__chip").forEach((x) => x.classList.toggle("is-on", x === c)); });
      steps.append(c);
    }
    size.append(steps);

    // Swap with another room on the same floor.
    const swap = el("div", "edit__row");
    swap.append(el("span", "edit__lab", "Swap with"));
    const other = el("select", "edit__sel edit__sel--s"); other.setAttribute("aria-label", "Room to swap with");
    const go = el("button", "edit__btn", "Swap"); go.type = "button";
    go.addEventListener("click", () => other.value && send([{ op: "swap", a: sel, b: other.value }], "Swapping those rooms…"));
    swap.append(other, go);

    // Rename / use as.
    const use = el("div", "edit__row");
    use.append(el("span", "edit__lab", "Name"));
    const name = el("input", "edit__in"); name.type = "text"; name.maxLength = 40; name.placeholder = "e.g. Gaming Room";
    name.setAttribute("aria-label", "New name");
    const ren = el("button", "edit__btn", "Rename"); ren.type = "button";
    ren.addEventListener("click", () => name.value.trim() && send([{ op: "rename", room: sel, name: name.value.trim() }], "Renaming…"));
    const as = el("select", "edit__sel edit__sel--s"); as.setAttribute("aria-label", "Use this room as");
    as.append(Object.assign(el("option", null, "Use as…"), { value: "" }));
    for (const [v, t] of USE_AS) as.append(Object.assign(el("option", null, t), { value: v }));
    as.addEventListener("change", () => {
      if (!as.value) return;
      const t = USE_AS.find((u) => u[0] === as.value)[1];
      send([{ op: "retype", room: sel, type: as.value, name: name.value.trim() || t }], `Making it a ${t.toLowerCase()}…`);
      as.value = "";
    });
    use.append(name, ren, as);

    // Ceiling.
    const ceil = el("div", "edit__row");
    ceil.append(el("span", "edit__lab", "Ceiling"));
    for (const h of CEILINGS) {
      const c = el("button", "edit__chip", `${h.toFixed(1)} m`); c.type = "button";
      c.addEventListener("click", () => send([{ op: "ceiling", room: sel, height: h }], `Setting the ceiling to ${h} m…`));
      ceil.append(c);
    }

    body.append(pick, size, swap, use, ceil);

    function sync() {
      const r = rooms.find((x) => x.id === sel);
      other.replaceChildren();
      for (const o of movable.filter((x) => x.level === r.level && x.id !== r.id)) {
        other.append(Object.assign(el("option", null, o.name), { value: o.id }));
      }
      go.disabled = !other.options.length;
      name.value = "";
    }
    sync();
  }
}
