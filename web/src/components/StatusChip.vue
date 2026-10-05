<script setup lang="ts">
// Chip de estado: icono + texto, nunca solo un punto de color.
import { computed } from "vue";

const props = defineProps<{
  label: string;
  state: "ok" | "warn" | "crit" | "pending" | "off";
  text: string;
  title?: string;
}>();

const icon = computed(() => ({ ok: "●", warn: "▲", crit: "✕", pending: "◌", off: "○" })[props.state]);
</script>

<template>
  <span class="chip mono" :class="`chip--${state}`" :title="title">
    <span class="chip__label">{{ label }}</span>
    <span class="chip__icon" aria-hidden="true">{{ icon }}</span>
    <span class="chip__text">{{ text }}</span>
  </span>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border: 1px solid var(--line);
  font-size: 11px;
  white-space: nowrap;
  color: var(--ink-dim);
}
.chip__label {
  color: var(--ink-faint);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.chip--ok .chip__icon,
.chip--ok .chip__text {
  color: var(--ok);
}
.chip--warn {
  border-color: var(--warn);
}
.chip--warn .chip__icon,
.chip--warn .chip__text {
  color: var(--warn);
}
.chip--crit {
  border-color: var(--crit);
}
.chip--crit .chip__icon,
.chip--crit .chip__text {
  color: var(--crit);
}
.chip--pending .chip__icon {
  color: var(--accent);
}
</style>
