import { test } from "node:test";
import assert from "node:assert/strict";
import { anadir, total } from "../src/inventario.js";

test("añadir y total", () => {
  assert.equal(total(anadir({ a: 1 }, "b", 2)), 3);
});
