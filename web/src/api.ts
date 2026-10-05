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
  | "failed" | "timeout" | "cancelled" | "interrupted";

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
  const [projects, agents, tasks, health] = await Promise.all([
    api<Project[]>("/api/projects"),
    api<Agent[]>("/api/agents"),
    api<Task[]>("/api/tasks"),
    api<{ limit: Limit | null }>("/api/health"),
  ]);
  live.projects = projects;
  live.agents = agents;
  live.tasks = Object.fromEntries(tasks.map((t) => [t.id, t]));
  live.limit = health.limit;
}

export const taskList = computed(() => Object.values(live.tasks).sort((a, b) => b.id - a.id));
export const pendingForYou = computed(() =>
  taskList.value.filter((t) => t.status === "review" || t.status === "approved"),
);

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
};

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${Math.round(v * 100)} %`;
}

export function usd(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${v.toFixed(v < 0.1 ? 4 : 2)} $`;
}
