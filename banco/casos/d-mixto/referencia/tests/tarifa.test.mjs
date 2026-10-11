import { test } from "node:test";
import assert from "node:assert/strict";
import { redondearCent, tarifaNoche, tarifaDia } from "../src/tarifa.js";

test("redondeo al céntimo", () => {
  assert.equal(redondearCent(10.4), 10);
  assert.equal(redondearCent(10.5), 11);
});

test("tarifa de noche", () => {
  assert.equal(tarifaNoche(10), 170);
});

test("tarifa de día", () => {
  assert.equal(tarifaDia(5), 200);
});
