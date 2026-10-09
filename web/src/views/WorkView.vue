<script setup lang="ts">
// Trabajo: lo que está en marcha AHORA (en vivo, con lo que hace el modelo local), lo que espera tu decisión y lo
// reciente; a la derecha, la revisión de lo elegido: encargo, respuesta, riesgo, archivos cambiados con su diff y
// los botones (aprobar e integrar, solo aprobar, descartar, pedir cambios). Nada de push: integrar es merge local.
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import Markdown from "../components/Markdown.vue";
import StatusChip from "../components/StatusChip.vue";
import {
  PLAN_TEXT, STATUS_TEXT, agentColor, agentName, api, describeActivity, duration, live, onTaskEvent, parseTs, post,
  projectName, refreshAll, statusChip, usd, type InboxItem, type Review, type Task,
} from "../api";

const route = useRoute();
const router = useRouter();
const now = ref(Date.now());
let clock: ReturnType<typeof setInterval>;

// ---------- listas (en vivo: salen de `live`, que se actualiza por SSE)
const tasks = computed(() => Object.values(live.tasks));
const running = computed(() => tasks.value.filter((t) => t.status === "running" || t.status === "pending").sort((a, b) => b.id - a.id));
const inboxTask = (id: number) => live.inbox.find((i) => i.task_id === id);
const OPEN = ["review", "approved", "done"];
const recent = computed(() => tasks.value.filter((t) => t.plan_id === null && (OPEN.includes(t.status) || ["merged", "rejected", "failed", "timeout", "cancelled"].includes(t.status)))
  .filter((t) => !live.inbox.some((i) => i.task_id === t.id))
  .sort((a, b) => parseTs(b.finished_at ?? b.created_at) - parseTs(a.finished_at ?? a.created_at)).slice(0, 15));

// lo que el modelo local está pensando/escribiendo ahora en cada tarea (worker_live)
const localNow = ref<Record<number, { task?: string; thinking: string; text: string; done: boolean; at: number }>>({});
const localOf = (tid: number) => {
  const l = localNow.value[tid];
  return l && !l.done && now.value / 1000 - l.at < 8 ? l : null;
};
let off: (() => void) | null = null;

// ---------- selección: ?t=<tarea> o ?p=<plan>
const sel = computed(() => (route.query.t ? { kind: "task" as const, id: Number(route.query.t) } : route.query.p ? { kind: "plan" as const, id: Number(route.query.p) } : null));
function choose(kind: "task" | "plan", id: number) {
  router.replace({ query: kind === "task" ? { t: String(id) } : { p: String(id) } });
}
const selTask = computed<Task | undefined>(() => (sel.value?.kind === "task" ? live.tasks[sel.value.id] : undefined));
const selPlan = computed(() => (sel.value?.kind === "plan" ? live.plans[sel.value.id] : undefined));
const selInbox = computed<InboxItem | undefined>(() => (selTask.value ? inboxTask(selTask.value.id) : selPlan.value ? live.inbox.find((i) => i.plan_id === selPlan.value!.id && !i.task_id) : undefined));
// por defecto: lo primero que espera tu decisión, o lo que está en marcha
watch(() => [live.inbox.length, running.value.length, recent.value.length], () => {
  if (sel.value) return;
  const i = live.inbox[0];
  if (i?.task_id) choose("task", i.task_id);
  else if (i?.plan_id) choose("plan", i.plan_id);
  else if (running.value[0]) choose("task", running.value[0].id);
  else if (recent.value[0]) choose("task", recent.value[0].id);
}, { immediate: true });

// ---------- revisión: diff partido por archivos
const review = ref<Review | null>(null);
const loadingDiff = ref(false);
watch(() => [selTask.value?.id, selTask.value?.status, selTask.value?.head_commit], async () => {
  const t = selTask.value;
  if (!t || t.status === "running" || t.status === "pending") { review.value = null; return; }
  loadingDiff.value = true;
  review.value = await api<Review>(`/api/tasks/${t.id}/review`).catch(() => null);
  loadingDiff.value = false;
}, { immediate: true });
interface FileDiff { path: string; add: number; del: number; lines: string[]; status: string }
const files = computed<FileDiff[]>(() => {
  const out: FileDiff[] = [];
  let cur: FileDiff | null = null;
  for (const line of (review.value?.diff ?? "").split("\n")) {
    if (line.startsWith("diff --git ")) {
      const m = line.match(/ b\/(.+)$/);
      cur = { path: m ? m[1] : line.slice(11), add: 0, del: 0, lines: [], status: "modificado" };
      out.push(cur);
      continue;
    }
    if (!cur) continue;
    if (line.startsWith("new file")) cur.status = "nuevo";
    else if (line.startsWith("deleted file")) cur.status = "borrado";
    else if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("index ")) continue;
    else {
      if (line.startsWith("+")) cur.add++;
      else if (line.startsWith("-")) cur.del++;
      cur.lines.push(line);
    }
  }
  return out;
});
const fileSel = ref(0);
watch(() => selTask.value?.id, () => (fileSel.value = 0));
const curFile = computed(() => files.value[fileSel.value] ?? files.value[0]);
const lineCls = (l: string) => (l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : l.startsWith("@@") ? "hunk" : "");
const totals = computed(() => files.value.reduce((a, f) => ({ add: a.add + f.add, del: a.del + f.del }), { add: 0, del: 0 }));

// ---------- acciones
const busy = ref(false);
const error = ref("");
const ask = ref("");
const promptOpen = ref(false);
async function act(fn: () => Promise<unknown>, confirmText?: string) {
  if (confirmText && !window.confirm(confirmText)) return;
  busy.value = true;
  error.value = "";
  try {
    await fn();
    await refreshAll();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
const NOPUSH = "Merge local en tu rama actual; nunca se hace push.";
const approveMerge = (t: Task) => act(async () => {
  if (t.status === "review") await post(`/api/tasks/${t.id}/approve`);
  await post(`/api/tasks/${t.id}/merge`, { confirm: true });
}, `¿Integrar «${t.title}»?\n\n${NOPUSH}`);
const approveOnly = (t: Task) => act(() => post(`/api/tasks/${t.id}/approve`));
const discard = (t: Task) => act(() => post(`/api/tasks/${t.id}/reject`), `¿Descartar «${t.title}»? Se borran su rama y su worktree.`);
const stop = (t: Task) => act(() => post(`/api/tasks/${t.id}/cancel`), "¿Parar esta tarea? Lo hecho queda en su rama.");
async function askChanges(t: Task) {
  const msg = ask.value.trim();
  if (!msg) return;
  await act(() => post(`/api/tasks/${t.id}/reply`, { message: msg }));
  if (!error.value) ask.value = "";
}
const planAct = (path: string, body: unknown = {}, confirmText?: string) => act(() => post(path, body), confirmText);

const LEVEL_TEXT: Record<string, string> = { N0: "bajo", N1: "medio", N2: "alto" };
const since = (t: Task) => duration(now.value - parseTs(t.created_at));

onMounted(() => {
  clock = setInterval(() => (now.value = Date.now()), 1000);
  off = onTaskEvent((ev) => {
    if (ev.kind === "worker_live") localNow.value = { ...localNow.value, [ev.task_id]: ev.data as never };
  });
});
onUnmounted(() => { clearInterval(clock); off?.(); });
</script>

<template>
  <div class="work">
    <!-- izquierda: en vivo -->
    <aside class="lists">
      <section class="card pad">
        <h3 class="card-title">En curso <em>{{ running.length }}</em></h3>
        <p v-if="!running.length" class="muted small">Nadie está trabajando ahora mismo.</p>
        <button v-for="t in running" :key="t.id" class="item" :class="{ on: sel?.kind === 'task' && sel.id === t.id }" @click="choose('task', t.id)">
          <span class="bar" :style="{ background: agentColor(live.agents.find((a) => a.id === t.agent_id)) }" />
          <span class="item__b">
            <b>{{ t.title }}</b>
            <small>{{ agentName(t.agent_id) }} · {{ projectName(t.project_id) }} · {{ since(t) }}</small>
            <small class="act"><i class="fa-solid fa-gear fa-spin" /> {{ t.status === "pending" ? "en cola" : describeActivity(live.activity[t.id]) }}</small>
            <small v-if="localOf(t.id)" class="loc">🦙 {{ localOf(t.id)!.text ? `✍️ ${localOf(t.id)!.text.slice(-90)}` : `💭 ${localOf(t.id)!.thinking.slice(-90)}` }}</small>
          </span>
        </button>
      </section>

      <section class="card pad">
        <h3 class="card-title">Espera tu decisión <em>{{ live.inbox.length }}</em></h3>
        <p v-if="!live.inbox.length" class="muted small">Nada pendiente.</p>
        <button
          v-for="(i, n) in live.inbox" :key="n" class="item"
          :class="{ on: (i.task_id && sel?.kind === 'task' && sel.id === i.task_id) || (!i.task_id && sel?.kind === 'plan' && sel.id === i.plan_id) }"
          @click="i.task_id ? choose('task', i.task_id) : choose('plan', i.plan_id!)"
        >
          <span class="lvl" :class="`lvl--${i.level}`">{{ i.level }}</span>
          <span class="item__b">
            <b>{{ i.title }}</b>
            <small>{{ { plan_approval: "Aprobar plan", plan_merge: "Integrar plan", task_decision: "Decidir subtarea", task_review: "Revisar cambios" }[i.type] }}{{ i.reasons.length ? ` · ${i.reasons.slice(0, 2).join(" · ")}` : "" }}</small>
          </span>
        </button>
      </section>

      <section class="card pad grow">
        <h3 class="card-title">Reciente</h3>
        <button v-for="t in recent" :key="t.id" class="item" :class="{ on: sel?.kind === 'task' && sel.id === t.id }" @click="choose('task', t.id)">
          <span class="item__b">
            <b>{{ t.title }}</b>
            <small>{{ agentName(t.agent_id) }} · <StatusChip :state="statusChip(t.status)" :text="STATUS_TEXT[t.status] ?? t.status" /></small>
          </span>
        </button>
      </section>
    </aside>

    <!-- derecha: revisión -->
    <main class="card pad detail">
      <template v-if="selTask">
        <div class="d-h">
          <div>
            <h2>{{ selTask.title }}</h2>
            <p class="muted small">
              #{{ selTask.id }} · {{ agentName(selTask.agent_id) }} · {{ projectName(selTask.project_id) }}
              <template v-if="selTask.branch"> · rama <code>{{ selTask.branch }}</code></template>
              <template v-if="selTask.cost_usd"> · {{ usd(selTask.cost_usd) }}</template>
            </p>
          </div>
          <StatusChip :state="statusChip(selTask.status)" :text="STATUS_TEXT[selTask.status] ?? selTask.status" />
        </div>

        <div v-if="selInbox" class="risk" :class="`risk--${selInbox.level}`">
          <b>Riesgo {{ LEVEL_TEXT[selInbox.level] ?? selInbox.level }} ({{ selInbox.level }})</b>
          <span v-for="r in selInbox.reasons" :key="r">· {{ r }}</span>
        </div>

        <!-- acciones -->
        <div class="acts">
          <template v-if="selTask.status === 'running' || selTask.status === 'pending'">
            <button class="btn btn--danger" :disabled="busy" @click="stop(selTask)"><i class="fa-solid fa-stop" /> Parar</button>
            <RouterLink class="btn" to="/oficina"><i class="fa-solid fa-building" /> Verlo en la oficina</RouterLink>
          </template>
          <template v-else-if="selTask.plan_id === null && ['review', 'approved'].includes(selTask.status)">
            <button class="btn btn--primary" :disabled="busy || !files.length" @click="approveMerge(selTask)"><i class="fa-solid fa-code-merge" /> {{ selTask.status === "review" ? "Aprobar e integrar" : "Integrar" }}</button>
            <button v-if="selTask.status === 'review'" class="btn" :disabled="busy" @click="approveOnly(selTask)"><i class="fa-solid fa-check" /> Solo aprobar</button>
            <button class="btn btn--danger" :disabled="busy" @click="discard(selTask)"><i class="fa-solid fa-xmark" /> Descartar</button>
          </template>
          <template v-else-if="selTask.plan_id !== null && selInbox?.type === 'task_decision'">
            <button class="btn btn--primary" :disabled="busy" @click="planAct(`/api/tasks/${selTask.id}/decide`, { approve: true })"><i class="fa-solid fa-check" /> Aprobar y seguir</button>
            <button class="btn btn--danger" :disabled="busy" @click="planAct(`/api/tasks/${selTask.id}/decide`, { approve: false }, '¿Rechazar esta subtarea? Se deshace su commit.')"><i class="fa-solid fa-xmark" /> Rechazar</button>
          </template>
          <RouterLink class="btn" :to="`/chat/${selTask.id}`"><i class="fa-solid fa-comments" /> Conversación</RouterLink>
          <RouterLink v-if="selTask.plan_id" class="btn" :to="`/planes/${selTask.plan_id}`"><i class="fa-solid fa-diagram-project" /> Plan</RouterLink>
        </div>
        <p v-if="error" class="error small">{{ error }}</p>

        <!-- pedir cambios: sigue la conversación en la misma rama -->
        <form v-if="selTask.plan_id === null && ['review', 'approved', 'done'].includes(selTask.status)" class="ask" @submit.prevent="askChanges(selTask)">
          <input v-model="ask" class="input" placeholder="¿Algo que cambiar? Pídeselo al agente (sigue en la misma rama)…">
          <button class="btn btn--small" :disabled="busy || !ask.trim()"><i class="fa-solid fa-reply" /> Pedir cambios</button>
        </form>

        <div class="blocks">
          <section class="blk">
            <h4 @click="promptOpen = !promptOpen">Encargo <i class="fa-solid" :class="promptOpen ? 'fa-chevron-up' : 'fa-chevron-down'" /></h4>
            <p class="prompt" :class="{ open: promptOpen }" @click="promptOpen = !promptOpen">{{ selTask.prompt }}</p>
          </section>
          <section v-if="selTask.final" class="blk">
            <h4>Respuesta del agente</h4>
            <div class="final"><Markdown :text="selTask.final" /></div>
          </section>
          <section v-if="selTask.status === 'running' && localOf(selTask.id)" class="blk live">
            <h4>🦙 Modelo local en directo · {{ localOf(selTask.id)!.task }}</h4>
            <p v-if="localOf(selTask.id)!.thinking" class="think">💭 {{ localOf(selTask.id)!.thinking.slice(-800) }}</p>
            <pre v-if="localOf(selTask.id)!.text">{{ localOf(selTask.id)!.text.slice(-1500) }}</pre>
          </section>
        </div>

        <!-- cambios -->
        <section v-if="!['running', 'pending'].includes(selTask.status)" class="changes">
          <h4>Cambios <em v-if="files.length">{{ files.length }} archivo{{ files.length === 1 ? "" : "s" }} · <span class="a">+{{ totals.add }}</span> <span class="d">−{{ totals.del }}</span></em></h4>
          <p v-if="loadingDiff" class="muted small">Cargando el diff…</p>
          <p v-else-if="!review?.available" class="muted small">El worktree ya no existe (integrada o descartada).</p>
          <p v-else-if="!files.length" class="muted small">Sin cambios en archivos (fue una consulta).</p>
          <div v-else class="diffwrap">
            <ul class="flist">
              <li v-for="(f, k) in files" :key="f.path" :class="{ on: k === fileSel }" @click="fileSel = k">
                <span class="fname">{{ f.path }}</span>
                <span class="fst">{{ f.status !== "modificado" ? f.status : "" }} <span class="a">+{{ f.add }}</span> <span class="d">−{{ f.del }}</span></span>
              </li>
            </ul>
            <pre v-if="curFile" class="diff"><span v-for="(l, k) in curFile.lines" :key="k" :class="lineCls(l)">{{ l }}
</span></pre>
          </div>
          <p v-if="review?.target" class="muted small">Se integraría en <code>{{ review.target }}</code>.</p>
        </section>
      </template>

      <template v-else-if="selPlan">
        <div class="d-h">
          <div>
            <h2>{{ selPlan.request }}</h2>
            <p class="muted small">Plan #{{ selPlan.id }} · {{ projectName(selPlan.project_id) }}<template v-if="selPlan.cost_usd"> · {{ usd(selPlan.cost_usd) }}</template></p>
          </div>
          <span class="pill">{{ PLAN_TEXT[selPlan.status] ?? selPlan.status }}</span>
        </div>
        <div v-if="selInbox" class="risk" :class="`risk--${selInbox.level}`">
          <b>Riesgo {{ LEVEL_TEXT[selInbox.level] ?? selInbox.level }}</b>
          <span v-for="r in selInbox.reasons" :key="r">· {{ r }}</span>
        </div>
        <div class="acts">
          <template v-if="selInbox?.type === 'plan_approval'">
            <button class="btn btn--primary" :disabled="busy" @click="planAct(`/api/plans/${selPlan.id}/approve`)"><i class="fa-solid fa-check" /> Aprobar plan</button>
            <button class="btn btn--danger" :disabled="busy" @click="planAct(`/api/plans/${selPlan.id}/reject`, {}, '¿Rechazar el plan?')"><i class="fa-solid fa-xmark" /> Rechazar</button>
          </template>
          <template v-else-if="selInbox?.type === 'plan_merge'">
            <button class="btn btn--primary" :disabled="busy" @click="planAct(`/api/plans/${selPlan.id}/merge`, { confirm: true }, `¿Integrar la rama del plan?\n\n${NOPUSH}`)"><i class="fa-solid fa-code-merge" /> Integrar plan</button>
            <button class="btn btn--danger" :disabled="busy" @click="planAct(`/api/plans/${selPlan.id}/reject`, {}, '¿Rechazar el plan? Se borra su rama.')"><i class="fa-solid fa-xmark" /> Rechazar</button>
          </template>
          <RouterLink class="btn" :to="`/planes/${selPlan.id}`"><i class="fa-solid fa-diagram-project" /> Ver el plan entero</RouterLink>
        </div>
        <p v-if="error" class="error small">{{ error }}</p>
      </template>

      <div v-else class="empty">
        <i class="fa-regular fa-circle-check" />
        <p>Nada que revisar ahora. Cuando un agente termine algo, aparecerá aquí.</p>
      </div>
    </main>
  </div>
</template>

<style scoped>
.work { display: grid; grid-template-columns: 340px minmax(0, 1fr); gap: 12px; max-width: 1500px; margin: 0 auto; align-items: start; }
.lists { display: grid; gap: 12px; position: sticky; top: calc(var(--top-h) + 12px); max-height: calc(100vh - 110px); overflow: auto; }
.pad { padding: 14px; }
.card-title em { font-style: normal; color: var(--ink-faint); margin-left: 4px; }
.item {
  display: flex; gap: 8px; width: 100%; text-align: left; border: 0; background: none; font: inherit; color: inherit;
  padding: 8px; border-radius: var(--radius-sm); cursor: pointer; align-items: flex-start;
}
.item:hover { background: var(--panel-hover); }
.item.on { background: var(--accent-weak); }
.item__b { display: grid; gap: 2px; min-width: 0; }
.item__b b { font-size: 13px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; }
.item__b small { color: var(--ink-faint); font-size: 11.5px; overflow-wrap: anywhere; }
.item .act { color: var(--ink-dim); }
.item .loc { color: #0284c7; font-style: italic; }
.bar { width: 4px; align-self: stretch; border-radius: 3px; flex-shrink: 0; }
.lvl { font-size: 10.5px; font-weight: 800; padding: 2px 6px; border-radius: 6px; background: var(--panel-raised); flex-shrink: 0; }
.lvl--N2 { background: var(--crit-weak); color: var(--crit); }
.lvl--N1 { background: var(--warn-weak); color: var(--warn); }
.detail { min-height: 60vh; display: grid; gap: 12px; align-content: start; }
.d-h { display: flex; gap: 12px; align-items: flex-start; justify-content: space-between; }
.d-h h2 { margin: 0; font-size: 19px; overflow-wrap: anywhere; }
.d-h p { margin: 4px 0 0; }
.risk { padding: 8px 12px; border-radius: var(--radius-sm); font-size: 12.5px; display: flex; flex-wrap: wrap; gap: 4px 8px; background: var(--panel-raised); }
.risk--N2 { background: var(--crit-weak); }
.risk--N1 { background: var(--warn-weak); }
.acts { display: flex; flex-wrap: wrap; gap: 8px; }
.ask { display: flex; gap: 8px; }
.ask input { flex: 1; min-width: 0; }
.blocks { display: grid; gap: 10px; }
.blk { background: var(--panel-raised); border-radius: var(--radius); padding: 10px 12px; }
.blk h4, .changes h4 { margin: 0 0 6px; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-faint); cursor: default; }
.blk h4 i { margin-left: 4px; cursor: pointer; }
.prompt { margin: 0; white-space: pre-wrap; font-size: 13px; display: -webkit-box; -webkit-line-clamp: 4; line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; cursor: pointer; }
.prompt.open { display: block; }
.final { max-height: 340px; overflow: auto; font-size: 13.5px; }
.live { background: rgba(14, 165, 233, 0.1); }
.live .think { font-style: italic; color: var(--ink-dim); font-size: 12.5px; white-space: pre-wrap; margin: 0 0 6px; }
.live pre { margin: 0; white-space: pre-wrap; font-size: 12px; max-height: 200px; overflow: auto; }
.changes em { font-style: normal; text-transform: none; letter-spacing: 0; margin-left: 4px; }
.a { color: var(--ok); font-weight: 700; }
.d { color: var(--crit); font-weight: 700; }
.diffwrap { display: grid; grid-template-columns: minmax(180px, 260px) minmax(0, 1fr); gap: 10px; }
.flist { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; align-content: start; }
.flist li { padding: 6px 8px; border-radius: var(--radius-sm); cursor: pointer; display: grid; gap: 1px; font-size: 12.5px; }
.flist li:hover { background: var(--panel-hover); }
.flist li.on { background: var(--accent-weak); }
.fname { font-family: var(--font-mono); overflow-wrap: anywhere; }
.fst { font-size: 11px; color: var(--ink-faint); }
.diff {
  margin: 0; font-family: var(--font-mono); font-size: 12px; line-height: 1.5; background: var(--panel-raised);
  border-radius: var(--radius-sm); padding: 8px 0; max-height: 60vh; overflow: auto; white-space: pre;
}
.diff span { display: block; padding: 0 12px; }
.diff .add { background: color-mix(in srgb, var(--ok) 16%, transparent); }
.diff .del { background: color-mix(in srgb, var(--crit) 14%, transparent); }
.diff .hunk { color: var(--info); background: color-mix(in srgb, var(--info) 8%, transparent); }
.empty { display: grid; place-items: center; gap: 8px; padding: 80px 20px; color: var(--ink-faint); text-align: center; }
.empty i { font-size: 30px; }
@media (max-width: 980px) {
  .work { grid-template-columns: 1fr; }
  .lists { position: static; max-height: none; }
  .diffwrap { grid-template-columns: 1fr; }
}
</style>
