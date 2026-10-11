/* ═══════════════════════════════════════════════════════════════════════
   The four steps under the hero, each showing the real thing small:
   a brief being typed, three schemes the studio actually drew, the
   specialists arguing over one, and a design being changed after the fact.
   ═══════════════════════════════════════════════════════════════════════ */

const NS = "http://www.w3.org/2000/svg";
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const svg = (tag, attrs = {}, parent) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.append(n);
  return n;
};
const visible = (node) => node.isConnected && node.getBoundingClientRect().top < innerHeight + 200;

/* 01 ── say it your way: prompts typed, read, rubbed out, the next one typed */
const PROMPTS = [
  "30x40 east-facing plot, G+1, 3 bedrooms and a pooja room",
  "2BHK on a 9 m wide plot, car parking in front",
  "Ground floor bedroom for my parents, Vastu please",
  "40x60 north road, 4 bedrooms, a home office and a big kitchen",
  "मुझे 3 बेडरूम का घर चाहिए, दो मंज़िल",
  "A courtyard house, single storey, lots of light",
];

async function typing(host) {
  host.classList.add("viz--chat");
  host.innerHTML = '<span class="vc__clip">⌁</span><span class="vc__text"></span><span class="vc__caret"></span><span class="vc__send">↑</span>';
  const text = host.querySelector(".vc__text");
  if (reduced()) { text.textContent = PROMPTS[0]; return; }
  for (let i = 0; ; i = (i + 1) % PROMPTS.length) {
    while (!visible(host)) await wait(800);
    const p = PROMPTS[i];
    for (let k = 1; k <= p.length; k++) { text.textContent = p.slice(0, k); await wait(34 + Math.random() * 40); }
    host.classList.add("is-sent"); await wait(1500); host.classList.remove("is-sent");
    for (let k = p.length; k >= 0; k--) { text.textContent = p.slice(0, k); await wait(14); }
    await wait(350);
  }
}

/* 02 ── three schemes, drawn live: the studio's own plans, wall by wall */
const TINT = { living: "#3a3428", dining: "#3b3226", kitchen: "#3d2f24", master_bedroom: "#28303b", bedroom: "#2a313a",
  bathroom: "#25333a", toilet: "#25333a", staircase: "#2f2f2f", garage: "#2b2b2b", puja: "#3b2a2f", corridor: "#262626",
  lobby: "#262626", foyer: "#2a2a2a", utility: "#2b3326", verandah: "#2c3127" };

async function schemes(host) {
  host.classList.add("viz--schemes");
  let data;
  try { data = await (await fetch("demo/schemes.json")).json(); } catch { return; }
  const s = svg("svg", { viewBox: "0 0 300 120", preserveAspectRatio: "xMidYMid meet" }, host);
  const plans = data.slice(0, 3).map((sc, i) => {
    const g = svg("g", {}, s);
    const k = Math.min(84 / sc.w, 96 / sc.d);
    const ox = 12 + i * 98 + (84 - sc.w * k) / 2, oy = 12 + (96 - sc.d * k) / 2;
    const rects = sc.rooms.map(([t, x, y, w, d]) => {
      const r = svg("rect", { x: ox + x * k, y: oy + y * k, width: w * k, height: d * k, fill: TINT[t] || "#2a2a2a",
        stroke: "var(--cream-2)", "stroke-width": 0.9, "fill-opacity": 0, "stroke-dasharray": 2 * (w + d) * k, "stroke-dashoffset": 2 * (w + d) * k }, g);
      return r;
    });
    return rects;
  });
  if (reduced()) { plans.flat().forEach((r) => { r.setAttribute("stroke-dashoffset", 0); r.setAttribute("fill-opacity", 1); }); return; }
  for (;;) {
    while (!visible(host)) await wait(800);
    for (const rects of plans) {
      for (const r of rects) {
        r.style.transition = "stroke-dashoffset .5s linear, fill-opacity .6s .3s";
        r.setAttribute("stroke-dashoffset", 0); r.setAttribute("fill-opacity", 1);
        await wait(170);
      }
    }
    await wait(3200);
    plans.flat().forEach((r) => { r.style.transition = "none"; r.setAttribute("stroke-dashoffset", r.getAttribute("stroke-dasharray")); r.setAttribute("fill-opacity", 0); });
    await wait(400);
  }
}

/* 03 ── thirteen specialists argue: the team, faces and all, over a plan */
const DEBATE = [
  [0, "Kitchen belongs in the south-east."],
  [1, "Span's 4.2 m - the beam takes it."],
  [2, "West bedroom needs a chajja."],
  [0, "Puja in the north-east corner, then."],
  [2, "Cross breeze through the living room."],
  [1, "Stair stacks on every floor. Good."],
  [0, "Agreed - Scheme B."],
];

function figure(s, x, hat, skin, extra) {
  const g = svg("g", { transform: `translate(${x} 4) scale(1.3)`, class: "vt__fig" }, s);
  svg("rect", { x: -11, y: 74, width: 22, height: 26, rx: 6, fill: extra.shirt }, g);       // body
  svg("rect", { x: -13, y: 96, width: 26, height: 6, rx: 2, fill: "#2a2a2a" }, g);          // legs
  const head = svg("g", { class: "vt__head" }, g);
  svg("circle", { cx: 0, cy: 58, r: 16, fill: skin }, head);
  svg("path", { d: "M-17 54 A17 17 0 0 1 17 54 L19 56 L-19 56 Z", fill: hat }, head);       // hard hat
  svg("rect", { x: -4, y: 39, width: 8, height: 4, rx: 2, fill: hat }, head);
  svg("circle", { cx: -5.5, cy: 60, r: 2, fill: "#1d1a17" }, head);                          // eyes
  svg("circle", { cx: 5.5, cy: 60, r: 2, fill: "#1d1a17" }, head);
  if (extra.glasses) {
    svg("circle", { cx: -5.5, cy: 60, r: 4.2, fill: "none", stroke: "#1d1a17", "stroke-width": 1.1 }, head);
    svg("circle", { cx: 5.5, cy: 60, r: 4.2, fill: "none", stroke: "#1d1a17", "stroke-width": 1.1 }, head);
  }
  if (extra.beard) svg("path", { d: "M-10 64 Q0 76 10 64 Q0 70 -10 64Z", fill: "#3b2a20" }, head);
  svg("path", { d: "M-4 66 Q0 69.5 4 66", stroke: "#7a3a2e", "stroke-width": 1.4, fill: "none", class: "vt__mouth" }, head);
  svg("ellipse", { cx: -9, cy: 64, rx: 2.4, ry: 1.4, fill: "#e98b78", opacity: 0.45 }, head);  // cheeks
  svg("ellipse", { cx: 9, cy: 64, rx: 2.4, ry: 1.4, fill: "#e98b78", opacity: 0.45 }, head);
  return g;
}

async function talk(host) {
  host.classList.add("viz--team");
  const s = svg("svg", { viewBox: "0 0 300 140", preserveAspectRatio: "xMidYMax meet" }, host);
  svg("rect", { x: 112, y: 118, width: 76, height: 14, rx: 2, fill: "rgba(239,233,222,.08)", stroke: "rgba(239,233,222,.35)" }, s);   // the plan on the table
  const team = [
    figure(s, 52, "#f2c230", "#e8b48a", { shirt: "#5d86b8", glasses: true }),
    figure(s, 150, "#ef7a2a", "#8d5a3c", { shirt: "#c9d46a", beard: true }),
    figure(s, 248, "#f1efe9", "#c58a63", { shirt: "#6b5a4a" }),
  ];
  const bubble = document.createElement("span");
  bubble.className = "vt__say";
  host.append(bubble);
  if (reduced()) { bubble.textContent = DEBATE[0][1]; return; }
  for (let i = 0; ; i = (i + 1) % DEBATE.length) {
    while (!visible(host)) await wait(800);
    const [who, line] = DEBATE[i];
    team.forEach((f, k) => f.classList.toggle("is-talking", k === who));
    bubble.textContent = line;
    bubble.style.left = `${[20, 50, 80][who]}%`;
    bubble.classList.add("is-on");
    await wait(2300);
    bubble.classList.remove("is-on");
    await wait(300);
  }
}

/* 04 ── explore, then change it: a finished plan, a change asked for, redrawn */
const CHANGES = [
  ["Bigger kitchen", (r) => { r.kitchen.x -= 14; r.kitchen.w += 14; r.dining.w -= 14; }],
  ["Add a study", (r) => { r.study = { x: 6, y: 66, w: 40, h: 36, t: "Study" }; r.bed2.w -= 40; r.bed2.x += 40; }],
  ["Jharokha facade", (r) => { r.facade = true; }],
  ["Kitchen to the south-east", (r) => { [r.kitchen.x, r.bed2.x] = [r.bed2.x, r.kitchen.x]; }],
];

async function change(host) {
  host.classList.add("viz--change");
  const s = svg("svg", { viewBox: "0 0 300 120", preserveAspectRatio: "xMidYMid meet" }, host);
  const chip = document.createElement("span");
  chip.className = "vch__chip";
  host.append(chip);
  const base = () => ({
    living: { x: 6, y: 8, w: 70, h: 52, t: "Living" }, dining: { x: 76, y: 8, w: 52, h: 52, t: "Dining" },
    kitchen: { x: 128, y: 8, w: 40, h: 52, t: "Kitchen" }, bed1: { x: 6, y: 66, w: 80, h: 46, t: "Bed" },
    bed2: { x: 86, y: 66, w: 82, h: 46, t: "Bed" },
  });
  const g = svg("g", { transform: "translate(66 0)" }, s);
  const shapes = {};
  const draw = (r) => {
    for (const [k, v] of Object.entries(r)) {
      if (k === "facade") continue;
      let n = shapes[k];
      if (!n) {
        n = shapes[k] = { rect: svg("rect", { fill: "rgba(239,233,222,.06)", stroke: "var(--cream-2)", "stroke-width": 1 }, g),
          text: svg("text", { "font-size": 8, fill: "var(--cream-3)", "text-anchor": "middle" }, g) };
      }
      for (const [a, b] of [["x", v.x], ["y", v.y], ["width", v.w], ["height", v.h]]) n.rect.setAttribute(a, b);
      n.text.setAttribute("x", v.x + v.w / 2); n.text.setAttribute("y", v.y + v.h / 2 + 3); n.text.textContent = v.t;
      n.rect.style.transition = "all .7s cubic-bezier(.2,.8,.2,1)";
    }
    for (const k of Object.keys(shapes)) if (!r[k] && k !== "bay") { shapes[k].rect.remove(); shapes[k].text.remove(); delete shapes[k]; }
    g.classList.toggle("has-facade", !!r.facade);
    if (r.facade && !shapes.bay) {
      // Two jharokha bays on the street face.
      shapes.bay = { rect: svg("path", { d: "M18 8 v-6 q12 -9 24 0 v6 M104 8 v-6 q12 -9 24 0 v6", fill: "none", stroke: "var(--ochre, #c9a46a)", "stroke-width": 1.4 }, g),
        text: svg("text", {}, g) };
    }
    if (!r.facade && shapes.bay) { shapes.bay.rect.remove(); shapes.bay.text.remove(); delete shapes.bay; }
  };
  draw(base());
  if (reduced()) return;
  for (let i = 0; ; i = (i + 1) % CHANGES.length) {
    while (!visible(host)) await wait(800);
    await wait(1400);
    const [label, fn] = CHANGES[i];
    chip.textContent = label;
    chip.classList.add("is-on");
    await wait(900);
    const r = base(); fn(r); draw(r);
    await wait(2600);
    chip.classList.remove("is-on");
    draw(base());
  }
}

export function mountSteps(root = document) {
  const cards = root.querySelectorAll(".step-card .viz");
  const make = [typing, schemes, talk, change];
  cards.forEach((v, i) => { v.innerHTML = ""; v.className = "viz"; make[i]?.(v); });
}
