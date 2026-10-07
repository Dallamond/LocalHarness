---
name: revision-de-diff
description: Lista de comprobación para el jefe técnico al revisar el diff de otro agente
category: Equipo
---

Comprueba, en este orden:
1. ¿El diff hace exactamente lo que pedía la subtarea? Lo que falte o sobre es motivo de `request_changes`.
2. ¿Es correcto? Casos límite, errores evidentes, imports que faltan, tests que no prueban nada.
3. ¿Cambia algo fuera de su alcance (otros archivos, formato masivo, dependencias)? Si es así, `escalate`.
4. ¿Los tests añadidos fallarían sin el cambio? Si no, no sirven.
Aprueba solo si los cuatro puntos están bien. Explica el motivo en una o dos frases concretas.
