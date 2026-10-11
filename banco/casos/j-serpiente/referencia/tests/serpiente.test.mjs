import { test } from "node:test";
import assert from "node:assert/strict";
import { crearPartida, paso } from "../src/serpiente.js";

test("avanza a la derecha", () => {
  assert.deepEqual(paso(crearPartida(10, 10)).cuerpo[0], { x: 3, y: 0 });
});
