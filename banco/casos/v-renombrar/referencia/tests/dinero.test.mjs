import { test } from "node:test";
import assert from "node:assert/strict";
import { formatearEuros } from "../src/dinero.js";

test("formatearEuros", () => {
  assert.equal(formatearEuros(1234), "12,34 €");
  assert.equal(formatearEuros(5), "0,05 €");
});
