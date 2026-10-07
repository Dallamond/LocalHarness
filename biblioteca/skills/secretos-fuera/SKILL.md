---
name: secretos-fuera
description: No filtrar secretos: variables de entorno, .gitignore y nada de claves en código, logs ni commits
category: Seguridad
tags: claves tokens env
---

- Las claves y tokens van en variables de entorno o en archivos ignorados por git (`.env`), nunca en el código.
- Si creas un `.env`, crea también un `.env.example` sin valores reales y añade `.env` al `.gitignore`.
- No imprimas secretos en logs ni en mensajes de error (enmascara: `sk-…ab12`).
- Si encuentras un secreto ya subido, NO lo borres en silencio: avisa, porque hay que revocarlo.
- No pegues secretos en búsquedas web ni en herramientas externas.
