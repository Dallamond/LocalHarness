---
name: comentarios-y-docstrings
description: Comentarios que explican el porqué y docstrings en la API pública, sin ruido
category: Documentación
tags: docstring jsdoc
---

- Comenta el PORQUÉ (decisión, limitación, bug externo), no el QUÉ que ya dice el código.
- Docstring en funciones/clases públicas: qué hace, parámetros no obvios, qué devuelve, qué errores lanza.
- Sigue el formato que use el proyecto (Google, NumPy, JSDoc…) y su idioma.
- Al cambiar código, actualiza o borra el comentario que ya no sea verdad: un comentario falso es peor que ninguno.
- Nada de código comentado «por si acaso»: para eso está git.
