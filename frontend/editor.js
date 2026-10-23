/* ═══════════════════════════════════════════════════════════════════════
   Edit the plan - exact changes to a finished plan, made on the drawing.

   Click a room on the plan (or pick it from the list) and the panel beside
   the drawing shows it as a CAD properties panel would: its name, what it
   is used as, its width and depth with steppers, its ceiling. Swap asks you
   to click the other room. Each change is made to the drawn plan itself
   (the server slides one wall, or exchanges two rooms) and everything not
   touched stays as drawn. Undo walks back.
   ═══════════════════════════════════════════════════════════════════════ */

import { icon } from "./icons.js?v=i1";

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

const USE_AS = [
  ["bedroom", "Bedroom"], ["master_bedroom", "Master bedroom"], ["guest_bedroom", "Guest bedroom"],
  ["children_bedroom", "Kids' bedroom"], ["study", "Study"], ["home_office", "Home office"],
  ["home_theatre", "Media room"], ["gym", "Gym or yoga room"], ["library", "Library"], ["family", "Family lounge"],
  ["living", "Living room"], ["dining", "Dining room"], ["store", "Store"], ["utility", "Utility"],
  ["laundry", "Laundry"], ["puja", "Puja room"],
];
const STEPS = [0.3, 0.5, 1.0];
const CEILINGS = [2.7, 3.0, 3.3, 3.6, 4.2];
const floorName = (i) => (i === 0 ? "Ground floor" : `Floor ${i}`);
const m = (v) => `${(+v).toFixed(v < 10 ? 2 : 1).replace(/0$/, "")} m`;

let plateHandler = null;      // one click handler on the plan, replaced on each mount

/**
 * Builds the edit panel before `after`.
 * ctx: { api, getPlanId(), onEdited(newPlanId, applied), onUndo(), canUndo(), selected(), select(id),
 *        said(), setSaid(t), plate(), sheetLevel(), showLevel(i), setSync(fn) }
 */
export function mountEditor(after, ctx) {
  document.getElementById("edit")?.remove();
  const planId = ctx.getPlanId();
  if (!planId) return;
  const box = el("section", "ed"); box.id = "edit";
  box.setAttribute("aria-label", "Edit the plan");

  const top = el("div", "ed__top");
  top.append(el("h3", "ed__title", "Edit the plan"));
  const undo = el("button", "ed__undo", "Undo"); undo.type = "button";
  undo.hidden = !ctx.canUndo();
  undo.title = "Undo the last change";
  undo.addEventListener("click", () => ctx.onUndo());
  top.append(undo);
  const body = el("div", "ed__body");
  const said = el("p", "ed__said"); said.setAttribute("aria-live", "polite");
  said.textContent = ctx.said?.() || "";
  box.append(top, body, said);
  after.before(box);

  body.append(el("p", "ed__note", "Loading the rooms…"));
  fetch(`${ctx.api}/plans/${planId}/rooms`)
    .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then((d) => build(d.rooms || []))
    .catch((err) => { body.replaceChildren(el("p", "ed__note", `The rooms could not be listed (${err.message}).`)); });

  function build(rooms) {
    const movable = rooms.filter((r) => !r.fixed);
    if (!movable.length) { body.replaceChildren(el("p", "ed__note", "There are no rooms to edit.")); return; }
    let sel = movable.find((r) => r.id === ctx.selected?.())?.id || null;
    let step = 0.3;
    let swapping = false;

    const send = async (ops, doing) => {
      said.textContent = doing || "Making that change…";
      box.classList.add("is-busy");
      try {
        const r = await fetch(`${ctx.api}/plans/${planId}/edit`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ops }),
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
        const msg = `${j.applied.join(". ")}.` + (j.refused?.length ? ` Not done: ${j.refused.join(" ")}` : "");
        said.textContent = msg;
        ctx.setSaid?.(msg);
        ctx.select?.(sel);
        await ctx.onEdited(j.plan_id, j.applied);
      } catch (err) {
        said.textContent = err.message;
        ctx.setSaid?.(err.message);
        box.classList.remove("is-busy");
      }
    };

    // The plan: rooms light up under the pointer, and a click picks one (or,
    // while swapping, the room to swap with).
    const plate = ctx.plate?.();
    const mark = () => {
      const svg = plate?.querySelector("svg");
      if (!svg) return;
      svg.classList.add("is-editing");
      svg.querySelectorAll("polygon[data-room]").forEach((p) => {
        const r = rooms.find((x) => x.id === p.dataset.room);
        p.classList.toggle("is-sel", p.dataset.room === sel);
        p.classList.toggle("is-fixed", !!r?.fixed);
        p.classList.toggle("is-target", swapping && !!r && !r.fixed && r.id !== sel && r.level === rooms.find((x) => x.id === sel)?.level);
      });
      svg.classList.toggle("is-swapping", swapping);
    };
    ctx.setSync?.(mark);
    if (plate) {
      if (plateHandler) plate.removeEventListener("click", plateHandler);
      let down = null;
      plate.onpointerdown = (e) => { down = [e.clientX, e.clientY]; };
      plateHandler = (e) => {
        if (!box.isConnected || box.closest("[hidden]")) return;
        if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;   // a pan, not a click
        const id = e.target.closest?.("polygon[data-room]")?.dataset.room;
        const r = rooms.find((x) => x.id === id);
        if (!r || r.fixed) return;
        if (swapping) {
          const a = rooms.find((x) => x.id === sel);
          if (r.id === sel || r.level !== a.level) { said.textContent = "Pick another room on the same floor."; return; }
          swapping = false;
          send([{ op: "swap", a: sel, b: r.id }], `Swapping the ${a.name.toLowerCase()} and the ${r.name.toLowerCase()}…`);
          return;
        }
        choose(r.id);
      };
      plate.addEventListener("click", plateHandler);
    }

    function choose(id, focus = false) {
      sel = id; swapping = false;
      ctx.select?.(id);
      const r = rooms.find((x) => x.id === id);
      if (r && ctx.sheetLevel?.() !== r.level) ctx.showLevel?.(r.level);
      draw();
      mark();
      if (focus) box.querySelector(".ed__name")?.focus();
    }

    function draw() {
      body.replaceChildren();
      const r = rooms.find((x) => x.id === sel);
      if (!r) {
        body.append(el("p", "ed__lead", "Click a room on the plan to change it."));
      } else {
        // The room: its name (edit it in place), where it is, how big.
        const head = el("div", "ed__room");
        const name = el("input", "ed__name"); name.type = "text"; name.maxLength = 40; name.value = r.name;
        name.setAttribute("aria-label", "Room name, press Enter to rename");
        const rename = () => {
          const v = name.value.trim();
          if (v && v !== r.name) send([{ op: "rename", room: sel, name: v }], `Renaming it ${v}…`);
          else name.value = r.name;
        };
        name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); rename(); } if (e.key === "Escape") { name.value = r.name; name.blur(); } });
        name.addEventListener("change", rename);
        head.append(name, el("p", "ed__meta", `${floorName(r.level)}, ${(+r.area).toFixed(1)} m²`));
        body.append(head);

        // What it is used as.
        const use = el("label", "ed__field");
        use.append(el("span", "ed__lab", "Used as"));
        const as = el("select", "ed__select");
        const known = USE_AS.some(([v]) => v === r.type);
        if (!known) as.append(Object.assign(el("option", null, r.name), { value: r.type }));
        for (const [v, t] of USE_AS) as.append(Object.assign(el("option", null, t), { value: v }));
        as.value = r.type;
        as.addEventListener("change", () => {
          const t = USE_AS.find((u) => u[0] === as.value)?.[1] || as.value;
          send([{ op: "retype", room: sel, type: as.value, name: t }], `Making it a ${t.toLowerCase()}…`);
        });
        use.append(as);
        body.append(use);

        // Size: width and depth, each with its own stepper, in the step chosen.
        const size = el("div", "ed__size");
        const stepper = (label, value, key, more, less) => {
          const row = el("div", "ed__dim");
          row.append(el("span", "ed__lab", label));
          const minus = el("button", "ed__step"); minus.type = "button"; minus.setAttribute("aria-label", `${less} by ${step} m`); minus.append(icon("minus"));
          const plus = el("button", "ed__step"); plus.type = "button"; plus.setAttribute("aria-label", `${more} by ${step} m`); plus.append(icon("plus"));
          minus.addEventListener("click", () => send([{ op: "resize", room: sel, [key]: -step }], `${less} by ${step} m…`));
          plus.addEventListener("click", () => send([{ op: "resize", room: sel, [key]: step }], `${more} by ${step} m…`));
          row.append(minus, el("output", "ed__val", m(value)), plus);
          return row;
        };
        size.append(stepper("Width", r.width, "width", "Wider", "Narrower"), stepper("Depth", r.depth, "depth", "Deeper", "Shallower"));
        const steps = el("div", "ed__seg ed__seg--small"); steps.setAttribute("role", "radiogroup"); steps.setAttribute("aria-label", "Step size");
        for (const s of STEPS) {
          const c = el("button", null, `${s} m`); c.type = "button"; c.setAttribute("role", "radio");
          c.setAttribute("aria-checked", String(s === step));
          c.addEventListener("click", () => { step = s; draw(); box.querySelector(`.ed__seg--small [aria-checked="true"]`)?.focus(); });
          steps.append(c);
        }
        const by = el("div", "ed__by");
        by.append(el("span", "ed__hint", "Each step moves one wall by"), steps);
        size.append(by);
        body.append(el("h4", "ed__sub", "Size"), size);

        // Ceiling.
        const ceil = el("div", "ed__seg"); ceil.setAttribute("role", "radiogroup"); ceil.setAttribute("aria-label", "Ceiling height");
        for (const h of CEILINGS) {
          const c = el("button", null, `${h.toFixed(1)}`); c.type = "button"; c.setAttribute("role", "radio");
          c.setAttribute("aria-checked", String(Math.abs(h - r.ceiling) < 0.01));
          c.title = `${h.toFixed(1)} m ceiling`;
          c.addEventListener("click", () => Math.abs(h - r.ceiling) > 0.01 && send([{ op: "ceiling", room: sel, height: h }], `Setting the ceiling to ${h} m…`));
          ceil.append(c);
        }
        const ch = el("h4", "ed__sub", "Ceiling height");
        ch.append(el("span", "ed__unit", " in metres"));
        body.append(ch, ceil);

        // Swap: click the other room on the plan, or pick it here.
        const peers = movable.filter((x) => x.level === r.level && x.id !== r.id);
        const sw = el("div", "ed__swap");
        if (!swapping) {
          const b = el("button", "ed__btn", "Swap with another room"); b.type = "button";
          b.disabled = !peers.length;
          b.addEventListener("click", () => { swapping = true; draw(); mark(); box.querySelector(".ed__swaplist button")?.focus(); });
          sw.append(b);
        } else {
          sw.classList.add("is-on");
          sw.append(el("p", "ed__lead", `Click the room to swap the ${r.name.toLowerCase()} with, or pick it:`));
          const list = el("div", "ed__swaplist");
          for (const o of peers) {
            const b = el("button", null, o.name); b.type = "button";
            b.addEventListener("click", () => { swapping = false; send([{ op: "swap", a: sel, b: o.id }], `Swapping the ${r.name.toLowerCase()} and the ${o.name.toLowerCase()}…`); });
            list.append(b);
          }
          const cancel = el("button", "ed__link", "Cancel"); cancel.type = "button";
          cancel.addEventListener("click", () => { swapping = false; draw(); mark(); });
          sw.append(list, cancel);
        }
        body.append(sw);
      }

      // Every room, floor by floor: the way to pick one without the plan.
      const all = el("details", "ed__all");
      all.open = !r;
      all.append(el("summary", null, r ? "All rooms" : "Or pick a room"));
      for (const lv of [...new Set(movable.map((x) => x.level))].sort()) {
        all.append(el("p", "ed__floor", floorName(lv)));
        const list = el("div", "ed__rooms");
        for (const x of movable.filter((y) => y.level === lv)) {
          const b = el("button", null, x.name); b.type = "button";
          b.setAttribute("aria-pressed", String(x.id === sel));
          b.addEventListener("click", () => choose(x.id, true));
          list.append(b);
        }
        all.append(list);
      }
      body.append(all);
    }

    draw();
    mark();
  }
}
