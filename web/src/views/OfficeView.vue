<script setup lang="ts">
// Oficina (sustituye al Inicio): la oficina 3D con un puesto por agente real, la misión seleccionada (tarea o
// plan) con sus pasos, la bandeja de aprobaciones, recursos (GPU, modelo local, plan de Claude, tok/s, worktrees),
// el inspector del agente elegido y abajo Timeline / Terminal / Diff. Nada simulado: todo sale de la API.
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import StatusChip from "../components/StatusChip.vue";
import LocalWorkerPanel from "../office/LocalWorkerPanel.vue";
import OfficeDock from "../office/OfficeDock.vue";
import { MAX_STATIONS, Office, type BoardStep, type GitRow, type Placement, type RackSpec, type StationKind, type StationSpec, type StationState } from "../office/office3d";
import {
  PLAN_TEXT, PROVIDER_TEXT, ROLE_TEXT, STATUS_TEXT, agentColor, agentName, api, describeActivity, duration, live,
  modelText, onTaskEvent, openCatalog, putTask, openWizard, parseTs, pct, planChip, planList, post, projectName, refreshAll, speedText,
  statusChip, tps, ui, usd, refreshLocals, SERVER_ROLE_LABEL, agentIcon,
  type Agent, type Gpu, type InboxItem, type Review, type Task, type TaskEvent, type Worktree,
} from "../api";

const router = useRouter();
const YOU = "#eab308";
const LOCAL = "#0ea5e9";
const LOCAL_COLORS = [LOCAL, "#10b981", "#a855f7", "#f97316"]; // un color por modelo local (por servidor)

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
// los agentes a medida son de UNA tarea: están mientras esa tarea sigue abierta; cerrada (integrada o descartada), se van
const CLOSED = ["merged", "rejected", "discarded", "cancelled", "failed", "timeout", "interrupted"];
const generatedOpen = (a: Agent) => mine(a.id).some((t) => !CLOSED.includes(t.status)) || mine(a.id).length === 0;
const present = computed(() => agentsSorted.value.filter((a) => runningOf(a.id) || waitingOf(a.id) ||
  (!isOff(a) && (summoned.value.has(a.id) ||
    (a.config.generated ? generatedOpen(a) : now.value - lastSeen(a.id) < PRESENCE_MS)))));
const shown = computed(() => present.value.slice(0, MAX_STATIONS));
const hidden = computed(() => present.value.slice(MAX_STATIONS));
const kindOf = (a: Agent): StationKind =>
  (["director", "jefe", "trabajador", "consultas"].includes(a.role ?? "") ? a.role : "otro") as StationKind;
const ICON: Record<string, string> = {
  you: "fa-crown", director: "fa-chess-king", jefe: "fa-shield-halved", trabajador: "fa-hammer",
  consultas: "fa-magnifying-glass", local: "fa-robot", otro: "fa-user-astronaut",
};
const specs = computed<StationSpec[]>(() => [
  { id: "you", name: "Tú", color: YOU, kind: "you", icon: "f007" },
  ...shown.value.map((a) => ({ id: `a${a.id}`, name: a.name, color: agentColor(a), kind: kindOf(a), icon: agentIcon(a).code })),
  // el trabajador del modelo local entra en cuanto un Claude le encarga algo, con su línea hacia ese Claude
  // con dos GPU, uno por modelo («Local · Fuerte», «Local · Rápido»), cada uno con sus encargos y su directo
  ...workers.value.map((w) => ({ id: wid(w.task.id, w.srv), name: serverLabel(w.srv), color: serverColor(w.srv),
    kind: "local" as StationKind, boss: `a${w.task.agent_id}`, icon: "f2db" })),
]);
const agentOf = (sid: string) => (sid.startsWith("a") ? live.agents.find((a) => `a${a.id}` === sid) : undefined);

const tasks = computed(() => Object.values(live.tasks));
const mine = (aid: number) => tasks.value.filter((t) => t.agent_id === aid).sort((a, b) => b.id - a.id);
const runningOf = (aid: number) => mine(aid).find((t) => t.status === "running");
const waitingOf = (aid: number) => live.inbox.find((i) => i.task_id && live.tasks[i.task_id]?.agent_id === aid);

// ---------- trabajador local: el modelo local trabajando para un Claude que delega (coordinador o «con ayuda»)
const isLocalEv = (e: { kind: string; text: string }) => ["delegate", "worker", "worker_thinking"].includes(e.kind)
  || (e.kind === "tool" && String(e.text).startsWith("mcp__local__"))
  || (e.kind === "progress" && String(e.text).startsWith("Modelo local:"));
// el jefe local (modo 100 % local) reparte a los modelos locales igual que el coordinador Claude
const delegates = (a?: Agent) => !!a && ((a.provider === "claude" && !!(a.config.delegate_local || a.config.coordinator)) || a.provider === "local_boss");
const workerEvents = reactive<Record<number, TaskEvent[]>>({});
// lo que el trabajador local está pensando/escribiendo AHORA (eventos `worker_live`, no se guardan)
interface WorkerLive { tool?: string; task?: string; thinking: string; text: string; done: boolean; at: number; skills?: string[] }
interface WorkerLiveSrv extends WorkerLive { server?: string; tps?: number | null }
const workerLive = reactive<Record<string, WorkerLiveSrv>>({}); // `${tarea}~${servidor}` → lo último de ese modelo
// sin `srv`, el más reciente de la tarea. Uno a medias (no `done`) sigue trabajando aunque no llegue nada nuevo:
// mientras el modelo lee un encargo largo pasan segundos sin que escriba
function liveNow(tid: number, srv?: string): WorkerLiveSrv | null {
  if (live.tasks[tid]?.status !== "running") return null;
  const all = Object.entries(workerLive).filter(([k]) => (srv ? k === `${tid}~${srv}` : k.startsWith(`${tid}~`)))
    .map(([, l]) => l).filter((l) => !l.done && Date.now() / 1000 - l.at < 600);
  return all.sort((a, b) => b.at - a.at)[0] ?? null;
}
// ---------- un trabajador por modelo local (servidor): puesto «w<tarea>~<servidor>»
const defaultServer = computed(() => live.locals[0]?.id ?? "principal");
const wid = (tid: number, srv: string) => `w${tid}~${srv}`;
function parseW(sid: string): { tid: number; srv: string } | null {
  const m = /^w(\d+)(?:~(.+))?$/.exec(sid);
  return m ? { tid: Number(m[1]), srv: m[2] ?? defaultServer.value } : null;
}
const serverOf = (id: string) => live.locals.find((l) => l.id === id);
const serverLabel = (id: string) => (live.locals.length < 2 ? "Trabajador local" : `Local · ${serverOf(id)?.name ?? id}`);
const serverColor = (id: string) => LOCAL_COLORS[Math.max(0, live.locals.findIndex((l) => l.id === id)) % LOCAL_COLORS.length];
// a quién va un encargo sin `server`: lo mismo que decide el servidor MCP por su papel
const LIGHT_TOOLS = ["local_ask", "local_research", "run_checks"];
function guessServer(tool: string): string {
  if (live.locals.length < 2) return defaultServer.value;
  const prefs = LIGHT_TOOLS.some((t) => tool.endsWith(t)) ? ["rapido", "general", "fuerte"] : ["fuerte", "general", "rapido"];
  const on = live.locals.filter((l) => l.state !== "off");
  for (const r of prefs) {
    const l = (on.length ? on : live.locals).find((x) => x.role === r);
    if (l) return l.id;
  }
  return defaultServer.value;
}
/** Servidor de cada evento del trabajador local («*» = de todos: equipar, o un plan que reparte bloques). La llamada
 * de Claude se empareja con la entrada del log que la cierra (misma herramienta y mismo encargo o archivo). */
function eventServers(evs: TaskEvent[]): string[] {
  const used = new Set<number>();
  return evs.map((e, i) => {
    const d = (e.data ?? {}) as Record<string, unknown>;
    if (e.kind === "delegate") {
      const tool = String(d.tool ?? "");
      return tool === "local_execute_plan" || tool === "local_prepare" ? "*" : String(d.server ?? defaultServer.value);
    }
    if (e.kind !== "tool") return d.server ? String(d.server) : "*";
    const tool = String(e.text).replace(/^mcp__local__/, "");
    const inp = (d.input ?? {}) as Record<string, unknown>;
    if (tool === "local_execute_plan" || tool === "local_prepare") return "*";
    if (inp.server) return String(inp.server);
    const key = String(inp.task ?? inp.question ?? inp.command ?? "").slice(0, 300);
    for (let j = i + 1; j < evs.length; j++) {
      const x = evs[j];
      const xd = (x.data ?? {}) as Record<string, unknown>;
      if (used.has(j) || x.kind !== "delegate" || xd.tool !== tool) continue;
      if ((inp.path && xd.path === inp.path) || (!inp.path && String(xd.task ?? "") === key)) {
        used.add(j);
        return String(xd.server ?? defaultServer.value);
      }
    }
    return guessServer(tool);
  });
}
function serverEvents(tid: number, srv: string): TaskEvent[] {
  const evs = workerEvents[tid] ?? [];
  const map = eventServers(evs);
  return evs.filter((_, i) => map[i] === "*" || map[i] === srv);
}
function serversOf(tid: number): string[] {
  const out = new Set<string>();
  eventServers(workerEvents[tid] ?? []).forEach((x) => { if (x !== "*") out.add(x); });
  Object.keys(workerLive).forEach((k) => { if (k.startsWith(`${tid}~`)) out.add(k.slice(String(tid).length + 1)); });
  if (!out.size) out.add(defaultServer.value);
  const pos = (id: string) => { const i = live.locals.findIndex((l) => l.id === id); return i < 0 ? 99 : i; };
  return [...out].sort((a, b) => pos(a) - pos(b));
}
const workerSkills = (tid: number): string[] => {
  const last = [...(workerEvents[tid] ?? [])].reverse().find((e) => e.kind === "worker");
  return (last?.data?.skills as string[] | undefined) ?? liveNow(tid)?.skills ?? [];
};
const workerLoaded = new Set<number>();
// candidatas: tareas de un Claude que delega en marcha, la misión elegida y la tarea del trabajador que miras
const workerCandidates = computed(() => tasks.value.filter((t) => delegates(live.agents.find((a) => a.id === t.agent_id))
  && (t.status === "running" || t.id === curTask.value?.id || sel.value === `w${t.id}`)));
// sale en la oficina cuando ya le han encargado algo (no antes); uno por cada modelo local que haya trabajado
const workers = computed(() => workerCandidates.value
  .filter((t) => workerEvents[t.id]?.some((e) => e.kind !== "progress") || liveNow(t.id))
  .flatMap((t) => serversOf(t.id).map((srv) => ({ task: t, srv }))));
async function loadWorkerEvents() {
  for (const t of workerCandidates.value) {
    if (workerLoaded.has(t.id)) continue;
    workerLoaded.add(t.id);
    const evs = await api<TaskEvent[]>(`/api/tasks/${t.id}/events`).catch(() => [] as TaskEvent[]);
    const live_ = (workerEvents[t.id] ?? []).filter((e) => !evs.some((x) => x.id === e.id));
    workerEvents[t.id] = [...evs.filter(isLocalEv), ...live_];
  }
}
const selW = computed(() => parseW(sel.value));
const selWorker = computed(() => (selW.value ? live.tasks[selW.value.tid] : undefined));
function workerBusy(tid: number, srv?: string): boolean {
  if (srv && serversOf(tid).length > 1) return !!liveNow(tid, srv); // con varios modelos, cada uno por su directo
  let open = 0;
  for (const e of srv ? serverEvents(tid, srv) : workerEvents[tid] ?? []) {
    const tool = String(e.data?.tool ?? "");
    if (e.kind === "tool" && !String(e.text).endsWith("local_prepare")) open++;
    if (e.kind === "delegate" && tool !== "local_prepare" && !tool.includes("/")) open = Math.max(0, open - 1);
  }
  return (open > 0 || !!liveNow(tid)) && live.tasks[tid]?.status === "running";
}
function workerBubble(tid: number, srv: string): string {
  if (live.tasks[tid]?.status !== "running") return "";
  const l = liveNow(tid, srv);
  if (l) return l.text ? `✍️ ${l.text.slice(-70)}` : l.thinking ? `💭 ${l.thinking.slice(-70)}` : "Leyendo el encargo…";
  const last = [...serverEvents(tid, srv)].reverse().find((e) => e.kind === "delegate" || e.kind === "tool" || e.kind === "progress");
  if (!last) return "";
  if (workerBusy(tid, srv)) return last.kind === "progress" ? String(last.text).replace(/^Modelo local:\s*/, "") : "Con un encargo…";
  return "Esperando encargo";
}

function stateOf(a: Agent): StationState {
  if (runningOf(a.id)) return "working";
  return waitingOf(a.id) ? "waiting" : "idle";
}

function bubbleOf(sid: string): string {
  const w = parseW(sid);
  if (w) return workerBubble(w.tid, w.srv);
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
  const w = parseW(sid);
  if (w) {
    const n = workerSkills(w.tid).length;
    const sk = n ? ` · ${n} skill${n > 1 ? "s" : ""}` : "";
    const sp = liveNow(w.tid, w.srv)?.tps;
    return workerBusy(w.tid, w.srv) ? { text: `trabajando${sp ? ` · ${tps(sp)}` : ""}${sk}`, cls: "working" }
      : { text: `para #${w.tid}${sk}`, cls: "" };
  }
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
// ---------- resumen de la misión: el encargo y lo que está haciendo el modelo local, encargo a encargo
const briefOpen = ref(false);
const curAgent = computed(() => (curTask.value ? live.agents.find((a) => a.id === curTask.value!.agent_id) : undefined));
interface LocalJob { key: string; title: string; kind: string; state: "run" | "ok" | "bad"; meta?: string; children: { title: string; ok: boolean }[] }
const LOCAL_KIND: Record<string, string> = { local_ask: "pregunta", local_write_file: "escribe", local_execute_plan: "plan",
  local_agent: "tarea", local_research: "investiga", run_checks: "tests" };
const localJobs = computed<LocalJob[]>(() => {
  const t = curTask.value;
  if (!t) return [];
  const out: LocalJob[] = [];
  for (const e of workerEvents[t.id] ?? []) {
    const d = (e.data ?? {}) as Record<string, unknown>;
    if (e.kind === "tool") {
      const tool = String(e.text).replace(/^mcp__local__/, "");
      if (tool === "local_prepare") continue;
      const inp = (d.input ?? {}) as Record<string, unknown>;
      const blocks = inp.blocks as { title?: string; path?: string }[] | undefined;
      const title = blocks ? `${blocks.length} bloques: ${blocks.map((b) => b.title ?? b.path).join(", ")}`
        : String(inp.task ?? inp.path ?? inp.question ?? inp.command ?? tool);
      out.push({ key: `j${e.id ?? out.length}`, title, kind: LOCAL_KIND[tool] ?? tool, state: "run", children: [] });
    } else if (e.kind === "delegate") {
      const tool = String(d.tool ?? "");
      if (tool === "local_prepare") continue;
      const open = out.find((j) => j.state === "run");
      if (tool.includes("/")) { // un bloque de un plan
        open?.children.push({ title: String(d.task ?? d.path ?? "bloque"), ok: d.ok !== false });
        continue;
      }
      const meta = [d.seconds != null ? `${d.seconds} s` : "", d.completion_tokens ? `${d.completion_tokens} tokens` : ""].filter(Boolean).join(" · ");
      if (open) { open.state = d.ok === false ? "bad" : "ok"; open.meta = d.ok === false ? String(d.error ?? "falló").slice(0, 120) : meta; }
      else out.push({ key: `d${e.id}`, title: String(d.task ?? d.path ?? tool), kind: LOCAL_KIND[tool] ?? tool, state: d.ok === false ? "bad" : "ok", meta, children: [] });
    }
  }
  if (t.status !== "running") out.forEach((j) => { if (j.state === "run") j.state = "bad"; });
  return out;
});
const curLive = computed(() => (curTask.value ? liveNow(curTask.value.id) : null));

// encargos de verdad: sin equipar (local_prepare) ni los bloques sueltos de un plan
const delegations = computed(() => events.value.filter((e) => e.kind === "delegate"
  && !String(e.data?.tool ?? "").includes("/") && e.data?.tool !== "local_prepare").length);
// (aquí y no arriba: usa la misión elegida, que se define más abajo que los puestos)
watch(() => workerCandidates.value.map((t) => t.id).join(), () => loadWorkerEvents().catch(() => {}), { immediate: true });
// cuando el trabajador local entra a trabajar y estabas mirando a su Claude (o a ti), se le enfoca para verlo
const seenWorkers = new Set<number>();
watch(() => workers.value.map((w) => w.task.id).join(), () => {
  for (const { task: t, srv } of workers.value) {
    if (seenWorkers.has(t.id)) continue;
    seenWorkers.add(t.id);
    if (t.status === "running" && (sel.value === `a${t.agent_id}` || sel.value === "you")) setTimeout(() => pick(wid(t.id, srv)), 600);
  }
});


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
// agent_id 0 = «agente a medida»: el diseñador lo crea desde cero para esta petición (designer.py)
const form = reactive({ project_id: null as number | null, agent_id: 0 as number | null, prompt: "" });
const formError = ref("");
const sending = ref(false);
watch(() => [live.projects.length, live.agents.length], () => {
  form.project_id ??= live.projects[0]?.id ?? null;
}, { immediate: true });
// ---------- agente a medida: propuesta del diseñador que puedes retocar antes de lanzar
interface Proposal {
  name: string; description: string; provider: string; model: string | null; coordinator: boolean; read_only: boolean;
  web: boolean; thinking: string; skills: string[]; local_skills: string[]; mcps: string[]; max_turns: number;
  max_budget_usd?: number; instructions: string; reason: string; designed_by: string; design_cost_usd: number;
}
const proposal = ref<Proposal | null>(null);
const designing = ref(false);
async function design() {
  designing.value = true;
  formError.value = "";
  try {
    proposal.value = await post<Proposal>("/api/agents/design", { project_id: form.project_id, prompt: form.prompt.trim() });
  } catch (e) {
    formError.value = (e as Error).message;
  } finally {
    designing.value = false;
  }
}
watch(() => [form.prompt, form.project_id], () => (proposal.value = null)); // otra petición: otro agente
const dropFrom = (key: "skills" | "local_skills" | "mcps", name: string) => {
  if (proposal.value) proposal.value[key] = proposal.value[key].filter((x) => x !== name);
};
async function launch() {
  if (!form.project_id || form.agent_id === null || !form.prompt.trim()) return;
  if (form.agent_id === 0 && !proposal.value) return design();
  sending.value = true;
  formError.value = "";
  try {
    if (form.agent_id === 0 && proposal.value) {
      const a = await post<Agent>("/api/agents/generated", { spec: proposal.value, prompt: form.prompt.trim() });
      await refreshAll();
      form.agent_id = a.id;
    }
    const t = await post<Task>("/api/tasks", { project_id: form.project_id, agent_id: form.agent_id, prompt: form.prompt.trim() });
    putTask(t);
    summoned.value = new Set([...summoned.value, form.agent_id]);
    chosen.value = `t${t.id}`;
    form.prompt = "";
    composing.value = false;
    sel.value = `a${form.agent_id}`;
    if (proposal.value) { proposal.value = null; form.agent_id = 0; }
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
interface SysUsage { cpu_pct: number | null; per_core: number[]; cores: number | null; ram_total_gb: number | null; ram_used_gb: number | null; ram_pct: number | null }
const sys = ref<SysUsage | null>(null);
async function loadResources() {
  const r = await api<{ gpus: Gpu[]; worktrees: Worktree[]; system?: SysUsage }>("/api/resources").catch(() => null);
  if (r) { gpus.value = r.gpus; worktrees.value = r.worktrees; sys.value = r.system ?? null; }
  await refreshLocals().catch(() => undefined); // con dos GPU, dos modelos: el estado de cada uno
}
// estado conjunto de los modelos locales: listo si alguno lo está, si no el del principal
const localState = computed(() => {
  const states = live.locals.map((l) => l.state);
  return states.includes("ready") ? "ready" : states.includes("external") ? "external"
    : states.includes("loading") ? "loading" : live.local.state;
});
const localsOn = computed(() => live.locals.filter((l) => l.state !== "off"));
// una torre por modelo local encendido; sus LEDs siguen la GPU en la que corre (CUDA1 → GPU 1)
const gpuIdx = (device: string) => Number(/(\d+)/.exec(device ?? "")?.[1] ?? 0);
const racks = computed<RackSpec[]>(() => localsOn.value.filter((l) => l.state !== "failed" || l.model).map((l) => ({
  id: l.id, name: l.name, model: l.model ?? (l.state === "loading" ? "cargando…" : "sin modelo"), state: l.state,
  gpu: gpuIdx(l.device), gpuName: gpus.value.find((g) => g.index === gpuIdx(l.device))?.name ?? "", color: serverColor(l.id),
})));
let resTimer: ReturnType<typeof setInterval>;
// los worktrees que importan ahora (trabajando, listos o fallidos), no los cientos ya integrados
const liveTrees = computed(() => worktrees.value.filter((w) => wtState(w) !== "merged" && wtState(w) !== "clean"));
const gpuFrac = (g: Gpu) => (g.mem_used_mb && g.mem_total_mb ? g.mem_used_mb / g.mem_total_mb : 0);
const gpuColor = (v: number) => (v > 0.85 ? "#ef4444" : v > 0.6 ? "#f59e0b" : "#22c55e");
const LOCAL_TEXT: Record<string, string> = { off: "apagado", loading: "cargando…", ready: "listo", failed: "falló al arrancar", external: "arrancado fuera" };

const series = ref<number[]>(new Array(60).fill(0));
// tokens/s de todos los modelos locales que están escribiendo AHORA, sumados (con dos GPU, los dos a la vez), más el
// agente local más rápido (sus eventos `speed` no dicen en qué servidor van)
const workingLocals = computed(() => Object.values(live.localWork).filter((w) => !w.done && now.value - w.at < 4000 && w.tps));
const tpsNow = computed(() => {
  const agents = Object.values(live.speed).filter((s) => s.src !== "worker" && now.value - s.at < 4000).map((s) => s.tps ?? 0);
  return workingLocals.value.reduce((sum, w) => sum + (w.tps ?? 0), 0) + (agents.length ? Math.max(...agents) : 0);
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
  g.strokeStyle = "#2a78d6"; g.lineWidth = 2; g.lineJoin = "round"; g.stroke();
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
      putTask(t);
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
  if (a.provider === "local_agent") {
    out.push({ text: c.read_only ? "lee y busca" : "lee, escribe y ejecuta", cls: "", icon: c.read_only ? "fa-eye" : "fa-pen" });
    if (c.web !== false) out.push({ text: "internet", cls: "pill--active", icon: "fa-globe" });
    return out;
  }
  if (a.provider === "local_boss") return [{ text: "jefe 100 % local", cls: live.local.state === "ready" ? "pill--ok" : "", icon: "fa-user-tie" }];
  if (a.provider !== "claude") return [{ text: "sin herramientas (solo responde)", cls: "", icon: "fa-comment" }];
  out.push({ text: c.read_only ? "solo lectura" : "lee y edita", cls: "", icon: c.read_only ? "fa-eye" : "fa-pen" });
  if (c.delegate_local || c.coordinator) out.push({ text: c.coordinator ? "jefe del local" : "delega en local", cls: live.local.state === "ready" ? "pill--ok" : "", icon: c.coordinator ? "fa-user-tie" : "fa-plug" });
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
let stopFocus: (() => void) | null = null;
// panel de abajo a la izquierda: Misión o Aprobaciones (salta solo a Aprobaciones cuando llega una nueva)
const ltab = ref<"mision" | "bandeja">("mision");
// modo cine de la oficina (se recuerda en este navegador)
const cinema = ref(true);
try { cinema.value = localStorage.getItem("lh-office-cine") !== "0"; } catch { /* sin almacenamiento */ }
watch(cinema, (v) => {
  if (office) office.cinematic = v;
  try { localStorage.setItem("lh-office-cine", v ? "1" : "0"); } catch { /* sin almacenamiento */ }
});
watch(() => live.inbox.length, (n, before) => { if (n > (before ?? 0)) ltab.value = "bandeja"; });
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
    : `¿Quitar a ${a.name} de la oficina?\n\nQueda fuera de servicio: el Director no le encargará nada hasta que lo vuelvas a traer (Catálogo → En la oficina).`;
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
function arrangeLayout() {
  if (!office) return;
  layout.value = office.autoArrange();
  saveLayout();
}
function resetLayout() {
  if (!confirm("¿Volver a colocar todos los puestos en su sitio por defecto?")) return;
  layout.value = {};
  saveLayout();
  location.reload();
}

// ---------- tamaño de los paneles: arrastrar las asas entre columnas y sobre el panel de abajo
const SIZE_DEFAULT = { left: 420, right: 330, dock: 290 }; // left: ancho de Misión/Aprobaciones (abajo)
const sizes = reactive({ ...SIZE_DEFAULT });
try { Object.assign(sizes, JSON.parse(localStorage.getItem("lh-office-sizes-2") ?? "{}")); } catch { /* sin almacenamiento */ }
const officeEl = ref<HTMLElement>();
const drag = ref<{ which: "left" | "right" | "dock"; x: number; y: number; start: number } | null>(null);
function clampSizes() {
  const w = officeEl.value?.clientWidth ?? 1400, h = officeEl.value?.clientHeight ?? 900;
  sizes.right = Math.round(Math.min(Math.max(260, w - 420), Math.max(220, sizes.right))); // la oficina nunca baja de ~400 px
  sizes.left = Math.round(Math.min(Math.max(280, w - sizes.right - 380), Math.max(260, sizes.left)));
  sizes.dock = Math.round(Math.min(h - 160, Math.max(40, sizes.dock)));
}
function saveSizes() {
  try { localStorage.setItem("lh-office-sizes-2", JSON.stringify(sizes)); } catch { /* sin almacenamiento */ }
}
function onDrag(e: PointerEvent) {
  const d = drag.value;
  if (!d) return;
  if (d.which === "left") sizes.left = d.start + (e.clientX - d.x);
  else if (d.which === "right") sizes.right = d.start - (e.clientX - d.x);
  else sizes.dock = d.start - (e.clientY - d.y);
  clampSizes();
}
function endDrag() {
  drag.value = null;
  window.removeEventListener("pointermove", onDrag);
  window.removeEventListener("pointerup", endDrag);
  saveSizes();
}
function startDrag(which: "left" | "right" | "dock", e: PointerEvent) {
  drag.value = { which, x: e.clientX, y: e.clientY, start: sizes[which] };
  window.addEventListener("pointermove", onDrag);
  window.addEventListener("pointerup", endDrag);
  e.preventDefault();
}
function resetSizes(which: "left" | "right" | "dock") {
  sizes[which] = SIZE_DEFAULT[which];
  saveSizes();
}
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
  clampSizes();
  window.addEventListener("resize", clampSizes);
  try {
    office = new Office(host.value!, labelsEl.value!, pick);
    office.movable = !locked.value;
    office.cinematic = cinema.value;
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
  // el asistente de agentes puede crear uno estando ya en la oficina: que entre y se enfoque
  stopFocus = watch(() => ui.focusAgent, (id) => { if (id) { callIn(id); ui.focusAgent = null; } });
  offEvents = onTaskEvent((ev) => {
    if (missionTaskIds.value.has(ev.task_id) && !["speed", "worker_live"].includes(ev.kind)) events.value.push({ ...ev, ts: undefined });
    // paquetes entre puestos: encargos al modelo local, arranques y entregas
    const t = live.tasks[ev.task_id];
    if (!t || !office) return;
    const me = `a${t.agent_id}`;
    if (ev.kind === "worker_live") {
      const d = ev.data as unknown as WorkerLiveSrv;
      const srv = d.server ?? defaultServer.value;
      const k = `${ev.task_id}~${srv}`;
      if ((!workerLive[k] || workerLive[k].done) && !d.done) office.packet(me, wid(t.id, srv), serverColor(srv));
      workerLive[k] = d;
    }
    if (isLocalEv(ev) && (workerEvents[ev.task_id] || delegates(live.agents.find((a) => a.id === t.agent_id)))) {
      workerEvents[ev.task_id] = [...(workerEvents[ev.task_id] ?? []), { ...ev, ts: undefined }];
    }
    // encargo: Claude → trabajador local → GPU (rack); respuesta: trabajador → Claude
    // con varios modelos, el paquete va al puesto del modelo que hace cada encargo
    if (ev.kind === "tool" && String(ev.text).startsWith("mcp__local__")) {
      const tool = String(ev.text).replace(/^mcp__local__/, "");
      const inp = (ev.data?.input ?? {}) as Record<string, unknown>;
      const to = tool === "local_execute_plan" ? serversOf(t.id) : [String(inp.server ?? guessServer(tool))];
      for (const srv of to) setTimeout(() => office?.packet(wid(t.id, srv), `rack:${srv}`, serverColor(srv)), 900);
    }
    if (ev.kind === "delegate") {
      const srv = String(ev.data?.server ?? defaultServer.value);
      const tool = String(ev.data?.tool ?? "");
      if (!tool.includes("/") && tool !== "local_execute_plan" && tool !== "local_prepare") office.packet(wid(t.id, srv), me, serverColor(srv));
    }
    if (ev.kind === "status" && ev.text === "running") {
      const from = t.plan_id && live.plans[t.plan_id]?.director_agent_id && t.kind !== "director" ? `a${live.plans[t.plan_id].director_agent_id}` : "you";
      office.packet(from, me, YOU);
    }
    if (ev.kind === "status" && ["review", "done"].includes(ev.text)) office.packet(me, "you", agentColor(live.agents.find((a) => a.id === t.agent_id)));
  });
});
onUnmounted(() => {
  window.removeEventListener("resize", clampSizes);
  endDrag();
  clearInterval(clock);
  clearInterval(resTimer);
  offEvents?.();
  stopFocus?.();
  office?.dispose();
  office = null;
});
const webglError = ref("");

function syncScene() {
  if (!office) return;
  office.setStations(specs.value);
  for (const a of shown.value) office.setState(`a${a.id}`, stateOf(a));
  for (const w of workers.value) office.setState(wid(w.task.id, w.srv), workerBusy(w.task.id, w.srv) ? "working" : "idle");
  office.setState("you", live.inbox.length ? "waiting" : "idle");
  office.pending = live.inbox.length > 0;
  office.setRacks(racks.value);
  office.selected = sel.value;
}
watch(() => [specs.value.map((s) => `${s.id}${s.color}${s.kind}`).join(), live.inbox.length, sel.value, JSON.stringify(racks.value),
  shown.value.map((a) => stateOf(a)).join(), workers.value.map((w) => `${w.task.id}${w.srv}${workerBusy(w.task.id, w.srv)}`).join()], syncScene);
watch(() => [missionTitle.value, JSON.stringify(steps.value.map((s) => [s.label, s.who, s.state])), progress.value],
  () => office?.drawBoard(missionTitle.value, steps.value, progress.value), { immediate: true, flush: "post" });
watch(worktrees, (w) => office?.drawGit(w.map((x) => ({ name: x.branch, status: wtState(x) }))));
watch(gpus, (list) => {
  const mem: number[] = [], util: number[] = [];
  for (const g of list) { mem[g.index] = gpuFrac(g); util[g.index] = (g.util ?? 0) / 100; }
  office?.setGpu(mem, util);
});
watch(sys, (v) => office?.setSystem((v?.cpu_pct ?? 0) / 100, (v?.ram_pct ?? 0) / 100));
</script>

<template>
  <div ref="officeEl" class="office" :class="{ dragging: !!drag }" :style="{ '--lw': `${sizes.left}px`, '--rw': `${sizes.right}px`, '--dockh': `${sizes.dock}px` }">

    <!-- centro: oficina 3D + dock -->
    <main class="stage">
      <div ref="host" class="viewport">
        <div ref="labelsEl" class="labels">
          <div v-for="s in specs" :key="s.id" class="lbl" :data-lbl="s.id" :style="{ '--c': s.color }">
            <div class="bubble" :class="{ off: !bubbleOf(s.id) }">{{ bubbleOf(s.id) }}</div>
            <button class="plate" :class="{ sel: sel === s.id }" @click="pick(s.id)">
              <span class="lv"><i class="fa-solid" :class="agentOf(s.id) ? `fa-${agentIcon(agentOf(s.id)).name}` : ICON[s.kind]" /></span>
              <span class="nm">{{ s.name }}<small :class="stateText(s.id).cls">{{ stateText(s.id).text }}</small></span>
              <span v-if="agentOf(s.id)" class="pdot" :class="`pdot--${agentOf(s.id)!.provider}`" :title="PROVIDER_TEXT[agentOf(s.id)!.provider] ?? agentOf(s.id)!.provider" />
            </button>
          </div>
          <div v-for="r in racks" :key="r.id" class="lbl" :data-lbl="`rack:${r.id}`">
            <button class="tag tag--btn" :class="{ sel: sel === `rack:${r.id}` }" :style="{ '--c': r.color }" @click="pick(`rack:${r.id}`)">
              <i class="fa-solid fa-server" /> {{ r.name }} · {{ LOCAL_TEXT[r.state] ?? r.state }}
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
          <button v-for="r in racks" :key="r.id" :class="{ on: view === `rack:${r.id}` }" :style="{ '--c': r.color }" @click="goView(`rack:${r.id}`)"><i class="d" />{{ r.name }}</button>
          <span class="sep" />
          <button :class="{ on: !locked }" :title="locked ? 'Desbloquear: arrastra los puestos para moverlos' : 'Arrastra un puesto para moverlo. Pulsa para bloquear.'" @click="locked = !locked">
            <i class="fa-solid" :class="locked ? 'fa-lock' : 'fa-up-down-left-right'" /> {{ locked ? "Bloqueado" : "Mover" }}
          </button>
          <button title="Ordenar: coloca todas las mesas repartidas y separadas, y las torres en fila" @click="arrangeLayout"><i class="fa-solid fa-table-cells" /> Ordenar</button>
          <button v-if="Object.keys(layout).length" title="Volver a la colocación por defecto" @click="resetLayout"><i class="fa-solid fa-rotate-left" /></button>
          <button title="Traer agentes a la oficina desde el Catálogo" @click="openCatalog('agents')"><i class="fa-solid fa-user-plus" /> Agentes</button>
          <button :class="{ on: cinema }" title="Modo cine: si no tocas la oficina en 20 s, la cámara se mueve sola" @click="cinema = !cinema"><i class="fa-solid fa-video" /> Cine</button>
        </div>
        <p v-if="hidden.length" class="more">{{ hidden.length }} sin puesto (caben {{ MAX_STATIONS }})</p>
        <p v-if="webglError" class="more more--err">No se puede dibujar la oficina 3D: {{ webglError }}</p>
        <p v-else-if="live.agents.length && !shown.length && !webglError" class="hint">
          <i class="fa-solid fa-door-open" /> La oficina está vacía: los agentes entran cuando les encargas algo
          (Misión → Nueva) o cuando los traes desde el Catálogo.
        </p>
        <p v-if="!live.agents.length" class="hint">
          <i class="fa-solid fa-boxes-stacked" /> Aún no hay agentes. <a href="#" @click.prevent="openCatalog('agents')">Créalos o tráelos desde el Catálogo</a>.
        </p>
      </div>
      <div class="gutter gutter--h" title="Arrastra para cambiar el alto del panel de abajo (doble clic: por defecto)" @pointerdown="startDrag('dock', $event)" @dblclick="resetSizes('dock')" />
      <div class="bottom">
        <!-- abajo a la izquierda: misión y bandeja de aprobaciones en pestañas (junto a Timeline/Modelos: menús en L) -->
        <section class="mdock">
          <div class="mdock-h">
            <button class="mtab" :class="{ on: ltab === 'mision' }" @click="ltab = 'mision'">
              <i class="fa-solid fa-flag" /> Misión <span v-if="curKey" class="n">{{ duration(missionEnd - missionStart) }}</span>
            </button>
            <button class="mtab" :class="{ on: ltab === 'bandeja' }" @click="ltab = 'bandeja'">
              <i class="fa-solid fa-inbox" /> Aprobaciones <span class="n" :class="{ 'n--warn': live.inbox.length }">{{ live.inbox.length }}</span>
            </button>
            <span class="spacer" />
            <RouterLink v-if="ltab === 'bandeja'" to="/trabajo" class="tolink" title="Revisar con el diff archivo a archivo">Revisar →</RouterLink>
          </div>
          <div class="mdock-b">
            <div v-show="ltab === 'mision'" class="mission">
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
                  <select v-model="form.agent_id" class="input" title="Agente" @change="proposal = null">
                    <option :value="0">✨ Agente a medida</option>
                    <option v-for="a in agentsSorted" :key="a.id" :value="a.id">{{ a.name }} · {{ a.provider }}</option>
                  </select>
                </div>
                <textarea
                  v-model="form.prompt" class="input" rows="3" placeholder="¿Qué hay que hacer? (Enter para ejecutar)"
                  @keydown.enter.exact.prevent="launch"
                />
                <!-- propuesta del diseñador: qué agente se va a crear y por qué (quita lo que no quieras) -->
                <div v-if="proposal" class="prop">
                  <div class="prop-h">
                    <i class="fa-solid fa-wand-magic-sparkles" />
                    <b>{{ proposal.name }}</b>
                    <span class="prov" :class="`prov--${proposal.provider}`">{{ proposal.provider === "claude" ? `Claude ${proposal.model}` : "Modelo local" }}</span>
                  </div>
                  <div class="chips">
                    <span v-if="proposal.coordinator" class="pill pill--ok" title="Claude planifica y el modelo local hace el trabajo"><i class="fa-solid fa-user-tie" />coordina al local</span>
                    <span v-if="proposal.read_only" class="pill"><i class="fa-solid fa-eye" />solo lectura</span>
                    <span v-if="proposal.web" class="pill pill--active"><i class="fa-solid fa-globe" />internet</span>
                    <span v-if="proposal.thinking !== 'normal'" class="pill"><i class="fa-solid fa-brain" />pensar {{ proposal.thinking }}</span>
                    <span class="pill"><i class="fa-solid fa-repeat" />{{ proposal.max_turns }} turnos</span>
                  </div>
                  <div v-if="proposal.skills.length" class="prop-row"><span>Skills</span>
                    <button v-for="x in proposal.skills" :key="x" type="button" class="pill pill--active" title="Quitar" @click="dropFrom('skills', x)"><i class="fa-solid fa-bolt" />{{ x }} ×</button>
                  </div>
                  <div v-if="proposal.local_skills.length" class="prop-row"><span>Su modelo local</span>
                    <button v-for="x in proposal.local_skills" :key="x" type="button" class="pill pill--active" title="Quitar" @click="dropFrom('local_skills', x)"><i class="fa-solid fa-robot" />{{ x }} ×</button>
                  </div>
                  <div v-if="proposal.mcps.length" class="prop-row"><span>MCP</span>
                    <button v-for="x in proposal.mcps" :key="x" type="button" class="pill pill--active" title="Quitar" @click="dropFrom('mcps', x)"><i class="fa-solid fa-plug" />{{ x }} ×</button>
                  </div>
                  <p v-if="proposal.reason" class="small muted">{{ proposal.reason }}</p>
                  <p class="small muted">Diseñado por {{ proposal.designed_by === "claude" ? `Claude Haiku (${usd(proposal.design_cost_usd)})` : "reglas (sin Claude)" }}</p>
                </div>
                <p v-if="formError" class="error small">{{ formError }}</p>
                <div class="row">
                  <button class="btn btn--primary" :disabled="sending || designing || !form.prompt.trim() || !form.project_id || form.agent_id === null">
                    <i class="fa-solid" :class="designing ? 'fa-spinner fa-spin' : form.agent_id === 0 && !proposal ? 'fa-wand-magic-sparkles' : 'fa-play'" />
                    {{ designing ? "Diseñando el agente…" : form.agent_id === 0 && !proposal ? "Diseñar agente" : form.agent_id === 0 ? "Crear agente y ejecutar" : "Ejecutar" }}
                  </button>
                  <button v-if="proposal" type="button" class="btn btn--small" :disabled="designing" @click="design">
                    <i class="fa-solid fa-rotate" /> Otra propuesta
                  </button>
                </div>
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
                <!-- el encargo entero (recortado) y, si el agente es a medida, por qué es así -->
                <div v-if="curTask" class="m-sum" :class="{ open: briefOpen }" title="Pulsa para ver el encargo entero" @click="briefOpen = !briefOpen">
                  <p>{{ curTask.prompt }}</p>
                  <small v-if="curAgent?.config.generated && curAgent.config.design_reason"><i class="fa-solid fa-wand-magic-sparkles" /> {{ curAgent.config.design_reason }}</small>
                </div>
                <div class="m-prog"><span :style="{ width: `${progress * 100}%` }" /></div>
                <!-- qué está haciendo el modelo local, encargo a encargo -->
                <div v-if="curTask && (localJobs.length || curLive)" class="ljobs">
                  <div class="ljobs__h"><i class="fa-solid fa-robot" /> Modelo local <em>{{ localJobs.filter((j) => j.state === "ok").length }}/{{ localJobs.length }} hechos</em>
                    <button v-for="w in workers.filter((x) => x.task.id === curTask!.id)" :key="w.srv" class="linkish" @click="pick(wid(w.task.id, w.srv))">{{ live.locals.length > 1 ? `${serverOf(w.srv)?.name ?? w.srv} →` : "ver →" }}</button>
                  </div>
                  <div v-for="j in localJobs.slice(-8)" :key="j.key" class="ljob" :class="j.state">
                    <i class="fa-solid" :class="j.state === 'run' ? 'fa-gear fa-spin' : j.state === 'ok' ? 'fa-check' : 'fa-xmark'" />
                    <div>
                      <b><span class="tag">{{ j.kind }}</span> {{ j.title.length > 110 ? j.title.slice(0, 110) + "…" : j.title }}</b>
                      <small v-if="j.meta">{{ j.meta }}</small>
                      <small v-for="(c, k) in j.children" :key="k" :class="{ bad: !c.ok }">{{ c.ok ? "✓" : "✗" }} {{ c.title }}</small>
                      <small v-if="j.state === 'run' && curLive" class="livetxt">{{ curLive.text ? `✍️ ${curLive.text.slice(-140)}` : curLive.thinking ? `💭 ${curLive.thinking.slice(-140)}` : "leyendo…" }}</small>
                    </div>
                  </div>
                </div>
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
            </div>
            <div v-show="ltab === 'bandeja'">
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
            </div>
          </div>
        </section>
        <div class="gutter" title="Arrastra para cambiar el ancho (doble clic: por defecto)" @pointerdown="startDrag('left', $event)" @dblclick="resetSizes('left')" />
        <OfficeDock ref="dock" :events="events" :review="review" :review-title="diffTask ? `#${diffTask.id} ${diffTask.title}` : ''" />
      </div>
    </main>
    <div class="gutter" title="Arrastra para cambiar el ancho (doble clic: por defecto)" @pointerdown="startDrag('right', $event)" @dblclick="resetSizes('right')" />

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
          <div class="l">CPU <span>{{ sys?.cpu_pct != null ? `${Math.round(sys.cpu_pct)} %` : "—" }}{{ sys?.cores ? ` · ${sys.cores} hilos` : "" }}</span></div>
          <span class="meter"><span :style="{ width: `${sys?.cpu_pct ?? 0}%`, background: gpuColor((sys?.cpu_pct ?? 0) / 100) }" /></span>
          <div v-if="sys?.per_core?.length" class="cores" :title="`Uso por núcleo: ${sys.per_core.map((c) => Math.round(c)).join(' · ')} %`">
            <i v-for="(c, k) in sys.per_core" :key="k" :style="{ height: `${Math.max(8, c)}%`, background: gpuColor(c / 100) }" />
          </div>
        </div>
        <div class="res-row">
          <div class="l">RAM <span>{{ sys?.ram_used_gb != null ? `${sys.ram_used_gb}/${sys.ram_total_gb} GB · ${Math.round(sys.ram_pct ?? 0)} %` : "—" }}</span></div>
          <span class="meter"><span :style="{ width: `${sys?.ram_pct ?? 0}%`, background: gpuColor((sys?.ram_pct ?? 0) / 100) }" /></span>
        </div>
        <div class="res-row">
          <div class="l">{{ live.locals.length > 1 ? "Modelos locales" : "Modelo local" }} <span :class="`ls-${localState}`">{{ LOCAL_TEXT[localState] ?? localState }}</span></div>
          <div v-if="live.locals.length > 1" class="sub sub--list">
            <span v-for="l in live.locals" :key="l.id" class="mono" :class="`ls-${l.state}`" :title="`${l.name} · ${l.device || 'GPU automática'} · puerto ${l.port}`">
              {{ l.name }}: {{ l.model ?? LOCAL_TEXT[l.state] ?? l.state }}</span>
            <RouterLink to="/modelos" class="small">Modelos →</RouterLink>
          </div>
          <div v-else class="sub">
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
        <div class="l">Tokens/s (local) <span class="mono">{{ tpsNow ? tps(tpsNow) + (workingLocals.length > 1 ? ` · ${workingLocals.length} modelos` : "") : live.lastSpeed?.tps ? `último ${tps(live.lastSpeed.tps)}` : "0" }}</span></div>
        <canvas ref="spark" class="spark" width="300" height="38" />
        <div class="kv">
          <div><b>{{ tasks.filter((t) => t.status === "running").length }}</b><span>Trabajando</span></div>
          <div title="Equivalente en API: con la suscripción no se paga aparte"><b>{{ usd(weekCost) }}</b><span>Coste 7 días</span></div>
        </div>
        <h3 class="card-title wt-title">Worktrees git <em>{{ liveTrees.length }} activos · {{ worktrees.length }}</em></h3>
        <div class="chips">
          <span class="pill"><i class="fa-solid fa-code-branch" />main</span>
          <button
            v-for="w in liveTrees.slice(0, 6)" :key="`${w.kind}${w.id}`" class="pill" :class="{ 'pill--active': wtState(w) === 'active', 'pill--ok': wtState(w) === 'ready' }"
            :title="`${w.project} · ${w.status}`" @click="chosen = `${w.kind === 'plan' ? 'p' : 't'}${w.id}`"
          ><i class="fa-solid fa-code-branch" />{{ w.branch.replace("localharness/", "") }}</button>
          <RouterLink v-if="liveTrees.length > 6 || worktrees.length > liveTrees.length" to="/trabajo" class="pill" :title="`${worktrees.length} worktrees en total`">
            +{{ worktrees.length - Math.min(6, liveTrees.length) }} más
          </RouterLink>
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
        <template v-else-if="sel.startsWith('rack')">
          <h3 class="card-title">Inspector <em>{{ (LOCAL_TEXT[localState] ?? localState).toUpperCase() }}</em></h3>
          <div class="insp-h">
            <div class="avatar" :style="{ '--c': LOCAL }"><i class="fa-solid fa-server" /></div>
            <div><b>{{ live.locals.length > 1 ? `${live.locals.length} modelos locales` : "Modelo local" }}</b><small>llama-server · {{ live.locals.length > 1 ? "uno por GPU" : "GPU" }}</small></div>
            <span class="prov prov--local">Gratis</span>
          </div>
          <template v-if="live.locals.length > 1">
            <div v-for="l in live.locals" :key="l.id" class="res-row">
              <div class="l">{{ l.name }} · {{ SERVER_ROLE_LABEL[l.role] }} <span :class="`ls-${l.state}`">{{ l.model ?? LOCAL_TEXT[l.state] ?? l.state }}</span></div>
              <div class="sub"><span class="mono small">{{ l.device || "GPU automática" }} · puerto {{ l.port }}</span></div>
            </div>
          </template>
          <div v-else class="res-row"><div class="l">Arrancado <span>{{ live.local.model ?? "ninguno" }}</span></div></div>
          <div class="res-row"><div class="l">Última velocidad <span>{{ live.lastSpeed?.tps ? tps(live.lastSpeed.tps) : "—" }}</span></div></div>
          <p class="small muted">
            Responde a los agentes locales y hace los encargos de los agentes Claude con «Puede delegar en el modelo local»:
            {{ delegators.length ? delegators.join(", ") : "ninguno todavía" }}.
          </p>
          <RouterLink class="btn btn--small wide" to="/modelos"><i class="fa-solid fa-microchip" /> Modelos locales</RouterLink>
        </template>

        <!-- el trabajador del modelo local de una tarea -->
        <LocalWorkerPanel
          v-else-if="selWorker && selW" :task="selWorker" :events="serverEvents(selWorker.id, selW.srv)" :stream="liveNow(selWorker.id, selW.srv)"
          :server="live.locals.length > 1 ? { id: selW.srv, name: serverOf(selW.srv)?.name ?? selW.srv, model: serverOf(selW.srv)?.model ?? null, color: serverColor(selW.srv) } : undefined"
          :agent="live.agents.find((a) => a.id === selWorker!.agent_id)"
        />

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
            <button class="btn btn--small" @click="openWizard(selAgent.id)"><i class="fa-solid fa-pen" /> Editar</button>
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
  --lw: 420px;
  --rw: 330px;
  height: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 12px var(--rw);
  min-height: 0;
}
/* abajo: Misión/Aprobaciones | Timeline/Terminal/Diff/Modelos, con la columna de la derecha forman una L */
.bottom {
  display: grid;
  grid-template-columns: var(--lw) 10px minmax(0, 1fr);
  height: var(--dockh);
  min-height: 0;
  border-top: 1px solid var(--line);
  background: var(--panel);
}
.bottom :deep(.dock) {
  height: 100%;
  border-top: 0;
}
.mdock {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
}
.mdock-h {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
}
.mtab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border: 0;
  border-radius: var(--radius-sm);
  background: none;
  color: var(--ink-dim);
  font: inherit;
  font-weight: 700;
  font-size: 12.5px;
  cursor: pointer;
}
.mtab:hover {
  background: var(--panel-hover);
}
.mtab.on {
  background: var(--ink);
  color: var(--panel);
}
.mtab .n {
  font-size: 10px;
  background: rgba(148, 163, 184, 0.3);
  padding: 0 6px;
  border-radius: 4px;
}
.mtab .n--warn {
  background: var(--warn);
  color: #fff;
}
.mdock-b {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 10px 12px;
}
.bottom .gutter::after {
  inset: 25% 3px;
}
.office.dragging {
  user-select: none;
  cursor: col-resize;
}
.office.dragging :deep(.dock) {
  transition: none;
}
/* asas para cambiar el tamaño de los paneles (se guarda en este navegador) */
.gutter {
  position: relative;
  cursor: col-resize;
  touch-action: none;
}
.gutter::after {
  content: "";
  position: absolute;
  inset: 30% 5px;
  border-radius: 3px;
  background: var(--line);
  opacity: 0;
  transition: opacity 0.15s, background 0.15s;
}
.gutter:hover::after,
.dragging .gutter::after {
  opacity: 1;
}
.gutter:hover::after {
  background: var(--accent);
}
.gutter--h {
  flex: 0 0 8px;
  cursor: row-resize;
  margin: -4px 0;
  z-index: 3;
}
.gutter--h::after {
  inset: 3px 40%;
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
  min-width: 0;
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
.m-sum {
  font-size: 12.5px;
  color: var(--ink-dim);
  background: var(--panel-raised);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  margin-bottom: 10px;
  cursor: pointer;
}
.m-sum p {
  margin: 0;
  white-space: pre-wrap;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.m-sum.open p {
  display: block;
}
.m-sum small {
  display: block;
  margin-top: 6px;
  color: var(--ink-faint);
}
.tolink {
  margin-left: auto;
  font-size: 12px;
  font-weight: 700;
  text-transform: none;
  letter-spacing: 0;
}
.ljobs {
  margin: 0 0 8px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: rgba(14, 165, 233, 0.1);
  display: grid;
  gap: 6px;
}
.ljobs__h {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 800;
  font-size: 12px;
  color: #0284c7;
}
.ljobs__h em {
  font-style: normal;
  font-weight: 600;
  color: var(--ink-faint);
}
.linkish {
  margin-left: auto;
  border: 0;
  background: none;
  color: #0284c7;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}
.ljob {
  display: grid;
  grid-template-columns: 16px 1fr;
  gap: 6px;
  font-size: 12px;
}
.ljob > i {
  margin-top: 3px;
  font-size: 11px;
  width: 12px;
  height: 12px;
  line-height: 12px;
  text-align: center;
  align-self: start;
}
.ljob.ok > i {
  color: var(--ok);
}
.ljob.bad > i {
  color: var(--crit);
}
.ljob.run > i {
  color: #0284c7;
}
.ljob b {
  font-weight: 600;
  overflow-wrap: anywhere;
}
.ljob small {
  display: block;
  color: var(--ink-faint);
  font-size: 11px;
  overflow-wrap: anywhere;
}
.ljob small.bad {
  color: var(--crit);
}
.ljob .livetxt {
  color: var(--ink-dim);
  font-style: italic;
}
.ljob .tag {
  font-size: 10px;
  font-weight: 800;
  text-transform: uppercase;
  color: #0284c7;
  margin-right: 2px;
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
  background: var(--accent);
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
  border-radius: var(--radius-sm);
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
  border-radius: var(--radius);
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
  background: var(--warn-weak);
  border-radius: var(--radius);
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
  border-radius: var(--radius);
  overflow: hidden;
  border: 1px solid var(--line);
  background: #c3c8cc;
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
  border-radius: 8px 8px 8px 2px;
  padding: 4px 8px;
  font-size: 11px;
  font-weight: 600;
  color: #4a505c;
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
  border: 1px solid color-mix(in srgb, var(--c) 40%, #eeebe4);
  border-radius: 7px;
  padding: 3px 8px 3px 4px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.18);
  transition: transform 0.15s;
  color: #1e232d;
  font: inherit;
}
.plate:hover {
  transform: scale(1.05);
}
.plate.sel {
  border-color: var(--c);
  box-shadow: inset 0 0 0 1px var(--c), 0 1px 2px rgba(15, 23, 42, 0.18);
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
  border-radius: 5px;
  border: 0;
  font-family: inherit;
}
.tag--btn {
  pointer-events: auto;
  cursor: pointer;
  text-transform: none;
  letter-spacing: 0;
  font-size: 11px;
  border-left: 3px solid var(--c, #0ea5e9);
}
.tag--btn.sel {
  background: rgba(15, 23, 42, 0.95);
  outline: 1px solid var(--c, #0ea5e9);
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
  border-radius: 8px;
  background: rgba(236, 233, 225, 0.96);
  border: 1px solid #cbc6ba;
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
  border-radius: var(--radius-sm);
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
  border-radius: var(--radius-sm);
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
.away--new {
  background: var(--accent, #5b5bf0);
  border-color: transparent;
  color: #fff;
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

/* propuesta de agente a medida */
.prop {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border-radius: var(--radius);
  background: var(--accent-weak);
}
.prop-h {
  display: flex;
  align-items: center;
  gap: 8px;
}
.prop-h .prov {
  margin-left: auto;
}
.prop-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}
.prop-row > span {
  font-size: 11px;
  font-weight: 700;
  color: var(--ink-dim);
  margin-right: 2px;
}
.prop p {
  margin: 0;
}

/* recursos */
.res-row {
  margin-bottom: 10px;
}
.cores {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 18px;
  margin-top: 4px;
}
.cores i {
  flex: 1;
  border-radius: 2px;
  min-width: 2px;
  opacity: 0.85;
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
.sub--list {
  flex-wrap: wrap;
  justify-content: flex-start;
}
.sub--list .mono:not(.ls-off) {
  color: var(--ink);
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
  border-radius: var(--radius-sm);
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
  border-radius: var(--radius);
  display: grid;
  place-items: center;
  font-size: 19px;
  color: #fff;
  background: var(--c);
}
.desc {
  margin: 0 0 10px;
}
.doing {
  display: grid;
  gap: 2px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
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

@media (max-width: 980px) {
  .gutter {
    display: none;
  }
  .office {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto auto;
    height: auto;
  }
  .bottom {
    grid-template-columns: minmax(0, 1fr);
    height: auto;
  }
  .mdock-b {
    max-height: 50vh;
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
