---
name: tests-de-especificacion
description: Escribir tests a partir de los casos exactos de la tarea, sin ver el código (se escribe a la vez)
category: Calidad y tests
---

- Los casos que da la tarea (entrada → salida) son la especificación: cópialos con sus valores exactos, uno por test.
- No inventes casos ni cambies valores para que «cuadren»; si la tarea no da un valor, no lo compruebes.
- Importa las funciones del archivo y con el nombre que dice la tarea, aunque ese archivo aún no exista.
- Usa el mismo framework y estilo que los tests que ya hay en el proyecto (por ejemplo `node:test` y
  `node:assert/strict` en JavaScript, `unittest` en Python).
- Para decimales usa una tolerancia (`Math.abs(a - b) < 1e-9`); para objetos, `deepStrictEqual`.
- Fabrica en el propio test los datos que necesites (mapas pequeños, objetos escritos a mano).
