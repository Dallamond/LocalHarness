---
name: modulos-es
description: Reglas de módulos ES (JavaScript) para que un archivo cargue: imports, exports y nada de Node en el navegador
category: Programación
---

- Exporta con nombre (`export function x`, `export const X`), nunca solo `export default`.
- Importa TODO lo que uses: `import { crearMapa } from './mapa.js';` con ruta relativa y extensión `.js`.
- Importa cada nombre del archivo que de verdad lo exporta (mira los ARCHIVOS DE CONTEXTO), sin inventar rutas.
- No cambies el nombre ni los parámetros de una función que ya existe: otros archivos la usan.
- El código del juego o de la web corre en el navegador: nada de `node:`, `require`, `fs`, `readFileSync` ni `process`.
- Devuelve el archivo como código JavaScript, no como JSON ni con texto alrededor, y sin líneas `<<<<<<<`, `=======`
  ni `>>>>>>>`.
