<script setup lang="ts">
// Comparativa: la MISMA petición hecha de varias maneras (Claude solo / coordinando 1 modelo local / coordinando
// todos), una detrás de otra, y sus números lado a lado: lo que gasta tu plan, el tiempo, lo que hicieron los modelos
// locales y si pasan los tests. Cada variante queda en Trabajo para ver su diff. Datos: /api/compare.
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import Card from "../components/Card.vue";
import StatusChip from "../components/StatusChip.vue";
import { STATUS_TEXT, api, duration, live, post, refreshAll, statusChip, usd, type TaskStatus } from "../api";

interface Check { command: string; exit: number | null; ok: boolean; output: string }
interface Result {
  task_id: number; status: string; started?: number; seconds?: number | null; cost_usd?: number;
  claude_tokens?: number; claude_in?: number; claude_out?: number; claude_cache_read?: number; claude_tools?: number;
  local_tokens?: number; delegations?: number; delegations_ok?: number; local_seconds?: number;
  by_server?: Record<string, number>; files?: string[]; added?: number; deleted?: number; check?: Check;
}
interface Comparison {
  id: number; project_id: number; prompt: string; claude_model: string; check_cmd: string | null;
  variants: string[]; labels: Record<string, string>; results: Record<string, Result>;
  status: "pending" | "running" | "done" | "failed" | "cancelled" | "interrupted"; error: string | null;
  created_at: string; finished_at: string | null;
}

const list = ref<Comparison[]>([]);
const VARIANTS = ref<Record<string, string>>({});
const MODELS = ref<string[]>(["haiku", "sonnet", "opus"]);
const error = ref("");
const busy = ref(false);
const now = ref(Date.now());

const EXAMPLE = "Arregla todos los fallos del repositorio (calc.py e inventario.py) y añade tests de inventario.py.";
const form = reactive({ project_id: 0, prompt: EXAMPLE, variants: ["solo", "local1", "local2"] as string[],
  claude_model: "sonnet", check: "python -m unittest" });

async function load() {
  try {
    const r = await api<{ comparisons: Comparison[]; variants: Record<string, string>; models: string[] }>("/api/compare");
    list.value = r.comparisons;
    VARIANTS.value = r.variants;
    MODELS.value = r.models;
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  }
}
let timer: ReturnType<typeof setInterval>;
onMounted(async () => {
  if (!live.projects.length) await refreshAll().catch(() => undefined);
  const sandbox = live.projects.find((p) => p.name.startsWith("sandbox"));
  form.project_id = sandbox?.id ?? live.projects[0]?.id ?? 0;
  await load();
  timer = setInterval(() => {
    now.value = Date.now();
    if (running.value) load();
  }, 3000);
});
onUnmounted(() => clearInterval(timer));

const running = computed(() => list.value.some((c) => c.status === "running" || c.status === "pending"));
const isSandbox = computed(() => live.projects.find((p) => p.id === form.project_id)?.name.startsWith("sandbox"));

async function launch() {
  error.value = "";
  busy.value = true;
  try {
    await post("/api/compare", { ...form });
    await load();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
async function cancel(c: Comparison) {
  try {
    await post(`/api/compare/${c.id}/cancel`);
    await load();
  } catch (e) {
    error.value = (e as Error).message;
  }
}

// ---------- tabla: una fila por medida, una columna por variante; se marca la mejor de cada fila
const projectName = (id: number) => live.projects.find((p) => p.id === id)?.name ?? `#${id}`;
const fmt = (n: number | undefined | null) =>
  n == null ? "—" : n >= 1e6 ? `${(n / 1e6).toFixed(1)} M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)} k` : String(n);
const secs = (s: number | null | undefined) => (s == null ? "—" : duration(s * 1000));
type Row = { label: string; hint?: string; value: (r: Result) => number | null | undefined; show: (r: Result) => string;
  best?: "min" | "max" };
const ROWS: Row[] = [
  { label: "Tokens de Claude", hint: "lo que gasta tu plan: entrada nueva + salida", value: (r) => r.claude_tokens,
    show: (r) => fmt(r.claude_tokens), best: "min" },
  { label: "Caché leída", hint: "cuenta mucho menos para el plan", value: (r) => r.claude_cache_read, show: (r) => fmt(r.claude_cache_read) },
  { label: "Coste nominal", hint: "lo que costaría por API; con el plan no se paga", value: (r) => r.cost_usd,
    show: (r) => usd(r.cost_usd), best: "min" },
  { label: "Tiempo", value: (r) => r.seconds, show: (r) => secs(r.seconds), best: "min" },
  { label: "Herramientas de Claude", hint: "Read, Glob, encargos…", value: (r) => r.claude_tools, show: (r) => fmt(r.claude_tools) },
  { label: "Encargos al modelo local", value: (r) => r.delegations,
    show: (r) => (r.delegations ? `${r.delegations_ok}/${r.delegations} bien` : "—") },
  { label: "Tokens locales", hint: "gratis: tu GPU", value: (r) => r.local_tokens, show: (r) => fmt(r.local_tokens) },
  { label: "Por modelo local", value: () => null,
    show: (r) => Object.entries(r.by_server ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ") || "—" },
  { label: "Archivos cambiados", value: (r) => r.files?.length,
    show: (r) => (r.files ? `${r.files.length} (+${r.added ?? 0} −${r.deleted ?? 0})` : "—") },
];
function bestOf(c: Comparison, row: Row): string | null {
  if (!row.best) return null;
  const vals = c.variants.map((v) => [v, c.results[v]?.status !== "running" ? row.value(c.results[v] ?? ({} as Result)) : null] as const)
    .filter(([, n]) => typeof n === "number") as [string, number][];
  if (vals.length < 2) return null;
  const pick = row.best === "min" ? Math.min(...vals.map(([, n]) => n)) : Math.max(...vals.map(([, n]) => n));
  return vals.find(([, n]) => n === pick)?.[0] ?? null;
}
// ahorro de tokens de Claude frente a «Solo Claude»
function saving(c: Comparison, v: string): string | null {
  const base = c.results.solo?.claude_tokens;
  const mine = c.results[v]?.claude_tokens;
  if (v === "solo" || !base || mine == null || c.results[v]?.status === "running") return null;
  const pct = Math.round((1 - mine / base) * 100);
  return pct >= 0 ? `−${pct} % de plan` : `+${-pct} % de plan`;
}
const CHIP: Record<Comparison["status"], "ok" | "warn" | "crit" | "pending" | "off"> = {
  pending: "pending", running: "pending", done: "ok", failed: "crit", cancelled: "off", interrupted: "warn",
};
const STATE_TEXT: Record<Comparison["status"], string> = {
  pending: "en cola", running: "en marcha", done: "terminada", failed: "falló", cancelled: "cancelada",
  interrupted: "interrumpida (se cerró LocalHarness)",
};
const taskText = (s: string) => STATUS_TEXT[s as TaskStatus] ?? s;
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2 class="title">Comparativa</h2>
      <p>La misma petición con Claude solo y coordinando a tus modelos locales: cuánto plan gasta, cuánto tarda y si pasan los tests.</p>
    </div>
    <p v-if="error" class="error">{{ error }}</p>

    <Card title="Nueva comparativa" :subtitle="`Gasta tu plan: ${form.variants.length} tarea(s) de Claude, una detrás de otra. Los modelos locales arrancan solos si están apagados.`">
      <form class="cform" @submit.prevent="launch">
        <label class="field">
          <span class="label">Proyecto</span>
          <select v-model.number="form.project_id" class="input">
            <option v-for="p in live.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
          <span v-if="!isSandbox" class="hint">Mejor el sandbox (<code>python -m localharness sandbox</code>): tiene fallos conocidos y tests.</span>
        </label>
        <label class="field wide">
          <span class="label">Petición (la misma para todas)</span>
          <textarea v-model="form.prompt" class="input" rows="3" />
        </label>
        <fieldset class="field">
          <span class="label">Variantes</span>
          <label v-for="(text, k) in VARIANTS" :key="k" class="check">
            <input v-model="form.variants" type="checkbox" :value="k" /> {{ text }}
          </label>
        </fieldset>
        <label class="field">
          <span class="label">Modelo de Claude</span>
          <select v-model="form.claude_model" class="input">
            <option v-for="m in MODELS" :key="m" :value="m">{{ m }}</option>
          </select>
          <span class="hint">El mismo en todas las variantes.</span>
        </label>
        <label class="field">
          <span class="label">Comprobación al terminar</span>
          <input v-model="form.check" class="input code" placeholder="python -m unittest" />
          <span class="hint">Se ejecuta en el worktree de cada variante (tests y linters de la lista permitida).</span>
        </label>
        <div class="row wide">
          <button class="btn btn--primary" :disabled="busy || running || !form.project_id || !form.variants.length || form.prompt.trim().length < 3">
            {{ running ? "Hay una en marcha…" : busy ? "Lanzando…" : "Lanzar comparativa" }}
          </button>
        </div>
      </form>
    </Card>

    <p v-if="!list.length" class="empty">Aún no hay comparativas.</p>
    <Card v-for="c in list" :key="c.id" :title="`#${c.id} · ${projectName(c.project_id)} · Claude ${c.claude_model}`" :subtitle="c.prompt">
      <template #actions>
        <StatusChip :state="CHIP[c.status]" :text="STATE_TEXT[c.status]" />
        <button v-if="c.status === 'running' || c.status === 'pending'" class="btn btn--small btn--danger" @click="cancel(c)">Cancelar</button>
      </template>
      <p v-if="c.error" class="error small">{{ c.error }}</p>
      <div class="tablewrap">
        <table class="cmp">
          <thead>
            <tr>
              <th />
              <th v-for="v in c.variants" :key="v">
                {{ c.labels[v] ?? v }}
                <small v-if="saving(c, v)" class="save" :class="{ worse: saving(c, v)!.startsWith('+') }">{{ saving(c, v) }}</small>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th>Estado</th>
              <td v-for="v in c.variants" :key="v">
                <template v-if="c.results[v]">
                  <StatusChip v-if="c.results[v].status !== 'running'" :state="statusChip(c.results[v].status as TaskStatus)" :text="taskText(c.results[v].status)" />
                  <span v-else class="small">trabajando… {{ c.results[v].started ? duration(now - c.results[v].started! * 1000) : "" }}</span>
                  <RouterLink :to="`/tareas/${c.results[v].task_id}`" class="small"> ver #{{ c.results[v].task_id }} →</RouterLink>
                </template>
                <span v-else class="muted small">esperando</span>
              </td>
            </tr>
            <tr v-for="row in ROWS" :key="row.label">
              <th :title="row.hint">{{ row.label }}<small v-if="row.hint">{{ row.hint }}</small></th>
              <td v-for="v in c.variants" :key="v" :class="{ best: bestOf(c, row) === v }">
                {{ c.results[v] && c.results[v].status !== "running" ? row.show(c.results[v]) : "—" }}
              </td>
            </tr>
            <tr v-if="c.check_cmd">
              <th>Tests <small class="mono">{{ c.check_cmd }}</small></th>
              <td v-for="v in c.variants" :key="v">
                <template v-if="c.results[v]?.check">
                  <span :class="c.results[v].check!.ok ? 'pass' : 'fail'" :title="c.results[v].check!.output">
                    {{ c.results[v].check!.ok ? "✔ pasan" : c.results[v].check!.exit === null ? "✘ no se pudo ejecutar" : `✘ fallan (código ${c.results[v].check!.exit})` }}
                  </span>
                </template>
                <span v-else>—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="hint">
        Las tareas quedan en <RouterLink to="/trabajo">Trabajo</RouterLink> para que veas el diff de cada una; nada se integra solo.
        La celda verde es la mejor de su fila.
      </p>
    </Card>
  </div>
</template>

<style scoped>
.cform {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 14px;
}
.cform .wide {
  grid-column: 1 / -1;
}
.cform fieldset {
  border: 0;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.cform textarea {
  resize: vertical;
  font: inherit;
}
.tablewrap {
  overflow-x: auto;
}
.cmp {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
  font-variant-numeric: tabular-nums;
}
.cmp th,
.cmp td {
  padding: 7px 10px;
  border-top: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}
.cmp thead th {
  border-top: 0;
  font-weight: 700;
}
.cmp tbody th {
  font-weight: 600;
  color: var(--ink-dim);
  white-space: nowrap;
}
.cmp th small {
  display: block;
  font-weight: 400;
  font-size: 0.74rem;
  color: var(--ink-faint);
  white-space: normal;
}
.cmp td.best {
  background: var(--ok-weak);
  color: var(--ok);
  font-weight: 700;
}
.save {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 7px;
  border-radius: 99px;
  background: var(--ok-weak);
  color: var(--ok);
  font-size: 0.74rem;
}
.save.worse {
  background: var(--crit-weak);
  color: var(--crit);
}
.pass {
  color: var(--ok);
  font-weight: 600;
}
.fail {
  color: var(--crit);
  font-weight: 600;
}
</style>
