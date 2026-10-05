<script setup lang="ts">
import { useRouter } from "vue-router";
import BlueprintCard from "../components/BlueprintCard.vue";
import { live } from "../api";

const router = useRouter();

const TYPE_TEXT: Record<string, string> = {
  plan_approval: "Aprobar plan",
  plan_merge: "Integrar plan",
  task_decision: "Decidir subtarea",
  task_review: "Revisar tarea suelta",
};

function open(i: (typeof live.inbox)[number]) {
  if (i.type === "task_review") router.push(`/tareas/${i.task_id}`);
  else router.push(`/planes/${i.plan_id}`);
}
</script>

<template>
  <div class="page">
    <h2 class="title">Pendiente de ti</h2>
    <BlueprintCard title="Decisiones N2">
      <p v-if="!live.inbox.length" class="muted">Nada pendiente. Lo de nivel N0/N1 lo resuelven solos los agentes.</p>
      <table v-else class="list">
        <thead><tr><th>Nivel</th><th>Qué</th><th>Título</th><th>Motivos</th></tr></thead>
        <tbody>
          <tr v-for="(i, n) in live.inbox" :key="n" class="clickable" @click="open(i)">
            <td class="mono">{{ i.level }}</td>
            <td>{{ TYPE_TEXT[i.type] ?? i.type }}</td>
            <td>{{ i.title }}</td>
            <td class="muted small">{{ i.reasons.join(" · ") }}</td>
          </tr>
        </tbody>
      </table>
    </BlueprintCard>
  </div>
</template>

<style scoped>
.small {
  font-size: 12px;
}
</style>
