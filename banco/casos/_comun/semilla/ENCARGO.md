# Encargo

Proyecto pequeño en JavaScript con módulos ES y sin dependencias.

## Reglas
1. El código va en `src/`. Nombres de funciones, variables y comentarios en castellano (sin ñ en los
   identificadores: `anadir`).
2. Las funciones son puras (salvo `src/main.js`, que es la única que toca el navegador): reciben datos y devuelven
   datos NUEVOS, sin modificar lo que reciben.
3. Los tests van en `tests/*.test.mjs` y usan solo `node:test` y `node:assert/strict`. `npm test` tiene que pasar.
4. No cambies la firma de una función que ya existe. No borres un test que comprueba lo que pide la especificación.
5. `CHANGELOG.md` lleva una línea por parche: `- Parche NNN · DD/MM/AAAA · qué cambió`.
