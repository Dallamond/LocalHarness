<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import Card from "../components/Card.vue";
import StatusChip from "../components/StatusChip.vue";
import {
  ROLE_TEXT, ago, api, duration, live, pickPath, post, refreshAll, tps, type LlamaInfo, type LocalModel, type ModelLaunch,
} from "../api";

const info = ref<LlamaInfo | null>(null);
const error = ref("");
const msg = ref("");
const starting = ref<string | null>(null);
const showLog = ref(false);
const now = ref(Date.now());

// configuración editable (se guarda en Ajustes → llama)
const cfg = reactive({
  server: "", model_dirs: [] as string[], port: 8080, ctx: 16384, ngl: 99, per_model: {} as Record<string, ModelLaunch>,
});
const newDir = ref("");

async function load(withCfg = false) {
  try {
    info.value = await api<LlamaInfo>("/api/llama");
    if (withCfg) Object.assign(cfg, JSON.parse(JSON.stringify(info.value.config)));
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  }
}

// sondeo: rápido mientras carga un modelo (tarda minutos), lento el resto del tiempo
let timer: ReturnType<typeof setTimeout>;
let clock: ReturnType<typeof setInterval>;
async function poll() {
  await load();
  const s = info.value?.status.state;
  timer = setTimeout(poll, s === "loading" || starting.value ? 2000 : 6000);
}
onMounted(async () => {
  await load(true);
  timer = setTimeout(poll, 2000);
  clock = setInterval(() => (now.value = Date.now()), 1000);
});
onUnmounted(() => {
  clearTimeout(timer);
  clearInterval(clock);
});

const status = computed(() => info.value?.status);
const STATE: Record<string, { text: string; chip: "ok" | "warn" | "crit" | "pending" | "off" }> = {
  off: { text: "apagado", chip: "off" },
  loading: { text: "cargando el modelo…", chip: "pending" },
  ready: { text: "listo", chip: "ok" },
  failed: { text: "se ha caído", chip: "crit" },
  external: { text: "en marcha (lanzado fuera)", chip: "ok" },
};
const progress = computed(() => status.value?.progress ?? null);
const speed = computed(() => info.value?.speed ?? live.lastSpeed);

// --- arranque propio de cada modelo (contexto, capas en GPU, argumentos extra)
const openCfg = ref<string | null>(null);
const own = reactive<{ ctx: number | null; ngl: number | null; extra: string }>({ ctx: null, ngl: null, extra: "" });
function toggleCfg(m: LocalModel) {
  if (openCfg.value === m.path) {
    openCfg.value = null;
    return;
  }
  const c = cfg.per_model[m.path] ?? {};
  Object.assign(own, { ctx: c.ctx ?? null, ngl: c.ngl ?? null, extra: c.extra ?? "" });
  openCfg.value = m.path;
}
async function saveOwn(m: LocalModel) {
  const per = { ...cfg.per_model };
  const entry: ModelLaunch = {};
  if (own.ctx) entry.ctx = Number(own.ctx);
  if (own.ngl !== null && String(own.ngl) !== "") entry.ngl = Number(own.ngl);
  if (own.extra.trim()) entry.extra = own.extra.trim();
  if (Object.keys(entry).length) per[m.path] = entry;
  else delete per[m.path];
  await saveCfg({ per_model: per });
  openCfg.value = null;
  if (isCurrent(m)) msg.value = "Guardado. Se aplica la próxima vez que arranques este modelo.";
}
function launchText(m: LocalModel): string {
  const c = cfg.per_model[m.path];
  if (!c) return "";
  return [c.ctx ? `ctx ${c.ctx}` : null, c.ngl !== undefined && c.ngl !== null ? `ngl ${c.ngl}` : null, c.extra || null]
    .filter(Boolean).join(" · ");
}
const loadTime = (m: LocalModel) => info.value?.load_times?.[m.path];

const isCurrent = (m: LocalModel) => status.value?.model === m.path && status.value.state !== "off";
const groups = computed(() => {
  const g: Record<string, LocalModel[]> = {};
  for (const m of info.value?.models ?? []) (g[m.dir] ??= []).push(m);
  return g;
});

async function saveCfg(changes: Partial<typeof cfg> = {}) {
  Object.assign(cfg, changes);
  error.value = msg.value = "";
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify({ llama: cfg }) });
    await load(true);
    msg.value = "Guardado.";
  } catch (e) {
    error.value = (e as Error).message;
  }
}

async function pickDir() {
  try {
    const p = await pickPath("folder", "Carpeta donde guardas los modelos GGUF");
    if (p && !cfg.model_dirs.includes(p)) await saveCfg({ model_dirs: [...cfg.model_dirs, p] });
  } catch (e) {
    error.value = `${(e as Error).message}. Escribe la ruta abajo.`;
  }
}
async function addDir() {
  const p = newDir.value.trim().replace(/^"|"$/g, "");
  if (p && !cfg.model_dirs.includes(p)) await saveCfg({ model_dirs: [...cfg.model_dirs, p] });
  newDir.value = "";
}
async function pickServer() {
  try {
    const p = await pickPath("file", "llama-server.exe");
    if (p) await saveCfg({ server: p });
  } catch (e) {
    error.value = `${(e as Error).message}. Escribe la ruta a mano.`;
  }
}

async function start(m: LocalModel) {
  error.value = msg.value = "";
  starting.value = m.path;
  try {
    await post("/api/llama/start", { path: m.path });
    await load();
    msg.value = `Arrancando ${m.name}. Los agentes locales se conectarán a http://127.0.0.1:${cfg.port} cuando esté listo.`;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    starting.value = null;
  }
}

async function stop() {
  error.value = "";
  try {
    await post("/api/llama/stop");
    await load();
  } catch (e) {
    error.value = (e as Error).message;
  }
}

// Agentes locales por ROL y sin modelo fijo: llama-server sirve uno a la vez y todos usan el que esté arrancado.
// Cambiar de modelo no obliga a crear otro agente.
const localAgents = computed(() => live.agents.filter((a) => a.provider === "local"));
const newRole = ref("jefe");
const ROLE_DESC: Record<string, string> = {
  jefe: "Jefe técnico local: revisa diffs y decide si se aprueban, sin coste.",
  director: "Director local: reparte la petición en subtareas, sin coste.",
  trabajador: "Consultas locales: responde preguntas sobre el repo, sin coste.",
};
async function createAgent() {
  const role = newRole.value;
  const slug = role === "trabajador" ? "consultas" : role;
  let name = `local-${slug}`;
  for (let i = 2; live.agents.some((a) => a.name === name); i++) name = `local-${slug}-${i}`;
  error.value = msg.value = "";
  try {
    await post("/api/agents", {
      name, provider: "local", role,
      description: `${ROLE_DESC[role]} Usa el modelo arrancado en llama-server. Lee el repo en el prompt; no edita archivos.`,
    });
    await refreshAll();
    msg.value = `Agente ${name} creado. Usará el modelo que tengas arrancado.`;
  } catch (e) {
    error.value = (e as Error).message;
  }
}
// agentes antiguos creados con el nombre de un GGUF concreto: avisar si piden otro distinto del arrancado
const servedName = computed(() => {
  const m = status.value && status.value.state !== "off" ? status.value.model : null;
  return m ? m.split(/[\\/]/).pop()!.replace(/\.gguf$/i, "") : null;
});
const mismatch = (model: string | null) =>
  !!model && !!servedName.value && !servedName.value.toLowerCase().includes(model.toLowerCase());
const modelFor = (name: string | null) => info.value?.models.find((m) => m.name === name);
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2 class="title">Modelos locales</h2>
      <p>Tus GGUF con llama.cpp: arranca uno y los agentes locales lo usan gratis.</p>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="msg" class="okmsg">{{ msg }}</p>

    <!-- estado del servidor -->
    <section v-if="status" class="server" :class="`server--${status.state}`">
      <div class="server__main">
        <span class="dot" aria-hidden="true" />
        <div class="server__txt">
          <strong>llama-server {{ STATE[status.state]?.text }}</strong>
          <span class="muted small">
            <template v-if="status.model">{{ status.model.split(/[\\/]/).pop() }} · </template>
            puerto {{ status.port }}
            <template v-if="status.started_at"> · hace {{ duration(now - status.started_at * 1000) }}</template>
            <template v-if="status.state === 'failed'"> · código {{ status.exit_code }}</template>
          </span>
        </div>
        <StatusChip :state="STATE[status.state]?.chip ?? 'off'" :text="STATE[status.state]?.text ?? status.state" />
        <button v-if="status.pid" class="btn btn--danger btn--small" @click="stop">Parar</button>
        <button v-if="status.log" class="btn btn--ghost btn--small" @click="showLog = !showLog">{{ showLog ? "Ocultar log" : "Ver log" }}</button>
      </div>
      <div v-if="status.state === 'loading'" class="progress">
        <div class="bar" :class="{ 'bar--unknown': progress?.pct == null }" role="progressbar"
             :aria-valuenow="progress?.pct ?? undefined" aria-valuemin="0" aria-valuemax="100">
          <span :style="{ width: progress?.pct != null ? `${progress.pct}%` : undefined }" />
        </div>
        <span class="small muted">
          {{ progress?.stage ?? "arrancando" }}<template v-if="progress?.pct != null"> · {{ progress.pct }} %</template>
          <template v-if="progress?.eta_s"> · faltan ~{{ duration(progress.eta_s * 1000) }}</template>
          <template v-if="progress?.source === 'tiempo'"> (según lo que tardó la última vez)</template>
          <template v-else-if="progress?.pct == null"> · la primera carga de cada modelo no tiene estimación</template>
        </span>
      </div>
      <div v-if="status.log_lines?.length && !showLog" class="loglines">
        <code v-for="(l, k) in status.log_lines" :key="k">{{ l }}</code>
      </div>
      <pre v-if="showLog && status.log" class="block log">{{ status.log }}</pre>
      <p v-if="speed?.tps" class="muted small hint">
        Velocidad {{ speed.final ? "de la última respuesta" : "ahora" }}: <strong>{{ tps(speed.tps) }}</strong>
        <template v-if="speed.model"> · {{ speed.model }}</template> · {{ ago(speed.at, now) }}
      </p>
    </section>

    <!-- modelos -->
    <Card title="Tus modelos" :subtitle="info ? `${info.models.length} encontrados en ${info.dirs.length} carpeta(s)` : 'Buscando…'">
      <template #actions>
        <button class="btn btn--small" @click="load()">Volver a buscar</button>
      </template>
      <p v-if="info && !info.dirs.length" class="empty">
        No hay ninguna carpeta de modelos. <button class="btn btn--primary btn--small" @click="pickDir">Elegir carpeta…</button>
      </p>
      <p v-else-if="info && !info.models.length" class="empty">No hay archivos .gguf en esas carpetas.</p>
      <div v-for="(models, dir) in groups" :key="dir" class="group">
        <p class="group__dir"><code>{{ dir }}</code></p>
        <div class="models">
          <article v-for="m in models" :key="m.path" class="model" :class="{ 'model--on': isCurrent(m) }">
            <div class="model__head">
              <span class="chip-icon" aria-hidden="true">🧠</span>
              <div class="model__name">
                <strong :title="m.file">{{ m.name }}</strong>
                <span class="muted small">{{ m.size_gb.toFixed(1) }} GB<template v-if="m.quant"> · {{ m.quant }}</template>
                  <template v-if="loadTime(m)"> · carga en {{ duration(loadTime(m)! * 1000) }}</template></span>
                <span v-if="launchText(m)" class="small launch">{{ launchText(m) }}</span>
              </div>
            </div>
            <div class="row">
              <template v-if="isCurrent(m)">
                <StatusChip :state="STATE[status!.state].chip" :text="STATE[status!.state].text" />
                <button v-if="status!.pid" class="btn btn--small btn--danger" @click="stop">Parar</button>
              </template>
              <button
                v-else class="btn btn--primary btn--small" :disabled="!!starting || !info?.server"
                :title="info?.server ? '' : 'Falta la ruta de llama-server'" @click="start(m)"
              >{{ starting === m.path ? "Arrancando…" : status?.pid ? "Cambiar a este" : "Arrancar" }}</button>
            </div>
            <button class="btn btn--small btn--ghost cfg-toggle" @click="toggleCfg(m)">
              {{ openCfg === m.path ? "Cerrar" : "⚙ Arranque de este modelo" }}
            </button>
            <form v-if="openCfg === m.path" class="own" @submit.prevent="saveOwn(m)">
              <label class="field"><span class="label">Contexto</span><input v-model.number="own.ctx" type="number" min="512" step="1024" :placeholder="String(cfg.ctx)" /></label>
              <label class="field"><span class="label">Capas en GPU</span><input v-model.number="own.ngl" type="number" min="0" :placeholder="String(cfg.ngl)" /></label>
              <label class="field own__wide">
                <span class="label">Argumentos extra</span>
                <input v-model="own.extra" class="code" placeholder="-fa on -t 8" />
              </label>
              <div class="row own__wide">
                <button class="btn btn--primary btn--small">Guardar</button>
                <span class="hint">Vacío = valores generales de abajo.</span>
              </div>
            </form>
          </article>
        </div>
      </div>
    </Card>

    <!-- agentes locales -->
    <Card title="Agentes locales" subtitle="Todos usan el modelo que esté arrancado: si cambias de modelo, siguen funcionando.">
      <p v-if="!localAgents.length" class="empty">Aún no hay agentes locales.</p>
      <ul class="lagents">
        <li v-for="a in localAgents" :key="a.id">
          <strong>{{ a.name }}</strong>
          <span class="muted small">{{ ROLE_TEXT[a.role ?? ""] ?? a.role ?? "sin rol" }} · usa {{ servedName ?? "(nada arrancado)" }}</span>
          <span v-if="mismatch(a.model)" class="warnline small">
            Se creó para «{{ a.model }}» pero el arrancado es otro (responde el arrancado).
            <button v-if="modelFor(a.model)" class="btn btn--small" :disabled="!!starting" @click="start(modelFor(a.model)!)">Arrancar {{ a.model }}</button>
          </span>
        </li>
      </ul>
      <form class="row" @submit.prevent="createAgent">
        <select v-model="newRole" class="input mini" aria-label="Rol del agente">
          <option value="jefe">jefe técnico</option>
          <option value="director">director</option>
          <option value="trabajador">consultas</option>
        </select>
        <button class="btn btn--small">+ Crear agente local</button>
        <span class="hint">Temperatura, tokens y contexto del repo: en Ajustes → Agentes.</span>
      </form>
    </Card>

    <!-- configuración -->
    <Card title="Dónde están las cosas" subtitle="Se guarda al cambiar. Vacío = lo que diga Arena LLM o las variables de entorno.">
      <div class="cfg">
        <div class="field">
          <span class="label">Carpetas de modelos</span>
          <ul class="dirs">
            <li v-for="d in cfg.model_dirs" :key="d">
              <code>{{ d }}</code>
              <button class="btn btn--ghost btn--small" @click="saveCfg({ model_dirs: cfg.model_dirs.filter((x) => x !== d) })">Quitar</button>
            </li>
            <li v-if="!cfg.model_dirs.length && info?.dirs.length" class="muted small">
              Usando: {{ info.dirs.join(", ") }} (de Arena LLM / variables de entorno)
            </li>
          </ul>
          <form class="row" @submit.prevent="addDir">
            <button type="button" class="btn btn--small" @click="pickDir">Elegir carpeta…</button>
            <input v-model="newDir" class="input code grow" placeholder="o pega la ruta: D:\IA\modelos" />
            <button class="btn btn--small" :disabled="!newDir.trim()">Añadir</button>
          </form>
        </div>
        <div class="field">
          <span class="label">llama-server</span>
          <div class="row">
            <input v-model.trim="cfg.server" class="input code grow" :placeholder="info?.server ?? 'ruta a llama-server.exe o a su carpeta'" @change="saveCfg()" />
            <button class="btn btn--small" @click="pickServer">Elegir…</button>
          </div>
          <span class="hint">{{ info?.server ? `Se usará: ${info.server}` : "No lo encuentro: indica dónde está llama-server.exe" }}</span>
        </div>
        <div class="nums">
          <label class="field"><span class="label">Puerto</span><input v-model.number="cfg.port" type="number" min="1024" max="65535" @change="saveCfg()" /></label>
          <label class="field"><span class="label">Contexto (tokens)</span><input v-model.number="cfg.ctx" type="number" min="512" step="1024" @change="saveCfg()" /></label>
          <label class="field">
            <span class="label">Capas en GPU</span><input v-model.number="cfg.ngl" type="number" min="0" @change="saveCfg()" />
            <span class="hint">99 = todas en la GPU.</span>
          </label>
        </div>
      </div>
    </Card>
  </div>
</template>

<style scoped>
.okmsg {
  margin: 0;
  padding: 8px 14px;
  border-radius: var(--radius-sm);
  background: var(--ok-weak);
  color: var(--ok);
}
.server {
  display: grid;
  gap: 10px;
  padding: 16px 18px;
  border-radius: var(--radius);
  background: var(--panel);
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
}
.server__main {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.server__txt {
  display: grid;
  flex: 1;
  min-width: 200px;
}
.dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--ink-faint);
}
.server--ready .dot,
.server--external .dot {
  background: var(--ok);
  box-shadow: 0 0 0 4px var(--ok-weak);
}
.server--loading .dot {
  background: var(--info);
  box-shadow: 0 0 0 4px var(--info-weak);
  animation: pulse 1.2s infinite;
}
.server--failed .dot {
  background: var(--crit);
  box-shadow: 0 0 0 4px var(--crit-weak);
}
@keyframes pulse {
  50% {
    opacity: 0.35;
  }
}
.progress {
  display: grid;
  gap: 6px;
}
.bar {
  position: relative;
  height: 8px;
  border-radius: 99px;
  background: var(--panel-raised);
  overflow: hidden;
}
.bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--info);
  transition: width 0.6s ease;
}
.bar--unknown span {
  width: 30%;
  animation: slide 1.6s ease-in-out infinite;
}
@keyframes slide {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(340%);
  }
}
.loglines {
  display: grid;
  gap: 2px;
}
.loglines code {
  font-size: 12px;
  color: var(--ink-faint);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.launch {
  color: var(--accent);
  font-weight: 600;
}
.cfg-toggle {
  justify-self: start;
}
.own {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--line);
}
.own__wide {
  grid-column: 1 / -1;
}
.lagents {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  display: grid;
  gap: 8px;
}
.lagents li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 10px;
}
.warnline {
  flex-basis: 100%;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  background: var(--warn-weak);
  color: var(--warn);
}
.log {
  max-height: 240px;
  white-space: pre-wrap;
}
.hint {
  margin: 0;
}
.group + .group {
  margin-top: 16px;
}
.group__dir {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--ink-faint);
  overflow-wrap: anywhere;
}
.models {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 10px;
}
.model {
  display: grid;
  gap: 10px;
  align-content: start;
  padding: 14px;
  border-radius: var(--radius-sm);
  background: var(--panel-raised);
  border: 1px solid transparent;
}
.model--on {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-weak);
  background: var(--panel);
}
.model__head {
  display: flex;
  gap: 10px;
  align-items: center;
}
.chip-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: var(--panel);
  font-size: 18px;
  flex-shrink: 0;
}
.model__name {
  display: grid;
  min-width: 0;
}
.model__name strong {
  overflow-wrap: anywhere;
}
.input.mini {
  padding: 4px 8px;
  font-size: 13px;
}
.cfg {
  display: grid;
  gap: 18px;
}
.dirs {
  list-style: none;
  margin: 0 0 6px;
  padding: 0;
  display: grid;
  gap: 4px;
}
.dirs li {
  display: flex;
  align-items: center;
  gap: 8px;
  overflow-wrap: anywhere;
}
.grow {
  flex: 1;
  min-width: 200px;
}
.nums {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 14px;
}
</style>
