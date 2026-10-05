<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import BlueprintCard from "../components/BlueprintCard.vue";
import StatusChip from "../components/StatusChip.vue";
import {
  STATUS_TEXT, agentName, api, live, onTaskEvent, post, projectName, statusChip, usd,
  type Review, type Task, type TaskEvent,
} from "../api";

const props = defineProps<{ id: number }>();

const events = ref<TaskEvent[]>([]);
const review = ref<Review | null>(null);
const error = ref("");
const acting = ref(false);
const logEl = ref<HTMLElement | null>(null);

const task = computed<Task | undefined>(() => live.tasks[props.id]);
const decided = computed(() => task.value && ["review", "approved"].includes(task.value.status));

async function load() {
  error.value = "";
  events.value = [];
  review.value = null;
  try {
    const [t, evs] = await Promise.all([
      api<Task>(`/api/tasks/${props.id}`),
      api<TaskEvent[]>(`/api/tasks/${props.id}/events`),
    ]);
    live.tasks[t.id] = t;
    const seen = new Set(evs.map((e) => e.id));
    events.value = [...evs, ...events.value.filter((e) => e.id == null || !seen.has(e.id))].sort(
      (a, b) => (a.id ?? 0) - (b.id ?? 0),
    );
    await loadReview();
  } catch (e) {
    error.value = (e as Error).message;
  }
}

async function loadReview() {
  const t = live.tasks[props.id];
  if (t && t.worktree && t.status !== "running") review.value = await api<Review>(`/api/tasks/${props.id}/review`);
}

const off = onTaskEvent((ev) => {
  if (ev.task_id !== props.id) return;
  // lo que llegó por SSE mientras se cargaba el historial ya puede estar en la lista
  if (ev.id != null && events.value.some((e) => e.id === ev.id)) return;
  events.value.push(ev);
  nextTick(() => logEl.value?.scrollTo({ top: logEl.value.scrollHeight }));
});
onUnmounted(off);

watch(() => props.id, load, { immediate: true });
// al terminar la ejecución aparece el diff
watch(() => task.value?.status, (s, prev) => {
  if (prev === "running" && s !== "running") loadReview().catch(() => {});
});

async function act(path: string, body: unknown = {}, question?: string) {
  if (question && !window.confirm(question)) return;
  acting.value = true;
  error.value = "";
  try {
    const t = await post<Task>(`/api/tasks/${props.id}/${path}`, body);
    live.tasks[t.id] = { ...live.tasks[t.id], ...t };
    if (path === "merge" || path === "reject") review.value = null;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    acting.value = false;
  }
}

const mergeQuestion = computed(
  () =>
    `¿Integrar ${task.value?.branch} en «${review.value?.target ?? "la rama actual"}»?\n\n` +
    "Se hace un merge local. LocalHarness nunca hace push: eso lo haces tú.",
);

// --- registro: una línea legible por evento
function line(ev: TaskEvent): { cls: string; tag: string; text: string } | null {
  const d = ev.data ?? {};
  switch (ev.kind) {
    case "status":
      return { cls: "st", tag: "estado", text: STATUS_TEXT[ev.text as keyof typeof STATUS_TEXT] ?? ev.text };
    case "session":
      return { cls: "dim", tag: "sesión", text: `${d.model ?? ""} · herramientas ${(d.tools as string[] | undefined)?.join(", ") ?? "?"}` };
    case "text":
      return { cls: "txt", tag: "agente", text: ev.text };
    case "tool": {
      const input = d.input as Record<string, unknown> | undefined;
      const target = input?.file_path ?? input?.pattern ?? input?.command ?? "";
      return { cls: "tool", tag: ev.text || "tool", text: String(target) };
    }
    case "usage":
      return { cls: "dim", tag: "uso", text: `${usd(d.cost_usd as number)} · ${d.turns ?? "?"} turnos` };
    case "error":
      return { cls: "err", tag: "error", text: ev.text };
    case "warning":
      return { cls: "warn", tag: "aviso", text: ev.text };
    case "result":
    case "limit":
      return null;
    default:
      return { cls: "dim", tag: ev.kind, text: ev.text };
  }
}
const lines = computed(() => events.value.map(line).filter((l): l is NonNullable<typeof l> => l !== null));

// --- diff: color por tipo de línea
function diffClass(l: string): string {
  if (l.startsWith("diff --git")) return "d-file";
  if (l.startsWith("+++") || l.startsWith("---") || l.startsWith("index ") || l.startsWith("new file")) return "d-meta";
  if (l.startsWith("@@")) return "d-hunk";
  if (l.startsWith("+")) return "d-add";
  if (l.startsWith("-")) return "d-del";
  return "";
}
const diffLines = computed(() => (review.value?.diff ?? "").split("\n"));
</script>

<template>
  <div class="page">
    <div class="row head">
      <RouterLink to="/tareas" class="muted">← Tareas</RouterLink>
      <h2 class="title">#{{ id }} {{ task?.title ?? "" }}</h2>
      <StatusChip v-if="task" label="estado" :state="statusChip(task.status)" :text="STATUS_TEXT[task.status] ?? task.status" />
    </div>
    <p v-if="error" class="error">{{ error }}</p>

    <BlueprintCard v-if="task" title="Decisión" :level="decided ? 'warn' : undefined">
      <dl class="meta mono">
        <div><dt class="label">Proyecto</dt><dd>{{ projectName(task.project_id) }}</dd></div>
        <div><dt class="label">Agente</dt><dd>{{ agentName(task.agent_id) }}</dd></div>
        <div><dt class="label">Rama</dt><dd>{{ task.branch ?? "—" }}</dd></div>
        <div><dt class="label">Coste equiv.</dt><dd>{{ usd(task.cost_usd) }}</dd></div>
      </dl>
      <div class="row actions">
        <button v-if="task.status === 'pending'" class="btn btn--primary" :disabled="acting" @click="act('start')">Arrancar</button>
        <button v-if="task.status === 'running'" class="btn btn--danger" :disabled="acting" @click="act('cancel', {}, '¿Cancelar la ejecución? Lo hecho se guarda en su rama.')">Cancelar</button>
        <button v-if="task.status === 'review'" class="btn btn--ok" :disabled="acting" @click="act('approve')">Aprobar</button>
        <button v-if="task.status === 'approved'" class="btn btn--primary" :disabled="acting" @click="act('merge', { confirm: true }, mergeQuestion)">
          Integrar en {{ review?.target ?? "rama actual" }}
        </button>
        <button
          v-if="['review', 'approved', 'failed', 'timeout', 'cancelled', 'interrupted'].includes(task.status)"
          class="btn btn--danger" :disabled="acting"
          @click="act('reject', {}, '¿Rechazar? Se borran el worktree y la rama de esta tarea.')"
        >Rechazar</button>
        <span v-if="task.status === 'review'" class="muted">Revisa el diff y aprueba; integrar es un segundo paso.</span>
        <span v-if="task.status === 'merged'" class="muted">Integrada. El push lo haces tú cuando quieras.</span>
      </div>
    </BlueprintCard>

    <div class="cols">
      <BlueprintCard title="Petición">
        <pre class="block">{{ task?.prompt }}</pre>
        <template v-if="task?.final">
          <h4 class="label sub">Respuesta final</h4>
          <pre class="block">{{ task.final }}</pre>
        </template>
      </BlueprintCard>

      <BlueprintCard title="Ejecución">
        <div ref="logEl" class="log mono">
          <div v-for="(l, i) in lines" :key="i" class="ln" :class="l.cls">
            <span class="tag">{{ l.tag }}</span><span class="tx">{{ l.text }}</span>
          </div>
          <div v-if="!lines.length" class="muted">Sin eventos todavía.</div>
        </div>
      </BlueprintCard>
    </div>

    <BlueprintCard title="Cambios">
      <template v-if="review?.available">
        <pre class="block">{{ review.stat || "(sin cambios)" }}</pre>
        <pre v-if="review.diff" class="block diff"><span v-for="(l, i) in diffLines" :key="i" :class="diffClass(l)">{{ l }}
</span></pre>
      </template>
      <p v-else-if="task?.status === 'running'" class="muted">El diff aparece cuando el agente termina.</p>
      <p v-else class="muted">No hay worktree para esta tarea (integrada, rechazada o sin empezar).</p>
    </BlueprintCard>
  </div>
</template>

<style scoped>
.head {
  gap: 14px;
}
.head a {
  text-decoration: none;
  font-size: 13px;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 28px;
  margin: 0 0 12px;
}
.meta dd {
  margin: 2px 0 0;
}
.actions {
  gap: 10px;
}
.cols {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
  gap: var(--gap);
}
@media (max-width: 900px) {
  .cols {
    grid-template-columns: 1fr;
  }
}
.sub {
  margin: 12px 0 6px;
}
.log {
  max-height: 420px;
  overflow: auto;
  font-size: 12px;
  display: grid;
  gap: 3px;
}
.ln {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 8px;
}
.tag {
  color: var(--ink-faint);
  text-align: right;
}
.tx {
  white-space: pre-wrap;
  word-break: break-word;
}
.ln.txt .tx {
  color: var(--ink);
  font-family: var(--font-sans);
  font-size: 13px;
}
.ln.tool .tag {
  color: var(--accent);
}
.ln.err .tx,
.ln.err .tag {
  color: var(--crit);
}
.ln.warn .tx {
  color: var(--warn);
}
.ln.st .tx {
  color: var(--ok);
}
.ln.dim .tx {
  color: var(--ink-dim);
}
.diff {
  margin-top: 10px;
  max-height: 640px;
  white-space: pre;
}
.d-file {
  color: var(--ink);
  font-weight: 600;
}
.d-meta {
  color: var(--ink-faint);
}
.d-hunk {
  color: var(--accent);
}
.d-add {
  color: var(--ok);
  background: rgba(110, 231, 183, 0.07);
}
.d-del {
  color: var(--crit);
  background: rgba(255, 107, 107, 0.07);
}
</style>
