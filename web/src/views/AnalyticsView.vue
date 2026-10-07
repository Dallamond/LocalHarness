<script setup lang="ts">
// Analíticas: peticiones, tokens (Claude y modelo local), coste, encargos al modelo local y uso por agente.
// Todo sale de /api/analytics (tareas y eventos guardados). Gráfico de barras apiladas por día en SVG propio.
import { computed, onMounted, ref, watch } from "vue";
import { api, usd } from "../api";

interface Row { requests: number; cost_usd: number; claude_in: number; claude_out: number; local_in: number; local_out: number; delegations: number }
interface Data {
  days: number;
  total: Row & { tasks: number; plans: number; delegations_ok: number; seconds_local: number; claude_tokens: number;
    local_tokens: number; tokens: number; local_share: number };
  by_day: { day: string; requests: number; cost_usd: number; claude_tokens: number; local_tokens: number }[];
  by_agent: (Row & { agent: string; provider: string; tasks: number })[];
  by_tool: Record<string, number>;
  by_status: Record<string, number>;
  by_model: Record<string, number>;
}

const days = ref(30);
const data = ref<Data | null>(null);
const error = ref("");
async function load() {
  error.value = "";
  try {
    data.value = await api<Data>(`/api/analytics?days=${days.value}`);
  } catch (e) {
    error.value = (e as Error).message;
  }
}
onMounted(load);
watch(days, load);

const fmt = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)} M` : n >= 1e3 ? `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)} k` : String(n));
const full = (n: number) => n.toLocaleString("es-ES");
const TOOL_TEXT: Record<string, string> = { ask: "Preguntas", write_file: "Escribir archivo", execute_plan: "Bloques de plan",
  agent: "Tareas con herramientas", research: "Investigar en internet", run_checks: "Pasar tests" };
const PROV: Record<string, string> = { claude: "Claude", local: "Local", local_agent: "Local (herramientas)", codex: "Codex" };

// ---------- gráfico: tokens por día, Claude + local apilados (un solo eje)
const W = 760, H = 220, PAD = { l: 44, r: 8, t: 10, b: 24 };
const view = ref<"chart" | "table">("chart");
const series = computed(() => data.value?.by_day ?? []);
const maxY = computed(() => {
  const m = Math.max(1, ...series.value.map((d) => d.claude_tokens + d.local_tokens));
  const p = 10 ** Math.floor(Math.log10(m));
  return Math.ceil(m / p) * p;
});
const ticks = computed(() => [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(maxY.value * f)));
const bw = computed(() => (W - PAD.l - PAD.r) / Math.max(1, series.value.length));
const y = (v: number) => PAD.t + (H - PAD.t - PAD.b) * (1 - v / maxY.value);
const x = (i: number) => PAD.l + i * bw.value;
const hover = ref<number | null>(null);
const hov = computed(() => (hover.value === null ? null : series.value[hover.value]));
const shortDay = (d: string) => `${Number(d.slice(8))}/${Number(d.slice(5, 7))}`;
const labelEvery = computed(() => Math.ceil(series.value.length / 10));
/** Barra apilada: local abajo (anclada a la base), Claude encima, con 2 px de hueco entre las dos. */
function bars(i: number) {
  const d = series.value[i];
  const w = Math.max(2, bw.value - (bw.value > 8 ? 4 : 1));
  const x0 = x(i) + (bw.value - w) / 2;
  const base = y(0);
  const hl = base - y(d.local_tokens);
  const hc = base - y(d.claude_tokens);
  const gap = hl > 0 && hc > 0 ? 2 : 0;
  return { x0, w, local: { y: base - hl, h: hl }, claude: { y: base - hl - gap - hc, h: Math.max(0, hc) } };
}
const totalTokens = computed(() => data.value?.total.tokens ?? 0);

const maxAgent = computed(() => Math.max(1, ...(data.value?.by_agent ?? []).map((a) => a.claude_in + a.claude_out + a.local_in + a.local_out)));
const toolRows = computed(() => Object.entries(data.value?.by_tool ?? {}));
const maxTool = computed(() => Math.max(1, ...toolRows.value.map(([, n]) => n)));
</script>

<template>
  <div class="page an">
    <div class="page-head">
      <h2 class="title">Analíticas</h2>
      <p>Peticiones, tokens y uso del modelo local y de los agentes.</p>
      <div class="seg" role="group" aria-label="Periodo">
        <button v-for="d in [7, 30, 90, 365]" :key="d" :class="{ on: days === d }" @click="days = d">{{ d === 365 ? "1 año" : `${d} días` }}</button>
      </div>
    </div>
    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="data">
      <!-- cifras principales -->
      <div class="tiles">
        <div class="tile card"><span>Peticiones</span><b>{{ full(data.total.requests) }}</b><small>{{ data.total.tasks }} tareas · {{ data.total.plans }} planes</small></div>
        <div class="tile card"><span>Tokens totales</span><b>{{ fmt(data.total.tokens) }}</b><small>{{ full(data.total.tokens) }}</small></div>
        <div class="tile card"><span><i class="sw sw--claude" />Tokens de Claude</span><b>{{ fmt(data.total.claude_tokens) }}</b><small>{{ fmt(data.total.claude_in) }} entrada · {{ fmt(data.total.claude_out) }} salida</small></div>
        <div class="tile card"><span><i class="sw sw--local" />Tokens del modelo local</span><b>{{ fmt(data.total.local_tokens) }}</b><small>{{ Math.round(data.total.local_share * 100) }} % del total · gratis</small></div>
        <div class="tile card"><span>Coste de Claude</span><b>{{ usd(data.total.cost_usd) }}</b><small>lo que diría la API; con suscripción es uso del plan</small></div>
        <div class="tile card"><span>Encargos al modelo local</span><b>{{ full(data.total.delegations) }}</b><small>{{ data.total.delegations_ok }} bien · {{ Math.round(data.total.seconds_local / 60) }} min de trabajo</small></div>
      </div>

      <!-- tokens por día -->
      <section class="card pad">
        <div class="head">
          <h3 class="card-title">Tokens por día</h3>
          <div class="legend">
            <span><i class="sw sw--claude" />Claude</span>
            <span><i class="sw sw--local" />Modelo local</span>
          </div>
          <div class="seg seg--small">
            <button :class="{ on: view === 'chart' }" @click="view = 'chart'"><i class="fa-solid fa-chart-column" /> Gráfico</button>
            <button :class="{ on: view === 'table' }" @click="view = 'table'"><i class="fa-solid fa-table" /> Tabla</button>
          </div>
        </div>
        <p v-if="!totalTokens" class="muted small">Sin tokens en este periodo.</p>
        <div v-else-if="view === 'chart'" class="chart">
          <svg :viewBox="`0 0 ${W} ${H}`" role="img" :aria-label="`Tokens por día de los últimos ${data.days} días`" @mouseleave="hover = null">
            <g class="grid">
              <g v-for="t in ticks" :key="t">
                <line :x1="PAD.l" :x2="W - PAD.r" :y1="y(t)" :y2="y(t)" />
                <text :x="PAD.l - 6" :y="y(t) + 3" text-anchor="end">{{ fmt(t) }}</text>
              </g>
            </g>
            <g v-for="(d, i) in series" :key="d.day">
              <template v-if="d.claude_tokens + d.local_tokens">
                <rect v-if="bars(i).local.h > 0" class="b b--local" :x="bars(i).x0" :y="bars(i).local.y" :width="bars(i).w" :height="bars(i).local.h" rx="2" />
                <rect v-if="bars(i).claude.h > 0" class="b b--claude" :x="bars(i).x0" :y="bars(i).claude.y" :width="bars(i).w" :height="bars(i).claude.h" rx="2" />
              </template>
              <text v-if="i % labelEvery === 0" class="xl" :x="x(i) + bw / 2" :y="H - 6" text-anchor="middle">{{ shortDay(d.day) }}</text>
              <!-- zona de hover más grande que la barra -->
              <rect class="hit" :class="{ on: hover === i }" :x="x(i)" :y="PAD.t" :width="bw" :height="H - PAD.t - PAD.b" @mouseenter="hover = i" />
            </g>
          </svg>
          <div v-if="hov" class="tip" :style="{ left: `${((x(hover!) + bw / 2) / W) * 100}%` }">
            <b>{{ shortDay(hov.day) }}</b>
            <span><i class="sw sw--claude" />Claude <em>{{ full(hov.claude_tokens) }}</em></span>
            <span><i class="sw sw--local" />Local <em>{{ full(hov.local_tokens) }}</em></span>
            <span class="muted">{{ hov.requests }} peticiones · {{ usd(hov.cost_usd) }}</span>
          </div>
        </div>
        <div v-else class="tablewrap">
          <table class="tbl">
            <thead><tr><th>Día</th><th>Peticiones</th><th>Tokens Claude</th><th>Tokens local</th><th>Coste</th></tr></thead>
            <tbody>
              <tr v-for="d in [...series].reverse().filter((r) => r.requests || r.claude_tokens || r.local_tokens)" :key="d.day">
                <td>{{ d.day }}</td><td>{{ d.requests }}</td><td>{{ full(d.claude_tokens) }}</td><td>{{ full(d.local_tokens) }}</td><td>{{ usd(d.cost_usd) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div class="two">
        <!-- por agente -->
        <section class="card pad">
          <h3 class="card-title">Uso por agente</h3>
          <p v-if="!data.by_agent.length" class="muted small">Sin actividad.</p>
          <div v-for="a in data.by_agent" :key="a.agent" class="arow">
            <div class="aname"><b>{{ a.agent }}</b><small>{{ PROV[a.provider] ?? a.provider }} · {{ a.tasks }} tareas · {{ a.requests }} peticiones{{ a.delegations ? ` · ${a.delegations} encargos` : "" }}</small></div>
            <div class="meter" :title="`Claude ${full(a.claude_in + a.claude_out)} · local ${full(a.local_in + a.local_out)}`">
              <i class="sw--claude" :style="{ width: `${((a.claude_in + a.claude_out) / maxAgent) * 100}%` }" />
              <i class="sw--local" :style="{ width: `${((a.local_in + a.local_out) / maxAgent) * 100}%` }" />
            </div>
            <div class="anum">{{ fmt(a.claude_in + a.claude_out + a.local_in + a.local_out) }}<small>{{ usd(a.cost_usd) }}</small></div>
          </div>
        </section>

        <div class="stack">
          <section class="card pad">
            <h3 class="card-title">Encargos al modelo local por tipo</h3>
            <p v-if="!toolRows.length" class="muted small">Ningún encargo todavía.</p>
            <div v-for="[t, n] in toolRows" :key="t" class="trow">
              <span>{{ TOOL_TEXT[t] ?? t }}</span>
              <div class="meter"><i class="sw--local" :style="{ width: `${(n / maxTool) * 100}%` }" /></div>
              <b>{{ n }}</b>
            </div>
          </section>
          <section class="card pad">
            <h3 class="card-title">Tokens por modelo local</h3>
            <p v-if="!Object.keys(data.by_model).length" class="muted small">Sin datos.</p>
            <div v-for="(n, m) in data.by_model" :key="m" class="trow">
              <span class="mono">{{ m }}</span><b>{{ fmt(n) }}</b>
            </div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.an {
  --c-claude: #5b5bf0;
  --c-local: #0891b2;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .an { --c-claude: #7a7af4; --c-local: #0a9fc0; }
}
:root[data-theme="dark"] .an { --c-claude: #7a7af4; --c-local: #0a9fc0; }
.page-head .seg { margin-left: auto; }
.seg { display: inline-flex; gap: 2px; padding: 3px; border-radius: 12px; background: var(--panel-raised); }
.seg button { border: 0; background: none; font: inherit; font-size: 12.5px; font-weight: 700; color: var(--ink-dim); padding: 5px 10px; border-radius: 9px; cursor: pointer; }
.seg button.on { background: var(--panel); color: var(--ink); box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12); }
.seg--small button { font-size: 11.5px; padding: 4px 8px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: var(--gap); }
.tile { padding: 14px 16px; display: grid; gap: 2px; }
.tile span { font-size: 12px; font-weight: 700; color: var(--ink-dim); display: flex; align-items: center; gap: 6px; }
.tile b { font-size: 26px; font-weight: 800; color: var(--ink); font-variant-numeric: tabular-nums; }
.tile small { color: var(--ink-faint); font-size: 11.5px; }
.sw { display: inline-block; width: 10px; height: 10px; border-radius: 3px; }
.sw--claude { background: var(--c-claude); }
.sw--local { background: var(--c-local); }
.pad { padding: 16px 18px; }
.head { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 8px; }
.head .card-title { margin: 0; }
.head .seg { margin-left: auto; }
.legend { display: flex; gap: 12px; font-size: 12px; color: var(--ink-dim); font-weight: 600; }
.legend span { display: flex; align-items: center; gap: 5px; }
.chart { position: relative; }
svg { width: 100%; height: auto; display: block; }
.grid line { stroke: var(--line); stroke-width: 1; }
.grid text, .xl { fill: var(--ink-faint); font-size: 10px; font-variant-numeric: tabular-nums; }
.b--claude { fill: var(--c-claude); }
.b--local { fill: var(--c-local); }
.hit { fill: transparent; }
.hit.on { fill: var(--ink); fill-opacity: 0.05; }
.tip {
  position: absolute; top: 4px; transform: translateX(-50%); pointer-events: none; display: grid; gap: 2px;
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 7px 10px; font-size: 12px;
  box-shadow: 0 8px 18px -10px rgba(0, 0, 0, 0.4); white-space: nowrap; color: var(--ink);
}
.tip span { display: flex; align-items: center; gap: 6px; }
.tip em { font-style: normal; font-weight: 700; margin-left: auto; padding-left: 10px; font-variant-numeric: tabular-nums; }
.tablewrap { max-height: 320px; overflow: auto; }
.tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
.tbl th, .tbl td { text-align: right; padding: 5px 8px; border-bottom: 1px solid var(--line); }
.tbl th:first-child, .tbl td:first-child { text-align: left; }
.two { display: grid; grid-template-columns: 1.4fr 1fr; gap: var(--gap); }
.stack { display: grid; gap: var(--gap); align-content: start; }
.arow { display: grid; grid-template-columns: minmax(140px, 1.1fr) 1.4fr 70px; gap: 12px; align-items: center; padding: 7px 0; border-bottom: 1px solid var(--line); }
.arow:last-child { border-bottom: 0; }
.aname { display: grid; min-width: 0; }
.aname b { font-size: 13px; }
.aname small { color: var(--ink-faint); font-size: 11px; }
.meter { display: flex; gap: 2px; height: 10px; border-radius: 4px; background: var(--meter); overflow: hidden; }
.meter i { display: block; height: 100%; border-radius: 4px; }
.anum { text-align: right; font-weight: 800; font-variant-numeric: tabular-nums; display: grid; }
.anum small { font-weight: 600; color: var(--ink-faint); font-size: 11px; }
.trow { display: grid; grid-template-columns: 1fr 1fr 40px; gap: 10px; align-items: center; padding: 5px 0; font-size: 12.5px; }
.trow:has(.mono) { grid-template-columns: 1fr auto; }
.trow b { text-align: right; font-variant-numeric: tabular-nums; }
.mono { font-family: var(--mono, ui-monospace, monospace); font-size: 12px; overflow-wrap: anywhere; }
@media (max-width: 900px) {
  .two { grid-template-columns: 1fr; }
}
</style>
