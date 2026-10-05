<script setup lang="ts">
// Tarjeta: superficie suave con título opcional y acciones a la derecha.
defineProps<{
  title?: string;
  subtitle?: string;
  level?: "ok" | "warn" | "crit" | "unknown";
  dense?: boolean;
}>();
</script>

<template>
  <section class="card" :class="[level && `card--${level}`, { 'card--dense': dense }]">
    <header v-if="title || $slots.actions" class="card__head">
      <div class="card__titles">
        <h3 v-if="title" class="card__title">{{ title }}</h3>
        <p v-if="subtitle" class="card__sub">{{ subtitle }}</p>
      </div>
      <div class="card__actions"><slot name="actions" /></div>
    </header>
    <slot />
  </section>
</template>

<style scoped>
.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 18px 20px 20px;
  min-width: 0;
}
.card--dense {
  padding: 12px 14px 14px;
}
.card--warn {
  border-color: var(--warn);
  box-shadow: 0 0 0 3px var(--warn-weak), var(--shadow);
}
.card--crit {
  border-color: var(--crit);
  box-shadow: 0 0 0 3px var(--crit-weak), var(--shadow);
}
.card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 14px;
}
.card__titles {
  min-width: 0;
}
.card__title {
  font-size: 16px;
  font-weight: 650;
}
.card__sub {
  margin: 2px 0 0;
  font-size: 13.5px;
  color: var(--ink-dim);
}
.card__actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
</style>
