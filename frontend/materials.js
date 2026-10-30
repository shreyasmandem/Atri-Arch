/* Real surfaces for the exterior: brick courses, stone ashlar, timber
   boards, board-marked concrete, clay tile, standing-seam metal, paving,
   lawn and lime plaster.

   The model's meshes carry no texture coordinates, so each finish is drawn
   once into a small tileable canvas (in metres) and laid on by world
   position, projected from the three axes and blended by the face's normal.
   The texture only modulates brightness, so every colour the client picks
   still reads true: a sage brick is sage, with mortar joints. */

import * as THREE from "three";

const PX = 512;

// Value noise, tileable over the canvas.
function noise(seed, cells) {
  const r = (i, j) => {
    const x = Math.sin(((i % cells) + cells) % cells * 127.1 + (((j % cells) + cells) % cells) * 311.7 + seed * 74.7) * 43758.5453;
    return x - Math.floor(x);
  };
  const s = (t) => t * t * (3 - 2 * t);
  return (u, v) => {
    const x = u * cells, y = v * cells, i = Math.floor(x), j = Math.floor(y), fx = s(x - i), fy = s(y - j);
    const a = r(i, j), b = r(i + 1, j), c = r(i, j + 1), d = r(i + 1, j + 1);
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
  };
}

function bake(fn) {
  const c = document.createElement("canvas");
  c.width = c.height = PX;
  const g = c.getContext("2d");
  const img = g.createImageData(PX, PX);
  for (let y = 0; y < PX; y++) {
    for (let x = 0; x < PX; x++) {
      const v = Math.max(0, Math.min(1, fn(x / PX, y / PX))) * 255;
      const k = (y * PX + x) * 4;
      img.data[k] = img.data[k + 1] = img.data[k + 2] = v;
      img.data[k + 3] = 255;
    }
  }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.NoColorSpace;
  t.anisotropy = 8;
  t.generateMipmaps = true;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  return t;
}

// A stable random number per tile of a pattern.
const hash = (a, b) => { const x = Math.sin(a * 91.3 + b * 47.9) * 15731.743; return x - Math.floor(x); };

// Each pattern covers one canvas; `size` is how many metres that canvas spans.
const PATTERNS = {
  // Running-bond brick: 12 courses and four bricks to a metre, pale mortar.
  brick: { size: 1.0, fn: () => {
    const n = noise(1, 64), m = noise(2, 8);
    return (u, v) => {
      const row = Math.floor(v * 12), fv = v * 12 - row;
      const off = row % 2 ? 0.5 : 0;
      const col = Math.floor(u * 4 + off), fu = u * 4 + off - col;
      const joint = fv < 0.11 || fu < 0.035;
      if (joint) return 0.76 + n(u, v) * 0.06;
      return 0.38 + hash(row, col) * 0.18 + (n(u, v) - 0.5) * 0.12 + (m(u, v) - 0.5) * 0.06;
    };
  } },
  // Coursed ashlar: rows of different heights, blocks of different lengths.
  stone: { size: 1.6, fn: () => {
    const n = noise(3, 48), f = noise(4, 160);
    const rows = [0, 0.18, 0.42, 0.56, 0.8, 1];
    return (u, v) => {
      let r = 0; while (v >= rows[r + 1]) r++;
      const fv = (v - rows[r]) / (rows[r + 1] - rows[r]);
      const len = 0.22 + hash(r, 7) * 0.18, x = u / len + hash(r, 3) * 3, c = Math.floor(x), fu = x - c;
      if (fv < 0.05 || fv > 0.97 || fu < 0.018) return 0.3;
      return 0.42 + hash(r, c) * 0.2 + (n(u, v) - 0.5) * 0.14 + (f(u, v) - 0.5) * 0.1;
    };
  } },
  // Horizontal boards with shadow gaps and a running grain.
  timber: { size: 1.0, fn: () => {
    const n = noise(5, 24), g = noise(6, 200);
    return (u, v) => {
      const row = Math.floor(v * 8), fv = v * 8 - row;
      if (fv < 0.05) return 0.18;
      const grain = Math.sin((u * 40 + n(u * 0.3, v) * 6 + hash(row, 1) * 9) * Math.PI) * 0.05;
      return 0.44 + hash(row, 2) * 0.14 + grain + (g(u, v * 0.2) - 0.5) * 0.12;
    };
  } },
  // Board-marked concrete: faint plank lines, tie holes, a mottled cure.
  concrete: { size: 1.2, fn: () => {
    const n = noise(7, 12), f = noise(8, 180), g = noise(9, 300);
    return (u, v) => {
      const row = v * 6, fv = row - Math.floor(row);
      const line = fv < 0.02 ? -0.08 : 0;
      const hx = u * 2 - Math.floor(u * 2) - 0.5, hy = v * 2 - Math.floor(v * 2) - 0.5;
      const hole = hx * hx + hy * hy < 0.0009 ? -0.22 : 0;
      return 0.5 + (n(u, v) - 0.5) * 0.18 + (f(u, v) - 0.5) * 0.08 + (g(u, v * 0.15) - 0.5) * 0.06 + line + hole;
    };
  } },
  // Lime plaster: soft blotches and a fine trowel grain, nothing more.
  plaster: { size: 2.0, fn: () => {
    const n = noise(10, 6), f = noise(11, 90), g = noise(12, 260);
    return (u, v) => 0.5 + (n(u, v) - 0.5) * 0.16 + (f(u, v) - 0.5) * 0.07 + (g(u, v) - 0.5) * 0.05;
  } },
  // Clay tile: overlapping courses, each darker at its lower lip.
  tile: { size: 1.0, fn: () => {
    const n = noise(13, 40);
    return (u, v) => {
      const row = Math.floor(v * 4), fv = v * 4 - row;
      const off = row % 2 ? 0.5 : 0, x = u * 5 + off, c = Math.floor(x), fu = x - c;
      const lip = fv > 0.9 ? 0.2 : 0.62 - fv * 0.24;
      const ridge = Math.sin(fu * Math.PI) * 0.1;
      return lip + ridge + hash(row, c) * 0.08 + (n(u, v) - 0.5) * 0.08;
    };
  } },
  // Standing-seam metal: a bright seam and its shadow every half metre.
  seam: { size: 1.0, fn: () => {
    const n = noise(14, 30);
    return (u, v) => {
      const fu = u * 2 - Math.floor(u * 2);
      const s = fu < 0.012 ? 0.85 : fu < 0.035 ? 0.3 : 0.5 + (fu - 0.5) * 0.04;
      return s + (n(u, v) - 0.5) * 0.05;
    };
  } },
  // Square pavers with sand joints.
  paving: { size: 1.2, fn: () => {
    const n = noise(15, 60);
    return (u, v) => {
      const x = u * 3, y = v * 3, fu = x - Math.floor(x), fv = y - Math.floor(y);
      if (fu < 0.03 || fv < 0.03) return 0.3;
      return 0.44 + hash(Math.floor(x), Math.floor(y)) * 0.16 + (n(u, v) - 0.5) * 0.12;
    };
  } },
  // Gravel: a dense speckle of stones over a darker bed.
  gravel: { size: 0.8, fn: () => {
    const n = noise(19, 160), f = noise(20, 60), g = noise(21, 8);
    return (u, v) => { const k = n(u, v); return (k > 0.55 ? 0.62 : 0.36) + (f(u, v) - 0.5) * 0.18 + (g(u, v) - 0.5) * 0.1; };
  } },
  // Grass pavers: a concrete grid with turf showing through each cell.
  grass: { size: 1.2, fn: () => {
    const n = noise(22, 120);
    return (u, v) => {
      const x = u * 6, y = v * 6, fu = x - Math.floor(x), fv = y - Math.floor(y);
      return fu < 0.22 || fv < 0.22 ? 0.82 : 0.38 + (n(u, v) - 0.5) * 0.3;
    };
  } },
  // Solar panels: cells in a grid behind bright busbars.
  solar: { size: 1.0, fn: () => {
    const n = noise(23, 40);
    return (u, v) => {
      const x = u * 6, y = v * 10, fu = x - Math.floor(x), fv = y - Math.floor(y);
      if (fu < 0.04 || fv < 0.05) return 0.85;
      return 0.45 + (n(u, v) - 0.5) * 0.06 + (Math.abs(fu - 0.5) < 0.01 ? 0.15 : 0);
    };
  } },
  // Terracotta cladding tiles: slim fired tiles, half-bond, hairline joints.
  tiles: { size: 1.0, fn: () => {
    const n = noise(24, 90);
    return (u, v) => {
      const row = Math.floor(v * 13), fv = v * 13 - row;
      const off = row % 2 ? 0.5 : 0, x = u * 4 + off, c = Math.floor(x), fu = x - c;
      if (fv < 0.07 || fu < 0.02) return 0.3;
      return 0.4 + hash(row, c) * 0.22 + (n(u, v) - 0.5) * 0.08;
    };
  } },
  // ACP: large aluminium panels on a grid of dark shadow joints, a soft sheen.
  acpanel: { size: 2.4, fn: () => (u, v) => {
    const x = u * 2, y = v * 4, fu = x - Math.floor(x), fv = y - Math.floor(y);
    if (fu < 0.008 || fv < 0.016) return 0.16;
    return 0.47 + (fv - 0.5) * 0.06 + hash(Math.floor(x), Math.floor(y)) * 0.04;
  } },
  // Stacked slate: thin strips of random length, deep shadows between them.
  slate: { size: 1.0, fn: () => {
    const n = noise(25, 70);
    return (u, v) => {
      const row = Math.floor(v * 18), fv = v * 18 - row;
      const len = 0.12 + hash(row, 2) * 0.22, x = u / len + hash(row, 5) * 7, c = Math.floor(x), fu = x - c;
      if (fv < 0.14 || fu < 0.025) return 0.12;
      return 0.36 + hash(row, c) * 0.3 + (n(u, v) - 0.5) * 0.1;
    };
  } },
  // A glass curtain wall: the sky's gradient in each pane, faint reflections, and the mullion grid between.
  curtain: { size: 1.25, fn: () => {
    const n = noise(21, 6);
    return (u, v) => {
      const fu = u % 1, fv = (v * 0.4) % 1;
      if (fu < 0.035 || fu > 0.965) return 0.22;
      return 0.62 + (1 - fv) * 0.28 + (n(u, v) - 0.5) * 0.12 + (((u + v) * 3) % 1 < 0.08 ? 0.12 : 0);
    };
  } },
  // Weathering steel: rust mottled over large plates, streaked where rain runs down.
  corten: { size: 2.0, fn: () => {
    const n = noise(31, 6), f = noise(32, 48), r = noise(33, 160);
    return (u, v) => {
      const seam = (u * 2) % 1 < 0.012 || (v * 1.2) % 1 < 0.012 ? -0.18 : 0;
      return 0.52 + (n(u, v) - 0.5) * 0.36 + (f(u, v * 0.2) - 0.5) * 0.18 + (r(u, v) - 0.5) * 0.1 + seam;
    };
  } },
  // Athangudi: hand-made Chettinad cement tiles, a four-petal flower in each square.
  athangudi: { size: 1.2, fn: () => {
    const n = noise(34, 90);
    return (u, v) => {
      const x = u * 6, y = v * 6, fu = x - Math.floor(x) - 0.5, fv = y - Math.floor(y) - 0.5;
      if (Math.abs(fu) > 0.48 || Math.abs(fv) > 0.48) return 0.3;
      const r = Math.hypot(fu, fv), a = Math.atan2(fv, fu);
      const petal = r < 0.18 + 0.14 * Math.abs(Math.cos(2 * a)) ? 0.75 : 0.45;
      const ring = Math.abs(r - 0.4) < 0.025 ? 0.7 : 0;
      return Math.max(petal, ring) + (n(u, v) - 0.5) * 0.06;
    };
  } },
  // A woven ikat-style chevron for rugs and cushions.
  weave: { size: 0.6, fn: () => {
    const n = noise(35, 200);
    return (u, v) => {
      const zig = Math.abs(((u * 6) % 1) - 0.5);
      const band = (v * 8 + zig * 1.2) % 1;
      const thread = Math.sin(u * 400) * 0.03 + Math.sin(v * 400) * 0.03;
      return (band < 0.5 ? 0.66 : 0.38) + thread + (n(u, v) - 0.5) * 0.12;
    };
  } },
  // Herringbone parquet: short oak blocks laid in a zigzag.
  herringbone: { size: 1.2, fn: () => {
    const n = noise(36, 120);
    return (u, v) => {
      const x = u * 8, y = v * 8, band = Math.floor(x), fx = x - band;
      const shift = band % 2 ? fx : 1 - fx, row = y + shift, k = Math.floor(row * 2), f = row * 2 - k;
      if (f < 0.04 || fx < 0.03) return 0.25;
      return 0.45 + hash(band, k) * 0.2 + Math.sin((fx + y) * 60) * 0.03 + (n(u, v) - 0.5) * 0.1;
    };
  } },
  // Moroccan cement tiles: a quatrefoil in each square.
  moroccan: { size: 0.8, fn: () => (u, v) => {
    const x = u * 4, y = v * 4, fu = x - Math.floor(x) - 0.5, fv = y - Math.floor(y) - 0.5;
    if (Math.abs(fu) > 0.48 || Math.abs(fv) > 0.48) return 0.3;
    const r = Math.min(Math.hypot(fu - 0.25, fv), Math.hypot(fu + 0.25, fv), Math.hypot(fu, fv - 0.25), Math.hypot(fu, fv + 0.25));
    return r < 0.22 ? 0.78 : 0.4 + (Math.abs(fu) + Math.abs(fv) < 0.18 ? 0.25 : 0);
  } },
  // Fluted timber: half-round slats 6 cm apart, a little grain down each.
  flutes: { size: 0.6, fn: () => {
    const g = noise(37, 300);
    return (u) => { const f = (u * 10) % 1; return 0.25 + Math.sin(f * Math.PI) * 0.45 + (g(u, 0.3) - 0.5) * 0.08; };
  } },
  // Acoustic panels: felt slats on black, grooves every 3 cm.
  acoustic: { size: 0.6, fn: () => {
    const n = noise(38, 220);
    return (u, v) => ((u * 20) % 1 < 0.35 ? 0.12 : 0.55 + (n(u, v) - 0.5) * 0.12);
  } },
  // A botanical Pichwai wallpaper: lotus leaves and stems in a repeat.
  pichwai: { size: 0.9, fn: () => (u, v) => {
    let d = 9;
    for (const [cx, cy, r] of [[0.25, 0.3, 0.16], [0.72, 0.68, 0.14], [0.7, 0.18, 0.09], [0.2, 0.8, 0.1]]) {
      const dx = ((u - cx + 1.5) % 1) - 0.5, dy = ((v - cy + 1.5) % 1) - 0.5;
      d = Math.min(d, Math.hypot(dx, dy * 1.4) / r);
    }
    const stem = Math.abs(((u * 3 + v * 0.6) % 1) - 0.5) < 0.012;
    return d < 1 ? (d < 0.12 ? 0.3 : 0.75) : stem ? 0.65 : 0.3;
  } },
  // Checkerboard marble: 60 cm squares, alternate ones darker, a faint vein.
  checker: { size: 1.2, fn: () => {
    const n = noise(39, 40);
    return (u, v) => {
      const x = Math.floor(u * 2), y = Math.floor(v * 2), f = (u * 2) % 1, g = (v * 2) % 1;
      if (f < 0.006 || g < 0.006) return 0.3;
      return ((x + y) % 2 ? 0.28 : 0.72) + (n(u, v) - 0.5) * 0.08;
    };
  } },
  // Chevron oak: planks meeting at a point down each row.
  chevron: { size: 1.0, fn: () => {
    const n = noise(40, 150);
    return (u, v) => {
      const col = Math.floor(u * 6), fx = u * 6 - col, y = v * 10 + Math.abs(fx - 0.5) * 2.4, k = Math.floor(y), f = y - k;
      if (f < 0.05 || Math.abs(fx - 0.5) < 0.012) return 0.25;
      return 0.45 + hash(col, k) * 0.2 + (n(u, v) - 0.5) * 0.1;
    };
  } },
  // Hexagon cement tiles.
  hexagon: { size: 0.8, fn: () => (u, v) => {
    const s3 = Math.sqrt(3), x = u * 6, y = v * 6 * s3 / 2 * 1.155;
    const r = Math.round(y / (s3 / 2)), q = Math.round(x - (r % 2) * 0.5);
    const dx = x - (q + (r % 2) * 0.5), dy = (y - r * s3 / 2) / (s3 / 2) * 0.5;
    const d = Math.max(Math.abs(dx) * 1.0, Math.abs(dx) * 0.5 + Math.abs(dy) * 0.866 * 2);
    return d > 0.47 ? 0.3 : 0.55 + hash(q, r) * 0.15;
  } },
  // Glass mosaic: 2 cm chips, each its own shade.
  mosaic: { size: 0.4, fn: () => (u, v) => {
    const x = u * 20, y = v * 20, fx = x % 1, fy = y % 1;
    return fx < 0.1 || fy < 0.1 ? 0.75 : 0.3 + hash(Math.floor(x), Math.floor(y)) * 0.5;
  } },
  // Real surfaces, photographed (Poly Haven, CC0), kept as brightness only so the chosen colour stays true.
  oak: { size: 2.0, url: "assets/tex/oak_planks.jpg" },
  slabs: { size: 2.0, url: "assets/tex/stone_slabs.jpg" },
  terrazzo: { size: 2.4, url: "assets/tex/terrazzo.jpg" },
  granite: { size: 2.0, url: "assets/tex/granite.jpg" },
  squares: { size: 3.0, url: "assets/tex/square_tiles.jpg" },
  oxide: { size: 3.0, url: "assets/tex/oxide.jpg" },
  sandstone: { size: 2.4, url: "assets/tex/sandstone.jpg" },
  pavers: { size: 3.0, url: "assets/tex/pavers.jpg" },
  grain: { size: 1.0, url: "assets/tex/wood_grain.jpg" },
  rosewood: { size: 1.2, url: "assets/tex/rosewood.jpg" },
  linen: { size: 0.35, url: "assets/tex/linen.jpg" },
  velvet: { size: 0.5, url: "assets/tex/velvet.jpg" },
  leather: { size: 0.8, url: "assets/tex/leather.jpg" },
  plasterIn: { size: 3.0, url: "assets/tex/plaster_in.jpg" },
  subway: { size: 1.2, url: "assets/tex/subway.jpg" },
  // Lawn: patchy, with a fine blade grain.
  lawn: { size: 3.0, fn: () => {
    const n = noise(16, 8), f = noise(17, 120), g = noise(18, 400);
    return (u, v) => 0.5 + (n(u, v) - 0.5) * 0.3 + (f(u, v) - 0.5) * 0.16 + (g(u, v) - 0.5) * 0.14;
  } },
};

// Material name (as the model names it) -> pattern and how strongly it shows.
const RULES = [
  // Inside the house: floors, furniture, cloth, walls and tiles.
  [/^floor_(timber|wood)/, "oak", 0.7],
  [/^floor_kota/, "slabs", 0.6],
  [/^floor_marble/, "slabs", 0.3],
  [/^floor_terrazzo/, "terrazzo", 0.8],
  [/^floor_granite/, "granite", 0.5],
  [/^floor_(vitrified|tile_matt|stone)/, "squares", 0.45],
  [/^floor_redoxide/, "oxide", 0.5],
  [/^floor_jaisalmer/, "sandstone", 0.7],
  [/^floor_athangudi/, "athangudi", 0.8],
  [/^floor_statuario/, "slabs", 0.25],
  [/^floor_checker/, "checker", 0.9],
  [/^floor_chevron/, "chevron", 0.8],
  [/^floor_hexagon/, "hexagon", 0.8],
  [/^floor_mosaic/, "mosaic", 0.8],
  [/^floor_walnut/, "oak", 0.75],
  [/^floor_cotto/, "squares", 0.6],
  [/^floor_greykota/, "slabs", 0.6],
  [/^floor_whiteterrazzo/, "terrazzo", 0.6],
  [/^floor_herringbone/, "herringbone", 0.8],
  [/^floor_microcement/, "plasterIn", 0.45],
  [/^floor_moroccan/, "moroccan", 0.85],
  [/^floor_slate/, "squares", 0.6],
  [/^wall_fluted/, "flutes", 0.8],
  [/^wall_acoustic/, "acoustic", 0.85],
  [/^wall_brick/, "brick", 0.95],
  [/^wall_travertine/, "slabs", 0.5],
  [/^wall_pichwai/, "pichwai", 0.85],
  [/^wall_linenpaper/, "linen", 0.6],
  [/^floor_outdoor/, "pavers", 0.6],
  [/^door_timber/, "rosewood", 0.7],
  [/^joinery/, "grain", 0.75],
  [/^(upholstery|linen|curtain_fabric)/, "linen", 0.6],
  [/^accent$|^accent_[0-9a-f]{6}$/, "weave", 0.7],
  [/^(interior_paint|paint_|accent_wall)/, "plasterIn", 0.25],
  [/wall_tile_bath|backsplash/, "subway", 0.8],
  [/counter_stone/, "granite", 0.45],
  [/terracotta_tile/, "tiles", 0.9],
  [/acp_panel/, "acpanel", 0.7],
  [/curtain_glass/, "curtain", 0.55],
  [/corten/, "corten", 0.9],
  [/slate_stack/, "slate", 0.95],
  [/brick/, "brick", 0.95],
  [/stone_cladding|compound_stone|plinth_stone/, "stone", 0.85],
  [/timber_boards|pergola_timber|main_door/, "timber", 0.7],
  [/board_concrete/, "concrete", 0.75],
  [/roof_tile/, "tile", 0.85],
  [/dark_metal|roof_metal/, "seam", 0.6],
  [/paving_concrete/, "concrete", 0.6],
  [/gravel/, "gravel", 0.9],
  [/boulder_stone/, "stone", 0.7],
  [/grass_pavers/, "grass", 0.9],
  [/solar_panel/, "solar", 0.8],
  [/paving/, "paving", 0.75],
  [/lawn/, "lawn", 0.9],
  [/^plaster$|compound_wall|concrete_band|roof_plate|roof_screed|stone_sill/, "plaster", 0.55],
];

const baked = {};
function texture(kind) {
  const p = PATTERNS[kind];
  if (baked[kind]) return baked[kind];
  if (!p.url) return (baked[kind] = bake(p.fn()));
  const t = new THREE.TextureLoader().load(p.url);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.NoColorSpace;
  t.anisotropy = 8;
  return (baked[kind] = t);
}

/** Give a model's material its real surface, if it is one we know. Idempotent. */
export function dress(mat) {
  if (!mat || mat.userData.dressed || !mat.isMeshStandardMaterial) return;
  const rule = RULES.find(([re]) => re.test(mat.name || ""));
  mat.userData.dressed = true;
  if (!rule) return;
  const [, kind, k] = rule;
  mat.userData.tri = { kind, k };
  const tex = texture(kind);
  const scale = 1 / PATTERNS[kind].size;
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.triMap = { value: tex };
    sh.uniforms.triScale = { value: scale };
    sh.uniforms.triK = { value: k };
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vTriP;")
      .replace("#include <fog_vertex>", "#include <fog_vertex>\n  vTriP = (modelMatrix * vec4(transformed, 1.0)).xyz;");
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", "#include <common>\nuniform sampler2D triMap;\nuniform float triScale;\nuniform float triK;\nvarying vec3 vTriP;")
      .replace("#include <map_fragment>", `#include <map_fragment>
  {
    // The face's own normal, from how its world position changes across the
    // pixel: the model is flat-shaded and may carry no normals at all.
    vec3 w = pow(abs(normalize(cross(dFdx(vTriP), dFdy(vTriP)))), vec3(8.0));
    w /= (w.x + w.y + w.z);
    vec3 p = vTriP * triScale;
    float d = texture2D(triMap, vec2(p.z, -p.y)).r * w.x
            + texture2D(triMap, p.xz).r * w.y
            + texture2D(triMap, vec2(p.x, -p.y)).r * w.z;
    diffuseColor.rgb *= mix(1.0, 0.3 + 1.4 * d, triK);
  }`)
      .replace("#include <roughnessmap_fragment>", "#include <roughnessmap_fragment>\n  roughnessFactor = clamp(roughnessFactor + (0.5 - texture2D(triMap, vTriP.xz * triScale).r) * 0.2 * triK, 0.04, 1.0);");
  };
  mat.customProgramCacheKey = () => `tri-${kind}`;
  mat.needsUpdate = true;
}

/** The finish a dressed material wears, for renderers that cannot run the
 * shader above (the photo path tracer): its grey pattern, how many metres
 * one tile spans and how strongly it shows. Null if it has none or the
 * pattern's image has not loaded yet. */
export function finishOf(mat) {
  const t = mat?.userData?.tri;
  if (!t) return null;
  const img = texture(t.kind).image;
  if (!img || (img.complete === false) || !(img.width || img.naturalWidth)) return null;
  return { kind: t.kind, image: img, size: PATTERNS[t.kind].size, k: t.k };
}

/** A swatch for whatever finish a material of this name gets in the model:
 * "floor_herringbone" in its colour, as the viewer will lay it. */
export function swatchFor(materialName, hex, size = 64) {
  const rule = RULES.find(([re]) => re.test(materialName));
  if (rule && (!PATTERNS[rule[1]].url || texture(rule[1]).image?.complete)) return swatch(rule[1], hex, size);
  if (rule && PATTERNS[rule[1]].url) texture(rule[1]);           // start loading for next time
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  g.fillStyle = hex; g.fillRect(0, 0, size, size);
  return c;
}

/** A small swatch of a finish in a colour, for the customise controls. */
export function swatch(kind, hex, size = 72) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  const k = PATTERNS[kind] && (!PATTERNS[kind].url || texture(kind).image?.complete) ? kind : "plaster";
  // Show about a metre of the finish, tinted the way the shader tints it.
  const m = Math.min(PX, PX / PATTERNS[k].size);
  g.drawImage(texture(k).image, 0, 0, m, m, 0, 0, size, size);
  const img = g.getImageData(0, 0, size, size);
  const [r, gg, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  for (let i = 0; i < img.data.length; i += 4) {
    const f = 0.3 + 1.4 * (img.data[i] / 255);
    img.data[i] = Math.min(255, r * f); img.data[i + 1] = Math.min(255, gg * f); img.data[i + 2] = Math.min(255, b * f);
  }
  g.putImageData(img, 0, 0);
  return c;
}

/** A daylight sky for the exterior: a clear zenith fading into a warm haze. */
export function skyTexture() {
  const c = document.createElement("canvas");
  c.width = 4; c.height = 256;
  const g = c.getContext("2d");
  const grad = g.createLinearGradient(0, 0, 0, 256);
  grad.addColorStop(0, "#7f9fb8");
  grad.addColorStop(0.55, "#c4ccc9");
  grad.addColorStop(0.8, "#e4ddcd");
  grad.addColorStop(1, "#d9cfbb");
  g.fillStyle = grad;
  g.fillRect(0, 0, 4, 256);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
