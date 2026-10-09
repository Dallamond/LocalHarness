<script setup lang="ts">
// Avatar de un agente: su icono único (el mismo que lleva en el pecho en la oficina) sobre el color de su rol;
// anillo animado mientras trabaja.
import { computed } from "vue";
import type { Agent } from "../api";
import { agentIcon, roleColor } from "../api";

const props = defineProps<{ agent: Agent | undefined; busy?: boolean; size?: number }>();

const icon = computed(() => agentIcon(props.agent).name);
</script>

<template>
  <span
    class="av"
    :class="{ 'av--busy': busy }"
    :style="{ '--c': roleColor(agent), '--s': `${size ?? 40}px` }"
    :title="agent?.name"
    aria-hidden="true"
  ><i class="fa-solid" :class="`fa-${icon}`" /></span>
</template>

<style scoped>
.av {
  position: relative;
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  width: var(--s);
  height: var(--s);
  border-radius: 30%;
  background: color-mix(in srgb, var(--c) 16%, var(--panel));
  border: 1px solid color-mix(in srgb, var(--c) 40%, var(--line));
  color: var(--c);
  font-size: calc(var(--s) * 0.44);
}
.av--busy::after {
  content: "";
  position: absolute;
  inset: -4px;
  border-radius: 34%;
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
