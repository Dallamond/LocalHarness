<script setup lang="ts">
import { computed, nextTick, onUnmounted, reactive, ref, watch, watchEffect } from "vue";
import { useRouter } from "vue-router";
import AgentAvatar from "../components/AgentAvatar.vue";
import Markdown from "../components/Markdown.vue";
import StatusChip from "../components/StatusChip.vue";
import {
  ROLE_TEXT, STATUS_TEXT, agentName, ago, api, live, onTaskEvent, parseTs, pickPath, post, projectName, putTask,
  refreshAll, speedText, statusChip, taskList, usd, localModelsText,
  type Plan, type Project, type Review, type Skill, type Task, type TaskEvent, THINKING_TEXT
} from "../api";

const props = defineProps<{ id?: number }>();
const router = useRouter();

// --- lista de conversaciones (tareas sueltas; las subtareas de planes viven en su plan)
const conversations = computed(() => taskList.value.filter((t) => t.plan_id == null));
const task = computed<Task | undefined>(() => (props.id ? live.tasks[props.id] : undefined));
const agent = computed(() => live.agents.find((a) => a.id === task.value?.agent_id));
// un agente local responde con el modelo ARRANCADO en llama-server, se llame como se llame
const localModel = computed(() => (agent.value?.provider?.startsWith("local") ? live.local.model : null));
const speed = computed(() => (task.value ? live.speed[task.value.id] : undefined));

const CLOSED = ["merged", "rejected", "discarded"];
const busy = computed(() => !!task.value && ["running", "pending"].includes(task.value.status));
const closed = computed(() => !!task.value && CLOSED.includes(task.value.status));

// --- mensajes: la petición inicial + los eventos de la tarea, agrupados para leerse como un chat
const events = ref<TaskEvent[]>([]);
const error = ref("");
const scroller = ref<HTMLElement | null>(null);

type Msg =
  | { type: "user"; text: string }
  | { type: "agent"; text: string }
  | { type: "tools"; items: { name: string; target: string }[] }
  | { type: "note"; text: string; tone: "ok" | "warn" | "crit" | "dim" }
  | { type: "delegate"; ok: boolean; what: string; tool: string; detail: string; thinking: string; answer: string; request: string; skills: string[]; to: Worker; step: string; boss: boolean }
  | { type: "plan"; label: string; by: Worker; blocks: PlanBlock[] }
  | { type: "thinking"; text: string; local?: boolean };

// --- chat de grupo: el jefe (Claude o el jefe local) y cada modelo local, por su servidor
type Worker = { id: string; name: string; model: string; tone: "fuerte" | "rapido" | "otro" };
type PlanBlock = { id: string; kind: string; path: string; title: string; after: string[]; to?: Worker; ok?: boolean; seconds?: number; tps?: number };
const TONE_EMOJI = { fuerte: "🦙", rapido: "⚡", otro: "🤖" } as const;
function workerOf(id: unknown, model?: unknown): Worker {
  const sid = String(id ?? "principal");
  const srv = live.locals.find((l) => l.id === sid);
  const tone = srv?.role === "rapido" || sid === "rapido" ? "rapido" : srv?.role === "fuerte" || sid === "principal" ? "fuerte" : "otro";
  return { id: sid, name: srv?.name ?? (sid === "principal" ? "Principal" : sid), tone,
           model: String(model ?? srv?.model ?? "").replace(/\.gguf$/i, "") };
}
const BOSS_STEP: Record<string, string> = {
  elegir_archivos: "elige qué archivos hay que leer", revisar: "revisa el diff contra el encargo",
  proponer_parches: "propone los parches siguientes",
};
function bossStep(tool: string): string {
  const step = tool.replace(/^jefe_local\//, "");
  const m = step.match(/^planificar \((.+)\)$/);
  return m ? `planifica (${m[1].toLowerCase()})` : BOSS_STEP[step] ?? step;
}
function stepOf(tool: string, d: Record<string, unknown>): string {
  if (tool.startsWith("local_execute_plan/")) return `bloque ${d.block ?? ""} · ${tool.split("/")[1] === "edit" ? "editar" : tool.split("/")[1] === "write" ? "escribir" : "pregunta"}`;
  return { local_ask: "pregunta", local_write_file: "escribir", local_edit_file: "editar", local_agent: "tarea con herramientas",
           local_research: "investigar en la web", local_plan: "planificar", local_map: "mapa del repo",
           local_read_documents: "leer documentos", local_look: "mirar la página" }[tool] ?? tool.replace(/^local_/, "");
}
const bossName = computed(() => agent.value?.name ?? "El jefe");
const bossKind = computed(() => (agent.value?.provider === "local_boss" ? "jefe local" : agent.value?.provider === "claude" ? "Claude" : "jefe"));

const TERMINAL = new Set(["review", "done", "failed", "timeout", "cancelled", "interrupted", "merged", "rejected"]);

const messages = computed<Msg[]>(() => {
  if (!task.value) return [];
  const out: Msg[] = [{ type: "user", text: task.value.prompt }];
  let currentPlan: Extract<Msg, { type: "plan" }> | null = null;
  let spoke = false; // el agente ya habló desde tu último mensaje (para no duplicar con `result`)
  for (const e of events.value) {
    const last = out[out.length - 1];
    if (e.kind === "user") {
      out.push({ type: "user", text: e.text });
      spoke = false;
    } else if (e.kind === "text" && e.text.trim()) {
      if (last.type === "agent") last.text += "\n\n" + e.text;
      else out.push({ type: "agent", text: e.text });
      spoke = true;
    } else if (e.kind === "result" && e.text && !spoke) {
      out.push({ type: "agent", text: e.text });
      spoke = true;
    } else if (e.kind === "tool") {
      const input = (e.data?.input ?? {}) as Record<string, unknown>;
      const item = { name: e.text || "herramienta", target: String(input.file_path ?? input.pattern ?? input.command ?? input.path ?? input.ruta ?? input.url ?? input.consulta ?? input.comando ?? input.pregunta ?? input.texto ?? "") };
      if (last.type === "tools") last.items.push(item);
      else out.push({ type: "tools", items: [item] });
    } else if (e.kind === "error") {
      out.push({ type: "note", text: e.text, tone: "crit" });
    } else if (e.kind === "thinking") {
      out.push({ type: "thinking", text: e.text });
    } else if (e.kind === "ask_director") {
      out.push({ type: "note", text: `❓ Pregunta al Director: ${e.text}`, tone: "warn" });
    } else if (e.kind === "director_answer") {
      out.push({ type: "note", text: `🧭 Director: ${e.text}`, tone: "ok" });
    } else if (e.kind === "progress") {
      out.push({ type: "note", text: `📣 ${e.text}`, tone: "ok" });
    } else if (e.kind === "warning") {
      out.push({ type: "note", text: e.text, tone: "warn" });
    } else if (e.kind === "worker") {
      const d = e.data as Record<string, unknown>;
      out.push({ type: "note", text: `🧰 ${e.text}${d.reason ? ` — «${d.reason}»` : ""}`, tone: "dim" });
    } else if (e.kind === "worker_thinking") {
      out.push({ type: "thinking", text: e.text, local: true });
    } else if (e.kind === "delegate") {
      const d = e.data as Record<string, unknown>;
      const tool = String(d.tool ?? "");
      if (tool === "local_prepare") continue; // lo cuenta el evento `worker`
      if (tool === "local_execute_plan") {
        const good = Number(d.blocks_ok ?? (typeof d.ok === "number" ? d.ok : NaN));
        out.push({ type: "note", tone: "ok", text: `📋 Plan ejecutado: ${Number.isFinite(good) ? `${good} de ${d.blocks} bloques bien` : d.task ?? "terminado"}`
          + `${Number(d.parallel ?? 0) > 1 ? ` · hasta ${d.parallel} a la vez` : ""}${d.plan_seconds ? ` · ${d.plan_seconds} s` : ""}` });
        continue;
      }
      if (tool === "run_checks") {
        const exit = String(d.exit ?? "");
        out.push({ type: "note", tone: exit.endsWith(" 0") ? "ok" : "warn",
                   text: `🧪 Tests (${d.task ?? ""}): ${exit === "código de salida 0" ? "pasan" : exit || (d.ok ? "ejecutados" : String(d.error ?? "no se pudieron lanzar"))}` });
        continue;
      }
      const to = workerOf(d.server, d.model);
      if (tool.startsWith("jefe_local/planificar") && Array.isArray(d.plan)) {
        currentPlan = { type: "plan", label: bossStep(tool), by: to, blocks: (d.plan as PlanBlock[]).map((b) => ({ ...b, after: b.after ?? [] })) };
        out.push(currentPlan);
      }
      if (currentPlan && tool.startsWith("local_execute_plan/") && d.block != null) {
        const b = currentPlan.blocks.find((x) => x.id === String(d.block));
        if (b) Object.assign(b, { to, ok: !!d.ok, seconds: Number(d.gen_seconds ?? d.seconds ?? 0) || undefined, tps: Number(d.tps ?? 0) || undefined });
      }
      const toks = Number(d.completion_tokens ?? 0);
      const boss = tool.startsWith("jefe_local/");
      out.push({
        type: "delegate", ok: !!d.ok, tool, to, boss, step: boss ? bossStep(tool) : stepOf(tool, d),
        what: boss ? "" : String(d.path ?? d.task ?? ""),
        detail: d.ok
          ? [toks ? `${toks} tokens` : null, d.tps ? `${d.tps} tok/s` : null, d.gen_seconds ?? d.seconds ? `${d.gen_seconds ?? d.seconds} s` : null]
              .filter(Boolean).join(" · ")
          : String(d.error ?? "falló"),
        thinking: String(d.thinking ?? ""), answer: String(d.answer ?? ""), request: String(d.request ?? ""),
        skills: (d.skills as string[] | undefined) ?? [],
      });
    } else if (e.kind === "delegate_summary") {
      const d = e.data as Record<string, unknown>;
      out.push({ type: "note", text: `🦙 ${e.text} · ${d.local_tokens ?? 0} tokens hechos gratis en local`, tone: "ok" });
    } else if (e.kind === "context") {
      out.push({ type: "note", text: `Contexto cargado: ${e.text}`, tone: "dim" });
    } else if (e.kind === "status" && TERMINAL.has(e.text)) {
      const tone = e.text === "review" || e.text === "done" || e.text === "merged" ? "ok" : e.text === "failed" || e.text === "timeout" ? "crit" : "dim";
      out.push({ type: "note", text: STATUS_TEXT[e.text as keyof typeof STATUS_TEXT] ?? e.text, tone });
    }
  }
  return out;
});

const openTools = reactive<Record<number, boolean>>({});

// --- los participantes: el jefe y cada modelo local que ha trabajado o está arrancado; quién tiene la pelota
type Party = { key: string; name: string; sub: string; tone: string; emoji: string; n: number; bad: number; tokens: number; seconds: number; ball: boolean; doing: string };
const party = computed<Party[]>(() => {
  const ws: Record<string, Party> = {};
  const add = (w: Worker) => (ws[w.id] ??= { key: w.id, name: w.name, sub: w.model || "modelo local", tone: w.tone, emoji: TONE_EMOJI[w.tone], n: 0, bad: 0, tokens: 0, seconds: 0, ball: false, doing: "" });
  for (const l of live.locals) if (l.state === "ready" || l.state === "external") add(workerOf(l.id, l.model));
  for (const e of events.value) {
    const d = e.data as Record<string, unknown> | undefined;
    if (e.kind !== "delegate" || !d || !d.server) continue;
    const r = add(workerOf(d.server, d.model));
    r.n++;
    if (!d.ok) r.bad++;
    r.tokens += Number(d.completion_tokens ?? 0);
    r.seconds += Number(d.gen_seconds ?? 0);
  }
  let bossThinking = "";
  for (const w of liveNow.value) {
    const r = add(workerOf(w.server));
    r.ball = true;
    r.doing = String(w.tool ?? "").startsWith("jefe_local/") ? `piensa para el jefe: ${bossStep(String(w.tool))}` : `${stepOf(String(w.tool ?? ""), {})}: ${w.task ?? ""}`;
    if (String(w.tool ?? "").startsWith("jefe_local/")) bossThinking = r.doing;
  }
  const workers = Object.values(ws);
  const boss: Party = {
    key: "jefe", name: bossName.value, sub: bossKind.value, tone: "jefe", emoji: "🧭", n: 0, bad: 0, tokens: 0, seconds: 0,
    ball: busy.value && (!workers.some((w) => w.ball) || !!bossThinking),
    doing: bossThinking || (busy.value && !workers.some((w) => w.ball) ? "organiza, reparte o pasa los tests" : ""),
  };
  return [boss, ...workers];
});
const ball = computed(() => {
  if (!task.value) return "";
  if (busy.value) {
    const now = party.value.filter((p) => p.ball && p.key !== "jefe");
    if (now.length) return `🏀 Tiene la pelota: ${now.map((p) => `${p.name} (${p.doing.slice(0, 80)})`).join(" y ")}`;
    return `🏀 Tiene la pelota: ${bossName.value} — ${party.value[0].doing}`;
  }
  if (task.value.status === "review") return "🏀 Te toca a ti: revisa los cambios y aprueba, rechaza o pide algo más";
  return "";
});
// filtro: seguir solo a un participante (clic en su ficha)
const who = ref("todo");
watch(() => props.id, () => (who.value = "todo"));
function shown(m: Msg): boolean {
  if (who.value === "todo") return true;
  if (who.value === "jefe") return m.type !== "delegate" || m.boss;
  return (m.type === "delegate" && m.to.id === who.value) || m.type === "plan" || m.type === "user";
}
// la lista de conversaciones se pliega para dar todo el ancho al chat
const listOpen = ref(!props.id);

function toBottom() {
  nextTick(() => scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: "smooth" }));
}

const review = ref<Review | null>(null);
const acting = ref(false);

async function load() {
  events.value = [];
  review.value = null;
  error.value = "";
  if (!props.id) return;
  try {
    const [t, evs] = await Promise.all([
      api<Task>(`/api/tasks/${props.id}`),
      api<TaskEvent[]>(`/api/tasks/${props.id}/events`),
    ]);
    live.tasks[t.id] = t;
    const seen = new Set(evs.map((e) => e.id));
    events.value = [...evs, ...events.value.filter((e) => e.id == null || !seen.has(e.id))];
    await loadReview();
    toBottom();
  } catch (e) {
    error.value = (e as Error).message;
  }
}

// cada modelo local pensando/escribiendo AHORA (eventos `worker_live`, no se guardan): uno por servidor
type LiveWork = { server?: string; tool?: string; task?: string; thinking: string; text: string; done: boolean; at: number; tps?: number | null };
const liveBy = reactive<Record<string, LiveWork>>({});
const liveNow = computed(() => (busy.value ? Object.values(liveBy).filter((w) => !w.done) : []));
watch(() => props.id, () => { for (const k of Object.keys(liveBy)) delete liveBy[k]; });
const off = onTaskEvent((ev) => {
  if (ev.task_id !== props.id) return;
  if (ev.kind === "worker_live") {
    const w = ev.data as unknown as LiveWork;
    liveBy[String(w.server ?? "principal")] = w;
    toBottom();
    return;
  }
  if (ev.id != null && events.value.some((e) => e.id === ev.id)) return;
  events.value.push(ev);
  toBottom();
});
onUnmounted(off);
watch(() => props.id, load, { immediate: true });

// --- cambios y decisión cuando el agente termina (review se declara arriba: load() la usa al montar)

async function loadReview() {
  const t = props.id ? live.tasks[props.id] : undefined;
  review.value = t && t.worktree && ["review", "approved"].includes(t.status)
    ? await api<Review>(`/api/tasks/${t.id}/review`)
    : null;
}
watch(() => task.value?.status, (s, prev) => {
  if (prev && s !== prev) loadReview().catch(() => {});
});

async function act(path: string, body: unknown = {}, question?: string) {
  if (!task.value || (question && !window.confirm(question))) return;
  acting.value = true;
  error.value = "";
  try {
    const t = await post<Task>(`/api/tasks/${task.value.id}/${path}`, body);
    live.tasks[t.id] = { ...live.tasks[t.id], ...t };
    await loadReview();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    acting.value = false;
  }
}

// --- escribir: respuesta en la conversación o conversación nueva
const draft = ref("");
const sending = ref(false);
const mode = ref<"agent" | "team">("agent");
const form = reactive({ project_id: 0, agent_id: 0, director_agent_id: 0, reviewer_agent_id: 0, skills: [] as string[], thinking: "" });

// M5: skills para esta conversación (se suman a las que el agente ya lleva siempre)
const skills = ref<Skill[]>([]);
const showSkills = ref(false);
api<Skill[]>("/api/skills").then((s) => (skills.value = s)).catch(() => {});
const agentThinking = computed(() => live.agents.find((a) => a.id === form.agent_id)?.config.thinking ?? "");
const agentSkills = computed(() => live.agents.find((a) => a.id === form.agent_id)?.config.skills ?? []);

watchEffect(() => {
  if (!form.project_id && live.projects.length) form.project_id = live.projects[live.projects.length - 1].id;
  if (!form.agent_id && live.agents.length) {
    form.agent_id = (live.agents.find((a) => a.role === "trabajador") ?? live.agents[0]).id;
  }
  if (!form.director_agent_id && live.agents.length) {
    form.director_agent_id = (live.agents.find((a) => a.role === "director") ?? live.agents[0]).id;
  }
  if (!form.reviewer_agent_id && live.agents.length) form.reviewer_agent_id = live.agents.find((a) => a.role === "jefe")?.id ?? 0;
});
const chosen = computed(() => live.agents.find((a) => a.id === (mode.value === "agent" ? form.agent_id : form.director_agent_id)));

async function send() {
  const text = draft.value.trim();
  if (!text) return;
  sending.value = true;
  error.value = "";
  try {
    if (task.value) {
      await post(`/api/tasks/${task.value.id}/reply`, { message: text });
    } else if (mode.value === "team") {
      const p = await post<Plan>("/api/plans", {
        project_id: form.project_id, director_agent_id: form.director_agent_id,
        reviewer_agent_id: form.reviewer_agent_id || null, request: text,
      });
      router.push(`/planes/${p.id}`);
    } else {
      const t = await post<Task>("/api/tasks", {
        project_id: form.project_id, agent_id: form.agent_id, prompt: text,
        skills: form.skills.filter((n) => !agentSkills.value.includes(n)),
        thinking: form.thinking || null,
      });
      form.skills = [];
      putTask(t);
      router.push(`/chat/${t.id}`);
    }
    draft.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    sending.value = false;
  }
}

function onKey(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    send();
  }
}

// --- vincular carpeta (proyecto) desde el propio chat
const linking = ref(false);
const link = reactive({ path: "", name: "", init_git: false });
const linkError = ref("");

async function choose() {
  linkError.value = "";
  try {
    const p = await pickPath("folder", "Carpeta del proyecto");
    if (p) setPath(p);
  } catch (e) {
    linkError.value = `${(e as Error).message}. Escribe la ruta a mano.`;
  }
}
function setPath(p: string) {
  link.path = p;
  if (!link.name) link.name = p.replace(/[\\/]+$/, "").split(/[\\/]/).pop() ?? "";
}
async function doLink() {
  linkError.value = "";
  try {
    const p = await post<Project>("/api/projects", { name: link.name, repo_path: link.path, init_git: link.init_git });
    await refreshAll();
    form.project_id = p.id;
    linking.value = false;
    Object.assign(link, { path: "", name: "", init_git: false });
  } catch (e) {
    linkError.value = (e as Error).message;
  }
}

const placeholder = computed(() => {
  if (!task.value) return mode.value === "team" ? "Qué quieres conseguir; el Director lo reparte…" : "Qué tiene que hacer el agente…";
  if (busy.value) return "El agente está trabajando…";
  if (closed.value) return "Conversación cerrada";
  return "Responde o pide algo más (Enter envía, Mayús+Enter salto de línea)";
});
</script>

<template>
  <div class="chat" :class="{ 'chat--wide': !listOpen }">
    <!-- conversaciones (plegable: así el chat de grupo usa toda la pantalla) -->
    <aside v-if="listOpen" class="list">
      <RouterLink to="/chat" class="btn btn--primary new">+ Nueva conversación</RouterLink>
      <p v-if="!conversations.length" class="muted small pad">Aún no hay conversaciones.</p>
      <RouterLink
        v-for="t in conversations" :key="t.id" :to="`/chat/${t.id}`" class="conv"
        :class="{ 'conv--on': t.id === id }"
      >
        <span class="conv__title">{{ t.title }}</span>
        <span class="conv__meta">
          <StatusChip :state="statusChip(t.status)" :text="STATUS_TEXT[t.status] ?? t.status" />
          <span class="muted small">{{ agentName(t.agent_id) }} · {{ ago(parseTs(t.created_at)) }}</span>
        </span>
      </RouterLink>
    </aside>

    <section class="room">
      <!-- cabecera -->
      <header v-if="task" class="room__head">
        <button class="btn btn--small btn--ghost" :title="listOpen ? 'Ocultar conversaciones' : 'Ver conversaciones'" @click="listOpen = !listOpen">☰</button>
        <AgentAvatar :agent="agent" :busy="busy" :size="34" />
        <div class="room__who">
          <strong>{{ task.title }}</strong>
          <span class="muted small">{{ agentName(task.agent_id) }}<template v-if="agent?.provider?.startsWith('local')"> · usa
            <strong>{{ localModel ?? "ningún modelo arrancado" }}</strong></template>
            <template v-if="agent?.provider === 'claude'"> ·
              <span v-if="agent.config.delegate_local" title="Puede encargar trabajo a los modelos arrancados">🦙 delega en {{ localModelsText("local (nada arrancado)") }}</span>
              <RouterLink v-else to="/ajustes?s=agentes" title="Ajustes → Agentes → Editar → «Puede delegar en el modelo local»">no delega en local</RouterLink>
            </template> · {{ projectName(task.project_id) }} · {{ usd(task.cost_usd) }}</span>
        </div>
        <StatusChip :state="statusChip(task.status)" :text="STATUS_TEXT[task.status] ?? task.status" />
        <RouterLink :to="`/tareas/${task.id}`" class="btn btn--small btn--ghost">Detalle y diff</RouterLink>
      </header>
      <header v-else class="room__head">
        <button class="btn btn--small btn--ghost" title="Conversaciones" @click="listOpen = !listOpen">☰</button>
        <div class="room__who">
          <strong>Nueva conversación</strong>
          <span class="muted small">Elige carpeta y agente, y escribe abajo.</span>
        </div>
      </header>

      <!-- participantes: quién es quién, cuánto ha hecho y quién tiene la pelota (clic = ver solo a ese) -->
      <div v-if="task && party.length > 1" class="party">
        <button class="party__all" :class="{ on: who === 'todo' }" @click="who = 'todo'">Todos</button>
        <button
          v-for="p in party" :key="p.key" class="party__m" :class="[`party__m--${p.tone}`, { on: who === p.key, 'party__m--ball': p.ball }]"
          @click="who = who === p.key ? 'todo' : p.key"
        >
          <span class="party__face" :class="`face--${p.tone}`">{{ p.emoji }}</span>
          <span class="party__txt">
            <strong>{{ p.name }}</strong>
            <span class="small">{{ p.sub }}</span>
            <span v-if="p.key !== 'jefe'" class="small">{{ p.n }} encargos{{ p.bad ? ` · ${p.bad} fallidos` : "" }} · {{ p.tokens }} tok · {{ Math.round(p.seconds) }} s</span>
          </span>
          <span v-if="p.ball" class="party__ball" title="Tiene la pelota">🏀</span>
        </button>
      </div>
      <p v-if="ball" class="ball" :class="{ 'ball--you': !busy }">{{ ball }}</p>

      <!-- mensajes -->
      <div ref="scroller" class="msgs">
        <template v-if="task">
          <template v-for="(m, i) in messages" :key="i">
            <template v-if="!shown(m)" />
            <div v-else-if="m.type === 'user'" class="bubble bubble--me"><Markdown :text="m.text" /></div>
            <div v-else-if="m.type === 'agent'" class="gm">
              <span class="gm__face face--jefe">🧭</span>
              <div class="gm__body">
                <span class="gm__name name--jefe">{{ bossName }} <span class="muted small">· informe</span></span>
                <div class="bubble bubble--agent bubble--jefe"><Markdown :text="m.text" /></div>
              </div>
            </div>
            <div v-else-if="m.type === 'tools'" class="tools">
              <button class="tools__btn" @click="openTools[i] = !openTools[i]">
                {{ openTools[i] ? "▾" : "▸" }} Usó {{ m.items.length }} {{ m.items.length === 1 ? "herramienta" : "herramientas" }}:
                {{ [...new Set(m.items.map((x) => x.name))].join(", ") }}
              </button>
              <ul v-if="openTools[i]">
                <li v-for="(x, j) in m.items" :key="j"><strong>{{ x.name }}</strong> <code>{{ x.target }}</code></li>
              </ul>
            </div>
            <!-- el plan del jefe: una tarjeta con el reparto (a quién fue cada bloque y cómo salió) -->
            <div v-else-if="m.type === 'plan'" class="gm">
              <span class="gm__face face--jefe">🧭</span>
              <div class="gm__body">
                <span class="gm__name name--jefe">{{ bossName }} <span class="muted small">· {{ m.label }} · lo pensó {{ m.by.name }}</span></span>
                <div class="plan">
                  <ol class="plan__list">
                    <li v-for="b in m.blocks" :key="b.id">
                      <span>{{ b.ok === undefined ? "⏳" : b.ok ? "✅" : "❌" }}</span>
                      <code class="small">{{ b.kind }}</code>
                      <strong>{{ b.path || b.title || b.id }}</strong>
                      <span v-if="b.to" class="tag" :class="`tag--${b.to.tone}`">→ {{ b.to.name }}</span>
                      <span v-if="b.after.length" class="muted small">tras {{ b.after.join(", ") }}</span>
                      <span v-if="b.seconds" class="muted small">{{ b.seconds }} s{{ b.tps ? ` · ${b.tps} tok/s` : "" }}</span>
                    </li>
                  </ol>
                </div>
              </div>
            </div>
            <!-- un encargo: el jefe se lo pide a un modelo (o piensa con él) y el modelo contesta -->
            <template v-else-if="m.type === 'delegate'">
              <div class="gm gm--ask">
                <span class="gm__face face--jefe">🧭</span>
                <div class="gm__body">
                  <span class="gm__name name--jefe">{{ bossName }}</span>
                  <div class="bubble bubble--ask">
                    <template v-if="m.boss">Piensa con <span class="tag" :class="`tag--${m.to.tone}`">{{ m.to.name }}</span>: {{ m.step }}</template>
                    <template v-else><span class="tag" :class="`tag--${m.to.tone}`">@{{ m.to.name }}</span> {{ m.step }}<template v-if="m.what">: <strong>{{ m.what }}</strong></template></template>
                    <details v-if="m.request" class="deleg__more">
                      <summary>📨 El encargo entero</summary>
                      <p class="deleg__think">{{ m.request }}</p>
                    </details>
                  </div>
                </div>
              </div>
              <div class="gm">
                <span class="gm__face" :class="`face--${m.to.tone}`">{{ TONE_EMOJI[m.to.tone] }}</span>
                <div class="gm__body">
                  <span class="gm__name" :class="`name--${m.to.tone}`">{{ m.to.name }} <span class="muted small">{{ m.to.model }} · {{ m.detail }}</span></span>
                  <div class="bubble bubble--model" :class="[`bubble--${m.to.tone}`, { 'bubble--bad': !m.ok }]">
                    <p v-if="!m.ok" class="gm__err">❌ {{ m.detail }}</p>
                    <details v-if="m.thinking" class="deleg__more">
                      <summary>💭 Lo que pensó ({{ m.thinking.length }} caracteres)</summary>
                      <p class="deleg__think">{{ m.thinking }}</p>
                    </details>
                    <details v-if="m.answer && m.ok" class="deleg__more" :open="m.answer.length < 700">
                      <summary>💬 Lo que contestó</summary>
                      <Markdown :text="m.answer.length > 4000 ? m.answer.slice(0, 4000) + '\n\n…' : m.answer" />
                    </details>
                    <p v-if="m.ok && !m.answer && !m.thinking" class="muted small">Hecho.</p>
                    <span v-for="sk in m.skills" :key="sk" class="pill pill--active small">⚡ {{ sk }}</span>
                  </div>
                </div>
              </div>
            </template>
            <details v-else-if="m.type === 'thinking'" class="think" :class="{ 'think--local': m.local }" :open="m.local">
              <summary>💭 {{ m.local ? "Pensamiento del modelo local" : "Pensamiento" }} ({{ m.text.length }} caracteres)</summary>
              <p>{{ m.text }}</p>
            </details>
            <p v-else class="note" :class="`note--${m.tone}`">{{ m.text }}</p>
          </template>
          <!-- en directo: cada modelo que está pensando o escribiendo ahora -->
          <div v-for="w in liveNow" :key="w.server" class="gm gm--live">
            <span class="gm__face" :class="`face--${workerOf(w.server).tone}`">{{ TONE_EMOJI[workerOf(w.server).tone] }}</span>
            <div class="gm__body">
              <span class="gm__name" :class="`name--${workerOf(w.server).tone}`">{{ workerOf(w.server).name }} <span class="muted small">en directo · {{ String(w.tool ?? "").startsWith("jefe_local/") ? `piensa para el jefe: ${bossStep(String(w.tool))}` : w.task }}{{ w.tps ? ` · ${w.tps} tok/s` : "" }}</span></span>
              <div class="bubble bubble--model bubble--live" :class="`bubble--${workerOf(w.server).tone}`">
                <p v-if="w.thinking" class="deleg__think">💭 {{ w.thinking.slice(-1200) }}</p>
                <p v-if="w.text" class="deleg__write">{{ w.text.slice(-1500) }}▍</p>
                <p v-if="!w.thinking && !w.text" class="muted small">leyendo el encargo…</p>
              </div>
            </div>
          </div>
          <div v-if="busy" class="from">
            <AgentAvatar :agent="agent" :busy="true" :size="28" />
            <div class="bubble bubble--agent typing">
              <span class="dots"><span /><span /><span /></span>
              <span v-if="speed" class="speed small">{{ speedText(speed) }}</span>
            </div>
          </div>

          <!-- cambios -->
          <div v-if="review?.available && ['review', 'approved'].includes(task.status)" class="changes">
            <strong>Cambios en su rama</strong>
            <pre class="block">{{ review.stat || "(sin cambios)" }}</pre>
            <div class="row">
              <button v-if="task.status === 'review'" class="btn btn--ok" :disabled="acting" @click="act('approve')">Aprobar</button>
              <button
                v-if="task.status === 'approved'" class="btn btn--primary" :disabled="acting"
                @click="act('merge', { confirm: true }, `¿Integrar ${task.branch} en «${review.target ?? 'la rama actual'}»?\n\nMerge local; nunca se hace push.`)"
              >Integrar en {{ review.target ?? "rama actual" }}</button>
              <button class="btn btn--danger" :disabled="acting" @click="act('reject', {}, '¿Rechazar? Se borran el worktree y la rama, y la conversación se cierra.')">Rechazar</button>
              <RouterLink :to="`/tareas/${task.id}`" class="btn btn--ghost">Ver diff</RouterLink>
              <span class="muted small">También puedes contestar para pedir cambios.</span>
            </div>
          </div>
        </template>

        <!-- conversación nueva: con quién y dónde -->
        <div v-else class="setup">
          <div class="seg">
            <button :class="{ on: mode === 'agent' }" @click="mode = 'agent'">Un agente</button>
            <button :class="{ on: mode === 'team' }" @click="mode = 'team'">Equipo (Director)</button>
          </div>

          <label class="field">
            <span class="label">Carpeta del proyecto</span>
            <div class="row">
              <select v-model.number="form.project_id" class="input grow">
                <option v-if="!live.projects.length" :value="0">Ninguna vinculada todavía</option>
                <option v-for="p in live.projects" :key="p.id" :value="p.id">{{ p.name }} — {{ p.repo_path }}</option>
              </select>
              <button type="button" class="btn" @click="linking = !linking">{{ linking ? "Cerrar" : "Vincular carpeta" }}</button>
            </div>
          </label>
          <form v-if="linking" class="linkbox" @submit.prevent="doLink">
            <div class="row">
              <input v-model.trim="link.path" class="input code grow" placeholder="D:\ruta\a\la\carpeta" required @change="setPath(link.path)" />
              <button type="button" class="btn" @click="choose">Elegir…</button>
            </div>
            <div class="row">
              <label class="field grow"><span class="label">Nombre</span><input v-model.trim="link.name" required /></label>
              <label class="check"><input v-model="link.init_git" type="checkbox" /> Inicializar git si no lo es</label>
              <button class="btn btn--primary">Vincular</button>
            </div>
            <p v-if="linkError" class="error">{{ linkError }}</p>
          </form>

          <template v-if="mode === 'agent'">
            <span class="label">Agente</span>
            <div class="pickers">
              <button
                v-for="a in live.agents" :key="a.id" type="button" class="pickcard"
                :class="{ on: form.agent_id === a.id }" @click="form.agent_id = a.id"
              >
                <AgentAvatar :agent="a" :size="30" />
                <span class="pickcard__txt">
                  <strong>{{ a.name }}</strong>
                  <span class="muted small">{{ ROLE_TEXT[a.role ?? ""] ?? a.role ?? "sin rol" }} · {{ a.provider }} {{ a.model ?? "" }}</span>
                  <span v-if="a.config.description" class="small">{{ a.config.description }}</span>
                </span>
              </button>
            </div>
            <label class="field thinkpick">
              <span class="label">Pensamiento</span>
              <select v-model="form.thinking">
                <option v-for="(t, k) in THINKING_TEXT" :key="k" :value="k">{{ t }}{{ k === "" && agentThinking ? ` (${agentThinking})` : "" }}</option>
              </select>
            </label>
            <div v-if="skills.length" class="skillpick">
              <button type="button" class="btn btn--small btn--ghost" @click="showSkills = !showSkills">
                {{ showSkills ? "▾" : "▸" }} Skills para esta conversación<template v-if="form.skills.length"> ({{ form.skills.length }})</template>
              </button>
              <div v-if="showSkills" class="skillpick__list">
                <label v-for="s in skills" :key="s.name" class="pick" :title="s.description">
                  <input v-if="agentSkills.includes(s.name)" type="checkbox" checked disabled />
                  <input v-else v-model="form.skills" type="checkbox" :value="s.name" />
                  {{ s.name }}<span v-if="agentSkills.includes(s.name)" class="muted small"> (ya la lleva el agente)</span>
                </label>
              </div>
            </div>
          </template>
          <div v-else class="row">
            <label class="field grow">
              <span class="label">Director</span>
              <select v-model.number="form.director_agent_id">
                <option v-for="a in live.agents" :key="a.id" :value="a.id">{{ a.name }} ({{ a.provider }})</option>
              </select>
            </label>
            <label class="field grow">
              <span class="label">Jefe técnico</span>
              <select v-model.number="form.reviewer_agent_id">
                <option :value="0">ninguno (N1 te llega a ti)</option>
                <option v-for="a in live.agents" :key="a.id" :value="a.id">{{ a.name }} ({{ a.provider }})</option>
              </select>
            </label>
          </div>
          <p v-if="chosen?.config.description && mode === 'team'" class="muted small">{{ chosen.config.description }}</p>
          <p v-if="!live.agents.length" class="muted">No hay agentes: créalos en <RouterLink to="/ajustes">Ajustes</RouterLink>
            o en <RouterLink to="/modelos">Modelos locales</RouterLink>.</p>
        </div>
      </div>

      <!-- caja de escribir -->
      <form class="composer" @submit.prevent="send">
        <p v-if="error" class="error">{{ error }}</p>
        <div class="composer__box">
          <textarea
            v-model="draft" rows="2" :placeholder="placeholder" :disabled="busy || closed || sending"
            @keydown="onKey"
          />
          <button v-if="busy" type="button" class="btn btn--danger" @click="act('cancel', {}, '¿Parar al agente? Lo hecho se guarda en su rama.')">Parar</button>
          <button v-else class="btn btn--primary" :disabled="closed || sending || !draft.trim() || (!task && (!form.project_id || !live.agents.length))">
            {{ task ? "Enviar" : mode === "team" ? "Planificar" : "Empezar" }}
          </button>
        </div>
        <p v-if="closed" class="muted small">Esta conversación terminó ({{ STATUS_TEXT[task!.status] }}).
          <RouterLink to="/chat">Empieza otra</RouterLink>.</p>
      </form>
    </section>
  </div>
</template>

<style scoped>
.chat {
  display: grid;
  grid-template-columns: 270px minmax(0, 1fr);
  gap: var(--gap);
  height: calc(100vh / var(--zoom) - 90px);
  min-height: 480px;
}
.chat--wide {
  grid-template-columns: minmax(0, 1fr);
}
/* participantes del chat de grupo */
.party {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
}
.party button {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px 6px 6px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--panel);
  color: var(--ink);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  text-align: left;
}
.party__all { padding: 6px 14px !important; }
.party button.on { outline: 2px solid var(--ink-dim); }
.party__txt { display: grid; line-height: 1.25; }
.party__txt .small { color: var(--ink-dim); }
.party__m--ball { box-shadow: 0 0 0 3px color-mix(in srgb, #f59e0b 55%, transparent); animation: ball 1.6s ease-in-out infinite; }
@keyframes ball { 50% { box-shadow: 0 0 0 6px color-mix(in srgb, #f59e0b 20%, transparent); } }
@media (prefers-reduced-motion: reduce) { .party__m--ball { animation: none; } }
.party__ball { font-size: 18px; }
.party__face, .gm__face {
  display: grid;
  place-items: center;
  flex: none;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  font-size: 16px;
  color: #fff;
}
.face--jefe { background: #7c3aed; }
.face--fuerte { background: #d97706; }
.face--rapido { background: #0d9488; }
.face--otro { background: #64748b; }
.ball {
  margin: 0;
  padding: 6px 16px;
  font-size: 13px;
  font-weight: 600;
  background: color-mix(in srgb, #f59e0b 12%, var(--panel));
  border-bottom: 1px solid var(--line);
}
.ball--you { background: color-mix(in srgb, var(--ok) 14%, var(--panel)); }
/* mensajes de grupo: cara + nombre + burbuja */
.gm {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.gm__body {
  display: grid;
  gap: 3px;
  min-width: 0;
  max-width: min(980px, 92%);
}
.gm__name { font-size: 12.5px; font-weight: 700; }
.name--jefe { color: #7c3aed; }
.name--fuerte { color: #b45309; }
.name--rapido { color: #0f766e; }
.bubble--jefe { border-left: 3px solid #7c3aed; }
.bubble--ask {
  padding: 7px 12px;
  border-radius: 14px;
  background: color-mix(in srgb, #7c3aed 9%, var(--panel));
  font-size: 14px;
  overflow-wrap: anywhere;
}
.bubble--model {
  padding: 8px 12px;
  border-radius: 14px;
  font-size: 14px;
  overflow-wrap: anywhere;
  display: grid;
  gap: 4px;
}
.bubble--fuerte { background: color-mix(in srgb, #d97706 9%, var(--panel)); }
.bubble--rapido { background: color-mix(in srgb, #0d9488 9%, var(--panel)); }
.bubble--otro { background: var(--panel-2, var(--panel)); }
.bubble--bad { background: var(--warn-weak); }
.bubble--live { outline: 2px dashed color-mix(in srgb, #f59e0b 60%, transparent); }
.gm__err { margin: 0; color: var(--warn); font-weight: 600; }
.tag {
  display: inline-block;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  background: #64748b;
}
.tag--fuerte { background: #b45309; }
.tag--rapido { background: #0f766e; }
.plan {
  padding: 10px 12px;
  border-radius: 14px;
  border: 1px solid color-mix(in srgb, #7c3aed 35%, var(--line));
  background: color-mix(in srgb, #7c3aed 6%, var(--panel));
  font-size: 14px;
}
.plan__list { margin: 0; padding-left: 20px; display: grid; gap: 4px; }
.plan__list li { overflow-wrap: anywhere; }
.plan__list li > * { margin-right: 6px; }
.list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow: auto;
  padding-right: 4px;
}
.new {
  justify-content: center;
  text-decoration: none;
  margin-bottom: 6px;
}
.pad {
  padding: 8px;
}
.conv {
  display: grid;
  gap: 5px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  color: inherit;
  text-decoration: none;
}
.conv:hover {
  background: var(--panel);
}
.conv--on {
  background: var(--panel);
  box-shadow: var(--shadow);
}
.conv__title {
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.conv__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.room {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.room__head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 18px;
  border-bottom: 1px solid var(--line);
}
.room__who {
  display: grid;
  flex: 1;
  min-width: 0;
}
.room__who strong {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.msgs {
  flex: 1;
  overflow: auto;
  padding: 20px 22px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.bubble {
  max-width: min(720px, 88%);
  padding: 10px 14px;
  border-radius: 16px;
  line-height: 1.55;
}
.bubble--me {
  align-self: flex-end;
  background: var(--accent);
  color: var(--accent-ink);
  border-bottom-right-radius: 5px;
}
.bubble--me :deep(code),
.bubble--me :deep(pre) {
  background: rgba(0, 0, 0, 0.15);
  border-color: transparent;
  color: inherit;
}
.from {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}
.bubble--agent {
  background: var(--panel-raised);
  border: 1px solid var(--line);
  border-bottom-left-radius: 5px;
}
.tools {
  margin-left: 38px;
  font-size: 13px;
  color: var(--ink-faint);
}
.tools__btn {
  border: 0;
  background: none;
  padding: 2px 0;
  color: inherit;
  cursor: pointer;
  text-align: left;
}
.tools ul {
  margin: 4px 0 0;
  padding-left: 18px;
}
.tools code {
  overflow-wrap: anywhere;
}
.note {
  align-self: center;
  margin: 0;
  padding: 3px 12px;
  border-radius: 999px;
  font-size: 13px;
  background: var(--panel-raised);
  color: var(--ink-dim);
  max-width: 90%;
  text-align: center;
}
.note--ok {
  background: var(--ok-weak);
  color: var(--ok);
}
.note--warn {
  background: var(--warn-weak);
  color: var(--warn);
}
.note--crit {
  background: var(--crit-weak);
  color: var(--crit);
  white-space: pre-wrap;
  text-align: left;
  border-radius: var(--radius-sm);
}
.thinkpick {
  max-width: 260px;
  margin-top: 8px;
}
.think {
  margin: 2px 0 2px 38px;
  font-size: 12px;
  color: var(--ink-dim);
}
.think summary {
  cursor: pointer;
}
.think p {
  margin: 6px 0 0;
  padding: 8px 10px;
  border-left: 3px solid var(--line-strong);
  white-space: pre-wrap;
  max-height: 280px;
  overflow: auto;
}
.deleg {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
  margin-left: 38px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--ok) 8%, var(--panel));
  border-left: 3px solid var(--ok);
  font-size: 14px;
  overflow-wrap: anywhere;
}
.deleg {
  flex-direction: column;
  align-items: stretch;
}
.deleg__h {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
}
.deleg__more summary {
  cursor: pointer;
  font-size: 12.5px;
  color: var(--ink-dim);
  font-weight: 600;
}
.deleg__think {
  margin: 6px 0 0;
  white-space: pre-wrap;
  font-size: 12.5px;
  font-style: italic;
  color: var(--ink-dim);
  max-height: 260px;
  overflow: auto;
}
.deleg__write {
  margin: 6px 0 0;
  white-space: pre-wrap;
  font-family: var(--font-mono);
  font-size: 12px;
  max-height: 220px;
  overflow: auto;
}
.deleg--live {
  background: color-mix(in srgb, #0ea5e9 10%, var(--panel));
  border-left-color: #0ea5e9;
}
.think--local summary {
  color: #0284c7;
}
.deleg--bad {
  background: var(--warn-weak);
  border-left-color: var(--warn);
}
.deleg__who {
  font-weight: 700;
}
.skillpick {
  display: grid;
  gap: 6px;
}
.skillpick > .btn {
  justify-self: start;
}
.skillpick__list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
}
.skillpick .pick {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
}
.typing {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
}
.dots {
  display: flex;
  gap: 4px;
}
.speed {
  color: var(--ink-dim);
  font-variant-numeric: tabular-nums;
}
.dots span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ink-faint);
  animation: blink 1.2s infinite;
}
.dots span:nth-child(2) {
  animation-delay: 0.2s;
}
.dots span:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes blink {
  50% {
    opacity: 0.25;
  }
}
.changes {
  display: grid;
  gap: 8px;
  padding: 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--warn);
  background: var(--warn-weak);
}
.setup {
  display: grid;
  grid-template-columns: minmax(0, 1fr); /* una ruta larga en el selector no ensancha la columna */
  gap: 14px;
  max-width: 760px;
}
.setup select {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  box-sizing: border-box;
  text-overflow: ellipsis;
}
.seg {
  display: inline-flex;
  gap: 4px;
  padding: 3px;
  border-radius: 999px;
  background: var(--panel-raised);
  border: 1px solid var(--line);
  width: fit-content;
}
.seg button {
  padding: 6px 14px;
  border: 0;
  border-radius: 999px;
  background: none;
  color: var(--ink-dim);
  font-weight: 600;
  cursor: pointer;
}
.seg button.on {
  background: var(--panel);
  color: var(--ink);
  box-shadow: var(--shadow);
}
.grow {
  flex: 1;
  min-width: 180px;
}
.linkbox {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius-sm);
}
.check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  align-self: end;
  padding-bottom: 9px;
}
.pickers {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}
.pickcard {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel);
  text-align: left;
  cursor: pointer;
}
.pickcard:hover {
  border-color: var(--line-strong);
}
.pickcard.on {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-weak);
}
.pickcard__txt {
  display: grid;
  gap: 1px;
  min-width: 0;
}
.composer {
  padding: 12px 16px 14px;
  border-top: 1px solid var(--line);
  display: grid;
  gap: 6px;
}
.composer p {
  margin: 0;
}
.composer__box {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}
.composer textarea {
  flex: 1;
  resize: none;
  min-height: 46px;
  max-height: 200px;
  padding: 11px 14px;
  border-radius: 14px;
  border: 1px solid var(--line-strong);
  background: var(--panel);
  color: var(--ink);
  font: inherit;
  field-sizing: content;
}
.composer textarea:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-weak);
}
.composer textarea:disabled {
  opacity: 0.6;
}
@media (max-width: 820px) {
  .chat {
    grid-template-columns: 1fr;
    height: auto;
  }
  .list {
    max-height: 220px;
  }
  .room {
    min-height: 70vh;
  }
}
</style>
