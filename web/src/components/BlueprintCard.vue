<script setup lang="ts">
// Lámina de plano: borde de 1 px, marcas de registro en las esquinas y título destacado.
defineProps<{
  title?: string;
  color?: string; // color del dispositivo (var CSS)
  level?: "ok" | "warn" | "crit" | "unknown";
  dense?: boolean;
}>();
</script>

<template>
  <section
    class="card"
    :class="[level && `card--${level}`, { 'card--dense': dense }]"
    :style="color ? { '--card-color': color } : undefined"
  >
    <span class="reg reg--tl" aria-hidden="true" />
    <span class="reg reg--tr" aria-hidden="true" />
    <span class="reg reg--bl" aria-hidden="true" />
    <span class="reg reg--br" aria-hidden="true" />
    <header v-if="title || $slots.actions" class="card__head">
      <h3 class="card__title">
        <span v-if="color" class="card__swatch" aria-hidden="true" />
        <span v-if="title" class="card__name">{{ title }}</span>
      </h3>
      <div class="card__actions"><slot name="actions" /></div>
    </header>
    <slot />
  </section>
</template>

<style scoped>
.card {
  --card-color: var(--line-strong);
  position: relative;
  background: var(--panel);
  border: 1px solid var(--line);
  border-top: 2px solid var(--card-color);
  padding: 14px 16px 16px;
  min-width: 0;
}
.card--dense {
  padding: 10px 12px 12px;
}
.card--warn {
  border-color: var(--warn);
  background-image: repeating-linear-gradient(
    -45deg,
    rgba(255, 224, 102, 0.05) 0 6px,
    transparent 6px 12px
  );
}
.card--crit {
  border-color: var(--crit);
  background-image: repeating-linear-gradient(
    -45deg,
    rgba(255, 107, 107, 0.09) 0 6px,
    transparent 6px 12px
  );
}
.reg {
  position: absolute;
  width: 9px;
  height: 9px;
  border-color: var(--line-strong);
  border-style: solid;
  border-width: 0;
  pointer-events: none;
}
.reg--tl {
  top: -5px;
  left: -5px;
  border-top-width: 1px;
  border-left-width: 1px;
}
.reg--tr {
  top: -5px;
  right: -5px;
  border-top-width: 1px;
  border-right-width: 1px;
}
.reg--bl {
  bottom: -5px;
  left: -5px;
  border-bottom-width: 1px;
  border-left-width: 1px;
}
.reg--br {
  bottom: -5px;
  right: -5px;
  border-bottom-width: 1px;
  border-right-width: 1px;
}
.card__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}
.card__title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-family: var(--font-sans);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.01em;
}
.card__name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.card__swatch {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  background: var(--card-color);
}
.card__name {
  color: var(--ink);
}
.card__actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
</style>
