// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("npm test pasa y siguen los 4 tests de nivel", () => verde(6));

test("posicionDe sigue la regla: columna × 16, fila × 16", async () => {
  verde(6);
  const { posicionDe } = await src("src/nivel.js");
  assert.deepEqual(posicionDe(["..F", "J.."], "F"), { x: 32, y: 0 });
  assert.deepEqual(posicionDe(["..F", "J.."], "J"), { x: 0, y: 16 });
  assert.deepEqual(posicionDe(["...", "...", "....o"], "o"), { x: 64, y: 32 });
  assert.equal(posicionDe(["..."], "J"), null);
});

test("contar sigue igual", async () => {
  verde(6);
  const { contar } = await src("src/nivel.js");
  assert.equal(contar(["#.#", "##"], "#"), 4);
});
