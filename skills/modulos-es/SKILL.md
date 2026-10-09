---
name: modulos-es
description: Reglas de módulos ES (JavaScript) para que un archivo cargue: imports, exports y nada de Node en el navegador
category: Programación
---

- Exporta con nombre (`export function x`, `export const X`) y una sola vez: si pones `export function x`, no
  repitas `x` en un `export { … }` al final. Nunca solo `export default`. Cada función se declara UNA vez.
- Importa solo lo que uses y que EXISTA: un archivo que veas en ARCHIVOS DE CONTEXTO o en la lista de MÓDULOS QUE YA
  EXISTEN, con ruta relativa y extensión `.js`. Si no usas nada de otro archivo, no pongas ningún import.
- Nunca inventes un módulo ni copies un import de ejemplo: si un archivo no aparece en el contexto, no existe.
- No cambies el nombre ni los parámetros de una función que ya existe: otros archivos la usan.
- El código del juego o de la web corre en el navegador: nada de `node:`, `require`, `fs`, `readFileSync` ni `process`.
- Devuelve el archivo como código JavaScript, no como JSON ni con texto alrededor, y sin líneas `<<<<<<<`, `=======`
  ni `>>>>>>>`.
