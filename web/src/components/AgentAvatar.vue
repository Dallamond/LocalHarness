<script setup lang="ts">
// Avatar de un agente: iniciales sobre el color de su rol; anillo animado mientras trabaja.
import { computed } from "vue";
import type { Agent } from "../api";
import { roleColor } from "../api";

const props = defineProps<{ agent: Agent | undefined; busy?: boolean; size?: number }>();

const initials = computed(() => {
  const n = props.agent?.name ?? "?";
  const parts = n.split(/[-_ .]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : n.slice(0, 2)).toUpperCase();
});
</script>

<template>
  <span
    class="av"
    :class="{ 'av--busy': busy }"
    :style="{ '--c': roleColor(agent), '--s': `${size ?? 40}px` }"
    aria-hidden="true"
  >{{ initials }}</span>
</template>

<style scoped>
.av {
  position: relative;
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  width: var(--s);
  height: var(--s);
  border-radius: 50%;
  background: color-mix(in srgb, var(--c) 18%, var(--panel));
  color: var(--c);
  font-weight: 700;
  font-size: calc(var(--s) * 0.36);
  letter-spacing: 0.02em;
}
.av--busy::after {
  content: "";
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  border: 2px solid transparent;
  border-top-color: var(--c);
  border-right-color: var(--c);
  animation: spin 1.6s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
