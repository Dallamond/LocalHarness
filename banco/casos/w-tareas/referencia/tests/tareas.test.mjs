import { test } from "node:test";
import assert from "node:assert/strict";
import { anadir, contar } from "../src/tareas.js";

test("añadir y contar", () => {
  assert.deepEqual(contar(anadir([], "pan", 1)), { total: 1, pendientes: 1, hechas: 0 });
});
