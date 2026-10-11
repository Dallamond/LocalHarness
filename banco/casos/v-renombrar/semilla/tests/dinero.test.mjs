import { test } from "node:test";
import assert from "node:assert/strict";
import { formatear } from "../src/dinero.js";

test("formatear", () => {
  assert.equal(formatear(1234), "12,34 €");
  assert.equal(formatear(5), "0,05 €");
});
