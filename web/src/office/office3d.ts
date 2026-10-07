// Oficina (three.js) estilo habitación isométrica tipo Habbo: un puesto por agente REAL con su muñeco androide,
// el tuyo con la baliza de aprobaciones, el rack del modelo local y dos pizarras (misión y worktrees).
// La vista Vue le pasa el estado; esta clase dibuja y avisa de clics y de puestos movidos (arrastrar con el ratón).
// Las etiquetas son HTML (las pinta Vue) y aquí solo se recolocan cada fotograma: [data-lbl="<id>"] en `labels`.

import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

export type StationKind = "you" | "director" | "jefe" | "trabajador" | "consultas" | "local" | "otro";
export type StationState = "idle" | "working" | "waiting";

export interface StationSpec {
  id: string; // "you" o "a<id del agente>"
  name: string;
  color: string;
  kind: StationKind;
  boss?: string; // puesto del que depende (el trabajador local, del Claude que le encarga): la línea va a él
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

/** Posición guardada de un puesto: x, z y giro en cuartos de vuelta. */
export type Placement = [number, number, number];

interface Station {
  spec: StationSpec;
  group: THREE.Group;
  ring: THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>;
  gem: THREE.Mesh<THREE.OctahedronGeometry, THREE.MeshStandardMaterial>;
  screen: { ctx: CanvasRenderingContext2D; tex: THREE.CanvasTexture; tick: number }[];
  eyes: THREE.MeshStandardMaterial;
  lamp: THREE.MeshStandardMaterial | null;
  char: { root: THREE.Group; head: THREE.Group; L: THREE.Group; R: THREE.Group };
  state: StationState;
}

// sala
const W = 22, D = 16, CZ = 0.2;
const BACK = CZ - D / 2, LEFT = -W / 2;
const BOUNDS = { x0: LEFT + 1.4, x1: W / 2 - 1.2, z0: BACK + 1.6, z1: CZ + D / 2 - 1.0 };
// puestos por defecto: tú al fondo, luego una cuadrícula (el primero, en el centro de la primera fila)
const YOU_POS: [number, number] = [0, -4.6];
const SLOTS: [number, number][] = [
  [0, -0.9], [-5.4, -0.9], [5.4, -0.9],
  [0, 2.6], [-5.4, 2.6], [5.4, 2.6],
  [0, 6.0], [-5.4, 6.0], [5.4, 6.0],
  [-9.0, 2.6], [-9.0, 6.0], [9.0, 2.6],
];
export const MAX_STATIONS = SLOTS.length;
const RACK_DEFAULT: [number, number] = [-8.9, -3.4];

const M = (c: THREE.ColorRepresentation, o: THREE.MeshStandardMaterialParameters = {}) =>
  new THREE.MeshStandardMaterial({ color: c, flatShading: true, roughness: 0.78, metalness: 0, ...o });
const S = (c: THREE.ColorRepresentation, o: THREE.MeshStandardMaterialParameters = {}) =>
  new THREE.MeshStandardMaterial({ color: c, roughness: 0.45, metalness: 0.02, ...o }); // liso (muñecos)
const B = (w: number, h: number, d: number) => new THREE.BoxGeometry(w, h, d);
const mix = (a: string, b: string, t: number) => "#" + new THREE.Color(a).lerp(new THREE.Color(b), t).getHexString();
const WOOD = 0xb9824f, WOOD_D = 0x8a5a33, WOOD_L = 0xd9a978;

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

function canvasTex(w: number, h: number, draw: (g: CanvasRenderingContext2D) => void, repeat?: [number, number]): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  draw(c.getContext("2d")!);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  if (repeat) {
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(repeat[0], repeat[1]);
  }
  return t;
}

const FONT = '"Plus Jakarta Sans Variable","Segoe UI",sans-serif';
const MONO = '"JetBrains Mono",monospace';
// colores de «código» en las pantallas
const CODE = ["#7dd3fc", "#c4b5fd", "#86efac", "#fcd34d", "#f9a8d4", "#e2e8f0"];

export class Office {
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(30, 1, 0.1, 200);
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
  private clockHands: { h: THREE.Object3D; m: THREE.Object3D } | null = null;
  private camGoal: THREE.Vector3 | null = null;
  private targetGoal: THREE.Vector3 | null = null;
  private raf = 0;
  private ro: ResizeObserver;
  private gpu: number[] = [];
  private gpuBusy = 0;
  private localState = "off";
  private layout: Record<string, Placement> = {};
  private dragging: { id: string; obj: THREE.Object3D; off: THREE.Vector3 } | null = null;
  pending = false; // baliza: hay algo esperando tu decisión
  selected: string | null = null;
  movable = true; // arrastrar puestos con el ratón
  /** Avisa cuando sueltas un puesto en otro sitio (para guardarlo). */
  onMove: (id: string, p: Placement) => void = () => {};
  private _v = new THREE.Vector3();

  constructor(private host: HTMLElement, private labels: HTMLElement, private onPick: (id: string) => void) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    host.insertBefore(this.renderer.domElement, labels);
    // casi isométrica (FOV estrecho y lejos), como las habitaciones de Habbo
    this.camera.position.set(21, 18, 23.5);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.08;
    this.controls.minDistance = 5;
    this.controls.maxDistance = 60;
    this.controls.target.set(0, 0.4, 0.4);
    this.controls.addEventListener("start", () => { this.camGoal = null; this.targetGoal = null; });

    this.scene.add(new THREE.HemisphereLight(0xfff7ec, 0xb89a7a, 0.55 * Math.PI));
    const sun = new THREE.DirectionalLight(0xffeccc, 1.0 * Math.PI);
    sun.position.set(10, 18, 12);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { near: 1, far: 60, left: -16, right: 16, top: 16, bottom: -16 });
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 0.02;
    this.scene.add(sun);
    const fill = new THREE.DirectionalLight(0xbcd4ff, 0.35 * Math.PI);
    fill.position.set(-12, 7, 6);
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
  private buildRoom(): void {
    const s = this.scene;
    // tarima de madera
    const floor = canvasTex(512, 512, (g) => {
      const tones = ["#c99563", "#c28c5a", "#d0a06d", "#bd8653", "#c79260"];
      const ph = 32;
      for (let r = 0; r < 512 / ph; r++) {
        let x = -((r * 97) % 180);
        while (x < 512) {
          const len = 140 + ((r * 31 + x) % 90);
          g.fillStyle = tones[(r * 7 + Math.abs(x)) % tones.length];
          g.fillRect(x, r * ph, len, ph);
          g.fillStyle = "rgba(90,50,20,.08)";
          for (let k = 0; k < 3; k++) g.fillRect(x + 6, r * ph + 6 + k * 9, len - 12, 1);
          g.fillStyle = "rgba(70,40,15,.45)";
          g.fillRect(x, r * ph, 2, ph);
          x += len;
        }
        g.fillStyle = "rgba(70,40,15,.4)";
        g.fillRect(0, r * ph, 512, 2);
      }
    }, [3, 2.2]);
    put(B(W + 0.6, 0.5, D + 0.6), M(0x8a6a4c), s, 0, -0.26, CZ);
    put(B(W + 0.2, 0.9, D + 0.2), M(0x6e5440), s, 0, -0.9, CZ, false);
    const fl = put(new THREE.PlaneGeometry(W, D), new THREE.MeshStandardMaterial({ map: floor, roughness: 0.85 }), s, 0, 0.001, CZ, false);
    fl.rotation.x = -Math.PI / 2;

    // papel pintado (dos tonos con rombos) y zócalo de madera
    const paper = (base: string, dot: string) => canvasTex(256, 256, (g) => {
      g.fillStyle = base; g.fillRect(0, 0, 256, 256);
      g.fillStyle = dot;
      for (let y = 0; y < 256; y += 32) for (let x = (y / 32) % 2 ? 16 : 0; x < 256; x += 32) {
        g.beginPath(); g.moveTo(x, y - 6); g.lineTo(x + 6, y); g.lineTo(x, y + 6); g.lineTo(x - 6, y); g.fill();
      }
      g.fillStyle = "rgba(255,255,255,.05)";
      for (let x = 0; x < 256; x += 64) g.fillRect(x, 0, 3, 256);
    }, [6, 1.2]);
    const H = 4.6;
    const backMat = new THREE.MeshStandardMaterial({ map: paper("#7aa6b4", "#8fb8c4"), roughness: 0.95 });
    const leftMat = new THREE.MeshStandardMaterial({ map: paper("#6f9aa8", "#86adba"), roughness: 0.95 });
    put(B(W, H, 0.3), backMat, s, 0, H / 2, BACK);
    put(B(0.3, H, D), leftMat, s, LEFT, H / 2, CZ);
    // zócalo alto de madera (friso) y moldura
    put(B(W, 1.1, 0.08), M(WOOD), s, 0, 0.55, BACK + 0.18, false);
    put(B(0.08, 1.1, D), M(WOOD), s, LEFT + 0.18, 0.55, CZ, false);
    put(B(W, 0.08, 0.14), M(WOOD_D), s, 0, 1.12, BACK + 0.2, false);
    put(B(0.14, 0.08, D), M(WOOD_D), s, LEFT + 0.2, 1.12, CZ, false);
    put(B(W + 0.3, 0.16, 0.5), M(0xe8e1d4), s, 0, H + 0.02, BACK, false);
    put(B(0.5, 0.16, D + 0.3), M(0xe8e1d4), s, LEFT, H + 0.02, CZ, false);

    // ventanas con cortinas en la pared izquierda
    [-3.4, 3.2].forEach((z) => {
      const sky = canvasTex(128, 128, (g) => {
        const gr = g.createLinearGradient(0, 0, 0, 128);
        gr.addColorStop(0, "#8fc7f0"); gr.addColorStop(1, "#d8eefc");
        g.fillStyle = gr; g.fillRect(0, 0, 128, 128);
        g.fillStyle = "#9fb4c8";
        [[8, 70, 18, 58], [30, 55, 16, 73], [50, 80, 22, 48], [78, 62, 18, 66], [100, 76, 20, 52]].forEach(([x, y, w, h]) => g.fillRect(x, y, w, h));
        g.fillStyle = "rgba(255,255,255,.5)";
        for (let i = 0; i < 6; i++) g.fillRect(12 + i * 18, 84 + (i % 2) * 8, 3, 3);
      });
      const gl = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 1.9), new THREE.MeshBasicMaterial({ map: sky }));
      gl.rotation.y = Math.PI / 2;
      gl.position.set(LEFT + 0.17, 2.75, z);
      s.add(gl);
      const frame = M(0xf5f1ea);
      put(B(0.12, 0.12, 2.8), frame, s, LEFT + 0.22, 3.75, z, false);
      put(B(0.2, 0.1, 2.9), frame, s, LEFT + 0.25, 1.78, z, false); // alféizar
      put(B(0.12, 1.9, 0.08), frame, s, LEFT + 0.22, 2.75, z, false);
      put(B(0.12, 0.08, 2.6), frame, s, LEFT + 0.22, 2.75, z, false);
      [-1, 1].forEach((side) => {
        const c = put(B(0.1, 2.3, 0.55), M(0xe9d8b4), s, LEFT + 0.32, 2.65, z + side * 1.55, false);
        c.scale.z = 1;
      });
      put(new THREE.CylinderGeometry(0.03, 0.03, 3.6, 6), M(0x8a6a4c), s, LEFT + 0.36, 3.92, z, false).rotation.x = Math.PI / 2;
    });
    // reloj de pared (con agujas de verdad)
    const clk = new THREE.Group();
    clk.position.set(LEFT + 0.2, 3.35, -0.1);
    clk.rotation.y = Math.PI / 2;
    s.add(clk);
    put(new THREE.CylinderGeometry(0.42, 0.42, 0.08, 28), M(0x334155), clk, 0, 0, 0, false).rotation.x = Math.PI / 2;
    put(new THREE.CylinderGeometry(0.36, 0.36, 0.09, 28), M(0xffffff), clk, 0, 0, 0.01, false).rotation.x = Math.PI / 2;
    for (let i = 0; i < 12; i++) {
      const a = (i / 12) * Math.PI * 2;
      put(B(0.03, 0.07, 0.02), M(0x334155), clk, Math.sin(a) * 0.3, Math.cos(a) * 0.3, 0.06, false).rotation.z = -a;
    }
    const hand = (len: number, w: number) => {
      const p = new THREE.Group();
      p.position.z = 0.07;
      clk.add(p);
      put(B(w, len, 0.015), M(0x0f172a), p, 0, len / 2, 0, false);
      return p;
    };
    this.clockHands = { h: hand(0.18, 0.04), m: hand(0.28, 0.025) };
    // póster
    const poster = canvasTex(256, 360, (g) => {
      g.fillStyle = "#f8f1e4"; g.fillRect(0, 0, 256, 360);
      g.fillStyle = "#5b5bf0"; rr(g, 20, 20, 216, 220, 18); g.fill();
      g.fillStyle = "#a3e635"; g.beginPath(); g.arc(128, 150, 62, Math.PI, 0); g.fill(); // androide
      g.fillStyle = "#a3e635"; g.fillRect(66, 156, 124, 70);
      g.fillStyle = "#fff"; g.beginPath(); g.arc(104, 122, 8, 0, 7); g.arc(152, 122, 8, 0, 7); g.fill();
      g.fillStyle = "#0f172a"; g.font = `800 34px ${FONT}`; g.textAlign = "center";
      g.fillText("SHIP IT", 128, 290);
      g.fillStyle = "#64748b"; g.font = `600 20px ${FONT}`; g.fillText("revisa el diff antes", 128, 326);
    });
    const pp = new THREE.Mesh(new THREE.PlaneGeometry(0.95, 1.33), new THREE.MeshStandardMaterial({ map: poster, roughness: 0.9 }));
    pp.rotation.y = Math.PI / 2;
    pp.position.set(LEFT + 0.17, 2.6, 6.4);
    s.add(pp);

    // placa con el nombre en la pared del fondo
    const plate = canvasTex(1024, 256, (g) => {
      g.fillStyle = "#1e293b"; rr(g, 0, 0, 1024, 256, 40); g.fill();
      const gr = g.createLinearGradient(0, 0, 1024, 0);
      gr.addColorStop(0, "#5b5bf0"); gr.addColorStop(1, "#22c1c3");
      g.fillStyle = gr; g.fillRect(60, 226, 904, 10);
      g.fillStyle = "#fff"; g.font = `800 96px ${FONT}`; g.textAlign = "center"; g.textBaseline = "middle";
      g.fillText("LocalHarness", 512, 108);
      g.fillStyle = "#94a3b8"; g.font = `600 34px ${FONT}`; g.fillText("OFICINA DE AGENTES", 512, 186);
    });
    const pl = new THREE.Mesh(new THREE.PlaneGeometry(4.2, 1.05), new THREE.MeshBasicMaterial({ map: plate, transparent: true }));
    pl.position.set(0, 3.55, BACK + 0.17);
    s.add(pl);
  }

  // ---------- puestos
  /** Posiciones guardadas (Ajustes → office_layout). Se aplican a los puestos presentes y a los que entren. */
  setLayout(layout: Record<string, Placement>): void {
    this.layout = { ...layout };
    for (const [id, st] of this.stations) {
      const p = this.layout[id];
      if (p) this.place(st.group, p);
    }
    const r = this.layout.rack;
    if (r && this.rack.group) this.place(this.rack.group, r);
    this.buildLinks();
  }

  private place(o: THREE.Object3D, p: Placement): void {
    o.position.set(p[0], 0, p[1]);
    o.rotation.y = (p[2] % 4) * (Math.PI / 2);
  }

  private placement(o: THREE.Object3D): Placement {
    return [Math.round(o.position.x * 100) / 100, Math.round(o.position.z * 100) / 100,
      ((Math.round(o.rotation.y / (Math.PI / 2)) % 4) + 4) % 4];
  }

  /** Puestos presentes. Cada agente conserva su sitio mientras esté; los nuevos van a donde los dejaste la última
   *  vez o al primer sitio libre (el director, al central si está libre) y entran con una pequeña animación. */
  setStations(specs: StationSpec[]): void {
    const want = new Set(specs.map((s) => s.id));
    for (const [id, st] of this.stations) {
      const spec = specs.find((s) => s.id === id);
      if (!want.has(id) || !spec || spec.color !== st.spec.color || spec.kind !== st.spec.kind) this.removeStation(id);
      else if (spec.boss !== st.spec.boss) st.spec = spec; // la línea de mando cambia, el puesto no
    }
    const taken = (p: [number, number]) => [...this.stations.values()].some((st) =>
      Math.hypot(st.group.position.x - p[0], st.group.position.z - p[1]) < 1.5);
    for (const spec of specs) {
      const st = this.stations.get(spec.id);
      if (st) { st.spec = spec; continue; }
      const saved = this.layout[spec.id];
      let pos: Placement | undefined = saved;
      if (!pos) {
        const xz = spec.kind === "you" ? YOU_POS
          : spec.kind === "director" && !taken(SLOTS[0]) ? SLOTS[0] : SLOTS.find((p, i) => i > 0 && !taken(p)) ?? (!taken(SLOTS[0]) ? SLOTS[0] : undefined);
        if (xz) pos = [xz[0], xz[1], 2]; // de espaldas a la cámara: se ve la pantalla con el código
      }
      if (!pos) continue;
      this.buildStation(spec, pos);
    }
    this.buildLinks();
  }

  /** Gira un puesto un cuarto de vuelta y lo guarda. */
  rotate(id: string): void {
    const o = id === "rack" ? this.rack.group : this.stations.get(id)?.group;
    if (!o) return;
    o.rotation.y += Math.PI / 2;
    const p = this.placement(o);
    this.layout[id] = p;
    this.onMove(id, p);
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
      const mat = m.material as THREE.MeshBasicMaterial | undefined;
      mat?.map?.dispose();
      mat?.dispose?.();
    });
    this.clickable = this.clickable.filter((o) => o.userData.station !== id);
    this.stations.delete(id);
  }

  private screenTex(): { ctx: CanvasRenderingContext2D; tex: THREE.CanvasTexture; tick: number } {
    const c = document.createElement("canvas");
    c.width = 256; c.height = 160;
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    return { ctx: c.getContext("2d")!, tex, tick: Math.random() * 10 };
  }

  /** Pantalla: código que se va escribiendo al trabajar; el logo y la hora en reposo. */
  private drawScreen(sc: { ctx: CanvasRenderingContext2D; tex: THREE.CanvasTexture; tick: number }, st: Station): void {
    const g = sc.ctx, acc = st.spec.color;
    g.fillStyle = "#0b1220"; g.fillRect(0, 0, 256, 160);
    if (st.state === "idle") {
      g.fillStyle = mix(acc, "#0b1220", 0.55); g.beginPath(); g.arc(128, 70, 26, 0, 7); g.fill();
      g.fillStyle = "#94a3b8"; g.font = `700 22px ${FONT}`; g.textAlign = "center";
      const d = new Date();
      g.fillText(`${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`, 128, 130);
    } else {
      g.fillStyle = mix(acc, "#0b1220", 0.3); g.fillRect(0, 0, 256, 16);
      g.fillStyle = "#fff"; g.font = `600 11px ${MONO}`; g.textAlign = "left";
      g.fillText(st.state === "waiting" ? "esperando tu decisión" : st.spec.name, 8, 12);
      const n = Math.floor(sc.tick * 3);
      for (let i = 0; i < 9; i++) {
        const line = n - 8 + i;
        if (line < 0) continue;
        let x = 10 + ((line * 7) % 4) * 12;
        const parts = 1 + ((line * 13) % 4);
        for (let k = 0; k < parts; k++) {
          const w = 14 + ((line * 31 + k * 17) % 50);
          g.fillStyle = CODE[(line + k * 3) % CODE.length];
          g.fillRect(x, 24 + i * 15, w, 7);
          x += w + 6;
        }
      }
      if (st.state === "working" && Math.floor(sc.tick * 4) % 2) { g.fillStyle = "#fff"; g.fillRect(10, 24 + 8 * 15, 7, 9); }
    }
    sc.tex.needsUpdate = true;
  }

  private buildStation(spec: StationSpec, pos: Placement): void {
    const me = spec.kind === "you", acc = spec.color, accL = mix(acc, "#ffffff", 0.55);
    const g = new THREE.Group();
    this.place(g, pos);
    g.scale.setScalar(0.01); // entra creciendo (animate)
    this.scene.add(g);
    const own: THREE.Object3D[] = [];
    const P = <T extends THREE.BufferGeometry>(geo: T, mat: THREE.Material, parent: THREE.Object3D, x = 0, y = 0, z = 0, sh = true) => {
      const m = put(geo, mat, parent, x, y, z, sh);
      own.push(m);
      return m;
    };
    // alfombra
    const rugTex = canvasTex(128, 128, (c) => {
      c.fillStyle = accL; c.fillRect(0, 0, 128, 128);
      c.strokeStyle = mix(acc, "#ffffff", 0.25); c.lineWidth = 6; c.strokeRect(10, 10, 108, 108);
      c.strokeStyle = "rgba(255,255,255,.5)"; c.lineWidth = 2; c.strokeRect(20, 20, 88, 88);
    });
    const rw = me ? 5.2 : 3.6, rd = me ? 3.6 : 3.0;
    P(B(rw, 0.03, rd), new THREE.MeshStandardMaterial({ map: rugTex, roughness: 1 }), g, 0, 0.015, -0.45, false);

    // escritorio de madera con cajonera y faldón delantero
    const dw = me ? 3.4 : 2.6, dd = me ? 1.25 : 1.15, top = 0.8;
    P(B(dw, 0.08, dd), M(WOOD_L, { roughness: 0.55 }), g, 0, top, 0);
    P(B(dw + 0.04, 0.03, dd + 0.04), M(WOOD_D), g, 0, top - 0.055, 0);
    P(B(dw - 0.1, top - 0.2, 0.05), M(WOOD), g, 0, (top - 0.2) / 2 + 0.12, dd / 2 - 0.06); // faldón (lado de la cámara)
    const ped = dw / 2 - 0.36;
    P(B(0.62, top - 0.06, dd - 0.08), M(WOOD), g, ped, (top - 0.06) / 2, 0);
    [0.18, 0.42, 0.64].forEach((y) => {
      P(B(0.56, 0.2, 0.02), M(WOOD_L), g, ped, y, -dd / 2 + 0.03);
      P(B(0.14, 0.025, 0.03), M(0x64748b), g, ped, y + 0.03, -dd / 2 + 0.01);
    });
    P(B(0.06, top - 0.06, dd - 0.08), M(WOOD), g, -dw / 2 + 0.06, (top - 0.06) / 2, 0);

    // monitor(es): la pantalla mira al muñeco; por detrás, el logo del agente
    const screens: Station["screen"] = [];
    const monitor = (x: number, rotY = 0) => {
      const m = new THREE.Group();
      m.position.set(x, top + 0.04, 0.12);
      m.rotation.y = rotY;
      g.add(m);
      own.push(put(new THREE.CylinderGeometry(0.16, 0.18, 0.03, 16), M(0x334155), m, 0, 0.015, 0));
      own.push(put(B(0.06, 0.32, 0.05), M(0x334155), m, 0, 0.17, 0.02));
      own.push(put(B(1.0, 0.62, 0.06), M(0x1e293b), m, 0, 0.55, 0));
      const sc = this.screenTex();
      screens.push(sc);
      const face = new THREE.Mesh(new THREE.PlaneGeometry(0.92, 0.54), new THREE.MeshBasicMaterial({ map: sc.tex }));
      face.rotation.y = Math.PI;
      face.position.set(0, 0.55, -0.032);
      m.add(face);
      const logo = new THREE.Mesh(new THREE.CircleGeometry(0.07, 20), new THREE.MeshBasicMaterial({ color: acc }));
      logo.position.set(0, 0.6, 0.032);
      m.add(logo);
    };
    if (me) { monitor(-0.55, -0.12); monitor(0.55, 0.12); } else monitor(-0.1);
    // teclado, ratón, taza, papeles
    P(B(0.62, 0.025, 0.2), M(0xe2e8f0), g, -0.1, top + 0.055, -0.3);
    for (let r = 0; r < 3; r++) P(B(0.56, 0.008, 0.035), M(0x94a3b8), g, -0.1, top + 0.072, -0.36 + r * 0.055, false);
    P(new THREE.SphereGeometry(0.05, 10, 8), M(0xe2e8f0), g, 0.38, top + 0.06, -0.3).scale.set(1, 0.5, 1.4);
    const mug = P(new THREE.CylinderGeometry(0.07, 0.065, 0.14, 14), S(acc), g, dw / 2 - 0.25, top + 0.11, -0.25);
    P(new THREE.TorusGeometry(0.04, 0.012, 6, 12), S(acc), mug, 0.075, 0, 0);
    P(B(0.34, 0.03, 0.44), M(0xf8fafc), g, -dw / 2 + 0.4, top + 0.055, -0.15).rotation.y = 0.15;
    P(B(0.3, 0.06, 0.4), M(0x60a5fa), g, -dw / 2 + 0.42, top + 0.09, -0.12).rotation.y = -0.1;
    // flexo con luz que se enciende al trabajar
    let lampMat: THREE.MeshStandardMaterial | null = null;
    if (!me) {
      const lx = dw / 2 - 0.3, lz = 0.25;
      P(new THREE.CylinderGeometry(0.1, 0.12, 0.03, 14), M(0x334155), g, lx, top + 0.055, lz);
      const arm = P(new THREE.CylinderGeometry(0.018, 0.018, 0.5, 6), M(0x334155), g, lx, top + 0.3, lz);
      arm.rotation.z = 0.25;
      const head = P(new THREE.ConeGeometry(0.1, 0.16, 14, 1, true), M(acc, { side: THREE.DoubleSide }), g, lx - 0.15, top + 0.52, lz - 0.05);
      head.rotation.z = -0.9;
      lampMat = M(0xfff7d6, { emissive: 0xffe9a8, emissiveIntensity: 0 });
      P(new THREE.SphereGeometry(0.04, 8, 6), lampMat, g, lx - 0.2, top + 0.47, lz - 0.05, false);
      // planta pequeña
      P(new THREE.CylinderGeometry(0.08, 0.06, 0.12, 10), M(0xc2410c), g, -dw / 2 + 0.25, top + 0.1, 0.3);
      [0, 1, 2, 3].forEach((i) => P(new THREE.SphereGeometry(0.07, 8, 6), M(i % 2 ? 0x22c55e : 0x15803d), g,
        -dw / 2 + 0.25 + Math.cos(i * 1.6) * 0.05, top + 0.22 + i * 0.03, 0.3 + Math.sin(i * 1.6) * 0.05).scale.set(1, 1.4, 1));
    }

    // silla de oficina con ruedas
    const ch = new THREE.Group();
    ch.position.set(0, 0, -0.95);
    g.add(ch);
    const dark = M(0x334155);
    for (let i = 0; i < 5; i++) {
      const a = (i / 5) * Math.PI * 2;
      const leg = put(B(0.05, 0.04, 0.36), dark, ch, Math.sin(a) * 0.17, 0.07, Math.cos(a) * 0.17);
      leg.rotation.y = a;
      put(new THREE.SphereGeometry(0.04, 8, 6), M(0x0f172a), ch, Math.sin(a) * 0.34, 0.04, Math.cos(a) * 0.34);
    }
    put(new THREE.CylinderGeometry(0.04, 0.04, 0.34, 8), M(0x94a3b8), ch, 0, 0.25, 0);
    own.push(put(B(0.68, 0.1, 0.62), S(mix(acc, "#1e293b", 0.25)), ch, 0, 0.47, 0));
    own.push(put(B(0.64, 0.7, 0.09), S(mix(acc, "#1e293b", 0.25)), ch, 0, 0.92, -0.32));
    [-1, 1].forEach((sx) => {
      put(B(0.05, 0.2, 0.05), dark, ch, sx * 0.34, 0.6, 0);
      put(B(0.08, 0.04, 0.32), dark, ch, sx * 0.34, 0.71, 0.02);
    });

    const chr = this.buildCharacter(spec, own);
    chr.root.position.set(0, 0.52, -0.92);
    g.add(chr.root);
    const gem = new THREE.Mesh(new THREE.OctahedronGeometry(0.15, 0),
      new THREE.MeshStandardMaterial({ color: acc, emissive: acc, emissiveIntensity: 0.8, flatShading: true }));
    gem.scale.y = 1.5;
    gem.position.set(0, 2.35, -0.92);
    gem.visible = false;
    g.add(gem);
    const ring = new THREE.Mesh(new THREE.RingGeometry(me ? 2.6 : 1.95, me ? 2.75 : 2.08, 48),
      new THREE.MeshBasicMaterial({ color: acc, transparent: true, opacity: 0, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(0, 0.04, -0.45);
    ring.scale.y = 0.8;
    g.add(ring);
    own.forEach((m) => (m.userData.station = spec.id));
    this.clickable.push(...own);
    if (me) {
      // dos pulsadores (aprobar / rechazar) y la baliza que se enciende cuando algo espera tu decisión
      const btn = (x: number, c: number) => {
        put(new THREE.CylinderGeometry(0.16, 0.18, 0.06, 14), M(0x334155), g, x, top + 0.07, -0.35);
        put(new THREE.CylinderGeometry(0.12, 0.12, 0.08, 14), M(c, { emissive: c, emissiveIntensity: 0.3 }), g, x, top + 0.12, -0.35);
      };
      btn(-1.3, 0x16a34a);
      btn(1.3, 0xe11d48);
      put(new THREE.CylinderGeometry(0.09, 0.12, 0.08, 10), M(0x334155), g, 1.45, top + 0.08, 0.3);
      this.beacon = new THREE.Mesh(new THREE.SphereGeometry(0.14, 14, 10, 0, Math.PI * 2, 0, Math.PI / 2),
        new THREE.MeshStandardMaterial({ color: 0xf59e0b, emissive: 0xf59e0b, emissiveIntensity: 0.2 }));
      this.beacon.position.set(1.45, top + 0.12, 0.3);
      g.add(this.beacon);
      this.beaconLight = new THREE.PointLight(0xf59e0b, 0, 6);
      this.beaconLight.position.set(0, 0.3, 0);
      this.beacon.add(this.beaconLight);
    }
    const st: Station = { spec, group: g, ring, gem, screen: screens, eyes: chr.eyes, lamp: lampMat, char: chr, state: "idle" };
    screens.forEach((sc) => this.drawScreen(sc, st));
    this.stations.set(spec.id, st);
  }

  /** Muñeco androide: cuerpo-cápsula, cabeza en cúpula con antenas y ojos que brillan al trabajar.
   *  El color es el del agente y el accesorio dice el rol (corona, casco, gafas, cascos con micro). */
  private buildCharacter(spec: StationSpec, own: THREE.Object3D[]) {
    const root = new THREE.Group(), acc = spec.color, me = spec.kind === "you";
    const T = <G extends THREE.BufferGeometry>(geo: G, mat: THREE.Material, parent: THREE.Object3D, x: number, y: number, z: number) => {
      const m = put(geo, mat, parent, x, y, z);
      own.push(m);
      return m;
    };
    const body = S(acc), band = S(0xf8fafc);
    // cuerpo: cilindro con la base redondeada (torno)
    const prof = [new THREE.Vector2(0, 0), new THREE.Vector2(0.2, 0.0), new THREE.Vector2(0.28, 0.04),
      new THREE.Vector2(0.31, 0.12), new THREE.Vector2(0.31, 0.56), new THREE.Vector2(0.29, 0.6), new THREE.Vector2(0, 0.6)];
    T(new THREE.LatheGeometry(prof, 28), body, root, 0, 0.0, 0);
    T(new THREE.CylinderGeometry(0.3, 0.3, 0.035, 28), band, root, 0, 0.625, 0); // la línea blanca del cuello
    // piernas (sentado: hacia delante) y brazos
    [-0.13, 0.13].forEach((x) => {
      const leg = T(new THREE.CapsuleGeometry(0.085, 0.2, 6, 12), body, root, x, 0.06, 0.18);
      leg.rotation.x = Math.PI / 2;
    });
    const head = new THREE.Group();
    head.position.set(0, 0.65, 0);
    root.add(head);
    T(new THREE.SphereGeometry(0.3, 28, 14, 0, Math.PI * 2, 0, Math.PI / 2), body, head, 0, 0.02, 0);
    T(new THREE.CircleGeometry(0.3, 28), body, head, 0, 0.02, 0).rotation.x = Math.PI / 2;
    const eyes = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: accL(acc), emissiveIntensity: 0.15, roughness: 0.3 });
    [-0.11, 0.11].forEach((x) => T(new THREE.SphereGeometry(0.042, 12, 10), eyes, head, x, 0.15, 0.255).scale.set(1, 1, 0.6));
    // antenas
    [-1, 1].forEach((sx) => {
      const a = new THREE.Group();
      a.position.set(sx * 0.13, 0.27, 0);
      a.rotation.z = -sx * 0.45;
      head.add(a);
      T(new THREE.CylinderGeometry(0.016, 0.016, 0.2, 8), body, a, 0, 0.1, 0);
      T(new THREE.SphereGeometry(0.024, 8, 6), body, a, 0, 0.2, 0);
    });
    // accesorio del rol
    if (me) {
      const gold = S(0xfacc15, { metalness: 0.4 });
      T(B(0.09, 0.22, 0.02), S(0xdc2626), root, 0, 0.42, 0.305); // corbata
      T(new THREE.SphereGeometry(0.035, 8, 6), gold, root, 0, 0.56, 0.3);
    } else if (spec.kind === "director") {
      const gold = S(0xfacc15, { metalness: 0.5, roughness: 0.3 });
      T(new THREE.CylinderGeometry(0.17, 0.17, 0.09, 16, 1, true), gold, head, 0, 0.3, 0).material.side = THREE.DoubleSide;
      for (let i = 0; i < 5; i++) {
        const a = (i / 5) * Math.PI * 2;
        T(new THREE.ConeGeometry(0.04, 0.09, 6), gold, head, Math.sin(a) * 0.16, 0.38, Math.cos(a) * 0.16);
      }
    } else if (spec.kind === "trabajador") {
      const y = S(0xfbbf24);
      T(new THREE.SphereGeometry(0.32, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), y, head, 0, 0.05, 0).scale.set(1, 0.85, 1);
      T(new THREE.CylinderGeometry(0.38, 0.38, 0.025, 24), y, head, 0, 0.05, 0.04).scale.set(1, 1, 1.1);
      T(B(0.05, 0.03, 0.5), S(0xf59e0b), head, 0, 0.32, 0);
    } else if (spec.kind === "jefe") {
      const k = S(0x1f2937);
      T(new THREE.TorusGeometry(0.31, 0.025, 8, 24, Math.PI), k, head, 0, 0.04, 0).rotation.y = Math.PI / 2;
      [-1, 1].forEach((sx) => T(new THREE.CylinderGeometry(0.08, 0.08, 0.06, 14), k, head, sx * 0.31, 0.06, 0).rotation.z = Math.PI / 2);
      const mic = T(new THREE.CylinderGeometry(0.012, 0.012, 0.22, 6), k, head, 0.24, -0.02, 0.15);
      mic.rotation.x = Math.PI / 2.4;
      T(new THREE.SphereGeometry(0.03, 8, 6), S(0x22c55e), head, 0.24, -0.06, 0.25);
    } else if (spec.kind === "local") {
      // trabajador del modelo local: visor de luz (corre en tu GPU) y un chip en la cabeza
      const glow = new THREE.MeshStandardMaterial({ color: 0x67e8f9, emissive: 0x22d3ee, emissiveIntensity: 0.9, roughness: 0.2 });
      T(new THREE.TorusGeometry(0.3, 0.035, 8, 28, Math.PI * 0.9), glow, head, 0, 0.15, 0).rotation.set(0, Math.PI * 0.05, 0);
      T(B(0.2, 0.05, 0.2), S(0x0f172a), head, 0, 0.33, 0);
      T(B(0.12, 0.02, 0.12), glow, head, 0, 0.365, 0);
    } else if (spec.kind === "consultas") {
      const k = S(0x0f172a);
      [-0.11, 0.11].forEach((x) => T(new THREE.TorusGeometry(0.065, 0.014, 6, 16), k, head, x, 0.15, 0.27));
      T(B(0.08, 0.014, 0.014), k, head, 0, 0.16, 0.28);
    }
    const arm = (x: number) => {
      const p = new THREE.Group();
      p.position.set(x, 0.5, 0.0);
      root.add(p);
      T(new THREE.CapsuleGeometry(0.07, 0.26, 6, 12), body, p, 0, -0.2, 0);
      return p;
    };
    return { root, head, L: arm(-0.39), R: arm(0.39), eyes };
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
    const bossOf = (s: Station) => (s.spec.boss ? this.stations.get(s.spec.boss) : undefined);
    const free = agents.filter((s) => !bossOf(s));
    if (hub) {
      heads.forEach((h) => pairs.push([you, h]));
      free.filter((s) => s.spec.kind !== "director").forEach((s) => pairs.push([hub, s]));
    } else {
      free.forEach((s) => pairs.push([you, s]));
    }
    agents.forEach((s) => { const b = bossOf(s); if (b) pairs.push([b, s]); });
    for (const [a, b] of pairs) {
      const pa = a.group.position, pb = b.group.position;
      const geo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(pa.x, 0.06, pa.z), new THREE.Vector3(pb.x, 0.06, pb.z)]);
      const mat = new THREE.LineDashedMaterial({ color: 0x94a3b8, dashSize: 0.28, gapSize: 0.2, transparent: true, opacity: 0.7 });
      const line = new THREE.Line(geo, mat);
      line.computeLineDistances();
      this.scene.add(line);
      this.links.push({ line, mat, flash: 0, color: b.spec.color, a: a.spec.id, b: b.spec.id });
    }
  }

  setState(id: string, state: StationState): void {
    const st = this.stations.get(id);
    if (st && st.state !== state) {
      st.state = state;
      st.screen.forEach((sc) => this.drawScreen(sc, st));
    }
  }

  // ---------- rack del modelo local (llama-server)
  private buildRack(): void {
    const g = new THREE.Group();
    g.position.set(RACK_DEFAULT[0], 0, RACK_DEFAULT[1]);
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
    put(B(w + 0.2, h + 0.2, 0.1), M(0x8a6a4c), this.scene, x, y, z, false);
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex }));
    m.position.set(x, y, z + 0.06);
    this.scene.add(m);
    this.boards[key] = { ctx: c.getContext("2d")!, tex };
  }

  private buildBoards(): void {
    const z = BACK + 0.2;
    this.mkBoard(4.4, 2.4, -5.5, 2.55, z, 1024, 560, "wb");
    this.mkBoard(3.2, 2.4, 5.3, 2.55, z, 768, 560, "git");
    // bandeja de rotuladores bajo la pizarra
    put(B(4.0, 0.06, 0.18), M(0x8a6a4c), this.scene, -5.5, 1.28, z + 0.12, false);
    [0x2563eb, 0xdc2626, 0x16a34a].forEach((c, i) => put(new THREE.CylinderGeometry(0.025, 0.025, 0.22, 6), M(c), this.scene, -6.6 + i * 0.3, 1.33, z + 0.12, false).rotation.z = Math.PI / 2);
    this.drawBoard("Sin misión", [], 0);
    this.drawGit([]);
  }

  drawBoard(title: string, steps: BoardStep[], progress: number): void {
    const b = this.boards.wb;
    if (!b) return;
    const g = b.ctx;
    g.fillStyle = "#f8f6f1"; g.fillRect(0, 0, 1024, 560);
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
  private plant(x: number, z: number, s = 1, tall = false): void {
    const g = new THREE.Group();
    g.position.set(x, 0, z);
    g.scale.setScalar(s);
    this.scene.add(g);
    put(new THREE.CylinderGeometry(0.36, 0.28, 0.62, 16), M(0xf1f5f9, { flatShading: false }), g, 0, 0.31, 0);
    put(new THREE.CylinderGeometry(0.33, 0.33, 0.04, 16), M(0x5b3a1e), g, 0, 0.6, 0, false);
    if (tall) {
      put(new THREE.CylinderGeometry(0.03, 0.04, 1.2, 6), M(0x7c5a3a), g, 0, 1.2, 0);
      for (let i = 0; i < 9; i++) {
        const a = i * 2.4, h = 1.0 + (i % 3) * 0.35;
        const leaf = put(new THREE.SphereGeometry(0.22, 8, 6), M(i % 2 ? 0x22c55e : 0x16a34a), g, Math.cos(a) * 0.32, h, Math.sin(a) * 0.32);
        leaf.scale.set(1.3, 0.35, 0.7);
        leaf.rotation.y = -a;
      }
    } else {
      [0, 1, 2, 3, 4, 5].forEach((i) => {
        put(new THREE.IcosahedronGeometry(0.3, 0), M(i % 2 ? 0x22c55e : 0x16a34a), g,
          Math.cos(i * 1.1) * 0.24, 0.85 + i * 0.13, Math.sin(i * 1.1) * 0.24).scale.set(1.1, 0.6, 1.1);
      });
    }
  }

  private bookshelf(x: number, z: number, rotY = 0): void {
    const g = new THREE.Group();
    g.position.set(x, 0, z);
    g.rotation.y = rotY;
    this.scene.add(g);
    const w = 1.8, h = 2.6, d = 0.5;
    put(B(w, h, 0.05), M(WOOD_D), g, 0, h / 2, -d / 2);
    [-1, 1].forEach((sx) => put(B(0.07, h, d), M(WOOD), g, sx * (w / 2 - 0.035), h / 2, 0));
    const books = [0x2563eb, 0xdc2626, 0x16a34a, 0xf59e0b, 0x7c3aed, 0x0891b2, 0xe11d48, 0x475569];
    for (let r = 0; r < 4; r++) {
      const y = 0.08 + r * 0.64;
      put(B(w - 0.1, 0.05, d), M(WOOD), g, 0, y, 0);
      let bx = -w / 2 + 0.12;
      let k = r * 3;
      while (bx < w / 2 - 0.2) {
        const bw = 0.07 + ((k * 7) % 5) * 0.015, bh = 0.36 + ((k * 11) % 4) * 0.05;
        if ((k * 5) % 9 === 0) { bx += 0.15; k++; continue; } // hueco
        const b = put(B(bw, bh, 0.32), M(books[k % books.length]), g, bx + bw / 2, y + 0.025 + bh / 2, 0.02, false);
        if ((k * 13) % 11 === 0) b.rotation.z = 0.18;
        bx += bw + 0.01;
        k++;
      }
    }
    put(B(w + 0.06, 0.06, d + 0.04), M(WOOD_D), g, 0, h, 0);
    put(new THREE.SphereGeometry(0.16, 16, 12), M(0x38bdf8, { flatShading: false }), g, 0.45, h + 0.18, 0); // globo terráqueo
    put(new THREE.CylinderGeometry(0.03, 0.08, 0.06, 10), M(WOOD_D), g, 0.45, h + 0.03, 0);
  }

  private buildProps(): void {
    const s = this.scene;
    this.plant(-10.0, BACK + 0.8, 1, true);
    this.plant(10.2, BACK + 0.8, 1.05, true);
    this.plant(-10.1, 7.5, 0.9);
    this.bookshelf(-8.4, BACK + 0.45);
    this.bookshelf(8.6, BACK + 0.45);
    // corcho con notas
    const cork = canvasTex(256, 192, (g) => {
      g.fillStyle = "#c79a64"; g.fillRect(0, 0, 256, 192);
      g.fillStyle = "rgba(90,50,20,.18)";
      for (let i = 0; i < 400; i++) g.fillRect((i * 53) % 256, (i * 97) % 192, 2, 2);
      [["#fde68a", 20, 18], ["#a7f3d0", 96, 30], ["#fbcfe8", 170, 16], ["#bfdbfe", 40, 100], ["#fde68a", 130, 104]].forEach(([c, x, y]) => {
        g.fillStyle = c as string; g.fillRect(x as number, y as number, 62, 62);
        g.fillStyle = "rgba(15,23,42,.35)";
        for (let l = 0; l < 4; l++) g.fillRect((x as number) + 8, (y as number) + 14 + l * 11, 40 - l * 6, 3);
        g.fillStyle = "#dc2626"; g.beginPath(); g.arc((x as number) + 31, (y as number) + 5, 4, 0, 7); g.fill();
      });
    });
    put(B(1.9, 1.4, 0.06), M(WOOD_D), s, 0, 1.95, BACK + 0.2, false);
    const ck = new THREE.Mesh(new THREE.PlaneGeometry(1.75, 1.25), new THREE.MeshStandardMaterial({ map: cork, roughness: 1 }));
    ck.position.set(0, 1.95, BACK + 0.24);
    s.add(ck);
    // rincón de descanso: sofá, mesa baja, alfombra
    const lounge = new THREE.Group();
    lounge.position.set(9.0, 0, 6.6);
    lounge.rotation.y = -Math.PI / 2;
    s.add(lounge);
    const sofa = S(0xf59e0b);
    put(B(2.4, 0.4, 0.95), sofa, lounge, 0, 0.32, 0);
    put(B(2.4, 0.7, 0.25), sofa, lounge, 0, 0.7, -0.38);
    [-1, 1].forEach((sx) => put(B(0.25, 0.55, 0.95), sofa, lounge, sx * 1.2, 0.45, 0));
    [-0.55, 0.55].forEach((x) => put(B(1.0, 0.12, 0.7), S(0xfbbf24), lounge, x, 0.58, 0.05));
    put(B(1.3, 0.06, 0.65), M(WOOD_L), lounge, 0, 0.42, 1.25);
    [[-0.55, -0.25], [0.55, -0.25], [-0.55, 0.25], [0.55, 0.25]].forEach(([x, z]) => put(B(0.05, 0.4, 0.05), M(WOOD_D), lounge, x, 0.2, 1.25 + z));
    put(B(0.3, 0.06, 0.4), M(0x7c3aed), lounge, -0.2, 0.48, 1.2);
    put(new THREE.CylinderGeometry(0.06, 0.05, 0.1, 12), M(0xffffff), lounge, 0.3, 0.5, 1.25);
    put(B(3.0, 0.02, 2.6), M(0xe7e0d2), lounge, 0, 0.012, 0.7, false);
    // fuente de agua y papelera
    const wc = new THREE.Group();
    wc.position.set(10.2, 0, -3.0);
    s.add(wc);
    put(B(0.6, 1.1, 0.6), M(0xf1f5f9), wc, 0, 0.55, 0);
    put(new THREE.CylinderGeometry(0.26, 0.26, 0.62, 18), M(0x7dd3fc, { transparent: true, opacity: 0.75, flatShading: false }), wc, 0, 1.42, 0);
    put(B(0.12, 0.08, 0.06), M(0x2563eb), wc, 0, 0.85, 0.32);
    put(new THREE.CylinderGeometry(0.2, 0.16, 0.42, 14, 1, true), M(0x94a3b8, { side: THREE.DoubleSide }), s, 10.25, 0.21, -1.9);
    // mueble de la impresora
    const c = new THREE.Group();
    c.position.set(10.1, 0, -5.4);
    s.add(c);
    put(B(0.9, 0.95, 1.3), M(WOOD), c, 0, 0.47, 0);
    put(B(0.6, 0.35, 0.7), M(0xe2e8f0), c, 0, 1.12, 0);
    put(B(0.4, 0.02, 0.5), M(0xffffff), c, 0, 1.31, 0.05);
  }

  // ---------- clic y arrastre de puestos
  private setupPicking(): void {
    const ray = new THREE.Raycaster(), v = new THREE.Vector2(), cv = this.renderer.domElement;
    const floor = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), hit = new THREE.Vector3();
    let down: { x: number; y: number; id: string | null } | null = null;
    const aim = (e: PointerEvent) => {
      const r = cv.getBoundingClientRect();
      v.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(v, this.camera);
    };
    const pick = (e: PointerEvent): string | null => {
      aim(e);
      const h = ray.intersectObjects(this.clickable.filter((o) => o.userData.station !== "rack" || this.rack.group?.visible), false);
      return h.length ? (h[0].object.userData.station as string) : null;
    };
    const objOf = (id: string) => (id === "rack" ? this.rack.group : this.stations.get(id)?.group);
    // en captura: antes que OrbitControls, para que agarrar un puesto no gire la cámara
    cv.addEventListener("pointerdown", (e) => {
      const id = e.button === 0 ? pick(e) : null;
      down = { x: e.clientX, y: e.clientY, id };
      if (id && this.movable) this.controls.enabled = false;
    }, { capture: true });
    cv.addEventListener("pointermove", (e) => {
      if (down?.id && this.movable && e.buttons === 1) {
        const o = objOf(down.id);
        if (!o) return;
        if (!this.dragging && Math.hypot(e.clientX - down.x, e.clientY - down.y) > 6) {
          aim(e);
          ray.ray.intersectPlane(floor, hit);
          this.dragging = { id: down.id, obj: o, off: o.position.clone().sub(hit).setY(0) };
          cv.style.cursor = "grabbing";
        }
        if (this.dragging) {
          aim(e);
          if (ray.ray.intersectPlane(floor, hit)) {
            const p = hit.add(this.dragging.off);
            o.position.set(
              Math.round(Math.min(BOUNDS.x1, Math.max(BOUNDS.x0, p.x)) * 4) / 4, 0,
              Math.round(Math.min(BOUNDS.z1, Math.max(BOUNDS.z0, p.z)) * 4) / 4);
          }
        }
        return;
      }
      if (e.buttons) return;
      cv.style.cursor = pick(e) ? (this.movable ? "grab" : "pointer") : "";
    });
    const end = (e: PointerEvent) => {
      if (this.dragging) {
        const { id, obj } = this.dragging;
        const p = this.placement(obj);
        this.layout[id] = p;
        this.onMove(id, p);
        this.buildLinks();
        this.dragging = null;
        cv.style.cursor = "grab";
      } else if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5) {
        const id = down.id ?? pick(e);
        if (id) this.onPick(id);
      }
      this.controls.enabled = true;
      down = null;
    };
    cv.addEventListener("pointerup", end);
    cv.addEventListener("pointercancel", () => { this.dragging = null; this.controls.enabled = true; down = null; });
  }

  // ---------- paquetes: un encargo que viaja de un puesto a otro ("rack" = el modelo local)
  private world(o: THREE.Object3D, x: number, y: number, z: number): THREE.Vector3 {
    return o.localToWorld(new THREE.Vector3(x, y, z));
  }

  private anchor(id: string): THREE.Vector3 | null {
    if (id === "rack") return this.rack.group?.visible ? this.rack.group.position.clone().add(new THREE.Vector3(0.4, 2.9, 0)) : null;
    const st = this.stations.get(id);
    return st ? this.world(st.group, 0, 1.8, -0.5) : null;
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
    if (k === "iso") return this.goto([21, 18, 23.5], [0, 0.4, 0.4]);
    if (k === "rack") {
      const r = this.rack.group!.position;
      return this.goto([r.x + 5.5, 4.6, r.z + 5.0], [r.x, 1.3, r.z]);
    }
    const st = this.stations.get(k);
    if (!st) return;
    const c = this.world(st.group, 0, 1.0, -0.6);
    this.goto([c.x + 4.6, c.y + 3.4, c.z + 5.6], [c.x, c.y, c.z]);
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
      if (st) this._v.copy(this.world(st.group, 0, 2.35, -0.92));
      else if (id === "rack" && this.rack.group?.visible) this._v.copy(this.rack.group.position).setY(3.3);
      else if (id === "wb") this._v.set(-5.5, 4.0, BACK + 0.3);
      else if (id === "git") this._v.set(5.3, 4.0, BACK + 0.3);
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
      const held = this.dragging?.id === st.spec.id;
      // brazos: teclear al trabajar, saludar si espera tu decisión, reposo si no
      ch.L.rotation.x += ((busy ? -1.2 + Math.sin(t * 14 + i) * 0.14 : held ? -2.6 : -0.5 + Math.sin(t * 1.5 + i) * 0.04) - ch.L.rotation.x) * 0.2;
      const rt = waiting ? Math.PI * 0.92 + Math.sin(t * 7) * 0.12 : busy ? -1.2 + Math.cos(t * 16 + i) * 0.14 : held ? -2.6 : -0.5 + Math.sin(t * 1.6 + i) * 0.04;
      ch.R.rotation.x += (rt - ch.R.rotation.x) * 0.18;
      ch.R.rotation.z += ((waiting ? -0.3 + Math.sin(t * 7) * 0.3 : 0) - ch.R.rotation.z) * 0.2;
      ch.head.rotation.y = Math.sin(t * 1.2 + i * 1.7) * (busy ? 0.08 : 0.25);
      ch.head.rotation.x = busy ? 0.1 : Math.sin(t * 0.9 + i) * 0.05;
      ch.root.position.y = 0.52 + (held ? 0.25 + Math.sin(t * 10) * 0.04 : st.state === "idle" ? Math.sin(t * 1.8 + i) * 0.015 : Math.abs(Math.sin(t * 7 + i)) * 0.01);
      st.eyes.emissiveIntensity += ((busy ? 1.2 + Math.sin(t * 6) * 0.3 : waiting ? 0.9 : 0.12) - st.eyes.emissiveIntensity) * 0.1;
      if (st.lamp) st.lamp.emissiveIntensity += ((busy ? 1.4 : 0) - st.lamp.emissiveIntensity) * 0.1;
      // pantallas: el código avanza mientras trabaja (se redibuja unas 6 veces por segundo)
      for (const sc of st.screen) {
        if (st.state === "idle") continue;
        const before = Math.floor(sc.tick * 6);
        sc.tick += dt * (busy ? 1 : 0.15);
        if (Math.floor(sc.tick * 6) !== before) this.drawScreen(sc, st);
      }
      const on = st.state !== "idle" || this.selected === st.spec.id || held;
      st.gem.visible = st.state !== "idle";
      st.gem.rotation.y = t * 2;
      st.gem.position.y = 2.35 + Math.sin(t * 3) * 0.07;
      const gc = waiting ? "#f59e0b" : st.spec.color;
      st.gem.material.color.set(gc);
      st.gem.material.emissive.set(gc);
      const target = held ? 0.8 : st.state !== "idle" ? 0.35 + Math.sin(t * 4) * 0.15 : on ? 0.45 : 0;
      st.ring.material.opacity += (target - st.ring.material.opacity) * 0.15;
      i++;
    }
    if (this.clockHands) {
      const d = new Date();
      this.clockHands.m.rotation.z = -(d.getMinutes() / 60) * Math.PI * 2;
      this.clockHands.h.rotation.z = -(((d.getHours() % 12) + d.getMinutes() / 60) / 12) * Math.PI * 2;
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

const accL = (c: string) => mix(c, "#ffffff", 0.35);
