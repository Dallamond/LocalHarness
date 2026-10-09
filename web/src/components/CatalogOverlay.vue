<script setup lang="ts">
// Catálogo: agentes, skills y servidores MCP. Skills instaladas, biblioteca (biblioteca/skills) y búsqueda en repos
// de GitHub, con categorías y vista previa; servidores MCP añadidos y preparados (biblioteca/mcp.json) para añadir
// con un clic. Desde la vista previa se asigna cada cosa a los agentes. Agentes nuevos/editar → AgentWizard.
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import Markdown from "./Markdown.vue";
import {
  PROVIDER_TEXT, ROLE_TEXT, agentColor, api, live, localModelsText, modelText, openWizard, pickPath, post, refreshAll, ui,
  type Agent, type Library, type LibraryMcp, type McpServer, type Settings, type Skill,
} from "../api";

const router = useRouter();
const tab = computed({
  get: () => ui.catalog?.tab ?? "agents",
  set: (t) => { if (ui.catalog) ui.catalog = { ...ui.catalog, tab: t, open: null }; preview.value = null; cat.value = ""; },
});
const open = computed({
  get: () => ui.catalog?.open ?? null,
  set: (v) => { if (ui.catalog) ui.catalog = { ...ui.catalog, open: v }; },
});
const q = ref("");
const error = ref("");
const skills = ref<Skill[]>([]);
const servers = ref<Record<string, McpServer>>({});
const lib = ref<Library>({ skills: [], mcps: [], templates: [] });

async function load() {
  const [sk, st, l] = await Promise.all([
    api<Skill[]>("/api/skills"), api<{ values: Settings }>("/api/settings"), api<Library>("/api/library"),
  ]);
  skills.value = sk;
  servers.value = st.values.mcp_servers ?? {};
  lib.value = l;
  if (gh.value.result) gh.value.result.skills.forEach((s) => (s.installed = sk.some((x) => x.name === s.name)));
}
function close() { ui.catalog = null; }
const onKey = (e: KeyboardEvent) => {
  if (e.key !== "Escape" || ui.wizard) return;
  if (importing.value) importing.value = false;
  else if (preview.value) preview.value = null;
  else close();
};
onMounted(() => { load().catch((e) => (error.value = (e as Error).message)); window.addEventListener("keydown", onKey); });
onUnmounted(() => window.removeEventListener("keydown", onKey));

const hit = (o: unknown) => !q.value || JSON.stringify(o).toLowerCase().includes(q.value.toLowerCase());
const agents = computed(() => live.agents.filter(hit));
const claudeAgents = computed(() => live.agents.filter((a) => a.provider === "claude"));
const usesSkill = (n: string) => live.agents.filter((a) => (a.config.skills ?? []).includes(n));
const usesMcp = (n: string) => live.agents.filter((a) => (n === "local" ? a.config.delegate_local : (a.config.mcps ?? []).includes(n)));
const iconClass = (i: string) => (i.includes("fa-brands") ? i : `fa-solid ${i}`);

const SUB = {
  agents: "Tus agentes. Créalos o edítalos con el asistente (plantillas por rol, Claude o modelo local, skills y servidores MCP). «Asignar» cambia skills y herramientas al momento.",
  skills: "Procedimientos (SKILL.md) que se añaden al prompt del agente. Instala de la biblioteca, busca en repos de GitHub o pega uno con Importar. Las instaladas viven en data/skills (fuera de git).",
  mcp: "Servidores MCP que dan herramientas a los agentes Claude. Se arrancan con cada tarea del agente que los tenga asignados. Añade los preparados con un clic.",
};

// ---------- vistas de skills y MCP, categorías
const skillView = ref<"installed" | "library" | "github">("library");
const mcpView = ref<"added" | "library">("library");
const cat = ref("");
interface SkillCard { name: string; description: string; category: string; chars: number; installed: boolean; imported?: boolean; source?: string | null; content?: string; url?: string; from: "installed" | "library" | "github" }
const skillPool = computed<SkillCard[]>(() => {
  if (skillView.value === "installed")
    return skills.value.map((s) => ({ ...s, category: s.category ?? "Otras", installed: true, from: "installed" as const }));
  if (skillView.value === "library") return lib.value.skills.map((s) => ({ ...s, from: "library" as const }));
  return (gh.value.result?.skills ?? []).map((s) => ({ ...s, from: "github" as const }));
});
const mcpPool = computed(() => (mcpView.value === "library" ? lib.value.mcps : []));
const cats = computed(() => {
  const list = tab.value === "skills" ? skillPool.value.map((s) => s.category) : tab.value === "mcp" && mcpView.value === "library" ? mcpPool.value.map((m) => m.category) : [];
  const n: Record<string, number> = {};
  list.forEach((c) => (n[c] = (n[c] ?? 0) + 1));
  return Object.entries(n).sort((a, b) => a[0].localeCompare(b[0]));
});
const skillList = computed(() => skillPool.value.filter((s) => (!cat.value || s.category === cat.value) && hit(s)));
const libMcpList = computed(() => mcpPool.value.filter((m) => (!cat.value || m.category === cat.value) && hit(m)));
const serverList = computed(() => Object.entries(servers.value).filter(([n, s]) => hit({ n, s })));
function setView(v: string) {
  if (tab.value === "skills") skillView.value = v as typeof skillView.value;
  else mcpView.value = v as typeof mcpView.value;
  cat.value = "";
  preview.value = null;
}

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
    preview.value = null;
    await load();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
const cmdOf = (s: McpServer) => s.url ?? [s.command, ...(s.args ?? [])].filter(Boolean).join(" ");
/** Configuración para enseñar, con claves y tokens tapados. */
function masked(s: McpServer & { headers?: Record<string, string> }): string {
  const hide = (o?: Record<string, string>) => o && Object.fromEntries(Object.keys(o).map((k) => [k, "••••••"]));
  return JSON.stringify({ ...s, env: hide(s.env), headers: hide(s.headers), description: undefined }, null, 2);
}

// ---------- vista previa (panel derecho)
type Preview = { kind: "skill"; card: SkillCard; content: string } | { kind: "lib-mcp"; entry: LibraryMcp } | { kind: "mcp"; name: string };
const preview = ref<Preview | null>(null);
const pvBusy = ref(false);
const body = (md: string) => md.replace(/^﻿?---\r?\n[\s\S]*?\r?\n---\r?\n?/, "");
async function showSkill(c: SkillCard) {
  preview.value = { kind: "skill", card: c, content: c.content ?? "" };
  if (!c.content) {
    try {
      const d = await api<Skill & { content: string }>(`/api/skills/${encodeURIComponent(c.name)}`);
      if (preview.value?.kind === "skill" && preview.value.card.name === c.name) preview.value.content = d.content;
    } catch (e) {
      error.value = (e as Error).message;
    }
  }
}
const params = ref<Record<string, string>>({});
const mcpName = ref("");
function showLibMcp(m: LibraryMcp) {
  preview.value = { kind: "lib-mcp", entry: m };
  params.value = {};
  mcpName.value = servers.value[m.id] ? `${m.id}-2` : m.id;
}
const installedSkill = (n: string) => skills.value.some((s) => s.name === n);
const importedSkill = (n: string) => !!skills.value.find((s) => s.name === n)?.imported;
async function installSkill(c: SkillCard): Promise<boolean> {
  if (installedSkill(c.name)) return true;
  pvBusy.value = true;
  error.value = "";
  try {
    if (c.from === "library") await post(`/api/library/skills/${encodeURIComponent(c.name)}`);
    else await post("/api/skills", { content: c.content, source: c.url ?? gh.value.result?.source, category: c.category });
    await load();
    result.value = `Skill ${c.name} instalada`;
    if (preview.value?.kind === "skill") preview.value.card = { ...preview.value.card, installed: true, imported: true };
    return true;
  } catch (e) {
    error.value = (e as Error).message;
    return false;
  } finally {
    pvBusy.value = false;
  }
}
async function removeSkill(name: string) {
  if (!window.confirm(`¿Borrar la skill ${name}? Se quitará también de los agentes que la tengan.`)) return;
  try {
    await api(`/api/skills/${encodeURIComponent(name)}`, { method: "DELETE" });
    for (const a of usesSkill(name)) await patch(a, { skills: toggle(a.config.skills, name, false) });
    await load();
    preview.value = null;
  } catch (e) {
    error.value = (e as Error).message;
  }
}
async function assignSkill(c: SkillCard, a: Agent, on: boolean) {
  if (on && !(await installSkill(c))) return;
  await patch(a, { skills: toggle(a.config.skills, c.name, on) });
}
const pendingAssign = ref<number[]>([]);
async function addLibMcp(m: LibraryMcp) {
  pvBusy.value = true;
  error.value = "";
  try {
    const r = await post<{ name: string }>(`/api/library/mcp/${m.id}`, { name: mcpName.value.trim() || m.id, params: params.value });
    for (const id of pendingAssign.value) {
      const a = live.agents.find((x) => x.id === id);
      if (a) await patch(a, { mcps: toggle(a.config.mcps, r.name, true) });
    }
    pendingAssign.value = [];
    await load();
    result.value = `Servidor ${r.name} añadido`;
    preview.value = { kind: "mcp", name: r.name };
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    pvBusy.value = false;
  }
}
async function quickAddMcp(m: LibraryMcp) {
  if (m.params?.length) return showLibMcp(m);
  mcpName.value = m.id;
  params.value = {};
  pendingAssign.value = [];
  await addLibMcp(m);
}
async function pick(key: string, kind: "folder" | "file") {
  try {
    const p = await pickPath(kind);
    if (p) params.value[key] = p;
  } catch (e) {
    error.value = (e as Error).message;
  }
}
const libFor = (name: string) => lib.value.mcps.find((m) => m.added_as.includes(name));

// ---------- skills de GitHub
const SUGGESTED = [
  { url: "anthropics/skills", text: "anthropics/skills", hint: "oficiales de Anthropic: documentos, diseño, pruebas web, MCP…" },
  { url: "https://github.com/anthropics/skills/tree/main/skills/webapp-testing", text: "webapp-testing", hint: "probar webs con Playwright" },
  { url: "https://github.com/anthropics/skills/tree/main/skills/mcp-builder", text: "mcp-builder", hint: "crear servidores MCP" },
];
const gh = ref<{ url: string; loading: boolean; error: string; result: { source: string; ref: string; skills: (SkillCard & { content: string })[] } | null }>(
  { url: "", loading: false, error: "", result: null });
async function searchGithub(url = gh.value.url) {
  if (!url.trim()) return;
  gh.value = { ...gh.value, url, loading: true, error: "" };
  try {
    gh.value.result = await post("/api/library/github", { url });
    cat.value = "";
  } catch (e) {
    gh.value.error = (e as Error).message;
  } finally {
    gh.value.loading = false;
  }
}
async function installAllGithub() {
  for (const s of skillList.value.filter((x) => !x.installed)) await installSkill(s);
}

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
  skillView.value = "installed";
  mcpView.value = "added";
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
        <button v-if="tab === 'agents'" class="btn btn--primary" @click="openWizard()"><i class="fa-solid fa-wand-magic-sparkles" /> Nuevo agente</button>
        <button class="btn" @click="importing = true; result = ''"><i class="fa-solid fa-file-import" /> Importar</button>
        <button class="icon-btn" title="Cerrar (Esc)" @click="close"><i class="fa-solid fa-xmark" /></button>
      </div>
      <div class="cat-sub">
        {{ SUB[tab] }}
        <span v-if="error" class="error"> · {{ error }}</span>
        <span v-if="result" class="ok"> · {{ result }}</span>
      </div>
      <div v-if="tab !== 'agents'" class="views">
        <div class="seg">
          <template v-if="tab === 'skills'">
            <button :class="{ on: skillView === 'library' }" @click="setView('library')"><i class="fa-solid fa-book" />Biblioteca<span class="n">{{ lib.skills.length }}</span></button>
            <button :class="{ on: skillView === 'installed' }" @click="setView('installed')"><i class="fa-solid fa-check" />Instaladas<span class="n">{{ skills.length }}</span></button>
            <button :class="{ on: skillView === 'github' }" @click="setView('github')"><i class="fa-brands fa-github" />Desde GitHub</button>
          </template>
          <template v-else>
            <button :class="{ on: mcpView === 'library' }" @click="setView('library')"><i class="fa-solid fa-book" />Preparados<span class="n">{{ lib.mcps.length }}</span></button>
            <button :class="{ on: mcpView === 'added' }" @click="setView('added')"><i class="fa-solid fa-check" />Añadidos<span class="n">{{ Object.keys(servers).length + 1 }}</span></button>
          </template>
        </div>
        <div v-if="cats.length > 1" class="cats">
          <button :class="{ on: !cat }" @click="cat = ''">Todas</button>
          <button v-for="[c, n] in cats" :key="c" :class="{ on: cat === c }" @click="cat = cat === c ? '' : c">{{ c }} <small>{{ n }}</small></button>
        </div>
      </div>
      <div v-if="tab === 'skills' && skillView === 'github'" class="ghbar">
        <form class="row" @submit.prevent="searchGithub()">
          <i class="fa-brands fa-github" />
          <input v-model="gh.url" class="input" placeholder="usuario/repo o https://github.com/usuario/repo/tree/main/carpeta (o un SKILL.md)">
          <button class="btn btn--primary" :disabled="gh.loading || !gh.url.trim()">{{ gh.loading ? "Buscando…" : "Buscar skills" }}</button>
        </form>
        <div class="row sugg">
          <span class="small muted">Prueba:</span>
          <button v-for="s in SUGGESTED" :key="s.url" class="btn btn--small" :title="s.hint" @click="searchGithub(s.url)">{{ s.text }}</button>
          <span v-if="gh.result" class="small muted">· {{ gh.result.skills.length }} en {{ gh.result.source }} ({{ gh.result.ref }})</span>
          <button v-if="gh.result && skillList.some((s) => !s.installed)" class="btn btn--small" :disabled="pvBusy" @click="installAllGithub">Instalar todas ({{ skillList.filter((s) => !s.installed).length }})</button>
        </div>
        <p v-if="gh.error" class="error small">{{ gh.error }}</p>
        <p class="small muted">Solo se importa el SKILL.md (el texto que lee el agente); si la skill trae scripts al lado, no se usan.</p>
      </div>

      <div class="body">
        <div class="grid">
          <!-- agentes -->
          <template v-if="tab === 'agents'">
            <div v-for="a in agents" :key="a.id" class="cc" :style="{ '--c': agentColor(a) }">
              <div class="cc-h">
                <span class="av" :style="{ background: agentColor(a) }"><i class="fa-solid fa-user-astronaut" /></span>
                <div><b>{{ a.name }}</b><small>{{ ROLE_TEXT[a.role ?? ""] ?? a.role ?? "sin rol" }}<template v-if="a.config.off"> · fuera de servicio</template></small></div>
                <span class="prov" :class="`prov--${a.provider}`">{{ PROVIDER_TEXT[a.provider] ?? a.provider }}</span>
              </div>
              <p>{{ a.config.description || "Sin descripción (el Director la lee para repartir trabajo)." }}</p>
              <div class="l">Modelo <span>{{ modelText(a) }}</span></div>
              <div class="chips">
                <span v-for="s in a.config.skills ?? []" :key="s" class="pill"><i class="fa-solid fa-bolt" />{{ s }}</span>
                <span v-if="a.config.delegate_local || a.config.coordinator" class="pill pill--ok"><i class="fa-solid" :class="a.config.coordinator ? 'fa-user-tie' : 'fa-plug'" />{{ a.config.coordinator ? "jefe del local" : "local" }}</span>
                <span v-for="m in a.config.mcps ?? []" :key="m" class="pill pill--active"><i class="fa-solid fa-plug" />{{ m }}</span>
                <span v-if="a.config.web" class="pill pill--active"><i class="fa-solid fa-globe" />internet</span>
                <span v-if="!(a.config.skills ?? []).length && !a.config.delegate_local && !(a.config.mcps ?? []).length && !a.config.web" class="muted small">Sin skills ni herramientas extra</span>
              </div>
              <div class="cc-act">
                <span class="spacer" />
                <button class="btn btn--small" @click="inOffice(a)"><i class="fa-solid fa-location-crosshairs" /> En la oficina</button>
                <button class="btn btn--small" @click="open = open === a.id ? null : a.id"><i class="fa-solid fa-sliders" /> {{ open === a.id ? "Cerrar" : "Asignar" }}</button>
                <button class="btn btn--small btn--primary" @click="openWizard(a.id)"><i class="fa-solid fa-pen" /> Editar</button>
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
                    <label v-if="a.config.delegate_local && !a.config.read_only" title="Jefe: Claude no escribe; encarga cada cambio al modelo local y lo revisa">
                      <input type="checkbox" :checked="a.config.coordinator" @change="patch(a, { coordinator: ($event.target as HTMLInputElement).checked })">jefe del local
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
                    <p v-if="!Object.keys(servers).length" class="muted small">Añade servidores en la pestaña Servidores MCP.</p>
                  </template>
                  <template v-else-if="a.provider === 'local_agent'">
                    <label title="buscar_web y leer_url (gratis)">
                      <input type="checkbox" :checked="a.config.web !== false" @change="patch(a, { web: ($event.target as HTMLInputElement).checked })">internet
                    </label>
                    <p class="muted small">Tiene sus herramientas propias (leer, buscar, escribir, ejecutar). Los MCP son solo para Claude.</p>
                  </template>
                  <p v-else class="muted small">«Solo responde»: sin herramientas. Cámbialo a «con herramientas» con Editar.</p>
                </div>
              </div>
            </div>
            <div class="cc cc--new">
              <i class="fa-solid fa-wand-magic-sparkles" />
              <b>Nuevo agente</b>
              <p>Elige un rol y en un minuto lo tienes en la oficina, con su cerebro (Claude o tu modelo local recomendado), skills y servidores MCP.</p>
              <div class="chips">
                <button v-for="t in lib.templates.filter((x) => x.id !== 'en-blanco')" :key="t.id" class="btn btn--small" :title="t.summary" @click="openWizard(undefined, t.id)">
                  <i class="fa-solid" :class="t.icon" /> {{ t.name }}
                </button>
                <button class="btn btn--small btn--primary" @click="openWizard(undefined, 'en-blanco')">En blanco</button>
              </div>
            </div>
          </template>

          <!-- skills -->
          <template v-else-if="tab === 'skills'">
            <div
              v-for="s in skillList" :key="s.from + s.name" class="cc cc--click" :class="{ sel: preview?.kind === 'skill' && preview.card.name === s.name }"
              style="--c: #6366f1" @click="showSkill(s)"
            >
              <div class="cc-h">
                <span class="av av--sm" style="background: #6366f1"><i class="fa-solid fa-bolt" /></span>
                <div><b class="mono">{{ s.name }}</b><small>{{ s.category }} · {{ Math.round(s.chars / 100) / 10 }}k car.</small></div>
                <span v-if="s.from === 'installed'" class="badge" :class="{ imp: s.imported }">{{ s.imported ? "instalada" : "de serie" }}</span>
                <span v-else-if="s.installed" class="badge team">instalada</span>
                <button v-else class="btn btn--small btn--primary" :disabled="pvBusy" @click.stop="installSkill(s)"><i class="fa-solid fa-download" /> Instalar</button>
              </div>
              <p class="clamp">{{ s.description || "Sin descripción." }}</p>
              <div class="chips">
                <span v-for="a in usesSkill(s.name)" :key="a.id" class="pill"><i class="fa-solid fa-circle" :style="{ color: agentColor(a), fontSize: '7px' }" />{{ a.name }}</span>
                <span v-if="s.installed && !usesSkill(s.name).length" class="muted small">Sin asignar: ábrela para dársela a un agente</span>
              </div>
            </div>
          </template>

          <!-- servidores MCP: preparados -->
          <template v-else-if="mcpView === 'library'">
            <div
              v-for="m in libMcpList" :key="m.id" class="cc cc--click" :class="{ sel: preview?.kind === 'lib-mcp' && preview.entry.id === m.id }"
              style="--c: #0ea5e9" @click="m.added_as.length ? (preview = { kind: 'mcp', name: m.added_as[0] }) : showLibMcp(m)"
            >
              <div class="cc-h">
                <span class="av av--sm" style="background: #0ea5e9"><i :class="iconClass(m.icon)" /></span>
                <div><b>{{ m.name }}</b><small>{{ m.category }} · {{ m.config.url ? "remoto" : m.needs }}</small></div>
                <span v-if="m.added_as.length" class="badge team">añadido</span>
                <button v-else class="btn btn--small btn--primary" :disabled="pvBusy" @click.stop="quickAddMcp(m)">
                  <i class="fa-solid" :class="m.params?.length ? 'fa-key' : 'fa-plus'" /> {{ m.params?.length ? "Configurar" : "Añadir" }}
                </button>
              </div>
              <p class="clamp">{{ m.description }}</p>
              <div class="chips">
                <span v-for="t in m.tools.slice(0, 4)" :key="t" class="pill"><i class="fa-solid fa-wrench" />{{ t }}</span>
                <span v-if="!m.available" class="pill pill--warn" :title="`Instala ${m.needs === 'npx' ? 'Node.js' : 'uv'} en el PC`"><i class="fa-solid fa-triangle-exclamation" />falta {{ m.needs }}</span>
              </div>
            </div>
          </template>

          <!-- servidores MCP: añadidos -->
          <template v-else>
            <div v-if="hit('local modelo')" class="cc" style="--c: #16a34a">
              <div class="cc-h">
                <span class="av av--sm" :style="{ background: live.local.state === 'ready' ? '#16a34a' : '#8a8f99' }"><i class="fa-solid fa-plug" /></span>
                <div><b class="mono">local</b><small><span class="dotst" :class="{ on: live.local.state === 'ready' || live.locals.some((l) => l.state === 'ready') }" /> {{ localModelsText("sin modelo arrancado") }}</small></div>
                <span class="badge team">de serie</span>
              </div>
              <p>El modelo local de LocalHarness: Claude le encarga leer, resumir, escribir archivos, tareas enteras (local_agent), pasar los tests e investigar, sin gastar plan.</p>
              <div class="chips"><span class="pill"><i class="fa-solid fa-wrench" />local_ask</span><span class="pill"><i class="fa-solid fa-wrench" />local_write_file</span><span class="pill"><i class="fa-solid fa-wrench" />local_research</span><span class="pill"><i class="fa-solid fa-wrench" />local_agent</span><span class="pill"><i class="fa-solid fa-wrench" />run_checks</span></div>
              <div class="chips">
                <span v-for="a in usesMcp('local')" :key="a.id" class="pill"><i class="fa-solid fa-circle" :style="{ color: agentColor(a), fontSize: '7px' }" />{{ a.name }}</span>
              </div>
            </div>
            <div
              v-for="[n, s] in serverList" :key="n" class="cc cc--click" :class="{ sel: preview?.kind === 'mcp' && preview.name === n }"
              style="--c: #0ea5e9" @click="preview = { kind: 'mcp', name: String(n) }"
            >
              <div class="cc-h">
                <span class="av av--sm" style="background: #0ea5e9"><i :class="iconClass(libFor(String(n))?.icon ?? 'fa-plug')" /></span>
                <div><b class="mono">{{ n }}</b><small>{{ s.url ? "remoto" : "en tu PC" }}</small></div>
                <span class="badge" :class="s.url ? 'http' : 'stdio'">{{ s.url ? s.type ?? "http" : "stdio" }}</span>
              </div>
              <code :title="cmdOf(s)">{{ cmdOf(s) }}</code>
              <p v-if="s.description" class="clamp">{{ s.description }}</p>
              <div class="chips">
                <span v-for="a in usesMcp(String(n))" :key="a.id" class="pill"><i class="fa-solid fa-circle" :style="{ color: agentColor(a), fontSize: '7px' }" />{{ a.name }}</span>
                <span v-if="!usesMcp(String(n)).length" class="muted small">Ningún agente lo usa: ábrelo para asignarlo</span>
              </div>
            </div>
          </template>
          <p
            v-if="(tab === 'agents' && !agents.length && q) || (tab === 'skills' && !skillList.length) || (tab === 'mcp' && mcpView === 'library' && !libMcpList.length) || (tab === 'mcp' && mcpView === 'added' && !serverList.length && q)"
            class="none"
          >
            {{ tab === 'skills' && skillView === 'github' && !gh.result ? "Escribe un repo de GitHub arriba para ver sus skills." : "Nada que coincida. Prueba con otra búsqueda o categoría." }}
          </p>
        </div>

        <!-- vista previa -->
        <aside v-if="preview" class="pv">
          <button class="icon-btn pv-x" title="Cerrar" @click="preview = null"><i class="fa-solid fa-xmark" /></button>
          <template v-if="preview.kind === 'skill'">
            <h3 class="mono">{{ preview.card.name }}</h3>
            <p class="small muted">{{ preview.card.category }}<template v-if="preview.card.source || preview.card.url"> · <a :href="preview.card.url ?? preview.card.source ?? '#'" target="_blank" rel="noopener">origen</a></template></p>
            <p>{{ preview.card.description }}</p>
            <div class="row">
              <button v-if="!installedSkill(preview.card.name)" class="btn btn--primary btn--small" :disabled="pvBusy" @click="installSkill(preview.card)"><i class="fa-solid fa-download" /> Instalar</button>
              <span v-else class="pill pill--ok"><i class="fa-solid fa-check" />instalada</span>
              <button v-if="importedSkill(preview.card.name)" class="btn btn--small btn--danger" @click="removeSkill(preview.card.name)"><i class="fa-solid fa-trash" /> Borrar</button>
            </div>
            <h5>Asignar a agentes <small class="muted">(se guarda al momento{{ installedSkill(preview.card.name) ? "" : "; se instala antes" }})</small></h5>
            <div class="assign">
              <label v-for="a in live.agents" :key="a.id" :class="{ busy: saving === a.id }">
                <input type="checkbox" :checked="(a.config.skills ?? []).includes(preview.card.name)" @change="assignSkill(preview.card, a, ($event.target as HTMLInputElement).checked)">
                <span class="dot" :style="{ background: agentColor(a) }" />{{ a.name }}
              </label>
              <p v-if="!live.agents.length" class="muted small">No hay agentes.</p>
            </div>
            <h5>Vista previa</h5>
            <div class="md-box"><Markdown v-if="preview.content" :text="body(preview.content)" /><span v-else class="muted">Cargando…</span></div>
          </template>

          <template v-else-if="preview.kind === 'lib-mcp'">
            <h3><i :class="iconClass(preview.entry.icon)" /> {{ preview.entry.name }}</h3>
            <p class="small muted">{{ preview.entry.category }} · <a v-if="preview.entry.homepage" :href="preview.entry.homepage" target="_blank" rel="noopener">web del proyecto</a></p>
            <p>{{ preview.entry.description }}</p>
            <div class="chips"><span v-for="t in preview.entry.tools" :key="t" class="pill"><i class="fa-solid fa-wrench" />{{ t }}</span></div>
            <p v-if="preview.entry.needs" class="small" :class="preview.entry.available ? 'ok' : 'error'">
              <i class="fa-solid" :class="preview.entry.available ? 'fa-check' : 'fa-triangle-exclamation'" />
              {{ preview.entry.available ? `${preview.entry.needs} está instalado en este PC` : `Necesita ${preview.entry.needs === "npx" ? "Node.js (npx)" : "uv (uvx): winget install astral-sh.uv"} en este PC` }}
            </p>
            <form class="pform" @submit.prevent="addLibMcp(preview.entry)">
              <label class="field"><span class="label">Nombre</span><input v-model.trim="mcpName" class="input mono"></label>
              <label v-for="p in preview.entry.params ?? []" :key="p.key" class="field">
                <span class="label">{{ p.label }}</span>
                <span class="row">
                  <input v-model="params[p.key]" class="input mono" :type="p.secret ? 'password' : 'text'" :placeholder="p.placeholder" autocomplete="off">
                  <button v-if="p.folder || p.file" type="button" class="btn btn--small" @click="pick(p.key, p.folder ? 'folder' : 'file')"><i class="fa-solid fa-folder-open" /></button>
                </span>
              </label>
              <p v-if="preview.entry.params?.some((p) => p.secret)" class="small muted">La clave se guarda en tu base de datos local (data/) y solo se pasa a este servidor.</p>
              <h5>Dárselo a <small class="muted">(agentes Claude)</small></h5>
              <div class="assign">
                <label v-for="a in claudeAgents" :key="a.id">
                  <input v-model="pendingAssign" type="checkbox" :value="a.id"><span class="dot" :style="{ background: agentColor(a) }" />{{ a.name }}
                </label>
                <p v-if="!claudeAgents.length" class="muted small">No hay agentes Claude.</p>
              </div>
              <button class="btn btn--primary" :disabled="pvBusy"><i class="fa-solid fa-plus" /> Añadir servidor</button>
            </form>
            <h5>Configuración</h5>
            <pre class="cfg">{{ masked(preview.entry.config) }}</pre>
          </template>

          <template v-else-if="servers[preview.name]">
            <h3 class="mono"><i :class="iconClass(libFor(preview.name)?.icon ?? 'fa-plug')" /> {{ preview.name }}</h3>
            <p>{{ servers[preview.name].description || libFor(preview.name)?.description || "Servidor MCP importado." }}</p>
            <h5>Agentes que lo usan <small class="muted">(se guarda al momento)</small></h5>
            <div class="assign">
              <label v-for="a in claudeAgents" :key="a.id" :class="{ busy: saving === a.id }">
                <input type="checkbox" :checked="(a.config.mcps ?? []).includes(preview.name)" @change="patch(a, { mcps: toggle(a.config.mcps, (preview as { name: string }).name, ($event.target as HTMLInputElement).checked) })">
                <span class="dot" :style="{ background: agentColor(a) }" />{{ a.name }}
              </label>
              <p v-if="!claudeAgents.length" class="muted small">No hay agentes Claude: los MCP son solo para ellos.</p>
            </div>
            <h5>Configuración</h5>
            <pre class="cfg">{{ masked(servers[preview.name]) }}</pre>
            <div class="row"><span class="spacer" /><button class="btn btn--small btn--danger" @click="removeServer(preview.name)"><i class="fa-solid fa-trash" /> Quitar</button></div>
          </template>
        </aside>
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
  border-radius: var(--radius-sm);
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
  border-radius: var(--radius-sm);
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
  border-radius: var(--radius);
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
  border-radius: var(--radius-sm);
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 16px;
}
.av--sm {
  width: 34px;
  height: 34px;
  font-size: 14px;
  border-radius: var(--radius-sm);
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
  border-radius: var(--radius);
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
.views {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  padding: 10px 16px 0;
}
.seg {
  display: flex;
  gap: 4px;
  background: var(--panel-raised);
  padding: 3px;
  border-radius: var(--radius-sm);
}
.seg button,
.cats button {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 5px 10px;
  border: 0;
  border-radius: 8px;
  background: none;
  color: var(--ink-dim);
  font-weight: 700;
  font-size: 12px;
  cursor: pointer;
}
.seg button.on {
  background: var(--panel);
  color: var(--ink);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
}
.cats {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.cats button {
  border: 1px solid var(--line);
  border-radius: 99px;
  padding: 3px 10px;
}
.cats button small {
  opacity: 0.6;
}
.cats button.on {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.ghbar {
  padding: 10px 16px 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ghbar form {
  gap: 8px;
}
.ghbar form .input {
  flex: 1;
}
.ghbar p {
  margin: 0;
}
.sugg {
  gap: 6px;
  flex-wrap: wrap;
}
.body {
  flex: 1;
  min-height: 0;
  display: flex;
}
.body .grid {
  flex: 1;
  min-width: 0;
}
.cc--click {
  cursor: pointer;
  transition: box-shadow 0.15s;
}
.cc--click:hover {
  box-shadow: 0 4px 14px -6px rgba(0, 0, 0, 0.25);
}
.cc.sel {
  outline: 2px solid var(--c);
}
.clamp {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.pill--warn {
  background: #fef3c7;
  color: #92400e;
}
.pv {
  position: relative;
  width: 420px;
  flex-shrink: 0;
  overflow: auto;
  padding: 16px;
  border-left: 1px solid var(--line);
  background: var(--panel);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pv-x {
  position: absolute;
  top: 10px;
  right: 10px;
}
.pv h3 {
  margin: 0;
  padding-right: 40px;
  font-size: 16px;
  display: flex;
  gap: 8px;
  align-items: center;
}
.pv p {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.45;
}
.pv h5 {
  margin: 8px 0 0;
  font-size: 10.5px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-faint);
}
.pv h5 small {
  text-transform: none;
  letter-spacing: 0;
}
.pv .ok {
  color: var(--ok);
}
.assign {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
}
.assign label {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 12px;
  cursor: pointer;
}
.assign label.busy {
  opacity: 0.5;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.md-box {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--panel-raised);
  border: 1px solid var(--line);
  font-size: 12.5px;
}
.cfg {
  margin: 0;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: #262b35;
  color: #d7dae0;
  font-size: 11px;
  overflow: auto;
}
.pform {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pform .field {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.pform .label {
  font-size: 12px;
  font-weight: 700;
}
.pform .row .input {
  flex: 1;
}
.pform > .btn {
  align-self: flex-start;
  margin-top: 4px;
}
@media (max-width: 900px) {
  .body {
    flex-direction: column;
    overflow: auto;
  }
  .body .grid {
    overflow: visible;
  }
  .pv {
    width: auto;
    border-left: 0;
    border-top: 1px solid var(--line);
    overflow: visible;
  }
}
</style>
