<script setup lang="ts">
// Panel inferior de la oficina: Timeline (lo que pasa en la misión), Terminal (herramientas que usan los agentes)
// Diff (cambios de la tarea seleccionada) y Modelos (cada modelo local: qué tiene cargado, qué encargo hace, a qué
// velocidad y qué piensa/escribe en directo). Datos reales: eventos de las tareas de la misión, /review y worker_live.
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import { SERVER_ROLE_LABEL, agentColor, agentName, duration, live, parseTs, tps, type Review, type TaskEvent } from "../api";

const props = defineProps<{ events: TaskEvent[]; review: Review | null; reviewTitle: string }>();
type Tab = "time" | "term" | "diff" | "models";
const tab = ref<Tab>("time");
const min = ref(false);
const body = ref<HTMLElement>();

const SKIP = new Set(["speed", "usage", "limit", "session"]);

function when(e: TaskEvent): string {
  const ms = e.ts ? parseTs(e.ts) : Date.now();
  return Number.isNaN(ms) ? "" : new Date(ms).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

const who = (e: TaskEvent) => {
  if (e.kind === "user") return { name: "Tú", color: "#eab308" };
  if (e.kind === "delegate" || e.kind === "delegate_summary") return { name: "Modelo local", color: "#0ea5e9" };
  const aid = live.tasks[e.task_id]?.agent_id ?? null;
  return { name: agentName(aid), color: agentColor(live.agents.find((a) => a.id === aid)) };
};

const STATUS: Record<string, string> = {
  running: "empieza a trabajar", review: "terminó: cambios listos para revisar", done: "terminó",
  failed: "falló", timeout: "se quedó sin tiempo", cancelled: "parado", approved: "aprobado",
  merged: "integrado", rejected: "rechazado", discarded: "descartado", interrupted: "interrumpido",
};

function toolText(e: TaskEvent): string {
  const input = (e.data?.input ?? {}) as Record<string, unknown>;
  if (e.text === "Bash") return `$ ${String(input.command ?? "")}`;
  if (e.text.startsWith("mcp__local__")) return `🦙 ${e.text.replace("mcp__local__", "")}: ${String(input.path ?? input.task ?? "").slice(0, 160)}`;
  const target = input.file_path ?? input.path ?? input.pattern ?? input.url ?? input.query ?? "";
  return `› ${e.text} ${String(target)}`.trim();
}

interface Row { id: string; time: string; name: string; color: string; text: string; tone: string }

const timeline = computed<Row[]>(() => props.events.filter((e) => !SKIP.has(e.kind) && e.kind !== "tool").map((e, i) => {
  const w = who(e);
  let text = e.text, tone = "info";
  if (e.kind === "status") { text = STATUS[e.text] ?? e.text; tone = ["failed", "timeout"].includes(e.text) ? "bad" : ["review", "done", "merged"].includes(e.text) ? "ok" : "info"; }
  else if (e.kind === "error") tone = "bad";
  else if (e.kind === "warning") tone = "ask";
  else if (e.kind === "user") text = `«${e.text}»`;
  else if (e.kind === "result") { text = e.text.replace(/\s+/g, " ").slice(0, 220); tone = "ok"; }
  else if (e.kind === "context") text = `contexto inyectado: ${e.text}`;
  else if (e.kind === "delegate") text = `hizo el encargo ${e.text}`;
  else if (e.kind === "delegate_summary") { text = e.text; tone = "ok"; }
  else text = e.text.replace(/\s+/g, " ").slice(0, 220);
  return { id: `${e.id ?? "x"}-${i}`, time: when(e), name: w.name, color: w.color, text, tone };
}).filter((r) => r.text));

const terminal = computed(() => props.events.filter((e) => ["tool", "error", "result", "usage", "delegate"].includes(e.kind)).map((e, i) => {
  const aname = agentName(live.tasks[e.task_id]?.agent_id ?? null);
  if (e.kind === "tool") return { id: i, cls: e.text === "Bash" ? "cmd" : "", who: aname, text: toolText(e) };
  if (e.kind === "error") return { id: i, cls: "e", who: aname, text: e.text };
  if (e.kind === "delegate") return { id: i, cls: "g", who: "local", text: `✔ ${e.text}` };
  if (e.kind === "usage") {
    const c = e.data?.cost_usd as number | undefined, tps = e.data?.tps as number | undefined;
    return { id: i, cls: "h", who: aname, text: [c !== undefined && c !== null ? `coste ${c.toFixed(4)} $` : null, tps ? `${tps.toFixed(1)} tok/s` : null, e.data?.turns ? `${e.data.turns} turnos` : null].filter(Boolean).join(" · ") };
  }
  return { id: i, cls: "g", who: aname, text: "✔ respuesta entregada" };
}).filter((r) => r.text));

const diffLines = computed(() => (props.review?.diff ?? "").split("\n").slice(0, 3000).map((l) => ({
  cls: l.startsWith("diff --git") ? "file" : l.startsWith("@@") ? "hunk" : l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : "ctx",
  text: l,
})));

// ---------- Modelos: uno por servidor local
const LOCAL_COLORS = ["#0ea5e9", "#10b981", "#a855f7", "#f97316"]; // los mismos que sus puestos en la oficina
const clock = ref(Date.now());
const ticker = setInterval(() => { clock.value = Date.now(); }, 1000);
onUnmounted(() => clearInterval(ticker));
const WORK_TEXT: Record<string, string> = {
  local_ask: "pregunta", local_write_file: "escribe un archivo", local_agent: "tarea con herramientas",
  local_research: "investiga", "local_execute_plan/write": "bloque del plan: escribe", "local_execute_plan/ask": "bloque del plan: pregunta",
};
interface ModelCard {
  id: string; name: string; role: string; device: string; state: string; model: string | null; color: string;
  busy: boolean; what: string; taskLabel: string; tps: number | null; tokens: number | null; since: string;
  thinking: string; text: string; last: string;
}
const models = computed<ModelCard[]>(() => {
  const ids = live.locals.length ? live.locals.map((l) => l.id) : Object.keys(live.localWork);
  return ids.map((id, i) => {
    const l = live.locals.find((x) => x.id === id);
    const w = live.localWork[id];
    // trabajando = encargo sin terminar con noticias recientes (mientras lee un prompt largo pasan segundos sin nada)
    const busy = !!w && !w.done && clock.value - w.at < 600_000 && live.tasks[w.task_id]?.status === "running";
    const t = w ? live.tasks[w.task_id] : undefined;
    return {
      id, name: l?.name ?? id, role: l?.role ? SERVER_ROLE_LABEL[l.role] ?? l.role : "", device: l?.device ?? "",
      state: l?.state ?? "off", model: l?.model ?? w?.model ?? null, color: LOCAL_COLORS[i % LOCAL_COLORS.length],
      busy, what: w ? WORK_TEXT[w.tool ?? ""] ?? (w.tool ?? "").replace(/^local_/, "") : "",
      taskLabel: w ? `${w.task ?? ""}${t ? ` · tarea #${t.id} de ${agentName(t.agent_id)}` : ""}` : "",
      tps: w?.tps ?? null, tokens: w?.tokens ?? null, since: w ? duration(clock.value - (busy ? w.started : w.at)) : "",
      thinking: w?.thinking ?? "", text: w?.text ?? "",
      last: w && !busy ? `Último: ${WORK_TEXT[w.tool ?? ""] ?? w.tool ?? "encargo"}${w.task ? ` · ${w.task.slice(0, 80)}` : ""} (hace ${duration(clock.value - w.at)})` : "",
    };
  });
});
const busyModels = computed(() => models.value.filter((m) => m.busy).length);
const STATE_TEXT: Record<string, string> = { ready: "cargado", external: "cargado (lanzado fuera)", loading: "cargando…", failed: "falló", off: "apagado" };

// baja sola al final mientras llegan eventos (si ya estabas abajo)
watch(() => [props.events.length, tab.value], async () => {
  const el = body.value;
  const atEnd = !el || el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  await nextTick();
  if (el && atEnd && tab.value !== "diff" && tab.value !== "models") el.scrollTop = el.scrollHeight;
});

defineExpose({ show: (t: Tab) => { tab.value = t; min.value = false; } });
</script>

<template>
  <section class="dock" :class="{ 'dock--min': min }">
    <div class="dock-h">
      <button class="tab" :class="{ on: tab === 'time' }" @click="tab = 'time'; min = false">
        <i class="fa-solid fa-list-ul" /> Timeline <span class="n">{{ timeline.length }}</span>
      </button>
      <button class="tab" :class="{ on: tab === 'term' }" @click="tab = 'term'; min = false">
        <i class="fa-solid fa-terminal" /> Terminal
      </button>
      <button class="tab" :class="{ on: tab === 'diff' }" @click="tab = 'diff'; min = false">
        <i class="fa-solid fa-code-compare" /> Diff <span v-if="review?.stat" class="n">{{ review.stat.trim().split("\n").pop()?.trim() }}</span>
      </button>
      <button class="tab" :class="{ on: tab === 'models' }" @click="tab = 'models'; min = false">
        <i class="fa-solid fa-microchip" /> Modelos <span v-if="busyModels" class="n">{{ busyModels }} trabajando</span>
      </button>
      <span class="spacer" />
      <button class="mini" :title="min ? 'Desplegar panel' : 'Plegar panel'" @click="min = !min">
        <i class="fa-solid" :class="min ? 'fa-chevron-up' : 'fa-chevron-down'" />
      </button>
    </div>
    <div v-show="!min" ref="body" class="pane" :class="{ dark: tab === 'term' || tab === 'diff' }">
      <template v-if="tab === 'time'">
        <p v-if="!timeline.length" class="none">Aún no ha pasado nada en esta misión.</p>
        <div v-for="r in timeline" :key="r.id" class="ev" :class="r.tone">
          <time>{{ r.time }}</time><i :style="{ background: r.color }" />
          <div><b>{{ r.name }}</b> <span>{{ r.text }}</span></div>
        </div>
      </template>
      <template v-else-if="tab === 'term'">
        <p v-if="!terminal.length" class="h">Sin herramientas usadas todavía.</p>
        <div v-for="r in terminal" :key="r.id" class="tl" :class="r.cls">
          <span class="p">{{ r.who }}@harness</span> <span class="h">›</span> {{ r.text }}
        </div>
      </template>
      <template v-else-if="tab === 'models'">
        <p v-if="!models.length" class="none">No hay modelos locales configurados (Modelos locales).</p>
        <div class="mgrid">
          <article v-for="m in models" :key="m.id" class="mcard" :class="{ busy: m.busy }" :style="{ '--c': m.color }">
            <header>
              <span class="dot" />
              <b>{{ m.name }}</b>
              <span v-if="m.role" class="role">{{ m.role }}</span>
              <span class="muted">{{ m.model ?? "sin modelo" }}{{ m.device ? ` · ${m.device}` : "" }}</span>
              <span class="st" :class="m.state">{{ STATE_TEXT[m.state] ?? m.state }}</span>
            </header>
            <template v-if="m.busy">
              <div class="doing">
                <i class="fa-solid fa-gear fa-spin" /> <b>{{ m.what }}</b>
                <span class="nums">{{ m.tps ? tps(m.tps) : "leyendo el encargo…" }}{{ m.tokens ? ` · ${m.tokens} tokens` : "" }} · {{ m.since }}</span>
              </div>
              <div class="task">{{ m.taskLabel }}</div>
              <div v-if="m.thinking" class="box think"><small>💭 Pensando</small>{{ m.thinking.slice(-500) }}</div>
              <div v-if="m.text" class="box write"><small>✍️ Escribiendo</small>{{ m.text.slice(-500) }}</div>
            </template>
            <p v-else class="idle">
              <i class="fa-solid fa-mug-hot" /> {{ m.state === "ready" || m.state === "external" ? "Libre" : "Sin trabajo" }}<template v-if="m.last"> · {{ m.last }}</template>
            </p>
          </article>
        </div>
      </template>
      <template v-else>
        <p v-if="!review" class="h">Elige una misión con cambios de código.</p>
        <p v-else-if="!review.available" class="h">Ya no hay worktree para {{ reviewTitle }} (integrada o limpiada).</p>
        <p v-else-if="!review.diff.trim()" class="h">{{ reviewTitle }}: sin cambios de código.</p>
        <template v-else>
          <div class="dfile"><i class="fa-solid fa-file-code" /> {{ reviewTitle }}</div>
          <span v-for="(l, i) in diffLines" :key="i" class="dl" :class="l.cls">{{ l.text || " " }}</span>
        </template>
      </template>
    </div>
  </section>
</template>

<style scoped>
.mgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; }
.mcard { border: 1px solid var(--line); border-left: 4px solid var(--c); border-radius: 10px; padding: 8px 10px; min-width: 0; }
.mcard.busy { background: color-mix(in srgb, var(--c) 7%, transparent); }
.mcard header { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 12px; }
.mcard header .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--c); }
.mcard.busy header .dot { box-shadow: 0 0 0 3px color-mix(in srgb, var(--c) 30%, transparent); }
.mcard .role { font-size: 10px; font-weight: 800; text-transform: uppercase; color: var(--c); }
.mcard .muted { color: var(--ink-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; flex: 1; }
.mcard .st { font-size: 11px; font-weight: 700; color: var(--ink-dim); }
.mcard .st.ready, .mcard .st.external { color: var(--ok); }
.mcard .st.failed { color: var(--crit); }
.doing { margin-top: 6px; font-size: 12px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.doing i { color: var(--c); display: inline-block; width: 1em; text-align: center; }
.doing .nums { margin-left: auto; font-family: ui-monospace, monospace; font-size: 11px; color: var(--ink-dim); }
.task { font-size: 11px; color: var(--ink-dim); margin: 2px 0 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.box { font-family: ui-monospace, monospace; font-size: 11px; white-space: pre-wrap; word-break: break-word; max-height: 90px; overflow: hidden;
  display: flex; flex-direction: column; justify-content: flex-end; padding: 6px 8px; border-radius: 8px; margin-top: 4px;
  background: color-mix(in srgb, var(--ink) 5%, transparent); }
.box small { font-family: inherit; font-weight: 700; color: var(--ink-dim); }
.box.think { font-style: italic; }
.idle { margin: 6px 0 0; font-size: 12px; color: var(--ink-dim); }
.dock {
  height: var(--dockh, 230px);
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: color-mix(in srgb, var(--panel) 96%, transparent);
  border-top: 1px solid var(--line);
  transition: height 0.25s;
}
.dock--min {
  height: 40px;
}
.dock-h {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
}
.tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border: 0;
  border-radius: 10px;
  background: none;
  color: var(--ink-dim);
  font-weight: 700;
  font-size: 12.5px;
  cursor: pointer;
}
.tab:hover {
  background: var(--panel-hover);
}
.tab.on {
  background: var(--ink);
  color: var(--panel);
}
.n {
  font-size: 10px;
  background: rgba(148, 163, 184, 0.3);
  padding: 0 6px;
  border-radius: 99px;
}
.spacer {
  flex: 1;
}
.mini {
  width: 28px;
  height: 28px;
  border-radius: 9px;
  border: 1px solid var(--line);
  background: var(--panel-raised);
  color: var(--ink-dim);
  cursor: pointer;
}
.pane {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 8px 12px;
  font-size: 12px;
}
.pane.dark {
  background: var(--term-bg);
  color: var(--term-ink);
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.55;
}
.none {
  margin: 8px 0;
  color: var(--ink-faint);
}
.ev {
  display: grid;
  grid-template-columns: 62px 8px 1fr;
  gap: 8px;
  align-items: baseline;
  padding: 3px 0;
}
.ev time {
  font-family: var(--font-mono);
  color: var(--ink-faint);
  font-size: 10.5px;
}
.ev i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  align-self: center;
}
.ev b {
  font-weight: 800;
}
.ev span {
  color: var(--ink-dim);
}
.ev.ok span {
  color: var(--ok);
}
.ev.bad span {
  color: var(--crit);
  font-weight: 700;
}
.ev.ask span {
  color: var(--warn);
  font-weight: 700;
}
.tl {
  white-space: pre-wrap;
  word-break: break-word;
}
.p {
  color: #34d399;
}
.h {
  color: #64748b;
}
.e {
  color: #f87171;
}
.g {
  color: #4ade80;
}
.cmd {
  color: #e2e8f0;
}
.dfile {
  color: #93c5fd;
  font-weight: 600;
  margin-bottom: 6px;
}
.dl {
  display: block;
  white-space: pre;
  padding: 0 6px;
  border-radius: 3px;
}
.dl.add {
  background: rgba(74, 222, 128, 0.14);
  color: #86efac;
}
.dl.del {
  background: rgba(248, 113, 113, 0.14);
  color: #fca5a5;
}
.dl.ctx {
  color: #94a3b8;
}
.dl.file {
  color: #93c5fd;
  font-weight: 600;
  margin-top: 8px;
}
.dl.hunk {
  color: #c4b5fd;
}
</style>
