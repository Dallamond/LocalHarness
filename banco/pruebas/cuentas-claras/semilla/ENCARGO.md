# Encargo: «Cuentas claras», una web para apuntar ingresos y gastos

Una página web de una sola pantalla para llevar las cuentas personales: apuntar movimientos, ver el resumen del
mes con un gráfico, filtrar, fijar presupuestos por categoría e importar/exportar CSV. Los datos se guardan en el
navegador (localStorage). Todo en castellano y con importes en euros.

## Cómo se usa
- Se sirve la carpeta con cualquier servidor estático y se abre `index.html`. Sin dependencias, sin build, sin
  frameworks: HTML, CSS y JavaScript con módulos ES.
- Vistas por hash: `#/resumen` (portada), `#/movimientos`, `#/nuevo`, `#/presupuestos` e `#/importar`.
- `docs/ejemplo.csv` trae 30 movimientos de agosto a octubre de 2026 para probar.

## Arquitectura (obligatoria)
1. **La lógica es pura** y vive en `src/`: funciones que reciben datos y devuelven datos NUEVOS (no modifican lo
   que reciben), sin DOM, sin `localStorage` directo, sin `Math.random` y sin `Date.now`.
2. **El dinero va en céntimos enteros** (`centimos`): un gasto es negativo y un ingreso positivo. Nunca se suman
   euros con decimales.
3. **Las vistas son funciones que devuelven HTML como texto** (`src/vista-*.js`, `src/navegacion.js`,
   `src/formulario.js`, `src/grafico.js`). Todo texto que venga del usuario pasa por `escapar` de `src/html.js`.
4. **Solo `src/main.js` toca el navegador**: lee la ruta, pinta en `<main id="app">` con `innerHTML`, escucha
   `hashchange`, formularios y clics, y guarda con `localStorage`.
5. **Ningún archivo pasa de 200 líneas**; si crece, se parte en módulos.
6. Nombres de funciones, variables y comentarios en castellano (sin ñ en los identificadores: `anadir`).
7. **No se cambia la firma de una función que ya existe.** Si hace falta algo más, se añade una función nueva.

## Reglas de los tests
1. Cada parche trae tests en `tests/*.test.mjs` (solo `node:test` y `node:assert/strict`, módulos ES) y deja
   **todos** los tests pasando con `npm test`.
2. Un test comprueba valores concretos (entrada → salida esperada), no solo «que no falle».
3. Las vistas se prueban buscando trozos en el HTML que devuelven, no abriendo un navegador.

## Reglas de cada parche
1. Cada parche suele traer DOS módulos independientes (A y B) que se pueden escribir a la vez.
2. `CHANGELOG.md` lleva una línea por parche: `- Parche NNN · DD/MM/AAAA · qué cambió`.
