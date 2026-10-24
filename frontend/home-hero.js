/* ═══════════════════════════════════════════════════════════════════════
   The homepage's live pieces.

   The hero is a real house from the studio - the same presentation model
   the review shows - being built while you watch: the site, then each floor
   rising, then the roof settling on, a slow turn, and then the same plan in
   another of its facades. Below the fold the showcase runs the real airflow
   solve for that house. Nothing here is a video or a mock.
   ═══════════════════════════════════════════════════════════════════════ */

const HOUSES = [
  ["demo/house0.glb", "Haveli · jharokhas · jaali · sandstone"],
  ["demo/house1.glb", "Kerala · colonnade · tiled hip roof"],
  ["demo/house2.glb", "Tropical · louvres · green wall"],
  ["demo/house3.glb", "Contemporary · deep frame · cornices"],
  ["demo/house4.glb", "Nordic · timber gable"],
  ["demo/house5.glb", "Mid-century · breeze block · butterfly roof"],
];
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const ease = (t) => 1 - Math.pow(1 - t, 3);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

function tween(ms, fn) {
  return new Promise((resolve) => {
    const t0 = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - t0) / ms);
      fn(ease(k));
      if (k < 1) requestAnimationFrame(step); else resolve();
    };
    requestAnimationFrame(step);
  });
}

// Raise the house: site, then floor by floor, then the roof.
async function build(viewer) {
  const m = viewer.model;
  const levels = [];
  m.traverse((o) => { const x = /^level_(\d+)$/.exec(o.name); if (x) levels.push([+x[1], o]); });
  levels.sort((a, b) => a[0] - b[0]);
  const roof = m.getObjectByName("roof");
  const site = m.getObjectByName("site");
  const parts = [site, ...levels.map(([, o]) => o)].filter(Boolean);
  for (const o of parts) { o.scale.y = 0.001; o.visible = true; }
  if (roof) { roof.visible = false; roof.position.y = 0; }
  for (const o of parts) {
    await tween(o === site ? 700 : 1100, (k) => { o.scale.y = Math.max(0.001, k); });
  }
  if (roof) {
    roof.visible = true;
    roof.position.y = 3;
    await tween(900, (k) => { roof.position.y = 3 * (1 - k); });
  }
}

export async function mountHero(host, caption) {
  if (!host) return;
  let Viewer3D;
  try { ({ Viewer3D } = await import("./viewer3d.js?v=p9")); } catch { return; }
  const viewer = new Viewer3D(host);
  viewer.controls.autoRotateSpeed = 0.35;
  viewer.controls.enableZoom = false;
  let k = 0;
  const show = async (first) => {
    const [url, label] = HOUSES[k % HOUSES.length];
    try {
      await viewer.load(url, { keepView: !first, front: [0, 1], zoom: 0.95, lift: 0.5 });
    } catch { return false; }
    if (caption) caption.textContent = label;
    if (!reduced()) await build(viewer);
    return true;
  };
  if (!(await show(true))) return;
  if (reduced()) return;
  // Keep building: every few seconds the same plan in its next facade.
  for (;;) {
    await wait(6500);
    if (!document.body.contains(host) || document.body.dataset.phase !== "compose") { await wait(3000); continue; }
    k++;
    await show(false);
  }
}

export async function mountAirShowcase(host) {
  if (!host) return;
  try {
    const [{ AirflowView }, data] = await Promise.all([
      import("./airflow.js"), fetch("demo/air.json").then((r) => r.json()),
    ]);
    const view = new AirflowView(host);
    view.setData(data);
  } catch { /* the tile keeps its caption */ }
}
