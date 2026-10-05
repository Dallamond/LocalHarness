// Estado en vivo: un único EventSource a /api/events alimenta toda la GUI (mismo patrón que Arena LLM).

import { computed, reactive } from "vue";

export interface Project {
  id: number;
  name: string;
  repo_path: string;
  memory_dir: string | null;
}

export interface Agent {
  id: number;
  name: string;
  provider: string;
  model: string | null;
  role: string | null;
  config: {
    max_turns?: number; max_budget_usd?: number; read_only?: boolean; tools?: string[];
    skills?: string[]; base_url?: string;
  };
}

export type TaskStatus =
  | "pending" | "running" | "review" | "approved" | "merged" | "rejected" | "discarded"
  | "failed" | "timeout" | "cancelled" | "interrupted" | "done";

export interface Task {
  id: number;
  project_id: number;
  agent_id: number | null;
  title: string;
  prompt: string;
  status: TaskStatus;
  branch: string | null;
  worktree: string | null;
  base_commit: string | null;
  session_id: string | null;
  final: string | null;
  cost_usd: number | null;
  created_at: string;
  finished_at: string | null;
  plan_id: number | null;
  seq: number | null;
  kind: "director" | "worker" | "reviewer" | null;
  level: string | null;
  approved_by: string | null;
  head_commit?: string | null;
}

/** Subtarea dentro del detalle de un plan (motivos y veredicto ya decodificados). */
export interface PlanTask extends Task {
  level_reasons: string[];
  review: { verdict: string; risk: string; reason: string } | null;
}

export type PlanStatus =
  | "planning" | "awaiting_you" | "approved" | "running" | "paused" | "ready" | "merged" | "rejected"
  | "failed" | "cancelled" | "interrupted" | "done";

export interface Plan {
  id: number;
  project_id: number;
  request: string;
  director_agent_id: number | null;
  reviewer_agent_id: number | null;
  status: PlanStatus;
  plan: { summary: string; risk: string; subtasks: { title: string; agent: string; risk: string; prompt: string }[] } | null;
  level: string | null;
  level_reasons: string[];
  branch: string | null;
  cost_usd: number | null;
  error: string | null;
  created_at: string;
  tasks?: PlanTask[];
}

export interface InboxItem {
  type: "plan_approval" | "plan_merge" | "task_decision" | "task_review";
  plan_id?: number;
  task_id?: number;
  title: string;
  level: string;
  reasons: string[];
}

export interface TaskEvent {
  id?: number;
  task_id: number;
  kind: string;
  text: string;
  data: Record<string, unknown>;
}

export interface Limit {
  status?: string;
  five_hour?: number | null;
  seven_day?: number | null;
  resets_at?: number | null;
  overage?: boolean | null;
}

export interface Review {
  available: boolean;
  stat: string;
  diff: string;
  target: string | null;
}

/** Lo último que ha hecho una tarea en marcha (para el Inicio). */
export interface Activity {
  kind: string;
  text: string;
  data: Record<string, unknown>;
  at: number;
}

/** Tarea terminada con los archivos que tocó (GET /api/activity). */
export interface RecentTask extends PlanTask {
  files: { path: string; added: number; deleted: number }[];
}

export interface Skill {
  name: string;
  description: string;
  path: string;
  chars: number;
}

export interface Settings {
  policy: {
    max_files: number; max_lines: number; max_auto_subtasks: number;
    sensitive: string[]; dependency: string[]; config: string[];
  };
  task_timeout_min: number;
  local_base_url: string;
  context: { max_memory_chars: number; max_skill_chars: number; skill_dirs: string[] };
  agent_defaults: { provider: string; model: string; role: string; max_turns: number | null; max_budget_usd: number | null };
}

export const live = reactive({
  connection: "connecting" as "connecting" | "open" | "closed",
  projects: [] as Project[],
  agents: [] as Agent[],
  tasks: {} as Record<number, Task>,
  plans: {} as Record<number, Plan>,
  inbox: [] as InboxItem[],
  limit: null as Limit | null,
  activity: {} as Record<number, Activity>,
  recent: [] as RecentTask[],
});

type Handler = (ev: TaskEvent) => void;
const eventHandlers = new Set<Handler>();

/** Suscribe a los eventos de ejecución de todas las tareas; devuelve la baja. */
export function onTaskEvent(fn: Handler): () => void {
  eventHandlers.add(fn);
  return () => eventHandlers.delete(fn);
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (r.status === 204) return undefined as T;
  const body = await r.json().catch(() => null);
  if (!r.ok) {
    const detail = body?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => String(d.msg).replace(/^Value error, /, "")).join(" · ")
          : `HTTP ${r.status}`,
    );
  }
  return body as T;
}

export const post = <T>(path: string, body: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });

export async function refreshAll(): Promise<void> {
  const [projects, agents, tasks, plans, health] = await Promise.all([
    api<Project[]>("/api/projects"),
    api<Agent[]>("/api/agents"),
    api<Task[]>("/api/tasks"),
    api<Plan[]>("/api/plans"),
    api<{ limit: Limit | null }>("/api/health"),
  ]);
  live.projects = projects;
  live.agents = agents;
  live.tasks = Object.fromEntries(tasks.map((t) => [t.id, t]));
  live.plans = Object.fromEntries(plans.map((p) => [p.id, p]));
  live.limit = health.limit;
  await Promise.all([refreshInbox(), refreshActivity()]);
}

/** Qué está haciendo cada tarea en marcha y las últimas terminadas (con sus archivos). */
export async function refreshActivity(): Promise<void> {
  const a = await api<{ current: Record<string, TaskEvent & { ts: string }>; recent: RecentTask[] }>("/api/activity");
  for (const [tid, ev] of Object.entries(a.current)) {
    live.activity[Number(tid)] = { kind: ev.kind, text: ev.text, data: ev.data, at: parseTs(ev.ts) };
  }
  live.recent = a.recent;
}

let inboxTimer: ReturnType<typeof setTimeout> | null = null;

/** La bandeja depende de planes y tareas: se recalcula en el servidor tras cada cambio (agrupado). */
export async function refreshInbox(): Promise<void> {
  live.inbox = await api<InboxItem[]>("/api/inbox");
}

function scheduleInbox(): void {
  if (inboxTimer) clearTimeout(inboxTimer);
  inboxTimer = setTimeout(() => {
    refreshInbox().catch(() => {});
    refreshActivity().catch(() => {});
  }, 400);
}

export const taskList = computed(() => Object.values(live.tasks).sort((a, b) => b.id - a.id));
export const pendingForYou = computed(() => live.inbox);
export const planList = computed(() => Object.values(live.plans).sort((a, b) => b.id - a.id));

export const projectName = (id: number) => live.projects.find((p) => p.id === id)?.name ?? `#${id}`;
export const agentName = (id: number | null) =>
  id === null ? "—" : live.agents.find((a) => a.id === id)?.name ?? `#${id}`;

let source: EventSource | null = null;

export function connect(url = "/api/events"): void {
  if (source) return;
  refreshAll().catch(() => {});
  source = new EventSource(url);
  source.onopen = () => {
    live.connection = "open";
    refreshAll().catch(() => {}); // tras una reconexión se recupera lo perdido
  };
  source.onerror = () => (live.connection = "closed"); // EventSource reintenta solo
  source.addEventListener("task", (e) => {
    const t = JSON.parse((e as MessageEvent).data) as Task;
    live.tasks[t.id] = t;
    scheduleInbox();
  });
  source.addEventListener("plan", (e) => {
    const p = JSON.parse((e as MessageEvent).data) as Plan;
    live.plans[p.id] = { ...live.plans[p.id], ...p };
    scheduleInbox();
  });
  source.addEventListener("task_event", (e) => {
    const ev = JSON.parse((e as MessageEvent).data) as TaskEvent;
    if (["text", "tool", "status", "context"].includes(ev.kind)) {
      live.activity[ev.task_id] = { kind: ev.kind, text: ev.text, data: ev.data ?? {}, at: Date.now() };
    }
    eventHandlers.forEach((fn) => fn(ev));
  });
  source.addEventListener("limit", (e) => {
    live.limit = JSON.parse((e as MessageEvent).data) as Limit;
  });
}

// --- presentación de estados (chip: icono + texto, nunca solo color)
export function statusChip(s: TaskStatus): "ok" | "warn" | "crit" | "pending" | "off" {
  if (s === "review" || s === "approved") return "warn"; // esperando decisión
  if (s === "merged") return "ok";
  if (s === "failed" || s === "timeout") return "crit";
  if (s === "running" || s === "pending") return "pending";
  return "off";
}

export const STATUS_TEXT: Record<TaskStatus, string> = {
  pending: "pendiente",
  running: "en marcha",
  review: "por revisar",
  approved: "aprobada",
  merged: "integrada",
  rejected: "rechazada",
  discarded: "descartada",
  failed: "fallida",
  timeout: "tiempo agotado",
  cancelled: "cancelada",
  interrupted: "interrumpida",
  done: "hecha",
};

export const PLAN_TEXT: Record<PlanStatus, string> = {
  planning: "planificando",
  awaiting_you: "espera tu aprobación",
  approved: "aprobado",
  running: "en marcha",
  paused: "parado: decides tú",
  ready: "listo para integrar",
  merged: "integrado",
  rejected: "rechazado",
  failed: "fallido",
  cancelled: "cancelado",
  interrupted: "interrumpido",
  done: "terminado sin cambios",
};

export function planChip(s: PlanStatus): "ok" | "warn" | "crit" | "pending" | "off" {
  if (s === "awaiting_you" || s === "paused" || s === "ready") return "warn";
  if (s === "merged") return "ok";
  if (s === "failed") return "crit";
  if (s === "planning" || s === "running" || s === "approved") return "pending";
  return "off";
}

/** SQLite guarda CURRENT_TIMESTAMP en UTC sin zona ("2026-10-05 19:32:42"). */
export function parseTs(s: string | null | undefined): number {
  if (!s) return NaN;
  return Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(s) ? s : s.replace(" ", "T") + "Z");
}

export function ago(ms: number, now = Date.now()): string {
  if (Number.isNaN(ms)) return "";
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 45) return "ahora mismo";
  const m = Math.round(s / 60);
  if (m < 60) return `hace ${m} min`;
  const h = Math.round(m / 60);
  if (h < 24) return `hace ${h} h`;
  const d = Math.round(h / 24);
  return d === 1 ? "ayer" : `hace ${d} días`;
}

export function duration(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m} min ${s % 60} s` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

export const ROLE_TEXT: Record<string, string> = {
  director: "Director",
  jefe: "Jefe técnico",
  trabajador: "Trabajador",
};

export function roleColor(a: Agent | undefined): string {
  const r = a?.role ?? "";
  return r === "director" || r === "jefe" || r === "trabajador" ? `var(--role-${r})` : "var(--role-otro)";
}

/** Frase corta de lo que está haciendo un agente a partir de su último evento. */
export function describeActivity(a: Activity | undefined): string {
  if (!a) return "arrancando…";
  if (a.kind === "tool") {
    const input = (a.data.input ?? {}) as Record<string, unknown>;
    const target = String(input.file_path ?? input.pattern ?? input.command ?? input.path ?? "");
    const short = target.split(/[\\/]/).slice(-2).join("/");
    const verb: Record<string, string> = {
      Read: "Leyendo", Edit: "Editando", Write: "Escribiendo", MultiEdit: "Editando",
      Grep: "Buscando", Glob: "Buscando archivos", Bash: "Ejecutando",
    };
    return `${verb[a.text] ?? a.text} ${short}`.trim();
  }
  if (a.kind === "text") return a.text.replace(/\s+/g, " ").slice(0, 140);
  if (a.kind === "context") return `Cargando contexto: ${a.text}`;
  return "pensando…";
}

// --- apariencia (solo de este navegador)
export interface Look {
  theme: "auto" | "claro" | "oscuro";
  density: "normal" | "compacta";
  zoom: number;
}

function readLook(): Look {
  try {
    return { theme: "auto", density: "normal", zoom: 1, ...JSON.parse(localStorage.getItem("lh-look") ?? "{}") };
  } catch {
    return { theme: "auto", density: "normal", zoom: 1 };
  }
}

export const look = reactive<Look>(readLook());

export function applyLook(): void {
  const r = document.documentElement;
  if (look.theme === "auto") delete r.dataset.theme;
  else r.dataset.theme = look.theme;
  r.dataset.density = look.density;
  r.style.setProperty("--zoom", String(look.zoom));
  try {
    localStorage.setItem("lh-look", JSON.stringify(look));
  } catch {
    /* modo privado: se aplica igual, solo no se recuerda */
  }
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${Math.round(v * 100)} %`;
}

export function usd(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${v.toFixed(v < 0.1 ? 4 : 2)} $`;
}
