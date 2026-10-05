<script setup lang="ts">
// Pastilla de estado: punto + texto (nunca solo color). `label` opcional delante.
defineProps<{
  label?: string;
  state: "ok" | "warn" | "crit" | "pending" | "off";
  text: string;
  title?: string;
}>();
</script>

<template>
  <span class="chip" :class="`chip--${state}`" :title="title">
    <span class="chip__dot" aria-hidden="true" />
    <span v-if="label" class="chip__label">{{ label }}</span>
    <span class="chip__text">{{ text }}</span>
  </span>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px 3px 8px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  background: var(--panel-raised);
  color: var(--ink-dim);
}
.chip__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
.chip__label {
  font-weight: 500;
  color: var(--ink-faint);
}
.chip--ok {
  background: var(--ok-weak);
  color: var(--ok);
}
.chip--warn {
  background: var(--warn-weak);
  color: var(--warn);
}
.chip--crit {
  background: var(--crit-weak);
  color: var(--crit);
}
.chip--pending {
  background: var(--info-weak);
  color: var(--info);
}
.chip--pending .chip__dot {
  animation: pulse 1.4s ease-in-out infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.3;
  }
}
</style>
