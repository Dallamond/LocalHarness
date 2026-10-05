<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import Card from "../components/Card.vue";
import StatusChip from "../components/StatusChip.vue";
import { api, duration, live, pickPath, post, refreshAll, type LlamaInfo, type LocalModel } from "../api";

const info = ref<LlamaInfo | null>(null);
const error = ref("");
const msg = ref("");
const starting = ref<string | null>(null);
const showLog = ref(false);
const now = ref(Date.now());

// configuración editable (se guarda en Ajustes → llama)
const cfg = reactive({ server: "", model_dirs: [] as string[], port: 8080, ctx: 16384, ngl: 99 });
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

// crear un agente local con el nombre del modelo (el modelo concreto lo decide el servidor arrancado)
const roleFor = reactive<Record<string, string>>({});
async function createAgent(m: LocalModel) {
  const role = roleFor[m.path] ?? "jefe";
  const base = m.name.toLowerCase().replace(/[^a-z0-9.]+/g, "-").replace(/-+$/, "").slice(0, 40);
  let name = `${base}-${role}`;
  for (let i = 2; live.agents.some((a) => a.name === name); i++) name = `${base}-${role}-${i}`;
  error.value = msg.value = "";
  try {
    await post("/api/agents", {
      name, provider: "local", role, model: m.name,
      description: `Modelo local ${m.name}${m.quant ? ` (${m.quant})` : ""}, sin coste. Lee el repo en el prompt; no edita archivos.`,
    });
    await refreshAll();
    msg.value = `Agente ${name} creado. Úsalo como ${role === "director" ? "Director" : "jefe técnico"} o para preguntas en el Chat.`;
  } catch (e) {
    error.value = (e as Error).message;
  }
}
const agentsFor = (m: LocalModel) => live.agents.filter((a) => a.provider === "local" && a.model === m.name);
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
      <pre v-if="showLog && status.log" class="block log">{{ status.log }}</pre>
      <p v-if="status.state === 'loading'" class="muted small hint">Cargar un modelo del disco a la GPU puede tardar varios minutos.</p>
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
                <span class="muted small">{{ m.size_gb.toFixed(1) }} GB<template v-if="m.quant"> · {{ m.quant }}</template></span>
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
            <div class="model__agents">
              <span v-for="a in agentsFor(m)" :key="a.id" class="tag">{{ a.name }}</span>
              <span class="row">
                <select v-model="roleFor[m.path]" class="input mini" aria-label="Rol del agente">
                  <option :value="undefined" disabled>rol…</option>
                  <option value="jefe">jefe técnico</option>
                  <option value="director">director</option>
                  <option value="trabajador">consultas</option>
                </select>
                <button class="btn btn--small btn--ghost" @click="createAgent(m)">+ Crear agente</button>
              </span>
            </div>
          </article>
        </div>
      </div>
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
.model__agents {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  padding-top: 8px;
  border-top: 1px solid var(--line);
}
.tag {
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--accent-weak);
  color: var(--accent);
  font-size: 12.5px;
  font-weight: 600;
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
