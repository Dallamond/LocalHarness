// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("precioFinal: descuento primero, luego IVA, cada paso al céntimo", async () => {
  const { precioFinal } = await src("src/precio.js");
  assert.equal(precioFinal(1000, 21, 10), 1089);
  assert.equal(precioFinal(999, 21, 0), 1209);
  assert.equal(precioFinal(1234, 10, 15), 1154);
});

test("desglose devuelve todas las piezas", async () => {
  const { desglose } = await src("src/precio.js");
  assert.deepEqual(desglose(1000, 21, 10), { base: 1000, descuento: 100, neto: 900, iva: 189, total: 1089 });
  assert.deepEqual(desglose(0, 21, 10), { base: 0, descuento: 0, neto: 0, iva: 0, total: 0 });
});

test("el descuento se limita entre 0 y 50", async () => {
  const { precioFinal } = await src("src/precio.js");
  assert.equal(precioFinal(1000, 21, 80), 605);
  assert.equal(precioFinal(1000, 21, -5), 1210);
});

test("base negativa lanza error", async () => {
  const { precioFinal, desglose } = await src("src/precio.js");
  assert.throws(() => precioFinal(-1, 21, 0), /base negativa/);
  assert.throws(() => desglose(-100, 21, 0), /base negativa/);
});
