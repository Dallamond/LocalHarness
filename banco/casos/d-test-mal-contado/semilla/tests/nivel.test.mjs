import { test } from "node:test";
import assert from "node:assert/strict";
import { posicionDe, contar } from "../src/nivel.js";

const NIVEL = [
  "....................",
  "..J.......o.....E...",
  "##########....####F#",
];

test("el jugador empieza donde está la J", () => {
  assert.deepEqual(posicionDe(NIVEL, "J"), { x: 32, y: 16 });
});

test("la moneda y el enemigo", () => {
  assert.deepEqual(posicionDe(NIVEL, "o"), { x: 160, y: 16 });
  assert.deepEqual(posicionDe(NIVEL, "E"), { x: 256, y: 16 });
});

test("la meta está en la F", () => {
  assert.deepEqual(posicionDe(NIVEL, "F"), { x: 272, y: 32 });
});

test("cuenta los bloques de suelo", () => {
  assert.equal(contar(NIVEL, "#"), 15);
  assert.equal(posicionDe(NIVEL, "K"), null);
});
