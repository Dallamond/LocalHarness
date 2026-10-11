import { test } from "node:test";
import assert from "node:assert/strict";
import { crearTablero, ganador } from "../src/tablero.js";

test("tablero vacío", () => {
  assert.equal(ganador(crearTablero()), null);
});
