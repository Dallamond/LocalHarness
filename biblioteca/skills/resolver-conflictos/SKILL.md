---
name: resolver-conflictos
description: Resolver conflictos de merge entendiendo la intención de cada lado
category: Git
tags: merge conflicto
---

1. Lista los archivos en conflicto (`git status`) y, para cada uno, mira qué pretendía cada rama
   (`git log -p` de los dos lados en ese archivo).
2. No elijas «el mío» o «el suyo» por defecto: combina la intención de ambos.
3. Archivos generados (lockfiles, builds): no los edites a mano; regenera con la herramienta del proyecto.
4. Quita TODOS los marcadores `<<<<<<<`, `=======`, `>>>>>>>` y compila/ejecuta los tests.
5. Si los dos lados cambiaron la misma lógica de formas incompatibles, para y pregunta en vez de adivinar.
Explica al final cómo has resuelto cada archivo.
