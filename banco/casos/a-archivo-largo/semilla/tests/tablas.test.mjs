import { test } from "node:test";
import assert from "node:assert/strict";
import { buscar, caros, totalStock } from "../src/tablas.js";

test("buscar un producto que existe", () => {
  assert.equal(buscar(5).nombre, "producto-005");
});

test("buscar uno que no existe da null", () => {
  assert.equal(buscar(999), null);
});

test("consultas", () => {
  assert.equal(caros(1100).length, 0);
  assert.ok(totalStock() > 0);
});
