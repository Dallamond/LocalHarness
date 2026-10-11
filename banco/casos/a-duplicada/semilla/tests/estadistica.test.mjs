import { test } from "node:test";
import assert from "node:assert/strict";
import { media, mediana } from "../src/estadistica.js";

test("media redondeada a 2 decimales", () => {
  assert.equal(media([1, 2, 3, 4]), 2.5);
  assert.equal(media([1, 2, 2]), 1.67);
});

test("media de una lista vacía", () => {
  assert.equal(media([]), 0);
});

test("mediana", () => {
  assert.equal(mediana([3, 1, 2]), 2);
  assert.equal(mediana([4, 1, 3, 2]), 2.5);
});
