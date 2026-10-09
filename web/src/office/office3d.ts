// Oficina (three.js) estilo habitación isométrica tipo Habbo: un puesto por agente REAL con su muñeco androide,
// el tuyo con la baliza de aprobaciones, una torre de servidores por cada modelo local encendido, la pantalla de las
// GPUs y dos pizarras (misión y worktrees). Los muñecos libres se levantan de vez en cuando a por un café, a la
// impresora, al sofá… y vuelven a su sitio en cuanto les llega trabajo.
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
  icon?: string; // código Font Awesome del icono del agente (el de su avatar en el chat): va en el pecho
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

/** Un modelo local encendido = una torre de servidores en la sala (id del servidor: «principal», «rapido»…). */
export interface RackSpec {
  id: string;
  name: string;   // «Fuerte»
  model: string;  // nombre del GGUF
  state: string;  // loading | ready | external | failed
  gpu: number;    // índice de la GPU (CUDA0 → 0): sus LEDs siguen la VRAM de esa GPU
  gpuName: string;
  color: string;
}

type Led = THREE.Mesh<THREE.BoxGeometry, THREE.MeshBasicMaterial>;

interface Tower {
  spec: RackSpec;
  group: THREE.Group;
  fans: THREE.Mesh[];
  vram: Led[];
  net: Led[];
  cpu: Led[][];
  lamp: THREE.MeshStandardMaterial;
  plate: { ctx: CanvasRenderingContext2D; tex: THREE.CanvasTexture };
}

/** Paseo de un muñeco libre: de la silla a un sitio de la oficina (café, impresora…) y vuelta. */
interface Trip {
  phase: "out" | "stay" | "back";
  path: THREE.Vector3[];
  k: number;          // siguiente punto del camino
  poi: Poi;
  spot: number;
  until: number;      // fin de la estancia (segundos del reloj de la escena)
}

interface Poi {
  name: "cafe" | "impresora" | "agua" | "sofa" | "ventana" | "estanteria";
  spots: [number, number][]; // dónde se queda de pie (o sentado, en el sofá)
  face: number;              // hacia dónde mira allí (giro en y)
  taken: (string | null)[];
}

interface Station {
  spec: StationSpec;
  group: THREE.Group;
  ring: THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>;
  gem: THREE.Mesh<THREE.OctahedronGeometry, THREE.MeshStandardMaterial>;
  screen: { ctx: CanvasRenderingContext2D; tex: THREE.CanvasTexture; tick: number; kind: "code" | "graph" }[];
  eyes: THREE.MeshStandardMaterial;
  lamp: THREE.MeshStandardMaterial | null;
  char: { root: THREE.Group; head: THREE.Group; L: THREE.Group; R: THREE.Group; legs: THREE.Group[] };
  pc: { fans: THREE.Mesh[]; glow: THREE.MeshStandardMaterial } | null;
  state: StationState;
  nextTrip: number;   // segundos de escena a partir de los cuales, si sigue libre, puede levantarse
  trip: Trip | null;
}

// sala
const W = 19, D = 14, CZ = 0.2;
const BACK = CZ - D / 2, LEFT = -W / 2, RX = W / 2, FZ = CZ + D / 2;
// cámara de la vista general (casi isométrica)
const ISO = [17.5, 15, 19.5];
const BOUNDS = { x0: LEFT + 1.4, x1: W / 2 - 1.2, z0: BACK + 1.6, z1: CZ + D / 2 - 1.0 };
// puestos por defecto: tú al fondo, luego una cuadrícula (el primero, en el centro de la primera fila)
const YOU_POS: [number, number] = [0, -4.0];
const SLOTS: [number, number][] = [
  [0, -0.9], [-4.8, -0.9], [4.8, -0.9],
  [0, 2.4], [-4.8, 2.4], [4.8, 2.4],
  [0, 5.4], [-4.8, 5.4], [4.8, 5.4],
  [-4.8, -3.7], [4.8, -3.7],
];
export const MAX_STATIONS = SLOTS.length;
// torres de los modelos locales: en fila contra la pared izquierda, entre las dos ventanas, mirando a la sala (la
// cuarta, si hay, en la esquina de delante)
const RACK_SLOTS: [number, number][] = [[LEFT + 1.0, -1.4], [LEFT + 1.0, 0.0], [LEFT + 1.0, 1.4], [LEFT + 2.3, FZ - 0.9]];
// rejilla para los paseos: celdas de medio metro sobre el suelo
const CELL = 0.5, GX = Math.ceil(W / CELL), GZ = Math.ceil(D / CELL);
const WALK = 1.25; // m/s

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
const ICON_FONT = '"Font Awesome 7 Free"';
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
  private towers = new Map<string, Tower>();
  private pois: Poi[] = [];
  private wallTv: { ctx: CanvasRenderingContext2D; tex: THREE.CanvasTexture; at: number } | null = null;
  private cpuUse = 0;
  private beacon: THREE.Mesh<THREE.SphereGeometry, THREE.MeshStandardMaterial> | null = null;
  private beaconLight: THREE.PointLight | null = null;
  private clockHands: { h: THREE.Object3D; m: THREE.Object3D } | null = null;
  private camGoal: THREE.Vector3 | null = null;
  private targetGoal: THREE.Vector3 | null = null;
  private raf = 0;
  private ro: ResizeObserver;
  private gpu: number[] = [];
  private gpuUtil: number[] = [];
  private layout: Record<string, Placement> = {};
  private dragging: { id: string; obj: THREE.Object3D; off: THREE.Vector3 } | null = null;
  pending = false; // baliza: hay algo esperando tu decisión
  selected: string | null = null;
  movable = true; // arrastrar puestos con el ratón
  /** Modo cine: si nadie toca la oficina en CINE_IDLE s, la cámara se mueve sola (planos generales y de quien trabaja). */
  cinematic = true;
  private lastInput = 0;
  private cine: { kind: "orbit" | "agent" | "tower"; id: string; start: number; until: number; a0: number } | null = null;
  private shots = 0;
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
    this.camera.position.set(ISO[0], ISO[1], ISO[2]);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.08;
    this.controls.minDistance = 5;
    this.controls.maxDistance = 60;
    this.controls.target.set(0, 0.4, 0.4);
    this.controls.addEventListener("start", () => { this.camGoal = null; this.targetGoal = null; this.touch(); });
    this.renderer.domElement.addEventListener("wheel", () => this.touch(), { passive: true });
    this.renderer.domElement.addEventListener("pointerdown", () => this.touch());

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

    // paneles acústicos (gris pizarra, juntas verticales) y zócalo de madera: oficina técnica, no salón
    const paper = (base: string, joint: string) => canvasTex(256, 256, (g) => {
      g.fillStyle = base; g.fillRect(0, 0, 256, 256);
      g.fillStyle = joint;
      for (let x = 0; x < 256; x += 64) g.fillRect(x, 0, 2, 256);
      g.fillStyle = "rgba(255,255,255,.035)";
      for (let i = 0; i < 900; i++) g.fillRect((i * 37) % 256, (i * 91) % 256, 1, 1); // textura de fieltro
    }, [6, 1.2]);
    const H = 4.6;
    const backMat = new THREE.MeshStandardMaterial({ map: paper("#5d6b78", "#4f5c68"), roughness: 0.95 });
    const leftMat = new THREE.MeshStandardMaterial({ map: paper("#55626f", "#48545f"), roughness: 0.95 });
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
    [-3.9, 3.9].forEach((z) => {
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
      g.fillStyle = "#f3efe6"; g.fillRect(0, 0, 256, 360);
      // una tarjeta gráfica de perfil: PCB, disipador y dos ventiladores
      g.fillStyle = "#1f2937"; rr(g, 22, 70, 212, 104, 8); g.fill();
      g.fillStyle = "#4b5563"; for (let x = 30; x < 226; x += 8) g.fillRect(x, 76, 4, 92);
      [80, 176].forEach((cx) => {
        g.fillStyle = "#111827"; g.beginPath(); g.arc(cx, 122, 38, 0, 7); g.fill();
        g.strokeStyle = "#6b7280"; g.lineWidth = 3;
        for (let k = 0; k < 7; k++) { const a = (k / 7) * Math.PI * 2; g.beginPath(); g.moveTo(cx, 122); g.lineTo(cx + Math.cos(a) * 34, 122 + Math.sin(a) * 34); g.stroke(); }
        g.fillStyle = "#9ca3af"; g.beginPath(); g.arc(cx, 122, 9, 0, 7); g.fill();
      });
      g.fillStyle = "#15803d"; g.fillRect(22, 174, 212, 12);
      g.fillStyle = "#d4a017"; for (let x = 40; x < 210; x += 10) g.fillRect(x, 186, 6, 10); // conector PCIe
      g.fillStyle = "#1e232d"; g.font = `800 40px ${FONT}`; g.textAlign = "center";
      g.fillText("VRAM", 128, 262);
      g.fillStyle = "#b45309"; g.font = `800 28px ${FONT}`; g.fillText("ES ORO", 128, 296);
      g.fillStyle = "#6b7280"; g.font = `600 17px ${FONT}`; g.fillText("cuantiza con cabeza", 128, 330);
    });
    const pp = new THREE.Mesh(new THREE.PlaneGeometry(0.95, 1.33), new THREE.MeshStandardMaterial({ map: poster, roughness: 0.9 }));
    pp.rotation.y = Math.PI / 2;
    pp.position.set(LEFT + 0.17, 2.6, -6.2);
    s.add(pp);

    // placa con el nombre en la pared del fondo
    const plate = canvasTex(1024, 256, (g) => {
      g.fillStyle = "#1e232d"; rr(g, 0, 0, 1024, 256, 16); g.fill();
      g.fillStyle = "#e8e6e1"; g.font = `800 96px ${FONT}`; g.textAlign = "center"; g.textBaseline = "middle";
      g.fillText("LocalHarness", 512, 108);
      g.fillStyle = "#9aa0aa"; g.font = `600 34px ${FONT}`; g.fillText("LABORATORIO DE MODELOS · OFICINA DE AGENTES", 512, 186);
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
    for (const [id, tw] of this.towers) {
      const p = this.layout[`rack:${id}`];
      if (p) this.place(tw.group, p);
    }
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
    const o = this.objOf(id);
    if (!o) return;
    o.rotation.y += Math.PI / 2;
    const p = this.placement(o);
    this.layout[id] = p;
    this.onMove(id, p);
    this.buildLinks();
  }

  /** Coloca todo ordenado: tú al fondo, las mesas en una cuadrícula centrada y repartida por la sala (el director
   *  delante en el centro, luego por nombre; la última fila, centrada) y las torres en fila contra la pared. Devuelve
   *  las posiciones nuevas para guardarlas. */
  autoArrange(): Record<string, Placement> {
    const out: Record<string, Placement> = {};
    const all = [...this.stations.values()];
    const you = all.find((st) => st.spec.kind === "you");
    if (you) out[you.spec.id] = [YOU_POS[0], YOU_POS[1], 2];
    const desks = all.filter((st) => st.spec.kind !== "you").sort((a, b) =>
      Number(b.spec.kind === "director") - Number(a.spec.kind === "director") || a.spec.name.localeCompare(b.spec.name));
    // zona de mesas: sin la pared de las torres (izquierda), sin tu puesto (fondo) y con paso por delante
    const x0 = LEFT + 3.4, x1 = RX - 1.8, z0 = -1.2, z1 = FZ - 1.6;
    const GAP_X = 4.2, GAP_Z = 3.2; // mesa con PC y dos pantallas + silla + pasillo
    const n = desks.length;
    const maxCols = Math.max(1, Math.floor((x1 - x0) / GAP_X) + 1);
    const cols = Math.min(maxCols, Math.max(1, Math.ceil(Math.sqrt(n * 1.6))));
    const rows = Math.max(1, Math.ceil(n / cols));
    const dx = cols > 1 ? Math.min(5.2, (x1 - x0) / (cols - 1)) : 0;
    const dz = rows > 1 ? Math.min(3.6, Math.max(GAP_Z, (z1 - z0) / (rows - 1))) : 0;
    const cx = (x0 + x1) / 2;
    const zStart = Math.max(z0, (z0 + z1) / 2 - (dz * (rows - 1)) / 2);
    const snap = (v: number) => Math.round(v * 4) / 4;
    desks.forEach((st, i) => {
      const r = Math.floor(i / cols), c = i % cols;
      const inRow = Math.min(cols, n - r * cols);
      out[st.spec.id] = [snap(cx + (c - (inRow - 1) / 2) * dx), snap(zStart + r * dz), 2];
    });
    [...this.towers.keys()].forEach((id, i) => {
      const xz = RACK_SLOTS[Math.min(i, RACK_SLOTS.length - 1)];
      out[`rack:${id}`] = [xz[0], xz[1], 0];
    });
    for (const [id, p] of Object.entries(out)) {
      const o = this.objOf(id);
      if (o) this.place(o, p);
    }
    // «rack» a secas era la primera torre antes de haber varias: fuera, para que no pise a la nueva posición
    const { rack: _old, ...rest } = this.layout;
    this.layout = { ...rest, ...out };
    this.buildLinks();
    return { ...this.layout };
  }

  /** El grupo de un puesto o de una torre («rack:<servidor>»; «rack» a secas = la primera torre). */
  private objOf(id: string): THREE.Object3D | undefined {
    if (id === "rack") return this.towers.values().next().value?.group;
    if (id.startsWith("rack:")) return this.towers.get(id.slice(5))?.group;
    return this.stations.get(id)?.group;
  }

  private disposeTree(o: THREE.Object3D): void {
    o.traverse((x) => {
      const m = x as THREE.Mesh;
      m.geometry?.dispose();
      const mat = m.material as THREE.MeshBasicMaterial | undefined;
      mat?.map?.dispose();
      mat?.dispose?.();
    });
  }

  private removeStation(id: string): void {
    const st = this.stations.get(id);
    if (!st) return;
    if (st.trip) this.endTrip(st, true);
    this.scene.remove(st.group);
    this.disposeTree(st.group);
    this.clickable = this.clickable.filter((o) => o.userData.station !== id);
    this.stations.delete(id);
  }

  private screenTex(kind: "code" | "graph" = "code"): Station["screen"][number] {
    const c = document.createElement("canvas");
    c.width = 256; c.height = 160;
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    return { ctx: c.getContext("2d")!, tex, tick: Math.random() * 10, kind };
  }

  /** Pantalla: código que se va escribiendo al trabajar (la segunda, la gráfica de tokens/s y la VRAM); el logo y la
   *  hora en reposo. */
  private drawScreen(sc: Station["screen"][number], st: Station): void {
    const g = sc.ctx, acc = st.spec.color;
    g.fillStyle = "#0b1220"; g.fillRect(0, 0, 256, 160);
    if (sc.kind === "graph" && st.state !== "idle") {
      g.fillStyle = "#94a3b8"; g.font = `600 11px ${MONO}`; g.textAlign = "left";
      g.fillText("tokens/s", 10, 16);
      g.strokeStyle = "#1e293b"; g.lineWidth = 1;
      for (let y = 40; y < 130; y += 22) { g.beginPath(); g.moveTo(8, y); g.lineTo(248, y); g.stroke(); }
      g.strokeStyle = acc; g.lineWidth = 2.5; g.beginPath();
      for (let i = 0; i <= 40; i++) {
        const x = 8 + i * 6, v = 0.55 + Math.sin((sc.tick + i) * 0.7) * 0.18 + Math.sin((sc.tick + i) * 2.3) * 0.08;
        const y = 128 - v * 88;
        if (i) g.lineTo(x, y); else g.moveTo(x, y);
      }
      g.stroke();
      g.fillStyle = "#1e293b"; g.fillRect(10, 140, 236, 8);
      g.fillStyle = "#22c55e"; g.fillRect(10, 140, 236 * (0.62 + Math.sin(sc.tick * 0.3) * 0.08), 8);
      g.fillStyle = "#94a3b8"; g.fillText("VRAM", 200, 16);
      sc.tex.needsUpdate = true;
      return;
    }
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
    const monitor = (x: number, rotY = 0, kind: "code" | "graph" = "code", w = 1.0) => {
      const m = new THREE.Group();
      m.position.set(x, top + 0.04, 0.12);
      m.rotation.y = rotY;
      m.scale.set(w, 1, 1);
      g.add(m);
      own.push(put(new THREE.CylinderGeometry(0.16, 0.18, 0.03, 16), M(0x334155), m, 0, 0.015, 0));
      own.push(put(B(0.06, 0.32, 0.05), M(0x334155), m, 0, 0.17, 0.02));
      own.push(put(B(1.0, 0.62, 0.06), M(0x1e293b), m, 0, 0.55, 0));
      const sc = this.screenTex(kind);
      screens.push(sc);
      const face = new THREE.Mesh(new THREE.PlaneGeometry(0.92, 0.54), new THREE.MeshBasicMaterial({ map: sc.tex }));
      face.rotation.y = Math.PI;
      face.position.set(0, 0.55, -0.032);
      m.add(face);
      const logo = new THREE.Mesh(new THREE.CircleGeometry(0.07, 20), new THREE.MeshBasicMaterial({ color: acc }));
      logo.position.set(0, 0.6, 0.032);
      m.add(logo);
    };
    // dos pantallas en todos los puestos: código a la izquierda, tokens/s y VRAM a la derecha
    if (me) { monitor(-0.55, -0.12); monitor(0.55, 0.12, "graph"); } else { monitor(-0.42, -0.1, "code", 0.86); monitor(0.46, 0.14, "graph", 0.78); }
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
      const lx = dw / 2 - 0.16, lz = 0.36;
      P(new THREE.CylinderGeometry(0.1, 0.12, 0.03, 14), M(0x334155), g, lx, top + 0.055, lz);
      const arm = P(new THREE.CylinderGeometry(0.018, 0.018, 0.5, 6), M(0x334155), g, lx, top + 0.3, lz);
      arm.rotation.z = 0.25;
      const head = P(new THREE.ConeGeometry(0.1, 0.16, 14, 1, true), M(acc, { side: THREE.DoubleSide }), g, lx - 0.15, top + 0.52, lz - 0.05);
      head.rotation.z = -0.9;
      lampMat = M(0xfff7d6, { emissive: 0xffe9a8, emissiveIntensity: 0 });
      P(new THREE.SphereGeometry(0.04, 8, 6), lampMat, g, lx - 0.2, top + 0.47, lz - 0.05, false);
    }
    // el PC de la mesa: torre en el suelo, con ventana lateral que deja ver la GPU (tira del color del agente) y dos
    // ventiladores delante que giran al trabajar
    const pc = new THREE.Group();
    pc.position.set(-dw / 2 - 0.3, 0, 0.0);
    g.add(pc);
    P(B(0.34, 0.76, 0.74), M(0x1f2329, { roughness: 0.5 }), pc, 0, 0.4, 0);
    P(B(0.36, 0.03, 0.76), M(0x111418), pc, 0, 0.015, 0, false);
    const side = canvasTex(128, 128, (c) => {
      c.fillStyle = "#0d1117"; c.fillRect(0, 0, 128, 128);
      c.fillStyle = "#2d333b"; c.fillRect(14, 20, 100, 24); // placa base y RAM
      c.fillStyle = "#3b434d"; for (let k = 0; k < 4; k++) c.fillRect(84 + k * 7, 10, 4, 40);
      c.fillStyle = "#374151"; c.fillRect(10, 62, 108, 26); // la GPU
      c.fillStyle = acc; c.fillRect(10, 86, 108, 4);
      [38, 88].forEach((x) => { c.fillStyle = "#111827"; c.beginPath(); c.arc(x, 75, 11, 0, 7); c.fill(); });
      c.fillStyle = "#2d333b"; c.fillRect(14, 104, 100, 16); // fuente
    });
    const glassMat = new THREE.MeshStandardMaterial({ map: side, roughness: 0.15, metalness: 0.2 });
    [-1, 1].forEach((sx) => {
      const pane = P(new THREE.PlaneGeometry(0.62, 0.6), glassMat, pc, sx * 0.172, 0.42, 0, false);
      pane.rotation.y = sx * Math.PI / 2;
    });
    const pcGlow = new THREE.MeshStandardMaterial({ color: acc, emissive: acc, emissiveIntensity: 0.1 });
    const pcFans: THREE.Mesh[] = [];
    [0.58, 0.28].forEach((y) => {
      P(new THREE.TorusGeometry(0.11, 0.012, 6, 20), pcGlow, pc, 0, y, -0.372, false);
      const blade = P(B(0.2, 0.03, 0.01), M(0x4b5563), pc, 0, y, -0.375, false);
      put(B(0.03, 0.2, 0.01), M(0x4b5563), blade, 0, 0, 0, false);
      pcFans.push(blade);
    });
    P(new THREE.CylinderGeometry(0.018, 0.018, 0.01, 10), pcGlow, pc, 0.1, 0.72, -0.372, false).rotation.x = Math.PI / 2;

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
    own.push(put(B(0.68, 0.1, 0.62), S(0x2f343c), ch, 0, 0.47, 0));
    own.push(put(B(0.64, 0.7, 0.09), S(0x2f343c), ch, 0, 0.92, -0.32));
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
    const st: Station = { spec, group: g, ring, gem, screen: screens, eyes: chr.eyes, lamp: lampMat, char: chr,
      pc: { fans: pcFans, glow: pcGlow }, state: "idle", nextTrip: this.clock.elapsedTime + 8 + Math.random() * 20, trip: null };
    screens.forEach((sc) => this.drawScreen(sc, st));
    this.stations.set(spec.id, st);
  }

  /** Icono del agente (Font Awesome) en un círculo oscuro: va en el pecho del muñeco. Se redibuja cuando la fuente de
   *  iconos termina de cargar (la primera vez puede no estar). */
  private badgeTex(code: string, color: string): THREE.CanvasTexture {
    const c = document.createElement("canvas");
    c.width = c.height = 96;
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    const glyph = String.fromCodePoint(parseInt(code, 16));
    const draw = () => {
      const g = c.getContext("2d")!;
      g.clearRect(0, 0, 96, 96);
      g.fillStyle = "#1b1f25"; g.beginPath(); g.arc(48, 48, 46, 0, 7); g.fill();
      g.strokeStyle = color; g.lineWidth = 5; g.beginPath(); g.arc(48, 48, 41, 0, 7); g.stroke();
      g.fillStyle = color; g.font = `900 46px ${ICON_FONT}`; g.textAlign = "center"; g.textBaseline = "middle";
      g.fillText(glyph, 48, 50);
      tex.needsUpdate = true;
    };
    draw();
    document.fonts?.load(`900 46px ${ICON_FONT}`, glyph).then(draw).catch(() => {});
    return tex;
  }

  /** Muñeco androide. Todos llevan el mismo chasis (blanco roto con juntas grafito y visor oscuro con ojos LED); lo
   *  que distingue el TIPO es el casco o la pieza ciborg, y lo que distingue a CADA agente es el icono del pecho (el
   *  mismo que su avatar en el chat). El color del agente solo va en ese icono.
   *  you: gorra de capitán y corbata · director: casco de mando con cresta · jefe: medio casco con cascos y micro ·
   *  trabajador: casco de obra con linterna · consultas: banda con lupa · local: medio cráneo metálico, ojo rojo y
   *  brazo mecánico (corre en tu GPU) · otro: antena parabólica. */
  private buildCharacter(spec: StationSpec, own: THREE.Object3D[]) {
    const root = new THREE.Group(), acc = spec.color, me = spec.kind === "you", cyborg = spec.kind === "local";
    const T = <G extends THREE.BufferGeometry>(geo: G, mat: THREE.Material, parent: THREE.Object3D, x: number, y: number, z: number) => {
      const m = put(geo, mat, parent, x, y, z);
      own.push(m);
      return m;
    };
    const shell = S(0xe6e3dc), joint = S(0x2b2f36), metal = S(0x8b929c, { metalness: 0.7, roughness: 0.3 });
    const dark = S(0x15181d, { roughness: 0.2 });
    // cuerpo: cilindro con la base redondeada (torno) y una franja grafito en la cintura
    const prof = [new THREE.Vector2(0, 0), new THREE.Vector2(0.2, 0.0), new THREE.Vector2(0.28, 0.04),
      new THREE.Vector2(0.31, 0.12), new THREE.Vector2(0.31, 0.56), new THREE.Vector2(0.29, 0.6), new THREE.Vector2(0, 0.6)];
    T(new THREE.LatheGeometry(prof, 28), shell, root, 0, 0.0, 0);
    T(new THREE.CylinderGeometry(0.315, 0.315, 0.05, 28), joint, root, 0, 0.16, 0);
    T(new THREE.CylinderGeometry(0.3, 0.3, 0.035, 28), joint, root, 0, 0.625, 0); // cuello
    // el icono del agente en el pecho
    const badge = new THREE.Mesh(new THREE.CircleGeometry(0.11, 24),
      new THREE.MeshBasicMaterial({ map: this.badgeTex(spec.icon ?? "f544", acc), transparent: true }));
    badge.position.set(0, 0.4, 0.312);
    root.add(badge);
    own.push(badge);
    // piernas con la cadera como pivote: sentado apuntan hacia delante (-90°), de pie hacia abajo y al andar se balancean
    const legs = [-0.13, 0.13].map((x) => {
      const hip = new THREE.Group();
      hip.position.set(x, 0.06, 0);
      hip.rotation.x = -Math.PI / 2;
      root.add(hip);
      T(new THREE.CapsuleGeometry(0.085, 0.2, 6, 12), shell, hip, 0, -0.18, 0);
      T(new THREE.CylinderGeometry(0.09, 0.09, 0.05, 12), joint, hip, 0, -0.16, 0); // rodilla
      return hip;
    });
    const head = new THREE.Group();
    head.position.set(0, 0.65, 0);
    root.add(head);
    T(new THREE.SphereGeometry(0.3, 28, 14, 0, Math.PI * 2, 0, Math.PI / 2), shell, head, 0, 0.02, 0);
    T(new THREE.CircleGeometry(0.3, 28), shell, head, 0, 0.02, 0).rotation.x = Math.PI / 2;
    // visor oscuro y ojos LED (cian; el ciborg, un solo ojo rojo)
    T(new THREE.SphereGeometry(0.305, 28, 6, Math.PI * 0.18, Math.PI * 0.64, Math.PI * 0.2, Math.PI * 0.2), dark, head, 0, 0.02, 0);
    const eyes = new THREE.MeshStandardMaterial({ color: cyborg ? 0xff6b6b : 0xbff4ff, emissive: cyborg ? 0xe34948 : 0x38bdf8, emissiveIntensity: 0.15, roughness: 0.3 });
    (cyborg ? [0.11] : [-0.11, 0.11]).forEach((x) => T(new THREE.SphereGeometry(cyborg ? 0.05 : 0.04, 12, 10), eyes, head, x, 0.15, 0.27).scale.set(1, 1, 0.5));
    if (me) {
      // gorra de capitán y corbata
      const navy = S(0x1e2a44);
      T(new THREE.CylinderGeometry(0.27, 0.31, 0.12, 24), navy, head, 0, 0.27, 0);
      T(new THREE.CylinderGeometry(0.33, 0.33, 0.03, 24), navy, head, 0, 0.33, -0.02).scale.set(1, 1, 0.9);
      T(B(0.34, 0.02, 0.16), S(0x0f1626), head, 0, 0.22, 0.27).rotation.x = 0.25; // visera
      T(new THREE.SphereGeometry(0.035, 8, 6), S(0xfacc15, { metalness: 0.5 }), head, 0, 0.3, 0.27);
      T(B(0.09, 0.22, 0.02), S(0xdc2626), root, -0.17, 0.42, 0.3); // corbata (al lado del icono)
    } else if (spec.kind === "director") {
      // casco de mando: carcasa grafito con cresta y franja dorada
      const k = S(0x2b2f36, { metalness: 0.3 });
      T(new THREE.SphereGeometry(0.325, 28, 12, 0, Math.PI * 2, 0, Math.PI / 3.2), k, head, 0, 0.03, -0.01);
      T(B(0.05, 0.12, 0.5), k, head, 0, 0.36, -0.02);
      T(new THREE.TorusGeometry(0.315, 0.014, 6, 32), S(0xd4a017, { metalness: 0.6, roughness: 0.3 }), head, 0, 0.12, 0).rotation.x = Math.PI / 2;
      [-1, 1].forEach((sx) => T(B(0.03, 0.14, 0.12), k, head, sx * 0.31, 0.12, 0));
    } else if (spec.kind === "trabajador") {
      const y = S(0xfbbf24);
      T(new THREE.SphereGeometry(0.33, 20, 10, 0, Math.PI * 2, 0, Math.PI / 3), y, head, 0, 0.0, 0);
      T(new THREE.CylinderGeometry(0.36, 0.36, 0.025, 24), y, head, 0, 0.17, 0.04).scale.set(1, 1, 1.1);
      T(B(0.05, 0.03, 0.5), S(0xf59e0b), head, 0, 0.32, 0);
      T(new THREE.CylinderGeometry(0.045, 0.05, 0.06, 12), joint, head, 0, 0.2, 0.3).rotation.x = Math.PI / 2; // linterna
      T(new THREE.CircleGeometry(0.035, 12), new THREE.MeshBasicMaterial({ color: 0xfff3c4 }), head, 0, 0.2, 0.332);
    } else if (spec.kind === "jefe") {
      // gorro táctico con cascos y micro
      T(new THREE.SphereGeometry(0.318, 24, 10, 0, Math.PI * 2, 0, Math.PI / 3.6), S(0x3a4049), head, 0, 0.03, 0);
      T(new THREE.TorusGeometry(0.31, 0.025, 8, 24, Math.PI), joint, head, 0, 0.04, 0).rotation.y = Math.PI / 2;
      [-1, 1].forEach((sx) => T(new THREE.CylinderGeometry(0.085, 0.085, 0.07, 14), joint, head, sx * 0.31, 0.06, 0).rotation.z = Math.PI / 2);
      const mic = T(new THREE.CylinderGeometry(0.012, 0.012, 0.22, 6), joint, head, 0.24, -0.02, 0.15);
      mic.rotation.x = Math.PI / 2.4;
      T(new THREE.SphereGeometry(0.03, 8, 6), S(0x22c55e), head, 0.24, -0.06, 0.25);
    } else if (spec.kind === "consultas") {
      // banda de lectura con lupa abatible
      T(new THREE.TorusGeometry(0.305, 0.03, 8, 28), joint, head, 0, 0.2, 0).rotation.x = Math.PI / 2;
      T(B(0.02, 0.16, 0.02), joint, head, 0.12, 0.2, 0.3).rotation.x = 0.4;
      T(new THREE.TorusGeometry(0.06, 0.012, 6, 16), metal, head, 0.12, 0.13, 0.36);
      T(new THREE.CircleGeometry(0.055, 16), new THREE.MeshStandardMaterial({ color: 0xbfe3ff, transparent: true, opacity: 0.45 }), head, 0.12, 0.13, 0.362);
    } else if (cyborg) {
      // medio ciborg: la mitad izquierda del cráneo es metal con tornillos, un chip a la vista y un tubo al cuello
      T(new THREE.SphereGeometry(0.312, 24, 12, Math.PI * 1.5, Math.PI, 0, Math.PI / 2), metal, head, 0, 0.02, 0);
      [0.25, 0.5, 0.75].forEach((f) => T(new THREE.SphereGeometry(0.018, 6, 4), joint, head,
        -Math.sin(f * Math.PI) * 0.27, 0.18, Math.cos(f * Math.PI) * 0.27));
      T(B(0.14, 0.03, 0.14), dark, head, -0.1, 0.31, -0.02);
      T(B(0.1, 0.012, 0.1), new THREE.MeshStandardMaterial({ color: 0x86efac, emissive: 0x22c55e, emissiveIntensity: 0.7 }), head, -0.1, 0.33, -0.02);
      T(new THREE.TorusGeometry(0.16, 0.025, 6, 14, Math.PI * 0.8), joint, root, -0.22, 0.56, -0.05).rotation.set(0, Math.PI / 2, 0.4);
    } else {
      // otro: antena parabólica
      T(new THREE.CylinderGeometry(0.015, 0.015, 0.2, 8), joint, head, 0.1, 0.38, 0);
      T(new THREE.SphereGeometry(0.11, 16, 8, 0, Math.PI * 2, 0, Math.PI / 3), metal, head, 0.1, 0.52, 0).rotation.x = Math.PI;
    }
    const arm = (x: number, mech: boolean) => {
      const p = new THREE.Group();
      p.position.set(x, 0.5, 0.0);
      root.add(p);
      T(new THREE.SphereGeometry(0.075, 12, 8), joint, p, 0, 0, 0); // hombro
      if (mech) {
        // brazo mecánico: barra, codo y pinza
        T(new THREE.CylinderGeometry(0.035, 0.035, 0.32, 8), metal, p, 0, -0.2, 0);
        T(new THREE.SphereGeometry(0.05, 10, 8), joint, p, 0, -0.36, 0);
        [-1, 1].forEach((sd) => T(B(0.025, 0.1, 0.05), metal, p, sd * 0.035, -0.42, 0));
      } else {
        T(new THREE.CapsuleGeometry(0.07, 0.26, 6, 12), shell, p, 0, -0.2, 0);
      }
      return p;
    };
    return { root, head, L: arm(-0.39, cyborg), R: arm(0.39, false), legs, eyes };
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
      if (state !== "idle") this.headBack(st); // le ha llegado trabajo: a su sitio
      else st.nextTrip = this.clock.elapsedTime + 10 + Math.random() * 25;
    }
  }

  // ---------- torres de los modelos locales (una por llama-server encendido)
  // Cada una es un armario de 24U con puerta de cristal: switch arriba, el servidor GPU de 4U (ventiladores y LEDs de
  // la VRAM de SU GPU), dos nodos de 2U (LEDs de CPU) y, encima, la placa con el servidor y el modelo que tiene
  // cargado. La parte frontal mira a +x.
  /** Torres presentes: entra una por cada modelo encendido y sale cuando se apaga. */
  setRacks(specs: RackSpec[]): void {
    const want = new Set(specs.map((s) => s.id));
    for (const [id, tw] of this.towers) {
      if (!want.has(id)) {
        this.scene.remove(tw.group);
        this.disposeTree(tw.group);
        this.clickable = this.clickable.filter((o) => o.userData.station !== `rack:${id}`);
        this.towers.delete(id);
      }
    }
    const taken = (p: [number, number]) => [...this.towers.values()].some((t) =>
      Math.hypot(t.group.position.x - p[0], t.group.position.z - p[1]) < 1.0);
    specs.forEach((spec, i) => {
      const tw = this.towers.get(spec.id);
      if (tw) {
        const old = tw.spec;
        tw.spec = spec;
        if (old.model !== spec.model || old.name !== spec.name || old.gpuName !== spec.gpuName) this.drawTowerPlate(tw);
        return;
      }
      // dónde la dejaste (la primera hereda la posición del rack antiguo) o el primer hueco de la fila
      const saved = this.layout[`rack:${spec.id}`] ?? (i === 0 ? this.layout.rack : undefined);
      const xz = RACK_SLOTS.find((p) => !taken(p)) ?? RACK_SLOTS[0];
      this.buildTower(spec, saved ?? [xz[0], xz[1], 0]);
    });
  }

  private buildTower(spec: RackSpec, pos: Placement): void {
    const g = new THREE.Group();
    this.place(g, pos);
    g.scale.setScalar(0.01);
    this.scene.add(g);
    const FX = 0.45; // cara frontal de los equipos
    const own: THREE.Object3D[] = [];
    const floorTex = canvasTex(64, 64, (c) => {
      c.fillStyle = "#9aa3ad"; c.fillRect(0, 0, 64, 64);
      c.fillStyle = "#6b7480";
      for (let y = 4; y < 64; y += 8) for (let x = 4; x < 64; x += 8) { c.beginPath(); c.arc(x, y, 1.6, 0, 7); c.fill(); }
      c.strokeStyle = "#5b636e"; c.lineWidth = 2; c.strokeRect(1, 1, 62, 62);
    }, [1, 1]);
    put(B(1.3, 0.04, 1.3), new THREE.MeshStandardMaterial({ map: floorTex, roughness: 0.6, metalness: 0.3 }), g, 0.15, 0.02, 0, false);
    const frame = M(0x15181d, { metalness: 0.35, roughness: 0.5 });
    own.push(put(B(0.86, 2.3, 1.0), frame, g, 0, 1.2, 0));
    put(B(0.92, 0.06, 1.06), M(0x23272e, { metalness: 0.4 }), g, 0, 2.38, 0, false);
    [-0.46, 0.46].forEach((z) => put(B(0.88, 2.3, 0.03), M(0x0d1014), g, 0, 1.2, z, false));
    const ledRow = (y: number, z: number, n: number, dz = 0.06): Led[] => {
      const row: Led[] = [];
      for (let i = 0; i < n; i++) {
        const m = new THREE.Mesh(B(0.02, 0.03, 0.035), new THREE.MeshBasicMaterial({ color: 0x1f2937 }));
        m.position.set(FX + 0.005, y, z + i * dz);
        g.add(m);
        row.push(m);
      }
      return row;
    };
    const unit = (y: number, h: number, color: number) => put(B(0.06, h - 0.02, 0.84), M(color, { metalness: 0.3, roughness: 0.45 }), g, FX - 0.03, y, 0, false);
    let y = 2.18;
    unit(y, 0.12, 0x334155);
    const net = ledRow(y, -0.33, 11);
    // servidor GPU 4U: 3 ventiladores y 8 LEDs de VRAM
    y = 1.84;
    unit(y, 0.5, 0x0f172a);
    const fans: THREE.Mesh[] = [];
    for (let k = 0; k < 3; k++) {
      const z = -0.26 + k * 0.26;
      put(new THREE.TorusGeometry(0.1, 0.014, 6, 18), M(0x475569), g, FX + 0.005, y + 0.04, z, false).rotation.y = Math.PI / 2;
      const fan = put(B(0.01, 0.18, 0.032), M(0x64748b), g, FX + 0.008, y + 0.04, z, false);
      put(B(0.01, 0.032, 0.18), M(0x64748b), fan, 0, 0, 0, false);
      fans.push(fan);
    }
    const vram = ledRow(y - 0.18, -0.36, 8, 0.065);
    put(B(0.01, 0.05, 0.2), new THREE.MeshBasicMaterial({ color: spec.color }), g, FX + 0.006, y - 0.18, 0.28, false);
    const cpu: Led[][] = [];
    [1.3, 1.03].forEach((yy) => {
      unit(yy, 0.25, 0x1e293b);
      for (let k = 0; k < 5; k++) put(B(0.012, 0.16, 0.12), M(0x0b1220), g, FX + 0.004, yy, -0.34 + k * 0.15, false);
      cpu.push(ledRow(yy + 0.09, -0.36, 6, 0.13));
    });
    unit(0.66, 0.45, 0x0b1220);
    unit(0.3, 0.25, 0x1f2937);
    // puerta de cristal ahumado y asa
    const glass = new THREE.MeshStandardMaterial({ color: 0x0f172a, transparent: true, opacity: 0.18, roughness: 0.05, metalness: 0.5 });
    put(B(0.015, 2.2, 0.92), glass, g, FX + 0.06, 1.22, 0, false);
    put(B(0.03, 0.36, 0.04), M(0x9ca3af, { metalness: 0.8, roughness: 0.25 }), g, FX + 0.08, 1.3, 0.4, false);
    const lamp = M(spec.color, { emissive: spec.color, emissiveIntensity: 0.1 });
    put(new THREE.CylinderGeometry(0.06, 0.06, 0.1, 12), lamp, g, 0.25, 2.46, -0.3, false);
    // placa con el servidor y el modelo, encima de la puerta
    const c = document.createElement("canvas");
    c.width = 512; c.height = 128;
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = 8;
    const pm = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.225), new THREE.MeshBasicMaterial({ map: tex }));
    pm.position.set(FX + 0.075, 2.62, 0);
    pm.rotation.y = Math.PI / 2;
    g.add(pm);
    put(B(0.04, 0.27, 0.95), M(0x0d1014), g, FX + 0.05, 2.62, 0, false);
    own.forEach((m) => (m.userData.station = `rack:${spec.id}`));
    this.clickable.push(...own);
    const tw: Tower = { spec, group: g, fans, vram, net, cpu, lamp, plate: { ctx: c.getContext("2d")!, tex } };
    this.drawTowerPlate(tw);
    this.towers.set(spec.id, tw);
  }

  private drawTowerPlate(tw: Tower): void {
    const g = tw.plate.ctx, s = tw.spec;
    g.fillStyle = "#0d1014"; g.fillRect(0, 0, 512, 128);
    g.fillStyle = s.color; g.fillRect(0, 0, 8, 128);
    g.textAlign = "left"; g.textBaseline = "middle";
    g.fillStyle = "#e8e6e1"; g.font = `800 40px ${FONT}`;
    let m = s.model.replace(/\.gguf$/i, "");
    while (g.measureText(m).width > 480 && m.length > 6) m = m.slice(0, -1);
    g.fillText(m === s.model.replace(/\.gguf$/i, "") ? m : m + "…", 24, 46);
    g.fillStyle = "#9aa0aa"; g.font = `600 28px ${FONT}`;
    g.fillText(`${s.name}${s.gpuName ? ` · ${s.gpuName.replace(/^NVIDIA (GeForce )?/, "")}` : ""}`.slice(0, 34), 24, 96);
    tw.plate.tex.needsUpdate = true;
  }

  /** Memoria usada (0–1) y uso (0–1) de cada GPU, por índice: cada torre mira la suya. */
  setGpu(levels: number[], util: number[]): void {
    this.gpu = levels;
    this.gpuUtil = util;
    this.drawTv();
  }
  /** Uso de CPU y RAM del PC (0–1): los LEDs de los nodos de cada torre siguen la CPU. */
  setSystem(cpu: number, ram: number): void {
    this.cpuUse = cpu;
    void ram; // la RAM ya la enseña el panel de Recursos
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
    this.mkBoard(4.0, 2.2, -4.3, 2.55, z, 1024, 560, "wb");
    this.mkBoard(2.9, 2.2, 4.25, 2.55, z, 768, 560, "git");
    // bandeja de rotuladores bajo la pizarra
    put(B(3.6, 0.06, 0.18), M(0x8a6a4c), this.scene, -4.3, 1.38, z + 0.12, false);
    [0x2563eb, 0xdc2626, 0x16a34a].forEach((c, i) => put(new THREE.CylinderGeometry(0.025, 0.025, 0.22, 6), M(c), this.scene, -5.3 + i * 0.3, 1.43, z + 0.12, false).rotation.z = Math.PI / 2);
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
    this.plant(RX - 0.65, BACK + 0.7, 0.95, true);
    this.plant(LEFT + 0.8, FZ - 0.8, 0.9);
    this.bookshelf(LEFT + 1.75, BACK + 0.45);
    this.hardwareShelf(RX - 2.05, BACK + 0.45);
    // pantalla grande en la pared: memoria y uso de cada GPU (la dibuja drawTv con los datos de setGpu)
    put(B(2.3, 1.36, 0.08), M(0x111418), s, 0, 2.0, BACK + 0.2, false);
    const tc = document.createElement("canvas");
    tc.width = 640; tc.height = 360;
    const ttex = new THREE.CanvasTexture(tc);
    ttex.colorSpace = THREE.SRGBColorSpace;
    ttex.anisotropy = 8;
    const tv = new THREE.Mesh(new THREE.PlaneGeometry(2.18, 1.23), new THREE.MeshBasicMaterial({ map: ttex }));
    tv.position.set(0, 2.0, BACK + 0.25);
    s.add(tv);
    this.wallTv = { ctx: tc.getContext("2d")!, tex: ttex, at: 0 };
    this.drawTv();
    // rincón de descanso: sofá, mesa baja, alfombra
    const lounge = new THREE.Group();
    lounge.position.set(RX - 1.0, 0, FZ - 1.55);
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
    wc.position.set(RX - 0.7, 0, -2.3);
    s.add(wc);
    put(B(0.6, 1.1, 0.6), M(0xf1f5f9), wc, 0, 0.55, 0);
    put(new THREE.CylinderGeometry(0.26, 0.26, 0.62, 18), M(0x7dd3fc, { transparent: true, opacity: 0.75, flatShading: false }), wc, 0, 1.42, 0);
    put(B(0.12, 0.08, 0.06), M(0x2563eb), wc, 0, 0.85, 0.32);
    put(new THREE.CylinderGeometry(0.2, 0.16, 0.42, 14, 1, true), M(0x94a3b8, { side: THREE.DoubleSide }), s, RX - 0.65, 0.21, -1.3);
    // mueble de la impresora
    const c = new THREE.Group();
    c.position.set(RX - 0.8, 0, -4.7);
    s.add(c);
    put(B(0.9, 0.95, 1.3), M(WOOD), c, 0, 0.47, 0);
    put(B(0.6, 0.35, 0.7), M(0xe2e8f0), c, 0, 1.12, 0);
    put(B(0.4, 0.02, 0.5), M(0xffffff), c, 0, 1.31, 0.05);
    // rincón del café: encimera con cafetera, tazas y un microondas
    const k = new THREE.Group();
    k.position.set(RX - 0.7, 0, 1.3);
    s.add(k);
    put(B(0.7, 0.92, 1.7), M(0xe7e3da), k, 0, 0.46, 0);
    put(B(0.74, 0.05, 1.74), M(0x3f454d), k, 0, 0.945, 0);
    put(B(0.4, 0.5, 0.36), M(0x22262c), k, 0.05, 1.22, -0.4);
    put(B(0.06, 0.08, 0.2), M(0x9ca3af, { metalness: 0.7 }), k, -0.17, 1.18, -0.4);
    put(new THREE.CylinderGeometry(0.06, 0.05, 0.1, 12), M(0xffffff), k, -0.2, 1.02, -0.4);
    put(B(0.42, 0.28, 0.5), M(0xd1d5db), k, 0.05, 1.11, 0.35);
    put(B(0.02, 0.2, 0.3), M(0x111418), k, -0.17, 1.11, 0.3);
    [0.0, 0.12, 0.24].forEach((dz, i) => put(new THREE.CylinderGeometry(0.045, 0.04, 0.09, 10), M([0xeb6834, 0x2a78d6, 0x1baf7a][i]), k, -0.15, 1.015, -0.05 + dz));
    // sitios a los que van los muñecos libres (de pie delante, mirando al objeto)
    const R = Math.PI / 2;
    this.pois = [
      { name: "cafe", spots: [[RX - 1.65, 0.95], [RX - 1.65, 1.7]], face: R, taken: [] },
      { name: "impresora", spots: [[RX - 1.75, -4.7], [RX - 1.75, -4.0]], face: R, taken: [] },
      { name: "agua", spots: [[RX - 1.6, -2.3]], face: R, taken: [] },
      { name: "sofa", spots: [[RX - 1.0, FZ - 2.0], [RX - 1.0, FZ - 1.1]], face: -R, taken: [] },
      { name: "ventana", spots: [[LEFT + 0.75, 3.9]], face: -R, taken: [] },
      { name: "estanteria", spots: [[LEFT + 1.75, BACK + 1.35], [RX - 2.05, BACK + 1.35]], face: Math.PI, taken: [] },
    ];
    this.pois.forEach((p) => (p.taken = p.spots.map(() => null)));
  }

  /** Estantería de hardware: cajas de GPU, un portátil, discos y cables. */
  private hardwareShelf(x: number, z: number): void {
    const g = new THREE.Group();
    g.position.set(x, 0, z);
    this.scene.add(g);
    const w = 1.8, h = 2.6, d = 0.5, metal = M(0x3f454d, { metalness: 0.5, roughness: 0.4 });
    [-1, 1].forEach((sx) => [-1, 1].forEach((sz) => put(B(0.05, h, 0.05), metal, g, sx * (w / 2 - 0.03), h / 2, sz * (d / 2 - 0.03))));
    for (let r = 0; r < 4; r++) put(B(w, 0.04, d), metal, g, 0, 0.1 + r * 0.66, 0);
    // cajas de gráficas (negras con la franja verde) en la balda de arriba y la de abajo
    [0.12, 2.1].forEach((y) => {
      for (let k = 0; k < 4; k++) {
        const b = put(B(0.34, 0.26, 0.4), M(0x16191d), g, -0.6 + k * 0.4, y + 0.15, 0, false);
        put(B(0.345, 0.04, 0.405), M(0x76b900), b, 0, 0.06, 0, false);
      }
    });
    // discos y un switch pequeño
    for (let k = 0; k < 6; k++) put(B(0.1, 0.14, 0.3), M(k % 2 ? 0x9ca3af : 0x6b7280, { metalness: 0.5 }), g, -0.7 + k * 0.13, 0.86, 0, false);
    put(B(0.6, 0.06, 0.3), M(0x1f2937), g, 0.45, 0.82, 0, false);
    // portátil abierto y un rollo de cable
    put(B(0.45, 0.02, 0.3), M(0x9ca3af, { metalness: 0.6 }), g, -0.35, 1.47, 0.02, false);
    const lid = put(B(0.45, 0.3, 0.02), M(0x9ca3af, { metalness: 0.6 }), g, -0.35, 1.61, -0.13, false);
    lid.rotation.x = -0.25;
    put(new THREE.TorusGeometry(0.13, 0.035, 8, 20), M(0x2a78d6), g, 0.4, 1.5, 0, false).rotation.x = Math.PI / 2;
  }

  /** La pantalla de la pared: VRAM y uso de cada GPU. */
  private drawTv(): void {
    const tv = this.wallTv;
    if (!tv) return;
    const g = tv.ctx;
    g.fillStyle = "#0d1014"; g.fillRect(0, 0, 640, 360);
    g.fillStyle = "#e8e6e1"; g.font = `800 34px ${FONT}`; g.textAlign = "left"; g.textBaseline = "middle";
    g.fillText("GPUs", 32, 42);
    const d = new Date();
    g.fillStyle = "#9aa0aa"; g.font = `600 26px ${FONT}`; g.textAlign = "right";
    g.fillText(`${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`, 608, 42);
    g.textAlign = "left";
    if (!this.gpu.length) {
      g.fillStyle = "#6b7280"; g.font = `600 26px ${FONT}`; g.fillText("sin datos de nvidia-smi", 32, 190);
    }
    this.gpu.slice(0, 3).forEach((v, i) => {
      const y = 100 + i * 86, u = this.gpuUtil[i] ?? 0;
      g.fillStyle = "#cbd5e1"; g.font = `700 24px ${FONT}`; g.fillText(`GPU ${i}`, 32, y);
      g.fillStyle = "#9aa0aa"; g.font = `600 20px ${FONT}`;
      g.fillText(`VRAM ${Math.round(v * 100)} %`, 150, y); g.fillText(`uso ${Math.round(u * 100)} %`, 420, y);
      g.fillStyle = "#23272e"; g.fillRect(32, y + 22, 576, 14); g.fillRect(32, y + 42, 576, 6);
      g.fillStyle = v > 0.9 ? "#e34948" : v > 0.75 ? "#eda100" : "#1baf7a"; g.fillRect(32, y + 22, 576 * Math.min(1, v), 14);
      g.fillStyle = "#3987e5"; g.fillRect(32, y + 42, 576 * Math.min(1, u), 6);
    });
    tv.tex.needsUpdate = true;
  }

  // ---------- paseos: los muñecos libres se levantan a por un café, a la impresora, al sofá…
  /** Rejilla de celdas libres (true = se puede pisar) con lo que hay ahora en la sala, inflado medio cuerpo. */
  private walkGrid(): boolean[] {
    const free = new Array<boolean>(GX * GZ).fill(true);
    const block = (x0: number, x1: number, z0: number, z1: number, m = 0.3) => {
      const i0 = Math.max(0, Math.floor((x0 - m - LEFT) / CELL)), i1 = Math.min(GX - 1, Math.floor((x1 + m - LEFT) / CELL));
      const j0 = Math.max(0, Math.floor((z0 - m - BACK) / CELL)), j1 = Math.min(GZ - 1, Math.floor((z1 + m - BACK) / CELL));
      for (let i = i0; i <= i1; i++) for (let j = j0; j <= j1; j++) free[j * GX + i] = false;
    };
    // paredes (y un margen) y muebles fijos
    block(LEFT - 1, LEFT + 0.3, BACK - 1, BACK + D + 1, 0.2);
    block(W / 2 - 0.2, W / 2 + 1, BACK - 1, BACK + D + 1, 0.2);
    block(LEFT - 1, W / 2 + 1, BACK - 1, BACK + 0.35, 0.2);
    block(LEFT - 1, W / 2 + 1, BACK + D - 0.2, BACK + D + 1, 0.2);
    [[LEFT + 1.75, BACK + 0.45], [RX - 2.05, BACK + 0.45]].forEach(([x, z]) => block(x - 0.9, x + 0.9, z - 0.25, z + 0.25));
    [[RX - 0.65, BACK + 0.7], [LEFT + 0.8, FZ - 0.8]].forEach(([x, z]) => block(x - 0.35, x + 0.35, z - 0.35, z + 0.35));
    block(RX - 1.25, RX - 0.35, -4.7 - 0.65, -4.7 + 0.65, 0.2);       // impresora
    block(RX - 1.0, RX - 0.4, -2.6, -2.0, 0.2);                       // agua
    block(RX - 0.85, RX - 0.45, -1.5, -1.1, 0.1);                     // papelera
    block(RX - 1.05, RX - 0.35, 1.3 - 0.85, 1.3 + 0.85, 0.2);         // café
    block(RX - 2.25 - 0.33, RX - 2.25 + 0.33, FZ - 1.55 - 0.65, FZ - 1.55 + 0.65, 0.2); // mesa baja del sofá
    // puestos y torres (giran de cuarto en cuarto: la caja girada sigue siendo una caja)
    const boxOf = (o: THREE.Object3D, x0: number, x1: number, z0: number, z1: number, m = 0.3) => {
      const a = o.localToWorld(new THREE.Vector3(x0, 0, z0)), b = o.localToWorld(new THREE.Vector3(x1, 0, z1));
      block(Math.min(a.x, b.x), Math.max(a.x, b.x), Math.min(a.z, b.z), Math.max(a.z, b.z), m);
    };
    for (const st of this.stations.values()) {
      const dw = st.spec.kind === "you" ? 3.4 : 2.6;
      boxOf(st.group, -dw / 2 - 0.5, dw / 2, -0.6, 0.65, 0.25); // mesa y PC
      boxOf(st.group, -0.4, 0.4, -1.35, -0.6, 0.15);              // silla
    }
    for (const tw of this.towers.values()) boxOf(tw.group, -0.45, 0.5, -0.5, 0.5, 0.25);
    return free;
  }

  private cellOf(x: number, z: number): [number, number] {
    return [Math.min(GX - 1, Math.max(0, Math.floor((x - LEFT) / CELL))), Math.min(GZ - 1, Math.max(0, Math.floor((z - BACK) / CELL)))];
  }

  /** Camino de a a b (A* con diagonales, sin cortar esquinas) ya suavizado: solo los puntos donde gira. */
  private findPath(a: THREE.Vector3, b: THREE.Vector3): THREE.Vector3[] | null {
    const free = this.walkGrid();
    const near = ([i, j]: [number, number]): [number, number] | null => { // la celda libre más cercana
      for (let r = 0; r < 6; r++) {
        for (let di = -r; di <= r; di++) for (let dj = -r; dj <= r; dj++) {
          const ii = i + di, jj = j + dj;
          if (Math.max(Math.abs(di), Math.abs(dj)) === r && ii >= 0 && jj >= 0 && ii < GX && jj < GZ && free[jj * GX + ii]) return [ii, jj];
        }
      }
      return null;
    };
    const s = near(this.cellOf(a.x, a.z)), e = near(this.cellOf(b.x, b.z));
    if (!s || !e) return null;
    const key = (i: number, j: number) => j * GX + i;
    const goal = key(e[0], e[1]);
    const g = new Map<number, number>([[key(s[0], s[1]), 0]]), from = new Map<number, number>();
    const open: [number, number][] = [[key(s[0], s[1]), 0]];
    const h = (k: number) => Math.hypot((k % GX) - e[0], Math.floor(k / GX) - e[1]);
    let found = false;
    while (open.length) {
      let bi = 0;
      for (let q = 1; q < open.length; q++) if (open[q][1] < open[bi][1]) bi = q;
      const [cur] = open.splice(bi, 1)[0];
      if (cur === goal) { found = true; break; }
      const ci = cur % GX, cj = Math.floor(cur / GX);
      for (let di = -1; di <= 1; di++) for (let dj = -1; dj <= 1; dj++) {
        if (!di && !dj) continue;
        const ni = ci + di, nj = cj + dj;
        if (ni < 0 || nj < 0 || ni >= GX || nj >= GZ || !free[key(ni, nj)]) continue;
        if (di && dj && (!free[key(ci + di, cj)] || !free[key(ci, cj + dj)])) continue;
        const nk = key(ni, nj), cost = (g.get(cur) ?? 0) + (di && dj ? Math.SQRT2 : 1);
        if (cost < (g.get(nk) ?? Infinity)) {
          g.set(nk, cost);
          from.set(nk, cur);
          open.push([nk, cost + h(nk)]);
        }
      }
    }
    if (!found) return null;
    const cells: number[] = [goal];
    while (cells[0] !== key(s[0], s[1])) cells.unshift(from.get(cells[0])!);
    const pt = (k: number) => new THREE.Vector3(LEFT + ((k % GX) + 0.5) * CELL, 0, BACK + (Math.floor(k / GX) + 0.5) * CELL);
    const clear = (p: THREE.Vector3, q: THREE.Vector3) => {
      const n = Math.ceil(p.distanceTo(q) / (CELL / 3));
      for (let t = 1; t < n; t++) {
        const [i, j] = this.cellOf(p.x + ((q.x - p.x) * t) / n, p.z + ((q.z - p.z) * t) / n);
        if (!free[key(i, j)]) return false;
      }
      return true;
    };
    // suavizado: desde cada punto, salta al más lejano que se vea en línea recta
    const raw = cells.map(pt);
    const out = [raw[0]];
    let i = 0;
    while (i < raw.length - 1) {
      let j = raw.length - 1;
      while (j > i + 1 && !clear(raw[i], raw[j])) j--;
      out.push(raw[j]);
      i = j;
    }
    out.push(b.clone().setY(0));
    return out;
  }

  private exitOf(st: Station): THREE.Vector3 {
    return st.group.localToWorld(new THREE.Vector3(0, 0, -1.8)).setY(0);
  }

  private startTrip(st: Station): boolean {
    const options = this.pois.flatMap((p) => p.spots.map((_, k) => ({ p, k })).filter(({ p: q, k }) => !q.taken[k]));
    if (!options.length) return false;
    const { p, k } = options[Math.floor(Math.random() * options.length)];
    const spot = new THREE.Vector3(p.spots[k][0], 0, p.spots[k][1]);
    const exit = this.exitOf(st);
    const path = this.findPath(exit, spot);
    if (!path) return false;
    p.taken[k] = st.spec.id;
    const root = st.char.root;
    this.scene.attach(root); // sale del puesto: a partir de aquí se mueve en coordenadas de la sala
    root.position.y = 0.305;
    root.rotation.set(0, root.rotation.y, 0);
    st.trip = { phase: "out", path: [exit, ...path], k: 0, poi: p, spot: k, until: 0 };
    return true;
  }

  /** Vuelta a la silla (también si le llega trabajo: entonces sin esperar). */
  private headBack(st: Station): void {
    const tr = st.trip;
    if (!tr || tr.phase === "back") return;
    tr.poi.taken[tr.spot] = null;
    const root = st.char.root, here = root.position.clone().setY(0);
    const exit = this.exitOf(st), seat = st.group.localToWorld(new THREE.Vector3(0, 0, -0.92)).setY(0);
    const path = this.findPath(here, exit) ?? [exit];
    tr.path = [...path, seat];
    tr.k = 0;
    tr.phase = "back";
    root.position.y = 0.305;
  }

  /** Se sienta: el muñeco vuelve al puesto en su postura de siempre. */
  private endTrip(st: Station, _removing = false): void {
    const tr = st.trip;
    if (!tr) return;
    if (tr.phase !== "back") tr.poi.taken[tr.spot] = null;
    const ch = st.char;
    st.group.attach(ch.root);
    ch.root.position.set(0, 0.52, -0.92);
    ch.root.rotation.set(0, 0, 0);
    ch.legs.forEach((l) => (l.rotation.x = -Math.PI / 2));
    st.trip = null;
    st.nextTrip = this.clock.elapsedTime + 20 + Math.random() * 40;
  }

  /** Un fotograma del paseo: andar por el camino, quedarse un rato haciendo lo suyo y volver. */
  private stepTrip(st: Station, dt: number, t: number, i: number): void {
    const tr = st.trip!, ch = st.char, root = ch.root;
    if (tr.phase === "stay") {
      const sofa = tr.poi.name === "sofa";
      root.position.y += ((sofa ? 0.6 : 0.305) - root.position.y) * 0.15;
      const turn = tr.poi.face - root.rotation.y;
      root.rotation.y += Math.atan2(Math.sin(turn), Math.cos(turn)) * 0.1;
      ch.legs.forEach((l) => (l.rotation.x += ((sofa ? -Math.PI / 2 : 0) - l.rotation.x) * 0.15));
      const sip = (tr.poi.name === "cafe" || tr.poi.name === "agua") && Math.sin(t * 0.9 + i) > 0.55; // da un sorbo
      const busyHands = tr.poi.name === "impresora";
      ch.R.rotation.x += ((sip ? -2.3 : busyHands ? -1.1 + Math.sin(t * 5) * 0.12 : -0.3) - ch.R.rotation.x) * 0.12;
      ch.L.rotation.x += ((busyHands ? -1.1 + Math.cos(t * 5) * 0.12 : sofa ? -0.6 : -0.2) - ch.L.rotation.x) * 0.12;
      ch.R.rotation.z += (0 - ch.R.rotation.z) * 0.2;
      ch.head.rotation.x = tr.poi.name === "estanteria" ? -0.25 : tr.poi.name === "ventana" ? -0.05 : sip ? -0.2 : 0.05;
      ch.head.rotation.y = Math.sin(t * 0.6 + i) * 0.35;
      if (t > tr.until) this.headBack(st);
      return;
    }
    const target = tr.path[tr.k];
    const dx = target.x - root.position.x, dz = target.z - root.position.z, dist = Math.hypot(dx, dz);
    const speed = (st.state === "idle" ? WALK : WALK * 1.8) * dt;
    if (dist <= speed) {
      root.position.x = target.x;
      root.position.z = target.z;
      tr.k++;
      if (tr.k >= tr.path.length) {
        if (tr.phase === "out") {
          tr.phase = "stay";
          tr.until = t + 7 + Math.random() * 10;
        } else {
          this.endTrip(st);
        }
      }
    } else {
      root.position.x += (dx / dist) * speed;
      root.position.z += (dz / dist) * speed;
      // gira hacia donde va por el camino más corto
      const want = Math.atan2(dx, dz);
      let d = want - root.rotation.y;
      d = Math.atan2(Math.sin(d), Math.cos(d));
      root.rotation.y += d * 0.2;
    }
    const sw = Math.sin(t * 9 + i);
    ch.legs[0].rotation.x = sw * 0.55;
    ch.legs[1].rotation.x = -sw * 0.55;
    ch.L.rotation.x = -sw * 0.45 - 0.1;
    ch.R.rotation.x = sw * 0.45 - 0.1;
    ch.R.rotation.z += (0 - ch.R.rotation.z) * 0.2;
    ch.head.rotation.set(0.04, 0, 0);
    root.position.y = 0.305 + Math.abs(Math.cos(t * 9 + i)) * 0.035;
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
      const h = ray.intersectObjects(this.clickable, false);
      return h.length ? (h[0].object.userData.station as string) : null;
    };
    const objOf = (id: string) => this.objOf(id);
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

  // ---------- paquetes: un encargo que viaja de un puesto a otro («rack:<servidor>» = la torre de ese modelo)
  private world(o: THREE.Object3D, x: number, y: number, z: number): THREE.Vector3 {
    return o.localToWorld(new THREE.Vector3(x, y, z));
  }

  private anchor(id: string): THREE.Vector3 | null {
    if (id === "rack" || id.startsWith("rack:")) {
      const o = this.objOf(id) ?? this.objOf("rack");
      return o ? o.position.clone().add(new THREE.Vector3(0, 2.7, 0)) : null;
    }
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
    this.touch();
    if (k === "iso") return this.goto([ISO[0], ISO[1], ISO[2]], [0, 0.4, 0.4]);
    if (k === "rack" || k.startsWith("rack:")) {
      const o = this.objOf(k);
      if (!o) return;
      const r = o.position;
      return this.goto([r.x + 7.2, 4.2, r.z + 4.8], [r.x + 0.4, 1.7, r.z]);
    }
    const st = this.stations.get(k);
    if (!st) return;
    const c = this.world(st.group, 0, 1.0, -0.6);
    this.goto([c.x + 4.6, c.y + 3.4, c.z + 5.6], [c.x, c.y, c.z]);
  }

  /** Alguien ha tocado la oficina: fuera el modo cine hasta el siguiente rato quieto. */
  touch(): void {
    this.lastInput = this.clock.elapsedTime;
    this.cine = null;
  }

  get cineOn(): boolean {
    return !!this.cine;
  }

  /** Siguiente plano: general, quien trabaja, quien pasea o una torre (alternando con planos generales). */
  private nextShot(t: number): NonNullable<Office["cine"]> {
    this.shots++;
    const crew = [...this.stations.values()].filter((s) => s.spec.kind !== "you");
    const busy = crew.filter((s) => s.state !== "idle"), walking = crew.filter((s) => s.trip);
    const towers = [...this.towers.keys()];
    const a0 = 0.35 + Math.random() * 0.9; // siempre desde el lado abierto de la sala (sin paredes delante)
    const pickOf = <T,>(xs: T[]) => xs[Math.floor(Math.random() * xs.length)];
    if (this.shots % 2 === 1) return { kind: "orbit", id: "", start: t, until: t + 14, a0 };
    const options: { kind: "agent" | "tower"; id: string }[] = [
      ...busy.map((s) => ({ kind: "agent" as const, id: s.spec.id })), ...busy.map((s) => ({ kind: "agent" as const, id: s.spec.id })),
      ...walking.map((s) => ({ kind: "agent" as const, id: s.spec.id })),
      ...towers.map((id) => ({ kind: "tower" as const, id })),
      ...(busy.length + walking.length ? [] : crew.map((s) => ({ kind: "agent" as const, id: s.spec.id }))),
    ];
    const o = options.length ? pickOf(options) : null;
    return o ? { ...o, start: t, until: t + 10, a0 } : { kind: "orbit", id: "", start: t, until: t + 14, a0 };
  }

  private cineStep(t: number): void {
    if (!this.cine || t > this.cine.until) this.cine = this.nextShot(t);
    const c = this.cine, e = t - c.start;
    const pos = new THREE.Vector3(), tgt = new THREE.Vector3();
    if (c.kind === "orbit") {
      const a = 0.8 + Math.sin(c.a0 * 5 + e * 0.07) * 0.5, r = 23 - Math.sin(e * 0.05) * 3;
      pos.set(Math.cos(a) * r, 12.5 + Math.sin(e * 0.09) * 2, Math.sin(a) * r);
      tgt.set(0, 0.4, 0.6);
    } else {
      const st = c.kind === "agent" ? this.stations.get(c.id) : undefined;
      const tw = c.kind === "tower" ? this.towers.get(c.id) : undefined;
      if (st) st.char.root.getWorldPosition(tgt);
      else if (tw) tgt.copy(tw.group.position).setY(1.4);
      else { this.cine = null; return; }
      if (st) tgt.y += 0.8;
      const a = c.a0 + e * 0.04, r = tw ? 6.5 : 6;
      pos.set(tgt.x + Math.cos(a) * r, tgt.y + (tw ? 2.2 : 3.2), tgt.z + Math.sin(a) * r);
    }
    this.camera.position.lerp(pos, 0.02);
    this.controls.target.lerp(tgt, 0.02);
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
      const tw = id.startsWith("rack:") ? this.towers.get(id.slice(5)) : undefined;
      if (st?.trip) { st.char.root.getWorldPosition(this._v); this._v.y += 1.83; }
      else if (st) this._v.copy(this.world(st.group, 0, 2.35, -0.92));
      else if (tw) this._v.copy(tw.group.position).setY(3.05);
      else if (id === "wb") this._v.set(-4.3, 3.85, BACK + 0.3);
      else if (id === "git") this._v.set(4.25, 3.85, BACK + 0.3);
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
    const CINE_IDLE = 20;
    if (this.cinematic && !this.dragging && !this.camGoal && t - this.lastInput > CINE_IDLE && this.stations.size) this.cineStep(t);
    else if (!this.cinematic) this.cine = null;
    if (this.camGoal && this.targetGoal) {
      this.camera.position.lerp(this.camGoal, 0.07);
      this.controls.target.lerp(this.targetGoal, 0.07);
      if (this.camera.position.distanceTo(this.camGoal) < 0.08) { this.camGoal = null; this.targetGoal = null; }
    }
    let i = 0;
    const grow = (o: THREE.Object3D) => {
      if (o.scale.x < 1) o.scale.setScalar(Math.min(1, o.scale.x + (1.05 - o.scale.x) * 0.12));
    };
    for (const tw of this.towers.values()) grow(tw.group);
    // paseos: como mucho la mitad de los libres fuera de su mesa a la vez
    const crew = [...this.stations.values()].filter((s) => s.spec.kind !== "you");
    let away = crew.filter((s) => s.trip).length;
    const maxAway = Math.max(1, Math.ceil(crew.length / 2));
    for (const st of this.stations.values()) {
      grow(st.group);
      const ch = st.char, busy = st.state === "working", waiting = st.state === "waiting";
      const held = this.dragging?.id === st.spec.id;
      if (st.pc) {
        st.pc.fans.forEach((f) => (f.rotation.z += busy ? 0.45 : 0.04));
        st.pc.glow.emissiveIntensity += ((busy ? 1.1 : 0.15) - st.pc.glow.emissiveIntensity) * 0.08;
      }
      if (st.trip) {
        this.stepTrip(st, dt, t, i);
      } else {
        if (st.spec.kind !== "you" && st.state === "idle" && !held && !this.dragging && t > st.nextTrip && away < maxAway) {
          if (this.startTrip(st)) away++;
          else st.nextTrip = t + 15;
        }
        // brazos: teclear al trabajar, saludar si espera tu decisión, reposo si no
        ch.L.rotation.x += ((busy ? -1.2 + Math.sin(t * 14 + i) * 0.14 : held ? -2.6 : -0.5 + Math.sin(t * 1.5 + i) * 0.04) - ch.L.rotation.x) * 0.2;
        const rt = waiting ? Math.PI * 0.92 + Math.sin(t * 7) * 0.12 : busy ? -1.2 + Math.cos(t * 16 + i) * 0.14 : held ? -2.6 : -0.5 + Math.sin(t * 1.6 + i) * 0.04;
        ch.R.rotation.x += (rt - ch.R.rotation.x) * 0.18;
        ch.R.rotation.z += ((waiting ? -0.3 + Math.sin(t * 7) * 0.3 : 0) - ch.R.rotation.z) * 0.2;
        ch.head.rotation.y = Math.sin(t * 1.2 + i * 1.7) * (busy ? 0.08 : 0.25);
        ch.head.rotation.x = busy ? 0.1 : Math.sin(t * 0.9 + i) * 0.05;
        if (!st.trip) ch.root.position.y = 0.52 + (held ? 0.25 + Math.sin(t * 10) * 0.04 : st.state === "idle" ? Math.sin(t * 1.8 + i) * 0.015 : Math.abs(Math.sin(t * 7 + i)) * 0.01);
      }
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
    // torres: LEDs = VRAM de su GPU; ventiladores y parpadeo de red según el uso de esa GPU; CPU del PC
    const level = (m: Led, j: number, n: number, v: number) =>
      m.material.color.set(j < Math.round(Math.min(1, v) * n) ? (j / n < 0.6 ? 0x22c55e : j / n < 0.85 ? 0xf59e0b : 0xef4444) : 0x1f2937);
    for (const tw of this.towers.values()) {
      const s = tw.spec, v = this.gpu[s.gpu], u = this.gpuUtil[s.gpu] ?? 0, up = s.state === "ready" || s.state === "external";
      const loading = s.state === "loading";
      tw.vram.forEach((m, j) => {
        const blink = loading && Math.sin(t * 8 + j * 0.6) > 0;
        if (blink) m.material.color.set(0x38bdf8);
        else level(m, j, tw.vram.length, v ?? (up ? 0.35 : 0));
      });
      tw.fans.forEach((f) => (f.rotation.x += 0.03 + u * 0.5));
      tw.net.forEach((m, j) => m.material.color.set(up && Math.sin(t * (6 + u * 20) + j * 2.3) > 0.2 ? 0x22c55e : 0x1f2937));
      tw.cpu.forEach((row, k) => row.forEach((m, j) => level(m, j, row.length, this.cpuUse * (k ? 0.9 : 1.05) + Math.sin(t * 3 + j) * 0.03)));
      tw.lamp.emissiveIntensity = up ? 0.9 : loading ? 0.4 + Math.sin(t * 6) * 0.4 : s.state === "failed" ? (Math.sin(t * 3) > 0 ? 0.9 : 0) : 0.05;
    }
    if (this.wallTv && t - this.wallTv.at > 30) { this.wallTv.at = t; this.drawTv(); } // la hora
    this.placeLabels();
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  };
}

