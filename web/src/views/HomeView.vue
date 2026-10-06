<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import AgentAvatar from "../components/AgentAvatar.vue";
import Card from "../components/Card.vue";
import StatusChip from "../components/StatusChip.vue";
import {
  PLAN_TEXT, ROLE_TEXT, STATUS_TEXT, agentName, ago, describeActivity, duration, live, parseTs, planChip, planList,
  post, projectName, refreshActivity, refreshAll, speedText, statusChip, usd,
  type Agent, type InboxItem, type RecentTask, type Task,
} from "../api";

const router = useRouter();

// reloj para «hace X» y el tiempo que lleva cada agente
const now = ref(Date.now());
let timer: ReturnType<typeof setInterval>;
onMounted(() => {
  timer = setInterval(() => (now.value = Date.now()), 1000);
  refreshActivity().catch(() => {});
});
onUnmounted(() => clearInterval(timer));

const tasks = computed(() => Object.values(live.tasks));
const running = computed(() => tasks.value.filter((t) => t.status === "running"));

interface Member {
  agent: Agent;
  current: Task | undefined;
  last: Task | undefined;
}

// trabajando primero, luego por rol (director, jefe, trabajadores)
const ROLE_ORDER: Record<string, number> = { director: 0, jefe: 1, trabajador: 2 };
const team = computed<Member[]>(() =>
  live.agents
    .map((agent) => {
      const mine = tasks.value.filter((t) => t.agent_id === agent.id).sort((a, b) => b.id - a.id);
      return { agent, current: mine.find((t) => t.status === "running"), last: mine.find((t) => t.status !== "running") };
    })
    .sort((a, b) => Number(!!b.current) - Number(!!a.current) ||
      (ROLE_ORDER[a.agent.role ?? ""] ?? 9) - (ROLE_ORDER[b.agent.role ?? ""] ?? 9)),
);

const activePlans = computed(() => planList.value.filter((p) => ["planning", "running", "approved"].includes(p.status)));

const weekCost = computed(() => {
  const since = now.value - 7 * 864e5;
  return tasks.value.filter((t) => parseTs(t.created_at) >= since).reduce((s, t) => s + (t.cost_usd ?? 0), 0);
});

const summary = computed(() => {
  const n = running.value.length;
  const p = live.inbox.length;
  const parts = [n ? `${n} ${n === 1 ? "agente trabajando" : "agentes trabajando"}` : "Nadie trabajando ahora mismo"];
  parts.push(p ? `${p} ${p === 1 ? "cosa espera" : "cosas esperan"} tu decisión` : "nada pendiente de ti");
  return parts.join(" · ");
});

const KIND: Record<string, string> = { director: "planificando", worker: "trabajando", reviewer: "revisando" };

function verdictText(v: string): { text: string; state: "ok" | "warn" | "crit" } {
  if (v === "approve") return { text: "aprobado", state: "ok" };
  if (v === "request_changes") return { text: "pide cambios", state: "crit" };
  return { text: "te lo pasa a ti", state: "warn" };
}

function reviewerOf(t: RecentTask): string {
  const plan = t.plan_id ? live.plans[t.plan_id] : undefined;
  return plan?.reviewer_agent_id ? agentName(plan.reviewer_agent_id) : "Jefe técnico";
}

function lines(t: RecentTask) {
  return t.files.reduce((s, f) => ({ add: s.add + f.added, del: s.del + f.deleted }), { add: 0, del: 0 });
}

const INBOX_TEXT: Record<string, string> = {
  plan_approval: "Aprobar plan",
  plan_merge: "Integrar plan",
  task_decision: "Decidir subtarea",
  task_review: "Revisar tarea",
};

function openInbox(i: InboxItem) {
  router.push(i.type === "task_review" ? `/chat/${i.task_id}` : `/planes/${i.plan_id}`);
}

// --- decidir sin salir del Inicio
interface Choice {
  label: string;
  tone: "ok" | "primary" | "danger";
  run: () => Promise<unknown>;
  confirm?: string;
}

function choices(i: InboxItem): Choice[] {
  const t = i.task_id ? live.tasks[i.task_id] : undefined;
  const merge = (path: string) => post(path, { confirm: true });
  switch (i.type) {
    case "task_review":
      return [
        t?.status === "approved"
          ? { label: "Integrar", tone: "primary", run: () => merge(`/api/tasks/${i.task_id}/merge`),
              confirm: `¿Integrar «${i.title}» en tu rama actual?

Merge local; nunca se hace push.` }
          : { label: "Aprobar e integrar", tone: "ok",
              run: async () => { await post(`/api/tasks/${i.task_id}/approve`); await merge(`/api/tasks/${i.task_id}/merge`); },
              confirm: `¿Aprobar e integrar «${i.title}» en tu rama actual?

Merge local; nunca se hace push.` },
        { label: "Descartar", tone: "danger", run: () => post(`/api/tasks/${i.task_id}/reject`),
          confirm: `¿Descartar «${i.title}»? Se borran su worktree y su rama.` },
      ];
    case "plan_approval":
      return [
        { label: "Aprobar plan", tone: "ok", run: () => post(`/api/plans/${i.plan_id}/approve`) },
        { label: "Rechazar", tone: "danger", run: () => post(`/api/plans/${i.plan_id}/reject`),
          confirm: "¿Rechazar el plan? No se ejecutará ninguna subtarea." },
      ];
    case "plan_merge":
      return [
        { label: "Integrar", tone: "primary", run: () => merge(`/api/plans/${i.plan_id}/merge`),
          confirm: `¿Integrar la rama del plan #${i.plan_id} en tu rama actual?

Merge local; nunca se hace push.` },
        { label: "Rechazar", tone: "danger", run: () => post(`/api/plans/${i.plan_id}/reject`),
          confirm: "¿Rechazar el plan? Se borra su rama con todo lo hecho." },
      ];
    case "task_decision":
      return [
        { label: "Aprobar y seguir", tone: "ok", run: () => post(`/api/tasks/${i.task_id}/decide`, { approve: true }) },
        { label: "Rechazar", tone: "danger", run: () => post(`/api/tasks/${i.task_id}/decide`, { approve: false }),
          confirm: "¿Rechazar esta subtarea? Se deshace su commit y el plan sigue con la siguiente." },
      ];
  }
  return [];
}

const acting = ref<string | null>(null);
const actError = ref("");
async function decide(i: InboxItem, c: Choice) {
  if (c.confirm && !window.confirm(c.confirm)) return;
  acting.value = `${i.type}-${i.plan_id ?? ""}-${i.task_id ?? ""}`;
  actError.value = "";
  try {
    await c.run();
  } catch (e) {
    actError.value = (e as Error).message;
  } finally {
    acting.value = null;
    await refreshAll().catch(() => {});
  }
}
const keyOf = (i: InboxItem) => `${i.type}-${i.plan_id ?? ""}-${i.task_id ?? ""}`;
</script>

<template>
  <div class="page">
    <div class="hello">
      <h2 class="title">Inicio</h2>
      <p class="muted">{{ summary }}</p>
    </div>

    <div class="stats">
      <div class="stat"><span class="stat__n mono">{{ running.length }}</span><span class="stat__t">trabajando</span></div>
      <RouterLink to="/bandeja" class="stat" :class="{ 'stat--warn': live.inbox.length }">
        <span class="stat__n mono">{{ live.inbox.length }}</span><span class="stat__t">esperan tu decisión</span>
      </RouterLink>
      <RouterLink to="/planes" class="stat">
        <span class="stat__n mono">{{ activePlans.length }}</span><span class="stat__t">planes en marcha</span>
      </RouterLink>
      <div class="stat" title="Coste equivalente en API (con suscripción no se paga aparte)">
        <span class="stat__n mono">{{ usd(weekCost) }}</span><span class="stat__t">últimos 7 días</span>
      </div>
    </div>

    <Card v-if="live.inbox.length" title="Te toca a ti" subtitle="Lo de nivel N0/N1 lo resuelven solos los agentes; esto no." level="warn">
      <p v-if="actError" class="error">{{ actError }}</p>
      <ul class="todo">
        <li v-for="i in live.inbox" :key="keyOf(i)" class="todo__item">
          <button class="todo__btn" :title="'Abrir ' + (i.type === 'task_review' ? 'la conversación' : 'el plan')" @click="openInbox(i)">
            <span class="todo__what">{{ INBOX_TEXT[i.type] ?? i.type }}</span>
            <span class="todo__title">{{ i.title }}</span>
            <span class="muted small">{{ i.reasons[0] }}</span>
            <span class="todo__go" aria-hidden="true">→</span>
          </button>
          <div class="todo__acts">
            <button
              v-for="c in choices(i)" :key="c.label" class="btn btn--small" :class="`btn--${c.tone}`"
              :disabled="acting === keyOf(i)" @click="decide(i, c)"
            >{{ c.label }}</button>
            <button class="btn btn--small btn--ghost" @click="openInbox(i)">{{ i.type === "task_review" ? "Ver cambios" : "Ver diff" }}</button>
          </div>
        </li>
      </ul>
    </Card>

    <section class="block">
      <h3 class="block__title">El equipo</h3>
      <p v-if="!live.agents.length" class="empty">
        Aún no hay agentes. Créalos en <RouterLink to="/ajustes">Ajustes</RouterLink>.
      </p>
      <div class="team">
        <article v-for="m in team" :key="m.agent.id" class="member" :class="{ 'member--busy': m.current }">
          <div class="member__head">
            <AgentAvatar :agent="m.agent" :busy="!!m.current" />
            <div class="member__who">
              <strong>{{ m.agent.name }}</strong>
              <span class="muted small">{{ ROLE_TEXT[m.agent.role ?? ""] ?? m.agent.role ?? "sin rol" }} ·
                <template v-if="m.agent.provider.startsWith('local')">local · usa {{ live.local.model ?? "(nada arrancado)" }}</template>
                <template v-else>{{ m.agent.provider }}{{ m.agent.model ? ` ${m.agent.model}` : "" }}</template></span>
            </div>
          </div>
          <template v-if="m.current">
            <RouterLink :to="`/tareas/${m.current.id}`" class="member__task">
              {{ KIND[m.current.kind ?? "worker"] }}: {{ m.current.title }}
            </RouterLink>
            <p class="member__doing">{{ describeActivity(live.activity[m.current.id]) }}</p>
            <p v-if="live.speed[m.current.id]" class="member__speed small">⚡ {{ speedText(live.speed[m.current.id]) }}</p>
            <p class="member__meta small muted">
              {{ projectName(m.current.project_id) }}
              <template v-if="m.current.plan_id"> · <RouterLink :to="`/planes/${m.current.plan_id}`">plan #{{ m.current.plan_id }}</RouterLink></template>
              · lleva {{ duration(now - parseTs(m.current.created_at)) }}
            </p>
          </template>
          <template v-else>
            <p class="member__idle">Libre</p>
            <p v-if="m.last" class="member__meta small muted">
              Último: <RouterLink :to="`/tareas/${m.last.id}`">{{ m.last.title }}</RouterLink>
              · {{ ago(parseTs(m.last.finished_at ?? m.last.created_at), now) }}
            </p>
          </template>
        </article>
      </div>
    </section>

    <div class="two">
      <section class="block">
        <h3 class="block__title">Lo último que ha pasado</h3>
        <p v-if="!live.recent.length" class="empty">Todavía no ha terminado ninguna tarea.</p>
        <ol class="feed">
          <li v-for="t in live.recent" :key="t.id" class="event">
            <AgentAvatar :agent="live.agents.find((a) => a.id === t.agent_id)" :size="32" />
            <div class="event__body">
              <p class="event__line">
                <strong>{{ agentName(t.agent_id) }}</strong>
                {{ t.kind === "reviewer" ? "revisó" : "terminó" }}
                <RouterLink :to="`/tareas/${t.id}`">{{ t.title }}</RouterLink>
              </p>
              <div class="row">
                <StatusChip :state="statusChip(t.status)" :text="STATUS_TEXT[t.status] ?? t.status" />
                <span v-if="t.level" class="lvl">{{ t.level }}</span>
                <span class="muted small">{{ ago(parseTs(t.finished_at), now) }}</span>
              </div>
              <div v-if="t.files.length" class="files">
                <span class="small"><span class="add">+{{ lines(t).add }}</span> <span class="del">−{{ lines(t).del }}</span>
                  en {{ t.files.length }} {{ t.files.length === 1 ? "archivo" : "archivos" }}</span>
                <code v-for="f in t.files.slice(0, 4)" :key="f.path" class="file">{{ f.path }}</code>
                <span v-if="t.files.length > 4" class="muted small">y {{ t.files.length - 4 }} más</span>
              </div>
              <div v-if="t.review" class="verdict">
                <span class="verdict__who">{{ reviewerOf(t) }}</span>
                <StatusChip :state="verdictText(t.review.verdict).state" :text="verdictText(t.review.verdict).text" />
                <span class="verdict__why">{{ t.review.reason }}</span>
              </div>
              <p v-else-if="t.approved_by" class="small muted">Aprobó: {{ t.approved_by }}</p>
            </div>
          </li>
        </ol>
      </section>

      <section class="block">
        <h3 class="block__title">Planes</h3>
        <p v-if="!planList.length" class="empty">Sin planes. <RouterLink to="/planes">Pide uno al Director</RouterLink>.</p>
        <ul class="plans">
          <li v-for="p in planList.slice(0, 6)" :key="p.id">
            <RouterLink :to="`/planes/${p.id}`" class="plan">
              <span class="plan__req">{{ p.request }}</span>
              <span class="row">
                <StatusChip :state="planChip(p.status)" :text="PLAN_TEXT[p.status] ?? p.status" />
                <span class="muted small">{{ projectName(p.project_id) }} · {{ ago(parseTs(p.created_at), now) }}</span>
              </span>
            </RouterLink>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<style scoped>
.hello p {
  margin: 4px 0 0;
  font-size: 16px;
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px;
}
.stat {
  display: grid;
  gap: 2px;
  padding: 14px 18px;
  border-radius: var(--radius);
  background: var(--panel);
  border: 1px solid var(--line);
  color: inherit;
  text-decoration: none;
}
a.stat:hover {
  border-color: var(--line-strong);
}
.stat__n {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.02em;
}
.stat__t {
  color: var(--ink-dim);
  font-size: 14px;
}
.stat--warn {
  background: var(--warn-weak);
  border-color: transparent;
}
.stat--warn .stat__n {
  color: var(--warn);
}
.block {
  display: grid;
  gap: 12px;
  align-content: start;
}
.block__title {
  font-size: 17px;
}
.team {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
.member {
  display: grid;
  gap: 8px;
  align-content: start;
  padding: 16px;
  border-radius: var(--radius);
  background: var(--panel);
  border: 1px solid var(--line);
}
.member--busy {
  box-shadow: var(--shadow);
  border-color: var(--line-strong);
}
.member__head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.member__who {
  display: grid;
  min-width: 0;
}
.member__who strong {
  font-size: 15.5px;
}
.member__task {
  font-weight: 600;
  color: var(--ink);
  text-decoration: none;
}
.member__task:hover {
  text-decoration: underline;
}
.member__doing {
  margin: 0;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: var(--panel-raised);
  font-size: 14px;
  color: var(--ink-dim);
  overflow-wrap: anywhere;
}
.member__speed {
  margin: 0;
  color: var(--ink-dim);
  font-variant-numeric: tabular-nums;
}
.member__idle {
  margin: 0;
  color: var(--ink-faint);
  font-weight: 600;
}
.member__meta {
  margin: 0;
}
.two {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr);
  gap: var(--gap);
  align-items: start;
}
@media (max-width: 960px) {
  .two {
    grid-template-columns: 1fr;
  }
}
.feed,
.plans,
.todo {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
}
.event {
  display: flex;
  gap: 12px;
  padding: 14px 16px;
  border-radius: var(--radius);
  background: var(--panel);
  border: 1px solid var(--line);
}
.event__body {
  display: grid;
  gap: 7px;
  min-width: 0;
  flex: 1;
}
.event__line {
  margin: 0;
}
.event__line a {
  color: var(--ink);
  font-weight: 600;
}
.lvl {
  font-size: 12px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--panel-raised);
  color: var(--ink-dim);
}
.files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.file {
  padding: 2px 7px;
  border-radius: 6px;
  background: var(--panel-raised);
  color: var(--ink-dim);
  overflow-wrap: anywhere;
}
.add {
  color: var(--ok);
  font-weight: 700;
}
.del {
  color: var(--crit);
  font-weight: 700;
}
.verdict {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 9px 11px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--role-jefe) 9%, var(--panel));
  border-left: 3px solid var(--role-jefe);
  font-size: 14px;
}
.verdict__who {
  font-weight: 700;
  color: var(--role-jefe);
}
.verdict__why {
  flex-basis: 100%;
  color: var(--ink-dim);
}
.plan {
  display: grid;
  gap: 6px;
  padding: 12px 14px;
  border-radius: var(--radius);
  background: var(--panel);
  border: 1px solid var(--line);
  color: inherit;
  text-decoration: none;
}
.plan:hover {
  border-color: var(--line-strong);
}
.plan__req {
  font-weight: 600;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.todo__item {
  display: grid;
  gap: 6px;
  padding: 4px;
  border-radius: var(--radius-sm);
  background: var(--panel-raised);
}
.todo__acts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 8px 6px;
}
.todo__btn {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  grid-template-areas: "what title go" "why why go";
  gap: 2px 12px;
  align-items: center;
  width: 100%;
  padding: 10px 12px;
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--panel-raised);
  text-align: left;
  cursor: pointer;
}
.todo__btn:hover {
  background: var(--warn-weak);
}
.todo__what {
  grid-area: what;
  font-weight: 700;
  color: var(--warn);
}
.todo__title {
  grid-area: title;
  font-weight: 600;
}
.todo__btn .small {
  grid-area: why;
}
.todo__go {
  grid-area: go;
  color: var(--ink-faint);
  font-size: 18px;
}
</style>
