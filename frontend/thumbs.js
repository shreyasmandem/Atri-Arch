/* Exterior thumbnails: the house rendered small, once per design and colour.

   One offscreen renderer is shared by every tile (a browser allows only a few
   WebGL contexts). Requests queue latest-first, so the tiles a viewer has just
   scrolled to or opened render before ones they have moved past, and each
   finished image is cached by its model URL. */

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { studioEnvironment } from "./viewer3d.js?v=p21";
import { dress, skyTexture } from "./materials.js?v=m5";

const W = 480, H = 360;
// The catalogue's lead design is shot wide, like the photograph on a brochure cover.
const SIZES = { card: [W, H], wide: [880, 400] };
const cache = new Map();       // url|size -> Promise<string | null>
const queue = [];              // { url, front, size, resolve }
let R = null, scene = null, cam = null, sun = null, hemi = null, grade = null, running = false;

function setup() {
  R = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  R.setPixelRatio(1.5);
  R.setSize(W, H, false);
  R.outputColorSpace = THREE.SRGBColorSpace;
  R.toneMapping = THREE.ACESFilmicToneMapping;
  R.toneMappingExposure = 1.0;
  R.shadowMap.enabled = true;
  // Filtered shadows with a wide radius: the soft edge of late sun, not a stencil.
  R.shadowMap.type = THREE.PCFShadowMap;
  scene = new THREE.Scene();
  scene.environment = studioEnvironment(R);
  scene.environmentIntensity = 0.5;
  scene.background = skyTexture();
  scene.fog = new THREE.Fog(0xd9d3c4, 60, 200);
  hemi = new THREE.HemisphereLight(0xcfdbe8, 0x7a6a55, 0.45);
  scene.add(hemi);
  // Late-afternoon sun: low, warm, long shadows that model every ledge.
  sun = new THREE.DirectionalLight(0xffe0b5, 3.3);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.02;
  sun.shadow.radius = 3.5;
  const fill = new THREE.DirectionalLight(0xbcd0ff, 0.45);
  fill.position.set(-1, 0.6, -0.8);
  scene.add(sun, sun.target, fill);
  // Open ground past the plot, so the house stands somewhere.
  const ground = new THREE.Mesh(new THREE.CircleGeometry(80, 48), new THREE.MeshStandardMaterial({ color: 0x968b76, roughness: 1 }));
  ground.rotation.x = -Math.PI / 2; ground.position.y = -0.01; ground.receiveShadow = true;
  scene.add(ground);
  // A longer lens than the viewer's: verticals stay upright, as in architectural photography.
  cam = new THREE.PerspectiveCamera(24, W / H, 0.1, 500);
  grade = document.createElement("canvas");
}

// The print: the render graded warm in the light and cool in the shade, with a
// gentle vignette that holds the eye on the house.
function develop(w, h) {
  grade.width = w; grade.height = h;
  const g = grade.getContext("2d");
  g.drawImage(R.domElement, 0, 0, w, h);
  g.globalCompositeOperation = "soft-light";
  g.fillStyle = "rgba(255, 214, 160, 0.16)";
  g.fillRect(0, 0, w, h);
  g.globalCompositeOperation = "multiply";
  const v = g.createRadialGradient(w * 0.5, h * 0.55, Math.min(w, h) * 0.35, w * 0.5, h * 0.55, Math.hypot(w, h) * 0.62);
  v.addColorStop(0, "rgba(255,255,255,1)");
  v.addColorStop(1, "rgba(150,140,128,1)");
  g.fillStyle = v;
  g.fillRect(0, 0, w, h);
  g.globalCompositeOperation = "source-over";
  return new Promise((ok) => grade.toBlob(ok, "image/webp", 0.88));
}

async function render(url, front, frame = "card") {
  if (!R) setup();
  const [w, h] = SIZES[frame] || SIZES.card;
  R.setSize(w, h, false);
  cam.aspect = w / h;
  cam.updateProjectionMatrix();
  const gltf = await new GLTFLoader().loadAsync(url);
  const m = gltf.scene;
  m.traverse((o) => {
    if (!o.isMesh) return;
    o.castShadow = o.receiveShadow = true;
    for (const x of [].concat(o.material || [])) { dress(x); if (x.transparent) { o.castShadow = false; x.depthWrite = false; } }
  });
  // Frame the house, not the plot: the site's lawn and trees spread wider.
  const house = m.getObjectByName("level_0") ? new THREE.Box3() : null;
  if (house) m.traverse((o) => { if (o.isMesh && !/site/.test(o.name + (o.parent?.name || ""))) house.expandByObject(o); });
  const box = house && !house.isEmpty() ? house : new THREE.Box3().setFromObject(m);
  const size = box.getSize(new THREE.Vector3());
  const c = box.getCenter(new THREE.Vector3());
  // Centred on the house; the lowest thing (the lawn) sits on the ground.
  const low = new THREE.Box3().setFromObject(m).min.y;
  m.position.sub(new THREE.Vector3(c.x, low, c.z));
  scene.add(m);
  // The street face, three-quarters on, from a little above eye level: the
  // house as a passer-by sees it, filling the frame. A wide frame fits the
  // house by its height, a card by its width.
  const a = front ? Math.atan2(-front[1], front[0]) + 0.62 : 0.9;
  // Fit the house's width (seen three-quarters on) and its height, each by its own angle of view.
  const vt = Math.tan((cam.fov * Math.PI) / 360), ht = vt * (w / h);
  const across = Math.abs(size.x * Math.sin(a)) + Math.abs(size.z * Math.cos(a));
  // Perspective swells the near corner, so the frame keeps a margin round the house.
  const dist = Math.max((across * 0.5) / ht, (size.y * 0.62) / vt) * (w / h > 1.6 ? 1.8 : 1.5);
  cam.position.set(Math.cos(a) * dist, size.y * 0.5 + dist * 0.18, Math.sin(a) * dist);
  cam.lookAt(0, box.min.y - low + size.y * 0.42, 0);
  const sc = sun.shadow.camera, reach = Math.max(size.x, size.z) * 1.6;
  sc.left = -reach; sc.right = reach; sc.top = reach; sc.bottom = -reach; sc.far = reach * 8;
  sc.updateProjectionMatrix();
  // Sun low and off to one side: it rakes across the street face, and the
  // house's shadow falls where the camera can see it.
  sun.position.set(Math.cos(a - 1.35) * reach * 1.5, reach * 0.7, Math.sin(a - 1.35) * reach * 1.5);
  // Haze toward the horizon, so the ground melts into the sky.
  scene.fog.near = dist * 1.6; scene.fog.far = dist * 5.5;
  R.render(scene, cam);
  const blob = await develop(w * 1.5, h * 1.5);
  R.setSize(W, H, false);
  scene.remove(m);
  m.traverse((o) => { o.geometry?.dispose(); for (const x of [].concat(o.material || [])) x.dispose?.(); });
  return blob ? URL.createObjectURL(blob) : null;
}

// The four elevations of a house: orthographic, square on to each side,
// the building alone (no plot), under the same sky.
const EW = 420, EH = 300;
async function renderElevations(url) {
  if (!R) setup();
  const gltf = await new GLTFLoader().loadAsync(url);
  const m = gltf.scene;
  m.traverse((o) => {
    if (!o.isMesh) return;
    o.castShadow = o.receiveShadow = true;
    for (const x of [].concat(o.material || [])) { dress(x); if (x.transparent) { o.castShadow = false; x.depthWrite = false; } }
  });
  const site = m.getObjectByName("site");
  if (site) site.visible = false;
  const box = new THREE.Box3().setFromObject(m);
  const size = box.getSize(new THREE.Vector3()), mid = box.getCenter(new THREE.Vector3());
  m.position.set(-mid.x, -box.min.y, -mid.z);
  scene.add(m);
  const span = Math.max(size.x, size.y, size.z);
  const sc = sun.shadow.camera;
  Object.assign(sc, { left: -span, right: span, top: span, bottom: -span, far: span * 10 });
  sc.updateProjectionMatrix();
  R.setSize(EW, EH, false);
  const fog = scene.fog; scene.fog = null;
  const out = [];
  const ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 500);
  for (const side of ["N", "E", "S", "W"]) {
    const wide = side === "N" || side === "S" ? size.x : size.z;
    let hw = wide / 2 * 1.15, hh = size.y / 2 * 1.15;
    if (hw / hh > EW / EH) hh = hw * EH / EW; else hw = hh * EW / EH;
    Object.assign(ortho, { left: -hw, right: hw, top: hh, bottom: -hh });
    const far = Math.max(size.x, size.z) * 3;
    const dir = { N: [0, 0, -1], S: [0, 0, 1], E: [1, 0, 0], W: [-1, 0, 0] }[side];
    ortho.position.set(dir[0] * far, size.y / 2, dir[2] * far);
    ortho.far = far * 3;
    ortho.lookAt(0, size.y / 2, 0);
    ortho.updateProjectionMatrix();
    sun.position.set(dir[0] * far + far * 0.4, far * 1.2, dir[2] * far + far * 0.4);
    R.render(scene, ortho);
    const blob = await new Promise((ok) => R.domElement.toBlob(ok, "image/webp", 0.88));
    out.push(blob ? URL.createObjectURL(blob) : null);
  }
  R.setSize(W, H, false);
  scene.fog = fog;
  scene.remove(m);
  m.traverse((o) => { o.geometry?.dispose(); for (const x of [].concat(o.material || [])) x.dispose?.(); });
  return out;
}

async function pump() {
  if (running) return;
  running = true;
  while (queue.length) {
    const job = queue.pop();               // latest first
    try { job.resolve(await (job.run ? job.run() : render(job.url, job.front, job.size))); } catch { job.resolve(job.run ? [] : null); }
  }
  running = false;
}

const elevCache = new Map();
/** Image URLs of the house's North, East, South and West elevations. */
export function elevations(url) {
  if (!elevCache.has(url)) {
    elevCache.set(url, new Promise((resolve) => { queue.push({ url: `elev:${url}`, run: () => renderElevations(url), resolve }); }));
    pump();
  }
  return elevCache.get(url);
}

/** A rendered image URL for this model, or null if it could not be drawn. */
export function thumb(url, front = null, size = "card") {
  const key = `${url}|${size}`;
  if (!cache.has(key)) {
    cache.set(key, new Promise((resolve) => { queue.push({ url, front, size, key, resolve }); }));
    pump();
  } else {
    // Asked again while still waiting: move it to the front of the line.
    const i = queue.findIndex((j) => j.key === key);
    if (i >= 0) queue.push(queue.splice(i, 1)[0]);
  }
  return cache.get(key);
}
