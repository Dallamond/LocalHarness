# Revisión completa del repositorio (07/10/2026)

Revisión de arquitectura, código, seguridad, pruebas, documentación y forma de trabajo, con lo que ya se ha
arreglado en esta pasada y lo que queda, en orden de prioridad. Objetivo inmediato acordado: **que Claude sepa
delegar en el modelo local**.

## 1. Lo que está bien (y conviene conservar)

- **La idea y el diseño de fondo son sólidos.** Un agente es una *configuración* (proveedor + modelo + límites),
  no código; cada tarea trabaja en un **git worktree con su rama** y nada se integra sin tu revisión; nunca hay
  push automático. Es el mismo patrón que usan los orquestadores serios (vibe-kanban, parallel-code…).
- **Adaptadores limpios** (`adapters/`): un contrato pequeño (`build_command` + `parse_line`) y eventos comunes.
  Añadir un proveedor es un archivo.
- **Aislamiento real de la CLI de Claude**, medido y documentado: `--safe-mode`/`--setting-sources ""`,
  `--strict-mcp-config`, sin `ANTHROPIC_API_KEY` en el entorno (para no cobrar por tokens). De lo mejor del repo.
- **Pruebas buenas y honestas**: 165 pruebas con CLIs y llama-server falsos (nunca gastan plan), *fixtures* reales
  de la CLI de Claude, extremo a extremo con el servidor MCP de verdad. Pasan en Python 3.10 y 3.13.
- **Sin dependencias innecesarias**: el núcleo es librería estándar; el servidor MCP propio es JSON-RPC a mano.
- **Herramientas del agente local confinadas** al worktree, `ejecutar` con lista blanca y sin shell.
- **Documentación de traspaso** (`ESTADO.md`) que permite retomar entre sesiones: poco habitual y muy útil.
- Interfaz cuidada: oficina 3D, Catálogo, asistente de agentes, pestaña de modelos con nota por rol.

## 2. Arreglado en esta revisión

| Problema | Gravedad | Arreglo |
|---|---|---|
| **Claude no delegaba**: la guía iba pegada al final de la tarea y Claude conservaba Edit/Write | Alta (objetivo principal) | Modo **coordinador** unificado: Claude solo con Read/Glob/Grep + herramientas del local; guías en `--append-system-prompt` (pesan como reglas y se repiten en cada vuelta) |
| El local solo podía escribir **un archivo entero** por encargo; no había bucle «hace → se revisa → corrige» | Alta | Herramienta **`local_agent`**: encarga una tarea entera al agente local con herramientas (lee, escribe, ejecuta tests) en el mismo worktree; devuelve resumen + archivos cambiados, con sus pasos en vivo |
| Claude sin Bash no podía comprobar nada | Media | **`run_checks`**: tests/linter de la lista blanca, sin modelo (gratis) |
| Coordinador sin llama-server = tarea que gasta y no hace nada | Media | Aviso y Claude trabaja solo esa vez |
| No se veía si Claude había delegado | Media | Aviso «Claude no le encargó nada al modelo local» y recuento por herramienta |
| **Seguridad: la API aceptaba peticiones de cualquier web** (DNS rebinding / otra pestaña) → podía añadir un «servidor MCP» que ejecuta un programa y lanzar una tarea | **Crítica** | Middleware que solo atiende a `Host` local y a `Origin` local; `serve --host 0.0.0.0` lo desactiva a propósito y avisa |
| Dos sesiones hicieron a la vez dos modos de delegación distintos | Media | Unificados en uno (`coordinator`) |
| `local_agent` contaba `__pycache__` como archivos cambiados | Baja | Filtrado |
| Sin lint ni CI | Media | `ruff` configurado y limpio; **CI en GitHub** (Linux + Windows, Python 3.10/3.12, tipos y compilación de la web) |
| Imports sin usar, `enterContext` (rompía 3.10) | Baja | Corregido |
| No había forma de comprobar la mitad local de la delegación sin gastar plan | Media | `localharness probar-delegacion` |

## 3. Lo que hay que cambiar o mejorar (por prioridad)

### P1 — Para que la delegación funcione de verdad en tu PC
1. **Probarlo en el PC del instituto**, en este orden (no gasta plan hasta el paso 3):
   1. `localharness probar-delegacion` con el modelo arrancado → debe acabar en ✔. Si el modelo no usa
      herramientas: Qwen3/Qwen3.5 o `tool_mode: json`.
   2. Sandbox: `localharness sandbox`, agente `programador` (rol en modo coordinador).
   3. Una tarea pequeña real con Haiku/Sonnet → en el Timeline deben verse «Encarga al agente local…», los pasos
      del modelo local y `run_checks`. Comprobar también que la CLI acepta `--append-system-prompt` con `-p`
      (documentado, pero sin verificar en tu versión).
2. **Medir**: misma tarea solo-Claude vs coordinador (coste, tiempo, ¿pasan los tests?). Sin números no sabremos
   si compensa. Propuesta: una página «Comparativa» que lance las dos variantes sobre el sandbox.
3. **Límite de vueltas del bucle Claude ↔ local**: hoy lo marca la guía («máximo 2 rondas») y `max_turns`. Si en la
   práctica se alarga, añadir un tope duro de encargos por tarea en el servidor MCP.

### P2 — Robustez
4. **Una tarea por repo a la vez** (y planes en serie). Para trabajar en paralelo hace falta rama de integración
   por proyecto (M6) y cola por agente.
5. **`ejecutar` y `run_checks` no aíslan la red** ni el sistema de archivos fuera del worktree (solo el directorio de
   trabajo y la lista blanca). Un `npm test` malicioso del repo puede hacer cualquier cosa. Aceptable para repos
   propios; documentarlo y, más adelante, contenedor o sandbox del sistema.
6. **Secretos en SQLite en claro** (tokens de MCP, token de Hugging Face). Es local y fuera de git, pero conviene
   el almacén de credenciales de Windows (`keyring`) cuando haya instalador.
7. **Migraciones de la base de datos**: hoy van en `store.py` a mano; con más tablas, numerarlas y probarlas.

### P3 — Código mantenible (lo que más se nota al crecer)
8. **Archivos demasiado grandes**: `api.py` (~1.200 líneas), `OfficeView.vue` (~1.550), `CatalogOverlay.vue`
   (~1.200), `ModelsView.vue` (~1.200), `office3d.ts` (~1.150). Partir `api.py` en routers de FastAPI
   (`agents`, `tasks`, `plans`, `llama`, `library`…) y las vistas en componentes (misión, bandeja, inspector,
   recursos). No cambia nada visible y reduce mucho los conflictos entre sesiones.
9. **Estilo Python**: líneas con varias órdenes separadas por `;` (sobre todo en pruebas) y algún `except
   Exception` amplio. Ir dejándolo al tocar cada archivo; `ruff` ya vigila lo importante.
10. **Tipos en el frontend**: hay `Record<string, any>` en algunos sitios (p. ej. metadatos del GGUF). Tiparlo poco a
    poco. Valorar unas pocas pruebas de componentes (Vitest) para el asistente y el Catálogo.

### P4 — Proyecto serio / presentación
11. **Licencia**: no hay `LICENSE`. Decide tú (MIT si quieres que se use libremente; propietaria si no). Sin
    licencia, legalmente nadie puede usarlo.
12. **Versiones y cambios**: `pyproject` dice 0.0.1 y la API 0.1.0. Unificar, etiquetar versiones (`v0.2.0`…) y
    llevar un `CHANGELOG.md`; encaja con el instalador `.exe` y «Buscar actualizaciones» propuestos en ESTADO.
13. **Documentación**: hay 10 documentos en `docs/` y `ESTADO.md` mezcla historial con estado actual (más de 500
    líneas). Propuesta: `README` (qué es, instalar, usar, capturas), `docs/GUIA.md` (referencia), `docs/ESTADO.md`
    corto (solo el ahora y lo siguiente) y mover el historial a `docs/historial/`. Un `CONTRIBUTING.md` con las
    reglas de trabajo (main, commits pequeños, pruebas antes de subir).
14. **Trabajo de varias sesiones a la vez en `main`**: hoy ha pasado dos veces (arranque fácil y modo
    coordinador). Funciona, pero conviene que cada sesión diga en `ESTADO.md` en qué está («en curso: …») o usar
    ramas cortas que se integran el mismo día.
15. **Idioma mezclado** en nombres de carpetas (`skills/` y `biblioteca/`, `roles/` y `manual/`). No urge;
    elegir una regla y aplicarla al reorganizar.

## 4. Cómo seguimos (propuesta)
1. Tú: `git pull`, `localharness probar-delegacion`, y una tarea pequeña con el agente `programador` en el sandbox.
   Me cuentas qué sale en el Timeline.
2. Yo, según eso: ajustar la guía del coordinador y los topes; después la comparativa (P1.2).
3. Luego P3.8 (partir `api.py` y las vistas grandes) antes de seguir añadiendo funciones.
