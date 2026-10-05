<script setup lang="ts">
import { computed, reactive, ref, watchEffect } from "vue";
import { useRouter } from "vue-router";
import BlueprintCard from "../components/BlueprintCard.vue";
import StatusChip from "../components/StatusChip.vue";
import {
  STATUS_TEXT, agentName, live, post, projectName, statusChip, taskList, usd, type Task,
} from "../api";

const router = useRouter();
const form = reactive({ project_id: 0, agent_id: 0, title: "", prompt: "" });
const error = ref("");
const sending = ref(false);

watchEffect(() => {
  if (!form.project_id && live.projects.length) form.project_id = live.projects[0].id;
  if (!form.agent_id && live.agents.length) form.agent_id = live.agents[0].id;
});

const busy = computed(() => taskList.value.some((t) => t.project_id === form.project_id && t.status === "running"));
const ready = computed(() => live.projects.length > 0 && live.agents.length > 0);

async function launch() {
  error.value = "";
  sending.value = true;
  try {
    const t = await post<Task>("/api/tasks", { ...form, title: form.title || null });
    form.prompt = form.title = "";
    router.push(`/tareas/${t.id}`);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    sending.value = false;
  }
}
</script>

<template>
  <div class="page">
    <h2 class="title">Tareas</h2>

    <BlueprintCard title="Nueva petición">
      <p v-if="!ready" class="muted">
        Primero registra un proyecto y un agente en <RouterLink to="/proyectos">Proyectos y agentes</RouterLink>.
      </p>
      <form v-else class="new" @submit.prevent="launch">
        <div class="row">
          <label class="field">
            <span class="label">Proyecto</span>
            <select v-model.number="form.project_id">
              <option v-for="p in live.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
          </label>
          <label class="field">
            <span class="label">Agente</span>
            <select v-model.number="form.agent_id">
              <option v-for="a in live.agents" :key="a.id" :value="a.id">
                {{ a.name }} ({{ a.provider }}{{ a.model ? "/" + a.model : "" }})
              </option>
            </select>
          </label>
          <label class="field grow">
            <span class="label">Título (opcional)</span><input v-model.trim="form.title" maxlength="80" />
          </label>
        </div>
        <label class="field">
          <span class="label">Petición</span>
          <textarea v-model="form.prompt" rows="5" required placeholder="Qué tiene que hacer el agente…" />
        </label>
        <div class="row">
          <button class="btn btn--primary" :disabled="sending || busy || !form.prompt.trim()">Lanzar en worktree aislado</button>
          <span v-if="busy" class="muted">Ese proyecto ya tiene una tarea en marcha (una por repo a la vez).</span>
          <span class="muted small">El agente trabaja en su rama; nada llega a la tuya sin que lo apruebes.</span>
        </div>
        <p v-if="error" class="error">{{ error }}</p>
      </form>
    </BlueprintCard>

    <BlueprintCard title="Historial">
      <table v-if="taskList.length" class="list">
        <thead><tr><th>#</th><th>Estado</th><th>Título</th><th>Proyecto</th><th>Agente</th><th>Coste equiv.</th></tr></thead>
        <tbody>
          <tr v-for="t in taskList" :key="t.id" class="clickable" @click="router.push(`/tareas/${t.id}`)">
            <td class="mono">{{ t.id }}</td>
            <td><StatusChip label="" :state="statusChip(t.status)" :text="STATUS_TEXT[t.status] ?? t.status" /></td>
            <td>{{ t.title }}</td>
            <td>{{ projectName(t.project_id) }}</td>
            <td>{{ agentName(t.agent_id) }}</td>
            <td class="mono">{{ usd(t.cost_usd) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">Sin tareas todavía.</p>
    </BlueprintCard>
  </div>
</template>

<style scoped>
.new {
  display: grid;
  gap: 12px;
}
.grow {
  flex: 1;
  min-width: 200px;
}
.small {
  font-size: 12px;
}
</style>
