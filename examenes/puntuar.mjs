// PUENTE TEMPORAL (09/10/2026): el examen se movió a banco/. Esto solo existe para que la prueba
// mario-gptoss-qwen4b, lanzada con el prueba-mario.ps1 viejo, puntúe al acabar. Borrar cuando termine.
import { spawnSync } from "node:child_process";
import { join } from "node:path";

const r = spawnSync(process.execPath, [join(import.meta.dirname, "..", "banco", "puntuar.mjs"), ...process.argv.slice(2)],
  { stdio: "inherit" });
process.exit(r.status ?? 1);
