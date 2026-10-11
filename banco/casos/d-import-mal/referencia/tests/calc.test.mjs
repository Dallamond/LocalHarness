import { test } from "node:test";
import assert from "node:assert/strict";
import { sumar, restar, media } from "../src/calc.js";

test("sumar y restar", () => {
  assert.equal(sumar(2, 3), 5);
  assert.equal(restar(2, 3), -1);
});

test("media", () => {
  assert.equal(media([1, 2, 3, 6]), 3);
});

test("media de una lista vacía", () => {
  assert.equal(media([]), 0);
});
