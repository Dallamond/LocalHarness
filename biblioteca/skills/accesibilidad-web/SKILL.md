---
name: accesibilidad-web
description: Interfaces web accesibles: semántica, teclado, contraste y etiquetas
category: Frontend
tags: a11y html css
---

- HTML semántico: `button` para acciones, `a` para navegar, encabezados en orden, `label` asociado a cada input.
- Todo se puede usar con teclado (Tab, Enter, Esc) y el foco se ve.
- Imágenes con `alt` (vacío si son decorativas); iconos-botón con `aria-label` o `title`.
- Contraste suficiente (4.5:1 en texto normal) en tema claro y oscuro.
- No transmitas información solo con color (añade icono o texto).
- Mensajes de error junto al campo y anunciados (`aria-live` en avisos dinámicos).
- Respeta `prefers-reduced-motion` en animaciones.
