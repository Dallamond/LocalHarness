<script setup lang="ts">
import { computed } from "vue";
import StatusChip from "./components/StatusChip.vue";
import { live, pct, pendingForYou } from "./api";

// Uso del plan de Claude (rate_limit_event): aviso desde el 75 %, crítico desde el 90 %
const usage = computed(() => {
  const l = live.limit;
  const worst = Math.max(l?.five_hour ?? 0, l?.seven_day ?? 0);
  return {
    state: (!l ? "off" : worst >= 0.9 ? "crit" : worst >= 0.75 ? "warn" : "ok") as "off" | "crit" | "warn" | "ok",
    text: l ? `5 h ${pct(l.five_hour)} · 7 d ${pct(l.seven_day)}` : "sin datos",
  };
});
</script>

<template>
  <header class="top">
    <h1 class="brand">Local<span>Harness</span></h1>
    <nav class="nav">
      <RouterLink to="/tareas">Tareas</RouterLink>
      <RouterLink to="/proyectos">Proyectos y agentes</RouterLink>
    </nav>
    <div class="row">
      <StatusChip
        label="por decidir"
        :state="pendingForYou.length ? 'warn' : 'off'"
        :text="String(pendingForYou.length)"
        title="Tareas esperando tu revisión o integración"
      />
      <StatusChip label="plan claude" :state="usage.state" :text="usage.text" title="Uso de la suscripción" />
      <StatusChip
        label="servidor"
        :state="live.connection === 'open' ? 'ok' : live.connection === 'connecting' ? 'pending' : 'crit'"
        :text="live.connection === 'open' ? 'conectado' : live.connection === 'connecting' ? 'conectando' : 'sin conexión'"
      />
    </div>
  </header>
  <main id="main" class="main">
    <RouterView />
  </main>
</template>

<style scoped>
.top {
  display: flex;
  align-items: center;
  gap: 24px;
  height: var(--topbar-h);
  padding: 0 var(--gap);
  border-bottom: 1px solid var(--line);
  background: var(--panel);
}
.brand {
  font-size: 16px;
  font-family: var(--font-mono);
  color: var(--ink);
}
.brand span {
  color: var(--accent);
}
.nav {
  display: flex;
  gap: 16px;
  flex: 1;
}
.nav a {
  color: var(--ink-dim);
  text-decoration: none;
  font-weight: 600;
  font-size: 13px;
  padding: 4px 0;
  border-bottom: 2px solid transparent;
}
.nav a.router-link-active {
  color: var(--ink);
  border-bottom-color: var(--accent);
}
.main {
  padding: 20px var(--gap) 40px;
}
@media (max-width: 760px) {
  .top {
    height: auto;
    flex-wrap: wrap;
    padding: 8px var(--gap);
    gap: 10px;
  }
}
</style>
