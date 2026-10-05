<script setup lang="ts">
import { computed } from "vue";
import { live, pct, pendingForYou } from "./api";

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
  { to: "/inicio", text: "Inicio", icon: "M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" },
  { to: "/chat", text: "Chat", icon: "M4 5h16v11H9l-5 4z" },
  { to: "/bandeja", text: "Pendiente de ti", icon: "M4 13h4l2 3h4l2-3h4M5 5h14l1 8v6H4v-6z", badge: true },
  { to: "/planes", text: "Planes", icon: "M6 4h12v16H6zM9 9h6M9 13h6M9 17h3" },
  { to: "/modelos", text: "Modelos locales", icon: "M5 5h14v6H5zM5 13h14v6H5zM8 8h.01M8 16h.01" },
  { to: "/ajustes", text: "Ajustes", icon: "M4 7h9m4 0h3M4 17h3m4 0h9M15 4v6M9 14v6" },
];
</script>

<template>
  <div class="shell">
    <aside class="side">
      <RouterLink to="/inicio" class="brand">
        <span class="brand__mark" aria-hidden="true">LH</span>
        <span>LocalHarness</span>
      </RouterLink>
      <nav class="nav">
        <RouterLink v-for="l in links" :key="l.to" :to="l.to">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path :d="l.icon" /></svg>
          <span class="nav__text">{{ l.text }}</span>
          <span v-if="l.badge && pendingForYou.length" class="badge">{{ pendingForYou.length }}</span>
        </RouterLink>
      </nav>
      <div class="foot">
        <div class="foot__item" :class="`is-${usage.state}`" title="Uso de la suscripción de Claude">
          <span class="foot__label">Plan de Claude</span>
          <span class="foot__value mono">{{ usage.text }}</span>
          <span v-if="live.limit" class="meter"><span :style="{ width: `${Math.min(100, usage.worst * 100)}%` }" /></span>
        </div>
        <div class="foot__item">
          <span class="conn" :class="`conn--${live.connection}`" aria-hidden="true" />
          <span class="foot__value">{{
            live.connection === "open" ? "Conectado" : live.connection === "connecting" ? "Conectando…" : "Sin conexión"
          }}</span>
        </div>
      </div>
    </aside>
    <main id="main" class="main">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: var(--side-w) minmax(0, 1fr);
  min-height: 100vh;
}
.side {
  position: sticky;
  top: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  gap: 22px;
  padding: 22px 14px 18px;
  border-right: 1px solid var(--line);
  background: var(--panel-raised);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 8px;
  color: var(--ink);
  text-decoration: none;
  font-weight: 700;
  font-size: 17px;
  letter-spacing: -0.01em;
}
.brand__mark {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: var(--accent);
  color: var(--accent-ink);
  font-size: 13px;
  font-weight: 800;
}
.nav {
  display: grid;
  gap: 2px;
}
.nav a {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 9px 10px;
  border-radius: 10px;
  color: var(--ink-dim);
  text-decoration: none;
  font-weight: 550;
  transition: background 0.15s, color 0.15s;
}
.nav a:hover {
  background: var(--panel);
  color: var(--ink);
}
.nav a.router-link-active {
  background: var(--panel);
  color: var(--ink);
  box-shadow: var(--shadow);
}
.nav svg {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
  flex-shrink: 0;
}
.nav a.router-link-active svg {
  stroke: var(--accent);
}
.badge {
  margin-left: auto;
  min-width: 22px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--warn);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  text-align: center;
}
.foot {
  margin-top: auto;
  display: grid;
  gap: 12px;
  padding: 0 8px;
  font-size: 13px;
}
.foot__item {
  display: grid;
  gap: 3px;
}
.foot__item:last-child {
  display: flex;
  align-items: center;
  gap: 8px;
}
.foot__label {
  color: var(--ink-faint);
  font-weight: 600;
}
.foot__value {
  color: var(--ink-dim);
}
.meter {
  height: 5px;
  border-radius: 999px;
  background: var(--line);
  overflow: hidden;
}
.meter span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--ok);
}
.is-warn .meter span {
  background: var(--warn);
}
.is-crit .meter span {
  background: var(--crit);
}
.is-crit .foot__value {
  color: var(--crit);
}
.conn {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--warn);
}
.conn--open {
  background: var(--ok);
}
.conn--closed {
  background: var(--crit);
}
.main {
  padding: 30px 36px 60px;
  min-width: 0;
}
@media (max-width: 820px) {
  .shell {
    grid-template-columns: 1fr;
  }
  .side {
    position: static;
    height: auto;
    flex-direction: row;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    padding: 10px 16px;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .nav {
    display: flex;
    flex-wrap: wrap;
    order: 3;
    width: 100%;
  }
  .nav__text {
    font-size: 14px;
  }
  .foot {
    display: none;
  }
  .main {
    padding: 20px 16px 48px;
  }
}
</style>
