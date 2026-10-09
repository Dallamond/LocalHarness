# Banco de pruebas

El mismo proyecto desde cero para cada **contendiente** (qué modelo va en cada GPU, con qué agente y con qué topes),
corregido con un **examen oculto** que los modelos no ven, después de cada parche. Sirve para comparar modelos y
flujos de trabajo con la misma vara.

- Lanzar: `Banco.bat` (LocalHarness abierto y sin otro autopiloto en marcha). Varios contendientes se corren uno
  detrás de otro, así que una noche entera de comparativas sale sola.
- Ver: `http://127.0.0.1:8095/banco`. Muestra la clasificación, la curva de nota por parche, el changelog y los
  archivos de cada parche lado a lado, y el botón para abrir el proyecto (o la referencia) en el navegador.
- Retomar una ejecución cortada: `.venv\Scripts\python.exe -m localharness banco seguir data\banco\<prueba>-<modalidad>\<carpeta>`.

## Pruebas (`pruebas/<nombre>/`)

| Archivo | Qué es |
|---|---|
| `prueba.json` | título, tipo, `check` (tests para integrar), qué abrir y las modalidades |
| `semilla/` | el Parche 000: ENCARGO.md, docs, package.json y el primer test |
| `semilla-libre/` | lo que se añade en la modalidad libre (CONTRATO.md) |
| `parches-guiada.md` | parches detallados con casos de test: mide **ejecución** |
| `parches-libre.md` | pocos hitos grandes y un contrato: mide **planificación** y tests propios |
| `examen/*.test.mjs` | examen oculto (`node:test`, con `PROYECTO=<ruta>`) |
| `referencia/` | solución hecha a mano: el examen tiene que darle 100 (lo comprueba tests/test_banco.py) |

Hay dos: **supersalto** (juego de plataformas en canvas: 39 parches guiados u 8 hitos libres, 35 tests) y
**cuentas-claras** (web de gastos con router, localStorage, CSV y gráfico SVG: 18 parches guiados o 6 hitos libres,
29 tests, con referencia).

Para añadir una prueba: copia la estructura, escribe primero la referencia y el examen, y comprueba que la
referencia saca 100 y la semilla 0 con `node banco/puntuar.mjs <prueba> <carpeta>`.

## Contendientes (`contendientes/<nombre>.json`)

```json
{"descripcion": "…", "agente": "Jefe local",
 "modelos": {"principal": "gpt-oss-20b-UD-Q4_K_XL", "rapido": "Qwen_Qwen3.5-4B-Q4_K_M"},
 "horas": 12, "minutos_tarea": 45, "presupuesto": 1}
```

`modelos` usa el nombre del GGUF tal como sale en Modelos locales. Un servidor a `null` se apaga (modelo grande en
solitario); sin `modelos` se usa lo que ya esté cargado. Un modelo puede llevar opciones:
`{"modelo": "…", "opciones": {"n_cpu_moe": 4}}`. `presupuesto` es el tope de Claude en $: con 0 no arranca, así
que para los locales se deja en 1. Los contendientes con un agente de Claude **gastan plan**.

## Resultados (`data/banco/<prueba>-<modalidad>/<contendiente>-<fecha>/`)

`resultado.json` (cada parche con resultado, minutos, tokens por modelo, coste, nota del examen tras ese parche,
commit, archivos tocados y líneas nuevas del CHANGELOG), `informe.md` del autopiloto, `CHANGELOG.md` y
`git-log.txt` del proyecto. El repo de cada ejecución queda en `D:\LocalHarness-proyectos\banco\` (o en
`LOCALHARNESS_PROYECTOS\banco`).
