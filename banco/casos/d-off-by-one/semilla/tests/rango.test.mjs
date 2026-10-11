import { test } from "node:test";
import assert from "node:assert/strict";
import { rango, suma } from "../src/rango.js";

test("rango incluye los dos extremos", () => {
  assert.deepEqual(rango(1, 3), [1, 2, 3]);
  assert.deepEqual(rango(4, 4), [4]);
});

test("rango vacío si a > b", () => {
  assert.deepEqual(rango(3, 1), []);
});

test("suma de 1 a 10", () => {
  assert.equal(suma(rango(1, 10)), 55);
});
