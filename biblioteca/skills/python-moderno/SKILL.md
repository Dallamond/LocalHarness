---
name: python-moderno
description: Python 3.10+ idiomático: tipos, pathlib, dataclasses, f-strings y librería estándar antes que dependencias
category: Programación
tags: python tipos
---

- Anotaciones de tipo en funciones públicas (`list[str]`, `X | None`).
- `pathlib.Path` para rutas; `encoding="utf-8"` siempre al leer/escribir texto (en Windows el defecto no es UTF-8).
- `dataclasses` o Pydantic para estructuras; nada de diccionarios con forma implícita que viajan por todo el código.
- f-strings; `logging` en vez de `print` para lo que no es salida del programa.
- `subprocess.run([...], check=True)` con lista de argumentos, nunca `shell=True` con texto del usuario.
- Context managers para archivos, locks y conexiones.
- Comprueba qué versión de Python usa el proyecto antes de usar sintaxis nueva (`match`, `except*`…).
- Librería estándar antes de añadir dependencias; si añades una, al archivo de dependencias del proyecto.
