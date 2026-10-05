// Estado en vivo: un único EventSource a /api/events alimenta toda la GUI (mismo patrón que Arena LLM).

import { computed, reactive } from "vue";

export interface Project {
  id: number;
  name: string;
  repo_path: string;
}

export interface Agent {
  id: number;
  name: string;
  provider: string;
  model: string | null;
  role: string | null;
  config: { max_turns?: number; max_budget_usd?: number; read_only?: boolean; tools?: string[] };
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
  | "failed" | "cancelled" | "interrupted";

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

export const live = reactive({
  connection: "connecting" as "connecting" | "open" | "closed",
  projects: [] as Project[],
  agents: [] as Agent[],
  tasks: {} as Record<number, Task>,
  plans: {} as Record<number, Plan>,
  inbox: [] as InboxItem[],
  limit: null as Limit | null,
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
  await refreshInbox();
}

let inboxTimer: ReturnType<typeof setTimeout> | null = null;

/** La bandeja depende de planes y tareas: se recalcula en el servidor tras cada cambio (agrupado). */
export async function refreshInbox(): Promise<void> {
  live.inbox = await api<InboxItem[]>("/api/inbox");
}

function scheduleInbox(): void {
  if (inboxTimer) clearTimeout(inboxTimer);
  inboxTimer = setTimeout(() => refreshInbox().catch(() => {}), 300);
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
};

export function planChip(s: PlanStatus): "ok" | "warn" | "crit" | "pending" | "off" {
  if (s === "awaiting_you" || s === "paused" || s === "ready") return "warn";
  if (s === "merged") return "ok";
  if (s === "failed") return "crit";
  if (s === "planning" || s === "running" || s === "approved") return "pending";
  return "off";
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${Math.round(v * 100)} %`;
}

export function usd(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${v.toFixed(v < 0.1 ? 4 : 2)} $`;
}
