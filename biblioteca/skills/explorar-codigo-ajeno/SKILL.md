---
name: explorar-codigo-ajeno
description: Entender un repo desconocido rápido: estructura, punto de entrada, flujo principal y convenciones
category: Programación
tags: entender repo onboarding
---

Para entender un proyecto que no conoces, en este orden y sin leerlo todo:

1. README, archivos de configuración (`package.json`, `pyproject.toml`, `Cargo.toml`, `pom.xml`…) y la estructura
   de carpetas de primer nivel. De ahí salen el lenguaje, las dependencias y cómo se ejecuta y se prueba.
2. El **punto de entrada** (main, servidor, CLI, rutas) y sigue UN flujo típico de punta a punta.
3. Los **modelos de datos** centrales (clases, esquemas, tablas).
4. Las **convenciones**: nombres, estilo de errores, logs, cómo están escritos los tests. Imítalas.
5. Busca con `grep` en vez de abrir archivos al azar; abre solo lo que el flujo necesita.

Resume en: qué hace el proyecto, mapa de carpetas (una línea por carpeta), flujo principal con archivos y
funciones, cómo se ejecuta/prueba, y dudas abiertas. No inventes lo que no has leído.
