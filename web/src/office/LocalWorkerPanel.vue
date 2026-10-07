<script setup lang="ts">
// Inspector del «trabajador local»: el modelo local trabajando para un agente Claude (coordinador o que delega).
// Chat = lo que Claude le encarga y lo que el modelo local contesta; Pensamiento = su razonamiento (si el modelo lo
// tiene); Skills = lo que lleva (lo elige Claude con `local_prepare`; tú lo cambias mientras trabaja).
import { computed, ref, watch } from "vue";
import Markdown from "../components/Markdown.vue";
import { api, live, refreshAll, type Agent, type Task, type TaskEvent } from "../api";

interface Live { tool?: string; task?: string; thinking: string; text: string; done: boolean; at: number; skills?: string[] }
// `server`: con varios modelos locales, este puesto es el de uno (sus encargos y su directo; las skills, de todos)
const props = defineProps<{ task: Task; events: TaskEvent[]; agent?: Agent; stream?: Live | null;
  server?: { id: string; name: string; model: string | null; color: string } }>();

interface WorkerInfo {
  active: boolean; skills: string[]; tools: string[] | null; by: string; reason: string;
  available: { name: string; description: string }[]; all_tools: Record<string, string>;
}

const tab = ref<"chat" | "think" | "skills">("chat");
const info = ref<WorkerInfo | null>(null);
const error = ref("");
const saving = ref(false);
const running = computed(() => props.task.status === "running");

async function load() {
  info.value = await api<WorkerInfo>(`/api/tasks/${props.task.id}/worker`).catch(() => info.value);
}
// se recarga al cambiar de tarea, al terminar y cada vez que alguien lo equipa (evento `worker`)
watch(() => [props.task.id, props.task.status, props.events.filter((e) => e.kind === "worker").length], load, { immediate: true });

const short = (tool: unknown) => String(tool ?? "").replace(/^mcp__local__/, "").replace(/^local_/, "");
const TOOL_TEXT: Record<string, string> = {
  ask: "pregunta", write_file: "escribir archivo", execute_plan: "plan por bloques", agent: "tarea con herramientas",
  research: "investigar en internet", prepare: "equipar", "execute_plan/write": "bloque: escribir", "execute_plan/ask": "bloque: pregunta",
};
const toolText = (t: unknown) => TOOL_TEXT[short(t)] ?? short(t);
const num = (v: unknown) => (typeof v === "number" ? v : null);

/** Lo que Claude le pide (la llamada a la herramienta): texto corto para la burbuja. */
function orderText(input: Record<string, unknown> | undefined): string {
  if (!input) return "";
  const blocks = input.blocks as { title?: string; path?: string; kind?: string }[] | undefined;
  if (Array.isArray(blocks)) {
    return `Plan de ${blocks.length} bloques:\n` + blocks.map((b, i) => `${i + 1}. ${b.title ?? b.path ?? b.kind ?? "bloque"}${b.path && b.title ? ` (${b.path})` : ""}`).join("\n")
      + (input.check ? `\nComprobar con: ${input.check}` : "");
  }
  const main = input.task ?? input.instructions ?? input.question ?? input.command ?? "";
  const files = (input.files ?? input.context_files) as string[] | undefined;
  return [input.path ? `Archivo: ${input.path}` : "", String(main), files?.length ? `Lee: ${files.join(", ")}` : ""].filter(Boolean).join("\n");
}

interface Line { key: string; who: "claude" | "local" | "sys" | "step"; title?: string; text: string; meta?: string; request?: string; ok?: boolean }
const lines = computed<Line[]>(() => {
  const out: Line[] = [];
  props.events.forEach((e, i) => {
    const d = e.data ?? {};
    const key = `${e.id ?? "x"}-${i}`;
    if (e.kind === "tool" && String(e.text).startsWith("mcp__local__")) {
      if (short(e.text) === "prepare") return; // lo cuenta el evento `worker`
      out.push({ key, who: "claude", title: `Claude → ${toolText(e.text)}`, text: orderText(d.input as Record<string, unknown>) });
    } else if (e.kind === "delegate") {
      const tool = String(d.tool ?? "");
      if (tool === "local_prepare") return;
      if (tool === "local_execute_plan") { out.push({ key, who: "sys", text: `📋 ${d.task ?? "plan terminado"}` }); return; }
      const toks = (num(d.prompt_tokens) ?? 0) + (num(d.completion_tokens) ?? 0);
      const meta = [d.seconds != null ? `${d.seconds} s` : "", toks ? `${toks} tokens` : "", d.tps ? `${d.tps} tok/s` : "",
        (d.skills as string[] | undefined)?.length ? `skills: ${(d.skills as string[]).join(", ")}` : ""].filter(Boolean).join(" · ");
      const what = d.path ? ` · ${d.path}` : d.block ? ` · bloque ${d.block}` : "";
      out.push({ key, who: "local", title: `Modelo local · ${toolText(tool)}${what}`, ok: d.ok !== false, meta,
        text: d.ok === false ? `No pudo: ${d.error ?? "error"}` : String(d.answer ?? d.task ?? "hecho"),
        request: d.request ? String(d.request) : undefined });
    } else if (e.kind === "worker") {
      out.push({ key, who: "sys", text: `🧰 ${e.text}${d.reason ? ` — «${d.reason}»` : ""}` });
    } else if (e.kind === "progress" && String(e.text).startsWith("Modelo local:")) {
      out.push({ key, who: "step", text: String(e.text).replace(/^Modelo local:\s*/, "") });
    }
  });
  return out;
});
const waiting = computed(() => {
  // último encargo empezado sin respuesta todavía: el modelo local está con él
  let open = 0;
  for (const e of props.events) {
    if (e.kind === "tool" && String(e.text).startsWith("mcp__local__") && short(e.text) !== "prepare") open++;
    // terminado = la entrada del log de esa llamada (los bloques de un plan llevan «/» y no cierran nada)
    const tool = String(e.data?.tool ?? "");
    if (e.kind === "delegate" && tool !== "local_prepare" && !tool.includes("/")) open = Math.max(0, open - 1);
  }
  return running.value && (open > 0 || !!props.stream);
});
// el directo: siempre la última parte a la vista
const liveBox = ref<HTMLElement>();
const chatEl = ref<HTMLElement>();
// el chat baja solo con cada mensaje nuevo y con el directo (salvo que hayas subido a leer algo)
let stick = true;
const onScroll = () => { const el = chatEl.value; if (el) stick = el.scrollHeight - el.scrollTop - el.clientHeight < 60; };
watch(() => [lines.value.length, props.stream?.text?.length, props.stream?.thinking?.length, tab.value], () =>
  setTimeout(() => { const el = chatEl.value; if (el && stick) el.scrollTop = el.scrollHeight; }, 0), { immediate: true });
const liveThink = ref<HTMLElement>();
watch(() => [props.stream?.thinking, props.stream?.text], () => setTimeout(() => {
  for (const el of [liveBox.value, liveThink.value]) if (el) el.scrollTop = el.scrollHeight;
}, 0));
const loaded = computed(() => info.value?.skills.length ? info.value.skills : props.stream?.skills ?? []);

interface Thought { key: string; title: string; text: string }
const thoughts = computed<Thought[]>(() => {
  const out: Thought[] = [];
  props.events.forEach((e, i) => {
    if (e.kind === "delegate" && e.data?.thinking) {
      out.push({ key: `d${e.id ?? i}`, title: `${toolText(e.data.tool)}${e.data.path ? ` · ${e.data.path}` : ""}`, text: String(e.data.thinking) });
    } else if (e.kind === "worker_thinking" && e.text) {
      out.push({ key: `t${e.id ?? i}`, title: "tarea con herramientas", text: e.text });
    }
  });
  return out.reverse();
});

// ---------- skills y herramientas
const toAdd = ref("");
const addable = computed(() => (info.value?.available ?? []).filter((s) => !info.value!.skills.includes(s.name)));
const descOf = (n: string) => info.value?.available.find((s) => s.name === n)?.description ?? "";
async function save(skills: string[], tools: string[] | null) {
  if (!info.value) return;
  saving.value = true;
  error.value = "";
  try {
    await api(`/api/tasks/${props.task.id}/worker`, { method: "PUT", body: JSON.stringify({ skills, tools }) });
    await load();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    saving.value = false;
  }
}
function addSkill() {
  if (!toAdd.value || !info.value) return;
  save([...info.value.skills, toAdd.value], info.value.tools);
  toAdd.value = "";
}
const removeSkill = (n: string) => info.value && save(info.value.skills.filter((x) => x !== n), info.value.tools);
const hasTool = (t: string) => !info.value?.tools || info.value.tools.includes(t);
function toggleTool(t: string) {
  if (!info.value) return;
  const all = Object.keys(info.value.all_tools);
  const cur = info.value.tools ?? all;
  const next = cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t];
  save(info.value.skills, next.length === all.length ? null : all.filter((x) => next.includes(x)));
}
const savedDefault = ref(false);
async function keepAsDefault() {
  if (!props.agent || !info.value) return;
  error.value = "";
  try {
    await api(`/api/agents/${props.agent.id}`, { method: "PATCH", body: JSON.stringify({ local_skills: info.value.skills }) });
    savedDefault.value = true;
    await refreshAll();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
const BY: Record<string, string> = { Claude: "Las eligió Claude", "tú": "Las cambiaste tú", agente: "Las trae el agente por defecto" };
</script>

<template>
  <div class="lw">
    <div class="insp-h">
      <div class="avatar" :style="{ '--c': server?.color ?? '#0ea5e9' }"><i class="fa-solid fa-robot" /></div>
      <div>
        <b>{{ server ? `Local · ${server.name}` : "Trabajador local" }}</b>
        <small>de {{ agent?.name ?? "agente" }} · tarea #{{ task.id }}</small>
      </div>
      <span class="prov prov--local">{{ server?.model ?? live.local.model ?? "modelo local" }}</span>
    </div>
    <div class="state" :class="{ on: waiting }">
      <i class="fa-solid" :class="waiting ? 'fa-gear fa-spin' : running ? 'fa-mug-hot' : 'fa-flag-checkered'" />
      {{ waiting ? "Trabajando en un encargo…" : running ? "Esperando el siguiente encargo de " + (agent?.name ?? "Claude") : "Tarea terminada" }}
    </div>

    <div v-if="loaded.length" class="loaded" title="Skills que lleva cargadas en este encargo">
      <i class="fa-solid fa-bolt" /> <span v-for="s in loaded" :key="s" class="pill pill--active">{{ s }}</span>
    </div>

    <div class="tabs">
      <button :class="{ on: tab === 'chat' }" @click="tab = 'chat'"><i class="fa-solid fa-comments" /> Chat</button>
      <button :class="{ on: tab === 'think' }" @click="tab = 'think'"><i class="fa-solid fa-brain" /> Piensa <em v-if="thoughts.length">{{ thoughts.length }}</em></button>
      <button :class="{ on: tab === 'skills' }" @click="tab = 'skills'"><i class="fa-solid fa-bolt" /> Skills <em v-if="info?.skills.length">{{ info.skills.length }}</em></button>
    </div>

    <!-- chat propio: encargos de Claude y respuestas del modelo local -->
    <div v-if="tab === 'chat'" ref="chatEl" class="chat" @scroll="onScroll">
      <p v-if="!lines.length" class="small muted">Todavía no le ha encargado nada.</p>
      <div v-for="l in lines" :key="l.key" class="msg" :class="[`msg--${l.who}`, { bad: l.ok === false }]">
        <b v-if="l.title">{{ l.title }}</b>
        <Markdown v-if="l.who === 'local'" :text="l.text.length > 2500 ? l.text.slice(0, 2500) + '\n\n…' : l.text" />
        <span v-else class="pre">{{ l.text }}</span>
        <details v-if="l.request" class="req"><summary>Lo que recibió</summary><pre>{{ l.request }}</pre></details>
        <small v-if="l.meta" class="muted">{{ l.meta }}</small>
      </div>
      <div v-if="waiting && stream" class="msg msg--local livemsg">
        <b><i class="fa-solid fa-circle fa-beat-fade rec" /> En directo · {{ toolText(stream.tool) }}{{ stream.task ? ` · ${stream.task.slice(0, 60)}` : "" }}</b>
        <div v-if="stream.thinking && !stream.text" class="pre think-live">💭 {{ stream.thinking.slice(-600) }}</div>
        <div v-if="stream.text" ref="liveBox" class="pre write-live">{{ stream.text.slice(-1500) }}<i class="caret" /></div>
        <span v-if="!stream.thinking && !stream.text" class="muted"><i class="fa-solid fa-ellipsis fa-fade" /> leyendo el encargo…</span>
      </div>
      <div v-else-if="waiting" class="msg msg--local typing"><i class="fa-solid fa-ellipsis fa-fade" /></div>
    </div>

    <!-- su cadena de pensamiento -->
    <div v-else-if="tab === 'think'" class="chat">
      <div v-if="stream && stream.thinking" class="thought now">
        <b><i class="fa-solid fa-circle fa-beat-fade rec" /> Pensando ahora · {{ toolText(stream.tool) }}</b>
        <pre ref="liveThink">{{ stream.thinking }}</pre>
      </div>
      <p v-if="!thoughts.length && !stream?.thinking" class="small muted">
        Sin pensamiento todavía. Solo aparece con modelos que razonan (Qwen3, DeepSeek-R1, gpt-oss…) y con el
        pensamiento encendido al arrancar el modelo.
      </p>
      <details v-for="(t, i) in thoughts" :key="t.key" class="thought" :open="i === 0">
        <summary>💭 {{ t.title }}</summary>
        <pre>{{ t.text }}</pre>
      </details>
    </div>

    <!-- skills y herramientas -->
    <div v-else class="skills">
      <p v-if="info?.by" class="small muted">{{ BY[info.by] ?? info.by }}<template v-if="info.reason">: «{{ info.reason }}»</template></p>
      <div class="chips">
        <span v-for="s in info?.skills ?? []" :key="s" class="pill pill--active" :title="descOf(s)">
          <i class="fa-solid fa-bolt" />{{ s }}
          <button v-if="info?.active" class="x" :disabled="saving" title="Quitar" @click="removeSkill(s)">×</button>
        </span>
        <span v-if="!info?.skills.length" class="small muted">ninguna</span>
      </div>
      <form v-if="info?.active" class="add" @submit.prevent="addSkill">
        <select v-model="toAdd" class="input" :disabled="saving">
          <option value="">Añadir skill…</option>
          <option v-for="s in addable" :key="s.name" :value="s.name" :title="s.description">{{ s.name }}</option>
        </select>
        <button class="btn btn--small btn--primary" :disabled="!toAdd || saving"><i class="fa-solid fa-plus" /></button>
      </form>
      <div class="sect">Herramientas (tarea con herramientas)</div>
      <div class="tools">
        <label v-for="(txt, t) in info?.all_tools ?? {}" :key="t" class="check">
          <input type="checkbox" :checked="hasTool(String(t))" :disabled="!info?.active || saving" @change="toggleTool(String(t))"> {{ txt }}
        </label>
      </div>
      <p class="small muted">
        <template v-if="info?.active">Los cambios valen desde su siguiente encargo.</template>
        <template v-else>Solo se cambian mientras trabaja. Para la próxima vez, guárdalas en el agente.</template>
      </p>
      <button v-if="agent && info" class="btn btn--small wide" :disabled="savedDefault" @click="keepAsDefault">
        <i class="fa-solid fa-floppy-disk" /> {{ savedDefault ? "Guardadas" : `Usar siempre estas skills con ${agent.name}` }}
      </button>
      <p v-if="error" class="error small">{{ error }}</p>
    </div>
  </div>
</template>

<style scoped>
.insp-h { display: flex; gap: 10px; align-items: center; margin-bottom: 8px; }
.insp-h b { display: block; font-size: 15px; font-weight: 800; }
.insp-h small { color: var(--ink-dim); font-weight: 600; }
.insp-h .prov { margin-left: auto; max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.avatar {
  width: 44px; height: 44px; flex-shrink: 0; border-radius: 14px; display: grid; place-items: center;
  font-size: 19px; color: #fff; background: var(--c); box-shadow: 0 8px 16px -8px var(--c);
}
.state { font-size: 12px; font-weight: 600; color: var(--ink-dim); padding: 6px 10px; border-radius: 10px; background: var(--panel-raised); }
.state.on { background: rgba(14, 165, 233, 0.14); color: #0284c7; }
.state i { display: inline-block; width: 1.1em; text-align: center; }
.tabs { display: flex; gap: 4px; margin: 10px 0 8px; }
.tabs button {
  flex: 1; min-width: 0; border: 0; border-radius: 10px; padding: 6px 4px; font: inherit; font-size: 11px; font-weight: 700;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  background: var(--panel-raised); color: var(--ink-dim); cursor: pointer;
}
.tabs button.on { background: #0ea5e9; color: #fff; }
.tabs em { font-style: normal; opacity: 0.8; margin-left: 2px; }
.chat { display: grid; gap: 6px; max-height: 46vh; overflow: auto; padding-right: 2px; }
.msg { display: grid; gap: 3px; padding: 7px 9px; border-radius: 12px; font-size: 12px; max-width: 94%; }
.msg b { font-size: 11px; }
.msg--claude { background: var(--accent-weak); justify-self: start; }
.msg--local { background: rgba(14, 165, 233, 0.13); justify-self: end; }
.msg--local.bad { background: rgba(239, 68, 68, 0.14); }
.msg--sys { justify-self: center; background: none; color: var(--ink-dim); font-size: 11px; text-align: center; }
.msg--step { justify-self: end; background: none; color: var(--ink-faint); font-size: 11px; padding: 0 9px; }
.msg--step::before { content: "↳ "; }
.pre { white-space: pre-wrap; overflow-wrap: anywhere; }
.typing { width: 46px; text-align: center; }
.req summary, .thought summary { cursor: pointer; font-size: 11px; font-weight: 700; color: var(--ink-dim); }
pre {
  white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11px; margin: 4px 0 0; max-height: 260px; overflow: auto;
  background: var(--panel-raised); padding: 6px 8px; border-radius: 8px;
}
.thought { padding: 6px 8px; border-radius: 10px; background: var(--panel-raised); }
.thought.now { background: rgba(14, 165, 233, 0.12); }
.thought.now b { font-size: 11px; }
.loaded { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; margin-top: 8px; font-size: 11px; color: var(--ink-dim); }
.livemsg { max-width: 100%; justify-self: stretch; }
.think-live { color: var(--ink-dim); font-style: italic; font-size: 11.5px; }
.write-live { font-family: var(--font-mono); font-size: 11px; max-height: 180px; overflow: auto; }
.rec { color: #ef4444; font-size: 8px; vertical-align: 2px; }
.caret { display: inline-block; width: 6px; height: 12px; background: #0ea5e9; margin-left: 2px; vertical-align: -2px; animation: blink 1s steps(2) infinite; }
@keyframes blink { 50% { opacity: 0; } }
.thought pre { background: none; padding: 0; }
.chips { display: flex; flex-wrap: wrap; gap: 5px; }
.x { border: 0; background: none; cursor: pointer; font-weight: 800; color: inherit; padding: 0 0 0 4px; }
.add { display: flex; gap: 6px; margin-top: 8px; }
.add select { flex: 1; min-width: 0; }
.sect {
  font-weight: 800; font-size: 11px; color: var(--ink-faint); letter-spacing: 0.06em; text-transform: uppercase; margin: 12px 0 6px;
}
.tools { display: grid; grid-template-columns: 1fr 1fr; gap: 3px 8px; font-size: 12px; }
.wide { width: 100%; margin-top: 8px; }
</style>
