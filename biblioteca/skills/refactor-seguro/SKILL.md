---
name: refactor-seguro
description: Reestructurar código sin cambiar su comportamiento: pasos pequeños con tests en verde
category: Programación
tags: limpiar reestructurar
---

Un refactor NO cambia lo que hace el programa. Reglas:

- Antes de empezar, ejecuta los tests y anota el resultado. Si no hay tests de la zona, escribe primero uno que
  fije el comportamiento actual (aunque sea feo).
- Cambios pequeños y de un tipo cada vez: renombrar, extraer función, mover, simplificar condición. Tras cada uno,
  tests otra vez.
- No mezcles refactor con arreglos de bugs ni con funciones nuevas. Si ves un bug, anótalo y sigue.
- Mantén las interfaces públicas (nombres exportados, rutas de API, formato de archivos) salvo que la tarea lo pida.
- Busca todos los usos (`grep`) antes de renombrar o cambiar una firma.
- Prefiere borrar código muerto a comentarlo.

Al terminar: lista de cambios agrupados, confirmación de que los tests siguen igual y cualquier bug que viste.
