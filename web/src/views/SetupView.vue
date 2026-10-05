<script setup lang="ts">
import { reactive, ref } from "vue";
import BlueprintCard from "../components/BlueprintCard.vue";
import { live, post, refreshAll, type Agent, type Project } from "../api";

const proj = reactive({ name: "", repo_path: "" });
const projError = ref("");

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

// Sonnet por defecto: gasta bastante menos plan que Opus para tareas de trabajador
const ag = reactive({
  name: "",
  provider: "claude",
  model: "sonnet",
  role: "trabajador",
  max_turns: 10 as number | null,
  max_budget_usd: 1 as number | null,
  read_only: false,
});
const agError = ref("");

async function addAgent() {
  agError.value = "";
  try {
    await post<Agent>("/api/agents", { ...ag, model: ag.model || null, role: ag.role || null });
    ag.name = "";
    await refreshAll();
  } catch (e) {
    agError.value = (e as Error).message;
  }
}

function limits(a: Agent): string {
  const c = a.config;
  return [
    c.max_turns ? `${c.max_turns} turnos` : null,
    c.max_budget_usd ? `≤ ${c.max_budget_usd} $` : null,
    c.read_only ? "solo lectura" : null,
    c.tools ? c.tools.join(",") : null,
  ]
    .filter(Boolean)
    .join(" · ") || "—";
}
</script>

<template>
  <div class="page">
    <h2 class="title">Proyectos y agentes</h2>

    <BlueprintCard title="Proyectos">
      <table v-if="live.projects.length" class="list">
        <thead><tr><th>#</th><th>Nombre</th><th>Repo</th></tr></thead>
        <tbody>
          <tr v-for="p in live.projects" :key="p.id">
            <td class="mono">{{ p.id }}</td>
            <td>{{ p.name }}</td>
            <td class="mono muted">{{ p.repo_path }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">Aún no hay proyectos. Registra un repo git con al menos un commit.</p>
      <form class="form" @submit.prevent="addProject">
        <label class="field"><span class="label">Nombre</span><input v-model.trim="proj.name" required /></label>
        <label class="field grow">
          <span class="label">Ruta del repo</span>
          <input v-model.trim="proj.repo_path" required placeholder="D:\ruta\al\repo" class="mono" />
        </label>
        <button class="btn btn--primary">Añadir proyecto</button>
      </form>
      <p v-if="projError" class="error">{{ projError }}</p>
    </BlueprintCard>

    <BlueprintCard title="Agentes">
      <table v-if="live.agents.length" class="list">
        <thead><tr><th>#</th><th>Nombre</th><th>Proveedor</th><th>Modelo</th><th>Rol</th><th>Límites</th></tr></thead>
        <tbody>
          <tr v-for="a in live.agents" :key="a.id">
            <td class="mono">{{ a.id }}</td>
            <td>{{ a.name }}</td>
            <td class="mono">{{ a.provider }}</td>
            <td class="mono">{{ a.model ?? "por defecto" }}</td>
            <td>{{ a.role ?? "—" }}</td>
            <td class="mono muted">{{ limits(a) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">Un agente es una configuración: proveedor, modelo, rol y límites.</p>
      <form class="form" @submit.prevent="addAgent">
        <label class="field"><span class="label">Nombre</span><input v-model.trim="ag.name" required /></label>
        <label class="field">
          <span class="label">Proveedor</span>
          <select v-model="ag.provider"><option>claude</option><option>codex</option></select>
        </label>
        <label class="field"><span class="label">Modelo</span><input v-model.trim="ag.model" class="mono" size="10" /></label>
        <label class="field"><span class="label">Rol</span><input v-model.trim="ag.role" size="10" /></label>
        <label class="field">
          <span class="label">Turnos máx.</span><input v-model.number="ag.max_turns" type="number" min="1" style="width: 80px" />
        </label>
        <label class="field">
          <span class="label">Tope $</span>
          <input v-model.number="ag.max_budget_usd" type="number" min="0.01" step="0.01" style="width: 80px" />
        </label>
        <label class="row check"><input v-model="ag.read_only" type="checkbox" /> solo lectura</label>
        <button class="btn btn--primary">Añadir agente</button>
      </form>
      <p v-if="agError" class="error">{{ agError }}</p>
    </BlueprintCard>
  </div>
</template>

<style scoped>
.form {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: flex-end;
  margin-top: 14px;
}
.grow {
  flex: 1;
  min-width: 240px;
}
.check {
  font-size: 13px;
  padding-bottom: 6px;
}
</style>
