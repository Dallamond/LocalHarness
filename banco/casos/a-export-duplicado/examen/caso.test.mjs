// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("npm test pasa", () => verde(4));

test("color hace lo mismo que antes", async () => {
  verde(4);
  const { hex, rgb, aclarar } = await src("src/color.js");
  assert.equal(hex(10, 11, 12), "#0a0b0c");
  assert.deepEqual(rgb("#0a0b0c"), [10, 11, 12]);
  assert.equal(aclarar("#204060", 10), "#3653703".slice(0, 7));
});
