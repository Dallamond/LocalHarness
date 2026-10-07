---
name: manejo-de-errores
description: Errores claros y útiles: validar en la frontera, no tragarse excepciones y mensajes que digan qué hacer
category: Programación
tags: excepciones validación
---

- Valida las entradas en la frontera (API, CLI, lectura de archivos) y falla pronto con un mensaje concreto:
  qué valor, qué se esperaba y, si se puede, cómo arreglarlo.
- No captures excepciones genéricas para seguir como si nada. Captura solo lo que sabes tratar; lo demás, que suba.
- Si conviertes una excepción en otra, conserva la causa (`raise X from e` / `cause`).
- Los mensajes para el usuario, en su idioma y sin trazas; las trazas, al log.
- Limpia recursos con `with`/`finally`/`using` (archivos, conexiones, procesos).
- No devuelvas `None`/`null` para indicar error si el lenguaje tiene excepciones o tipos Result.
- Añade un test para cada error que se espera (entrada inválida, archivo que no existe, red caída).
