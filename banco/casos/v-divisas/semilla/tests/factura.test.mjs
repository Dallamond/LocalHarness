import { test } from "node:test";
import assert from "node:assert/strict";
import { totalFactura } from "../src/factura.js";
import { resumen } from "../src/resumen.js";

test("total y resumen en euros", () => {
  assert.equal(totalFactura([{ precio: 500, cantidad: 3 }]), 1500);
  assert.deepEqual(resumen([[{ precio: 100, cantidad: 1 }], []]), { numero: 2, total: 100 });
});
