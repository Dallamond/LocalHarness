---
name: componentes-vue
description: Componentes Vue 3 limpios con <script setup>, props tipadas y estado mínimo
category: Frontend
tags: vue typescript frontend
---

- `<script setup lang="ts">` y Composition API; props y emits tipados (`defineProps<{…}>()`).
- Estado mínimo: lo derivable, en `computed`; nada de duplicar datos que ya vienen por props.
- Un componente, una responsabilidad; si pasa de ~300 líneas o mezcla dos cosas, divídelo.
- Estilos `scoped` y variables CSS del proyecto (no colores sueltos).
- Limpia en `onUnmounted` lo que abras (intervalos, listeners, EventSource).
- Antes de terminar: `vue-tsc --noEmit` y el build sin errores.
