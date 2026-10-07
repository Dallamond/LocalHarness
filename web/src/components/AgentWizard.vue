<script setup lang="ts">
// Asistente de agentes: plantilla por rol → cerebro (Claude o modelo local recomendado por su nota) → skills y
// herramientas → nombre. Vista previa en vivo a la derecha. Al crear, instala lo que falte de la biblioteca (skills y
// servidores MCP sin parámetros) y lleva al agente a la oficina. Con `ui.wizard.agentId` edita uno que ya existe.
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import {
  ROLE_TEXT, api, live, post, refreshAll, ui,
  type Agent, type AgentTemplate, type Library, type LlamaInfo, type LocalServer, type ModelRating, type Settings, type Skill, type Thinking,
} from "../api";

const router = useRouter();
const editing = computed(() => (ui.wizard?.agentId ? live.agents.find((a) => a.id === ui.wizard!.agentId) ?? null : null));
const error = ref("");
const busy = ref(false);
const lib = ref<Library | null>(null);
const installed = ref<Skill[]>([]);
const servers = ref<Settings["mcp_servers"]>({});
const models = ref<{ name: string; path: string; size_gb: number; rating?: ModelRating["rating"] }[]>([]);
const llamaServers = ref<LocalServer[]>([]); // servidores locales (uno por GPU); con uno solo no se pregunta
const modelsLoading = ref(true);

const ROLE_HEX: Record<string, string> = { director: "#5b5bf0", jefe: "#10b981", trabajador: "#f97316", consultas: "#0ea5e9" };
const CLAUDE_MODELS = [
  { id: "haiku", text: "Haiku", hint: "rápido y barato" },
  { id: "sonnet", text: "Sonnet", hint: "equilibrado" },
  { id: "opus", text: "Opus", hint: "el más capaz, gasta más" },
];

interface Form {
  template: string;
  name: string;
  role: string;
  brain: "claude" | "local";
  claude_model: string;
  local_model: string;       // nombre del GGUF preferido ("" = el que esté arrancado)
  local_server: string;      // servidor local (GPU) en el que trabaja ("" = el principal)
  local_provider: "local" | "local_agent";
  local_use: string;
  description: string;
  instructions: string;
  skills: string[];
  mcps: string[];
  web: boolean;
  delegate_local: boolean;
  coordinator: boolean;
  read_only: boolean;
  thinking: Thinking | "";
  max_turns: number | null;
  max_budget_usd: number | null;
  timeout_min: number | null;
}
const f = reactive<Form>({
  template: "", name: "", role: "trabajador", brain: "claude", claude_model: "sonnet", local_model: "", local_server: "",
  local_provider: "local_agent", local_use: "agente con herramientas", description: "", instructions: "", skills: [],
  mcps: [], web: false, delegate_local: false, coordinator: false, read_only: false, thinking: "", max_turns: 10, max_budget_usd: 0.5,
  timeout_min: null,
});
const nameTouched = ref(false);
const showAdvanced = ref(false);
const showTemplates = ref(true); // al editar, plegadas: aplicar una plantilla pisa lo que tenga el agente

function uniqueName(base: string): string {
  const slug = base.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "agente";
  let n = slug;
  for (let i = 2; live.agents.some((a) => a.name === n && a.id !== editing.value?.id); i++) n = `${slug}-${i}`;
  return n;
}

function applyTemplate(t: AgentTemplate) {
  Object.assign(f, {
    template: t.id, role: t.role, brain: t.provider, claude_model: t.claude_model, local_provider: t.local_provider,
    local_use: t.local_use, description: t.description, instructions: t.instructions, skills: [...t.skills],
    mcps: [...t.mcps], web: t.web, delegate_local: t.delegate_local || !!t.coordinator, coordinator: !!t.coordinator, read_only: t.read_only,
    thinking: t.thinking === "normal" ? "" : t.thinking,
    max_turns: t.max_turns, max_budget_usd: t.max_budget_usd,
  });
  if (!nameTouched.value && !editing.value) f.name = uniqueName(t.id === "en-blanco" ? "agente" : t.id);
  if (f.brain === "local" && !f.local_model) f.local_model = best.value?.name ?? "";
}

function fromAgent(a: Agent) {
  const c = a.config;
  const local = a.provider.startsWith("local");
  Object.assign(f, {
    template: c.template ?? "", name: a.name, role: a.role ?? "trabajador", brain: local ? "local" : "claude",
    claude_model: local ? "sonnet" : a.model ?? "sonnet", local_model: local ? a.model ?? "" : "", local_server: c.server ?? "",
    local_provider: a.provider === "local" ? "local" : "local_agent",
    local_use: a.role === "director" ? "director" : a.role === "jefe" ? "jefe técnico" : "agente con herramientas",
    description: c.description ?? "", instructions: c.instructions ?? "", skills: [...(c.skills ?? [])],
    mcps: [...(c.mcps ?? [])], web: !!c.web, delegate_local: !!c.delegate_local || !!c.coordinator, coordinator: !!c.coordinator,
    read_only: !!c.read_only,
    thinking: c.thinking && c.thinking !== "normal" ? c.thinking : "", max_turns: c.max_turns ?? null, max_budget_usd: c.max_budget_usd ?? null,
    timeout_min: c.timeout_s ? Math.round(c.timeout_s / 60) : null,
  });
  nameTouched.value = true;
}

async function load() {
  const [l, sk, st] = await Promise.all([
    api<Library>("/api/library"), api<Skill[]>("/api/skills"), api<{ values: Settings }>("/api/settings"),
  ]);
  lib.value = l;
  installed.value = sk;
  servers.value = st.values.mcp_servers ?? {};
  if (editing.value) { fromAgent(editing.value); showTemplates.value = false; }
  else applyTemplate(l.templates.find((t) => t.id === (ui.wizard?.template ?? "programador")) ?? l.templates[0]);
}
async function loadModels() {
  try {
    const [info, r] = await Promise.all([
      api<LlamaInfo>("/api/llama"),
      api<{ models: Record<string, ModelRating> }>("/api/llama/ratings").catch(() => ({ models: {} as Record<string, ModelRating> })),
    ]);
    models.value = info.models.map((m) => ({ name: m.name, path: m.path, size_gb: m.size_gb, rating: r.models[m.path]?.rating }));
    llamaServers.value = info.servers ?? [];
    if (f.brain === "local" && !f.local_model && !editing.value) f.local_model = best.value?.name ?? "";
  } catch {
    models.value = [];
  } finally {
    modelsLoading.value = false;
  }
}
const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
onMounted(() => {
  load().catch((e) => (error.value = (e as Error).message));
  loadModels();
  window.addEventListener("keydown", onKey);
});
onUnmounted(() => window.removeEventListener("keydown", onKey));
function close() { ui.wizard = null; }

// ---------- modelo local recomendado: nota de la pestaña Modelos, primero los que sirven para este rol
const fits = (m: (typeof models.value)[number]) => !!m.rating?.roles.some((r) => r.startsWith(f.local_use));
const ranked = computed(() => [...models.value].sort((a, b) =>
  Number(fits(b)) - Number(fits(a)) || (b.rating?.score ?? -1) - (a.rating?.score ?? -1)));
const best = computed(() => ranked.value.find((m) => m.rating && fits(m)) ?? ranked.value.find((m) => m.rating) ?? null);
watch(() => f.local_use, () => { if (f.brain === "local" && !editing.value) f.local_model = best.value?.name ?? f.local_model; });
watch(() => f.brain, (b) => {
  if (b === "claude" && !f.max_budget_usd) f.max_budget_usd = 0.5;
  if (b === "local" && !f.local_model) f.local_model = best.value?.name ?? "";
  if (b === "local" && f.local_provider === "local_agent" && !editing.value) f.web = f.web || f.role === "consultas";
});
// el modelo arrancado en el servidor de este agente (el principal si no tiene uno)
const chosenServer = computed(() => llamaServers.value.find((x) => x.id === f.local_server) ?? llamaServers.value[0]);
const servedName = computed(() => {
  if (chosenServer.value) return chosenServer.value.model_name;
  return live.local.state !== "off" && live.local.model ? live.local.model.split(/[\\/]/).pop()!.replace(/\.gguf$/i, "") : null;
});
// al elegir un modelo que ya está arrancado en otro servidor, el agente se va a ese servidor
watch(() => f.local_model, (name) => {
  if (!name || llamaServers.value.length < 2) return;
  const on = llamaServers.value.find((x) => x.model_name?.toLowerCase().includes(name.toLowerCase()));
  if (on) f.local_server = on.id === "principal" ? "" : on.id;
});
const scoreClass = (s?: number) => (s === undefined ? "" : s >= 80 ? "s-hi" : s >= 60 ? "s-ok" : s >= 40 ? "s-mid" : "s-lo");

// ---------- skills y servidores: las instaladas + las de la biblioteca (se instalan al guardar)
const skillQ = ref("");
const skillCat = ref("");
interface SkillOpt { name: string; description: string; category: string; fromLibrary: boolean }
const skillOpts = computed<SkillOpt[]>(() => {
  const have = new Map(installed.value.map((s) => [s.name, { name: s.name, description: s.description, category: s.category ?? "Otras", fromLibrary: false }]));
  for (const s of lib.value?.skills ?? []) if (!have.has(s.name)) have.set(s.name, { name: s.name, description: s.description, category: s.category, fromLibrary: true });
  return [...have.values()].sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name));
});
const skillCats = computed(() => [...new Set(skillOpts.value.map((s) => s.category))]);
const shownSkills = computed(() => skillOpts.value.filter((s) =>
  (!skillCat.value || s.category === skillCat.value) &&
  (!skillQ.value || `${s.name} ${s.description}`.toLowerCase().includes(skillQ.value.toLowerCase()))));
const toggleIn = (list: string[], v: string) => { const i = list.indexOf(v); if (i >= 0) list.splice(i, 1); else list.push(v); };

interface McpOpt { name: string; description: string; fromLibrary: boolean; needsParams: boolean; available: boolean; icon: string; needs?: string }
const mcpOpts = computed<McpOpt[]>(() => {
  const out: McpOpt[] = Object.entries(servers.value).map(([n, s]) => {
    const e = lib.value?.mcps.find((x) => x.added_as.includes(n));
    return { name: n, description: s.description ?? "", fromLibrary: false, needsParams: false, available: true, icon: e?.icon ?? "fa-plug" };
  });
  for (const e of lib.value?.mcps ?? []) {
    if (e.added_as.length || servers.value[e.id]) continue;
    out.push({ name: e.id, description: e.description, fromLibrary: true, needsParams: !!e.params?.length,
      available: e.available, icon: e.icon, needs: e.needs });
  }
  return out;
});
const iconClass = (i: string) => (i.includes("fa-brands") ? i : `fa-solid ${i}`);

// ---------- vista previa
const color = computed(() => ROLE_HEX[f.role] ?? "#8b5cf6");
const provider = computed(() => (f.brain === "claude" ? "claude" : f.local_provider));
const brainText = computed(() => f.brain === "claude"
  ? `Claude ${CLAUDE_MODELS.find((m) => m.id === f.claude_model)?.text ?? f.claude_model} · tu suscripción`
  : `${f.local_model || "el modelo arrancado"} · ${f.local_provider === "local_agent" ? "con herramientas" : "solo responde"} · gratis`);
const chosenModel = computed(() => models.value.find((m) => m.name === f.local_model));
const warnings = computed(() => {
  const w: string[] = [];
  if (f.brain === "local") {
    if (!models.value.length && !modelsLoading.value) w.push("No tienes modelos GGUF descargados: descárgalos en Modelos locales.");
    else if (f.local_model && servedName.value && !servedName.value.toLowerCase().includes(f.local_model.toLowerCase()))
      w.push(`Ahora está arrancado ${servedName.value}: el agente responde con el que esté arrancado.`);
    else if (!servedName.value) w.push("No hay ningún modelo arrancado: arráncalo en Modelos locales antes de encargarle algo.");
    if (f.local_provider === "local" && !f.read_only && f.role === "trabajador") w.push("«Solo responde» no modifica archivos: para programar elige «con herramientas».");
    if (chosenModel.value?.rating && !fits(chosenModel.value)) w.push(`Según su nota, ${chosenModel.value.name} no es de los mejores para «${f.local_use}».`);
  }
  for (const m of f.mcps) {
    const o = mcpOpts.value.find((x) => x.name === m);
    if (o?.needsParams) w.push(`El servidor ${m} necesita configurarse (clave o ruta): añádelo desde el Catálogo → Servidores MCP.`);
    else if (o && !o.available) w.push(`El servidor ${m} necesita ${o.needs === "npx" ? "Node.js (npx)" : o.needs === "uvx" ? "uv (uvx)" : o.needs} instalado en el PC.`);
  }
  if (editing.value?.config.from_role) w.push(`Este agente sale de roles/${editing.value.config.from_role}.md: al reiniciar LocalHarness el archivo vuelve a mandar.`);
  return w;
});
const usesMcp = computed(() => provider.value === "claude");
const toolsList = computed(() => [
  ...(usesMcp.value ? f.mcps : []),
  ...(f.web ? ["internet"] : []),
  ...(usesMcp.value && (f.delegate_local || f.coordinator) ? [f.coordinator && !f.read_only ? "jefe del modelo local" : "delega en el modelo local"] : []),
  ...(provider.value === "local_agent" ? ["leer", "buscar", f.read_only ? null : "escribir", f.read_only ? null : "ejecutar tests"].filter(Boolean) as string[] : []),
]);
const nameOk = computed(() => /^[\w.-]{1,60}$/.test(f.name) && !live.agents.some((a) => a.name === f.name && a.id !== editing.value?.id));

// ---------- guardar
async function save() {
  if (!nameOk.value) { error.value = "Pon un nombre sin espacios que no use otro agente"; return; }
  busy.value = true;
  error.value = "";
  try {
    // lo que viene de la biblioteca se instala primero
    for (const n of f.skills) {
      if (skillOpts.value.find((s) => s.name === n)?.fromLibrary) await post(`/api/library/skills/${encodeURIComponent(n)}`).catch((e) => { if (!/existe/.test(String(e))) throw e; });
    }
    const mcps = usesMcp.value ? f.mcps.filter((m) => !mcpOpts.value.find((o) => o.name === m)?.needsParams) : [];
    for (const m of mcps) {
      if (mcpOpts.value.find((o) => o.name === m)?.fromLibrary) await post(`/api/library/mcp/${m}`, {}).catch((e) => { if (!/Ya hay/.test(String(e))) throw e; });
    }
    const isClaude = provider.value === "claude";
    const body: Record<string, unknown> = {
      role: f.role, model: isClaude ? f.claude_model || null : f.local_model || null,
      description: f.description.trim() || null, instructions: f.instructions.trim() || null,
      skills: f.skills, read_only: f.read_only, thinking: f.thinking || null,
      max_turns: f.max_turns || null, max_budget_usd: isClaude ? f.max_budget_usd || null : null,
      timeout_s: f.timeout_min ? f.timeout_min * 60 : null,
      web: provider.value === "local" ? null : f.web, mcps: isClaude ? mcps : [], delegate_local: isClaude && f.delegate_local,
      coordinator: isClaude && f.delegate_local && f.coordinator && !f.read_only,
      server: isClaude ? null : f.local_server || null,
    };
    let id: number;
    if (editing.value) {
      id = editing.value.id;
      await api(`/api/agents/${id}`, { method: "PATCH", body: JSON.stringify({ ...body, provider: provider.value, name: f.name }) });
    } else {
      const a = await post<Agent>("/api/agents", { ...body, name: f.name, provider: provider.value, template: f.template || null });
      id = a.id;
    }
    await refreshAll();
    ui.wizard = null;
    if (!editing.value) {
      ui.catalog = null;
      ui.focusAgent = id;
      router.push("/oficina");
    }
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="overlay" @mousedown.self="close">
    <div class="wiz card">
      <div class="wiz-h">
        <h2><i class="fa-solid fa-wand-magic-sparkles" /> {{ editing ? `Editar ${editing.name}` : "Nuevo agente" }}</h2>
        <span class="spacer" />
        <span v-if="error" class="error small">{{ error }}</span>
        <button class="icon-btn" title="Cerrar (Esc)" @click="close"><i class="fa-solid fa-xmark" /></button>
      </div>
      <div v-if="!lib" class="loading muted">Cargando…</div>
      <div v-else class="wiz-b">
        <form class="steps" @submit.prevent="save">
          <!-- 1 plantilla -->
          <section>
            <h3>
              <span class="n">1</span> Rol
              <em v-if="showTemplates">elige una plantilla: lo rellena todo y luego lo ajustas</em>
              <template v-else>
                <em>plantilla: {{ lib.templates.find((t) => t.id === f.template)?.name ?? "ninguna" }}</em>
                <button type="button" class="btn btn--small btn--ghost" @click="showTemplates = true">Cambiar plantilla (pisa lo de abajo)</button>
              </template>
            </h3>
            <div v-if="showTemplates" class="tpls">
              <button
                v-for="t in lib.templates" :key="t.id" type="button" class="tpl" :class="{ on: f.template === t.id }"
                :style="{ '--c': ROLE_HEX[t.role] ?? '#8b5cf6' }" :title="t.summary" @click="applyTemplate(t)"
              >
                <i class="fa-solid" :class="t.icon" />
                <b>{{ t.name }}</b>
                <small>{{ t.summary }}</small>
              </button>
            </div>
          </section>

          <!-- 2 cerebro -->
          <section>
            <h3><span class="n">2</span> Cerebro <em>quién piensa: Claude con tu suscripción o un modelo de tu PC</em></h3>
            <div class="brains">
              <label class="brain" :class="{ on: f.brain === 'claude' }">
                <input v-model="f.brain" type="radio" value="claude">
                <span class="bi"><i class="fa-solid fa-cloud" /></span>
                <span><b>Claude</b><small>Tu suscripción. Usa herramientas, servidores MCP e internet.</small></span>
              </label>
              <label class="brain" :class="{ on: f.brain === 'local' }">
                <input v-model="f.brain" type="radio" value="local">
                <span class="bi bi--local"><i class="fa-solid fa-microchip" /></span>
                <span><b>Modelo local</b><small>Gratis, en tu GPU con llama-server.</small></span>
              </label>
            </div>
            <div v-if="f.brain === 'claude'" class="seg">
              <button v-for="m in CLAUDE_MODELS" :key="m.id" type="button" :class="{ on: f.claude_model === m.id }" @click="f.claude_model = m.id">
                <b>{{ m.text }}</b><small>{{ m.hint }}</small>
              </button>
            </div>
            <template v-else>
              <div class="seg">
                <button type="button" :class="{ on: f.local_provider === 'local_agent' }" @click="f.local_provider = 'local_agent'">
                  <b>Con herramientas</b><small>lee, escribe, ejecuta tests</small>
                </button>
                <button type="button" :class="{ on: f.local_provider === 'local' }" @click="f.local_provider = 'local'">
                  <b>Solo responde</b><small>chat con el repo en el prompt</small>
                </button>
              </div>
              <div class="mlist">
                <p v-if="modelsLoading" class="muted small">Mirando tus modelos y su nota…</p>
                <p v-else-if="!models.length" class="muted small">
                  No hay modelos descargados. <a href="#" @click.prevent="close(); router.push('/modelos')">Ir a Modelos locales</a>
                </p>
                <label v-for="m in ranked" :key="m.path" class="mrow" :class="{ on: f.local_model === m.name }">
                  <input v-model="f.local_model" type="radio" :value="m.name">
                  <span class="score" :class="scoreClass(m.rating?.score)">{{ m.rating?.score ?? "?" }}</span>
                  <span class="mname">
                    <b class="mono">{{ m.name }}</b>
                    <small>
                      {{ m.size_gb.toFixed(1) }} GB · {{ m.rating?.verdict ?? "sin nota" }}
                      <template v-if="m.rating?.roles.length"> · sirve de {{ m.rating.roles.join(", ") }}</template>
                    </small>
                  </span>
                  <span v-if="best && m.name === best.name" class="pill pill--ok"><i class="fa-solid fa-star" />recomendado</span>
                  <span v-if="servedName && servedName.toLowerCase().includes(m.name.toLowerCase())" class="pill pill--active">arrancado</span>
                </label>
                <p v-if="models.length" class="muted small">Nota de la pestaña Modelos para «{{ f.local_use }}». El agente usa el modelo que esté arrancado; este queda como preferido.</p>
              </div>
              <div v-if="llamaServers.length > 1" class="srvpick">
                <span class="small muted">Trabaja en</span>
                <div class="seg">
                  <button v-for="x in llamaServers" :key="x.id" type="button" :class="{ on: (f.local_server || 'principal') === x.id }"
                          @click="f.local_server = x.id === 'principal' ? '' : x.id">
                    <b>{{ x.name }}</b><small>{{ x.device || "GPU automática" }} · {{ x.model_name ?? "apagado" }}</small>
                  </button>
                </div>
              </div>
            </template>
          </section>

          <!-- 3 skills y herramientas -->
          <section>
            <h3><span class="n">3</span> Skills y herramientas <em>las de la biblioteca se instalan al guardar</em></h3>
            <div class="row filt">
              <input v-model="skillQ" class="input" placeholder="Buscar skills…">
              <select v-model="skillCat" class="input"><option value="">Todas las categorías</option><option v-for="c in skillCats" :key="c">{{ c }}</option></select>
              <span class="muted small">{{ f.skills.length }} elegidas</span>
            </div>
            <div class="chipsel">
              <button
                v-for="s in shownSkills" :key="s.name" type="button" class="chip" :class="{ on: f.skills.includes(s.name) }"
                :title="`${s.category} · ${s.description}${s.fromLibrary ? ' (de la biblioteca: se instala al guardar)' : ''}`"
                @click="toggleIn(f.skills, s.name)"
              >
                <i class="fa-solid" :class="f.skills.includes(s.name) ? 'fa-check' : s.fromLibrary ? 'fa-cloud-arrow-down' : 'fa-bolt'" />{{ s.name }}
              </button>
            </div>
            <template v-if="usesMcp">
              <h4>Servidores MCP</h4>
              <div class="chipsel">
                <button
                  v-for="m in mcpOpts" :key="m.name" type="button" class="chip chip--mcp"
                  :class="{ on: f.mcps.includes(m.name), warn: m.needsParams || !m.available }"
                  :title="m.description + (m.needsParams ? ' · necesita configurarse en el Catálogo' : m.fromLibrary ? ' · se añade al guardar' : '')"
                  @click="toggleIn(f.mcps, m.name)"
                >
                  <i :class="f.mcps.includes(m.name) ? 'fa-solid fa-check' : iconClass(m.icon)" />{{ m.name }}
                  <i v-if="m.needsParams" class="fa-solid fa-key mini" />
                </button>
              </div>
            </template>
            <p v-else class="muted small">Los agentes locales usan sus propias herramientas (leer, buscar, escribir, ejecutar, buscar_web); los servidores MCP son solo para Claude.</p>
            <div class="toggles">
              <label v-if="provider !== 'local'" class="check"><input v-model="f.web" type="checkbox"> Internet <span class="muted small">{{ provider === "claude" ? "(WebSearch/WebFetch, gasta plan)" : "(buscar_web, gratis)" }}</span></label>
              <label v-if="provider === 'claude'" class="check"><input v-model="f.delegate_local" type="checkbox"> Trabaja con el modelo local <span class="muted small">(ahorra plan)</span></label>
              <label class="check"><input v-model="f.read_only" type="checkbox"> Solo lectura <span class="muted small">(no modifica archivos)</span></label>
              <label class="check">Pensamiento
                <select v-model="f.thinking" class="input mini"><option value="">normal</option><option value="apagado">apagado</option><option value="profundo">profundo</option></select>
              </label>
            </div>
            <div v-if="provider === 'claude' && f.delegate_local && !f.read_only" class="seg modes">
              <button type="button" :class="{ on: f.coordinator }" @click="f.coordinator = true">
                <b><i class="fa-solid fa-user-tie" /> Jefe del modelo local (solo coordina)</b>
                <small>Claude no escribe: encarga cada cambio al modelo local, lo revisa y pide correcciones. Gasta mucho menos plan. Sin modelo arrancado, trabaja solo.</small>
              </button>
              <button type="button" :class="{ on: !f.coordinator }" @click="f.coordinator = false">
                <b><i class="fa-solid fa-handshake" /> Con ayuda del local</b>
                <small>Claude puede escribir él mismo y delega lo que encaje (leer, resumir, tests, archivos nuevos).</small>
              </button>
            </div>
          </section>

          <!-- 4 nombre -->
          <section>
            <h3><span class="n">4</span> Nombre y encargo</h3>
            <div class="grid2">
              <label class="field"><span class="label">Nombre</span>
                <input v-model.trim="f.name" class="input mono" :class="{ bad: !nameOk }" :disabled="!!editing?.config.from_role" @input="nameTouched = true">
              </label>
              <label class="field"><span class="label">Rol en el equipo</span>
                <select v-model="f.role" class="input">
                  <option value="director">Director</option><option value="jefe">Jefe técnico</option>
                  <option value="trabajador">Trabajador</option><option value="consultas">Consultas</option>
                </select>
              </label>
            </div>
            <label class="field"><span class="label">En qué es bueno <small class="muted">(el Director lo lee para repartir trabajo)</small></span>
              <input v-model="f.description" class="input">
            </label>
            <label class="field"><span class="label">Instrucciones <small class="muted">(se añaden a cada tarea suya)</small></span>
              <textarea v-model="f.instructions" class="input" rows="3" placeholder="Opcional: cómo debe trabajar, qué no debe tocar…" />
            </label>
            <button type="button" class="btn btn--ghost btn--small" @click="showAdvanced = !showAdvanced">
              <i class="fa-solid" :class="showAdvanced ? 'fa-chevron-up' : 'fa-chevron-down'" /> Límites
            </button>
            <div v-if="showAdvanced" class="grid3">
              <label class="field"><span class="label">Turnos máx.</span><input v-model.number="f.max_turns" class="input" type="number" min="1" max="200"></label>
              <label v-if="provider === 'claude'" class="field"><span class="label">Tope en $ por tarea</span><input v-model.number="f.max_budget_usd" class="input" type="number" min="0.01" step="0.05"></label>
              <label class="field"><span class="label">Tiempo máx. (min)</span><input v-model.number="f.timeout_min" class="input" type="number" min="1" placeholder="el de Ajustes"></label>
            </div>
          </section>
          <button type="submit" hidden />
        </form>

        <!-- vista previa -->
        <aside class="prev" :style="{ '--c': color }">
          <div class="pv-card">
            <div class="pv-h">
              <span class="pv-av"><i class="fa-solid fa-user-astronaut" /></span>
              <div>
                <b class="mono">{{ f.name || "sin-nombre" }}</b>
                <small>{{ ROLE_TEXT[f.role] ?? f.role }}</small>
              </div>
            </div>
            <p class="pv-desc">{{ f.description || "Sin descripción." }}</p>
            <dl>
              <dt><i class="fa-solid fa-brain" /> Cerebro</dt><dd>{{ brainText }}</dd>
              <dt><i class="fa-solid fa-bolt" /> Skills</dt>
              <dd><span v-for="s in f.skills" :key="s" class="pill">{{ s }}</span><span v-if="!f.skills.length" class="muted">ninguna</span></dd>
              <dt><i class="fa-solid fa-screwdriver-wrench" /> Herramientas</dt>
              <dd><span v-for="t in toolsList" :key="t" class="pill pill--active">{{ t }}</span><span v-if="!toolsList.length" class="muted">las básicas</span></dd>
              <dt><i class="fa-solid fa-gauge" /> Límites</dt>
              <dd>
                {{ f.read_only ? "solo lectura" : "puede modificar archivos" }} · {{ f.max_turns ?? "∞" }} turnos
                <template v-if="provider === 'claude' && f.max_budget_usd"> · tope {{ f.max_budget_usd }} $</template>
                · pensamiento {{ f.thinking || "normal" }}
              </dd>
            </dl>
            <div v-if="f.instructions" class="pv-ins"><b>Instrucciones</b>{{ f.instructions }}</div>
          </div>
          <ul v-if="warnings.length" class="warns">
            <li v-for="w in warnings" :key="w"><i class="fa-solid fa-triangle-exclamation" /> {{ w }}</li>
          </ul>
          <div class="pv-act">
            <button class="btn" @click="close">Cancelar</button>
            <button class="btn btn--primary" :disabled="busy || !nameOk" @click="save">
              <i class="fa-solid" :class="editing ? 'fa-floppy-disk' : 'fa-building'" />
              {{ busy ? "Guardando…" : editing ? "Guardar cambios" : "Crear y ver en la oficina" }}
            </button>
          </div>
        </aside>
      </div>
    </div>
  </div>
</template>

<style scoped>
.srvpick {
  display: grid;
  gap: 6px;
  margin-top: 8px;
}
.overlay {
  position: fixed;
  inset: 0;
  z-index: 110;
  display: grid;
  place-items: center;
  padding: 22px;
  background: rgba(30, 35, 45, 0.5);
  backdrop-filter: blur(4px);
}
.wiz {
  width: min(1180px, 100%);
  height: min(860px, 100%);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.wiz-h {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
}
.wiz-h h2 {
  display: flex;
  gap: 9px;
  align-items: center;
  font-size: 17px;
}
.wiz-h h2 i {
  color: var(--accent);
}
.spacer {
  flex: 1;
}
.icon-btn {
  width: 34px;
  height: 34px;
  border-radius: 11px;
  background: var(--panel-raised);
  border: 1px solid var(--line);
  display: grid;
  place-items: center;
  color: var(--ink-dim);
  cursor: pointer;
}
.loading {
  padding: 40px;
  text-align: center;
}
.wiz-b {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
}
.steps {
  overflow: auto;
  padding: 6px 18px 18px;
}
section {
  padding: 12px 0 14px;
  border-bottom: 1px dashed var(--line);
}
section:last-of-type {
  border-bottom: 0;
}
h3 {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  margin: 0 0 10px;
  font-size: 14px;
}
h3 em {
  font-style: normal;
  font-weight: 500;
  color: var(--ink-faint);
  font-size: 12px;
}
h3 .n {
  display: inline-grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  font-size: 12px;
}
h4 {
  margin: 12px 0 6px;
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-faint);
}
.tpls {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(128px, 1fr));
  gap: 6px;
}
.tpl {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 7px 9px;
  text-align: left;
  border: 1px solid var(--line);
  border-top: 3px solid var(--c);
  border-radius: 12px;
  background: var(--panel-raised);
  color: var(--ink);
  cursor: pointer;
}
.tpl i {
  color: var(--c);
  font-size: 14px;
}
.tpl b {
  font-size: 12.5px;
}
.tpl small {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: var(--ink-dim);
  font-size: 10.5px;
  line-height: 1.25;
}
.tpl.on {
  outline: 2px solid var(--c);
  background: var(--panel);
}
.brains {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.brain {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel-raised);
  cursor: pointer;
}
.brain input {
  display: none;
}
.brain.on {
  outline: 2px solid var(--accent);
  background: var(--panel);
}
.brain small {
  display: block;
  color: var(--ink-dim);
  font-size: 11.5px;
}
.bi {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  display: grid;
  place-items: center;
  border-radius: 11px;
  background: #d97706;
  color: #fff;
}
.bi--local {
  background: #16a34a;
}
.seg {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.seg button {
  flex: 1;
  min-width: 120px;
  display: flex;
  flex-direction: column;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-raised);
  color: var(--ink);
  cursor: pointer;
  text-align: left;
}
.seg button small {
  color: var(--ink-faint);
  font-size: 11px;
}
.seg button.on {
  border-color: var(--accent);
  background: var(--accent-weak);
}
.mlist {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 8px;
}
.mrow {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 7px 9px;
  border: 1px solid var(--line);
  border-radius: 10px;
  cursor: pointer;
}
.mrow input {
  display: none;
}
.mrow.on {
  border-color: var(--accent);
  background: var(--accent-weak);
}
.mname {
  flex: 1;
  min-width: 0;
}
.mname b {
  display: block;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mname small {
  color: var(--ink-dim);
  font-size: 11px;
}
.score {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  display: grid;
  place-items: center;
  border-radius: 10px;
  font-weight: 800;
  background: var(--meter);
}
.s-hi { background: #bbf7d0; color: #166534; }
.s-ok { background: #d9f99d; color: #3f6212; }
.s-mid { background: #fef08a; color: #854d0e; }
.s-lo { background: #fecaca; color: #991b1b; }
.filt {
  gap: 8px;
  margin-bottom: 8px;
}
.filt .input:first-child {
  flex: 1;
}
.chipsel {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  max-height: 170px;
  overflow: auto;
}
.chip {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  padding: 4px 9px;
  border: 1px solid var(--line);
  border-radius: 99px;
  background: var(--panel-raised);
  color: var(--ink-dim);
  font-family: var(--font-mono);
  font-size: 11px;
  cursor: pointer;
}
.chip i {
  font-size: 10px;
}
.chip.on {
  border-color: #6366f1;
  background: #6366f1;
  color: #fff;
}
.chip--mcp.on {
  border-color: #0ea5e9;
  background: #0ea5e9;
}
.chip.warn:not(.on) {
  border-style: dashed;
}
.mini {
  opacity: 0.7;
}
.modes {
  margin-top: 10px;
}
.modes button small {
  line-height: 1.3;
}
.toggles {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  margin-top: 10px;
}
.check {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 13px;
}
.input.mini {
  padding: 2px 6px;
  width: auto;
}
.grid2,
.grid3 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.grid3 {
  grid-template-columns: repeat(3, 1fr);
  margin-top: 8px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
}
.label {
  font-size: 12px;
  font-weight: 700;
}
.input.bad {
  border-color: var(--crit);
}
textarea.input {
  resize: vertical;
  font-family: inherit;
}
.prev {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  border-left: 1px solid var(--line);
  background: var(--panel-raised);
  overflow: auto;
}
.pv-card {
  padding: 14px;
  border-radius: 16px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-top: 5px solid var(--c);
}
.pv-h {
  display: flex;
  gap: 10px;
  align-items: center;
}
.pv-h b {
  display: block;
  font-size: 15px;
}
.pv-h small {
  color: var(--c);
  font-weight: 800;
}
.pv-av {
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  background: var(--c);
  color: #fff;
  font-size: 20px;
}
.pv-desc {
  margin: 10px 0;
  font-size: 12.5px;
  color: var(--ink-dim);
}
dl {
  margin: 0;
  display: grid;
  gap: 4px;
  font-size: 12px;
}
dt {
  font-weight: 800;
  color: var(--ink-faint);
  font-size: 10.5px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin-top: 6px;
}
dd {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.pv-ins {
  margin-top: 10px;
  padding: 8px;
  border-radius: 10px;
  background: var(--panel-raised);
  font-size: 11.5px;
  color: var(--ink-dim);
  white-space: pre-wrap;
}
.pv-ins b {
  display: block;
  color: var(--ink);
}
.warns {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.warns li {
  font-size: 12px;
  padding: 7px 9px;
  border-radius: 10px;
  background: #fef3c7;
  color: #92400e;
}
.pv-act {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: auto;
}
@media (max-width: 860px) {
  .wiz-b {
    grid-template-columns: 1fr;
    overflow: auto;
  }
  .steps {
    overflow: visible;
  }
  .prev {
    border-left: 0;
    border-top: 1px solid var(--line);
  }
  .brains,
  .grid2,
  .grid3 {
    grid-template-columns: 1fr;
  }
}
</style>
