// Puntúa un proyecto con su examen oculto: node banco/puntuar.mjs <examen> <ruta del proyecto> [etiqueta] [--json]
// <examen> es el nombre de una prueba de banco/pruebas (supersalto, cuentas-claras; «mario» = supersalto) o la ruta
// de una carpeta con *.test.mjs. Corre cada test con PROYECTO=<ruta> y cuenta los que pasan.
// Sin --json: lo imprime y lo guarda en data/examenes/<examen>-<etiqueta>-<fecha>.json.
// Con --json: solo escribe el resultado en JSON por la salida (lo usa localharness/banco.py tras cada parche).
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { basename, join, resolve } from "node:path";

const args = process.argv.slice(2);
const json = args.includes("--json");
const [examen, proyecto, etiqueta = "sin-etiqueta"] = args.filter((a) => a !== "--json");
if (!examen || !proyecto) {
  console.error("uso: node banco/puntuar.mjs <prueba o carpeta del examen> <ruta del proyecto> [etiqueta] [--json]");
  process.exit(2);
}
const ALIAS = { mario: "supersalto" };
const porNombre = join(import.meta.dirname, "pruebas", ALIAS[examen] || examen, "examen");
const dir = existsSync(porNombre) ? porNombre : resolve(examen);
const nombre = existsSync(porNombre) ? examen : basename(resolve(dir, dir.endsWith("examen") ? ".." : "."));
const porArchivo = Number(process.env.EXAMEN_TIMEOUT_S || 300) * 1000;
const archivos = readdirSync(dir).filter((f) => f.endsWith(".test.mjs")).sort();
const filas = [];
for (const f of archivos) {
  const r = spawnSync(process.execPath, ["--test", "--test-reporter=tap", join(dir, f)], {
    env: { ...process.env, PROYECTO: resolve(proyecto) }, encoding: "utf8", timeout: porArchivo,
  });
  // en TAP, los tests de primer nivel son «ok N - nombre» / «not ok N - nombre» sin sangría
  const lineas = (r.stdout || "").split("\n").filter((l) => /^(not )?ok \d+ - /.test(l));
  const fallan = lineas.filter((l) => l.startsWith("not ok")).map((l) => l.replace(/^not ok \d+ - /, "").trim());
  filas.push({ archivo: f, tests: lineas.length, pasan: lineas.length - fallan.length, fallan,
    ...(r.error ? { error: r.error.code === "ETIMEDOUT" ? "tardó demasiado" : String(r.error.message) } : {}) });
}
const total = filas.reduce((a, f) => a + f.tests, 0);
const pasan = filas.reduce((a, f) => a + f.pasan, 0);
const nota = total ? Math.round((pasan / total) * 1000) / 10 : 0;
if (json) {
  process.stdout.write(JSON.stringify({ examen: nombre, pasan, total, nota, filas }));
  process.exit(0);
}
console.log(`\nExamen «${nombre}» · ${etiqueta} · ${proyecto}\n`);
for (const f of filas) {
  console.log(`  ${f.archivo.padEnd(22)} ${String(f.pasan).padStart(3)} / ${f.tests}${f.error ? ` (${f.error})` : ""}`);
  for (const n of f.fallan) console.log(`      ✖ ${n}`);
}
console.log(`\n  NOTA: ${pasan} de ${total} = ${nota} %\n`);
const salida = join(import.meta.dirname, "..", "data", "examenes");
mkdirSync(salida, { recursive: true });
const fecha = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
const fichero = join(salida, `${nombre}-${etiqueta.replace(/[^\w.+-]/g, "_")}-${fecha}.json`);
writeFileSync(fichero, JSON.stringify({ examen: nombre, proyecto, etiqueta, fecha, pasan, total, nota, filas }, null, 1));
console.log(`  Guardado en ${fichero}`);
