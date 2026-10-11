import { test } from "node:test";
import assert from "node:assert/strict";
import { precioFinal, desglose } from "../src/precio.js";

test("precio final con descuento e IVA", () => {
  assert.equal(precioFinal(1000, 21, 10), 1089); // 1000 - 100 = 900; 900 * 0,21 = 189
  assert.deepEqual(desglose(1000, 21, 10), { base: 1000, descuento: 100, neto: 900, iva: 189, total: 1089 });
});
