// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("npm test pasa y siguen los tests de rango", () => verde(5));

test("rango incluye los dos extremos", async () => {
  verde(5);
  const { rango } = await src("src/rango.js");
  assert.deepEqual(rango(-2, 1), [-2, -1, 0, 1]);
  assert.deepEqual(rango(0, 0), [0]);
  assert.deepEqual(rango(2, 1), []);
});
