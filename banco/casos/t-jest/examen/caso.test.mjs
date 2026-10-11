// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

const BUENO = "// formatear(segundos) \u2192 'MM:SS' (los minutos pueden pasar de 59); aSegundos('MM:SS') \u2192 segundos.\nexport function formatear(segundos) {\n  const m = Math.floor(segundos / 60);\n  const s = segundos % 60;\n  return `${String(m).padStart(2, \"0\")}:${String(s).padStart(2, \"0\")}`;\n}\n\nexport function aSegundos(texto) {\n  const [m, s] = texto.split(\":\").map(Number);\n  return m * 60 + s;\n}\n";
test("tests con node:test, sin expect de Jest", () => {
  verde(5);
  const t = leer("tests/reloj.test.mjs");
  assert.match(t, /from\s+["']node:test["']/);
  assert.doesNotMatch(t, /\bexpect\s*\(/);
});
test("los tests siguen pillando: sin ceros delante", () => {
  pilla({ "src/reloj.js": BUENO }, { "src/reloj.js": "// formatear(segundos) \u2192 'MM:SS' (los minutos pueden pasar de 59); aSegundos('MM:SS') \u2192 segundos.\nexport function formatear(segundos) {\n  const m = Math.floor(segundos / 60);\n  const s = segundos % 60;\n  return `${String(m)}:${String(s)}`;\n}\n\nexport function aSegundos(texto) {\n  const [m, s] = texto.split(\":\").map(Number);\n  return m * 60 + s;\n}\n" }, 5);
});
test("los tests siguen pillando: minutos de 100 segundos", () => {
  pilla({ "src/reloj.js": BUENO }, { "src/reloj.js": "// formatear(segundos) \u2192 'MM:SS' (los minutos pueden pasar de 59); aSegundos('MM:SS') \u2192 segundos.\nexport function formatear(segundos) {\n  const m = Math.floor(segundos / 60);\n  const s = segundos % 60;\n  return `${String(m).padStart(2, \"0\")}:${String(s).padStart(2, \"0\")}`;\n}\n\nexport function aSegundos(texto) {\n  const [m, s] = texto.split(\":\").map(Number);\n  return m * 100 + s;\n}\n" }, 5);
});
test("los tests siguen pillando: segundos sin el resto de 60", () => {
  pilla({ "src/reloj.js": BUENO }, { "src/reloj.js": "// formatear(segundos) \u2192 'MM:SS' (los minutos pueden pasar de 59); aSegundos('MM:SS') \u2192 segundos.\nexport function formatear(segundos) {\n  const m = Math.floor(segundos / 60);\n  const s = segundos % 100;\n  return `${String(m).padStart(2, \"0\")}:${String(s).padStart(2, \"0\")}`;\n}\n\nexport function aSegundos(texto) {\n  const [m, s] = texto.split(\":\").map(Number);\n  return m * 60 + s;\n}\n" }, 5);
});
