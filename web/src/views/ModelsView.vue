<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import ResourceUsage from "../components/ResourceUsage.vue";
import Card from "../components/Card.vue";
import LaunchDialog from "../components/LaunchDialog.vue";
import StatusChip from "../components/StatusChip.vue";
import {
  ROLE_TEXT, SERVER_ROLE_LABEL, SERVER_ROLE_TEXT, ago, api, duration, live, pickPath, post, refreshAll, refreshLocals,
  tps, type DownloadJob, type Hardware, type LlamaInfo, type LocalModel, type LocalServer, type LocalServerCfg,
  type ModelLaunch, type ModelRating, type Recommendation, type ServerRole,
} from "../api";

const info = ref<LlamaInfo | null>(null);
const error = ref("");
const msg = ref("");
const starting = ref<string | null>(null);
const now = ref(Date.now());

// configuración editable (se guarda en Ajustes → llama)
const cfg = reactive({
  server: "", model_dirs: [] as string[], port: 8080, ctx: 16384, ngl: 99, per_model: {} as Record<string, ModelLaunch>,
  hardware: {} as { vram_gb?: number | null; ram_gb?: number | null; gpu_name?: string; bandwidth_gbs?: number | null },
  hf_token: "", download_dir: "", autostart: false, autostart_on_task: true,
});
const newDir = ref("");

async function load(withCfg = false) {
  try {
    info.value = await api<LlamaInfo>("/api/llama");
    if (withCfg) {
      // los servidores se guardan aparte (si fueran con el resto, cambiar el puerto aquí no movería el del principal)
      const { servers, last, last_by_server, ...rest } = JSON.parse(JSON.stringify(info.value.config));
      void last; void last_by_server;
      Object.assign(cfg, rest);
      editServers.value = (servers?.length ? servers : info.value.servers.map(serverCfg)) as LocalServerCfg[];
    }
    if (!info.value.servers.some((s) => s.id === target.value)) target.value = info.value.servers[0]?.id ?? "principal";
    live.locals = info.value.servers.map((s) => ({ id: s.id, name: s.name, role: s.role, device: s.device,
      port: s.port, state: s.status.state, model: s.model_name }));
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
  const busy = info.value?.servers.some((s) => s.status.state === "loading");
  timer = setTimeout(poll, busy || starting.value ? 2000 : 6000);
}
onMounted(async () => {
  await load(true);
  timer = setTimeout(poll, 2000);
  loadHardware();
  loadRatings();
  loadRecs(true);
  pollDownloads();
  clock = setInterval(() => (now.value = Date.now()), 1000);
});
onUnmounted(() => {
  clearTimeout(timer);
  clearTimeout(dlTimer);
  clearInterval(clock);
});

const status = computed(() => info.value?.status); // el principal
// --- varios servidores locales (normalmente uno por GPU)
const servers = computed<LocalServer[]>(() => info.value?.servers ?? []);
const target = ref("principal"); // dónde arrancan los botones de «Tus modelos»
const targetSrv = computed(() => servers.value.find((s) => s.id === target.value) ?? servers.value[0]);
const openLog = ref<string | null>(null);
const serverCfg = (s: LocalServer): LocalServerCfg => ({ id: s.id, name: s.name, port: s.port, device: s.device, role: s.role,
  thinking: s.thinking ?? "normal" });
const THINK_TEXT: Record<string, string> = { normal: "lo que haga el modelo", apagado: "apagado (contesta al momento)",
  profundo: "siempre" };
const devices = computed(() => info.value?.devices ?? []);
const short = (name: string) => name.replace(/^NVIDIA GeForce /, "").replace(/^NVIDIA /, "");
function gpuText(dev: string): string {
  if (!dev) return devices.value.length > 1 ? "GPU: la que elija llama.cpp" : "";
  return dev.split(",").map((id) => {
    const d = devices.value.find((x) => x.id === id);
    return d ? `${short(d.name)} · ${Math.round(d.total_mb / 1024)} GB (${id})` : id;
  }).join(" + ");
}
const serversWith = (m: LocalModel) => servers.value.filter((s) => s.status.model === m.path && s.status.state !== "off");
const pid = (s: LocalServer) => s.status.pid;
const STATE: Record<string, { text: string; chip: "ok" | "warn" | "crit" | "pending" | "off" }> = {
  off: { text: "apagado", chip: "off" },
  loading: { text: "cargando el modelo…", chip: "pending" },
  ready: { text: "listo", chip: "ok" },
  failed: { text: "se ha caído", chip: "crit" },
  external: { text: "en marcha (lanzado fuera)", chip: "ok" },
};
const speed = computed(() => info.value?.speed ?? live.lastSpeed);

// --- arranque con ajustes (diálogo) y configuración propia de cada modelo
const dialogFor = ref<LocalModel | null>(null);
async function saveOwn(m: LocalModel, entry: ModelLaunch) {
  const per = { ...cfg.per_model };
  if (Object.keys(entry).length) per[m.path] = entry;
  else delete per[m.path];
  await saveCfg({ per_model: per });
  msg.value = isCurrent(m) ? "Guardado. Se aplica la próxima vez que arranques este modelo." : `Ajustes de ${m.name} guardados.`;
}
async function launchWith(m: LocalModel, options: ModelLaunch, save: boolean) {
  await start(m, options, save);
  if (!error.value) dialogFor.value = null;
}
function launchText(m: LocalModel): string {
  const c = cfg.per_model[m.path];
  if (!c) return "";
  return [c.ctx ? `ctx ${c.ctx}` : null, c.ngl !== undefined && c.ngl !== null ? `ngl ${c.ngl}` : null,
    c.cache_k && c.cache_k !== "f16" ? `kv ${c.cache_k}` : null, c.n_cpu_moe ? `expertos CPU ${c.n_cpu_moe}` : null,
    c.temp != null ? `temp ${c.temp}` : null, c.extra || null]
    .filter(Boolean).join(" · ");
}

// --- hardware
const hw = ref<Hardware | null>(null);
const editHw = ref(false);
async function loadHardware(refresh = false) {
  try {
    hw.value = await api<Hardware>(`/api/hardware${refresh ? "?refresh=true" : ""}`);
  } catch (e) {
    error.value = (e as Error).message;
  }
}
async function saveHw() {
  const h = { ...cfg.hardware };
  for (const k of Object.keys(h) as (keyof typeof h)[]) if (h[k] === "" || h[k] === null) delete h[k];
  await saveCfg({ hardware: h });
  editHw.value = false;
  await Promise.all([loadHardware(), loadRatings(), loadRecs(false)]);
}

// --- fichas (nota para LocalHarness) de los modelos descargados
const ratings = ref<Record<string, ModelRating>>({});
const ratingsLoading = ref(false);
async function loadRatings() {
  ratingsLoading.value = true;
  try {
    ratings.value = (await api<{ models: Record<string, ModelRating> }>("/api/llama/ratings")).models;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    ratingsLoading.value = false;
  }
}
const openInfo = ref<string | null>(null);
const scoreCls = (n: number) => (n >= 80 ? "ok" : n >= 60 ? "good" : n >= 40 ? "warn" : "crit");
const probing = ref(false);
async function probe(server = "principal") {
  probing.value = true;
  error.value = msg.value = "";
  try {
    const r = await post<{ model: string; probe: { tool_calls: boolean | null; json: boolean | null; tps?: number } }>(
      `/api/llama/probe?server=${encodeURIComponent(server)}`);
    const p = r.probe;
    msg.value = `Prueba hecha: herramientas ${p.tool_calls ? "✔" : "✘"} · JSON ${p.json ? "✔" : "✘"}${p.tps ? ` · ${p.tps} tok/s` : ""}`;
    await loadRatings();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    probing.value = false;
  }
}
// orden: los mejor valorados primero dentro de cada carpeta
const sortBy = ref<"score" | "name" | "size">("score");

// --- recomendaciones de Hugging Face
const recs = ref<Recommendation[]>([]);
const recErrors = ref<string[]>([]);
const recLoading = ref(false);
const showAllRecs = ref(false);
async function loadRecs(online = true) {
  recLoading.value = true;
  try {
    const r = await api<{ models: Recommendation[]; errors: string[] }>(`/api/llama/recommend?online=${online}`);
    recs.value = r.models;
    recErrors.value = r.errors;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    recLoading.value = false;
  }
}
const shownRecs = computed(() => (showAllRecs.value ? recs.value : recs.value.filter((r) => r.fit !== "no").slice(0, 6)));
const FIT_TEXT: Record<string, string> = { gpu: "cabe en la GPU", mixto: "GPU + RAM", cpu: "solo CPU", no: "no cabe" };
const FIT_CLS: Record<string, string> = { gpu: "ok", mixto: "warn", cpu: "warn", no: "crit" };
const pickedQuant = reactive<Record<string, string>>({});
function quantFor(r: Recommendation) {
  const q = pickedQuant[r.id] ?? r.best?.quant;
  return r.quants.find((x) => x.quant === q);
}

// buscar cualquier repo GGUF
const query = ref("");
const results = ref<{ repo: string; downloads: number; likes: number; url: string }[]>([]);
const repoInfo = ref<{ repo: string; url: string; quants: { quant: string; size_gb: number; files: string[]; fit: string; ctx: number; tps_est: number | null }[]; best: string | null } | null>(null);
const searching = ref(false);
async function search() {
  if (!query.value.trim()) return;
  searching.value = true;
  error.value = "";
  repoInfo.value = null;
  try {
    results.value = (await api<{ results: typeof results.value }>(`/api/llama/hf/search?q=${encodeURIComponent(query.value.trim())}`)).results;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    searching.value = false;
  }
}
async function openRepo(repo: string) {
  searching.value = true;
  try {
    repoInfo.value = await api(`/api/llama/hf/repo?repo=${encodeURIComponent(repo)}`);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    searching.value = false;
  }
}

// descargas
const downloads = ref<DownloadJob[]>([]);
let dlTimer: ReturnType<typeof setTimeout>;
async function pollDownloads() {
  try {
    const before = downloads.value.filter((j) => j.state === "downloading" || j.state === "queued").length;
    downloads.value = (await api<{ jobs: DownloadJob[] }>("/api/llama/downloads")).jobs;
    const active = downloads.value.filter((j) => j.state === "downloading" || j.state === "queued").length;
    if (before && active < before) { // acabó alguna: aparece en «Tus modelos»
      await load();
      await loadRatings();
      await loadRecs(false);
    }
    dlTimer = setTimeout(pollDownloads, active ? 1500 : 8000);
  } catch {
    dlTimer = setTimeout(pollDownloads, 8000);
  }
}
// antes de descargar: elegir carpeta (las de modelos, la última usada u otra con el selector de Windows)
const askDl = ref<{ repo: string; files: string[]; dest: string; size?: number } | null>(null);
const dlDirs = computed(() => [...new Set([cfg.download_dir, ...cfg.model_dirs, ...(info.value?.dirs ?? [])].filter(Boolean))]);
function download(repo: string, files: string[], size?: number) {
  if (!files.length) {
    error.value = "Sin la lista de archivos de Hugging Face no sé qué descargar: pulsa «Consultar Hugging Face».";
    return;
  }
  askDl.value = { repo, files, size, dest: dlDirs.value[0] ?? "" };
}
async function pickDlDir() {
  try {
    const p = await pickPath("folder", "Carpeta donde guardar el modelo");
    if (p && askDl.value) askDl.value.dest = p;
  } catch (e) {
    error.value = `${(e as Error).message}. Escribe la ruta a mano.`;
  }
}
async function confirmDownload() {
  const a = askDl.value;
  if (!a) return;
  const { repo, files } = a;
  error.value = msg.value = "";
  try {
    await post("/api/llama/download", { repo, files, dest: a.dest.trim() || null });
    askDl.value = null;
    await load(true);
    msg.value = `Descargando ${files[0].split("/").pop()}…`;
    clearTimeout(dlTimer);
    pollDownloads();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
async function cancelDownload(id: string) {
  await post("/api/llama/downloads/cancel", { id });
}
const gb = (b: number) => (b / 2 ** 30).toFixed(1);
const loadTime = (m: LocalModel) => info.value?.load_times?.[m.path];

const isCurrent = (m: LocalModel) => serversWith(m).length > 0;
const groups = computed(() => {
  const g: Record<string, LocalModel[]> = {};
  for (const m of info.value?.models ?? []) (g[m.dir] ??= []).push(m);
  const score = (m: LocalModel) => ratings.value[m.path]?.rating?.score ?? -1;
  for (const list of Object.values(g))
    list.sort((a, b) => sortBy.value === "score" ? score(b) - score(a)
      : sortBy.value === "size" ? b.size_gb - a.size_gb : a.name.localeCompare(b.name));
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

async function start(m: LocalModel, options?: ModelLaunch, save = false) {
  error.value = msg.value = "";
  starting.value = m.path;
  const srv = targetSrv.value;
  try {
    await post("/api/llama/start", { path: m.path, options, save, server: srv?.id ?? "principal" });
    if (save) await load(true);
    await load();
    msg.value = servers.value.length > 1 && srv
      ? `Arrancando ${m.name} en ${srv.name} (${gpuText(srv.device) || `puerto ${srv.port}`}).`
      : `Arrancando ${m.name}. Los agentes locales se conectarán a http://127.0.0.1:${cfg.port} cuando esté listo.`;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    starting.value = null;
  }
}

async function stop(server = "principal") {
  error.value = "";
  try {
    await post(`/api/llama/stop?server=${encodeURIComponent(server)}`);
    await load();
    await refreshLocals().catch(() => undefined);
  } catch (e) {
    error.value = (e as Error).message;
  }
}

// --- editor de servidores locales (Ajustes → llama.servers)
const editServers = ref<LocalServerCfg[]>([]);
const serversDirty = ref(false);
const ROLES: ServerRole[] = ["general", "fuerte", "rapido"];
function addServer() {
  const ports = editServers.value.map((s) => s.port);
  let port = Math.max(...ports, cfg.port) + 1;
  while (ports.includes(port)) port++;
  let id = "local2";
  for (let i = 2; editServers.value.some((s) => s.id === id); i++) id = `local${i}`;
  const used = editServers.value.map((s) => s.device);
  const free = devices.value.find((d) => !used.includes(d.id));
  editServers.value.push({ id, name: `Local ${editServers.value.length + 1}`, port, device: free?.id ?? "", role: "rapido",
    thinking: "apagado" });
  serversDirty.value = true;
}
function removeServer(id: string) {
  editServers.value = editServers.value.filter((s) => s.id !== id);
  serversDirty.value = true;
}
async function saveServers(list: LocalServerCfg[] = editServers.value) {
  error.value = msg.value = "";
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify({ llama: { servers: list } }) });
    serversDirty.value = false;
    await load(true);
    await refreshLocals().catch(() => undefined);
    msg.value = list.length > 1
      ? `Guardado: ${list.length} servidores locales. Arranca un modelo en cada uno desde «Tus modelos».`
      : "Guardado.";
  } catch (e) {
    error.value = (e as Error).message;
  }
}
const running = (id: string) => servers.value.find((s) => s.id === id)?.status.state !== "off";

// Agentes locales por ROL y sin modelo fijo: llama-server sirve uno a la vez y todos usan el que esté arrancado.
// Cambiar de modelo no obliga a crear otro agente.
const localAgents = computed(() => live.agents.filter((a) => a.provider.startsWith("local")));
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
function agentModel(a: { config: { server?: string } }): string {
  const s = a.config.server ? servers.value.find((x) => x.id === a.config.server) : servers.value[0];
  if (!s) return servedName.value ?? "(nada arrancado)";
  const name = s.model_name ?? "(nada arrancado)";
  return servers.value.length > 1 ? `${name} en ${s.name}` : name;
}
async function setAgentServer(id: number, server: string) {
  error.value = "";
  try {
    await api(`/api/agents/${id}`, { method: "PATCH", body: JSON.stringify({ server: server || null }) });
    await refreshAll();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2 class="title">Modelos locales</h2>
      <p>Tus GGUF con llama.cpp: arranca uno y los agentes locales lo usan gratis.</p>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="msg" class="okmsg">{{ msg }}</p>

    <!-- estado de cada servidor local (uno por GPU) -->
    <div class="servers" :class="{ 'servers--multi': servers.length > 1 }">
      <section v-for="srv in servers" :key="srv.id" class="server" :class="`server--${srv.status.state}`">
        <div class="server__main">
          <span class="dot" aria-hidden="true" />
          <div class="server__txt">
            <strong>
              <template v-if="servers.length > 1">{{ srv.name }} <span class="role" :class="`role--${srv.role}`">{{ SERVER_ROLE_LABEL[srv.role] }}</span> · </template>
              llama-server {{ STATE[srv.status.state]?.text }}
            </strong>
            <span class="muted small">
              <template v-if="srv.status.model">{{ srv.status.model.split(/[\\/]/).pop() }} · </template>
              <template v-if="gpuText(srv.device)">{{ gpuText(srv.device) }} · </template>
              puerto {{ srv.status.port }}
              <template v-if="srv.status.started_at"> · hace {{ duration(now - srv.status.started_at * 1000) }}</template>
              <template v-if="srv.status.state === 'failed'"> · código {{ srv.status.exit_code }}</template>
            </span>
            <span v-if="servers.length > 1" class="small muted">{{ SERVER_ROLE_TEXT[srv.role] }}</span>
          </div>
          <StatusChip :state="STATE[srv.status.state]?.chip ?? 'off'" :text="STATE[srv.status.state]?.text ?? srv.status.state" />
          <button v-if="srv.status.state === 'ready' || srv.status.state === 'external'" class="btn btn--small"
                  :disabled="probing" title="Herramientas, JSON y velocidad: gratis, es tu GPU" @click="probe(srv.id)">🧪</button>
          <button v-if="pid(srv)" class="btn btn--danger btn--small" @click="stop(srv.id)">Parar</button>
          <button v-if="srv.status.log" class="btn btn--ghost btn--small" @click="openLog = openLog === srv.id ? null : srv.id">
            {{ openLog === srv.id ? "Ocultar log" : "Ver log" }}</button>
        </div>
        <div v-if="srv.status.state === 'loading'" class="progress">
          <div class="bar" :class="{ 'bar--unknown': srv.status.progress?.pct == null }" role="progressbar"
               :aria-valuenow="srv.status.progress?.pct ?? undefined" aria-valuemin="0" aria-valuemax="100">
            <span :style="{ width: srv.status.progress?.pct != null ? `${srv.status.progress.pct}%` : undefined }" />
          </div>
          <span class="small muted">
            {{ srv.status.progress?.stage ?? "arrancando" }}<template v-if="srv.status.progress?.pct != null"> · {{ srv.status.progress.pct }} %</template>
            <template v-if="srv.status.progress?.eta_s"> · faltan ~{{ duration(srv.status.progress.eta_s * 1000) }}</template>
            <template v-if="srv.status.progress?.source === 'tiempo'"> (según lo que tardó la última vez)</template>
            <template v-else-if="srv.status.progress?.pct == null"> · la primera carga de cada modelo no tiene estimación</template>
          </span>
        </div>
        <div v-if="srv.status.log_lines?.length && openLog !== srv.id" class="loglines">
          <code v-for="(l, k) in srv.status.log_lines" :key="k">{{ l }}</code>
        </div>
        <pre v-if="openLog === srv.id && srv.status.log" class="block log">{{ srv.status.log }}</pre>
      </section>
    </div>
    <p v-if="speed?.tps" class="muted small hint">
      Velocidad {{ speed.final ? "de la última respuesta" : "ahora" }}: <strong>{{ tps(speed.tps) }}</strong>
      <template v-if="speed.model"> · {{ speed.model }}</template> · {{ ago(speed.at, now) }}
    </p>

    <!-- servidores locales: uno por GPU -->
    <Card title="Servidores locales" :subtitle="servers.length > 1
      ? `${servers.length} modelos a la vez: Claude reparte los encargos según el papel de cada uno`
      : 'Un llama-server. Con dos GPU puedes tener un modelo en cada una'">
      <div v-if="info?.suggested_servers" class="warnline block-info">
        <span>
          Tienes <strong>{{ devices.length }} GPU</strong>:
          <template v-for="(d, k) in devices" :key="d.id">{{ k ? " y " : "" }}{{ short(d.name) }} ({{ Math.round(d.total_mb / 1024) }} GB)</template>.
          Propuesta: el modelo <strong>fuerte</strong> (escribe código) en la grande y uno <strong>rápido</strong> (preguntas, resúmenes,
          investigar) en la otra, trabajando a la vez.
        </span>
        <button class="btn btn--primary btn--small" @click="saveServers(info.suggested_servers!)">Usar las {{ devices.length }} GPU</button>
      </div>
      <table class="srvtab">
        <thead><tr><th>Nombre</th><th>Papel</th><th>GPU</th><th>Pensamiento</th><th>Puerto</th><th /></tr></thead>
        <tbody>
          <tr v-for="s in editServers" :key="s.id">
            <td><input v-model.trim="s.name" class="input mini" maxlength="40" :aria-label="`Nombre de ${s.id}`" @input="serversDirty = true" />
              <span class="muted small mono"> {{ s.id }}</span></td>
            <td>
              <select v-model="s.role" class="input mini" aria-label="Papel" @change="serversDirty = true">
                <option v-for="r in ROLES" :key="r" :value="r">{{ SERVER_ROLE_LABEL[r] }} — {{ SERVER_ROLE_TEXT[r] }}</option>
              </select>
            </td>
            <td>
              <select v-model="s.device" class="input mini" aria-label="GPU" @change="serversDirty = true">
                <option value="">la que elija llama.cpp</option>
                <option v-for="d in devices" :key="d.id" :value="d.id">{{ gpuText(d.id) }}</option>
                <option v-if="devices.length > 1" :value="devices.map((d) => d.id).join(',')">las {{ devices.length }} juntas</option>
              </select>
            </td>
            <td>
              <select v-model="s.thinking" class="input mini" aria-label="Pensamiento" @change="serversDirty = true">
                <option v-for="(t, k) in THINK_TEXT" :key="k" :value="k">{{ t }}</option>
              </select>
            </td>
            <td><input v-model.number="s.port" class="input mini num" type="number" min="1024" max="65535" aria-label="Puerto" @input="serversDirty = true" /></td>
            <td>
              <button v-if="s.id !== 'principal'" class="btn btn--ghost btn--small" :disabled="running(s.id)"
                      :title="running(s.id) ? 'Páralo antes de quitarlo' : 'Quitar'" @click="removeServer(s.id)">Quitar</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="row">
        <button class="btn btn--small" :disabled="editServers.length >= 4" @click="addServer">+ Añadir servidor</button>
        <span class="grow" />
        <button class="btn btn--primary btn--small" :disabled="!serversDirty" @click="saveServers()">Guardar servidores</button>
      </div>
      <p v-if="devices.length > 1" class="hint">
        La numeración (CUDA0, CUDA1…) es la de llama.cpp, que ordena de la GPU más rápida a la más lenta: no tiene por qué
        coincidir con la de nvidia-smi ni con la del Administrador de tareas. Los cambios de GPU o puerto se aplican al
        volver a arrancar el modelo de ese servidor.
      </p>
    </Card>

    <!-- hardware -->
    <ResourceUsage />

    <Card title="Tu equipo" :subtitle="hw ? (hw.budget.manual ? 'Valores puestos a mano' : 'Detectado automáticamente') : 'Detectando…'">
      <template #actions>
        <button class="btn btn--small btn--ghost" @click="editHw = !editHw">{{ editHw ? "Cancelar" : "Corregir" }}</button>
        <button class="btn btn--small" @click="loadHardware(true)">Volver a detectar</button>
      </template>
      <div v-if="hw" class="hw">
        <div class="hw__item">
          <span class="label">GPU</span>
          <strong>{{ hw.budget.gpu ?? "Ninguna detectada" }}</strong>
          <span class="muted small">
            {{ hw.budget.vram_gb ? `${hw.budget.vram_gb} GB VRAM` : "sin VRAM: todo irá en la CPU" }}
            <template v-if="hw.gpus[0]?.vram_free_gb != null"> · {{ hw.gpus[0].vram_free_gb }} GB libres ahora</template>
            · ~{{ hw.budget.bandwidth_gbs }} GB/s
          </span>
        </div>
        <div class="hw__item">
          <span class="label">RAM</span>
          <strong>{{ hw.budget.ram_gb ? `${hw.budget.ram_gb} GB` : "?" }}</strong>
          <span class="muted small"><template v-if="hw.ram_free_gb">{{ hw.ram_free_gb }} GB libres</template></span>
        </div>
        <div class="hw__item">
          <span class="label">CPU</span>
          <strong class="ellipsis" :title="hw.cpu ?? ''">{{ hw.cpu ?? "?" }}</strong>
          <span class="muted small">{{ hw.cores }} hilos · {{ hw.os }}</span>
        </div>
      </div>
      <form v-if="editHw" class="nums hwedit" @submit.prevent="saveHw">
        <label class="field"><span class="label">VRAM (GB)</span><input v-model.number="cfg.hardware.vram_gb" type="number" min="0" step="0.5" placeholder="detectar" /></label>
        <label class="field"><span class="label">RAM (GB)</span><input v-model.number="cfg.hardware.ram_gb" type="number" min="0" step="1" placeholder="detectar" /></label>
        <label class="field"><span class="label">Nombre de la GPU</span><input v-model="cfg.hardware.gpu_name" placeholder="RTX 3060" /></label>
        <label class="field"><span class="label">Ancho de banda (GB/s)</span><input v-model.number="cfg.hardware.bandwidth_gbs" type="number" min="10" placeholder="según la GPU" /></label>
        <div class="row"><button class="btn btn--primary btn--small">Guardar</button><span class="hint">Vacío = lo detectado.</span></div>
      </form>
    </Card>

    <!-- modelos -->
    <Card title="Tus modelos" :subtitle="info ? `${info.models.length} encontrados en ${info.dirs.length} carpeta(s)` : 'Buscando…'">
      <template #actions>
        <select v-model="sortBy" class="input mini" aria-label="Ordenar">
          <option value="score">mejor nota</option><option value="size">tamaño</option><option value="name">nombre</option>
        </select>
        <button class="btn btn--small" @click="load(); loadRatings()">Volver a buscar</button>
      </template>
      <div v-if="info && !info.server" class="warnline block-warn">
        <span><strong>No puedo arrancar modelos:</strong> no sé dónde está <code>llama-server.exe</code>.
          Elige el archivo (o la carpeta de llama.cpp que descomprimiste).</span>
        <button class="btn btn--primary btn--small" @click="pickServer">Elegir llama-server…</button>
      </div>
      <div v-for="srv in servers.filter((x) => x.status.state === 'external')" :key="srv.id" class="warnline block-warn">
        <span>Hay un llama-server <strong>lanzado fuera de la app</strong> en el puerto {{ srv.status.port }}<template
          v-if="servers.length > 1"> ({{ srv.name }})</template>: los agentes ya lo usan, pero para arrancar otro modelo ahí desde
          aquí ciérralo antes (su ventana o Ctrl+C) o cambia el puerto en «Servidores locales».</span>
      </div>
      <div v-if="servers.length > 1" class="target">
        <span class="label">Arrancar en</span>
        <button v-for="srv in servers" :key="srv.id" type="button" class="preset" :class="{ on: target === srv.id }"
                :title="SERVER_ROLE_TEXT[srv.role]" @click="target = srv.id">
          {{ srv.name }}<small v-if="srv.device"> · {{ gpuText(srv.device) }}</small>
          <small v-if="srv.model_name"> · ahora {{ srv.model_name }}</small>
        </button>
      </div>
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
            <!-- nota para LocalHarness -->
            <div v-if="ratings[m.path]?.rating" class="score" :class="`score--${scoreCls(ratings[m.path].rating!.score)}`">
              <span class="score__num">{{ ratings[m.path].rating!.score }}</span>
              <span class="score__txt">
                <strong>{{ ratings[m.path].rating!.verdict }}</strong>
                <span class="small">para LocalHarness<template v-if="ratings[m.path].probe"> · probado</template></span>
              </span>
              <button class="btn btn--ghost btn--small" @click="openInfo = openInfo === m.path ? null : m.path">
                {{ openInfo === m.path ? "Ocultar" : "Por qué" }}
              </button>
            </div>
            <p v-else-if="ratings[m.path]?.meta?.error" class="small warnline">No pude leer la cabecera: {{ ratings[m.path].meta.error }}</p>
            <p v-else-if="ratingsLoading" class="small muted">Leyendo la ficha…</p>
            <div v-if="openInfo === m.path && ratings[m.path]?.rating" class="why small">
              <ul>
                <li v-for="(r, k) in ratings[m.path].rating!.reasons" :key="k">{{ r }}</li>
              </ul>
              <p v-if="ratings[m.path].rating!.roles.length"><strong>Para:</strong> {{ ratings[m.path].rating!.roles.join(", ") }}</p>
              <p class="muted">
                Herramientas {{ ratings[m.path].rating!.parts.tools }}/35 · cabe {{ ratings[m.path].rating!.parts.fit }}/25 ·
                capacidad {{ ratings[m.path].rating!.parts.quality }}/25 · velocidad {{ ratings[m.path].rating!.parts.speed }}/15
              </p>
              <p v-if="ratings[m.path].meta.arch" class="muted">
                {{ ratings[m.path].meta.arch }}<template v-if="ratings[m.path].meta.params_b"> · {{ ratings[m.path].meta.params_b }}B</template>
                <template v-if="ratings[m.path].meta.moe"> · MoE {{ ratings[m.path].meta.experts_used }}/{{ ratings[m.path].meta.experts }} expertos</template>
                · {{ ratings[m.path].meta.n_layer }} capas · contexto máx. {{ Math.round((ratings[m.path].meta.ctx_train ?? 0) / 1024) }}k
                <template v-if="m.vision"> · visión (mmproj)</template>
              </p>
              <p v-if="ratings[m.path].probe" class="muted">
                Prueba real {{ ago(ratings[m.path].probe!.at, now) }}: herramientas {{ ratings[m.path].probe!.tool_calls ? "✔" : "✘" }}
                ({{ ratings[m.path].probe!.tool_detail }}) · JSON {{ ratings[m.path].probe!.json ? "✔" : "✘" }}
                <template v-if="ratings[m.path].probe!.tps"> · {{ ratings[m.path].probe!.tps }} tok/s</template>
              </p>
              <p v-if="ratings[m.path].catalog" class="muted">{{ ratings[m.path].catalog!.notes }}</p>
            </div>
            <div class="row">
              <template v-for="srv in serversWith(m)" :key="srv.id">
                <StatusChip :state="STATE[srv.status.state].chip"
                            :text="servers.length > 1 ? `${STATE[srv.status.state].text} en ${srv.name}` : STATE[srv.status.state].text" />
                <button v-if="pid(srv)" class="btn btn--small btn--danger" @click="stop(srv.id)">Parar</button>
                <button v-if="srv.status.state === 'ready'" class="btn btn--small" :disabled="probing" title="Herramientas, JSON y velocidad: gratis, es tu GPU" @click="probe(srv.id)">
                  {{ probing ? "Probando…" : "🧪 Probar capacidades" }}
                </button>
              </template>
              <template v-if="!serversWith(m).some((x) => x.id === targetSrv?.id)">
                <button
                  class="btn btn--primary btn--small" :disabled="!!starting || !info?.server"
                  :title="info?.server ? 'Elegir contexto, caché, muestreo… antes de arrancar' : 'Falta la ruta de llama-server'" @click="dialogFor = m"
                >{{ starting === m.path ? "Arrancando…" : targetSrv?.status.pid ? "Cambiar a este…" : "Arrancar…" }}<template
                  v-if="servers.length > 1 && targetSrv"> en {{ targetSrv.name }}</template></button>
                <button class="btn btn--small btn--ghost" :disabled="!!starting || !info?.server" title="Con lo guardado, sin preguntar" @click="start(m)">Rápido</button>
              </template>
            </div>
          </article>
        </div>
      </div>
    </Card>

    <!-- recomendaciones y descargas -->
    <Card title="Recomendados para tu equipo" subtitle="Modelos GGUF de Hugging Face que mejor funcionan como agentes, con la cuantización y los ajustes que te caben.">
      <template #actions>
        <button class="btn btn--small" :disabled="recLoading" @click="loadRecs(true)">{{ recLoading ? "Consultando…" : "Consultar Hugging Face" }}</button>
      </template>
      <p v-if="recErrors.length && recs.length && !recs.some((r) => r.hf_checked)" class="small muted">
        Sin conexión con Hugging Face: tamaños estimados. Para descargar hace falta conexión.
      </p>
      <div class="recs">
        <article v-for="r in shownRecs" :key="r.id" class="rec">
          <div class="rec__head">
            <span class="score__num small-num" :class="`score--${scoreCls(r.score)}`">{{ r.score }}</span>
            <div class="rec__name">
              <a :href="r.url" target="_blank" rel="noopener"><strong>{{ r.name }}</strong></a>
              <span class="muted small">
                {{ r.params_b }}B<template v-if="r.moe"> (MoE, {{ r.active_b }}B activos)</template> · contexto {{ Math.round(r.ctx_train / 1024) }}k
              </span>
            </div>
          </div>
          <div class="tags">
            <span class="tag" :class="`tag--${FIT_CLS[r.fit]}`">{{ FIT_TEXT[r.fit] }}</span>
            <span class="tag">agente {{ r.agentic }}/10</span>
            <span v-if="r.tools" class="tag">herramientas</span>
            <span v-if="r.thinking" class="tag">razona</span>
            <span v-for="t in r.tags" :key="t" class="tag">{{ t }}</span>
            <span v-if="r.downloaded" class="tag tag--ok">ya lo tienes</span>
          </div>
          <p class="small muted">{{ r.notes }}</p>
          <p v-if="r.best" class="small">
            <strong>{{ r.best.quant }}</strong> · {{ r.best.size_gb.toFixed(1) }} GB<template v-if="!r.best.exact"> (aprox.)</template>
            · {{ Math.round(r.best.estimate.ctx / 1024) }}k contexto · ~{{ r.best.estimate.tps_est }} tok/s
            <br /><span class="muted">{{ r.best.why }}</span>
          </p>
          <div class="row">
            <select v-if="r.quants.length > 1" :value="quantFor(r)?.quant" class="input mini" aria-label="Cuantización"
                    @change="pickedQuant[r.id] = ($event.target as HTMLSelectElement).value">
              <option v-for="q in r.quants" :key="q.quant" :value="q.quant">
                {{ q.quant }} · {{ q.size_gb.toFixed(1) }} GB{{ q.quant === r.best?.quant ? " ★" : "" }}
              </option>
            </select>
            <button class="btn btn--small btn--primary" :disabled="!r.hf_checked" :title="r.hf_checked ? '' : 'Consulta antes Hugging Face'"
                    @click="download(r.repo, quantFor(r)?.files ?? r.best?.files ?? [], quantFor(r)?.size_gb)">Descargar</button>
          </div>
        </article>
      </div>
      <button v-if="recs.length" class="btn btn--ghost btn--small" @click="showAllRecs = !showAllRecs">
        {{ showAllRecs ? "Ver solo los que te caben" : `Ver los ${recs.length}` }}
      </button>

      <form class="row search" @submit.prevent="search">
        <input v-model="query" class="input grow" placeholder="Buscar cualquier GGUF en Hugging Face: qwen3.5, devstral, granite…" />
        <button class="btn btn--small" :disabled="searching">{{ searching ? "Buscando…" : "Buscar" }}</button>
      </form>
      <ul v-if="results.length && !repoInfo" class="results">
        <li v-for="x in results" :key="x.repo">
          <button class="linkbtn" @click="openRepo(x.repo)">{{ x.repo }}</button>
          <span class="muted small">{{ x.downloads?.toLocaleString() }} descargas · {{ x.likes }} ♥</span>
        </li>
      </ul>
      <div v-if="repoInfo" class="repo">
        <p class="row">
          <a :href="repoInfo.url" target="_blank" rel="noopener"><strong>{{ repoInfo.repo }}</strong></a>
          <button class="btn btn--ghost btn--small" @click="repoInfo = null">← resultados</button>
        </p>
        <table class="qt">
          <thead><tr><th>Cuant.</th><th>Tamaño</th><th>En tu equipo</th><th /></tr></thead>
          <tbody>
          <tr v-for="q in repoInfo.quants" :key="q.quant" :class="{ best: q.quant === repoInfo.best }">
            <td>{{ q.quant }}<template v-if="q.quant === repoInfo.best"> ★</template></td>
            <td>{{ q.size_gb.toFixed(1) }} GB</td>
            <td><span class="tag" :class="`tag--${FIT_CLS[q.fit]}`">{{ FIT_TEXT[q.fit] }}</span>
              <span class="muted small"> {{ Math.round(q.ctx / 1024) }}k<template v-if="q.tps_est"> · ~{{ q.tps_est }} tok/s</template></span></td>
            <td><button class="btn btn--small" @click="download(repoInfo.repo, q.files, q.size_gb)">Descargar</button></td>
          </tr>
          </tbody>
        </table>
        <p class="hint">Estimación por el nombre del repo; al descargarlo se lee su cabecera y la nota es exacta.</p>
      </div>

      <div v-if="downloads.length" class="dls">
        <div v-for="j in downloads" :key="j.id" class="dl">
          <span class="small"><strong>{{ j.files[0].split("/").pop() }}</strong>
            <template v-if="j.files.length > 1"> (+{{ j.files.length - 1 }} partes)</template></span>
          <div v-if="j.state === 'downloading' || j.state === 'queued'" class="bar"><span :style="{ width: j.total ? `${(j.done / j.total) * 100}%` : '5%' }" /></div>
          <span class="small muted">
            <template v-if="j.state === 'downloading'">{{ gb(j.done) }} / {{ j.total ? gb(j.total) : "?" }} GB · {{ j.speed }} MB/s</template>
            <template v-else-if="j.state === 'done'">✔ Descargado en {{ j.dest }}</template>
            <template v-else-if="j.state === 'failed'"><span class="error">✘ {{ j.error }}</span></template>
            <template v-else>{{ j.state === "cancelled" ? "Cancelada (se reanuda si la vuelves a lanzar)" : "En cola" }}</template>
          </span>
          <button v-if="j.state === 'downloading' || j.state === 'queued'" class="btn btn--ghost btn--small" @click="cancelDownload(j.id)">Cancelar</button>
        </div>
      </div>
    </Card>

    <!-- agentes locales -->
    <Card title="Agentes locales" subtitle="Todos usan el modelo que esté arrancado: si cambias de modelo, siguen funcionando.">
      <p v-if="!localAgents.length" class="empty">Aún no hay agentes locales.</p>
      <ul class="lagents">
        <li v-for="a in localAgents" :key="a.id">
          <strong>{{ a.name }}</strong>
          <span class="muted small">{{ ROLE_TEXT[a.role ?? ""] ?? a.role ?? "sin rol" }} · usa {{ agentModel(a) }}</span>
          <select v-if="servers.length > 1" class="input mini" :value="a.config.server ?? ''" aria-label="Servidor local"
                  @change="setAgentServer(a.id, ($event.target as HTMLSelectElement).value)">
            <option value="">el principal</option>
            <option v-for="s in servers.slice(1)" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
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
        <label class="check">
          <input v-model="cfg.autostart" type="checkbox" @change="saveCfg()" />
          Arrancar el último modelo al abrir LocalHarness
          <span class="muted small">(el que arrancaste la última vez en cada servidor, con los mismos ajustes)</span>
        </label>
        <label class="check">
          <input v-model="cfg.autostart_on_task" type="checkbox" @change="saveCfg()" />
          Arrancar solos los modelos cuando una tarea los necesita
          <span class="muted small">(si delega o coordina y están apagados: el último de cada servidor; así Claude no trabaja solo por un despiste)</span>
        </label>
        <div class="nums">
          <label class="field">
            <span class="label">Carpeta de descargas</span>
            <input v-model.trim="cfg.download_dir" class="code" :placeholder="cfg.model_dirs[0] ?? 'la primera carpeta de modelos'" @change="saveCfg()" />
          </label>
          <label class="field">
            <span class="label">Token de Hugging Face</span>
            <input v-model.trim="cfg.hf_token" type="password" autocomplete="off" placeholder="solo para repos restringidos" @change="saveCfg()" />
          </label>
        </div>
        <div class="nums">
          <label class="field"><span class="label">Puerto del principal</span><input v-model.number="cfg.port" type="number" min="1024" max="65535" @change="saveCfg()" /></label>
          <label class="field"><span class="label">Contexto (tokens)</span><input v-model.number="cfg.ctx" type="number" min="512" step="1024" @change="saveCfg()" /></label>
          <label class="field">
            <span class="label">Capas en GPU</span><input v-model.number="cfg.ngl" type="number" min="0" @change="saveCfg()" />
            <span class="hint">99 = todas en la GPU.</span>
          </label>
        </div>
      </div>
    </Card>

    <div v-if="askDl" class="overlay" @click.self="askDl = null">
      <form class="dl-dialog" @submit.prevent="confirmDownload">
        <h3>¿Dónde lo guardo?</h3>
        <p class="small muted">
          <strong>{{ askDl.files[0].split("/").pop() }}</strong><template v-if="askDl.files.length > 1"> (+{{ askDl.files.length - 1 }} partes)</template>
          <template v-if="askDl.size"> · {{ askDl.size.toFixed(1) }} GB</template> · de {{ askDl.repo }}
        </p>
        <label v-for="d in dlDirs" :key="d" class="dl-opt">
          <input v-model="askDl.dest" type="radio" :value="d" /> <code>{{ d }}</code>
        </label>
        <div class="row">
          <button type="button" class="btn btn--small" @click="pickDlDir">Elegir otra carpeta…</button>
          <input v-model="askDl.dest" class="input code grow" placeholder="o pega la ruta: D:\IA\modelos" />
        </div>
        <p class="hint">Se guarda en una subcarpeta con el nombre del repo. Si la carpeta no está entre las de modelos, se añade para que aparezca en «Tus modelos».</p>
        <div class="row dl-actions">
          <button type="button" class="btn btn--small" @click="askDl = null">Cancelar</button>
          <button class="btn btn--primary btn--small" :disabled="!askDl.dest.trim()">Descargar aquí</button>
        </div>
      </form>
    </div>

    <LaunchDialog
      v-if="dialogFor" :model="dialogFor" :rating="ratings[dialogFor.path]" :saved="cfg.per_model[dialogFor.path]"
      :defaults="{ ctx: cfg.ctx, ngl: cfg.ngl }" :busy="!!starting" :server="targetSrv" :devices="devices"
      @close="dialogFor = null" @launch="(o, save) => launchWith(dialogFor!, o, save)"
      @save="async (o) => { await saveOwn(dialogFor!, o); dialogFor = null; }"
    />
  </div>
</template>

<style scoped>
.servers {
  display: grid;
  gap: 12px;
}
.servers--multi {
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
}
.role {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 99px;
  font-size: 0.72rem;
  font-weight: 600;
  vertical-align: 1px;
  background: var(--panel-raised);
  color: var(--ink-dim);
}
.role--fuerte {
  background: var(--info-weak);
  color: var(--info);
}
.role--rapido {
  background: var(--ok-weak);
  color: var(--ok);
}
.block-info {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--info-weak);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.srvtab {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
.srvtab th {
  text-align: left;
  font-weight: 600;
  color: var(--ink-dim);
  padding: 4px 6px;
}
.srvtab td {
  padding: 4px 6px;
  border-top: 1px solid var(--line);
}
.srvtab .num {
  width: 90px;
}
.target {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.target .preset {
  padding: 6px 12px;
  border-radius: 99px;
  border: 1px solid var(--line);
  background: var(--panel);
  color: var(--ink);
  cursor: pointer;
}
.target .preset.on {
  border-color: var(--info);
  background: var(--info-weak);
  color: var(--info);
  font-weight: 600;
}
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
.hw {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 14px;
}
.hw__item {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.ellipsis {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hwedit {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
  align-items: end;
}
.score {
  display: flex;
  align-items: center;
  gap: 10px;
}
.score__txt {
  display: grid;
  flex: 1;
  line-height: 1.2;
}
.score__num {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  font-weight: 800;
  font-size: 16px;
  flex-shrink: 0;
  background: var(--panel);
}
.small-num {
  width: 34px;
  height: 34px;
  font-size: 14px;
}
.score--ok .score__num,
.score__num.score--ok {
  background: var(--ok-weak);
  color: var(--ok);
}
.score--good .score__num,
.score__num.score--good {
  background: var(--accent-weak);
  color: var(--accent);
}
.score--warn .score__num,
.score__num.score--warn {
  background: var(--warn-weak);
  color: var(--warn);
}
.score--crit .score__num,
.score__num.score--crit {
  background: var(--crit-weak);
  color: var(--crit);
}
.why ul {
  margin: 0 0 6px;
  padding-left: 18px;
}
.why p {
  margin: 4px 0;
}
.recs {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px;
  margin-bottom: 8px;
}
.rec {
  display: grid;
  gap: 8px;
  align-content: start;
  padding: 14px;
  border-radius: var(--radius-sm);
  background: var(--panel-raised);
}
.rec p {
  margin: 0;
}
.rec__head {
  display: flex;
  gap: 10px;
  align-items: center;
}
.rec__name {
  display: grid;
  min-width: 0;
}
.rec__name a {
  color: inherit;
  overflow-wrap: anywhere;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.tag {
  padding: 1px 8px;
  border-radius: 99px;
  font-size: 12px;
  background: var(--panel);
  color: var(--ink-faint);
}
.tag--ok {
  background: var(--ok-weak);
  color: var(--ok);
}
.tag--warn {
  background: var(--warn-weak);
  color: var(--warn);
}
.tag--crit {
  background: var(--crit-weak);
  color: var(--crit);
}
.search {
  margin-top: 14px;
}
.results {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.results li {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  align-items: baseline;
}
.linkbtn {
  border: 0;
  background: none;
  padding: 0;
  color: var(--accent);
  font: inherit;
  cursor: pointer;
  text-align: left;
  overflow-wrap: anywhere;
}
.repo {
  margin-top: 10px;
  overflow-x: auto;
}
.repo a {
  color: inherit;
}
.qt {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}
.qt th,
.qt td {
  padding: 5px 8px;
  text-align: left;
  border-bottom: 1px solid var(--line);
}
.qt tr.best td {
  background: var(--accent-weak);
}
.dls {
  display: grid;
  gap: 10px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}
.dl {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 4px 10px;
  align-items: center;
}
.dl .bar,
.dl > span:nth-of-type(2) {
  grid-column: 1;
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
.overlay {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgb(0 0 0 / 0.45);
}
.dl-dialog {
  width: min(560px, 100%);
  display: grid;
  gap: 10px;
  padding: 18px 20px;
  border-radius: var(--radius);
  background: var(--panel);
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
}
.dl-dialog h3,
.dl-dialog p {
  margin: 0;
}
.dl-opt {
  display: flex;
  gap: 8px;
  align-items: center;
  overflow-wrap: anywhere;
  cursor: pointer;
}
.dl-actions {
  justify-content: flex-end;
}
.check {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 8px;
}
.block-warn {
  margin-bottom: 12px;
  justify-content: space-between;
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
