import { test } from "node:test";
import assert from "node:assert/strict";
import { calcular } from "../src/propinas.js";

test("calcular", () => {
  assert.deepEqual(calcular(5000, 10, 3), { propina: 500, total: 5500, porPersona: 1834 });
});
