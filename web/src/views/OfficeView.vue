<script setup lang="ts">
// Oficina (sustituye al Inicio): la oficina 3D con un puesto por agente real, la misión seleccionada (tarea o
// plan) con sus pasos, la bandeja de aprobaciones, recursos (GPU, modelo local, plan de Claude, tok/s, worktrees),
// el inspector del agente elegido y abajo Timeline / Terminal / Diff. Nada simulado: todo sale de la API.
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import StatusChip from "../components/StatusChip.vue";
import OfficeDock from "../office/OfficeDock.vue";
import { MAX_STATIONS, Office, type BoardStep, type GitRow, type Placement, type StationKind, type StationSpec, type StationState } from "../office/office3d";
import {
  PLAN_TEXT, PROVIDER_TEXT, ROLE_TEXT, STATUS_TEXT, agentColor, agentName, api, describeActivity, duration, live,
  modelText, onTaskEvent, openCatalog, parseTs, pct, planChip, planList, post, projectName, refreshAll, speedText,
  statusChip, tps, ui, usd,
  type Agent, type Gpu, type InboxItem, type Review, type Task, type TaskEvent, type Worktree,
} from "../api";

const router = useRouter();
const YOU = "#eab308";
const LOCAL = "#0ea5e9";

// reloj para tiempos «lleva X»
const now = ref(Date.now());
let clock: ReturnType<typeof setInterval>;

// ---------- agentes y puestos
const ROLE_ORDER: Record<string, number> = { director: 0, jefe: 1, trabajador: 2, consultas: 3 };
const agentsSorted = computed(() => [...live.agents].sort((a, b) =>
  (ROLE_ORDER[a.role ?? ""] ?? 9) - (ROLE_ORDER[b.role ?? ""] ?? 9) || a.id - b.id));
// En la oficina solo está quien tiene algo que ver con el trabajo: trabajando, esperando tu decisión, que trabajó hace
// poco (PRESENCE_MS) o que llamaste tú (Catálogo → «En la oficina»). Los demás aparecen cuando se les encarga algo.
const PRESENCE_MS = 2 * 3600e3;
const summoned = ref(new Set<number>());
function lastSeen(aid: number): number {
  return Math.max(0, ...mine(aid).map((t) => Math.max(parseTs(t.created_at) || 0, parseTs(t.finished_at) || 0)));
}
// «Quitar de la oficina» = fuera de servicio (config.off): no aparece aunque haya trabajado y el Director no le
// encarga nada. Si aún le queda una tarea en marcha o esperando tu decisión, sigue en su puesto hasta acabar.
const isOff = (a: Agent) => !!a.config.off;
const present = computed(() => agentsSorted.value.filter((a) => runningOf(a.id) || waitingOf(a.id) ||
  (!isOff(a) && (summoned.value.has(a.id) || now.value - lastSeen(a.id) < PRESENCE_MS))));
const shown = computed(() => present.value.slice(0, MAX_STATIONS));
const hidden = computed(() => present.value.slice(MAX_STATIONS));
const away = computed(() => agentsSorted.value.filter((a) => !present.value.includes(a)));
const kindOf = (a: Agent): StationKind =>
  (["director", "jefe", "trabajador", "consultas"].includes(a.role ?? "") ? a.role : "otro") as StationKind;
const ICON: Record<string, string> = {
  you: "fa-crown", director: "fa-chess-king", jefe: "fa-shield-halved", trabajador: "fa-hammer",
  consultas: "fa-magnifying-glass", otro: "fa-user-astronaut",
};
const specs = computed<StationSpec[]>(() => [
  { id: "you", name: "Tú", color: YOU, kind: "you" },
  ...shown.value.map((a) => ({ id: `a${a.id}`, name: a.name, color: agentColor(a), kind: kindOf(a) })),
]);
const agentOf = (sid: string) => (sid.startsWith("a") ? live.agents.find((a) => `a${a.id}` === sid) : undefined);

const tasks = computed(() => Object.values(live.tasks));
const mine = (aid: number) => tasks.value.filter((t) => t.agent_id === aid).sort((a, b) => b.id - a.id);
const runningOf = (aid: number) => mine(aid).find((t) => t.status === "running");
const waitingOf = (aid: number) => live.inbox.find((i) => i.task_id && live.tasks[i.task_id]?.agent_id === aid);

function stateOf(a: Agent): StationState {
  if (runningOf(a.id)) return "working";
  return waitingOf(a.id) ? "waiting" : "idle";
}

function bubbleOf(sid: string): string {
  if (sid === "you") return live.inbox.length ? `${live.inbox.length} ${live.inbox.length === 1 ? "decisión pendiente" : "decisiones pendientes"}` : "";
  const a = agentOf(sid);
  if (!a) return "";
  const t = runningOf(a.id);
  if (t) {
    const sp = live.speed[t.id];
    return describeActivity(live.activity[t.id]) + (sp?.tps ? ` · ${tps(sp.tps)}` : "");
  }
  return waitingOf(a.id) ? "Espera tu decisión" : "";
}

function stateText(sid: string): { text: string; cls: string } {
  if (sid === "you") return live.inbox.length ? { text: "decide", cls: "waiting" } : { text: "director", cls: "" };
  const a = agentOf(sid);
  if (!a) return { text: "", cls: "" };
  const s = stateOf(a);
  return s === "working" ? { text: "trabajando", cls: "working" } : s === "waiting" ? { text: "espera", cls: "waiting" }
    : { text: ROLE_TEXT[a.role ?? ""] ?? a.role ?? "agente", cls: "" };
}

// ---------- selección (puesto, «you» o «rack»)
const sel = ref<string>("you");
const selAgent = computed(() => agentOf(sel.value));

// ---------- misiones: tareas sueltas y planes, la más reciente (o la que está en marcha) por defecto
interface MissionRef { key: string; kind: "task" | "plan"; id: number; title: string; created: number }
const missions = computed<MissionRef[]>(() => [
  ...tasks.value.filter((t) => t.plan_id === null).map((t) => ({ key: `t${t.id}`, kind: "task" as const, id: t.id, title: t.title, created: parseTs(t.created_at) })),
  ...planList.value.map((p) => ({ key: `p${p.id}`, kind: "plan" as const, id: p.id, title: p.request, created: parseTs(p.created_at) })),
].sort((a, b) => b.created - a.created).slice(0, 30));
const chosen = ref<string | null>(null);
const autoKey = computed(() => {
  const t = tasks.value.find((x) => x.status === "running" && x.plan_id === null);
  if (t) return `t${t.id}`;
  const p = planList.value.find((x) => ["planning", "running"].includes(x.status));
  return p ? `p${p.id}` : missions.value[0]?.key ?? null;
});
const curKey = computed(() => (chosen.value && missions.value.some((m) => m.key === chosen.value) ? chosen.value : autoKey.value));
const curTask = computed(() => (curKey.value?.startsWith("t") ? live.tasks[Number(curKey.value.slice(1))] : undefined));
const curPlan = computed(() => (curKey.value?.startsWith("p") ? live.plans[Number(curKey.value.slice(1))] : undefined));
const planTasks = computed(() => (curPlan.value ? tasks.value.filter((t) => t.plan_id === curPlan.value!.id).sort((a, b) => (a.seq ?? a.id) - (b.seq ?? b.id) || a.id - b.id) : []));
const missionTaskIds = computed(() => new Set(curTask.value ? [curTask.value.id] : planTasks.value.map((t) => t.id)));

// eventos de la misión (timeline, terminal) — se cargan al cambiar de misión y se completan en vivo
const events = ref<TaskEvent[]>([]);
async function loadEvents() {
  const ids = [...missionTaskIds.value];
  const all = await Promise.all(ids.map((id) => api<TaskEvent[]>(`/api/tasks/${id}/events`).catch(() => [])));
  events.value = all.flat().sort((a, b) => (a.id ?? 0) - (b.id ?? 0));
}
watch(() => [curKey.value, [...missionTaskIds.value].join(",")], () => loadEvents().catch(() => {}), { immediate: true });
const delegations = computed(() => events.value.filter((e) => e.kind === "delegate").length);

interface Step extends BoardStep { icon: string; sub?: string }
const FAILED = ["failed", "timeout", "cancelled", "interrupted"];
function taskStepState(t: Task): BoardStep["state"] {
  if (t.status === "running") return "active";
  if (t.status === "pending") return "todo";
  if (FAILED.includes(t.status)) return "failed";
  if (live.inbox.some((i) => i.task_id === t.id)) return "wait";
  return "done";
}

const steps = computed<Step[]>(() => {
  const t = curTask.value, p = curPlan.value;
  if (t) {
    const a = live.agents.find((x) => x.id === t.agent_id);
    const c = agentColor(a), name = a?.name ?? "agente", run = t.status === "running";
    const out: Step[] = [
      { label: "Encargo", who: `Tú → ${name}`, color: YOU, state: "done", icon: "fa-paper-plane" },
      { label: run ? "Trabajando" : "Trabajo", who: name, color: c, icon: ICON[kindOf(a ?? ({} as Agent))] ?? "fa-user",
        state: run ? "active" : FAILED.includes(t.status) ? "failed" : "done",
        sub: run ? describeActivity(live.activity[t.id]) : FAILED.includes(t.status) ? STATUS_TEXT[t.status] : undefined },
    ];
    if (delegations.value || (run && a?.config.delegate_local)) {
      out.push({ label: `Encargos al modelo local (${delegations.value})`, who: "Modelo local", color: LOCAL, icon: "fa-server",
        state: delegations.value ? (run ? "active" : "done") : "todo" });
    }
    if (t.status === "done") {
      out.push({ label: "Respuesta lista", who: name, color: c, state: "done", icon: "fa-comment-dots" });
    } else {
      const closed = ["merged", "rejected", "discarded"].includes(t.status);
      out.push({ label: t.status === "rejected" || t.status === "discarded" ? "Descartada" : "Revisar cambios", who: "Tú", color: YOU,
        icon: "fa-lock", state: t.status === "review" ? "wait" : closed || t.status === "approved" ? "done" : "todo" });
      out.push({ label: "Integrar en tu rama", who: "Tú", color: YOU, icon: "fa-code-merge",
        state: t.status === "merged" ? "done" : t.status === "approved" ? "wait" : "todo" });
    }
    return out;
  }
  if (p) {
    const dir = live.agents.find((x) => x.id === p.director_agent_id);
    const out: Step[] = [{ label: "Planificar", who: dir?.name ?? "Director", color: agentColor(dir), icon: "fa-chess-king",
      state: p.status === "planning" ? "active" : p.status === "failed" && !planTasks.value.length ? "failed" : "done" }];
    if (p.status === "awaiting_you") out.push({ label: "Aprobar plan", who: "Tú", color: YOU, icon: "fa-lock", state: "wait" });
    for (const st of planTasks.value.filter((x) => x.kind !== "director")) {
      const a = live.agents.find((x) => x.id === st.agent_id);
      out.push({ label: st.title, who: a?.name ?? "—", color: agentColor(a), icon: st.kind === "reviewer" ? "fa-shield-halved" : ICON[kindOf(a ?? ({} as Agent))] ?? "fa-user",
        state: taskStepState(st), sub: st.status === "running" ? describeActivity(live.activity[st.id]) : undefined });
    }
    out.push({ label: "Integrar en tu rama", who: "Tú", color: YOU, icon: "fa-code-merge",
      state: p.status === "merged" ? "done" : p.status === "ready" ? "wait" : FAILED.includes(p.status) || p.status === "rejected" ? "failed" : "todo" });
    return out;
  }
  return [];
});
const progress = computed(() => {
  const s = steps.value;
  if (!s.length) return 0;
  return s.reduce((n, x) => n + (x.state === "done" || x.state === "failed" ? 1 : x.state === "active" || x.state === "wait" ? 0.5 : 0), 0) / s.length;
});
const missionTitle = computed(() => curTask.value?.title ?? curPlan.value?.request ?? "Sin misión");
const missionStart = computed(() => parseTs(curTask.value?.created_at ?? curPlan.value?.created_at));
const missionEnd = computed(() => {
  const f = curTask.value?.finished_at;
  if (curTask.value) return curTask.value.status === "running" ? now.value : parseTs(f) || now.value;
  const ts = planTasks.value.map((t) => parseTs(t.finished_at)).filter((x) => !Number.isNaN(x));
  return curPlan.value && ["planning", "running", "approved"].includes(curPlan.value.status) ? now.value : ts.length ? Math.max(...ts) : now.value;
});

// diff: la tarea de la misión o la última subtarea con commit del plan
const diffTask = computed<Task | undefined>(() => curTask.value ?? [...planTasks.value].reverse().find((t) => t.kind === "worker" && t.head_commit));
const review = ref<Review | null>(null);
watch(() => [diffTask.value?.id, diffTask.value?.status, diffTask.value?.head_commit], async () => {
  const t = diffTask.value;
  if (!t || t.status === "running") { review.value = t ? review.value : null; return; }
  review.value = await api<Review>(`/api/tasks/${t.id}/review`).catch(() => null);
}, { immediate: true });

// ---------- nueva misión
const composing = ref(false);
const form = reactive({ project_id: null as number | null, agent_id: null as number | null, prompt: "" });
const formError = ref("");
const sending = ref(false);
watch(() => [live.projects.length, live.agents.length], () => {
  form.project_id ??= live.projects[0]?.id ?? null;
  form.agent_id ??= agentsSorted.value.find((a) => a.provider === "claude")?.id ?? agentsSorted.value[0]?.id ?? null;
}, { immediate: true });
async function launch() {
  if (!form.project_id || !form.agent_id || !form.prompt.trim()) return;
  sending.value = true;
  formError.value = "";
  try {
    const t = await post<Task>("/api/tasks", { project_id: form.project_id, agent_id: form.agent_id, prompt: form.prompt.trim() });
    live.tasks[t.id] = t;
    summoned.value = new Set([...summoned.value, form.agent_id]);
    chosen.value = `t${t.id}`;
    form.prompt = "";
    composing.value = false;
    sel.value = `a${form.agent_id}`;
  } catch (e) {
    formError.value = (e as Error).message;
  } finally {
    sending.value = false;
  }
}
async function stopMission() {
  if (curTask.value) await post(`/api/tasks/${curTask.value.id}/cancel`).catch(() => {});
  else if (curPlan.value) await post(`/api/plans/${curPlan.value.id}/cancel`).catch(() => {});
}

// ---------- bandeja de aprobaciones (las mismas decisiones que antes estaban en el Inicio)
interface Choice { label: string; icon: string; tone: "ok" | "primary" | "danger"; run: () => Promise<unknown>; confirm?: string }
const INBOX_TEXT: Record<string, string> = {
  plan_approval: "Aprobar plan", plan_merge: "Integrar plan", task_decision: "Decidir subtarea", task_review: "Revisar cambios",
};
function choices(i: InboxItem): Choice[] {
  const t = i.task_id ? live.tasks[i.task_id] : undefined;
  const merge = (path: string) => post(path, { confirm: true });
  const nopush = "Merge local; nunca se hace push.";
  switch (i.type) {
    case "task_review":
      return [
        t?.status === "approved"
          ? { label: "Integrar", icon: "fa-code-merge", tone: "primary", run: () => merge(`/api/tasks/${i.task_id}/merge`), confirm: `¿Integrar «${i.title}» en tu rama actual?\n\n${nopush}` }
          : { label: "Aprobar e integrar", icon: "fa-check", tone: "ok", confirm: `¿Aprobar e integrar «${i.title}» en tu rama actual?\n\n${nopush}`,
              run: async () => { await post(`/api/tasks/${i.task_id}/approve`); await merge(`/api/tasks/${i.task_id}/merge`); } },
        { label: "Descartar", icon: "fa-xmark", tone: "danger", run: () => post(`/api/tasks/${i.task_id}/reject`), confirm: `¿Descartar «${i.title}»? Se borran su worktree y su rama.` },
      ];
    case "plan_approval":
      return [
        { label: "Aprobar", icon: "fa-check", tone: "ok", run: () => post(`/api/plans/${i.plan_id}/approve`) },
        { label: "Rechazar", icon: "fa-xmark", tone: "danger", run: () => post(`/api/plans/${i.plan_id}/reject`), confirm: "¿Rechazar el plan? No se ejecutará ninguna subtarea." },
      ];
    case "plan_merge":
      return [
        { label: "Integrar", icon: "fa-code-merge", tone: "primary", run: () => merge(`/api/plans/${i.plan_id}/merge`), confirm: `¿Integrar la rama del plan #${i.plan_id} en tu rama actual?\n\n${nopush}` },
        { label: "Rechazar", icon: "fa-xmark", tone: "danger", run: () => post(`/api/plans/${i.plan_id}/reject`), confirm: "¿Rechazar el plan? Se borra su rama con todo lo hecho." },
      ];
    case "task_decision":
      return [
        { label: "Aprobar y seguir", icon: "fa-check", tone: "ok", run: () => post(`/api/tasks/${i.task_id}/decide`, { approve: true }) },
        { label: "Rechazar", icon: "fa-xmark", tone: "danger", run: () => post(`/api/tasks/${i.task_id}/decide`, { approve: false }), confirm: "¿Rechazar esta subtarea? Se deshace su commit y el plan sigue con la siguiente." },
      ];
  }
  return [];
}
const keyOf = (i: InboxItem) => `${i.type}-${i.plan_id ?? ""}-${i.task_id ?? ""}`;
const acting = ref<string | null>(null);
const actError = ref("");
const history = ref<{ title: string; ok: boolean; label: string }[]>([]);
async function decide(i: InboxItem, c: Choice) {
  if (c.confirm && !window.confirm(c.confirm)) return;
  acting.value = keyOf(i);
  actError.value = "";
  try {
    await c.run();
    history.value.unshift({ title: i.title, ok: c.tone !== "danger", label: c.label });
  } catch (e) {
    actError.value = (e as Error).message;
  } finally {
    acting.value = null;
    await refreshAll().catch(() => {});
  }
}
function fromOf(i: InboxItem): Agent | undefined {
  const aid = i.task_id ? live.tasks[i.task_id]?.agent_id : i.plan_id ? live.plans[i.plan_id]?.director_agent_id : null;
  return live.agents.find((a) => a.id === aid);
}
const riskOf = (i: InboxItem) => (i.level === "N2" ? "alto" : i.level === "N1" ? "medio" : "bajo");
function showInbox(i: InboxItem) {
  const t = i.task_id ? live.tasks[i.task_id] : undefined;
  chosen.value = t && t.plan_id === null ? `t${t.id}` : i.plan_id ? `p${i.plan_id}` : t?.plan_id ? `p${t.plan_id}` : chosen.value;
  dock.value?.show("diff");
}

// ---------- recursos: GPU (nvidia-smi), worktrees, tokens/s
const gpus = ref<Gpu[]>([]);
const worktrees = ref<Worktree[]>([]);
async function loadResources() {
  const r = await api<{ gpus: Gpu[]; worktrees: Worktree[] }>("/api/resources").catch(() => null);
  if (r) { gpus.value = r.gpus; worktrees.value = r.worktrees; }
}
let resTimer: ReturnType<typeof setInterval>;
const gpuFrac = (g: Gpu) => (g.mem_used_mb && g.mem_total_mb ? g.mem_used_mb / g.mem_total_mb : 0);
const gpuColor = (v: number) => (v > 0.85 ? "#ef4444" : v > 0.6 ? "#f59e0b" : "#22c55e");
const LOCAL_TEXT: Record<string, string> = { off: "apagado", loading: "cargando…", ready: "listo", failed: "falló al arrancar", external: "arrancado fuera" };

const series = ref<number[]>(new Array(60).fill(0));
const tpsNow = computed(() => {
  const vals = Object.values(live.speed).filter((s) => now.value - s.at < 4000).map((s) => s.tps ?? 0);
  return vals.length ? Math.max(...vals) : 0;
});
const spark = ref<HTMLCanvasElement>();
function drawSpark() {
  const cv = spark.value;
  if (!cv) return;
  const g = cv.getContext("2d")!, w = cv.width, h = cv.height, max = Math.max(60, ...series.value);
  g.clearRect(0, 0, w, h);
  g.beginPath();
  series.value.forEach((v, i) => {
    const x = (i / (series.value.length - 1)) * w, y = h - 2 - (v / max) * (h - 6);
    if (i) g.lineTo(x, y); else g.moveTo(x, y);
  });
  g.strokeStyle = "#5b5bf0"; g.lineWidth = 2; g.lineJoin = "round"; g.stroke();
  g.lineTo(w, h); g.lineTo(0, h); g.fillStyle = "rgba(91,91,240,.12)"; g.fill();
}
const weekCost = computed(() => {
  const since = now.value - 7 * 864e5;
  return tasks.value.filter((t) => parseTs(t.created_at) >= since).reduce((s, t) => s + (t.cost_usd ?? 0), 0);
});
const wtState = (w: Worktree): GitRow["status"] =>
  w.status === "running" || w.status === "planning" ? "active" : ["review", "approved", "ready", "done"].includes(w.status) ? "ready" : FAILED.includes(w.status) || w.status === "failed" ? "failed" : "clean";

// ---------- inspector: instrucción directa al agente seleccionado
const nudge = ref("");
const thinkOpen = ref(false);
const tail = (t: string, n = 220) => (t.length > n ? "…" + t.slice(-n).trimStart() : t);
const nudgeError = ref("");
const OPEN = ["done", "review", "approved"];
const nudgeTarget = computed(() => {
  const a = selAgent.value;
  if (!a) return null;
  const run = runningOf(a.id);
  if (run) return { kind: "busy" as const, task: run };
  const last = mine(a.id).find((t) => t.plan_id === null);
  if (last && OPEN.includes(last.status)) return { kind: "reply" as const, task: last };
  return { kind: "new" as const, project: form.project_id ?? last?.project_id ?? live.projects[0]?.id ?? null };
});
async function sendNudge() {
  const a = selAgent.value, tgt = nudgeTarget.value, text = nudge.value.trim();
  if (!a || !tgt || !text || tgt.kind === "busy") return;
  nudgeError.value = "";
  try {
    if (tgt.kind === "reply") {
      await post(`/api/tasks/${tgt.task.id}/reply`, { message: text });
      chosen.value = `t${tgt.task.id}`;
    } else {
      if (!tgt.project) throw new Error("Primero vincula un proyecto (Chat → Vincular carpeta)");
      const t = await post<Task>("/api/tasks", { project_id: tgt.project, agent_id: a.id, prompt: text });
      live.tasks[t.id] = t;
      chosen.value = `t${t.id}`;
    }
    nudge.value = "";
  } catch (e) {
    nudgeError.value = (e as Error).message;
  }
}
const agentStats = computed(() => {
  const a = selAgent.value;
  if (!a) return null;
  const ts = mine(a.id);
  return { count: ts.length, cost: ts.reduce((s, t) => s + (t.cost_usd ?? 0), 0), last: ts.find((t) => t.plan_id === null), run: runningOf(a.id) };
});
function tools(a: Agent): { text: string; cls: string; icon: string }[] {
  const c = a.config, out: { text: string; cls: string; icon: string }[] = [];
  if (a.provider !== "claude") return [{ text: "sin herramientas (solo responde)", cls: "", icon: "fa-comment" }];
  out.push({ text: c.read_only ? "solo lectura" : "lee y edita", cls: "", icon: c.read_only ? "fa-eye" : "fa-pen" });
  if (c.delegate_local) out.push({ text: "local", cls: live.local.state === "ready" ? "pill--ok" : "", icon: "fa-plug" });
  for (const m of c.mcps ?? []) out.push({ text: m, cls: "pill--active", icon: "fa-plug" });
  if (c.web) out.push({ text: "internet", cls: "pill--active", icon: "fa-globe" });
  if (c.subagents) out.push({ text: "subagentes", cls: "", icon: "fa-sitemap" });
  return out;
}
const delegators = computed(() => live.agents.filter((a) => a.config.delegate_local).map((a) => a.name));

// ---------- la escena 3D
const host = ref<HTMLElement>();
const labelsEl = ref<HTMLElement>();
const dock = ref<InstanceType<typeof OfficeDock>>();
let office: Office | null = null;
const view = ref("iso");
function goView(k: string) {
  view.value = k;
  office?.view(k);
  if (k !== "iso") sel.value = k;
}
/** Trae a un agente a la oficina (aunque no tenga trabajo) y lo enfoca. */
async function callIn(aid: number) {
  const a = live.agents.find((x) => x.id === aid);
  if (a && isOff(a)) {
    try {
      await api(`/api/agents/${aid}`, { method: "PATCH", body: JSON.stringify({ off: false }) });
      await refreshAll();
    } catch (e) {
      nudgeError.value = (e as Error).message;
      return;
    }
  }
  summoned.value = new Set([...summoned.value, aid]);
  setTimeout(() => pick(`a${aid}`), 50);
}

/** Quitar de la oficina: fuera de servicio. Si está trabajando, ofrece cancelar su tarea. */
const removing = ref(false);
async function dismiss(a: Agent) {
  const run = runningOf(a.id);
  const msg = run
    ? `${a.name} está trabajando en #${run.id} «${run.title}».\n\nAceptar: cancelar esa tarea y sacarlo de la oficina.\nCancelar: no hacer nada.`
    : `¿Quitar a ${a.name} de la oficina?\n\nQueda fuera de servicio: el Director no le encargará nada hasta que lo vuelvas a llamar (abajo, «Fuera de la oficina»).`;
  if (!confirm(msg)) return;
  removing.value = true;
  try {
    if (run) await post(`/api/tasks/${run.id}/cancel`);
    await api(`/api/agents/${a.id}`, { method: "PATCH", body: JSON.stringify({ off: true }) });
    const next = new Set(summoned.value);
    next.delete(a.id);
    summoned.value = next;
    await refreshAll();
    pick("you");
  } catch (e) {
    nudgeError.value = (e as Error).message;
  } finally {
    removing.value = false;
  }
}

// ---------- distribución: arrastrar puestos y girarlos (se guarda en Ajustes → office_layout)
const layout = ref<Record<string, Placement>>({});
const locked = ref(false);
try { locked.value = localStorage.getItem("lh-office-locked") === "1"; } catch { /* sin almacenamiento */ }
watch(locked, (v) => {
  if (office) office.movable = !v;
  try { localStorage.setItem("lh-office-locked", v ? "1" : "0"); } catch { /* sin almacenamiento */ }
});
let saveTimer: ReturnType<typeof setTimeout>;
function saveLayout() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    api("/api/settings", { method: "PUT", body: JSON.stringify({ office_layout: layout.value }) }).catch(() => {});
  }, 400);
}
async function loadLayout() {
  try {
    const r = await api<{ values: { office_layout?: Record<string, Placement> } }>("/api/settings");
    layout.value = r.values.office_layout ?? {};
    office?.setLayout(layout.value);
  } catch { /* sin ajustes: posiciones por defecto */ }
}
function resetLayout() {
  if (!confirm("¿Volver a colocar todos los puestos en su sitio por defecto?")) return;
  layout.value = {};
  saveLayout();
  location.reload();
}
const localOn = computed(() => live.local.state !== "off");
function pick(id: string) {
  sel.value = id;
  view.value = id;
  office?.view(id);
}

let offEvents: (() => void) | null = null;
onMounted(() => {
  clock = setInterval(() => {
    now.value = Date.now();
    series.value = [...series.value.slice(1), tpsNow.value];
    drawSpark();
  }, 500);
  loadResources();
  resTimer = setInterval(loadResources, 3000);
  try {
    office = new Office(host.value!, labelsEl.value!, pick);
    office.movable = !locked.value;
    office.onMove = (id, p) => {
      layout.value = { ...layout.value, [id]: p };
      saveLayout();
    };
  } catch (e) {
    webglError.value = (e as Error).message || "WebGL no disponible";
  }
  loadLayout().then(syncScene);
  syncScene();
  if (ui.focusAgent) { callIn(ui.focusAgent); ui.focusAgent = null; }
  offEvents = onTaskEvent((ev) => {
    if (missionTaskIds.value.has(ev.task_id) && ev.kind !== "speed") events.value.push({ ...ev, ts: undefined });
    // paquetes entre puestos: encargos al modelo local, arranques y entregas
    const t = live.tasks[ev.task_id];
    if (!t || !office) return;
    const me = `a${t.agent_id}`;
    if (ev.kind === "delegate") office.packet(me, "rack", LOCAL);
    if (ev.kind === "tool" && String(ev.text).startsWith("mcp__local__")) office.packet(me, "rack", LOCAL);
    if (ev.kind === "status" && ev.text === "running") {
      const from = t.plan_id && live.plans[t.plan_id]?.director_agent_id && t.kind !== "director" ? `a${live.plans[t.plan_id].director_agent_id}` : "you";
      office.packet(from, me, YOU);
    }
    if (ev.kind === "status" && ["review", "done"].includes(ev.text)) office.packet(me, "you", agentColor(live.agents.find((a) => a.id === t.agent_id)));
  });
});
onUnmounted(() => {
  clearInterval(clock);
  clearInterval(resTimer);
  offEvents?.();
  office?.dispose();
  office = null;
});
const webglError = ref("");

function syncScene() {
  if (!office) return;
  office.setStations(specs.value);
  for (const a of shown.value) office.setState(`a${a.id}`, stateOf(a));
  office.setState("you", live.inbox.length ? "waiting" : "idle");
  office.pending = live.inbox.length > 0;
  office.setRackVisible(localOn.value);
  office.selected = sel.value;
}
watch(() => [specs.value.map((s) => `${s.id}${s.color}${s.kind}`).join(), live.inbox.length, sel.value, localOn.value,
  shown.value.map((a) => stateOf(a)).join()], syncScene);
watch(() => [missionTitle.value, JSON.stringify(steps.value.map((s) => [s.label, s.who, s.state])), progress.value],
  () => office?.drawBoard(missionTitle.value, steps.value, progress.value), { immediate: true, flush: "post" });
watch(worktrees, (w) => office?.drawGit(w.map((x) => ({ name: x.branch, status: wtState(x) }))));
watch(() => [gpus.value, live.local.state, tpsNow.value > 0], () =>
  office?.setGpu(gpus.value.map(gpuFrac), Math.max(0, ...gpus.value.map((g) => (g.util ?? 0) / 100)), live.local.state));
</script>

<template>
  <div class="office">
    <!-- izquierda: misión + bandeja -->
    <aside class="col">
      <section class="card pad mission">
        <h3 class="card-title">
          Misión <em>{{ curKey ? duration(missionEnd - missionStart) : "" }}</em>
        </h3>
        <div class="msel">
          <select v-model="chosen" class="input" title="Misión" :disabled="!missions.length">
            <option :value="null">Seguir la actual{{ autoKey ? ` (#${autoKey.slice(1)})` : "" }}</option>
            <option v-for="m in missions" :key="m.key" :value="m.key">{{ m.kind === "plan" ? "Plan" : "Tarea" }} #{{ m.id }} · {{ m.title.slice(0, 60) }}</option>
          </select>
          <button class="btn btn--primary btn--small" :class="{ on: composing }" title="Nueva misión" @click="composing = !composing">
            <i class="fa-solid" :class="composing ? 'fa-xmark' : 'fa-plus'" /> Nueva
          </button>
        </div>

        <form v-if="composing || !missions.length" class="compose" @submit.prevent="launch">
          <p v-if="!live.projects.length" class="muted small">
            Primero vincula una carpeta: <RouterLink to="/chat">Chat → Vincular carpeta</RouterLink>.
          </p>
          <div class="two">
            <select v-model="form.project_id" class="input" title="Proyecto">
              <option v-for="p in live.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
            <select v-model="form.agent_id" class="input" title="Agente">
              <option v-for="a in agentsSorted" :key="a.id" :value="a.id">{{ a.name }} · {{ a.provider }}</option>
            </select>
          </div>
          <textarea
            v-model="form.prompt" class="input" rows="3" placeholder="¿Qué hay que hacer? (Enter para ejecutar)"
            @keydown.enter.exact.prevent="launch"
          />
          <p v-if="formError" class="error small">{{ formError }}</p>
          <button class="btn btn--primary" :disabled="sending || !form.prompt.trim() || !form.project_id || !form.agent_id">
            <i class="fa-solid fa-play" /> Ejecutar
          </button>
        </form>

        <template v-if="curKey && !composing">
          <div class="m-title">{{ missionTitle }}</div>
          <div class="m-brief">
            <template v-if="curTask">
              {{ projectName(curTask.project_id) }} · {{ agentName(curTask.agent_id) }}
              <StatusChip :state="statusChip(curTask.status)" :text="STATUS_TEXT[curTask.status] ?? curTask.status" />
              <span v-if="curTask.cost_usd" class="muted">{{ usd(curTask.cost_usd) }}</span>
            </template>
            <template v-else-if="curPlan">
              {{ projectName(curPlan.project_id) }} · plan #{{ curPlan.id }}
              <StatusChip :state="planChip(curPlan.status)" :text="PLAN_TEXT[curPlan.status] ?? curPlan.status" />
            </template>
          </div>
          <div class="m-prog"><span :style="{ width: `${progress * 100}%` }" /></div>
          <div class="steps">
            <div v-for="(s, i) in steps" :key="i" class="step" :class="s.state" :style="{ '--c': s.color }">
              <div class="dot"><i class="fa-solid" :class="s.state === 'wait' ? 'fa-lock' : s.icon" /></div>
              <div class="step__txt"><b>{{ s.label }}</b><small>{{ s.sub ?? s.who }}</small></div>
              <div class="st">
                <i v-if="s.state === 'done'" class="fa-solid fa-check" />
                <i v-else-if="s.state === 'failed'" class="fa-solid fa-xmark" />
                <template v-else-if="s.state === 'wait'">espera</template>
                <template v-else-if="s.state === 'active'">en curso</template>
              </div>
            </div>
          </div>
          <div class="m-acts">
            <RouterLink v-if="curTask" class="btn btn--small" :to="`/chat/${curTask.id}`"><i class="fa-solid fa-comments" /> Abrir chat</RouterLink>
            <RouterLink v-if="curPlan" class="btn btn--small" :to="`/planes/${curPlan.id}`"><i class="fa-solid fa-diagram-project" /> Ver plan</RouterLink>
            <button v-if="curTask?.status === 'running' || (curPlan && ['planning', 'running'].includes(curPlan.status))" class="btn btn--small btn--danger" @click="stopMission">
              <i class="fa-solid fa-stop" /> Parar
            </button>
          </div>
        </template>
      </section>

      <section class="card pad grow">
        <h3 class="card-title">Bandeja de aprobaciones <em>{{ live.inbox.length }} pendiente{{ live.inbox.length === 1 ? "" : "s" }}</em></h3>
        <p v-if="actError" class="error small">{{ actError }}</p>
        <div v-if="!live.inbox.length" class="empty-box">
          <i class="fa-regular fa-circle-check" />
          Sin aprobaciones pendientes.<br>Lo de riesgo bajo lo resuelven solos los agentes.
        </div>
        <div v-for="i in live.inbox" :key="keyOf(i)" class="ask">
          <div class="ask-h">
            <span class="from"><i :style="{ background: agentColor(fromOf(i)) }" />{{ fromOf(i)?.name ?? "Agente" }} solicita</span>
            <span class="risk" :class="`risk-${riskOf(i)}`">{{ i.level }} · riesgo {{ riskOf(i) }}</span>
          </div>
          <h4>{{ INBOX_TEXT[i.type] ?? i.type }}: {{ i.title }}</h4>
          <ul v-if="i.reasons.length"><li v-for="r in i.reasons.slice(0, 4)" :key="r">{{ r }}</li></ul>
          <div class="ask-actions">
            <button
              v-for="c in choices(i)" :key="c.label" class="btn btn--small" :class="`btn--${c.tone}`"
              :disabled="acting === keyOf(i)" @click="decide(i, c)"
            ><i class="fa-solid" :class="c.icon" /> {{ c.label }}</button>
            <button class="btn btn--small" title="Ver la misión y su diff" @click="showInbox(i)"><i class="fa-solid fa-code-compare" /> Ver</button>
          </div>
        </div>
        <div v-for="(h, k) in history" :key="k" class="hist">
          <i class="fa-solid" :class="h.ok ? 'fa-circle-check ok' : 'fa-circle-xmark no'" />
          <span>{{ h.label }}: {{ h.title }}</span>
        </div>
      </section>
    </aside>

    <!-- centro: oficina 3D + dock -->
    <main class="stage">
      <div ref="host" class="viewport">
        <div ref="labelsEl" class="labels">
          <div v-for="s in specs" :key="s.id" class="lbl" :data-lbl="s.id" :style="{ '--c': s.color }">
            <div class="bubble" :class="{ off: !bubbleOf(s.id) }">{{ bubbleOf(s.id) }}</div>
            <button class="plate" :class="{ sel: sel === s.id }" @click="pick(s.id)">
              <span class="lv"><i class="fa-solid" :class="ICON[s.kind]" /></span>
              <span class="nm">{{ s.name }}<small :class="stateText(s.id).cls">{{ stateText(s.id).text }}</small></span>
              <span v-if="agentOf(s.id)" class="pdot" :class="`pdot--${agentOf(s.id)!.provider}`" :title="PROVIDER_TEXT[agentOf(s.id)!.provider] ?? agentOf(s.id)!.provider" />
            </button>
          </div>
          <div v-if="localOn" class="lbl" data-lbl="rack">
            <button class="tag tag--btn" @click="pick('rack')">
              <i class="fa-solid fa-server" /> Modelo local · {{ live.local.model ?? LOCAL_TEXT[live.local.state] ?? live.local.state }}
            </button>
          </div>
          <div class="lbl" data-lbl="wb"><span class="tag">Misión</span></div>
          <div class="lbl" data-lbl="git"><span class="tag">Worktrees</span></div>
        </div>
        <div class="views">
          <button :class="{ on: view === 'iso' }" @click="goView('iso')"><i class="fa-solid fa-border-all" /> Vista general</button>
          <button v-for="s in specs" :key="s.id" :class="{ on: view === s.id }" :style="{ '--c': s.color }" @click="goView(s.id)">
            <i class="d" />{{ s.name }}
          </button>
          <button v-if="localOn" :class="{ on: view === 'rack' }" :style="{ '--c': LOCAL }" @click="goView('rack')"><i class="d" />Modelo local</button>
          <span class="sep" />
          <button :class="{ on: !locked }" :title="locked ? 'Desbloquear: arrastra los puestos para moverlos' : 'Arrastra un puesto para moverlo. Pulsa para bloquear.'" @click="locked = !locked">
            <i class="fa-solid" :class="locked ? 'fa-lock' : 'fa-up-down-left-right'" /> {{ locked ? "Bloqueado" : "Mover" }}
          </button>
          <button v-if="Object.keys(layout).length" title="Volver a la colocación por defecto" @click="resetLayout"><i class="fa-solid fa-rotate-left" /></button>
        </div>
        <div v-if="away.length || hidden.length" class="more">
          <template v-if="hidden.length">{{ hidden.length }} sin puesto (caben {{ MAX_STATIONS }}) · </template>
          <span>Fuera de la oficina:</span>
          <button v-for="a in away" :key="a.id" class="away" :class="{ 'away--off': isOff(a) }" :style="{ '--c': agentColor(a) }"
                  :title="isOff(a) ? `${a.name} está fuera de servicio: pulsa para volver a ponerlo a trabajar` : `Llamar a ${a.name} a la oficina`" @click="callIn(a.id)">
            <i class="d" />{{ a.name }}<small v-if="isOff(a)"> · fuera de servicio</small>
          </button>
        </div>
        <p v-if="webglError" class="more more--err">No se puede dibujar la oficina 3D: {{ webglError }}</p>
        <p v-else-if="live.agents.length && !shown.length && !webglError" class="hint">
          <i class="fa-solid fa-door-open" /> La oficina está vacía: los agentes entran cuando les encargas algo
          (Misión → Nueva) o cuando los llamas desde abajo.
        </p>
        <p v-if="!live.agents.length" class="hint">
          <i class="fa-solid fa-user-plus" /> Aún no hay agentes. Créalos en <RouterLink to="/ajustes">Ajustes</RouterLink> o en
          <RouterLink to="/modelos">Modelos locales</RouterLink>.
        </p>
      </div>
      <OfficeDock ref="dock" :events="events" :review="review" :review-title="diffTask ? `#${diffTask.id} ${diffTask.title}` : ''" />
    </main>

    <!-- derecha: recursos + inspector -->
    <aside class="col">
      <section class="card pad">
        <h3 class="card-title">Recursos <em>en vivo</em></h3>
        <div v-for="g in gpus" :key="g.index" class="res-row">
          <div class="l">GPU {{ g.index }} <span>{{ ((g.mem_used_mb ?? 0) / 1024).toFixed(1) }}/{{ ((g.mem_total_mb ?? 0) / 1024).toFixed(0) }} GB · {{ g.util ?? "—" }} % · {{ g.temp ?? "—" }} °C</span></div>
          <span class="meter" :title="g.name"><span :style="{ width: `${gpuFrac(g) * 100}%`, background: gpuColor(gpuFrac(g)) }" /></span>
        </div>
        <div v-if="!gpus.length" class="res-row"><div class="l">GPU <span>sin datos (nvidia-smi no encontrado)</span></div></div>
        <div class="res-row">
          <div class="l">Modelo local <span :class="`ls-${live.local.state}`">{{ LOCAL_TEXT[live.local.state] ?? live.local.state }}</span></div>
          <div class="sub">
            <span class="mono">{{ live.local.model ?? "—" }}</span>
            <RouterLink to="/modelos" class="small">{{ live.local.state === "off" ? "Arrancar" : "Modelos" }} →</RouterLink>
          </div>
        </div>
        <div class="res-row">
          <div class="l">Claude · ventana 5 h <span>{{ pct(live.limit?.five_hour) }}</span></div>
          <span class="meter"><span :style="{ width: `${(live.limit?.five_hour ?? 0) * 100}%`, background: '#f97316' }" /></span>
        </div>
        <div class="res-row">
          <div class="l">Claude · semana <span>{{ pct(live.limit?.seven_day) }}</span></div>
          <span class="meter"><span :style="{ width: `${(live.limit?.seven_day ?? 0) * 100}%`, background: '#fb923c' }" /></span>
        </div>
        <div class="l">Tokens/s (local) <span class="mono">{{ tpsNow ? tps(tpsNow) : live.lastSpeed?.tps ? `último ${tps(live.lastSpeed.tps)}` : "0" }}</span></div>
        <canvas ref="spark" class="spark" width="300" height="38" />
        <div class="kv">
          <div><b>{{ tasks.filter((t) => t.status === "running").length }}</b><span>Trabajando</span></div>
          <div title="Equivalente en API: con la suscripción no se paga aparte"><b>{{ usd(weekCost) }}</b><span>Coste 7 días</span></div>
        </div>
        <h3 class="card-title wt-title">Worktrees git <em>{{ worktrees.length }}</em></h3>
        <div class="chips">
          <span class="pill"><i class="fa-solid fa-code-branch" />main</span>
          <button
            v-for="w in worktrees" :key="`${w.kind}${w.id}`" class="pill" :class="{ 'pill--active': wtState(w) === 'active', 'pill--ok': wtState(w) === 'ready' }"
            :title="`${w.project} · ${w.status}`" @click="chosen = `${w.kind === 'plan' ? 'p' : 't'}${w.id}`"
          ><i class="fa-solid fa-code-branch" />{{ w.branch.replace("localharness/", "") }}</button>
        </div>
      </section>

      <section class="card pad grow insp">
        <!-- Tú -->
        <template v-if="sel === 'you'">
          <h3 class="card-title">Inspector <em>{{ live.inbox.length ? "ESPERA DECISIÓN" : "AL MANDO" }}</em></h3>
          <div class="insp-h">
            <div class="avatar" :style="{ '--c': YOU }"><i class="fa-solid fa-crown" /></div>
            <div><b>Tú</b><small>Director · aprobaciones</small></div>
            <span class="prov prov--human">Humano</span>
          </div>
          <p class="small muted">Apruebas los cambios importantes, integras en tu rama y haces el push a mano. Los agentes nunca hacen push.</p>
          <div class="kv">
            <div><b>{{ live.inbox.length }}</b><span>Pendientes</span></div>
            <div><b>{{ live.agents.length }}</b><span>Agentes</span></div>
          </div>
          <button class="btn btn--small wide" @click="composing = true"><i class="fa-solid fa-plus" /> Nueva misión</button>
        </template>

        <!-- el modelo local -->
        <template v-else-if="sel === 'rack'">
          <h3 class="card-title">Inspector <em>{{ (LOCAL_TEXT[live.local.state] ?? live.local.state).toUpperCase() }}</em></h3>
          <div class="insp-h">
            <div class="avatar" :style="{ '--c': LOCAL }"><i class="fa-solid fa-server" /></div>
            <div><b>Modelo local</b><small>llama-server · GPU</small></div>
            <span class="prov prov--local">Gratis</span>
          </div>
          <div class="res-row"><div class="l">Arrancado <span>{{ live.local.model ?? "ninguno" }}</span></div></div>
          <div class="res-row"><div class="l">Última velocidad <span>{{ live.lastSpeed?.tps ? tps(live.lastSpeed.tps) : "—" }}</span></div></div>
          <p class="small muted">
            Responde a los agentes locales y hace los encargos de los agentes Claude con «Puede delegar en el modelo local»:
            {{ delegators.length ? delegators.join(", ") : "ninguno todavía" }}.
          </p>
          <RouterLink class="btn btn--small wide" to="/modelos"><i class="fa-solid fa-microchip" /> Modelos locales</RouterLink>
        </template>

        <!-- un agente -->
        <template v-else-if="selAgent && agentStats">
          <h3 class="card-title">Inspector <em>{{ stateOf(selAgent) === "working" ? "TRABAJANDO" : stateOf(selAgent) === "waiting" ? "ESPERA DECISIÓN" : "LIBRE" }}</em></h3>
          <div class="insp-h">
            <div class="avatar" :style="{ '--c': agentColor(selAgent) }"><i class="fa-solid" :class="ICON[kindOf(selAgent)]" /></div>
            <div><b>{{ selAgent.name }}</b><small>{{ ROLE_TEXT[selAgent.role ?? ""] ?? selAgent.role ?? "sin rol" }}</small></div>
            <span class="prov" :class="`prov--${selAgent.provider}`">{{ PROVIDER_TEXT[selAgent.provider] ?? selAgent.provider }}</span>
          </div>
          <p v-if="selAgent.config.description" class="small muted desc">{{ selAgent.config.description }}</p>
          <div class="res-row"><div class="l">Modelo <span>{{ modelText(selAgent) }}</span></div></div>
          <div v-if="agentStats.run" class="doing">
            <b>{{ agentStats.run.title }}</b>
            <span>{{ describeActivity(live.activity[agentStats.run.id]) }}</span>
            <span v-if="live.speed[agentStats.run.id]" class="small">⚡ {{ speedText(live.speed[agentStats.run.id]) }}</span>
            <span class="small muted">rama {{ agentStats.run.branch ?? "—" }} · lleva {{ duration(now - parseTs(agentStats.run.created_at)) }}</span>
          </div>
          <div class="kv">
            <div><b>{{ agentStats.count }}</b><span>Tareas</span></div>
            <div><b>{{ usd(agentStats.cost) }}</b><span>Coste total</span></div>
          </div>
          <div class="sect">Skills</div>
          <div class="chips">
            <span v-for="s in selAgent.config.skills ?? []" :key="s" class="pill"><i class="fa-solid fa-bolt" />{{ s }}</span>
            <span v-if="!(selAgent.config.skills ?? []).length" class="small muted">ninguna</span>
          </div>
          <div class="sect">Herramientas</div>
          <div class="chips">
            <span v-for="t in tools(selAgent)" :key="t.text" class="pill" :class="t.cls"><i class="fa-solid" :class="t.icon" />{{ t.text }}</span>
          </div>
          <div v-if="agentStats.run && live.thinking[agentStats.run.id]" class="think">
            <button class="think__btn" :class="{ open: thinkOpen }" @click="thinkOpen = !thinkOpen">
              <b>💭 {{ live.thinking[agentStats.run.id].live ? "pensando ahora" : "último pensamiento" }}</b>
              {{ thinkOpen ? live.thinking[agentStats.run.id].text : tail(live.thinking[agentStats.run.id].text) }}
            </button>
          </div>
          <div class="row btns">
            <button class="btn btn--small" :disabled="locked" title="Girar el puesto un cuarto de vuelta" @click="office?.rotate(sel)"><i class="fa-solid fa-rotate-right" /> Girar</button>
            <button class="btn btn--small btn--danger" :disabled="removing" title="Fuera de servicio: sale de la oficina y no recibe trabajo" @click="dismiss(selAgent)">
              <i class="fa-solid fa-person-walking-arrow-right" /> Quitar de la oficina
            </button>
          </div>
          <p v-if="!locked" class="small muted">Arrastra su puesto en la oficina para recolocarlo.</p>
          <div class="row btns">
            <button class="btn btn--small" @click="openCatalog('agents', selAgent.id)"><i class="fa-solid fa-boxes-stacked" /> Asignar</button>
            <button v-if="agentStats.last" class="btn btn--small" @click="router.push(`/chat/${agentStats.last.id}`)"><i class="fa-solid fa-comments" /> Chat</button>
          </div>
          <form class="nudge" @submit.prevent="sendNudge">
            <input
              v-model="nudge" class="input" :disabled="nudgeTarget?.kind === 'busy'"
              :placeholder="nudgeTarget?.kind === 'busy' ? `${selAgent.name} está trabajando…` : `Instrucción directa a ${selAgent.name}…`"
            >
            <button class="btn btn--primary btn--small" :disabled="!nudge.trim() || nudgeTarget?.kind === 'busy'" title="Enviar"><i class="fa-solid fa-paper-plane" /></button>
          </form>
          <p class="small muted">
            <template v-if="nudgeTarget?.kind === 'reply'">Sigue la conversación #{{ nudgeTarget.task.id }} «{{ nudgeTarget.task.title }}».</template>
            <template v-else-if="nudgeTarget?.kind === 'new'">Nueva tarea en {{ nudgeTarget.project ? projectName(nudgeTarget.project) : "(sin proyecto)" }}.</template>
          </p>
          <p v-if="nudgeError" class="error small">{{ nudgeError }}</p>
        </template>
      </section>
    </aside>
  </div>
</template>

<style scoped>
.office {
  --colw: 330px;
  height: 100%;
  display: grid;
  grid-template-columns: var(--colw) minmax(0, 1fr) var(--colw);
  gap: 12px;
  min-height: 0;
}
.col {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  min-width: 0;
}
.pad {
  padding: 14px;
}
.grow {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.mission {
  max-height: 62%;
  overflow: auto;
  flex-shrink: 0;
}
.msel {
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
}
.msel select {
  flex: 1;
  min-width: 0;
  font-weight: 600;
}
.compose {
  display: grid;
  gap: 8px;
  margin-bottom: 10px;
}
.compose .two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}
.compose textarea {
  resize: vertical;
}
.m-title {
  font-weight: 800;
  font-size: 15px;
  letter-spacing: -0.01em;
  overflow-wrap: anywhere;
}
.m-brief {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  color: var(--ink-dim);
  margin: 2px 0 10px;
  font-size: 12.5px;
}
.m-prog {
  height: 8px;
  background: var(--meter);
  border-radius: 9px;
  overflow: hidden;
  margin-bottom: 12px;
}
.m-prog span {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
  transition: width 0.4s;
  border-radius: 9px;
}
.steps {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.step {
  display: grid;
  grid-template-columns: 26px 1fr auto;
  gap: 9px;
  align-items: center;
  padding: 6px;
  border-radius: 12px;
  opacity: 0.55;
}
.step .dot {
  width: 26px;
  height: 26px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  font-size: 11px;
  color: #fff;
  background: var(--c);
  filter: saturate(0.5) brightness(1.1);
}
.step__txt {
  min-width: 0;
}
.step b {
  display: block;
  font-weight: 700;
  font-size: 12.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.step small {
  display: block;
  color: var(--ink-faint);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.step .st {
  font-size: 11px;
  color: var(--ink-faint);
}
.step.done,
.step.failed {
  opacity: 1;
}
.step.done .dot {
  filter: none;
  opacity: 0.85;
}
.step.done .st {
  color: var(--ok);
}
.step.failed .st {
  color: var(--crit);
}
.step.active,
.step.wait {
  opacity: 1;
  background: color-mix(in srgb, var(--c) 12%, var(--panel));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--c) 30%, transparent);
}
.step.active .dot {
  filter: none;
  animation: pulse 1.6s infinite;
}
.step.wait .dot {
  filter: none;
  background: #f59e0b;
}
.step.wait .st {
  color: var(--warn);
  font-weight: 700;
}
@keyframes pulse {
  50% {
    transform: scale(1.12);
  }
}
.m-acts {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 10px;
}

/* bandeja */
.empty-box {
  border: 1.5px dashed var(--line);
  border-radius: 14px;
  padding: 16px;
  text-align: center;
  color: var(--ink-faint);
  font-size: 12px;
  line-height: 1.5;
}
.empty-box i {
  display: block;
  font-size: 20px;
  margin-bottom: 6px;
}
.ask {
  border: 1.5px solid #fcd34d;
  background: linear-gradient(180deg, var(--warn-weak), var(--panel));
  border-radius: 16px;
  padding: 12px;
  margin-bottom: 10px;
  animation: pop 0.35s cubic-bezier(0.2, 1.4, 0.4, 1);
}
@keyframes pop {
  from {
    transform: scale(0.92);
    opacity: 0;
  }
}
.ask-h {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.from {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 700;
  color: var(--ink-dim);
}
.from i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.risk {
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  padding: 2px 7px;
  border-radius: 99px;
  white-space: nowrap;
}
.risk-bajo {
  background: #dcfce7;
  color: #15803d;
}
.risk-medio {
  background: #fef3c7;
  color: #b45309;
}
.risk-alto {
  background: #ffe4e6;
  color: #be123c;
}
.ask h4 {
  font-size: 13px;
  font-weight: 800;
  margin-bottom: 6px;
  overflow-wrap: anywhere;
}
.ask ul {
  margin: 0 0 8px;
  padding-left: 16px;
  color: var(--ink-dim);
  font-size: 12px;
}
.ask-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.hist {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 2px;
  font-size: 11.5px;
  color: var(--ink-dim);
  border-top: 1px solid var(--line);
}
.hist .ok {
  color: var(--ok);
}
.hist .no {
  color: var(--crit);
}

/* escenario */
.stage {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  border-radius: 22px;
  overflow: hidden;
  border: 1px solid var(--line);
  box-shadow: 0 12px 30px -16px rgba(15, 23, 42, 0.25);
  background: linear-gradient(180deg, #a7b5c4 0%, #c9cdcb 52%, #d4c9b6 100%);
}
.viewport {
  flex: 1;
  position: relative;
  min-height: 0;
  overflow: hidden;
}
.viewport :deep(canvas) {
  display: block;
  width: 100%;
  height: 100%;
  cursor: grab;
}
.viewport :deep(canvas:active) {
  cursor: grabbing;
}
.labels {
  position: absolute;
  z-index: 1;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}
.lbl {
  position: absolute;
  left: 0;
  top: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  will-change: transform;
}
.bubble {
  max-width: 230px;
  background: rgba(238, 235, 228, 0.97);
  border: 1px solid #cbc6ba;
  border-radius: 14px 14px 14px 4px;
  padding: 5px 9px;
  font-size: 11px;
  font-weight: 600;
  color: #4a505c;
  box-shadow: 0 8px 18px -8px rgba(15, 23, 42, 0.3);
  text-align: center;
  line-height: 1.3;
  transition: opacity 0.25s, transform 0.25s;
  overflow-wrap: anywhere;
}
.bubble.off {
  opacity: 0;
  transform: translateY(6px);
}
.plate {
  pointer-events: auto;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 7px;
  background: rgba(238, 235, 228, 0.97);
  border: 1.5px solid color-mix(in srgb, var(--c) 40%, #eeebe4);
  border-radius: 13px;
  padding: 4px 9px 4px 5px;
  box-shadow: 0 8px 18px -10px rgba(15, 23, 42, 0.45);
  transition: transform 0.15s;
  color: #1e232d;
  font: inherit;
}
.plate:hover {
  transform: scale(1.05);
}
.plate.sel {
  border-color: var(--c);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--c) 22%, transparent), 0 8px 18px -10px rgba(15, 23, 42, 0.45);
}
.plate .lv {
  background: var(--c);
  color: #fff;
  font-size: 10px;
  border-radius: 8px;
  padding: 4px 6px;
}
.plate .nm {
  font-weight: 800;
  font-size: 12px;
  line-height: 1.1;
  text-align: left;
}
.plate .nm small {
  display: block;
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: #868b96;
}
.plate .nm small.working {
  color: var(--c);
}
.plate .nm small.waiting {
  color: #d97706;
}
.pdot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
}
.pdot--claude {
  background: #ea580c;
}
.pdot--local {
  background: #0284c7;
}
.tag {
  pointer-events: none;
  background: rgba(15, 23, 42, 0.78);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 99px;
  border: 0;
  font-family: inherit;
}
.tag--btn {
  pointer-events: auto;
  cursor: pointer;
  text-transform: none;
  letter-spacing: 0;
  font-size: 11px;
}
.views {
  position: absolute;
  z-index: 5;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 4px;
  padding: 4px;
  border-radius: 14px;
  background: rgba(236, 233, 225, 0.92);
  backdrop-filter: blur(8px);
  border: 1px solid #cbc6ba;
  box-shadow: 0 8px 18px -10px rgba(15, 23, 42, 0.35);
  max-width: 96%;
  overflow-x: auto;
}
.views .sep {
  width: 1px;
  margin: 4px 2px;
  background: #cbc6ba;
}
.away--off {
  opacity: 0.6;
  text-decoration: line-through dotted;
}
.away small {
  font-size: 11px;
}
.think__btn {
  display: block;
  width: 100%;
  margin: 6px 0;
  padding: 6px 9px;
  border: 1px dashed var(--line-strong, #cbc6ba);
  border-radius: 8px;
  background: var(--panel-raised);
  color: var(--ink-dim);
  font: inherit;
  font-size: 12px;
  text-align: left;
  white-space: pre-wrap;
  cursor: pointer;
}
.think__btn.open {
  max-height: 280px;
  overflow: auto;
}
.think__btn b {
  display: block;
  color: var(--ink-faint);
}
.views button {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 0;
  border-radius: 10px;
  background: none;
  color: #4a505c;
  font-weight: 700;
  font-size: 11.5px;
  white-space: nowrap;
  cursor: pointer;
}
.views button:hover {
  background: #d6d2c8;
}
.views button.on {
  background: #1e232d;
  color: #fff;
}
.views i.d {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--c, #94a3b8);
}
.more,
.hint {
  position: absolute;
  z-index: 5;
  left: 12px;
  bottom: 10px;
  margin: 0;
  padding: 5px 10px;
  border-radius: 10px;
  background: rgba(236, 233, 225, 0.92);
  color: #4a505c;
  font-size: 11.5px;
  font-weight: 600;
}
.more {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  max-width: calc(100% - 24px);
}
.away {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border: 1px solid #cbc6ba;
  border-radius: 99px;
  background: #eeebe4;
  color: #1e232d;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}
.away:hover {
  background: #d6d2c8;
}
.away i.d {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--c);
}
.more--err {
  color: #be123c;
  bottom: 40px;
}
.hint {
  left: 50%;
  bottom: 50%;
  transform: translate(-50%, 50%);
  font-size: 13px;
  padding: 10px 14px;
}

/* recursos */
.res-row {
  margin-bottom: 10px;
}
.l {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-weight: 700;
  font-size: 12px;
  margin-bottom: 4px;
}
.l span {
  color: var(--ink-faint);
  font-weight: 600;
  font-family: var(--font-mono);
  font-size: 11px;
  text-align: right;
  overflow-wrap: anywhere;
}
.l span.ls-ready {
  color: var(--ok);
}
.l span.ls-loading {
  color: var(--warn);
}
.sub {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 11.5px;
  color: var(--ink-dim);
}
.spark {
  width: 100%;
  height: 38px;
  display: block;
  margin-top: 4px;
}
.kv {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin: 10px 0;
}
.kv div {
  background: var(--panel-raised);
  border-radius: 12px;
  padding: 8px 10px;
}
.kv b {
  display: block;
  font-size: 15px;
  font-weight: 800;
}
.kv span {
  font-size: 10.5px;
  color: var(--ink-faint);
  font-weight: 600;
}
.wt-title {
  margin-top: 4px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
button.pill {
  cursor: pointer;
}

/* inspector */
.insp-h {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 10px;
}
.insp-h b {
  display: block;
  font-size: 15px;
  font-weight: 800;
}
.insp-h small {
  color: var(--ink-dim);
  font-weight: 600;
}
.insp-h .prov {
  margin-left: auto;
}
.avatar {
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  border-radius: 14px;
  display: grid;
  place-items: center;
  font-size: 19px;
  color: #fff;
  background: var(--c);
  box-shadow: 0 8px 16px -8px var(--c);
}
.desc {
  margin: 0 0 10px;
}
.doing {
  display: grid;
  gap: 2px;
  padding: 8px 10px;
  border-radius: 12px;
  background: var(--accent-weak);
  font-size: 12px;
  margin-bottom: 4px;
}
.sect {
  font-weight: 800;
  font-size: 11px;
  color: var(--ink-faint);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  margin: 10px 0 6px;
}
.btns {
  margin: 12px 0 10px;
}
.wide {
  width: 100%;
  margin-top: 8px;
}
.nudge {
  display: flex;
  gap: 6px;
}
.nudge input {
  flex: 1;
  min-width: 0;
}
.nudge + p {
  margin: 6px 0 0;
}

@media (max-width: 1280px) {
  .office {
    --colw: 280px;
  }
}
@media (max-width: 980px) {
  .office {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: 60vh auto auto;
    height: auto;
  }
  .stage {
    order: -1;
    min-height: 60vh;
  }
  .mission {
    max-height: none;
  }
}
</style>
