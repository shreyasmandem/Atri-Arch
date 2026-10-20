/* Exterior thumbnails: the house rendered small, once per design and colour.

   One offscreen renderer is shared by every tile (a browser allows only a few
   WebGL contexts). Requests queue latest-first, so the tiles a viewer has just
   scrolled to or opened render before ones they have moved past, and each
   finished image is cached by its model URL. */

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { studioEnvironment } from "./viewer3d.js?v=p7";
import { dress, skyTexture } from "./materials.js";

const W = 360, H = 270;
const cache = new Map();       // url -> Promise<string | null>
const queue = [];              // { url, front, resolve }
let R = null, scene = null, cam = null, sun = null, running = false;

function setup() {
  R = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  R.setPixelRatio(1.5);
  R.setSize(W, H, false);
  R.outputColorSpace = THREE.SRGBColorSpace;
  R.toneMapping = THREE.ACESFilmicToneMapping;
  R.shadowMap.enabled = true;
  R.shadowMap.type = THREE.PCFSoftShadowMap;
  scene = new THREE.Scene();
  scene.environment = studioEnvironment(R);
  scene.background = skyTexture();
  scene.add(new THREE.HemisphereLight(0xdde6ee, 0x6b5f4f, 0.95));
  sun = new THREE.DirectionalLight(0xfff1dc, 2.3);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.bias = -0.0006;
  const fill = new THREE.DirectionalLight(0xbcd0ff, 0.45);
  fill.position.set(-1, 0.6, -0.8);
  scene.add(sun, sun.target, fill);
  // Open ground past the plot, so the house stands somewhere.
  const ground = new THREE.Mesh(new THREE.CircleGeometry(80, 48), new THREE.MeshStandardMaterial({ color: 0x8f8877, roughness: 1 }));
  ground.rotation.x = -Math.PI / 2; ground.position.y = -0.01; ground.receiveShadow = true;
  scene.add(ground);
  cam = new THREE.PerspectiveCamera(30, W / H, 0.1, 500);
}

async function render(url, front) {
  if (!R) setup();
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
  // The street face, three-quarters on, as the main view opens.
  const span = Math.max(size.x, size.z, size.y * 1.4);
  const dist = span / (2 * Math.tan((cam.fov * Math.PI) / 360)) * 1.18;
  const a = front ? Math.atan2(-front[1], front[0]) + 0.6 : 0.9;
  cam.position.set(Math.cos(a) * dist, dist * 0.42, Math.sin(a) * dist);
  cam.lookAt(0, box.min.y - low + size.y * 0.42, 0);
  const sc = sun.shadow.camera;
  sc.left = -span * 1.4; sc.right = span * 1.4; sc.top = span * 1.4; sc.bottom = -span * 1.4; sc.far = span * 8;
  sc.updateProjectionMatrix();
  sun.position.set(Math.cos(a - 0.5) * span * 1.2, span * 2, Math.sin(a - 0.5) * span * 1.2);
  R.render(scene, cam);
  const blob = await new Promise((ok) => R.domElement.toBlob(ok, "image/webp", 0.86));
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
  scene.remove(m);
  m.traverse((o) => { o.geometry?.dispose(); for (const x of [].concat(o.material || [])) x.dispose?.(); });
  return out;
}

async function pump() {
  if (running) return;
  running = true;
  while (queue.length) {
    const job = queue.pop();               // latest first
    try { job.resolve(await (job.run ? job.run() : render(job.url, job.front))); } catch { job.resolve(job.run ? [] : null); }
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
export function thumb(url, front = null) {
  if (!cache.has(url)) {
    cache.set(url, new Promise((resolve) => { queue.push({ url, front, resolve }); }));
    pump();
  } else {
    // Asked again while still waiting: move it to the front of the line.
    const i = queue.findIndex((j) => j.url === url);
    if (i >= 0) queue.push(queue.splice(i, 1)[0]);
  }
  return cache.get(url);
}
