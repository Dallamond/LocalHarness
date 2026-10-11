import { test } from "node:test";
import assert from "node:assert/strict";
import { crearEstado, paso } from "../src/paso.js";

test("se mueve a la derecha y a la izquierda", () => {
  let e = paso(crearEstado(), { derecha: true });
  assert.equal(e.x, 2);
  e = paso(e, { izquierda: true });
  assert.equal(e.x, 0);
});

test("no sale de 0..300", () => {
  assert.equal(paso({ ...crearEstado(), x: 299 }, { derecha: true }).x, 300);
  assert.equal(paso(crearEstado(), { izquierda: true }).x, 0);
});
