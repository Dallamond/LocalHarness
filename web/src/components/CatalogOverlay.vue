<script setup lang="ts">
// Catálogo (prototipo v2.1): agentes reales, skills y servidores MCP. Se asignan skills, servidores MCP,
// internet y el modelo local a cada agente; se importan SKILL.md, JSON `mcpServers` y agentes (.md o JSON).
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  PROVIDER_TEXT, ROLE_TEXT, agentColor, api, live, modelText, post, refreshAll, ui,
  type Agent, type McpServer, type Settings, type Skill,
} from "../api";

const router = useRouter();
const tab = computed({
  get: () => ui.catalog?.tab ?? "agents",
  set: (t) => { if (ui.catalog) ui.catalog = { ...ui.catalog, tab: t, open: null }; },
});
const open = computed({
  get: () => ui.catalog?.open ?? null,
  set: (v) => { if (ui.catalog) ui.catalog = { ...ui.catalog, open: v }; },
});
const q = ref("");
const error = ref("");
const skills = ref<Skill[]>([]);
const servers = ref<Record<string, McpServer>>({});

async function load() {
  const [sk, st] = await Promise.all([api<Skill[]>("/api/skills"), api<{ values: Settings }>("/api/settings")]);
  skills.value = sk;
  servers.value = st.values.mcp_servers ?? {};
}
function close() { ui.catalog = null; }
const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") (importing.value ? (importing.value = false) : close()); };
onMounted(() => { load().catch((e) => (error.value = (e as Error).message)); window.addEventListener("keydown", onKey); });
onUnmounted(() => window.removeEventListener("keydown", onKey));

const hit = (o: unknown) => !q.value || JSON.stringify(o).toLowerCase().includes(q.value.toLowerCase());
const agents = computed(() => live.agents.filter(hit));
const skillList = computed(() => skills.value.filter(hit));
const serverList = computed(() => Object.entries(servers.value).filter(([n, s]) => hit({ n, s })));
const usesSkill = (n: string) => live.agents.filter((a) => (a.config.skills ?? []).includes(n));
const usesMcp = (n: string) => live.agents.filter((a) => (n === "local" ? a.config.delegate_local : (a.config.mcps ?? []).includes(n)));

const SUB = {
  agents: "Tus agentes. Asígnales skills (procedimientos que se inyectan en el prompt) y herramientas: servidores MCP, internet y el modelo local. Solo los agentes Claude usan herramientas; los locales de momento solo responden.",
  skills: "Procedimientos en SKILL.md que se añaden al prompt del agente. Las importadas se guardan en data/skills (fuera de git).",
  mcp: "Servidores MCP que dan herramientas a los agentes Claude. Se arrancan con cada tarea del agente que los tenga asignados (no hace falta conectarlos antes).",
};

// ---------- asignar a un agente (cada cambio se guarda al momento)
const saving = ref<number | null>(null);
async function patch(a: Agent, body: Record<string, unknown>) {
  saving.value = a.id;
  error.value = "";
  try {
    const r = await api<Agent>(`/api/agents/${a.id}`, { method: "PATCH", body: JSON.stringify(body) });
    const i = live.agents.findIndex((x) => x.id === a.id);
    if (i >= 0) live.agents[i] = r;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    saving.value = null;
  }
}
const toggle = (list: string[] | undefined, v: string, on: boolean) => (on ? [...new Set([...(list ?? []), v])] : (list ?? []).filter((x) => x !== v));
async function removeAgent(a: Agent) {
  if (!window.confirm(`¿Borrar el agente ${a.name}?`)) return;
  try {
    await api(`/api/agents/${a.id}`, { method: "DELETE" });
    await refreshAll();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
function inOffice(a: Agent) {
  ui.focusAgent = a.id;
  close();
  router.push("/oficina");
}
async function removeSkill(s: Skill) {
  if (!window.confirm(`¿Borrar la skill ${s.name}?`)) return;
  try {
    await api(`/api/skills/${encodeURIComponent(s.name)}`, { method: "DELETE" });
    await load();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
async function saveServers(next: Record<string, McpServer>) {
  const r = await api<{ values: Settings }>("/api/settings", { method: "PUT", body: JSON.stringify({ mcp_servers: next }) });
  servers.value = r.values.mcp_servers ?? {};
}
async function removeServer(name: string) {
  if (!window.confirm(`¿Quitar el servidor MCP ${name}? Los agentes que lo tengan dejarán de cargarlo.`)) return;
  const next = { ...servers.value };
  delete next[name];
  try {
    await saveServers(next);
    for (const a of usesMcp(name)) await patch(a, { mcps: toggle(a.config.mcps, name, false) });
  } catch (e) {
    error.value = (e as Error).message;
  }
}
const cmdOf = (s: McpServer) => s.url ?? [s.command, ...(s.args ?? [])].filter(Boolean).join(" ");

// ---------- importar
const importing = ref(false);
const text = ref("");
const drag = ref(false);
interface Parsed { agents: AgentDraft[]; skills: string[]; mcps: Record<string, McpServer>; err: string | null }
interface AgentDraft { name: string; provider: string; model: string | null; role: string | null; description: string | null; skills: string[] }

function frontmatter(t: string): Record<string, string> | null {
  const m = t.replace(/^﻿/, "").match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!m) return null;
  const d: Record<string, string> = {};
  m[1].split(/\r?\n/).forEach((l) => {
    const k = l.match(/^([\w-]+):\s*(.*)$/);
    if (k) d[k[1]] = k[2].replace(/^["']|["']$/g, "");
  });
  return d;
}
const asList = (v: unknown) => (Array.isArray(v) ? v.map(String) : String(v ?? "").split(/[,\s]+/).filter(Boolean));
const CLAUDE_RE = /claude|sonnet|opus|haiku|fable/i;
const ROLES = ["director", "jefe", "trabajador", "consultas"];
function draft(o: Record<string, unknown>): AgentDraft {
  const model = o.model ? String(o.model) : null;
  const provider = o.provider ? String(o.provider) : model && !CLAUDE_RE.test(model) ? "local" : "claude";
  const role = ROLES.includes(String(o.role)) ? String(o.role) : "trabajador";
  return { name: String(o.name).trim().slice(0, 60), provider, model: provider === "local" ? null : model, role,
    description: (o.description ?? o.desc ?? null) as string | null, skills: asList(o.skills) };
}
function parse(t: string, fname = ""): Parsed {
  const out: Parsed = { agents: [], skills: [], mcps: {}, err: null };
  t = t.trim();
  if (!t) return { ...out, err: "Vacío" };
  if (t[0] === "{" || t[0] === "[") {
    let j: unknown;
    try { j = JSON.parse(t); } catch (e) { return { ...out, err: `JSON no válido: ${(e as Error).message}` }; }
    const o = j as Record<string, unknown>;
    const srv = !Array.isArray(j) && ((o.mcpServers ?? o.servers ?? ((o.command || o.url) ? { [fname.replace(/\.\w+$/, "") || "servidor"]: o } : null)) as Record<string, McpServer> | null);
    if (srv) Object.entries(srv).forEach(([n, c]) => (out.mcps[n.replace(/[^A-Za-z0-9_-]+/g, "-").slice(0, 40)] = c));
    const ag = Array.isArray(j) ? j : Array.isArray(o.agents) ? o.agents : !srv && o.name && (o.role || o.model) ? [o] : null;
    (ag as Record<string, unknown>[] | null)?.forEach((a) => a?.name && out.agents.push(draft(a)));
  } else {
    const fm = frontmatter(t);
    if (!fm?.name) return { ...out, err: "Formato no reconocido: usa JSON (mcpServers / agents) o Markdown con frontmatter que incluya name" };
    if (fm.model || fm.tools || fm.role || fm.provider) out.agents.push(draft(fm));
    else out.skills.push(t);
  }
  if (!out.agents.length && !out.skills.length && !Object.keys(out.mcps).length) out.err = "No se ha encontrado nada importable";
  return out;
}
function summary(p: Parsed): string {
  const n = Object.keys(p.mcps).length;
  return [p.agents.length && `${p.agents.length} agente${p.agents.length > 1 ? "s" : ""}`,
    p.skills.length && `${p.skills.length} skill${p.skills.length > 1 ? "s" : ""}`,
    n && `${n} servidor${n > 1 ? "es" : ""} MCP`].filter(Boolean).join(" · ");
}
const detected = computed(() => (text.value.trim() ? parse(text.value) : null));
const result = ref("");

async function commit(p: Parsed) {
  const errs: string[] = [];
  for (const s of p.skills) {
    try { await post("/api/skills", { content: s }); } catch (e) { errs.push((e as Error).message); }
  }
  if (Object.keys(p.mcps).length) {
    try { await saveServers({ ...servers.value, ...p.mcps }); } catch (e) { errs.push((e as Error).message); }
  }
  for (const a of p.agents) {
    try {
      await post("/api/agents", { ...a, max_turns: a.provider === "claude" ? 10 : null, max_budget_usd: a.provider === "claude" ? 0.5 : null });
    } catch (e) { errs.push(`${a.name}: ${(e as Error).message}`); }
  }
  await Promise.all([load(), refreshAll()]).catch(() => {});
  tab.value = p.agents.length && !p.skills.length && !Object.keys(p.mcps).length ? "agents"
    : p.skills.length && !p.agents.length && !Object.keys(p.mcps).length ? "skills" : Object.keys(p.mcps).length ? "mcp" : tab.value;
  return errs;
}
async function doImport() {
  const p = parse(text.value);
  if (p.err) return;
  const errs = await commit(p);
  result.value = errs.length ? errs.join(" · ") : `Importado: ${summary(p)}`;
  if (!errs.length) { text.value = ""; importing.value = false; }
}
async function importFiles(files: File[]) {
  const all: Parsed = { agents: [], skills: [], mcps: {}, err: null };
  const errs: string[] = [];
  for (const f of files) {
    const p = parse(await f.text(), f.name);
    if (p.err) errs.push(`${f.name}: ${p.err}`);
    else { all.agents.push(...p.agents); all.skills.push(...p.skills); Object.assign(all.mcps, p.mcps); }
  }
  if (all.agents.length || all.skills.length || Object.keys(all.mcps).length) errs.push(...(await commit(all)));
  result.value = errs.length ? errs.join(" · ") : `Importado: ${summary(all)}`;
  if (!errs.length) importing.value = false;
}
function onFiles(e: Event) {
  const input = e.target as HTMLInputElement;
  importFiles([...(input.files ?? [])]);
  input.value = "";
}
function onDrop(e: DragEvent) {
  drag.value = false;
  if (e.dataTransfer?.files.length) importFiles([...e.dataTransfer.files]);
}
const EXAMPLES: Record<string, string> = {
  mcp: '{\n  "mcpServers": {\n    "fetch": { "command": "uvx", "args": ["mcp-server-fetch"] },\n    "playwright": { "command": "npx", "args": ["@playwright/mcp@latest", "--headless"] }\n  }\n}',
  skill: "---\nname: resumen-semanal\ndescription: Resume los cambios de la semana del repo\n---\n\n1. Mira el git log de los últimos 7 días\n2. Agrupa por tema\n3. Devuelve 5 viñetas y una acción para la semana",
  agent: "---\nname: revisor-docs\ndescription: Revisa la documentación y propone mejoras concretas\nmodel: sonnet\nrole: jefe\n---\n",
};
</script>

<template>
  <div class="overlay" @mousedown.self="close">
    <div class="cat card">
      <div class="cat-h">
        <h2><i class="fa-solid fa-boxes-stacked" /> Catálogo</h2>
        <div class="cat-tabs">
          <button :class="{ on: tab === 'agents' }" @click="tab = 'agents'"><i class="fa-solid fa-user-astronaut" />Agentes<span class="n">{{ live.agents.length }}</span></button>
          <button :class="{ on: tab === 'skills' }" @click="tab = 'skills'"><i class="fa-solid fa-bolt" />Skills<span class="n">{{ skills.length }}</span></button>
          <button :class="{ on: tab === 'mcp' }" @click="tab = 'mcp'"><i class="fa-solid fa-plug" />Servidores MCP<span class="n">{{ Object.keys(servers).length + 1 }}</span></button>
        </div>
        <input v-model="q" class="input search" placeholder="Buscar…">
        <span class="spacer" />
        <button class="btn btn--primary" @click="importing = true; result = ''"><i class="fa-solid fa-file-import" /> Importar</button>
        <button class="icon-btn" title="Cerrar (Esc)" @click="close"><i class="fa-solid fa-xmark" /></button>
      </div>
      <div class="cat-sub">
        {{ SUB[tab] }}
        <span v-if="error" class="error"> · {{ error }}</span>
        <span v-if="result" class="ok"> · {{ result }}</span>
      </div>

      <div class="grid">
        <!-- agentes -->
        <template v-if="tab === 'agents'">
          <div v-for="a in agents" :key="a.id" class="cc" :style="{ '--c': agentColor(a) }">
            <div class="cc-h">
              <span class="av" :style="{ background: agentColor(a) }"><i class="fa-solid fa-user-astronaut" /></span>
              <div><b>{{ a.name }}</b><small>{{ ROLE_TEXT[a.role ?? ""] ?? a.role ?? "sin rol" }}</small></div>
              <span class="prov" :class="`prov--${a.provider}`">{{ PROVIDER_TEXT[a.provider] ?? a.provider }}</span>
            </div>
            <p>{{ a.config.description || "Sin descripción (el Director la lee para repartir trabajo)." }}</p>
            <div class="l">Modelo <span>{{ modelText(a) }}</span></div>
            <div class="chips">
              <span v-for="s in a.config.skills ?? []" :key="s" class="pill"><i class="fa-solid fa-bolt" />{{ s }}</span>
              <span v-if="a.config.delegate_local" class="pill pill--ok"><i class="fa-solid fa-plug" />local</span>
              <span v-for="m in a.config.mcps ?? []" :key="m" class="pill pill--active"><i class="fa-solid fa-plug" />{{ m }}</span>
              <span v-if="a.config.web" class="pill pill--active"><i class="fa-solid fa-globe" />internet</span>
              <span v-if="!(a.config.skills ?? []).length && !a.config.delegate_local && !(a.config.mcps ?? []).length && !a.config.web" class="muted small">Sin skills ni herramientas extra</span>
            </div>
            <div class="cc-act">
              <span class="spacer" />
              <button class="btn btn--small" @click="inOffice(a)"><i class="fa-solid fa-location-crosshairs" /> En la oficina</button>
              <button class="btn btn--small" @click="open = open === a.id ? null : a.id"><i class="fa-solid fa-sliders" /> {{ open === a.id ? "Cerrar" : "Asignar" }}</button>
              <button class="btn btn--small btn--danger" title="Borrar (solo si no tiene historial)" @click="removeAgent(a)"><i class="fa-solid fa-trash" /></button>
            </div>
            <div v-if="open === a.id" class="edit" :class="{ busy: saving === a.id }">
              <div>
                <h5>Skills</h5>
                <label v-for="s in skills" :key="s.name" :title="s.description">
                  <input
                    type="checkbox" :checked="(a.config.skills ?? []).includes(s.name)"
                    @change="patch(a, { skills: toggle(a.config.skills, s.name, ($event.target as HTMLInputElement).checked) })"
                  >{{ s.name }}
                </label>
              </div>
              <div>
                <h5>Herramientas</h5>
                <template v-if="a.provider === 'claude'">
                  <label title="local_ask / local_write_file: el modelo arrancado en llama-server hace el trabajo gratis">
                    <input type="checkbox" :checked="!!a.config.delegate_local" @change="patch(a, { delegate_local: ($event.target as HTMLInputElement).checked })">local (modelo local)
                  </label>
                  <label title="WebSearch y WebFetch">
                    <input type="checkbox" :checked="!!a.config.web" @change="patch(a, { web: ($event.target as HTMLInputElement).checked })">internet
                  </label>
                  <label v-for="(s, n) in servers" :key="n" :title="cmdOf(s)">
                    <input
                      type="checkbox" :checked="(a.config.mcps ?? []).includes(String(n))"
                      @change="patch(a, { mcps: toggle(a.config.mcps, String(n), ($event.target as HTMLInputElement).checked) })"
                    >{{ n }}
                  </label>
                  <p v-if="!Object.keys(servers).length" class="muted small">Importa servidores MCP para asignarlos.</p>
                </template>
                <p v-else class="muted small">Los agentes locales aún no usan herramientas: solo responden con el repo en el prompt.</p>
              </div>
            </div>
          </div>
          <div class="cc cc--new">
            <i class="fa-solid fa-user-plus" />
            <b>Nuevo agente</b>
            <p>Créalo en Ajustes (Claude) o en Modelos locales (local), o impórtalo desde un .md con frontmatter.</p>
            <div class="row">
              <button class="btn btn--small" @click="close(); router.push('/ajustes?s=agentes')">Ajustes</button>
              <button class="btn btn--small" @click="close(); router.push('/modelos')">Modelos locales</button>
            </div>
          </div>
        </template>

        <!-- skills -->
        <template v-else-if="tab === 'skills'">
          <div v-for="s in skillList" :key="s.name" class="cc" style="--c: #6366f1">
            <div class="cc-h">
              <span class="av av--sm" style="background: #6366f1"><i class="fa-solid fa-bolt" /></span>
              <div><b class="mono">{{ s.name }}</b><small>{{ Math.round(s.chars / 100) / 10 }}k caracteres</small></div>
              <span class="badge" :class="{ imp: s.imported }">{{ s.imported ? "importada" : "de serie" }}</span>
            </div>
            <p>{{ s.description || "Sin descripción." }}</p>
            <div class="chips">
              <span v-for="a in usesSkill(s.name)" :key="a.id" class="pill"><i class="fa-solid fa-circle" :style="{ color: agentColor(a), fontSize: '7px' }" />{{ a.name }}</span>
              <span v-if="!usesSkill(s.name).length" class="muted small">Sin usar todavía</span>
            </div>
            <div v-if="s.imported" class="cc-act"><span class="spacer" />
              <button class="btn btn--small btn--danger" @click="removeSkill(s)"><i class="fa-solid fa-trash" /></button>
            </div>
          </div>
        </template>

        <!-- servidores MCP -->
        <template v-else>
          <div v-if="hit('local modelo')" class="cc" style="--c: #16a34a">
            <div class="cc-h">
              <span class="av av--sm" :style="{ background: live.local.state === 'ready' ? '#16a34a' : '#8a8f99' }"><i class="fa-solid fa-plug" /></span>
              <div><b class="mono">local</b><small><span class="dotst" :class="{ on: live.local.state === 'ready' }" /> {{ live.local.model ?? "sin modelo arrancado" }}</small></div>
              <span class="badge team">de serie</span>
            </div>
            <p>El modelo local de LocalHarness: Claude le encarga leer, resumir y escribir archivos sin gastar plan.</p>
            <div class="chips"><span class="pill"><i class="fa-solid fa-wrench" />local_ask</span><span class="pill"><i class="fa-solid fa-wrench" />local_write_file</span></div>
            <div class="chips">
              <span v-for="a in usesMcp('local')" :key="a.id" class="pill"><i class="fa-solid fa-circle" :style="{ color: agentColor(a), fontSize: '7px' }" />{{ a.name }}</span>
            </div>
          </div>
          <div v-for="[n, s] in serverList" :key="n" class="cc" style="--c: #0ea5e9">
            <div class="cc-h">
              <span class="av av--sm" style="background: #0ea5e9"><i class="fa-solid fa-plug" /></span>
              <div><b class="mono">{{ n }}</b><small>{{ s.url ? "remoto" : "local" }}</small></div>
              <span class="badge" :class="s.url ? 'http' : 'stdio'">{{ s.url ? s.type ?? "http" : "stdio" }}</span>
            </div>
            <code :title="cmdOf(s)">{{ cmdOf(s) }}</code>
            <p v-if="s.description">{{ s.description }}</p>
            <div class="chips">
              <span v-for="a in usesMcp(String(n))" :key="a.id" class="pill"><i class="fa-solid fa-circle" :style="{ color: agentColor(a), fontSize: '7px' }" />{{ a.name }}</span>
              <span v-if="!usesMcp(String(n)).length" class="muted small">Ningún agente lo usa: asígnalo en la pestaña Agentes</span>
            </div>
            <div class="cc-act"><span class="spacer" />
              <button class="btn btn--small btn--danger" @click="removeServer(String(n))"><i class="fa-solid fa-trash" /></button>
            </div>
          </div>
        </template>
        <p v-if="(tab === 'agents' && !agents.length && q) || (tab === 'skills' && !skillList.length) || (tab === 'mcp' && !serverList.length && q)" class="none">
          Nada que coincida. Prueba con otra búsqueda o importa algo nuevo.
        </p>
      </div>

      <div v-if="importing" class="imp-wrap" @mousedown.self="importing = false">
        <div class="imp" @dragenter.prevent="drag = true" @dragover.prevent="drag = true" @dragleave.prevent="drag = false" @drop.prevent="onDrop">
          <h3 class="card-title">Importar al catálogo <em>agentes · skills · servidores MCP</em></h3>
          <p class="small muted">
            Pega o suelta archivos: <b>JSON</b> con <code>mcpServers</code> (formato Claude/Cursor), <b>.md</b> con frontmatter — skill
            (<code>SKILL.md</code>) o agente (si trae <code>model</code>, <code>role</code> o <code>tools</code>) — o JSON con <code>agents</code>.
          </p>
          <textarea v-model="text" class="input" :class="{ drag }" spellcheck="false" placeholder="Pega aquí el contenido o suelta archivos…" />
          <div class="det" :class="detected?.err ? 'err' : 'ok'">{{ detected ? (detected.err ?? `Detectado: ${summary(detected)}`) : "" }}</div>
          <div class="row">
            <span class="small muted"><b>Ejemplos:</b></span>
            <button class="btn btn--small" @click="text = EXAMPLES.mcp">Servidores MCP</button>
            <button class="btn btn--small" @click="text = EXAMPLES.skill">Skill</button>
            <button class="btn btn--small" @click="text = EXAMPLES.agent">Agente</button>
          </div>
          <div class="row between">
            <label class="btn"><i class="fa-solid fa-folder-open" /> Elegir archivos<input type="file" multiple accept=".json,.md,.txt" hidden @change="onFiles"></label>
            <div class="row">
              <button class="btn" @click="importing = false">Cancelar</button>
              <button class="btn btn--primary" :disabled="!detected || !!detected.err" @click="doImport">Importar</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: grid;
  place-items: center;
  padding: 26px;
  background: rgba(30, 35, 45, 0.5);
  backdrop-filter: blur(4px);
}
.cat {
  position: relative;
  width: min(1200px, 100%);
  height: min(800px, 100%);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.cat-h {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
  flex-wrap: wrap;
}
.cat-h h2 {
  display: flex;
  gap: 9px;
  align-items: center;
  font-size: 17px;
  margin-right: 8px;
}
.cat-h h2 i {
  color: var(--accent);
}
.cat-tabs {
  display: flex;
  gap: 4px;
  background: var(--panel-raised);
  padding: 3px;
  border-radius: 12px;
}
.cat-tabs button {
  display: flex;
  gap: 7px;
  align-items: center;
  padding: 6px 12px;
  border: 0;
  border-radius: 9px;
  background: none;
  color: var(--ink-dim);
  font-weight: 700;
  cursor: pointer;
}
.cat-tabs button.on {
  background: var(--ink);
  color: var(--panel);
}
.n {
  font-size: 10px;
  background: rgba(134, 139, 150, 0.3);
  padding: 0 6px;
  border-radius: 99px;
}
.search {
  flex: 1;
  min-width: 160px;
  max-width: 300px;
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
.cat-sub {
  padding: 10px 16px;
  color: var(--ink-dim);
  font-size: 12px;
  border-bottom: 1px solid var(--line);
  background: var(--panel-raised);
}
.cat-sub .ok {
  color: var(--ok);
  font-weight: 700;
}
.grid {
  flex: 1;
  overflow: auto;
  padding: 16px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
  gap: 12px;
  align-content: start;
}
.cc {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  padding: 12px;
  background: var(--panel-raised);
  border: 1px solid var(--line);
  border-left: 4px solid var(--c, #868b96);
  border-radius: 14px;
}
.cc--new {
  align-items: flex-start;
  border-style: dashed;
  border-left-style: dashed;
  color: var(--ink-dim);
}
.cc--new > i {
  font-size: 20px;
  color: var(--accent);
}
.cc-h {
  display: flex;
  gap: 10px;
  align-items: center;
}
.cc-h b {
  display: block;
  font-weight: 800;
  font-size: 13.5px;
}
.cc-h small {
  color: var(--ink-dim);
  font-weight: 600;
}
.cc-h > :last-child {
  margin-left: auto;
}
.av {
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  border-radius: 12px;
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 16px;
}
.av--sm {
  width: 34px;
  height: 34px;
  font-size: 14px;
  border-radius: 11px;
}
.cc p {
  margin: 0;
  color: var(--ink-dim);
  font-size: 12px;
  line-height: 1.4;
}
.cc code {
  display: block;
  font-size: 11px;
  background: #262b35;
  color: #d7dae0;
  border-radius: 8px;
  padding: 5px 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.l {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-weight: 700;
  font-size: 12px;
}
.l span {
  color: var(--ink-faint);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  text-align: right;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.cc-act {
  display: flex;
  gap: 6px;
  margin-top: auto;
  padding-top: 4px;
  flex-wrap: wrap;
  align-items: center;
}
.badge {
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 2px 7px;
  border-radius: 99px;
  background: var(--meter);
  color: var(--ink-dim);
}
.badge.imp {
  background: #ddd6fe;
  color: #5b21b6;
}
.badge.team {
  background: #bbf7d0;
  color: #166534;
}
.badge.http {
  background: #bae6fd;
  color: #075985;
}
.badge.stdio {
  background: #e7e5e4;
  color: #44403c;
}
.dotst {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #a3a3a3;
}
.dotst.on {
  background: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.2);
}
.edit {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  max-height: 230px;
  overflow: auto;
  padding-top: 8px;
  border-top: 1px dashed var(--line);
}
.edit.busy {
  opacity: 0.6;
}
.edit h5 {
  margin: 0 0 4px;
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-faint);
}
.edit label {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 2px 0;
  font-family: var(--font-mono);
  font-size: 11px;
  cursor: pointer;
}
.none {
  grid-column: 1 / -1;
  text-align: center;
  color: var(--ink-faint);
  padding: 40px;
}
.imp-wrap {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: grid;
  place-items: center;
  background: rgba(30, 35, 45, 0.45);
}
.imp {
  width: min(660px, 92%);
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  border-radius: 18px;
  background: var(--panel);
  box-shadow: 0 30px 60px -20px rgba(0, 0, 0, 0.5);
}
.imp p {
  margin: 0;
  line-height: 1.5;
}
.imp textarea {
  height: 210px;
  resize: vertical;
  border-style: dashed;
  border-width: 1.5px;
  font-family: var(--font-mono);
  font-size: 11.5px;
}
.imp textarea.drag {
  border-color: var(--accent);
  background: var(--accent-weak);
}
.det {
  min-height: 18px;
  font-size: 12px;
  font-weight: 700;
}
.det.ok {
  color: var(--ok);
}
.det.err {
  color: var(--crit);
}
.between {
  justify-content: space-between;
}
</style>
