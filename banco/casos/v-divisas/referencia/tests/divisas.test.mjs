import { test } from "node:test";
import assert from "node:assert/strict";
import { convertir } from "../src/divisas.js";

test("convertir", () => {
  assert.equal(convertir(1000, "EUR", "USD"), 1100);
});
