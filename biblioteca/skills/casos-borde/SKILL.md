---
name: casos-borde
description: Lista de comprobación de casos borde para revisar código o diseñar tests
category: Calidad y tests
tags: edge cases
---

Antes de dar algo por terminado, piensa qué pasa con:
- Vacío: cadena vacía, lista vacía, archivo vacío, `None`/`null`, campo que falta.
- Límites: 0, 1, -1, máximo, desbordamiento, fechas en cambio de año/horario, 29 de febrero.
- Texto: acentos y ñ, emojis, espacios al principio/final, mayúsculas, saltos de línea `\r\n` (Windows).
- Rutas: espacios, acentos, barras `\` y `/`, rutas relativas, que no exista, sin permisos.
- Concurrencia: dos peticiones a la vez, doble clic, reintentos.
- Red: lenta, caída, respuesta inesperada o enorme.
- Datos grandes: miles de elementos, archivos de varios GB.
Para cada punto que aplique: o hay test, o hay una razón para no cubrirlo.
