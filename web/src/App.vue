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
  { to: "/trabajo", text: "Trabajo", icon: "fa-list-check" },
  { to: "/chat", text: "Chat", icon: "fa-comments" },
  { to: "/modelos", text: "Modelos locales", icon: "fa-microchip" },
  { to: "/analiticas", text: "Analíticas", icon: "fa-chart-column" },
  { to: "/comparativa", text: "Comparativa", icon: "fa-scale-balanced" },
  { to: "/ajustes", text: "Ajustes", icon: "fa-sliders" },
];
</script>

<template>
  <div class="shell" :class="{ 'shell--full': full }">
    <header class="top">
      <RouterLink to="/oficina" class="brand" title="LocalHarness · Oficina de agentes">
        <svg class="logo" viewBox="0 0 28 28" aria-hidden="true">
          <rect x="4" y="3" width="20" height="6" rx="1.5" />
          <rect x="4" y="11" width="20" height="6" rx="1.5" />
          <rect x="4" y="19" width="20" height="6" rx="1.5" />
          <circle class="logo__led" cx="20" cy="6" r="1.4" />
          <circle class="logo__led" cx="20" cy="14" r="1.4" />
          <circle class="logo__led logo__led--off" cx="20" cy="22" r="1.4" />
        </svg>
        <b>LocalHarness</b>
      </RouterLink>
      <nav class="nav">
        <RouterLink v-for="l in links" :key="l.to" :to="l.to">
          <i class="fa-solid" :class="l.icon" aria-hidden="true" />
          <span class="nav__text">{{ l.text }}</span>
          <span v-if="l.to === '/trabajo' && live.inbox.length" class="badge" title="Esperan tu decisión">{{ live.inbox.length }}</span>
        </RouterLink>
      </nav>
      <span class="spacer" />
      <button class="btn btn--small" title="Agentes, skills y servidores MCP" @click="openCatalog()">
        <i class="fa-solid fa-boxes-stacked" /> <span class="hide-sm">Catálogo</span>
      </button>
      <div class="usage hide-sm" :class="`is-${usage.state}`" title="Uso de la suscripción de Claude (ventana de 5 h y semanal)">
        <span class="usage__label">Plan de Claude <span class="usage__value">{{ usage.text }}</span></span>
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
/* barra fija arriba del todo, a todo lo ancho; el contenido va debajo */
.shell {
  display: grid;
  grid-template-rows: var(--top-h) minmax(0, 1fr);
  min-height: 100vh;
}
@media (min-width: 981px) {
  .shell--full {
    height: 100vh;
    overflow: hidden;
  }
}
.top {
  position: sticky;
  top: 0;
  z-index: 40;
  display: flex;
  align-items: center;
  gap: 14px;
  height: var(--top-h);
  padding: 0 16px;
  min-width: 0;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-right: 14px;
  border-right: 1px solid var(--line);
  height: 28px;
  color: var(--ink);
  text-decoration: none;
}
.brand b {
  font-weight: 800;
  font-size: 15px;
  letter-spacing: -0.015em;
}
.logo {
  width: 22px;
  height: 22px;
  fill: var(--ink);
}
.logo__led {
  fill: var(--ok);
}
.logo__led--off {
  fill: var(--panel);
}
.spacer {
  flex: 1;
}
.nav {
  display: flex;
  align-self: stretch;
  gap: 2px;
  min-width: 0;
  overflow-x: auto;
}
.nav a {
  position: relative;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 10px;
  color: var(--ink-dim);
  text-decoration: none;
  font-weight: 600;
  white-space: nowrap;
  transition: color 0.15s;
}
.nav a i {
  font-size: 12.5px;
  opacity: 0.8;
}
.nav a:hover {
  color: var(--ink);
}
.nav a.router-link-active {
  color: var(--ink);
}
.nav a.router-link-active::after {
  content: "";
  position: absolute;
  left: 8px;
  right: 8px;
  bottom: -1px;
  height: 2px;
  background: var(--accent);
}
.badge {
  min-width: 18px;
  padding: 0 5px;
  border-radius: 4px;
  background: var(--warn);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  text-align: center;
}
.usage {
  display: grid;
  gap: 4px;
  min-width: 170px;
  font-size: 11.5px;
}
.usage__label {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: var(--ink-faint);
  font-weight: 600;
}
.usage__value {
  color: var(--ink-dim);
  font-variant-numeric: tabular-nums;
}
.usage .meter {
  height: 4px;
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
  width: 8px;
  height: 8px;
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
  padding: 20px 16px 48px;
}
.shell--full .main {
  padding: 10px;
}
@media (max-width: 980px) {
  .hide-sm,
  .nav__text {
    display: none;
  }
}
@media (max-width: 640px) {
  .top {
    gap: 8px;
    padding: 0 10px;
  }
  .brand b {
    display: none;
  }
  .main {
    padding: 14px 10px 40px;
  }
}
</style>
