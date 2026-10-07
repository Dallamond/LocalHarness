<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import AgentWizard from "./components/AgentWizard.vue";
import CatalogOverlay from "./components/CatalogOverlay.vue";
import { live, openCatalog, pct, ui } from "./api";

const route = useRoute();
const full = computed(() => !!route.meta.full); // la oficina ocupa toda la ventana, sin scroll de página

// Uso del plan de Claude (rate_limit_event): aviso desde el 75 %, crítico desde el 90 %
const usage = computed(() => {
  const l = live.limit;
  const worst = Math.max(l?.five_hour ?? 0, l?.seven_day ?? 0);
  return {
    state: !l ? "off" : worst >= 0.9 ? "crit" : worst >= 0.75 ? "warn" : "ok",
    worst,
    text: l ? `5 h ${pct(l.five_hour)} · semana ${pct(l.seven_day)}` : "sin datos aún",
  };
});

const links = [
  { to: "/oficina", text: "Oficina", icon: "fa-building" },
  { to: "/chat", text: "Chat", icon: "fa-comments" },
  { to: "/modelos", text: "Modelos locales", icon: "fa-microchip" },
  { to: "/ajustes", text: "Ajustes", icon: "fa-sliders" },
];
</script>

<template>
  <div class="shell" :class="{ 'shell--full': full }">
    <header class="top card">
      <RouterLink to="/oficina" class="brand">
        <span class="logo" aria-hidden="true"><i class="fa-solid fa-cubes" /></span>
        <span><b>LocalHarness</b><small>Oficina de agentes</small></span>
      </RouterLink>
      <span class="sep" />
      <nav class="nav">
        <RouterLink v-for="l in links" :key="l.to" :to="l.to">
          <i class="fa-solid" :class="l.icon" aria-hidden="true" />
          <span class="nav__text">{{ l.text }}</span>
          <span v-if="l.to === '/oficina' && live.inbox.length" class="badge" title="Esperan tu decisión">{{ live.inbox.length }}</span>
        </RouterLink>
      </nav>
      <span class="spacer" />
      <button class="btn" title="Agentes, skills y servidores MCP" @click="openCatalog()">
        <i class="fa-solid fa-boxes-stacked" /> <span class="hide-sm">Catálogo</span>
      </button>
      <span class="sep hide-sm" />
      <div class="usage hide-sm" :class="`is-${usage.state}`" title="Uso de la suscripción de Claude (ventana de 5 h y semanal)">
        <span class="usage__label">Plan de Claude</span>
        <span class="usage__value mono">{{ usage.text }}</span>
        <span v-if="live.limit" class="meter"><span :style="{ width: `${Math.min(100, usage.worst * 100)}%` }" /></span>
      </div>
      <span
        class="conn" :class="`conn--${live.connection}`"
        :title="live.connection === 'open' ? 'Conectado' : live.connection === 'connecting' ? 'Conectando…' : 'Sin conexión'"
      />
    </header>
    <main id="main" class="main">
      <RouterView />
    </main>
    <CatalogOverlay v-if="ui.catalog" />
    <AgentWizard v-if="ui.wizard" />
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-rows: var(--top-h) minmax(0, 1fr);
  gap: 12px;
  min-height: 100vh;
  padding: 12px;
}
@media (min-width: 981px) {
  .shell--full {
    height: 100vh;
    overflow: hidden;
  }
}
.top {
  position: sticky;
  top: 12px;
  z-index: 40;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 12px;
  min-width: 0;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--ink);
  text-decoration: none;
}
.brand b {
  display: block;
  font-weight: 800;
  font-size: 15px;
  letter-spacing: -0.01em;
  line-height: 1.1;
}
.brand small {
  color: var(--ink-faint);
  font-weight: 600;
  font-size: 10.5px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.logo {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 11px;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: #fff;
  box-shadow: 0 6px 14px -4px color-mix(in srgb, var(--accent) 55%, transparent);
}
.sep {
  width: 1px;
  height: 26px;
  background: var(--line);
}
.spacer {
  flex: 1;
}
.nav {
  display: flex;
  gap: 4px;
  min-width: 0;
  overflow-x: auto;
}
.nav a {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 11px;
  border-radius: 11px;
  color: var(--ink-dim);
  text-decoration: none;
  font-weight: 700;
  white-space: nowrap;
  transition: background 0.15s, color 0.15s;
}
.nav a:hover {
  background: var(--panel-hover);
  color: var(--ink);
}
.nav a.router-link-active {
  background: var(--ink);
  color: var(--panel);
}
.badge {
  min-width: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--warn);
  color: #fff;
  font-size: 11px;
  font-weight: 800;
  text-align: center;
}
.usage {
  display: grid;
  gap: 2px;
  min-width: 150px;
  font-size: 11.5px;
}
.usage__label {
  color: var(--ink-faint);
  font-weight: 700;
}
.usage__value {
  color: var(--ink-dim);
}
.usage .meter {
  height: 5px;
}
.usage .meter span {
  background: var(--ok);
}
.is-warn .meter span {
  background: var(--warn);
}
.is-crit .meter span {
  background: var(--crit);
}
.is-crit .usage__value {
  color: var(--crit);
}
.conn {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--warn);
  flex-shrink: 0;
}
.conn--open {
  background: var(--ok);
}
.conn--closed {
  background: var(--crit);
}
.main {
  min-width: 0;
  min-height: 0;
  padding: 18px 8px 48px;
}
.shell--full .main {
  padding: 0;
}
@media (max-width: 980px) {
  .hide-sm,
  .nav__text {
    display: none;
  }
}
@media (max-width: 640px) {
  .shell {
    padding: 8px;
  }
  .brand span:last-child {
    display: none;
  }
}
</style>
