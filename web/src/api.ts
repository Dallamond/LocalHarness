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
    skills?: string[]; base_url?: string; description?: string; subagents?: boolean; delegate_local?: boolean;
    coordinator?: boolean; generated?: boolean; designed_for?: string; design_reason?: string; local_skills?: string[];
    mcps?: string[];
    temperature?: number; max_tokens?: number; repo_context?: number;
    tool_mode?: string; web?: boolean; commands?: string[]; command_timeout_s?: number; timeout_s?: number;
    from_role?: string; instructions?: string; thinking?: Thinking; off?: boolean; template?: string;
    server?: string; // local: en qué servidor local (GPU) trabaja; vacío = el principal
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
  skills?: string[];
}

/** Subtarea dentro del detalle de un plan (motivos y veredicto ya decodificados). */
export interface PlanTask extends Task {
  level_reasons: string[];
  review: { verdict: string; risk: string; reason: string } | null;
}

export type PlanStatus =
  | "planning" | "awaiting_you" | "approved" | "running" | "paused" | "ready" | "merged" | "rejected"
  | "failed" | "cancelled" | "interrupted" | "done";

export type Thinking = "apagado" | "normal" | "profundo";
export const THINKING_TEXT: Record<string, string> = {
  "": "el del agente", apagado: "apagado (rápido)", normal: "normal", profundo: "profundo (más lento y caro)",
};

export interface PlanStep {
  title: string;
  agent: string;
  risk: string;
  prompt: string;
  skills?: string[];
  thinking?: Thinking;
}

export interface Plan {
  id: number;
  project_id: number;
  request: string;
  director_agent_id: number | null;
  reviewer_agent_id: number | null;
  status: PlanStatus;
  plan: { summary: string; risk: string; subtasks: PlanStep[] } | null;
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
  ts?: string;
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
  imported?: boolean;
  category?: string;
  source?: string | null;
}

/** Skill de la biblioteca (biblioteca/skills) o encontrada en GitHub: se previsualiza antes de instalarla. */
export interface LibrarySkill {
  name: string;
  description: string;
  category: string;
  content: string;
  chars: number;
  installed: boolean;
  tags?: string;
  path?: string; // GitHub
  url?: string;  // GitHub
}

export interface McpParam { key: string; label: string; placeholder?: string; secret?: boolean; folder?: boolean; file?: boolean }

/** Servidor MCP preparado (biblioteca/mcp.json). */
export interface LibraryMcp {
  id: string;
  name: string;
  category: string;
  icon: string;
  description: string;
  tools: string[];
  needs?: string;
  config: McpServer & { headers?: Record<string, string> };
  params?: McpParam[];
  homepage?: string;
  available: boolean;
  added_as: string[];
}

/** Plantilla por rol del asistente de agentes (biblioteca/agentes.json). */
export interface AgentTemplate {
  id: string;
  name: string;
  icon: string;
  role: string;
  summary: string;
  description: string;
  provider: "claude" | "local";
  claude_model: string;
  local_use: string;
  local_provider: "local" | "local_agent";
  read_only: boolean;
  max_turns: number;
  max_budget_usd: number;
  thinking: Thinking;
  skills: string[];
  mcps: string[];
  web: boolean;
  delegate_local: boolean;
  coordinator?: boolean;
  instructions: string;
}

export interface Library { skills: LibrarySkill[]; mcps: LibraryMcp[]; templates: AgentTemplate[] }

/** Servidor MCP del Catálogo (formato mcpServers de Claude/Cursor). */
export interface McpServer {
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  type?: string;
  description?: string;
}

export interface Gpu {
  index: number;
  name: string;
  mem_used_mb: number | null;
  mem_total_mb: number | null;
  util: number | null;
  temp: number | null;
}

export interface Worktree {
  kind: "task" | "plan";
  id: number;
  branch: string;
  status: string;
  project: string | null;
}

export interface Settings {
  policy: {
    max_files: number; max_lines: number; max_auto_subtasks: number;
    sensitive: string[]; dependency: string[]; config: string[];
  };
  plans: { always_review: boolean };
  task_timeout_min: number;
  local_base_url: string;
  context: { max_memory_chars: number; max_skill_chars: number; skill_dirs: string[] };
  llama: {
    server: string; model_dirs: string[]; port: number; ctx: number; ngl: number;
    per_model: Record<string, ModelLaunch>;
    hardware: { vram_gb?: number | null; ram_gb?: number | null; gpu_name?: string; bandwidth_gbs?: number | null };
    hf_token: string;
    download_dir: string;
    autostart: boolean;
    last?: { model?: string; options?: ModelLaunch };
    last_by_server?: Record<string, { model?: string; options?: ModelLaunch }>;
    autostart_on_task?: boolean;
    servers: LocalServerCfg[];
  };
  agent_defaults: { provider: string; model: string; role: string; max_turns: number | null; max_budget_usd: number | null };
  mcp_servers: Record<string, McpServer>;
}

/** Arranque propio de un GGUF (vacío = valores generales). Claves = llama.OPTION_FLAGS / BOOL_FLAGS. */
export interface ModelLaunch {
  ctx?: number | null;
  ngl?: number | null;
  extra?: string;
  flash_attn?: "auto" | "on" | "off";
  cache_k?: string;
  cache_v?: string;
  threads?: number | null;
  batch?: number | null;
  ubatch?: number | null;
  parallel?: number | null;
  n_cpu_moe?: number | null;
  temp?: number | null;
  top_p?: number | null;
  top_k?: number | null;
  min_p?: number | null;
  repeat_penalty?: number | null;
  reasoning_budget?: number | null;
  mlock?: boolean;
  no_mmap?: boolean;
  // varias GPU: en cuáles (-dev CUDA0,CUDA1), cómo repartir (-sm), proporción (-ts 2,1) y la principal (-mg)
  device?: string;
  split_mode?: "layer" | "row" | "none" | "";
  tensor_split?: string;
  main_gpu?: number | null;
}

/** Un llama-server de los que puede tener encendidos LocalHarness a la vez (normalmente uno por GPU). */
export type ServerRole = "general" | "fuerte" | "rapido";
export interface LocalServerCfg {
  id: string;
  name: string;
  port: number;
  device: string; // -dev de llama.cpp: CUDA0, CUDA1, CUDA0,CUDA1… ("" = lo decide llama.cpp)
  role: ServerRole;
  thinking?: "normal" | "apagado" | "profundo"; // en cada encargo (apagado = contesta al momento)
}
export interface LocalServer extends LocalServerCfg {
  url: string;
  status: LlamaStatus;
  model_name: string | null;
}
/** Una GPU tal como la numera llama.cpp (no coincide con el índice de nvidia-smi). */
export interface LlamaDevice {
  id: string;
  name: string;
  total_mb: number;
  free_mb: number;
}
export const SERVER_ROLE_TEXT: Record<ServerRole, string> = {
  general: "de todo", fuerte: "escribe código y tareas enteras", rapido: "preguntas, resúmenes e investigar",
};
export const SERVER_ROLE_LABEL: Record<ServerRole, string> = { general: "General", fuerte: "Fuerte", rapido: "Rápido" };

export interface Budget {
  gpu: string | null;
  vram_gb: number;
  usable_vram_gb: number;
  ram_gb: number;
  usable_ram_gb: number;
  bandwidth_gbs: number;
  manual: boolean;
}

export interface Hardware {
  gpus: { name: string; vendor: string; vram_gb: number | null; vram_used_gb: number | null; vram_free_gb: number | null; driver: string | null; backend: string }[];
  cpu: string | null;
  cores: number | null;
  os: string | null;
  ram_gb: number | null;
  ram_free_gb: number | null;
  budget: Budget;
}

export type Fit = "gpu" | "mixto" | "cpu" | "no";

export interface Estimate {
  ctx: number;
  weights_gb: number;
  weights_gpu_gb: number;
  weights_cpu_gb: number;
  kv_gb: number;
  kv_gpu_gb?: number;
  overhead_gb: number;
  vram_gb: number;
  ram_gb: number;
  tps_est?: number | null;
  fit?: Fit;
  vram_free_after_gb?: number;
}

export interface Probe {
  at: number;
  tool_calls: boolean | null;
  tool_detail?: string;
  json: boolean | null;
  tps?: number;
  prompt_tps?: number;
  error?: string;
}

export interface ModelRating {
  meta: Record<string, any> & { error?: string; arch?: string; ctx_train?: number; params_b?: number; moe?: boolean; tools_in_template?: boolean; thinking?: boolean; n_layer?: number };
  rating?: {
    score: number;
    verdict: string;
    reasons: string[];
    roles: string[];
    parts: { tools: number; fit: number; quality: number; speed: number };
    suggested: { options: ModelLaunch; estimate: Estimate; why?: string };
  };
  probe?: Probe | null;
  catalog?: { id: string; name: string; repo: string; notes: string; agentic: number; sampling?: Record<string, number> } | null;
  last_launch?: { options: ModelLaunch; at: number } | null;
}

export interface Recommendation {
  id: string;
  name: string;
  repo: string;
  url: string;
  params_b: number;
  active_b: number;
  moe: boolean;
  ctx_train: number;
  agentic: number;
  tools: boolean;
  thinking: boolean;
  tags: string[];
  roles: string[];
  notes: string;
  fit: Fit;
  score: number;
  downloaded: boolean;
  hf_checked: boolean;
  best: null | { quant: string; size_gb: number; files: string[]; exact: boolean; options: ModelLaunch; estimate: Estimate; why?: string };
  quants: { quant: string; size_gb: number; exact: boolean; files: string[] }[];
}

export interface DownloadJob {
  id: string;
  repo: string;
  files: string[];
  dest: string;
  state: "queued" | "downloading" | "done" | "failed" | "cancelled";
  done: number;
  total: number;
  speed: number;
  error: string | null;
  path: string | null;
}

/** Velocidad de un modelo local: en vivo (evento speed) o la última medida. */
export interface Speed {
  tps: number | null;
  tokens?: number;
  phase?: string;
  model?: string | null;
  at: number;
  final?: boolean;
  src?: "worker"; // de un encargo de Claude a un modelo local (los suma `live.localWork`, no esto)
}

/** Lo que hace AHORA (o lo último que hizo) cada modelo local con los encargos de un Claude que delega. */
export interface LocalWork {
  server: string; task_id: number; tool?: string; task?: string; thinking: string; text: string;
  tps?: number | null; tokens?: number | null; model?: string | null; done: boolean; at: number; started: number;
}

export interface LocalModel {
  name: string;
  file: string;
  path: string;
  dir: string;
  size_gb: number;
  quant: string | null;
  vision?: boolean;
}

export interface LlamaStatus {
  state: "off" | "loading" | "ready" | "failed" | "external";
  model: string | null;
  port: number;
  device?: string | null;
  pid: number | null;
  started_at: number | null;
  exit_code: number | null;
  log: string;
  log_lines: string[];
  progress?: { pct: number | null; stage: string; source?: string | null; eta_s?: number } | null;
}

export interface LlamaInfo {
  server: string | null;
  dirs: string[];
  models: LocalModel[];
  status: LlamaStatus;
  config: Settings["llama"];
  servers: LocalServer[];
  devices: LlamaDevice[];
  suggested_servers: LocalServerCfg[] | null;
  roles: ServerRole[];
  speed: Speed | null;
  load_times: Record<string, number>;
  strays?: { pid: number; port: number | null; model: string | null }[]; // llama-server sueltos (no de esta sesión)
}

/** Selector nativo del PC (el servidor es local). null si se cancela; lanza error si no hay escritorio. */
export async function pickPath(kind: "folder" | "file" = "folder", title?: string): Promise<string | null> {
  return (await post<{ path: string | null }>("/api/pick", { kind, title })).path;
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
  speed: {} as Record<number, Speed>,          // tokens/s en vivo por tarea (modelos locales)
  thinking: {} as Record<number, { text: string; at: number; live: boolean }>, // último pensamiento por tarea
  local: { state: "off", model: null } as { state: string; model: string | null }, // el modelo ARRANCADO (principal)
  locals: [] as LocalLive[], // todos los servidores locales (con dos GPU, normalmente dos modelos a la vez)
  lastSpeed: null as Speed | null,
  localWork: {} as Record<string, LocalWork>, // id del servidor local → su encargo en curso o el último
});

export interface LocalLive {
  id: string;
  name: string;
  role: ServerRole;
  device: string;
  port: number;
  state: string;
  model: string | null;
}

/** Los modelos locales que responden ahora (encendidos), para enseñarlos juntos: «Qwen3.5-9B + Qwen3.5-4B». */
export function localModelsText(empty = "ningún modelo arrancado"): string {
  const on = live.locals.filter((l) => l.state !== "off" && l.model);
  if (!on.length) return live.local.model ?? empty;
  return on.length === 1 ? on[0].model! : on.map((l) => `${l.model} (${l.name})`).join(" + ");
}

/** Solo /api/health: estado de los modelos locales (lo usan las vistas que lo enseñan, cada pocos segundos). */
export async function refreshLocals(): Promise<void> {
  const h = await api<{ local: typeof live.local; locals?: LocalLive[] }>("/api/health");
  live.local = h.local ?? live.local;
  live.locals = h.locals ?? [];
}

type Handler = (ev: TaskEvent) => void;
const eventHandlers = new Set<Handler>();

/** Suscribe a los eventos de ejecución de todas las tareas; devuelve la baja. */
/** Guarda una tarea recién creada SIN pisar lo que ya trajo el directo: el aviso «running» puede llegar antes que la
 *  respuesta del POST (que aún dice «pending»), y entonces la tarea se quedaría pendiente en la pantalla. */
export function putTask(t: Task): void {
  const cur = live.tasks[t.id];
  if (cur && t.status === "pending" && cur.status !== "pending") return;
  live.tasks[t.id] = t;
}

export function onTaskEvent(fn: Handler): () => void {
  eventHandlers.add(fn);
  return () => eventHandlers.delete(fn);
}

const DOWN = "El servidor de LocalHarness no responde. ¿Sigue abierta la ventana de «python -m localharness serve» "
  + "y sin errores? Ábrelo y entra por http://127.0.0.1:8095";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new Error(DOWN);
  }
  if (r.status === 204) return undefined as T;
  const body = await r.json().catch(() => null);
  // sin JSON de FastAPI = no ha contestado LocalHarness sino algo intermedio (el servidor de desarrollo de Vite o un
  // proxy) porque el servidor de Python no está en marcha o se ha caído
  if (!r.ok && body?.detail === undefined && [502, 503, 504].includes(r.status)) throw new Error(`${DOWN} (HTTP ${r.status})`);
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
    api<{ limit: Limit | null; local: typeof live.local; locals?: LocalLive[]; speed: Speed | null }>("/api/health"),
  ]);
  live.projects = projects;
  live.agents = agents;
  live.tasks = Object.fromEntries(tasks.map((t) => [t.id, t]));
  live.plans = Object.fromEntries(plans.map((p) => [p.id, p]));
  live.limit = health.limit;
  live.local = health.local ?? live.local;
  live.locals = health.locals ?? [];
  live.lastSpeed = health.speed ? { ...health.speed, at: health.speed.at * 1000 } : null;
  await Promise.all([refreshInbox(), refreshActivity()]);
}

/** Qué está haciendo cada tarea en marcha y las últimas terminadas (con sus archivos). */
export async function refreshActivity(): Promise<void> {
  const a = await api<{
    current: Record<string, TaskEvent & { ts: string }>; recent: RecentTask[];
    thinking?: Record<string, { text: string; ts: string }>;
  }>("/api/activity");
  for (const [tid, ev] of Object.entries(a.current)) {
    live.activity[Number(tid)] = { kind: ev.kind, text: ev.text, data: ev.data, at: parseTs(ev.ts) };
  }
  for (const [tid, th] of Object.entries(a.thinking ?? {})) {
    live.thinking[Number(tid)] = { text: th.text, at: parseTs(th.ts), live: false };
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
    if (ev.kind === "thinking" || ev.kind === "thinking_live") {
      live.thinking[ev.task_id] = { text: ev.text, at: Date.now(), live: ev.kind === "thinking_live" };
    }
    if (["text", "tool", "status", "context", "progress", "thinking"].includes(ev.kind)) {
      live.activity[ev.task_id] = { kind: ev.kind, text: ev.text, data: ev.data ?? {}, at: Date.now() };
    }
    // velocidad: la de un agente local (speed/usage) y la de los encargos de un Claude que delega (worker_live
    // mientras el modelo local escribe, delegate al acabar)
    const delegated = (ev.kind === "worker_live" || ev.kind === "delegate") && !!ev.data?.tps;
    if (ev.kind === "speed" || (ev.kind === "usage" && ev.data?.local && ev.data?.tps) || delegated) {
      const fin = ev.kind === "usage" || ev.kind === "delegate" || (ev.kind === "worker_live" && !!ev.data?.done);
      const sp: Speed = { ...(ev.data as unknown as Speed), at: Date.now(), final: fin, src: delegated ? "worker" : undefined };
      if (ev.kind === "speed" || (ev.kind === "worker_live" && !fin)) live.speed[ev.task_id] = sp;
      live.lastSpeed = sp;
    }
    // cada modelo local por separado: con dos GPU, los dos pueden estar con un encargo a la vez
    if (ev.kind === "worker_live") {
      const d = (ev.data ?? {}) as Record<string, unknown>;
      const srv = String(d.server ?? "principal");
      const prev = live.localWork[srv];
      const same = prev && !prev.done && prev.task_id === ev.task_id && prev.task === d.task && prev.tool === d.tool;
      live.localWork[srv] = {
        server: srv, task_id: ev.task_id, tool: d.tool as string | undefined, task: d.task as string | undefined,
        thinking: String(d.thinking ?? ""), text: String(d.text ?? ""), tps: (d.tps as number | null) ?? prev?.tps ?? null,
        tokens: d.tokens as number | null, model: (d.model as string | null) ?? prev?.model ?? null, done: !!d.done,
        at: Date.now(), started: same ? prev.started : Date.now(),
      };
    }
    if (ev.kind === "delegate" && ev.data?.server && live.localWork[String(ev.data.server)]) {
      const w = live.localWork[String(ev.data.server)];
      if (w.task_id === ev.task_id) Object.assign(w, { done: true, tps: (ev.data.tps as number) ?? w.tps, model: (ev.data.model as string) ?? w.model });
    }
    if (ev.kind === "session" && ev.data?.base_url && ev.data?.model) {
      live.local = { state: "ready", model: String(ev.data.model) };
    }
    if (ev.kind === "status" && ev.text !== "running") {
      delete live.speed[ev.task_id];
      delete live.thinking[ev.task_id];
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
  // sin fecha (0 o vacía) no se pinta nada: salía «hace 20714 días» (desde 1970)
  if (Number.isNaN(ms) || ms <= 0) return "";
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
  consultas: "Consultas",
};

const ROLE_HEX: Record<string, string> = {
  director: "#5b5bf0", jefe: "#10b981", trabajador: "#f97316", consultas: "#0ea5e9",
};
const EXTRA_HEX = ["#8b5cf6", "#ec4899", "#14b8a6", "#eab308", "#06b6d4", "#f43f5e", "#84cc16"];

export function roleColor(a: Agent | undefined): string {
  return agentColor(a);
}

/** Color fijo de un agente (oficina 3D, avatares): el de su rol; sin rol conocido, uno de la paleta por id. */
export function agentColor(a: Agent | undefined): string {
  if (!a) return "#868b96";
  return ROLE_HEX[a.role ?? ""] ?? EXTRA_HEX[a.id % EXTRA_HEX.length];
}

export const PROVIDER_TEXT: Record<string, string> = {
  claude: "Suscripción", local: "Local · GPU", local_agent: "Local · agente", local_boss: "Local · jefe", codex: "Codex", human: "Humano",
};

/** Qué modelo usa de verdad: los locales, el que esté arrancado en llama-server. */
export function modelText(a: Agent): string {
  if (a.provider.startsWith("local")) {
    const srv = a.config?.server ? live.locals.find((l) => l.id === a.config.server) : null;
    if (srv) return srv.model ? `${srv.model} (${srv.name})` : `${srv.name}: apagado`;
    return live.local.model ? `${live.local.model} (arrancado)` : "ningún modelo arrancado";
  }
  return [a.provider === "claude" ? "Claude" : a.provider, a.model].filter(Boolean).join(" ");
}

// --- estado de la interfaz compartido entre vistas (el Catálogo se abre desde cualquier página)
export const ui = reactive({
  catalog: null as null | { tab: "agents" | "skills" | "mcp"; open?: number | null },
  focusAgent: null as number | null, // la oficina enfoca este agente al abrirse
  wizard: null as null | { agentId?: number; template?: string }, // asistente de agentes (crear o editar)
});

/** Abre el asistente de agentes: sin id crea uno nuevo (opcionalmente con una plantilla); con id lo edita. */
export function openWizard(agentId?: number, template?: string): void {
  ui.wizard = { agentId, template };
}

export function openCatalog(tab: "agents" | "skills" | "mcp" = "agents", open: number | null = null): void {
  ui.catalog = { tab, open };
}

/** Frase corta de lo que está haciendo un agente a partir de su último evento. */
export function describeActivity(a: Activity | undefined): string {
  if (!a) return "arrancando…";
  if (a.kind === "progress") return a.text;
  if (a.kind === "thinking") return "Pensando…";
  if (a.kind === "tool") {
    const input = (a.data.input ?? {}) as Record<string, unknown>;
    const target = String(input.file_path ?? input.pattern ?? input.command ?? input.path ?? input.ruta ?? input.url ?? input.consulta ?? input.comando ?? input.pregunta ?? input.texto ?? "");
    const short = target.split(/[\\/]/).slice(-2).join("/");
    if (a.text === "mcp__local__local_ask") return `Encargando al modelo local: ${String(input.task ?? "").slice(0, 110)}`;
    if (a.text === "mcp__local__local_write_file") return `El modelo local escribe ${String(input.path ?? "")}`;
    if (a.text === "mcp__local__local_agent") return `Encarga al agente local: ${String(input.task ?? "").slice(0, 110)}`;
    if (a.text === "mcp__local__run_checks") return `Comprueba: ${String(input.command ?? "")}`;
    if (a.text === "mcp__local__local_research") return `El modelo local investiga en la web: ${String(input.question ?? "").slice(0, 100)}`;
    const verb: Record<string, string> = {
      Read: "Leyendo", Edit: "Editando", Write: "Escribiendo", MultiEdit: "Editando",
      Grep: "Buscando", Glob: "Buscando archivos", Bash: "Ejecutando",
      leer_archivo: "Leyendo", listar: "Mirando", buscar_texto: "Buscando", escribir_archivo: "Escribiendo",
      buscar_web: "Buscando en la web:", leer_url: "Leyendo la página", ejecutar: "Ejecutando",
      preguntar_director: "Preguntando al Director:",
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

export function tps(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${v.toFixed(v < 10 ? 1 : 0)} tok/s`;
}

/** Frase de velocidad para la burbuja «escribiendo…» y las tarjetas: «pensando · 42 tok/s · 310 tokens». */
export function speedText(sp: Speed | undefined): string {
  if (!sp) return "";
  return [sp.phase, tps(sp.tps), sp.tokens ? `${sp.tokens} tokens` : null].filter(Boolean).join(" · ");
}
