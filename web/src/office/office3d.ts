// Oficina low-poly (three.js) del prototipo v2.1 de Lucas, sin gamificación: un puesto por agente REAL,
// el tuyo con la baliza de aprobaciones, el rack del modelo local y dos pizarras (misión y worktrees).
// La vista Vue le pasa el estado; esta clase solo dibuja. Las etiquetas son HTML (las pinta Vue) y aquí solo se
// recolocan cada fotograma: el elemento con [data-lbl="<id>"] dentro de `labels`.

import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

export type StationKind = "you" | "director" | "jefe" | "trabajador" | "consultas" | "otro";
export type StationState = "idle" | "working" | "waiting";

export interface StationSpec {
  id: string; // "you" o "a<id del agente>"
  name: string;
  color: string;
  kind: StationKind;
}

export interface BoardStep {
  label: string;
  who: string;
  color: string;
  state: "done" | "active" | "wait" | "todo" | "failed";
}

export interface GitRow {
  name: string;
  status: "clean" | "active" | "ready" | "merged" | "failed";
}

interface Station {
  spec: StationSpec;
  group: THREE.Group;
  ring: THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>;
  gem: THREE.Mesh<THREE.OctahedronGeometry, THREE.MeshStandardMaterial>;
  scr: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>;
  logo: THREE.Mesh<THREE.CircleGeometry, THREE.MeshBasicMaterial>;
  char: { root: THREE.Group; head: THREE.Group; L: THREE.Group; R: THREE.Group };
  state: StationState;
  pos: [number, number];
}

// puestos: tú al fondo, luego una cuadrícula 3×3 (el primero, en el centro de la primera fila)
const YOU_POS: [number, number] = [0, -5];
const SLOTS: [number, number][] = [
  [0, -1.2], [-5.2, -1.2], [5.2, -1.2],
  [0, 2.3], [-5.2, 2.3], [5.2, 2.3],
  [0, 5.6], [-5.2, 5.6], [5.2, 5.6],
];
export const MAX_STATIONS = SLOTS.length;
const RACK_POS = new THREE.Vector3(-8.6, 0, -3.2);

const M = (c: THREE.ColorRepresentation, o: THREE.MeshStandardMaterialParameters = {}) =>
  new THREE.MeshStandardMaterial({ color: c, flatShading: true, roughness: 0.78, metalness: 0, ...o });
const B = (w: number, h: number, d: number) => new THREE.BoxGeometry(w, h, d);
const mix = (a: string, b: string, t: number) => "#" + new THREE.Color(a).lerp(new THREE.Color(b), t).getHexString();

function put<T extends THREE.BufferGeometry>(geo: T, mat: THREE.Material, parent: THREE.Object3D,
  x = 0, y = 0, z = 0, shadow = true): THREE.Mesh<T, THREE.Material> {
  const m = new THREE.Mesh(geo, mat);
  m.position.set(x, y, z);
  m.castShadow = shadow;
  m.receiveShadow = true;
  parent.add(m);
  return m;
}

function rr(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}

const FONT = '"Plus Jakarta Sans Variable","Segoe UI",sans-serif';
const MONO = '"JetBrains Mono",monospace';

export class Office {
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(36, 1, 0.1, 200);
  private renderer: THREE.WebGLRenderer;
  private controls: OrbitControls;
  private clock = new THREE.Clock();
  private stations = new Map<string, Station>();
  private clickable: THREE.Object3D[] = [];
  private links: { line: THREE.Line; mat: THREE.LineDashedMaterial; flash: number; color: string; a: string; b: string }[] = [];
  private packets: { m: THREE.Mesh; s: THREE.Vector3; e: THREE.Vector3; p: number }[] = [];
  private boards: Record<string, { ctx: CanvasRenderingContext2D; tex: THREE.CanvasTexture }> = {};
  private rack: { group?: THREE.Group; fans: THREE.Mesh[]; leds: THREE.Mesh<THREE.BoxGeometry, THREE.MeshBasicMaterial>[][]; lamp?: THREE.MeshStandardMaterial } = { fans: [], leds: [] };
  private beacon: THREE.Mesh<THREE.SphereGeometry, THREE.MeshStandardMaterial> | null = null;
  private beaconLight: THREE.PointLight | null = null;
  private camGoal: THREE.Vector3 | null = null;
  private targetGoal: THREE.Vector3 | null = null;
  private raf = 0;
  private ro: ResizeObserver;
  private gpu: number[] = [];
  private gpuBusy = 0;
  private localState = "off";
  pending = false; // baliza: hay algo esperando tu decisión
  selected: string | null = null;
  private _v = new THREE.Vector3();

  constructor(private host: HTMLElement, private labels: HTMLElement, private onPick: (id: string) => void) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    host.insertBefore(this.renderer.domElement, labels);
    this.camera.position.set(13.5, 11.5, 15);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.06;
    this.controls.minDistance = 4;
    this.controls.maxDistance = 45;
    this.controls.target.set(0, 0.2, 0);
    this.controls.addEventListener("start", () => { this.camGoal = null; this.targetGoal = null; });

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0xc9bda8, 0.62 * Math.PI));
    const sun = new THREE.DirectionalLight(0xfff0d6, 0.9 * Math.PI);
    sun.position.set(9, 16, 10);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { near: 1, far: 50, left: -15, right: 15, top: 15, bottom: -15 });
    sun.shadow.bias = -0.0004;
    this.scene.add(sun);
    const fill = new THREE.DirectionalLight(0xbfd6ff, 0.4 * Math.PI);
    fill.position.set(-9, 6, 6);
    this.scene.add(fill);

    this.buildRoom();
    this.buildRack();
    this.buildBoards();
    this.buildProps();
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this.resize();
    this.setupPicking();
    this.animate();
  }

  dispose(): void {
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    this.controls.dispose();
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh;
      m.geometry?.dispose();
      const mat = m.material as THREE.Material | THREE.Material[] | undefined;
      (Array.isArray(mat) ? mat : mat ? [mat] : []).forEach((x) => {
        (x as THREE.MeshBasicMaterial).map?.dispose();
        x.dispose();
      });
    });
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }

  private resize(): void {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
  }

  // ---------- sala
  private floorTexture(): THREE.CanvasTexture {
    const c = document.createElement("canvas");
    c.width = c.height = 512;
    const g = c.getContext("2d")!;
    for (let i = 0; i < 8; i++) for (let j = 0; j < 8; j++) {
      g.fillStyle = (i + j) % 2 ? "#efe6d6" : "#e8dcc8";
      g.fillRect(i * 64, j * 64, 64, 64);
      g.fillStyle = "rgba(120,95,60,.05)";
      for (let k = 0; k < 4; k++) g.fillRect(i * 64, j * 64 + k * 16, 64, 1);
    }
    g.strokeStyle = "rgba(120,95,60,.14)";
    g.lineWidth = 2;
    for (let i = 0; i <= 8; i++) {
      g.beginPath(); g.moveTo(i * 64, 0); g.lineTo(i * 64, 512); g.stroke();
      g.beginPath(); g.moveTo(0, i * 64); g.lineTo(512, i * 64); g.stroke();
    }
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(2.5, 1.9);
    t.anisotropy = 8;
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }

  private buildRoom(): void {
    const W = 21, D = 15.5, cz = 0.2, s = this.scene;
    put(B(W + 0.6, 0.5, D + 0.6), M(0xcfc9bc), s, 0, -0.28, cz);
    put(B(W - 1, 1.2, D - 1), M(0xa8a294), s, 0, -1.1, cz, false);
    put(B(W - 3, 1, D - 3), M(0x7f796c), s, 0, -2.0, cz, false);
    const fl = put(new THREE.PlaneGeometry(W, D), new THREE.MeshStandardMaterial({ map: this.floorTexture(), color: 0xb3a388, roughness: 0.9 }), s, 0, 0, cz, false);
    fl.rotation.x = -Math.PI / 2;
    const back = cz - D / 2, left = -W / 2;
    put(B(W, 4.4, 0.35), M(0xe0dbd0), s, 0, 2.2, back);
    put(B(0.35, 4.4, D), M(0xd6d1c5), s, left, 2.2, cz);
    put(B(W + 0.2, 0.28, 0.45), M(0xa59f92), s, 0, 0.14, back + 0.15, false);
    put(B(0.45, 0.28, D), M(0xa59f92), s, left + 0.15, 0.14, cz, false);
    put(B(W + 0.4, 0.18, 0.5), M(0xc9c3b6), s, 0, 4.45, back, false);
    put(B(0.5, 0.18, D + 0.1), M(0xc9c3b6), s, left, 4.45, cz, false);
    [-3.6, 2.6].forEach((z) => {
      put(B(0.12, 2.0, 2.8), M(0x64748b), s, left + 0.22, 2.6, z, false);
      const gl = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 1.8), new THREE.MeshBasicMaterial({ color: 0xaecdea }));
      gl.rotation.y = Math.PI / 2;
      gl.position.set(left + 0.3, 2.6, z);
      s.add(gl);
      put(B(0.14, 1.8, 0.08), M(0x64748b), s, left + 0.32, 2.6, z, false);
      put(B(0.14, 0.08, 2.6), M(0x64748b), s, left + 0.32, 2.6, z, false);
    });
    // placa con el nombre en la pared del fondo
    const c = document.createElement("canvas");
    c.width = 1024; c.height = 256;
    const g = c.getContext("2d")!;
    g.fillStyle = "#0f172a"; g.fillRect(0, 0, 1024, 256);
    const gr = g.createLinearGradient(0, 0, 1024, 0);
    gr.addColorStop(0, "#5b5bf0"); gr.addColorStop(1, "#22c1c3");
    g.fillStyle = gr; g.fillRect(0, 236, 1024, 20);
    g.fillStyle = "#fff"; g.font = `800 96px ${FONT}`; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText("LocalHarness", 512, 112);
    g.fillStyle = "#94a3b8"; g.font = `600 34px ${FONT}`; g.fillText("OFICINA DE AGENTES", 512, 188);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    const pl = new THREE.Mesh(new THREE.PlaneGeometry(4.6, 1.15), new THREE.MeshBasicMaterial({ map: tex }));
    pl.position.set(0, 3.35, back + 0.2);
    s.add(pl);
  }

  // ---------- puestos
  /** Puestos presentes. Cada agente conserva su sitio mientras esté; los nuevos entran en el primer sitio libre
   *  (el director, en el central si está libre) y aparecen con una pequeña animación. */
  setStations(specs: StationSpec[]): void {
    const want = new Set(specs.map((s) => s.id));
    for (const [id, st] of this.stations) {
      const spec = specs.find((s) => s.id === id);
      if (!want.has(id) || !spec || spec.color !== st.spec.color || spec.kind !== st.spec.kind) this.removeStation(id);
    }
    const taken = (p: [number, number]) => [...this.stations.values()].some((st) => st.pos[0] === p[0] && st.pos[1] === p[1]);
    for (const spec of specs) {
      const st = this.stations.get(spec.id);
      if (st) { st.spec = spec; continue; }
      const pos = spec.kind === "you" ? YOU_POS
        : spec.kind === "director" && !taken(SLOTS[0]) ? SLOTS[0] : SLOTS.find((p, i) => i > 0 && !taken(p)) ?? (!taken(SLOTS[0]) ? SLOTS[0] : undefined);
      if (!pos) continue;
      this.buildStation(spec, pos);
    }
    this.buildLinks();
  }

  /** El rack del modelo local solo está en la sala mientras llama-server está encendido (o cargando). */
  setRackVisible(on: boolean): void {
    if (!this.rack.group || this.rack.group.visible === on) return;
    this.rack.group.visible = on;
    if (on) this.rack.group.scale.setScalar(0.01);
  }

  private removeStation(id: string): void {
    const st = this.stations.get(id);
    if (!st) return;
    this.scene.remove(st.group);
    st.group.traverse((o) => {
      const m = o as THREE.Mesh;
      m.geometry?.dispose();
      (m.material as THREE.Material | undefined)?.dispose?.();
    });
    this.clickable = this.clickable.filter((o) => o.userData.station !== id);
    this.stations.delete(id);
  }

  private buildStation(spec: StationSpec, pos: [number, number]): void {
    const me = spec.kind === "you", acc = spec.color, accL = mix(acc, "#ffffff", 0.5);
    const g = new THREE.Group();
    g.position.set(pos[0], 0, pos[1]);
    g.scale.setScalar(0.01); // entra creciendo (animate)
    this.scene.add(g);
    const own: THREE.Object3D[] = [];
    const P = <T extends THREE.BufferGeometry>(geo: T, mat: THREE.Material, parent: THREE.Object3D, x = 0, y = 0, z = 0, sh = true) => {
      const m = put(geo, mat, parent, x, y, z, sh);
      own.push(m);
      return m;
    };
    const rug = P(new THREE.CylinderGeometry(me ? 2.9 : 2.45, me ? 2.9 : 2.45, 0.04, 8), M(accL), g, 0, 0.02, -0.2, false);
    rug.scale.z = 0.78;
    rug.rotation.y = Math.PI / 8;
    const dw = me ? 3.2 : 2.5, dd = me ? 1.3 : 1.2;
    P(B(dw, 0.09, dd), M(0xe6d8c0, { roughness: 0.5 }), g, 0, 0.78, 0);
    P(B(dw, 0.05, dd + 0.04), M(acc), g, 0, 0.72, 0);
    [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach(([sx, sz]) =>
      P(new THREE.CylinderGeometry(0.045, 0.045, 0.74, 6), M(0xa59f92), g, sx * (dw / 2 - 0.12), 0.37, sz * (dd / 2 - 0.1)));
    // portátil: vemos el dorso de la tapa con el logo; la pantalla se ilumina al trabajar
    P(B(0.7, 0.025, 0.46), M(0x475569), g, 0, 0.82, 0.05);
    const lid = new THREE.Group();
    lid.position.set(0, 0.83, -0.17);
    lid.rotation.x = -0.28;
    g.add(lid);
    own.push(put(B(0.7, 0.46, 0.03), M(0xc9c3b6), lid, 0, 0.23, 0));
    const logo = new THREE.Mesh(new THREE.CircleGeometry(0.07, 6), new THREE.MeshBasicMaterial({ color: acc }));
    logo.position.set(0, 0.24, 0.02);
    lid.add(logo);
    const scr = new THREE.Mesh(new THREE.PlaneGeometry(0.64, 0.4), new THREE.MeshBasicMaterial({ color: acc }));
    scr.rotation.y = Math.PI;
    scr.position.set(0, 0.23, -0.017);
    lid.add(scr);
    P(new THREE.CylinderGeometry(0.07, 0.07, 0.13, 7), M(acc), g, dw / 2 - 0.4, 0.9, 0.2);
    if (!me) {
      P(B(0.5, 0.04, 0.2), M(0x94a3b8), g, -0.8, 0.83, 0.28);
      P(new THREE.CylinderGeometry(0.09, 0.07, 0.12, 6), M(0xc98a62), g, -dw / 2 + 0.3, 0.89, 0);
      P(new THREE.IcosahedronGeometry(0.13, 0), M(0x4ade80), g, -dw / 2 + 0.3, 1.04, 0);
    }
    const ch = new THREE.Group();
    ch.position.set(0, 0, -1.05);
    g.add(ch);
    own.push(put(B(0.74, 0.1, 0.74), M(acc), ch, 0, 0.52, 0), put(B(0.7, 0.7, 0.09), M(acc), ch, 0, 0.92, -0.34));
    put(new THREE.CylinderGeometry(0.05, 0.05, 0.35, 6), M(0x64748b), ch, 0, 0.3, 0);
    put(new THREE.CylinderGeometry(0.34, 0.34, 0.05, 5), M(0x64748b), ch, 0, 0.06, 0);
    const chr = this.buildCharacter(spec, own);
    chr.root.position.set(0, 0.6, -0.78);
    g.add(chr.root);
    const gem = new THREE.Mesh(new THREE.OctahedronGeometry(0.16, 0),
      new THREE.MeshStandardMaterial({ color: acc, emissive: acc, emissiveIntensity: 0.8, flatShading: true }));
    gem.scale.y = 1.5;
    gem.position.set(0, 2.55, -0.78);
    gem.visible = false;
    g.add(gem);
    const ring = new THREE.Mesh(new THREE.RingGeometry(me ? 2.55 : 2.15, me ? 2.7 : 2.3, 40),
      new THREE.MeshBasicMaterial({ color: acc, transparent: true, opacity: 0, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(0, 0.05, -0.2);
    ring.scale.z = 0.78;
    g.add(ring);
    own.forEach((m) => (m.userData.station = spec.id));
    this.clickable.push(...own);
    if (me) {
      // dos pulsadores (aprobar / rechazar) y la baliza que se enciende cuando algo espera tu decisión
      const btn = (x: number, c: number) => {
        put(new THREE.CylinderGeometry(0.2, 0.22, 0.08, 10), M(0x334155), g, x, 0.87, 0.25);
        put(new THREE.CylinderGeometry(0.15, 0.15, 0.1, 10), M(c, { emissive: c, emissiveIntensity: 0.25 }), g, x, 0.94, 0.25);
      };
      btn(-0.95, 0x16a34a);
      btn(0.95, 0xe11d48);
      put(new THREE.CylinderGeometry(0.09, 0.12, 0.08, 8), M(0x334155), g, 1.3, 0.86, -0.2);
      this.beacon = new THREE.Mesh(new THREE.SphereGeometry(0.14, 10, 8, 0, Math.PI * 2, 0, Math.PI / 2),
        new THREE.MeshStandardMaterial({ color: 0xf59e0b, emissive: 0xf59e0b, emissiveIntensity: 0.2 }));
      this.beacon.position.set(1.3, 0.92, -0.2);
      g.add(this.beacon);
      this.beaconLight = new THREE.PointLight(0xf59e0b, 0, 6);
      this.beaconLight.position.set(0, 0.3, 0);
      this.beacon.add(this.beaconLight);
      put(B(6.4, 0.12, 3.6), M(0xd9d3c6), g, 0, 0, -0.4, false);
    }
    this.stations.set(spec.id, { spec, group: g, ring, gem, scr, logo, char: chr, state: "idle", pos });
  }

  private buildCharacter(spec: StationSpec, own: THREE.Object3D[]) {
    // mascota blanda: cuerpo-gota, cabezón, ojos de punto; el accesorio dice el rol
    const root = new THREE.Group(), acc = spec.color, me = spec.kind === "you";
    const SM = (c: THREE.ColorRepresentation) => M(c, { flatShading: false, roughness: 0.55 });
    const T = <G extends THREE.BufferGeometry>(geo: G, mat: THREE.Material, parent: THREE.Object3D, x: number, y: number, z: number) => {
      const m = put(geo, mat, parent, x, y, z);
      own.push(m);
      return m;
    };
    const bodyC = me ? "#7c8aa0" : acc, skin = me ? "#f0c4a0" : mix(acc, "#ffffff", 0.5);
    T(new THREE.SphereGeometry(0.36, 16, 12), SM(bodyC), root, 0, 0.3, 0).scale.set(1.05, 0.95, 0.88);
    T(new THREE.SphereGeometry(0.2, 10, 8), SM(mix(bodyC, "#ffffff", 0.35)), root, 0, 0.22, 0.27).scale.set(1, 1, 0.45);
    const head = new THREE.Group();
    head.position.set(0, 0.93, 0);
    root.add(head);
    T(new THREE.SphereGeometry(0.42, 20, 16), SM(skin), head, 0, 0, 0).scale.set(1.1, 0.96, 1);
    const dark = M(0x1b1f27, { flatShading: false });
    [-0.15, 0.15].forEach((x) => {
      T(new THREE.SphereGeometry(0.07, 10, 8), dark, head, x, 0.03, 0.405).scale.set(0.9, 1.35, 0.5);
      T(new THREE.SphereGeometry(0.022, 6, 5), M(0xffffff, { flatShading: false, emissive: 0xffffff, emissiveIntensity: 0.5 }), head, x + 0.02, 0.075, 0.43);
    });
    T(new THREE.TorusGeometry(0.07, 0.016, 6, 12, Math.PI), dark, head, 0, -0.1, 0.405).rotation.z = Math.PI;
    [-0.27, 0.27].forEach((x) => T(new THREE.SphereGeometry(0.07, 8, 6), M(0xfda4af, { flatShading: false }), head, x, -0.06, 0.335).scale.set(1, 0.65, 0.4));
    const antenna = (h: number) => {
      T(new THREE.CylinderGeometry(0.015, 0.015, h, 5), M(0x8a8f99), head, 0, 0.4 + h / 2, 0);
      T(new THREE.SphereGeometry(0.075, 10, 8), new THREE.MeshStandardMaterial({ color: acc, emissive: acc, emissiveIntensity: 0.9 }), head, 0, 0.42 + h, 0).castShadow = false;
    };
    if (me) {
      T(new THREE.SphereGeometry(0.44, 14, 10, 0, Math.PI * 2, 0, Math.PI * 0.42), SM(0x3b2a20), head, 0, 0.02, -0.03).scale.set(1.1, 0.96, 1);
    } else if (spec.kind === "director") {
      antenna(0.3);
      T(new THREE.CylinderGeometry(0.1, 0.1, 0.03, 5), M(0xfbbf24), root, 0.2, 0.42, 0.3).rotation.x = Math.PI / 2;
    } else if (spec.kind === "consultas") {
      [-0.15, 0.15].forEach((x) => { T(new THREE.TorusGeometry(0.09, 0.032, 6, 10), M(0x0369a1), head, x, 0.28, 0.34).rotation.x = 0.35; });
      T(new THREE.SphereGeometry(0.24, 10, 8), SM(0x0369a1), root, 0, 0.33, -0.32).scale.set(1, 1.2, 0.6);
    } else if (spec.kind === "trabajador") {
      T(new THREE.SphereGeometry(0.45, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2), SM(0xfbbf24), head, 0, 0.1, 0).scale.set(1.08, 0.9, 1);
      T(new THREE.CylinderGeometry(0.5, 0.5, 0.04, 14), SM(0xf59e0b), head, 0, 0.12, 0.06).scale.set(1.05, 1, 1.15);
      T(B(0.09, 0.05, 0.7), SM(0xf59e0b), head, 0, 0.5, 0);
    } else if (spec.kind === "jefe") {
      T(new THREE.SphereGeometry(0.45, 14, 8, 0, Math.PI * 2, 0, Math.PI * 0.5), SM(0x059669), head, 0, 0.06, 0).scale.set(1.08, 0.95, 1);
      T(B(0.07, 0.15, 0.55), SM(0x34d399), head, 0, 0.5, 0);
      T(new THREE.CylinderGeometry(0.13, 0.13, 0.04, 5), SM(0xd1fae5), root, 0, 0.36, 0.34).rotation.x = Math.PI / 2;
    } else {
      antenna(0.28);
    }
    const arm = (x: number) => {
      const p = new THREE.Group();
      p.position.set(x, 0.5, 0.05);
      root.add(p);
      T(new THREE.SphereGeometry(0.12, 10, 8), SM(bodyC), p, 0, -0.2, 0).scale.set(1, 1.8, 1);
      T(new THREE.SphereGeometry(0.09, 8, 6), SM(skin), p, 0, -0.4, 0);
      return p;
    };
    return { root, head, L: arm(-0.38), R: arm(0.38) };
  }

  /** Líneas discontinuas de mando: tú → directores; director → el resto (sin director, tú → todos). */
  private buildLinks(): void {
    this.links.forEach((l) => { this.scene.remove(l.line); l.line.geometry.dispose(); l.mat.dispose(); });
    this.links = [];
    const agents = [...this.stations.values()].filter((s) => s.spec.kind !== "you");
    const heads = agents.filter((s) => s.spec.kind === "director");
    const hub = heads[0];
    const pairs: [Station, Station][] = [];
    const you = this.stations.get("you");
    if (!you) return;
    if (hub) {
      heads.forEach((h) => pairs.push([you, h]));
      agents.filter((s) => s.spec.kind !== "director").forEach((s) => pairs.push([hub, s]));
    } else {
      agents.forEach((s) => pairs.push([you, s]));
    }
    for (const [a, b] of pairs) {
      const geo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(a.pos[0], 0.07, a.pos[1] + 1.2), new THREE.Vector3(b.pos[0], 0.07, b.pos[1] - 1.9)]);
      const mat = new THREE.LineDashedMaterial({ color: 0x94a3b8, dashSize: 0.28, gapSize: 0.2 });
      const line = new THREE.Line(geo, mat);
      line.computeLineDistances();
      this.scene.add(line);
      this.links.push({ line, mat, flash: 0, color: b.spec.color, a: a.spec.id, b: b.spec.id });
    }
  }

  setState(id: string, state: StationState): void {
    const st = this.stations.get(id);
    if (st) st.state = state;
  }

  // ---------- rack del modelo local (llama-server)
  private buildRack(): void {
    const g = new THREE.Group();
    g.position.copy(RACK_POS);
    g.visible = false;
    this.rack.group = g;
    this.scene.add(g);
    const body = put(B(1.2, 2.7, 1.5), M(0x1e293b), g, 0, 1.35, 0);
    body.userData.station = "rack";
    this.clickable.push(body);
    put(B(1.3, 0.1, 1.6), M(0x334155), g, 0, 2.72, 0);
    [0, 1].forEach((k) => {
      const y = 0.85 + k * 1.15;
      put(B(0.08, 0.95, 1.2), M(0x0f172a), g, 0.62, y + 0.15, 0, false);
      const fan = put(new THREE.CylinderGeometry(0.28, 0.28, 0.05, 6), M(0x475569), g, 0.67, y + 0.15, -0.3, false);
      fan.rotation.z = Math.PI / 2;
      this.rack.fans.push(fan);
      const row: THREE.Mesh<THREE.BoxGeometry, THREE.MeshBasicMaterial>[] = [];
      for (let i = 0; i < 8; i++) {
        const m = new THREE.Mesh(B(0.05, 0.07, 0.07), new THREE.MeshBasicMaterial({ color: 0x334155 }));
        m.position.set(0.68, y - 0.12 + i * 0.1, 0.28);
        g.add(m);
        row.push(m);
      }
      this.rack.leds.push(row);
    });
    const lamp = M(0x38bdf8, { emissive: 0x38bdf8, emissiveIntensity: 0.1 });
    put(B(0.05, 0.12, 0.5), lamp, g, 0.64, 2.55, 0, false);
    this.rack.lamp = lamp;
  }

  /** Memoria usada (0–1) por GPU y si el modelo local está cargando, listo o apagado. */
  setGpu(levels: number[], busy: number, localState: string): void {
    this.gpu = levels;
    this.gpuBusy = busy;
    this.localState = localState;
  }

  // ---------- pizarras
  private mkBoard(w: number, h: number, x: number, y: number, z: number, cw: number, chh: number, key: string): void {
    const c = document.createElement("canvas");
    c.width = cw; c.height = chh;
    const tex = new THREE.CanvasTexture(c);
    tex.anisotropy = 8;
    tex.colorSpace = THREE.SRGBColorSpace;
    put(B(w + 0.2, h + 0.2, 0.1), M(0x64748b), this.scene, x, y, z, false);
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex }));
    m.position.set(x, y, z + 0.06);
    this.scene.add(m);
    this.boards[key] = { ctx: c.getContext("2d")!, tex };
  }

  private buildBoards(): void {
    const z = 0.2 - 15.5 / 2 + 0.26;
    this.mkBoard(4.6, 2.5, -5.4, 2.4, z, 1024, 560, "wb");
    this.mkBoard(3.4, 2.5, 5.4, 2.4, z, 768, 560, "git");
    this.drawBoard("Sin misión", [], 0);
    this.drawGit([]);
  }

  drawBoard(title: string, steps: BoardStep[], progress: number): void {
    const b = this.boards.wb;
    if (!b) return;
    const g = b.ctx;
    g.fillStyle = "#f1eee7"; g.fillRect(0, 0, 1024, 560);
    g.fillStyle = "#0f172a"; g.font = `800 40px ${FONT}`; g.textBaseline = "middle"; g.textAlign = "left";
    let t = title;
    while (g.measureText(t).width > 950 && t.length > 4) t = t.slice(0, -2);
    g.fillText(t === title ? t : t + "…", 34, 48);
    g.fillStyle = "#e2e8f0"; g.fillRect(34, 84, 956, 3);
    const n = Math.max(steps.length, 1), rh = Math.min(50, 420 / n);
    steps.slice(0, 8).forEach((s, i) => {
      const y = 100 + i * rh, mid = y + (rh - 6) / 2 + 1;
      const act = s.state === "active" || s.state === "wait";
      g.globalAlpha = s.state === "todo" ? 0.45 : 1;
      if (act) { g.fillStyle = mix(s.color, "#ffffff", 0.88); rr(g, 24, y, 976, rh - 6, 14); g.fill(); }
      g.fillStyle = s.color; rr(g, 40, mid - 15, 28, 28, 9); g.fill();
      g.fillStyle = "#0f172a"; g.font = `${act ? 800 : 600} 27px ${FONT}`;
      g.fillText(s.label.slice(0, 32), 86, mid);
      g.font = `600 22px ${FONT}`; g.fillStyle = "#64748b"; g.fillText(s.who.slice(0, 26), 560, mid);
      g.font = `800 28px ${FONT}`; g.textAlign = "right";
      const mark = { done: ["✓", "#16a34a"], failed: ["✗", "#e11d48"], wait: ["ESPERA", "#d97706"], active: ["▶", s.color], todo: ["", ""] }[s.state];
      if (mark[0]) { g.fillStyle = mark[1]; g.fillText(mark[0], 975, mid); }
      g.textAlign = "left"; g.globalAlpha = 1;
    });
    g.fillStyle = "#cfcbc0"; rr(g, 34, 520, 956, 14, 7); g.fill();
    g.fillStyle = "#5b5bf0"; rr(g, 34, 520, Math.max(14, 956 * Math.min(1, progress)), 14, 7); g.fill();
    b.tex.needsUpdate = true;
  }

  drawGit(rows: GitRow[]): void {
    const b = this.boards.git;
    if (!b) return;
    const g = b.ctx;
    g.fillStyle = "#0f172a"; g.fillRect(0, 0, 768, 560);
    g.fillStyle = "#e2e8f0"; g.font = `800 36px ${FONT}`; g.textBaseline = "middle"; g.textAlign = "left";
    g.fillText("git worktrees", 34, 46);
    g.fillStyle = "#334155"; g.fillRect(34, 80, 700, 3);
    const all: GitRow[] = [{ name: "main", status: "clean" }, ...rows];
    const colors = { clean: "#64748b", active: "#818cf8", ready: "#34d399", merged: "#475569", failed: "#f87171" };
    all.slice(0, 6).forEach((w, i) => {
      const y = 110 + i * 66, c = colors[w.status] ?? "#64748b";
      g.fillStyle = c; g.beginPath(); g.arc(56, y + 22, 11, 0, 7); g.fill();
      if (i < Math.min(all.length, 6) - 1) { g.fillStyle = "#334155"; g.fillRect(54, y + 34, 4, 32); }
      g.fillStyle = w.status === "merged" ? "#64748b" : "#e2e8f0"; g.font = `600 28px ${MONO}`;
      g.fillText(w.name.replace(/^localharness\//, "").slice(0, 22), 86, y + 22);
      g.fillStyle = c; g.font = `700 22px ${FONT}`; g.textAlign = "right";
      g.fillText(w.status.toUpperCase(), 730, y + 22); g.textAlign = "left";
    });
    if (all.length > 6) { g.fillStyle = "#64748b"; g.font = `600 22px ${FONT}`; g.fillText(`y ${all.length - 6} más`, 86, 520); }
    b.tex.needsUpdate = true;
  }

  // ---------- atrezzo
  private plant(x: number, z: number, s = 1): void {
    const g = new THREE.Group();
    g.position.set(x, 0, z);
    g.scale.setScalar(s);
    this.scene.add(g);
    put(new THREE.CylinderGeometry(0.42, 0.32, 0.7, 7), M(0xc98a62), g, 0, 0.35, 0);
    [0, 1, 2, 3, 4, 5].forEach((i) => {
      put(new THREE.IcosahedronGeometry(0.34, 0), M(i % 2 ? 0x22c55e : 0x16a34a), g,
        Math.cos(i * 1.1) * 0.28, 0.95 + i * 0.17, Math.sin(i * 1.1) * 0.28).scale.set(1.1, 0.55, 1.1);
    });
  }

  private buildProps(): void {
    this.plant(-9.4, -6.7); this.plant(9.5, -6.7); this.plant(-9.4, 7.2, 0.9); this.plant(9.6, 7.2, 0.9);
    const c = new THREE.Group();
    c.position.set(9.1, 0, -3.6);
    this.scene.add(c);
    put(B(1.3, 0.95, 0.9), M(0xc98a62), c, 0, 0.47, 0);
    put(B(0.55, 0.6, 0.5), M(0x334155), c, -0.25, 1.25, 0);
    put(new THREE.CylinderGeometry(0.08, 0.08, 0.15, 7), M(0xef4444), c, 0.3, 1.02, 0.1);
    put(new THREE.CylinderGeometry(0.3, 0.3, 0.7, 8), M(0x38bdf8, { transparent: true, opacity: 0.8 }), this.scene, 9.0, 1.55, -5.2);
    put(B(0.7, 1.2, 0.7), M(0xc9c3b6), this.scene, 9.0, 0.6, -5.2);
  }

  // ---------- clic en un puesto
  private setupPicking(): void {
    const ray = new THREE.Raycaster(), v = new THREE.Vector2(), cv = this.renderer.domElement;
    let down: [number, number] | null = null;
    const pick = (e: PointerEvent): string | null => {
      const r = cv.getBoundingClientRect();
      v.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(v, this.camera);
      const h = ray.intersectObjects(this.clickable.filter((o) => o.userData.station !== "rack" || this.rack.group?.visible), false);
      return h.length ? (h[0].object.userData.station as string) : null;
    };
    cv.addEventListener("pointerdown", (e) => (down = [e.clientX, e.clientY]));
    cv.addEventListener("pointerup", (e) => {
      if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 5) {
        const id = pick(e);
        if (id) this.onPick(id);
      }
      down = null;
    });
    let last = 0;
    cv.addEventListener("pointermove", (e) => {
      const n = performance.now();
      if (n - last < 60 || e.buttons) return;
      last = n;
      cv.style.cursor = pick(e) ? "pointer" : "";
    });
  }

  // ---------- paquetes: un encargo que viaja de un puesto a otro ("rack" = el modelo local)
  private anchor(id: string): THREE.Vector3 | null {
    if (id === "rack") return this.rack.group?.visible ? RACK_POS.clone().add(new THREE.Vector3(0.4, 2.9, 0)) : null;
    const st = this.stations.get(id);
    return st ? st.group.position.clone().add(new THREE.Vector3(0, 1.9, -0.4)) : null;
  }

  packet(from: string, to: string, color = "#5b5bf0"): void {
    const s = this.anchor(from), e = this.anchor(to);
    if (!s || !e || from === to) return;
    const m = new THREE.Mesh(B(0.4, 0.28, 0.1), new THREE.MeshBasicMaterial({ color }));
    const flap = new THREE.Mesh(new THREE.ConeGeometry(0.2, 0.14, 3), new THREE.MeshBasicMaterial({ color: 0xffffff }));
    flap.position.set(0, 0.07, 0.06);
    flap.rotation.z = Math.PI;
    flap.scale.set(1, 0.7, 0.2);
    m.add(flap);
    m.position.copy(s);
    this.scene.add(m);
    this.packets.push({ m, s, e, p: 0 });
    const link = this.links.find((l) => (l.a === from && l.b === to) || (l.a === to && l.b === from));
    if (link) link.flash = 1;
  }

  private updPackets(dt: number): void {
    for (let i = this.packets.length - 1; i >= 0; i--) {
      const p = this.packets[i];
      p.p += dt * 0.6;
      if (p.p >= 1) {
        this.scene.remove(p.m);
        p.m.geometry.dispose();
        this.packets.splice(i, 1);
        continue;
      }
      const t = p.p, mid = p.s.clone().add(p.e).multiplyScalar(0.5);
      mid.y += 2.2;
      p.m.position.set(
        (1 - t) ** 2 * p.s.x + 2 * (1 - t) * t * mid.x + t * t * p.e.x,
        (1 - t) ** 2 * p.s.y + 2 * (1 - t) * t * mid.y + t * t * p.e.y,
        (1 - t) ** 2 * p.s.z + 2 * (1 - t) * t * mid.z + t * t * p.e.z);
      p.m.rotation.y += 0.12;
    }
  }

  // ---------- cámara
  view(k: string): void {
    if (k === "iso") return this.goto([13.5, 11.5, 15], [0, 0.2, 0]);
    if (k === "rack") return this.goto([-3.2, 4.4, 1.8], [RACK_POS.x, 1.3, RACK_POS.z]);
    const st = this.stations.get(k);
    if (st) this.goto([st.pos[0] + 4.2, 3.9, st.pos[1] + 5.2], [st.pos[0], 1.1, st.pos[1] - 0.6]);
  }

  private goto(p: number[], t: number[]): void {
    this.camGoal = new THREE.Vector3(p[0], p[1], p[2]);
    this.targetGoal = new THREE.Vector3(t[0], t[1], t[2]);
  }

  // ---------- bucle
  private placeLabels(): void {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    for (const el of Array.from(this.labels.querySelectorAll<HTMLElement>("[data-lbl]"))) {
      const id = el.dataset.lbl!;
      const st = this.stations.get(id);
      if (st) this._v.set(st.pos[0], 2.95, st.pos[1] - 0.8);
      else if (id === "rack" && this.rack.group?.visible) this._v.set(RACK_POS.x, 3.3, RACK_POS.z);
      else if (id === "wb") this._v.set(-5.4, 3.95, -7.2);
      else if (id === "git") this._v.set(5.4, 3.95, -7.2);
      else { el.style.display = "none"; continue; }
      this._v.project(this.camera);
      el.style.transform = `translate(${(this._v.x * 0.5 + 0.5) * w}px,${(this._v.y * -0.5 + 0.5) * h}px) translate(-50%,-100%)`;
      el.style.zIndex = String(Math.round((1 - this._v.z) * 1000));
      el.style.display = this._v.z < 1 ? "" : "none";
    }
  }

  private animate = (): void => {
    this.raf = requestAnimationFrame(this.animate);
    const dt = Math.min(this.clock.getDelta(), 0.05), t = this.clock.elapsedTime;
    this.updPackets(dt);
    if (this.camGoal && this.targetGoal) {
      this.camera.position.lerp(this.camGoal, 0.07);
      this.controls.target.lerp(this.targetGoal, 0.07);
      if (this.camera.position.distanceTo(this.camGoal) < 0.08) { this.camGoal = null; this.targetGoal = null; }
    }
    let i = 0;
    const grow = (o: THREE.Object3D) => {
      if (o.scale.x < 1) o.scale.setScalar(Math.min(1, o.scale.x + (1.05 - o.scale.x) * 0.12));
    };
    if (this.rack.group?.visible) grow(this.rack.group);
    for (const st of this.stations.values()) {
      grow(st.group);
      const ch = st.char, busy = st.state === "working", waiting = st.state === "waiting";
      ch.L.rotation.x += ((busy ? -1.15 + Math.sin(t * 14 + i) * 0.12 : -0.85 + Math.sin(t * 1.5 + i) * 0.03) - ch.L.rotation.x) * 0.2;
      const rt = waiting ? Math.PI * 0.92 + Math.sin(t * 7) * 0.12 : busy ? -1.15 + Math.cos(t * 16 + i) * 0.12 : -0.85 + Math.sin(t * 1.6 + i) * 0.03;
      ch.R.rotation.x += (rt - ch.R.rotation.x) * 0.18;
      ch.R.rotation.z += ((waiting ? -0.25 + Math.sin(t * 7) * 0.25 : 0) - ch.R.rotation.z) * 0.2;
      ch.head.rotation.y = Math.sin(t * 1.2 + i * 1.7) * (busy ? 0.06 : 0.22);
      ch.head.rotation.x = busy ? 0.12 : Math.sin(t * 0.9 + i) * 0.04;
      ch.root.position.y = 0.6 + (st.state === "idle" ? Math.sin(t * 1.8 + i) * 0.012 : 0);
      const on = st.state !== "idle" || this.selected === st.spec.id;
      st.gem.visible = st.state !== "idle";
      st.gem.rotation.y = t * 2;
      st.gem.position.y = 2.55 + Math.sin(t * 3) * 0.07;
      const gc = waiting ? "#f59e0b" : st.spec.color;
      st.gem.material.color.set(gc);
      st.gem.material.emissive.set(gc);
      const target = st.state !== "idle" ? 0.35 + Math.sin(t * 4) * 0.15 : on ? 0.3 : 0;
      st.ring.material.opacity += (target - st.ring.material.opacity) * 0.15;
      st.scr.material.color.set(busy ? st.spec.color : "#cbd5e1");
      st.logo.material.color.set(busy ? "#ffffff" : st.spec.color);
      i++;
    }
    if (this.beacon && this.beaconLight) {
      this.beacon.material.emissiveIntensity = this.pending ? 0.6 + Math.sin(t * 8) * 0.5 : 0.15;
      this.beaconLight.intensity = this.pending ? (1.8 + Math.sin(t * 8)) * Math.PI : 0;
      this.beacon.rotation.y = t * 3;
    }
    for (const l of this.links) {
      l.flash = Math.max(0, l.flash - dt * 0.5);
      l.mat.color.set(l.flash > 0 ? l.color : "#94a3b8");
    }
    // rack: LEDs = memoria de cada GPU; ventiladores más rápidos si el modelo local trabaja
    this.rack.leds.forEach((row, k) => {
      const v = this.gpu[k];
      const n = v === undefined ? (this.localState === "ready" && k === 0 ? 3 : 0) : Math.round(Math.min(1, v) * 8);
      const blink = this.localState === "loading" && Math.sin(t * 8 + k) > 0;
      row.forEach((m, j) => m.material.color.set(blink ? 0x38bdf8 : j < n ? (j < 5 ? 0x22c55e : j < 7 ? 0xf59e0b : 0xef4444) : 0x334155));
    });
    this.rack.fans.forEach((f) => (f.rotation.x += 0.03 + this.gpuBusy * 0.5));
    if (this.rack.lamp) this.rack.lamp.emissiveIntensity = this.localState === "ready" ? 0.9 : this.localState === "loading" ? 0.4 + Math.sin(t * 6) * 0.4 : 0.05;
    this.placeLabels();
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  };
}
