<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import AgentAvatar from "../components/AgentAvatar.vue";
import Card from "../components/Card.vue";
import {
  ROLE_TEXT, api, applyLook, live, look, post, refreshAll,
  type Agent, type Project, type Settings, type Skill,
} from "../api";

const route = useRoute();
const router = useRouter();

const SECTIONS = [
  { id: "agentes", text: "Agentes" },
  { id: "proyectos", text: "Proyectos" },
  { id: "aprobaciones", text: "Aprobaciones" },
  { id: "ejecucion", text: "Ejecución" },
  { id: "skills", text: "Skills y memoria" },
  { id: "apariencia", text: "Apariencia" },
] as const;
const section = computed(() => (route.query.s as string) || "agentes");
const go = (id: string) => router.replace({ query: { s: id } });

// --- ajustes del servidor: se editan en un borrador y se guardan juntos
const saved = ref<Settings | null>(null);
const defaults = ref<Settings | null>(null);
const draft = ref<Settings | null>(null);
const msg = ref("");
const error = ref("");
const providers = ref<string[]>(["claude", "codex", "local"]);
const skills = ref<Skill[]>([]);

// las listas de patrones y carpetas se editan como texto, una por línea
const lists = reactive({ sensitive: "", dependency: "", config: "", skill_dirs: "" });
const toLines = (a: string[]) => a.join("\n");
const fromLines = (s: string) => s.split("\n").map((l) => l.trim()).filter(Boolean);

function take(s: { values: Settings; defaults: Settings }) {
  saved.value = s.values;
  defaults.value = s.defaults;
  draft.value = JSON.parse(JSON.stringify(s.values));
  lists.sensitive = toLines(s.values.policy.sensitive);
  lists.dependency = toLines(s.values.policy.dependency);
  lists.config = toLines(s.values.policy.config);
  lists.skill_dirs = toLines(s.values.context.skill_dirs);
}

function current(): Settings | null {
  if (!draft.value) return null;
  const d: Settings = JSON.parse(JSON.stringify(draft.value));
  d.policy.sensitive = fromLines(lists.sensitive);
  d.policy.dependency = fromLines(lists.dependency);
  d.policy.config = fromLines(lists.config);
  d.context.skill_dirs = fromLines(lists.skill_dirs);
  return d;
}

const dirty = computed(() => {
  const c = current();
  return !!c && JSON.stringify(c) !== JSON.stringify(saved.value);
});

async function loadSkills() {
  skills.value = await api<Skill[]>("/api/skills");
}

onMounted(async () => {
  try {
    const [s, h] = await Promise.all([
      api<{ values: Settings; defaults: Settings }>("/api/settings"),
      api<{ providers: string[] }>("/api/health"),
    ]);
    take(s);
    providers.value = h.providers;
    resetNewAgent();
    await loadSkills();
  } catch (e) {
    error.value = (e as Error).message;
  }
});

async function save() {
  error.value = msg.value = "";
  try {
    take(await api("/api/settings", { method: "PUT", body: JSON.stringify(current()) }));
    msg.value = "Guardado. Se aplica a lo que arranque a partir de ahora.";
    await loadSkills();
  } catch (e) {
    error.value = (e as Error).message;
  }
}

function discard() {
  if (saved.value && defaults.value) take({ values: saved.value, defaults: defaults.value });
}

async function resetAll() {
  if (!window.confirm("¿Volver a los valores por defecto en aprobaciones, ejecución, skills y agentes nuevos?")) return;
  take(await post("/api/settings/reset"));
  msg.value = "Valores por defecto restaurados.";
}

// --- proyectos
const proj = reactive({ name: "", repo_path: "" });
const projError = ref("");
const memEdit = reactive<Record<number, string>>({});

async function addProject() {
  projError.value = "";
  try {
    await post<Project>("/api/projects", proj);
    proj.name = proj.repo_path = "";
    await refreshAll();
  } catch (e) {
    projError.value = (e as Error).message;
  }
}

async function saveMemory(p: Project) {
  projError.value = "";
  try {
    await api(`/api/projects/${p.id}`, { method: "PATCH", body: JSON.stringify({ memory_dir: memEdit[p.id] }) });
    delete memEdit[p.id];
    await refreshAll();
  } catch (e) {
    projError.value = (e as Error).message;
  }
}

// --- agentes
interface AgentForm {
  name: string;
  provider: string;
  model: string;
  role: string;
  max_turns: number | null;
  max_budget_usd: number | null;
  read_only: boolean;
  skills: string[];
  base_url: string;
  description: string;
}
const blank = (): AgentForm => ({
  name: "", provider: "claude", model: "", role: "trabajador", max_turns: null, max_budget_usd: null,
  read_only: false, skills: [], base_url: "", description: "",
});
const newAgent = reactive<AgentForm>(blank());
const showNew = ref(false);
const agError = ref("");
const editing = ref<number | null>(null);
const edit = reactive<AgentForm>(blank());

function resetNewAgent() {
  const d = saved.value?.agent_defaults;
  Object.assign(newAgent, blank(), d ? { ...d, model: d.model ?? "" } : {});
}

async function addAgent() {
  agError.value = "";
  try {
    await post<Agent>("/api/agents", {
      ...newAgent, model: newAgent.model || null, role: newAgent.role || null,
      base_url: newAgent.provider === "local" ? newAgent.base_url || null : null,
    });
    resetNewAgent();
    showNew.value = false;
    await refreshAll();
  } catch (e) {
    agError.value = (e as Error).message;
  }
}

function startEdit(a: Agent) {
  editing.value = a.id;
  Object.assign(edit, {
    name: a.name, provider: a.provider, model: a.model ?? "", role: a.role ?? "",
    max_turns: a.config.max_turns ?? null, max_budget_usd: a.config.max_budget_usd ?? null,
    read_only: !!a.config.read_only, skills: [...(a.config.skills ?? [])], base_url: a.config.base_url ?? "",
    description: a.config.description ?? "",
  });
}

async function saveAgent(a: Agent) {
  agError.value = "";
  try {
    await api(`/api/agents/${a.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        model: edit.model, role: edit.role, max_turns: edit.max_turns || null,
        max_budget_usd: edit.max_budget_usd || null, read_only: edit.read_only, skills: edit.skills,
        description: edit.description,
        ...(a.provider === "local" ? { base_url: edit.base_url } : {}),
      }),
    });
    editing.value = null;
    await refreshAll();
  } catch (e) {
    agError.value = (e as Error).message;
  }
}

async function removeAgent(a: Agent) {
  if (!window.confirm(`¿Borrar el agente ${a.name}?`)) return;
  agError.value = "";
  try {
    await api(`/api/agents/${a.id}`, { method: "DELETE" });
    await refreshAll();
  } catch (e) {
    agError.value = (e as Error).message;
  }
}

function limits(a: Agent): string {
  const c = a.config;
  return [
    c.max_turns ? `${c.max_turns} turnos` : null,
    c.max_budget_usd ? `máx. ${c.max_budget_usd} $` : null,
    c.read_only ? "solo lectura" : null,
    c.base_url ? c.base_url : null,
  ].filter(Boolean).join(" · ") || "sin límites";
}

watch(look, applyLook, { deep: true });
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2 class="title">Ajustes</h2>
      <p>Todo lo que se puede ajustar de momento. Lo de apariencia solo afecta a este navegador.</p>
    </div>

    <nav class="tabs" aria-label="Secciones de ajustes">
      <button
        v-for="s in SECTIONS" :key="s.id" class="tab" :class="{ 'tab--on': section === s.id }"
        :aria-current="section === s.id ? 'page' : undefined" @click="go(s.id)"
      >{{ s.text }}</button>
    </nav>

    <p v-if="error" class="error">{{ error }}</p>

    <!-- AGENTES -->
    <template v-if="section === 'agentes'">
      <Card title="Agentes" subtitle="Cada agente es una configuración: proveedor, modelo, rol, límites y skills.">
        <template #actions>
          <button class="btn btn--primary btn--small" @click="showNew = !showNew">{{ showNew ? "Cerrar" : "Nuevo agente" }}</button>
        </template>

        <form v-if="showNew" class="agent-form new-agent" @submit.prevent="addAgent">
          <label class="field"><span class="label">Nombre</span><input v-model.trim="newAgent.name" required placeholder="sonnet-trabajador" /></label>
          <label class="field">
            <span class="label">Proveedor</span>
            <select v-model="newAgent.provider"><option v-for="p in providers" :key="p">{{ p }}</option></select>
          </label>
          <label class="field"><span class="label">Modelo</span><input v-model.trim="newAgent.model" placeholder="por defecto" /></label>
          <label class="field">
            <span class="label">Rol</span>
            <select v-model="newAgent.role">
              <option value="trabajador">Trabajador</option><option value="director">Director</option>
              <option value="jefe">Jefe técnico</option><option value="">Sin rol</option>
            </select>
          </label>
          <label class="field"><span class="label">Turnos máx.</span><input v-model.number="newAgent.max_turns" type="number" min="1" /></label>
          <label class="field"><span class="label">Tope en $</span><input v-model.number="newAgent.max_budget_usd" type="number" min="0.01" step="0.01" /></label>
          <label class="field wide">
            <span class="label">Descripción</span>
            <input v-model.trim="newAgent.description" placeholder="En qué es bueno (el Director lo lee para repartir trabajo)" />
          </label>
          <label v-if="newAgent.provider === 'local'" class="field wide">
            <span class="label">URL del llama-server</span>
            <input v-model.trim="newAgent.base_url" :placeholder="saved?.local_base_url" class="code" />
          </label>
          <fieldset v-if="skills.length" class="skills-pick wide">
            <legend class="label">Skills siempre activas</legend>
            <label v-for="s in skills" :key="s.name" class="pick" :title="s.description">
              <input v-model="newAgent.skills" type="checkbox" :value="s.name" /> {{ s.name }}
            </label>
          </fieldset>
          <label class="check"><input v-model="newAgent.read_only" type="checkbox" /> Solo lectura</label>
          <div class="row wide"><button class="btn btn--primary">Crear agente</button></div>
        </form>

        <p v-if="agError" class="error">{{ agError }}</p>
        <p v-if="!live.agents.length" class="empty">Aún no hay agentes.</p>

        <ul class="agents">
          <li v-for="a in live.agents" :key="a.id" class="agent">
            <div class="agent__row">
              <AgentAvatar :agent="a" :size="36" />
              <div class="agent__who">
                <strong>{{ a.name }}</strong>
                <span class="muted small">{{ ROLE_TEXT[a.role ?? ""] ?? a.role ?? "sin rol" }} · {{ a.provider }}
                  {{ a.model ?? "(modelo por defecto)" }}</span>
              </div>
              <span class="agent__limits small muted">{{ limits(a) }}</span>
              <span v-if="a.config.description" class="small desc">{{ a.config.description }}</span>
              <span v-if="a.config.skills?.length" class="small tagline">{{ a.config.skills.join(", ") }}</span>
              <div class="row agent__actions">
                <button class="btn btn--small" @click="editing === a.id ? (editing = null) : startEdit(a)">
                  {{ editing === a.id ? "Cerrar" : "Editar" }}
                </button>
                <button class="btn btn--small btn--ghost" title="Solo si no tiene historial" @click="removeAgent(a)">Borrar</button>
              </div>
            </div>
            <form v-if="editing === a.id" class="agent-form" @submit.prevent="saveAgent(a)">
              <label class="field"><span class="label">Modelo</span><input v-model.trim="edit.model" placeholder="por defecto" /></label>
              <label class="field">
                <span class="label">Rol</span>
                <select v-model="edit.role">
                  <option value="trabajador">Trabajador</option><option value="director">Director</option>
                  <option value="jefe">Jefe técnico</option><option value="">Sin rol</option>
                </select>
              </label>
              <label class="field"><span class="label">Turnos máx.</span><input v-model.number="edit.max_turns" type="number" min="1" /></label>
              <label class="field"><span class="label">Tope en $</span><input v-model.number="edit.max_budget_usd" type="number" min="0.01" step="0.01" /></label>
              <label class="field wide">
                <span class="label">Descripción</span>
                <input v-model.trim="edit.description" placeholder="En qué es bueno (el Director lo lee para repartir trabajo)" />
              </label>
              <label v-if="a.provider === 'local'" class="field wide">
                <span class="label">URL del llama-server</span>
                <input v-model.trim="edit.base_url" :placeholder="saved?.local_base_url" class="code" />
              </label>
              <fieldset v-if="skills.length" class="skills-pick wide">
                <legend class="label">Skills siempre activas</legend>
                <label v-for="s in skills" :key="s.name" class="pick" :title="s.description">
                  <input v-model="edit.skills" type="checkbox" :value="s.name" /> {{ s.name }}
                </label>
              </fieldset>
              <label class="check"><input v-model="edit.read_only" type="checkbox" /> Solo lectura</label>
              <div class="row wide"><button class="btn btn--primary">Guardar agente</button></div>
            </form>
          </li>
        </ul>
      </Card>

      <Card v-if="draft" title="Valores para agentes nuevos" subtitle="Lo que aparece rellenado al crear un agente.">
        <div class="grid">
          <label class="field">
            <span class="label">Proveedor</span>
            <select v-model="draft.agent_defaults.provider"><option v-for="p in providers" :key="p">{{ p }}</option></select>
          </label>
          <label class="field"><span class="label">Modelo</span><input v-model.trim="draft.agent_defaults.model" /></label>
          <label class="field"><span class="label">Turnos máx.</span><input v-model.number="draft.agent_defaults.max_turns" type="number" min="1" /></label>
          <label class="field"><span class="label">Tope en $</span><input v-model.number="draft.agent_defaults.max_budget_usd" type="number" min="0.01" step="0.01" /></label>
        </div>
      </Card>
    </template>

    <!-- PROYECTOS -->
    <Card v-else-if="section === 'proyectos'" title="Proyectos" subtitle="Repos git donde trabajan los agentes (cada tarea en su propio worktree).">
      <ul class="projects">
        <li v-for="p in live.projects" :key="p.id" class="project">
          <div class="project__head">
            <strong>{{ p.name }}</strong>
            <code class="muted">{{ p.repo_path }}</code>
          </div>
          <div class="project__mem">
            <span class="label">Memoria del proyecto</span>
            <template v-if="memEdit[p.id] === undefined">
              <code v-if="p.memory_dir">{{ p.memory_dir }}</code>
              <span v-else class="muted small">sin carpeta (los agentes no reciben memoria)</span>
              <button class="btn btn--small btn--ghost" @click="memEdit[p.id] = p.memory_dir ?? ''">Cambiar</button>
            </template>
            <form v-else class="row" @submit.prevent="saveMemory(p)">
              <input v-model.trim="memEdit[p.id]" class="input code grow" placeholder="D:\ruta\a\memoria (vacío = ninguna)" />
              <button class="btn btn--small btn--primary">Guardar</button>
              <button type="button" class="btn btn--small btn--ghost" @click="delete memEdit[p.id]">Cancelar</button>
            </form>
          </div>
        </li>
      </ul>
      <p v-if="!live.projects.length" class="empty">Aún no hay proyectos. Registra un repo git con al menos un commit.</p>
      <form class="add-project" @submit.prevent="addProject">
        <label class="field"><span class="label">Nombre</span><input v-model.trim="proj.name" required /></label>
        <label class="field grow">
          <span class="label">Ruta del repo</span>
          <input v-model.trim="proj.repo_path" required placeholder="D:\ruta\al\repo" class="code" />
        </label>
        <button class="btn btn--primary">Añadir proyecto</button>
      </form>
      <p v-if="projError" class="error">{{ projError }}</p>
    </Card>

    <!-- APROBACIONES -->
    <template v-else-if="section === 'aprobaciones' && draft">
      <Card title="Cuándo te lo pasan a ti" subtitle="Un cambio que supere cualquiera de estos límites sube a N2: lo decides tú.">
        <div class="grid">
          <label class="field">
            <span class="label">Archivos por subtarea</span>
            <input v-model.number="draft.policy.max_files" type="number" min="1" />
            <span class="hint">Más de esto = cambio grande.</span>
          </label>
          <label class="field">
            <span class="label">Líneas cambiadas</span>
            <input v-model.number="draft.policy.max_lines" type="number" min="1" />
            <span class="hint">Sumando añadidas y borradas.</span>
          </label>
          <label class="field">
            <span class="label">Subtareas sin preguntarte</span>
            <input v-model.number="draft.policy.max_auto_subtasks" type="number" min="0" />
            <span class="hint">Un plan con más espera tu aprobación.</span>
          </label>
        </div>
      </Card>
      <Card title="Archivos delicados" subtitle="Patrones (uno por línea). Tocar cualquiera de ellos es siempre N2.">
        <div class="grid grid--3">
          <label class="field"><span class="label">Sensibles</span><textarea v-model="lists.sensitive" rows="8" class="code" /></label>
          <label class="field"><span class="label">Dependencias</span><textarea v-model="lists.dependency" rows="8" class="code" /></label>
          <label class="field"><span class="label">Configuración / CI</span><textarea v-model="lists.config" rows="8" class="code" /></label>
        </div>
      </Card>
    </template>

    <!-- EJECUCIÓN -->
    <Card v-else-if="section === 'ejecucion' && draft" title="Ejecución">
      <div class="grid">
        <label class="field">
          <span class="label">Tiempo máximo por tarea (min)</span>
          <input v-model.number="draft.task_timeout_min" type="number" min="1" max="600" />
          <span class="hint">Pasado esto se corta y queda como «tiempo agotado».</span>
        </label>
        <label class="field wide">
          <span class="label">URL del llama-server por defecto</span>
          <input v-model.trim="draft.local_base_url" class="code" />
          <span class="hint">Para agentes locales que no tengan una propia.</span>
        </label>
      </div>
    </Card>

    <!-- SKILLS -->
    <template v-else-if="section === 'skills' && draft">
      <Card title="Contexto que reciben los agentes">
        <div class="grid">
          <label class="field">
            <span class="label">Memoria del proyecto (caracteres)</span>
            <input v-model.number="draft.context.max_memory_chars" type="number" min="0" step="1000" />
          </label>
          <label class="field">
            <span class="label">Skills por tarea (caracteres)</span>
            <input v-model.number="draft.context.max_skill_chars" type="number" min="0" step="1000" />
          </label>
          <label class="field wide">
            <span class="label">Carpetas extra de skills</span>
            <textarea v-model="lists.skill_dirs" rows="3" class="code" placeholder="D:\Lukaton1\.claude\skills\superpowers\skills" />
            <span class="hint">Una por línea. Se suman a las del repo y a LOCALHARNESS_SKILL_DIRS.</span>
          </label>
        </div>
      </Card>
      <Card :title="`Skills disponibles (${skills.length})`" subtitle="Se asignan a un agente (Agentes → Editar) o las elige el Director por subtarea.">
        <ul class="skill-list">
          <li v-for="s in skills" :key="s.name">
            <strong>{{ s.name }}</strong>
            <span class="muted small">{{ s.description }}</span>
          </li>
        </ul>
        <p v-if="!skills.length" class="empty">No se ha encontrado ninguna skill.</p>
      </Card>
    </template>

    <!-- APARIENCIA -->
    <Card v-else-if="section === 'apariencia'" title="Apariencia" subtitle="Se guarda en este navegador.">
      <div class="grid">
        <fieldset class="field seg-field">
          <legend class="label">Tema</legend>
          <div class="seg">
            <label v-for="t in (['auto', 'claro', 'oscuro'] as const)" :key="t" :class="{ on: look.theme === t }">
              <input v-model="look.theme" type="radio" :value="t" class="sr-only" />{{ t === "auto" ? "Como el sistema" : t[0].toUpperCase() + t.slice(1) }}
            </label>
          </div>
        </fieldset>
        <fieldset class="field seg-field">
          <legend class="label">Densidad</legend>
          <div class="seg">
            <label v-for="d in (['normal', 'compacta'] as const)" :key="d" :class="{ on: look.density === d }">
              <input v-model="look.density" type="radio" :value="d" class="sr-only" />{{ d[0].toUpperCase() + d.slice(1) }}
            </label>
          </div>
        </fieldset>
        <label class="field">
          <span class="label">Tamaño: {{ Math.round(look.zoom * 100) }} %</span>
          <input v-model.number="look.zoom" type="range" min="0.8" max="1.3" step="0.05" />
        </label>
      </div>
    </Card>

    <div v-if="dirty || msg" class="savebar" :class="{ 'savebar--dirty': dirty }">
      <span>{{ dirty ? "Tienes cambios sin guardar." : msg }}</span>
      <template v-if="dirty">
        <button class="btn btn--ghost" @click="discard">Descartar</button>
        <button class="btn btn--primary" @click="save">Guardar cambios</button>
      </template>
    </div>
    <p v-if="['aprobaciones', 'ejecucion', 'skills', 'agentes'].includes(section)" class="reset">
      <button class="btn btn--ghost btn--small" @click="resetAll">Restaurar valores por defecto</button>
    </p>
  </div>
</template>

<style scoped>
.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 4px;
  border-radius: 999px;
  background: var(--panel-raised);
  border: 1px solid var(--line);
  width: fit-content;
  max-width: 100%;
}
.tab {
  padding: 7px 16px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--ink-dim);
  font-weight: 600;
  cursor: pointer;
}
.tab:hover {
  color: var(--ink);
}
.tab--on {
  background: var(--panel);
  color: var(--ink);
  box-shadow: var(--shadow);
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
}
.grid--3 {
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}
.wide {
  grid-column: 1 / -1;
}
.grow {
  flex: 1;
  min-width: 200px;
}
.agents,
.projects,
.skill-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.agent {
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--panel-raised);
}
.agent__row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 14px;
}
.agent__who {
  display: grid;
  min-width: 180px;
}
.agent__limits {
  flex: 1;
}
.desc {
  flex-basis: 100%;
  padding-left: 50px;
  color: var(--ink-dim);
}
.tagline {
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--accent-weak);
  color: var(--accent);
  font-weight: 600;
}
.agent__actions {
  margin-left: auto;
}
.agent-form {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}
.new-agent {
  margin: 0 0 16px;
  padding: 16px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius-sm);
}
.skills-pick {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  margin: 0;
  padding: 0;
  border: 0;
}
.skills-pick legend {
  margin-bottom: 6px;
}
.pick,
.check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
}
.check {
  align-self: end;
  padding-bottom: 9px;
}
.project {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--panel-raised);
}
.project__head {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  align-items: baseline;
}
.project__head code {
  overflow-wrap: anywhere;
}
.project__mem {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.add-project {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
  margin-top: 16px;
}
.skill-list li {
  display: grid;
  gap: 2px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--panel-raised);
}
.seg-field {
  margin: 0;
  padding: 0;
  border: 0;
}
.seg {
  display: inline-flex;
  gap: 4px;
  padding: 3px;
  border-radius: 999px;
  background: var(--panel-raised);
  border: 1px solid var(--line);
  margin-top: 5px;
}
.seg label {
  padding: 5px 12px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 14px;
  color: var(--ink-dim);
}
.seg label.on {
  background: var(--panel);
  color: var(--ink);
  box-shadow: var(--shadow);
  font-weight: 600;
}
.seg label:focus-within {
  outline: 2px solid var(--accent);
}
input[type="range"] {
  accent-color: var(--accent);
}
.savebar {
  position: sticky;
  bottom: 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: flex-end;
  padding: 10px 12px 10px 18px;
  border-radius: 999px;
  background: var(--panel);
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
  color: var(--ok);
  font-weight: 600;
}
.savebar span {
  margin-right: auto;
}
.savebar--dirty {
  color: var(--ink);
  border-color: var(--accent);
}
.reset {
  margin: 0;
}
</style>
