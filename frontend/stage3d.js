/* ═══════════════════════════════════════════════════════════════════════
   Stage3D: the drafting table as a small 3D model.

   A team of three works the plot for the whole run: the site engineer
   stakes the corners with a survey staff, one architect marks the
   setbacks, the other sketches the zoning, and they keep laying out the
   column grid until the engine returns its schemes. Then they draw the
   real plan room by room, the walls rise, and the camera settles to plan
   view for the hand-off into the review.

   While the committee reviews, its specialists walk on with their papers,
   read the drawing, take notes, say what they found to whoever on the team
   is free, hand the sheet over and leave. A drone camera follows the work:
   in close on the floor being drawn, out again when the board is still.
   Every line drawn after the planning sketch is the engine's own geometry,
   and every remark is the engine's own words.
   ═══════════════════════════════════════════════════════════════════════ */

import * as THREE from "three";

const TAU = Math.PI * 2;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const damp = (dt, rate) => 1 - Math.exp(-dt * rate);
const angDiff = (a, b) => Math.atan2(Math.sin(a - b), Math.cos(a - b));
const pick = (xs) => xs[Math.floor(Math.random() * xs.length)];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const GAP = 3.6;          // metres between floor plates
const WALL_H = 1.05;      // cut-away height: a model, not a building
const H = 1.9;            // figure height: collectible proportions that read at plan scale
const WALK = 1.6;         // m/s
const RUN = 3.6;          // m/s, for long crossings
const PACE = 2.2;         // m/s while drawing
const ACCEL = 4.5;        // m/s²

const COL = {
  ground: 0x0b0a09, plot: 0x1c1b19, slab: 0x141312, line: 0xede6dc, chalk: 0x8a847b,
  gold: 0xc9b497, indigo: 0xa39c92, wall: 0xefe9df, glass: 0x9fb2bf,
  public: 0xc9b497, service: 0xa39c92, wet: 0x8f9aa1, private: 0xe8dcc6,
};

const PUBLIC = new Set(["foyer", "living", "dining", "puja", "verandah", "garage", "drawing", "family", "lobby", "home_office"]);
const PRIVATE = new Set(["master_bedroom", "bedroom", "guest_bedroom", "children_bedroom", "study", "balcony", "terrace", "wardrobe", "servant"]);
const WET = new Set(["bathroom", "toilet", "powder", "utility", "laundry"]);
const zoneOf = (t) => (PUBLIC.has(t) ? "public" : PRIVATE.has(t) ? "private" : "service");
const tintOf = (t) => (PUBLIC.has(t) ? "public" : PRIVATE.has(t) ? "private" : WET.has(t) ? "wet" : "service");

export function webglAvailable() {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch { return false; }
}

/* ── geometry helpers ─────────────────────────────────────────────────── */

// Points along a polyline every `step` metres, so a line can be revealed
// at the pace someone walks it.
function resample(pts, step = 0.08, closed = false) {
  const src = closed ? [...pts, pts[0]] : pts;
  const out = [src[0].clone()];
  for (let i = 1; i < src.length; i++) {
    const a = src[i - 1], b = src[i];
    const n = Math.max(1, Math.ceil(a.distanceTo(b) / step));
    for (let k = 1; k <= n; k++) out.push(a.clone().lerp(b, k / n));
  }
  return out;
}

function lineOf(points, color, opacity = 1, y = 0.02) {
  const pos = new Float32Array(points.length * 3);
  points.forEach((p, i) => { pos[i * 3] = p.x; pos[i * 3 + 1] = y; pos[i * 3 + 2] = p.z; });
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setDrawRange(0, 0);
  const m = new THREE.LineBasicMaterial({ color, transparent: true, opacity });
  const line = new THREE.Line(g, m);
  line.userData.count = points.length;
  return line;
}

function plane(w, d, color, opacity) {
  const m = new THREE.MeshStandardMaterial({ color, transparent: true, opacity, roughness: 1, metalness: 0, depthWrite: false });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, d), m);
  mesh.rotation.x = -Math.PI / 2;
  return mesh;
}

function shapeFill(pts, color, opacity) {
  const s = new THREE.Shape(pts.map((p) => new THREE.Vector2(p.x, -p.z)));
  const g = new THREE.ShapeGeometry(s);
  const m = new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false });
  const mesh = new THREE.Mesh(g, m);
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = 0.012;
  return mesh;
}

/* ── the people ───────────────────────────────────────────────────────── */

// Collectible-figure proportions: a big friendly head with a face, a
// chunky body, short legs. Built at a height of 1 and scaled to H.
//   Lead architect: yellow hard hat, glasses, chambray shirt with the
//     sleeves rolled, jeans, a roll of plans in hand.
//   Architect: white hard hat, long hair, black blazer over a cream
//     blouse, ruler and pencil.
//   Site engineer: orange hard hat, high-visibility vest, survey staff.
//   Specialists: their discipline's colour, no hard hat, a clipboard.
const LOOKS = {
  arch1: {
    hat: 0xf2c230, hair: 0x1b1511, glasses: true, skin: 0xe8b894,
    shirt: 0x6f93c4, collar: 0x8eabd3, placket: true, pocket: true, rolled: true,
    legs: 0x2c3f5c, shoes: 0x5a3a24, carry: "tube", tool: "pencil",
  },
  arch2: {
    hat: 0xf1eee6, hair: 0x4a2c1c, hairStyle: "long", lashes: true, skin: 0xf0c6a4,
    top: 0x1d1f24, shirt: 0xf1e9dc, buttons: true,
    legs: 0x2a2e2a, shoes: 0x7a4a2a, carry: "ruler", tool: "pencil",
  },
  eng: {
    hat: 0xf08a24, hair: 0x2b2118, skin: 0xc68e62,
    shirt: 0x6b7280, vest: 0xc9e83a,
    legs: 0x4a5160, shoes: 0x3a2a1c, tool: "staff",
  },
};
const PIGMENT = { indigo: 0x4f6fa3, hingula: 0xb24a36, ochre: 0xa8733a, orpiment: 0xc29a2e, gold: 0xc48a3e, chalk: 0x7d8494 };
const SKINS = [0xf0c6a4, 0xe8b894, 0xd29a6e, 0xb27a52, 0x8a5a3c];
const HAIRS = [0x1b1511, 0x2b2118, 0x4a2c1c, 0x6b4a2e, 0x8b8f96];
const IDLE = ["Bedrooms want the quiet side.", "Stair near the middle?", "Kitchen in the south-east.", "Let's keep the centre open.",
  "That wall can carry the slab.", "Two windows, opposite walls.", "Parking off the drive.", "Light from the north for the study."];
const ACKS = ["Noted.", "Good catch. We'll revise it.", "Understood.", "We'll take that on.", "Agreed, adjusting it."];

function criticLook(pig) {
  return {
    top: PIGMENT[pig] ?? PIGMENT.chalk, shirt: 0xeceff3, buttons: Math.random() < 0.5,
    skin: pick(SKINS), hair: pick(HAIRS), hairStyle: pick(["short", "short", "long", "bun"]),
    glasses: Math.random() < 0.45, legs: 0x2a2d35, shoes: 0x1b1c20, carry: "clipboard", tool: "pen",
  };
}

const GEO = new Map();
const geo = (key, make) => { if (!GEO.has(key)) GEO.set(key, make()); return GEO.get(key); };
const cap = (r, len) => geo(`c${r}:${len}`, () => new THREE.CapsuleGeometry(r, len, 6, 16));
const box = (x, y, z) => geo(`b${x}:${y}:${z}`, () => new THREE.BoxGeometry(x, y, z));
const ball = (r) => geo(`s${r}`, () => new THREE.SphereGeometry(r, 24, 18));
const dome = (r) => geo(`d${r}`, () => new THREE.SphereGeometry(r, 28, 12, 0, TAU, 0, Math.PI / 2));
const cyl = (r0, r1, h, n = 16) => geo(`y${r0}:${r1}:${h}:${n}`, () => new THREE.CylinderGeometry(r0, r1, h, n));
const arc = (r, t, a = Math.PI) => geo(`t${r}:${t}:${a}`, () => new THREE.TorusGeometry(r, t, 8, 20, a));

const MATS = new Map();
function mat(color, rough = 0.7) {
  const k = `${color}:${rough}`;
  if (!MATS.has(k)) MATS.set(k, new THREE.MeshStandardMaterial({ color, roughness: rough, metalness: 0.02 }));
  return MATS.get(k);
}
const PAPER = new THREE.MeshStandardMaterial({ color: 0xf4f1ea, roughness: 0.9, side: THREE.DoubleSide });
const GLINT = new THREE.MeshBasicMaterial({ color: 0xffffff });
const BLUSH = new THREE.MeshStandardMaterial({ color: 0xf08f84, roughness: 0.8, transparent: true, opacity: 0.5, depthWrite: false });

function buildFigure(L) {
  const root = new THREE.Group();
  const skin = mat(L.skin, 0.55);
  const shirt = mat(L.shirt, 0.8);
  const top = L.top != null ? mat(L.top, 0.72) : shirt;
  const sleeve = L.vest ? shirt : top;
  const legs = mat(L.legs, 0.85), shoes = mat(L.shoes, 0.45);
  const hairM = mat(L.hair ?? 0x1b1511, 0.9);
  const add = (parent, g, m, x = 0, y = 0, z = 0, shadow = true) => {
    const o = new THREE.Mesh(g, m);
    o.position.set(x, y, z);
    o.castShadow = shadow;
    parent.add(o);
    return o;
  };
  const joint = (parent, x = 0, y = 0, z = 0) => {
    const g = new THREE.Group();
    g.position.set(x, y, z);
    parent.add(g);
    return g;
  };

  // Legs and shoes.
  const hips = joint(root, 0, 0.3, 0);
  add(hips, ball(0.1), legs).scale.set(1.05, 0.7, 0.85);
  const leg = (side) => {
    const thigh = joint(hips, side * 0.058, -0.01, 0);
    add(thigh, cap(0.046, 0.06), legs, 0, -0.06, 0);
    const knee = joint(thigh, 0, -0.13, 0);
    add(knee, cap(0.043, 0.05), legs, 0, -0.05, 0);
    const ankle = joint(knee, 0, -0.127, 0);
    const shoe = add(ankle, cap(0.036, 0.06), shoes, 0, -0.008, 0.022);
    shoe.rotation.x = Math.PI / 2;
    shoe.scale.set(1.15, 1, 0.8);
    return { thigh, knee, ankle };
  };
  const lL = leg(1), lR = leg(-1);

  // Body: shirt or jacket, trousers to the waist, a belt.
  const spine = joint(hips, 0, 0, 0);
  add(spine, cap(0.125, 0.1), L.vest ? shirt : top, 0, 0.15, 0).scale.set(1, 1, 0.78);
  add(spine, ball(0.118), legs, 0, 0.03, 0).scale.set(1, 0.55, 0.82);
  if (!L.vest) {
    add(spine, cyl(0.127, 0.127, 0.022, 24), mat(0x2a1d14, 0.5), 0, 0.075, 0).scale.set(1, 1, 0.8);
    add(spine, box(0.03, 0.022, 0.01), mat(0xc9a45a, 0.3), 0, 0.075, 0.102, false);
  }
  if (L.top != null) {
    // An open jacket: the blouse shows in the V, two buttons below it.
    const v = add(spine, geo("vee", () => new THREE.ConeGeometry(0.055, 0.15, 3)), shirt, 0, 0.215, 0.093, false);
    v.rotation.z = Math.PI;
    v.scale.set(1, 1, 0.2);
    if (L.buttons) for (const y of [0.13, 0.09]) add(spine, ball(0.009), mat(0x0c0d10, 0.4), 0, y, 0.099, false);
  }
  if (L.collar != null) {
    const cm = mat(L.collar, 0.8);
    for (const s of [-1, 1]) {
      const c = add(spine, box(0.055, 0.022, 0.035), cm, s * 0.032, 0.272, 0.072, false);
      c.rotation.z = s * -0.45;
    }
  }
  if (L.placket) add(spine, box(0.014, 0.17, 0.005), mat(L.collar ?? L.shirt, 0.8), 0, 0.17, 0.098, false);
  if (L.pocket) add(spine, box(0.045, 0.045, 0.006), mat(L.collar ?? L.shirt, 0.8), 0.058, 0.19, 0.096, false);
  if (L.vest) {
    add(spine, cap(0.131, 0.08), mat(L.vest, 0.55), 0, 0.15, 0).scale.set(1, 1, 0.82);
    for (const y of [0.1, 0.2]) add(spine, cyl(0.134, 0.134, 0.022, 24), mat(0xe3e7ee, 0.25), 0, y, 0, false).scale.set(1, 1, 0.83);
  }

  // Head: a big round face with eyes that catch the light.
  add(spine, cyl(0.045, 0.05, 0.05), skin, 0, 0.32, 0);
  const head = joint(spine, 0, 0.5, 0);
  add(head, ball(0.2), skin);
  for (const s of [-1, 1]) {
    const x = s * 0.072;
    add(head, ball(0.042), mat(0xffffff, 0.3), x, 0, 0.172, false).scale.set(1, 1.15, 0.45);
    add(head, ball(0.03), mat(0x5a3520, 0.4), x, -0.004, 0.183, false).scale.set(1, 1.12, 0.4);
    add(head, ball(0.016), mat(0x0a0706, 0.3), x, -0.004, 0.19, false).scale.set(1, 1.1, 0.4);
    add(head, ball(0.008), GLINT, x + 0.011, 0.012, 0.197, false);
    add(head, box(0.056, 0.013, 0.012), hairM, x, 0.066, 0.176, false).rotation.z = s * -0.14;
    add(head, ball(0.026), BLUSH, s * 0.115, -0.05, 0.152, false).scale.set(1, 0.7, 0.3);
    add(head, ball(0.035), skin, s * 0.197, -0.01, 0, false).scale.set(0.6, 1, 0.9);
    if (L.lashes) add(head, box(0.05, 0.008, 0.01), mat(0x0a0706, 0.4), x, 0.034, 0.187, false).rotation.z = s * -0.12;
  }
  add(head, ball(0.018), skin, 0, -0.035, 0.19, false).scale.set(1, 0.8, 0.8);
  const smile = add(head, arc(0.035, 0.0065), mat(0x8a3b2e, 0.5), 0, -0.078, 0.178, false);
  smile.rotation.z = Math.PI;

  // Hair: one cap sets the hairline; longer styles add volume behind.
  add(head, ball(0.21), hairM, 0, 0.015, -0.025);
  if (L.hairStyle === "long") {
    add(head, ball(0.2), hairM, 0, -0.1, -0.08).scale.set(1.08, 1.3, 0.8);
    for (const s of [-1, 1]) add(head, cap(0.055, 0.14), hairM, s * 0.165, -0.14, 0.0);
  } else if (L.hairStyle === "bun") {
    add(head, ball(0.07), hairM, 0, 0.13, -0.17);
  }
  if (L.glasses) {
    const gm = mat(0x111214, 0.3);
    for (const s of [-1, 1]) add(head, arc(0.043, 0.007, TAU), gm, s * 0.072, 0, 0.198, false);
    add(head, box(0.03, 0.008, 0.008), gm, 0, 0.006, 0.202, false);
  }
  if (L.hat != null) {
    const hm = mat(L.hat, 0.35);
    add(head, dome(0.214), hm, 0, 0.112, -0.01);
    add(head, cyl(0.232, 0.232, 0.016, 32), hm, 0, 0.116, 0.004).scale.set(1, 1, 1.08);
    const rib = add(head, arc(0.214, 0.013), hm, 0, 0.112, -0.01);
    rib.rotation.y = Math.PI / 2;
  }

  // Arms: short and round, with mitten hands.
  const arm = (side) => {
    const sh = joint(spine, side * 0.14, 0.25, 0);
    add(sh, ball(0.045), sleeve);
    add(sh, cap(0.038, 0.06), sleeve, 0, -0.055, 0);
    const el = joint(sh, 0, -0.105, 0);
    add(el, cap(0.034, 0.05), L.rolled ? skin : sleeve, 0, -0.045, 0);
    if (L.rolled) add(el, cyl(0.041, 0.041, 0.026), shirt, 0, -0.004, 0, false);
    const hand = joint(el, 0, -0.1, 0);
    add(hand, ball(0.04), skin, 0, -0.02, 0);
    return { sh, el, hand };
  };
  const aL = arm(1), aR = arm(-1);

  // What they work with.
  let tip;
  if (L.tool === "staff") {
    const staff = joint(aR.hand, 0, -0.02, 0.01);
    for (let i = 0; i < 8; i++) add(staff, cyl(0.012, 0.012, 0.1, 8), mat(i % 2 ? 0xd2402f : 0xe9ebef, 0.5), 0, 0.49 - i * 0.1, 0);
    tip = joint(staff, 0, -0.26, 0);
  } else {
    const pencil = joint(aR.hand, 0, -0.02, 0.03);
    add(pencil, cyl(0.011, 0.011, 0.12, 6), mat(L.tool === "pen" ? 0x1b1d22 : 0xf2b33d, 0.4), 0, -0.05, 0, false);
    add(pencil, new THREE.ConeGeometry(0.011, 0.025, 6), mat(0x2a221c, 0.5), 0, -0.122, 0, false).rotation.x = Math.PI;
    tip = joint(pencil, 0, -0.135, 0);
  }
  if (L.carry === "tube") {
    const roll = joint(aL.hand, 0, -0.02, 0.05);
    roll.rotation.x = Math.PI / 2 - 0.25;
    add(roll, cyl(0.032, 0.032, 0.3, 16), PAPER);
    add(roll, cyl(0.034, 0.034, 0.02, 16), mat(0x4f6fa3, 0.6), 0, 0.07, 0, false);
  } else if (L.carry === "ruler") {
    add(aL.hand, box(0.036, 0.26, 0.008), mat(0xdc9b4a, 0.6), 0, 0.04, 0.035);
  } else if (L.carry === "clipboard") {
    const board = joint(aL.hand, 0, -0.04, 0.03);
    board.rotation.x = -0.5;
    add(board, box(0.13, 0.17, 0.008), mat(0x8a6a45, 0.7));
    add(board, box(0.115, 0.14, 0.003), PAPER, 0, -0.008, 0.006, false);
    add(board, box(0.045, 0.015, 0.012), mat(0x9aa0aa, 0.3), 0, 0.08, 0.008, false);
  }

  root.scale.setScalar(H);
  root.userData = {
    j: {
      hips, spine, head,
      thighL: lL.thigh, kneeL: lL.knee, ankleL: lL.ankle,
      thighR: lR.thigh, kneeR: lR.knee, ankleR: lR.ankle,
      shL: aL.sh, elL: aL.el, handL: aL.hand,
      shR: aR.sh, elR: aR.el, handR: aR.hand,
    },
    tip, look: L, phase: Math.random() * TAU, clock: Math.random() * 10, speed: 0, pose: {},
  };
  return root;
}

const brief = (s, n = 92) => {
  s = String(s || "").trim();
  if (s.length <= n) return s;
  const cut = s.slice(0, n);
  return `${cut.slice(0, cut.lastIndexOf(" ")).replace(/[,;:.]$/, "")}…`;
};

/* ═══ THE STAGE ═════════════════════════════════════════════════════════ */

/* ── fit-out: finishes and furniture by room ──────────────────────────── */

const bounce = (t) => {
  // Drops, touches down and settles once: the furniture has weight.
  if (t < 0.72) return (t / 0.72) ** 2;
  const k = (t - 0.72) / 0.28;
  return 1 - Math.sin(k * Math.PI) * 0.08 * (1 - k);
};
const elastic = (t) => (t <= 0 ? 0 : t >= 1 ? 1 : 1 - Math.pow(2, -9 * t) * Math.cos(t * 9.5));
const GLOW = new THREE.MeshBasicMaterial({ color: 0xffc46b });

const BEDS = new Set(["master_bedroom", "bedroom", "guest_bedroom", "children_bedroom"]);
const FLOOR_OF = (t) => (BEDS.has(t) || t === "study" || t === "home_office" ? 0x9a6b45
  : WET.has(t) ? 0xc9c4ba : t === "kitchen" || t === "store" ? 0x8f9a8e
  : t === "balcony" || t === "terrace" || t === "verandah" || t === "courtyard" ? 0xa89a86
  : t === "staircase" ? 0xb9ad9a : t === "garage" || t === "parking" ? 0x7d7a74 : 0xd8cab2);
const PAINT_OF = (t) => ({
  master_bedroom: 0xd6c6ae, bedroom: 0xdbe2d2, guest_bedroom: 0xe6dccc, children_bedroom: 0xefe2c6,
  living: 0xefe7da, dining: 0xebe1d1, kitchen: 0xf3ede3, puja: 0xf1e0b6, study: 0xe2d6c3,
  bathroom: 0xd9e3e8, toilet: 0xd9e3e8, powder: 0xd9e3e8,
}[t] ?? 0xede6da);

const C = {
  wood: 0x8a5f3c, oak: 0xc2a37c, linen: 0xefe9df, fabric: 0x9c8a74, accent: 0x6f8662, dark: 0x2b2a29,
  steel: 0xbfc3c6, gold: 0xc9a14a, white: 0xf5f4f0, leaf: 0x4f7a3a, pot: 0xa35a3a, rug: 0x8c6b52,
  stone: 0x3a3a3c, blush: 0xc98f7a, glass: 0x9fb2bf,
};

// Pieces for a room, in the room's own frame: u runs along its long side,
// v across it. Each is [u, v, y, size_u, size_v, size_y, colour, kind].
function FURNISH(type, L, S) {
  const m = 0.18;
  const out = [];
  const add = (...p) => out.push(p);
  const plant = (u, v) => { add(u, v, 0, 0.32, 0.32, 0.3, C.pot, "cyl"); add(u, v, 0.28, 0.5, 0.5, 0.5, C.leaf, "ball"); };
  if (L < 1.2 || S < 1.0) return out;
  if (BEDS.has(type)) {
    const bw = type === "master_bedroom" ? 1.8 : type === "children_bedroom" ? 1.1 : 1.6;
    const bl = Math.min(2.05, L - 2 * m - 0.6);
    const hu = -L / 2 + m;
    add(hu + bl / 2 + 0.05, 0, 0, bl + 0.5, Math.min(S - 0.6, bw + 0.9), 0.012, C.rug);
    add(hu + bl / 2, 0, 0, bl, bw, 0.3, C.wood);
    add(hu + bl / 2 + 0.02, 0, 0.3, bl - 0.06, bw - 0.06, 0.16, C.linen);
    add(hu + bl * 0.66, 0, 0.46, bl * 0.42, bw - 0.02, 0.05, type === "children_bedroom" ? 0xd6a23a : C.accent);
    for (const s of bw > 1.3 ? [-bw / 4, bw / 4] : [0]) add(hu + 0.3, s, 0.46, 0.34, bw > 1.3 ? bw / 2 - 0.12 : 0.6, 0.1, C.white);
    add(hu + 0.04, 0, 0, 0.08, bw + 0.1, 0.95, C.wood);
    if (S >= bw + 1.1) for (const s of [-1, 1]) add(hu + 0.25, s * (bw / 2 + 0.3), 0, 0.42, 0.42, 0.45, C.oak);
    if (S >= bw + 1.8 && L >= 3.2) add(L / 2 - m - 0.9, S / 2 - m - 0.3, 0, Math.min(1.8, L - bl - 0.9), 0.6, 1.0, C.oak);
    if (L >= 3.6) plant(L / 2 - m - 0.3, -S / 2 + m + 0.3);
  } else if (type === "living" || type === "family" || type === "drawing") {
    const sl = Math.min(2.6, L - 1.4);
    const sv = S / 2 - m - 0.45;
    add(0, 0, 0, Math.min(2.6, L - 1.2), Math.min(2.0, S - 1.4), 0.012, C.rug);
    add(0, sv, 0, sl, 0.9, 0.42, C.fabric);
    add(0, sv + 0.36, 0.42, sl, 0.18, 0.4, C.fabric);
    for (const s of [-1, 1]) add(s * (sl / 2 - 0.08), sv, 0.42, 0.16, 0.9, 0.2, C.fabric);
    add(-sl / 4, sv - 0.05, 0.42, 0.4, 0.4, 0.12, C.accent);
    add(sl / 4, sv - 0.05, 0.42, 0.4, 0.4, 0.12, C.blush);
    add(0, 0.05, 0, 1.0, 0.6, 0.38, C.oak);
    add(0, -S / 2 + m + 0.2, 0, Math.min(1.8, L - 1.5), 0.4, 0.5, C.wood);
    add(0, -S / 2 + m + 0.08, 0.5, Math.min(1.3, L - 1.8), 0.06, 0.45, C.dark);
    if (L >= 3.8) add(-L / 2 + m + 0.5, 0, 0, 0.8, 0.8, 0.45, C.fabric);
    plant(L / 2 - m - 0.3, S / 2 - m - 0.3);
    if (S >= 3.4) plant(-L / 2 + m + 0.3, -S / 2 + m + 0.3);
  } else if (type === "dining") {
    const tl = Math.min(1.8, L - 1.3), tw = Math.min(0.95, S - 1.3);
    if (tl < 0.8 || tw < 0.6) return out;
    add(0, 0, 0, tl, tw, 0.72, C.wood);
    add(0, 0, 0.72, tl + 0.06, tw + 0.06, 0.04, C.oak);
    const n = Math.max(1, Math.floor(tl / 0.62));
    for (let k = 0; k < n; k++) {
      const u = -tl / 2 + tl * (k + 0.5) / n;
      for (const s of [-1, 1]) {
        add(u, s * (tw / 2 + 0.28), 0, 0.42, 0.42, 0.45, C.oak);
        add(u, s * (tw / 2 + 0.47), 0.45, 0.42, 0.06, 0.4, C.oak);
      }
    }
    add(0, 0, 1.25, 0.3, 0.3, 0.12, C.gold, "cyl");
    add(0, 0, 1.18, 0.12, 0.12, 0.12, C.gold, "glow");
  } else if (type === "kitchen" || type === "pantry") {
    const run = L - 2 * m;
    add(0, -S / 2 + m + 0.3, 0, run, 0.6, 0.86, C.oak);
    add(0, -S / 2 + m + 0.3, 0.86, run, 0.62, 0.04, C.stone);
    add(-run / 4, -S / 2 + m + 0.3, 0.9, 0.6, 0.5, 0.02, C.dark);
    if (S >= 2.6) {
      add(-L / 2 + m + 0.3, 0.2, 0, 0.6, Math.min(S - 1.2, 2.0), 0.86, C.oak);
      add(-L / 2 + m + 0.3, 0.2, 0.86, 0.62, Math.min(S - 1.2, 2.0), 0.04, C.stone);
    }
    add(L / 2 - m - 0.38, S / 2 - m - 0.38, 0, 0.7, 0.7, 1.0, C.steel, "gloss");
    if (S >= 3.2) add(0.4, 0.3, 0, Math.min(1.6, L - 2.4), 0.8, 0.9, C.wood);
  } else if (WET.has(type)) {
    if (type === "utility" || type === "laundry") {
      add(-L / 2 + m + 0.32, -S / 2 + m + 0.32, 0, 0.62, 0.62, 0.85, C.white, "gloss");
      add(-L / 2 + m + 0.32, -S / 2 + m + 0.02, 0.4, 0.36, 0.04, 0.36, C.dark);
      add(L / 2 - m - 0.3, -S / 2 + m + 0.25, 0, 0.6, 0.5, 0.85, C.steel);
      return out;
    }
    add(-L / 2 + m + 0.35, S / 2 - m - 0.25, 0, 0.38, 0.38, 0.4, C.white, "cyl");
    add(-L / 2 + m + 0.35, S / 2 - m - 0.05, 0.3, 0.4, 0.16, 0.42, C.white, "gloss");
    add(0, -S / 2 + m + 0.25, 0, Math.min(0.9, L - 1.2), 0.48, 0.82, C.oak);
    add(0, -S / 2 + m + 0.25, 0.82, 0.42, 0.34, 0.08, C.white, "gloss");
    if (L >= 2.0) add(L / 2 - m - 0.45, 0, 0, 0.04, Math.min(1.0, S - 0.5), 1.0, C.glass, "gloss");
  } else if (type === "puja") {
    add(0, -S / 2 + m + 0.3, 0, 0.9, 0.55, 0.7, C.wood);
    add(0, -S / 2 + m + 0.3, 0.7, 0.7, 0.45, 0.25, C.gold, "gloss");
    add(0, -S / 2 + m + 0.3, 0.95, 0.5, 0.5, 0.3, C.gold, "cone");
    for (const s of [-0.22, 0.22]) add(s, -S / 2 + m + 0.68, 0, 0.08, 0.08, 0.08, C.gold, "glow");
    add(0, 0.1, 0, Math.min(1.2, L - 0.6), Math.min(0.8, S - 0.8), 0.012, 0xb6553a);
  } else if (type === "study" || type === "home_office" || type === "library") {
    add(0, -S / 2 + m + 0.3, 0, Math.min(1.4, L - 0.8), 0.6, 0.75, C.oak);
    add(0, -S / 2 + m + 0.85, 0, 0.5, 0.5, 0.5, C.dark);
    add(-L / 2 + m + 0.18, 0.2, 0, 0.35, Math.min(1.6, S - 1.2), 1.0, C.wood);
    plant(L / 2 - m - 0.3, S / 2 - m - 0.3);
  } else if (type === "staircase") {
    const n = 9, run = Math.min(L - 0.4, 3.0), sw = Math.min(1.0, S / 2 - 0.1);
    for (let k = 0; k < n; k++) {
      add(-run / 2 + run * (k + 0.5) / n, -S / 4, 0, run / n, sw, 0.05 * (k + 1), C.oak);
      add(run / 2 - run * (k + 0.5) / n, S / 4, 0, run / n, sw, 0.05 * (n + k + 1), C.oak);
    }
  } else if (type === "foyer" || type === "lobby") {
    add(0, -S / 2 + m + 0.2, 0, Math.min(1.1, L - 0.8), 0.35, 0.8, C.wood);
    add(0, 0, 0, Math.min(1.4, L - 0.6), Math.min(0.9, S - 0.6), 0.012, C.rug);
    plant(L / 2 - m - 0.25, S / 2 - m - 0.25);
  } else if (type === "balcony" || type === "terrace" || type === "verandah") {
    for (let u = -L / 2 + 0.5; u <= L / 2 - 0.4; u += 0.9) plant(u, S / 2 - m - 0.25);
    if (S >= 1.6 && L >= 2.2) {
      add(0, -0.1, 0, 0.6, 0.6, 0.45, C.oak, "cyl");
      for (const s of [-0.7, 0.7]) add(s, -0.1, 0, 0.55, 0.55, 0.45, C.fabric);
    }
  } else if (type === "garage" || type === "parking" || type === "car_porch") {
    // A hatchback, 3.8 x 1.65 m, with a clear metre to walk round it; smaller only if the porch is.
    const k = clamp(Math.min((L - 1.2) / 3.8, (S - 1.1) / 1.65), 0.5, 1);
    const cl = 3.8 * k, cw = 1.65 * k;
    add(0, 0, 0.18 * k, cl, cw, 0.5 * k, 0x8a2f2a, "gloss");
    add(0.15 * k, 0, 0.68 * k, cl * 0.5, cw * 0.9, 0.36 * k, 0x2b3a44, "gloss");
    for (const su of [-1, 1]) for (const sv of [-1, 1]) add(su * cl * 0.32, sv * cw * 0.46, 0, 0.5 * k, 0.18 * k, 0.5 * k, C.dark);
  } else if (type === "corridor") {
    add(0, 0, 0, Math.max(0.6, L - 0.8), Math.min(0.8, S - 0.3), 0.012, C.rug);
  }
  return out;
}

export class Stage3D {
  constructor(host) {
    this.host = host;
    this.speed = 1;
    this.static = reduced();
    this.labels = [];
    this.schemes = {};
    this.critics = [];
    this.pending = [];
    this.raf = 0;

    const r = (this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" }));
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    r.outputColorSpace = THREE.SRGBColorSpace;
    r.toneMapping = THREE.ACESFilmicToneMapping;
    r.toneMappingExposure = 1.05;
    r.shadowMap.enabled = true;
    r.shadowMap.type = THREE.PCFSoftShadowMap;
    r.setClearColor(COL.ground, 1);
    r.domElement.className = "st-canvas";
    host.append(r.domElement);

    this.labelLayer = document.createElement("div");
    this.labelLayer.className = "st-labels";
    host.append(this.labelLayer);

    const scene = (this.scene = new THREE.Scene());
    scene.add(new THREE.HemisphereLight(0xf4ead8, 0x1e1914, 1.2));
    const sun = (this.sun = new THREE.DirectionalLight(0xffeedb, 1.75));
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    sun.shadow.bias = -0.0008;
    sun.shadow.radius = 4;
    scene.add(sun, sun.target);

    const ground = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), new THREE.MeshStandardMaterial({ color: COL.ground, roughness: 1 }));
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    scene.add(ground);
    // A faint metre grid: the drafting table's own paper.
    const grid = new THREE.GridHelper(120, 120, 0x1d1b19, 0x151413);
    grid.position.y = 0.001;
    scene.add(grid);

    this.camera = new THREE.OrthographicCamera(-10, 10, 10, -10, 0.1, 400);
    this.view = { tilt: 1, target: new THREE.Vector3(), s: 12, rate: 1.4, ready: false };
    this.root = new THREE.Group();
    scene.add(this.root);

    this.team = ["arch1", "eng", "arch2"].map((k, i) => this._person(LOOKS[k], k, new THREE.Vector3(-30, 0, 4 + i)));
    this.team.forEach((m) => { m.fig.visible = !this.static; });

    this._resize = () => this.resize();
    this.ro = new ResizeObserver(this._resize);
    this.ro.observe(host);
    this.resize();
    this._tick = this._tick.bind(this);
    this.raf = requestAnimationFrame(this._tick);
  }

  _person(look, kind, at) {
    const fig = buildFigure(look);
    fig.position.copy(at);
    this.scene.add(fig);
    const m = { kind, fig, tasks: [], task: null, face: 0, vel: 0, moved: 0, busyUntil: 0 };
    // Where the pen point sits relative to the person holding it.
    m.reach0 = look.tool === "staff" ? { f: 0.34, r: 0.27 } : { f: 0.9, r: 0.2 };
    this._sizeFig(m);
    if (look.tool !== "pen") {
      // The mark being made, and for the architects a stylus beam to it.
      m.dot = new THREE.Mesh(new THREE.CircleGeometry(0.09, 20), new THREE.MeshBasicMaterial({
        color: COL.gold, transparent: true, opacity: 0.95, depthWrite: false, blending: THREE.AdditiveBlending,
      }));
      m.dot.rotation.x = -Math.PI / 2;
      m.dot.visible = false;
      this.scene.add(m.dot);
      if (look.tool === "stylus") {
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(6), 3));
        m.beam = new THREE.Line(g, new THREE.LineBasicMaterial({ color: COL.gold, transparent: true, opacity: 0.55 }));
        m.beam.frustumCulled = false;
        m.beam.visible = false;
        this.scene.add(m.beam);
      }
    }
    return m;
  }

  // People are sized to the board: on a large plot a life-size figure is a
  // speck, so the team grows with the plot (and walks proportionally faster).
  _sizeFig(m) {
    const k = this.figS || 1;
    m.fig.scale.setScalar(H * k);
    m.reach = { f: m.reach0.f * k, r: m.reach0.r * k };
    if (m.dot) m.dot.scale.setScalar(k);
  }

  /* ── framing: a drone over the work ───────────────────────────────── */

  resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.aspect = w / h;
    this._frame(0, true);
  }

  // The box the camera should hold: the whole site, or the floor being
  // worked, eased toward the rooms in hand, but never so close that the
  // rest of that floor drops out of frame.
  _focusBox() {
    if (!this.plot) return null;
    const { w, d } = this.plot;
    const z0 = this.origin.z - d, z1 = this.origin.z;
    const lv = this.settling ? null : this.focusLevel;
    if (lv == null) return { x0: this.origin.x, x1: this.origin.x + this.extent.total, z0, z1, pad: 0.8 };
    const x0 = this.origin.x + lv * (w + GAP);
    const plate = { x0, x1: x0 + w, z0, z1 };
    const rs = this.focusRooms || [];
    if (!rs.length) return { ...plate, pad: 0.35 };
    let ax0 = Infinity, ax1 = -Infinity, az0 = Infinity, az1 = -Infinity;
    for (const r of rs) for (const p of r.pts) {
      ax0 = Math.min(ax0, p.x); ax1 = Math.max(ax1, p.x); az0 = Math.min(az0, p.z); az1 = Math.max(az1, p.z);
    }
    const k = 0.32;
    return {
      x0: lerp(plate.x0, ax0 - 1.5, k), x1: lerp(plate.x1, ax1 + 1.5, k),
      z0: lerp(plate.z0, az0 - 1.5, k), z1: lerp(plate.z1, az1 + 1.5, k), pad: 0.3,
    };
  }

  _frame(dt = 0, snap = false) {
    const c = this.camera, v = this.view;
    const a = Math.max(this.aspect || 1.6, 0.4);
    const box = this._focusBox();
    if (box) {
      c.updateMatrixWorld();
      const q = c.quaternion.clone().invert();
      const centre = new THREE.Vector3((box.x0 + box.x1) / 2, 0, (box.z0 + box.z1) / 2);
      const p = new THREE.Vector3();
      let mx = 0, my = 0;
      for (const x of [box.x0, box.x1]) for (const z of [box.z0, box.z1]) for (const y of [0, WALL_H]) {
        p.set(x, y, z).sub(centre).applyQuaternion(q);
        mx = Math.max(mx, Math.abs(p.x)); my = Math.max(my, Math.abs(p.y));
      }
      const want = Math.max(my * 1.12, (mx * 1.08) / a) + box.pad;
      const k = snap || !v.ready ? 1 : damp(dt, v.rate);
      v.target.lerp(centre, k);
      v.s += (want - v.s) * k;
      v.ready = true;
    }
    c.left = -v.s * a; c.right = v.s * a; c.top = v.s * 1.16; c.bottom = -v.s * 0.84;
    c.updateProjectionMatrix();
  }

  // Isometric while the team works, with a slow drone drift; straight down
  // for the hand-off. `tilt` runs 1 (iso) to 0 (plan).
  _placeCamera(now) {
    const v = this.view;
    const drone = this.static ? 0 : v.tilt;
    const yaw = -Math.PI / 4 * 0.62 * v.tilt + Math.sin((now / 15000) * TAU) * 0.16 * drone;
    const elev = lerp(Math.PI / 2 - 0.0001, 0.66 + Math.sin((now / 11000) * TAU) * 0.035 * drone, v.tilt);
    const r = 80;
    this.camera.position.set(
      v.target.x + r * Math.cos(elev) * Math.sin(yaw),
      v.target.y + r * Math.sin(elev),
      v.target.z + r * Math.cos(elev) * Math.cos(yaw),
    );
    this.camera.up.set(0, 1, 0);
    if (v.tilt < 0.02) this.camera.up.set(0, 0, -1);
    this.camera.lookAt(v.target);
  }

  // Which floor the drone holds: the one most hands are drawing on, or the
  // one the specialists are standing on. It waits a beat before moving so
  // it never twitches between floors.
  _updateFocus(dt) {
    const s = this.current;
    const rooms = [];
    if (s && !s.risen) {
      for (const m of this.team) {
        const t = m.task?.type === "draw" ? m.task : m.tasks.find((x) => x.type === "draw");
        if (t?.room) rooms.push(t.room);
      }
    }
    if (!rooms.length) for (const c of this.critics) if (!c.leaving && c.p.room) rooms.push(c.p.room);
    const n = {};
    for (const r of rooms) n[r.li] = (n[r.li] || 0) + 1;
    if (!rooms.length && this.planningActive && this.plot) {
      // Setting out: hold the floor most of the team is standing on.
      const { w } = this.plot;
      for (const m of this.team) {
        const li = Math.floor((m.fig.position.x - this.origin.x + GAP / 2) / (w + GAP));
        if (li >= 0 && li < this.plot.n) n[li] = (n[li] || 0) + 1;
      }
    }
    const top = Object.entries(n).sort((a, b) => b[1] - a[1])[0];
    const lv = top ? +top[0] : null;
    if (lv !== this.focusLevel) {
      this.focusHold = (this.focusHold || 0) + dt;
      if (this.focusHold > 0.9) { this.focusLevel = lv; this.focusHold = 0; }
    } else this.focusHold = 0;
    this.focusRooms = rooms.filter((r) => r.li === this.focusLevel);
  }

  /* ── the plot ─────────────────────────────────────────────────────── */

  // Lay out floor plates for a plot of w x d metres with n levels.
  setPlot({ w, d, levels = 1, road = "N", setbacks = null }) {
    this.root.clear();
    this.labels.forEach((l) => l.el.remove());
    this.labels = [];
    this.schemes = {};
    this.current = null;
    this.tweens = [];
    this.speed = 1;
    this.deadline = 0;
    this.boost = 1;
    this.settling = false;
    this.focusLevel = null;
    this.focusRooms = [];
    this.view.tilt = 1;
    this.view.rate = 1.4;
    this.view.ready = false;
    this.critics.forEach((c) => this.scene.remove(c.fig));
    this.critics = [];
    this.pending = [];
    this.team.forEach((m, i) => {
      m.tasks = []; m.task = null; m.vel = 0; m.consulting = false; m.bubble = null;
      m.fig.position.set(-30, 0, 4 + i);
    });
    this.resume();
    this.plot = { w, d, n: Math.max(1, levels), road };
    this.figS = clamp(Math.sqrt(w * d * Math.max(1, levels)) / 17, 1, 3.4);
    this.team.forEach((m) => this._sizeFig(m));
    const total = this.plot.n * w + (this.plot.n - 1) * GAP;
    this.origin = new THREE.Vector3(-total / 2, 0, d / 2);   // plan (0,0) of plate 0
    this.view.target.set(0, 0, 0);
    this.extent = { total, d };
    this._frame(0, true);

    const sun = this.sun;
    sun.position.set(-14, 26, 18);
    sun.target.position.set(0, 0, 0);
    const sc = sun.shadow.camera;
    sc.left = -total; sc.right = total; sc.top = d + 6; sc.bottom = -d - 6;
    sc.updateProjectionMatrix();

    this.plates = [];
    for (let i = 0; i < this.plot.n; i++) {
      const g = new THREE.Group();
      g.position.copy(this.P(i, 0, 0));
      // A slab you could pick up, with its edge drawn in.
      const slab = new THREE.Mesh(new THREE.BoxGeometry(w + 0.3, 0.16, d + 0.3),
        new THREE.MeshStandardMaterial({ color: COL.slab, roughness: 0.95 }));
      slab.position.set(w / 2, -0.08, -d / 2);
      slab.receiveShadow = true;
      slab.castShadow = true;
      const surf = plane(w, d, COL.plot, 1);
      surf.position.set(w / 2, 0.004, -d / 2);
      surf.receiveShadow = true;
      const edge = lineOf([new THREE.Vector3(0, 0, 0), new THREE.Vector3(w, 0, 0), new THREE.Vector3(w, 0, -d), new THREE.Vector3(0, 0, -d), new THREE.Vector3(0, 0, 0)], COL.chalk, 0.5, 0.008);
      edge.geometry.setDrawRange(0, 5);
      g.add(slab, surf, edge);
      this.root.add(g);
      this.plates.push(g);
    }

    // The planning layer: everything the team sketches before a scheme exists.
    this.planning = new THREE.Group();
    this.root.add(this.planning);
    this.setbacks = setbacks;
    this.construction = [];
  }

  // Plan coordinates on level i to world space.
  P(i, x, y) {
    const { w } = this.plot;
    return new THREE.Vector3(this.origin.x + i * (w + GAP) + x, 0, this.origin.z - y);
  }

  // Keep the board in step with the run: the later the engine is, the
  // quicker the team works, so the drawing is never left behind the bar.
  // Keep the board in step with the engine: from how far the run has got
  // and how long it took to get there, estimate when it will finish, and
  // let the team aim to put the last line down at that moment.
  pace(progress, elapsed) {
    if (this.settling || !(progress > 0.02) || !(elapsed > 0)) return;
    const eta = (elapsed * (1 - progress)) / Math.max(progress, 0.08);
    this.deadline = performance.now() + clamp(eta, 2, 180) * 1000;
  }

  // Metres still to walk and draw for whoever has the most left.
  _left() {
    let most = 0;
    for (const m of this.team) {
      let left = 0;
      for (const t of [m.task, ...m.tasks]) {
        if (t?.type === "draw") left += (t.pts.length - (t.i ?? 0)) * 0.08;
        else if (t?.type === "run") left += 2;
      }
      most = Math.max(most, left);
    }
    return most;
  }

  // A few times a second: the speed that lands the drawing on the deadline,
  // eased so nobody visibly lurches.
  _keepPace(now) {
    if (this.settling || now < (this.paceAt || 0)) return;
    this.paceAt = now + 400;
    const s = this.current;
    let want = 1;
    if (s && !s.drawn && this.deadline) {
      const secs = Math.max(1.5, ((this.deadline - performance.now()) / 1000) * 0.85);
      want = clamp(this._left() / (PACE * secs), 1, 9);
    }
    want *= this.boost || 1;
    this.speed += (want - this.speed) * 0.35;
  }

  /* ── labels and voices ────────────────────────────────────────────── */

  _label(text, world, cls = "") {
    const el = document.createElement("span");
    el.className = `st-label ${cls}`;
    el.textContent = text;
    this.labelLayer.append(el);
    const l = { el, world: world.clone(), on: false };
    this.labels.push(l);
    return l;
  }

  _show(l, on = true) {
    l.on = on;
    l.el.classList.toggle("is-on", on);
  }

  // A few words above someone's head, following them as they move.
  _bubble(fig, head, text, cls = "", pig = "") {
    const el = document.createElement("div");
    el.className = `st-bubble ${cls}`;
    if (pig) el.dataset.pig = pig;
    if (head) {
      const b = document.createElement("b");
      b.textContent = head;
      el.append(b);
    }
    el.append(document.createTextNode(text));
    this.labelLayer.append(el);
    const l = { el, world: fig.position.clone(), on: false, follow: fig, lift: H * 1.1 * (this.figS || 1), anchor: "translate(-50%, -100%)" };
    this.labels.push(l);
    this._labelsTick();
    void el.offsetWidth;
    this._show(l);
    // The board stays legible: three voices at most.
    const live = this.labels.filter((x) => x.follow && x.on);
    if (live.length > 3) this._drop(live[0]);
    return l;
  }

  _drop(l) {
    if (!l) return;
    l.el.classList.remove("is-on");
    this.labels = this.labels.filter((x) => x !== l);
    setTimeout(() => l.el.remove(), 320);
  }

  /* ── tasks ────────────────────────────────────────────────────────── */

  _do(who, ...tasks) { who.tasks.push(...tasks); }
  _member(kind) { return this.team.find((t) => t.kind === kind); }

  _clear(m) {
    m.tasks = [];
    m.task = null;
    m.consulting = false;
    if (m.bubble) { this._drop(m.bubble); m.bubble = null; }
  }

  // Where to stand so the pen lands on `a`, heading toward `b`.
  _standAt(m, a, b) {
    const dir = b.clone().sub(a);
    dir.y = 0;
    if (dir.lengthSq() < 1e-6) dir.set(0, 0, 1);
    dir.normalize();
    const right = new THREE.Vector3(-dir.z, 0, dir.x);
    return a.clone().addScaledVector(dir, -m.reach.f).addScaledVector(right, -m.reach.r);
  }

  _drawLine(m, a, b, color, opacity, parent) {
    const pts = resample([a, b]);
    this._do(m, { type: "run", to: this._standAt(m, a, b) }, { type: "draw", pts, line: this._line([a, b], color, opacity, parent) });
  }

  // The first minutes on site, in order: the engineer stakes and walks the
  // boundary, one architect marks the setback envelope, the other splits
  // it into zones. Then the three of them huddle at the front of the plot
  // until the schemes arrive, rather than drawing anything made up.
  plan(brief_) {
    const { w, d, n } = this.plot;
    const team = [...this.team].sort(() => Math.random() - 0.5);
    const [p1, p2, p3] = team;
    // Each run starts from a different place, in a different formation.
    const start = pick([[w * 0.3, -4], [-3, d * 0.4], [w + 3, d * 0.6], [w * 0.7, d + 3]]);
    this.team.forEach((t, i) => { t.fig.position.copy(this.P(0, start[0] + i * 1.3 * (this.figS || 1), start[1])); this._clear(t); });
    const quick = (m, a, b, color, opacity, parent) => {
      this._drawLine(m, a, b, color, opacity, parent);
      m.tasks[m.tasks.length - 1].quick = true;
    };
    const rnd = (a, b) => a + Math.random() * (b - a);
    const at = (x, y, lv = 0) => this.P(lv, x, y);
    const say = (m, text) => this._do(m, { type: "say", text, t: 1.6, team: true });

    const sb = this.setbacks || { front: 0, rear: 0, left: 0, right: 0 };
    const r = this.plot.road;
    const inset = r === "N" ? { t: sb.front, b: sb.rear, l: sb.left, r: sb.right }
      : r === "S" ? { t: sb.rear, b: sb.front, l: sb.right, r: sb.left }
        : r === "E" ? { t: sb.left, b: sb.right, l: sb.rear, r: sb.front }
          : { t: sb.right, b: sb.left, l: sb.front, r: sb.rear };
    const env = { x0: inset.l, x1: w - inset.r, y0: inset.b, y1: d - inset.t };

    // A repertoire of real first-day site work. Each render draws a different
    // hand from it, deals the jobs to different people, in a different order.
    const plays = {
      // Pace the plot, drive a few stakes where the soil is tested.
      survey: (m) => {
        say(m, pick(["Walking the plot first.", "Let's see the ground.", "Checking levels."]));
        const k = 3 + Math.floor(Math.random() * 3);
        for (let i = 0; i < k; i++) {
          const p = at(rnd(1, w - 1), rnd(1, d - 1));
          this._do(m, { type: "run", to: p }, { type: "note", t: rnd(0.8, 1.6) }, { type: "call", fn: () => this._stake(p) });
        }
      },
      // Peg the four corners of the plot, string a line round them and write
      // each side's length on the ground.
      corners: (m) => {
        say(m, pick(["Pegging the corners.", "Corners first, then the string.", "Let's find the boundary stones."]));
        const c = [[0, 0], [w, 0], [w, d], [0, d]];
        const s0 = Math.floor(Math.random() * 4);
        for (let k = 0; k < 4; k++) {
          const [x, y] = c[(s0 + k) % 4], [nx, ny] = c[(s0 + k + 1) % 4];
          const p = at(x, y);
          this._do(m, { type: "run", to: p }, { type: "note", t: 0.6 }, { type: "call", fn: () => this._stake(p) });
          quick(m, p, at(nx, ny), COL.chalk, 0.4, this.planning);
          this._do(m, { type: "call", fn: () => this._dim(at((x + nx) / 2, (y + ny) / 2), Math.hypot(nx - x, ny - y)) });
        }
      },
      // Tape both diagonals: if they agree, the plot is square.
      diagonal: (m) => {
        say(m, pick(["Checking it's square.", "Diagonals, to be sure.", "Taping corner to corner."]));
        quick(m, at(0, 0), at(w, d), COL.chalk, 0.22, this.planning);
        this._do(m, { type: "call", fn: () => this._dim(at(w * 0.5, d * 0.5), Math.hypot(w, d), "diag") });
        quick(m, at(w, 0), at(0, d), COL.chalk, 0.22, this.planning);
        this._do(m, { type: "note", t: 1.2 }, { type: "say", text: "Diagonals agree - it's square.", t: 1.6, team: true });
      },
      // Measure each setback in from the boundary and write it down.
      setbacks: (m) => {
        say(m, pick(["Measuring the setbacks.", "How far in can we build?", "Offsets from the boundary."]));
        const marks = [[env.x0 / 2, d / 2, env.x0, [0, d / 2], [env.x0, d / 2]], [(w + env.x1) / 2, d / 2, w - env.x1, [w, d / 2], [env.x1, d / 2]],
          [w / 2, env.y0 / 2, env.y0, [w / 2, 0], [w / 2, env.y0]], [w / 2, (d + env.y1) / 2, d - env.y1, [w / 2, d], [w / 2, env.y1]]];
        for (const [x, y, len, a0, a1] of marks.sort(() => Math.random() - 0.5)) {
          if (len < 0.3) continue;
          quick(m, at(...a0), at(...a1), COL.gold, 0.6, this.planning);
          this._do(m, { type: "note", t: 0.5 }, { type: "call", fn: () => this._dim(at(x, y), len) });
        }
      },
      // Set up the level at a corner and read the staff across the plot.
      levels: (m) => {
        say(m, pick(["Taking levels.", "Reading the staff.", "Which way does it drain?"]));
        for (let i = 0; i < 3; i++) {
          const p = at(rnd(1, w - 1), rnd(1, d - 1));
          this._do(m, { type: "run", to: p }, { type: "note", t: rnd(1.0, 1.6) },
            { type: "call", fn: () => { this._stake(p); this._dim(p, null, `+${(Math.random() * 0.3).toFixed(2)}`); } });
        }
      },
      // Tape the frontage and a side: stakes every few metres, no lines.
      measure: (m) => {
        say(m, pick(["Checking the frontage.", "Let's confirm the dimensions.", "Measuring the setbacks."]));
        const step = pick([2.5, 3, 3.5]);
        const front = r === "S" ? 0 : d;
        for (let x = 0; x <= w + 0.01; x += step) {
          const p = at(x, front);
          this._do(m, { type: "run", to: p, slow: true }, { type: "note", t: 0.5 }, { type: "call", fn: () => this._stake(p) });
        }
      },
      // The setback envelope, starting from a random corner.
      envelope: (m) => {
        say(m, pick(["Marking the setbacks.", "This is what we can build on.", "Envelope first."]));
        const c = [[env.x0, env.y0], [env.x1, env.y0], [env.x1, env.y1], [env.x0, env.y1]];
        const s0 = Math.floor(Math.random() * 4), dir = Math.random() < 0.5 ? 1 : 3;
        for (let k = 0; k < 4; k++) {
          const a = c[(s0 + k * dir) % 4], b = c[(s0 + (k + 1) * dir) % 4];
          quick(m, at(...a), at(...b), COL.gold, 0.5);
        }
      },
      // A structural grid: column lines at a bay that suits the plot.
      grid: (m) => {
        say(m, pick(["Columns on a 4 m grid?", "Let's set out the bays.", "Grid lines for the frame."]));
        const bay = pick([3.6, 4.0, 4.5]);
        for (let x = env.x0; x <= env.x1 + 0.01; x += bay) quick(m, at(x, env.y0), at(x, env.y1), COL.chalk, 0.35, this.planning);
      },
      // Stand at the road and look back at the plot: the view from the gate.
      gate: (m) => {
        const g = at(w / 2 + rnd(-2, 2), r === "S" ? -1.2 : d + 1.2);
        this._do(m, { type: "run", to: g }, { type: "face", to: at(w / 2, d / 2) }, { type: "point", t: 1.4 });
        say(m, pick(["The approach matters.", "First thing a guest sees.", "The gate should frame the door."]));
      },
    };
    // The order a survey team works in: the boundary is pegged and checked
    // first, then the setbacks and the envelope; levels, the grid and the
    // view from the gate follow. Jobs are dealt so all three are busy.
    const first = ["corners", "diagonal"].sort(() => Math.random() - 0.5);
    const then = ["setbacks", "envelope", "measure"].sort(() => Math.random() - 0.5);
    const last = ["levels", "grid", "gate", "survey"].sort(() => Math.random() - 0.5);
    const jobs = [[first[0], then[0], last[0]], [then[1], first[1], last[1]], [then[2], last[2], last[3]]];
    [p1, p2, p3].forEach((m, i) => {
      this._do(m, { type: "wait", t: rnd(0, 1.0) });
      jobs[i].forEach((j) => plays[j](m));
    });
    this.construction = [];
    this.planningActive = true;
  }

  // Where each of the team stands in the huddle, and the middle of it.
  _huddle(m) {
    const { w } = this.plot;
    const c = this.P(0, w / 2, 1.8);
    const i = this.team.indexOf(m);
    const a = Math.PI / 2 + (i * TAU) / 3;
    return { at: c.clone().add(new THREE.Vector3(Math.cos(a) * 0.95, 0, Math.sin(a) * 0.95)), centre: c };
  }

  // Fraction of depth from the road (0) to the rear (1), as a plan y.
  _depth(f) {
    const { d, road } = this.plot;
    return road === "S" ? f * d : d - f * d;
  }

  _line(pts, color, opacity, parent = this.root) {
    const line = lineOf(resample(pts), color, opacity);
    parent.add(line);
    return line;
  }

  // A dimension written on the ground: a length in metres, or a note.
  _dim(at, len, text = null) {
    const t = text ?? (len >= 10 ? `${len.toFixed(1)} m` : `${len.toFixed(2)} m`);
    const l = this._label(t, at, "st-label--zone st-label--dim");
    this._show(l);
  }

  _stake(at) {
    const post = new THREE.Mesh(cyl(0.035, 0.035, 0.5, 8), mat(0xe9ecf1));
    post.position.set(at.x, 0.25, at.z);
    post.castShadow = true;
    const top = new THREE.Mesh(new THREE.ConeGeometry(0.07, 0.12, 10), mat(0xe8792f, 0.5));
    top.position.set(at.x, 0.56, at.z);
    const g = new THREE.Group();
    g.add(post, top);
    g.scale.setScalar(0.01);
    this.root.add(g);
    this._tween(400, (k) => g.scale.setScalar(Math.max(0.01, ease(k))));
  }

  /* ── the schemes ──────────────────────────────────────────────────── */

  // Build a scheme's geometry (hidden) so it can be drawn on demand.
  addScheme(sk) {
    if (this.schemes[sk.id]) return this.schemes[sk.id];
    const group = new THREE.Group();
    group.visible = false;
    this.root.add(group);
    const rooms = [];
    const walls = [];
    sk.levels.forEach((lv, li) => {
      if (li >= this.plot.n) return;
      for (const room of lv.rooms) {
        const pts = room.poly.map((p) => this.P(li, p[0], p[1]));
        const line = lineOf(resample(pts, 0.08, true), COL.line, 0.9, 0.03);
        const fill = shapeFill(pts, COL[tintOf(room.type)], 0);
        group.add(fill, line);
        const c = pts.reduce((a, p) => a.add(p), new THREE.Vector3()).multiplyScalar(1 / pts.length);
        const lab = this._label(`${room.name}`, c, "st-label--room");
        lab.scheme = sk.id;
        rooms.push({ room, li, pts, line, fill, lab, centre: c, zone: zoneOf(room.type), drawn: false });
      }
      for (const w of lv.walls) walls.push(...this._wallPieces(group, li, w));
    });
    const s = { sk, group, rooms, walls, drawn: false, risen: false };
    this.schemes[sk.id] = s;
    return s;
  }

  // A wall as boxes between its openings; glazing as a pane in the gap.
  _wallPieces(group, li, w) {
    const a = this.P(li, w.a[0], w.a[1]), b = this.P(li, w.b[0], w.b[1]);
    const len = a.distanceTo(b);
    if (len < 0.05) return [];
    const dir = b.clone().sub(a).normalize();
    const cuts = w.open.map((o) => [clamp(o.p * len - o.w / 2, 0, len), clamp(o.p * len + o.w / 2, 0, len), o.k])
      .sort((x, y) => x[0] - y[0]);
    const spans = [];
    let at = 0;
    for (const [s0, s1] of cuts) { if (s0 > at) spans.push([at, s0]); at = Math.max(at, s1); }
    if (at < len) spans.push([at, len]);
    const t = Math.max(0.1, w.t);
    const wm = mat(w.ext ? COL.wall : 0xd6dae2, 0.85);
    const out = [];
    const angle = Math.atan2(dir.x, dir.z);
    for (const [s0, s1] of spans) {
      if (s1 - s0 < 0.02) continue;
      const piece = new THREE.Mesh(new THREE.BoxGeometry(t, WALL_H, s1 - s0 + t * 0.5), wm);
      const mid = a.clone().addScaledVector(dir, (s0 + s1) / 2);
      piece.position.set(mid.x, WALL_H / 2, mid.z);
      piece.rotation.y = angle;
      piece.castShadow = true; piece.receiveShadow = true;
      piece.scale.y = 0.001; piece.visible = false;
      piece.userData.seg = [a.clone().addScaledVector(dir, s0), a.clone().addScaledVector(dir, s1)];
      group.add(piece);
      out.push(piece);
    }
    for (const [s0, s1, k] of cuts) {
      if (k.includes("door")) continue;
      const pane = new THREE.Mesh(new THREE.BoxGeometry(0.03, WALL_H * 0.55, s1 - s0),
        new THREE.MeshStandardMaterial({ color: COL.glass, transparent: true, opacity: 0.45, roughness: 0.1 }));
      const mid = a.clone().addScaledVector(dir, (s0 + s1) / 2);
      pane.position.set(mid.x, WALL_H * 0.55, mid.z);
      pane.rotation.y = angle;
      pane.scale.y = 0.001; pane.visible = false;
      pane.userData.seg = [a.clone().addScaledVector(dir, s0), a.clone().addScaledVector(dir, s1)];
      group.add(pane);
      out.push(pane);
    }
    return out;
  }

  // Draw a scheme: the planning sketch steps aside, each member takes
  // their zone, and the outlines are walked out one by one.
  draw(id, { fast = false } = {}) {
    const s = this.schemes[id];
    if (!s) return Promise.resolve();
    this.planningActive = false;
    for (const other of Object.values(this.schemes)) {
      if (other !== s && other.group.visible) {
        other.group.visible = false;
        other.rooms.forEach((r) => this._show(r.lab, false));
      }
    }
    this.planning.children.forEach((c) => c.material && this._fade(c.material, c.material.opacity * 0.25, 700));
    this.labels.filter((l) => l.el.classList.contains("st-label--zone")).forEach((l) => this._show(l, false));
    s.group.visible = true;
    this.current = s;

    if (s.drawn) return Promise.resolve();
    if (this.static) {
      s.rooms.forEach((r) => this._complete(r, true));
      this._rise(s, true);
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      s.resolve = resolve;
      const queues = { public: [], service: [], private: [] };
      // Front to back on each plate, plate by plate.
      [...s.rooms].sort((a, b) => a.li - b.li || a.centre.z - b.centre.z).forEach((r) => queues[r.zone].push(r));
      const owner = { public: "arch1", service: "eng", private: "arch2" };
      const hands = Object.entries(queues).map(([z, q]) => ({ who: this._member(owner[z]), q }));
      for (const h of hands) {
        if (!h.q.length) {
          const busiest = hands.reduce((a, b) => (b.q.length > a.q.length ? b : a));
          if (busiest.q.length > 1) h.q.push(...busiest.q.splice(Math.ceil(busiest.q.length / 2)));
        }
      }
      for (const h of hands) {
        this._clear(h.who);
        for (const r of h.q) {
          const pts = resample(r.pts, 0.08, true);
          h.who.tasks.push({ type: "run", to: this._standAt(h.who, pts[0], pts[Math.min(3, pts.length - 1)]) },
            { type: "draw", pts, line: r.line, room: r, fast });
        }
      }
      s.pending = s.rooms.length;
    });
  }

  _complete(r, instant = false) {
    if (r.drawn) return;
    r.drawn = true;
    r.line.geometry.setDrawRange(0, r.line.userData.count);
    if (instant) r.fill.material.opacity = 0.16;
    else this._fade(r.fill.material, 0.16, 500);
    this._show(r.lab);
    const s = this.current;
    if (!instant && s && s.rooms.includes(r)) this._build(s, r);
    if (s && s.rooms.includes(r) && s.rooms.every((x) => x.drawn) && !s.drawn) {
      s.drawn = true;
      this._rise(s, instant);
    }
  }

  // A room is built the moment its outline closes: its walls and glazing
  // go up one after another around it, so the house is constructed room by
  // room behind the people drawing it rather than appearing at the end.
  _build(s, r) {
    const near = (seg) => {
      const m = seg[0].clone().lerp(seg[1], 0.5);
      let best = Infinity;
      for (let i = 0; i < r.pts.length; i++) {
        const a = r.pts[i], b = r.pts[(i + 1) % r.pts.length];
        const ab = b.clone().sub(a), t = clamp(m.clone().sub(a).dot(ab) / Math.max(ab.lengthSq(), 1e-9), 0, 1);
        best = Math.min(best, a.clone().addScaledVector(ab, t).distanceTo(m));
      }
      return best < 0.35;
    };
    const mine = s.walls.filter((w) => !w.userData.up && w.userData.seg && near(w.userData.seg));
    mine.sort((x, y) => Math.atan2(x.position.z - r.centre.z, x.position.x - r.centre.x)
      - Math.atan2(y.position.z - r.centre.z, y.position.x - r.centre.x));
    mine.forEach((w, i) => {
      w.userData.up = true;
      setTimeout(() => {
        w.visible = true;
        this._tween(900, (t) => { w.scale.y = Math.max(0.001, ease(t)); });
      }, (i * 160) / this.speed);
    });
  }

  // Whatever is still standing open goes up in a wave from the road, then
  // the team steps back.
  _rise(s, instant = false) {
    if (s.risen) return;
    s.risen = true;
    const front = this.P(0, this.plot.w / 2, this.plot.road === "S" ? 0 : this.plot.d);
    const order = s.walls.filter((m) => !m.userData.up || instant)
      .map((m) => ({ m, k: m.position.distanceTo(front) })).sort((a, b) => a.k - b.k);
    const span = order.length ? order[order.length - 1].k || 1 : 1;
    for (const { m, k } of order) {
      m.visible = true;
      if (instant) { m.scale.y = 1; continue; }
      setTimeout(() => this._tween(520, (t) => { m.scale.y = Math.max(0.001, ease(t)); }), (k / span) * 900 / this.speed);
    }
    const done = () => {
      s.resolve?.();
      // The shell is up: now the fit-out. The team stands back when it is done.
      if (this.settling) { this._finishFit(s); this._standBack(); } else this._fitOut(s, instant);
    };
    if (instant) done(); else setTimeout(done, 1100 / this.speed);
  }

  _standBack() {
    if (this.settling) {
      // The hand-off: stop where you are and look up.
      this.team.forEach((t) => { this._clear(t); t.tasks = [{ type: "face", to: this.camera.position.clone().setY(0) }]; });
      return;
    }
    const { w, d, n } = this.plot;
    const spots = [this.P(0, -1.6, d * 0.35), this.P(0, -1.6, d * 0.7), this.P(n - 1, w + 1.6, d * 0.5)];
    this.team.forEach((t, i) => {
      if (t.consulting) return;
      this._clear(t);
      t.tasks = [{ type: "run", to: spots[i] }, { type: "face", to: this.view.target }];
    });
  }

  /* ── fit-out: paint, furniture and the garden ─────────────────────── */

  // Once the walls are up the team fits the house out room by room: each
  // walks to a room, points, and its floor is laid in a sweep, its walls take
  // their paint and its furniture is set down piece by piece. The garden
  // grows in around the ground floor while they work.
  _fitOut(s, instant = false) {
    if (s.fitting) return;
    s.fitting = true;
    this.renderer.localClippingEnabled = true;
    s.fit = new THREE.Group();
    s.group.add(s.fit);
    const rooms = [...s.rooms].sort((a, b) => a.li - b.li || a.centre.z - b.centre.z || a.centre.x - b.centre.x);
    if (instant || this.static) {
      this._landscape(s, true);
      rooms.forEach((r) => this._fit(s, r, true));
      this._standBack();
      return;
    }
    this._landscape(s, false);
    s.unfitted = rooms.length;
    const team = this.team.filter((m) => !m.consulting);
    rooms.forEach((r, i) => {
      const m = team[i % Math.max(1, team.length)];
      if (!m) { this._fit(s, r); return; }
      const off = new THREE.Vector3(Math.sin(i * 2.1) * 0.5, 0, Math.cos(i * 2.1) * 0.5);
      m.tasks.push(
        { type: "run", to: r.centre.clone().add(off).setY(0) },
        { type: "face", to: r.centre.clone() },
        { type: "point", t: 0.7 },
        { type: "call", fn: () => this._fit(s, r) },
      );
      // The member who walks there pays the room a visit; the room does not wait for them.
      setTimeout(() => this._fit(s, r), (2600 + i * 650) / this.speed);
    });
  }

  // Whatever is left, quickly: the result is in and the board must settle.
  _finishFit(s) {
    if (!s) return;
    if (!s.fitting) { this._fitOut(s, true); return; }
    this.team.forEach((m) => { m.tasks = m.tasks.filter((t) => t.type !== "call" && t.type !== "point"); });
    s.rooms.filter((r) => !r.fitted).forEach((r, i) => setTimeout(() => this._fit(s, r), i * 60));
    // Whatever is still growing or being lowered in finishes now.
    setTimeout(() => this._settleGarden(s), s.rooms.length * 60 + 900);
  }

  _settleGarden(s) {
    const gd = s.garden;
    if (gd) {
      gd.lawn.forEach((m) => { m.scale[m.userData.axis] = 1; });
      gd.plants.forEach((p) => { p.scale.setScalar(p.userData.size); p.rotation.z = 0; });
      if (gd.drive) gd.drive.material.opacity = 0.85;
    }
    (s.pieces || []).forEach(({ mesh, rest }) => { mesh.visible = true; mesh.position.y = rest; mesh.scale.setScalar(1); });
  }

  _fit(s, r, instant = false) {
    if (r.fitted) return;
    r.fitted = true;
    this._paintRoom(s, r, instant);
    this._furnish(s, r, instant);
    if (!instant && --s.unfitted <= 0) setTimeout(() => this._standBack(), 900 / this.speed);
  }

  // The floor is laid in a sweep across the room; the walls around it take
  // their paint.
  _paintRoom(s, r, instant) {
    const t = r.room.type;
    const floor = FLOOR_OF(t);
    const xs = r.pts.map((p) => p.x), zs = r.pts.map((p) => p.z);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const plane = new THREE.Plane(new THREE.Vector3(-1, 0, 0), instant ? x1 + 1 : x0);
    const shape = new THREE.Shape(r.pts.map((p) => new THREE.Vector2(p.x, -p.z)));
    const m = new THREE.MeshStandardMaterial({ color: floor, roughness: 0.75, clippingPlanes: [plane] });
    const mesh = new THREE.Mesh(new THREE.ShapeGeometry(shape), m);
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.y = 0.016;
    mesh.receiveShadow = true;
    s.fit.add(mesh);
    r.fill.visible = false;
    if (!instant) this._tween(700, (k) => { plane.constant = lerp(x0, x1 + 0.05, ease(k)); });
    // Wall paint: every leaf that bounds this room.
    const paint = new THREE.Color(PAINT_OF(t));
    const near = (seg) => {
      const mid = seg[0].clone().lerp(seg[1], 0.5);
      for (let i = 0; i < r.pts.length; i++) {
        const a = r.pts[i], b = r.pts[(i + 1) % r.pts.length];
        const ab = b.clone().sub(a), k = clamp(mid.clone().sub(a).dot(ab) / Math.max(ab.lengthSq(), 1e-9), 0, 1);
        if (a.clone().addScaledVector(ab, k).distanceTo(mid) < 0.35) return true;
      }
      return false;
    };
    for (const w of s.walls) {
      if (!w.userData.seg || w.material.transparent || !near(w.userData.seg)) continue;
      if (!w.userData.own) { w.material = w.material.clone(); w.userData.own = true; }
      const from = w.material.color.clone();
      const to = from.clone().lerp(paint, 0.55);
      if (instant) w.material.color.copy(to);
      else this._tween(800, (k) => { w.material.color.copy(from).lerp(to, ease(k)); });
    }
  }

  // Furniture: each piece is lowered in and lands with a small settle.
  _furnish(s, r, instant) {
    const xs = r.pts.map((p) => p.x), zs = r.pts.map((p) => p.z);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cz = (Math.min(...zs) + Math.max(...zs)) / 2;
    const wx = Math.max(...xs) - Math.min(...xs), wz = Math.max(...zs) - Math.min(...zs);
    const alongX = wx >= wz;
    const L = alongX ? wx : wz, S = alongX ? wz : wx;
    const parts = FURNISH(r.room.type, L, S);
    const g = new THREE.Group();
    s.fit.add(g);
    parts.forEach((p, i) => {
      const [u, v, y, su, sv, sy, color, kind] = p;
      let geom;
      if (kind === "ball") geom = ball(su / 2);
      else if (kind === "cyl") geom = cyl(su / 2, su / 2, sy, 14);
      else if (kind === "cone") geom = cyl(0.001, su / 2, sy, 12);
      else geom = box(alongX ? su : sv, sy, alongX ? sv : su);
      const material = kind === "glow" ? GLOW : mat(color, kind === "gloss" ? 0.25 : 0.75);
      const mesh = new THREE.Mesh(geom, material);
      const x = cx + (alongX ? u : v), z = cz + (alongX ? v : u);
      const rest = y + (kind === "ball" ? su / 2 : sy / 2);
      mesh.position.set(x, rest, z);
      mesh.castShadow = kind !== "glow" && sy > 0.05;
      mesh.receiveShadow = true;
      g.add(mesh);
      if (instant) return;
      (s.pieces ||= []).push({ mesh, rest });
      mesh.visible = false;
      setTimeout(() => {
        mesh.visible = true;
        mesh.position.y = rest + 2.2;
        mesh.scale.setScalar(0.6);
        this._tween(520, (k) => {
          mesh.position.y = rest + 2.2 * (1 - bounce(k));
          mesh.scale.setScalar(lerp(0.6, 1, ease(Math.min(1, k * 1.6))));
        }, () => { if (i === 0) this._puff(new THREE.Vector3(x, 0.02, z)); });
      }, (380 + i * 85) / this.speed);
    });
  }

  // A ring of dust where the first piece lands.
  _puff(at) {
    const m = new THREE.MeshBasicMaterial({ color: 0xede6dc, transparent: true, opacity: 0.5, depthWrite: false });
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.2, 0.28, 28), m);
    ring.rotation.x = -Math.PI / 2;
    ring.position.copy(at);
    this.root.add(ring);
    this._tween(600, (k) => { ring.scale.setScalar(1 + k * 3); m.opacity = 0.5 * (1 - k); }, () => { this.root.remove(ring); ring.geometry.dispose(); m.dispose(); });
  }

  // The garden on the ground plate: lawn in the setbacks, a drive from the
  // road, shrubs along the house and trees along the boundary, all growing in.
  _landscape(s, instant) {
    const { w, d, road } = this.plot;
    const ground = s.rooms.filter((r) => r.li === 0);
    if (!ground.length) return;
    const xs = ground.flatMap((r) => r.pts.map((p) => p.x)), zs = ground.flatMap((r) => r.pts.map((p) => p.z));
    const fx0 = Math.min(...xs) - 0.12, fx1 = Math.max(...xs) + 0.12, fz0 = Math.min(...zs) - 0.12, fz1 = Math.max(...zs) + 0.12;
    const A = this.P(0, 0, 0), B = this.P(0, w, d);
    const px0 = Math.min(A.x, B.x), px1 = Math.max(A.x, B.x), pz0 = Math.min(A.z, B.z), pz1 = Math.max(A.z, B.z);
    const g = new THREE.Group();
    s.fit.add(g);
    const lawn = new THREE.MeshStandardMaterial({ color: 0x5e6c47, roughness: 1, transparent: true, opacity: 0.62, depthWrite: false });
    // Each setback strip, anchored on its house edge so it can spread outward.
    const strips = [
      [px0, px1, pz0, fz0, "z", fz0], [px0, px1, fz1, pz1, "z", fz1],
      [px0, fx0, fz0, fz1, "x", fx0], [fx1, px1, fz0, fz1, "x", fx1],
    ];
    const lawnMeshes = [];
    for (const [a, b, c, e, axis, edge] of strips) {
      if (b - a < 0.2 || e - c < 0.2) continue;
      const geo = new THREE.PlaneGeometry(b - a, e - c);
      geo.rotateX(-Math.PI / 2);
      const pivot = new THREE.Group();
      if (axis === "z") { pivot.position.set((a + b) / 2, 0.006, edge); geo.translate(0, 0, (c + e) / 2 - edge); }
      else { pivot.position.set(edge, 0.006, (c + e) / 2); geo.translate((a + b) / 2 - edge, 0, 0); }
      const m = new THREE.Mesh(geo, lawn);
      m.receiveShadow = true;
      pivot.add(m);
      pivot.userData.axis = axis;
      if (!instant) pivot.scale[axis] = 0.001;
      g.add(pivot); lawnMeshes.push(pivot);
    }
    // The drive: from the road edge to the house, on the road's side.
    const r0 = road || "N";
    const roadPt = r0 === "S" ? new THREE.Vector3((fx0 + fx1) / 2, 0, pz1) : r0 === "E" ? new THREE.Vector3(px1, 0, (fz0 + fz1) / 2)
      : r0 === "W" ? new THREE.Vector3(px0, 0, (fz0 + fz1) / 2) : new THREE.Vector3((fx0 + fx1) / 2, 0, pz0);
    const houseEdge = r0 === "S" ? fz1 : r0 === "E" ? fx1 : r0 === "W" ? fx0 : fz0;
    const vertical = r0 === "N" || r0 === "S";
    const dlen = Math.abs((vertical ? roadPt.z : roadPt.x) - houseEdge);
    if (dlen > 0.4) {
      const drive = new THREE.Mesh(new THREE.PlaneGeometry(vertical ? 2.6 : dlen, vertical ? dlen : 2.6), mat(0x77726a, 0.95).clone());
      drive.material.transparent = true; drive.material.opacity = instant ? 0.85 : 0;
      drive.rotation.x = -Math.PI / 2;
      drive.position.set(vertical ? roadPt.x : (roadPt.x + houseEdge) / 2, 0.009, vertical ? (roadPt.z + houseEdge) / 2 : roadPt.z);
      g.add(drive);
      if (!instant) this._tween(1600, (k) => { drive.material.opacity = 0.85 * ease(k); });
    }
    const inDrive = (x, z) => dlen > 0.4 && (vertical ? Math.abs(x - roadPt.x) < 2 && (z - roadPt.z) * (houseEdge - roadPt.z) >= -0.5
      : Math.abs(z - roadPt.z) < 2 && (x - roadPt.x) * (houseEdge - roadPt.x) >= -0.5);
    const inHouse = (x, z, pad) => x > fx0 - pad && x < fx1 + pad && z > fz0 - pad && z < fz1 + pad;
    const plants = [];
    // A few trees, where a setback is deep enough to hold a crown: the
    // corners first, then the middle of a generous side. Never a hedge row.
    const room = (x, z) => !inHouse(x, z, 0.8) && !inDrive(x, z) && x > px0 + 0.7 && x < px1 - 0.7 && z > pz0 + 0.7 && z < pz1 - 0.7;
    const spots = [[px0 + 1.3, pz0 + 1.3], [px1 - 1.3, pz1 - 1.3], [px1 - 1.3, pz0 + 1.3], [px0 + 1.3, pz1 - 1.3],
      [(px0 + fx0) / 2, (pz0 + pz1) / 2], [(fx1 + px1) / 2, (pz0 + pz1) / 2], [(px0 + px1) / 2, (fz1 + pz1) / 2]]
      .map(([x, z]) => [x + (Math.random() - 0.5) * 0.8, z + (Math.random() - 0.5) * 0.8]).filter(([x, z]) => room(x, z));
    const open = (px1 - px0) * (pz1 - pz0) - (fx1 - fx0) * (fz1 - fz0);
    const nTrees = clamp(Math.round(open / 40), 1, 4);
    const trees = [];
    for (const [x, z] of spots) {
      if (trees.length >= nTrees) break;
      if (trees.some(([a, b]) => Math.hypot(a - x, b - z) < 4)) continue;
      trees.push([x, z]);
      plants.push(this._tree(g, x, z, Math.min(1, 0.5 + Math.min(Math.abs(x - (x < fx0 ? fx0 : fx1)), Math.abs(z - (z < fz0 ? fz0 : fz1))) * 0.18) * (0.85 + Math.random() * 0.2)));
    }
    // Shrubs in small clusters: either side of the entrance and at a corner or two.
    const clusters = [];
    if (dlen > 0.4) {
      const side = vertical ? [[roadPt.x - 1.9, houseEdge + Math.sign(roadPt.z - houseEdge) * 0.5], [roadPt.x + 1.9, houseEdge + Math.sign(roadPt.z - houseEdge) * 0.5]]
        : [[houseEdge + Math.sign(roadPt.x - houseEdge) * 0.5, roadPt.z - 1.9], [houseEdge + Math.sign(roadPt.x - houseEdge) * 0.5, roadPt.z + 1.9]];
      clusters.push(...side);
    }
    clusters.push(pick([[fx0 - 0.5, fz1 + 0.5], [fx1 + 0.5, fz1 + 0.5], [fx0 - 0.5, fz0 - 0.5], [fx1 + 0.5, fz0 - 0.5]]));
    for (const [x, z] of clusters) {
      const n = 2 + Math.floor(Math.random() * 2);
      for (let k = 0; k < n; k++) {
        const sx = x + (Math.random() - 0.5) * 0.7, sz = z + (Math.random() - 0.5) * 0.7;
        if (sx > px0 + 0.2 && sx < px1 - 0.2 && sz > pz0 + 0.2 && sz < pz1 - 0.2 && !inDrive(sx, sz)) plants.push(this._shrub(g, sx, sz));
      }
    }
    s.garden = { lawn: lawnMeshes, plants, drive: g.children.find((c) => c.isMesh && c.material?.color?.getHex?.() === 0x77726a) };
    if (instant) return;
    // The garden grows while the rooms are fitted: grass creeps out from the
    // house on every side at once, saplings appear and fill out.
    const span = Math.min(6000, Math.max(3600, s.rooms.length * 300)) / this.speed;
    lawnMeshes.forEach((m, i) => setTimeout(() => this._tween(span * 0.7, (k) => {
      m.scale[m.userData.axis] = Math.max(0.001, 1 - Math.pow(1 - k, 2.2));
    }), i * 120 / this.speed));
    for (const p of plants) {
      const full = p.userData.size;
      const tree = p.isGroup;
      p.scale.setScalar(0.001);
      setTimeout(() => {
        // A sapling first, then a long, slowing growth to its full size.
        this._tween(tree ? span * 0.75 : span * 0.4, (k) => {
          const grow = 1 - Math.pow(1 - k, 2.6);
          p.scale.setScalar(Math.max(0.001, full * (0.18 + 0.82 * grow)));
          if (tree) p.rotation.z = Math.sin(k * 9) * 0.02 * (1 - k);
        });
      }, (span * (tree ? 0.05 + Math.random() * 0.25 : 0.25 + Math.random() * 0.4)) / 1);
    }
  }

  _tree(g, x, z, size) {
    const t = new THREE.Group();
    const trunk = new THREE.Mesh(cyl(0.07, 0.1, 0.9, 8), mat(0x6b4a2e, 0.9));
    trunk.position.y = 0.45;
    const leaf = mat(pick([0x52653d, 0x5d6f43, 0x4a5c39, 0x66764a]), 0.9);
    const c1 = new THREE.Mesh(ball(0.75), leaf); c1.position.set(0, 1.35, 0);
    const c2 = new THREE.Mesh(ball(0.5), leaf); c2.position.set(0.35, 1.05, 0.2);
    const c3 = new THREE.Mesh(ball(0.45), leaf); c3.position.set(-0.3, 1.1, -0.2);
    for (const m of [trunk, c1, c2, c3]) { m.castShadow = true; t.add(m); }
    t.position.set(x, 0, z);
    t.rotation.y = Math.random() * TAU;
    t.userData.size = size;
    t.scale.setScalar(size);
    g.add(t);
    return t;
  }

  _shrub(g, x, z) {
    const m = new THREE.Mesh(ball(0.26), mat(pick([0x5b6b40, 0x667449, 0x50603a]), 0.95));
    m.position.set(x + (Math.random() - 0.5) * 0.2, 0.2, z + (Math.random() - 0.5) * 0.2);
    m.castShadow = true;
    m.userData.size = 0.8 + Math.random() * 0.5;
    m.scale.setScalar(m.userData.size);
    g.add(m);
    return m;
  }

  /* ── the committee on the board ───────────────────────────────────── */

  _roomFor(text) {
    const s = this.current;
    if (!s || !text) return null;
    const t = text.toLowerCase();
    return [...s.rooms].sort((a, b) => b.room.name.length - a.room.name.length)
      .find((x) => t.includes(x.room.name.toLowerCase())) || null;
  }

  _pulse(r) {
    if (!r || !r.drawn) return;
    this._tween(1400, (k) => { r.fill.material.opacity = 0.16 + Math.sin(k * Math.PI) * 0.22; });
    r.lab.el.classList.add("is-hot");
    setTimeout(() => r.lab.el.classList.remove("is-hot"), 1600);
  }

  highlight(text) { this._pulse(this._roomFor(text)); }

  // One specialist's remark. They queue at the edge of the board and walk
  // on one at a time; when too many are waiting, the sharpest remarks (the
  // lowest scores) keep their place.
  critique({ critic, short, pig, line, score }) {
    const room = this._roomFor(line);
    this._pulse(room);
    if (this.static || !this.plot || !line || this.settling) return;
    this.pending.push({ critic, short, pig, line, score: score ?? 1, room });
    if (this.pending.length > 5) {
      let k = 0;
      this.pending.forEach((p, i) => { if (p.score > this.pending[k].score) k = i; });
      this.pending.splice(k, 1);
    }
  }

  _spawnCritic(now) {
    if (this.settling || !this.plot || !this.pending.length || now < (this.nextCritic || 0)) return;
    const live = this.critics.filter((c) => !c.leaving);
    if (live.length >= 3) this._dismiss(live[0]);
    const p = this.pending.shift();
    // Unhurried, so a reader can follow who said what to whom.
    this.nextCritic = now + 3400 / (this.boost || 1);
    const { w, d, n } = this.plot;
    const lv = p.room ? p.room.li : Math.min(n - 1, this.focusLevel ?? 0);
    const enter = this.P(lv, 1 + Math.random() * (w - 2), d + 3.5 + Math.random() * 1.5);
    const c = this._person(criticLook(p.pig), "critic", enter);
    c.p = p;
    c.exit = enter;
    // Stand at the room's front, a little apart from anyone already there.
    const spot = p.room
      ? p.room.centre.clone().add(new THREE.Vector3((Math.random() - 0.5) * 1.4, 0, 0.9))
      : this.P(lv, 1.5 + Math.random() * (w - 3), 1.5 + Math.random() * (d - 3));
    const toward = p.room?.centre ?? this.P(lv, w / 2, d / 2);
    c.tasks.push(
      { type: "run", to: spot, max: WALK * 1.35 },
      { type: "face", to: toward },
      { type: "note", t: 1.6 },
      { type: "call", fn: () => this._consult(c) },
      { type: "await", fn: () => !c.partner || c.partner.ready, t: 3.5 },
      { type: "face", fig: () => c.partner?.m.fig ?? c.peer?.fig },
      { type: "say", head: p.short, text: brief(p.line), pig: p.pig, t: 3.4 + Math.min(3.6, p.line.length / 32) },
      { type: "give", t: 0.8, fn: () => c.partner && this._paper(c.fig, c.partner.m.fig) },
      { type: "call", fn: () => { c.gave = true; } },
      { type: "wait", t: 0.5 },
      { type: "call", fn: () => this._dismiss(c) },
    );
    this.critics.push(c);
  }

  // Whoever on the team is free and nearest walks over to hear it; if the
  // whole team is drawing, the specialist turns to a colleague instead.
  _consult(c) {
    const free = this.team.filter((m) => !m.consulting && m.task?.type !== "draw" && !m.tasks.some((t) => t.type === "draw"));
    if (!free.length) {
      const others = this.critics.filter((x) => x !== c && !x.leaving);
      c.peer = others.sort((a, b) => a.fig.position.distanceTo(c.fig.position) - b.fig.position.distanceTo(c.fig.position))[0] || null;
      return;
    }
    const m = free.sort((a, b) => a.fig.position.distanceTo(c.fig.position) - b.fig.position.distanceTo(c.fig.position))[0];
    const away = m.fig.position.clone().sub(c.fig.position);
    away.y = 0;
    if (away.lengthSq() < 0.01) away.set(1, 0, 0);
    const to = c.fig.position.clone().addScaledVector(away.normalize(), 1.3);
    const partner = { m, ready: false };
    c.partner = partner;
    this._clear(m);
    m.consulting = true;
    m.tasks = [
      { type: "run", to },
      { type: "face", fig: () => c.fig },
      { type: "call", fn: () => { partner.ready = true; } },
      { type: "listen", fig: () => c.fig, until: () => c.gave || c.leaving, t: 9 },
      { type: "say", text: pick(ACKS), t: 1.3, team: true },
      { type: "call", fn: () => { m.consulting = false; } },
    ];
    if (c.p.room) {
      const r = c.p.room;
      m.tasks.push({ type: "run", to: r.centre.clone().add(new THREE.Vector3(0.5, 0, 0.5)), slow: true },
        { type: "face", to: r.centre }, { type: "point", t: 1.0 });
    }
  }

  _dismiss(c) {
    if (c.leaving) return;
    c.leaving = true;
    c.gave = true;
    if (c.bubble) { this._drop(c.bubble); c.bubble = null; }
    c.tasks = [{ type: "run", to: c.exit, max: this.settling ? RUN * 2 : WALK * 1.2 }, { type: "call", fn: () => this._remove(c) }];
    c.task = null;
  }

  _remove(c) {
    this.scene.remove(c.fig);
    if (c.bubble) this._drop(c.bubble);
    this.critics = this.critics.filter((x) => x !== c);
  }

  // A sheet of notes passed from one hand to another.
  _paper(from, to) {
    const sheet = new THREE.Mesh(geo("paper", () => new THREE.PlaneGeometry(0.21, 0.29)), PAPER);
    sheet.castShadow = true;
    const a = new THREE.Vector3(), b = new THREE.Vector3();
    from.updateMatrixWorld(true);
    from.userData.j.handR.getWorldPosition(a);
    this.scene.add(sheet);
    this._tween(700, (k) => {
      to.updateMatrixWorld(true);
      to.userData.j.handL.getWorldPosition(b);
      sheet.position.lerpVectors(a, b, ease(k));
      sheet.position.y += Math.sin(k * Math.PI) * 0.4;
      sheet.rotation.set(-Math.PI / 2 + Math.sin(k * Math.PI) * 0.9, k * 3, 0);
    }, () => {
      const hand = to.userData.j.handL;
      this.scene.remove(sheet);
      sheet.scale.setScalar(1 / H);
      sheet.position.set(0, -0.04, 0.04);
      sheet.rotation.set(-0.4, 0, 0);
      hand.add(sheet);
      setTimeout(() => hand.remove(sheet), 2600);
    });
  }

  // After the result: no more racing the engine's clock - a human pace.
  calm() { this.deadline = 0; this.boost = 1; }

  // Fast-forward: everything at several times speed until it is done.
  hurry() { this.boost = 4; this.pending = this.pending.slice(-2); }

  // Nothing left to draw, fit out or say.
  idle() {
    const s = this.current;
    const busy = this.team.some((m) => m.task || m.tasks.length > 0 && m.tasks.some((t) => t.type !== "face"));
    return !!s && s.drawn && (!s.fitting || (s.unfitted ?? 0) <= 0) && !this.pending.length && !this.critics.length && !busy;
  }

  // The result is in: the team fast-forwards through what is left at a pace
  // you can still follow, every line and wall still drawn and built, the specialists
  // leave, the walls go up and the camera settles to plan view. Resolves
  // when the board is still.
  async settle() {
    this.settling = true;
    this.speed = 2.5;
    this.view.rate = 4;
    this.pending = [];
    for (const c of this.critics.slice()) {
      if (c.bubble) this._drop(c.bubble);
      const f = c.fig;
      this._tween(260, (k) => f.scale.setScalar(H * (this.figS || 1) * (1 - ease(k)) + 0.001), () => this._remove(c), { real: true });
    }
    const s = this.current;
    if (s && !s.drawn && !this.static) {
      for (const m of this.team) {
        m.tasks = m.tasks.filter((t) => t.type === "draw" || t.type === "run");
      }
      // Fast-forward, not skip: set the speed from what is left to draw, so
      // the busiest hand finishes in about two and a half seconds, every line drawn
      // and every wall raised on screen.
      this.speed = clamp(this._left() / (PACE * 2.5), 2, 14);
      const until = performance.now() + 6000;   // a safety net, not the plan
      while (!s.drawn && performance.now() < until) await sleep(50);
    }
    if (s && !s.drawn) s.rooms.forEach((x) => this._complete(x, true));
    if (s) this._rise(s, this.static);
    if (s && s.risen) this._finishFit(s);
    await new Promise((resolve) => {
      if (this.static) { this.view.tilt = 0; resolve(); return; }
      const from = this.view.tilt;
      this._tween(950, (k) => { this.view.tilt = lerp(from, 0, ease(k)); }, resolve, { real: true });
    });
    this.critics.slice().forEach((c) => this._remove(c));
    this.team.forEach((t) => { if (t.task?.type === "run") this._clear(t); });
    this._placeCamera(performance.now());
    this._frame(0, true);
  }

  /* ── animation plumbing ──────────────────────────────────────────── */

  _fade(material, to, ms) {
    const from = material.opacity;
    this._tween(ms, (k) => { material.opacity = lerp(from, to, ease(k)); });
  }

  _tween(ms, fn, done, { real = false } = {}) {
    (this.tweens ||= []).push({ t: 0, ms: Math.max(1, ms), fn, done, real });
  }

  // Stop drawing frames while the stage is off screen.
  pause() { cancelAnimationFrame(this.raf); this.raf = 0; }
  resume() { if (!this.raf) { this.last = 0; this.raf = requestAnimationFrame(this._tick); } }

  _tick(now) {
    this.raf = requestAnimationFrame(this._tick);
    const dt = clamp((now - (this.last || now)) / 1000, 0, 0.12);
    this.last = now;
    const step = dt * this.speed;

    if (this.tweens?.length) {
      for (const tw of this.tweens) {
        tw.t += dt * 1000 * (tw.real ? 1 : Math.max(1, this.speed * 0.6));
        tw.fn(clamp(tw.t / tw.ms, 0, 1));
      }
      const done = this.tweens.filter((tw) => tw.t >= tw.ms);
      this.tweens = this.tweens.filter((tw) => tw.t < tw.ms);
      done.forEach((tw) => tw.done?.());
    }

    if (!this.static) {
      this._spawnCritic(now);
      for (const m of this.team) this._member_tick(m, step, dt, now);
      // The specialists keep a human pace even when the drafting fast-forwards.
      const calm = dt * Math.min(this.speed, 1.2) * (this.boost || 1);
      for (const c of this.critics.slice()) this._member_tick(c, calm, dt, now);
    }

    this._keepPace(now);
    this._updateFocus(dt);
    this._placeCamera(now);
    this._frame(dt);
    this.renderer.render(this.scene, this.camera);
    this._labelsTick();
  }

  _member_tick(m, step, dt, now) {
    const fig = m.fig;
    if (!m.task) {
      m.task = m.tasks.shift() || null;
      if (!m.task && m.kind !== "critic" && this.planningActive && this.plot) {
        // No invented lines and no aimless pacing: the team confers.
        const h = this._huddle(m);
        const roll = Math.random();
        if (roll < 0.22) {
          // Wander off to check something on the plot.
          const { w, d } = this.plot;
          m.tasks.push({ type: "run", to: this.P(0, Math.random() * w, Math.random() * d), slow: true }, { type: pick(["note", "point", "wait"]), t: 1 + Math.random() * 1.5 });
        } else if (roll < 0.32) {
          m.tasks.push({ type: "say", text: pick(IDLE), t: 1.8, team: true });
        } else if (fig.position.distanceTo(h.at) > 0.35 * (this.figS || 1)) {
          m.tasks.push({ type: "run", to: h.at }, { type: "face", to: h.centre });
        } else if (m.kind === "arch1") {
          m.tasks.push(pick([{ type: "talk", t: 2.4 }, { type: "point", t: 1.4 }, { type: "talk", t: 1.8 }]));
        } else {
          m.tasks.push({ type: "face", to: this._member("arch1").fig.position.clone() }, { type: "listen", t: 1.6 + Math.random() * 1.6 });
        }
        m.task = m.tasks.shift();
      }
    }

    m.pose = "idle";
    const t = m.task;
    if (t?.type !== "run") m.vel = Math.max(0, m.vel - ACCEL * 2 * step);
    if (t) {
      switch (t.type) {
        case "run": {
          const v = t.to.clone().sub(fig.position);
          v.y = 0;
          const dist = v.length();
          t.max ??= (t.slow ? 1.1 : dist > 7 * (this.figS || 1) ? RUN : WALK) * (this.figS || 1);
          // Ease in and out: never faster than lets you stop on the mark.
          const want = Math.min(t.max, Math.sqrt(2 * ACCEL * Math.max(0, dist - 0.02)) + 0.25);
          m.vel += clamp(want - m.vel, -ACCEL * step, ACCEL * step);
          if (dist > 0.02) m.face = Math.atan2(v.x, v.z);
          // Turn first when the mark is behind you, then stride off.
          const turn = Math.abs(angDiff(m.face, fig.rotation.y));
          const go = m.vel * step * clamp(1.25 - turn * 0.9, 0.12, 1);
          if (dist <= go || dist < 0.03) {
            m.moved += dist;
            fig.position.set(t.to.x, 0, t.to.z);
            m.task = null;
          } else {
            fig.position.addScaledVector(v.normalize(), go);
            m.moved += go;
          }
          m.pose = "walk";
          break;
        }
        case "draw": {
          // The pen point walks the line; the person follows beside it.
          t.i ??= 0;
          t.acc ??= 0;
          t.acc += ((t.fast ? PACE * 3 : t.quick ? PACE * 2.2 : PACE) * step) / 0.08;
          const before = t.i;
          while (t.acc >= 1 && t.i < t.pts.length - 1) { t.i++; t.acc -= 1; }
          const p = t.pts[t.i];
          if (t.i > before) {
            const q = t.pts[Math.max(0, t.i - 1)];
            m.face = Math.atan2(p.x - q.x, p.z - q.z);
          }
          const ry = fig.rotation.y;
          const want = new THREE.Vector3(
            p.x - Math.sin(ry) * m.reach.f + Math.cos(ry) * m.reach.r, 0,
            p.z - Math.cos(ry) * m.reach.f - Math.sin(ry) * m.reach.r);
          const from = fig.position.clone();
          fig.position.lerp(want, damp(step, 9));
          m.moved += from.distanceTo(fig.position);
          t.line.geometry.setDrawRange(0, t.i + 1);
          m.pose = "draw";
          if (t.i >= t.pts.length - 1) {
            if (t.room) this._complete(t.room);
            m.task = null;
          }
          break;
        }
        case "face": {
          const to = t.fig ? t.fig()?.position : t.to;
          if (to) {
            const v = to.clone().sub(fig.position);
            if (v.lengthSq() > 1e-4) m.face = Math.atan2(v.x, v.z);
          }
          t.left = (t.left ?? 0.6) - step;
          if (t.left <= 0 || Math.abs(angDiff(m.face, fig.rotation.y)) < 0.1) m.task = null;
          break;
        }
        case "say": {
          if (!t.bub) t.bub = m.bubble = this._bubble(fig, t.head, t.text, t.team ? "st-bubble--team" : "", t.pig);
          t.left = (t.left ?? t.t) - step;
          m.pose = "talk";
          if (t.left <= 0) { this._drop(t.bub); m.bubble = null; m.task = null; }
          break;
        }
        case "listen": {
          const to = t.fig?.()?.position;
          if (to) { const v = to.clone().sub(fig.position); if (v.lengthSq() > 1e-4) m.face = Math.atan2(v.x, v.z); }
          t.left = (t.left ?? t.t) - step;
          m.pose = "listen";
          if (t.left <= 0 || t.until?.()) m.task = null;
          break;
        }
        case "give": {
          if (!t.started) { t.started = true; t.fn?.(); }
          t.left = (t.left ?? t.t) - step;
          m.pose = "give";
          if (t.left <= 0) m.task = null;
          break;
        }
        case "await": {
          t.left = (t.left ?? t.t) - step;
          m.pose = m.p ? "note" : "idle";
          if (t.fn() || t.left <= 0) m.task = null;
          break;
        }
        case "note":
        case "point":
        case "talk":
        case "wait": {
          t.left = (t.left ?? t.t) - step;
          m.pose = t.type === "wait" ? "idle" : t.type;
          if (t.left <= 0) m.task = null;
          break;
        }
        case "call": {
          m.task = null;
          t.fn();
          break;
        }
        default: m.task = null;
      }
    }
    this._animate(m, dt, step);
    this._pen(m);
  }

  // Pose and gait. A pose sets where the joints rest; the walk cycle rides
  // on top of it, its phase advanced by the distance actually covered, so
  // the feet never skate. Knees fold in the swing, the body rises over the
  // planted foot and rocks a little side to side, arms counter-swing, and
  // the big head bobs a beat behind.
  _animate(m, dt, step) {
    const fig = m.fig, u = fig.userData, J = u.j;
    fig.rotation.y += angDiff(m.face, fig.rotation.y) * Math.min(1, step * 9);

    const moved = m.moved;
    m.moved = 0;
    const v = step > 0 ? moved / step : 0;
    u.speed += (v - u.speed) * damp(step, 10);
    // Gait in the figure's own size: a big figure on a big plot takes long
    // strides, so its legs keep time with the ground it covers.
    const fs = this.figS || 1;
    const loco = clamp(u.speed / (0.45 * fs), 0, 1);
    const runW = clamp((u.speed / fs - 2.1) / 0.9, 0, 1);
    u.phase += (moved / (lerp(0.95, 1.6, runW) * fs)) * TAU;
    u.clock += dt;
    const c = u.clock;

    const T = { hy: 0, sx: 0.015 + Math.sin(c * 1.7) * 0.012, hx: -0.14, hz: 0, th: 0, kn: 0.04, shl: 0.08, shlz: 0.12, ell: -0.2, shr: 0.08, shrz: -0.12, elr: -0.2 };
    switch (m.pose) {
      case "draw":
        if (u.look.tool === "staff") Object.assign(T, { shr: -0.35, elr: -0.05, hx: 0.3, hy: -0.03 });
        else Object.assign(T, { shr: -0.95, elr: -0.45, hx: 0.38, sx: 0.08 });
        break;
      case "point": Object.assign(T, { shr: -1.65, shrz: -0.2, elr: -0.05, hx: -0.08 }); break;
      case "note": Object.assign(T, { hx: 0.42, sx: 0.05, shr: -0.6, shrz: 0.5, elr: -1.35 + Math.sin(c * 12) * 0.08 }); break;
      case "talk": Object.assign(T, {
        hx: -0.1 + Math.sin(c * 4.6) * 0.06, hz: Math.sin(c * 2.1) * 0.06,
        shr: -0.45 + Math.sin(c * 2.4) * 0.2, elr: -1.1 + Math.sin(c * 2.4 + 1) * 0.3, shrz: -0.05,
      }); break;
      case "listen": Object.assign(T, { hx: -0.08 + Math.max(0, Math.sin(c * 2.2)) * 0.12, hz: 0.08 }); break;
      case "give": Object.assign(T, { shr: -1.3, elr: -0.2, hx: 0.12 }); break;
      default: break;
    }
    // The left hand keeps hold of what it carries.
    const carry = u.look.carry;
    if (carry === "clipboard") Object.assign(T, m.pose === "note" ? { shl: -0.45, ell: -1.55, shlz: -0.2 } : { shl: -0.3, ell: -1.45, shlz: -0.15 });
    else if (carry === "ruler") Object.assign(T, { shl: -0.25, ell: -1.15, shlz: 0.05 });
    else if (carry === "tube") Object.assign(T, { shl: 0.05, ell: -0.35, shlz: 0.18 });

    const P = u.pose;
    const k = damp(dt, 9);
    for (const key in T) P[key] = P[key] == null ? T[key] : P[key] + (T[key] - P[key]) * k;

    const p = u.phase, sp = Math.sin(p), cp = Math.cos(p);
    const walk = loco * (1 - runW), run = loco * runW;
    const A = 0.5 * walk + 0.85 * run;
    const K = 0.85 * walk + 1.5 * run;
    const busyR = m.pose !== "idle" && m.pose !== "walk";
    const holdL = !!carry;
    const armA = 0.5 * walk + 0.95 * run;

    J.hips.position.set(0, 0.3 + P.hy - 0.012 * walk * (1 - Math.abs(cp)) + run * (-0.02 + 0.02 * Math.abs(sp)), 0);
    J.hips.rotation.set(0, 0.1 * sp * loco, 0.045 * sp * walk);
    J.spine.rotation.set(P.sx + 0.04 * walk + 0.18 * run, -0.14 * sp * loco, -0.03 * sp * walk);
    J.head.rotation.set(P.hx - 0.02 * walk - 0.12 * run + 0.04 * Math.abs(cp) * loco, 0.1 * sp * loco, P.hz + 0.05 * Math.sin(p - 0.6) * walk);
    J.thighL.rotation.x = P.th - A * sp;
    J.thighR.rotation.x = P.th + A * sp;
    J.kneeL.rotation.x = P.kn + K * Math.pow(Math.max(0, cp), 1.3) + 0.05 * loco;
    J.kneeR.rotation.x = P.kn + K * Math.pow(Math.max(0, -cp), 1.3) + 0.05 * loco;
    J.ankleL.rotation.x = -(J.thighL.rotation.x + J.kneeL.rotation.x) * 0.85;
    J.ankleR.rotation.x = -(J.thighR.rotation.x + J.kneeR.rotation.x) * 0.85;
    J.shL.rotation.set(P.shl + armA * sp * (holdL ? 0.15 : 1), 0, P.shlz);
    J.elL.rotation.x = P.ell - (holdL ? 0 : 0.15 * walk + 1.1 * run);
    J.shR.rotation.set(P.shr - armA * sp * (busyR ? 0.15 : 1), 0, P.shrz);
    J.elR.rotation.x = P.elr - (busyR ? 0 : 0.15 * walk + 1.1 * run);
  }

  // The mark being made, and the stylus beam to it.
  _pen(m) {
    if (!m.dot) return;
    const t = m.task;
    const on = t?.type === "draw";
    m.dot.visible = on;
    if (m.beam) m.beam.visible = on;
    if (!on) return;
    const p = t.pts[t.i ?? 0];
    const color = t.line.material.color;
    m.dot.material.color.copy(color);
    m.dot.position.set(p.x, 0.04, p.z);
    m.dot.scale.setScalar(0.85 + Math.sin(performance.now() / 90) * 0.15);
    if (m.beam) {
      m.beam.material.color.copy(color);
      m.fig.updateMatrixWorld(true);
      const a = m.fig.userData.tip.getWorldPosition(this._v || (this._v = new THREE.Vector3()));
      const pos = m.beam.geometry.attributes.position;
      pos.setXYZ(0, a.x, a.y, a.z);
      pos.setXYZ(1, p.x, 0.04, p.z);
      pos.needsUpdate = true;
    }
  }

  _labelsTick() {
    if (!this.labels.length) return;
    const w = this.host.clientWidth, h = this.host.clientHeight;
    const v = new THREE.Vector3();
    for (const l of this.labels) {
      if (!l.on && !l.follow) continue;
      if (l.follow) l.world.set(l.follow.position.x, l.lift, l.follow.position.z);
      v.copy(l.world).project(this.camera);
      const x = (v.x * 0.5 + 0.5) * w, y = (-v.y * 0.5 + 0.5) * h;
      l.el.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) ${l.anchor || "translate(-50%, -50%)"}`;
    }
  }

  /** The board as an image, rendered now without the people, for the hand-off into the review. */
  snapshot() {
    try {
      const people = [...this.team, ...this.critics];
      const was = people.map((m) => m.fig.visible);
      people.forEach((m) => {
        m.fig.visible = false;
        if (m.dot) m.dot.visible = false;
        if (m.beam) m.beam.visible = false;
      });
      this._placeCamera(performance.now());
      this.renderer.render(this.scene, this.camera);
      const url = this.renderer.domElement.toDataURL("image/png");
      people.forEach((m, i) => { m.fig.visible = was[i]; });
      return url;
    } catch { return null; }
  }

  dispose() {
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    this.renderer.dispose();
    this.host.innerHTML = "";
  }
}
