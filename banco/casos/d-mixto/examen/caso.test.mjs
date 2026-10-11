// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("npm test pasa y siguen los tests de tarifa", () => verde(5));

test("redondeo como dice la especificación", async () => {
  verde(5);
  const { redondearCent } = await src("src/tarifa.js");
  assert.equal(redondearCent(2.5), 3);
  assert.equal(redondearCent(2.49), 2);
});

test("tarifas como dice la especificación", async () => {
  verde(5);
  const { tarifaNoche, tarifaDia } = await src("src/tarifa.js");
  assert.equal(tarifaNoche(0), 50);
  assert.equal(tarifaNoche(30), 410);
  assert.equal(tarifaDia(1), 120);
});
