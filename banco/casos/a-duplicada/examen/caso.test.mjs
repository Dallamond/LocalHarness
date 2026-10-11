// Examen oculto: los modelos no lo ven.
import { test } from "node:test";
import assert from "node:assert/strict";
import { src, leer, existe, verde, pilla, testsDelProyecto } from "../../_comun/examen.mjs";

test("npm test pasa", () => verde(5));

test("media como dice el comentario", async () => {
  verde(5);
  const { media } = await src("src/estadistica.js");
  assert.equal(media([10, 20, 25]), 18.33);
  assert.equal(media([]), 0);
});

test("mediana sigue igual", async () => {
  verde(5);
  const { mediana } = await src("src/estadistica.js");
  assert.equal(mediana([5]), 5);
  assert.equal(mediana([9, 1]), 5);
});
