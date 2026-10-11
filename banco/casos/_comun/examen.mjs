// Ayuda de los exámenes de los casos (banco/casos/*/examen): se corren con PROYECTO=<ruta> (banco/puntuar.mjs).
import { cpSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

export const RAIZ = process.env.PROYECTO;
if (!RAIZ) throw new Error("falta PROYECTO=<ruta del proyecto>");

let vez = 0;
/** Importa un módulo del proyecto (ruta relativa, p. ej. "src/precio.js"); si no carga, el test que lo usa falla. */
export const src = (ruta) => import(`${pathToFileURL(join(RAIZ, ruta)).href}?v=${vez++}`);
export const leer = (ruta) => readFileSync(join(RAIZ, ruta), "utf8");
export const existe = (ruta) => existsSync(join(RAIZ, ruta));

/** Copia el proyecto, cambia los archivos de `cambios` ({ruta: texto}) y corre `node --test`: {ok, tests, salida}. */
export function testsDelProyecto(cambios = {}) {
  const dir = mkdtempSync(join(tmpdir(), "caso-"));
  try {
    cpSync(RAIZ, dir, { recursive: true, filter: (s) => !/[\\/](\.git|node_modules)([\\/]|$)/.test(s) });
    for (const [ruta, texto] of Object.entries(cambios)) writeFileSync(join(dir, ruta), texto);
    // sin NODE_TEST_CONTEXT: dentro de un test, el `node --test` hijo se cree parte del runner y no da su resumen
    const env = { ...process.env };
    delete env.NODE_TEST_CONTEXT;
    const p = spawnSync(process.execPath, ["--test"], { cwd: dir, env, encoding: "utf8", timeout: 120000 });
    const m = /ℹ tests (\d+)/.exec(p.stdout || "");
    return { ok: p.status === 0, tests: m ? Number(m[1]) : 0, salida: `${p.stdout || ""}${p.stderr || ""}` };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

let cache = null;
/** Los tests del proyecto, tal cual, pasan y son al menos `minimo` (incluidos los 2 de proyecto.test.mjs). */
export function verde(minimo) {
  cache ??= testsDelProyecto();
  if (!cache.ok) throw new Error(`npm test falla en el proyecto:\n${cache.salida.slice(-1500)}`);
  if (cache.tests < minimo) throw new Error(`solo hay ${cache.tests} tests (se esperan al menos ${minimo})`);
}

/** Con el código bueno los tests del proyecto pasan (y hay al menos `minimo`) y con el mutante fallan. */
export function pilla(bueno, mutante, minimo) {
  const b = testsDelProyecto(bueno);
  if (!b.ok) throw new Error(`con el código bueno tus tests fallan:\n${b.salida.slice(-1200)}`);
  if (b.tests < minimo) throw new Error(`solo hay ${b.tests} tests (se esperan al menos ${minimo})`);
  const m = testsDelProyecto(mutante);
  if (m.ok) throw new Error("tus tests no pillan este fallo");
}
