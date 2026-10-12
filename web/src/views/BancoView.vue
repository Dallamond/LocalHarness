<script setup lang="ts">
// Banco de pruebas: montar tandas (prueba × modelos × agente × repeticiones), ponerlas en cola y dejarlas corriendo
// solas; abajo, los resultados por configuración con varias tiradas (media, mejor y peor). La cola la procesa un
// proceso aparte (localharness/banco_cola.py); el detalle de cada ejecución sigue en el visor (/banco).
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import Card from "../components/Card.vue";
import StatusChip from "../components/StatusChip.vue";
import { api, live, post, refreshAll, type LlamaInfo } from "../api";

interface Ficha { nombre: string; titulo: string; tipo: string; grupo?: string; modalidades: Record<string, { parches: number }> }
interface Repertorio { nombre: string; titulo: string; descripcion?: string; minutos_tarea: number; casos: string[] }
interface Celda { tiradas: number; aprobados: number; media: number }
interface Matriz { repertorio: string; titulo: string; contendientes: string[];
  filas: { caso: string; titulo: string; grupo: string; celdas: Record<string, Celda> }[];
  totales: Record<string, { casos: number; aprobados: number; tiradas: number; media: number | null }> }
interface Cont {
  nombre: string; descripcion?: string; agente: string; modelos?: Record<string, string | null>;
  pensamiento?: Record<string, string>; linea?: number; reparar?: number; relevo?: string;
  horas: number; minutos_tarea: number; presupuesto: number;
}
interface Ejec { id: string; prueba: string; modalidad: string; estado: string; contendiente: string; inicio: string;
  totales: { nota?: number | null } | null }
interface Corta { id: string; nota: number | null; integrados: number | null; parches: number | null; minutos: number;
  curva?: [number, number | null, string][]; inicio?: string;
  estado: string; hechos?: number }
interface Tanda {
  id: string; prueba: string; modalidad: string; repeticiones: number; contendiente: Cont;
  estado: "pendiente" | "en marcha" | "hecha" | "parada" | "error"; hechas: string[]; actual: string | null;
  error: string | null; resultados: Corta[]; media: number | null; en_curso: Corta | null;
  total: number; repertorio?: string; casos?: string[]; de_casos?: number;
}
interface Grupo { prueba: string; modalidad: string; contendiente: string; agente: string; descripcion: string;
  tiradas: number; media: number; mejor: number; peor: number; integrados: number; parches: number;
  minutos: number; ultima: string }
interface Cola { tandas: Tanda[]; parar: string | null; corriendo: boolean; log: string; resumen: Grupo[]; matrices: Matriz[] }

const pruebas = ref<Ficha[]>([]);
const casos = ref<Ficha[]>([]);
const repertorios = ref<Repertorio[]>([]);
const guardados = ref<Cont[]>([]);
const ejecuciones = ref<Ejec[]>([]);
const llama = ref<LlamaInfo | null>(null);
const cola = ref<Cola | null>(null);
const error = ref("");
const aviso = ref("");
const busy = ref(false);

const KEEP = "__keep__"; // modelo: no tocar el que esté cargado
const OFF = "__off__"; // modelo: apagar ese servidor
const PENSAR = ["normal", "apagado", "profundo"];

const form = reactive({
  prueba: "", modalidad: "", repeticiones: 3, partir: "", agente: "Jefe local 2",
  modelos: {} as Record<string, string>, pensamiento: {} as Record<string, string>,
  linea: 0, reparar: 0, relevo: "", horas: 12, minutos_tarea: 45, presupuesto: 1,
  nombre: "", nombreTocado: false, descripcion: "",
});

async function cargar() {
  // cada parte por su lado: si una falla (p. ej. un servidor viejo sin la cola), el resto se ve igual
  const [b, l, c] = await Promise.allSettled([
    api<{ pruebas: Ficha[]; casos: Ficha[]; repertorios: Repertorio[]; contendientes: Cont[]; ejecuciones: Ejec[] }>("/api/banco"),
    api<LlamaInfo>("/api/llama"),
    api<Cola>("/api/banco/cola"),
  ]);
  const fallos: string[] = [];
  if (b.status === "fulfilled") {
    pruebas.value = b.value.pruebas;
    casos.value = b.value.casos ?? [];
    repertorios.value = b.value.repertorios ?? [];
    guardados.value = b.value.contendientes;
    ejecuciones.value = b.value.ejecuciones;
    if (!form.prueba && b.value.pruebas.length) form.prueba = b.value.pruebas[0].nombre;
  } else fallos.push(`pruebas: ${(b.reason as Error).message}`);
  if (l.status === "fulfilled") {
    llama.value = l.value;
    for (const s of l.value.servers) {
      if (!(s.id in form.modelos)) form.modelos[s.id] = KEEP;
      if (!(s.id in form.pensamiento)) form.pensamiento[s.id] = "normal";
    }
  } else fallos.push(`modelos: ${(l.reason as Error).message}`);
  if (c.status === "fulfilled") cola.value = c.value;
  else fallos.push(`cola: ${(c.reason as Error).message} (¿LocalHarness sin reiniciar tras actualizar?)`);
  error.value = fallos.join(" · ");
}
async function refrescarCola() {
  try {
    cola.value = await api<Cola>("/api/banco/cola");
  } catch {
    /* sin conexión un momento: la siguiente vuelta lo vuelve a intentar */
  }
}
let timer: ReturnType<typeof setInterval>;
onMounted(async () => {
  if (!live.agents.length) await refreshAll().catch(() => undefined);
  await cargar();
  timer = setInterval(refrescarCola, 4000);
});
onUnmounted(() => clearInterval(timer));

const REP = "rep:";
const repertorio = computed(() => (form.prueba.startsWith(REP)
  ? repertorios.value.find((r) => r.nombre === form.prueba.slice(REP.length)) : undefined));
// en un repertorio se puede correr solo una parte de los casos (5 en vez de 22: resultados en minutos, no en una hora)
const elegidos = ref<string[]>([]);
watch(repertorio, (r) => { elegidos.value = r ? [...r.casos] : []; }, { immediate: true });
const nCasos = computed(() => elegidos.value.length);
function alAzar(k: number) {
  const todos = [...(repertorio.value?.casos ?? [])];
  for (let i = todos.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [todos[i], todos[j]] = [todos[j], todos[i]];
  }
  const sel = new Set(todos.slice(0, k));
  elegidos.value = (repertorio.value?.casos ?? []).filter((c) => sel.has(c));
}
function alternar(c: string) {
  const sel = new Set(elegidos.value);
  if (sel.has(c)) sel.delete(c); else sel.add(c);
  elegidos.value = (repertorio.value?.casos ?? []).filter((x) => sel.has(x));
}
const prueba = computed(() => pruebas.value.find((p) => p.nombre === form.prueba));
const modalidades = computed(() => Object.entries(prueba.value?.modalidades ?? {}));
watch(() => form.prueba, () => {
  if (!prueba.value?.modalidades[form.modalidad]) form.modalidad = modalidades.value[0]?.[0] ?? "";
  form.relevo = "";
});
const servidores = computed(() => llama.value?.servers ?? []);
const modelos = computed(() => [...(llama.value?.models ?? [])].sort((a, b) => a.name.localeCompare(b.name)));
const agentes = computed(() => [...live.agents].filter((a) => !a.config.off)
  .sort((a, b) => Number(b.provider === "local_boss") - Number(a.provider === "local_boss") || a.name.localeCompare(b.name)));
const agente = computed(() => live.agents.find((a) => a.name === form.agente));
const gastaPlan = computed(() => !!agente.value && !["local_boss", "local", "local_agent"].includes(agente.value.provider));
const relevos = computed(() => ejecuciones.value.filter((e) => e.prueba === form.prueba && e.modalidad === form.modalidad
  && e.estado === "terminada").sort((a, b) => b.inicio.localeCompare(a.inicio)));

// partir de un contendiente guardado: rellena el formulario
watch(() => form.partir, (n) => {
  const c = guardados.value.find((g) => g.nombre === n);
  if (!c) return;
  form.agente = c.agente;
  for (const s of servidores.value) {
    const m = c.modelos ? c.modelos[s.id] : undefined;
    form.modelos[s.id] = m === undefined ? KEEP : m === null ? OFF : modelos.value.find((x) => [x.name, x.file, x.path].includes(m))?.name ?? KEEP;
    form.pensamiento[s.id] = c.pensamiento?.[s.id] ?? "normal";
  }
  Object.assign(form, { linea: c.linea ?? 0, reparar: c.reparar ?? 0, horas: c.horas, minutos_tarea: c.minutos_tarea,
    presupuesto: c.presupuesto, descripcion: c.descripcion ?? "", nombre: c.nombre, nombreTocado: true });
  form.relevo = c.relevo && relevos.value.some((e) => e.id === c.relevo) ? c.relevo : "";
});

// nombre automático: modelos + agente + opciones («gpt-oss-20b-qwen3.5-4b-jefe-local-2-l1»), editable
const corto = (m: string) => m.toLowerCase().replace(/^[a-z0-9]+_(?=[a-z])/, "").replace(/[-_.]?(ud-)?(i?q\d.*|f16|bf16|mxfp4.*)$/, "");
const slug = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9.]+/g, "-").replace(/^-|-$/g, "");
const nombreAuto = computed(() => {
  const ms = servidores.value.map((s) => form.modelos[s.id]).filter((m) => m && m !== KEEP && m !== OFF).map(corto);
  const partes = [...ms, slug(form.agente), form.linea ? `l${form.linea}` : "", form.reparar ? `r${form.reparar}` : "",
    form.relevo ? "relevo" : ""];
  return slug(partes.filter(Boolean).join("-")).slice(0, 60) || "contendiente";
});
watch(nombreAuto, (n) => { if (!form.nombreTocado) form.nombre = n; }, { immediate: true });

function contendiente(): Cont & Record<string, unknown> {
  const mods: Record<string, string | null> = {};
  const pens: Record<string, string> = {};
  for (const s of servidores.value) {
    const m = form.modelos[s.id];
    if (m === OFF) mods[s.id] = null;
    else if (m && m !== KEEP) mods[s.id] = m;
    if (m !== OFF && form.pensamiento[s.id] && form.pensamiento[s.id] !== "normal") pens[s.id] = form.pensamiento[s.id];
  }
  return {
    nombre: form.nombre.trim(), agente: form.agente, descripcion: form.descripcion.trim() || undefined,
    modelos: Object.keys(mods).length ? mods : undefined, pensamiento: Object.keys(pens).length ? pens : undefined,
    linea: form.linea || undefined, reparar: form.reparar || undefined, relevo: form.relevo || undefined,
    horas: form.horas, minutos_tarea: form.minutos_tarea, presupuesto: form.presupuesto,
  };
}

async function hacer(fn: () => Promise<unknown>, ok = "") {
  error.value = "";
  aviso.value = "";
  busy.value = true;
  try {
    await fn();
    aviso.value = ok;
    await refrescarCola();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
// El formulario no usa la validación del navegador (con un campo fuera de rango bloqueaba el envío sin decir nada,
// y el aviso quedaba dentro del desplegable cerrado): se revisa aquí y el motivo sale junto al botón.
const formError = ref("");
const formAviso = ref("");
function revisar(): string {
  const n = (v: unknown) => typeof v === "number" && Number.isFinite(v);
  if (!form.prueba) return "Elige una prueba.";
  if (!repertorio.value && !form.modalidad) return "Elige una modalidad.";
  if (repertorio.value && !nCasos.value) return "Marca al menos un caso.";
  if (!n(form.repeticiones) || !Number.isInteger(form.repeticiones) || form.repeticiones < 1 || form.repeticiones > 50)
    return "Repeticiones: un número entero de 1 a 50.";
  if (!/^[a-z0-9][a-z0-9._-]{0,60}$/.test(form.nombre.trim()))
    return "Nombre del contendiente: minúsculas, números, «-», «_» o «.» (máx. 60), sin espacios.";
  if (!n(form.horas) || form.horas < 0.1 || form.horas > 48) return "Horas como máximo: de 0,1 a 48 (en «Topes y descripción»).";
  if (!n(form.minutos_tarea) || form.minutos_tarea < 1 || form.minutos_tarea > 240) return "Minutos por tarea: de 1 a 240 (en «Topes y descripción»).";
  if (!n(form.presupuesto) || form.presupuesto < 0 || form.presupuesto > 100) return "Presupuesto: de 0 a 100 (en «Topes y descripción»).";
  if (!gastaPlan.value && form.presupuesto < 1) return "Con un agente local el presupuesto tiene que ser al menos 1 (si no, el autopiloto se para nada más empezar).";
  return "";
}
async function enviar(fn: () => Promise<unknown>, ok: string) {
  formError.value = revisar();
  formAviso.value = "";
  if (formError.value) return;
  busy.value = true;
  try {
    await fn();
    formAviso.value = ok;
    await refrescarCola();
  } catch (e) {
    formError.value = `No se pudo: ${(e as Error).message}`;
  } finally {
    busy.value = false;
  }
}
const anadir = () => enviar(() => post("/api/banco/cola", repertorio.value
  ? { repertorio: repertorio.value.nombre, repeticiones: form.repeticiones, contendiente: contendiente(),
      casos: nCasos.value < repertorio.value.casos.length ? elegidos.value : null }
  : { prueba: form.prueba, modalidad: form.modalidad, repeticiones: form.repeticiones, contendiente: contendiente() }),
`Añadida a la cola: ${form.repeticiones}× ${form.nombre.trim()}. ${cola.value?.corriendo ? "Se hará cuando acabe lo que hay delante." : "Pulsa Empezar en la tarjeta Cola."}`);
const guardar = () => enviar(async () => {
  await post("/api/banco/contendientes", { contendiente: contendiente() });
  await cargar();
}, `Guardado como banco/contendientes/${form.nombre.trim()}.json`);
const empezar = () => hacer(() => post("/api/banco/cola/empezar"));
const parar = (modo: "despues" | "ya") => hacer(() => post("/api/banco/cola/parar", { modo }));
const mover = (t: Tanda, delta: number) => hacer(() => post(`/api/banco/cola/${t.id}/mover`, { delta }));
const reabrir = (t: Tanda) => hacer(() => post(`/api/banco/cola/${t.id}/reabrir`));
const quitar = (t: Tanda) => hacer(() => api(`/api/banco/cola/${t.id}`, { method: "DELETE" }));

const pendientes = computed(() => (cola.value?.tandas ?? []).filter((t) => t.estado === "pendiente" || t.estado === "en marcha"));
const estadoCola = computed(() => {
  const c = cola.value;
  if (!c) return { state: "off" as const, text: "…" };
  if (c.corriendo) return c.parar ? { state: "warn" as const, text: c.parar === "ya" ? "parando ya…" : "para al acabar esta ejecución" }
    : { state: "pending" as const, text: "corriendo" };
  return pendientes.value.length ? { state: "off" as const, text: `parada · ${pendientes.value.length} tanda(s) esperando` }
    : { state: "off" as const, text: "vacía" };
});
const CHIP: Record<Tanda["estado"], "ok" | "warn" | "crit" | "pending" | "off"> = {
  pendiente: "off", "en marcha": "pending", hecha: "ok", parada: "warn", error: "crit",
};
const titulo = (p: string) => pruebas.value.find((x) => x.nombre === p)?.titulo
  ?? repertorios.value.find((x) => x.nombre === p)?.titulo ?? p;
const casoDe = (id: string) => id.split("/")[0].replace(/-caso$/, "");
const fichaCaso = (n: string) => casos.value.find((c) => c.nombre === n);
// en una tanda de repertorio, cada pastilla es un caso: los tangibles (web, juego) se abren tal cual los dejó el modelo
const enlace = (t: Tanda, r: Corta) => (t.repertorio && fichaCaso(casoDe(r.id))?.grupo === "tangible"
  ? `/banco/abrir/${r.id}/` : "/banco");
const etiqueta = (t: Tanda, r: Corta) => (t.repertorio ? `${casoDe(r.id)} · ${r.nota ?? "—"}` : `${r.nota ?? "—"} %`);
const tonoCelda = (c: Celda | undefined) => (!c ? "" : c.aprobados === c.tiradas ? "nota-alta" : c.aprobados ? "nota-media" : "nota-baja");
const GRUPO: Record<string, string> = { escribir: "Escribir", tests: "Tests", diagnosticar: "Diagnosticar",
  arreglar: "Arreglar", ampliar: "Ampliar", varios: "Varios archivos", tangible: "Web y juegos" };
const modelosDe = (c: Cont) => Object.entries(c.modelos ?? {}).map(([s, m]) => `${s}: ${m === null ? "apagado" : corto(m)}`).join(" · ")
  || "los modelos que estén cargados";
const extras = (c: Cont) => [c.linea ? `línea ×${c.linea}` : "", c.reparar ? `reparación ×${c.reparar}` : "",
  c.relevo ? `relevo de ${c.relevo.split("/")[1]}` : ""].filter(Boolean).join(" · ");
const tono = (n: number | null | undefined) => (n == null ? "" : n >= 80 ? "nota-alta" : n >= 40 ? "nota-media" : "nota-baja");
// ---------- en vivo: la tanda que corre
const enMarcha = computed(() => (cola.value?.corriendo ? cola.value.tandas.find((t) => t.estado === "en marcha") : undefined));

/** Repertorio: los casos de la vuelta en curso, cada uno hecho (con su nota), en curso o pendiente. */
const tira = computed(() => {
  const t = enMarcha.value;
  if (!t?.repertorio || !t.casos?.length) return null;
  const n = t.casos.length;
  const hechas = t.resultados.length;
  const vuelta = Math.min(Math.floor(hechas / n), t.repeticiones - 1);
  const celdas = t.casos.map((caso, k) => {
    const i = vuelta * n + k;
    const r = t.resultados[i];
    return { caso, titulo: fichaCaso(caso)?.titulo ?? caso, grupo: fichaCaso(caso)?.grupo ?? "",
      estado: r ? "hecho" : i === hechas && t.en_curso ? "curso" : "pendiente", r };
  });
  const notas = t.resultados.map((r) => r.nota ?? 0);
  const gastado = t.resultados.reduce((a, r) => a + (r.minutos || 0), 0);
  const restantes = t.total - hechas;
  return {
    celdas, vuelta: vuelta + 1, vueltas: t.repeticiones, hechas, total: t.total,
    aprobados: notas.filter((x) => x >= 100).length, media: notas.length ? Math.round((notas.reduce((a, b) => a + b, 0) / notas.length) * 10) / 10 : null,
    gastado, falta: hechas ? (gastado / hechas) * restantes : null,
  };
});

/** Prueba larga: la curva de nota parche a parche de la ejecución en curso y de las repeticiones anteriores. */
const W = 640, H = 220, M = { l: 36, r: 12, t: 12, b: 28 };
const grafica = computed(() => {
  const t = enMarcha.value;
  if (!t || t.repertorio || !t.en_curso) return null;
  const total = Math.max(t.en_curso.parches ?? 1, ...t.resultados.map((r) => r.curva?.length ?? 0), 1);
  const x = (n: number) => M.l + ((n - 0.5) / total) * (W - M.l - M.r);
  const y = (v: number) => H - M.b - (v / 100) * (H - M.t - M.b);
  const linea = (curva: Corta["curva"]) => (curva ?? []).filter((c) => c[1] != null)
    .map((c, i) => `${i ? "L" : "M"}${x(c[0]).toFixed(1)},${y(c[1] as number).toFixed(1)}`).join(" ");
  const puntos = (t.en_curso.curva ?? []).filter((c) => c[1] != null)
    .map((c) => ({ n: c[0], v: c[1] as number, cx: x(c[0]), cy: y(c[1] as number), res: c[2] }));
  const ticksX = Array.from({ length: total }, (_, i) => i + 1).filter((n) => total <= 12 || n % Math.ceil(total / 12) === 0 || n === 1);
  return {
    actual: linea(t.en_curso.curva), previas: t.resultados.map((r) => linea(r.curva)).filter(Boolean), puntos,
    ticksX: ticksX.map((n) => ({ n, x: x(n) })), ticksY: [0, 25, 50, 75, 100].map((v) => ({ v, y: y(v) })),
    hechos: t.en_curso.hechos ?? 0, total, ultima: puntos.at(-1)?.v ?? null, rep: t.resultados.length + 1, reps: t.repeticiones,
  };
});
const ICONO: Record<string, string> = { "nota-alta": "fa-check", "nota-media": "fa-circle-half-stroke", "nota-baja": "fa-xmark" };

const minutos = (m: number) => (m >= 60 ? `${Math.floor(m / 60)} h ${Math.round(m % 60)} min` : `${Math.round(m)} min`);

const grupos = computed(() => {
  const out: Record<string, Grupo[]> = {};
  for (const g of cola.value?.resumen ?? []) (out[`${titulo(g.prueba)} · ${g.modalidad}`] ??= []).push(g);
  return Object.entries(out);
});
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2 class="title">Banco de pruebas</h2>
      <p>Monta tandas (una prueba con unos modelos y un agente, varias veces), ponlas en cola y déjalas corriendo. Cada ejecución empieza el proyecto desde cero y se puntúa con el examen oculto.</p>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="aviso" class="aviso">{{ aviso }}</p>

    <Card v-if="enMarcha" :title="`En vivo · ${titulo(enMarcha.prueba)}${enMarcha.repertorio ? '' : ` · ${enMarcha.modalidad}`}`"
          :subtitle="`${enMarcha.contendiente.nombre} · ${enMarcha.contendiente.agente}`">
      <template v-if="tira">
        <div class="vivo__cifras">
          <div><b>{{ tira.hechas }}/{{ tira.total }}</b><span>casos hechos{{ tira.vueltas > 1 ? ` · vuelta ${tira.vuelta}/${tira.vueltas}` : "" }}</span></div>
          <div><b>{{ tira.aprobados }}</b><span>aprobados (nota 100)</span></div>
          <div><b>{{ tira.media ?? "—" }}{{ tira.media != null ? " %" : "" }}</b><span>nota media</span></div>
          <div><b>{{ minutos(tira.gastado) }}</b><span>{{ tira.falta != null ? `quedan unos ${minutos(tira.falta)}` : "calculando lo que queda…" }}</span></div>
        </div>
        <div class="barra" role="progressbar" :aria-valuenow="tira.hechas" :aria-valuemax="tira.total"><span :style="{ width: `${(100 * tira.hechas) / tira.total}%` }" /></div>
        <ol class="tira">
          <li v-for="c in tira.celdas" :key="c.caso" class="tira__caso" :class="[`is-${c.estado}`, c.r ? tono(c.r.nota) : '']"
              :title="c.r ? `${c.titulo} · nota ${c.r.nota} · ${minutos(c.r.minutos)}` : c.titulo">
            <span class="tira__grupo">{{ GRUPO[c.grupo] ?? c.grupo }}</span>
            <span class="tira__titulo">{{ c.titulo }}</span>
            <span v-if="c.r" class="tira__nota"><i class="fa-solid" :class="ICONO[tono(c.r.nota)]" aria-hidden="true" /> {{ c.r.nota }}</span>
            <span v-else-if="c.estado === 'curso'" class="tira__nota"><i class="fa-solid fa-spinner fa-spin" aria-hidden="true" /> en curso</span>
            <span v-else class="tira__nota tira__nota--vacia">pendiente</span>
            <a v-if="c.r && c.grupo === 'tangible'" class="tira__abrir" :href="`/banco/abrir/${c.r.id}/`" target="_blank" rel="noopener">abrir</a>
          </li>
        </ol>
      </template>
      <template v-else-if="grafica">
        <div class="vivo__cifras">
          <div><b>{{ grafica.hechos }}/{{ grafica.total }}</b><span>parches · repetición {{ grafica.rep }}/{{ grafica.reps }}</span></div>
          <div><b>{{ grafica.ultima ?? "—" }}{{ grafica.ultima != null ? " %" : "" }}</b><span>nota tras el último parche</span></div>
          <div><b>{{ enMarcha.media ?? "—" }}{{ enMarcha.media != null ? " %" : "" }}</b><span>media de las repeticiones acabadas</span></div>
        </div>
        <div class="barra"><span :style="{ width: `${(100 * grafica.hechos) / grafica.total}%` }" /></div>
        <svg class="curva" :viewBox="`0 0 ${W} ${H}`" role="img" :aria-label="`Nota del examen tras cada parche: ${grafica.puntos.map((p) => `${p.n}: ${p.v}`).join(', ')}`">
          <g class="curva__eje">
            <line v-for="t in grafica.ticksY" :key="t.v" :x1="M.l" :x2="W - M.r" :y1="t.y" :y2="t.y" />
            <text v-for="t in grafica.ticksY" :key="`y${t.v}`" :x="M.l - 6" :y="t.y + 4" text-anchor="end">{{ t.v }}</text>
            <text v-for="t in grafica.ticksX" :key="`x${t.n}`" :x="t.x" :y="H - 8" text-anchor="middle">{{ t.n }}</text>
          </g>
          <path v-for="(d, i) in grafica.previas" :key="i" :d="d" class="curva__previa" />
          <path :d="grafica.actual" class="curva__actual" />
          <g v-for="pt in grafica.puntos" :key="pt.n" class="curva__punto">
            <circle :cx="pt.cx" :cy="pt.cy" r="12" class="curva__hit"><title>Parche {{ pt.n }}: {{ pt.v }} % · {{ pt.res }}</title></circle>
            <circle :cx="pt.cx" :cy="pt.cy" r="4" />
          </g>
        </svg>
        <p class="hint">Nota del examen oculto tras cada parche. En gris, las repeticiones anteriores de esta tanda. Pasa el ratón por un punto para ver el detalle.</p>
      </template>
      <p v-else class="empty">Preparando la ejecución…</p>
    </Card>

    <Card title="Cola" :subtitle="cola?.corriendo ? 'Las tandas se hacen en orden; cada repetición, una ejecución completa.' : 'Pulsa Empezar y se hará sola, tanda tras tanda.'">
      <template #actions>
        <StatusChip :state="estadoCola.state" :text="estadoCola.text" />
        <button v-if="!cola?.corriendo" class="btn btn--primary btn--small" :disabled="busy || !pendientes.length" @click="empezar">
          <i class="fa-solid fa-play" /> Empezar
        </button>
        <template v-else>
          <button class="btn btn--small" :disabled="busy || !!cola?.parar" title="Termina la ejecución que corre y no empieza otra" @click="parar('despues')">
            Parar al acabar
          </button>
          <button class="btn btn--small btn--danger" :disabled="busy || cola?.parar === 'ya'" title="Cancela la tarea en marcha; la ejecución queda parada y se puede seguir" @click="parar('ya')">
            Parar ya
          </button>
        </template>
        <a class="btn btn--small btn--ghost" href="/banco" target="_blank" rel="noopener">Visor de ejecuciones</a>
      </template>

      <p v-if="!cola?.tandas.length" class="empty">La cola está vacía: añade una tanda abajo.</p>
      <ol v-else class="tandas">
        <li v-for="(t, i) in cola.tandas" :key="t.id" class="tanda" :class="`is-${t.estado.replace(' ', '-')}`">
          <div class="tanda__orden">
            <button class="icon" :disabled="busy || i === 0" title="Subir" @click="mover(t, -1)"><i class="fa-solid fa-chevron-up" /></button>
            <button class="icon" :disabled="busy || i === cola.tandas.length - 1" title="Bajar" @click="mover(t, 1)"><i class="fa-solid fa-chevron-down" /></button>
          </div>
          <div class="tanda__cuerpo">
            <div class="tanda__cab">
              <b>{{ t.repertorio ? `Repertorio ${titulo(t.prueba)}${t.de_casos && t.casos && t.casos.length < t.de_casos ? ` · ${t.casos.length} de ${t.de_casos} casos` : ""}` : `${titulo(t.prueba)} · ${t.modalidad}` }}</b>
              <span class="nombre">{{ t.contendiente.nombre }}</span>
              <StatusChip :state="CHIP[t.estado]" :text="t.estado" />
            </div>
            <div class="tanda__meta">
              {{ t.contendiente.agente }} · {{ modelosDe(t.contendiente) }}<template v-if="extras(t.contendiente)"> · {{ extras(t.contendiente) }}</template>
            </div>
            <div class="tiradas">
              <span class="cuenta">{{ t.resultados.length }}/{{ t.total ?? t.repeticiones }}</span>
              <a v-for="r in t.resultados" :key="r.id" class="tirada" :class="tono(r.nota)" :href="enlace(t, r)" target="_blank"
                 :title="`${r.id} · ${r.integrados}/${r.parches} integrados · ${minutos(r.minutos)}`">{{ etiqueta(t, r) }}</a>
              <span v-if="t.en_curso" class="tirada en-curso" :title="t.en_curso.id">
                en curso · parche {{ (t.en_curso.hechos ?? 0) + 1 }}/{{ t.en_curso.parches }}
              </span>
              <span v-for="k in Math.min(30, Math.max(0, (t.total ?? t.repeticiones) - t.resultados.length - (t.en_curso ? 1 : 0)))" :key="k" class="tirada vacia" />
              <span v-if="t.media != null && t.resultados.length > 1" class="media">media {{ t.media }} %</span>
            </div>
            <p v-if="t.error" class="error small">{{ t.error }}</p>
          </div>
          <div class="tanda__acc">
            <button v-if="['parada', 'error', 'hecha'].includes(t.estado)" class="btn btn--small" :disabled="busy"
                    :title="t.estado === 'hecha' ? 'Una repetición más' : 'Vuelve a la cola con lo que le falte'" @click="reabrir(t)">
              {{ t.estado === "hecha" ? "+1" : "Reabrir" }}
            </button>
            <button class="icon" :disabled="busy || (t.estado === 'en marcha' && cola.corriendo)" title="Quitar de la cola" @click="quitar(t)">
              <i class="fa-solid fa-xmark" />
            </button>
          </div>
        </li>
      </ol>
      <details v-if="cola?.log" class="log">
        <summary>Salida de la cola</summary>
        <pre>{{ cola.log }}</pre>
      </details>
    </Card>

    <Card title="Nueva tanda" subtitle="Lo que elijas aquí es el «contendiente»: se guarda dentro de la tanda (y, si quieres, como archivo para reutilizarlo).">
      <form class="bform" novalidate @submit.prevent="anadir">
        <label class="field">
          <span class="label">Prueba</span>
          <select v-model="form.prueba" class="input">
            <optgroup v-if="repertorios.length" label="Repertorios de casos cortos">
              <option v-for="r in repertorios" :key="r.nombre" :value="`rep:${r.nombre}`">{{ r.titulo }} · {{ r.casos.length }} casos</option>
            </optgroup>
            <optgroup label="Pruebas largas">
              <option v-for="p in pruebas" :key="p.nombre" :value="p.nombre">{{ p.titulo }} ({{ p.tipo }})</option>
            </optgroup>
          </select>
          <span v-if="repertorio" class="hint">{{ repertorio.descripcion }}</span>
        </label>
        <label v-if="!repertorio" class="field">
          <span class="label">Modalidad</span>
          <select v-model="form.modalidad" class="input">
            <option v-for="[m, d] in modalidades" :key="m" :value="m">{{ m }} · {{ d.parches }} parches</option>
          </select>
        </label>
        <div v-else class="field wide">
          <span class="label">Casos · {{ nCasos }} de {{ repertorio.casos.length }}</span>
          <div class="elegir">
            <button type="button" class="btn btn--small" @click="alAzar(5)">5 al azar</button>
            <button type="button" class="btn btn--small" @click="alAzar(10)">10 al azar</button>
            <button type="button" class="btn btn--small btn--ghost" @click="elegidos = [...repertorio.casos]">Todos</button>
            <button type="button" class="btn btn--small btn--ghost" @click="elegidos = []">Ninguno</button>
          </div>
          <div class="casos-sel">
            <button v-for="c in repertorio.casos" :key="c" type="button" class="caso-sel" :class="{ 'is-on': elegidos.includes(c) }"
                    :title="c" :aria-pressed="elegidos.includes(c)" @click="alternar(c)">
              <small>{{ fichaCaso(c)?.grupo ?? "" }}</small>{{ fichaCaso(c)?.titulo ?? c }}
            </button>
          </div>
          <span class="hint">Un parche cada uno, con {{ repertorio.minutos_tarea }} min como máximo por caso. Para comparar modelos,
            deja la misma selección entre tandas: «al azar» sortea una vez y se queda.</span>
        </div>
        <label class="field">
          <span class="label">Partir de un contendiente guardado</span>
          <select v-model="form.partir" class="input">
            <option value="">— ninguno —</option>
            <option v-for="c in guardados" :key="c.nombre" :value="c.nombre">{{ c.nombre }}</option>
          </select>
          <span v-if="form.partir" class="hint">{{ guardados.find((g) => g.nombre === form.partir)?.descripcion }}</span>
        </label>
        <label class="field">
          <span class="label">Agente que dirige</span>
          <select v-model="form.agente" class="input">
            <option v-for="a in agentes" :key="a.id" :value="a.name">{{ a.name }}{{ a.provider === "local_boss" ? "" : ` (${a.provider})` }}</option>
          </select>
          <span v-if="gastaPlan" class="hint warn-text">Este agente usa Claude: gasta plan.</span>
          <span v-else-if="agente?.config.description" class="hint">{{ agente.config.description }}</span>
        </label>

        <fieldset class="wide servidores">
          <legend class="label">Modelos por servidor (GPU)</legend>
          <div v-for="s in servidores" :key="s.id" class="srv">
            <span class="srv__nombre">{{ s.name }} <small>{{ s.id }}</small></span>
            <select v-model="form.modelos[s.id]" class="input">
              <option :value="KEEP">el que esté cargado</option>
              <option :value="OFF">apagado</option>
              <option v-for="m in modelos" :key="m.path" :value="m.name">{{ m.name }} · {{ m.size_gb.toFixed(1) }} GB</option>
            </select>
            <select v-model="form.pensamiento[s.id]" class="input srv__pensar" :disabled="form.modelos[s.id] === OFF" title="Razonamiento del modelo">
              <option v-for="p in PENSAR" :key="p" :value="p">pensar: {{ p }}</option>
            </select>
          </div>
          <span class="hint">Los Qwen3.5 en «normal» razonan sin tope: en el banco, mejor «apagado».</span>
        </fieldset>

        <label class="field">
          <span class="label">{{ repertorio ? "Vueltas (a los casos marcados)" : "Repeticiones" }}</span>
          <input v-model.number="form.repeticiones" type="number" min="1" max="50" class="input" />
          <span class="hint">{{ repertorio ? `${form.repeticiones || 0} × ${nCasos} = ${(form.repeticiones || 0) * nCasos} ejecuciones cortas.` : "Con 3 o más se ve si un cambio mejora de verdad o fue suerte." }}</span>
        </label>
        <label class="field">
          <span class="label">Parar la línea</span>
          <select v-model.number="form.linea" class="input">
            <option :value="0">no: si un parche cae, sigue</option>
            <option v-for="n in 3" :key="n" :value="n">reintentar {{ n }} vez/veces antes de seguir</option>
          </select>
        </label>
        <label class="field">
          <span class="label">Reparación al final</span>
          <select v-model.number="form.reparar" class="input">
            <option :value="0">no</option>
            <option v-for="n in 3" :key="n" :value="n">hasta {{ n }} vuelta(s) con el tiempo que sobre</option>
          </select>
        </label>
        <label v-if="!repertorio" class="field">
          <span class="label">Relevo (hito por hito)</span>
          <select v-model="form.relevo" class="input">
            <option value="">no: un proyecto seguido</option>
            <option v-for="e in relevos" :key="e.id" :value="e.id">desde {{ e.contendiente }} · {{ e.inicio.slice(0, 16).replace("T", " ") }} ({{ e.totales?.nota ?? "—" }} %)</option>
          </select>
          <span class="hint">Cada parche sale del repo que tenía esa ejecución antes de él: un parche caído no arrastra a los demás.</span>
        </label>

        <details class="wide avanzado">
          <summary>Topes y descripción</summary>
          <div class="bform">
            <label class="field"><span class="label">Horas como máximo</span><input v-model.number="form.horas" type="number" min="0.1" max="48" step="any" class="input" /></label>
            <label class="field"><span class="label">Minutos por tarea</span><input v-model.number="form.minutos_tarea" type="number" min="1" max="240" class="input" /></label>
            <label class="field"><span class="label">Presupuesto de Claude ($ nominales)</span><input v-model.number="form.presupuesto" type="number" min="0" max="100" step="any" class="input" /><span class="hint">Con un agente local no se gasta nada; tiene que ser al menos 1 o el autopiloto se para.</span></label>
            <label class="field wide"><span class="label">Descripción</span><input v-model="form.descripcion" class="input" placeholder="Qué pruebas con esta configuración" /></label>
          </div>
        </details>

        <label class="field wide">
          <span class="label">Nombre del contendiente</span>
          <input v-model="form.nombre" class="input code" @input="form.nombreTocado = true" />
          <span class="hint">Las ejecuciones con el mismo nombre se agrupan en los resultados.
            <button v-if="form.nombreTocado" type="button" class="linklike" @click="form.nombreTocado = false; form.nombre = nombreAuto">usar el automático</button></span>
        </label>
        <div class="row wide">
          <button class="btn btn--primary" :disabled="busy">
            {{ busy ? "Añadiendo…" : `Añadir a la cola (${form.repeticiones}×)` }}
          </button>
          <button type="button" class="btn" :disabled="busy" title="banco/contendientes/<nombre>.json" @click="guardar">Guardar como contendiente</button>
        </div>
        <p v-if="formError" class="error wide" role="alert">{{ formError }}</p>
        <p v-if="formAviso" class="aviso wide" role="status">{{ formAviso }}</p>
      </form>
    </Card>

    <Card v-for="m in (cola?.matrices ?? []).filter((x) => x.contendientes.length)" :key="m.repertorio"
          :title="`Casos · ${m.titulo}`" subtitle="Aprobados (nota 100) de las tiradas terminadas de cada caso, por contendiente. Pasa el ratón para ver la nota media.">
      <div class="tablewrap">
        <table class="res matriz">
          <thead>
            <tr><th>Caso</th><th v-for="c in m.contendientes" :key="c" class="nombre">{{ c }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="f in m.filas" :key="f.caso">
              <td>{{ f.titulo }}<small>{{ GRUPO[f.grupo] ?? f.grupo }} · {{ f.caso }}</small></td>
              <td v-for="c in m.contendientes" :key="c" :class="tonoCelda(f.celdas[c])"
                  :title="f.celdas[c] ? `nota media ${f.celdas[c].media}` : 'sin tiradas'">
                {{ f.celdas[c] ? `${f.celdas[c].aprobados}/${f.celdas[c].tiradas}` : "—" }}
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <th>Total</th>
              <th v-for="c in m.contendientes" :key="c">{{ m.totales[c].aprobados }}/{{ m.totales[c].tiradas }}
                <small>media {{ m.totales[c].media ?? "—" }} · {{ m.totales[c].casos }} casos</small></th>
            </tr>
          </tfoot>
        </table>
      </div>
    </Card>

    <Card title="Resultados" subtitle="Pruebas largas terminadas, agrupadas por configuración. Las paradas no cuentan.">
      <p v-if="!grupos.length" class="empty">Aún no hay ejecuciones terminadas.</p>
      <div v-for="[nombre, gs] in grupos" :key="nombre" class="grupo">
        <h4>{{ nombre }}</h4>
        <div class="tablewrap">
          <table class="res">
            <thead>
              <tr><th>Contendiente</th><th>Tiradas</th><th>Media</th><th>Mejor · peor</th><th>Integrados</th><th>Tiempo medio</th><th>Última</th></tr>
            </thead>
            <tbody>
              <tr v-for="g in gs" :key="g.contendiente" :title="g.descripcion">
                <td><span class="nombre">{{ g.contendiente }}</span><small>{{ g.agente }}</small></td>
                <td>{{ g.tiradas }}</td>
                <td><b :class="tono(g.media)">{{ g.media }} %</b></td>
                <td>{{ g.tiradas > 1 ? `${g.mejor} · ${g.peor}` : "—" }}</td>
                <td>{{ g.integrados }}/{{ g.parches }}</td>
                <td>{{ minutos(g.minutos) }}</td>
                <td>{{ g.ultima.slice(0, 10) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </Card>
  </div>
</template>

<style scoped>
.elegir {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.casos-sel {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 6px;
}
.caso-sel {
  display: grid;
  gap: 1px;
  text-align: left;
  padding: 6px 8px;
  border: 1px dashed var(--line);
  border-radius: 4px;
  background: transparent;
  color: var(--ink-dim);
  font: inherit;
  font-size: 0.82rem;
  line-height: 1.25;
  cursor: pointer;
}
.caso-sel small {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-faint);
}
.caso-sel.is-on {
  border: 1px solid var(--accent);
  box-shadow: inset 3px 0 0 var(--accent);
  background: var(--panel-raised);
  color: var(--ink);
}
.vivo__cifras {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 10px;
}
.vivo__cifras div {
  display: grid;
}
.vivo__cifras b {
  font-size: 1.5rem;
  font-variant-numeric: tabular-nums;
}
.vivo__cifras span {
  color: var(--ink-dim);
  font-size: 0.85rem;
}
.barra {
  height: 6px;
  border-radius: 3px;
  background: var(--line);
  overflow: hidden;
  margin-bottom: 12px;
}
.barra span {
  display: block;
  height: 100%;
  background: var(--accent);
  transition: width 0.4s ease;
}
.tira {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 6px;
}
.tira__caso {
  display: grid;
  gap: 2px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--panel-raised);
  min-height: 78px;
}
.tira__caso.is-pendiente {
  border-style: dashed;
  opacity: 0.7;
}
.tira__caso.is-curso {
  border-color: var(--accent);
  box-shadow: inset 3px 0 0 var(--accent);
}
.tira__caso.nota-alta {
  background: var(--ok-weak);
}
.tira__caso.nota-media {
  background: var(--warn-weak);
}
.tira__caso.nota-baja {
  background: var(--crit-weak);
}
.tira__grupo {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-faint);
}
.tira__titulo {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--ink);
  line-height: 1.25;
}
.tira__nota {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}
.tira__nota--vacia {
  font-weight: 400;
  color: var(--ink-faint);
}
.tira__abrir {
  font-size: 0.8rem;
}
.curva {
  width: 100%;
  height: auto;
  display: block;
}
.curva__eje line {
  stroke: var(--line);
  stroke-width: 1;
}
.curva__eje text {
  fill: var(--ink-faint);
  font-size: 11px;
}
.curva__previa {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1.5;
  opacity: 0.45;
}
.curva__actual {
  fill: none;
  stroke: var(--accent);
  stroke-width: 2;
  stroke-linejoin: round;
}
.curva__punto circle:last-child {
  fill: var(--accent);
  stroke: var(--panel);
  stroke-width: 2;
  pointer-events: none;
}
.curva__hit {
  fill: transparent;
  cursor: default;
}
.curva__punto:hover circle:last-child {
  r: 6;
}
.aviso {
  margin: 0 0 12px;
  color: var(--ok);
  font-weight: 600;
}
.bform {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 14px;
}
.bform .wide {
  grid-column: 1 / -1;
}
.servidores {
  border: 0;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.srv {
  display: grid;
  grid-template-columns: minmax(120px, 180px) minmax(0, 1fr) 150px;
  gap: 8px;
  align-items: center;
}
.srv__nombre {
  font-weight: 600;
}
.srv__nombre small {
  color: var(--ink-faint);
  font-weight: 400;
  margin-left: 4px;
}
@media (max-width: 640px) {
  .srv {
    grid-template-columns: 1fr;
  }
}
.avanzado summary,
.log summary {
  cursor: pointer;
  color: var(--ink-dim);
  font-weight: 600;
  margin-bottom: 10px;
}
.warn-text {
  color: var(--warn);
}
.linklike {
  border: 0;
  background: none;
  padding: 0;
  color: var(--accent, var(--ink));
  text-decoration: underline;
  cursor: pointer;
  font: inherit;
}
.code,
.nombre {
  font-family: var(--mono, ui-monospace, monospace);
}
.tandas {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.tanda {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--panel-raised);
}
.tanda.is-en-marcha {
  border-left: 3px solid var(--accent, var(--ok));
}
.tanda.is-hecha {
  opacity: 0.85;
}
.tanda__orden {
  display: grid;
  gap: 2px;
}
.tanda__cab {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.tanda__cab .nombre {
  font-size: 0.85rem;
  color: var(--ink-dim);
}
.tanda__meta {
  margin-top: 2px;
  font-size: 0.85rem;
  color: var(--ink-faint);
}
.tanda__acc {
  display: flex;
  gap: 6px;
  align-items: center;
}
.icon {
  border: 0;
  background: none;
  padding: 2px 6px;
  color: var(--ink-dim);
  cursor: pointer;
  border-radius: 4px;
}
.icon:hover:not(:disabled) {
  background: var(--line);
}
.icon:disabled {
  opacity: 0.35;
  cursor: default;
}
.tiradas {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  font-variant-numeric: tabular-nums;
}
.cuenta {
  font-weight: 700;
  margin-right: 4px;
}
.tirada {
  display: inline-block;
  min-width: 46px;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid var(--line);
  font-size: 0.82rem;
  font-weight: 700;
  text-align: center;
  text-decoration: none;
  color: var(--ink);
}
.tirada.vacia {
  border-style: dashed;
  height: 22px;
}
.tirada.en-curso {
  font-weight: 600;
  color: var(--ink-dim);
}
.media {
  margin-left: 6px;
  color: var(--ink-dim);
  font-size: 0.85rem;
}
.nota-alta {
  color: var(--ok);
}
.nota-media {
  color: var(--warn);
}
.nota-baja {
  color: var(--crit);
}
.tirada.nota-alta {
  background: var(--ok-weak);
}
.tirada.nota-media {
  background: var(--warn-weak);
}
.tirada.nota-baja {
  background: var(--crit-weak);
}
.log pre {
  max-height: 260px;
  overflow: auto;
  font-size: 0.78rem;
  background: var(--panel-raised);
  padding: 8px;
  border-radius: 4px;
  white-space: pre-wrap;
}
.grupo + .grupo {
  margin-top: 16px;
}
.grupo h4 {
  margin: 0 0 6px;
}
.tablewrap {
  overflow-x: auto;
}
.res {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
  font-variant-numeric: tabular-nums;
}
.res th,
.res td {
  padding: 6px 10px;
  border-top: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}
.res thead th {
  border-top: 0;
  font-weight: 700;
  color: var(--ink-dim);
}
.matriz td:not(:first-child),
.matriz th:not(:first-child) {
  text-align: center;
  font-weight: 700;
}
.matriz tfoot th {
  border-top: 2px solid var(--line);
}
.matriz th small {
  display: block;
  font-weight: 400;
  font-size: 0.75rem;
  color: var(--ink-faint);
}
td.nota-alta {
  background: var(--ok-weak);
}
td.nota-media {
  background: var(--warn-weak);
}
td.nota-baja {
  background: var(--crit-weak);
}
.res td small {
  display: block;
  color: var(--ink-faint);
  font-size: 0.75rem;
}
.small {
  font-size: 0.85rem;
}
</style>
