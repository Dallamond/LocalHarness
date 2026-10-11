// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("npm test pasa y siguen los tests de calc", () => verde(5));

test("calc hace lo mismo que antes", async () => {
  verde(5);
  const { sumar, restar, media } = await src("src/calc.js");
  assert.equal(sumar(10, -4), 6);
  assert.equal(restar(10, -4), 14);
  assert.equal(media([2, 4]), 3);
  assert.equal(media([]), 0);
});
