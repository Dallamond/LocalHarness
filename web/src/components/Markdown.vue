<script setup lang="ts">
// Texto del agente en markdown, saneado (el modelo podría devolver HTML).
import DOMPurify from "dompurify";
import { marked } from "marked";
import { computed } from "vue";

const props = defineProps<{ text: string }>();
const html = computed(() => DOMPurify.sanitize(marked.parse(props.text, { async: false, gfm: true, breaks: true })));
</script>

<template>
  <div class="md" v-html="html" />
</template>

<style scoped>
.md {
  overflow-wrap: anywhere;
}
.md :deep(p) {
  margin: 0 0 0.6em;
}
.md :deep(p:last-child) {
  margin-bottom: 0;
}
.md :deep(ul),
.md :deep(ol) {
  margin: 0.2em 0 0.6em;
  padding-left: 1.4em;
}
.md :deep(li) {
  margin: 0.15em 0;
}
.md :deep(h1),
.md :deep(h2),
.md :deep(h3),
.md :deep(h4) {
  margin: 0.8em 0 0.4em;
  font-size: 1.05em;
}
.md :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.86em;
  padding: 1px 5px;
  border-radius: 5px;
  background: var(--panel-raised);
}
.md :deep(pre) {
  margin: 0.4em 0 0.7em;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--panel-raised);
  border: 1px solid var(--line);
  overflow: auto;
}
.md :deep(pre code) {
  padding: 0;
  background: none;
  font-size: 12.5px;
}
.md :deep(blockquote) {
  margin: 0.4em 0;
  padding-left: 10px;
  border-left: 3px solid var(--line-strong);
  color: var(--ink-dim);
}
.md :deep(table) {
  border-collapse: collapse;
  margin: 0.4em 0;
}
.md :deep(th),
.md :deep(td) {
  border: 1px solid var(--line);
  padding: 4px 8px;
}
</style>
