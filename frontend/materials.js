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
  // Lawn: patchy, with a fine blade grain.
  lawn: { size: 3.0, fn: () => {
    const n = noise(16, 8), f = noise(17, 120), g = noise(18, 400);
    return (u, v) => 0.5 + (n(u, v) - 0.5) * 0.3 + (f(u, v) - 0.5) * 0.16 + (g(u, v) - 0.5) * 0.14;
  } },
};

// Material name (as the model names it) -> pattern and how strongly it shows.
const RULES = [
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
  return (baked[kind] ||= bake(PATTERNS[kind].fn()));
}

/** Give a model's material its real surface, if it is one we know. Idempotent. */
export function dress(mat) {
  if (!mat || mat.userData.dressed || !mat.isMeshStandardMaterial) return;
  const rule = RULES.find(([re]) => re.test(mat.name || ""));
  mat.userData.dressed = true;
  if (!rule) return;
  const [, kind, k] = rule;
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

/** A small swatch of a finish in a colour, for the customise controls. */
export function swatch(kind, hex, size = 72) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  const k = PATTERNS[kind] ? kind : "plaster";
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
