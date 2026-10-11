import { test } from "node:test";
import assert from "node:assert/strict";
import { porcentaje, totalConDescuento } from "../src/descuento.js";

test("bordes de cada tramo", () => {
  const casos = [[9, 0], [10, 5], [49, 5], [50, 10], [99, 10], [100, 15]];
  for (const [u, pct] of casos) assert.equal(porcentaje(u), pct, String(u));
});

test("totales", () => {
  assert.equal(totalConDescuento(5, 100), 500);
  assert.equal(totalConDescuento(100, 200), 17000); // 20000 × 85 / 100
});

test("el redondeo importa", () => {
  assert.equal(totalConDescuento(10, 333), 3164); // 3330 × 95 / 100 = 3163,5 → 3164
});
