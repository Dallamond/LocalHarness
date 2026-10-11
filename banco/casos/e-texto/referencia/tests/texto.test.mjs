import { test } from "node:test";
import assert from "node:assert/strict";
import { slug, truncar } from "../src/texto.js";

test("slug y truncar", () => {
  assert.equal(slug("¡Hola, Señor Pérez!"), "hola-senor-perez");
  assert.equal(truncar("abcdef", 4), "abc…");
});
