<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import Card from "../components/Card.vue";
import StatusChip from "../components/StatusChip.vue";
import {
  PLAN_TEXT, STATUS_TEXT, agentName, api, live, onTaskEvent, planChip, post, projectName, statusChip, usd,
  type Plan, type PlanStep, type PlanTask, type Review,
} from "../api";

const props = defineProps<{ id: number }>();
const detail = ref<Plan | null>(null);
const error = ref("");
const acting = ref(false);
const open = ref<number | null>(null); // subtarea con el diff desplegado
const diffs = ref<Record<number, Review>>({});

const plan = computed(() => (live.plans[props.id] ? { ...detail.value, ...live.plans[props.id] } : detail.value));
const tasks = computed<PlanTask[]>(() =>
  (detail.value?.tasks ?? []).map((t) => ({ ...t, ...(live.tasks[t.id] ?? {}) }) as PlanTask),
);

async function load() {
  try {
    detail.value = await api<Plan>(`/api/plans/${props.id}`);
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  }
}

watch(() => props.id, load, { immediate: true });
// cualquier cambio del plan o de sus tareas recarga el detalle (motivos, veredictos, nuevas subtareas)
watch(() => live.plans[props.id]?.status, () => load());
const off = onTaskEvent((ev) => {
  if (ev.kind === "status" && tasks.value.some((t) => t.id === ev.task_id)) load();
});
onUnmounted(off);

async function toggleDiff(t: PlanTask) {
  if (open.value === t.id) {
    open.value = null;
    return;
  }
  open.value = t.id;
  if (!diffs.value[t.id]) diffs.value[t.id] = await api<Review>(`/api/tasks/${t.id}/review`);
}

async function act(path: string, body: unknown = {}, question?: string) {
  if (question && !window.confirm(question)) return;
  acting.value = true;
  error.value = "";
  try {
    await post(path, body);
    await load();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    acting.value = false;
  }
}

// --- revisar el plan antes de empezar (objetivo 3): editar pasos a mano o pedir al Director que rehaga uno
const draft = ref<PlanStep[]>([]);
const editingStep = ref<number | null>(null);
const redoFor = ref<number | null>(null);
const redoComment = ref("");
const dirty = ref(false);
const reviewing = computed(() => plan.value?.status === "awaiting_you");
const replanning = computed(() => plan.value?.status === "planning" && (detail.value?.tasks ?? []).some((t) => t.kind === "worker"));
// trabajadores posibles: los que pueden escribir (no `local` ni el Director)
const workers = computed(() => live.agents.filter((a) => a.provider !== "local" && a.id !== plan.value?.director_agent_id));
const RISK_TEXT: Record<string, string> = { low: "bajo", medium: "medio", high: "alto" };

watch(() => detail.value?.plan, (p) => {
  if (!dirty.value) draft.value = (p?.subtasks ?? []).map((s) => ({ ...s, skills: [...(s.skills ?? [])] }));
}, { immediate: true });

function changed() {
  dirty.value = true;
}
function removeStep(i: number) {
  draft.value.splice(i, 1);
  editingStep.value = null;
  changed();
}
function moveStep(i: number, d: number) {
  const j = i + d;
  if (j < 0 || j >= draft.value.length) return;
  [draft.value[i], draft.value[j]] = [draft.value[j], draft.value[i]];
  changed();
}
function discard() {
  dirty.value = false;
  editingStep.value = null;
  draft.value = (detail.value?.plan?.subtasks ?? []).map((s) => ({ ...s, skills: [...(s.skills ?? [])] }));
}
async function saveDraft() {
  acting.value = true;
  error.value = "";
  try {
    await api(`/api/plans/${props.id}`, { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subtasks: draft.value }) });
    dirty.value = false;
    editingStep.value = null;
    await load();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    acting.value = false;
  }
}
async function redo(i: number) {
  if (!redoComment.value.trim()) return;
  await act(`/api/plans/${props.id}/redo`, { seq: i + 1, comment: redoComment.value.trim() });
  redoFor.value = null;
  redoComment.value = "";
}

const KIND: Record<string, string> = { director: "Director", worker: "Trabajador", reviewer: "Jefe técnico" };

function diffClass(l: string): string {
  if (l.startsWith("@@")) return "d-hunk";
  if (l.startsWith("+++") || l.startsWith("---") || l.startsWith("diff ") || l.startsWith("index ")) return "d-meta";
  if (l.startsWith("+")) return "d-add";
  if (l.startsWith("-")) return "d-del";
  return "";
}
</script>

<template>
  <div v-if="plan" class="page">
    <div class="row head">
      <RouterLink to="/planes" class="muted">← Planes</RouterLink>
      <h2 class="title">Plan #{{ id }}</h2>
      <StatusChip label="estado" :state="planChip(plan.status)" :text="PLAN_TEXT[plan.status] ?? plan.status" />
      <span class="mono muted">{{ plan.level ?? "" }} · {{ usd(plan.cost_usd) }}</span>
    </div>
    <p v-if="error" class="error">{{ error }}</p>

    <Card title="Petición" :level="['awaiting_you', 'paused', 'ready'].includes(plan.status) ? 'warn' : undefined">
      <p class="req">{{ plan.request }}</p>
      <p class="muted small">
        {{ projectName(plan.project_id) }} · Director {{ agentName(plan.director_agent_id) }} ·
        jefe técnico {{ plan.reviewer_agent_id ? agentName(plan.reviewer_agent_id) : "ninguno" }} ·
        rama <span class="mono">{{ plan.branch ?? "—" }}</span>
      </p>
      <ul v-if="plan.level_reasons?.length" class="reasons">
        <li v-for="(r, i) in plan.level_reasons" :key="i">{{ r }}</li>
      </ul>
      <p v-if="plan.error" class="warn-text">{{ plan.error }}</p>
      <div class="row actions">
        <button
          v-if="plan.status === 'ready'" class="btn btn--primary" :disabled="acting"
          @click="act(`/api/plans/${id}/merge`, { confirm: true }, `¿Integrar ${plan.branch} en tu rama actual?\n\nMerge local; nunca se hace push.`)"
        >Integrar plan</button>
        <button v-if="['planning', 'running'].includes(plan.status)" class="btn btn--danger" :disabled="acting" @click="act(`/api/plans/${id}/cancel`, {}, '¿Cancelar el plan?')">Cancelar</button>
        <button
          v-if="['awaiting_you', 'paused', 'ready', 'failed', 'cancelled', 'interrupted'].includes(plan.status)"
          class="btn btn--danger" :disabled="acting"
          @click="act(`/api/plans/${id}/reject`, {}, '¿Rechazar el plan? Se borran su rama y su worktree.')"
        >Rechazar plan</button>
      </div>
    </Card>

    <Card v-if="reviewing || replanning" title="Revisa el plan antes de empezar" level="warn">
      <p class="muted small">
        Apruébalo entero, cambia un paso a mano o pide al Director que rehaga uno con tu comentario.
        <template v-if="plan.plan?.summary"><br />Resumen del Director: {{ plan.plan.summary }}</template>
      </p>
      <p v-if="replanning" class="warn-text">El Director está rehaciendo un paso…</p>
      <ol class="steps">
        <li v-for="(s, i) in draft" :key="i" class="step">
          <div class="row">
            <strong class="grow">{{ s.title }}</strong>
            <span class="small muted">{{ s.agent }}</span>
            <span v-if="s.thinking && s.thinking !== 'normal'" class="risk">💭 {{ s.thinking }}</span>
            <span class="risk" :class="`risk--${s.risk}`">riesgo {{ RISK_TEXT[s.risk] ?? s.risk }}</span>
          </div>
          <p v-if="editingStep !== i" class="small prompt">{{ s.prompt }}</p>
          <div v-else class="edit">
            <label class="field">Título <input v-model="s.title" @input="changed" /></label>
            <label class="field">Instrucciones para el agente (incluye cómo se comprueba)
              <textarea v-model="s.prompt" rows="5" @input="changed" /></label>
            <div class="row">
              <label class="field">Agente
                <select v-model="s.agent" @change="changed">
                  <option v-for="a in workers" :key="a.id" :value="a.name">{{ a.name }} ({{ a.provider }})</option>
                </select></label>
              <label class="field">Pensamiento
                <select v-model="s.thinking" @change="changed">
                  <option :value="undefined">el del agente</option><option value="apagado">apagado</option>
                  <option value="normal">normal</option><option value="profundo">profundo</option>
                </select></label>
              <label class="field">Riesgo
                <select v-model="s.risk" @change="changed">
                  <option value="low">bajo</option><option value="medium">medio</option><option value="high">alto</option>
                </select></label>
            </div>
          </div>
          <p v-if="s.skills?.length" class="small skills">Skills: <span v-for="n in s.skills" :key="n" class="skilltag">{{ n }}</span></p>
          <div v-if="reviewing" class="row actions">
            <button class="btn" @click="editingStep = editingStep === i ? null : i">{{ editingStep === i ? "Listo" : "Editar" }}</button>
            <button class="btn" :disabled="dirty" :title="dirty ? 'Guarda o descarta tus cambios antes' : ''"
                    @click="redoFor = redoFor === i ? null : i">Pedir al Director que lo rehaga</button>
            <button class="btn" :disabled="i === 0" @click="moveStep(i, -1)">↑</button>
            <button class="btn" :disabled="i === draft.length - 1" @click="moveStep(i, 1)">↓</button>
            <button class="btn btn--danger" :disabled="draft.length === 1" @click="removeStep(i)">Quitar</button>
          </div>
          <div v-if="redoFor === i" class="row redo">
            <input v-model="redoComment" class="grow" placeholder="Qué quieres que cambie (p. ej. «hazlo con tests», «usa el agente local»)"
                   @keyup.enter="redo(i)" />
            <button class="btn btn--primary" :disabled="acting || !redoComment.trim()" @click="redo(i)">Rehacer paso {{ i + 1 }}</button>
          </div>
        </li>
      </ol>
      <div v-if="reviewing" class="row actions">
        <template v-if="dirty">
          <button class="btn btn--primary" :disabled="acting" @click="saveDraft">Guardar cambios</button>
          <button class="btn" :disabled="acting" @click="discard">Descartar</button>
        </template>
        <button v-else class="btn btn--ok" :disabled="acting" @click="act(`/api/plans/${id}/approve`)">Aprobar todo y ejecutar</button>
      </div>
    </Card>

    <Card title="Subtareas">
      <p v-if="!tasks.length" class="muted">El Director está preparando el plan…</p>
      <div v-for="t in tasks" :key="t.id" class="sub" :class="`sub--${t.kind}`">
        <div class="row">
          <span class="mono seq">{{ t.seq }}</span>
          <span class="kind">{{ KIND[t.kind ?? "worker"] }}</span>
          <StatusChip label="" :state="statusChip(t.status)" :text="STATUS_TEXT[t.status] ?? t.status" />
          <span v-if="t.level" class="mono">{{ t.level }}</span>
          <RouterLink :to="`/tareas/${t.id}`" class="grow">{{ t.title }}</RouterLink>
          <span class="muted small">{{ agentName(t.agent_id) }}<template v-if="t.approved_by"> · aprobó {{ t.approved_by }}</template></span>
          <span class="mono small">{{ usd(t.cost_usd) }}</span>
        </div>
        <p v-if="t.skills?.length" class="small skills">Skills elegidas por el Director:
          <span v-for="n in t.skills" :key="n" class="skilltag">{{ n }}</span>
        </p>
        <ul v-if="t.kind === 'worker' && t.level_reasons?.length" class="reasons">
          <li v-for="(r, i) in t.level_reasons" :key="i">{{ r }}</li>
        </ul>
        <div v-if="t.kind === 'worker'" class="row actions">
          <button v-if="t.head_commit && ['review', 'approved'].includes(t.status)" class="btn" @click="toggleDiff(t)">{{ open === t.id ? "Ocultar diff" : "Ver diff" }}</button>
          <template v-if="t.status === 'review' && plan.status === 'paused'">
            <button class="btn btn--ok" :disabled="acting" @click="act(`/api/tasks/${t.id}/decide`, { approve: true })">Aprobar y seguir</button>
            <button class="btn btn--danger" :disabled="acting" @click="act(`/api/tasks/${t.id}/decide`, { approve: false }, '¿Rechazar? Se deshace el commit de esta subtarea y el plan sigue.')">Rechazar y seguir</button>
          </template>
        </div>
        <pre v-if="open === t.id && diffs[t.id]" class="block diff"><span v-for="(l, i) in diffs[t.id].diff.split('\n')" :key="i" :class="diffClass(l)">{{ l }}
</span></pre>
      </div>
    </Card>
  </div>
  <p v-else-if="error" class="error">{{ error }}</p>
</template>

<style scoped>
.head {
  gap: 14px;
}
.head a {
  text-decoration: none;
  font-size: 13px;
}
.req {
  margin: 0 0 6px;
  white-space: pre-wrap;
}
.small {
  font-size: 12px;
}
.skills {
  margin: 4px 0 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  color: var(--ink-dim);
}
.skilltag {
  padding: 1px 8px;
  border-radius: 6px;
  background: var(--accent-weak);
  color: var(--accent);
  font-weight: 600;
}
.reasons {
  margin: 6px 0 0 18px;
  padding: 0;
  font-size: 12px;
  color: var(--ink-dim);
}
.warn-text {
  color: var(--warn);
}
.actions {
  margin-top: 10px;
}
.sub {
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
.sub--reviewer,
.sub--director {
  opacity: 0.75;
}
.seq {
  width: 18px;
  color: var(--ink-faint);
}
.kind {
  width: 96px;
  font-size: 12px;
  color: var(--ink-dim);
}
.grow {
  flex: 1;
  min-width: 160px;
}
.diff {
  margin-top: 8px;
  max-height: 480px;
  white-space: pre;
}
.steps {
  margin: 8px 0 0;
  padding-left: 22px;
}
.step {
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
.prompt {
  margin: 4px 0 0;
  white-space: pre-wrap;
  color: var(--ink-dim);
}
.edit {
  display: grid;
  gap: 8px;
  margin-top: 8px;
}
.field {
  display: grid;
  gap: 4px;
  font-size: 12px;
  color: var(--ink-dim);
}
.edit input,
.edit textarea,
.edit select,
.redo input {
  font: inherit;
  padding: 6px 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
  color: var(--ink);
}
.redo {
  margin-top: 8px;
}
.risk {
  font-size: 12px;
  padding: 1px 8px;
  border-radius: 6px;
  background: var(--accent-weak);
}
.risk--medium {
  color: var(--warn);
}
.risk--high {
  color: var(--crit);
}
.d-hunk {
  color: var(--accent);
}
.d-meta {
  color: var(--ink-faint);
}
.d-add {
  color: var(--ok);
}
.d-del {
  color: var(--crit);
}
</style>
