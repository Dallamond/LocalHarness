---
name: commits-claros
description: Mensajes de commit útiles y commits pequeños de un solo propósito
category: Git
tags: git commit mensajes
---

- Un commit = un cambio con sentido (no «arreglos varios»). Si el diff mezcla cosas, sepáralo.
- Título en imperativo, ≤ 72 caracteres, que diga QUÉ cambia: «Valida el email al registrarse».
- Si hace falta, cuerpo tras una línea en blanco con el PORQUÉ y efectos secundarios, no un relato de lo hecho.
- Sigue la convención del repo si existe (Conventional Commits `feat:`/`fix:`, idioma, prefijos): mira `git log`.
- Nunca subas secretos, archivos generados, `node_modules`, `.venv` ni datos personales.
- No reescribas historia ya compartida (rebase/force-push) sin permiso.
