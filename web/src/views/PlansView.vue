<script setup lang="ts">
import { computed, reactive, ref, watchEffect } from "vue";
import { useRouter } from "vue-router";
import Card from "../components/Card.vue";
import StatusChip from "../components/StatusChip.vue";
import { PLAN_TEXT, live, planChip, planList, post, projectName, usd, type Plan } from "../api";

const router = useRouter();
const form = reactive({ project_id: 0, director_agent_id: 0, reviewer_agent_id: 0, request: "" });
const error = ref("");
const sending = ref(false);

watchEffect(() => {
  if (!form.project_id && live.projects.length) form.project_id = live.projects[0].id;
  if (!form.director_agent_id && live.agents.length) {
    form.director_agent_id = (live.agents.find((a) => a.role === "director") ?? live.agents[0]).id;
  }
  if (!form.reviewer_agent_id && live.agents.length) {
    form.reviewer_agent_id = live.agents.find((a) => a.role === "jefe")?.id ?? 0;
  }
});

const busy = computed(() =>
  planList.value.some((p) => p.project_id === form.project_id && ["planning", "running"].includes(p.status)),
);

async function launch() {
  error.value = "";
  sending.value = true;
  try {
    const p = await post<Plan>("/api/plans", { ...form, reviewer_agent_id: form.reviewer_agent_id || null });
    form.request = "";
    router.push(`/planes/${p.id}`);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    sending.value = false;
  }
}
</script>

<template>
  <div class="page">
    <h2 class="title">Planes</h2>
    <Card title="Nueva petición al Director">
      <p v-if="!live.projects.length || !live.agents.length" class="muted">
        Primero registra un proyecto y agentes en <RouterLink to="/ajustes">Ajustes</RouterLink>.
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
            <span class="label">Director</span>
            <select v-model.number="form.director_agent_id">
              <option v-for="a in live.agents" :key="a.id" :value="a.id">{{ a.name }} ({{ a.provider }})</option>
            </select>
          </label>
          <label class="field">
            <span class="label">Jefe técnico</span>
            <select v-model.number="form.reviewer_agent_id">
              <option :value="0">ninguno (N1 te llega a ti)</option>
              <option v-for="a in live.agents" :key="a.id" :value="a.id">{{ a.name }} ({{ a.provider }})</option>
            </select>
          </label>
        </div>
        <label class="field">
          <span class="label">Petición</span>
          <textarea v-model="form.request" rows="4" required placeholder="Qué quieres conseguir…" />
        </label>
        <div class="row">
          <button class="btn btn--primary" :disabled="sending || busy || !form.request.trim()">Planificar y ejecutar</button>
          <span v-if="busy" class="muted">Ese proyecto ya tiene un plan en marcha.</span>
          <span class="muted small">Planes grandes o de riesgo alto esperan tu aprobación antes de ejecutarse.</span>
        </div>
        <p v-if="error" class="error">{{ error }}</p>
      </form>
    </Card>

    <Card title="Historial">
      <table v-if="planList.length" class="list">
        <thead><tr><th>#</th><th>Estado</th><th>Nivel</th><th>Petición</th><th>Proyecto</th><th>Coste equiv.</th></tr></thead>
        <tbody>
          <tr v-for="p in planList" :key="p.id" class="clickable" @click="router.push(`/planes/${p.id}`)">
            <td class="mono">{{ p.id }}</td>
            <td><StatusChip label="" :state="planChip(p.status)" :text="PLAN_TEXT[p.status] ?? p.status" /></td>
            <td class="mono">{{ p.level ?? "—" }}</td>
            <td>{{ p.request }}</td>
            <td>{{ projectName(p.project_id) }}</td>
            <td class="mono">{{ usd(p.cost_usd) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">Sin planes todavía.</p>
    </Card>
  </div>
</template>

<style scoped>
.new {
  display: grid;
  gap: 12px;
}
.small {
  font-size: 12px;
}
</style>
