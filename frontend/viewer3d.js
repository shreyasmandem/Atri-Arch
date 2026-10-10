/* ═══════════════════════════════════════════════════════════════════════
   Viewer3D: the scheme's glTF model, in the page.

   The same .glb the studio exports, loaded as is and lit like a massing
   model on a dark table. Drag to orbit, scroll to zoom. It opens at a
   three-quarter view from the road side and turns slowly until touched.
   ═══════════════════════════════════════════════════════════════════════ */

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export class Viewer3D {
  constructor(host) {
    this.host = host;
    const r = (this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false }));
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    r.outputColorSpace = THREE.SRGBColorSpace;
    r.toneMapping = THREE.ACESFilmicToneMapping;
    r.shadowMap.enabled = true;
    r.shadowMap.type = THREE.PCFSoftShadowMap;
    r.setClearColor(0x0b0a09, 1);
    r.domElement.className = "v3-canvas";
    host.append(r.domElement);

    const scene = (this.scene = new THREE.Scene());
    scene.add(new THREE.HemisphereLight(0xf4ead8, 0x221c16, 1.25));
    const sun = (this.sun = new THREE.DirectionalLight(0xfff1dc, 2.1));
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.bias = -0.0005;
    scene.add(sun, sun.target);
    const fill = new THREE.DirectionalLight(0xbcd0ff, 0.45);
    fill.position.set(-1, 0.6, -0.8);
    scene.add(fill);

    this.camera = new THREE.PerspectiveCamera(32, 1, 0.1, 500);
    const c = (this.controls = new OrbitControls(this.camera, r.domElement));
    c.enableDamping = true;
    c.dampingFactor = 0.08;
    c.maxPolarAngle = Math.PI * 0.49;
    c.autoRotate = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    c.autoRotateSpeed = 0.5;
    c.addEventListener("start", () => { c.autoRotate = false; });

    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this.resize();
    this._tick = this._tick.bind(this);
    this.raf = requestAnimationFrame(this._tick);
  }

  resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  async load(url) {
    const gltf = await new GLTFLoader().loadAsync(url);
    if (this.model) this.scene.remove(this.model);
    const m = (this.model = gltf.scene);
    let tris = 0;
    m.traverse((o) => {
      if (!o.isMesh) return;
      o.castShadow = true;
      o.receiveShadow = true;
      const g = o.geometry;
      tris += (g.index ? g.index.count : g.attributes.position.count) / 3;
      for (const mat of [].concat(o.material)) {
        if (mat && "roughness" in mat) mat.roughness = Math.max(mat.roughness ?? 0.8, 0.6);
      }
    });
    this.scene.add(m);

    // Frame it: centre on the footprint, sit it on the table, and light it
    // from over the viewer's shoulder so the faces you see first read.
    const box = new THREE.Box3().setFromObject(m);
    const size = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3());
    m.position.sub(new THREE.Vector3(centre.x, box.min.y, centre.z));
    const span = Math.max(size.x, size.z, size.y * 1.5);

    const ground = new THREE.Mesh(new THREE.CircleGeometry(span * 1.6, 64),
      new THREE.MeshStandardMaterial({ color: 0x141312, roughness: 1 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.002;
    ground.receiveShadow = true;
    if (this.ground) this.scene.remove(this.ground);
    this.ground = ground;
    this.scene.add(ground);

    const sc = this.sun.shadow.camera;
    sc.left = -span; sc.right = span; sc.top = span; sc.bottom = -span; sc.far = span * 6;
    sc.updateProjectionMatrix();
    this.sun.position.set(span * 0.35, span * 1.7, span * 1.25);

    const dist = span / (2 * Math.tan((this.camera.fov * Math.PI) / 360)) * 1.35;
    this.camera.position.set(dist * 0.62, dist * 0.55, dist * 0.78);
    this.controls.target.set(0, size.y * 0.3, 0);
    this.controls.minDistance = span * 0.4;
    this.controls.maxDistance = span * 4;
    this.controls.update();
    return { triangles: Math.round(tris), width: size.x, depth: size.z, height: size.y };
  }

  _tick() {
    this.raf = requestAnimationFrame(this._tick);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
